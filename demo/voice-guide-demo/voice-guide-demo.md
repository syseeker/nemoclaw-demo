# Jewel Voice Guide Demo (Direct-First Planner)

This demo shows how a voice concierge can do more than simple Q&A.
It can answer quick questions, give grounded Jewel recommendations, and build a clearer multi-step plan when the request is more complex.

The goal is to give users a more natural travel-assistant experience:
fast when the question is easy, and more structured when a real itinerary is needed.

It also demonstrates an NVIDIA-centered software stack for voice agents:
`pipecat` for realtime orchestration, NVIDIA ASR/TTS/LLM services for speech and language,
and `NemoClaw` / `OpenClaw` / `OpenShell` for planner-style agent execution and sandbox access.

**Reference:** [Basic demo](../basic/basic.md) · [Token Budget](../token-budget/token-budget-guide.md) · [Voice Agent Brev Setup](voice-agent/SETUP_BREV_LAPTOP.md)

---

## What you will learn

- What this demo proves about the NVIDIA voice-agent stack in a realistic travel use case
- How `pipecat` can be used as the realtime backbone for browser-to-voice interactions
- How hosted NVIDIA ASR, TTS, and LLM services can be combined into one end-to-end assistant
- How `NemoClaw`, `OpenClaw`, and `OpenShell` fit into the planning and sandboxed tool path
- How to run the packaged demo and explain the main user journeys during a walkthrough

---

## Architecture (Data + Network + System Flow)

```text
Client (Browser)
  |
  | WebRTC audio + data channel
  v
webrtc_ui (React)
  |
  | POST /offer
  v
voice-agent-planner pipeline (Pipecat)
  |
  v
VoiceGuideOrchestratorService
  |-- direct route ------------------------------> NVIDIA LLM (nano) --> spoken reply
  |-- lookup route ------------------------------> JewelKnowledgeIndex --> spoken reply
  |
  |-- planner route
      |-- emits planner_status + planner_display over RTVI --> Planner panel (UI)
      |-- PlannerBackendRouter (mode=auto, direct-first)
          |-- DirectPlannerBackend -------------> NVIDIA API (super model)
          |-- OpenclawPlannerBackend (escalation/fallback)
               -> OpenShell/SSH tunnel -> OpenClaw sandbox agent/tools
      |-- returns spoken summary + structured display (timetable + route/tasks/activities)
  |
  v
TTS audio back to browser

Checked-in demo assets live under:
  demo/voice-guide-demo/

Live implementation in this demo lives under:
  demo/voice-guide-demo/voice-agent-planner/apps/jewel_voice_guide/
```

---

## Prerequisites

- A working Brev setup from [voice-agent/SETUP_BREV_LAPTOP.md](voice-agent/SETUP_BREV_LAPTOP.md)
- `openshell` installed on the host
- A working sandbox such as `clawpit`
- Hosted NVIDIA ASR, TTS, and LLM credentials for the voice path

---

## Step 1 — Install planner-side demo assets

```bash
cd <your-checkout>/demo/voice-guide-demo
./install.sh [sandbox-name]
```

This installs:
1. `skills/jewel-voice-planner/SKILL.md` into `/sandbox/.openclaw-data/workspace/skills/`
2. `data/jewel_knowledge.json` into `/sandbox/.openclaw-data/workspace/`
3. an AGENTS.md snippet that guides planner behavior inside the supported `main` agent path
4. a higher planner timeout budget for slower OpenClaw/Nemotron starts
5. a reset of `planner-*` session files under the `main` agent so stale planner state does not linger

Before starting the voice stack, review the generated shared environment file:

```bash
${EDITOR:-nano} "${XDG_CONFIG_HOME:-$HOME/.config}/nemoclaw-voice-agent/voice-agent.env"
```

At minimum, set `NVIDIA_API_KEY`. If your setup needs TURN, hosted/local NIM overrides, or a custom upstream voice-agent path, update the matching `TURN_*`, `ASR_*`, `TTS_*`, `NVIDIA_LLM_*`, and `UPSTREAM_VOICE_AGENT_DIR` values there too.

Important:
- this installer does **not** currently apply a custom OpenShell network policy for planner live tools
- keep `openshell term` open while testing planner prompts so you can see and approve anything the sandbox requests
- if you later add live planner tools, add the matching OpenShell policy explicitly rather than assuming the installer already did it
- the installer raises `agents.defaults.timeoutSeconds` so planner calls have more time to complete on cold starts

---

## Step 2 — Verify the planner path first

Open the OpenShell approval view in one terminal:

```bash
openshell term
```

Then in another terminal run the same host-to-sandbox planner path used by the app:

```bash
cd <your-checkout>/demo/voice-guide-demo
./verify-planner.sh [sandbox-name]
```

If this preflight hangs or times out, check:
- `openshell term` for approval requests
- device approval on the host via `openclaw devices list`
- whether the sandbox is healthy before starting the voice UI

---

## Step 3 — Run the host voice stack

Start the Jewel app entrypoint after the shared env file is configured:

```bash
cd <your-checkout>/demo/voice-guide-demo/voice-agent-planner
uv run -m apps.jewel_voice_guide.pipeline
```

Then start the UI from the matching working copy:

```bash
cd <your-checkout>/demo/voice-guide-demo/voice-agent-planner/webrtc_ui
npm install
npm run dev -- --host 0.0.0.0
```

Use the same SSH tunnel and TURN workflow described in
[voice-agent/SETUP_BREV_LAPTOP.md](voice-agent/SETUP_BREV_LAPTOP.md).

---

## Step 4 — Verify the planner backend

Health:

```bash
curl -s http://localhost:7860/planner/health
```

Sample query:

```bash
curl -s http://localhost:7860/planner/query \
  -H 'content-type: application/json' \
  -d '{
    "request_id":"demo-1",
    "session_id":"voice-guide-demo",
    "user_text":"I land at 2pm and want Jewel, Marina Bay sunset, then supper.",
    "route_reason":"multi_step_or_live_data_request",
    "session_context":{"current_location":"Jewel Singapore","prior_turns":[]},
    "planner_options":{"response_style":"voice_friendly","max_steps":5,"allow_live_data":true,"allow_tools":true}
  }'
```

---

## Demo flow

### Prompt 1 — direct path

Say:

```text
What can I do at Jewel for two hours?
```

Show:
- low-latency voice response
- no planner requirement for the easy case

### Prompt 2 — lookup path

Say:

```text
Find dessert and a toy shop near Rain Vortex for my kids.
```

Show:
- grounded Jewel-local answer
- curated dataset value without invoking the planner

### Prompt 3 — planner path

Say:

```text
I land at 2pm and want Jewel, Marina Bay sunset, then supper. Plan it for me.
```

Show:
- routing into the planner path
- direct-first planner execution with escalation/fallback path available
- Planner panel updates (`planner_status`, `planner_display`) during long turns
- planner display focused on timetable + route/tasks/activities
- concise spoken summary that asks the user to refer to the Planner panel
- if it stalls, look at `openshell term` first before assuming routing failed

---

## File structure

```text
voice-guide-demo/
├── voice-guide-demo.md
├── install.sh
├── verify-planner.sh
├── agents-md-snippet.md
├── data/jewel_knowledge.json
├── skills/jewel-voice-planner/SKILL.md
└── voice-agent-planner/            # sanitized, runnable app snapshot (no credentials)
```

---

## Notes

- `voice-guide-demo/voice-agent-planner/apps/jewel_voice_guide` is the Jewel-specific app root.
- `voice-guide-demo/voice-agent.env.example` is the template for `${XDG_CONFIG_HOME:-$HOME/.config}/nemoclaw-voice-agent/voice-agent.env`.
- the current installer deploys skill + data + AGENTS guidance, but not a custom planner egress policy
- planner state is intended to be ephemeral per voice conversation and should be destroyed on voice disconnect/timeout, even though it currently runs on `main`
