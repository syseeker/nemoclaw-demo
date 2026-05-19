#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Collect sandbox health info via OpenShell SSH and print a heartbeat block
# to stdout. Pipe into send_telegram_message.py --stdin.
#
# Requires: openshell; SANDBOX_NAME
#
# Usage:
#   SANDBOX_NAME=nemoclaw ./run_sandbox_heartbeat.sh | python3 send_telegram_message.py --stdin

set -euo pipefail

SANDBOX_NAME="${SANDBOX_NAME:-${NEMOCLAW_SANDBOX_NAME:-nemoclaw}}"

die() { printf '%s\n' "run_sandbox_heartbeat: FAIL: $*" >&2; exit 1; }

[[ -n "$SANDBOX_NAME" ]] || die "set SANDBOX_NAME"
command -v openshell >/dev/null 2>&1 || die "openshell not on PATH"

ssh_config="$(mktemp)"
trap 'rm -f "$ssh_config"' EXIT
openshell sandbox ssh-config "$SANDBOX_NAME" >"$ssh_config" 2>/dev/null \
  || die "openshell sandbox ssh-config failed for '${SANDBOX_NAME}'"

printf '%s\n' "run_sandbox_heartbeat: sandbox=${SANDBOX_NAME}" >&2

health_output=$(
  timeout 30 ssh -T -F "$ssh_config" \
    -o StrictHostKeyChecking=no \
    -o UserKnownHostsFile=/dev/null \
    -o ConnectTimeout=10 \
    -o LogLevel=ERROR \
    "openshell-${SANDBOX_NAME}" \
    'ts=$(date "+%Y-%m-%d %H:%M %Z")
     model=$(openclaw models list 2>/dev/null | grep -v Warning | grep -v "^$" | grep -v "^Model" | head -1 | awk "{print \$1}" || echo "unknown")
     hn=$(hostname)
     echo "NemoClaw heartbeat OK"
     echo "Time: $ts"
     echo "Model: $model"
     echo "Host: $hn"' 2>&1
) || die "SSH timed out or failed"

line=$(printf '%s\n' "$health_output" | grep -E '^NemoClaw heartbeat' | head -n 1 || true)
if [[ -z "$line" ]]; then
  printf '%s\n' "--- unexpected output ---" >&2
  printf '%s' "$health_output" | tail -c 2000 >&2
  printf '\n' >&2
  die "no heartbeat line in output"
fi

block=$(printf '%s\n' "$health_output" | sed -n '/^NemoClaw heartbeat/,/^Host:/p')
[[ -z "$block" ]] && block="$line"

printf '%s\n' "run_sandbox_heartbeat: done (${#block} chars)" >&2
printf '%s\n' "$block"
