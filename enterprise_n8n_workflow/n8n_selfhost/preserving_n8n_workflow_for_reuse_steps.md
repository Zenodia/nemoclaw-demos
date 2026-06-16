# Preserving & Redeploying the Enterprise n8n Workflow

This folder packages a self-hosted n8n **EnterpriseOrchestrator** workflow (an AI
agent that runs `policy_guard → task_router → cost_gate → execution plan`) plus 3
sub-workflows, so it can be saved and redeployed elsewhere — **without** shipping
any API keys.

**Which part do you need?**
- **Redeploying a copy someone sent you?** → jump to
  [Re-deployment Steps](#re-deployment-steps---on-the-new-machine) and
  [Using your own API keys](#using-your-own-api-keys). After import, run
  `bash fix_n8n_setup.sh` with your `nvapi-…` key in `../.env`.
- **You own the running instance and want to re-save it?** → Option A below.

---

## Option A: Export via n8n CLI (owner — saving your instance)

> **Shortcut:** `bash save_created_workflow_from_inside_n8n_container.sh` runs the
> save steps from the host in one go — exports workflows + a **sanitized**
> credentials template (no secrets), safe to commit. Add `--with-secrets` to also
> write your real encrypted backup into `./private/` (gitignored).

> ### 🔐 Secrets policy — use YOUR OWN keys
>
> The committed `credentials-export.json` is a **sanitized template**: credential
> names / types / ids only, with the encrypted `data` blanked. `encryption-key.txt`
> is a **placeholder**. No real API keys live in this folder.
>
> n8n credential exports are AES-encrypted, but anyone holding the matching
> `encryption-key` can decrypt them — so an encrypted export **plus** the key is a
> full key leak. Never commit both. See **["Using your own API keys"](#using-your-own-api-keys)**
> below for how a new user plugs in their own key at deploy time.

Run these inside your Docker container:

```bash
# Enter the container
docker exec -it n8n sh

# Export ALL workflows (including sub-workflows) as one JSON
n8n export:workflow --all --output=/home/node/.n8n/workflows-export.json

# Export credentials (AES-encrypted — contains real secrets, NOT safe to commit)
n8n export:credentials --all --output=/home/node/.n8n/credentials-export.json

exit
```

Then copy out of the container:
```bash
docker cp n8n:/home/node/.n8n/workflows-export.json ./workflows-export.json
# ⚠ The raw credentials export holds your real (encrypted) keys. Keep it private
#   (e.g. ./private/, gitignored) — or just use the sanitized template the save
#   script produces. The encryption key below is ONLY needed to decrypt a raw
#   export; keep it private too, never commit it.
docker exec n8n cat /home/node/.n8n/config \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['encryptionKey'])"
```

==================================================================================

## Using your own API keys

Every new user brings their **own** NVIDIA API key (`nvapi-…`). This repo ships
**no** real keys — only a blank `credentials-export.json` template.

### Two places your key is used (they are separate!)

| Where | What it powers | How you set it |
|---|---|---|
| **`.env` → `INFERENCE_API_KEY`** | The OpenClaw agent inside the NemoClaw sandbox (`install.sh` / `nemoclaw onboard`) | Edit `.env` in the repo root |
| **n8n → `NVIDIAInferenceAPI` credential** | The **EnterpriseOrchestrator** LLM node (the workflow that runs when you POST `/webhook/agent-hub`) | n8n UI **or** `fix_n8n_setup.sh` (below) |

> ⚠️ **`INFERENCE_API_KEY` in `.env` is NOT wired into n8n automatically.**
> After import, n8n has **zero** credentials — the workflow references credential
> ID `rO9tDpks1CwG9AN7` which does not exist on your instance until you create it.
> Without it you get `{"message":"Error in workflow"}` (HTTP 500).

You can use the **same** `nvapi-…` value in both places; they are just configured
independently.

### Fastest — automated (`fix_n8n_setup.sh`)

After importing workflows (step 3 below), run from the repo root:

```bash
# Reads INFERENCE_API_KEY + INFERENCE_BASE_URL from ../.env
# Creates NVIDIAInferenceAPI credential, sets model, publishes all 4 workflows, restarts, verifies
bash fix_n8n_setup.sh
```

This script:
1. Creates the **`NVIDIAInferenceAPI`** credential (`openAiApi`) with your `nvapi-…` key
2. Sets the orchestrator model to `OPENCLAW_MODEL` from `.env` (default:
   `nvidia/llama-3.3-nemotron-super-49b-v1.5`)
3. **Publishes** all 4 workflows and restarts n8n
4. Waits for the webhook and runs a smoke test (may take **1–3 min** — the agent
   runs the full guardrail chain)

### Manual — n8n UI

1. Import the workflows (next section), then open **EnterpriseOrchestrator**.
2. Click the **OpenAI Chat Model** node → **Credential → Create New**:
   - **API Key:** your own `nvapi-…` (or any OpenAI-compatible key)
   - **Base URL:** the endpoint that issues your key, e.g.
     `https://integrate.api.nvidia.com/v1`
   - (You can name it `NVIDIAInferenceAPI` to match, but the name is cosmetic.)
3. **Set the model** on that same node — use one your endpoint actually serves, e.g.
   `nvidia/llama-3.3-nemotron-super-49b-v1.5` (the committed export already ships
   this model; older copies may still have `aws/anthropic/bedrock-claude-sonnet-4-6`
   which will **not** work with an NVIDIA key).
4. **Publish** the workflow (n8n 2.22+: **Save** alone updates a draft — click
   **Publish** so production webhooks pick up your changes).

> ⚠️ **Bind by ID, not name.** The imported node references credential ID
> `rO9tDpks1CwG9AN7`. A credential you create elsewhere gets a *new* ID and won't
> auto-link — always create/pick the credential **from the node** (step 2) so n8n
> rebinds it. If the node shows "credential not set" after import, that's why.

**Or via env var (no key stored in the credential):** start n8n with your key in
the environment, then put the expression `={{ $env.NVIDIA_API_KEY }}` in the
credential's **API Key** field:
```bash
docker run -d --name n8n -p 5678:5678 -v n8n_data:/home/node/.n8n \
  -e NVIDIA_API_KEY="$NVIDIA_API_KEY" \
  docker.n8n.io/n8nio/n8n
```
> `$env` access in nodes/credentials is **on by default**; it only fails if the
> instance sets `N8N_BLOCK_ENV_ACCESS_IN_NODE=true`. (There is no
> `N8N_EXPRESSION_EVALUATION` flag.)

> The other two template entries (`Header Auth account`, `NVIDIA_API_TOKEN`) are
> leftovers not referenced by the current workflows — create them only if you add
> nodes that need them.

==================================================================================
## Re-deployment Steps - On the new machine

**1. Start n8n**
```bash
docker volume create n8n_data

docker run -d --name n8n \
  -p 5678:5678 \
  -v n8n_data:/home/node/.n8n \
  docker.n8n.io/n8nio/n8n
```

> Using the sanitized template + your own keys (recommended): a fresh instance
> generates its own encryption key — nothing to pass.
> Only if you are restoring a **private real** credentials backup
> (`./private/credentials-export.SECRET.json`) do you need the matching key:
> add `-e N8N_ENCRYPTION_KEY="$(cat ./private/encryption-key.SECRET.txt)"`.

**2. Get the export files onto the machine**

If you received `n8n_selfhost.tar.gz`, just `tar xzf n8n_selfhost.tar.gz` — the
files are already in the folder. Only if n8n runs on a *different* host:
```bash
scp workflows-export.json user@newmachine:~/
```
(You do **not** need `credentials-export.json` — it's a blank template; you'll
create your own credential below.)

**3. Import the workflows** (no secrets inside)
```bash
docker cp ~/workflows-export.json n8n:/home/node/.n8n/
docker exec n8n n8n import:workflow --input=/home/node/.n8n/workflows-export.json
docker exec n8n n8n list:workflow      # should list all 4
```

**4. Set up YOUR credential + model** — see
[Using your own API keys](#using-your-own-api-keys).

**Recommended (covers steps 4–6 in one shot):** populate `../.env` with your
`nvapi-…` key, then:

```bash
bash fix_n8n_setup.sh    # credential + model + publish + restart + verify
```

Skip to the end if this succeeds. **Or** continue manually below.

**Manual UI:** **EnterpriseOrchestrator** → **OpenAI Chat Model** → create
credential (your `nvapi-…` + Base URL) → set model → **Publish**.

> Do **not** import the sanitized `credentials-export.json` (its `data` is blank).
> *(Only if you kept a `--with-secrets` private backup AND started n8n with the
> matching `N8N_ENCRYPTION_KEY`:*
> `docker exec n8n n8n import:credentials --input=/home/node/.n8n/creds.json`*.)*

**5. Publish ALL 4 workflows, THEN restart** — skip if you ran `fix_n8n_setup.sh`.
`import:workflow` deactivates everything. On n8n 2.22+ use **`publish:workflow`**
(not the deprecated `update:workflow --active=true`). A webhook is **not** reachable
until its workflow is published and active (you'd get `Cannot POST /webhook/agent-hub`).

> ⚠️ The 3 sub-workflows must be published too — n8n refuses to run an inactive
> workflow invoked as a tool (`Workflow is not active and cannot be executed`),
> which breaks the orchestrator's guardrail calls.

```bash
for id in TzLcGZKuV0TZxXHs 8eFCKIE4qlfhMna0 mAPFaEvgygizLfaY XPYjIUowrNmN5aUj; do
  docker exec n8n n8n publish:workflow --id=$id
done
docker restart n8n
# Wait ~15s for webhooks to register, then confirm all 4 activated at boot:
docker logs n8n --since 30s 2>&1 | grep 'Activated workflow'   # expect 4 lines
```

(Or in the UI: open each of the 4 → **Publish**.)

> The workflow IDs above are preserved on import, so the loop works as-is. If you
> rebuilt the workflows by hand, grab the new IDs from `n8n list:workflow`.

> ⚠️ **Never `docker restart n8n` without publishing first** — a restart reloads
> only published workflows. If you edited credential/model in the UI but only hit
> **Save** (not **Publish**), your changes won't survive a restart.

**6. Verify the pipeline** — only now the webhook is live. The AI Agent reads the
webhook body, so post `chatInput`:

```bash
curl -s --max-time 300 -X POST http://localhost:5678/webhook/agent-hub \
  -H "Content-Type: application/json" \
  -d '{"chatInput": "Analyze GPU cluster utilization"}'
```

Expect **HTTP 200** and a JSON execution plan with all 3 guardrails
(`policy_guard`, `task_router`, `cost_gate`) **PASSED**. The call can take
**1–3 minutes** — the agent runs the full LLM + tool chain.

| Symptom | Likely cause | Fix |
|---|---|---|
| `Cannot POST /webhook/agent-hub` (404) | Workflows not published, or tested too soon after restart | `publish:workflow` on all 4 → restart → wait 15s |
| `{"message":"Error in workflow"}` (500) | Missing `NVIDIAInferenceAPI` credential or wrong model for your endpoint | Run `fix_n8n_setup.sh` or create credential on the **OpenAI Chat Model** node |
| `No prompt specified` | Webhook body not reaching the agent (rare with stock export) | Check AI Agent prompt reads `$json.body?.chatInput` |
| UI edit "didn't work" after restart | Saved a **draft** but didn't **Publish** | Open workflow → **Publish** → restart |

> **Code-node language:** the sub-workflows use **JavaScript** Code nodes. The
> stock n8n image has no Python task runner, so Python Code nodes fail at runtime.

That's it — full redeployment.