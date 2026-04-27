# Voice Guide Demo Architecture Design Questions

This note records the main architecture questions discussed for the Jewel voice guide demo.
It is intentionally written as a decision record, not as a final production architecture.

## Problem Statement

**Problem:** What is the right architecture for a real-time voice guide agent that also demonstrates `NemoClaw`, `OpenShell`, and `OpenClaw` without damaging the low-latency voice experience?

**Persona:** A tourist arriving at Jewel Singapore who wants fast spoken guidance for mall discovery, family-friendly recommendations, and larger Singapore itinerary planning.

**Goal / Target:** Build a demo architecture that lets the tourist ask naturally by voice, receive quick answers when the request is simple, and escalate to governed planning when the request needs structure, tools, live data, or policy-visible execution.

**Constraints:** Browser microphone/speaker access, WebRTC/TURN session handling, ASR/TTS latency, OpenShell policy boundaries, OpenClaw planner state, and Brev-host deployment reality must all be represented accurately.

**Success Criteria:** The architecture should clearly explain which component owns realtime voice UX, which component owns routing, which component owns governed planning, and why `NemoClaw` / `OpenShell` / `OpenClaw` are useful beyond "just another planner agent."

**Success Metrics:** Compare voice-only, lookup, direct-planner, and OpenClaw-planner paths using:
- **Answer factuality:** At least 90% of scripted lookup/planner answers should be judged correct against the Jewel dataset or cited live/tool output.
- **Task completion quality:** At least 80% of scripted planner prompts should satisfy the main user constraints: destination, timing, sequence, and spoken summary.
- **Latency:** Direct and lookup turns should feel realtime, with first spoken response under 2 seconds target and under 4 seconds acceptable for demo conditions.
- **Planner responsiveness:** Planner path should send an immediate spoken acknowledgement within 2 seconds, even if the full plan takes longer.
- **Planner timeout rate:** Scripted demo prompts should have zero timeouts; ad-hoc planner exploration should stay below 10% timeout/fallback rate.
- **OpenShell policy visibility:** 100% of OpenClaw tool-using turns should have visible policy, approval, or execution evidence.
- **Real vs implied tool use:** 100% of answers that claim live checks should be backed by actual tool execution; otherwise the assistant should explicitly say live data was not checked.

<hr>
The current demo has settled on a Phase 1 shape:

```text
+------------------------------------------------+
| Laptop / Browser                               |
|                                                |
|  +------------------------------------------+  |
|  | webrtc_ui                                |  |
|  | mic / speaker / Planner panel            |  |
|  +------------------------------------------+  |
+------------------------------------------------+
                         :
                         : WebRTC media + RTVI data
                         v
+------------------------------------------------+
| Brev Host                                      |
|                                                |
|  +------------------------------------------+  |
|  | voice-agent-planner / Pipecat            |  |
|  | VoiceGuideOrchestratorService            |  |
|  | direct / lookup / planner paths          |  |
|  +------------------------------------------+  |
|                         :                      |
|                         : OpenShell SSH        |
|                         : planner text         |
|                         v                      |
|  +------------------------------------------+  |
|  | NemoClaw / OpenShell / OpenClaw          |  |
|  | planner + skills + tools                 |  |
|  +------------------------------------------+  |
+------------------------------------------------+
```

Phase 2 remains a possible stronger OpenShell topology where the voice runtime and the OpenClaw planner become peer governed services.

Diagram convention: large outer rectangles are physical/runtime zones such as `Laptop / Browser` and `Brev Host`. Inner rectangles are logical components or governance boundaries. `OpenShell`, `OpenClaw`, NemoClaw-managed sandbox state, skills, policies, and tool execution all sit on the `Brev Host`; they are not separate physical machines. Markdown width is controlled by the editor/viewer, so diagrams should stay readable within normal code-block width.

### Terminology Used In This Document

`OpenShell` is not itself "the sandbox." In the NemoClaw docs, the cleaner model is:

- `NemoClaw`: CLI/control plane that installs, creates, and manages the sandboxed OpenClaw environment.
- `OpenShell`: sandbox runtime and governance layer, including gateway, `inference.local` routing, k3s/runtime pieces, network policy, and approval/monitoring TUI.
- `OpenClaw`: the agent runtime inside the OpenShell-managed sandbox. It calls LLM inference through `inference.local` and runs tools inside the governed sandbox.
- `OpenShell-managed sandbox`: the actual governed execution environment. This is the phrase this document should use instead of the ambiguous "OpenShell sandbox."

So if a diagram says `NemoClaw / OpenShell / OpenClaw`, read it as:

```text
Brev Host
  |
  +-- NemoClaw manages lifecycle/config
  +-- OpenShell provides sandbox runtime, gateway, policy, approval
  +-- OpenClaw runs as the agent inside that governed sandbox
```

### Recommended Architecture Vocabulary

Use these terms in design discussions:

- **Host voice service:** `voice-agent-planner` running on the `Brev Host`, outside the OpenShell-managed sandbox. This is Phase 1.
- **OpenShell-managed OpenClaw sandbox:** the governed sandbox where `OpenClaw` runs skills and tools under OpenShell policy. This is also Phase 1.
- **OpenShell-governed host voice service:** a future Phase 2A design where the voice service remains a host process, but its inference/planner/tool-related traffic is routed through OpenShell-governed surfaces where feasible.
- **Voice-agent sandbox:** a future Phase 2B design where the voice runtime itself is placed inside an OpenShell-managed sandbox. This is a real sandbox design, not just routing through OpenShell.

Avoid saying "voice-agent planner inside OpenShell" without specifying which of the last two designs is meant.

## Index

1. [Question 1: What Is The Right Voice Entry Point?](#question-1-what-is-the-right-voice-entry-point)
2. [Question 2: Where Should The Voice Agent Sit?](#question-2-where-should-the-voice-agent-sit)
3. [Question 3: How Should The Per-Conversation Bridge Work?](#question-3-how-should-the-per-conversation-bridge-work)
4. [Question 4: What Is OpenClaw's Role In This Demo?](#question-4-what-is-openclaws-role-in-this-demo)
5. [Question 5: Where Should Routing Live?](#question-5-where-should-routing-live)
6. [Question 6: How Do We Prove The Value?](#question-6-how-do-we-prove-the-value)
7. [Current Recommended Architecture](#current-recommended-architecture)
8. [Future Phase 2 Architecture](#future-phase-2-architecture)
9. [Open Decisions](#open-decisions)

---

## Question 1: What Is The Right Voice Entry Point?

### Options Considered

#### Option A: OpenClaw gateway first

User input starts at the OpenClaw gateway, similar to many existing NemoClaw demos.

```text
+------------------------------------------------+
| User / Client                                  |
|                                                |
|  +------------------------------------------+  |
|  | text input                               |  |
|  +------------------------------------------+  |
+------------------------------------------------+
                         :
                         : text request
                         v
+------------------------------------------------+
| Brev Host                                      |
|                                                |
|  +------------------------------------------+  |
|  | NemoClaw / OpenShell                     |  |
|  | policy + inference.local routing         |  |
|  |                                          |  |
|  |  +------------------------------------+  |  |
|  |  | OpenClaw gateway / agent           |  |  |
|  |  | response generation                |  |  |
|  |  +------------------------------------+  |  |
|  +------------------------------------------+  |
+------------------------------------------------+
```

This is the cleanest way to demonstrate policy, inference routing, and sandboxed tool execution. It is less natural for realtime voice because the browser still needs microphone permission, speaker playback, WebRTC negotiation, TURN/ICE, and low-latency audio handling.

#### Option B: WebRTC UI first, then delegate to planner

User input starts at the current `webrtc_ui` and Pipecat voice service.

```text
+------------------------------------------------+
| Laptop / Browser                               |
|                                                |
|  +------------------------------------------+  |
|  | webrtc_ui                                |  |
|  | mic / speaker                            |  |
|  +------------------------------------------+  |
+------------------------------------------------+
                         :
                         : POST /offer
                         : WebRTC media + RTVI data
                         v
+------------------------------------------------+
| Brev Host                                      |
|                                                |
|  +------------------------------------------+  |
|  | voice-agent-planner / Pipecat            |  |
|  | TurnOrchestrator                         |  |
|  | - direct answer                          |  |
|  | - Jewel lookup                           |  |
|  | - planner bridge                         |  |
|  +------------------------------------------+  |
|                         :                      |
|                         : planner text + SSH   |
|                         v                      |
|  +------------------------------------------+  |
|  | NemoClaw / OpenShell / OpenClaw planner  |  |
|  +------------------------------------------+  |
+------------------------------------------------+
```

This is the Phase 1 recommendation. It optimizes for realtime voice UX first, then sends only planner-worthy text turns into the governed OpenClaw path.

#### Option C: Voice-agent and OpenClaw are peer governed services

The voice runtime becomes its own governed service, separate from but peer to the OpenClaw planner.

```text
+------------------------------------------------+
| Laptop / Browser                               |
|                                                |
|  +------------------------------------------+  |
|  | webrtc_ui                                |  |
|  +------------------------------------------+  |
+------------------------------------------------+
                         :
                         : WebRTC media
                         v
+------------------------------------------------+
| Brev Host                                      |
|                                                |
|  +------------------------------------------+  |
|  | NemoClaw / OpenShell boundary            |  |
|  |                                          |  |
|  |  +------------------------------------+  |  |
|  |  | voice-agent / Pipecat              |  |  |
|  |  +----------------+-------------------+  |  |
|  |                   :                      |  |
|  |                   : planner request      |  |
|  |                   v                      |  |
|  |  +------------------------------------+  |  |
|  |  | OpenClaw planner                   |  |  |
|  |  +------------------------------------+  |  |
|  +------------------------------------------+  |
+------------------------------------------------+
```

This is the likely Phase 2 direction. It gives a stronger OpenShell story, but adds deployment, network, and latency risk.

### Current Recommendation

Use **Option B** for Phase 1.

The voice guide demo starts with a realtime media problem, not just a text-agent problem. The browser and WebRTC path should remain the entry point until the speech experience is stable. OpenClaw should be introduced where it adds visible value: governed planning, tool access, policy, and observability.

---

## Question 2: Where Should The Voice Agent Sit?

### Option A: Voice agent outside sandbox, bridge into OpenClaw

```text
+------------------------------------------------+
| Brev Host                                      |
|                                                |
|  +--------------------+  +------------------+  |
|  | webrtc_ui          |  | voice-agent      |  |
|  | Vite / browser UI  |  | planner / Pipecat|  |
|  +--------------------+  +------------------+  |
|                         :                      |
|                         : SSH / OpenShell      |
|                         : planner bridge       |
|                         v                      |
|  +------------------------------------------+  |
|  | NemoClaw / OpenShell / OpenClaw          |  |
|  | - OpenClaw agent                         |  |
|  | - jewel-voice-planner skill              |  |
|  | - sandboxed tools                        |  |
|  +------------------------------------------+  |
+------------------------------------------------+
```

This is the current Phase 1 shape.

Benefits:
- Lowest risk for realtime audio and WebRTC.
- Easier to debug browser, TURN, Pipecat, ASR, TTS, and planner separately.
- Lets the voice stack use NVIDIA ASR/TTS/LLM directly for low-latency voice turns.
- Keeps OpenClaw focused on planner-worthy turns.

Costs:
- The initial user input does not enter through the OpenClaw gateway.
- The voice agent itself is not fully governed by OpenShell.
- The demo must clearly explain why this asymmetry exists.

### Option B: Voice agent inside the same sandbox as OpenClaw

```text
+------------------------------------------------+
| Laptop / Browser                               |
|                                                |
|  +------------------------------------------+  |
|  | webrtc_ui                                |  |
|  +------------------------------------------+  |
+------------------------------------------------+
                         :
                         : WebRTC media
                         v
+------------------------------------------------+
| Brev Host                                      |
|                                                |
|  +------------------------------------------+  |
|  | OpenShell-managed sandbox                |  |
|  |                                          |  |
|  |  +------------------+ +----------------+ |  |
|  |  | voice-agent      | | OpenClaw       | |  |
|  |  | Pipecat          | | tools          | |  |
|  |  +------------------+ +----------------+ |  |
|  +------------------------------------------+  |
+------------------------------------------------+
```

This looks clean on one diagram, but it couples realtime media to the OpenShell-managed sandbox and agent runtime. It can make TURN/WebRTC debugging harder and may introduce latency or jitter in the audio path.

### Option C: Voice agent in its own governed sandbox, OpenClaw in another

```text
+------------------------------------------------+
| Laptop / Browser                               |
|                                                |
|  +------------------------------------------+  |
|  | webrtc_ui                                |  |
|  +------------------------------------------+  |
+------------------------------------------------+
                         :
                         : WebRTC media
                         v
+------------------------------------------------+
| Brev Host                                      |
|                                                |
|  +------------------------------------------+  |
|  | NemoClaw / OpenShell                     |  |
|  |                                          |  |
|  |  +------------------------------------+  |  |
|  |  | Voice sandbox                      |  |  |
|  |  | voice-agent / Pipecat              |  |  |
|  |  +----------------+-------------------+  |  |
|  |                   :                      |  |
|  |                   : service planner call |  |
|  |                   v                      |  |
|  |  +------------------------------------+  |  |
|  |  | Planner sandbox                    |  |  |
|  |  | OpenClaw agent + tools             |  |  |
|  |  +------------------------------------+  |  |
|  +------------------------------------------+  |
+------------------------------------------------+
```

This is cleaner long-term than putting both in one sandbox. It treats voice-agent and OpenClaw as peer services under OpenShell governance.

### Current Recommendation

Keep the voice agent **outside the OpenClaw sandbox** for Phase 1.

Move toward peer governed services only after the demo proves the value of planner-backed voice guidance. The realtime speech path should not be made harder before the planner value is clear.

### Latency Note From The Current Phase 1 Implementation

The current Phase 1 risk is not simply "OpenShell adds latency." The sharper finding is:

```text
Raw/direct path:
  curl or direct HTTPS call
  -> fast enough for a backend probe or direct planner path

OpenClaw planner path:
  voice-agent -> OpenShell bridge -> OpenClaw agent loop
  -> skill/prompt/session/model/tool orchestration
  -> much slower in today's demo
```

So the architectural blocker is the end-to-end `OpenClaw` planner path latency, not the mere existence of OpenShell.

If the OpenClaw path becomes fast enough, the trade-off changes:
- keeping the voice agent outside the governed path becomes less necessary for latency
- moving the voice runtime behind OpenShell governance becomes more practical
- Phase 2 can be considered earlier because the main voice UX objection weakens

Even then, realtime voice still has extra constraints that raw `curl` does not have:
- WebRTC media negotiation
- ASR/TTS streaming
- interruption handling
- first spoken response expectations
- long-turn heartbeat and fallback behavior

So OpenClaw speed helps a lot, but the voice runtime still needs careful turn-timing design.

---

## Question 3: How Should The Per-Conversation Bridge Work?

### Desired Model

Each voice conversation should have a logical planner session that is created when the user starts speaking and destroyed when the conversation ends.

```text
+-------------------------------------------+
| Brev Host                                 |
|                                           |
| +---------------------------------------+ |
| | Voice conversation                    | |
| | - conversation_id                     | |
| | - planner session_id                  | |
| | - request_id per planner call         | |
| +-------------------+-------------------+ |
|                     :                     |
|                     : planner query       |
|                     v                     |
| +---------------------------------------+ |
| | PlannerBridge                         | |
| | timeout / fallback / request_id guard | |
| +-------------------+-------------------+ |
|                     :                     |
|                     : OpenClaw CLI / SSH  |
|                     v                     |
| +---------------------------------------+ |
| | NemoClaw / OpenShell / OpenClaw state | |
| | planner turns / artifacts / locks     | |
| +---------------------------------------+ |
+-------------------------------------------+
```

The voice side should own:
- `conversation_id`
- planner `session_id`
- per-call `request_id`
- timeout and fallback behavior
- cleanup on disconnect or timeout

The OpenClaw side should own:
- planner skill execution
- tool use
- structured response generation
- sandboxed session artifacts

### Option A: Use the main OpenClaw agent

```text
+-------------------------------------------+
| Brev Host                                 |
| +---------------------------------------+ |
| | voice-agent-planner                   | |
| +-------------------+-------------------+ |
|                     :                     |
|                     : openclaw agent      |
|                     : --agent main        |
|                     v                     |
| +---------------------------------------+ |
| | NemoClaw / OpenShell / OpenClaw       | |
| | main agent                            | |
| +---------------------------------------+ |
+-------------------------------------------+
```

This diagram is same-host. The CLI/SSH bridge crosses a governance boundary on the `Brev Host`; it is not crossing to a separate physical machine.

This is the current implementation path. It is simple and matches the installed `AGENTS.md` / skill setup.

Important observed behavior:
- Direct OpenClaw CLI calls have collapsed into the `main` agent's canonical session slot in testing.
- The passed `--session-id` is not a sufficient isolation boundary in the current path.
- Cleanup therefore wipes the main agent session directory for this demo path rather than deleting one named session file.
- The bridge detects stale responses by checking that the returned JSON `request_id` matches the request it sent.

### Option B: Create a different OpenClaw agent per voice conversation

```text
+---------------------------+
| Voice conversation A      |
+---------------------------+
              :
              : request A
              v
+---------------------------+
| Brev Host / OpenClaw      |
| agent planner-A           |
+---------------------------+

+---------------------------+
| Voice conversation B      |
+---------------------------+
              :
              : request B
              v
+---------------------------+
| Brev Host / OpenClaw      |
| agent planner-B           |
+---------------------------+

+---------------------------+
| Voice conversation C      |
+---------------------------+
              :
              : request C
              v
+---------------------------+
| Brev Host / OpenClaw      |
| agent planner-C           |
+---------------------------+
```

This gives stronger isolation in principle, but it is operationally heavier:
- agent creation and cleanup cost
- more files and config churn
- harder warmup
- more ways to leave stale agents behind

This is not recommended for Phase 1 unless OpenClaw gets a cheap, explicit per-session or per-channel API that makes this natural.

### Option C: Use one planner agent with explicit channel binding

```text
+-------------------------------------------+
| Voice Session                             |
| +---------------------------------------+ |
| | stable channel identity               | |
| | unique request_id                     | |
| +-------------------+-------------------+ |
+---------------------|---------------------+
                      |
                      : channel-bound planner request
                      v
+-------------------------------------------+
| Brev Host                                 |
| +---------------------------------------+ |
| | NemoClaw / OpenShell / OpenClaw agent | |
| | isolated session by channel key       | |
| +---------------------------------------+ |
+-------------------------------------------+
```

This is the preferred future direction if OpenClaw exposes a reliable channel-bound session model. Earlier investigation suggested that `--session-id` alone was not enough, and that a channel identity such as `--to` may be needed to derive a true session key.

### Current Recommendation

Use the `main` OpenClaw agent in Phase 1, but treat planner state as **ephemeral**:
- create a logical planner session per voice conversation
- include `request_id` in every planner request
- reject stale responses with mismatched `request_id`
- clean up OpenClaw session artifacts on voice disconnect or timeout
- avoid relying on long accumulated planner memory

This is pragmatic for the demo. It is not the ideal multi-tenant production design.

---

## Question 4: What Is OpenClaw's Role In This Demo?

### The Hard Question

Is `NemoClaw` / `OpenShell` / `OpenClaw` technically necessary for the voice guide demo?

The honest answer is: **not for basic voice Q&A**.

A voice-only demo can work like this:

```text
+------------------------------------------------+
| Browser                                        |
|                                                |
|  +------------------------------------------+  |
|  | mic / speaker                            |  |
|  +------------------------------------------+  |
+------------------------------------------------+
                         :
                         : WebRTC audio
                         v
+------------------------------------------------+
| Brev Host                                      |
|                                                |
|  +------------------------------------------+  |
|  | Pipecat voice-agent                      |  |
|  +------------------------------------------+  |
+------------------------------------------------+
                         :
                         : ASR / LLM / TTS API calls
                         v
+------------------------------------------------+
| NVIDIA Hosted Services                         |
|                                                |
|  +----------+   +----------+   +-----------+  |
|  | ASR      |   | LLM      |   | TTS       |  |
|  +----------+   +----------+   +-----------+  |
+------------------------------------------------+
```

That proves realtime speech, but not governed agentic execution.

### Technical Ladder

#### Level 0: Voice only

```text
+------------------+
| WebRTC           |
+------------------+
          :
          : audio
          v
+------------------+
| ASR              |
+------------------+
          :
          : text
          v
+------------------+
| LLM              |
+------------------+
          :
          : text
          v
+------------------+
| TTS              |
+------------------+
          :
          : audio
          v
+------------------+
| Browser          |
+------------------+
```

Good for:
- fast concierge answers
- speech experience
- simple prompt/persona demo

Weak for:
- grounded factuality
- tool use
- policy story
- multi-step travel planning

#### Level 1: Voice plus curated lookup

```text
+--------------------------+
| WebRTC                   |
+--------------------------+
             :
             : audio
             v
+--------------------------+
| ASR                      |
+--------------------------+
             :
             : text
             v
+--------------------------+
| Router                   |
+--------------------------+
             :
             : Jewel-local query
             v
+--------------------------+
| JewelKnowledgeIndex      |
+--------------------------+
             :
             : grounded answer
             v
+--------------------------+
| TTS                      |
+--------------------------+
```

Good for:
- Jewel directory questions
- family-friendly recommendations
- lower hallucination risk
- low latency versus full planner

Still weak for:
- live checks
- external tool governance
- explainable sandbox boundary

#### Level 2: Voice plus direct planner

```text
+--------------------------+
| WebRTC                   |
+--------------------------+
             :
             : audio
             v
+--------------------------+
| ASR                      |
+--------------------------+
             :
             : text
             v
+--------------------------+
| Router                   |
+--------------------------+
             :
             : planner prompt
             v
+--------------------------+
| DirectPlannerBackend     |
+--------------------------+
             :
             : HTTPS
             v
+--------------------------+
| NVIDIA hosted LLM for    |
| direct planning          |
+--------------------------+
             :
             : structured answer
             v
+--------------------------+
| TTS                      |
+--------------------------+
```

Good for:
- structured itinerary output
- better planning without sandbox overhead
- direct-first latency

Still weak for:
- OpenShell policy demonstration
- tool approval and sandbox observability
- showing why OpenClaw exists

#### Level 3: Voice plus OpenClaw planner inside an OpenShell-managed sandbox

```text
+--------------------------+
| WebRTC                   |
+--------------------------+
             :
             : audio
             v
+--------------------------+
| ASR                      |
+--------------------------+
             :
             : text
             v
+--------------------------+
| Router                   |
+--------------------------+
             :
             : planner query
             v
+------------------------------------------------+
| Brev Host                                      |
|                                                |
|  +------------------------------------------+  |
|  | NemoClaw / OpenShell managed sandbox     |  |
|  |                                          |  |
|  |  +------------------------------------+  |  |
|  |  | OpenClaw planner                   |  |  |
|  |  | - skills                           |  |  |
|  |  | - governed tools                   |  |  |
|  |  | - policy-visible execution         |  |  |
|  |  +------------------------------------+  |  |
|  +------------------------------------------+  |
+------------------------------------------------+
```

This is where OpenClaw earns its place. It is not just "another planner agent"; it is the governed planner tier.

OpenClaw should represent:
- agentic planning logic
- tool execution boundary
- skill-based behavior
- structured planner output
- session state and cleanup

OpenShell should represent:
- sandbox access
- approvals
- network/tool policy
- observable execution boundary

NemoClaw should represent:
- the broader demo/control-plane story
- a consistent way to package and operate sandboxed agent demos
- the reason this demo belongs with the rest of the NemoClaw examples

### Current Recommendation

Do not claim that OpenClaw is necessary for all voice turns.

Instead, make the demo story:
- voice-only is fastest but less grounded
- lookup is grounded for Jewel-local facts
- direct planner is fast for structured plans
- OpenClaw planner is for governed tool-heavy planning

That is more defensible than routing every user utterance through OpenClaw.

---

## Question 5: Where Should Routing Live?

### Options Considered

#### Option A: Put routing inside the prompt

```text
+--------------------------------+
| ASR transcript                 |
+--------------------------------+
                :
                : transcript text
                v
+--------------------------------+
| Prompt-Controlled LLM          |
|                                |
|  +--------------------------+  |
|  | decides answer/lookup    |  |
|  | versus planner           |  |
|  +--------------------------+  |
+--------------------------------+
```

This is simple to start, but hard to observe and tune. It makes route decisions depend on model behavior instead of explicit system policy.

#### Option B: Put routing directly in `pipeline.py`

```text
+-------------------------------------------+
| pipeline.py                               |
| +---------------------------------------+ |
| | build transport                       | |
| | build ASR/TTS                         | |
| | decide routes                         | |
| | call planner                          | |
| +---------------------------------------+ |
+-------------------------------------------+
```

This works for a prototype, but `pipeline.py` can become a large mixed-responsibility file. It should assemble the pipeline, not own all business logic.

#### Option C: Use an explicit orchestrator service

```text
+-------------------------------------------+
| Pipecat Pipeline                          |
| +---------------------------------------+ |
| | ASR / transcript frames               | |
| +-------------------+-------------------+ |
+---------------------|---------------------+
                      |
                      : LLMContextFrame / transcript
                      v
+-------------------------------------------+
| VoiceGuideOrchestratorService             |
| +---------------------------------------+ |
| | DirectAnswerPath                      | |
| | LookupPath                            | |
| | PlannerPath                           | |
| +---------------------------------------+ |
+-------------------------------------------+
```

This is the current implementation direction.

The prompt should shape answer style. The orchestrator should own route selection and logging.

### Current Recommendation

Keep routing in an explicit `VoiceGuideOrchestratorService`, created by `pipeline.py`.

Use clear route names:
- `direct`
- `lookup`
- `planner`

Avoid explaining Phase 1 as separate runtime agents named `JewelMallGuide` and `SingaporeTripPlanner`. Those are better treated as planner modes, skills, or content domains. The runtime diagram should stay focused on response paths.

---

## Question 6: How Do We Prove The Value?

The demo should compare the same user prompts across increasing capability levels.

```text
+-------------------------------+
| Demo Prompt                   |
+-------------------------------+
                :
                : run same prompt
                v
+-------------------------------+
| Voice-only / Direct           |
| latency / TTFB / quality      |
+-------------------------------+

+-------------------------------+
| Demo Prompt                   |
+-------------------------------+
                :
                : run same prompt
                v
+-------------------------------+
| Lookup                        |
| groundedness / correctness    |
+-------------------------------+

+-------------------------------+
| Demo Prompt                   |
+-------------------------------+
                :
                : run same prompt
                v
+-------------------------------+
| Planner                       |
| task completion / governance  |
+-------------------------------+
```

Recommended prompts:

1. "What can I do at Jewel for two hours?"
2. "Find dessert and a toy shop near Rain Vortex for my kids."
3. "I land at 2pm and want Jewel, Marina Bay sunset, then supper. Plan it for me."
4. "Actually check if anything is open right now before you plan."

Metrics to record:
- answer factuality
- task completion quality
- latency
- TTFB / first spoken response time
- planner timeout rate
- whether OpenShell approval or policy was visible
- whether tool use was real or only implied

The key product proof is not "OpenClaw always gives better latency." It will not.

The key proof is:
- for simple turns, cheaper paths are better
- for local factual turns, curated lookup reduces hallucination
- for multi-step and tool-governed turns, OpenClaw provides a reason to trust the result and inspect the execution

---

## Current Recommended Architecture

```text
+------------------------------------------------+
| Laptop / Browser                               |
|                                                |
|  +------------------------------------------+  |
|  | webrtc_ui                                |  |
|  | mic / speaker                            |  |
|  | transcript + Planner UI                  |  |
|  +------------------------------------------+  |
+------------------------------------------------+
                         :
                         : WebRTC media + RTVI data
                         v
+------------------------------------------------+
| Brev Host                                      |
|                                                |
|  +------------------------------------------+  |
|  | voice-agent-planner                      |  |
|  | FastAPI /offer + Pipecat                 |  |
|  | transcript frames into orchestrator       |  |
|  +------------------------------------------+  |
|                                                |
|  +------------------------------------------+  |
|  | VoiceGuideOrchestratorService            |  |
|  |                                          |  |
|  |  +------------+   +-------------------+  |  |
|  |  | Direct     |   | Lookup            |  |  |
|  |  | fast LLM   |   | JewelKnowledge    |  |  |
|  |  +------------+   +-------------------+  |  |
|  |                                          |  |
|  |  +------------------------------------+  |  |
|  |  | PlannerPath                        |  |  |
|  |  | PlannerBackendRouter               |  |  |
|  |  | - default: DirectPlannerBackend    |  |  |
|  |  | - escalation: OpenClawBackend      |  |  |
|  |  +------------------------------------+  |  |
|  +------------------------------------------+  |
|                      :                         |
|                      : OpenShell SSH           |
|                      : planner text            |
|                      v                         |
|  +------------------------------------------+  |
|  | NemoClaw / OpenShell managed sandbox     |  |
|  |                                          |  |
|  |  +------------------------------------+  |  |
|  |  | OpenClaw main agent                |  |  |
|  |  | jewel-voice-planner skill          |  |  |
|  |  | sandboxed tools / governed exec    |  |  |
|  |  +------------------------------------+  |  |
|  +------------------------------------------+  |
+------------------------------------------------+
```

This architecture is intentionally asymmetric:
- voice remains outside the sandbox for realtime UX
- OpenClaw is used when planner/tool governance matters
- direct-first planning avoids making every itinerary wait on OpenClaw

---

## Future Phase 2 Architecture

```text
+------------------------------------------------+
| Laptop / Browser                               |
|                                                |
|  +------------------------------------------+  |
|  | webrtc_ui                                |  |
|  | mic / speaker                            |  |
|  | transcript + Planner UI                  |  |
|  +------------------------------------------+  |
+------------------------------------------------+
                         :
                         : WebRTC media + RTVI data
                         v
+------------------------------------------------+
| Brev Host                                      |
|                                                |
|  +------------------------------------------+  |
|  | NemoClaw / OpenShell boundary            |  |
|  |                                          |  |
|  |  +------------------------------------+  |  |
|  |  | Voice-agent runtime                |  |  |
|  |  | - WebRTC / Pipecat session         |  |  |
|  |  | - ASR / TTS streaming              |  |  |
|  |  |                                    |  |  |
|  |  | +------------------------------+   |  |  |
|  |  | | VoiceGuideOrchestratorService |   |  |  |
|  |  | | - direct answer path          |   |  |  |
|  |  | | - Jewel lookup path           |   |  |  |
|  |  | | - planner request client      |   |  |  |
|  |  | | - timeout / fallback policy   |   |  |  |
|  |  | +---------------+--------------+   |  |  |
|  |  +----------------+-------------------+  |  |
|  |                   :                      |  |
|  |                   : governed service     |  |
|  |                   : planner request      |  |
|  |                   v                      |  |
|  |  +------------------------------------+  |  |
|  |  | OpenClaw                           |  |  |
|  |  | - planner agent                    |  |  |
|  |  | - Jewel / Singapore skills         |  |  |
|  |  | - tool execution                   |  |  |
|  |  | - future cuOpt planning skill      |  |  |
|  |  +----------------+-------------------+  |  |
|  |                   :                      |  |
|  |                   : approved egress      |  |
|  |                   : maps / weather       |  |
|  |                   : directory / cuOpt    |  |
|  |                   : booking / live APIs  |  |
|  +------------------------------------------+  |
+------------------------------------------------+
```

### What Moves From Phase 1 To Phase 2

Phase 1 has the voice runtime on the `Brev Host` and only calls into `OpenShell` / `OpenClaw` for planner-worthy work. Phase 2 moves the **voice-agent runtime itself behind the OpenShell governance boundary**.

That means:
- `Laptop / Browser` still owns only user device concerns: microphone, speaker, WebRTC UI, transcript view, and Planner panel.
- `Brev Host` still runs the demo processes, but now `OpenShell` is the visible governance boundary for both voice and planning work.
- `OpenShell` owns policy, audit, approval, service-to-service access, and approved egress for both the voice path and the planner path.
- `OpenClaw` owns agentic planning, skills, tool execution, structured planner output, and future cuOpt itinerary optimization.

### What "Voice-Agent Runtime Behind OpenShell" Means

This should not be read as "OpenShell becomes the voice agent." It means one of two concrete architectures:

#### Phase 2A: Governed host service

The voice-agent remains a normal process on the `Brev Host`, but its inference, service-to-service calls, and planner calls are routed through OpenShell-controlled policy surfaces where possible.

```text
Brev Host
  |
  +-- voice-agent process
  |     - WebRTC / Pipecat / ASR / TTS
  |     - VoiceGuideOrchestratorService
  |
  +-- OpenShell gateway / policy / approval
  |
  +-- OpenClaw inside OpenShell-managed sandbox
```

This is easier operationally and is the likely next step if we want more governance without putting WebRTC itself inside a sandbox.

#### Phase 2B: Voice runtime inside an OpenShell-managed sandbox

The voice-agent runtime itself is deployed inside a sandbox managed by NemoClaw/OpenShell.

```text
Brev Host
  |
  +-- NemoClaw / OpenShell
        |
        +-- voice-agent sandbox
        |     - WebRTC / Pipecat / ASR / TTS
        |     - VoiceGuideOrchestratorService
        |
        +-- OpenClaw planner sandbox
              - planner agent
              - skills
              - tools
```

This is the cleanest governance story, but it is also the riskiest for realtime voice because media, TURN, ASR/TTS streaming, and interruption behavior now cross the sandbox boundary.

Recommended interpretation for now: Phase 2 means **Phase 2A first**, unless OpenClaw/OpenShell latency and sandbox networking are proven fast and stable enough for Phase 2B.

### Where The Work Sits In Phase 2

`voice-agent` work sits inside the `OpenShell` boundary on the `Brev Host`:
- WebRTC/Pipecat session handling
- ASR/TTS streaming calls
- user-facing timeout and fallback behavior

`VoiceGuideOrchestratorService` still exists in Phase 2. It is not removed or replaced by OpenShell. It sits inside the voice-agent runtime and owns:
- route selection between `direct`, `lookup`, and `planner`
- speculative direct/lookup response handling
- planner request construction
- planner status/display events for the UI
- timeout, heartbeat, interruption, and fallback behavior
- the boundary between voice UX timing and slower governed planning

The difference from Phase 1 is governance, not ownership of routing. In both phases, `VoiceGuideOrchestratorService` remains the voice-side brain. In Phase 2, OpenShell governs the runtime that contains it.

`OpenClaw` work sits inside `OpenClaw`, also under `OpenShell`:
- planner agent state
- Jewel and Singapore planning skills
- tool execution
- live-data checks
- future cuOpt planning skill
- response schema generation for the Planner panel and spoken summary

`governed external access` is not a fifth entity. It is the **approved egress path managed by OpenShell** for OpenClaw tool calls:
- maps
- weather
- mall directory APIs
- cuOpt endpoint
- booking or live availability APIs

### Why Phase 2 Is Different From Phase 1

Phase 1 asks:
- can the existing voice app call OpenClaw for planner turns without hurting realtime voice?
- can we prove OpenClaw value only where planning and tools matter?

Phase 2 asks:
- can the whole voice application be governed by OpenShell?
- can voice-agent and OpenClaw communicate through a policy-visible service boundary?
- can both LLM/ASR/TTS access and planner tool egress be audited and constrained consistently?

Phase 2 is cleaner for governance, but more complex:
- more service boundaries inside the `Brev Host`
- more OpenShell policy to define
- higher latency and jitter risk for the voice path
- harder debugging across WebRTC, TURN, voice runtime, OpenShell policy, and OpenClaw planner execution

Phase 2 should come after Phase 1 clearly proves planner value.

---

## Open Decisions

1. Should OpenClaw expose a first-class per-conversation session API for this kind of voice bridge?
2. Should Phase 2 put the voice runtime in a sandbox or merely behind OpenShell governance?
3. Should planner escalation require explicit live/tool intent, or should all multi-step itinerary requests go through OpenClaw?
4. What is the acceptable voice UX timeout for governed planning: 5 seconds, 10 seconds, or a background planner panel with spoken heartbeat?
5. Should future cuOpt integration live as an OpenClaw skill, an MCP tool, or a separate planner service called by OpenClaw?

The current Phase 1 answer is conservative: keep voice fast, make planner governance visible only where it matters, and avoid pretending that OpenClaw is necessary for every voice turn.
