# Demo Plan: NemoClaw + OpenShell + OpenClaw with Nemotron 3 Super

## Overview

| Component | Role |
|-----------|------|
| **NemoClaw** | CLI that installs and manages sandboxed OpenClaw |
| **OpenShell** | Sandbox runtime (gateway, k3s, network policy) |
| **OpenClaw** | Agent that uses LLM inference and tools |
| **Nemotron 3 Super** | 120B reasoning model via NVIDIA NIM |

---

## Prerequisites (2 min)

- Node.js ≥20, Docker
- NVIDIA API key from [build.nvidia.com](https://build.nvidia.com)

```bash
export NVIDIA_API_KEY=nvapi-xxxx
```

---

## Phase 1: Install & Create Sandbox (≈5 min)

```bash
cd ~/NemoClaw
bash ./install.sh
```

When asked, choose:

- **Provider**: `nvidia-nim` (cloud)
- **Model**: `nvidia/nemotron-3-super-120b-a12b`
- **Policy**: `suggested` (to see approval flow)

### Fix DNS (Brev / Linux Docker only)

If DNS fails inside the sandbox (common on non-Colima setups), run **from
the host before connecting**:

```bash
NEMOCLAW_FIX_COREDNS_FORCE=1 bash ~/NemoClaw/scripts/fix-coredns.sh nemoclaw
```

Wait ~15 seconds, then verify from inside the sandbox:

```bash
nemoclaw <name> connect
# Inside the sandbox (nslookup may not be installed, use curl instead):
curl -s -o /dev/null -w "HTTP %{http_code}\n" --connect-timeout 5 https://www.google.com
# Expected: HTTP 200
```

> **Important**: Run the CoreDNS fix **before** connecting to the sandbox for
> the first time. The OpenClaw gateway starts when the sandbox is created. If
> DNS is broken at that point, the gateway's Node.js process caches the failures.
> Even after fixing CoreDNS, the gateway's `web_fetch` tool may still fail until
> the gateway process is restarted (see Troubleshooting below).

### Add finance policy preset (optional)

To allow stock price lookups (Yahoo Finance, Google Finance):

```bash
nemoclaw <name> policy-add
# Select: finance
```

The finance preset (`nemoclaw-blueprint/policies/presets/finance.yaml`) allows
`query1.finance.yahoo.com`, `query2.finance.yahoo.com`, `finance.yahoo.com`,
`www.google.com`, and `google.com` on port 443 with **no binary restriction**
(any process — curl, python, node, openclaw — can use them).

---

## Phase 2: Connect & Run Demo Prompts (5 min)

```bash
nemoclaw <name> connect
```

### Prompt 1: Basic inference (no tools, no egress)

```bash
openclaw agent --agent main --local -m "Explain what Nemotron 3 is in one sentence" --session-id demo1
```

Shows: inference routing through the gateway to Nemotron 3 Super. No network
egress needed — pure LLM call.

### Prompt 2: Tool execution with egress (will fail without policy)

```bash
openclaw agent --agent main --local -m "Fetch today NVIDIA stock price and print it" --session-id demo1
```

Shows: the agent tries `web_fetch` but gets blocked by sandbox policy (or DNS
fails). This demonstrates deny-by-default. Apply the finance preset and use a
new session to retry.

### Prompt 3: Working stock price fetch via curl (exec tool)

```bash
openclaw agent --agent main --local -m "Use bash to run: curl -s 'https://query1.finance.yahoo.com/v8/finance/chart/NVDA?range=1d&interval=1m' then parse and print the NVIDIA stock price from the JSON output" --session-id demo6
```

Shows: the agent uses the `exec` tool to run `curl` (a fresh process with
working DNS) instead of `web_fetch`. This bypasses the gateway's DNS cache.

### Prompt 3 (alternative): Google Finance via curl

```bash
openclaw agent --agent main --local -m "Run: curl -s 'https://www.google.com/finance/quote/NVDA:NASDAQ' | python3 -c \"import sys,re; html=sys.stdin.read(); m=re.search(r'data-last-price=\\\"([0-9.]+)\\\"', html); print(f'NVIDIA (NVDA): \${m.group(1)}' if m else 'Price not found')\" -- print the result" --session-id demo11
```

Use this if Yahoo Finance returns HTTP 429 (rate-limited).

> **Why specify curl in the prompt?** See the "Gotcha" section below for details
> on `web_fetch` vs `exec` and binary restrictions.

---

## Phase 3: Split-Screen Walkthrough (5 min)

Use two terminals side by side (Cursor: click the split terminal icon).

**Terminal 1 – OpenShell TUI (monitor + approve)**

```bash
openshell term
```

**Terminal 2 – Agent**

```bash
nemoclaw <name> connect
openclaw tui --session demo1
```

### Suggested prompts

1. *"Fetch the current NVIDIA stock price and print it"*
   → triggers finance API access (needs finance policy or approval)

2. *"Install the requests library and get the top story from Hacker News"*
   → triggers PyPI (allowed) + `news.ycombinator.com` (needs approval)

### What to watch

- In `openshell term`: blocked network requests appear with host, port, and binary.
- Approve or deny each request.
- Approved endpoints persist for the session only.

### Troubleshooting

- **Agent says "DNS resolution fails" but DNS works**: start a new session
  so the agent doesn't carry over memory of past failures:
  ```bash
  openclaw tui --session demo2
  ```
- **Yahoo Finance returns HTTP 429**: rate-limited; wait a moment and retry,
  or use Google Finance instead.
- **`jq: command not found`**: `jq` is not installed in the sandbox. Tell the
  agent to use `python3` for JSON parsing instead.
- **`nslookup: command not found`**: use `curl` or `getent hosts` to test DNS.

---

## Phase 4: Verify Inference & Status (1 min)

```bash
# Check active model
openshell inference set --provider nvidia-nim --model nvidia/nemotron-3-super-120b-a12b

# Sandbox status
nemoclaw <name> status

# Logs
nemoclaw <name> logs
```

---

## Demo Flow Cheat Sheet

| Step | Command | What to Show |
|------|---------|--------------|
| 1 | `nemoclaw list` | Sandbox registry |
| 2 | `nemoclaw <name> connect` | SSH-like connection into sandbox |
| 3 | `openclaw agent -m "..."` | Agent reasoning with Nemotron 3 Super |
| 4 | `openshell term` | Network monitoring and policy approval |
| 5 | Ask agent for PyPI/HN fetch | Blocked request → approve → success |

---

## Talking Points

1. **Sandboxing**: OpenClaw runs in an OpenShell sandbox; all network access is deny-by-default.
2. **Nemotron 3 Super**: 120B reasoning model hosted on NVIDIA NIM cloud.
3. **Inference routing**: Agent → `inference.local` → OpenShell gateway → NVIDIA NIM. The agent never calls the cloud API directly.
4. **Policy enforcement**: Unknown hosts require explicit operator approval in the TUI. Approved endpoints persist for the session only.
5. **Two kinds of traffic**:
   - *Inference* (LLM calls) routes through the gateway — always allowed.
   - *Tool execution* (curl, Python HTTP) uses sandbox egress — subject to network policy.

---

## Gotcha: `web_fetch` vs `exec` and Binary Restrictions

Two things can cause the agent's HTTP requests to fail even when `curl` works
from the command line.

### 1. `web_fetch` uses the gateway's DNS cache

OpenClaw has two ways to make HTTP requests:

| Tool | How it works | DNS source |
|------|-------------|------------|
| `web_fetch` | Built-in Node.js HTTP inside the OpenClaw gateway process | Gateway's DNS cache |
| `exec` | Spawns a new subprocess (e.g. `curl`, `python3`) | Fresh DNS lookup |

The OpenClaw gateway is a **long-running Node.js process** that starts when the
sandbox is created. If DNS was broken at that time, Node.js caches the failures.
Even after fixing CoreDNS, `web_fetch` continues to fail until the gateway
process is restarted.

**Fix**: Tell the agent to use `curl` via `exec` (e.g. "Use bash to run:
curl ..."). Each `curl` invocation is a fresh process with a fresh DNS lookup.

To restart the gateway and fix `web_fetch` permanently:

```bash
# Exit sandbox, then reconnect
exit
nemoclaw <name> connect
```

### 2. Binary restrictions in policy rules

When OpenShell auto-approves a request in the TUI, it creates a rule restricted
to the **binary that made the request** (e.g. `/usr/bin/curl`). OpenClaw's
`web_fetch` tool runs inside `/usr/local/bin/openclaw` (Node.js), so a rule
allowing only `curl` won't cover `web_fetch`.

**Fix**: Use the finance preset (`nemoclaw <name> policy-add` → finance) which
has **no binary restriction**, allowing any process to reach finance endpoints.

---

## Deep Dive: How Inference and Tool Execution Differ

There are two separate network flows in the sandbox. Understanding the
difference is key to explaining why some requests work and others get blocked.

### What `inference.local` actually means

`inference.local` is **not** "run inference on the local machine." It is the
hostname the agent uses to reach the inference system. The OpenShell gateway
exposes this endpoint inside the sandbox.

```
Agent sends to: https://inference.local/v1/chat/completions
                      │
                      ▼
              OpenShell gateway
              (receives the request)
                      │
                      ▼
              Routes to configured provider:
              • nvidia-nim  → integrate.api.nvidia.com (remote)
              • ollama      → local Ollama
              • vllm        → local vLLM
```

"Local" = "local to the sandbox's view of the network" (the gateway's internal
endpoint). The gateway then forwards to whichever provider is configured
(e.g. remote NVIDIA NIM).

### Flow A: LLM inference (always works)

```
OpenClaw agent  →  inference.local  →  OpenShell gateway  →  NVIDIA NIM (integrate.api.nvidia.com)
      │                    │                     │
   In sandbox        Special route         Gateway is outside sandbox,
                     (no egress policy)    so it can reach NVIDIA
```

- The agent calls `inference.local`.
- The gateway intercepts that and forwards to nvidia-nim.
- This path does **not** use the sandbox's network egress policy.
- Result: inference works; Nemotron 3 Super runs and returns text.

### Flow B: Tool execution (subject to policy)

NVIDIA NIM is only a language model API: text in, text out. It does **not**
run tools or fetch web pages.

To get the stock price, the **OpenClaw agent** uses its own tools (e.g. run
Python) and that Python code does something like:

```python
requests.get("https://query1.finance.yahoo.com/...")
```

That request is made **from inside the sandbox** and goes out as normal egress.
It is subject to the network policy. If Yahoo Finance is not in the allow list,
it gets blocked:

```
OpenClaw agent decides: "Run a Python script to fetch from Yahoo"
                              │
                              ▼
              Agent runs: python script.py
                              │
                              ▼
              Python does: requests.get("https://query1.finance.yahoo.com/...")
                              │
                              ▼
              Sandbox egress policy: BLOCKED (Yahoo not allowed)
                              │
                              ▼
              Connection fails → "DNS resolution fails"
```

Key points:

- NIM does **not** "call" a stock price tool. NIM only returns text
  (plans, reasoning, etc.).
- The **agent** interprets that text and runs tools (Python, curl, etc.)
  **inside the sandbox**.
- Those tool executions use normal egress and must be allowed by the
  sandbox policy.

### Summary table

| What | Who does it | Destination | Policy |
|------|-------------|-------------|--------|
| Get LLM response | Agent → gateway | `inference.local` | Not sandbox egress |
| Forward to LLM | Gateway | `integrate.api.nvidia.com` | Gateway (outside sandbox) |
| Fetch stock price | Python/curl (tool) | `query1.finance.yahoo.com` | Sandbox egress policy |

- Inference goes through the gateway and does **not** use the sandbox egress policy.
- The stock price fetch is a tool run inside the sandbox, so it is blocked
  until you allow Yahoo Finance (or similar) in the policy or approve it in
  `openshell term`.

---

## Optional: Switch Models at Runtime

```bash
# Nemotron 3 Nano (smaller, 30B)
openshell inference set --provider nvidia-nim --model nvidia/nemotron-3-nano-30b-a3b

# Back to Super (120B)
openshell inference set --provider nvidia-nim --model nvidia/nemotron-3-super-120b-a12b
```

No sandbox restart required. The change takes effect immediately.

---

## Architecture Reference

```
┌─────────────────────────────────────────────────────────┐
│  Host                                                   │
│                                                         │
│  nemoclaw CLI  →  OpenShell gateway  →  NVIDIA NIM      │
│       │               ↑                (cloud)          │
│       ▼               │                                 │
│  ┌────────────────────┼──────────────────────────────┐  │
│  │  OpenShell Sandbox │                              │  │
│  │                    │                              │  │
│  │  OpenClaw agent ───┘ (inference.local)            │  │
│  │       │                                           │  │
│  │       ├── Tool: curl/python → egress policy       │  │
│  │       │       (blocked unless allowed)            │  │
│  │       │                                           │  │
│  │       └── Filesystem: /sandbox (rw), /usr (ro)    │  │
│  └───────────────────────────────────────────────────┘  │
│                                                         │
│  openshell term  ← monitor + approve blocked requests   │
└─────────────────────────────────────────────────────────┘
```
