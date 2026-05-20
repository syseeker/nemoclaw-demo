# Voice Guide Demo — Architecture Design Questions (Decision Log)

This note is a **decision log** of the open architecture questions we worked through
while building the Jewel voice guide demo. It is written from the chat history,
not a polished spec. Each topic captures: what we asked, what we considered,
what we picked for Phase 1, and what is still on the table for later.

A companion view of the same design space written separately is in
[architecture-design-questions_openai.md](architecture-design-questions_openai.md).
The two documents are deliberately kept side by side so different framings can
be compared.

---

## Index

1. [Terminology and Phases](#0-terminology-and-phases)
2. [Topic 1 — Where is the right voice entry point?](#topic-1--where-is-the-right-voice-entry-point)
3. [Topic 2 — Where should the voice agent sit?](#topic-2--where-should-the-voice-agent-sit)
4. [Topic 3 — How should the per-conversation bridge work?](#topic-3--how-should-the-per-conversation-bridge-work)
5. [Topic 4 — Is `NemoClaw` / `OpenShell` / `OpenClaw` even necessary here?](#topic-4--is-nemoclaw--openshell--openclaw-even-necessary-here)
6. [Topic 5 — Where should the `DirectPlannerBackend` live?](#topic-5--where-should-the-directplannerbackend-live)
7. [Topic 6 — `OpenClaw` gateway vs embedded runner](#topic-6--openclaw-gateway-vs-embedded-runner)
8. [Topic 7 — Voice UX during long planner turns](#topic-7--voice-ux-during-long-planner-turns)
9. [Summary Table and Current Architecture](#summary-table-and-current-architecture)
10. [Open Decisions](#open-decisions)

---

## 0. Terminology and Phases

A lot of confusion in the chats came from overloaded words. Pin them down first.

| Term | What it actually is |
|---|---|
| `NemoClaw` | The CLI/control plane that installs and lifecycles the sandboxed agent setup. |
| `OpenShell` | Sandbox runtime + governance: gateway, `inference.local`, k3s pieces, network policy, approval TUI. |
| `OpenClaw` | The agent runtime that lives **inside** an OpenShell-managed sandbox. |
| `OpenShell-managed sandbox` | The actual governed execution environment. Avoid the ambiguous phrase "OpenShell sandbox". |
| `voice-agent-planner` | The Pipecat-based host process running on the Brev box (orchestrator, ASR, TTS, planner client). |
| `webrtc_ui` | The React UI in the browser: mic, speaker, transcript, Planner panel. |
| `Brev Host` | One physical/virtual machine. Both the host voice service AND the OpenShell-managed sandbox sit on it. They are **not** different machines. |

Phases used throughout this doc:

- **Phase 1** — voice service runs on the host, OpenClaw runs in the OpenShell-managed sandbox, and a planner bridge crosses between them. This is what currently ships.
- **Phase 2A** — voice service stays on the host, but its inference and planner traffic is routed through OpenShell-governed surfaces.
- **Phase 2B** — voice service itself runs inside its own OpenShell-managed sandbox, peer to the OpenClaw planner sandbox.

---

## Topic 1 — Where is the right voice entry point?

**The question (from chat):**
> "I'm concerned that the user input does not go through openclaw gateway, but through webrtc ui instead… most of the existing nemoclaw demo shows input via openclaw gateway."

This is the first place the voice demo diverges from the standard NemoClaw pattern.

### Option A — OpenClaw gateway first (the typical NemoClaw demo)

```text
+------------------+        +-----------------------------------+
|  Browser / CLI   | text   |  Brev Host                        |
|  text input      +------->|                                   |
+------------------+        |  +-----------------------------+  |
                            |  | OpenShell-managed sandbox   |  |
                            |  |   OpenClaw gateway          |  |
                            |  |   --> agent loop            |  |
                            |  |   --> inference.local       |  |
                            |  +-----------------------------+  |
                            +-----------------------------------+
```

Strong demo for policy and inference routing, weak for realtime voice
(no place to handle WebRTC, ASR/TTS streaming, or interruption timing).

### Option B — `webrtc_ui` first, planner bridge into the sandbox (Phase 1)

```text
+----------------+    WebRTC + RTVI    +-------------------------------------+
|  Browser       |<------------------->|  Brev Host                          |
|  webrtc_ui     |    POST /offer      |                                     |
+----------------+                     |  +-------------------------------+  |
                                       |  | voice-agent-planner (host)    |  |
                                       |  |  - Pipecat / ASR / TTS        |  |
                                       |  |  - Orchestrator + Router      |  |
                                       |  +---------------+---------------+  |
                                       |                  | planner text     |
                                       |                  v                  |
                                       |  +-------------------------------+  |
                                       |  | OpenShell-managed sandbox     |  |
                                       |  |  OpenClaw "main" agent        |  |
                                       |  +-------------------------------+  |
                                       +-------------------------------------+
```

What this optimizes for:

- realtime media is debugged in one place (browser + host process)
- the OpenClaw path is touched only on planner-worthy turns
- ASR/TTS latency is not coupled to sandbox networking

What it costs:

- the very first user input does not flow through the OpenClaw gateway
- the demo must explicitly explain why it is asymmetric
- governance only kicks in at the planner step, not at the entry

### Option C — `webrtc_ui` to OpenShell, OpenShell fans out (Phase 2A)

```text
+----------------+    WebRTC    +-------------------------------------+
|  Browser       |<------------>|  Brev Host                          |
|  webrtc_ui     |              |                                     |
+----------------+              |  +-------------------------------+  |
                                |  | OpenShell governance layer    |  |
                                |  +---+----------------------+----+  |
                                |      | governed voice path  |      |
                                |      v                      v      |
                                |  +--------+        +------------+  |
                                |  | voice  |        | OpenClaw   |  |
                                |  | agent  |        | planner    |  |
                                |  +--------+        +------------+  |
                                +-------------------------------------+
```

Cleaner governance story, but adds a hop in front of the realtime path.

### What we picked

Option B for Phase 1. The constraint that drove this was simple: the voice
guide is a realtime media problem first, and an agent governance demo second.
We do not want to debug TURN/ICE through a sandbox boundary while still
proving the planner story.

---

## Topic 2 — Where should the voice agent sit?

**The question (from chat):**
> "Should voice agent inside openclaw? Or behind openshell (independent from
> nemoclaw/openclaw because it is an agent by itself same level as openclaw)?
> If we move voice agent inside openshell, is it going to introduce more lag?"

### Option A — Voice agent on the host, bridge into sandbox (Phase 1)

```text
+---------------------------------------------------------------+
|  Brev Host                                                    |
|                                                               |
|  +------------------+   SSH tunnel /     +----------------+   |
|  | voice-agent      |   openclaw CLI     | OpenShell-     |   |
|  | (host process)   +------------------->| managed        |   |
|  | Pipecat + ASR/   |                    | sandbox        |   |
|  | TTS + Orchestr.  |<-------------------| (OpenClaw)     |   |
|  +------------------+   planner JSON     +----------------+   |
+---------------------------------------------------------------+
```

Pros:

- realtime audio path stays simple
- planner can fail or be slow without breaking the conversation
- ASR/TTS keeps direct access to NVIDIA hosted services via `NVIDIA_API_KEY`

Cons:

- voice-agent is not OpenShell-governed
- entry asymmetry (Topic 1) follows from this

### Option B — Voice agent **inside** the same sandbox as OpenClaw

```text
+---------------------------------------------------------------+
|  Brev Host                                                    |
|                                                               |
|  +-------------------------------------------------------+    |
|  |  OpenShell-managed sandbox                            |    |
|  |                                                       |    |
|  |  +---------------------+   +---------------------+    |    |
|  |  | voice-agent process |   | OpenClaw agent loop |    |    |
|  |  | Pipecat + ASR/TTS   |<->| skills + tools      |    |    |
|  |  +---------------------+   +---------------------+    |    |
|  +-------------------------------------------------------+    |
+---------------------------------------------------------------+
```

Looks tidy on a slide, but it puts the WebRTC media path, TURN, ASR/TTS, and
OpenClaw's slow agent loop into one runtime. We saw OpenClaw cold starts and
LLM idle timeouts of 60+ seconds; coupling that to live voice is a bad idea.

### Option C — Voice agent in its **own** governed sandbox, peer to OpenClaw (Phase 2B)

```text
+---------------------------------------------------------------+
|  Brev Host                                                    |
|                                                               |
|  +-------------------------------------------------------+    |
|  |  OpenShell governance boundary                        |    |
|  |                                                       |    |
|  |  +---------------------+    governed RPC/HTTP         |    |
|  |  | voice-agent sandbox |<------------------------+    |    |
|  |  | webrtc_ui+pipecat   |                         |    |    |
|  |  +---------------------+                         |    |    |
|  |                                                  v    |    |
|  |                                +---------------------+|    |
|  |                                | OpenClaw planner    ||    |
|  |                                | sandbox             ||    |
|  |                                +---------------------+|    |
|  +-------------------------------------------------------+    |
+---------------------------------------------------------------+
```

This is the cleanest governance story and matches user intent for "Option C as
next phase". It only becomes practical once OpenClaw planner latency is fixed
and OpenShell exposes a stable service-to-service surface.

### What we picked

Option A for Phase 1. We explicitly accept the entry asymmetry from Topic 1
because realtime voice UX is the harder constraint right now.

The chat finding worth preserving: the latency objection to moving the voice
agent into the sandbox is **not** "OpenShell adds latency by itself". The real
issue is that the **OpenClaw planner path is slow** (system prompt size +
embedded runner cold start + Nemotron idle gaps). If that path becomes fast,
the case for Phase 2B gets stronger.

---

## Topic 3 — How should the per-conversation bridge work?

**The question (from chat):**
> "one planner worker per voice conversation is good. Then the session is killed?
> then openclaw agent lost the state, but does the voice agent keep state and
> send to openclaw agent everytime? … how to sessionize it based on what rules
> is a key."

This was the topic we hit reality hardest on. What looked clean on paper did
not match how OpenClaw actually behaves.

### Desired model

```text
+-------------------------------------------------------+
|  per voice conversation                               |
|                                                       |
|  conversation_id                                      |
|     |                                                 |
|     +-- planner session_id   (created on connect)     |
|     +-- request_id           (per planner call)       |
|     +-- timeout / fallback   (owned by voice side)    |
|     +-- destroyed on disconnect                       |
+-------------------------------------------------------+
```

Voice side owns identity, timeout, fallback, and cleanup.
OpenClaw side owns skill execution, tools, and structured output.

### Option A — Use the OpenClaw `main` agent (current Phase 1)

```text
+-------------------+                 +----------------------+
|  voice-agent      | openclaw agent  |  OpenClaw "main"     |
|  PlannerBridge    +---------------->|  agent (session)     |
|  + request_id     |   --agent main  |                      |
+-------------------+                 +----------------------+
```

Observed reality from the chat:

- direct CLI calls collapse into the **canonical** session slot for the agent
- `--session-id` is **not** an isolation boundary in the current openclaw build
- `--to` looks promising but the `mainKey` is effectively hardcoded to `"main"`
  unless the agent is configured for sender-scope
- so the bridge cannot rely on multiple isolated sessions inside `main`

Mitigation we settled on:

- voice side owns a logical `session_id` and a per-call `request_id`
- bridge **rejects** any reply whose payload `request_id` does not match
  (this caught the case where Nemotron idled past 60s and OpenClaw replayed
  the previous turn's assistant message)
- `cleanup_session()` wipes the actual session storage on disconnect, not just
  one named jsonl file

### Option B — A different OpenClaw agent per voice conversation

```text
+-----------+   +-----------+   +-----------+
| voice A   |   | voice B   |   | voice C   |
+-----+-----+   +-----+-----+   +-----+-----+
      |               |               |
      v               v               v
+-----------+   +-----------+   +-----------+
| planner-A |   | planner-B |   | planner-C |
+-----------+   +-----------+   +-----------+
```

We tried a `voice-planner` agent overnight (separate from `main`). It did not
hold up: agent creation/cleanup churn, skill discovery quirks, and OpenShell
policy gaps meant we ended up rolling back to `main`. So this is the
**theoretically right** answer, but practically expensive in the current
OpenClaw build.

### Option C — One agent, real channel binding via `--to` / scope

```text
+--------------------------+
|  voice-agent             |
|   conversation_id = X    |
|   --to=channel:X         |
|   --session-id=plan-X    |
+------------+-------------+
             |
             v
+--------------------------+
|  OpenClaw planner agent  |
|   isolated by channel X  |
|   (only works if agent   |
|    is scoped per sender) |
+--------------------------+
```

The cleanest future shape, blocked today by how OpenClaw resolves the session
key when the agent is not scope-configured. Worth revisiting once OpenClaw
exposes a first-class per-conversation session API.

### What we picked

Option A with **strict ephemeral discipline**:

- `request_id` correlation per call
- raw stdout tail + payload `request_id` mismatch detection
- session storage wiped on voice disconnect or timeout
- no reliance on accumulated planner memory between conversations

This is good enough for a single-tenant demo on a Brev host. It is not the
right shape for multi-tenant production, and we explicitly do not pretend it
is.

---

## Topic 4 — Is `NemoClaw` / `OpenShell` / `OpenClaw` even necessary here?

**The question (from chat, near-verbatim):**
> "what's the need of openclaw planner skill? and the future live data pulling
> tools, cuopt tool? if we bypass openclaw, what's the needs of going through
> openshell and come back, i can just ask voice-agent LLM (which is also
> nemotron-3-super) to answer directly, no need planner route."

This is the most important question in the document. The honest answer is
not "yes, all of NemoClaw/OpenShell/OpenClaw is needed for every turn".

### What OpenClaw actually adds on top of a raw model call

| Capability | Used by current planner skill? | Cheaper alternative |
|---|---|---|
| Multi-step agent loop (model → tool → model → answer) | No, single-pass JSON | Direct LLM call with structured output prompt |
| Tool registry (`web_search`, `web_fetch`, `browser`, `memory_*`, future cuOpt) | Almost no tool calls observed in smoke tests | Call tool APIs directly from the bridge |
| Skill discipline (SKILL.md JSON marker contract) | Yes, weakly | A system prompt enforces the same contract |
| Sandboxed execution + governance + approvals | Yes | Hard to replicate without OpenShell |

The first three things can be replicated outside OpenClaw with less plumbing.
The **fourth** is what OpenClaw uniquely buys, and it is the entire point of
this stack.

### The "ladder" of capability we settled on

```text
Level 0   voice only                     fast, ungrounded
Level 1   voice + JewelKnowledgeIndex    fast, grounded for Jewel facts
Level 2   voice + DirectPlannerBackend   structured, no governance
Level 3   voice + OpenClaw planner       governed, tool-capable, slower
```

### What we picked: direct-first, OpenClaw on escalation (Option 4 in chat)

```text
+------------------+
| Browser          |
+--------+---------+
         |
         v
+----------------------------+
| voice-agent-planner        |
|   Orchestrator + Router    |
|     - direct (nano LLM)    |
|     - lookup (Jewel index) |
|     - planner -> Backend   |
+--------+-------------------+
         |
         v
+----------------------------+
| PlannerBackendRouter       |
|  default  : DirectPlanner  |
|  escalate : OpenClawPlanner|
+--------+-----------+-------+
         |           |
         v           v
+--------------+   +-----------------------+
| NVIDIA hosted|   | OpenShell-managed     |
| LLM (nemotron|   | sandbox - OpenClaw    |
| -super) over |   | "main" agent + skill  |
| HTTPS        |   | + governed tools      |
+--------------+   +-----------------------+
```

Why this works as a demo:

- **direct path** disproves the strawman "you must always go through OpenClaw"
- **lookup path** shows curated grounding without an LLM
- **direct planner** shows that pretty itineraries are easy with the model alone
- **OpenClaw planner** is the path where the demo actually earns its name —
  governed tool use, approval visibility, sandboxed execution

The story to tell is not "OpenClaw makes everything better". It is
"OpenClaw makes governed tool-using planning possible at all". Forcing every
voice turn through OpenClaw makes the latency look bad **and** makes the
governance look pointless.

### Could we just scrap NemoClaw entirely?

That was raised in the chat: "if we bypass openclaw, what's the need of going
through openshell and come back?" The honest answer:

- without OpenClaw, the demo has no story for the planner skill
- without OpenShell, the demo has no story for tool governance
- without NemoClaw, the demo has no story for how this gets installed/managed
  alongside other sandboxed agent demos

So all three are kept, but their job is **only the escalation path**, not the
fast path. The voice runtime stays out of the sandbox until Phase 2.

---

## Topic 5 — Where should the `DirectPlannerBackend` live?

**The question (from chat):**
> "im curious to see the system component diagram… getting confused now on
> why the directplannerbackend needs to sit inside sandbox alongside openclaw…
> can directplannerbackend directly access openshell inference provider? No
> need to ssh into sandbox."

This came up because the natural symmetry is:

- both backends use the same Nemotron model
- so route both through the same `inference.local` provider for consistency
- which would mean the direct backend also lives inside the sandbox or at
  least talks through the OpenShell inference gateway

### What we found in the chat

The host **already has** `NVIDIA_API_KEY` for the direct catalog endpoint
(`integrate.api.nvidia.com/v1`). It does **not** need OpenShell to reach
NVIDIA hosted inference for the small `nemotron-3-nano-30b-a3b` model that
serves the direct conversational path.

So the placement options are:

```text
Option 1 - host-only DirectPlanner (Phase 1):
+------------------+        +--------------------------+
| voice-agent host |  HTTPS | NVIDIA hosted catalog    |
| DirectPlanner    +------->| nemotron-3-super         |
+------------------+        +--------------------------+

Option 2 - DirectPlanner via OpenShell inference:
+------------------+   ssh -L  +--------------+   +----------+
| voice-agent host +---------->| openshell    +-->| inference|
| DirectPlanner    |  tunnel   | gateway      |   | .local   |
+------------------+           +--------------+   +----------+

Option 3 - DirectPlanner inside sandbox (next to OpenClaw):
+------------------+   ssh    +-------------------------+
| voice-agent host +--------->| sandbox: DirectPlanner +|
+------------------+          | OpenClaw, both via      |
                              | inference.local         |
                              +-------------------------+
```

Option 2 was the symmetric choice but required a persistent
`ssh -L 13128:10.200.0.1:3128 -N -f openshell-clawpit` started by the host.
That was correctly flagged in the chat as "a hack". Option 3 was even worse
because it pulled the fast path into the slow runtime.

### What we picked

Option 1. The direct backend goes straight to NVIDIA hosted inference with
the host's existing `NVIDIA_API_KEY`. We accept the asymmetry that
DirectPlanner does **not** go through OpenShell — that is consistent with
"direct = fast, ungoverned" and "OpenClaw = governed, slower".

---

## Topic 6 — `OpenClaw` gateway vs embedded runner

**The question (from chat):**
> "i still don't understand why gateway failure and if this is a design problem
> of nemoclaw/openshell, or problem of openclaw and if connecting to that
> gateway is a must, seems like it is not because you've embedded runner
> options."

OpenClaw can reach the agent loop two ways:

```text
+--------------------+        +-----------------------+
| openclaw CLI       | WS     | OpenClaw gateway      |
| (gateway client)   +------->| (in OpenShell)        |
+--------------------+        +-----------------------+
                                    | spawns
                                    v
                              +-----------------------+
                              | agent loop            |
                              +-----------------------+

vs.

+--------------------+        +-----------------------+
| openclaw CLI       | IPC    | embedded runner       |
| (--embed)          +------->| spawned in same proc  |
+--------------------+        +-----------------------+
                                    | calls
                                    v
                              +-----------------------+
                              | agent loop            |
                              +-----------------------+
```

In testing the gateway WebSocket failed (abnormal close), and the CLI fell
back to the embedded runner, which works. The user's reading is correct: the
embedded path is essentially **IPC RPC**, the gateway path is **WebSocket
RPC**. Either way the agent loop is the same.

### What we picked

For Phase 1 we accept whichever path works. The bridge logs both, prefers
gateway when it is healthy, and falls back cleanly. Fixing the gateway is a
NemoClaw/OpenShell concern, not a voice-agent concern.

---

## Topic 7 — Voice UX during long planner turns

This is not strictly an architecture topic but it shaped the bridge contract.
From the chat:

> "as openclawbackend will take longer time, it's actually good to keep the
> user warm by continue to keep them update every X seconds… just like the
> loading cursor in windows…"

We landed on three layers of feedback for slow planner turns:

```text
0 ms     spoken acknowledgement     "Let me put that together for you"
~5s+     planner_status events      Planner panel: "Planning your answer…"
~15s+    short heartbeat tone /     spoken "still on it…" (sparse)
         spoken filler
ready    spoken summary +           Planner panel renders timetable +
         planner_display            route/tasks/activities only
```

Two design rules came out of this:

1. The **Planner panel** only shows timetable and route/task/activities.
   Anything else (internal thinking, full prose) belongs in the spoken reply
   or nowhere at all.
2. The **spoken summary** asks the user to refer to the Planner panel rather
   than reading the whole plan aloud.

This affects the bridge contract: the planner must return structured display
data, not just spoken prose. That structure also makes evaluation easier —
we can score timetable correctness independently of the spoken response.

---

## Summary Table and Current Architecture

### Decisions at a glance

| Topic | Phase 1 choice | Why | Phase 2 candidate |
|---|---|---|---|
| Entry point | `webrtc_ui` first, then planner bridge | realtime voice UX wins for now | route via OpenShell when latency permits |
| Voice agent placement | host process, outside sandbox | keep WebRTC/ASR/TTS simple | Phase 2A (governed host) → Phase 2B (peer sandboxes) |
| Per-conversation bridge | `main` agent + ephemeral session + `request_id` correlation | OpenClaw does not isolate by `--session-id` today | per-conversation sandbox or scope-bound channel |
| Role of OpenClaw stack | governed escalation only, not for every turn | direct path is faster and good enough for most asks | full governance once Phase 2 lands |
| DirectPlanner placement | host process, NVIDIA hosted catalog | host already has API key, no SSH tunnel needed | route through OpenShell inference for symmetry |
| Gateway vs embedded | accept either, prefer gateway | gateway WS bug is upstream; embedded works | rely on healthy gateway when fixed |
| Voice UX on slow turns | acknowledgement + status + heartbeat + structured display | otherwise long OpenClaw turns feel broken | same, but with shorter OpenClaw latency |

### Phase 1 architecture (what currently ships)

```text
+---------------------------------------------------------------+
|  Laptop / Browser                                             |
|  +-------------------------------------------------------+    |
|  |  webrtc_ui : mic, speaker, transcript, Planner panel  |    |
|  +-------------------------------------------------------+    |
+---------------------------------------------------------------+
                           |
                           |  WebRTC media + RTVI data
                           v
+---------------------------------------------------------------+
|  Brev Host                                                    |
|                                                               |
|  +-------------------------------------------------------+    |
|  | voice-agent-planner (host process)                    |    |
|  |   FastAPI /offer + Pipecat                            |    |
|  |   ASR + TTS via NVIDIA hosted services                |    |
|  |                                                       |    |
|  |   VoiceGuideOrchestratorService                       |    |
|  |     - direct  : nemotron-3-nano (host LLM)            |    |
|  |     - lookup  : JewelKnowledgeIndex (no LLM)          |    |
|  |     - planner : PlannerBackendRouter                  |    |
|  |         default  -> DirectPlannerBackend (host)       |    |
|  |         escalate -> OpenclawPlannerBackend            |    |
|  +-------------------------+-----------------------------+    |
|                            |                                  |
|                            |  ssh + openclaw CLI              |
|                            |  (planner JSON contract)         |
|                            v                                  |
|  +-------------------------------------------------------+    |
|  | OpenShell-managed sandbox                             |    |
|  |   OpenClaw "main" agent                               |    |
|  |     skill: jewel-voice-planner                        |    |
|  |     governed tools (web_search, web_fetch, ...)       |    |
|  |     ephemeral session per voice conversation          |    |
|  +-------------------------------------------------------+    |
+---------------------------------------------------------------+
                            |
                            |  HTTPS over NVIDIA_API_KEY
                            v
              +---------------------------------+
              |  NVIDIA hosted catalog          |
              |  nemotron-3-nano (host direct)  |
              |  nemotron-3-super (DirectPlan)  |
              +---------------------------------+
```

The asymmetry is intentional:

- voice path stays on the host for realtime UX
- OpenShell-managed sandbox is the governed planner tier, used only when it
  earns its place
- both fast paths (direct and lookup) and the symmetric DirectPlanner bypass
  the sandbox so the demo does not pay a governance tax for turns that do not
  benefit from governance

---

## Open Decisions

These are still genuinely open and worth revisiting:

1. **Per-conversation isolation in OpenClaw.** Should NemoClaw expose a
   first-class per-conversation session API, or is `--to` + scoped
   `mainKey` enough once the agent is correctly scoped?
2. **Phase 2A vs Phase 2B sequencing.** Move the voice service behind
   OpenShell governance first (2A), or jump straight to sandboxed voice
   runtime (2B) once OpenClaw latency improves?
3. **DirectPlanner symmetry.** Once OpenShell inference is reliably
   reachable from the host without ad-hoc SSH tunnels, should
   DirectPlanner switch to `inference.local` for consistency, even though
   it costs latency?
4. **Escalation policy.** Should escalation to OpenClaw require explicit
   live/tool intent (rule-based classifier), or should every multi-step
   itinerary request go through OpenClaw by default?
5. **Voice timeout budget.** What is the acceptable voice UX timeout for
   governed planning — 5s, 10s, or always-async with a Planner panel and
   spoken heartbeat?
6. **Future cuOpt integration.** Does cuOpt land as an OpenClaw skill, an
   MCP tool exposed inside the sandbox, or a separate planner service that
   OpenClaw calls? This drives whether OpenClaw stays a planner agent or
   grows into a planner orchestrator.

The Phase 1 stance throughout is conservative on purpose: keep voice fast,
make OpenClaw governance visible only where it actually matters, and avoid
claiming OpenClaw is necessary for every spoken turn.
