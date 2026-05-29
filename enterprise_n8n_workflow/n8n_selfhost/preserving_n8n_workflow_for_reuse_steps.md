# Preserving & Redeploying the Enterprise n8n Workflow

This folder packages a self-hosted n8n **EnterpriseOrchestrator** workflow (an AI
agent that runs `policy_guard → task_router → cost_gate → execution plan`) plus 3
sub-workflows, so it can be saved and redeployed elsewhere — **without** shipping
any API keys.

**Which part do you need?**
- **Redeploying a copy someone sent you?** → jump to
  [Re-deployment Steps](#re-deployment-steps---on-the-new-machine) and
  [Using your own API keys](#using-your-own-api-keys). (Skip Option A.)
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

The workflows reference exactly **one** credential by name: **`NVIDIAInferenceAPI`**
(type **OpenAI API** / `openAiApi`), used by the orchestrator's chat-model node.
To run with your own key — no need for the original owner's secrets:

**Easiest — n8n UI (recommended):**
1. Import the workflows (next section), then open **EnterpriseOrchestrator**.
2. Click the **OpenAI Chat Model** node → **Credential → Create New**:
   - **API Key:** your own key — Claude `sk-…`, NVIDIA `nvapi-…`, or any OpenAI-compatible key.
   - **Base URL:** the endpoint **that issues your key**, e.g.
     - NVIDIA build/Nemotron: `https://integrate.api.nvidia.com/v1`
     - the original demo used: `https://inference-api.nvidia.com/v1`
   - (You can name it `NVIDIAInferenceAPI` to match, but the name is cosmetic.)
3. **Set the model** on that same node — the import ships a hardcoded
   `aws/anthropic/bedrock-claude-sonnet-4-6`. Change the **Model** field to one your
   endpoint actually serves (e.g. a `nvidia/…` Nemotron id, or your Claude model).
4. **Save.** Selecting/creating the credential *on the node* re-binds it correctly.

> ⚠️ **Bind by ID, not name.** The imported node references the original
> credential's **ID** (`rO9tDpks1CwG9AN7`). A standalone credential you create
> elsewhere gets a *new* ID and won't auto-link — always create/pick the
> credential **from the node** (step 2) so n8n rebinds it. If the node shows
> "credential not set" after import, that's why: open it and select your credential.

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
[Using your own API keys](#using-your-own-api-keys). In the UI, open
**EnterpriseOrchestrator** → **OpenAI Chat Model** node → create your credential
(your key + correct Base URL) **and** set the **Model** field to one your endpoint
serves. Save the workflow.

> Do **not** import the sanitized `credentials-export.json` (its `data` is blank).
> *(Only if you kept a `--with-secrets` private backup AND started n8n with the
> matching `N8N_ENCRYPTION_KEY`:*
> `docker exec n8n n8n import:credentials --input=/home/node/.n8n/creds.json`*.)*

**5. Activate ALL 4 workflows, THEN restart** — imports arrive **inactive**, and a
webhook is **not** reachable until its workflow is active (you'd get a 404).

> ⚠️ The 3 sub-workflows must be active too — this n8n version refuses to run an
> inactive workflow invoked as a tool (`Workflow is not active and cannot be
> executed`), which breaks the orchestrator's guardrail calls.

```bash
for id in TzLcGZKuV0TZxXHs 8eFCKIE4qlfhMna0 mAPFaEvgygizLfaY XPYjIUowrNmN5aUj; do
  docker exec n8n n8n update:workflow --id=$id --active=true
done
docker restart n8n
# Confirm all 4 register at boot:
docker logs n8n --since 30s 2>&1 | grep -A5 'Start Active Workflows'
```
(Or in the UI: open each of the 4 → toggle **Active**.)

> The workflow IDs above are preserved on import, so the loop works as-is. If you
> rebuilt the workflows by hand, grab the new IDs from `n8n list:workflow`.

**6. Verify the pipeline** — only now the webhook is live. The AI Agent reads the
webhook body, so post `chatInput`:
```bash
curl -X POST http://localhost:5678/webhook/agent-hub \
  -H "Content-Type: application/json" \
  -d '{"chatInput": "Analyze GPU cluster utilization"}'
```
Expect a JSON execution plan with all 3 guardrails (`policy_guard`, `task_router`,
`cost_gate`) **PASSED**. If you get `No prompt specified` or an echoed system
prompt, the credential/model isn't set on the node (Step 4) — fix and retry.

> **Code-node language:** the sub-workflows use **JavaScript** Code nodes. The
> stock n8n image has no Python task runner, so Python Code nodes fail at runtime.

That's it — full redeployment.