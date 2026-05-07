#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SESSIONS_PATH="/sandbox/.openclaw-data/agents/main/sessions/sessions.json"

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
echo -e "${CYAN}  Token Budget Skill — Install${NC}"
echo ""

command -v openshell >/dev/null 2>&1 || fail "openshell not found."

# ── Upload SKILL.md ──────────────────────────────────────────────────

SKILL_UPLOAD=$(mktemp -d /tmp/token-budget-skill-XXXXXX)
trap 'rm -rf "$SKILL_UPLOAD"' EXIT

mkdir -p "$SKILL_UPLOAD/token-budget"
cp "$SCRIPT_DIR/skills/token-budget/SKILL.md" "$SKILL_UPLOAD/token-budget/SKILL.md"

openshell sandbox upload "$SANDBOX" "$SKILL_UPLOAD/token-budget" \
  /sandbox/.openclaw/skills/token-budget 2>/dev/null || \
  fail "Failed to upload SKILL.md"
ok "token-budget SKILL.md deployed"

# ── Upload token-budget.json config ──────────────────────────────────

CONFIG_UPLOAD=$(mktemp -d /tmp/token-budget-config-XXXXXX)
trap 'rm -rf "$SKILL_UPLOAD" "$CONFIG_UPLOAD"' EXIT

cp "$SCRIPT_DIR/token-budget.json" "$CONFIG_UPLOAD/token-budget.json"

openshell sandbox upload "$SANDBOX" "$CONFIG_UPLOAD/token-budget.json" \
  /sandbox/.openclaw/workspace/token-budget.json 2>/dev/null || \
  fail "Failed to upload token-budget.json"
ok "token-budget.json deployed to workspace"

# ── Append AGENTS.md directive ───────────────────────────────────────

AGENTS_SNIPPET="$SCRIPT_DIR/agents-md-snippet.md"
if [ -f "$AGENTS_SNIPPET" ]; then
  openshell sandbox exec -n "$SANDBOX" -- bash -c \
    "grep -q 'Token Budget' /sandbox/.openclaw/workspace/AGENTS.md 2>/dev/null && exit 0; \
     cat >> /sandbox/.openclaw/workspace/AGENTS.md" < "$AGENTS_SNIPPET" 2>/dev/null || \
    info "AGENTS.md update skipped (may need manual append)"
  ok "AGENTS.md updated with token-budget directive"
fi

# ── Optionally set contextTokens in openclaw.json ────────────────────

MAX_TOKENS=$(python3 -c "import json; print(json.load(open('$SCRIPT_DIR/token-budget.json'))['max_tokens'])" 2>/dev/null || echo "")
if [ -n "$MAX_TOKENS" ]; then
  openshell sandbox exec -n "$SANDBOX" -- python3 -c "
import json
p = '/sandbox/.openclaw/openclaw.json'
d = json.load(open(p))
d.setdefault('agents', {}).setdefault('defaults', {})['contextTokens'] = $MAX_TOKENS
with open(p, 'w') as f:
    json.dump(d, f, indent=2)
" 2>/dev/null || info "contextTokens update skipped (non-fatal)"
  ok "contextTokens set to $MAX_TOKENS in openclaw.json"
fi

# ── Clear sessions ───────────────────────────────────────────────────

info "Clearing sessions..."
openshell sandbox exec -n "$SANDBOX" -- bash -c \
  "[ -f $SESSIONS_PATH ] && echo '{}' > $SESSIONS_PATH || true" 2>/dev/null
ok "Sessions cleared"

echo ""
echo -e "${GREEN}  Token budget skill installed.${NC}"
echo "  Budget: ${MAX_TOKENS:-50000} tokens per session"
echo ""
echo "  Connect: nemoclaw $SANDBOX connect"
echo ""
