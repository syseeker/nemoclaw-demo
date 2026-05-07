# FAQ

1. [What is `inference.local`?](#1-what-is-inferencelocal)
2. [How do inference and tool execution differ?](#2-how-do-inference-and-tool-execution-differ)
3. [How do I fix DNS inside the sandbox?](#3-how-do-i-fix-dns-inside-the-sandbox)
4. [Why does `web_fetch` fail when `curl` works?](#4-why-does-web_fetch-fail-when-curl-works)
5. [Where should I store credentials — host or sandbox?](#5-where-should-i-store-credentials--host-or-sandbox)

---

## 1. What is `inference.local`?

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

---

## 2. How do inference and tool execution differ?

There are two separate network flows in the sandbox. Understanding the
difference is key to explaining why some requests work and others get blocked.

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

### Summary

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

## 3. How do I fix DNS inside the sandbox?

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
> the gateway process is restarted (see below).

---

## 4. Why does `web_fetch` fail when `curl` works?

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

## 5. Where should I store credentials — host or sandbox?

**Short answer**: Keep credentials on the NemoClaw host. Inject them into the
sandbox only when needed, scoped to a single session.

### Why not store them in the sandbox?

The sandbox runs **LLM-generated code** — it is inherently the least trusted
environment. That is the entire reason NemoClaw and OpenShell exist: to contain
what the agent does. If you persist secrets inside the sandbox (e.g. in a file
or environment variable), any code the agent writes or executes has direct
access to them.

### The recommended pattern

The philosopher-nudge pipeline is a good example of the right design:

```
Host (trusted)                          Sandbox (untrusted)
─────────────────                       ────────────────────
~/.config/nemoclaw-telegram-nudge.env
  • TELEGRAM_BOT_TOKEN
  • NVIDIA_API_KEY
  • TELEGRAM_NUDGE_CHAT_ID

crontab (schedule)
  └─► run-telegram-nudge.sh
        │
        ├─ Injects NVIDIA_API_KEY       ──► openclaw agent runs
        │  via SSH (per-session,             philosopher-nudge skill,
        │  base64-encoded env var)           returns one line of text
        │                               ◄──
        ├─ Receives agent output
        │
        └─ Posts to Telegram using
           TELEGRAM_BOT_TOKEN
           (never enters the sandbox)
```

| Concern | Where | Why |
|---------|-------|-----|
| Secrets storage | Host (`~/.config/...env`) | Only the host is under your direct control |
| Schedule (cron) | Host (`crontab -e`) | Prevents the agent from rescheduling itself |
| LLM inference | Sandbox (via `openclaw agent`) | Contained by OpenShell policies |
| External delivery | Host (`hourly_telegram_nudge.py`) | Requires bot token, which stays on the host |

### Pros of keeping credentials on the host

- **Least privilege** — The sandbox only receives `NVIDIA_API_KEY` for the
  duration of one agent run, injected via SSH. It never sees
  `TELEGRAM_BOT_TOKEN` at all.
- **Blast radius** — If the agent goes rogue or the sandbox is compromised,
  the attacker cannot exfiltrate your bot token or impersonate your bot.
- **Auditability** — `crontab -l` on the host gives you a single source of
  truth for what runs and when. Sandbox-side schedules can be modified by
  the agent via natural language.
- **Reliability** — Host cron is a battle-tested Linux daemon. Sandbox cron
  depends on the OpenClaw runtime being healthy.

### Cons / trade-offs

- **More moving parts on the host** — You maintain wrapper scripts
  (`run-telegram-nudge.sh`), env files, and crontab entries outside the
  sandbox.
- **Harder to set up initially** — Compared to telling the agent "send a
  Telegram message every hour," the host-side approach requires manual
  scripting and SSH plumbing.
- **Secrets are still on disk** — The env file on the host is only as secure
  as the host itself. Use appropriate file permissions (`chmod 600`) and
  avoid committing it to version control.

### When to keep credentials on the host

- The job **directly calls an external API** with credentials (Telegram,
  Slack, email, etc.).
- The job **injects API keys** into the sandbox for LLM inference.
- You want to **control the schedule** and prevent the agent from modifying
  it.

### When sandbox-side scheduling is acceptable

- The job lives **entirely inside the sandbox** and does not need secrets
  (e.g. log rotation, workspace cleanup).
- The job uses **internal OpenClaw channels** (`openclaw message send`) and
  a trusted host-side bridge (like `telegram-bridge.js`) handles external
  delivery — so the sandbox never touches external credentials.

### The guiding principle

**Whoever holds the secrets holds the trigger.** If a cron job needs to
inject secrets or deliver results to an external service, the host should
own the schedule. The sandbox should only generate content; the host decides
when and how to deliver it.
