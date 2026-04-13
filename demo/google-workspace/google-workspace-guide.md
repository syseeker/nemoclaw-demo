# Google Workspace for OpenClaw (Gmail, Calendar, Drive, Sheets, Contacts, Tasks)

Give your OpenClaw agent Google Workspace access -- send emails, manage calendar events, read and write spreadsheets, upload and share Drive files, look up contacts, and manage tasks. All with Tier 1 security: the refresh token never enters the sandbox.

## Prerequisites

| Requirement | Details |
|-------------|---------|
| Running NemoClaw sandbox | A working OpenShell sandbox with OpenClaw. See [NemoClaw setup](https://github.com/NVIDIA/NemoClaw). |
| Google Cloud project | With the Google APIs you need enabled. See [Step 1](#step-1-google-cloud-project-setup). |
| Google OAuth refresh token | Generated via OAuth Playground. See [Step 2](#step-2-generate-a-refresh-token). |

## Step 1: Google Cloud Project Setup

### 1.1 Create a project

Go to [console.cloud.google.com](https://console.cloud.google.com) and create a new project (or select an existing one).

### 1.2 Enable APIs

Go to **APIs & Services > Library** and enable the APIs you need:

- Google Calendar API
- Gmail API
- Google Drive API
- Google Sheets API
- People API (Contacts)
- Tasks API

You only need to enable the ones you plan to use. Calendar alone is enough to get started.

### 1.3 Configure OAuth consent screen

1. Go to **APIs & Services > OAuth consent screen**
2. Select **External**, click **Create**
3. Fill in app name, support email, developer email
4. Add scopes for the services you enabled:
   - `https://www.googleapis.com/auth/calendar` (Calendar read/write)
   - `https://mail.google.com/` (Gmail full access)
   - `https://www.googleapis.com/auth/drive` (Drive read/write)
   - `https://www.googleapis.com/auth/spreadsheets` (Sheets read/write)
   - `https://www.googleapis.com/auth/contacts.readonly` (Contacts read-only)
   - `https://www.googleapis.com/auth/tasks` (Tasks read/write)
5. Add your Gmail address as a **test user**

### 1.4 Create OAuth credentials (Web application)

> **Important:** You must create a **Web application** client, not a Desktop app. The Desktop app type does not allow custom redirect URIs, which you need for the OAuth Playground in the next step.

1. Go to **APIs & Services > Credentials**
2. Click **Create Credentials > OAuth client ID**
3. Application type: **Web application**
4. Under **Authorized redirect URIs**, click **Add URI** and enter exactly:
   ```
   https://developers.google.com/oauthplayground
   ```
   > **No trailing slash.** Google treats `https://developers.google.com/oauthplayground` and `https://developers.google.com/oauthplayground/` as different URIs. A trailing slash will cause `Error 400: redirect_uri_mismatch`.
5. Click **Create**
6. Copy the **Client ID** and **Client Secret** -- you need them in the next step

### 1.5 Publish your app (avoid 7-day token expiry)

If your app stays in **Testing** mode, Google automatically expires refresh tokens after **7 days**. To avoid this:

1. Go to **APIs & Services > OAuth consent screen**
2. Check the publishing status
3. If it says **"Testing"**, click **Publish App**

Since you are the only user (your own Gmail as test user), you do not need Google's full app verification. Once published, your refresh token will not expire unless you manually revoke it.

## Step 2: Generate a Refresh Token

The refresh token is what allows the push daemon to keep getting fresh access tokens. Use the [Google OAuth 2.0 Playground](https://developers.google.com/oauthplayground) to generate one.

1. Go to [https://developers.google.com/oauthplayground](https://developers.google.com/oauthplayground)
2. Click the **gear icon** (top right) to open **OAuth 2.0 Configuration**
3. Check **"Use your own OAuth credentials"**
4. Paste the **Client ID** and **Client Secret** from Step 1.4
5. In **Step 1** on the left panel, type your scopes in the input box (one per line or space-separated):
   ```
   https://www.googleapis.com/auth/calendar
   ```
   Add more scopes if needed (e.g. `https://mail.google.com/` for Gmail).
   > **Tip:** Don't select the full API from the list -- it expands into dozens of individual sub-scopes you don't need. Just type the scope URL directly.
6. Click **Authorize APIs** -- sign in with your Google account and grant access
7. In **Step 2**, click **Exchange authorization code for tokens**
8. Copy the **Refresh token** from the response

You now have three values: Client ID, Client Secret, and Refresh Token.

## Step 3: Install

```bash
cd demo/google-workspace
./install.sh [sandbox-name]
```

The install script will:
1. Prompt you for your Google Client ID, Client Secret, and Refresh Token (or read from `~/.nemoclaw/credentials.json` if already set)
2. Save credentials to `~/.nemoclaw/credentials.json`
3. Install Go and build the `gog` CLI if needed
4. Start the host-side push daemon (exchanges refresh token for short-lived access tokens)
5. Upload the `gog` binary, wrapper, and SKILL.md into the sandbox
6. Apply the network policy allowing traffic to Google API endpoints
7. Clear agent sessions so OpenClaw discovers the new `gog` skill

### Re-deploy after a reboot or sandbox reset

```bash
./setup.sh [sandbox-name]
```

This restarts the push daemon, re-uploads the sandbox wrapper, and reapplies the network policy without repeating OAuth setup.

## Step 4: Verify

### Check the push daemon is running

```bash
cat ~/.nemoclaw/gog-push-daemon.log
```

You should see:
```
INFO Credentials loaded from /home/ubuntu/.nemoclaw/credentials.json
INFO Initial token exchange...
INFO Token pushed to sandbox '<sandbox-name>', expires ...
INFO Push daemon ready (pid ...)
INFO Next refresh in ...s
```

If you see `HTTP Error 401: Unauthorized`, your credentials are wrong -- see [Troubleshooting](#troubleshooting).

### Check the network policy is applied

```bash
openshell policy get --full <sandbox-name> | grep google_
```

You should see entries like `google_calendar`, `google_gmail`, etc. Note: `nemoclaw <sandbox> policy-list` only shows built-in presets; custom policies like Google Workspace won't appear there.

### Test gog directly in the sandbox

Connect to your sandbox and test the `gog` CLI:

```bash
nemoclaw <sandbox-name> connect

# Inside the sandbox:
/sandbox/.config/gogcli/bin/gog calendar events list --max 3
```

If this returns your calendar events as JSON, everything is working.

## Trying It Out

Open the OpenClaw TUI and try these prompts:

```bash
nemoclaw <sandbox-name> connect
openclaw tui
```

### Calendar
- "What's on my calendar today?"
- "Schedule a meeting with bob@example.com on Friday at 2pm"
- "Am I free tomorrow between 2-4pm?"
- "Block focus time Thursday afternoon"

### Gmail
- "Check my email for unread messages"
- "Send an email to alice@example.com about the project update"
- "Reply to the last email from my boss"

### Drive
- "List my recent Drive files"
- "Upload this report to Drive and share it with the team"

### Sheets
- "Read cells A1:D10 from the budget spreadsheet"
- "Add a row to the sales tracker: Acme Corp, $50000, Q2"

### Contacts & Tasks
- "Look up Sarah's email in my contacts"
- "Create a task to follow up with the client by Friday"

### Multi-step workflows
- "Pull the sales numbers from the Q1 spreadsheet, summarize them, and email the summary to the team"
- "Check my calendar for conflicts this week, then email affected attendees about rescheduling"

## Multiple Calendars

If you have multiple Google Calendars, the `gog` CLI uses `primary` as the default (your main calendar). To target a specific calendar:

```bash
# List all your calendars with their IDs
gog calendar calendars

# Create an event on a specific calendar
gog calendar create <calendar-id> --title "Meeting" --start "2026-04-14T09:00:00" --duration 30m
```

OpenClaw will use `primary` unless you specify otherwise. If you want the agent to automatically know your calendar names, add a hint to the SKILL.md inside the sandbox at `/sandbox/.openclaw/skills/gog/SKILL.md`.

## Security Model

The refresh token never enters the sandbox. Only short-lived access tokens (60 min) are pushed in.

```
Host                                    Sandbox
+-----------------------------------+   +----------------------------------+
| ~/.nemoclaw/credentials.json      |   | /sandbox/.openclaw-data/gogcli/  |
|   GOOGLE_CLIENT_ID                |   |   access_token  (60 min, pushed) |
|   GOOGLE_CLIENT_SECRET            |   |   token_expiry                   |
|   GOOGLE_REFRESH_TOKEN            |   |                                  |
|                                   |   | gog wrapper reads token from     |
| gog-push-daemon.py                |   | file, passes to gog-bin via      |
|   exchanges refresh token         |   | GOG_ACCESS_TOKEN env var         |
|   pushes access token via         |   |                                  |
|   openshell sandbox upload -------+-->| gog-bin --> Google APIs           |
|                                   |   |   (L7 proxy inspects all traffic)|
| No network port exposed           |   | No credentials stored here       |
+-----------------------------------+   +----------------------------------+
```

The network policy restricts sandbox egress to specific Google API endpoints, and only the `gog-bin` binary is authorized to make requests.

## Troubleshooting

| Issue | Fix |
|-------|-----|
| `Error 400: redirect_uri_mismatch` during OAuth | Make sure you created a **Web application** client (not Desktop app) and the redirect URI is exactly `https://developers.google.com/oauthplayground` with **no trailing slash**. |
| `HTTP Error 401: Unauthorized` in push daemon log | The Client ID/Secret in `~/.nemoclaw/credentials.json` don't match the ones used to generate the refresh token. All three values must come from the same OAuth client. |
| Refresh token expires after 7 days | Your Google Cloud app is in "Testing" mode. Go to OAuth consent screen and click **Publish App**. |
| Agent says "I need your Google account email" | The `gog` SKILL.md isn't loaded. Clear sessions: `echo '{}' > /sandbox/.openclaw-data/agents/main/sessions/sessions.json`, then restart the TUI. |
| Agent doesn't find `gog` | Disconnect and reconnect, or run `./setup.sh`. |
| "token not found" inside sandbox | Push daemon isn't running. Check `cat ~/.nemoclaw/gog-push-daemon.log` and re-run `./setup.sh`. |
| OpenClaw spinner runs forever (model shows "unknown") | The NVIDIA inference API may be slow. Check `nemoclaw <sandbox> logs` for errors. Try Ctrl+C and restarting the TUI. |
| `l7_decision=deny` in logs | Network policy not applied. Run `openshell policy get --full <sandbox>` to verify. Re-run `./setup.sh` to reapply. |
| Google policy doesn't show in `nemoclaw policy-list` | This is expected. `nemoclaw policy-list` only shows built-in presets. Use `openshell policy get --full <sandbox> \| grep google_` to verify custom policies. |

## File Structure

```
google-workspace/
+-- install.sh                  # Full bootstrap (first-time setup)
+-- setup.sh                    # Re-deploy after reboot
+-- gog-push-daemon.py          # Host-side token push daemon
+-- gmail-oauth-setup.js        # OAuth browser flow helper (alternative to Playground)
+-- google-workspace-guide.md   # This guide
+-- skills/gog/SKILL.md         # OpenClaw skill definition
+-- policy/google-workspace.yaml # Network policy template
```

---

Based on upstream work by **Tim Klawa** (tklawa@nvidia.com), updated with deployment learnings.
