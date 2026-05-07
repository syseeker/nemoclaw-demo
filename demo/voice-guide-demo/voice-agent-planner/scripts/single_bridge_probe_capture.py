"""Run a single bridge call and copy the openclaw session jsonl out
before the cleanup wipes it. Prints the on-sandbox path of the saved jsonl.
"""

from __future__ import annotations

import asyncio
import sys
import uuid

from loguru import logger

from apps.jewel_voice_guide.planner_bridge import PlannerBridge, PlannerQueryRequest


async def main() -> int:
    prompt = sys.argv[1] if len(sys.argv) > 1 else "I have 3 hours at Jewel before my flight, plan something with food and the Rain Vortex"

    bridge = PlannerBridge()
    health = await bridge.health()
    if not health.planner_available:
        logger.error("planner not available")
        return 1

    # IMPORTANT: do NOT cleanup before — we want the session jsonl to exist after.
    request = PlannerQueryRequest(
        request_id=f"capture_{uuid.uuid4().hex[:10]}",
        session_id=f"capture-session-{uuid.uuid4().hex[:8]}",
        user_text=prompt,
        route_reason="manual_capture",
        session_context={"current_location": "Jewel Singapore", "prior_turns": []},
        planner_options={
            "response_style": "voice_friendly",
            "max_steps": 5,
            "allow_live_data": True,
            "allow_tools": True,
        },
    )
    logger.info("sending: {!r}", prompt)
    response = await bridge.query(request)
    logger.info("status={} elapsed-via-bridge=N/A spoken={!r}", response.status, response.spoken_response[:120])

    # Snapshot sessions dir into /tmp/captured_session_<request_id>/
    snapshot_dir = f"/tmp/captured_session_{request.request_id}"
    import os
    import tempfile

    ssh_config = await bridge._run(["openshell", "sandbox", "ssh-config", bridge.sandbox_name], timeout=15)
    with tempfile.NamedTemporaryFile("w", delete=False) as h:
        h.write(ssh_config)
        cfg_path = h.name
    try:
        # tar up the sandbox sessions dir, stream out, untar locally
        cmd = (
            "tar -C /sandbox/.openclaw-data/agents/main -cf - sessions"
        )
        proc = await asyncio.create_subprocess_exec(
            "ssh", "-T", "-F", cfg_path,
            "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null",
            "-o", "LogLevel=ERROR",
            f"openshell-{bridge.sandbox_name}",
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        os.makedirs(snapshot_dir, exist_ok=True)
        with open(f"{snapshot_dir}/sessions.tar", "wb") as fh:
            fh.write(stdout)
        if stderr:
            logger.warning("ssh stderr: {!r}", stderr.decode("utf-8", errors="replace")[:500])
        proc2 = await asyncio.create_subprocess_exec(
            "tar", "-C", snapshot_dir, "-xf", f"{snapshot_dir}/sessions.tar",
        )
        await proc2.communicate()
        logger.info("snapshot saved to: {}", snapshot_dir)
    finally:
        os.unlink(cfg_path)

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
