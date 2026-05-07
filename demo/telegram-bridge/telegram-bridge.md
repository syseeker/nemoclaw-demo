# Telegram Bridge — HEARTBEAT Health Monitor

Interact with the OpenClaw agent through Telegram instead of the terminal.
This demo sets up the Telegram bridge and configures a HEARTBEAT that posts
periodic sandbox health summaries to a Telegram chat.

## What you will learn

- How to create a Telegram bot and connect it to the sandbox
- Starting and stopping the Telegram bridge and cloudflared tunnel
- Setting up a HEARTBEAT for periodic health checks
- Attaching a Markdown file to heartbeat messages
- Restricting bot access by Telegram chat ID

> **Reference**: [Set Up the Telegram Bridge](https://docs.nvidia.com/nemoclaw/latest/deployment/set-up-telegram-bridge.html)
>
> **See also**: [Telegram hourly nudge](../telegram-hourly-nudge/hourly-nudge.md) (CRON jobs) · [Remote GPU](../remote-gpu/remote-gpu.md) (model switching) · [Token budget](../token-budget/token-budget-guide.md) (token usage tracking)

---

## Prerequisites

- A running NemoClaw sandbox (complete [INSTALL.md](../../INSTALL.md) Steps 1–2).
- A Telegram bot token from [@BotFather](https://t.me/BotFather).

---

## Step 1: Create a Telegram Bot

Open Telegram and send `/newbot` to **@BotFather**. Follow the prompts to
create a bot and receive a bot token.

## Step 2: Start the Telegram Bridge

```bash
export TELEGRAM_BOT_TOKEN=<your-bot-token>
nemoclaw start
```

The `start` command launches:

- **Telegram bridge** — forwards messages between Telegram and the agent.
- **cloudflared tunnel** — provides external access to the sandbox.

Verify the services are running:

```bash
nemoclaw status
```

## Step 3: Send a Message

Open Telegram, find your bot, and send a message. The bridge forwards it to
the OpenClaw agent inside the sandbox and returns the response.

### Restrict access by chat ID (optional)

```bash
export ALLOWED_CHAT_IDS="123456789,987654321"
nemoclaw start
```

---

## Use Case A: HEARTBEAT — Sandbox Health Monitor
**Scenario**: Your bot posts **periodic health messages** to a Telegram chat you choose. Each tick summarizes sandbox readiness, inference (provider + model), gateway connectivity, and (optionally) hints about policy / egress denials in recent logs.
**Important**: NemoClaw starts a small **host-side** process (`telegram-heartbeat.js`) alongside the Telegram bridge when you set **`TELEGRAM_HEARTBEAT_CHAT_ID`** and **`TELEGRAM_BOT_TOKEN`**. It calls `openshell` on the host to inspect the sandbox and sends `sendMessage` to Telegram directly.
### How it is enabled
| Variable | Required | Purpose |
|----------|----------|---------|
| `TELEGRAM_BOT_TOKEN` | Yes | Same token as the bridge; heartbeat will not start without it. |
| `TELEGRAM_HEARTBEAT_CHAT_ID` | Yes | Numeric chat id where pings are sent (private DM or group). |
| `HEARTBEAT_INTERVAL_SEC` | No | Seconds between pings (default **300**). |
| `HEARTBEAT_POLICY_LOG` | No | Set to **`1`** to scan recent sandbox logs for denial-style markers (slower; can time out on huge logs). |
| `HEARTBEAT_MARKDOWN_FILE` | No | Host path to a UTF-8 `.md` file; each tick also sends that file after the health message (see [below](#optional-markdown-file-heartbeatmd)). Alias: `TELEGRAM_HEARTBEAT_MARKDOWN_FILE`. |
| `HEARTBEAT_MARKDOWN_AS_PLAIN_APPEND` | No | Set to **`1`** to append the file into the **same** message as the health block as plain text (4096 char limit). Omit for default: follow-up message(s) with Telegram Markdown. |
`SANDBOX_NAME` is taken from your NemoClaw registry default when you run `nemoclaw start` (so it matches `nemoclaw status` / PID files under `/tmp/nemoclaw-services-<name>/`). If you customize the default sandbox name, heartbeat probes **that** name.
### Step-by-step
**1. Find your Telegram chat id (numeric)**
- Message [@userinfobot](https://t.me/userinfobot) and note `Id`, or
- Send any message to your bot, then inspect the bridge log on the host:
  ```bash
  grep -E '^\[[0-9]+\]' /tmp/nemoclaw-services-<sandbox>/telegram-bridge.log | tail -1
  ```
  A line like `[123412345] Name: …` means your chat id is `123412345`.
**2. Export variables and start services**
Shortest path (adjust interval if you want faster demo ticks):
```bash
export TELEGRAM_BOT_TOKEN='<your-bot-token>'
export TELEGRAM_HEARTBEAT_CHAT_ID='<your-chat-id>'
export HEARTBEAT_INTERVAL_SEC=120   # optional; omit for default 300s
# export HEARTBEAT_POLICY_LOG=1     # optional: include log-based denial hints
# export HEARTBEAT_MARKDOWN_FILE="$HOME/heartbeat.md"   # optional: see below
# export HEARTBEAT_MARKDOWN_AS_PLAIN_APPEND=1           # optional: merge .md into health message as plain text
nemoclaw start
```
Instead of `export`, you can put the same keys in `~/.nemoclaw/credentials.json`; `nemoclaw start` loads them for the service script.
**3. Confirm heartbeat is running**
```bash
nemoclaw status
```
You should see a line indicating **Telegram pings enabled** (or equivalent “Heartbeat” wording in the services banner).
Process check (avoid matching `tail -f` on log files):
```bash
pgrep -af 'telegram-heartbeat\.js'
```
Logs:
```bash
tail -f /tmp/nemoclaw-services-<sandbox>/telegram-heartbeat.log
```
Replace `<sandbox>` with your default sandbox name (often `nemoclaw`).

### Optional Markdown file (`heartbeat.md`)
Save any **`.md` on the host** where `nemoclaw start` runs (e.g. `$HOME/heartbeat.md`) and set **`HEARTBEAT_MARKDOWN_FILE`** to that path. Each tick you still get the **health check** message first; **then** the file is sent as **follow-up** Telegram Markdown (with plain-text retry if Telegram rejects the markup), unless **`HEARTBEAT_MARKDOWN_AS_PLAIN_APPEND=1`**, in which case health + `---` + file contents arrive in **one** message as plain text. 

---

## Stop the Services

```bash
nemoclaw stop
```
