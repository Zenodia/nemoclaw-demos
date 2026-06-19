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
| NemoClaw | `nemoclaw` and `openshell` CLIs installed (see [Install NemoClaw](#step-1--install-nemoclaw)). |
| NVIDIA API key | `nvapi-...` key for NVIDIA NIM inference and embedding. Get one at [build.nvidia.com](https://build.nvidia.com). |
| Python 3 | `python3` available on the host (Python 3.10–3.12 all work). |
| `uv` | Installed automatically by `install.sh` if missing. |
| `curl` | For downloading installers and health-checking the server. |

---

## One-Command Setup

### Step 1 — Install NemoClaw

If NemoClaw is not yet installed, run:

```bash
bash
export NEMOCLAW_AGENT=openclaw
export NEMOCLAW_INSTALL_TAG=v0.0.55
curl -fsSL https://www.nvidia.com/nemoclaw.sh | NEMOCLAW_ACCEPT_THIRD_PARTY_SOFTWARE=1 bash
```

This installs the `nemoclaw` and `openshell` CLIs and sets up the gateway binary. After installation, open a new terminal (or `source ~/.bashrc` / `source ~/.zshrc`) to pick up the updated PATH.

Verify:

```bash
nemoclaw --version    # e.g. nemoclaw v0.0.55
openshell --version   # e.g. openshell 0.0.44
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

`install.sh` loads `.env` automatically. `haystack_rag_server.py` also reads `.env` from the demo directory via `python-dotenv`, so you do **not** need to `export NVIDIA_API_KEY` when starting the server manually.

`NVIDIA_API_KEY` is cached to `~/.nemoclaw/credentials.json` after the first run so future re-runs pick it up automatically. You can also pass overrides inline:

```bash
INFERENCE_MODEL=nvidia/llama-3.3-70b bash install.sh
```

---

### Step 3 — Run the Installer

```bash
bash install.sh
```

Pass a sandbox name to skip the interactive selection prompt:

```bash
bash install.sh my-assistant
```

**What the installer does:**

1. **Cleans up** stale RAG server processes (PID file `/tmp/haystack-rag.pid` and any leftover `haystack_rag_server` processes).
2. **Loads `.env`** and resolves `NVIDIA_API_KEY`, inference provider, base URL, and model.
3. **Installs OpenClaw** (if missing) via the official install script with `--no-onboard`. The installer locates the binary automatically under nvm, `~/.local/bin`, or system paths.
4. **Configures OpenClaw** on the host with `openclaw onboard --non-interactive` (NVIDIA API key + chat model for the host WebUI).
5. **Starts the host OpenClaw gateway** as a background process and prints the WebUI URL with token.
6. **Installs host-side Python deps** into `.venv`: `fastapi`, `uvicorn`, `python-dotenv`, `haystack-ai`, `nvidia-haystack`, `pypdf`.
7. **Starts `haystack_rag_server.py`** on port 9004 as a background process with auto-restart. Frees port 9004 first if something is already listening. Logs: `/tmp/haystack-rag.log`. PID: `/tmp/haystack-rag.pid`.
8. **Clears any global network policy** (`openshell policy delete --global`) so `nemoclaw onboard` can apply its own presets.
9. **Onboards a NemoClaw sandbox** (if none exists) via `nemoclaw onboard --non-interactive`, then waits for it to become ready.
10. **Sets the inference provider** for the sandbox agent to NVIDIA NIM (always overrides the bootstrap default).
11. **Applies the sandbox network policy** (`policy/sandbox_policy.yaml`) to open port 9004 egress from the skill venv to the host. On a live sandbox that already has incompatible filesystem policy, this step warns instead of failing — see [Troubleshooting](#troubleshooting).
12. **Installs `haystack-rag-skills`** via `nemoclaw <sandbox> skill install` (validates `SKILL.md`, uploads to the correct path, registers the skill). Falls back to `openshell sandbox upload` if needed.
13. **Enables the skill in OpenClaw's registry** — sets `skills.entries.haystack-rag-skills.enabled=true` and `tools.profile=coding` in `/sandbox/.openclaw/openclaw.json` so the agent can `exec` the skill scripts.
14. **Restarts the OpenClaw gateway inside the sandbox** so it re-reads the skill registry.
15. **Bootstraps the skill venv** inside the sandbox with only `requests`.
16. **Verifies** server health, skill presence, and venv import.

> **After install:** Disconnect and reconnect the sandbox TUI so OpenClaw picks up the new skill (see [Step 5](#step-5--connect-and-try-it-out)).

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

**Reconnect after install** (required for the agent to see the skill):

```bash
# Exit any existing sandbox session first, then:
nemoclaw my-assistant connect
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
```

If the skill is missing, reinstall it and reconnect:

```bash
# From the host (not inside the sandbox)
nemoclaw my-assistant skill install ~/nemoclaw-demos/haystack-rag-demo/haystack-rag-skills
```

Then disconnect and run `nemoclaw my-assistant connect` again.

---

**"Index my documents"**

The agent calls `index` on the server, which embeds all files in `data/documents/` using `nvidia/nv-embedqa-e5-v5` and stores chunks in `data/store.json`.

```
> Index my documents

  Indexed 28 new chunk(s) from 2 file(s).
  Total chunks in store: 28
```

---

**"What documents are indexed?"**

```
> What documents are indexed?

  Total chunks: 28
  Sources (2):
    .../data/documents/guide.pdf: 22 chunk(s)
    .../data/documents/notes.txt: 6 chunk(s)
```

---

**"What are the key recommendations in the guide?"**

The agent retrieves relevant chunks and generates a grounded answer via `nvidia/llama-3.3-nemotron-super-49b-v1.5`.

---

## OpenClaw WebUI (Optional)

If you're on a remote machine (e.g., a Brev instance), forward the gateway port locally:

```bash
# Run this on your local machine
brev port-forward <your-instance-name> -p 18789:18789
```

Then open the WebUI URL printed by `install.sh`:

```
http://127.0.0.1:18789/#token=<token>
```

Retrieve the token manually:

```bash
python3 -c "import json; d=json.load(open('$HOME/.openclaw/openclaw.json')); print(d['gateway']['auth']['token'])"
```

**For vision/image input:** Set `OPENCLAW_MODEL=nvidia/moonshotai/kimi-k2.6` in `.env` before running `install.sh`.

If the WebUI shows a permission error:

```bash
openclaw devices list
openclaw devices approve <hash-shown-as-pending>
```

---

## How the Skill Works

The `haystack-rag-skills` client (`scripts/haystack_client.py`) is a pure HTTP client. OpenClaw invokes it via the skill's venv Python — the only binary the sandbox policy permits to reach port 9004:

```bash
SKILL_DIR=~/.openclaw/workspace/skills/haystack-rag-skills
$SKILL_DIR/venv/bin/python3 $SKILL_DIR/scripts/haystack_client.py <command> [args]
```

**Skill location:** On current NemoClaw sandboxes (OpenClaw 2026.5+), skills live at:

```
/sandbox/.openclaw/workspace/skills/haystack-rag-skills/
```

Legacy sandboxes may use `/sandbox/.openclaw-data/workspace/skills/`. `nemoclaw skill install` picks the correct path automatically. Do **not** rely on a raw `openshell sandbox upload` to `.openclaw-data` — OpenClaw will not discover the skill unless it is registered in `openclaw.json`.

**Command reference:**

```bash
# Index all files in the server's default data directory
python3 haystack_client.py index

# Ask a question (top-k chunks retrieved)
python3 haystack_client.py query --question "What is the main topic?" --top-k 8

# List all indexed sources
python3 haystack_client.py list-documents

# Custom server URL (default: http://host.openshell.internal:9004)
python3 haystack_client.py --server-url http://127.0.0.1:9004 query --question "..."
```

See `haystack-rag-skills/SKILL.md` for the full argument reference.

---

## Access Control

Access is governed by two independent controls.

### Control 1 — Server API surface (`haystack_rag_server.py`)

The host server runs with full access to `NVIDIA_API_KEY`, the filesystem, and the NVIDIA API. Only four HTTP endpoints are reachable from the network:

```python
@app.get("/health")    # liveness — no key required
@app.post("/index")    # triggers embedding + store update
@app.post("/query")     # triggers retrieval + generation
@app.get("/documents")  # lists indexed sources
```

### Control 2 — `sandbox_policy.yaml` (network-level)

The `haystack_rag_host` policy block opens outbound HTTP from the sandbox to port 9004 only, and only from the skill venv's Python binary:

```yaml
network_policies:
  haystack_rag_host:
    endpoints:
      - host: host.openshell.internal
        port: 9004
    binaries:
      - { path: "/sandbox/.openclaw/workspace/skills/*/venv/bin/python3" }
      - { path: "/sandbox/.openclaw-data/workspace/skills/*/venv/bin/python3" }
      # ... (full list in policy/sandbox_policy.yaml)
```

The `nvidia` policy block deliberately **does not** include the skill venv python binaries — skills cannot call NVIDIA directly even if they tried.

---

## Manual Operations

### Run the RAG server manually (without full reinstall)

The server loads `NVIDIA_API_KEY` from `.env` automatically:

```bash
cd nemoclaw-demos/haystack-rag-demo
source .venv/bin/activate

# Free port 9004 if a previous instance is still running
kill $(lsof -t -i:9004) 2>/dev/null || true

python haystack_rag_server.py
```

### Restart via installer (recommended)

Restarts the server, reapplies policy, reinstalls the skill, and refreshes the skill venv:

```bash
kill $(cat /tmp/haystack-rag.pid) 2>/dev/null || true
bash install.sh my-assistant
```

### Reinstall only the skill

```bash
nemoclaw my-assistant skill install ~/nemoclaw-demos/haystack-rag-demo/haystack-rag-skills
```

Then disconnect and reconnect the sandbox TUI.

---

## Troubleshooting

| Issue | Fix |
|---|---|
| `NVIDIA_API_KEY is not set` at install time | Add `NVIDIA_API_KEY=nvapi-...` to `.env` (no inline comment after the value). |
| `NVIDIA_API_KEY is not set` when querying (server 500) | Confirm `.env` has the key and restart the server. The server reads `.env` via `python-dotenv`; re-run `install.sh` or start manually from the demo directory. |
| `[Errno 98] address already in use` on port 9004 | Kill the stale process: `kill $(lsof -t -i:9004)` then restart. `install.sh` does this automatically. |
| Agent doesn't find `haystack-rag-skills` | Reinstall: `nemoclaw <sandbox> skill install haystack-rag-skills/`. Disconnect and reconnect the TUI. Verify: `openshell sandbox exec -n <sandbox> -- test -f /sandbox/.openclaw/workspace/skills/haystack-rag-skills/SKILL.md && echo ok` |
| Skill uploaded but not in agent's skill list | OpenClaw 2026.5+ requires registry entry. Re-run `install.sh` (enables `skills.entries.haystack-rag-skills` in `openclaw.json`) or run `nemoclaw skill install`. |
| `nemoclaw skill install` says success but agent has no skill body | On some versions the files don't land at the workspace path (only `venv/` is there), leaving the skill registered-but-empty. Re-upload the skill DIRECTORY into the **parent** skills dir: `openshell sandbox upload <sandbox> haystack-rag-skills /sandbox/.openclaw/workspace/skills` — uploading to the skill dir itself nests `haystack-rag-skills/haystack-rag-skills/`. |
| `not permitted by policy` / `blocked: internal address` from the skill | Two causes: the venv python resolves to `/usr/bin/python3.NN` (must be allowlisted — 3.13 on current images), and `host.openshell.internal`'s Docker bridge IP must be in `allowed_ips`. On a live sandbox apply incrementally (preserves filesystem policy): `openshell policy update <sandbox> --add-endpoint host.openshell.internal:9004:full:::allowed-ip=<bridge-ip> --binary '/sandbox/.openclaw/workspace/skills/*/venv/bin/python3' --binary /usr/bin/python3.13 --rule-name haystack_rag_host --wait`. Find the bridge IP with `openshell sandbox exec -n <sandbox> -- getent hosts host.openshell.internal`. |
| RAG server not responding | Check logs: `tail -50 /tmp/haystack-rag.log`. Health check: `curl http://127.0.0.1:9004/health` |
| `Connection refused` / port 9004 from sandbox | Server not running, or sandbox policy not applied. Re-run `install.sh`. If policy failed on a live sandbox, see [Full environment reset](#full-environment-reset). |
| `l7_decision=deny` / 403 in OpenShell logs | Policy not applied or binary path not listed. Re-run: `openshell policy set <sandbox> --policy policy/sandbox_policy.yaml --wait` |
| `"filesystem policy cannot be removed on a live sandbox"` | Policy step failed on an existing sandbox. Skill install still works, but port 9004 egress may be blocked. Delete and recreate the sandbox (see reset below). |
| `"policy is managed globally"` | Run `openshell policy delete --global --yes`, then re-run `install.sh`. The installer clears this automatically before onboard. |
| `ModuleNotFoundError: requests` in sandbox | Re-run `install.sh` to recreate the skill venv, or manually: `openshell sandbox exec -n <sandbox> -- python3 -m venv /sandbox/.openclaw/workspace/skills/haystack-rag-skills/venv && .../venv/bin/pip install -q requests` |
| `No documents indexed` at query time | Run `index` first; confirm files exist in `data/documents/` on the host. |
| Wrong inference model in TUI | `openshell inference set --provider nvidia --model nvidia/llama-3.3-nemotron-super-49b-v1.5` then reconnect. |
| `openclaw: command not found` | If using nvm: `export PATH="$(dirname $(find ~/.nvm -name openclaw -type f 2>/dev/null \| head -1)):$PATH"` |
| WebUI token not found | Token is at `.gateway.auth.token` in `~/.openclaw/openclaw.json` (see Step 3 / WebUI section). |

### Agent won't run the skill (model & session)

The skill can be installed, registered, and reachable and the agent *still*
refuses to use it. Causes, in order of likelihood:

1. **Use a Nemotron-3 agent model.** OpenClaw exposes tools through a
   tool-search / code-execution surface (`openclaw.tools.search/describe/call`,
   invoked as `tool_search_code`) rather than as plain bash. Llama-based models —
   `nvidia/llama-3.3-nemotron-super-49b`, `meta/llama-3.3-70b-instruct`,
   `nvidia/llama-3.1-nemotron-70b-instruct` — mishandle it: they refuse
   ("restricted access"), claim only `tool_search_code` is available, or misfire
   (e.g. create a cron job) instead of running the skill. **Nemotron-3** models
   drive it reliably. Set `INFERENCE_MODEL=nvidia/nemotron-3-super-120b-a12b` in
   `.env`, then `openshell inference update --model nvidia/nemotron-3-super-120b-a12b`
   and reconnect. (There is no Nemotron-3 between 30B and 120B; the 120B is the
   practical floor for reliable tool use here. The model navigates the skill via
   `await openclaw.tools.call('openclaw:core:exec', { command: '...' })` — see
   `haystack-rag-skills/SKILL.md`.)

2. **Start a fresh session.** A session that accumulated refusals (e.g. while on
   a weaker model) stays "poisoned": the model reads its own past refusals and
   keeps refusing, even after you switch models. Open a clean session —
   `openclaw tui --session demo` (or `/new` in the TUI). Confirm the model in the
   TUI status bar reads `inference/nvidia/nemotron-3-super-120b-a12b`.

3. **Queries time out → use a fast RAG generation model.** `/query` runs answer
   generation on the host. A *reasoning* model (nemotron-super / nemotron-ultra)
   can emit a long reasoning trace and time out (~150s observed). Set
   `NVIDIA_CHAT_MODEL=meta/llama-3.3-70b-instruct` (fast, non-reasoning) in `.env`
   and restart the RAG server — queries return in ~3s.

### Full environment reset

Use when policy errors are unrecoverable, a sandbox was partially created, or you want a clean slate.

```bash
cd nemoclaw-demos/haystack-rag-demo

# Stop the RAG server
kill $(cat /tmp/haystack-rag.pid) 2>/dev/null || true
kill $(lsof -t -i:9004) 2>/dev/null || true

# Clear global policy (required before sandbox delete / re-onboard)
openshell policy delete --global --yes 2>/dev/null || true

# Delete the sandbox
openshell sandbox delete my-assistant

# Remove host venv and stored index
rm -rf .venv data/store.json

# Re-run from scratch
bash install.sh
```

---

## File Structure

```
haystack-rag-demo/
├── install.sh                          # One-command installer
├── haystack_rag_server.py              # Host-side FastAPI RAG server (port 9004)
├── .env.template                       # Configuration template — copy to .env
├── .env                                # Your local config (not committed)
├── haystack-rag-openclaw-guide.md      # This guide
├── data/
│   ├── documents/                      # ← drop your .txt / .md / .pdf files here
│   └── store.json                      # Auto-created on first index run
├── policy/
│   └── sandbox_policy.yaml             # Network policy — haystack_rag_host on port 9004
└── haystack-rag-skills/
    ├── SKILL.md                        # OpenClaw skill definition
    └── scripts/
        └── haystack_client.py          # HTTP client — calls /index, /query, /documents
```

---

## Implementation Notes

These design decisions are baked into the current scripts. Documented here for anyone adapting the demo.

**OpenClaw PATH after npm install.** On nvm systems, `openclaw` lands in the active node's bin dir, not `~/.local/bin`. `install.sh` uses `_ensure_openclaw_path()` to find it automatically.

**Gateway token location.** The WebUI token is at `.gateway.auth.token` inside `~/.openclaw/openclaw.json`, not the JSON root.

**`NvidiaChatGenerator` parameter name.** Embedders use `api_url=`; the chat generator uses `api_base_url=`. Mixing these up causes silent 500 errors at query time.

**Restart loop under `set -e`.** Background server loops append `|| true` to the Python invocation so a crash triggers restart instead of killing the subshell.

**Skill deployment path.** Raw `openshell sandbox upload` to `.openclaw-data/workspace/skills/` is insufficient on OpenClaw 2026.5+. Use `nemoclaw <sandbox> skill install`, enable the skill in `openclaw.json`, and restart the sandbox OpenClaw gateway. This matches the pattern used in `google-workspace-demo` and `outlook-pst-demo`.

**Policy on live sandboxes.** `sandbox_policy.yaml` contains only `network_policies` (no `filesystem_policy`). Network-only updates work on fresh sandboxes. If a live sandbox rejects the policy update, recreate it via the reset procedure above.

**Global policy conflict.** `nemoclaw onboard` step `[8/8]` fails if a gateway-global policy is active. `install.sh` clears it with `openshell policy delete --global` before onboard.

---

Created by **zcharpy**
