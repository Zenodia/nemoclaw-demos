#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CREDS_PATH="$HOME/.nemoclaw/credentials.json"
RAG_PORT=9004
RAG_PID_FILE="/tmp/haystack-rag.pid"
RAG_LOG_FILE="/tmp/haystack-rag.log"
OPENCLAW_LOG="/tmp/openclaw-gateway.log"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

info()  { echo -e "${CYAN}  ▸ $1${NC}"; }
ok()    { echo -e "${GREEN}  ✓ $1${NC}"; }
warn()  { echo -e "${YELLOW}  ⚠ $1${NC}"; }
fail()  { echo -e "${RED}  ✗ $1${NC}"; exit 1; }

echo ""
echo -e "${CYAN}  ╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}  ║  Haystack RAG Demo Installer for NemoClaw                ║${NC}"
echo -e "${CYAN}  ║  NVIDIA NIM • Haystack • OpenClaw • Host-Side Server     ║${NC}"
echo -e "${CYAN}  ╚══════════════════════════════════════════════════════════╝${NC}"
echo ""

# ── Step 0: Clean up stale server process ────────────────────────
info "Cleaning up stale environment..."
if [ -f "$RAG_PID_FILE" ]; then
  OLD_PID=$(cat "$RAG_PID_FILE" 2>/dev/null || true)
  if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
    kill "$OLD_PID" 2>/dev/null || true
    ok "Killed existing RAG server (PID $OLD_PID)"
  fi
  rm -f "$RAG_PID_FILE"
fi
STALE=$(pgrep -f "haystack_rag_server" 2>/dev/null || true)
if [ -n "$STALE" ]; then
  kill $STALE 2>/dev/null || true
  ok "Killed stale RAG server process(es)"
fi
ok "Environment clean"
echo ""

# ── Step 1: Check prerequisites ──────────────────────────────────
info "Checking prerequisites..."
command -v openshell >/dev/null 2>&1 || fail "openshell CLI not found. Is NemoClaw installed?"
command -v nemoclaw  >/dev/null 2>&1 || fail "nemoclaw CLI not found. Is NemoClaw installed?"
command -v python3   >/dev/null 2>&1 || fail "python3 not found."
command -v curl      >/dev/null 2>&1 || fail "curl not found."

if ! command -v uv >/dev/null 2>&1; then
  warn "uv not found — installing..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
  command -v uv >/dev/null 2>&1 || fail "uv install failed. Add ~/.local/bin to PATH and retry."
  ok "uv installed"
fi

ok "Prerequisites OK"
echo ""

# ── Step 2: Load .env and resolve configuration ──────────────────
info "Loading configuration..."

if [ -f "$SCRIPT_DIR/.env" ]; then
  while IFS= read -r line || [ -n "$line" ]; do
    [[ "$line" =~ ^[[:space:]]*# ]] && continue
    [[ -z "${line// }" ]] && continue
    key="${line%%=*}"
    val="${line#*=}"
    # strip inline comment (anything after whitespace + #)
    [[ "$val" =~ ^([^#]*[^[:space:]])[[:space:]]+\# ]] && val="${BASH_REMATCH[1]}"
    val="${val#\"}" ; val="${val%\"}" ; val="${val#\'}" ; val="${val%\'}"
    val="${val%"${val##*[! ]}"}"  # rtrim whitespace
    [ -z "${!key+x}" ] && export "$key"="$val"
  done < "$SCRIPT_DIR/.env"
  ok "Loaded .env from $SCRIPT_DIR/.env"
fi

# Fall back to credentials.json
if [ -z "${NVIDIA_API_KEY:-}" ] && [ -f "$CREDS_PATH" ]; then
  NVIDIA_API_KEY=$(python3 -c "
import json
print(json.load(open('$CREDS_PATH')).get('NVIDIA_API_KEY',''))
" 2>/dev/null || true)
  [ -n "${NVIDIA_API_KEY:-}" ] && ok "NVIDIA_API_KEY loaded from $CREDS_PATH"
fi

[ -z "${NVIDIA_API_KEY:-}" ] && \
  fail "NVIDIA_API_KEY is not set. Add it to $SCRIPT_DIR/.env or run: export NVIDIA_API_KEY=nvapi-..."

INFERENCE_PROVIDER_TYPE="${INFERENCE_PROVIDER_TYPE:-nvidia}"
INFERENCE_PROVIDER_NAME="${INFERENCE_PROVIDER_NAME:-nvidia}"
INFERENCE_BASE_URL="${INFERENCE_BASE_URL:-https://integrate.api.nvidia.com/v1}"
INFERENCE_MODEL="${INFERENCE_MODEL:-nvidia/llama-3.3-nemotron-super-49b-v1.5}"
OPENCLAW_MODEL="${OPENCLAW_MODEL:-nvidia/llama-3.3-nemotron-super-49b-v1.5}"

ok "NVIDIA_API_KEY      : found"
ok "INFERENCE_MODEL     : $INFERENCE_MODEL"
ok "OPENCLAW_MODEL      : $OPENCLAW_MODEL"
echo ""

# ── Step 3: Install openclaw (if not already present) ────────────
info "Checking openclaw installation..."

# openclaw installs via npm into whichever node runtime is active (nvm, system, etc.)
# After installation we search common locations and add the containing dir to PATH.
_ensure_openclaw_path() {
  # Already on PATH — nothing to do
  command -v openclaw >/dev/null 2>&1 && return 0
  # Search inside nvm and standard bin locations
  local found
  found=$(find \
    "$HOME/.nvm/versions" "$HOME/.local/bin" "$HOME/.cargo/bin" \
    /usr/local/bin /usr/bin \
    -maxdepth 4 -name "openclaw" -type f 2>/dev/null | head -1 || true)
  if [ -n "$found" ]; then
    export PATH="$(dirname "$found"):$PATH"
    return 0
  fi
  return 1
}

if ! _ensure_openclaw_path; then
  info "openclaw not found — installing (--no-onboard)..."
  curl -fsSL --proto '=https' --tlsv1.2 https://openclaw.ai/install.sh | bash -s -- --no-onboard
  _ensure_openclaw_path || \
    fail "openclaw install failed. Run 'openclaw onboard' manually after adding its bin dir to PATH."
  ok "openclaw installed"
else
  ok "openclaw already installed: $(openclaw --version 2>/dev/null | head -1 || echo 'version unknown')"
fi
mkdir -p "$HOME/.openclaw"
echo ""

# ── Step 4: Configure openclaw with NVIDIA API ───────────────────
info "Configuring openclaw with NVIDIA API key..."
#
# Stores the NVIDIA_API_KEY inside openclaw's config. OpenClaw injects it
# into the sandbox environment when running skills, but the sandbox policy
# strips it before the skill process starts — all actual inference runs on
# the host via haystack_rag_server.py, not from inside the sandbox.
#
openclaw onboard \
  --non-interactive \
  --accept-risk \
  --mode local \
  --no-install-daemon \
  --skip-skills \
  --skip-health \
  --auth-choice nvidia-api-key \
  --custom-base-url "https://integrate.api.nvidia.com/v1" \
  --custom-model-id "$OPENCLAW_MODEL" \
  --custom-image-input \
  --custom-compatibility openai \
  --nvidia-api-key "$NVIDIA_API_KEY" \
  --secret-input-mode plaintext \
  || fail "openclaw onboard failed. Check your NVIDIA_API_KEY and retry."
ok "openclaw configured (model: $OPENCLAW_MODEL)"
echo ""

# ── Step 5: Restart openclaw gateway ─────────────────────────────
info "Restarting openclaw gateway..."
pkill -f "openclaw gateway run" 2>/dev/null || true
sleep 1
nohup openclaw gateway run > "$OPENCLAW_LOG" 2>&1 &
sleep 3

if tail -5 "$OPENCLAW_LOG" 2>/dev/null | grep -qi "error\|failed\|panic"; then
  warn "openclaw gateway may have errors — check: tail -20 $OPENCLAW_LOG"
else
  ok "openclaw gateway started (logs: $OPENCLAW_LOG)"
fi

TOKEN=$(python3 -c "
import json
try:
    d = json.load(open('$HOME/.openclaw/openclaw.json'))
    print(d.get('gateway', {}).get('auth', {}).get('token', '') or '')
except: pass
" 2>/dev/null || true)
[ -n "${TOKEN:-}" ] \
  && ok "WebUI: http://127.0.0.1:18789/#token=$TOKEN" \
  || warn "Could not extract token — run: python3 -c \"import json; d=json.load(open('~/.openclaw/openclaw.json')); print(d['gateway']['auth']['token'])\""
echo ""

# ── Step 6: Install host-side Python deps for the RAG server ─────
info "Installing host-side Python dependencies for RAG server..."
cd "$SCRIPT_DIR"
uv venv --quiet --seed --allow-existing 2>/dev/null || uv venv --quiet --seed
uv pip install --quiet --upgrade \
  "fastapi" \
  "uvicorn[standard]" \
  "python-dotenv" \
  "haystack-ai>=2.18.1,<3.0.0" \
  "nvidia-haystack~=0.3.0" \
  "pypdf~=6.5"
ok "Host dependencies installed in .venv"

# Create data directories the server will use
mkdir -p "$SCRIPT_DIR/data/documents"
ok "Data directory ready at $SCRIPT_DIR/data/documents"
echo ""

# ── Step 7: Start Haystack RAG server as background process ──────
info "Starting Haystack RAG server in background (port $RAG_PORT)..."

if lsof -t -i:"$RAG_PORT" >/dev/null 2>&1; then
  kill $(lsof -t -i:"$RAG_PORT") 2>/dev/null || true
  sleep 1
  ok "Freed port $RAG_PORT (killed stale listener)"
fi

(
  cd "$SCRIPT_DIR"
  source .venv/bin/activate
  export NVIDIA_API_KEY="$NVIDIA_API_KEY"
  while true; do
    kill $(lsof -t -i:"$RAG_PORT") 2>/dev/null || true
    python haystack_rag_server.py \
      --port "$RAG_PORT" \
      --store-path "$SCRIPT_DIR/data/store.json" \
      --data-dir "$SCRIPT_DIR/data/documents" || true
    echo "[haystack-rag] Server exited, restarting in 2s..." >> "$RAG_LOG_FILE"
    sleep 2
  done
) >> "$RAG_LOG_FILE" 2>&1 &

echo $! > "$RAG_PID_FILE"
ok "RAG server started (PID $(cat $RAG_PID_FILE))"

# Wait up to 10s for the server to respond
SERVER_UP=false
for i in $(seq 1 10); do
  sleep 1
  if curl -s --max-time 1 "http://127.0.0.1:${RAG_PORT}/health" >/dev/null 2>&1; then
    SERVER_UP=true
    break
  fi
done

if [ "$SERVER_UP" = true ]; then
  ok "RAG server is up on port $RAG_PORT"
else
  if kill -0 "$(cat $RAG_PID_FILE 2>/dev/null)" 2>/dev/null; then
    warn "RAG server started but not yet responding — check: tail -f $RAG_LOG_FILE"
  else
    fail "RAG server process exited immediately. Check: cat $RAG_LOG_FILE"
  fi
fi
echo ""

# ── Step 8: Onboard nemoclaw sandbox (if none exists) ────────────
live_sandboxes() {
  openshell sandbox list 2>/dev/null \
    | sed 's/\x1b\[[0-9;]*m//g' \
    | awk 'NR>1 && NF {print $1}' \
    | grep -v '^$' || true
}

wait_for_live_sandbox() {
  local count=0 attempt=0
  while [ "$attempt" -lt 20 ]; do
    count=$(live_sandboxes | wc -l | tr -d '[:space:]')
    if [ "${count:-0}" -gt 0 ]; then
      return 0
    fi
    attempt=$((attempt + 1))
    sleep 1
  done
  return 1
}

LIVE_COUNT=$(live_sandboxes | wc -l | tr -d ' ')

# nemoclaw onboard step [8/8] fails with "policy is managed globally" when a
# gateway-global policy is active. Delete it here so onboard can set its own
# network presets (npm, pypi, etc.). We then apply our per-sandbox policy
# after the sandbox is created and its name is resolved (see Step 10 below).
info "Clearing any global network policy (required for nemoclaw onboard)..."
openshell policy delete --global --yes 2>/dev/null \
  && ok "Global policy cleared" \
  || true  # No global policy is fine — continue normally
echo ""

if [ "${LIVE_COUNT:-0}" -eq 0 ]; then
  info "No sandbox found — running 'nemoclaw onboard' (non-interactive)..."
  command -v nemoclaw >/dev/null 2>&1 || fail "nemoclaw CLI not found. Install NemoClaw and retry."

  export NEMOCLAW_NON_INTERACTIVE=1
  export NEMOCLAW_PROVIDER=custom
  export NEMOCLAW_ENDPOINT_URL="${INFERENCE_BASE_URL}"
  export NEMOCLAW_MODEL="${INFERENCE_MODEL}"
  export COMPATIBLE_API_KEY="${NVIDIA_API_KEY}"
  export NEMOCLAW_ACCEPT_THIRD_PARTY_SOFTWARE=1

  nemoclaw onboard --non-interactive --yes-i-accept-third-party-software \
    || fail "nemoclaw onboard failed. Check INFERENCE_* values in .env, then re-run install.sh."
  ok "Onboarding complete"
  echo ""

  info "Waiting for sandbox to become ready..."
  wait_for_live_sandbox \
    || fail "No sandbox appeared after onboarding. Run 'openshell sandbox list' to check."
  LIVE_COUNT=$(live_sandboxes | wc -l | tr -d '[:space:]')
fi

# ── Step 8b: Enforce inference provider in sandbox ───────────────
info "Ensuring inference provider '$INFERENCE_PROVIDER_NAME' in sandbox..."
openshell provider create \
  --type "$INFERENCE_PROVIDER_TYPE" \
  --name "$INFERENCE_PROVIDER_NAME" \
  --credential NVIDIA_API_KEY \
  --config "NVIDIA_BASE_URL=$INFERENCE_BASE_URL" \
  2>/dev/null \
  && ok "Provider '$INFERENCE_PROVIDER_NAME' created" \
  || ok "Provider '$INFERENCE_PROVIDER_NAME' already exists"

info "Setting inference model to $INFERENCE_MODEL..."
openshell inference set \
  --provider "$INFERENCE_PROVIDER_NAME" \
  --model "$INFERENCE_MODEL" \
  && ok "Inference set: $INFERENCE_PROVIDER_NAME / $INFERENCE_MODEL" \
  || fail "Could not set inference model."
echo ""

# ── Step 9: Resolve sandbox name ─────────────────────────────────
if [ -n "${1:-}" ]; then
  SANDBOX_NAME="$1"
else
  LIVE_NAMES=$(live_sandboxes)
  LIVE_COUNT=$(echo "$LIVE_NAMES" | grep -c . || true)

  if [ "${LIVE_COUNT:-0}" -eq 1 ]; then
    SANDBOX_NAME=$(echo "$LIVE_NAMES" | head -1)
  else
    JSON_DEFAULT=$(python3 -c "
import json
try:
    d = json.load(open('$HOME/.nemoclaw/sandboxes.json'))
    print(d.get('defaultSandbox') or '')
except: pass
" 2>/dev/null || true)

    if [ -n "${JSON_DEFAULT:-}" ] && echo "$LIVE_NAMES" | grep -qx "$JSON_DEFAULT"; then
      SANDBOX_NAME="$JSON_DEFAULT"
    else
      echo ""
      echo -e "  ${YELLOW}Multiple sandboxes found:${NC}"
      echo "$LIVE_NAMES" | while read -r n; do echo "    - $n"; done
      echo ""
      echo -n "  Which sandbox should be used? "
      read -r SANDBOX_NAME
    fi
  fi
fi

[ -z "${SANDBOX_NAME:-}" ] && \
  fail "Could not determine sandbox name. Usage: ./install.sh <sandbox-name>"

if ! live_sandboxes | grep -qx "$SANDBOX_NAME"; then
  echo ""
  echo -e "  ${RED}  ✗ Sandbox '$SANDBOX_NAME' not found. Live sandboxes:${NC}"
  live_sandboxes | while read -r n; do echo "    - $n"; done
  echo ""
  fail "Re-run with: bash install.sh <sandbox-name>"
fi

info "Target sandbox: $SANDBOX_NAME"
echo ""

# Persist credentials
mkdir -p "$(dirname "$CREDS_PATH")"
python3 -c "
import json, os
path = '$CREDS_PATH'
try: d = json.load(open(path))
except: d = {}
d['NVIDIA_API_KEY'] = '$NVIDIA_API_KEY'
d['INFERENCE_PROVIDER_TYPE'] = '$INFERENCE_PROVIDER_TYPE'
d['INFERENCE_PROVIDER_NAME'] = '$INFERENCE_PROVIDER_NAME'
d['INFERENCE_BASE_URL'] = '$INFERENCE_BASE_URL'
d['INFERENCE_MODEL'] = '$INFERENCE_MODEL'
with open(path, 'w') as f: json.dump(d, f, indent=2)
os.chmod(path, 0o600)
" 2>/dev/null || true

# ── Step 10: Apply sandbox network policy ───────────────────────
# Applied per-sandbox (not global) so nemoclaw onboard's preset step can run
# without conflict. Safe on a fresh sandbox — no filesystem_policy in our YAML
# means nothing to remove from the sandbox image's built-in policy.
# On a live sandbox, OpenShell may reject policy changes that remove filesystem
# rules; upload + skill registration still proceed, but egress to port 9004 may
# need a sandbox recreate if policy was never applied successfully.
info "Applying sandbox network policy..."
openshell policy set "$SANDBOX_NAME" \
  --policy "$SCRIPT_DIR/policy/sandbox_policy.yaml" \
  --wait \
  && ok "Policy applied (haystack_rag_host egress on port $RAG_PORT)" \
  || warn "Policy set failed — egress to port $RAG_PORT may be blocked (recreate sandbox if queries fail)"
echo ""

# ── Step 11: Install haystack-rag-skills in sandbox ─────────────
SKILL_NAME="haystack-rag-skills"
SKILL_SRC="$SCRIPT_DIR/haystack-rag-skills"
# New NemoClaw sandboxes use .openclaw/workspace/skills/; legacy builds used
# .openclaw-data/workspace/skills/. nemoclaw skill install picks the right path.
SKILL_DEST="/sandbox/.openclaw/workspace/skills/$SKILL_NAME"
SKILL_DEST_LEGACY="/sandbox/.openclaw-data/workspace/skills/$SKILL_NAME"

enable_haystack_skill_registry() {
  openshell sandbox exec -n "$SANDBOX_NAME" -- python3 - <<'PYEOF'
import json, os, sys
p = "/sandbox/.openclaw/openclaw.json"
if not os.path.exists(p):
    print("skip: openclaw.json not found", file=sys.stderr)
    sys.exit(0)
d = json.load(open(p))
changed = False

entry = d.setdefault("skills", {}).setdefault("entries", {}).setdefault("haystack-rag-skills", {})
if entry.get("enabled") is not True:
    entry["enabled"] = True
    changed = True

tools = d.setdefault("tools", {})
if tools.get("profile") != "coding":
    tools["profile"] = "coding"
    changed = True

if changed:
    json.dump(d, open(p, "w"), indent=2)
    print("updated")
else:
    print("already configured")
PYEOF
}

restart_sandbox_openclaw() {
  openshell sandbox exec -n "$SANDBOX_NAME" -- \
    bash -c "pkill -TERM -f '^openclaw\$' 2>/dev/null || pkill -TERM openclaw 2>/dev/null || true"
}

resolve_skill_dest() {
  if openshell sandbox exec -n "$SANDBOX_NAME" -- \
    test -f "$SKILL_DEST/SKILL.md" 2>/dev/null; then
    echo "$SKILL_DEST"
  elif openshell sandbox exec -n "$SANDBOX_NAME" -- \
    test -f "$SKILL_DEST_LEGACY/SKILL.md" 2>/dev/null; then
    echo "$SKILL_DEST_LEGACY"
  else
    echo "$SKILL_DEST"
  fi
}

info "Installing $SKILL_NAME in sandbox..."
if nemoclaw "$SANDBOX_NAME" skill install "$SKILL_SRC"; then
  ok "Skill registered via nemoclaw skill install"
else
  warn "nemoclaw skill install failed — falling back to openshell upload"
  openshell sandbox upload "$SANDBOX_NAME" \
    "$SKILL_SRC" \
    "$SKILL_DEST" \
    || openshell sandbox upload "$SANDBOX_NAME" \
      "$SKILL_SRC" \
      "$SKILL_DEST_LEGACY" \
      || fail "Skill upload failed on both $SKILL_DEST and $SKILL_DEST_LEGACY"
  ok "Skill uploaded (fallback path)"
fi

SKILL_DEST="$(resolve_skill_dest)"
ok "Skill path: $SKILL_DEST"

info "Enabling skill in OpenClaw registry..."
if enable_haystack_skill_registry 2>/dev/null | grep -qE 'updated|already configured'; then
  ok "haystack-rag-skills enabled in openclaw.json (tools.profile=coding)"
else
  warn "Could not update openclaw.json — add skills.entries.haystack-rag-skills.enabled=true manually"
fi

info "Restarting OpenClaw gateway inside sandbox (reload skills)..."
if restart_sandbox_openclaw 2>/dev/null; then
  sleep 2
  ok "OpenClaw gateway restart signaled"
else
  warn "Could not restart sandbox OpenClaw — disconnect and reconnect the TUI"
fi
echo ""

# ── Step 12: Bootstrap skill venv (requests only) ───────────────
# The skill is a thin HTTP client — no haystack packages needed in the sandbox.
# Only 'requests' is required to call the host-side RAG server.
info "Setting up skill Python venv (requests)..."
SKILL_VENV="$SKILL_DEST/venv"

openshell sandbox exec -n "$SANDBOX_NAME" -- \
  python3 -m venv "$SKILL_VENV" \
  || fail "Failed to create skill venv at $SKILL_VENV inside sandbox '$SANDBOX_NAME'."

openshell sandbox exec -n "$SANDBOX_NAME" -- \
  "$SKILL_VENV/bin/pip" install -q requests \
  || fail "pip install of requests failed inside the skill venv."

# Verify
VENV_CHECK=$(openshell sandbox exec -n "$SANDBOX_NAME" -- \
  "$SKILL_VENV/bin/python3" -c "import requests; print('ok')" 2>/dev/null || true)
[ "$VENV_CHECK" = "ok" ] \
  && ok "Skill venv ready ($SKILL_VENV)" \
  || fail "Skill venv verification failed — 'import requests' returned no output."

ok "Skill and inference model are configured — reconnect to activate them"
echo ""

# ── Step 13: Verify ─────────────────────────────────────────────
info "Verifying installation..."

RAG_UP=$(curl -s --max-time 3 "http://127.0.0.1:${RAG_PORT}/health" 2>/dev/null || true)
if echo "$RAG_UP" | python3 -c "import json,sys; d=json.load(sys.stdin); exit(0 if d.get('status')=='ok' else 1)" 2>/dev/null; then
  CHUNK_COUNT=$(echo "$RAG_UP" | python3 -c "import json,sys; print(json.load(sys.stdin).get('indexed_chunks', 0))")
  ok "RAG server responding: $CHUNK_COUNT chunks indexed"
else
  warn "RAG server not responding — check: cat $RAG_LOG_FILE"
fi

SKILL_CHECK=$(openshell sandbox exec -n "$SANDBOX_NAME" -- \
  sh -c "test -f $SKILL_DEST/SKILL.md && echo ok" 2>/dev/null || true)
[ "$SKILL_CHECK" = "ok" ] \
  && ok "Skill confirmed at $SKILL_DEST" \
  || warn "SKILL.md not found at $SKILL_DEST — try: nemoclaw $SANDBOX_NAME skill install $SKILL_SRC"

REQUESTS_CHECK=$(openshell sandbox exec -n "$SANDBOX_NAME" -- \
  "$SKILL_VENV/bin/python3" -c "import requests; print('ok')" 2>/dev/null || true)
[ "$REQUESTS_CHECK" = "ok" ] \
  && ok "requests reachable via skill venv" \
  || warn "Skill venv check failed — try re-running install.sh"

echo ""
echo -e "${GREEN}  ╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}  ║  Installation complete!                                  ║${NC}"
echo -e "${GREEN}  ╚══════════════════════════════════════════════════════════╝${NC}"
echo ""
echo "  Sandbox    : $SANDBOX_NAME"
echo "  Skill path : $SKILL_DEST"
echo "  RAG server : http://127.0.0.1:${RAG_PORT}/health  (PID $(cat $RAG_PID_FILE 2>/dev/null || echo '?'))"
echo "  Server logs: tail -f $RAG_LOG_FILE"
echo "  Data dir   : $SCRIPT_DIR/data/documents  ← copy files here before indexing"
if [ -n "${TOKEN:-}" ]; then
echo "  WebUI      : http://127.0.0.1:18789/#token=$TOKEN"
fi
echo ""
echo "  Brev tunnel (run locally if on a brev instance):"
echo "    brev port-forward <brev-instance-name> -p 18789:18789"
echo ""
echo "  Next steps:"
echo "    1. Copy documents to the host data dir:"
echo "       cp your-file.pdf $SCRIPT_DIR/data/documents/"
echo "    2. Connect:  nemoclaw $SANDBOX_NAME connect"
echo "    3. Index:    \"Index my documents\""
echo "    4. Query:    \"What does the document say about X?\""
echo "    5. List:     \"What documents are indexed?\""
echo ""
echo "  If the agent doesn't find the skill, disconnect and reconnect."
echo -e "  ${YELLOW}To restart server: kill \$(cat $RAG_PID_FILE) && bash $SCRIPT_DIR/install.sh $SANDBOX_NAME${NC}"
echo ""
