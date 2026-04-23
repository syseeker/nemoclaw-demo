#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SESSIONS_PATH="/sandbox/.openclaw-data/agents/main/sessions/sessions.json"
PLANNER_TIMEOUT_SECONDS=150
LOCAL_APP_ROOT="$SCRIPT_DIR/voice-agent-planner"

RED='\033[0;31m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
NC='\033[0m'

info()  { echo -e "${CYAN}  ▸ $1${NC}"; }
ok()    { echo -e "${GREEN}  ✓ $1${NC}"; }
fail()  { echo -e "${RED}  ✗ $1${NC}"; exit 1; }

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
echo "      export PLANNER_SANDBOX_NAME=$SANDBOX"
echo "      uv run -m apps.jewel_voice_guide.pipeline"
echo ""
echo "    Terminal D:"
echo "      cd $LOCAL_APP_ROOT/webrtc_ui"
echo "      npm install"
echo "      npm run dev -- --host 0.0.0.0"
echo ""
echo "  Keep Terminal A open while testing planner prompts."
echo ""
