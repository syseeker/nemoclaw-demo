# Deploy AI-Q Blueprint

Deploy the [NVIDIA AI-Q Blueprint](https://docs.nvidia.com/aiq-blueprint/latest/index.html)
as a host-side research service and connect it to the NemoClaw sandbox. The
OpenClaw agent can then call AI-Q's multi-agent research pipeline (intent
classification, shallow/deep research, web search, citations) via REST API.

## What you will learn

- Deploying AI-Q Blueprint on the host via Docker Compose
- Adding a network policy so the sandbox can reach the AI-Q API
- Installing the **`aiq-research`** skill so the agent calls AI-Q on its own
  when you ask for "deep research"
- Calling AI-Q's research endpoint from inside the sandbox
- Accessing the AI-Q web UI

> **Reference:** [AI-Q Blueprint docs](https://docs.nvidia.com/aiq-blueprint/latest/index.html) · [NemoClaw network policies](https://docs.nvidia.com/nemoclaw/latest/reference/network-policies.html)

---

## Prerequisites

- A running NemoClaw sandbox (complete [INSTALL.md](../../INSTALL.md) Steps 1–2).
- Docker Engine and Docker Compose v2 on the host.
- An [NVIDIA API key](https://build.nvidia.com/) (`NVIDIA_API_KEY`).
- A [Tavily API key](https://tavily.com/) (`TAVILY_API_KEY`) for web search.

---

## Demo variables

Set these once in the host shell you use for this demo:

```bash
export NEMOCLAW_SANDBOX=....
export NEMOCLAW_DEMO_ROOT=...
```

Run the `NEMOCLAW_DEMO_ROOT` line from anywhere inside this demo repo. If you
keep the repo elsewhere, set `NEMOCLAW_DEMO_ROOT` explicitly to that path.

---

## Architecture

```
┌──────────────────────────────────────────────────┐      ┌─────────────────┐
│                   Host Machine                   │      │ Client Browser  │
│                                                  │      │                 │
│  ┌──────────────────┐   ┌─────────────────────┐  │      │  AI-Q Web UI    │◄─┐
│  │ AI-Q Blueprint   │   │ NemoClaw Sandbox    │  │      │  (user-facing)  │  │
│  │ (Docker Compose) │   │ (OpenShell)         │  │      └─────────────────┘  │
│  │                  │   │                     │  │               │           │
│  │ aiq-agent :8000 ◄┼───┼─ curl / skills      │  │◄──────────────┘           │
│  │ aiq-ui   :3000 ──┼───┼─────────────────────┼──┼───────────────────────────┘
│  │ postgres :5432   │   │ OpenClaw Agent      │  │   (browser ↔ host, direct)
│  └──────────────────┘   └─────────────────────┘  │
│                                │                 │
│                       OpenShell Proxy            │
│                       (network policy enforced)  │
└──────────────────────────────────────────────────┘
```

AI-Q runs as a standalone Docker Compose stack on the host. The **AI-Q web UI
is served by the AI-Q backend and opened in the user's browser** (laptop/desktop). The sandbox agent calls AI-Q's REST
API through the OpenShell proxy, which enforces the network policy. AI-Q
handles model inference (NVIDIA API Catalog), web search (Tavily), and
multi-agent orchestration. The sandbox controls what the agent can reach.

**Two independent flows:**

- **End-user flow (AI-Q alone):** the user opens the AI-Q UI in their browser
  and talks directly to the AI-Q backend on the host. Collections, uploads, and
  deep-dive research work independently of NemoClaw.
- **Agent flow (NemoClaw + AI-Q tool):** the OpenClaw agent inside the sandbox
  uses AI-Q as a **tool** — its HTTP calls are routed through the OpenShell
  gateway and network policy to the AI-Q backend, then results flow back to the
  agent.

---

## Step 1 — Clone and configure AI-Q

```bash
cd ~
git clone https://github.com/NVIDIA-AI-Blueprints/aiq.git
cd aiq
cp deploy/.env.example deploy/.env
```

Edit `deploy/.env` and set your API keys:

```bash
nano deploy/.env
```

Required keys:

```
NVIDIA_API_KEY=nvapi-...
TAVILY_API_KEY=tvly-...
```

---

## Step 2 — Start AI-Q via Docker Compose

```bash
cd ~/aiq/deploy/compose
docker compose --env-file ../.env -f docker-compose.yaml up -d --build
```

This starts three containers:

| Container | Port | Description |
|---|---|---|
| `aiq-agent` | 8000 | Backend API (FastAPI + Dask workers) |
| `aiq-blueprint-ui` | 3000 | Web UI (Next.js) |
| `aiq-postgres` | 5432 | PostgreSQL (jobs, checkpoints, summaries) |

Verify AI-Q is healthy:

```bash
curl http://localhost:8000/health
# {"status":"healthy"}
```

---

## Step 3 — Find the host IP for the sandbox

The sandbox reaches the host via the Docker network gateway. Find it:

```bash
export AIQ_HOST="$(
  docker inspect "openshell-cluster-${NEMOCLAW_SANDBOX}" \
    --format '{{range .NetworkSettings.Networks}}{{.Gateway}}{{end}}'
)"
printf 'AI-Q endpoint: http://%s:8000\n' "${AIQ_HOST}"
```

This records the gateway IP in `AIQ_HOST`. You will use the same value in the
network policy and when calling AI-Q from inside the sandbox.

---

## Step 4 — Add the AI-Q network policy

**4a — Create the policy preset:**

Copy the template into the NemoClaw policy presets directory:

```bash
cat > ~/.nemoclaw/source/nemoclaw-blueprint/policies/presets/aiq-local.yaml << EOF
preset:
  name: aiq-local
  description: "AI-Q Blueprint API on local host (port 8000)"

network_policies:
  aiq_local:
    name: aiq_local
    endpoints:
      - host: ${AIQ_HOST}
        port: 8000
        access: full
    binaries:
      - { path: /usr/bin/curl }
      - { path: /usr/bin/python3* }
      - { path: /usr/local/bin/node }
EOF
```

The generated preset should contain the same host printed in Step 3.

**4b — Apply the policy:**

```bash
nemoclaw "${NEMOCLAW_SANDBOX}" policy-add
```

Select `aiq-local` from the list.

---

## Step 5 — Install the `aiq-research` skill

Without a skill, the agent doesn't know AI-Q exists — you'd have to spell out
`curl "http://${AIQ_HOST}:8000/generate" …` every time. The
[`aiq-research` skill](skills/aiq-research/SKILL.md) in this repo teaches the
agent to route any "research / deep dive / investigate" request through AI-Q
and return a clean **Answer + Sources** block.

OpenClaw should see the skill under **both** of these paths inside the
sandbox (create dirs if needed):

- `/sandbox/.openclaw/skills/aiq-research/SKILL.md`
- `$HOME/.openclaw/skills/aiq-research/SKILL.md` (usually `/home/sandbox/...`)

**Fast path — upload from the host:**

```bash
openshell sandbox upload "${NEMOCLAW_SANDBOX}" \
  "${NEMOCLAW_DEMO_ROOT}/demo/aiq-blueprint/skills/aiq-research/SKILL.md" \
  /sandbox/.openclaw/skills/aiq-research/

openshell sandbox upload "${NEMOCLAW_SANDBOX}" \
  "${NEMOCLAW_DEMO_ROOT}/demo/aiq-blueprint/skills/aiq-research/SKILL.md" \
  /home/sandbox/.openclaw/skills/aiq-research/
```

> The skill uses `AIQ_HOST` in its `curl` examples. Keep the same value
> exported in the sandbox shell when you launch OpenClaw.

**Verify** the skill is registered:

```bash
nemoclaw "${NEMOCLAW_SANDBOX}" connect
openclaw skills list | grep aiq-research
```

For alternative install paths (copy-paste into `nano`, or the e2e helper
script), see [Install the philosopher-nudge skill](../telegram-hourly-nudge/hourly-nudge.md#step-2--install-the-philosopher-nudge-skill-in-the-sandbox)
— the mechanics are identical.

---

## Step 6 — Test from inside the sandbox

Connect to the sandbox:

```bash
nemoclaw "${NEMOCLAW_SANDBOX}" connect
```

Inside the sandbox shell, set the same endpoint values from the host:

```bash
export AIQ_HOST="<host-ip-from-step-3>"
```

Test the health endpoint:

```bash
curl "http://${AIQ_HOST}:8000/health"
# {"status":"healthy"}
```

Send a research query (streaming):

```bash
curl -N -X POST "http://${AIQ_HOST}:8000/generate/stream" \
  -H "Content-Type: application/json" \
  -d '{"query": "What is CUDA and how does it relate to GPU programming?"}'
```

Send a research query (non-streaming):

```bash
curl -s -X POST "http://${AIQ_HOST}:8000/generate" \
  -H "Content-Type: application/json" \
  -d '{"query": "What is CUDA?"}' | python3 -m json.tool
```

You should see AI-Q's research response with citations and sources.

---

## Step 7 — Ask the agent (skill-driven)

This is the payoff. With the skill from Step 5 installed, you can ask for
research in **plain language** and OpenClaw will call AI-Q on its own — no
more hand-typed `curl`.

Open a TUI session in the sandbox:

```bash
nemoclaw "${NEMOCLAW_SANDBOX}" connect
export AIQ_HOST="<host-ip-from-step-3>"
openclaw tui
```

Then try any of these prompts:

- `Use skill aiq-research. Query: What is CUDA? Cite sources.`
- `/research What changed in NVIDIA Blackwell vs Hopper for inference?`
- `Investigate recent developments in retrieval-augmented generation.`

The agent should recognize the intent, invoke **`aiq-research`**, hit
`http://${AIQ_HOST}:8000/generate`, and reply with an `### Answer` +
`### Sources` block per the skill's output contract.

If the agent answers from its own weights instead of calling AI-Q, that's
usually one of:

1. The skill file isn't under both paths from Step 5 — re-check with
   `openclaw skills list`.
2. The network policy isn't applied — re-run
   `nemoclaw "${NEMOCLAW_SANDBOX}" policy-add` and pick `aiq-local`.
3. AI-Q is down — curl `/health` from inside the sandbox (Step 6).

---

## Step 8 (optional) — Access the web UI

The AI-Q web UI runs on port 3000. From your local machine, forward the port:

```bash
ssh -L 3000:localhost:3000 -L 8000:localhost:8000 user@your-vm
```

Then open [http://localhost:3000](http://localhost:3000) in your browser.

---

## How it works

1. **User prompt** (e.g. "do deep research on X") matches the **`aiq-research`
   skill's** `Use when` block. OpenClaw loads the skill's instructions and
   issues a single `curl` to `http://${AIQ_HOST}:8000/generate`.
2. **OpenShell gateway / proxy** intercepts the request and checks the
   `aiq-local` network policy — `${AIQ_HOST}:8000` is allowed with
   `access: full`.
3. **AI-Q backend** receives the query and runs its multi-agent pipeline:
   - Intent classifier routes to shallow or deep research
   - Research agents call NVIDIA models (Nemotron) and Tavily web search
   - Results are synthesized with citations
4. **Response flows back** through the proxy to the agent, which formats it
   into the skill's **Answer + Sources** output contract.

The sandbox governs which endpoints the agent can reach. AI-Q handles
the research pipeline independently on the host. The **AI-Q UI stays in the
user's browser** and talks directly to the AI-Q backend — it never runs inside
the sandbox.

---

## Stopping AI-Q

```bash
cd ~/aiq/deploy/compose
docker compose --env-file ../.env -f docker-compose.yaml down
```

Add `-v` to also remove database volumes:

```bash
docker compose --env-file ../.env -f docker-compose.yaml down -v
```

---


## See also

- [AI-Q Blueprint documentation](https://docs.nvidia.com/aiq-blueprint/latest/index.html)
- [AI-Q Docker Compose deployment](https://docs.nvidia.com/aiq-blueprint/2.0.0/deployment/docker-compose.html)
- [`aiq-research` skill](skills/aiq-research/SKILL.md)
- [Basic sandbox](../basic/basic.md)
- [Telegram Bridge](../telegram-bridge/telegram-bridge.md)
- [Telegram hourly nudge — philosopher-nudge skill install pattern](../telegram-hourly-nudge/hourly-nudge.md)
