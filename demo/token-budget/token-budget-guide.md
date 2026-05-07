# Token Budget — Session Usage Cap

Monitor and cap per-session token usage so the agent stays within a
configurable budget. The agent checks cumulative input/output tokens
before every response and warns or refuses when the budget is exhausted.

## What you will learn

- Setting a native context-token cap via `agents.defaults.contextTokens`
- Installing a token-budget skill that enforces a session-wide limit
- Using `openclaw status --json` and `openclaw sessions --json` for structured token data
- Tuning `maxTokens` (per-turn output cap) vs `contextTokens` (session-wide context cap)
- Adjusting budget thresholds at runtime

**Reference:** [Basic demo](../basic/basic.md) · [OpenClaw skills](https://docs.openclaw.ai/tools/skills) · [OpenClaw CLI — sessions](https://docs.openclaw.ai/cli/sessions)

---

## Prerequisites

- A working NemoClaw sandbox ([INSTALL.md](../../INSTALL.md) Steps 1–2)
- Familiarity with `nemoclaw <sandbox> connect` and the OpenClaw TUI

---

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│  Sandbox                                                      │
│                                                               │
│  OpenClaw agent                                               │
│    │                                                          │
│    ├── AGENTS.md (mandatory: check budget every turn)         │
│    │                                                          │
│    ├── skills/token-budget/SKILL.md                           │
│    │     reads token-budget.json (max_tokens, warn_at_percent)│
│    │     runs  openclaw status --json                         │
│    │     compares usage vs budget                             │
│    │     → under budget: respond normally                     │
│    │     → near limit:   respond + warning footer             │
│    │     → over budget:  refuse, suggest session clear        │
│    │                                                          │
│    └── workspace/token-budget.json (user-editable config)     │
│                                                               │
│  openclaw.json                                                │
│    agents.defaults.contextTokens: 50000  (native cap)         │
│    models[].maxTokens: 4096              (per-turn output)    │
└──────────────────────────────────────────────────────────────┘
```

---

## How token limits work

There are three layers of token control:

| Layer | Config | Scope | Enforcement |
|-------|--------|-------|-------------|
| **Per-turn output** | `models[].maxTokens` in `openclaw.json` | Single response | Hard — API-level |
| **Context window** | `agents.defaults.contextTokens` in `openclaw.json` | Session context | Native OpenClaw |
| **Session budget** | `token-budget.json` + skill | Cumulative in+out | Soft — agent follows skill |

The install script sets all three.

---

## Step 1 — Install

```bash
cd demo/token-budget
./install.sh [sandbox-name]
```

The install script:
1. Uploads `skills/token-budget/SKILL.md` into the sandbox
2. Deploys `token-budget.json` config to the agent workspace
3. Appends a mandatory budget-check directive to `AGENTS.md`
4. Sets `agents.defaults.contextTokens` in `openclaw.json`
5. Clears sessions so the agent discovers the new skill

---

## Step 2 — Connect and verify

```bash
nemoclaw <sandbox-name> connect
```

In the TUI, send `/status`. You should see:

```
📚 Context: 0k/50k (0%)
```

The context cap should now show `50k` instead of the default `131k`.

---

## Step 3 — Test the budget

### Prompt 1: Normal usage

Send a simple message:

```
What is 2 + 2?
```

The agent should respond normally — well under budget.

### Prompt 2: Check budget awareness

```
How much of my token budget have I used?
```

The agent should run `openclaw status --json`, read `token-budget.json`, and
report your usage vs the 50k cap.

### Prompt 3: Approach the limit

Have a longer conversation. As you approach 80% of the budget (40k tokens),
the agent should start appending warnings:

```
⚠ Token budget: 41k/50k used (82%). Keep responses concise.
```

### Prompt 4: Hit the cap

Once you exceed 50k tokens, the agent should refuse:

```
Token budget exhausted (51k/50k used). Clear the session or start a new one to continue.
```

---

## Adjust the budget

Edit the config directly in the sandbox:

```bash
nemoclaw <sandbox-name> connect
```

Then inside the sandbox:

```bash
cat ~/.openclaw/workspace/token-budget.json
# Edit: change max_tokens or warn_at_percent
```

Or ask the agent:

```
Set my token budget to 100000 tokens
```

The agent can update `token-budget.json` for you.

To also update the native cap:

```bash
# On the host
python3 -c "
import json
p = '/path/to/openclaw.json'
d = json.load(open(p))
d['agents']['defaults']['contextTokens'] = 100000
json.dump(d, open(p, 'w'), indent=2)
"
```

---

## File structure

```
token-budget/
├── token-budget-guide.md              # This guide
├── install.sh                         # Deploy skill + config into sandbox
├── token-budget.json                  # Budget config template (50k default)
├── agents-md-snippet.md               # AGENTS.md directive (appended on install)
└── skills/token-budget/SKILL.md       # Skill: budget check + enforcement
```

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| `/status` still shows 131k context | `contextTokens` not applied. Re-run `./install.sh` or manually set it in `openclaw.json` inside the sandbox. |
| Agent doesn't check budget | Stale session. Clear: `echo '{}' > /sandbox/.openclaw-data/agents/main/sessions/sessions.json` and reconnect. |
| Agent ignores the cap and keeps responding | Soft enforcement — the skill is instructions, not a hard block. Reinforce by editing AGENTS.md or lowering `maxTokens` for shorter responses. |
| `openclaw status --json` fails | Fallback behavior: the agent responds normally without enforcement. Check OpenClaw version (`openclaw --version`). |
| Budget resets unexpectedly | Token counts are per-session. Clearing sessions resets the count. The `token-budget.json` config persists. |

---

## See also

- [Basic demo](../basic/basic.md)
- [Telegram bridge demo](../telegram-bridge/telegram-bridge.md)
- [INSTALL.md](../../INSTALL.md)
- [INSTALL-OPTIONAL.md](../../INSTALL-OPTIONAL.md) — model switching at runtime
