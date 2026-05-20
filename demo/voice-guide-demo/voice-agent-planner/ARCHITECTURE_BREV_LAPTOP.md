# Voice Agent Architecture

This document explains how the software components fit together in the current working setup:

- browser runs on your laptop
- backend and TURN run on the Brev instance
- ASR, TTS, and LLM run on NVIDIA hosted endpoints

It is meant to answer:

- what runs where
- how WebRTC, TURN, Pipecat, ASR, TTS, LLM, and prompts interact
- what each config file is responsible for

## 1. Big Picture

At a high level, the system is split into four zones:

1. the laptop browser
2. the Brev instance
3. the TURN relay on Brev
4. NVIDIA hosted AI services

```text
                       +----------------------------------+
                       |        NVIDIA Hosted APIs        |
                       |----------------------------------|
                       | ASR  -> Parakeet streaming ASR   |
                       | TTS  -> Magpie TTS              |
                       | LLM  -> Nemotron 3 Nano         |
                       +----------------^-----------------+
                                        |
                                        | gRPC / HTTPS
                                        |
+--------------------+     SSH tunnel   |        +---------------------------+
|   Laptop Browser   |------------------+--------|       Brev Instance       |
|--------------------|                           |---------------------------|
| webrtc_ui in       |                           | voice_agent_webrtc        |
| Chrome             |                           | FastAPI + Pipecat         |
| microphone         |                           | /offer endpoint           |
| speaker            |                           | pipeline.py               |
+---------+----------+                           +-------------+-------------+
          |                                                      |
          | WebRTC media via TURN                                |
          v                                                      v
                   +--------------------------------------+
                   |        Coturn on Brev instance       |
                   |--------------------------------------|
                   | ICE / TURN relay for browser <-> app |
                   +--------------------------------------+
```

## 2. What Runs Where

### On your laptop

- Chrome
- the `webrtc_ui` frontend loaded at `http://localhost:5173`
- microphone capture
- audio playback
- the browser's built-in WebRTC engine

### On the Brev instance

- `voice_agent_webrtc/pipeline.py`
- FastAPI `/offer` endpoint
- Pipecat pipeline runtime
- Coturn Docker container
- Vite dev server for the UI

### On NVIDIA hosted infrastructure

- Parakeet ASR
- Magpie TTS
- Nemotron-3-Nano LLM

This is why the Brev instance can stay CPU-only: it orchestrates audio and text flow, but model inference is remote.

## 3. Why The Browser Is On The Laptop

The browser is the real WebRTC client. It owns:

- microphone permission
- mic audio capture
- local WebRTC peer connection
- speaker playback

The Brev instance does not need a browser. It only needs to expose:

- the HTTP signaling endpoint `/offer`
- a TURN relay

## 4. Why SSH Tunnel Alone Was Not Enough

The SSH tunnel solved the HTTP path:

```text
Laptop browser  --->  localhost:7860  --->  SSH tunnel  --->  Brev :7860
```

That was enough for signaling, but not enough for media.

WebRTC media needs ICE candidate connectivity. In this topology, the browser and backend are on different networks, so TURN was needed.

Without TURN:

```text
Browser ---- POST /offer ----> backend         works
Browser ---- actual media ----> backend        fails
```

With TURN:

```text
Browser ---- POST /offer ----> backend         works
Browser ---- media via TURN ---> Coturn <--- backend
```

## 5. Layered View

Here is the stack from top to bottom.

```text
Application layer
  - persona / prompting
  - turn-taking
  - transcripts
  - TTS voice selection

AI services layer
  - ASR (speech -> text)
  - LLM (text -> text)
  - TTS (text -> speech)

Pipeline/orchestration layer
  - Pipecat pipeline
  - NvidiaRTVIInput
  - context aggregation
  - transcript synchronization

Transport layer
  - FastAPI /offer signaling
  - SmallWebRTCConnection
  - SmallWebRTCTransport
  - Coturn relay

Client/device layer
  - browser mic
  - browser speaker
  - Chrome WebRTC engine
```

## 6. Startup Sequence

When you run the system, the order looks like this:

```text
1. Start backend on Brev
   uv run pipeline.py

2. Start UI dev server on Brev
   npm run dev -- --host 0.0.0.0

3. Open laptop browser at http://localhost:5173

4. Browser loads webrtc_ui

5. UI POSTs SDP offer to http://localhost:7860/offer
   through the SSH tunnel

6. Backend creates SmallWebRTCConnection

7. Browser and backend gather ICE candidates

8. Browser and backend use Coturn when direct path is not enough

9. Once connected, Pipecat starts audio/text processing
```

## 7. Request And Media Flow

This is the end-to-end runtime flow for one conversation.

```text
User speaks into laptop mic
  |
  v
Browser WebRTC peer connection
  |
  v
TURN / ICE connectivity
  |
  v
SmallWebRTCTransport input on Brev
  |
  v
NemotronASRService
  |
  v
Transcript + context aggregation
  |
  v
NvidiaLLMService
  |
  v
NemotronTTSService
  |
  v
SmallWebRTCTransport output
  |
  v
Browser receives audio
  |
  v
User hears response
```

## 8. What `pipeline.py` Actually Does

The backend performs three main jobs:

1. create the WebRTC connection
2. build the speech pipeline
3. connect the pipeline to NVIDIA hosted services

### 8.1 ICE/TURN setup

`pipeline.py` reads TURN settings from the environment and builds `ice_servers`:

- `TURN_SERVER_URL`
- `TURN_USERNAME`
- `TURN_PASSWORD`

That list is passed into `SmallWebRTCConnection(...)`.

Conceptually:

```text
.env ---> ice_servers ---> SmallWebRTCConnection ---> WebRTC answer
```

### 8.2 `/offer` endpoint

The frontend sends an SDP offer to `/offer`.

The backend:

- creates or reuses `SmallWebRTCConnection`
- initializes it with the browser's SDP
- returns an SDP answer
- launches `run_bot(...)`

ASCII view:

```text
Browser
  |
  | POST /offer { sdp, type }
  v
FastAPI /offer
  |
  +--> SmallWebRTCConnection.initialize(...)
  |
  +--> asyncio.create_task(run_bot(...))
  |
  +--> return SDP answer
```

### 8.3 Pipecat runtime graph

Inside `run_bot(...)`, the pipeline is assembled in this order:

```text
transport.input()
  -> NvidiaRTVIInput
  -> NemotronASRService
  -> UserTranscriptSynchronization
  -> context_aggregator.user()
  -> NvidiaLLMService
  -> NemotronTTSService
  -> NvidiaTTSResponseCacher
  -> BotTranscriptSynchronization
  -> transport.output()
  -> context_aggregator.assistant()
```

This is the core runtime graph of the app.

## 9. What Pipecat Is Doing For You

Pipecat is the orchestration layer. It is not the ASR model, TTS model, or LLM itself.

Its job here is to:

- accept audio from the WebRTC transport
- feed audio into ASR
- maintain chat context
- call the LLM
- send LLM output into TTS
- stream audio back to the browser
- handle interruptions and transcript synchronization

You can think of Pipecat as the "conductor" of the conversation.

```text
Pipecat does not decide the answer quality by itself.
Pipecat decides how data moves between components.
```

## 10. What The NVIDIA Services Are

In the current setup, there are three distinct hosted AI services.

### ASR

Configured by:

- `ASR_SERVER_URL`
- `ASR_CLOUD_FUNCTION_ID`
- `ASR_MODEL_NAME`

Job:

- convert incoming user speech into text

Current hosted endpoint:

- `grpc.nvcf.nvidia.com:443`

### TTS

Configured by:

- `TTS_SERVER_URL`
- `TTS_VOICE_ID`
- `TTS_MODEL_NAME`
- `TTS_LANGUAGE`

Job:

- convert assistant text into audio

Current voice:

- `Magpie-Multilingual.EN-US.Aria`

### LLM

Configured by:

- `NVIDIA_LLM_URL`
- `NVIDIA_LLM_MODEL`

Job:

- generate the assistant's text response

Current hosted model:

- `nvidia/nemotron-3-nano-30b-a3b`

## 11. What `prompt.yaml` Does

`prompt.yaml` is the persona and behavior catalog.

It does not do inference by itself. It tells the LLM:

- how to behave
- what role/persona to adopt
- formatting rules
- special modes like multilingual or emotion-aware output

Current selector in `.env`:

```text
SYSTEM_PROMPT_SELECTOR=nemotron-3-nano/generic_voice_assistant
```

That means:

- use the `nemotron-3-nano` section in `prompt.yaml`
- choose the `generic_voice_assistant` prompt entry

Conceptually:

```text
prompt.yaml
  |
  +--> selector from .env
  |
  +--> resolved messages list
  |
  +--> LLMContext
  |
  +--> sent into NvidiaLLMService
```

## 12. Why The Bot Invented `NAME1`

The current prompt tells the model to be helpful, but it does not define a bot name.

So when the framework asked the bot to introduce itself, the LLM invented one.

That is why you saw:

- `NAME1`

instead of:

- `Aria`

Important distinction:

- `Aria` is the TTS voice identity
- `NAME1` came from the LLM text output

If you want the assistant identity to be `Aria`, that must be stated explicitly in `prompt.yaml`.

## 13. Why You See `Aria.Neutral`, `Aria.Angry`, `Aria.Fearful`

Those are TTS expression variants or voice styles.

They do not mean the system is reading your actual emotional state from the microphone.

In this repo, emotion-aware behavior is mainly driven by:

- prompt rules
- LLM output format
- TTS emotion switching

So the model can decide:

```text
Respond in a calm voice
Respond in a sad voice
Respond in a neutral voice
```

But that is different from:

```text
The system detected your real emotional state biometrically
```

## 14. File Responsibilities

Here is the simplest way to think about the main files:

```text
webrtc_ui/src/config.ts
  - browser-side TURN config
  - browser-side /offer URL

voice_agent_webrtc/.env
  - runtime configuration
  - model selection
  - TURN credentials
  - voice selection
  - prompt selector

voice_agent_webrtc/pipeline.py
  - FastAPI app
  - WebRTC connection setup
  - Pipecat pipeline assembly
  - hosted ASR/TTS/LLM client setup

voice_agent_webrtc/prompt.yaml
  - persona catalog
  - behavior rules
  - prompt variants and modes

src/nvidia_pipecat/...
  - SDK implementation details
  - service wrappers
  - processors
  - frame types
```

## 15. Topology-Specific Notes For Your Setup

This exact topology matters:

```text
Laptop browser
    |
    | HTTP signaling over SSH tunnel
    v
Brev backend
    |
    | TURN / ICE relay
    v
Coturn on Brev
    |
    | HTTPS / gRPC
    v
NVIDIA hosted services
```

Key consequence:

- browser UI can stay on the laptop
- Brev does not need a browser
- TURN must still be reachable publicly
- hosted AI endpoints keep the instance CPU-friendly

## 16. Mental Model

If you want one sentence for each component:

```text
Browser:
  captures and plays audio

webrtc_ui:
  starts the session and shows transcripts/controls

FastAPI /offer:
  exchanges WebRTC offers and answers

Coturn:
  helps media packets get through NAT/firewall boundaries

SmallWebRTCTransport:
  bridges WebRTC media into the Pipecat pipeline

NemotronASRService:
  turns speech into text

NvidiaLLMService:
  decides what the assistant says

NemotronTTSService:
  turns assistant text into speech

prompt.yaml:
  defines the assistant's rules and persona
```

## 17. End-To-End Summary

The architecture is not "one model talking directly to the browser."

It is a chain:

```text
Browser audio
  -> WebRTC transport
  -> Pipecat orchestration
  -> Hosted ASR
  -> Hosted LLM
  -> Hosted TTS
  -> WebRTC transport
  -> Browser audio
```

And for your Brev topology, TURN is the networking glue that allows the browser and backend to exchange media successfully across machine boundaries.
