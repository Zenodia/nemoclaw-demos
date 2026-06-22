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

# Onboard model: used only for nemoclaw onboard's own verification smoke-test.
# Large models (550b+) time out during that sync check — use a fast 49b here.
# After onboard, install.sh patches the sandbox openclaw.json to the real INFERENCE_MODEL.
NEMOCLAW_ONBOARD_MODEL="${NEMOCLAW_ONBOARD_MODEL:-nvidia/llama-3.3-nemotron-super-49b-v1.5}"

ok "NVIDIA_API_KEY      : found"
ok "INFERENCE_MODEL     : $INFERENCE_MODEL  (runtime model — patched into sandbox after onboard)"
ok "ONBOARD_MODEL       : $NEMOCLAW_ONBOARD_MODEL  (used only for nemoclaw onboard verification)"
ok "OPENCLAW_MODEL      : $OPENCLAW_MODEL"
echo ""

# ── Step 2b: Resolve the host IP the sandbox will reach ──────────
# Per the NemoClaw guidance, the sandbox must reach the host service via the
# host's REAL, non-loopback IP — NOT host.openshell.internal/host.docker.internal
# (not a reliable host-service path) and NOT 127.0.0.1 (loopback inside the
# sandbox). The server binds 0.0.0.0, so any host IP works; the OpenShell
# gateway (on the host) proxies sandbox egress to this address after a policy
# match. Override by exporting HOST_IP before running install.sh.
info "Resolving host IP for sandbox egress..."
# The OpenShell sandbox container routes outbound traffic through the sandbox
# network bridge (172.18.0.0/16 by default, or 172.17.0.0/16 for docker0).
# The sandbox proxy (openshell-sandbox) forwards allowed requests by making
# TCP connections from WITHIN the sandbox network namespace — so the host IP
# must be the bridge gateway reachable from that namespace, NOT the host's
# primary external IP (which is only reachable in the host default namespace).
#
# Priority order:
#  1. HOST_IP env var (user override)
#  2. OpenShell sandbox bridge gateway (172.18.0.1) — most common
#  3. Docker0 bridge gateway (172.17.0.1) — fallback
#  4. Primary outbound IP via ip route — last resort
_resolve_host_ip() {
  local ip
  # OpenShell sandbox bridge (standard NemoClaw default)
  ip=$(python3 -c "import socket; s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM); s.bind(('172.18.0.1',0)); print('172.18.0.1'); s.close()" 2>/dev/null || true)
  # Docker0 bridge
  [ -z "$ip" ] && ip=$(python3 -c "import socket; s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM); s.bind(('172.17.0.1',0)); print('172.17.0.1'); s.close()" 2>/dev/null || true)
  # Primary outbound source IP (last resort — may not be reachable from sandbox namespace)
  [ -z "$ip" ] && ip=$(ip route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="src"){print $(i+1); exit}}')
  [ -z "$ip" ] && ip=$(hostname -I 2>/dev/null | awk '{print $1}')
  echo "$ip"
}
HOST_IP="${HOST_IP:-$(_resolve_host_ip)}"
[ -z "${HOST_IP:-}" ] && \
  fail "Could not resolve the sandbox-reachable host IP. Export HOST_IP=<bridge-ip> and re-run."
RAG_SERVER_URL="http://${HOST_IP}:${RAG_PORT}"
ok "HOST_IP             : $HOST_IP  (sandbox reaches the RAG server at $RAG_SERVER_URL)"
echo ""

# ── Step 3: Install openclaw (if not already present) ────────────
info "Checking openclaw installation..."

# Host openclaw must match the sandbox Dockerfile pin (not npm "latest").
_parse_dockerfile_openclaw_version() {
  local dockerfile="$SCRIPT_DIR/Dockerfile"
  [ -f "$dockerfile" ] || return 1
  grep -m 1 '^ARG OPENCLAW_VERSION=' "$dockerfile" | sed 's/^ARG OPENCLAW_VERSION=//'
}
OPENCLAW_VERSION="$(_parse_dockerfile_openclaw_version || true)"
OPENCLAW_VERSION="${OPENCLAW_VERSION:-2026.5.22}"

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
    -maxdepth 6 -name "openclaw" -type f 2>/dev/null | head -1 || true)
  if [ -n "$found" ]; then
    export PATH="$(dirname "$found"):$PATH"
    return 0
  fi
  return 1
}

_get_openclaw_version() {
  openclaw --version 2>/dev/null | awk '{print $2}' || true
}

_install_openclaw_pinned() {
  curl -fsSL --proto '=https' --tlsv1.2 https://openclaw.ai/install.sh | \
    bash -s -- --no-onboard --version "$OPENCLAW_VERSION"
}

_needs_openclaw_install() {
  _ensure_openclaw_path || return 0
  local cur_ver
  cur_ver="$(_get_openclaw_version)"
  [ -z "$cur_ver" ] && return 0
  [ "$cur_ver" = "$OPENCLAW_VERSION" ] && return 1
  return 0
}

if _needs_openclaw_install; then
  if _ensure_openclaw_path; then
    info "openclaw $(_get_openclaw_version) != sandbox pin $OPENCLAW_VERSION — reinstalling..."
  else
    info "openclaw not found — installing $OPENCLAW_VERSION (--no-onboard)..."
  fi
  _install_openclaw_pinned
  _ensure_openclaw_path || \
    fail "openclaw install failed. Run 'openclaw onboard' manually after adding its bin dir to PATH."
  ok "openclaw installed ($OPENCLAW_VERSION)"
else
  ok "openclaw already installed: $(_get_openclaw_version) (matches Dockerfile pin)"
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

# The skill ships a sample.txt about Haystack; the server needs to be able to
# reach it at index time via the skill's POST /index {"data_dir": ...} call.
# The skill's data/ dir is inside the sandbox (read-only from the host), so we
# keep the authoritative copy inside the skill source tree and the server reads
# it directly when the skill sends its path over the REST API.
# No copy needed — the server accepts any absolute path as data_dir.
ok "Sample document is at $SCRIPT_DIR/haystack-rag-skills/data/sample.txt"
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
  source "$SCRIPT_DIR/.venv/bin/activate"
  export NVIDIA_API_KEY="$NVIDIA_API_KEY"
  while true; do
    kill $(lsof -t -i:"$RAG_PORT") 2>/dev/null || true
    python "$SCRIPT_DIR/haystack_rag_server.py" \
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

# Open the host firewall so the OpenShell sandbox container can reach the RAG server.
# The openshell-sandbox container (172.18.0.0/16) makes outbound TCP connections
# from within the Docker bridge network. By default the host's INPUT chain drops
# traffic from Docker containers to host-side ports. We add explicit ACCEPT rules
# for the two standard Docker bridge networks.
# Using 'docker run --privileged' avoids needing the ubuntu user to have
# passwordless sudo while still using root for iptables.
_add_iptables_rule() {
  local net="$1"
  docker run --rm --privileged --network host python:3.12-alpine sh -c \
    "apk add --quiet iptables 2>/dev/null; \
     iptables -C INPUT -s ${net} -p tcp --dport ${RAG_PORT} -j ACCEPT 2>/dev/null || \
     iptables -I INPUT -s ${net} -p tcp --dport ${RAG_PORT} -j ACCEPT" \
    2>/dev/null && return 0
  return 1
}
if command -v docker >/dev/null 2>&1; then
  _add_iptables_rule "172.18.0.0/16" \
    && ok "iptables: sandbox bridge (172.18.0.0/16) → port $RAG_PORT ACCEPT" \
    || warn "iptables rule for 172.18.0.0/16 failed — may need: sudo iptables -I INPUT -s 172.18.0.0/16 -p tcp --dport $RAG_PORT -j ACCEPT"
  _add_iptables_rule "172.17.0.0/16" \
    && ok "iptables: docker0 bridge (172.17.0.0/16) → port $RAG_PORT ACCEPT" \
    || warn "iptables rule for 172.17.0.0/16 failed — may need: sudo iptables -I INPUT -s 172.17.0.0/16 -p tcp --dport $RAG_PORT -j ACCEPT"
else
  warn "docker not found — add iptables rules manually if sandbox cannot reach host:"
  warn "  sudo iptables -I INPUT -s 172.18.0.0/16 -p tcp --dport $RAG_PORT -j ACCEPT"
fi

# Confirm the server is reachable on the host's real IP, not just loopback.
# This is the address the sandbox egress policy will target.
if curl -s --max-time 3 "http://${HOST_IP}:${RAG_PORT}/health" >/dev/null 2>&1; then
  ok "RAG server reachable at host IP: ${RAG_SERVER_URL}/health"
else
  warn "Server answers on 127.0.0.1 but NOT on ${HOST_IP}:${RAG_PORT}."
  warn "The sandbox reaches the host via $HOST_IP — confirm the server binds 0.0.0.0"
  warn "and that a host firewall isn't blocking port $RAG_PORT."
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
  export NEMOCLAW_MODEL="${NEMOCLAW_ONBOARD_MODEL}"   # fast model for onboard verification only
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
# Large models (550b+) may time out during the sync endpoint verification.
# Try with verification first; if that times out, retry with --no-verify.
# The model is still usable — the verification just does a blocking smoke-test call.
if openshell inference set \
     --provider "$INFERENCE_PROVIDER_NAME" \
     --model "$INFERENCE_MODEL" 2>/dev/null; then
  ok "Inference set: $INFERENCE_PROVIDER_NAME / $INFERENCE_MODEL"
elif openshell inference set \
     --provider "$INFERENCE_PROVIDER_NAME" \
     --model "$INFERENCE_MODEL" \
     --no-verify 2>/dev/null; then
  ok "Inference set (skipped verification — model may be slow to cold-start): $INFERENCE_PROVIDER_NAME / $INFERENCE_MODEL"
  warn "If queries fail, confirm the model is available: curl https://integrate.api.nvidia.com/v1/models | grep $INFERENCE_MODEL"
else
  fail "Could not set inference model '$INFERENCE_MODEL'. Check INFERENCE_* values in .env."
fi
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
# Render the egress preset template, substituting the host's real IP and port
# for the __HOST_IP__ / __RAG_PORT__ placeholders, then apply it with the
# documented `nemoclaw <sandbox> policy-add --from-file` command. This is an
# additive preset (egress only, no filesystem rules) so it won't clobber the
# filesystem presets added by nemoclaw onboard.
EGRESS_TEMPLATE="$SCRIPT_DIR/policy/haystack-rag-egress.yaml"
EGRESS_POLICY="$(mktemp /tmp/haystack-rag-egress.XXXXXX.yaml)"
sed -e "s|__HOST_IP__|${HOST_IP}|g" -e "s|__RAG_PORT__|${RAG_PORT}|g" \
  "$EGRESS_TEMPLATE" > "$EGRESS_POLICY"
info "Applying haystack_rag_host egress policy (host $HOST_IP, port $RAG_PORT)..."
POLICY_OK=false

if nemoclaw "$SANDBOX_NAME" policy-add --from-file "$EGRESS_POLICY" --yes 2>/dev/null; then
  ok "Policy applied via nemoclaw policy-add --from-file (egress to $HOST_IP:$RAG_PORT)"
  POLICY_OK=true
elif openshell policy set "$SANDBOX_NAME" \
     --policy "$EGRESS_POLICY" \
     --wait 2>/dev/null; then
  ok "Policy applied via openshell policy set (egress to $HOST_IP:$RAG_PORT)"
  POLICY_OK=true
else
  # Last resort: render + apply the full policy file (may fail on live sandboxes
  # that already carry filesystem rules).
  FULL_POLICY="$(mktemp /tmp/haystack-rag-sandbox.XXXXXX.yaml)"
  sed -e "s|__HOST_IP__|${HOST_IP}|g" -e "s|__RAG_PORT__|${RAG_PORT}|g" \
    "$SCRIPT_DIR/policy/sandbox_policy.yaml" > "$FULL_POLICY"
  openshell policy set "$SANDBOX_NAME" \
    --policy "$FULL_POLICY" \
    --wait 2>/dev/null \
    && ok "Policy applied via full sandbox_policy.yaml" \
    && POLICY_OK=true \
    || true
  rm -f "$FULL_POLICY"
fi

if [ "$POLICY_OK" = false ]; then
  warn "Could not apply egress policy — egress to $HOST_IP:$RAG_PORT may be blocked."
  warn "To fix manually, run:"
  warn "  nemoclaw $SANDBOX_NAME policy-add --from-file $EGRESS_POLICY"
else
  rm -f "$EGRESS_POLICY"
fi
echo ""

# ── Step 11: Install haystack-rag-skills in sandbox ─────────────
SKILL_NAME="haystack-rag-skills"
SKILL_SRC="$SCRIPT_DIR/haystack-rag-skills"
# New NemoClaw sandboxes use .openclaw/workspace/skills/; legacy builds used
# .openclaw-data/workspace/skills/. nemoclaw skill install picks the right path.
SKILL_DEST="/sandbox/.openclaw/workspace/skills/$SKILL_NAME"
SKILL_DEST_LEGACY="/sandbox/.openclaw-data/workspace/skills/$SKILL_NAME"
# openshell sandbox upload places SRC *inside* DEST as a subdirectory, so the
# fallback must target the parent skills/ dir — not the named skill subdir.
SKILL_DEST_PARENT="/sandbox/.openclaw/workspace/skills"
SKILL_DEST_LEGACY_PARENT="/sandbox/.openclaw-data/workspace/skills"

enable_haystack_skill_registry() {
  openshell sandbox exec -n "$SANDBOX_NAME" -- python3 - <<'PYEOF'
import json, os, sys

# Try both possible openclaw.json locations (root exec vs connected user)
CANDIDATES = [
    "/sandbox/.openclaw/openclaw.json",
    "/sandbox/.openclaw-data/openclaw.json",
    os.path.expanduser("~/.openclaw/openclaw.json"),
]
p = None
for c in CANDIDATES:
    if os.path.exists(c):
        p = c
        break

if p is None:
    # openclaw.json not yet created — write a minimal skeleton so the skill is
    # enabled when openclaw first starts and creates its own config.
    # Prefer the canonical path.
    p = "/sandbox/.openclaw/openclaw.json"
    os.makedirs(os.path.dirname(p), exist_ok=True)
    d = {}
    print(f"created skeleton at {p}", file=sys.stderr)
else:
    try:
        d = json.load(open(p))
    except Exception as e:
        print(f"warning: could not parse {p}: {e} — resetting", file=sys.stderr)
        d = {}

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
    print(f"updated ({p})")
else:
    print(f"already configured ({p})")
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

info "Cleaning up stale skill installation in sandbox..."
# Remove any previous install so we don't accumulate wrong content across runs.
openshell sandbox exec -n "$SANDBOX_NAME" -- \
  sh -c "rm -rf '$SKILL_DEST' '$SKILL_DEST_LEGACY'" 2>/dev/null || true
ok "Stale skill directory removed"

info "Installing $SKILL_NAME in sandbox..."
# nemoclaw skill install traverses up to the git root and uploads the entire
# repo instead of just the skill directory — skip it and upload directly.
# openshell upload places the source directory *inside* the destination, so
# uploading $SKILL_SRC to $SKILL_DEST_PARENT lands it as skills/haystack-rag-skills/.
openshell sandbox upload "$SANDBOX_NAME" \
  "$SKILL_SRC" \
  "$SKILL_DEST_PARENT" \
  || openshell sandbox upload "$SANDBOX_NAME" \
    "$SKILL_SRC" \
    "$SKILL_DEST_LEGACY_PARENT" \
    || fail "Skill upload failed on both $SKILL_DEST_PARENT and $SKILL_DEST_LEGACY_PARENT"
ok "Skill files uploaded to sandbox"

SKILL_DEST="$(resolve_skill_dest)"
ok "Skill path: $SKILL_DEST"

# Tell the in-sandbox client which host IP/URL to call. haystack_client.py reads
# this file (after --server-url flag and RAG_SERVER_URL env) so the skill talks
# to the host's real IP instead of an unreliable host.openshell.internal name.
if openshell sandbox exec -n "$SANDBOX_NAME" -- \
     sh -c "printf '%s\n' '$RAG_SERVER_URL' > '$SKILL_DEST/server_url.txt'" 2>/dev/null; then
  ok "Wrote server URL to sandbox: $SKILL_DEST/server_url.txt → $RAG_SERVER_URL"
else
  warn "Could not write server_url.txt — set RAG_SERVER_URL=$RAG_SERVER_URL in the sandbox,"
  warn "or pass --server-url $RAG_SERVER_URL to haystack_client.py."
fi

# Boot openclaw once so it initializes openclaw.json, then patch it.
# openclaw writes its default config on first start — we must let it do that
# before we add the skill entry, otherwise our skeleton gets overwritten.
info "Booting OpenClaw in sandbox to initialise openclaw.json..."
openshell sandbox exec -n "$SANDBOX_NAME" -- \
  bash -c "openclaw gateway run --once 2>/dev/null & sleep 4; kill %1 2>/dev/null; true" \
  2>/dev/null || true

info "Enabling skill in OpenClaw registry..."
ENABLE_ATTEMPTS=0
ENABLE_OK=false
while [ "$ENABLE_ATTEMPTS" -lt 5 ]; do
  RESULT=$(enable_haystack_skill_registry 2>/dev/null || true)
  if echo "$RESULT" | grep -qE 'updated|already configured'; then
    ok "haystack-rag-skills enabled in openclaw.json (tools.profile=coding)"
    ENABLE_OK=true
    break
  fi
  ENABLE_ATTEMPTS=$((ENABLE_ATTEMPTS + 1))
  warn "Enable attempt $ENABLE_ATTEMPTS/5 — openclaw.json not ready yet, retrying in 2s..."
  sleep 2
done
if [ "$ENABLE_OK" = false ]; then
  warn "Could not update openclaw.json after 5 attempts."
  warn "Run manually on the host after connecting to the sandbox:"
  warn "  openshell sandbox exec -n $SANDBOX_NAME -- python3 -c \""
  warn "    import json; p='/sandbox/.openclaw/openclaw.json';"
  warn "    d=json.load(open(p)); d.setdefault('skills',{}).setdefault('entries',{})['haystack-rag-skills']={'enabled':True};"
  warn "    json.dump(d,open(p,'w'))\""
fi

info "Uploading workspace configuration files to sandbox..."
# Upload demo-specific AGENTS.md, TOOLS.md, SOUL.md, IDENTITY.md, USER.md,
# and HEARTBEAT.md to the sandbox workspace. These replace the generic OpenClaw
# defaults with files that:
#   - Explicitly tell the agent it has bash/shell execution (TOOLS.md, AGENTS.md)
#   - Document the haystack-rag-skills location and commands (TOOLS.md)
#   - Give the agent purpose-specific identity and soul (IDENTITY.md, SOUL.md)
#   - Add a periodic health check + skill-routing reminder (HEARTBEAT.md)
#
# We use base64 encode+decode because openshell sandbox exec rejects multi-line
# command arguments, and openshell sandbox upload cannot overwrite an existing
# file at the same path.

WORKSPACE_SRC="$SCRIPT_DIR/workspace"
WORKSPACE_DEST="/sandbox/.openclaw/workspace"
WORKSPACE_DEST_LEGACY="/sandbox/.openclaw-data/workspace"

_upload_b64_file() {
  local src="$1" dest="$2"
  local b64
  b64=$(base64 -w0 "$src")
  openshell sandbox exec -n "$SANDBOX_NAME" -- \
    bash -c "mkdir -p \$(dirname '$dest') && echo '${b64}' | base64 -d > '$dest' && echo ok" \
    2>/dev/null
}

_upload_workspace_file() {
  local fname="$1"
  local src="$WORKSPACE_SRC/$fname"
  [ -f "$src" ] || { warn "workspace/$fname not found — skipping"; return; }
  local result
  result=$(_upload_b64_file "$src" "$WORKSPACE_DEST/$fname")
  if [ "$result" = "ok" ]; then
    ok "workspace/$fname → $WORKSPACE_DEST/$fname"
  else
    result=$(_upload_b64_file "$src" "$WORKSPACE_DEST_LEGACY/$fname")
    if [ "$result" = "ok" ]; then
      ok "workspace/$fname → $WORKSPACE_DEST_LEGACY/$fname"
    else
      warn "Could not upload workspace/$fname — upload manually:"
      warn "  B64=\$(base64 -w0 $src)"
      warn "  openshell sandbox exec -n $SANDBOX_NAME -- bash -c \"echo '\$B64' | base64 -d > $WORKSPACE_DEST/$fname\""
    fi
  fi
}

# Upload HEARTBEAT.md from demo root (not workspace/ subdir)
HEARTBEAT_SRC="$SCRIPT_DIR/HEARTBEAT.md"
if [ -f "$HEARTBEAT_SRC" ]; then
  result=$(_upload_b64_file "$HEARTBEAT_SRC" "$WORKSPACE_DEST/HEARTBEAT.md")
  if [ "$result" = "ok" ]; then
    ok "HEARTBEAT.md → $WORKSPACE_DEST/HEARTBEAT.md"
  else
    result=$(_upload_b64_file "$HEARTBEAT_SRC" "$WORKSPACE_DEST_LEGACY/HEARTBEAT.md")
    [ "$result" = "ok" ] \
      && ok "HEARTBEAT.md → $WORKSPACE_DEST_LEGACY/HEARTBEAT.md" \
      || warn "HEARTBEAT.md upload failed — see troubleshooting guide"
  fi
else
  warn "HEARTBEAT.md not found at $HEARTBEAT_SRC — skipping"
fi

# Upload all workspace configuration files
for _wf in AGENTS.md TOOLS.md SOUL.md IDENTITY.md USER.md; do
  _upload_workspace_file "$_wf"
done

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

# pip lives at bin/pip regardless of python version; use it directly
openshell sandbox exec -n "$SANDBOX_NAME" -- \
  "$SKILL_VENV/bin/pip" install -q requests \
  || fail "pip install of requests failed inside the skill venv."

# Detect whichever python3.x binary the venv created (3.11, 3.12, etc.)
VENV_PY=$(openshell sandbox exec -n "$SANDBOX_NAME" -- \
  sh -c "ls $SKILL_VENV/bin/python3* 2>/dev/null | head -1" || true)
[ -z "$VENV_PY" ] && VENV_PY="$SKILL_VENV/bin/python3"

# Verify
VENV_CHECK=$(openshell sandbox exec -n "$SANDBOX_NAME" -- \
  "$VENV_PY" -c "import requests; print('ok')" 2>/dev/null || true)
[ "$VENV_CHECK" = "ok" ] \
  && ok "Skill venv ready ($SKILL_VENV, python: $VENV_PY)" \
  || fail "Skill venv verification failed — 'import requests' returned no output (tried $VENV_PY)."

ok "Skill venv configured"
echo ""

# ── Step 12b: Patch sandbox openclaw.json with runtime INFERENCE_MODEL ──────
# nemoclaw onboard bakes the ONBOARD_MODEL into the sandbox image. Patch it
# here to the real INFERENCE_MODEL so the agent inside uses the right model.
if [ "$NEMOCLAW_ONBOARD_MODEL" != "$INFERENCE_MODEL" ]; then
  info "Patching sandbox model: $NEMOCLAW_ONBOARD_MODEL → $INFERENCE_MODEL ..."
  openshell sandbox exec -n "$SANDBOX_NAME" -- python3 - <<PYEOF
import json, os, sys

candidates = [
    "/sandbox/.openclaw/openclaw.json",
    "/sandbox/.openclaw-data/openclaw.json",
]
p = next((c for c in candidates if os.path.exists(c)), None)
if not p:
    print("WARNING: openclaw.json not found, skipping model patch", file=sys.stderr)
    sys.exit(0)

d = json.load(open(p))
model_ref = "inference/$INFERENCE_MODEL"

# Primary model path used by OpenClaw/NemoClaw
agents = d.setdefault("agents", {})
defaults = agents.setdefault("defaults", {})
model_cfg = defaults.setdefault("model", {})
old = model_cfg.get("primary", "(not set)")
model_cfg["primary"] = model_ref

# Also update top-level model reference if present
if "model" in d and isinstance(d["model"], dict):
    d["model"]["primary"] = model_ref

json.dump(d, open(p, "w"), indent=2)
print(f"Patched {p}: {old} -> {model_ref}")
PYEOF
  if [ $? -eq 0 ]; then
    ok "Sandbox model patched to $INFERENCE_MODEL"
  else
    warn "Model patch may not have applied — agent may still use $NEMOCLAW_ONBOARD_MODEL"
  fi
else
  ok "Onboard model matches runtime model ($INFERENCE_MODEL) — no patch needed"
fi

info "Restarting OpenClaw in sandbox to pick up model change..."
restart_sandbox_openclaw 2>/dev/null && sleep 2 || true
echo ""

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
echo "  RAG server : ${RAG_SERVER_URL}/health  (host IP — what the sandbox calls)"
echo "             : http://127.0.0.1:${RAG_PORT}/health  (host-local, PID $(cat $RAG_PID_FILE 2>/dev/null || echo '?'))"
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
