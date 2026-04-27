#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SESSIONS_PATH="/sandbox/.openclaw-data/agents/main/sessions/sessions.json"
PLANNER_TIMEOUT_SECONDS=150
LOCAL_APP_ROOT="$SCRIPT_DIR/voice-agent-planner"
ENV_EXAMPLE="$SCRIPT_DIR/voice-agent.env.example"
ENV_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/nemoclaw-voice-agent"
ENV_FILE="$ENV_DIR/voice-agent.env"
LEGACY_ENV_FILE="$LOCAL_APP_ROOT/voice-guide.env"

RED='\033[0;31m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
NC='\033[0m'

info()  { echo -e "${CYAN}  ▸ $1${NC}"; }
ok()    { echo -e "${GREEN}  ✓ $1${NC}"; }
fail()  { echo -e "${RED}  ✗ $1${NC}"; exit 1; }

set_env_value() {
  local file="$1"
  local key="$2"
  local value="$3"
  python3 - "$file" "$key" "$value" <<'PY'
import sys
from pathlib import Path

path = Path(sys.argv[1])
key = sys.argv[2]
value = sys.argv[3]
line = f"{key}={value}\n"

lines = path.read_text(encoding="utf-8").splitlines(keepends=True) if path.exists() else []
for idx, existing in enumerate(lines):
    stripped = existing.lstrip()
    if stripped.startswith(f"{key}=") or stripped.startswith(f"export {key}="):
        lines[idx] = line
        break
else:
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"
    lines.append(line)

path.write_text("".join(lines), encoding="utf-8")
PY
}

merge_env_file() {
  local source="$1"
  local target="$2"
  python3 - "$source" "$target" <<'PY'
import re
import sys
from pathlib import Path

source = Path(sys.argv[1])
target = Path(sys.argv[2])
key_re = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)$")

if not source.exists():
    sys.exit(0)

target_lines = target.read_text(encoding="utf-8").splitlines(keepends=True) if target.exists() else []
target_index = {}
target_values = {}
for idx, line in enumerate(target_lines):
    match = key_re.match(line)
    if match:
        target_index[match.group(1)] = idx
        target_values[match.group(1)] = match.group(2).strip()

pending = []
for line in source.read_text(encoding="utf-8").splitlines(keepends=True):
    match = key_re.match(line)
    if not match:
        if not target_lines:
            pending.append(line)
        continue

    key = match.group(1)
    value = match.group(2).strip()
    if key not in target_index:
        pending.append(line)
    elif not target_values.get(key) and value:
        target_lines[target_index[key]] = line

if pending:
    if target_lines and not target_lines[-1].endswith("\n"):
        target_lines[-1] += "\n"
    if target_lines and target_lines[-1].strip():
        target_lines.append("\n")
    target_lines.extend(pending)

target.write_text("".join(target_lines), encoding="utf-8")
PY
}

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
[ -z "$SANDBOX" ] && fail "Usage: ./install.sh <sandbox-name>"

echo ""
echo -e "${CYAN}  Voice Guide Demo — Install${NC}"
echo ""

command -v openshell >/dev/null 2>&1 || fail "openshell not found."
command -v nemoclaw >/dev/null 2>&1 || fail "nemoclaw not found."
[ -f "$LOCAL_APP_ROOT/apps/jewel_voice_guide/pipeline.py" ] || \
  fail "Missing local app snapshot at $LOCAL_APP_ROOT. Re-copy voice-agent-planner into this demo folder."
[ -f "$ENV_EXAMPLE" ] || fail "Missing environment template at $ENV_EXAMPLE."

mkdir -p "$ENV_DIR"
if [ ! -f "$ENV_FILE" ]; then
  cp "$ENV_EXAMPLE" "$ENV_FILE"
else
  merge_env_file "$ENV_EXAMPLE" "$ENV_FILE"
fi
if [ -f "$LEGACY_ENV_FILE" ]; then
  merge_env_file "$LEGACY_ENV_FILE" "$ENV_FILE"
fi
set_env_value "$ENV_FILE" "PLANNER_SANDBOX_NAME" "$SANDBOX"
set_env_value "$ENV_FILE" "OPENCLAW_BRIDGE_SANDBOX" "$SANDBOX"
ok "environment file ready: $ENV_FILE"

UPLOAD_ROOT=$(mktemp -d /tmp/voice-guide-demo-XXXXXX)
trap 'rm -rf "$UPLOAD_ROOT"' EXIT

mkdir -p "$UPLOAD_ROOT/jewel-voice-planner"
cp "$SCRIPT_DIR/skills/jewel-voice-planner/SKILL.md" \
  "$UPLOAD_ROOT/jewel-voice-planner/SKILL.md"

openshell sandbox upload "$SANDBOX" "$UPLOAD_ROOT/jewel-voice-planner" \
  /sandbox/.openclaw-data/workspace/skills/jewel-voice-planner 2>/dev/null || \
  fail "Failed to upload jewel-voice-planner skill into workspace"
ok "jewel-voice-planner skill deployed to workspace"

openshell sandbox upload "$SANDBOX" "$UPLOAD_ROOT/jewel-voice-planner" \
  /sandbox/.openclaw/skills/jewel-voice-planner 2>/dev/null || \
  info "canonical skill mirror under /sandbox/.openclaw/skills skipped (non-fatal)"

mkdir -p "$UPLOAD_ROOT/jewel-data"
cp "$SCRIPT_DIR/data/jewel_knowledge.json" \
  "$UPLOAD_ROOT/jewel-data/jewel_knowledge.json"

openshell sandbox upload "$SANDBOX" "$UPLOAD_ROOT/jewel-data/jewel_knowledge.json" \
  /sandbox/.openclaw-data/workspace/jewel_knowledge.json 2>/dev/null || \
  fail "Failed to upload jewel_knowledge.json"
ok "jewel_knowledge.json deployed to workspace"

AGENTS_SNIPPET="$SCRIPT_DIR/agents-md-snippet.md"
if [ -f "$AGENTS_SNIPPET" ]; then
  openshell sandbox exec -n "$SANDBOX" -- bash -c \
    "grep -q 'Jewel Voice Planner' /sandbox/.openclaw-data/workspace/AGENTS.md 2>/dev/null && exit 0; \
     mkdir -p /sandbox/.openclaw-data/workspace; \
     cat >> /sandbox/.openclaw-data/workspace/AGENTS.md" < "$AGENTS_SNIPPET" 2>/dev/null || \
    info "AGENTS.md update skipped (may need manual append)"
  ok "AGENTS.md updated with jewel-voice-planner directive"
fi

info "Setting planner timeout budget..."
nemoclaw "$SANDBOX" config set \
  --key agents.defaults.timeoutSeconds \
  --value "$PLANNER_TIMEOUT_SECONDS" >/dev/null 2>&1 || \
  info "timeoutSeconds update skipped (non-fatal)"
ok "planner timeout budget set to ${PLANNER_TIMEOUT_SECONDS}s"

info "Clearing sessions..."
openshell sandbox exec -n "$SANDBOX" -- bash -c \
  "[ -f $SESSIONS_PATH ] && echo '{}' > $SESSIONS_PATH || true; \
   rm -f /sandbox/.openclaw-data/agents/main/sessions/planner-*.jsonl \
         /sandbox/.openclaw-data/agents/main/sessions/planner-*.jsonl.lock \
         /sandbox/.openclaw-data/agents/main/sessions/planner-*.json 2>/dev/null || true" 2>/dev/null
ok "Main planner sessions cleared"

echo ""
echo -e "${GREEN}  Voice guide assets installed.${NC}"
echo "  Sandbox: $SANDBOX"
echo ""
echo "  Run these next steps in order:"
echo ""
echo "    Terminal A:"
echo "      openshell term"
echo ""
echo "    Terminal B:"
echo "      cd $SCRIPT_DIR"
echo "      ./verify-planner.sh $SANDBOX"
echo ""
echo "    Terminal C:"
echo "      cd $LOCAL_APP_ROOT"
echo "      # Edit the shared env once and set NVIDIA_API_KEY before starting."
echo "      \${EDITOR:-nano} $ENV_FILE"
echo "      uv run -m apps.jewel_voice_guide.pipeline"
echo ""
echo "    Terminal D:"
echo "      cd $LOCAL_APP_ROOT/webrtc_ui"
echo "      npm install"
echo "      npm run dev -- --host 0.0.0.0"
echo ""
echo "  Keep Terminal A open while testing planner prompts."
echo ""
