#!/usr/bin/env bash
# Fix n8n EnterpriseOrchestrator: credential + model + publish + verify.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
CONTAINER="${N8N_CONTAINER:-n8n}"

# shellcheck source=/dev/null
source "$ROOT_DIR/.env"

: "${INFERENCE_API_KEY:?INFERENCE_API_KEY must be set in .env}"
NVIDIA_BASE_URL="${INFERENCE_BASE_URL:-https://integrate.api.nvidia.com/v1}"
MODEL="${OPENCLAW_MODEL:-nvidia/llama-3.3-nemotron-super-49b-v1.5}"

echo "▸ Creating NVIDIAInferenceAPI credential..."
docker cp "$SCRIPT_DIR/create_nvidia_credential.js" "$CONTAINER:/tmp/create_nvidia_credential.js"
docker exec \
  -e NVIDIA_API_KEY="$INFERENCE_API_KEY" \
  -e NVIDIA_BASE_URL="$NVIDIA_BASE_URL" \
  "$CONTAINER" node /tmp/create_nvidia_credential.js

docker exec "$CONTAINER" n8n import:credentials --input=/home/node/.n8n/nvidia-credential.json

echo "▸ Patching workflow model to $MODEL..."
docker exec "$CONTAINER" n8n export:workflow --id=TzLcGZKuV0TZxXHs --output=/home/node/.n8n/orch-patch.json
docker cp "$CONTAINER:/home/node/.n8n/orch-patch.json" /tmp/orch-patch.json
python3 - "$MODEL" /tmp/orch-patch.json /tmp/orch-patched.json <<'PY'
import json, sys
model, src, dst = sys.argv[1], sys.argv[2], sys.argv[3]
data = json.load(open(src))
wf = data[0] if isinstance(data, list) else data
for node in wf.get('nodes', []):
    if node.get('type') == '@n8n/n8n-nodes-langchain.lmChatOpenAi':
        node['parameters']['model'] = {
            '__rl': True,
            'value': model,
            'mode': 'list',
            'cachedResultName': model,
        }
        node.setdefault('credentials', {})['openAiApi'] = {
            'id': 'rO9tDpks1CwG9AN7',
            'name': 'NVIDIAInferenceAPI',
        }
json.dump([wf] if isinstance(data, list) else wf, open(dst, 'w'), indent=2)
print('  patched OpenAI Chat Model node')
PY
docker cp /tmp/orch-patched.json "$CONTAINER:/home/node/.n8n/orch-patched.json"
docker exec "$CONTAINER" n8n import:workflow --input=/home/node/.n8n/orch-patched.json

echo "▸ Publishing all 4 workflows..."
for id in TzLcGZKuV0TZxXHs 8eFCKIE4qlfhMna0 mAPFaEvgygizLfaY XPYjIUowrNmN5aUj; do
  docker exec "$CONTAINER" n8n publish:workflow --id="$id"
done

echo "▸ Restarting n8n..."
docker restart "$CONTAINER" >/dev/null

echo "▸ Waiting for webhook (up to 60s)..."
code="000"
for _ in $(seq 1 12); do
  sleep 5
  code=$(curl -s -o /dev/null -w "%{http_code}" -X POST http://localhost:5678/webhook/agent-hub \
    -H "Content-Type: application/json" \
    -d '{"chatInput":"ping"}' 2>/dev/null || echo "000")
  [ "$code" != "404" ] && [ "$code" != "000" ] && break
done
echo "▸ Verifying webhook (LLM call may take 1–3 min)..."
code=$(curl -s -o /tmp/n8n-webhook-out.json -w "%{http_code}" --max-time 300 -X POST http://localhost:5678/webhook/agent-hub \
  -H "Content-Type: application/json" \
  -d '{"chatInput":"ping"}')
echo "HTTP $code"
head -c 500 /tmp/n8n-webhook-out.json; echo
if [ "$code" != "200" ]; then
  echo "✗ Webhook check failed — see docker logs n8n --since 2m"
  exit 1
fi
echo "✓ Webhook OK"
