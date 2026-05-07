"""Abstract base for planner backends."""

from __future__ import annotations

from abc import ABC, abstractmethod

from apps.jewel_voice_guide.planner_bridge import (
    PlannerHealthResponse,
    PlannerQueryRequest,
    PlannerQueryResponse,
)


class PlannerBackend(ABC):
    """Common contract for planner executors.

    Every backend converts a PlannerQueryRequest into a PlannerQueryResponse,
    surfaces health, and may optionally pre-warm itself + clean up sessions.
    """

    name: str = "abstract"

    @abstractmethod
    async def query(self, request: PlannerQueryRequest) -> PlannerQueryResponse:
        """Execute one planner turn."""

    @abstractmethod
    async def health(self) -> PlannerHealthResponse:
        """Report whether this backend is reachable / configured."""

    async def warmup(self) -> None:
        """Optional pre-warm hook called once at pipeline startup."""
        return None

    async def cleanup_session(self, session_id: str) -> None:
        """Optional per-conversation cleanup hook."""
        return None
