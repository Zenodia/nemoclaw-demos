#!/usr/bin/env bash
# =============================================================================
# Enterprise n8n Workflow — Full Install Script
#
# Sets up the complete stack:
#   1. Host venv  (fastmcp + httpx + python-dotenv + colorama)
#   2. MCP wrapper server  (host Python process on port 4300)
#   3. Sandbox network policy  (allows skill venv to reach port 4300)
#   4. OpenShell skill  (sandbox upload + venv + config.json + HEARTBEAT)
#
# Idempotent — each step checks whether it is already done before acting.
# Assumes the sandbox is already onboarded (nemoclaw onboard already run).
#
# Usage:
#   bash install.sh [sandbox-name]
#
#   sandbox-name  Target sandbox (auto-detected when only one exists).
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="$SCRIPT_DIR/.env"
MCP_PORT="${N8N_MCP_PORT:-4300}"
MCP_HOST="${N8N_MCP_HOST:-0.0.0.0}"
MCP_PATH="${N8N_MCP_PATH:-/mcp}"
MCP_PID_FILE="/tmp/n8n-mcp.pid"
MCP_LOG_FILE="/tmp/n8n-mcp.log"
SKILL_NAME="n8n-workflow-skills"
SKILL_SRC="$SCRIPT_DIR/n8n_workflow_skills"
SANDBOX_SKILL_ROOT="/sandbox/.openclaw/workspace/skills/$SKILL_NAME"
HOST_VENV="$SCRIPT_DIR/.venv"

SANDBOX_ARG="${1:-}"

# ── Colour helpers ────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'

info()  { echo -e "${CYAN}  ▸ $*${NC}"; }
ok()    { echo -e "${GREEN}  ✓ $*${NC}"; }
warn()  { echo -e "${YELLOW}  ⚠ $*${NC}"; }
fail()  { echo -e "${RED}  ✗ $*${NC}"; exit 1; }
step()  { echo ""; echo -e "${CYAN}━━━ $* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"; }

echo ""
echo -e "${CYAN}  ╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}  ║  Enterprise n8n Workflow — Installer                     ║${NC}"
echo -e "${CYAN}  ║  Host MCP wrapper  +  OpenShell skill                    ║${NC}"
echo -e "${CYAN}  ╚══════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "  MCP port  : ${GREEN}$MCP_PORT${NC}"
echo -e "  Sandbox   : ${GREEN}${SANDBOX_ARG:-auto-detect}${NC}"
echo ""

# =============================================================================
# STEP 0 — Clean up stale MCP server process
# =============================================================================
step "Step 0 — Clean up stale MCP server"

if [ -f "$MCP_PID_FILE" ]; then
  OLD_PID=$(cat "$MCP_PID_FILE" 2>/dev/null || true)
  if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
    kill "$OLD_PID" 2>/dev/null || true
    ok "Stopped existing MCP wrapper (PID $OLD_PID)"
  fi
  rm -f "$MCP_PID_FILE"
fi

STALE=$(pgrep -f "n8n_mcp_server" 2>/dev/null || true)
if [ -n "$STALE" ]; then
  # shellcheck disable=SC2086
  kill $STALE 2>/dev/null || true
  ok "Killed stale n8n_mcp_server process(es)"
fi
ok "Environment clean"

# =============================================================================
# STEP 1 — Prerequisites
# =============================================================================
step "Step 1 — Prerequisites"

command -v python3   >/dev/null 2>&1 || fail "python3 not found. Install Python 3.10+."
command -v openshell >/dev/null 2>&1 || fail "openshell CLI not found. Is NemoClaw installed?"
command -v curl      >/dev/null 2>&1 || fail "curl not found."

if ! command -v uv >/dev/null 2>&1; then
  warn "uv not found — installing..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
  command -v uv >/dev/null 2>&1 || fail "uv install failed. Add ~/.local/bin to PATH and retry."
  ok "uv installed"
fi

ok "Python    : $(python3 --version)"
ok "uv        : $(uv --version)"
ok "openshell : $(openshell --version 2>/dev/null | head -1 || echo found)"

# =============================================================================
# STEP 2 — Validate .env (required for the host wrapper)
# =============================================================================
step "Step 2 — Validate .env"

[ -f "$ENV_FILE" ] || fail ".env not found at $ENV_FILE. Create it with N8N_INSTANCE_URL and N8N_MCP_TOKEN."

# Load .env into the current shell without clobbering already-set vars.
while IFS= read -r line || [ -n "$line" ]; do
  [[ "$line" =~ ^[[:space:]]*# ]] && continue
  [[ -z "${line// }" ]] && continue
  key="${line%%=*}"
  val="${line#*=}"
  # strip surrounding single/double quotes
  val="${val#\"}" ; val="${val%\"}" ; val="${val#\'}" ; val="${val%\'}"
  [ -z "${!key+x}" ] && export "$key"="$val"
done < "$ENV_FILE"

[ -n "${N8N_INSTANCE_URL:-}" ]   || fail "N8N_INSTANCE_URL not set in .env"
[ -n "${N8N_MCP_TOKEN:-}" ]      || fail "N8N_MCP_TOKEN not set in .env"
[ -n "${INFERENCE_API_KEY:-}" ]  || fail "INFERENCE_API_KEY not set in .env (used by nemoclaw onboard + openshell provider)"
[ -n "${INFERENCE_BASE_URL:-}" ] || fail "INFERENCE_BASE_URL not set in .env (e.g. https://inference-api.nvidia.com/v1)"
[ -n "${INFERENCE_MODEL:-}" ]    || fail "INFERENCE_MODEL not set in .env (e.g. aws/anthropic/bedrock-claude-sonnet-4-6)"

INFERENCE_PROVIDER_TYPE="${INFERENCE_PROVIDER_TYPE:-nvidia}"
INFERENCE_PROVIDER_NAME="${INFERENCE_PROVIDER_NAME:-nvidia}"

ok "N8N_INSTANCE_URL    : $N8N_INSTANCE_URL"
ok "N8N_MCP_TOKEN       : ***${N8N_MCP_TOKEN: -8}"
ok "INFERENCE_API_KEY   : ***${INFERENCE_API_KEY: -8}"
ok "INFERENCE_BASE_URL  : $INFERENCE_BASE_URL"
ok "INFERENCE_MODEL     : $INFERENCE_MODEL"
ok "Provider            : $INFERENCE_PROVIDER_NAME ($INFERENCE_PROVIDER_TYPE)"

# =============================================================================
# STEP 3 — Host Python venv
# =============================================================================
step "Step 3 — Host Python venv ($HOST_VENV)"

cd "$SCRIPT_DIR"

if [ ! -d "$HOST_VENV" ]; then
  info "Creating host venv with Python 3.10..."
  uv venv --python 3.10 --quiet "$HOST_VENV"
  ok "venv created at $HOST_VENV"
else
  ok "Host venv already exists — skipping creation"
fi

info "Installing/verifying host requirements..."
VIRTUAL_ENV="$HOST_VENV" uv pip install --quiet -r "$SCRIPT_DIR/requirements.txt"
ok "Host requirements installed (fastmcp, httpx, python-dotenv, colorama)"

"$HOST_VENV/bin/python3" -c "import fastmcp, httpx, dotenv, colorama" \
  || fail "Import check failed in host venv — check $HOST_VENV"
ok "Import check passed"

# =============================================================================
# STEP 4 — Detect sandbox
# =============================================================================
step "Step 4 — Detect sandbox"

_live_sandboxes() {
  openshell sandbox list 2>/dev/null \
    | sed 's/\x1b\[[0-9;]*m//g' \
    | grep -v "^No sandboxes" | grep -v "^NAME" \
    | awk '{print $1}' | grep -v '^$' || true
}

LIVE_NAMES=$(_live_sandboxes)
LIVE_COUNT=$(echo "$LIVE_NAMES" | grep -c . || true)

# No sandbox? Drive 'nemoclaw onboard' end-to-end without prompts using
# INFERENCE_* from .env. We pick the "custom" (Other OpenAI-compatible)
# provider and feed it INFERENCE_BASE_URL + INFERENCE_API_KEY directly —
# the NVIDIA Endpoints menu option points at integrate.api.nvidia.com
# (the API Catalog) and would auth against the wrong endpoint.
# The canonical INFERENCE_PROVIDER_NAME is wired up below in the
# inference-provider step.
if [ "${LIVE_COUNT:-0}" -eq 0 ] && [ -z "$SANDBOX_ARG" ]; then
  info "No sandbox found — running 'nemoclaw onboard' (non-interactive)..."
  command -v nemoclaw >/dev/null 2>&1 || fail "nemoclaw CLI not found. Install NemoClaw and retry."

  export NEMOCLAW_NON_INTERACTIVE=1
  export NEMOCLAW_PROVIDER=custom
  export NEMOCLAW_ENDPOINT_URL="${INFERENCE_BASE_URL}"
  export NEMOCLAW_MODEL="${INFERENCE_MODEL}"
  export COMPATIBLE_API_KEY="${INFERENCE_API_KEY}"
  # Some legacy code paths still look for NVIDIA_API_KEY — stage same value.
  export NVIDIA_API_KEY="${NVIDIA_API_KEY:-$INFERENCE_API_KEY}"
  export NEMOCLAW_ACCEPT_THIRD_PARTY_SOFTWARE=1

  nemoclaw onboard --non-interactive --yes-i-accept-third-party-software \
    || fail "nemoclaw onboard failed. Check INFERENCE_* values in .env, then re-run install.sh."
  ok "Onboarding complete"

  info "Waiting for sandbox to appear..."
  for _ in $(seq 1 20); do
    LIVE_NAMES=$(_live_sandboxes)
    LIVE_COUNT=$(echo "$LIVE_NAMES" | grep -c . || true)
    [ "${LIVE_COUNT:-0}" -gt 0 ] && break
    sleep 2
  done
  [ "${LIVE_COUNT:-0}" -eq 0 ] && fail "No sandbox appeared after onboarding."
  ok "Sandbox onboarded"
fi

if [ -n "$SANDBOX_ARG" ]; then
  SANDBOX_NAME="$SANDBOX_ARG"
elif [ "${LIVE_COUNT:-0}" -eq 0 ]; then
  fail "No sandbox found. Run 'nemoclaw onboard' first, then re-run this script."
elif [ "${LIVE_COUNT:-0}" -eq 1 ]; then
  SANDBOX_NAME=$(echo "$LIVE_NAMES" | head -1)
else
  JSON_DEFAULT=$(python3 -c "
import json
try:
    d = json.load(open('$HOME/.nemoclaw/sandboxes.json'))
    print(d.get('defaultSandbox') or '')
except Exception:
    pass
" 2>/dev/null || true)
  if [ -n "${JSON_DEFAULT:-}" ] && echo "$LIVE_NAMES" | grep -qx "$JSON_DEFAULT"; then
    SANDBOX_NAME="$JSON_DEFAULT"
  else
    echo ""
    echo -e "  ${YELLOW}Multiple sandboxes found:${NC}"
    echo "$LIVE_NAMES" | while read -r n; do echo "    - $n"; done
    echo -n "  Which sandbox to use? "
    read -r SANDBOX_NAME
  fi
fi

[ -z "${SANDBOX_NAME:-}" ] && fail "Could not determine sandbox. Re-run: bash install.sh <sandbox-name>"
_live_sandboxes | grep -qx "$SANDBOX_NAME" || fail "Sandbox '$SANDBOX_NAME' not found."
ok "Target sandbox: $SANDBOX_NAME"

# =============================================================================
# STEP 4b — Inference provider + model (OpenShell gateway)
# =============================================================================
step "Step 4b — Inference provider + model"

if openshell provider get "$INFERENCE_PROVIDER_NAME" >/dev/null 2>&1; then
  openshell provider update "$INFERENCE_PROVIDER_NAME" \
    --credential INFERENCE_API_KEY \
    --config "NVIDIA_BASE_URL=$INFERENCE_BASE_URL" \
    2>/dev/null \
    && ok "Provider '$INFERENCE_PROVIDER_NAME' updated" \
    || warn "Provider '$INFERENCE_PROVIDER_NAME' update failed — continuing"
else
  openshell provider create \
    --type  "$INFERENCE_PROVIDER_TYPE" \
    --name  "$INFERENCE_PROVIDER_NAME" \
    --credential INFERENCE_API_KEY \
    --config "NVIDIA_BASE_URL=$INFERENCE_BASE_URL" \
    && ok "Provider '$INFERENCE_PROVIDER_NAME' created" \
    || fail "Could not create inference provider."
fi

openshell inference set \
  --provider "$INFERENCE_PROVIDER_NAME" \
  --model    "$INFERENCE_MODEL" \
  --no-verify \
  && ok "Inference: $INFERENCE_PROVIDER_NAME / $INFERENCE_MODEL" \
  || fail "Could not set inference model."

# =============================================================================
# STEP 4c — Patch openclaw.json inside sandbox with the chosen model
# =============================================================================
step "Step 4c — Patch openclaw model inside sandbox"

# openclaw.json is root-owned (444) inside the sandbox — cannot be written by the
# sandbox user. We reach it via kubectl exec (root) through the cluster container.
_CLUSTER_CONTAINER=$(docker ps --format "{{.Names}}" 2>/dev/null \
  | grep "^openshell-cluster-" | head -1 || true)

if [ -z "${_CLUSTER_CONTAINER:-}" ]; then
  warn "OpenShell cluster container not found — skipping openclaw model patch."
  warn "Connect to the sandbox and run: openclaw onboard (choose $INFERENCE_MODEL)"
else
  docker exec "$_CLUSTER_CONTAINER" \
    kubectl exec -n openshell "$SANDBOX_NAME" -c agent -- \
    sh -c "
      python3 -c \"
import json
with open('/sandbox/.openclaw/openclaw.json') as f:
    d = json.load(f)
model = '$INFERENCE_MODEL'
d['models']['providers']['inference']['models'] = [{
    'id': model,
    'name': 'inference/' + model,
    'reasoning': False,
    'input': ['text'],
    'cost': {'input': 0, 'output': 0, 'cacheRead': 0, 'cacheWrite': 0},
    'contextWindow': 131072,
    'maxTokens': 4096
}]
d['agents']['defaults']['model']['primary'] = 'inference/' + model
with open('/sandbox/.openclaw/openclaw.json', 'w') as f:
    json.dump(d, f, indent=2)
\"
    " \
    && ok "openclaw patched: inference/$INFERENCE_MODEL" \
    || fail "Failed to patch openclaw.json inside sandbox."
fi

# =============================================================================
# STEP 4d — OpenClaw gateway token + chat-UI URL
# =============================================================================
step "Step 4d — OpenClaw gateway token + chat-UI URL"

# Upload helper scripts (idempotent — overwrites whatever was there)
_oc_upload_stage="/tmp/n8n-install-stage"
openshell sandbox exec -n "$SANDBOX_NAME" -- \
  sh -c "mkdir -p ${_oc_upload_stage}" 2>/dev/null || true

openshell sandbox upload "$SANDBOX_NAME" \
  "$SCRIPT_DIR/scripts/set_oc_token.py" \
  "${_oc_upload_stage}/" \
  >/dev/null 2>&1 \
  && ok "uploaded set_oc_token.py" \
  || warn "set_oc_token.py upload failed — skipping gateway token step"

openshell sandbox upload "$SANDBOX_NAME" \
  "$SCRIPT_DIR/scripts/start_oc_gateway.sh" \
  "${_oc_upload_stage}/" \
  >/dev/null 2>&1 \
  && ok "uploaded start_oc_gateway.sh" \
  || warn "start_oc_gateway.sh upload failed — skipping gateway token step"

# Run the launcher inside the sandbox. It:
#   - kills any old gateway
#   - persists a random token into /sandbox/.openclaw/openclaw.json
#   - starts gateway detached on 127.0.0.1:18789
#   - writes /tmp/oc-token.env containing TOKEN=<hex>
openshell sandbox exec -n "$SANDBOX_NAME" -- \
  sh -c "cp -f ${_oc_upload_stage}/set_oc_token.py /tmp/set_oc_token.py && cp -f ${_oc_upload_stage}/start_oc_gateway.sh /tmp/start_oc_gateway.sh && chmod +x /tmp/set_oc_token.py /tmp/start_oc_gateway.sh && SET_TOKEN_PY=/tmp/set_oc_token.py sh /tmp/start_oc_gateway.sh" \
  2>&1 | sed 's/^/      /' \
  || warn "Gateway launcher reported errors — see output above"

# Read back the token from the sandbox
OC_GATEWAY_TOKEN=$(openshell sandbox exec -n "$SANDBOX_NAME" -- \
  sh -c "test -f /tmp/oc-token.env && . /tmp/oc-token.env && echo \"\$TOKEN\"" \
  2>/dev/null | tr -d '\r\n' || true)

if [ -n "${OC_GATEWAY_TOKEN:-}" ]; then
  ok "Gateway token persisted: ***${OC_GATEWAY_TOKEN: -8}"
else
  warn "Could not read /tmp/oc-token.env from sandbox — token unknown."
  warn "Inside sandbox: jq -r '.gateway.auth.token' /sandbox/.openclaw/openclaw.json"
fi

# Ensure the host port-forward is up so the user can hit :18789 from outside
if openshell forward list 2>/dev/null | grep -q "${SANDBOX_NAME}.*18789.*running"; then
  ok "Port-forward already running: 127.0.0.1:18789 → ${SANDBOX_NAME}:18789"
else
  openshell forward start 18789 "$SANDBOX_NAME" 2>&1 | sed 's/^/      /' || \
    warn "openshell forward start 18789 failed — run it manually."
fi

# =============================================================================
# STEP 5 — Start MCP wrapper on port $MCP_PORT
# =============================================================================
step "Step 5 — MCP wrapper (port $MCP_PORT)"

_wrapper_up() {
  curl -s --max-time 2 "http://127.0.0.1:${MCP_PORT}${MCP_PATH}" >/dev/null 2>&1
}

if _wrapper_up; then
  ok "MCP wrapper already running on port $MCP_PORT — skipping start"
else
  info "Starting MCP wrapper in background..."
  (
    cd "$SCRIPT_DIR"
    # shellcheck disable=SC1091
    source "$HOST_VENV/bin/activate"
    export N8N_INSTANCE_URL="$N8N_INSTANCE_URL"
    export N8N_MCP_TOKEN="$N8N_MCP_TOKEN"
    export N8N_MCP_HOST="$MCP_HOST"
    export N8N_MCP_PORT="$MCP_PORT"
    export N8N_MCP_PATH="$MCP_PATH"
    while true; do
      python3 n8n_mcp_server.py \
        --host "$MCP_HOST" --port "$MCP_PORT" --path "$MCP_PATH"
      echo "[n8n-mcp] Server exited (code $?), restarting in 2s..." >> "$MCP_LOG_FILE"
      sleep 2
    done
  ) >> "$MCP_LOG_FILE" 2>&1 &
  echo $! > "$MCP_PID_FILE"
  ok "MCP wrapper launched (PID $(cat $MCP_PID_FILE))"

  info "Waiting for MCP wrapper to become ready..."
  MCP_UP=false
  for _ in $(seq 1 20); do
    sleep 1
    if _wrapper_up; then MCP_UP=true; break; fi
  done
  if $MCP_UP; then
    ok "MCP wrapper is up on http://127.0.0.1:${MCP_PORT}${MCP_PATH}"
  else
    kill -0 "$(cat "$MCP_PID_FILE" 2>/dev/null)" 2>/dev/null \
      && warn "MCP wrapper started but not yet responding — check: tail -f $MCP_LOG_FILE" \
      || fail "MCP wrapper exited immediately. Check: cat $MCP_LOG_FILE"
  fi
fi

# =============================================================================
# STEP 6 — Apply sandbox network policy
# =============================================================================
step "Step 6 — Sandbox network policy"

POLICY_FILE="$SCRIPT_DIR/policy/sandbox_policy.yaml"
[ -f "$POLICY_FILE" ] || fail "Policy file not found: $POLICY_FILE"

openshell policy set "$SANDBOX_NAME" \
  --policy "$POLICY_FILE" \
  --wait \
  && ok "Policy applied (port $MCP_PORT allowed for skill venv)" \
  || fail "Failed to apply sandbox policy."

# =============================================================================
# STEP 7 — Upload skill to sandbox
# =============================================================================
step "Step 7 — Upload skill"

[ -f "$SKILL_SRC/SKILL.md" ] || fail "SKILL.md missing at $SKILL_SRC"

openshell sandbox upload "$SANDBOX_NAME" \
  "$SKILL_SRC" \
  "$SANDBOX_SKILL_ROOT" \
  && ok "Skill uploaded to $SANDBOX_SKILL_ROOT" \
  || fail "Skill upload failed."

SKILL_CONFIRM=$(openshell sandbox exec -n "$SANDBOX_NAME" -- \
  sh -c "test -f ${SANDBOX_SKILL_ROOT}/SKILL.md && echo ok" 2>/dev/null || true)
[ "$SKILL_CONFIRM" = "ok" ] \
  || fail "SKILL.md not found in sandbox after upload."
ok "Upload confirmed"

# Upload HEARTBEAT.md to workspace root so the agent picks up routing rules on every session start.
HEARTBEAT_SRC="$SKILL_SRC/HEARTBEAT.md"
HEARTBEAT_DEST="/sandbox/.openclaw-data/workspace/HEARTBEAT.md"
if [ -f "$HEARTBEAT_SRC" ]; then
  openshell sandbox upload "$SANDBOX_NAME" \
    "$HEARTBEAT_SRC" \
    "$HEARTBEAT_DEST" \
    && ok "HEARTBEAT.md uploaded to $HEARTBEAT_DEST" \
    || warn "HEARTBEAT.md upload failed — agent may not invoke skill tools correctly"
fi

# =============================================================================
# STEP 8 — Write config.json into sandbox skill root
# =============================================================================
step "Step 8 — Write config.json"

POLL_INTERVAL="${N8N_POLL_INTERVAL_SEC:-3}"
POLL_TIMEOUT="${N8N_POLL_TIMEOUT_SEC:-600}"

CONFIG_JSON="{\"server_url\":\"http://host.openshell.internal:${MCP_PORT}${MCP_PATH}\",\"poll_interval_sec\":${POLL_INTERVAL},\"poll_timeout_sec\":${POLL_TIMEOUT}}"

openshell sandbox exec -n "$SANDBOX_NAME" -- \
  sh -c "echo '${CONFIG_JSON}' > ${SANDBOX_SKILL_ROOT}/config.json" \
  && ok "config.json written to ${SANDBOX_SKILL_ROOT}/config.json" \
  || warn "Could not write config.json — run setup_config.py inside the sandbox manually"

# =============================================================================
# STEP 9 — Bootstrap skill venv inside sandbox
# =============================================================================
step "Step 9 — Skill venv (sandbox)"

SKILL_VENV="${SANDBOX_SKILL_ROOT}/venv"

VENV_CHECK=$(openshell sandbox exec -n "$SANDBOX_NAME" -- \
  sh -c "test -f ${SKILL_VENV}/bin/python3 && ${SKILL_VENV}/bin/python3 -c 'import fastmcp; print(fastmcp.__version__)' 2>/dev/null || echo missing" \
  2>/dev/null || echo missing)

if [ "$VENV_CHECK" = "missing" ]; then
  info "Creating skill venv..."
  openshell sandbox exec -n "$SANDBOX_NAME" -- \
    python3 -m venv "$SKILL_VENV" \
    || fail "Failed to create skill venv inside sandbox."
  ok "Skill venv created"

  info "Installing fastmcp..."
  openshell sandbox exec -n "$SANDBOX_NAME" -- \
    "${SKILL_VENV}/bin/pip" install -q fastmcp \
    || fail "pip install fastmcp failed inside sandbox."
  ok "fastmcp installed"
else
  ok "fastmcp $VENV_CHECK already installed in skill venv — skipping"
fi

IMPORT_CHECK=$(openshell sandbox exec -n "$SANDBOX_NAME" -- \
  "${SKILL_VENV}/bin/python3" -c "import fastmcp; print('ok')" 2>/dev/null || true)
[ "$IMPORT_CHECK" = "ok" ] \
  || fail "fastmcp import check failed in skill venv. Re-run install.sh."
ok "fastmcp import verified in skill venv"

# =============================================================================
# STEP 10 — Verification
# =============================================================================
step "Step 10 — Verification"

_check() {
  local label="$1" result="$2"
  [ "$result" = "ok" ] \
    && ok "$label" \
    || warn "$label — FAILED (check logs)"
}

# MCP wrapper
MCP_STATUS=$(curl -s --max-time 3 "http://127.0.0.1:${MCP_PORT}${MCP_PATH}" 2>&1 | wc -c || echo 0)
[ "${MCP_STATUS:-0}" -gt 0 ] \
  && ok "MCP wrapper : http://127.0.0.1:${MCP_PORT}${MCP_PATH}" \
  || warn "MCP wrapper : not responding — check: cat $MCP_LOG_FILE"

# Skill in sandbox
SKILL_V=$(openshell sandbox exec -n "$SANDBOX_NAME" -- \
  sh -c "test -f ${SANDBOX_SKILL_ROOT}/SKILL.md && echo ok" 2>/dev/null || true)
_check "Skill upload: $SANDBOX_SKILL_ROOT"  "$SKILL_V"

# config.json
CFG_V=$(openshell sandbox exec -n "$SANDBOX_NAME" -- \
  sh -c "test -f ${SANDBOX_SKILL_ROOT}/config.json && echo ok" 2>/dev/null || true)
_check "config.json : $SANDBOX_SKILL_ROOT"  "$CFG_V"

# HEARTBEAT.md
HB_V=$(openshell sandbox exec -n "$SANDBOX_NAME" -- \
  sh -c "test -f /sandbox/.openclaw-data/workspace/HEARTBEAT.md && echo ok" 2>/dev/null || true)
_check "HEARTBEAT   : /sandbox/.openclaw-data/workspace/HEARTBEAT.md"  "$HB_V"

# fastmcp in skill venv
FM_V=$(openshell sandbox exec -n "$SANDBOX_NAME" -- \
  "${SKILL_VENV}/bin/python3" -c "import fastmcp; print('ok')" 2>/dev/null || true)
_check "fastmcp venv: $SKILL_VENV"  "$FM_V"

# Skill end-to-end: run n8n_health from inside the sandbox
HEALTH_OUT=$(openshell sandbox exec -n "$SANDBOX_NAME" -- \
  "${SKILL_VENV}/bin/python3" "${SANDBOX_SKILL_ROOT}/scripts/n8n_client.py" n8n_health 2>&1 || true)
if echo "$HEALTH_OUT" | grep -q '"status": "ok"'; then
  ok "Skill end-to-end: n8n_health → status ok"
else
  warn "Skill end-to-end: n8n_health did not return ok"
  echo "$HEALTH_OUT" | sed 's/^/      /'
fi

# Skill read-only path: list_workflows from inside the sandbox (proves the
# composed search_workflows path + filter, without triggering any workflow).
LIST_OUT=$(openshell sandbox exec -n "$SANDBOX_NAME" -- \
  "${SKILL_VENV}/bin/python3" "${SANDBOX_SKILL_ROOT}/scripts/n8n_client.py" list_workflows 2>&1 || true)
if echo "$LIST_OUT" | grep -q '"id"'; then
  LIST_N=$(echo "$LIST_OUT" | grep -c '"id"' || true)
  ok "Skill end-to-end: list_workflows → ${LIST_N} executable workflow(s)"
elif echo "$LIST_OUT" | grep -q '^\[\]$'; then
  warn "Skill end-to-end: list_workflows → [] (user lacks workflow:execute, or no 'Available in MCP' workflows)"
else
  warn "Skill end-to-end: list_workflows did not return a workflow list"
  echo "$LIST_OUT" | sed 's/^/      /'
fi

# NOTE: execute_workflow is intentionally NOT smoke-tested here — it triggers a
# real workflow run (LLM + sub-workflows). Verify it manually after install:
#   $SKILL execute_workflow --workflow-id <id> --query "..."
# It POSTs the workflow's n8n webhook directly (see Step-5 note) and returns the
# final node output synchronously.

# =============================================================================
# Done
# =============================================================================
echo ""
echo -e "${GREEN}  ╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}  ║  Installation complete!                                  ║${NC}"
echo -e "${GREEN}  ╚══════════════════════════════════════════════════════════╝${NC}"
echo ""
echo "  MCP wrapper  : http://127.0.0.1:${MCP_PORT}${MCP_PATH}  (PID $(cat "$MCP_PID_FILE" 2>/dev/null || echo '?'))"
echo "  Sandbox URL  : http://host.openshell.internal:${MCP_PORT}${MCP_PATH}"
echo "  Wrapper logs : tail -f $MCP_LOG_FILE"
echo ""

if [ -n "${OC_GATEWAY_TOKEN:-}" ]; then
  echo -e "${CYAN}  ── OpenClaw chat UI ──────────────────────────────────────${NC}"
  echo "  Browser URL  : http://127.0.0.1:18789/#token=${OC_GATEWAY_TOKEN}"
  echo "  TUI env      : export OPENCLAW_GATEWAY_TOKEN=${OC_GATEWAY_TOKEN}"
  echo "                 openclaw tui      (inside sandbox)"
  echo ""
  echo "  If you're on a remote brev host, forward port 18789 to your laptop:"
  echo "    brev port-forward <instance> -p 18789:18789"
  echo "    # then open the Browser URL above"
  echo ""
fi

echo "  Next steps:"
echo "    1. Connect : nemoclaw $SANDBOX_NAME connect"
echo "    2. Try: \"what n8n workflows can I run?\""
echo "    3. Try: \"describe workflow <id>\""
echo "    4. Try: \"run workflow <id> with query 'find files containing roadmap in OneDrive'\""
echo "    5. Try: \"find NVbugs related to NeMo using workflow <id>\""
echo ""
echo "  Update config.json (server_url / polling):"
echo "    openshell sandbox exec -n $SANDBOX_NAME -- \\"
echo "      ${SKILL_VENV}/bin/python3 ${SANDBOX_SKILL_ROOT}/scripts/setup_config.py"
echo ""
echo "  Restart MCP wrapper:"
echo "    kill \$(cat $MCP_PID_FILE) && bash $SCRIPT_DIR/install.sh $SANDBOX_NAME"
echo ""
