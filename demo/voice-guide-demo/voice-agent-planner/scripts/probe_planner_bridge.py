"""One-shot manual probe: runs a single planner query through the bridge and prints raw output.

This bypasses the voice pipeline entirely so we can see exactly what the openclaw
sandbox returns for a 'please make me a plan'-style request.
"""

from __future__ import annotations

import asyncio
import sys
import uuid

from loguru import logger

from apps.jewel_voice_guide.planner_bridge import PlannerBridge, PlannerQueryRequest


async def main() -> int:
    user_text = sys.argv[1] if len(sys.argv) > 1 else "please make me a plan"
    bridge = PlannerBridge()
    health = await bridge.health()
    logger.info("Bridge health: {}", health.model_dump())
    if not health.planner_available:
        logger.error("Planner is not available; aborting probe.")
        return 1

    request = PlannerQueryRequest(
        request_id=f"probe_{uuid.uuid4().hex[:10]}",
        session_id=f"probe-session-{uuid.uuid4().hex[:8]}",
        user_text=user_text,
        route_reason="manual_probe",
        session_context={
            "current_location": "Jewel Singapore",
            "prior_turns": [],
        },
        planner_options={
            "response_style": "voice_friendly",
            "max_steps": 5,
            "allow_live_data": True,
            "allow_tools": True,
        },
    )

    logger.info("Sending probe request id={} text={!r}", request.request_id, user_text)
    response = await bridge.query(request)
    logger.info("Bridge returned response: {}", response.model_dump())
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
