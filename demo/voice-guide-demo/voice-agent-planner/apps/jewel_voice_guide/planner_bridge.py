"""Text-first planner bridge for the Jewel voice-guide Phase 1 demo."""

from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from loguru import logger
from pydantic import BaseModel, Field, ValidationError, field_validator

MARKER_BEGIN = "VOICE_GUIDE_JSON_BEGIN"
MARKER_END = "VOICE_GUIDE_JSON_END"


class PlannerHealthResponse(BaseModel):
    """Health response exposed by the planner bridge."""

    status: str = "ok"
    planner_available: bool
    tools_available: bool
    timestamp: str
    sandbox_name: str | None = None


class PlannerQueryRequest(BaseModel):
    """Request payload sent from the voice layer to the planner bridge."""

    api_version: str = "v1"
    request_id: str
    session_id: str
    user_text: str
    route_reason: str
    user_profile: dict[str, Any] = Field(default_factory=dict)
    session_context: dict[str, Any] = Field(default_factory=dict)
    planner_options: dict[str, Any] = Field(default_factory=dict)


class PlannerQueryResponse(BaseModel):
    """Structured planner response consumed by the voice layer."""

    request_id: str
    status: str
    planner_mode: str = "singapore_itinerary"
    spoken_response: str
    display_response: str | None = None
    confidence: str = "low"
    result_type: str = "recommendation"
    recommendations: list[dict[str, Any]] = Field(default_factory=list)
    itinerary: dict[str, Any] = Field(default_factory=dict)
    citations: list[str] = Field(default_factory=list)
    planner_metadata: dict[str, Any] = Field(default_factory=dict)
    followup_question: dict[str, Any] | None = None
    warnings: list[dict[str, Any]] = Field(default_factory=list)
    error_code: str | None = None

    @field_validator("confidence", mode="before")
    @classmethod
    def normalize_confidence(cls, value: Any) -> str:
        """Accept either string or numeric confidence values."""
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"high", "medium", "low"}:
                return normalized
            try:
                value = float(normalized)
            except ValueError:
                return "low"

        if isinstance(value, int | float):
            if value >= 0.75:
                return "high"
            if value >= 0.4:
                return "medium"
            return "low"

        return "low"

    @field_validator("warnings", mode="before")
    @classmethod
    def normalize_warnings(cls, value: Any) -> list[dict[str, Any]]:
        """Coerce planner warnings into list[dict] regardless of whether the model returned strings."""
        if value is None:
            return []
        if isinstance(value, str):
            value = [value]
        if not isinstance(value, list):
            return [{"code": "planner_warning", "message": str(value)[:500]}]
        normalized: list[dict[str, Any]] = []
        for item in value:
            if isinstance(item, dict):
                normalized.append(item)
            elif item is None:
                continue
            else:
                normalized.append({"code": "planner_warning", "message": str(item)[:500]})
        return normalized

    @field_validator("citations", mode="before")
    @classmethod
    def normalize_citations(cls, value: Any) -> list[str]:
        """Coerce citations into list[str] in case the planner returns dicts or a single value."""
        if value is None:
            return []
        if isinstance(value, str):
            return [value]
        if not isinstance(value, list):
            return [str(value)]
        normalized: list[str] = []
        for item in value:
            if item is None:
                continue
            if isinstance(item, str):
                normalized.append(item)
            elif isinstance(item, dict):
                text = item.get("url") or item.get("title") or item.get("source") or item.get("text")
                normalized.append(str(text) if text is not None else str(item))
            else:
                normalized.append(str(item))
        return normalized


def _timestamp() -> str:
    """Return an ISO-8601 UTC timestamp."""
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _resolve_default_sandbox() -> str | None:
    sandboxes_path = Path.home() / ".nemoclaw" / "sandboxes.json"
    if not sandboxes_path.exists():
        return None
    try:
        payload = json.loads(sandboxes_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return payload.get("defaultSandbox")


class PlannerBridge:
    """Runs planner turns inside the OpenClaw sandbox via OpenShell SSH."""

    def __init__(
        self,
        sandbox_name: str | None = None,
        agent_name: str = "main",
        timeout_sec: int = 95,
        openclaw_agent_prefix: str = "nemoclaw-start",
    ):
        """Initialize planner bridge settings from args and environment."""
        self.sandbox_name = sandbox_name or os.getenv("PLANNER_SANDBOX_NAME") or _resolve_default_sandbox()
        self.agent_name = os.getenv("PLANNER_AGENT_NAME", agent_name)
        self.timeout_sec = int(os.getenv("PLANNER_TIMEOUT_SEC", str(timeout_sec)))
        self.openclaw_agent_prefix = os.getenv("OPENCLAW_AGENT_PREFIX", openclaw_agent_prefix).strip()
        self.gateway_autostart = os.getenv("OPENCLAW_GATEWAY_AUTOSTART", "true").lower() == "true"
        self._gateway_bootstrapped = False

    async def health(self) -> PlannerHealthResponse:
        """Check whether the configured sandbox planner path is reachable."""
        planner_available = bool(self.sandbox_name and shutil.which("openshell") and shutil.which("ssh"))
        if planner_available:
            try:
                await self._run(["openshell", "sandbox", "ssh-config", self.sandbox_name], timeout=10)
            except Exception as exc:
                planner_available = False
                logger.warning(f"Planner health check failed: {exc}")
        return PlannerHealthResponse(
            planner_available=planner_available,
            tools_available=planner_available,
            timestamp=_timestamp(),
            sandbox_name=self.sandbox_name,
        )

    async def query(self, request: PlannerQueryRequest) -> PlannerQueryResponse:
        """Execute one planner turn and parse its structured response."""
        health = await self.health()
        if not health.planner_available:
            return PlannerQueryResponse(
                request_id=request.request_id,
                status="error",
                error_code="planner_unavailable",
                spoken_response=(
                    "I can give a simpler suggestion now, but detailed planning is temporarily unavailable."
                ),
                display_response="Planner unavailable",
                confidence="low",
                result_type="recommendation",
                planner_metadata={
                    "used_tools": [],
                    "used_live_data": False,
                    "needs_followup": False,
                    "route_class": "planner",
                    "response_style": "voice_friendly",
                },
            )

        ssh_config = await self._run(["openshell", "sandbox", "ssh-config", self.sandbox_name], timeout=15)
        with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8") as handle:
            handle.write(ssh_config)
            ssh_config_path = handle.name

        try:
            if self.gateway_autostart and not self._gateway_bootstrapped:
                await self._ensure_remote_gateway(ssh_config_path)
                self._gateway_bootstrapped = True
            remote_output = await self._run_remote_query(ssh_config_path, request)
            logger.debug(
                "Planner raw output (request_id={}, len={}): {!r}",
                request.request_id,
                len(remote_output),
                remote_output[-2000:],
            )
            response = self._parse_response(request.request_id, remote_output)

            payload_request_id = self._extract_payload_request_id(remote_output)
            if (
                payload_request_id is not None
                and payload_request_id != request.request_id
                and response.status == "ok"
            ):
                logger.warning(
                    "Planner returned stale response: sent request_id={}, payload request_id={}; "
                    "openclaw likely replayed a prior turn after an LLM idle timeout. raw tail={!r}",
                    request.request_id,
                    payload_request_id,
                    remote_output[-2000:],
                )
                return PlannerQueryResponse(
                    request_id=request.request_id,
                    status="timeout",
                    error_code="planner_stale_response",
                    spoken_response="I need a bit more time to plan that. Please try again in a moment.",
                    display_response="Planner returned a stale response",
                    confidence="low",
                    result_type="recommendation",
                    warnings=[
                        {
                            "code": "planner_stale_response",
                            "message": (
                                "Openclaw replayed a prior assistant message instead of a fresh reply "
                                f"(sent={request.request_id}, got={payload_request_id})."
                            ),
                        }
                    ],
                    planner_metadata={
                        "used_tools": [],
                        "used_live_data": False,
                        "needs_followup": True,
                        "route_class": "planner",
                        "response_style": "voice_friendly",
                    },
                )

            if response.status in {"ok", "timeout"} or response.error_code is not None:
                return response
            logger.warning(
                "Planner returned unrecognized status={} for request_id={}; raw tail={!r}",
                response.status,
                request.request_id,
                remote_output[-2000:],
            )
            return PlannerQueryResponse(
                request_id=request.request_id,
                status="error",
                error_code="planner_invalid_response",
                spoken_response="I can give a simpler suggestion now, but the planner response was incomplete.",
                display_response="Planner invalid response",
                confidence="low",
                result_type="recommendation",
                warnings=[{"code": "planner_invalid_response", "message": "Planner output could not be parsed."}],
                planner_metadata={
                    "used_tools": [],
                    "used_live_data": False,
                    "needs_followup": False,
                    "route_class": "planner",
                    "response_style": "voice_friendly",
                },
            )
        except TimeoutError:
            return PlannerQueryResponse(
                request_id=request.request_id,
                status="timeout",
                spoken_response="I need a bit more time to plan that. Please try again in a moment.",
                display_response="Planner timeout",
                confidence="low",
                result_type="recommendation",
                planner_metadata={
                    "used_tools": [],
                    "used_live_data": False,
                    "needs_followup": False,
                    "route_class": "planner",
                    "response_style": "voice_friendly",
                },
            )
        except RuntimeError as exc:
            return self._classify_runtime_error(request.request_id, str(exc))
        except Exception as exc:
            tail = locals().get("remote_output", "")
            if isinstance(tail, str) and tail:
                logger.error(
                    "Unexpected planner bridge failure for request_id={}: {}; raw tail={!r}",
                    request.request_id,
                    exc,
                    tail[-2000:],
                )
            else:
                logger.error(f"Unexpected planner bridge failure for request_id={request.request_id}: {exc}")
            return PlannerQueryResponse(
                request_id=request.request_id,
                status="error",
                error_code="planner_bridge_failure",
                spoken_response="Detailed planning hit an internal bridge error. Please try again in a moment.",
                display_response="Planner bridge failure",
                confidence="low",
                result_type="recommendation",
                warnings=[{"code": "planner_bridge_failure", "message": str(exc)[:200]}],
                planner_metadata={
                    "used_tools": [],
                    "used_live_data": False,
                    "needs_followup": False,
                    "route_class": "planner",
                    "response_style": "voice_friendly",
                },
            )
        finally:
            Path(ssh_config_path).unlink(missing_ok=True)

    async def _ensure_remote_gateway(self, ssh_config_path: str) -> None:
        """Best-effort gateway bootstrapping for containerized sandboxes without systemd."""
        remote_cmd = (
            "set -e; "
            "log_dir=\"$HOME/.openclaw\"; mkdir -p \"$log_dir\"; "
            "probe_log=\"$log_dir/gateway-probe.log\"; run_log=\"$log_dir/gateway-run.log\"; "
            "if openclaw gateway probe >\"$probe_log\" 2>&1; then "
            "  echo 'gateway-ready'; "
            "  exit 0; "
            "fi; "
            "nohup openclaw gateway run --allow-unconfigured >\"$run_log\" 2>&1 & "
            "sleep 2; "
            "openclaw gateway probe >\"$probe_log\" 2>&1 || true; "
            "echo 'gateway-bootstrapped'"
        )
        try:
            out = await self._run(
                [
                    "ssh",
                    "-T",
                    "-F",
                    ssh_config_path,
                    "-o",
                    "StrictHostKeyChecking=no",
                    "-o",
                    "UserKnownHostsFile=/dev/null",
                    "-o",
                    "ConnectTimeout=10",
                    "-o",
                    "LogLevel=ERROR",
                    f"openshell-{self.sandbox_name}",
                    remote_cmd,
                ],
                timeout=20,
            )
            logger.info("OpenClaw gateway bootstrap: {}", out.strip()[:180])
        except Exception as exc:
            logger.warning("OpenClaw gateway bootstrap failed (continuing with embedded fallback): {}", exc)

    async def cleanup_session(self, session_id: str) -> None:
        """Delete session artifacts for the active planner session."""
        if not self.sandbox_name or not session_id:
            return

        ssh_config = await self._run(["openshell", "sandbox", "ssh-config", self.sandbox_name], timeout=15)
        with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8") as handle:
            handle.write(ssh_config)
            ssh_config_path = handle.name

        try:
            await self._run_remote_cleanup(ssh_config_path, session_id)
        except Exception as exc:
            logger.warning(f"Planner session cleanup failed for {session_id}: {exc}")
        finally:
            Path(ssh_config_path).unlink(missing_ok=True)

    async def _run_remote_query(self, ssh_config_path: str, request: PlannerQueryRequest) -> str:
        prompt = self._render_prompt(request)
        prompt_b64 = base64.b64encode(prompt.encode("utf-8")).decode("ascii")
        api_key = os.getenv("NVIDIA_API_KEY", "")
        api_b64 = base64.b64encode(api_key.encode("utf-8")).decode("ascii")
        remote_cmd = (
            f"pm=$(printf '%s' '{prompt_b64}' | base64 -d) || exit 1; "
            f"nv=$(printf '%s' '{api_b64}' | base64 -d) || exit 1; "
            "if [ -n \"$nv\" ]; then export NVIDIA_API_KEY=\"$nv\"; fi; "
            f"openclaw agent --agent {self.agent_name} "
            f"-m \"$pm\" --session-id '{request.session_id}'"
        )

        return await self._run(
            [
                "ssh",
                "-T",
                "-F",
                ssh_config_path,
                "-o",
                "StrictHostKeyChecking=no",
                "-o",
                "UserKnownHostsFile=/dev/null",
                "-o",
                "ConnectTimeout=10",
                "-o",
                "LogLevel=ERROR",
                f"openshell-{self.sandbox_name}",
                remote_cmd,
            ],
            timeout=self.timeout_sec,
        )

    async def _run_remote_cleanup(self, ssh_config_path: str, session_id: str) -> str:
        # openclaw collapses every direct CLI invocation into a canonical
        # `agent:<agent_id>:<mainKey>` slot regardless of the --session-id we pass, and the
        # actual on-disk file is named after openclaw's internal UUID — not our session_id.
        # So we wipe the entire session directory for this agent rather than trying to
        # delete a single file by our own id (which never exists).
        sessions_dir = f"/sandbox/.openclaw-data/agents/{self.agent_name}/sessions"
        remote_cmd = (
            "set -e; "
            f"if [ -d '{sessions_dir}' ]; then "
            f"  rm -f '{sessions_dir}'/*.jsonl '{sessions_dir}'/*.jsonl.lock "
            f"     '{sessions_dir}'/*.json '{sessions_dir}'/*.json.lock; "
            f"fi; "
            f"echo 'cleaned (logical session_id={session_id})'"
        )
        return await self._run(
            [
                "ssh",
                "-T",
                "-F",
                ssh_config_path,
                "-o",
                "StrictHostKeyChecking=no",
                "-o",
                "UserKnownHostsFile=/dev/null",
                "-o",
                "ConnectTimeout=10",
                "-o",
                "LogLevel=ERROR",
                f"openshell-{self.sandbox_name}",
                remote_cmd,
            ],
            timeout=20,
        )

    async def _run(self, args: list[str], timeout: int) -> str:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except TimeoutError as exc:
            proc.kill()
            await proc.communicate()
            raise TimeoutError("planner command timed out") from exc
        output = stdout.decode("utf-8", errors="replace")
        if proc.returncode != 0:
            raise RuntimeError(output.strip() or f"planner command failed with exit {proc.returncode}")
        return output

    def _render_prompt(self, request: PlannerQueryRequest) -> str:
        allow_tools = bool(request.planner_options.get("allow_tools"))
        allow_live_data = bool(request.planner_options.get("allow_live_data"))
        payload = {
            "api_version": request.api_version,
            "request_id": request.request_id,
            "session_id": request.session_id,
            "user_text": request.user_text,
            "route_reason": request.route_reason,
            "user_profile": request.user_profile,
            "session_context": request.session_context,
            "planner_options": request.planner_options,
        }
        payload_json = json.dumps(payload, indent=2)
        return f"""
You are the Phase 1 Jewel voice planner for a Singapore travel demo.
Respond quickly. Do not reveal your internal reasoning.
Keep the final JSON concise: target <= 220 output tokens.

If the file /sandbox/.openclaw/skills/jewel-voice-planner/SKILL.md exists, read that exact file first.
If that file is missing, try /sandbox/.openclaw/workspace/skills/jewel-voice-planner/SKILL.md.
Do not search for alternate skill paths. Do not write temp files just to format your answer.
Always answer with one JSON object only, wrapped between the marker lines below.
Do not include markdown, commentary, or any text outside the markers.

Required response shape (every field below must appear with the exact type shown):
- request_id: string (echo the request_id from the input payload exactly)
- status: string, one of: "ok", "error", "timeout"
- planner_mode: string (e.g. "singapore_itinerary", "itinerary", "recommendation")
- spoken_response: string, concise and speakable
- confidence: number between 0 and 1, OR one of "high" | "medium" | "low"
- result_type: string, one of: "recommendation" | "itinerary" | "hybrid" | "clarification"
- planner_metadata: object, e.g. {{"used_tools": [], "used_live_data": false, "needs_followup": false, "route_class": "planner", "response_style": "voice_friendly"}}

Optional fields (include only when meaningful, but ALWAYS use the exact shape below):
- display_response: string (richer text version)
- recommendations: array of objects (free-form keys allowed)
- itinerary: object (free-form keys allowed)
- citations: array of strings only (URLs or short source labels). Never an array of objects, never a single string.
- warnings: array of objects only, where each object is {{"code": "<short_snake_case>", "message": "<human readable text>"}}.
  Never a bare string, never an array of strings. Example: [{{"code": "no_live_data", "message": "Live data not checked; based on typical Singapore itinerary."}}]
- followup_question: object {{"text": "...", "options": ["..."]}} (only when result_type == "clarification")
- error_code: string (only when status != "ok")

Marker format:
{MARKER_BEGIN}
{{"request_id":"...","status":"ok",...}}
{MARKER_END}

Voice rules:
- spoken_response must be concise and speakable
- display_response may be richer
- use warnings (in the array-of-objects shape above) instead of pretending live checks happened when they did not
- if you need clarification, use result_type=clarification
- If tools/live checks are disabled in planner_options, do not call tools.
- If tools are disabled, rely on static knowledge and add warning code "no_live_data".
- Keep spoken_response under ~90 characters when practical.

Strict output rules:
- Output exactly one JSON object between the markers, nothing else (no markdown, no prose, no code fences)
- Do not invent extra top-level keys outside this contract
- Do not wrap the JSON in quotes or escape it; emit raw JSON
- No bullet-list planning notes outside the marker payload.

Runtime flags for this request:
- planner_options.allow_tools = {str(allow_tools).lower()}
- planner_options.allow_live_data = {str(allow_live_data).lower()}

Current request payload:
{payload_json}
""".strip()

    def _classify_runtime_error(self, request_id: str, message: str) -> PlannerQueryResponse:
        """Convert bridge/runtime failures into structured planner responses."""
        lowered = message.lower()
        if "request timed out before a response was generated" in lowered:
            return PlannerQueryResponse(
                request_id=request_id,
                status="timeout",
                error_code="planner_model_timeout",
                spoken_response="I need a bit more time to plan that. Please try again in a moment.",
                display_response="Planner model timeout",
                confidence="low",
                result_type="recommendation",
                warnings=[{"code": "planner_model_timeout", "message": message[:200]}],
                planner_metadata={
                    "used_tools": [],
                    "used_live_data": False,
                    "needs_followup": True,
                    "route_class": "planner",
                    "response_style": "voice_friendly",
                },
            )
        if "session file locked" in lowered or "lane task error" in lowered:
            return PlannerQueryResponse(
                request_id=request_id,
                status="error",
                error_code="planner_busy",
                spoken_response="The planner is still busy with a previous step. Let me try that again in a moment.",
                display_response="Planner busy",
                confidence="low",
                result_type="recommendation",
                warnings=[{"code": "planner_busy", "message": message[:200]}],
                planner_metadata={
                    "used_tools": [],
                    "used_live_data": False,
                    "needs_followup": True,
                    "route_class": "planner",
                    "response_style": "voice_friendly",
                },
            )

        return PlannerQueryResponse(
            request_id=request_id,
            status="error",
            error_code="planner_runtime_error",
            spoken_response="Detailed planning ran into a runtime issue. Please try again in a moment.",
            display_response="Planner runtime error",
            confidence="low",
            result_type="recommendation",
            warnings=[{"code": "planner_runtime_error", "message": message[:200]}],
            planner_metadata={
                "used_tools": [],
                "used_live_data": False,
                "needs_followup": False,
                "route_class": "planner",
                "response_style": "voice_friendly",
            },
        )

    def _extract_payload_request_id(self, output: str) -> str | None:
        """Best-effort extraction of the inner JSON's request_id without re-validating the whole payload."""
        marker_pattern = rf"{MARKER_BEGIN}\s*(\{{.*?\}})\s*{MARKER_END}"
        match = re.search(marker_pattern, output, flags=re.DOTALL)
        if not match:
            return None
        try:
            payload = json.loads(match.group(1))
        except json.JSONDecodeError:
            return None
        candidate = payload.get("request_id") if isinstance(payload, dict) else None
        return candidate if isinstance(candidate, str) and candidate else None

    def _parse_response(self, request_id: str, output: str) -> PlannerQueryResponse:
        lowered = output.lower()
        if "request timed out before a response was generated" in lowered:
            return PlannerQueryResponse(
                request_id=request_id,
                status="timeout",
                error_code="planner_model_timeout",
                spoken_response="I need a bit more time to plan that. Please try again in a moment.",
                display_response="Planner model timeout",
                confidence="low",
                result_type="recommendation",
                warnings=[{"code": "planner_model_timeout", "message": output[:200]}],
                planner_metadata={
                    "used_tools": [],
                    "used_live_data": False,
                    "needs_followup": True,
                    "route_class": "planner",
                    "response_style": "voice_friendly",
                },
            )
        marker_pattern = rf"{MARKER_BEGIN}\s*(\{{.*?\}})\s*{MARKER_END}"
        match = re.search(marker_pattern, output, flags=re.DOTALL)
        if not match:
            recovered = self._extract_json_object_with_required_keys(output)
            if recovered is not None:
                try:
                    payload = json.loads(recovered)
                    payload.setdefault("request_id", request_id)
                    payload.setdefault("planner_metadata", {})
                    return PlannerQueryResponse.model_validate(payload)
                except (json.JSONDecodeError, ValidationError) as exc:
                    logger.warning("Planner recovered bare JSON but validation failed: {}", exc)
            logger.warning(f"Planner output missing JSON markers: {output[-2000:]}")
            return self._build_runtime_parse_response(
                request_id=request_id,
                message="Planner output missing structured JSON markers.",
            )

        try:
            payload = json.loads(match.group(1))
        except json.JSONDecodeError as exc:
            logger.warning(f"Planner output JSON parse failed: {exc}")
            return self._build_runtime_parse_response(
                request_id=request_id,
                message=f"Planner output JSON parse failed: {exc}",
            )

        payload.setdefault("request_id", request_id)
        payload.setdefault("planner_metadata", {})
        try:
            return PlannerQueryResponse.model_validate(payload)
        except ValidationError as exc:
            logger.warning("Planner payload schema validation failed: {}", exc)
            return self._build_runtime_parse_response(
                request_id=request_id,
                message=f"Planner payload schema validation failed: {exc}",
            )

    @staticmethod
    def _extract_json_object_with_required_keys(output: str) -> str | None:
        """Best-effort recovery when markers are missing but JSON is present."""
        required = ("status", "spoken_response")
        start = output.find("{")
        while start >= 0:
            depth = 0
            in_string = False
            escape = False
            for idx in range(start, len(output)):
                ch = output[idx]
                if in_string:
                    if escape:
                        escape = False
                    elif ch == "\\":
                        escape = True
                    elif ch == '"':
                        in_string = False
                    continue
                if ch == '"':
                    in_string = True
                    continue
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        candidate = output[start : idx + 1]
                        try:
                            obj = json.loads(candidate)
                        except json.JSONDecodeError:
                            break
                        if isinstance(obj, dict) and all(obj.get(key) for key in required):
                            return candidate
                        break
            start = output.find("{", start + 1)
        return None

    @staticmethod
    def _build_runtime_parse_response(request_id: str, message: str) -> PlannerQueryResponse:
        return PlannerQueryResponse(
            request_id=request_id,
            status="error",
            error_code="planner_runtime_error",
            spoken_response="I can still suggest a simpler plan while detailed parsing recovers.",
            display_response="Planner parse fallback",
            confidence="low",
            result_type="recommendation",
            warnings=[{"code": "planner_runtime_error", "message": message[:500]}],
            planner_metadata={
                "used_tools": [],
                "used_live_data": False,
                "needs_followup": True,
                "route_class": "planner",
                "response_style": "voice_friendly",
            },
        )
