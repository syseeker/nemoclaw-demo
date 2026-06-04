# Telegram + Google Calendar

Manage your Google Calendar from Telegram -- check today's schedule, create
events, reschedule meetings, and delete entries, all by chatting with the
OpenClaw agent via a Telegram bot. Because the **Telegram bridge**
(`nemoclaw start`) stays running, you can query and modify your calendar from
DMs or a group chat at any time.

## What you will learn

- Setting up Google OAuth2 credentials for Calendar access
- Generating a refresh token via the OAuth Playground
- Installing the `gog` CLI and calendar skill inside a NemoClaw sandbox
- Running the host-side push daemon that keeps access tokens fresh
- Applying a calendar-only network policy via `openshell`
- Querying and modifying Google Calendar from Telegram (DM and group)
- Troubleshooting common issues (token mismatch, group policy, stale sessions)

**Reference:** [Telegram bridge demo](../telegram-bridge/telegram-bridge.md) · [OpenClaw skills](https://docs.openclaw.ai/tools/skills)

---

## Prerequisites

- Finish a normal **Telegram + NemoClaw** setup ([Telegram bridge demo](../telegram-bridge/telegram-bridge.md)):
  you need a bot token and a working sandbox with `openclaw`.
- A [Google Cloud](https://console.cloud.google.com) project (free tier is fine).
- Python 3 on the host (for the push daemon).

---

## Architecture

```
 Operator (host terminal)
  │
  │  ./install.sh  (one-time)
  │  ./setup.sh    (after reboot)
  │
  ┌──────┼───────────────────────────────────────────────────────┐
  │      ▼                                                       │
  │  Host                                                        │
  │  ────                                                        │
  │  ~/.nemoclaw/credentials.json                                │
  │    GOOGLE_CLIENT_ID                                          │
  │    GOOGLE_CLIENT_SECRET                                      │
  │    GOOGLE_REFRESH_TOKEN                                      │
  │                                                              │
  │  gog-push-daemon.py                                          │
  │    exchanges refresh token for 60-min access token           │
  │    pushes via openshell sandbox upload ──────────────────┐   │
  │                                                          │   │
  │  No network port exposed. Refresh token never enters     │   │
  │  the sandbox (Tier 1 security).                          │   │
  └──────────────────────────────────────────────────────────┼───┘
                                                             │
  ┌──────────────────────────────────────────────────────────┼───┐
  │  Sandbox (clawpit)                                       ▼   │
  │  ──────────────────                                          │
  │  /sandbox/.openclaw-data/gogcli/access_token  (pushed)       │
  │                                                              │
  │  OpenClaw agent                                              │
  │    reads skills/calendar/SKILL.md                            │
  │    runs: gog calendar events list                            │
  │    gog-bin ──► calendar.googleapis.com                        │
  │         (L7 proxy inspects all traffic)                       │
  │                                                              │
  │  Telegram bridge ◄──► Telegram Bot API                       │
  └──────────────────────────────────────────────────────────────┘

 You (Telegram DM or group)
  │
  │  "What's on my calendar tomorrow?"
  │  ──────────────────────────────────►  agent responds with events
  │  ◄──────────────────────────────────
```

---

## Step 1 — Google Calendar OAuth setup

### 1.1 Enable the Calendar API

1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Navigate to **APIs & Services > Library**
3. Search for **Google Calendar API** and click **Enable**

### 1.2 Configure OAuth consent screen

1. Go to **APIs & Services > OAuth consent screen**
2. Select **External**, click **Create**
3. Fill in app name, support email, developer email
4. Add scope: `https://www.googleapis.com/auth/calendar`
5. Add your Gmail address as a **test user**

### 1.3 Create OAuth credentials (Web application)

> You must create a **Web application** client, not Desktop app. Desktop apps don't support custom redirect URIs.

1. Go to **APIs & Services > Credentials**
2. Click **Create Credentials > OAuth client ID**
3. Application type: **Web application**
4. Under **Authorized redirect URIs**, add exactly:
   ```
   https://developers.google.com/oauthplayground
   ```
   > No trailing slash — `oauthplayground/` and `oauthplayground` are different URIs. A trailing slash causes `Error 400: redirect_uri_mismatch`.
5. Click **Create**, then copy the **Client ID** and **Client Secret**

### 1.4 Publish your app

Go to **OAuth consent screen** and click **Publish App** to move out of
Testing mode. Otherwise your refresh token expires after **7 days**.

Since you are the only user, you don't need Google's full app verification.

---

## Step 2 — Generate a refresh token

1. Go to [https://developers.google.com/oauthplayground](https://developers.google.com/oauthplayground)
2. Click the **gear icon** (top right), check **"Use your own OAuth credentials"**
3. Paste your **Client ID** and **Client Secret** from Step 1.3
4. In Step 1 on the left panel, type this scope in the input box:
   ```
   https://www.googleapis.com/auth/calendar
   ```
   > Don't select the full API from the list — it expands into dozens of sub-scopes you don't need. Just type the scope URL directly.
5. Click **Authorize APIs**, sign in with your Google account, grant access
6. In Step 2, click **Exchange authorization code for tokens**
7. Copy the **Refresh token** from the response

---

## Step 3 — Set up Telegram + NemoClaw

Before creating (or re-creating) your sandbox, export the Telegram env vars so
they get baked into the read-only OpenClaw config:

```bash
export TELEGRAM_BOT_TOKEN=<your-bot-token>
export TELEGRAM_ALLOWED_IDS=<group-chat-id>,<your-user-id>
```

`TELEGRAM_ALLOWED_IDS` is a comma-separated list of Telegram chat IDs:
- **Group chat ID** (negative number, e.g. `-1234567890`) — required for group access
- **Personal user ID** (positive number) — required for DM access

To find your user ID, send `/start` to [@userinfobot](https://t.me/userinfobot)
on Telegram. For group chat IDs, use [@getidsbot](https://t.me/getidsbot) in the group.

> **Important:** `TELEGRAM_ALLOWED_IDS` must be set **before** `nemoclaw onboard`.
> It's a build-time variable that gets written into the read-only `openclaw.json`
> inside the sandbox. Setting it after onboard has no effect. If you need to change
> it, destroy and re-onboard:

```bash
nemoclaw <sandbox-name> destroy --yes
nemoclaw onboard
```

---

## Step 4 — Install

```bash
cd demo/telegram-calendar
./install.sh [sandbox-name]
```

The install script handles everything:
1. Prompts for Google Client ID, Client Secret, and Refresh Token (or reads from `~/.nemoclaw/credentials.json`)
2. Saves credentials to `~/.nemoclaw/credentials.json`
3. Installs Go and builds the `gog` CLI if needed
4. Starts the host-side push daemon
5. Uploads the `gog` binary, wrapper, and calendar SKILL.md into the sandbox
6. Applies the Google Calendar network policy
7. Clears agent sessions so OpenClaw discovers the new skill

### Re-deploy after a reboot or sandbox reset

```bash
./setup.sh [sandbox-name]
```

---

## Step 5 — Start the Telegram bridge

```bash
nemoclaw start
```

This starts the Telegram bridge and cloudflared tunnel. Leave it running.

---

## Step 6 — Verify

### Check the push daemon

```bash
cat ~/.nemoclaw/gog-push-daemon.log
```

Look for `Token pushed to sandbox` and `Push daemon ready`.

### Check the network policy

```bash
openshell policy get --full <sandbox-name> | grep google_calendar
```

> `nemoclaw <sandbox> policy-list` only shows built-in presets. Custom policies
> like Google Calendar won't appear there — use `openshell` to verify.

### Test gog directly in the sandbox

`gog` is **not** on the interactive shell's PATH (the sandbox `.bashrc` is a
read-only root-owned file, and PATH isn't needed: the OpenClaw agent invokes the
tool by its absolute path via the calendar skill). When testing by hand, call it
by full path:

```bash
nemoclaw <sandbox-name> connect
/sandbox/.config/gogcli/bin/gog calendar events --max 3
```

If this returns JSON with your calendar events, you're ready.

---

## Try it from Telegram

Open your Telegram bot (DM or group) and send:

### Read
- "What's on my calendar today?"
- "Do I have any meetings tomorrow?"
- "Search my calendar for standup"

### Create
- "Schedule a meeting called Team Sync on Friday at 2pm for 30 minutes"
- "Create a focus time block tomorrow from 2pm to 5pm"
- "Set up a 1:1 with alice@example.com next Tuesday at 10am"

### Update
- "Rename the 3pm meeting to Project Review"
- "Move my Friday meeting to Monday same time"

### Delete
- "Cancel my 4pm meeting today"
- "Delete all focus time blocks this week"

### Multi-step
- "Check if I'm free Friday afternoon, and if so, schedule a demo prep session"
- "Find scheduling conflicts this week and list them"

---

## Multiple Calendars

By default, commands use `primary` (your main calendar). To target other calendars
(run by full path in the sandbox shell — see note in "Test gog directly" above):

```bash
/sandbox/.config/gogcli/bin/gog calendar calendars       # list all calendars with IDs
/sandbox/.config/gogcli/bin/gog calendar create <calendar-id> --title "Gym" --start "2026-04-14T07:00:00" --duration 1h
```

In Telegram, just say: *"Add a Gym session to my Personal calendar at 7am tomorrow."*

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| "This group is not allowed" | `TELEGRAM_ALLOWED_IDS` was not set before `nemoclaw onboard`. Destroy and re-onboard with the env var set. |
| `Error 400: redirect_uri_mismatch` | Create a **Web application** client (not Desktop). Redirect URI must be exactly `https://developers.google.com/oauthplayground` with **no trailing slash**. |
| `401 Unauthorized` in push daemon | Client ID/Secret in `credentials.json` don't match the ones used to generate the refresh token. All three must come from the same OAuth client. |
| Refresh token expires after 7 days | App is in "Testing" mode. Go to OAuth consent screen and **Publish App**. |
| Agent says "I need your Google email" | Stale session. Clear: `echo '{}' > /sandbox/.openclaw-data/agents/main/sessions/sessions.json` |
| Telegram bot doesn't respond | Check bridge: `nemoclaw status`. Restart: `nemoclaw start`. |
| OpenClaw spinner forever | Check `nemoclaw <sandbox> logs`. Restart push daemon: `./setup.sh`. |
| `l7_decision=deny` | Policy not applied. Run `./setup.sh` or `./install.sh` to reapply. |
| Google policy not in `nemoclaw policy-list` | Expected. Use `openshell policy get --full <sandbox> \| grep google_calendar`. |

---

## File structure

```
telegram-calendar/
+-- telegram-calendar-guide.md    # This guide
+-- install.sh                    # Full bootstrap (first-time setup)
+-- setup.sh                      # Re-deploy after reboot
+-- gog-push-daemon.py            # Host-side token push daemon
+-- gmail-oauth-setup.js          # OAuth browser flow helper (alternative to Playground)
+-- skills/calendar/SKILL.md      # Calendar-only skill for OpenClaw
+-- policy/google-calendar.yaml   # Calendar-only network policy
```

---

## See also

- [Telegram bridge demo](../telegram-bridge/telegram-bridge.md)
- [INSTALL.md](../../INSTALL.md)
