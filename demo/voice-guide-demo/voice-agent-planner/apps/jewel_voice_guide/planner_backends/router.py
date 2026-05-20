"""Backend router for planner turns.

Modes:
- `direct`: always use DirectPlannerBackend.
- `openclaw`: always use OpenclawPlannerBackend.
- `auto` (default): use direct unless a small rule-based classifier flags the turn
  as needing the openclaw agent loop (live tools, bookings, etc.).

Rule-based escalation keeps Phase 1 predictable. The keyword list will grow as
Phase 2 wires in cuOpt + booking + live-data tools.
"""

from __future__ import annotations

import os
import re
from enum import Enum

from loguru import logger

from apps.jewel_voice_guide.planner_backends.base import PlannerBackend
from apps.jewel_voice_guide.planner_backends.direct import DirectPlannerBackend
from apps.jewel_voice_guide.planner_backends.openclaw import OpenclawPlannerBackend
from apps.jewel_voice_guide.planner_bridge import (
    PlannerHealthResponse,
    PlannerQueryRequest,
    PlannerQueryResponse,
)


class PlannerBackendMode(str, Enum):
    """How the router picks a backend per turn."""

    AUTO = "auto"
    DIRECT = "direct"
    OPENCLAW = "openclaw"

    @classmethod
    def from_env(cls, default: "PlannerBackendMode" = "PlannerBackendMode.AUTO") -> "PlannerBackendMode":  # type: ignore[assignment]
        raw = (os.getenv("PLANNER_BACKEND") or "auto").strip().lower()
        try:
            return cls(raw)
        except ValueError:
            logger.warning("Unknown PLANNER_BACKEND={!r}; defaulting to auto", raw)
            return cls.AUTO


# Phrases that indicate the user needs verifiable live data or external action.
# When any of these match the user's text, we escalate to openclaw so its tool loop
# (web_search, web_fetch, future cuOpt/booking) can actually do the work.
ESCALATION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\bactually\s+(check|verify|look\s*up|confirm)\b", re.IGNORECASE),
    re.compile(r"\bright\s+now\b", re.IGNORECASE),
    re.compile(r"\bat\s+this\s+(moment|hour)\b", re.IGNORECASE),
    re.compile(r"\bthis\s+(hour|minute)\b", re.IGNORECASE),
    re.compile(r"\bcurrent(?:ly)?\s+(open|closed|running|available|crowded|busy)\b", re.IGNORECASE),
    re.compile(r"\blive\s+(weather|traffic|delay|closure|wait\s*time|hours?)\b", re.IGNORECASE),
    re.compile(r"\b(real[-\s]?time|up[-\s]?to[-\s]?date)\b", re.IGNORECASE),
    re.compile(r"\b(book|reserve|purchase|buy)\s+(a|the|me)?\b", re.IGNORECASE),
]


def should_escalate_to_openclaw(user_text: str) -> tuple[bool, str | None]:
    """Returns (escalate, matching_phrase) using the rule-based classifier."""
    if not user_text:
        return False, None
    for pattern in ESCALATION_PATTERNS:
        match = pattern.search(user_text)
        if match:
            return True, match.group(0)
    return False, None


class PlannerBackendRouter(PlannerBackend):
    """Selects DirectPlannerBackend or OpenclawPlannerBackend per turn."""

    name = "router"

    def __init__(
        self,
        *,
        mode: PlannerBackendMode | None = None,
        direct: DirectPlannerBackend | None = None,
        openclaw: OpenclawPlannerBackend | None = None,
    ) -> None:
        self.mode = mode if mode is not None else PlannerBackendMode.from_env()
        self.direct = direct or DirectPlannerBackend()
        self.openclaw = openclaw or OpenclawPlannerBackend()
        logger.info("PlannerBackendRouter initialised in {} mode", self.mode.value)

    async def query(self, request: PlannerQueryRequest) -> PlannerQueryResponse:
        backend = self._select_backend(request)
        logger.info(
            "Planner routed to backend={} mode={} request_id={} user_text={!r}",
            backend.name,
            self.mode.value,
            request.request_id,
            request.user_text[:120],
        )
        response = await backend.query(request)
        metadata = response.planner_metadata or {}
        metadata.setdefault("backend", backend.name)
        response.planner_metadata = metadata
        return response

    async def health(self) -> PlannerHealthResponse:
        if self.mode == PlannerBackendMode.OPENCLAW:
            return await self.openclaw.health()
        if self.mode == PlannerBackendMode.DIRECT:
            return await self.direct.health()
        # AUTO: report direct as primary; both must be healthy for full coverage but
        # direct alone is enough for Phase 1 default behaviour.
        return await self.direct.health()

    async def warmup(self) -> None:
        # Direct backend is stateless HTTP, doesn't need warmup; only openclaw does.
        if self.mode != PlannerBackendMode.DIRECT:
            await self.openclaw.warmup()

    async def cleanup_session(self, session_id: str) -> None:
        # Only openclaw maintains per-session state inside the sandbox.
        await self.openclaw.cleanup_session(session_id)

    def _select_backend(self, request: PlannerQueryRequest) -> PlannerBackend:
        if self.mode == PlannerBackendMode.DIRECT:
            return self.direct
        if self.mode == PlannerBackendMode.OPENCLAW:
            return self.openclaw

        escalate, phrase = should_escalate_to_openclaw(request.user_text)
        if escalate:
            logger.info(
                "Escalating to openclaw (matched phrase={!r}) for request_id={}",
                phrase,
                request.request_id,
            )
            return self.openclaw
        return self.direct
