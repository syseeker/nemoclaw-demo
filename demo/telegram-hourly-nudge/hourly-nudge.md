# Telegram — Hourly philosopher nudge (cron + OpenClaw skill)

In this tutorial you will wire up an **hourly Telegram nudge** powered by
NemoClaw. A cron job on the host asks the **LLM inside the sandbox** — guided
by an OpenClaw **skill** — to compose one short, philosopher-style reflective
question, then posts it to a Telegram chat. Because the **Telegram bridge**
(`nemoclaw start`) stays running, anyone in that chat can **reply to the nudge**
and carry on a conversation with the agent, turning a one-line prompt into a
back-and-forth exchange of ideas.

Each automated nudge looks like:

> **Ting tong,** *current local time* **—** *one short reflective question*

Example: `Ting tong, 2026-04-04 14:00 +08 — Is rest part of work, or its interruption?`

## What you will learn

- Installing an OpenClaw **workspace skill** (`philosopher-nudge`) inside a sandbox
- Generating LLM content from the host via **`openclaw agent`** over SSH
- Sending that content to Telegram with a lightweight **Python sender**
- Scheduling the pipeline with **cron** (timezone-aware, waking hours only)
- Letting users **reply** through the NemoClaw Telegram bridge for two-way chat

See [How it fits together](#how-it-fits-together) at the end for a diagram of the
full flow (Cron → Host → OpenShell → Sandbox/OpenClaw → Telegram → bridge).

**Reference:** [Telegram bridge (NVIDIA)](https://docs.nvidia.com/nemoclaw/latest/deployment/set-up-telegram-bridge.html) · [Telegram bridge demo](../telegram-bridge/telegram-bridge.md) · [OpenClaw skills](https://docs.openclaw.ai/tools/skills)

---

## Before you start

- Finish a normal **Telegram + NemoClaw** setup ([Telegram bridge demo](../telegram-bridge/telegram-bridge.md)):
  you need a bot token, `nemoclaw start`, and a working sandbox with `openclaw`.
- **On the host** (same machine as `openshell` / `cron`): Python 3, `ssh`, `base64`.
- Know **one Telegram chat id** where the bot may post (DM or group; often a
  negative number for groups). See [FAQ: find nudge chat id](#faq-find-nudge-chat-id).

---

## Step 1 — Keep the bridge running

Replies in Telegram go through the bridge, same as the [Telegram bridge demo](../telegram-bridge/telegram-bridge.md).

```bash
export TELEGRAM_BOT_TOKEN="…"
export NVIDIA_API_KEY="nvapi-…"
# Optional: export ALLOWED_CHAT_IDS="…"
nemoclaw start
```

Leave this running (or use your usual process manager). Optional chat filtering
and tokens are covered in the [FAQ: bot token vs chat ids](#faq-bot-token-vs-chats).

---

## Step 2 — Install the `philosopher-nudge` skill in the sandbox

The skill file in this repo is [`skills/philosopher-nudge/SKILL.md`](skills/philosopher-nudge/SKILL.md).
OpenClaw should see it under **both** of these inside the sandbox (create dirs if needed):

- `/sandbox/.openclaw/skills/philosopher-nudge/SKILL.md`
- `$HOME/.openclaw/skills/philosopher-nudge/SKILL.md` (often `/home/sandbox/...`)

**Fast path** (if you have the NemoClaw repo on the host):

```bash
export SANDBOX_NAME="your-sandbox"
export SKILL_ID="philosopher-nudge"
export SKILL_FILE="${HOME}/NemoClaw-Demo/demo/telegram-hourly-nudge/skills/philosopher-nudge/SKILL.md"
bash "${HOME}/NemoClaw/test/e2e/e2e-cloud-experimental/features/skill/add-sandbox-skill.sh"
```

**Or** open a shell in the sandbox (`nemoclaw <sandbox> connect`), create the
dirs, and paste the skill into both paths (e.g. `nano`). **Or** use
`openshell sandbox upload` from the host — see [FAQ: install skill other ways](#faq-install-skill-other-ways).

---

## Step 2b — Upload `AGENTS.md` (feedback recording)

The agent inside the sandbox reads
`~/.openclaw/workspace/AGENTS.md` at the start of **every** session —
including Telegram bridge replies. This repo ships a template
[`templates/AGENTS.md`](templates/AGENTS.md) that includes a
**Telegram Feedback** section telling the agent to record every reply
(who, what, sentiment) into its daily memory log
(`memory/YYYY-MM-DD.md`). Both the philosopher-nudge and chinese-jokes
skills read that memory before generating, so the agent learns which
topics and styles land well over time.

**Upload from host** (replace `<sandbox>` with your sandbox name):

```bash
openshell sandbox upload "<sandbox>" \
  "${HOME}/NemoClaw-Demo/demo/telegram-hourly-nudge/templates/AGENTS.md" \
  /sandbox/.openclaw/workspace/
```

> **Already have a customized `AGENTS.md`?** Don't overwrite it. Instead,
> append just the feedback section. Connect to the sandbox and run:
>
> ```bash
> nemoclaw <sandbox> connect
> cat >> ~/.openclaw/workspace/AGENTS.md << 'EOF'
>
> ## Telegram Feedback — Record Every Reply
>
> When a user **replies** to any message in Telegram (via the NemoClaw bridge),
> **append** a short entry to the daily memory log
> (`memory/YYYY-MM-DD.md`, where `YYYY-MM-DD` is today's date).
>
> Each entry should include:
>
> - **Timestamp** (HH:MM)
> - **Who** replied (Telegram display name if available)
> - **What** they said (brief summary or direct quote if short)
> - **Sentiment** — liked / disliked / suggested topic / asked follow-up
> - **Action** — any follow-up you took (e.g. replied with another joke, clarified, switched topic)
>
> This applies to **all** scheduled nudges (philosopher nudge, joke nudge, or
> any future nudge type). Recording feedback lets you learn what lands well and
> adjust your tone, topics, and style over time.
> EOF
> ```

**Verify** (inside the sandbox):

```bash
tail -5 ~/.openclaw/workspace/AGENTS.md
```

You should see the "Telegram Feedback — Record Every Reply" heading.

---

## Step 3 — Config + wrapper (copy from this repo)

This repo ships two templates in [`templates/`](templates/). Copy them to
your home directory and fill in the blanks:

**3a — Environment file** (secrets + settings):

```bash
mkdir -p ~/.config
cp "${HOME}/NemoClaw-Demo/demo/telegram-hourly-nudge/templates/nemoclaw-telegram-nudge.env.example" \
   ~/.config/nemoclaw-telegram-nudge.env
chmod 600 ~/.config/nemoclaw-telegram-nudge.env
```

Open it in an editor and fill in your real values:

```bash
nano ~/.config/nemoclaw-telegram-nudge.env
```

You need at minimum: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_NUDGE_CHAT_ID`,
`NVIDIA_API_KEY`, `SANDBOX_NAME`. Set `PHILOSOPHER_THEME` to `life`, `work`,
`games`, or any custom words — see the skill for the full list.

Save and exit (`Ctrl+O`, `Enter`, `Ctrl+X` in nano).

**3b — Cron wrapper script:**

```bash
mkdir -p ~/bin
cp "${HOME}/NemoClaw-Demo/demo/telegram-hourly-nudge/templates/run-telegram-nudge.sh" \
   ~/bin/run-telegram-nudge.sh
chmod +x ~/bin/run-telegram-nudge.sh
```

The wrapper does four things (see comments inside the file):

1. **Sources** your `.env` for secrets
2. **Fixes `PATH`** so cron can find `openshell` (under `~/.local/bin`)
3. Runs **`run_philosopher_nudge_llm.sh`** — SSHs into the sandbox, runs
   `openclaw agent` with the philosopher-nudge skill, prints one "Ting tong, …"
   line
4. **Pipes** that line into **`hourly_telegram_nudge.py --stdin`**, which POSTs
   it to Telegram

If this repo is **not** at `~/NemoClaw-Demo`, edit the `NEMOCLAW_DEMO_ROOT`
line at the top of your copied wrapper.

**3c — Make the pipeline scripts executable** (once):

```bash
chmod +x ~/NemoClaw-Demo/demo/telegram-hourly-nudge/scripts/run_philosopher_nudge_llm.sh
chmod +x ~/NemoClaw-Demo/demo/telegram-hourly-nudge/scripts/hourly_telegram_nudge.py
```

---

## Step 4 — Test once, then set up cron

**Smoke test** — run the wrapper (it pipes the LLM line straight to Telegram):

```bash
~/bin/run-telegram-nudge.sh
```

Stderr shows progress; when the LLM returns you should see:

```
run_philosopher_nudge_llm: extracted nudge (…chars) → send to Telegram pipeline
hourly_telegram_nudge: OK — message sent to Telegram.
```

If it sits quiet for a long time, see [FAQ: hang or pairing](#faq-hang-or-pairing).
If no message arrives on Telegram, see [FAQ: expected output](#faq-expected-output).

**Set up cron** — open the cron editor:

```bash
crontab -e
```

This opens a text editor (often nano or vi). Add these **two lines** at the
bottom of the file (adjust the home path if yours is not `/home/ubuntu`):

```cron
0 0-15,22-23 * * * /home/ubuntu/bin/run-telegram-nudge.sh >> /home/ubuntu/.local/log/telegram-nudge.log 2>&1
```

Save and exit (`Ctrl+O`, `Enter`, `Ctrl+X` in nano; `:wq` in vi).

Create the log directory so the first run does not fail:

```bash
mkdir -p ~/.local/log
```

Cron will now run the nudge **every hour from 06:00 to 23:00** Singapore time
(no 00:00–05:00 runs). Check the log anytime with:

```bash
tail -20 ~/.local/log/telegram-nudge.log
```

---

## Step 5 — Verify the bridge sees replies

After a nudge lands in Telegram, someone can **reply** in the same chat. The
NemoClaw bridge forwards those replies to OpenClaw and returns a response.

To confirm the bridge is picking up messages, check its log on the **host**
(replace `clawpit` with your sandbox name):

```bash
tail -100 /tmp/nemoclaw-services-clawpit/telegram-bridge.log
```

You should see lines like **`[<chatId>] <userName>: <text>`** for each incoming
message and **`[<chatId>] agent: <response>…`** for the agent's reply. If the
log only shows the startup banner, see [FAQ: group but log empty](#faq-bridge-no-group-messages).

To follow messages in real time:

```bash
tail -f /tmp/nemoclaw-services-clawpit/telegram-bridge.log
```

---

## What to show in a demo

1. **Scheduled nudge** — show a Telegram message arriving on the hour.
2. **Reply** — type a follow-up in the same chat; the NemoClaw bridge forwards
   it to OpenClaw and returns the agent's reply, continuing the conversation.
3. **Theme toggle** — change `PHILOSOPHER_THEME` in the `.env` (e.g. `work` →
   `games`), run the wrapper manually, and show the different style.
4. **Skill-only** — point out that you did **not** edit `SOUL.md` or
   `IDENTITY.md`; the nudge is driven entirely by the skill file.

---

## Customizing

- **Theme**: change **`PHILOSOPHER_THEME`** in your `.env` file — `life`, `work`,
  `games`, `love`, `hobby`, `nature`, or freeform text like `friendship and loyalty`.
- **Skill rules & output format**: edit
  [`skills/philosopher-nudge/SKILL.md`](skills/philosopher-nudge/SKILL.md),
  re-upload to the sandbox (Step 2).
- **Cron schedule**: edit the crontab line — e.g. `*/30 6-23 * * *` for every
  30 minutes, or `0 9,12,18 * * *` for three fixed times.
- **Multiple themes per day**: create several wrapper copies
  (`run-nudge-work.sh`, `run-nudge-games.sh`) each sourcing a different `.env`,
  then point separate crontab lines at them.
- **Switch to Chinese jokes**: install the `chinese-jokes` skill
  ([`skills/chinese-jokes/SKILL.md`](skills/chinese-jokes/SKILL.md)) into the
  sandbox (same process as Step 2), then change the LLM script line in your
  cron wrapper from `run_philosopher_nudge_llm.sh` to `run_joke_nudge_llm.sh`.
  Jokes are localized for Malaysian / Singaporean Chinese and end with
  `哈哈` or `Meow~~`. Set `JOKE_TOPIC` in your `.env` to force a category
  (e.g. `方言梗`, `吃的`, `家庭`) or leave it empty for random.

---

## How it fits together

```
┌──────────┐  every hour   ┌─────────────────────────────────────────────┐
│  Cron    │──────────────▸│  ~/bin/run-telegram-nudge.sh  (Host)       │
└──────────┘               │                                             │
                           │  1. source .env  (secrets, theme, sandbox)  │
                           │  2. fix PATH for openshell                  │
                           │  3. run_philosopher_nudge_llm.sh ──┐        │
                           │  4. hourly_telegram_nudge.py  ◂────┘ pipe   │
                           └──────────┬────────────────────┬─────────────┘
                                      │ SSH via openshell  │ HTTPS POST
                                      ▼                    ▼
                           ┌──────────────────┐   ┌──────────────────┐
                           │  OpenShell       │   │  Telegram API    │
                           │  Sandbox         │   │  (sendMessage)   │
                           │                  │   └────────┬─────────┘
                           │  openclaw agent  │            │
                           │  + philosopher-  │            ▼
                           │    nudge skill   │   ┌──────────────────┐
                           │  (LLM: Nemotron) │   │  Telegram Chat   │
                           └──────────────────┘   │  "Ting tong …"   │
                                                  └────────┬─────────┘
                                                           │ user replies
                                                           ▼
                           ┌──────────────────┐   ┌──────────────────┐
                           │  NemoClaw Bridge │◂──│  Telegram Bot    │
                           │  (nemoclaw start)│──▸│  getUpdates      │
                           │  on Host         │   └──────────────────┘
                           │        │         │
                           │        ▼         │
                           │  OpenClaw agent  │
                           │  in Sandbox      │
                           └──────────────────┘
```

**Top half — scheduled nudge (cron):** Cron fires the wrapper on the host. The
script SSHs into the sandbox through **OpenShell**, runs **`openclaw agent`**
with the **philosopher-nudge** skill to generate one line, then pipes it to the
Python sender which POSTs to the **Telegram API**.

**Bottom half — two-way chat (bridge):** The user replies in Telegram. The
**NemoClaw bridge** (`nemoclaw start`, long-polling `getUpdates`) picks up the
reply and forwards it to the **OpenClaw agent** inside the sandbox. The agent's
response goes back to Telegram through the bridge.

---

## Troubleshooting (quick)

| Symptom | Likely fix |
|---------|------------|
| `No such file` for `~/bin/run-telegram-nudge.sh` | `mkdir -p ~/bin`, then copy the template |
| `openshell not on PATH` in cron | Use the template wrapper's `export PATH=…` or set `PATH` in crontab |
| `no Ting tong line` / `timed out` | Skill install, pairing, `openshell term`, or increase timeout |
| Telegram `400` chat not found | Wrong `TELEGRAM_NUDGE_CHAT_ID`; bot not in group; no DM `/start`; supergroup id `-100…` |
| Replies ignored | Bridge down, `ALLOWED_CHAT_IDS`, or group privacy |
| Group: log only shows banner | [FAQ #5: group messages not in log](#faq-bridge-no-group-messages) |
| Stuck session | Rare: remove stale `.jsonl.lock` under sandbox sessions |

---

## FAQ

1. [Bot token vs ALLOWED_CHAT_IDS vs TELEGRAM_NUDGE_CHAT_ID](#faq-bot-token-vs-chats)
2. [How do I find TELEGRAM_NUDGE_CHAT_ID?](#faq-find-nudge-chat-id)
3. [Where do I get / set TELEGRAM_BOT_TOKEN?](#faq-bot-token)
4. [How do I watch incoming messages (bridge log)?](#faq-bridge-incoming-messages)
5. [Group messages not appearing in bridge log](#faq-bridge-no-group-messages)
6. [How else can I install the skill files?](#faq-install-skill-other-ways)
7. [How do I list or try the skill in the sandbox?](#faq-try-skill)
8. [The smoke test or cron run seems to hang](#faq-hang-or-pairing)
9. [What should I see in the terminal or cron log?](#faq-expected-output)
10. [Optional env knobs](#faq-env-knobs)
11. [Do I need SOUL.md / IDENTITY.md / USER.md?](#faq-soul-identity)
12. [How do I find ALLOWED_CHAT_IDS for a group?](#faq-allowed-chat-ids-group)

<a id="faq-bot-token-vs-chats"></a>

### 1. Bot token vs `ALLOWED_CHAT_IDS` vs `TELEGRAM_NUDGE_CHAT_ID`

| Setting | Role |
|--------|------|
| **`TELEGRAM_BOT_TOKEN`** | Secret from [@BotFather](https://t.me/BotFather); identifies the bot everywhere. |
| **`ALLOWED_CHAT_IDS`** | Optional for **`nemoclaw start`** only: which chats may *message* the agent. Omit to allow all. |
| **`TELEGRAM_NUDGE_CHAT_ID`** | Used by **`hourly_telegram_nudge.py`**: *where to send* the scheduled line (one id). |

The bridge does **not** read `TELEGRAM_NUDGE_CHAT_ID`. If you lock down
`ALLOWED_CHAT_IDS`, include every chat that should **both** get nudges **and**
talk to the agent.

<a id="faq-find-nudge-chat-id"></a>

### 2. How do I find `TELEGRAM_NUDGE_CHAT_ID`?

Use [@getidsbot](https://t.me/getidsbot) or similar **in that chat**. Groups are
often **negative** (many supergroups use **`-100…`**).

<a id="faq-bot-token"></a>

### 3. Where do I get / set `TELEGRAM_BOT_TOKEN`?

From **[@BotFather](https://t.me/BotFather)** only (`/newbot` or **API Token** on an existing bot).

| What you run | Where |
|--------------|--------|
| **`nemoclaw start`** | `export` in that shell, or `~/.bashrc` / `~/.profile` |
| **Hourly nudge** | `~/.config/nemoclaw-telegram-nudge.env` (sourced by the wrapper) |

Never commit real tokens.

<a id="faq-bridge-incoming-messages"></a>

### 4. How do I watch incoming messages (bridge log)?

On the **host**, `nemoclaw start` writes bridge output under `/tmp/nemoclaw-services-<sandbox>/`. Follow the log (replace `<sandbox>` with your sandbox name, e.g. `clawpit`):

```bash
tail -f /tmp/nemoclaw-services-clawpit/telegram-bridge.log
```

Incoming lines look like `[<chatId>] <userName>: <text>`. If `ALLOWED_CHAT_IDS` blocks a chat, you may see `[ignored] chat … not in allowed list`. Use `nemoclaw status` to confirm the bridge is running.

<a id="faq-bridge-no-group-messages"></a>

### 5. Group messages not appearing in bridge log

The bridge only appends lines when Telegram delivers `getUpdates` with a **text** message. If you never see `[<chatId>] …` (and no `[ignored]`), Telegram is usually **not sending** those group messages to the bot.

1. **Group privacy (very common)** — With the default **privacy mode**, a bot in a group only gets: `/commands`, **replies to the bot's messages**, and `@YourBotUsername` mentions. Plain "hello" in the group is **not** delivered. **Fix:** In [@BotFather](https://t.me/BotFather) → your bot → **Bot Settings** → **Group Privacy** → **Turn off** (or always reply to the bot / mention `@YourBotUsername`). You may need to **remove and re-add** the bot to the group after changing privacy.
2. **`ALLOWED_CHAT_IDS`** — If you use it, the group id (often negative, e.g. `-100…`) must be in the list. Wrong or missing ids give `[ignored] chat …` in the log (so you *would* see that line).
3. **Webhook vs long poll** — This bridge uses **long polling**. If something else set a **webhook** on the same bot, `getUpdates` can stay empty. Clear it with the Bot API (e.g. `deleteWebhook`) or BotFather if applicable, then restart the bridge.
4. **Non-text messages** — Stickers, photos without caption text, etc. are skipped by the bridge with no log line; try a plain text message first.

<a id="faq-install-skill-other-ways"></a>

### 6. How else can I install the skill files?

**Upload from host** (not inside `nemoclaw connect`); destinations are directories; filename stays `SKILL.md`:

```bash
NEMOCLAW_DEMO_ROOT="${NEMOCLAW_DEMO_ROOT:-${HOME}/NemoClaw-Demo}"
openshell sandbox upload "<sandbox>" \
  "${NEMOCLAW_DEMO_ROOT}/demo/telegram-hourly-nudge/skills/philosopher-nudge/SKILL.md" \
  /sandbox/.openclaw/skills/philosopher-nudge/

openshell sandbox upload "<sandbox>" \
  "${NEMOCLAW_DEMO_ROOT}/demo/telegram-hourly-nudge/skills/philosopher-nudge/SKILL.md" \
  /home/sandbox/.openclaw/skills/philosopher-nudge/
```

If `echo $HOME` inside the sandbox is not `/home/sandbox`, use that path for the
second upload.

**Check the file**:

```bash
nemoclaw <sandbox> connect
test -f /sandbox/.openclaw/skills/philosopher-nudge/SKILL.md && grep -m1 '^name:' "$_"
```

<a id="faq-try-skill"></a>

### 7. How do I list or try the skill in the sandbox?

```bash
openclaw skills list
```

Or use `openclaw tui` and ask in plain language, e.g. *Use the philosopher-nudge skill with theme work; one Ting tong line.* Telegram usually wants **sentences**, not `/commands` — see the skill and the [Telegram bridge demo](../telegram-bridge/telegram-bridge.md).

<a id="faq-hang-or-pairing"></a>

### 8. The smoke test or cron run seems to hang

1. **Gateway / pairing** — complete device approval if prompted ([Telegram bridge demo](../telegram-bridge/telegram-bridge.md)).
2. On the **host**, run `openshell term` and approve egress if asked.
3. Confirm `SKILL.md` exists in the sandbox paths from Step 2.
4. First model call can take minutes; default cap is **180s** (`RUN_PHILOSOPHER_NUDGE_TIMEOUT_SEC` in the env file).
5. **Cron only:** ensure `openshell` is on `PATH` (the template wrapper prepends `~/.local/bin`). If you still see `openshell not on PATH`, set `PATH` in crontab or check `command -v openshell` in a login shell.

<a id="faq-expected-output"></a>

### 9. What should I see in the terminal or cron log?

- Stderr: hints from `run_philosopher_nudge_llm`, then `extracted nudge … → send to Telegram pipeline`.
- Stderr from Python: `hourly_telegram_nudge: OK — message sent` (unless silent mode).
- `No message text` usually means the LLM step failed or printed no `Ting tong` line — fix OpenClaw/skill first; `No such file` for `~/bin` means create it before copying the wrapper.

<a id="faq-env-knobs"></a>

### 10. Optional env knobs (`nemoclaw-telegram-nudge.env`)

- **`PHILOSOPHER_NUDGE_TZ`** — IANA timezone for the "Ting tong, *time*" stamp (default **Asia/Singapore**). Align with `CRON_TZ` if you want wall-clock consistency.
- **`TELEGRAM_NUDGE_REPLY_HINT`** — `0` to drop the default "you can reply" footer.
- **`TELEGRAM_NUDGE_REPLY_HINT_TEXT`** — custom footer line.
- **`TELEGRAM_NUDGE_SILENT=1`** — hide the OK line in logs.

<a id="faq-soul-identity"></a>

### 11. Do I need `SOUL.md` / `IDENTITY.md` / `USER.md` / `AGENTS.md`?

**`SOUL.md` / `IDENTITY.md` / `USER.md`** — optional for this demo. The
skill's `SKILL.md` is enough for the nudge format. Add workspace persona
files only if you want the **same** tone on **every** bridge reply; see
[workspace files](https://docs.nvidia.com/nemoclaw/latest/workspace/workspace-files.html).

**`AGENTS.md`** — **recommended**. The template in this repo
([`templates/AGENTS.md`](templates/AGENTS.md)) includes a
**Telegram Feedback** section that tells the agent to record every Telegram
reply into `memory/YYYY-MM-DD.md`. Without it, the agent ignores user
feedback because skills are only loaded during cron — not during bridge
replies. See [Step 2b](#step-2b--upload-agentsmd-feedback-recording).

<a id="faq-allowed-chat-ids-group"></a>

### 12. How do I find `ALLOWED_CHAT_IDS` for a group?

Comma-separated numeric ids (e.g. `-100…` for supergroups). Use [@getidsbot](https://t.me/getidsbot) in the group. If the bot misses messages, reply **to** the bot once or use `/command@YourBot` (group privacy).

---

## See also

- [Telegram bridge demo](../telegram-bridge/telegram-bridge.md)
- [Demo skills README](skills/README.md)
- [INSTALL.md](../../INSTALL.md)
