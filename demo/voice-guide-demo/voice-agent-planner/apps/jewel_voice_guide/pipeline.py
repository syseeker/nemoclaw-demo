# SPDX-FileCopyrightText: Copyright (c) 2024-2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: BSD 2-Clause License

"""Jewel voice-guide pipeline application."""

import argparse
import asyncio
import json
import os
import sys
import uuid
from enum import Enum
from pathlib import Path

import uvicorn
import yaml
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.frames.frames import (
    InputAudioRawFrame,
    TTSAudioRawFrame,
)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.frameworks.rtvi import RTVIServerMessageFrame
from pipecat.services.openai.base_llm import BaseOpenAILLMService
from pipecat.transports.base_transport import TransportParams
from pipecat.transports.smallwebrtc.connection import (
    IceServer,
    SmallWebRTCConnection,
)
from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport

APP_DIR = Path(__file__).resolve().parent
REPO_ROOT = APP_DIR.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from apps.jewel_voice_guide.lookup import JewelKnowledgeIndex  # noqa: E402
from apps.jewel_voice_guide.orchestrator import VoiceGuideOrchestratorService  # noqa: E402
from apps.jewel_voice_guide.planner_backends.router import (  # noqa: E402
    PlannerBackendMode,
    PlannerBackendRouter,
)
from apps.jewel_voice_guide.planner_bridge import (  # noqa: E402
    PlannerHealthResponse,
    PlannerQueryRequest,
)
from nvidia_pipecat.frames.riva import RivaFetchVoicesFrame  # noqa: E402
from nvidia_pipecat.processors.audio_util import AudioRecorder  # noqa: E402
from nvidia_pipecat.processors.nvidia_context_aggregator import (  # noqa: E402
    NvidiaTTSResponseCacher,
    create_nvidia_context_aggregator,
)
from nvidia_pipecat.processors.nvidia_rtvi import NvidiaRTVIInput, NvidiaRTVIObserver  # noqa: E402
from nvidia_pipecat.processors.transcript_synchronization import (  # noqa: E402
    BotTranscriptSynchronization,
    UserTranscriptSynchronization,
)
from nvidia_pipecat.services.riva_speech import NemotronASRService, NemotronTTSService  # noqa: E402
from nvidia_pipecat.utils.riva_text_filter import RivaTextFilter  # noqa: E402

VOICE_AGENT_WEBRTC_DIR = REPO_ROOT / "voice_agent_webrtc"
USER_CONFIG_DIR = Path(os.getenv("XDG_CONFIG_HOME", Path.home() / ".config"))
USER_ENV_FILE = USER_CONFIG_DIR / "nemoclaw-voice-agent" / "voice-agent.env"
DEMO_ENV_FILE = REPO_ROOT.parent / "voice-agent.env"

# Load the demo-level environment explicitly so the pipeline behaves the same
# regardless of the directory or process manager used to start it.
load_dotenv(USER_ENV_FILE, override=False)
load_dotenv(DEMO_ENV_FILE, override=False)
load_dotenv(VOICE_AGENT_WEBRTC_DIR / ".env", override=False)
load_dotenv(override=False)

def _resolve_config_path(raw_value: str | None, base_dir: Path, default_path: Path) -> Path:
    if not raw_value:
        return default_path
    candidate = Path(raw_value)
    return candidate if candidate.is_absolute() else (base_dir / candidate).resolve()


PROMPT_FILE = _resolve_config_path(
    os.getenv("PROMPT_FILE_PATH"),
    APP_DIR,
    APP_DIR / "prompt.yaml",
)
JEWEL_DATA_FILE = _resolve_config_path(
    os.getenv("JEWEL_DATA_PATH"),
    APP_DIR,
    APP_DIR / "jewel_knowledge.json",
)
IPA_FILE = _resolve_config_path(
    os.getenv("TTS_IPA_FILE_PATH"),
    VOICE_AGENT_WEBRTC_DIR,
    VOICE_AGENT_WEBRTC_DIR / "ipa.json",
)
MULTILINGUAL_MODE = os.getenv("ENABLE_MULTILINGUAL", "false").lower() == "true"


class VADProfile(Enum):
    """VAD Profile options."""

    SILERO = "Silero"
    ASR = "ASR"


VAD_PROFILE = VADProfile(os.getenv("VAD_PROFILE", VADProfile.ASR))


def _load_prompts() -> dict:
    if not PROMPT_FILE.exists():
        raise FileNotFoundError(f"Prompt catalog not found at {PROMPT_FILE}")
    try:
        data = yaml.safe_load(PROMPT_FILE.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid YAML in prompt catalog {PROMPT_FILE}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"Prompt catalog at {PROMPT_FILE} must be a mapping.")
    return data


PROMPTS = _load_prompts()


def _resolve_prompt(selector: str) -> list[dict[str, str]]:
    """Resolve a selector like 'model/prompt' into a list of messages."""
    try:
        entry = PROMPTS
        for part in selector.split("/"):
            entry = entry[part]
        return [{"role": m["role"], "content": m["content"]} for m in entry["messages"]]
    except (KeyError, TypeError) as exc:
        raise KeyError(f"Prompt '{selector}' not found or invalid: {exc}") from exc


def _resolve_prompt_with_fallback(selector: str, fallback: str) -> list[dict[str, str]]:
    """Resolve a prompt selector, falling back to the app default if needed."""
    try:
        return _resolve_prompt(selector)
    except KeyError:
        logger.warning(f"Prompt selector '{selector}' not found in {PROMPT_FILE}; falling back to '{fallback}'")
        return _resolve_prompt(fallback)


def _inject_prompt_variables(prompt: str, **variables) -> str:
    """Inject variables into prompt placeholders like {lang_codes}."""
    try:
        return prompt.format(**variables)
    except KeyError:
        return prompt


app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

pcs_map: dict[str, SmallWebRTCConnection] = {}
bot_tasks: dict[str, asyncio.Task] = {}
planner_backend = PlannerBackendRouter(mode=PlannerBackendMode.from_env())
planner_warmup_task: asyncio.Task | None = None
knowledge_index = JewelKnowledgeIndex(JEWEL_DATA_FILE)

ice_servers = (
    [
        IceServer(
            urls=os.getenv("TURN_SERVER_URL", ""),
            username=os.getenv("TURN_USERNAME", ""),
            credential=os.getenv("TURN_PASSWORD", ""),
        )
    ]
    if os.getenv("TURN_SERVER_URL")
    else []
)


async def run_bot(webrtc_connection):
    """Run the Jewel voice-guide bot over WebRTC."""
    _kickoff_planner_warmup()
    stream_id = uuid.uuid4()
    conversation_id = str(webrtc_connection.pc_id or stream_id)
    transport_params = TransportParams(
        audio_in_enabled=True,
        audio_in_sample_rate=16000,
        audio_out_sample_rate=22050,
        audio_out_enabled=True,
        audio_out_10ms_chunks=5,
        vad_analyzer=SileroVADAnalyzer() if VAD_PROFILE == VADProfile.SILERO else None,
    )

    transport = SmallWebRTCTransport(
        webrtc_connection=webrtc_connection,
        params=transport_params,
    )

    enable_thinking = {"true": True, "false": False}.get(os.getenv("ENABLE_THINKING", "").lower())

    try:
        temperature = float(os.getenv("TEMPERATURE", "1.0"))
    except ValueError:
        logger.warning("Invalid TEMPERATURE, falling back to default 1.0")
        temperature = 1.0

    try:
        top_p = float(os.getenv("TOP_P", "1.0"))
    except ValueError:
        logger.warning("Invalid TOP_P, falling back to default 1.0")
        top_p = 1.0

    try:
        max_tokens = int(os.getenv("MAX_TOKENS", "2048"))
    except ValueError:
        logger.warning("Invalid MAX_TOKENS, falling back to default 2048")
        max_tokens = 2048

    llm = VoiceGuideOrchestratorService(
        api_key=os.getenv("NVIDIA_API_KEY"),
        base_url=os.getenv("NVIDIA_LLM_URL", "https://integrate.api.nvidia.com/v1"),
        model=os.getenv("NVIDIA_LLM_MODEL", "nvidia/nemotron-3-nano-30b-a3b"),
        knowledge_index=knowledge_index,
        planner_bridge=planner_backend,
        conversation_id=conversation_id,
        params=BaseOpenAILLMService.InputParams(
            temperature=temperature,
            top_p=top_p,
            max_tokens=max_tokens,
            **(
                {"extra": {"extra_body": {"chat_template_kwargs": {"enable_thinking": enable_thinking}}}}
                if enable_thinking is not None
                else {}
            ),
        ),
    )

    stt_config = {
        "server": os.getenv("ASR_SERVER_URL", "grpc.nvcf.nvidia.com:443"),
        "api_key": os.getenv("NVIDIA_API_KEY"),
        "function_id": os.getenv("ASR_CLOUD_FUNCTION_ID", "1598d209-5e27-4d3c-8079-4751568b1081"),
        "language": os.getenv("ASR_LANGUAGE", "en-US"),
        "sample_rate": 16000,
        "generate_interruptions": VAD_PROFILE == VADProfile.ASR,
        "model": os.getenv("ASR_MODEL_NAME", "parakeet-1.1b-en-US-asr-streaming-silero-vad-sortformer"),
    }
    if MULTILINGUAL_MODE:
        stt_config.update(stop_history=900, stop_history_eou=900)

    stt = NemotronASRService(**stt_config)

    try:
        with IPA_FILE.open(encoding="utf-8") as handle:
            ipa_dict = json.load(handle)
    except FileNotFoundError as exc:
        logger.error(f"IPA dictionary file not found at {IPA_FILE}")
        raise FileNotFoundError(f"IPA dictionary file not found at {IPA_FILE}") from exc
    except json.JSONDecodeError as exc:
        logger.error(f"Invalid JSON in IPA dictionary file: {exc}")
        raise ValueError(f"Invalid JSON in IPA dictionary file: {exc}") from exc

    enable_riva_text_filter = (
        os.getenv("ENABLE_TTS_TEXT_FILTER", "true").lower() == "true"
        and os.getenv("TTS_LANGUAGE", "en-US") == "en-US"
        and os.getenv("ENABLE_MULTILINGUAL", "false").lower() == "false"
    )

    tts = NemotronTTSService(
        server=os.getenv("TTS_SERVER_URL", "grpc.nvcf.nvidia.com:443"),
        api_key=os.getenv("NVIDIA_API_KEY"),
        voice_id=os.getenv("TTS_VOICE_ID", "Magpie-Multilingual.EN-US.Aria"),
        model=os.getenv("TTS_MODEL_NAME", "magpie_tts_ensemble-Magpie-Multilingual"),
        language=os.getenv("TTS_LANGUAGE", "en-US"),
        sample_rate=22050,
        zero_shot_audio_prompt_file=(
            Path(os.getenv("ZERO_SHOT_AUDIO_PROMPT")) if os.getenv("ZERO_SHOT_AUDIO_PROMPT") else None
        ),
        custom_dictionary=ipa_dict,
        text_filters=[RivaTextFilter()] if enable_riva_text_filter else [],
    )

    enable_asr_audio_dump = os.getenv("ENABLE_ASR_AUDIO_DUMP", "false").lower() == "true"
    enable_tts_audio_dump = os.getenv("ENABLE_TTS_AUDIO_DUMP", "false").lower() == "true"

    asr_recorder = None
    tts_recorder = None

    if enable_asr_audio_dump or enable_tts_audio_dump:
        audio_dumps_dir = Path(os.getenv("AUDIO_DUMP_PATH", str(VOICE_AGENT_WEBRTC_DIR / "audio_dumps")))
        audio_dumps_dir.mkdir(parents=True, exist_ok=True)

        if enable_asr_audio_dump:
            asr_recorder = AudioRecorder(
                output_file=str(audio_dumps_dir / f"asr_recording_{stream_id}.wav"),
                frame_type=InputAudioRawFrame,
            )

        if enable_tts_audio_dump:
            tts_recorder = AudioRecorder(
                output_file=str(audio_dumps_dir / f"tts_recording_{stream_id}.wav"),
                frame_type=TTSAudioRawFrame,
            )

    stt_transcript_synchronization = UserTranscriptSynchronization()
    tts_transcript_synchronization = BotTranscriptSynchronization()

    def _validated_selector(raw_value: str | None, default: str) -> str:
        selector = (raw_value or "").strip() or default
        if "/" not in selector:
            raise ValueError("SYSTEM_PROMPT_SELECTOR must be in '<model>/<prompt>' format")
        return selector

    if MULTILINGUAL_MODE:
        fallback_selector = "llama-3.3-nemotron-super-49b-v1.5/jewel_multilingual_voice_guide"
        prompt_selector = _validated_selector(
            os.getenv("SYSTEM_PROMPT_SELECTOR"),
            fallback_selector,
        )
        lang_codes = ", ".join(tts.list_available_voices().keys())
        messages = _resolve_prompt_with_fallback(prompt_selector, fallback_selector)
        messages = [
            {"role": msg["role"], "content": _inject_prompt_variables(msg["content"], lang_codes=lang_codes)}
            for msg in messages
        ]
    else:
        fallback_selector = "nemotron-3-nano/jewel_voice_guide"
        prompt_selector = _validated_selector(
            os.getenv("SYSTEM_PROMPT_SELECTOR"),
            fallback_selector,
        )
        messages = _resolve_prompt_with_fallback(prompt_selector, fallback_selector)

    if not messages:
        raise ValueError(f"Resolved system prompt has no messages for selector: {prompt_selector}")

    context = LLMContext(messages)

    enable_speculative_speech = os.getenv("ENABLE_SPECULATIVE_SPEECH", "true").lower() == "true"
    try:
        chat_history_limit = int(os.getenv("CHAT_HISTORY_LIMIT", "20"))
    except ValueError:
        logger.warning("Invalid CHAT_HISTORY_LIMIT, falling back to default 20")
        chat_history_limit = 20

    preserve_prompt_messages = len(messages)

    if enable_speculative_speech:
        context_aggregator = create_nvidia_context_aggregator(
            context,
            send_interims=True,
            chat_history_limit=chat_history_limit,
            preserve_prompt_messages=preserve_prompt_messages,
        )
        tts_response_cacher = NvidiaTTSResponseCacher()
    else:
        context_aggregator = create_nvidia_context_aggregator(
            context,
            send_interims=False,
            chat_history_limit=chat_history_limit,
            preserve_prompt_messages=preserve_prompt_messages,
        )
        tts_response_cacher = None

    rtvi_input = NvidiaRTVIInput(
        transport=transport,
        context=context,
    )

    pipeline = Pipeline(
        [
            transport.input(),
            rtvi_input,
            *([asr_recorder] if asr_recorder else []),
            stt,
            stt_transcript_synchronization,
            context_aggregator.user(),
            llm,
            tts,
            *([tts_recorder] if tts_recorder else []),
            *([tts_response_cacher] if tts_response_cacher else []),
            tts_transcript_synchronization,
            transport.output(),
            context_aggregator.assistant(),
        ]
    )

    task = PipelineTask(
        pipeline,
        params=PipelineParams(
            allow_interruptions=True,
            enable_metrics=True,
            enable_usage_metrics=True,
            send_initial_empty_metrics=True,
            start_metadata={"stream_id": stream_id},
        ),
        observers=[NvidiaRTVIObserver(rtvi_input)],
    )

    @rtvi_input.event_handler("on_client_ready")
    async def on_client_ready(rtvi_input):
        try:
            await rtvi_input.set_bot_ready()
            await task.queue_frames(
                [
                    RivaFetchVoicesFrame(),
                    RTVIServerMessageFrame(
                        data={
                            "type": "system_prompt",
                            "prompts": messages,
                            "prompt": messages[0]["content"],
                        }
                    ),
                ]
            )
        except Exception as exc:
            logger.error(f"Error on client ready: {exc}")
            await rtvi_input.send_error(str(exc))

    runner = PipelineRunner(handle_sigint=False)
    try:
        await runner.run(task)
    finally:
        await llm.terminate_conversation()


async def _warmup_planner_backend():
    try:
        await planner_backend.warmup()
        logger.info("Planner backend warmup completed")
    except Exception as exc:
        logger.warning("Planner backend warmup failed: {}", exc)


def _kickoff_planner_warmup():
    global planner_warmup_task
    if planner_warmup_task is not None and not planner_warmup_task.done():
        return
    planner_warmup_task = asyncio.create_task(_warmup_planner_backend())


@app.get("/planner/health", response_model=PlannerHealthResponse)
async def planner_health():
    """Expose planner availability for local inspection and demo checks."""
    return await planner_backend.health()


@app.post("/planner/query")
async def planner_query(payload: PlannerQueryRequest):
    """Expose the text-first planner bridge contract."""
    response = await planner_backend.query(payload)
    return response.model_dump(exclude_none=True)


@app.post("/offer")
async def offer(request: Request):
    """Offer endpoint for handling voice agent connections."""
    request = await request.json()
    pc_id = request.get("pc_id")

    if pc_id and pc_id in pcs_map:
        pipecat_connection = pcs_map[pc_id]
        logger.info(f"Reusing existing connection for pc_id: {pc_id}")
        await pipecat_connection.renegotiate(sdp=request["sdp"], type=request["type"])
    else:
        pipecat_connection = SmallWebRTCConnection(ice_servers)
        await pipecat_connection.initialize(sdp=request["sdp"], type=request["type"])

        @pipecat_connection.event_handler("closed")
        async def handle_disconnected(webrtc_connection: SmallWebRTCConnection):
            pcs_map.pop(webrtc_connection.pc_id, None)
            bot_task = bot_tasks.pop(webrtc_connection.pc_id, None)
            if bot_task is not None and not bot_task.done():
                bot_task.cancel()

        bot_task = asyncio.create_task(run_bot(pipecat_connection))
        bot_tasks[pipecat_connection.pc_id] = bot_task

    answer = pipecat_connection.get_answer()
    pcs_map[answer["pc_id"]] = pipecat_connection
    return answer


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Jewel voice-guide WebRTC demo")
    parser.add_argument("--host", default="0.0.0.0", help="Host for HTTP server (default: localhost)")
    parser.add_argument("--port", type=int, default=7860, help="Port for HTTP server (default: 7860)")
    parser.add_argument("--verbose", "-v", action="count")
    args = parser.parse_args()

    logger.remove(0)
    logger.add(sys.stderr, level="TRACE" if args.verbose else "DEBUG")
    uvicorn.run(app, host=args.host, port=args.port)
