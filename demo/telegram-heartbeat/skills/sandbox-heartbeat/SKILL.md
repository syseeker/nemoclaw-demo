---
name: sandbox-heartbeat
description: Produce a single plain-text health summary of the NemoClaw sandbox suitable for a Telegram ping.
user-invocable: true
---

# Sandbox heartbeat (Telegram)

## Purpose

Produce **one short plain-text health block** for a scheduled Telegram ping.

## Use when

- The user runs **`/sandbox-heartbeat`**.
- Automation invokes you with: *use skill **sandbox-heartbeat***.

## How to collect data

Run these shell commands **one at a time** with the `exec` tool:

1. `date '+%Y-%m-%d %H:%M %Z'`
2. `openclaw models list 2>/dev/null | grep -v Warning | grep -v '^$' | tail -1`
3. `hostname`

Each command is a separate exec call. Do not combine them.

## Output contract (strict)

Return **exactly one block** of plain text:

```
NemoClaw heartbeat OK
Time: <result of date command>
Model: <model line from openclaw models list>
Host: <result of hostname>
```

Do **not** add:

- Markdown, bullets, or quotation marks
- Preamble ("Here is your heartbeat:")
- Explanations before or after the block
- Extra blank lines or decorations
