# Voice Agent WebRTC Setup Guide

This document captures a working setup for the NVIDIA `voice_agent_webrtc` example using:

- a laptop browser for the UI
- a remote Brev instance for the backend and UI dev server
- NVIDIA hosted endpoints for ASR, TTS, and LLM
- Coturn on the Brev instance for WebRTC relay

This guide is tailored to the current project layout:

- `/home/ubuntu/voice-agent/voice_agent_webrtc`
- `/home/ubuntu/voice-agent/webrtc_ui`

## 1. What This Setup Uses

The working stack is:

- frontend: Vite app in `webrtc_ui`
- backend: FastAPI + Pipecat in `voice_agent_webrtc`
- ASR: NVIDIA hosted endpoint at `grpc.nvcf.nvidia.com:443`
- TTS: NVIDIA hosted endpoint at `grpc.nvcf.nvidia.com:443`
- LLM: NVIDIA hosted endpoint at `https://integrate.api.nvidia.com/v1`
- TURN relay: Coturn running in Docker on the Brev instance

This setup runs on a CPU instance because inference is offloaded to NVIDIA hosted services.

## 2. Why TURN Was Needed

For this topology:

- browser runs on the laptop
- backend runs on the Brev instance
- access to UI/backend is through SSH tunneling

plain HTTP signaling worked, but WebRTC media did not connect without TURN.

Important details:

- `http://localhost` on the laptop is enough for browser microphone access
- the Brev instance does not need a browser
- SSH tunneling is enough for the UI and `/offer` endpoint
- SSH tunneling is not enough to make WebRTC media reliably connect
- TURN/Coturn was required for the laptop browser to establish media with the remote backend

## 3. Prerequisites

On the Brev instance:

- Python 3.12 available through `uv`
- Node.js and npm installed
- Docker installed
- NVIDIA API key with access to:
  - hosted Parakeet ASR
  - hosted Magpie TTS
  - hosted Nemotron LLM

## 4. Project Layout

The project has been reduced to a minimal standalone folder:

```text
/home/ubuntu/voice-agent
├── pyproject.toml
├── uv.lock
├── src/
├── voice_agent_webrtc/
└── webrtc_ui/
```

Notes:

- `voice_agent_webrtc` depends on the local SDK in `../src`
- `voice_agent_webrtc/pyproject.toml` was updated so the editable dependency points to `..`

## 5. Backend Environment

The backend configuration lives at:

- `/home/ubuntu/voice-agent/voice_agent_webrtc/.env`

The important values are:

```env
NVIDIA_API_KEY=<your_nvidia_api_key>

ASR_SERVER_URL=grpc.nvcf.nvidia.com:443
ASR_CLOUD_FUNCTION_ID=1598d209-5e27-4d3c-8079-4751568b1081
ASR_MODEL_NAME=parakeet-1.1b-en-US-asr-streaming-silero-vad-sortformer

TTS_SERVER_URL=grpc.nvcf.nvidia.com:443
TTS_VOICE_ID=Magpie-Multilingual.EN-US.Aria
TTS_MODEL_NAME=magpie_tts_ensemble-Magpie-Multilingual

NVIDIA_LLM_URL=https://integrate.api.nvidia.com/v1
NVIDIA_LLM_MODEL=nvidia/nemotron-3-nano-30b-a3b
SYSTEM_PROMPT_SELECTOR=nemotron-3-nano/generic_voice_assistant
```

TURN values must also be set:

```env
TURN_SERVER_URL=turn:<brev_public_ip>:3478?transport=udp
TURN_USERNAME=<turn_username>
TURN_PASSWORD=<turn_password>
```

How to get `TURN_USERNAME` and `TURN_PASSWORD`:

- you choose them yourself
- they are not issued by NVIDIA or Brev
- Coturn uses whatever static username/password you provide at startup

Example generation:

```bash
python3 - <<'PY'
import secrets
print("TURN_USERNAME=turnuser")
print("TURN_PASSWORD=" + secrets.token_urlsafe(24))
PY
```

Then reuse the exact same values in all three places:

1. Coturn Docker `--user=<turn_username>:<turn_password>`
2. `voice_agent_webrtc/.env`
3. `webrtc_ui/src/config.ts`

Do not commit real secrets from `.env`.

## 6. Frontend TURN Config

The frontend TURN config lives at:

- `/home/ubuntu/voice-agent/webrtc_ui/src/config.ts`

The working shape is:

```ts
export const RTC_CONFIG: ConstructorParameters<typeof RTCPeerConnection>[0] = {
  iceServers: [
    {
      urls: [
        "turn:<brev_public_ip>:3478?transport=udp",
        "turn:<brev_public_ip>:3478?transport=tcp",
      ],
      username: "<turn_username>",
      credential: "<turn_password>",
    },
  ],
};

const host = window.location.hostname;
export const RTC_OFFER_URL = `http://${host}:7860/offer`;
```

Why this works:

- the page is opened as `http://localhost:5173` on the laptop
- `window.location.hostname` becomes `localhost`
- the browser calls `http://localhost:7860/offer`
- that hits the SSH-forwarded backend port

## 7. Install Steps

### Backend

```bash
cd /home/ubuntu/voice-agent/voice_agent_webrtc
uv venv --python 3.12
uv sync
```

If OpenCV import fails with `libGL.so.1` missing, install runtime libs:

```bash
sudo apt-get update
sudo apt-get install -y libgl1 libglib2.0-0
```

### Frontend

```bash
cd /home/ubuntu/voice-agent/webrtc_ui
npm install
```

## 8. Start Coturn

Coturn was started on the Brev instance with Docker host networking:

```bash
docker run -d \
  --name voice-agent-coturn \
  --restart unless-stopped \
  --network=host \
  instrumentisto/coturn \
  -n \
  --verbose \
  --log-file=stdout \
  --external-ip=<brev_public_ip> \
  --listening-ip=0.0.0.0 \
  --lt-cred-mech \
  --fingerprint \
  --user=<turn_username>:<turn_password> \
  --no-multicast-peers \
  --realm=voice-agent.local \
  --min-port=51000 \
  --max-port=52000
```

Notes:

- `turn_username` can be any simple username, for example `turnuser`
- `turn_password` should be a strong random string
- these credentials must match the backend and frontend TURN settings exactly

Check logs with:

```bash
docker logs --tail 100 voice-agent-coturn
```

## 9. Open Brev Ports

The Brev instance needed raw port exposure for TURN. HTTP secure links are not enough.

Open:

- `3478/udp`
- `3478/tcp`
- `51000-52000/udp`

These are for TURN only.

You do not need to publicly expose:

- `5173`
- `7860`

if you are reaching them from the laptop via SSH tunnel.

## 10. Run The App

### Start backend on Brev

```bash
cd /home/ubuntu/voice-agent/voice_agent_webrtc
uv run pipeline.py
```

### Start UI on Brev

```bash
cd /home/ubuntu/voice-agent/webrtc_ui
npm run dev -- --host 0.0.0.0
```

## 11. Connect From Laptop

From the laptop, create the SSH tunnel:

```bash
ssh -L 5173:localhost:5173 -L 7860:localhost:7860 ubuntu@<brev_host>
```

Then open in Chrome:

```text
http://localhost:5173
```

## 12. How We Verified TURN Was Working

Before TURN was configured correctly:

- `/offer` returned `200 OK`
- backend started the pipeline
- ICE stayed in `checking`
- backend timed out after 60 seconds

After TURN and Brev ports were set up:

- backend log showed:
  - `ICE connection state is completed`
  - `Connection state changed to: connected`
  - `Peer connection established`
- Coturn log showed:
  - `ALLOCATE processed, success`
  - `CREATE_PERMISSION processed, success`
  - `CHANNEL_BIND processed, success`

That confirmed the WebRTC relay path was working.

## 13. LLM Fix We Needed

The first hosted LLM config returned a `404 or model not found`.

The working hosted model value was:

```env
NVIDIA_LLM_MODEL=nvidia/nemotron-3-nano-30b-a3b
```

not:

```env
NVIDIA_LLM_MODEL=nvidia/nemotron-3-nano
```

## 14. Current Behavior Notes

### Bot name vs voice name

`Aria` is the TTS voice name, not the assistant identity.

The current prompt:

```env
SYSTEM_PROMPT_SELECTOR=nemotron-3-nano/generic_voice_assistant
```

does not define a bot name, so the LLM may invent one like `NAME1`.

If you want the assistant to always introduce itself as `Aria`, update the prompt in:

- `/home/ubuntu/voice-agent/voice_agent_webrtc/prompt.yaml`

### Emotion voices

Entries like `Aria.Neutral`, `Aria.Angry`, and `Aria.Fearful` are TTS voice styles, not proof that the system is reading user emotion.

In this repo, emotion-aware speech is driven by LLM output format and prompt selection, not by a dedicated biometric emotion detector in the current setup.

## 15. Troubleshooting

### UI loads but WebRTC fails

Check:

- Coturn is running
- TURN values in `.env` are correct
- `webrtc_ui/src/config.ts` has matching TURN credentials
- Brev ports are open:
  - `3478/udp`
  - `3478/tcp`
  - `51000-52000/udp`

### WebRTC connects but bot does not answer

Check backend logs for:

- invalid LLM model
- bad NVIDIA API key
- ASR/TTS endpoint errors

### Chrome microphone problems

For local tunneled development, `http://localhost:5173` should be allowed as a secure-enough context for mic access.

## 16. Useful Commands

### Backend

```bash
cd /home/ubuntu/voice-agent/voice_agent_webrtc
uv run pipeline.py
```

### Frontend

```bash
cd /home/ubuntu/voice-agent/webrtc_ui
npm run dev -- --host 0.0.0.0
```

### Coturn logs

```bash
docker logs --tail 100 voice-agent-coturn
```

### Stop Coturn

```bash
docker rm -f voice-agent-coturn
```

## 17. Summary

This topology works:

- laptop browser for the client
- Brev instance for backend and UI
- SSH tunnel for HTTP
- Coturn on Brev for WebRTC relay
- NVIDIA hosted inference endpoints for CPU-friendly deployment

The key lesson is that for a remote browser talking to a remote WebRTC backend through SSH tunneling, TURN is the difference between a UI that loads and a voice session that actually connects.
