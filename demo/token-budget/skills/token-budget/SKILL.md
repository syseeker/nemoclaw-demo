---
name: token-budget
description: "Session token budget enforcement. MUST run at the start of every turn. Checks cumulative token usage against a configurable cap and warns or refuses when the budget is exhausted."
---

# Token Budget — Session Usage Monitor

You MUST check the token budget **before generating any response**. This is non-negotiable.

## How to Check

1. Read `~/.openclaw/workspace/token-budget.json` for the budget config.
2. Run this command to get current session token usage:

```bash
openclaw status --json 2>/dev/null
```

3. From the JSON output, extract `tokens.input` and `tokens.output` (total tokens used this session).
4. Compute `total = tokens.input + tokens.output`.

## Enforcement Rules

- If `total >= max_tokens` from `token-budget.json`:
  - Reply ONLY with: "Token budget exhausted (TOTAL/MAX used). Clear the session or start a new one to continue."
  - Do NOT generate any other content. Stop immediately.

- If `total >= max_tokens * warn_at_percent / 100`:
  - Respond normally but append a warning line at the end:
    "⚠ Token budget: TOTAL/MAX used (PERCENT%). Keep responses concise."
  - Prefer shorter, more direct answers to conserve budget.

- If `total < max_tokens * warn_at_percent / 100`:
  - Respond normally. No warning needed.

## Fallback

If `openclaw status --json` fails or `token-budget.json` is missing, respond normally without budget enforcement but throw warning. Do not block the user due to a monitoring failure.

## Config Format

`~/.openclaw/workspace/token-budget.json`:

```json
{
  "max_tokens": 50000,
  "warn_at_percent": 80
}
```

The user can change these values at any time by editing the file or asking you to update it.
