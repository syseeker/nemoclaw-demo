#!/usr/bin/env bash
# Cron wrapper: generate one philosopher nudge via LLM, then post it to Telegram.
#
# How it works:
#   1. Source the env file for secrets (bot token, API key, sandbox name, etc.)
#   2. Fix PATH so cron can find openshell (installed under ~/.local/bin)
#   3. Run the LLM script — it SSHs into the sandbox, runs `openclaw agent`
#      with the philosopher-nudge skill, and prints one "Ting tong, …" line
#   4. Pipe that line into the Python sender, which POSTs it to Telegram
#
# Setup:
#   cp  this file  ~/bin/run-telegram-nudge.sh
#   chmod +x       ~/bin/run-telegram-nudge.sh
#   # then fill in ~/.config/nemoclaw-telegram-nudge.env (see .env.example)

set -euo pipefail

# Where this repo is checked out (override if not ~/NemoClaw-Demo)
NEMOCLAW_DEMO_ROOT="${NEMOCLAW_DEMO_ROOT:-${HOME}/NemoClaw-Demo}"

# 1) Load secrets + config
# shellcheck source=/dev/null
source "${HOME}/.config/nemoclaw-telegram-nudge.env"

# 2) Cron uses a minimal PATH; add the dirs where NemoClaw puts openshell
export PATH="${HOME}/.local/bin:${HOME}/.npm-global/bin:/usr/local/bin:/usr/local/sbin:/usr/bin:/bin${PATH:+:$PATH}"

# 3+4) Export what the scripts need, then pipe LLM output → Telegram sender
export SANDBOX_NAME NVIDIA_API_KEY PHILOSOPHER_THEME PHILOSOPHER_NUDGE_TZ
"${NEMOCLAW_DEMO_ROOT}/demo/telegram-hourly-nudge/scripts/run_philosopher_nudge_llm.sh" \
  | /usr/bin/python3 "${NEMOCLAW_DEMO_ROOT}/demo/telegram-hourly-nudge/scripts/hourly_telegram_nudge.py" --stdin
