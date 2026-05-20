#!/usr/bin/env bash
set -euo pipefail

SANDBOX=${1:-}
if [ -z "$SANDBOX" ]; then
  SANDBOX=$(python3 -c "
import json
try:
    d = json.load(open('$HOME/.nemoclaw/sandboxes.json'))
    print(d.get('defaultSandbox',''))
except: pass
" 2>/dev/null || true)
fi
[ -z "$SANDBOX" ] && { echo "Usage: ./verify-planner.sh <sandbox-name>" >&2; exit 1; }

command -v openshell >/dev/null 2>&1 || { echo "openshell not found" >&2; exit 1; }
command -v ssh >/dev/null 2>&1 || { echo "ssh not found" >&2; exit 1; }
command -v timeout >/dev/null 2>&1 || { echo "timeout not found" >&2; exit 1; }

SESSION_ID="voice-guide-preflight-$(date +%s)-$RANDOM"
PROMPT="Reply with exactly OK and nothing else."

prompt_b64=$(printf '%s' "$PROMPT" | base64 | tr -d '\n')
nv_b64=$(printf '%s' "${NVIDIA_API_KEY:-}" | base64 | tr -d '\n')

ssh_config="$(mktemp)"
trap 'rm -f "$ssh_config"' EXIT
openshell sandbox ssh-config "$SANDBOX" >"$ssh_config"

remote_cmd="pm=\$(printf '%s' '${prompt_b64}' | base64 -d) || exit 1; \
nv=\$(printf '%s' '${nv_b64}' | base64 -d) || exit 1; \
if [ -n \"\$nv\" ]; then export NVIDIA_API_KEY=\"\$nv\"; fi; \
rm -f '/sandbox/.openclaw-data/agents/main/sessions/${SESSION_ID}.jsonl.lock' 2>/dev/null || true; \
rm -f '/sandbox/.openclaw-data/agents/main/sessions/${SESSION_ID}.jsonl' '/sandbox/.openclaw-data/agents/main/sessions/${SESSION_ID}.json' 2>/dev/null || true; \
openclaw agent --agent main -m \"\$pm\" --session-id '${SESSION_ID}'"

echo "voice-guide preflight: sandbox=$SANDBOX session=$SESSION_ID" >&2
echo "voice-guide preflight: keep 'openshell term' open in another terminal while this runs." >&2
echo "voice-guide preflight: if this hangs, check device approval with 'openclaw devices list' on the host." >&2

set +e
raw_out=$(timeout 30 ssh -T -F "$ssh_config" \
  -o StrictHostKeyChecking=no \
  -o UserKnownHostsFile=/dev/null \
  -o ConnectTimeout=10 \
  -o LogLevel=ERROR \
  "openshell-${SANDBOX}" \
  "$remote_cmd" 2>&1)
rc=$?
set -e

if [ "$rc" -eq 0 ] && printf '%s\n' "$raw_out" | grep -Eq '^OK\r?$'; then
  echo "voice-guide preflight: planner path is reachable." >&2
  echo "OK"
  exit 0
fi

echo "--- planner preflight output ---" >&2
printf '%s\n' "$raw_out" | tail -n 80 >&2
echo "--------------------------------" >&2

if [ "$rc" -eq 124 ]; then
  echo "voice-guide preflight: timed out after 30s." >&2
  echo "Likely causes:" >&2
  echo "  1. 'openshell term' was not open to approve runtime egress." >&2
  echo "  2. OpenClaw device pairing approval is pending." >&2
  echo "  3. The sandbox skill/runtime is blocked or stalled." >&2
else
  echo "voice-guide preflight: planner command failed with exit $rc." >&2
fi

exit 1
