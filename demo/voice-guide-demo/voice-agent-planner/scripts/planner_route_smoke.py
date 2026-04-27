"""Batch tester for the planner route.

Runs a curated set of prompts through any PlannerBackend in isolation and writes
structured outcomes to a JSON file.

Usage:
    PYTHONPATH=. uv run -- python scripts/planner_route_smoke.py \
        [--backend auto|direct|openclaw] [--out PATH]

Direct backend is stateless. Openclaw backend wipes its session between turns so
accumulated history can't bias the next turn.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import time
import uuid
from pathlib import Path

from dotenv import load_dotenv
from loguru import logger

REPO_ROOT = Path(__file__).resolve().parent.parent
USER_CONFIG_DIR = Path(os.getenv("XDG_CONFIG_HOME", Path.home() / ".config"))
load_dotenv(USER_CONFIG_DIR / "nemoclaw-voice-agent" / "voice-agent.env", override=False)
load_dotenv(REPO_ROOT.parent / "voice-agent.env", override=False)
load_dotenv(REPO_ROOT / "voice_agent_webrtc" / ".env", override=False)

from apps.jewel_voice_guide.planner_backends import (
    DirectPlannerBackend,
    OpenclawPlannerBackend,
    PlannerBackend,
    PlannerBackendMode,
    PlannerBackendRouter,
)
from apps.jewel_voice_guide.planner_bridge import (
    MARKER_BEGIN,
    MARKER_END,
    PlannerQueryRequest,
    PlannerQueryResponse,
)
from apps.jewel_voice_guide.router import route_turn


SCENARIOS: list[dict[str, str]] = [
    {
        "id": "multi_step_itinerary",
        "label": "Multi-step Jewel itinerary with constraint",
        "prompt": "I have 3 hours at Jewel before my flight, plan something with food and the Rain Vortex",
    },
    {
        "id": "cross_destination_marina_bay",
        "label": "Cross-destination plan: Jewel → Marina Bay sunset",
        "prompt": "Plan a sunset trip to Marina Bay then back to Jewel before my flight",
    },
    {
        "id": "transit_time_bound",
        "label": "Time-bound airport transit",
        "prompt": "I land at Changi at 4 pm, what should I do before my 8 pm flight",
    },
    {
        "id": "live_weather",
        "label": "Live data: Jewel weather tonight",
        "prompt": "What's the weather like at Jewel tonight",
    },
    {
        "id": "live_hours",
        "label": "Live data: which attractions are open now",
        "prompt": "Which attractions at Jewel are open right now",
    },
    {
        "id": "sequencing_explicit",
        "label": "Explicit sequencing inside Jewel",
        "prompt": "I want to see the Rain Vortex first then Canopy Park before I leave",
    },
    {
        "id": "vague_short",
        "label": "Vague short ask (should ideally clarify)",
        "prompt": "Make me a plan",
    },
    {
        "id": "family_multi_step",
        "label": "Family multi-step with constraints",
        "prompt": "Plan a 4 hour visit for my family with two kids who want food and toys",
    },
    {
        "id": "cross_dest_sentosa_with_kids",
        "label": "Cross-destination Sentosa with kids and time bound",
        "prompt": "Best route from Jewel to Sentosa with kids in 5 hours",
    },
    {
        "id": "live_closure",
        "label": "Live data: closure check",
        "prompt": "Is the Rain Vortex closed today",
    },
]


def _marker_seen(raw: str | None) -> bool:
    if not raw:
        return False
    return MARKER_BEGIN in raw and MARKER_END in raw


def _stripped_marker_payload(raw: str | None) -> str | None:
    if not raw:
        return None
    pattern = rf"{MARKER_BEGIN}\s*(\{{.*?\}})\s*{MARKER_END}"
    match = re.search(pattern, raw, flags=re.DOTALL)
    return match.group(1) if match else None


def _classify_outcome(response: PlannerQueryResponse) -> str:
    if response.status == "ok":
        return "ok"
    if response.status == "timeout" or response.error_code in {"planner_model_timeout", "planner_stale_response"}:
        return "graceful_timeout"
    if response.error_code == "planner_unavailable":
        return "graceful_unavailable"
    if response.error_code in {"planner_busy", "planner_runtime_error"}:
        return "graceful_runtime_error"
    if response.error_code in {"planner_invalid_response", "planner_bridge_failure"}:
        return "schema_error"
    return "other_error"


async def _run_one(backend: PlannerBackend, scenario: dict[str, str]) -> dict[str, object]:
    # Only the openclaw backend has session state worth wiping. Direct/router are stateless
    # for our purposes (router will only delegate cleanup to openclaw if present).
    try:
        await backend.cleanup_session(f"smoke-pre-{scenario['id']}")
    except Exception as exc:
        logger.debug("cleanup_session noop / failed for backend={}: {}", backend.name, exc)

    decision = route_turn(scenario["prompt"], {"planner_available": True, "lookup_available": True})
    request = PlannerQueryRequest(
        request_id=f"smoke_{uuid.uuid4().hex[:10]}",
        session_id=f"smoke-session-{scenario['id']}",
        user_text=scenario["prompt"],
        route_reason=decision.reason,
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

    raw_capture: dict[str, str | None] = {"raw": None}

    # Best-effort raw-output snooping for the openclaw bridge path so the smoke report
    # can show marker presence and request_id matches. Direct backend doesn't need this.
    bridge_obj = getattr(backend, "bridge", None)
    original_run = None
    if bridge_obj is not None and hasattr(bridge_obj, "_run_remote_query"):
        original_run = bridge_obj._run_remote_query

        async def capture(ssh_config_path: str, request: PlannerQueryRequest) -> str:
            raw = await original_run(ssh_config_path, request)
            raw_capture["raw"] = raw
            return raw

        bridge_obj._run_remote_query = capture  # type: ignore[assignment]

    started = time.monotonic()
    try:
        response = await backend.query(request)
    finally:
        if bridge_obj is not None and original_run is not None:
            bridge_obj._run_remote_query = original_run  # type: ignore[assignment]
        elapsed = time.monotonic() - started

    raw = raw_capture["raw"]
    payload_request_id: str | None = None
    payload = _stripped_marker_payload(raw)
    if payload:
        try:
            payload_obj = json.loads(payload)
            if isinstance(payload_obj, dict):
                cand = payload_obj.get("request_id")
                if isinstance(cand, str):
                    payload_request_id = cand
        except json.JSONDecodeError:
            pass

    return {
        "id": scenario["id"],
        "label": scenario["label"],
        "prompt": scenario["prompt"],
        "route_reason": decision.reason,
        "router_route": decision.route,
        "router_confidence": decision.confidence,
        "elapsed_seconds": round(elapsed, 2),
        "status": response.status,
        "error_code": response.error_code,
        "result_type": response.result_type,
        "planner_mode": response.planner_mode,
        "confidence": response.confidence,
        "spoken_response": response.spoken_response,
        "display_response": response.display_response,
        "warning_count": len(response.warnings),
        "warnings_sample": response.warnings[:2],
        "marker_seen": _marker_seen(raw),
        "raw_request_id_match": payload_request_id == request.request_id if payload_request_id else None,
        "raw_payload_request_id": payload_request_id,
        "raw_tail": (raw or "")[-300:],
        "outcome": _classify_outcome(response),
        "backend": backend.name,
    }


def _build_backend(name: str) -> PlannerBackend:
    name = name.strip().lower()
    if name == "direct":
        return DirectPlannerBackend()
    if name == "openclaw":
        return OpenclawPlannerBackend()
    if name == "auto":
        return PlannerBackendRouter(mode=PlannerBackendMode.AUTO)
    raise ValueError(f"Unknown backend {name!r}; use direct|openclaw|auto")


async def main() -> int:
    parser = argparse.ArgumentParser(description="Planner-route smoke tester")
    parser.add_argument(
        "--backend",
        default="auto",
        choices=["auto", "direct", "openclaw"],
        help="Which planner backend to exercise (default: auto = router)",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="Path to write JSON results (default: /tmp/planner_route_smoke_<backend>.json)",
    )
    parser.add_argument(
        "out_positional",
        nargs="?",
        default=None,
        help=argparse.SUPPRESS,
    )
    args = parser.parse_args()

    out_arg = args.out or args.out_positional
    out_path = Path(out_arg) if out_arg else Path(f"/tmp/planner_route_smoke_{args.backend}.json")

    backend = _build_backend(args.backend)
    health = await backend.health()
    if not health.planner_available:
        logger.error("Backend {} not available; aborting. health={}", backend.name, health.model_dump())
        return 1

    logger.info(
        "Starting {} planner smoke tests against backend={}; results -> {}",
        len(SCENARIOS),
        backend.name,
        out_path,
    )
    results: list[dict[str, object]] = []
    for index, scenario in enumerate(SCENARIOS, 1):
        logger.info("[{:>2}/{:>2}] {} :: {!r}", index, len(SCENARIOS), scenario["id"], scenario["prompt"])
        try:
            result = await _run_one(backend, scenario)
        except Exception as exc:
            logger.exception("Test {} blew up: {}", scenario["id"], exc)
            result = {
                "id": scenario["id"],
                "label": scenario["label"],
                "prompt": scenario["prompt"],
                "outcome": "harness_error",
                "error_code": "harness_exception",
                "spoken_response": str(exc)[:300],
                "elapsed_seconds": 0.0,
                "status": "error",
                "result_type": None,
                "planner_mode": None,
                "confidence": None,
                "display_response": None,
                "warning_count": 0,
                "warnings_sample": [],
                "marker_seen": False,
                "raw_request_id_match": None,
                "raw_payload_request_id": None,
                "raw_tail": "",
                "route_reason": None,
                "router_route": None,
                "router_confidence": None,
                "backend": backend.name,
            }
        results.append(result)
        logger.info(
            "[{:>2}/{:>2}] -> outcome={} status={} elapsed={}s spoken={!r}",
            index,
            len(SCENARIOS),
            result.get("outcome"),
            result.get("status"),
            result.get("elapsed_seconds"),
            (result.get("spoken_response") or "")[:120],
        )
        out_path.write_text(
            json.dumps(
                {
                    "backend": backend.name,
                    "sandbox": health.sandbox_name,
                    "results": results,
                },
                indent=2,
                ensure_ascii=False,
            )
        )

    try:
        await backend.cleanup_session("smoke-final")
    except Exception as exc:
        logger.debug("final cleanup_session noop / failed: {}", exc)
    logger.info("Done. Wrote {} results to {}", len(results), out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
