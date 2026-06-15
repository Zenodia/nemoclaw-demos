# Haystack RAG with OpenClaw and NVIDIA NIM

This guide walks you through deploying a Retrieval-Augmented Generation (RAG) skill for an OpenClaw agent running inside a NemoClaw OpenShell sandbox. By the end, your agent will be able to index documents (`.txt`, `.md`, `.pdf`), answer natural-language questions grounded in those documents, and list what's currently in its knowledge base — all via NVIDIA NIM for both embeddings and generation.

> **Reference:** For a full introduction to NemoClaw and OpenClaw concepts, see the official quickstart:
> [https://docs.nvidia.com/nemoclaw/latest/user-guide/openclaw/get-started/quickstart](https://docs.nvidia.com/nemoclaw/latest/user-guide/openclaw/get-started/quickstart)

---

## Architecture

The setup has two components:

```
┌─────────────────────────────────────────────────────────────────┐
│  HOST MACHINE                                                   │
│                                                                 │
│  haystack_rag_server.py  (FastAPI, port 9004)                   │
│  ├── POST /index     ← embed + store documents via NVIDIA NIM   │
│  ├── POST /query     ← retrieve + generate answer via NVIDIA    │
│  ├── GET  /documents ← list indexed sources                     │
│  └── GET  /health    ← liveness check                           │
│                                                                 │
│  NVIDIA_API_KEY lives here — never enters the sandbox           │
└────────────────────────────────┬────────────────────────────────┘
                                 │  HTTP only, port 9004
                                 │  governed by sandbox_policy.yaml
┌────────────────────────────────┴────────────────────────────────┐
│  SANDBOX (OpenShell, managed by NemoClaw)                       │
│                                                                 │
│  haystack-rag-skills/scripts/haystack_client.py                 │
│  └── calls server endpoints (index / query / list-documents)    │
│      via requests — zero NVIDIA API calls from sandbox          │
└─────────────────────────────────────────────────────────────────┘
```

**Why a host-side server instead of running Haystack directly in the sandbox?**
The OpenShell sandbox strips `NVIDIA_API_KEY` from the environment by design — it cannot call `integrate.api.nvidia.com` directly. The host-side `haystack_rag_server.py` holds the key and runs all NVIDIA API calls. The sandbox skill is a thin HTTP client that calls the host server through an egress-approved port. This mirrors how the PST demo uses an MCP server, but uses plain JSON REST instead of MCP.

---

## Prerequisites

| Requirement | Details |
|---|---|
| NemoClaw | `nemoclaw` and `openshell` CLIs installed (see [Install NemoClaw](#step-1-install-nemoclaw)). |
| NVIDIA API key | `nvapi-...` key for NVIDIA NIM inference and embedding. Get one at [build.nvidia.com](https://build.nvidia.com). |
| Python 3 | `python3` available on the host (Python 3.10–3.12 all work). |
| `uv` | Installed automatically by `install.sh` if missing. |
| `curl` | For downloading installers and health-checking the server. |

---

## One-Command Setup

### Step 1 — Install NemoClaw

If NemoClaw is not yet installed, run:

```bash
curl -fsSL https://www.nvidia.com/nemoclaw.sh | NEMOCLAW_ACCEPT_THIRD_PARTY_SOFTWARE=1 bash
```

This installs the `nemoclaw` and `openshell` CLIs and sets up the gateway binary. After installation, open a new terminal (or `source ~/.bashrc` / `source ~/.zshrc`) to pick up the updated PATH.

Verify:

```bash
nemoclaw --version # test against nemoclaw v0.0.55
openshell --version # test against openshell 0.0.44
```

---

### Step 2 — Configure `.env`

```bash
cd nemoclaw-demos/haystack-rag-demo
cp .env.template .env
```

Open `.env` and set your NVIDIA API key. All other values have sensible defaults:

```bash
# Required
NVIDIA_API_KEY=nvapi-your-key-here

# Inference provider (sandbox agent model — separate from the RAG server)
INFERENCE_PROVIDER_TYPE=nvidia
INFERENCE_PROVIDER_NAME=nvidia
INFERENCE_BASE_URL=https://integrate.api.nvidia.com/v1
INFERENCE_MODEL=nvidia/llama-3.3-nemotron-super-49b-v1.5

# OpenClaw frontend chat model
# Use nvidia/moonshotai/kimi-k2.6 if you want image/vision input support
OPENCLAW_MODEL=nvidia/llama-3.3-nemotron-super-49b-v1.5
```

> **Important:** Do not add inline comments (`# ...`) after a value on the same line. Write comments on their own lines or the value will include the comment text.

```bash
# Correct
NVIDIA_API_KEY=nvapi-xxx

# Wrong — inline comment gets included in the value
NVIDIA_API_KEY=nvapi-xxx  # my key
```

`NVIDIA_API_KEY` is cached to `~/.nemoclaw/credentials.json` after the first run so future re-runs pick it up automatically. You can also pass overrides inline:

```bash
INFERENCE_MODEL=nvidia/llama-3.3-70b bash install.sh
```

---

### Step 3 — Run the Installer

```bash
bash install.sh
```

The script runs the following steps automatically. You can also pass a sandbox name as an argument to skip the interactive selection prompt:

```bash
bash install.sh <sandbox-name>
```

**What the installer does:**

1. **Cleans up** any stale server processes from a previous run (by PID file `/tmp/haystack-rag.pid`).
2. **Loads `.env`** and resolves `NVIDIA_API_KEY`, inference provider, base URL, and model.
3. **Installs OpenClaw** (if not already installed) via the official install script with `--no-onboard`. OpenClaw installs as an npm package via the Node.js runtime. If you use `nvm`, the binary lands in your active nvm version's bin directory (e.g., `~/.nvm/versions/node/vX.Y.Z/bin/openclaw`) rather than `~/.local/bin`. The installer locates the binary automatically after installation — you do not need to update PATH manually.
4. **Configures OpenClaw** with your NVIDIA API key using `openclaw onboard --non-interactive`. This writes the key into `~/.openclaw/openclaw.json` under `.gateway.auth.token` and configures the NVIDIA NIM endpoint as the inference provider for the OpenClaw frontend chat interface.
5. **Starts the OpenClaw gateway** as a background process. The WebUI token is extracted from `~/.openclaw/openclaw.json` at `.gateway.auth.token` and printed as a ready-to-use URL: `http://127.0.0.1:18789/#token=<token>`.
6. **Installs host-side Python deps** into a `.venv` in the demo directory: `fastapi`, `uvicorn`, `haystack-ai`, `nvidia-haystack`, `pypdf`. These are used by the RAG server only — the sandbox skill does not need them.
7. **Starts `haystack_rag_server.py`** as a background process (port 9004) with auto-restart on crash. The server is started with `NVIDIA_API_KEY` injected from the environment. Logs go to `/tmp/haystack-rag.log`. PID is tracked at `/tmp/haystack-rag.pid`.
8. **Clears any active global network policy** (`openshell policy delete --global`) before running `nemoclaw onboard`. This is required because `nemoclaw onboard` applies its own network presets (npm, pypi, huggingface, etc.) as a per-sandbox policy during its step `[8/8]`, and that step fails with `"policy is managed globally"` if a gateway-global policy is already active.
9. **Onboards a NemoClaw sandbox** fully non-interactively via `nemoclaw onboard --non-interactive`. Provider, model, and API key are passed via environment variables (`NEMOCLAW_NON_INTERACTIVE=1`, `NEMOCLAW_PROVIDER=custom`, `NEMOCLAW_ENDPOINT_URL`, `NEMOCLAW_MODEL`, `COMPATIBLE_API_KEY`). The sandbox defaults to the name `my-assistant`. If multiple sandboxes exist, the script prompts you to pick one.
10. **Sets the inference provider** for the sandbox agent to NVIDIA NIM, always overriding whatever bootstrap model `nemoclaw onboard` chose.
11. **Applies the sandbox network policy** (`policy/sandbox_policy.yaml`) as a per-sandbox (not global) policy after the sandbox is created. This opens port 9004 egress from the sandbox to the host, restricted to the skill venv's Python binary. `NVIDIA_API_KEY` is **never** passed into the sandbox. The policy file contains only `network_policies` — no `filesystem_policy` section — because modifying filesystem policy on a live sandbox is not permitted by the OpenShell runtime.
11. **Uploads `haystack-rag-skills`** to `/sandbox/.openclaw-data/workspace/skills/haystack-rag-skills/`.
12. **Bootstraps the skill venv** inside the sandbox with only `requests` — no Haystack packages needed in the sandbox since the skill is a pure HTTP client.
13. **Verifies** the installation: server health, skill presence, and skill venv import.

---

### Step 4 — Add Documents

Copy the files you want to index into the server's data directory on the host:

```bash
# From the demo directory
cp /path/to/your-report.pdf data/documents/
cp /path/to/notes.txt data/documents/
```

Supported formats: `.pdf`, `.txt`, `.md` (searched recursively).

---

### Step 5 — Connect and Try It Out

Connect to the sandbox:

```bash
# From your host terminal
nemoclaw <sandbox-name> connect
```

Inside the sandbox, launch the OpenClaw TUI:

```bash
openclaw tui
```

Verify the skill is loaded:

```
> do you have a skill to search documents?

  Yes, I have the haystack-rag-skills skill available. It connects to a
  Haystack RAG server running on the host to index and search documents
  using NVIDIA NIM for embeddings and generation.

  I can:
  - Index documents from the host data directory
  - Answer questions grounded in the indexed documents
  - List what documents are currently indexed

  What would you like to know?
```

---

**"Index my documents"**

The agent will call `index` on the server, which embeds all files in `data/documents/` using `nvidia/nv-embedqa-e5-v5` and stores chunks in `data/store.json`.

```
> Index my documents

  Running index on the server...

  Indexed 28 new chunk(s) from 2 file(s).
  Total chunks in store: 28
  Store: /home/user/haystack-rag-demo/data/store.json
```

---

**"What documents are in the knowledge base?"**

```
> What documents are indexed?

  Total chunks: 28
  Sources (2):
    /home/user/haystack-rag-demo/data/documents/guide.pdf: 22 chunk(s)
    /home/user/haystack-rag-demo/data/documents/notes.txt: 6 chunk(s)
```

---

**"What are the key recommendations in the guide?"**

The agent retrieves the most relevant chunks and calls `nvidia/llama-3.3-nemotron-super-49b-v1.5` to generate a grounded answer.

```
> What are the key recommendations in the guide?

  Based on guide.pdf, the key recommendations are:

  1. **Start with a baseline pipeline** before adding complexity. The document
     emphasizes composability — assemble only the components you need.

  2. **Use NvidiaDocumentEmbedder for indexing** and NvidiaTextEmbedder for
     queries to ensure vector-space consistency.

  3. **Set split_overlap ≥ 15%** of split_length to avoid context loss at chunk
     boundaries.

  Source: guide.pdf
```

---

**"Ask my documents about authentication flows"**

```
> Ask my documents about authentication flows

  The documents do not contain information about authentication flows.
  Only guide.pdf and notes.txt are indexed — neither covers authentication.
  If you have a relevant document, add it to the data directory and
  ask me to index again.
```

The RAG server answers honestly when the indexed documents don't cover a topic.

---

## OpenClaw WebUI (Optional)

If you're on a remote machine (e.g., a Brev instance), forward the gateway port locally:

```bash
# Run this on your local machine
brev port-forward <your-instance-name> -p 18789:18789
```

Then open the WebUI in your local browser using the URL printed by `install.sh`:

```
http://127.0.0.1:18789/#token=<token>
```

The token is stored at `.gateway.auth.token` inside `~/.openclaw/openclaw.json`. To retrieve it manually:

```bash
python3 -c "import json; d=json.load(open('$HOME/.openclaw/openclaw.json')); print(d['gateway']['auth']['token'])"
```

**Default chat model:** `nvidia/llama-3.3-nemotron-super-49b-v1.5`

**For vision/image input:** Switch to `nvidia/moonshotai/kimi-k2.6` by setting `OPENCLAW_MODEL=nvidia/moonshotai/kimi-k2.6` in `.env` before running `install.sh`.

If the WebUI shows a permission error, list and approve the pending device:

```bash
openclaw devices list
openclaw devices approve <hash-shown-as-pending>
```

---

## How the Skill Works

The `haystack-rag-skills` client (`scripts/haystack_client.py`) is a pure HTTP client. OpenClaw invokes it via the skill's venv Python, which is the only binary the sandbox policy permits to open a connection to port 9004:

```bash
SKILL_DIR=~/.openclaw/workspace/skills/haystack-rag-skills
$SKILL_DIR/venv/bin/python3 $SKILL_DIR/scripts/haystack_client.py <command> [args]
```

> **Note:** Inside the sandbox, `~/.openclaw` is a symlink to `~/.openclaw-data`. The skill is physically at `/sandbox/.openclaw-data/workspace/skills/haystack-rag-skills/`. The network policy lists both path forms so egress is permitted from either resolved path.

**Command reference:**

```bash
# Index all files in the server's default data directory
python3 haystack_client.py index

# Index from a specific host path (pass as an override)
python3 haystack_client.py index --data-dir /absolute/host/path

# Ask a question (top-k chunks retrieved)
python3 haystack_client.py query --question "What is the main topic?" --top-k 8

# List all indexed sources
python3 haystack_client.py list-documents

# Use a custom server URL (default: http://host.openshell.internal:9004)
python3 haystack_client.py --server-url http://127.0.0.1:9004 query --question "..."
```

See `haystack-rag-skills/SKILL.md` for the full argument reference.

---

## Access Control

Access is governed by two independent controls.

### Control 1 — Server API surface (`haystack_rag_server.py`)

The host server runs with full access to `NVIDIA_API_KEY`, the filesystem, and the NVIDIA API. Only four HTTP endpoints are reachable from the network — `NVIDIA_API_KEY` and internal pipeline state are never exposed:

```python
@app.get("/health")   # liveness — no key required
@app.post("/index")   # triggers embedding + store update
@app.post("/query")   # triggers retrieval + generation
@app.get("/documents") # lists indexed sources
```

### Control 2 — `sandbox_policy.yaml` (network-level)

The `haystack_rag_host` policy block opens outbound HTTP from the sandbox to port 9004 only, and only from the skill venv's Python binary:

```yaml
network_policies:
  haystack_rag_host:
    endpoints:
      - host: host.openshell.internal
        port: 9004
        allowed_ips: [172.17.0.1]
      - host: 127.0.0.1
        port: 9004
    binaries:
      - { path: /usr/bin/python3 }
      - { path: "/sandbox/.openclaw/workspace/skills/*/venv/bin/python3" }
      - { path: "/sandbox/.openclaw-data/workspace/skills/*/venv/bin/python3" }
      # ... (full list in policy/sandbox_policy.yaml)
```

The `nvidia` policy block (which would allow direct NVIDIA API calls) deliberately **does not** include the skill venv python binaries — skills cannot call NVIDIA directly even if they tried.

---

## Troubleshooting

| Issue | Fix |
|---|---|
| `NVIDIA_API_KEY is not set` (fatal at step 2) | Add `NVIDIA_API_KEY=nvapi-...` to `.env` with no inline comment after the value, or `export NVIDIA_API_KEY=...` before running `install.sh`. |
| `openclaw: command not found` after install | OpenClaw installs via npm into your active Node.js bin dir. If you use nvm this is `~/.nvm/versions/node/vX.Y.Z/bin/`. `install.sh` finds it automatically; for manual use run: `export PATH="$(dirname $(find ~/.nvm -name openclaw -type f 2>/dev/null \| head -1)):$PATH"` |
| `openclaw onboard` fails with auth error | Confirm `NVIDIA_API_KEY` is a valid `nvapi-...` key. Check: `curl -s -H "Authorization: Bearer $NVIDIA_API_KEY" https://integrate.api.nvidia.com/v1/models \| head -1` |
| WebUI token not found | The token lives at `.gateway.auth.token` inside `~/.openclaw/openclaw.json`, not at the top level. Retrieve it with: `python3 -c "import json; d=json.load(open('$HOME/.openclaw/openclaw.json')); print(d['gateway']['auth']['token'])"` |
| WebUI shows permission error | Approve the pending device: `openclaw devices list` then `openclaw devices approve <hash>` |
| RAG server not responding on port 9004 | Check logs: `tail -50 /tmp/haystack-rag.log`. Restart: `kill $(cat /tmp/haystack-rag.pid) && bash install.sh <sandbox-name>` |
| `NVIDIA_API_KEY is not set on the host` (server 500) | The server process was started without the key. Re-run `install.sh` — it exports the key when starting the server. Do not start the server manually without `export NVIDIA_API_KEY=...`. |
| `Connection refused` / `cannot connect to ... port 9004` | Server is not running, or the sandbox policy was not applied. Verify: `curl http://127.0.0.1:9004/health` from the host. Re-run `install.sh`. |
| `l7_decision=deny` / 403 in OpenShell logs | Policy not applied, or the binary path isn't listed. Re-run: `openshell policy set <sandbox-name> --policy policy/sandbox_policy.yaml --wait` |
| `"filesystem policy cannot be removed on a live sandbox"` or `"filesystem read_write path ... cannot be removed"` from `openshell policy set` | The submitted policy was trying to add or remove a `filesystem_policy` section on a running sandbox, which is forbidden. The correct policy file (`sandbox_policy.yaml`) contains only `network_policies`. If your policy file has a `filesystem_policy` block, remove it entirely. If the sandbox was built with an old policy that included one, delete the sandbox and re-run `install.sh` (see [Full environment reset](#full-environment-reset)). |
| `"policy is managed globally; delete global policy before sandbox policy update"` | A gateway-global policy is active. `nemoclaw onboard`'s step `[8/8]` and any per-sandbox `openshell policy set` call will fail. Clear it first: `openshell policy delete --global --yes`. `install.sh` does this automatically, but if you ran `openshell policy set --global` manually you must clear it yourself. After clearing, re-run `install.sh`. |
| `ModuleNotFoundError: requests` (in sandbox) | Skill venv is missing. Recreate it inside the sandbox: `openshell sandbox exec -n <sandbox-name> -- python3 -m venv /sandbox/.openclaw-data/workspace/skills/haystack-rag-skills/venv && openshell sandbox exec -n <sandbox-name> -- /sandbox/.openclaw-data/workspace/skills/haystack-rag-skills/venv/bin/pip install -q requests` |
| `No documents indexed` at query time | Run `index` first, and confirm `.txt`/`.md`/`.pdf` files exist in `data/documents/` on the host. |
| Agent doesn't find the skill | Disconnect and reconnect to the sandbox. Verify the skill exists: `openshell sandbox exec -n <sandbox-name> -- test -f /sandbox/.openclaw-data/workspace/skills/haystack-rag-skills/SKILL.md && echo ok` |
| Wrong inference model in TUI | `nemoclaw onboard` sets its own default. `install.sh` always overrides it with your `.env` model after the gateway is live. To fix manually: `openshell inference set --provider nvidia --model nvidia/llama-3.3-nemotron-super-49b-v1.5` then reconnect. |
| Re-indexing adds duplicate chunks | The indexing pipeline uses `DuplicatePolicy.SKIP` — re-indexing the same files is safe. The chunk count won't grow. To force a full re-index, delete `data/store.json` and run `index` again. |

### Restart the RAG server without full reinstall

```bash
kill $(cat /tmp/haystack-rag.pid) 2>/dev/null || true
bash install.sh <sandbox-name>
```

### Full environment reset

Use this when you hit an unrecoverable policy error, a partially-created sandbox from a failed install, or just want a clean slate.

```bash
# 1. Stop the RAG server
kill $(cat /tmp/haystack-rag.pid) 2>/dev/null || true

# 2. Clear any active global network policy
#    Required before sandbox deletion and before the next nemoclaw onboard.
#    A stale global policy causes "policy is managed globally" errors.
openshell policy delete --global --yes 2>/dev/null || true

# 3. Delete the sandbox (replace my-assistant with your sandbox name)
openshell sandbox delete my-assistant

# 4. Remove host venv and stored document index
rm -rf .venv data/store.json

# 5. Re-run from scratch
bash install.sh
```

> **When to run a full reset:**
> - `install.sh` failed mid-run and left a partially-configured sandbox
> - You see `"filesystem policy cannot be removed on a live sandbox"` — the sandbox was built with an incompatible policy
> - You see `"policy is managed globally"` and `openshell policy delete --global` was not enough to unblock it
> - You want to switch to a different sandbox name or model

---

## File Structure

```
haystack-rag-demo/
├── install.sh                          # One-command installer (Steps 1–12)
├── haystack_rag_server.py              # Host-side FastAPI RAG server (port 9004)
├── .env.template                       # Configuration template — copy to .env
├── .env                                # Your local config (not committed)
├── haystack-rag-openclaw-guide.md      # This guide
├── data/
│   ├── documents/                      # ← drop your .txt / .md / .pdf files here
│   └── store.json                      # Auto-created on first 'index' run
├── policy/
│   └── sandbox_policy.yaml             # Network policy — haystack_rag_host on port 9004
└── haystack-rag-skills/
    ├── SKILL.md                        # OpenClaw skill definition and usage examples
    └── scripts/
        └── haystack_client.py          # HTTP client — calls /index, /query, /documents
```

---

## Notes on Tested Environment

The following issues were identified and fixed during development of this demo. They are all resolved in the current code, but are documented here so you understand the design decisions and can diagnose similar issues if you adapt the scripts.

---

### OpenClaw PATH after npm install

On systems with `nvm`, `openclaw` installs into the active nvm node's bin directory (e.g., `~/.nvm/versions/node/v22.22.3/bin/`), not `~/.local/bin`. A naive `export PATH="$HOME/.local/bin:$PATH"` after install fails silently. The `install.sh` `_ensure_openclaw_path()` function uses `find` to locate the binary under `~/.nvm`, `~/.local/bin`, `~/.cargo/bin`, and standard system paths, then prepends the correct directory to `PATH`.

---

### Gateway token nested under `.gateway.auth.token`

The OpenClaw gateway auth token lives at `.gateway.auth.token` inside `~/.openclaw/openclaw.json`, not at the JSON root. Grep-based extraction (`grep -o '"token":"[^"]*"'`) finds nothing because the top-level keys are different. The installer uses a Python one-liner to parse the JSON properly:

```bash
python3 -c "
import json
d = json.load(open('$HOME/.openclaw/openclaw.json'))
print(d.get('gateway', {}).get('auth', {}).get('token', ''))
"
```

---

### `NvidiaChatGenerator` uses `api_base_url=`, not `api_url=`

The Haystack NVIDIA integration has an inconsistency: `NvidiaTextEmbedder` and `NvidiaDocumentEmbedder` take `api_url=` as the endpoint parameter, but `NvidiaChatGenerator` takes `api_base_url=`. If you copy initialization code from an embedder to the generator, the wrong parameter is silently ignored and every query returns a 500 error at request time with no helpful message at import time. `haystack_rag_server.py` uses `api_base_url=` for the generator.

---

### Restart loop exits under `set -euo pipefail`

With `set -euo pipefail` active (which `install.sh` uses), any non-zero exit code inside a subshell causes the subshell to terminate. This means a crashing Python server inside a `while true` restart loop kills the loop rather than restarting the server. All background server loops in `install.sh` append `|| true` to the Python invocation so a server crash is treated as a recoverable event.

---

### `filesystem policy cannot be removed on a live sandbox`

**Error:** `openshell policy set` returns `"filesystem read_write path '/sandbox/.openclaw' cannot be removed on a live sandbox"` or `"filesystem policy cannot be removed on a live sandbox"`.

**Cause:** Submitting a policy that either (a) includes a `filesystem_policy` section that conflicts with what was set at sandbox build time, or (b) omits `filesystem_policy` entirely (which the runtime interprets as "remove the existing filesystem policy"). Neither is permitted on a running sandbox container.

**Fix:** The `sandbox_policy.yaml` in this demo contains only `network_policies` — no `filesystem_policy` block. Network-only policies can be applied to live sandboxes without restriction. If you ever need filesystem policy changes, they must be baked in at sandbox build time (i.e., before `nemoclaw onboard` runs), not patched afterward. If you encounter this error on an existing sandbox, perform a [full environment reset](#full-environment-reset) to delete and recreate it.

---

### `policy is managed globally; delete global policy before sandbox policy update`

**Error:** `nemoclaw onboard` fails at step `[8/8]` with `"policy is managed globally; delete global policy before sandbox policy update"`. Per-sandbox `openshell policy set` calls also fail with the same message.

**Cause:** A gateway-global policy (set with `openshell policy set --global`) was active when `nemoclaw onboard` tried to apply its network presets (npm, pypi, huggingface, etc.) to the newly created sandbox. The runtime enforces that sandbox-level policy updates are not permitted while a global policy is managing the gateway.

**Fix:** Delete the global policy before running `nemoclaw onboard` or any per-sandbox `openshell policy set`:

```bash
openshell policy delete --global --yes
```

`install.sh` does this automatically at the start of step 8 (`|| true` so it's a no-op when no global policy exists). Our earlier approach of applying the policy globally before onboard was reversed precisely because of this conflict.

**Cleanup if you hit this mid-run** (sandbox partially created, global policy still active):

```bash
openshell policy delete --global --yes
openshell sandbox delete <sandbox-name>
bash install.sh
```

---

Created by **zcharpy**
