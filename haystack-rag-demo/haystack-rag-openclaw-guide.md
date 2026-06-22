# Haystack RAG with OpenClaw and NVIDIA NIM

This guide walks you through deploying a Retrieval-Augmented Generation (RAG) skill for an OpenClaw agent running inside a NemoClaw OpenShell sandbox. By the end, your agent will be able to index documents (`.txt`, `.md`, `.pdf`), answer natural-language questions grounded in those documents, and list what's currently in its knowledge base — all via NVIDIA NIM for both embeddings and generation.

> **Reference:** For a full introduction to NemoClaw and OpenClaw concepts, see the official quickstart:
> [https://docs.nvidia.com/nemoclaw/latest/user-guide/openclaw/get-started/quickstart](https://docs.nvidia.com/nemoclaw/latest/user-guide/openclaw/get-started/quickstart)

---

## Architecture

The setup has two components:

```
┌─────────────────────────────────────────────────────────────────┐
│  HOST MACHINE (default network namespace)                       │
│                                                                 │
│  haystack_rag_server.py  (FastAPI, 0.0.0.0:9004)               │
│  ├── POST /index     ← embed + store documents via NVIDIA NIM   │
│  ├── POST /query     ← retrieve + generate answer via NVIDIA    │
│  ├── GET  /documents ← list indexed sources                     │
│  └── GET  /health    ← liveness check                           │
│                                                                 │
│  NVIDIA_API_KEY lives here — never enters the sandbox           │
│                                                                 │
│  HOST BRIDGE  172.18.0.1  ← reachable from sandbox namespace   │
│  (OpenShell sandbox bridge gateway — the address the sandbox    │
│   proxy uses to make outbound forwarded connections)            │
└────────────────────────────────┬────────────────────────────────┘
                                 │  HTTP only, port 9004
                                 │  governed by haystack-rag-egress.yaml
                                 │  + host iptables INPUT ACCEPT rule
                                 │  (see Troubleshooting → proxy timeout)
┌────────────────────────────────┴────────────────────────────────┐
│  SANDBOX (OpenShell, Docker bridge 172.18.0.0/16)              │
│                                                                 │
│  haystack-rag-skills/scripts/haystack_client.py                 │
│  └── calls server endpoints (index / query / list-documents)    │
│      via requests through OpenShell proxy at 10.200.0.1:3128   │
│      — zero NVIDIA API calls from sandbox                       │
└─────────────────────────────────────────────────────────────────┘
```

**Why a host-side server instead of running Haystack directly in the sandbox?**
The OpenShell sandbox strips `NVIDIA_API_KEY` from the environment by design — it cannot call `integrate.api.nvidia.com` directly. The host-side `haystack_rag_server.py` holds the key and runs all NVIDIA API calls. The sandbox skill is a thin HTTP client that calls the host server through an egress-approved port. This mirrors how the PST demo uses an MCP server, but uses plain JSON REST instead of MCP.

> **Network note:** The sandbox proxy (`openshell-sandbox`) runs in the Docker bridge network namespace (`172.18.0.0/16`), **not** the host's default network namespace. The host's primary external IP (e.g. `10.0.0.5`) is not routable from this namespace. The correct `HOST_IP` is the bridge gateway `172.18.0.1`. Additionally, a host iptables INPUT rule is required to allow sandbox container traffic to reach the server on port 9004. `install.sh` handles both automatically — see [Troubleshooting → Proxy timeout](#proxy-timeout-read-timed-out-at-10200013128) if you hit this manually.

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
export NEMOCLAW_INSTALL_TAG=v0.0.56
curl -fsSL https://www.nvidia.com/nemoclaw.sh | NEMOCLAW_ACCEPT_THIRD_PARTY_SOFTWARE=1 bash
```

This installs the `nemoclaw` and `openshell` CLIs and sets up the gateway binary. After installation, open a new terminal (or `source ~/.bashrc` / `source ~/.zshrc`) to pick up the updated PATH.

Verify:

```bash
nemoclaw --version    # e.g. nemoclaw v0.0.56
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
16. **Uploads `HEARTBEAT.md`** to `/sandbox/.openclaw/workspace/HEARTBEAT.md` via base64-pipe so the agent gets a periodic health check task and mandatory skill-routing reminder. An empty HEARTBEAT.md (the OpenClaw default) causes the agent to answer Haystack questions from general knowledge instead of running the skill.
17. **Verifies** server health, skill presence, and venv import.

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

> **If the agent answers Haystack questions from general knowledge instead of running the skill**, the `SKILL.md` routing language is not strong enough. The `description` frontmatter field (not just the body) must contain MANDATORY language and exec-ready commands — this is what the routing layer uses to decide whether to invoke the skill. See [Troubleshooting → Agent ignores skill](#agent-answers-from-general-knowledge-instead-of-running-the-skill) for the fix and the base64-pipe workaround for updating SKILL.md in a live sandbox without deleting and re-installing the skill.

> **`openshell sandbox upload` cannot overwrite an existing file at the same path.** If you need to update SKILL.md or HEARTBEAT.md in place, use the base64-pipe method or delete the file first. See [Troubleshooting → Updating SKILL.md in place](#updating-skillmd-or-heartbeatmd-in-a-live-sandbox).

**Command reference:**

```bash
# Index all files in the server's default data directory
python3 haystack_client.py index

# Ask a question (top-k chunks retrieved)
# NOTE: "query" is a subcommand — --question is its argument, not a top-level flag.
# Wrong: python3 haystack_client.py --question "..."
# Right: python3 haystack_client.py query --question "..."
python3 haystack_client.py query --question "What is the main topic?" --top-k 8

# List all indexed sources
python3 haystack_client.py list-documents

# Custom server URL. The default is read from <skill_dir>/server_url.txt, which
# install.sh writes with the host's Docker bridge IP (172.18.0.1), the only host
# address reachable from the sandbox network namespace (not 10.x.x.x).
# Override with --server-url or the RAG_SERVER_URL env var.
python3 haystack_client.py --server-url http://172.18.0.1:9004 query --question "..."
```

> **Common syntax mistake:** `python3 haystack_client.py --question "..."` will fail with "unrecognized arguments". The `--question` flag belongs to the `query` subcommand, not the top-level parser. Always use `query --question "..."`. See [Troubleshooting → Wrong query subcommand syntax](#wrong-query-subcommand-syntax--question-is-not-a-top-level-flag) for details.

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

The `haystack_rag_host` policy block opens outbound HTTP from the sandbox to the
host's Docker bridge gateway on port 9004 only, restricted to specific REST
methods/paths and only from the skill venv's Python binary. `__HOST_IP__` is a
placeholder that install.sh renders to `172.18.0.1` at apply time — **not**
`10.x.x.x` or `host.openshell.internal`. The sandbox proxy runs in the Docker
bridge namespace (`172.18.0.0/16`) and can only reach the bridge gateway:

```yaml
network_policies:
  haystack_rag_host:
    endpoints:
      - host: __HOST_IP__        # rendered to 172.18.0.1 (Docker bridge gateway)
        port: 9004
        protocol: rest
        enforcement: enforce
        rules:
          - allow: { method: GET,  path: "/health" }
          - allow: { method: POST, path: "/query" }
          # ... (full list in policy/haystack-rag-egress.yaml)
    binaries:
      - { path: "/sandbox/.openclaw/workspace/skills/*/venv/bin/python3" }
      - { path: "/sandbox/.openclaw-data/workspace/skills/*/venv/bin/python3" }
      # ... (full list in policy/sandbox_policy.yaml)
```

The preset is applied with the documented command:

```bash
nemoclaw <sandbox> policy-add --from-file ./policy/haystack-rag-egress.yaml
```

> **Important:** The OpenShell egress policy controls what the *sandbox* is allowed to request. It does **not** open the host's TCP port. The host iptables INPUT chain drops traffic from Docker containers by default — even if the OpenShell L7 engine marks the request `ALLOWED`, the TCP SYN is still dropped at the host. A second control is needed: an iptables ACCEPT rule for the Docker bridge network. `install.sh` adds this automatically via `docker run --privileged`. If you apply the policy manually without running the installer, you must also run: `sudo iptables -I INPUT -s 172.18.0.0/16 -p tcp --dport 9004 -j ACCEPT`. See [Troubleshooting → Proxy timeout](#proxy-timeout-read-timed-out-at-10200013128) for the full diagnostic walkthrough.

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

# Use the absolute path — running via a relative path can fail if CWD drifts
python "$(pwd)/haystack_rag_server.py"
```

> **Stale install.sh processes:** If you ran `bash install.sh` multiple times, earlier invocations may still be alive (each has a background `while true` restart loop). Each loop kills the other's server via `lsof -t -i:9004`, causing a crash-restart race. Before restarting manually, kill all stale install.sh processes: `pkill -f "bash.*install.sh"`. See [Troubleshooting → Competing restart loops](#competing-restart-loops-from-stale-installsh-processes) for details.

### Restart via installer (recommended)

Restarts the server, reapplies policy, reinstalls the skill, and refreshes the skill venv:

```bash
# Kill all stale install.sh loops first to avoid process conflicts
pkill -f "bash.*install.sh" 2>/dev/null || true
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
| **`Read timed out (host='10.200.0.1', port=3128)`** — sandbox request hangs 120 s | Host iptables is dropping Docker bridge traffic. Apply: `sudo iptables -I INPUT -s 172.18.0.0/16 -p tcp --dport 9004 -j ACCEPT`. See [Proxy timeout](#proxy-timeout-read-timed-out-at-10200013128) for the full diagnostic. `install.sh` does this automatically. |
| **Server unreachable from sandbox despite policy `ALLOWED`** — `10.x.x.x:9004` not routable | The sandbox proxy runs in the Docker bridge namespace; `10.x.x.x` host IPs are not routable from there. Use `172.18.0.1` as HOST_IP. `install.sh` resolves this automatically; if you applied the policy manually, re-render it with the correct IP. See [Wrong HOST_IP](#wrong-host_ip-host-primary-ip-is-not-routable-from-sandbox-namespace). |
| **Competing restart loops / server crash-loop** after running install.sh twice | Multiple `bash install.sh` processes leave overlapping background restart loops alive. Each kills the other's server. Fix: `pkill -f "bash.*install.sh"` then `bash install.sh`. See [Competing restart loops](#competing-restart-loops-from-stale-installsh-processes). |
| **`error: unrecognized arguments: --question`** from `haystack_client.py` | `--question` belongs to the `query` subcommand, not the top-level parser. Wrong: `haystack_client.py --question "..."`. Right: `haystack_client.py query --question "..."`. See [Wrong query syntax](#wrong-query-subcommand-syntax--question-is-not-a-top-level-flag). |
| **Agent answers Haystack / RAG questions from general knowledge instead of running the skill** | SKILL.md description lacked mandatory-execution language. Re-install the skill with the updated SKILL.md (see [Agent ignores skill](#agent-answers-from-general-knowledge-instead-of-running-the-skill)). |
| **`openshell sandbox upload` fails with "mkdir: cannot create directory ... File exists"** when updating an existing skill file | `upload` cannot overwrite a file that already exists at the destination. Use the base64 workaround to write in place. See [Updating SKILL.md in place](#updating-skillmd-or-heartbeatmd-in-a-live-sandbox). |
| **HEARTBEAT.md is empty** — agent has no periodic reminder to use the skill | Populate `HEARTBEAT.md` in `/sandbox/.openclaw/workspace/` with a health check task and skill-routing reminder, then upload via `openshell sandbox upload`. See [Updating SKILL.md in place](#updating-skillmd-or-heartbeatmd-in-a-live-sandbox). |

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

### Proxy timeout: `Read timed out` at `10.200.0.1:3128`

**Symptom:**

Running any `haystack_client.py` command from the sandbox produces:

```
Unexpected error: HTTPConnectionPool(host='10.200.0.1', port=3128): Read timed out. (read timeout=120)
```

**What `10.200.0.1:3128` is — and why it times out:**

`10.200.0.1:3128` is the OpenShell gateway's HTTP forward proxy inside the sandbox's user network namespace — **not** a corporate proxy. All sandbox HTTP traffic routes through it for L7 policy enforcement. When the sandbox makes a request to `http://172.18.0.1:9004`, the gateway inspects it, marks it `ALLOWED` (if the egress policy permits), and then makes an outbound TCP connection from the Docker bridge network namespace to `172.18.0.1:9004`.

The timeout occurs because the host's iptables INPUT chain drops traffic arriving from Docker container source IPs (`172.18.0.0/16`), even for ports that have a running server. The OpenShell L7 engine allowing the request does **not** open the host's TCP port — these are independent controls. The gateway sends a TCP SYN, the host drops it silently (no RST), and after 120 s the client times out waiting.

**How to confirm it's an iptables issue:**

From the sandbox, hit a port that is definitely policy-denied:

```bash
openshell sandbox exec -n my-assistant -- curl --max-time 5 http://172.18.0.1:9005/
# → immediate: {"error":"policy_denied"}
```

If port 9004 times out while port 9005 is instantly denied, the OpenShell proxy is responding — but the TCP connection to port 9004 is being silently dropped by the host, not by the proxy.

**Fix:**

```bash
# Option 1 — if you have sudo on the host
sudo iptables -I INPUT -s 172.18.0.0/16 -p tcp --dport 9004 -j ACCEPT

# Option 2 — if the ubuntu user is in the docker group (no sudo needed)
docker run --rm --privileged --network host alpine sh -c \
  "apk add --quiet iptables && iptables -I INPUT -s 172.18.0.0/16 -p tcp --dport 9004 -j ACCEPT"
```

Verify from the sandbox:

```bash
openshell sandbox exec -n my-assistant -- curl -s --max-time 10 http://172.18.0.1:9004/health
# → {"status":"ok","indexed_chunks":0,...}
```

`install.sh` adds this iptables rule automatically (via the `docker run --privileged` method) so you normally never hit this manually. If you applied only the egress policy without running the installer, this is the missing step.

---

### Wrong HOST_IP: host primary IP is not routable from sandbox namespace

**Symptom:**

After `install.sh`, the `server_url.txt` file contains something like `http://10.0.0.5:9004` and sandbox requests either time out or return connection errors, even with a valid policy.

**Root cause:**

The openshell-sandbox proxy process runs in a Docker bridge network namespace (`172.18.0.0/16`). When it makes outbound connections (forwarding sandbox requests), it uses that namespace's routing table — not the host's default routing table.

The host's primary external IP (e.g. `10.0.0.5`, resolved by `ip route get 1.1.1.1`) is typically only routable from the host's default namespace. From inside the Docker bridge namespace, the only reachable host address is the bridge gateway: `172.18.0.1`.

**Fix:**

`install.sh` resolves `172.18.0.1` first by attempting to bind a socket to it. If you applied the policy manually with the wrong IP, re-render and re-apply it:

```bash
# Confirm 172.18.0.1 is live on this host
ip addr show | grep 172.18.0.1

# Update server_url.txt in the sandbox
echo "http://172.18.0.1:9004" | openshell sandbox exec -n my-assistant -- \
  tee /sandbox/.openclaw/workspace/skills/haystack-rag-skills/server_url.txt

# Re-apply the egress policy with the correct IP
HOST_IP=172.18.0.1 RAG_PORT=9004
sed "s/__HOST_IP__/$HOST_IP/g; s/__RAG_PORT__/$RAG_PORT/g" \
  policy/haystack-rag-egress.yaml > /tmp/haystack-rag-egress-rendered.yaml
nemoclaw my-assistant policy-add --from-file /tmp/haystack-rag-egress-rendered.yaml
```

Or simply re-run `install.sh` — it re-resolves the correct IP and re-applies everything.

---

### Competing restart loops from stale `install.sh` processes

**Symptom:**

After running `bash install.sh` a second time (or after killing and restarting it), the RAG server enters a rapid crash loop. Logs (`/tmp/haystack-rag.log`) show:

```
python: can't open file 'haystack_rag_server.py': [Errno 2] No such file or directory
[haystack-rag] Server exited, restarting in 2s...
[haystack-rag] Server exited, restarting in 2s...
```

**Root cause:**

`install.sh` spawns a background `while true` restart loop for the server. If you run `install.sh` again without killing the previous instance, two overlapping loops exist simultaneously. Each loop's first action is `kill $(lsof -t -i:9004)` — which kills the server the *other* loop just started. The two loops race to kill and restart the server indefinitely.

Additionally, if the CWD inside the subshell drifts (e.g. because a subshell `cd` failed or was missing), the relative path `python haystack_rag_server.py` fails with "No such file or directory".

**Fix:**

Kill all stale install.sh processes before restarting:

```bash
# Kill all background install.sh restart loops
pkill -f "bash.*install.sh" 2>/dev/null || true
# Also clear the port
kill $(lsof -t -i:9004) 2>/dev/null || true
# Then reinstall fresh
bash install.sh my-assistant
```

The absolute path fix (`python "$SCRIPT_DIR/haystack_rag_server.py"`) in the restart loop ensures the server can be started from any CWD — this is already baked into `install.sh`.

---

### Wrong query subcommand syntax: `--question` is not a top-level flag

**Symptom:**

Running either of these commands fails:

```bash
# Wrong 1 — --question before the subcommand
python3 haystack_client.py --question "what is haystack"
# error: unrecognized arguments: --question

# Wrong 2 — using --query instead of --question
python3 haystack_client.py query --query "what is haystack"
# error: unrecognized arguments: --query
```

**Root cause:**

`haystack_client.py` uses an argparse subcommand structure. `query` is a subcommand, and `--question` is an argument specific to that subcommand. Placing `--question` before `query` gives it to the top-level parser (which doesn't know the flag). `--query` was a SKILL.md typo that has since been corrected to `--question`.

**Correct syntax:**

```bash
# Resolve SKILL_DIR first
for _c in /sandbox/.openclaw/workspace/skills/haystack-rag-skills \
           /sandbox/.openclaw-data/workspace/skills/haystack-rag-skills \
           "$HOME/.openclaw/workspace/skills/haystack-rag-skills"; do
  [ -d "$_c" ] && SKILL_DIR="$_c" && break
done

# The subcommand comes first, then its flag
$SKILL_DIR/venv/bin/python3 $SKILL_DIR/scripts/haystack_client.py query --question "what is haystack"
```

**Quick reference — all valid subcommands:**

```bash
python3 haystack_client.py health
python3 haystack_client.py setup
python3 haystack_client.py index
python3 haystack_client.py query --question "YOUR QUESTION" [--top-k 5]
python3 haystack_client.py list-documents
```

---

### Agent answers from general knowledge instead of running the skill

**Symptom:**

The OpenClaw TUI agent responds to Haystack/RAG queries from its training data instead of executing `haystack_client.py`. For example:

- `"tell me what is haystack"` → agent writes a paragraph from general knowledge; skill never runs
- `"index document for me"` → agent replies "I'm not sure what you mean by 'index document'"
- `"could you use the haystack-rag-skills you have..."` → agent describes the skill but never executes a command

**Root cause:**

The `description` field in `SKILL.md` frontmatter is the first (and often only) thing the agent reads when deciding whether and how to invoke a skill. If the description is polite and descriptive ("Answers questions about Haystack..."), the agent treats it as optional context and falls back to general knowledge. The body of SKILL.md is only read when the agent has already decided to invoke — so hard rules in the body don't help if the routing decision was wrong.

The original SKILL.md description listed trigger topics but used no mandatory language. The agent saw "triggers on questions about haystack" as a hint, not a command.

**Fix:**

The SKILL.md description must include the word MANDATORY, copy-paste exec-ready commands, and explicit ANTI-PATTERNS in the description frontmatter itself — not just in the body. This mirrors the pattern used in the flight-tracking skill.

Re-install the updated skill (which already uses this pattern):

```bash
# From the demo directory on the host
nemoclaw my-assistant skill install ~/nemoclaw-demos/haystack-rag-demo/haystack-rag-skills
```

Then force-write the new SKILL.md directly into the sandbox (see below — `nemoclaw skill install` may not overwrite an existing file in place):

```bash
B64=$(base64 -w0 ~/nemoclaw-demos/haystack-rag-demo/haystack-rag-skills/SKILL.md)
openshell sandbox exec -n my-assistant -- bash -c "echo '${B64}' | base64 -d > /sandbox/.openclaw/workspace/skills/haystack-rag-skills/SKILL.md && wc -l /sandbox/.openclaw/workspace/skills/haystack-rag-skills/SKILL.md"
```

Also populate `HEARTBEAT.md` so the agent gets a periodic skill-routing reminder (see below). Then reconnect the TUI: `exit` → `nemoclaw my-assistant connect` → `openclaw tui`.

**Signs the fix worked:**

After reconnecting and asking "tell me what is haystack", the agent should immediately run `health` (and `setup` if needed) then `query --question "what is haystack"` via the bash tool, and reply with the RAG-grounded answer citing `sample.txt`.

---

### Updating SKILL.md or HEARTBEAT.md in a live sandbox

**Symptom:**

After running `nemoclaw skill install`, the old SKILL.md is still in the sandbox (verified with `grep`). Or `openshell sandbox upload` fails:

```
mkdir: cannot create directory '.../SKILL.md': File exists
Error: × ssh tar extract exited with status exit status: 1
```

**Root cause:**

`nemoclaw skill install` uploads the skill files but may not overwrite files that already exist at the destination path on a live sandbox — it depends on the tar extraction mode. `openshell sandbox upload` with a file destination also fails when the destination path already exists as a file (it tries to `mkdir` the destination).

**Fix 1 — base64 pipe (works for any text file, no sudo needed):**

```bash
# Write SKILL.md
B64=$(base64 -w0 ~/nemoclaw-demos/haystack-rag-demo/haystack-rag-skills/SKILL.md)
openshell sandbox exec -n my-assistant -- bash -c \
  "echo '${B64}' | base64 -d > /sandbox/.openclaw/workspace/skills/haystack-rag-skills/SKILL.md \
   && wc -l /sandbox/.openclaw/workspace/skills/haystack-rag-skills/SKILL.md"
```

```bash
# Write HEARTBEAT.md (workspace-level, not skill-level)
B64=$(base64 -w0 /tmp/HEARTBEAT.md)
openshell sandbox exec -n my-assistant -- bash -c \
  "echo '${B64}' | base64 -d > /sandbox/.openclaw/workspace/HEARTBEAT.md"
```

**Fix 2 — upload to a temp path then move:**

```bash
openshell sandbox upload my-assistant /tmp/HEARTBEAT.md /tmp/HEARTBEAT_new.md
openshell sandbox exec -n my-assistant -- mv /tmp/HEARTBEAT_new.md /sandbox/.openclaw/workspace/HEARTBEAT.md
```

**Fix 3 — delete the skill and reinstall:**

```bash
openshell sandbox exec -n my-assistant -- rm -rf /sandbox/.openclaw/workspace/skills/haystack-rag-skills
nemoclaw my-assistant skill install ~/nemoclaw-demos/haystack-rag-demo/haystack-rag-skills
```

After any of these, restart the OpenClaw gateway and reconnect the TUI:

```bash
openshell sandbox exec -n my-assistant -- openclaw gateway restart
# then reconnect:
nemoclaw my-assistant connect
```

---

## File Structure

```
haystack-rag-demo/
├── install.sh                          # One-command installer
├── haystack_rag_server.py              # Host-side FastAPI RAG server (port 9004)
├── HEARTBEAT.md                        # Uploaded to sandbox workspace — periodic health check
├── .env.template                       # Configuration template — copy to .env
├── .env                                # Your local config (not committed)
├── haystack-rag-openclaw-guide.md      # This guide
├── data/
│   ├── documents/                      # ← drop your .txt / .md / .pdf files here
│   └── store.json                      # Auto-created on first index run
├── policy/
│   └── sandbox_policy.yaml             # Network policy — haystack_rag_host on port 9004
└── haystack-rag-skills/
    ├── SKILL.md                        # OpenClaw skill definition (mandatory-execution language)
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
