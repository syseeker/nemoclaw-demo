"""Three-path orchestrator for the Jewel voice-guide demo."""

from __future__ import annotations

import asyncio
import json
import re
import time
import uuid
from dataclasses import dataclass
from typing import Any

from loguru import logger
from pipecat.frames.frames import (
    Frame,
    InterruptionFrame,
    LLMContextFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    LLMMessagesUpdateFrame,
    LLMTextFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
)
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.frame_processor import FrameDirection
from pipecat.processors.frameworks.rtvi import RTVIServerMessageFrame
from rapidfuzz.distance import Levenshtein

from apps.jewel_voice_guide.lookup import JewelKnowledgeIndex
from apps.jewel_voice_guide.planner_backends.base import PlannerBackend
from apps.jewel_voice_guide.planner_backends.router import should_escalate_to_openclaw
from apps.jewel_voice_guide.planner_bridge import PlannerQueryRequest, PlannerQueryResponse
from apps.jewel_voice_guide.router import CROSS_DESTINATION_TERMS, RouteDecision, route_turn
from nvidia_pipecat.services.nvidia_llm import NvidiaLLMService

PLANNER_DEBOUNCE_SECONDS = 0.75
PLANNER_HEALTH_TTL_SECONDS = 5.0
REENGAGE_DELAY_SECONDS = 1.8
PHOTO_REQUEST_RESPONSE = (
    "I can't show photos in this voice view, but I can describe the store or guide you there."
)
REENGAGE_RESPONSE = "I'm here whenever you're ready. What would you like help with at Jewel?"
PLANNER_PROGRESS_ACK = (
    "Let me put that together for you."
)
PLANNER_HEARTBEAT_FIRST_INTERVAL_SECONDS = 10.0
PLANNER_HEARTBEAT_INTERVAL_SECONDS = 18.0
PLANNER_HEARTBEAT_VOICE_CUES = (
    "Still working on it.",
    "Thanks for waiting.",
    "Almost there.",
)
PLANNER_REFER_PANEL_CUE = "Please refer to the Planner panel for the timetable and route details."


@dataclass(slots=True)
class PlannerTurnState:
    """Tracks planner execution state for a single evolving user utterance."""

    conversation_id: str
    session_id: str
    active_turn_id: int = 0
    latest_text: str = ""
    latest_context: LLMContext | None = None
    latest_reason: str = ""
    active_text: str | None = None
    active_request_id: str | None = None
    active_task: asyncio.Task | None = None
    debounce_task: asyncio.Task | None = None
    pending_text: str | None = None
    pending_context: LLMContext | None = None
    pending_reason: str | None = None
    last_result: PlannerQueryResponse | None = None
    last_spoken_text: str | None = None
    progress_task: asyncio.Task | None = None


class VoiceGuideOrchestratorService(NvidiaLLMService):
    """Routes direct and lookup speculatively, and planner with gated commits."""

    def __init__(
        self,
        *,
        knowledge_index: JewelKnowledgeIndex,
        planner_bridge: PlannerBackend,
        conversation_id: str,
        **kwargs,
    ):
        """Initialize the orchestrator with lookup and planner dependencies."""
        super().__init__(**kwargs)
        self._knowledge_index = knowledge_index
        self._planner_bridge = planner_bridge
        self._conversation_id = self._sanitize_conversation_id(conversation_id)
        self._user_speaking = False
        self._turn_id = 0
        self._planner_state: PlannerTurnState | None = None
        self._planner_health_cache: tuple[float, bool] | None = None
        self._silence_reprompt_task: asyncio.Task | None = None
        self._turn_has_meaningful_input = False

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        """Handle speculative direct/lookup and queued planner execution."""
        if isinstance(frame, UserStartedSpeakingFrame):
            await self._cancel_silence_reprompt()
            self._user_speaking = True
            self._turn_id += 1
            self._turn_has_meaningful_input = False
            await super().process_frame(frame, direction)
            return

        if isinstance(frame, UserStoppedSpeakingFrame):
            self._user_speaking = False
            self._schedule_silence_reprompt(self._turn_id)
            await super().process_frame(frame, direction)
            return

        if isinstance(frame, InterruptionFrame):
            await self._cancel_direct_task()
            await self._start_interruption()
            await self.stop_all_metrics()
            await self.push_frame(frame, direction)
            return

        context = None
        if isinstance(frame, LLMContextFrame):
            context = frame.context
        elif isinstance(frame, LLMMessagesUpdateFrame):
            context = LLMContext(messages=frame.messages)

        if context is not None:
            await self._handle_context(context)
            return

        await super().process_frame(frame, direction)

    async def _handle_context(self, context: LLMContext):
        messages = context.get_messages()
        raw_user_text = self._extract_last_user_text(messages)
        if not raw_user_text:
            await self._start_direct_generation(context)
            return

        system_state = await self._get_system_state()
        user_text = raw_user_text
        decision = route_turn(user_text, system_state)
        if self._should_llm_repair(user_text, decision):
            repaired_text = await self._repair_transcript_with_llm(user_text, messages, decision.route)
            if repaired_text != self._normalize_text(user_text):
                logger.info("Repaired ASR transcript raw={!r} repaired={!r}", raw_user_text, repaired_text)
            user_text = repaired_text
            decision = route_turn(user_text, system_state)

        if self._is_low_information_transcript(user_text):
            logger.info("Ignoring low-information transcript {!r}", user_text)
            return

        self._turn_has_meaningful_input = True
        await self._cancel_silence_reprompt()
        logger.info(
            "Voice guide route={} reason={} confidence={} user_text={!r} speaking={}",
            decision.route,
            decision.reason,
            decision.confidence,
            user_text,
            self._user_speaking,
        )

        if decision.route == "direct":
            await self._cancel_planner_for_current_turn()
            await self._start_direct_generation(context)
            return

        if decision.route == "lookup":
            await self._cancel_planner_for_current_turn()
            await self._start_lookup_generation(user_text, context)
            return

        await self._cancel_direct_task()
        await self._handle_planner_candidate(context, user_text, decision)

    async def _start_direct_generation(self, context: LLMContext):
        await self._cancel_direct_task()
        self._current_task = self.create_task(self._run_direct_generation(context))
        self._current_task.add_done_callback(lambda _: setattr(self, "_current_task", None))

    async def _run_direct_generation(self, context: LLMContext):
        await self.push_frame(LLMFullResponseStartFrame())
        try:
            await self.start_processing_metrics()
            await self._process_direct_context(context)
        finally:
            await self.stop_processing_metrics()
            await self.push_frame(LLMFullResponseEndFrame())

    async def _process_direct_context(self, context: LLMContext):
        await NvidiaLLMService._process_context(self, context)

    async def _start_lookup_generation(self, user_text: str, context: LLMContext):
        await self._cancel_direct_task()
        self._current_task = self.create_task(self._run_lookup_generation(user_text, context))
        self._current_task.add_done_callback(lambda _: setattr(self, "_current_task", None))

    async def _run_lookup_generation(self, user_text: str, context: LLMContext):
        if self._is_visual_request(user_text):
            await self._emit_text_response(PHOTO_REQUEST_RESPONSE)
            return

        lookup_result = self._knowledge_index.answer(user_text)
        if lookup_result is None:
            logger.warning("Lookup path had no grounded answer, falling back to direct")
            await self._run_direct_generation(context)
            return

        await self._emit_text_response(lookup_result.spoken_response)

    async def _handle_planner_candidate(self, context: LLMContext, user_text: str, decision: RouteDecision):
        state = self._ensure_planner_state()
        state.latest_text = user_text
        state.latest_context = context
        state.latest_reason = decision.reason

        if state.active_task is not None:
            relation = self._classify_planner_update(state.active_text or "", user_text)
            logger.info("Planner update relation={} active={!r} latest={!r}", relation, state.active_text, user_text)
            if relation == "equivalent":
                return
            if relation == "additive":
                state.pending_text = user_text
                state.pending_context = context
                state.pending_reason = decision.reason
                return

            await self._cancel_async_task(state.active_task)
            state.active_task = None
            state.active_text = None
            state.active_request_id = None

        if not self._user_speaking:
            await self._launch_planner(state, context, user_text, decision.reason)
            return

        if self._is_semantically_complete_planner(user_text, decision):
            self._schedule_planner_debounce(state)

    def _schedule_planner_debounce(self, state: PlannerTurnState):
        if state.debounce_task is not None and not state.debounce_task.done():
            return
        state.debounce_task = self.create_task(self._debounced_planner_launch(state.active_turn_id))
        state.debounce_task.add_done_callback(self._clear_debounce_task)

    def _clear_debounce_task(self, task: asyncio.Task):
        del task
        if self._planner_state is not None:
            self._planner_state.debounce_task = None

    async def _debounced_planner_launch(self, turn_id: int):
        await asyncio.sleep(PLANNER_DEBOUNCE_SECONDS)
        state = self._planner_state
        if state is None or state.active_turn_id != turn_id or state.active_task is not None:
            return
        if not state.latest_context or not state.latest_text:
            return

        system_state = await self._get_system_state()
        decision = route_turn(state.latest_text, system_state)
        if decision.route != "planner":
            return
        if self._user_speaking and not self._is_semantically_complete_planner(state.latest_text, decision):
            return

        await self._launch_planner(state, state.latest_context, state.latest_text, decision.reason)

    async def _launch_planner(
        self,
        state: PlannerTurnState,
        context: LLMContext,
        user_text: str,
        route_reason: str,
        prior_result: PlannerQueryResponse | None = None,
    ):
        state.active_text = user_text
        await self._start_planner_progress(state, user_text)
        wants_live_or_actions, matched_phrase = should_escalate_to_openclaw(user_text)
        if matched_phrase:
            logger.debug("Planner live/tool escalation matched phrase={!r}", matched_phrase)
        request = PlannerQueryRequest(
            request_id=f"req_{uuid.uuid4().hex[:12]}",
            session_id=state.session_id,
            user_text=user_text,
            route_reason=route_reason,
            session_context=self._build_session_context(context.get_messages(), prior_result),
            planner_options={
                "response_style": "voice_friendly",
                "max_steps": 5,
                "allow_live_data": wants_live_or_actions,
                "allow_tools": wants_live_or_actions,
            },
        )
        state.active_request_id = request.request_id
        state.pending_text = None
        state.pending_context = None
        state.pending_reason = None
        state.active_task = self.create_task(self._run_planner_generation(state.active_turn_id, request))
        state.active_task.add_done_callback(lambda _: self._clear_planner_active_task(state.active_turn_id))

    def _clear_planner_active_task(self, turn_id: int):
        if self._planner_state is not None and self._planner_state.active_turn_id == turn_id:
            self._planner_state.active_task = None

    async def _run_planner_generation(self, turn_id: int, request: PlannerQueryRequest):
        response = await self._planner_bridge.query(request)
        state = self._planner_state
        if state is None or state.active_turn_id != turn_id or state.active_request_id != request.request_id:
            return

        state.last_result = response
        state.active_text = None
        state.active_request_id = None
        await self._cancel_planner_progress(state)

        if state.pending_context is not None and state.pending_text is not None:
            pending_context = state.pending_context
            pending_text = state.pending_text
            pending_reason = state.pending_reason or request.route_reason
            state.pending_context = None
            state.pending_text = None
            state.pending_reason = None
            await self._launch_planner(
                state,
                pending_context,
                pending_text,
                pending_reason,
                prior_result=response,
            )
            return

        status_state = "done" if response.status == "ok" else "error"
        status_message = "Plan ready" if response.status == "ok" else "Planner fallback response"
        await self._emit_planner_status(status_state, status_message)
        await self._emit_planner_display(self._build_planner_display_payload(response))
        spoken_text = self._build_planner_spoken_payload(response.spoken_response)
        if spoken_text and spoken_text != state.last_spoken_text:
            await self._emit_text_response(spoken_text)
            state.last_spoken_text = spoken_text

    async def _emit_text_response(self, text: str):
        await self._cancel_silence_reprompt()
        await self.push_frame(LLMFullResponseStartFrame())
        try:
            await self.start_processing_metrics()
            await self.start_ttfb_metrics()
            await self.stop_ttfb_metrics()
            await self.push_frame(LLMTextFrame(text))
        finally:
            await self.stop_processing_metrics()
            await self.push_frame(LLMFullResponseEndFrame())

    async def _emit_planner_status(self, state: str, message: str):
        """Send planner progress state to the WebRTC UI data channel."""
        await self.push_frame(
            RTVIServerMessageFrame(
                data={
                    "type": "planner_status",
                    "state": state,
                    "message": message,
                }
            )
        )

    async def _emit_planner_display(self, markdown: str | None):
        """Send rich planner display text to the UI panel."""
        if not markdown:
            return
        await self.push_frame(
            RTVIServerMessageFrame(
                data={
                    "type": "planner_display",
                    "markdown": markdown,
                }
            )
        )

    @staticmethod
    def _build_planner_display_payload(response: PlannerQueryResponse) -> str:
        """Render planner panel as timetable + route/tasks/activities only."""
        timetable = VoiceGuideOrchestratorService._extract_timetable_rows(response)
        route_items = VoiceGuideOrchestratorService._extract_route_items(response)

        lines: list[str] = ["## Timetable"]
        if timetable:
            lines.extend(
                [
                    "| Time | Task |",
                    "| --- | --- |",
                    *[f"| {time_text} | {task_text} |" for time_text, task_text in timetable[:8]],
                ]
            )
        else:
            lines.append("- No timetable available yet.")

        lines.extend(["", "## Route / Tasks / Activities"])
        if route_items:
            lines.extend([f"- {item}" for item in route_items[:10]])
        else:
            lines.append("- No route/tasks/activities available yet.")

        return "\n".join(lines)

    @staticmethod
    def _build_planner_spoken_payload(spoken_response: str | None) -> str:
        base = (spoken_response or "").strip()
        if not base:
            return PLANNER_REFER_PANEL_CUE
        lowered = base.lower()
        already_refs_panel = "planner" in lowered and ("refer" in lowered or "look" in lowered)
        if already_refs_panel:
            return base
        return f"{base} {PLANNER_REFER_PANEL_CUE}"

    @staticmethod
    def _extract_timetable_rows(response: PlannerQueryResponse) -> list[tuple[str, str]]:
        rows: list[tuple[str, str]] = []
        seen: set[tuple[str, str]] = set()

        for node in VoiceGuideOrchestratorService._iter_dict_nodes(
            [response.itinerary, {"recommendations": response.recommendations}]
        ):
            time_text = VoiceGuideOrchestratorService._pick_string(
                node,
                "time",
                "time_slot",
                "time_range",
                "start_time",
                "end_time",
                "when",
                "eta",
            )
            task_text = VoiceGuideOrchestratorService._pick_string(
                node,
                "task",
                "activity",
                "title",
                "name",
                "summary",
                "description",
                "location",
                "place",
                "stop",
            )
            if not time_text or not task_text:
                continue
            pair = (time_text.strip(), task_text.strip())
            if pair in seen:
                continue
            seen.add(pair)
            rows.append(pair)
        if rows:
            return rows

        # Fallback: parse model-authored markdown text when structured itinerary is absent.
        for raw_line in (response.display_response or "").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            line = re.sub(r"^\s*[-*]\s*", "", line)
            line = re.sub(r"^\s*\d+[.)]\s*", "", line)
            line = re.sub(r"\*\*", "", line).strip()
            match = re.match(r"^(?P<time>[^:]{2,40}):\s*(?P<task>.+)$", line)
            if not match:
                continue
            time_text = match.group("time").strip()
            task_text = match.group("task").strip()
            pair = (time_text, task_text)
            if pair in seen:
                continue
            seen.add(pair)
            rows.append(pair)
        return rows

    @staticmethod
    def _extract_route_items(response: PlannerQueryResponse) -> list[str]:
        items: list[str] = []
        seen: set[str] = set()

        for node in VoiceGuideOrchestratorService._iter_dict_nodes(
            [response.itinerary, {"recommendations": response.recommendations}]
        ):
            direct_value = VoiceGuideOrchestratorService._pick_string(
                node,
                "route",
                "task",
                "activity",
                "step",
                "instruction",
                "action",
            )
            if direct_value:
                normalized = direct_value.strip()
                if normalized and normalized.lower() not in seen:
                    seen.add(normalized.lower())
                    items.append(normalized)

            for list_key in ("routes", "tasks", "activities", "steps", "stops"):
                list_value = node.get(list_key)
                if not isinstance(list_value, list):
                    continue
                for entry in list_value:
                    if isinstance(entry, str):
                        normalized = entry.strip()
                    elif isinstance(entry, dict):
                        normalized = VoiceGuideOrchestratorService._pick_string(
                            entry,
                            "task",
                            "activity",
                            "title",
                            "name",
                            "summary",
                            "description",
                            "location",
                            "place",
                            "instruction",
                            "action",
                        ).strip()
                    else:
                        normalized = ""
                    if normalized and normalized.lower() not in seen:
                        seen.add(normalized.lower())
                        items.append(normalized)
        if items:
            return items

        # Fallback: use display markdown bullet/numbered lines as route/task/activity items.
        for raw_line in (response.display_response or "").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith("#"):
                continue
            line = re.sub(r"^\s*[-*]\s*", "", line)
            line = re.sub(r"^\s*\d+[.)]\s*", "", line)
            line = re.sub(r"\*\*", "", line).strip()
            if not line:
                continue
            if line.lower().startswith("jewel ") and "plan" in line.lower():
                continue
            if line.lower() not in seen:
                seen.add(line.lower())
                items.append(line)
        return items

    @staticmethod
    def _iter_dict_nodes(root: Any) -> list[dict[str, Any]]:
        nodes: list[dict[str, Any]] = []
        stack: list[Any] = [root]
        while stack:
            current = stack.pop()
            if isinstance(current, dict):
                nodes.append(current)
                stack.extend(current.values())
            elif isinstance(current, list):
                stack.extend(current)
        return nodes

    @staticmethod
    def _pick_string(source: dict[str, Any], *keys: str) -> str:
        for key in keys:
            value = source.get(key)
            if isinstance(value, str) and value.strip():
                return value
        return ""

    async def _start_planner_progress(self, state: PlannerTurnState, user_text: str):
        await self._cancel_planner_progress(state)
        extended, phrase = should_escalate_to_openclaw(user_text)
        logger.debug(
            "Planner progress task starting (extended={} matched_phrase={!r})",
            extended,
            phrase,
        )
        state.progress_task = self.create_task(self._run_planner_progress(state.active_turn_id, True))
        state.progress_task.add_done_callback(lambda _: self._clear_planner_progress_task(state.active_turn_id))

    def _clear_planner_progress_task(self, turn_id: int):
        if self._planner_state is not None and self._planner_state.active_turn_id == turn_id:
            self._planner_state.progress_task = None

    async def _cancel_planner_progress(self, state: PlannerTurnState):
        if state.progress_task is None or state.progress_task.done():
            state.progress_task = None
            return
        state.progress_task.cancel()
        try:
            await state.progress_task
        except asyncio.CancelledError:
            pass
        state.progress_task = None

    async def _run_planner_progress(self, turn_id: int, extended: bool):
        await self._emit_planner_status("working", "Planning your answer...")
        if not self._user_speaking:
            await self._emit_text_response(PLANNER_PROGRESS_ACK)
        if not extended:
            return

        heartbeat_index = 0
        while True:
            delay = (
                PLANNER_HEARTBEAT_FIRST_INTERVAL_SECONDS
                if heartbeat_index == 0
                else PLANNER_HEARTBEAT_INTERVAL_SECONDS
            )
            await asyncio.sleep(delay)
            state = self._planner_state
            if state is None or state.active_turn_id != turn_id or state.active_task is None:
                return
            ui_message = "Still refining the plan..." if heartbeat_index >= 2 else "Still working on it..."
            await self._emit_planner_status("working", ui_message)
            if not self._user_speaking:
                voice_cue = PLANNER_HEARTBEAT_VOICE_CUES[heartbeat_index % len(PLANNER_HEARTBEAT_VOICE_CUES)]
                await self._emit_text_response(voice_cue)
            heartbeat_index += 1

    async def _cancel_direct_task(self):
        if self._current_task is not None and not self._current_task.done():
            await self.cancel_task(self._current_task)
        self._current_task = None

    async def _cancel_planner_for_current_turn(self):
        state = self._planner_state
        if state is None:
            return
        if state.debounce_task is not None and not state.debounce_task.done():
            state.debounce_task.cancel()
        await self._cancel_planner_progress(state)
        if state.active_task is not None and not state.active_task.done():
            await self._cancel_async_task(state.active_task)
        state.active_task = None
        state.active_request_id = None
        state.active_text = None
        state.pending_text = None
        state.pending_context = None
        state.pending_reason = None

    async def _cancel_async_task(self, task: asyncio.Task):
        if task.done():
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            return

    def _ensure_planner_state(self) -> PlannerTurnState:
        if self._planner_state is None:
            self._planner_state = PlannerTurnState(
                conversation_id=self._conversation_id,
                session_id=f"planner-{self._conversation_id}",
            )
        self._planner_state.active_turn_id = self._turn_id
        return self._planner_state

    async def terminate_conversation(self) -> None:
        """Cancel planner work and destroy the dedicated planner session."""
        await self._cancel_direct_task()
        await self._cancel_silence_reprompt()
        state = self._planner_state
        if state is None:
            return
        if state.debounce_task is not None and not state.debounce_task.done():
            state.debounce_task.cancel()
        await self._cancel_planner_progress(state)
        if state.active_task is not None and not state.active_task.done():
            await self._cancel_async_task(state.active_task)
        await self._planner_bridge.cleanup_session(state.session_id)
        self._planner_state = None

    async def _get_system_state(self) -> dict[str, bool]:
        now = time.monotonic()
        if self._planner_health_cache is not None and now - self._planner_health_cache[0] < PLANNER_HEALTH_TTL_SECONDS:
            planner_available = self._planner_health_cache[1]
        else:
            planner_health = await self._planner_bridge.health()
            planner_available = planner_health.planner_available
            self._planner_health_cache = (now, planner_available)

        return {
            "planner_available": planner_available,
            "lookup_available": self._knowledge_index.available,
        }

    def _is_semantically_complete_planner(self, user_text: str, decision: RouteDecision) -> bool:
        text = self._normalize_text(user_text)
        if decision.confidence != "high":
            return False
        if len(text.split()) < 8:
            return False

        multi_destination = "jewel" in text and any(term in text for term in CROSS_DESTINATION_TERMS)
        temporal = bool(re.search(r"\b\d+\s*(am|pm|hours?|minutes?)\b", text)) or "land at" in text
        sequencing = any(f" {word} " in f" {text} " for word in ("then", "after", "before"))
        signals = sum([multi_destination, temporal, sequencing])
        return signals >= 2

    def _classify_planner_update(self, old_text: str, new_text: str) -> str:
        old_norm = self._normalize_text(old_text)
        new_norm = self._normalize_text(new_text)
        if not old_norm or old_norm == new_norm:
            return "equivalent"
        if old_norm.startswith(new_norm):
            return "equivalent"
        if new_norm.startswith(old_norm):
            return "additive"

        similarity = 1 - Levenshtein.normalized_distance(old_norm, new_norm)
        if similarity >= 0.92:
            return "equivalent"

        old_tokens = set(old_norm.split())
        new_tokens = set(new_norm.split())
        if old_tokens and old_tokens.issubset(new_tokens):
            return "additive"

        return "corrective"

    def _normalize_text(self, text: str) -> str:
        return re.sub(r"\s+", " ", text.strip().lower())

    def _is_low_information_transcript(self, text: str) -> bool:
        normalized = self._normalize_text(text)
        if not normalized:
            return True

        tokens = normalized.split()
        filler_tokens = {"he", "eh", "uh", "um", "ah", "hm", "hmm", "mm"}
        return len(tokens) == 1 and (tokens[0] in filler_tokens or len(tokens[0]) <= 2)

    def _should_llm_repair(self, text: str, decision: RouteDecision) -> bool:
        normalized = self._normalize_text(text)
        return (
            len(normalized.split()) >= 4
            and (
                decision.route in {"lookup", "planner"}
                or any(term in normalized for term in ("rain vortex", "jewel", "marina bay"))
            )
        )

    async def _repair_transcript_with_llm(
        self,
        text: str,
        messages: list[dict[str, Any]],
        route_hint: str,
    ) -> str:
        normalized = self._normalize_text(text)
        recent_turns = []
        for message in messages[-4:]:
            content = message.get("content", "")
            role = message.get("role")
            if isinstance(content, str) and role in {"user", "assistant"}:
                recent_turns.append(f"{role}: {content}")

        prompt_messages = [
            {
                "role": "system",
                "content": (
                    "You repair speech-to-text transcripts for a Jewel Singapore voice guide. "
                    "Correct only likely ASR mistakes. Preserve intent, places, times, and ordering. "
                    "Do not invent new constraints or locations. If uncertain, keep the original wording. "
                    'Return strict JSON: {"normalized_text":"..."} and nothing else.'
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Route hint: {route_hint}\n"
                    f"Recent turns:\n" + "\n".join(recent_turns) + "\n\n"
                    f"Raw transcript:\n{text}"
                ),
            },
        ]
        try:
            response = await self._client.chat.completions.create(
                model=self.model_name,
                messages=prompt_messages,
                temperature=0,
                max_tokens=120,
            )
            content = (response.choices[0].message.content or "").strip()
            repaired = self._extract_repaired_text(content)
            return repaired or normalized
        except Exception as exc:
            logger.warning(f"Transcript repair failed, using raw transcript: {exc}")
            return normalized

    def _extract_repaired_text(self, content: str) -> str:
        try:
            payload = json.loads(content)
            repaired = payload.get("normalized_text", "")
            if isinstance(repaired, str) and repaired.strip():
                return self._normalize_text(repaired)
        except json.JSONDecodeError:
            pass

        match = re.search(r'"normalized_text"\s*:\s*"([^"]+)"', content)
        if match:
            return self._normalize_text(match.group(1))

        stripped = content.strip().strip('"')
        if stripped and "\n" not in stripped and len(stripped.split()) >= 2:
            return self._normalize_text(stripped)
        return ""

    def _is_visual_request(self, text: str) -> bool:
        normalized = self._normalize_text(text)
        return any(term in normalized for term in ("photo", "picture", "image", "show me"))

    def _schedule_silence_reprompt(self, turn_id: int):
        if self._silence_reprompt_task is not None and not self._silence_reprompt_task.done():
            self._silence_reprompt_task.cancel()
        self._silence_reprompt_task = self.create_task(self._run_silence_reprompt(turn_id))
        self._silence_reprompt_task.add_done_callback(lambda _: setattr(self, "_silence_reprompt_task", None))

    async def _run_silence_reprompt(self, turn_id: int):
        await asyncio.sleep(REENGAGE_DELAY_SECONDS)
        if self._turn_id != turn_id or self._user_speaking or self._turn_has_meaningful_input:
            return
        await self._emit_text_response(REENGAGE_RESPONSE)

    async def _cancel_silence_reprompt(self):
        if self._silence_reprompt_task is not None and not self._silence_reprompt_task.done():
            self._silence_reprompt_task.cancel()
            try:
                await self._silence_reprompt_task
            except asyncio.CancelledError:
                return

    def _extract_last_user_text(self, messages: list[dict[str, Any]]) -> str:
        for message in reversed(messages):
            if message.get("role") == "user":
                content = message.get("content", "")
                if isinstance(content, str):
                    return content.strip()
        return ""

    def _build_session_context(
        self,
        messages: list[dict[str, Any]],
        prior_result: PlannerQueryResponse | None = None,
    ) -> dict[str, Any]:
        recent_turns = []
        for message in messages[-6:]:
            content = message.get("content", "")
            if isinstance(content, str) and message.get("role") in {"user", "assistant"}:
                recent_turns.append({"role": message["role"], "text": content})

        session_context = {
            "current_location": "Jewel Singapore",
            "prior_turns": recent_turns,
        }
        if prior_result is not None:
            session_context["prior_planner_result"] = prior_result.model_dump(exclude_none=True)
        return session_context

    def _sanitize_conversation_id(self, value: str) -> str:
        normalized = re.sub(r"[^a-zA-Z0-9_-]+", "-", value).strip("-").lower()
        return normalized or uuid.uuid4().hex[:12]
