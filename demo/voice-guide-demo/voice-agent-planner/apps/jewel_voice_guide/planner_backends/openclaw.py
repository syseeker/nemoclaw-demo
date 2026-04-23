"""Openclaw planner backend - thin wrapper around the existing PlannerBridge.

The bridge already handles SSH, the marker JSON contract, lenient validation,
the stale-response guard, and cleanup. We just adapt it to the PlannerBackend ABC.
"""

from __future__ import annotations

import asyncio
import os
import uuid

from loguru import logger

from apps.jewel_voice_guide.planner_backends.base import PlannerBackend
from apps.jewel_voice_guide.planner_backends.direct import DirectPlannerBackend
from apps.jewel_voice_guide.planner_bridge import (
    PlannerBridge,
    PlannerHealthResponse,
    PlannerQueryRequest,
    PlannerQueryResponse,
)


class OpenclawPlannerBackend(PlannerBackend):
    """Routes planner turns through openclaw inside the openshell sandbox."""

    name = "openclaw"

    def __init__(
        self,
        bridge: PlannerBridge | None = None,
        direct_fallback: DirectPlannerBackend | None = None,
    ) -> None:
        self.bridge = bridge or PlannerBridge()
        self.direct_fallback = direct_fallback or DirectPlannerBackend()
        self.enable_direct_fallback = os.getenv("OPENCLAW_DIRECT_FALLBACK", "true").lower() == "true"

    async def query(self, request: PlannerQueryRequest) -> PlannerQueryResponse:
        response = await self.bridge.query(request)
        if not self.enable_direct_fallback:
            return response
        if response.status == "ok":
            return response
        timeout_like = response.status == "timeout" or response.error_code in {
            "planner_model_timeout",
            "planner_runtime_error",
            "planner_busy",
        }
        if not timeout_like:
            return response

        logger.warning(
            "Openclaw fallback -> direct for request_id={} status={} error_code={}",
            request.request_id,
            response.status,
            response.error_code,
        )
        fallback_response = await self.direct_fallback.query(request)
        metadata = fallback_response.planner_metadata or {}
        metadata["openclaw_fallback"] = {
            "triggered": True,
            "openclaw_status": response.status,
            "openclaw_error_code": response.error_code,
        }
        fallback_response.planner_metadata = metadata
        return fallback_response

    async def health(self) -> PlannerHealthResponse:
        return await self.bridge.health()

    async def cleanup_session(self, session_id: str) -> None:
        await self.bridge.cleanup_session(session_id)

    async def warmup(self) -> None:
        """Fire one tiny planner call so the openclaw embedded runner is hot.

        Catches and logs any failure: warmup MUST NOT block pipeline startup.
        """
        try:
            health = await self.bridge.health()
            if not health.planner_available:
                logger.info("Openclaw warmup skipped: planner not available")
                return
            request = PlannerQueryRequest(
                request_id=f"warmup_{uuid.uuid4().hex[:10]}",
                session_id=f"warmup-session-{uuid.uuid4().hex[:8]}",
                user_text="warmup ping; reply with status only",
                route_reason="pipeline_warmup",
                session_context={"current_location": "Jewel Singapore", "prior_turns": []},
                planner_options={
                    "response_style": "voice_friendly",
                    "max_steps": 1,
                    "allow_live_data": False,
                    "allow_tools": False,
                },
            )
            logger.info("Openclaw warmup ping starting")
            response = await asyncio.wait_for(self.bridge.query(request), timeout=120)
            logger.info("Openclaw warmup completed: status={}", response.status)
        except Exception as exc:
            logger.warning("Openclaw warmup failed (non-fatal): {}", exc)
