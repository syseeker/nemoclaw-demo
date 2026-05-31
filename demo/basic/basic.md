# Basic — Sandbox Policy & Network Control

Walk through NemoClaw's core sandbox features: deny-by-default network policy,
real-time request approval, inference routing, and custom policy creation.
This is the starting demo — run it first to understand how NemoClaw works
before moving on to more advanced scenarios.

## What you will learn

- How inference routes through `inference.local` to NVIDIA NIM
- Deny-by-default network policy in action
- Approving and denying egress requests via the OpenShell TUI
- Creating a custom network policy (e.g. finance) manually or with a coding companion
- Switching between CLI and TUI agent interfaces

## Overview

| Component | Role |
|-----------|------|
| **NemoClaw** | CLI that installs and manages sandboxed OpenClaw |
| **OpenShell** | Sandbox runtime (gateway, k3s, network policy) |
| **OpenClaw** | Agent that uses LLM inference and tools |
| **Nemotron 3 Super** | 120B reasoning model via NVIDIA NIM |

> **Setup first?** See [INSTALL.md](../../INSTALL.md) for prerequisites and installation. For DNS issues see [FAQ](../../FAQ.md#3-how-do-i-fix-dns-inside-the-sandbox).

---

## Phase 0: Create a Custom Finance Policy

The finance policy allows the agent to reach Yahoo Finance and Google Finance
for stock price lookups. Unlike built-in presets, this is a custom policy
you create yourself.

**Option A — Manual**: Create `nemoclaw-blueprint/policies/presets/finance.yaml`
with the following content:

```yaml
network_policies:
  finance:
    name: finance
    endpoints:
      - host: query1.finance.yahoo.com
        port: 443
        protocol: rest
        enforcement: enforce
        tls: terminate
        rules:
          - allow: { method: GET, path: "/**" }
      - host: query2.finance.yahoo.com
        port: 443
        protocol: rest
        enforcement: enforce
        tls: terminate
        rules:
          - allow: { method: GET, path: "/**" }
      - host: finance.yahoo.com
        port: 443
        protocol: rest
        enforcement: enforce
        tls: terminate
        rules:
          - allow: { method: GET, path: "/**" }
      - host: www.google.com
        port: 443
        protocol: rest
        enforcement: enforce
        tls: terminate
        rules:
          - allow: { method: GET, path: "/**" }
      - host: google.com
        port: 443
        protocol: rest
        enforcement: enforce
        tls: terminate
        rules:
          - allow: { method: GET, path: "/**" }

```

Then apply it:

```bash
nemoclaw <name> policy-add
# Select: finance
```

**Option B — With a coding companion**: Ask Cursor or Claude Code to create
a network policy that allows Yahoo Finance and Google Finance on port 443
with no binary restriction, then apply it with `nemoclaw <name> policy-add`.

---

## Phase 1: Connect & Run Demo Prompts (5 min)

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

> **Why specify curl in the prompt?** See [FAQ](../../FAQ.md#4-why-does-web_fetch-fail-when-curl-works) for details
> on `web_fetch` vs `exec` and binary restrictions.

---

## Phase 2: Split-Screen Walkthrough (5 min)

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

---

## Phase 3: Verify Inference & Status (1 min)

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

## Troubleshooting

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
