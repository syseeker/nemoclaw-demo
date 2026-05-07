"""Direct planner backend - HTTPS to NVIDIA cloud, bypassing openclaw entirely.

The voice-agent LLM already calls integrate.api.nvidia.com from the host with
NVIDIA_API_KEY. This backend reuses that exact pattern but targets the larger
nemotron-3-super-120b-a12b model and inlines the jewel-voice-planner skill prompt.

Tested latency: ~13-37s (vs openclaw's ~60-100s) for the same prompt and model.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from datetime import UTC, datetime
from typing import Any

import httpx
from loguru import logger
from pydantic import ValidationError

from apps.jewel_voice_guide.planner_backends.base import PlannerBackend
from apps.jewel_voice_guide.planner_backends.skill_prompt import (
    JEWEL_VOICE_PLANNER_SYSTEM_PROMPT,
    build_user_message,
)
from apps.jewel_voice_guide.planner_bridge import (
    MARKER_BEGIN,
    MARKER_END,
    PlannerHealthResponse,
    PlannerQueryRequest,
    PlannerQueryResponse,
)

DEFAULT_BASE_URL = "https://integrate.api.nvidia.com/v1"
DEFAULT_MODEL = "nvidia/nemotron-3-super-120b-a12b"
DEFAULT_TIMEOUT_SEC = 120.0
DEFAULT_MAX_TOKENS = 1500
_REQUIRED_RESPONSE_KEYS = ("status", "spoken_response")


def _timestamp() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class DirectPlannerBackend(PlannerBackend):
    """Calls NVIDIA cloud directly via HTTPS (no SSH, no openclaw)."""

    name = "direct"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        timeout_sec: float | None = None,
        max_tokens: int | None = None,
    ) -> None:
        self.api_key = (api_key or os.getenv("PLANNER_DIRECT_API_KEY") or os.getenv("NVIDIA_API_KEY") or "").strip()
        self.base_url = (
            base_url
            or os.getenv("PLANNER_DIRECT_BASE_URL")
            or os.getenv("NVIDIA_LLM_URL")
            or DEFAULT_BASE_URL
        ).rstrip("/")
        self.model = model or os.getenv("PLANNER_DIRECT_MODEL") or DEFAULT_MODEL
        self.timeout_sec = timeout_sec or float(os.getenv("PLANNER_DIRECT_TIMEOUT_SEC", str(DEFAULT_TIMEOUT_SEC)))
        self.max_tokens = max_tokens or int(os.getenv("PLANNER_DIRECT_MAX_TOKENS", str(DEFAULT_MAX_TOKENS)))

    async def health(self) -> PlannerHealthResponse:
        available = bool(self.api_key)
        return PlannerHealthResponse(
            planner_available=available,
            tools_available=False,
            timestamp=_timestamp(),
            sandbox_name=None,
        )

    async def query(self, request: PlannerQueryRequest) -> PlannerQueryResponse:
        if not self.api_key:
            return self._build_unavailable_response(request, "missing PLANNER_DIRECT_API_KEY / NVIDIA_API_KEY")

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
        body = {
            "model": self.model,
            "stream": False,
            "max_tokens": self.max_tokens,
            "temperature": 0.0,
            "messages": [
                {"role": "system", "content": JEWEL_VOICE_PLANNER_SYSTEM_PROMPT},
                {"role": "user", "content": build_user_message(payload)},
            ],
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout_sec) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers={
                        "authorization": f"Bearer {self.api_key}",
                        "content-type": "application/json",
                        "accept": "application/json",
                    },
                    json=body,
                )
        except (httpx.TimeoutException, asyncio.TimeoutError) as exc:
            logger.warning("DirectPlannerBackend timed out for {}: {}", request.request_id, exc)
            return self._build_timeout_response(request, str(exc))
        except httpx.HTTPError as exc:
            logger.error("DirectPlannerBackend HTTP error for {}: {}", request.request_id, exc)
            return self._build_runtime_error_response(request, str(exc))

        if response.status_code != 200:
            tail = response.text[-2000:] if response.text else f"HTTP {response.status_code}"
            logger.error(
                "DirectPlannerBackend got non-200 ({}) for {}: {!r}",
                response.status_code,
                request.request_id,
                tail,
            )
            return self._build_runtime_error_response(
                request,
                f"HTTP {response.status_code}: {response.text[:200] if response.text else ''}",
            )

        try:
            chat = response.json()
        except json.JSONDecodeError as exc:
            logger.error("DirectPlannerBackend non-JSON response for {}: {}", request.request_id, exc)
            return self._build_runtime_error_response(request, f"non-json response: {exc}")

        try:
            content = chat["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            logger.error("DirectPlannerBackend malformed chat shape for {}: {}", request.request_id, exc)
            return self._build_runtime_error_response(request, f"unexpected chat shape: {exc}")

        if not isinstance(content, str) or not content.strip():
            logger.warning("DirectPlannerBackend got empty content for {}", request.request_id)
            return self._build_invalid_response(request, "model returned empty content")

        logger.debug(
            "DirectPlannerBackend raw content (request_id={}, len={}): {!r}",
            request.request_id,
            len(content),
            content[-2000:],
        )
        parsed = self._parse_marker_payload(request, content)
        if parsed.error_code == "planner_invalid_response":
            retry = await self._retry_strict_format(request, payload, content)
            if retry is not None:
                return retry
            return self._build_salvaged_response(
                request,
                "strict-format retry could not recover valid planner JSON",
                source_text=content,
            )
        return parsed

    def _parse_marker_payload(self, request: PlannerQueryRequest, content: str) -> PlannerQueryResponse:
        json_payload = self._extract_marker_or_json_payload(content)
        if json_payload is None:
            logger.warning(
                "DirectPlannerBackend missing markers/JSON for {}; head={!r}",
                request.request_id,
                content[:600],
            )
            return self._build_invalid_response(request, "model omitted parseable JSON payload")

        try:
            parsed = json.loads(json_payload)
        except json.JSONDecodeError as exc:
            logger.warning("DirectPlannerBackend marker JSON parse failed for {}: {}", request.request_id, exc)
            return self._build_invalid_response(request, f"marker JSON parse failed: {exc}")

        if not isinstance(parsed, dict):
            return self._build_invalid_response(request, "marker payload was not a JSON object")
        if not all(parsed.get(key) for key in _REQUIRED_RESPONSE_KEYS):
            return self._build_invalid_response(request, "marker payload missing required keys")

        parsed = self._normalize_payload_shapes(parsed)
        parsed.setdefault("request_id", request.request_id)
        parsed.setdefault("planner_metadata", {})

        try:
            response = PlannerQueryResponse.model_validate(parsed)
        except ValidationError as exc:
            logger.warning(
                "DirectPlannerBackend pydantic validation failed for {}: {}",
                request.request_id,
                exc,
            )
            return self._build_invalid_response(request, f"validation failed: {exc.errors()[:3]}")
        if self._looks_internal_reasoning(response.spoken_response):
            return self._build_invalid_response(request, "spoken_response looked like internal reasoning")
        return response

    @staticmethod
    def _normalize_payload_shapes(payload: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(payload)
        display_value = normalized.get("display_response")
        if isinstance(display_value, dict | list):
            normalized["display_response"] = DirectPlannerBackend._render_display_response_markdown(display_value)
            # Preserve structured steps for downstream UI extraction.
            if not normalized.get("itinerary") and isinstance(display_value, dict):
                normalized["itinerary"] = display_value
        elif display_value is not None and not isinstance(display_value, str):
            normalized["display_response"] = str(display_value)

        spoken_value = normalized.get("spoken_response")
        if spoken_value is not None and not isinstance(spoken_value, str):
            normalized["spoken_response"] = str(spoken_value)
        return normalized

    @staticmethod
    def _render_display_response_markdown(value: Any) -> str:
        if isinstance(value, dict):
            title = value.get("title") if isinstance(value.get("title"), str) else None
            steps = value.get("steps")
            lines: list[str] = []
            if title:
                lines.append(f"**{title}**")
                lines.append("")
            if isinstance(steps, list):
                for step in steps:
                    if isinstance(step, dict):
                        time_text = step.get("time") or step.get("time_slot") or step.get("time_range")
                        activity_text = (
                            step.get("activity")
                            or step.get("task")
                            or step.get("title")
                            or step.get("description")
                        )
                        if time_text and activity_text:
                            lines.append(f"- **{time_text}**: {activity_text}")
                        elif activity_text:
                            lines.append(f"- {activity_text}")
                if lines:
                    return "\n".join(lines).strip()
            # Generic dict fallback.
            compact = json.dumps(value, ensure_ascii=False)
            return compact[:2000]
        if isinstance(value, list):
            lines: list[str] = []
            for item in value:
                if isinstance(item, str):
                    lines.append(f"- {item}")
                elif isinstance(item, dict):
                    label = item.get("activity") or item.get("task") or item.get("title") or item.get("name")
                    if label:
                        lines.append(f"- {label}")
            if lines:
                return "\n".join(lines)
            return json.dumps(value, ensure_ascii=False)[:2000]
        return str(value)

    @staticmethod
    def _extract_marker_or_json_payload(content: str) -> str | None:
        """Best-effort extraction from markers, fenced code blocks, or inline JSON object."""
        text = content.strip()

        # 1) Canonical marker block.
        marker_pattern = rf"{MARKER_BEGIN}\s*(\{{.*?\}})\s*{MARKER_END}"
        marker_match = re.search(marker_pattern, text, flags=re.DOTALL)
        if marker_match:
            return marker_match.group(1)

        # 2) Marker begin seen but end marker missing due truncation.
        begin_idx = text.find(MARKER_BEGIN)
        if begin_idx >= 0:
            tail = text[begin_idx + len(MARKER_BEGIN) :]
            obj = DirectPlannerBackend._extract_first_json_object_with_required_keys(tail)
            if obj is not None:
                return obj
            obj = DirectPlannerBackend._extract_json_object_from_start(tail)
            if obj is not None:
                return obj
            # If marker begin exists but object is incomplete, treat as invalid and
            # force retry rather than accidentally parsing nested planner_metadata.
            return None

        # 3) Fenced or bare JSON.
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```\s*$", "", text)
        if text.startswith("{") and text.endswith("}"):
            return text

        # 4) Reasoning + then a JSON object later in the response.
        return DirectPlannerBackend._extract_first_json_object_with_required_keys(text)

    @staticmethod
    def _extract_first_json_object(text: str) -> str | None:
        """Extract the first balanced JSON object from arbitrary text."""
        start = text.find("{")
        while start >= 0:
            depth = 0
            in_string = False
            escape = False
            for idx in range(start, len(text)):
                ch = text[idx]
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
                        return text[start : idx + 1]
            start = text.find("{", start + 1)
        return None

    @staticmethod
    def _extract_first_json_object_with_required_keys(text: str) -> str | None:
        """Pick the first balanced JSON object containing required response keys."""
        start = text.find("{")
        while start >= 0:
            candidate = DirectPlannerBackend._extract_first_json_object(text[start:])
            if candidate is None:
                return None
            try:
                payload = json.loads(candidate)
            except json.JSONDecodeError:
                next_start = text.find("{", start + 1)
                start = next_start
                continue
            if isinstance(payload, dict) and all(payload.get(key) for key in _REQUIRED_RESPONSE_KEYS):
                return candidate
            next_start = text.find("{", start + len(candidate))
            start = next_start
        return None

    @staticmethod
    def _extract_json_object_from_start(text: str) -> str | None:
        """Extract one balanced JSON object only if payload starts with an object."""
        stripped = text.strip()
        if not stripped.startswith("{"):
            return None
        depth = 0
        in_string = False
        escape = False
        for idx, ch in enumerate(stripped):
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
                    return stripped[: idx + 1]
        return None

    @staticmethod
    def _build_salvaged_response(
        request: PlannerQueryRequest,
        reason: str,
        source_text: str | None = None,
    ) -> PlannerQueryResponse:
        """Fallback when model output is malformed: keep conversation moving gracefully."""
        plan_lines = DirectPlannerBackend._extract_plan_lines(source_text or "")
        if plan_lines:
            spoken = plan_lines[0]
            display = "\n".join(f"- {line}" for line in plan_lines[:6])
        else:
            spoken = "I have a quick plan ready, and I can refine details if you want."
            display = "Planner fallback response generated. Ask me to refine destination, timing, or food choices."
        return PlannerQueryResponse(
            request_id=request.request_id,
            status="ok",
            planner_mode="fallback_recommendation",
            spoken_response=spoken,
            display_response=display,
            confidence="low",
            result_type="recommendation",
            warnings=[{"code": "planner_output_salvaged", "message": reason[:500]}],
            planner_metadata={
                "used_tools": [],
                "used_live_data": False,
                "needs_followup": True,
                "route_class": "planner",
                "response_style": "voice_friendly",
                "salvaged": True,
            },
        )

    @staticmethod
    def _extract_plan_lines(text: str) -> list[str]:
        if not text:
            return []
        filtered: list[str] = []
        seen: set[str] = set()
        bad_tokens = (
            "we need to",
            "output json",
            "request_id",
            "spoken_response",
            "display_response",
            "planner_mode",
            "result_type",
            "confidence",
            "status",
            "planner_metadata",
            "result_type",
            "voice_guide_json",
            "markers",
            "fields:",
            "count:",
            "let's count",
            "valid json",
        )
        signal_pattern = re.compile(
            r"\b(\d{1,2}(:\d{2})?\s*(am|pm)|\d+\s*(min|minutes|hour|hours|h)|sunset|flight|jewel|rain vortex|marina|gate)\b",
            flags=re.IGNORECASE,
        )
        for raw in text.splitlines():
            line = raw.strip()
            if not line:
                continue
            if line.startswith("{") or line.startswith("}") or line.endswith("{") or line.endswith("}"):
                continue
            if re.search(r'"\w+"\s*:', line):
                continue
            line = re.sub(r"^\s*[-*]\s*", "", line)
            line = re.sub(r"^\s*\d+[.)]\s*", "", line)
            line = re.sub(r"\*\*", "", line).strip()
            lowered = line.lower()
            if any(token in lowered for token in bad_tokens):
                continue
            if len(line) < 20 or len(line) > 180:
                continue
            if not signal_pattern.search(lowered):
                continue
            normalized = re.sub(r"\s+", " ", line)
            key = normalized.lower()
            if key in seen:
                continue
            seen.add(key)
            filtered.append(normalized)
            if len(filtered) >= 8:
                break
        return filtered

    @staticmethod
    def _looks_internal_reasoning(text: str) -> bool:
        lowered = (text or "").strip().lower()
        if not lowered:
            return False
        suspicious = (
            "the user says",
            "we need to",
            "let's count",
            "request_id",
            "json",
            "marker",
            "validation",
        )
        return any(token in lowered for token in suspicious)

    async def _retry_strict_format(
        self,
        request: PlannerQueryRequest,
        payload: dict[str, Any],
        prior_content: str,
    ) -> PlannerQueryResponse | None:
        """Single-shot retry asking the model to reformat prior output only."""
        retry_body = {
            "model": self.model,
            "stream": False,
            # Retry often needs extra room to include both markers and complete JSON.
            "max_tokens": min(self.max_tokens, 1300),
            "temperature": 0.0,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a strict JSON formatter. "
                        "Output exactly one JSON object between markers. "
                        "No reasoning, no markdown, no prose."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        "The previous planner output was invalid. Reformat this request into valid planner JSON.\n\n"
                        f"{build_user_message(payload)}\n\n"
                        f"Return ONLY one JSON object between {MARKER_BEGIN} and {MARKER_END}.\n"
                        "Required keys: request_id, status, planner_mode, spoken_response, confidence, result_type, planner_metadata.\n"
                        "If result_type is itinerary or hybrid, include display_response.\n"
                        "Echo request_id exactly.\n"
                        "No reasoning, no commentary, no markdown outside JSON."
                    ),
                },
            ],
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout_sec) as client:
                retry_response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers={
                        "authorization": f"Bearer {self.api_key}",
                        "content-type": "application/json",
                        "accept": "application/json",
                    },
                    json=retry_body,
                )
            if retry_response.status_code != 200:
                return None
            retry_json = retry_response.json()
            retry_content = retry_json["choices"][0]["message"]["content"]
            if not isinstance(retry_content, str):
                return None
            logger.debug(
                "DirectPlannerBackend retry content (request_id={}, len={}): {!r}",
                request.request_id,
                len(retry_content),
                retry_content[-2000:],
            )
            parsed = self._parse_marker_payload(request, retry_content)
            if parsed.error_code != "planner_invalid_response":
                return parsed
        except Exception as exc:
            logger.debug("DirectPlannerBackend retry failed for {}: {}", request.request_id, exc)
        return None

    @staticmethod
    def _build_invalid_response(request: PlannerQueryRequest, message: str) -> PlannerQueryResponse:
        return PlannerQueryResponse(
            request_id=request.request_id,
            status="error",
            error_code="planner_invalid_response",
            spoken_response="I can give a simpler suggestion now, but the planner response was incomplete.",
            display_response="Planner invalid response",
            confidence="low",
            result_type="recommendation",
            warnings=[{"code": "planner_invalid_response", "message": message[:500]}],
            planner_metadata={
                "used_tools": [],
                "used_live_data": False,
                "needs_followup": False,
                "route_class": "planner",
                "response_style": "voice_friendly",
            },
        )

    @staticmethod
    def _build_timeout_response(request: PlannerQueryRequest, message: str) -> PlannerQueryResponse:
        return PlannerQueryResponse(
            request_id=request.request_id,
            status="timeout",
            error_code="planner_model_timeout",
            spoken_response="I need a bit more time to plan that. Please try again in a moment.",
            display_response="Planner model timeout",
            confidence="low",
            result_type="recommendation",
            warnings=[{"code": "planner_model_timeout", "message": message[:500]}],
            planner_metadata={
                "used_tools": [],
                "used_live_data": False,
                "needs_followup": True,
                "route_class": "planner",
                "response_style": "voice_friendly",
            },
        )

    @staticmethod
    def _build_runtime_error_response(request: PlannerQueryRequest, message: str) -> PlannerQueryResponse:
        return PlannerQueryResponse(
            request_id=request.request_id,
            status="error",
            error_code="planner_runtime_error",
            spoken_response="Detailed planning ran into a runtime issue. Please try again in a moment.",
            display_response="Planner runtime error",
            confidence="low",
            result_type="recommendation",
            warnings=[{"code": "planner_runtime_error", "message": message[:500]}],
            planner_metadata={
                "used_tools": [],
                "used_live_data": False,
                "needs_followup": False,
                "route_class": "planner",
                "response_style": "voice_friendly",
            },
        )

    @staticmethod
    def _build_unavailable_response(request: PlannerQueryRequest, message: str) -> PlannerQueryResponse:
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
            warnings=[{"code": "planner_unavailable", "message": message[:500]}],
            planner_metadata={
                "used_tools": [],
                "used_live_data": False,
                "needs_followup": False,
                "route_class": "planner",
                "response_style": "voice_friendly",
            },
        )

    @staticmethod
    def _coerce_dict(value: Any) -> dict[str, Any]:
        return value if isinstance(value, dict) else {}
