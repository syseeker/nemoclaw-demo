#!/usr/bin/env bash
# Cron wrapper for the NemoClaw Telegram heartbeat.
# Crontab example (every 5 min, 06:00–23:00 SGT):
#   CRON_TZ=Asia/Singapore
#   */5 6-23 * * * /home/ubuntu/bin/run-telegram-heartbeat.sh >> ~/.local/log/telegram-heartbeat.log 2>&1

set -euo pipefail

NEMOCLAW_DEMO_ROOT="${NEMOCLAW_DEMO_ROOT:-${HOME}/nemoclaw/nemoclaw-demo}"

# Load secrets
# shellcheck disable=SC1090
source "${HOME}/.config/nemoclaw-telegram-heartbeat.env"

# Ensure openshell is on PATH (nvm + local bin)
export PATH="${HOME}/.local/bin:${HOME}/.nvm/versions/node/v22.22.2/bin:${PATH}"

# Run heartbeat skill inside sandbox, pipe output to Telegram sender
bash "${NEMOCLAW_DEMO_ROOT}/demo/telegram-heartbeat/scripts/run_sandbox_heartbeat.sh" \
  | python3 "${NEMOCLAW_DEMO_ROOT}/demo/telegram-heartbeat/scripts/send_telegram_message.py" --stdin
