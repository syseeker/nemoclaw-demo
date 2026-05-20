# Telegram Bridge — Setup & Use Cases

Interact with the OpenClaw agent through Telegram instead of the terminal.

## What you will learn

- How to create a Telegram bot and connect it to the sandbox
- Sending messages to the agent via Telegram
- Scheduling recurring agent tasks (heartbeat, cron jobs)
- Switching the LLM model at runtime via Telegram
- Restricting bot access by Telegram user ID

> **Reference**: [Set Up the Telegram Bridge](https://docs.nvidia.com/nemoclaw/latest/deployment/set-up-telegram-bridge.html)
>
> **See also**: [Telegram Heartbeat](../telegram-heartbeat/heartbeat.md) · [Telegram hourly nudge](../telegram-hourly-nudge/hourly-nudge.md) · [Remote GPU](../remote-gpu/remote-gpu.md) · [Token budget](../token-budget/token-budget-guide.md)

---

## Prerequisites

- A running NemoClaw sandbox (complete [INSTALL.md](../../INSTALL.md) Steps 1–2).
- A Telegram bot token from [@BotFather](https://t.me/BotFather).

---

## Step 1: Create a Telegram Bot

Open Telegram and send `/newbot` to **@BotFather**. Follow the prompts to
create a bot and receive a bot token.

## Step 2: Configure Telegram during onboarding

Telegram is configured during `nemoclaw onboard`. Provide your bot token
either as an environment variable before running the wizard, or when prompted:

```bash
export TELEGRAM_BOT_TOKEN=<your-bot-token>
nemoclaw onboard
```

During onboarding step **Messaging channels**, toggle Telegram on. The wizard
stores the token securely in an OpenShell provider and bakes the channel
config into the sandbox image. The agent inside the sandbox receives a
placeholder — never the real token.

If you already completed onboarding with Telegram enabled, you're set.

## Step 3: Send a Message

Open Telegram, find your bot, and send `/start`, then any message. OpenClaw
inside the sandbox handles Telegram natively — no host-side bridge process
is needed.

## Step 4: Start cloudflared (optional)

`nemoclaw start` launches a **cloudflared tunnel** that gives your dashboard
a public URL. It does **not** affect Telegram — Telegram works as long as
the sandbox is running.

```bash
nemoclaw start
nemoclaw status
```

---

## Use Case A: HEARTBEAT — Sandbox Health Monitor

**Scenario**: Post periodic health summaries to a Telegram chat using an
OpenClaw **skill** and a **cron job** on the host.

See [**Telegram Heartbeat**](../telegram-heartbeat/heartbeat.md) for full
step-by-step instructions covering skill installation, cron setup, and the
end-to-end pipeline.

---

## Use Case B: CRON Job — Scheduled Agent Tasks

**Scenario**: Schedule the agent to perform a task on a recurring basis and
post results to Telegram. For example, fetch the NVIDIA stock price every
morning at 9:00 AM.

The pattern is the same as the heartbeat: create a **skill**, invoke it via
`openclaw agent` through OpenShell, and pipe the output to Telegram. See
[Telegram Heartbeat](../telegram-heartbeat/heartbeat.md) for the template, and
[Telegram hourly nudge](../telegram-hourly-nudge/hourly-nudge.md) for another
worked example using the `philosopher-nudge` skill.

---

## Use Case C: Switch LLM via Telegram

**Scenario**: Send a Telegram message to switch the inference model at runtime
without SSH-ing into the instance.

**Example messages to the bot**:

- *"Switch to Nemotron 3 Nano for faster responses"*
- *"Switch back to Nemotron 3 Super for better reasoning"*

The agent uses the `exec` tool to run the model switch:

```bash
openshell inference set --provider nvidia-nim --model nvidia/nemotron-3-nano-30b-a3b
```

**What to expect in Telegram**:

- The bot confirms the model switch
- Subsequent responses come from the new model

**What to show**:

- Send a complex reasoning prompt -> agent responds using Super (120B)
- Switch to Nano via Telegram message
- Send the same prompt -> faster response, possibly less detailed
- Switch back to Super via Telegram message -> full reasoning restored

---

## Use Case D: Token Usage Tracker

**Scenario**: Monitor token consumption in real time. The agent tracks
cumulative token usage and posts an update to Telegram whenever the count
changes — useful for cost awareness and quota management.

<!-- TODO: implementation details — poll inference logs or gateway metrics
     for token counts, post delta to Telegram when threshold is crossed -->

**Example Telegram updates**:

- *"Token usage: 12,450 total (+1,230 since last update) — model: Nemotron 3 Super"*
- *"Token usage: 15,800 total (+3,350 since last update) — model: Nemotron 3 Nano"*

**What to show**:

- Send a few prompts via Telegram and watch the token counter update
- Switch models (Use Case C) and compare token consumption per prompt
- Set a token budget threshold and get an alert when approaching the limit

---

## Stop cloudflared

```bash
nemoclaw stop
```

This stops cloudflared (the public URL tunnel). It does **not** stop the
sandbox or Telegram — those keep running independently.
