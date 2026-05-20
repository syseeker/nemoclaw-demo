#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Run one OpenClaw agent turn inside the sandbox using the chinese-jokes
# skill, then print the joke block (哈哈, ... + body) to stdout for piping
# into hourly_telegram_nudge.py --stdin.
#
# Requires: openshell, ssh; NVIDIA_API_KEY; SANDBOX_NAME (or NEMOCLAW_SANDBOX_NAME)
#
# Usage:
#   NVIDIA_API_KEY=nvapi-... SANDBOX_NAME=my-sbx \
#     ./run_joke_nudge_llm.sh
#
# Optional:
#   JOKE_TOPIC — override topic category (e.g. 方言梗, 生活, 人生阶段); omit for random
#   OPENCLAW_AGENT_PREFIX — default nemoclaw-start
#   SESSION_ID — override session id (default: joke-llm-<epoch>)

set -euo pipefail

SANDBOX_NAME="${SANDBOX_NAME:-${NEMOCLAW_SANDBOX_NAME:-}}"
TOPIC="${JOKE_TOPIC:-}"
OPENCLAW_AGENT_PREFIX="${OPENCLAW_AGENT_PREFIX:-nemoclaw-start}"
AGENT_LAUNCHER=""
[[ -n "$OPENCLAW_AGENT_PREFIX" ]] && AGENT_LAUNCHER="${OPENCLAW_AGENT_PREFIX} "
SESSION_ID="${SESSION_ID:-joke-llm-$(date +%s)-${RANDOM}}"

die() { printf '%s\n' "run_joke_nudge_llm: FAIL: $*" >&2; exit 1; }

[[ -n "$SANDBOX_NAME" ]] || die "set SANDBOX_NAME (or NEMOCLAW_SANDBOX_NAME)"
[[ -n "${NVIDIA_API_KEY:-}" ]] || die "set NVIDIA_API_KEY"

command -v openshell >/dev/null 2>&1 || die "openshell not on PATH"
command -v base64 >/dev/null 2>&1 || die "base64 not on PATH"

TOPIC_CLAUSE=""
if [[ -n "$TOPIC" ]]; then
  TOPIC_CLAUSE=" For this turn use topic: ${TOPIC}."
fi

PROMPT="Use the OpenClaw managed skill named 'chinese-jokes'. Read its SKILL.md.${TOPIC_CLAUSE} Obey the skill output contract: reply with the joke body in Chinese (no header, no timestamp), ending with exactly 哈哈 or Meow~~ on its own line. No markdown, no preamble, no explanation after the joke. No blank lines inside the joke body."

prompt_b64=$(printf '%s' "$PROMPT" | base64 | tr -d '\n')
nv_b64=$(printf '%s' "$NVIDIA_API_KEY" | base64 | tr -d '\n')

ssh_config="$(mktemp)"
trap 'rm -f "$ssh_config"' EXIT
openshell sandbox ssh-config "$SANDBOX_NAME" >"$ssh_config" 2>/dev/null \
  || die "openshell sandbox ssh-config failed for '${SANDBOX_NAME}'"

TIMEOUT_SEC="${RUN_JOKE_NUDGE_TIMEOUT_SEC:-180}"
TIMEOUT_CMD=()
if command -v timeout >/dev/null 2>&1; then
  TIMEOUT_CMD=(timeout "$TIMEOUT_SEC")
elif command -v gtimeout >/dev/null 2>&1; then
  TIMEOUT_CMD=(gtimeout "$TIMEOUT_SEC")
fi

_lock_rm="rm -f '/sandbox/.openclaw-data/agents/main/sessions/${SESSION_ID}.jsonl.lock' 2>/dev/null || true; "
remote_cmd="pm=\$(printf '%s' '${prompt_b64}' | base64 -d) || exit 1; nv=\$(printf '%s' '${nv_b64}' | base64 -d) || exit 1; export NVIDIA_API_KEY=\"\$nv\"; ${_lock_rm}${AGENT_LAUNCHER}openclaw agent --agent main --local -m \"\$pm\" --session-id '${SESSION_ID}'"

if [[ ${#TIMEOUT_CMD[@]} -eq 0 ]]; then
  printf '%s\n' "run_joke_nudge_llm: WARN: no 'timeout' binary — ssh may hang if the gateway or model never responds. Install coreutils or set RUN_JOKE_NUDGE_TIMEOUT_SEC and use GNU timeout." >&2
fi
printf '%s\n' "run_joke_nudge_llm: sandbox=${SANDBOX_NAME} session=${SESSION_ID} topic=${TOPIC:-random}" >&2
printf '%s\n' "run_joke_nudge_llm: running openclaw inside sandbox (max ${TIMEOUT_SEC}s). If this sits silent:" >&2
printf '%s\n' "  - Approve device pairing: openclaw devices list / approve on the host." >&2
printf '%s\n' "  - In another terminal on the host run: openshell term  (approve any egress prompts)." >&2
printf '%s\n' "  - Ensure ~/.openclaw/skills/chinese-jokes/SKILL.md exists in the sandbox." >&2

set +e
raw_out=$(
  "${TIMEOUT_CMD[@]}" ssh -T -F "$ssh_config" \
    -o StrictHostKeyChecking=no \
    -o UserKnownHostsFile=/dev/null \
    -o ConnectTimeout=10 \
    -o LogLevel=ERROR \
    "openshell-${SANDBOX_NAME}" \
    "$remote_cmd" 2>&1
)
agent_rc=$?
set -e

# Strip openclaw/nemoclaw system noise that lacks a blank-line separator from
# the joke body, then extract from the first content line to the end marker.
filtered=$(printf '%s\n' "$raw_out" | grep -vE \
  '^\[SECURITY\]|^Setting up NemoClaw|^\[gateway\]|^\[channels\]|^\(node:|^\(Use `node|Warning:.*EnvHttpProxyAgent|^\[tools\]|^Skill .* not available')

joke=$(printf '%s\n' "$filtered" | awk '
/^(哈哈|Meow~~)$/ {
  for (i = 1; i <= n; i++) print buf[i]
  print
  found = 1
  exit
}
/^[[:space:]]*$/ { n = 0; next }
{ buf[++n] = $0 }
')
if [[ -z "$joke" ]]; then
  printf '%s\n' "--- openclaw output (no 哈哈 / Meow~~ ending found) ---" >&2
  printf '%s' "$raw_out" | tail -c 8000 >&2
  printf '\n' >&2
  if [[ "$agent_rc" == 124 ]]; then
    die "timed out after ${TIMEOUT_SEC}s (exit 124) — gateway pairing, openshell term approval, or missing SKILL.md? See demo telegram-hourly-nudge Step 3"
  fi
  die "agent exit ${agent_rc}: expected joke ending with '哈哈' or 'Meow~~'"
fi

line_count=$(printf '%s\n' "$joke" | wc -l)
printf '%s\n' "run_joke_nudge_llm: extracted joke (${#joke} chars, ${line_count} lines) → send to Telegram pipeline" >&2
printf '%s\n' "$joke"
