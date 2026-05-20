"""Measure bridge latency on a freshly-wiped openclaw session, three calls in a row.

Distinguishes whether the slow bridge calls are caused by (a) a fat static system
prompt, (b) accumulated session context, or (c) pure model latency.
"""

from __future__ import annotations

import asyncio
import time
import uuid

from loguru import logger

from apps.jewel_voice_guide.planner_bridge import PlannerBridge, PlannerQueryRequest


PROMPT = "I have 3 hours at Jewel before my flight, plan something with food and the Rain Vortex"


async def call_once(bridge: PlannerBridge, attempt: int) -> dict:
    request = PlannerQueryRequest(
        request_id=f"clean_{attempt}_{uuid.uuid4().hex[:8]}",
        session_id=f"clean-session-{attempt}-{uuid.uuid4().hex[:6]}",
        user_text=PROMPT,
        route_reason="latency_probe",
        session_context={"current_location": "Jewel Singapore", "prior_turns": []},
        planner_options={
            "response_style": "voice_friendly",
            "max_steps": 5,
            "allow_live_data": True,
            "allow_tools": True,
        },
    )
    started = time.monotonic()
    response = await bridge.query(request)
    elapsed = time.monotonic() - started
    return {
        "attempt": attempt,
        "elapsed_s": round(elapsed, 2),
        "status": response.status,
        "error_code": response.error_code,
        "spoken": response.spoken_response[:120],
    }


async def main() -> int:
    bridge = PlannerBridge()
    health = await bridge.health()
    if not health.planner_available:
        logger.error("planner not available")
        return 1

    logger.info("Wiping session before any test call")
    await bridge.cleanup_session("pre-clean-baseline")

    for i in range(1, 4):
        result = await call_once(bridge, i)
        logger.info(
            "[{}/3] elapsed={}s status={} error={} spoken={!r}",
            result["attempt"],
            result["elapsed_s"],
            result["status"],
            result["error_code"],
            result["spoken"],
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
