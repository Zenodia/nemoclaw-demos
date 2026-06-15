# Enterprise n8n Workflow — OpenClaw Guide

Run an enterprise n8n workflow from inside a NemoClaw sandbox via OpenClaw chat. The agent picks the **EnterpriseOrchestrator** workflow, triggers it with a natural-language task (e.g. _"inference pod cluster-3 is down, restore service"_), and returns the consolidated result — a guardrailed execution plan. Chat/agent workflows are triggered through their n8n **webhook** (synchronous, `responseMode=lastNode`) so the reply comes back in a single call — no polling required.

```
sandbox skill venv  ──►  host:4300 (n8n_mcp_server.py wrapper)  ──►  n8n instance /mcp-server/http
                                                                     (self-hosted ./n8n_selfhost on :5678,
                                                                      or a remote enterprise n8n)
```

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Environment Setup](#2-environment-setup)
3. [Bring up the self-hosted n8n (first!)](#3-bring-up-the-self-hosted-n8n-first)
4. [One-Command Install (OpenClaw + MCP)](#4-one-command-install-openclaw--mcp)
5. [Full Workflow via OpenClaw Chat](#5-full-workflow-via-openclaw-chat)
6. [Skill Tool Reference (CLI)](#6-skill-tool-reference-cli)
7. [Daily Operations](#7-daily-operations)
8. [Architecture](#8-architecture)
9. [Troubleshooting](#9-troubleshooting)

---

## 1. Prerequisites

| Requirement | Check |
|---|---|
| `python3` 3.10+ | `python3 --version` (host only) |
| `curl` | `curl --version` |
| `INFERENCE_API_KEY` | **Required** — OpenShell gateway inference credential + driven into `nemoclaw onboard` |
| `N8N_INSTANCE_URL` / `N8N_MCP_TOKEN` | **Required** — credentials for the remote enterprise n8n MCP endpoint |
| NemoClaw / OpenShell CLI | `openshell --version`, `nemoclaw --version` |
| `uv` | Auto-installed by `install.sh` if missing |
| Docker | Only needed for the `openshell-cluster-*` container that hosts the sandbox; the n8n demo does not run any local Docker stack of its own |

No GPU. No local RAG stack. No browser upload portal.

---

## 2. Environment Setup

Create a `.env` file in the repo root (`enterprise_n8n_workflow/.env`):

```bash
# --- n8n MCP wrapper (host:4300) → points at the n8n instance ---
# Self-hosted (bundled in ./n8n_selfhost, default for this demo):
N8N_INSTANCE_URL=http://localhost:5678/mcp-server/http
N8N_MCP_TOKEN=<your-n8n-api-key>
# Or a remote enterprise n8n instead:
# N8N_INSTANCE_URL=https://n8n.prd.astra.nvidia.com/mcp-server/http

# --- Inference (OpenShell gateway provider + nemoclaw onboard) ---
INFERENCE_API_KEY=nvapi-...
INFERENCE_BASE_URL=https://inference-api.nvidia.com/v1
INFERENCE_MODEL=aws/anthropic/bedrock-claude-sonnet-4-6

# Optional — defaults to nvidia/nvidia
# INFERENCE_PROVIDER_TYPE=nvidia
# INFERENCE_PROVIDER_NAME=nvidia
```

All five core variables are required. `install.sh` fails fast if any are missing.

> **Using the bundled self-hosted n8n?** Set `N8N_INSTANCE_URL=http://localhost:5678/mcp-server/http`
> and bring n8n up **first** — see [Section 3](#3-bring-up-the-self-hosted-n8n-first).
> `N8N_MCP_TOKEN` is an n8n API key you create in that instance (Settings → API).

> **`INFERENCE_API_KEY` / `INFERENCE_BASE_URL` / `INFERENCE_MODEL`** drive `nemoclaw onboard` non-interactively (no clicking through provider/model pickers). The script picks the `custom` (OpenAI-compatible) provider, points it at `INFERENCE_BASE_URL`, and passes `INFERENCE_API_KEY` as `COMPATIBLE_API_KEY`. The OpenShell gateway provider is then created (or updated) with `--credential INFERENCE_API_KEY` and `--config NVIDIA_BASE_URL=$INFERENCE_BASE_URL`, and `openclaw.json` inside the sandbox is patched to make `inference/$INFERENCE_MODEL` the agent's primary model.

> **`N8N_INSTANCE_URL` / `N8N_MCP_TOKEN`** are read by `n8n_mcp_server.py` (the host wrapper) — never sent to the sandbox.

---

## 3. Bring up the self-hosted n8n (first!)

The host wrapper (`n8n_mcp_server.py`) connects to `N8N_INSTANCE_URL`. When that's
the bundled self-hosted n8n (`http://localhost:5678/...`), **n8n must already be
running and reachable before `install.sh` Step 5 starts the wrapper** — otherwise
the wrapper comes up but every tool call fails to reach n8n.

Order: **self-hosted n8n up → then `install.sh`**.

```bash
cd n8n_selfhost

# 1. Start n8n (Docker volume + container on :5678)
bash 0_build_and_run_docker.sh

# 2. Import the EnterpriseOrchestrator + 3 sub-workflows
#    ⚠ Import always deactivates workflows — publish them AFTER import (step 3).
docker cp workflows-export.json n8n:/home/node/.n8n/
docker exec n8n n8n import:workflow --input=/home/node/.n8n/workflows-export.json

# 3. Publish all 4 workflows, THEN restart
#    (n8n 2.22+: use publish:workflow — update:workflow is deprecated)
#    Full walkthrough — credentials, model, activation, verify:
#    see n8n_selfhost/preserving_n8n_workflow_for_reuse_steps.md
for id in TzLcGZKuV0TZxXHs 8eFCKIE4qlfhMna0 mAPFaEvgygizLfaY XPYjIUowrNmN5aUj; do
  docker exec n8n n8n publish:workflow --id=$id
done
docker restart n8n
# Confirm all 4 register at boot:
docker logs n8n --since 30s 2>&1 | grep -A5 'Start Active Workflows'

# 4. Sign in at http://localhost:5678 and create an n8n API key
#    (Settings → n8n API) → put it in .env as N8N_MCP_TOKEN.
#    See "Sign in to n8n" below if you don't know the email/password.

# 5. Confirm n8n + webhook are live
curl -s -o /dev/null -w "%{http_code}\n" -X POST http://localhost:5678/webhook/agent-hub \
  -H "Content-Type: application/json" -d '{"chatInput":"ping"}'   # 200 = ready
cd ..
```

### Sign in to n8n (owner account)

The **Email / Password** screen at http://localhost:5678 is n8n's **owner account**
(user management). It is **not** the `admin` / `changeme` values in
`0_build_and_run_docker.sh` — those env vars (`N8N_BASIC_AUTH_*`) configure an
optional HTTP Basic Auth layer and do not populate the UI sign-in form.

On first start, n8n prompts you to create an owner (email + password). That
account lives in the persistent Docker volume `n8n_data`, so re-running
`0_build_and_run_docker.sh` on the same machine keeps the same login.

**Forgot the password?** Reset the owner account (workflows and credentials are
kept; only the login user is cleared):

```bash
docker exec n8n n8n user-management:reset
docker restart n8n
```

Open http://localhost:5678 again — you'll get the first-time owner setup to pick a
new email and password.

**Look up the current owner email** (password is hashed — it cannot be read back):

```bash
docker cp n8n:/home/node/.n8n/database.sqlite /tmp/n8n-db.sqlite
python3 -c "import sqlite3; c=sqlite3.connect('/tmp/n8n-db.sqlite'); print(list(c.execute('SELECT email FROM user')))"
```

**Full wipe** (new n8n with no prior data — you'll re-import workflows):

```bash
docker stop n8n && docker rm n8n
docker volume rm n8n_data
bash 0_build_and_run_docker.sh
# then repeat steps 2–5 above
```

> Full detail (bring-your-own-key, model field, activation order, troubleshooting)
> lives in **[`n8n_selfhost/preserving_n8n_workflow_for_reuse_steps.md`](n8n_selfhost/preserving_n8n_workflow_for_reuse_steps.md)**.
> Using a remote enterprise n8n instead? Skip this section and point
> `N8N_INSTANCE_URL` at it.

---

## 4. One-Command Install (OpenClaw + MCP)

With the n8n instance up ([Section 3](#3-bring-up-the-self-hosted-n8n-first)) and
`.env` populated, run:

```bash
bash install.sh [sandbox-name]
```

### Arguments

| Arg | Description |
|---|---|
| *(none)* | Auto-detect sandbox; if none exists, run `nemoclaw onboard` non-interactively using INFERENCE_* from `.env` |
| `sandbox-name` | Positional — target a specific sandbox; skips auto-detect |

### Environment variable overrides

| Variable | Default | Purpose |
|---|---|---|
| `N8N_MCP_PORT` | `4300` | Host wrapper listen port |
| `N8N_MCP_HOST` | `127.0.0.1` | Wrapper bind host |
| `N8N_MCP_PATH` | `/mcp` | URL path |
| `N8N_POLL_INTERVAL_SEC` | `3` | `execute_workflow` poll cadence |
| `N8N_POLL_TIMEOUT_SEC` | `600` | `execute_workflow` hard cap |
| `INFERENCE_PROVIDER_TYPE` | `nvidia` | OpenShell provider type |
| `INFERENCE_PROVIDER_NAME` | `nvidia` | OpenShell provider name |

**What `install.sh` does (idempotent — safe to re-run):**

| Step | Action | Skip condition |
|---|---|---|
| 0 | Kill stale wrapper (`/tmp/n8n-mcp.pid` + `pgrep n8n_mcp_server`) | — |
| 1 | Verify python3, curl, openshell, uv (auto-install uv if missing) | fails fast if other prereqs missing |
| 2 | Load `.env`, validate all 5 required keys | fails fast if any missing |
| 3 | Host venv at `.venv` + `pip install -r requirements.txt` | reuses existing `.venv` |
| 4 | Detect sandbox; if none, run `nemoclaw onboard --non-interactive` with `NEMOCLAW_PROVIDER=custom`, `NEMOCLAW_ENDPOINT_URL=$INFERENCE_BASE_URL`, `NEMOCLAW_MODEL=$INFERENCE_MODEL`, `COMPATIBLE_API_KEY=$INFERENCE_API_KEY` | skipped if sandbox exists |
| 4b | `openshell provider create/update` + `openshell inference set` | provider update/create idempotent |
| 4c | Patch `/sandbox/.openclaw/openclaw.json` inside sandbox → set `inference/$INFERENCE_MODEL` as primary | always re-applied |
| 5 | Start `n8n_mcp_server.py` on `127.0.0.1:4300/mcp` (background, auto-restart, logs `/tmp/n8n-mcp.log`). **Requires the n8n instance from [Section 3](#3-bring-up-the-self-hosted-n8n-first) to be reachable at `N8N_INSTANCE_URL`.** | skipped if port responding |
| 6 | Apply `policy/sandbox_policy.yaml` (skill venv → port 4300) | always re-applied |
| 7 | Upload `n8n_workflow_skills/` → `/sandbox/.openclaw/workspace/skills/n8n-workflow-skills` + HEARTBEAT to workspace root | always re-uploaded |
| 8 | Write `config.json` with server_url + polling tunables | always re-written |
| 9 | Bootstrap sandbox skill venv + `pip install fastmcp` | reuses existing venv |
| 10 | End-to-end verify — run `n8n_health` (assert `"status": "ok"`) **and** `list_workflows` (read-only) from the sandbox | — |

Expected final output:

```
✓ Skill end-to-end: n8n_health → status ok
  ╔══════════════════════════════════════════════════════════╗
  ║  Installation complete!                                  ║
  ╚══════════════════════════════════════════════════════════╝
```

---

## 5. Full Workflow via OpenClaw Chat

Connect to the sandbox:

```bash
nemoclaw <sandbox-name> connect
```

`HEARTBEAT.md` is loaded at session start — the agent already knows the routing table. No further setup needed.

**Step 4 — Open the OpenClaw UI (optional)**

`install.sh` Step 4d auto-runs `scripts/start_oc_gateway.sh` inside the sandbox. That script:

1. Persists a random hex token into `/sandbox/.openclaw/openclaw.json` under `gateway.auth.token` (uses `scripts/set_oc_token.py`).
2. Starts the gateway detached on `127.0.0.1:18789` so it picks up the token from the config file on next start.
3. Writes `/tmp/oc-token.env` (sourceable: `TOKEN=<hex>`) and tails the log to confirm "GATEWAY_UP".

`install.sh` then reads the token back and prints the final URL at the end of the run:

```
── OpenClaw chat UI ──────────────────────────────────────
Browser URL  : http://127.0.0.1:18789/#token=<HEX>
TUI env      : export OPENCLAW_GATEWAY_TOKEN=<HEX>
               openclaw tui      (inside sandbox)
```

Save it — the same token survives across `openclaw gateway` restarts because it lives in the config file.

> **Why not the old grep trick?** The TA-demo snippet
> `grep -o '"token"\s*:\s*"[^"]*"' ~/.openclaw/openclaw.json` ran against a file
> where `gateway.auth.token` was an empty string immediately after onboarding
> (`nemoclaw onboard` no longer auto-populates it in OpenClaw 2026.5.22+). It
> returned an empty token, and any TUI/UI connect attempt failed with
> `unauthorized: gateway token mismatch`. The `set_oc_token.py` helper writes a
> real value before the gateway starts so both the TUI (via
> `OPENCLAW_GATEWAY_TOKEN` env) and the dashboard URL (`#token=…`) authenticate
> against the same value.

### Manual re-run (after a sandbox reboot / fresh shell)

If you need to restart the gateway without re-running `install.sh`:

```bash
openshell sandbox connect <sandbox>
# inside sandbox:
sh /tmp/start_oc_gateway.sh             # reuse existing token
sh /tmp/start_oc_gateway.sh --rotate    # generate a fresh token
```

The script prints the token and the final URL on stdout. Then:

```bash
export OPENCLAW_GATEWAY_TOKEN=$(. /tmp/oc-token.env && echo "$TOKEN")
openclaw tui
```

### Forwarding port 18789 to your laptop

If the sandbox host is a brev cloud instance, forward port 18789 in two hops:

```bash
# host (already done by install.sh Step 4d, but safe to re-run):
openshell forward start 18789 <sandbox>

# laptop (WSL terminal):
brev port-forward <instance> -p 18789:18789
# or via SSH:
# ssh -L 18789:127.0.0.1:18789 <user>@<brev-host>
```

Then open the Browser URL printed by `install.sh` in your laptop browser.

---


### Sample queries to try

The **EnterpriseOrchestrator** runs every task through
`policy_guard → task_router → cost_gate → execution plan`. Paste any of these into
the OpenClaw chat (the agent calls `list_workflows` then `execute_workflow`):

**Incident Response** — routed `incident`, high/critical priority:
```
ALERT: inference pod cluster-3 is down and failing health checks, restore service immediately
inference latency spiked to 45 seconds on A100-cluster-01, investigate and remediate
GPU memory overflow detected on worker node 7, prevent cascading failure
```

**Finance / Budget** — routed `finance`, checked against the daily budget:
```
Review current GPU spend against Q2 budget and flag any overage
Generate a cost breakdown report for all active Nemotron inference jobs this month
Forecast AI Factory compute costs for next quarter based on current utilization trends
```

**Policy Violation** — `policy_guard` should **block** these (no plan returned):
```
delete_all checkpoints from training cluster to free up storage
override_budget limit for this sprint to run extra fine-tuning jobs
disable_guardrails on the privacy router for faster inference
```

### What a run looks like

```
You:   what n8n workflows can I run?
Agent: [calls list_workflows]
       - EnterpriseOrchestrator (id=TzLcGZKuV0TZxXHs) — runs policy_guard → task_router → cost_gate → plan

You:   ALERT: inference pod cluster-3 is down and failing health checks, restore service immediately
Agent: [calls execute_workflow --workflow-id TzLcGZKuV0TZxXHs --query "<the alert>"]
       ✅ Guardrails passed:
         • policy_guard → allowed
         • task_router  → category=incident, priority=critical
         • cost_gate    → approved ($10 of $100 daily budget)
       Execution plan: { phase_1_triage, phase_2_remediation, ... }

You:   disable_guardrails on the privacy router for faster inference
Agent: [calls execute_workflow with that query]
       🚫 policy_guard DENIED — action matches a restricted policy pattern. No plan produced.
```

> The guardrail thresholds (blocked patterns, $100 daily budget, category/priority
> rules) live in the 3 sub-workflows' JavaScript Code nodes — tune them there.

### Hard rules baked into HEARTBEAT.md

- Agent never invents a workflow id. Always `list_workflows` first.
- `execute_workflow` returns the workflow's final output synchronously (the wrapper POSTs the n8n webhook; no polling).
- If `list_workflows` returns empty: user lacks `workflow:execute` permission in n8n, or workflows missing "Available in MCP" toggle. Suggest contacting a project admin.

---

## 6. Skill Tool Reference (CLI)

`SKILL=$SKILL_DIR/venv/bin/python3 $SKILL_DIR/scripts/n8n_client.py` where `SKILL_DIR=/sandbox/.openclaw/workspace/skills/n8n-workflow-skills`.

| Tool | When to use |
|---|---|
| `list_workflows` | User asks what's available; agent needs a workflow id |
| `describe_workflow --workflow-id <id>` (or `--name "..."`) | User asks "what does this workflow do?" |
| `execute_workflow --workflow-id <id> --query "..."` | User picked a workflow + supplied a query |
| `get_execution --workflow-id <id> --execution-id <eid>` | Inspect a specific run without re-triggering |
| `list_n8n_tools` | Discover what the remote n8n MCP exposes |
| `call_n8n_tool --name X --arguments '<json>'` | Generic passthrough to any remote n8n tool |
| `n8n_health` | Verify remote n8n endpoint reachable |

Full reference: [`n8n_workflow_skills/SKILL.md`](n8n_workflow_skills/SKILL.md).

### Calling directly from the sandbox shell

```bash
SKILL_DIR=/sandbox/.openclaw/workspace/skills/n8n-workflow-skills
SKILL="$SKILL_DIR/venv/bin/python3 $SKILL_DIR/scripts/n8n_client.py"

$SKILL n8n_health
$SKILL list_workflows
$SKILL describe_workflow --workflow-id TzLcGZKuV0TZxXHs
$SKILL execute_workflow --workflow-id TzLcGZKuV0TZxXHs \
  --query "inference pod cluster-3 is down and failing health checks, restore service immediately"
```

---

## 7. Daily Operations

```bash
# If the wrapper runs as a systemd service (reboot-durable, auto-restart):
sudo systemctl restart n8n-mcp-wrapper     # after editing n8n_mcp_server.py
sudo systemctl status  n8n-mcp-wrapper
journalctl -u n8n-mcp-wrapper -f           # logs
# Unit: /etc/systemd/system/n8n-mcp-wrapper.service  (User=ubuntu, EnvironmentFile=.env)

# Otherwise (install.sh background launch):
# Restart MCP wrapper after editing n8n_mcp_server.py
kill $(cat /tmp/n8n-mcp.pid) && bash install.sh <sandbox-name>

# Tail wrapper logs
tail -f /tmp/n8n-mcp.log

# Re-upload skill after editing source
bash install.sh <sandbox-name>     # idempotent; re-uploads + re-applies policy + re-writes config

# Update polling tunables
openshell sandbox exec -n <sandbox> -- \
  /sandbox/.openclaw/workspace/skills/n8n-workflow-skills/venv/bin/python3 \
  /sandbox/.openclaw/workspace/skills/n8n-workflow-skills/scripts/setup_config.py \
  --poll-interval 5 --poll-timeout 900

# Standalone host-side picker (no sandbox)
source .venv/bin/activate
python3 n8n_mcp_client.py          # interactive prompt: pick workflow → enter query → wait
```

### Manual MCP wrapper start (without install.sh)

```bash
source .venv/bin/activate
python3 n8n_mcp_server.py --host 127.0.0.1 --port 4300 --path /mcp
```

---

## 8. Architecture

```
User (OpenClaw chat in NemoClaw sandbox)
     │  agent picks tool from HEARTBEAT.md routing table
     ▼
Skill CLI: n8n_client.py  (sandbox skill venv, port allowed by policy)
     │  fastmcp.Client → StreamableHttpTransport
     ▼
Host wrapper: n8n_mcp_server.py  (FastMCP, port 4300)
     │  meta-tools:    list_n8n_tools / call_n8n_tool / n8n_health
     │  webhook tool:  execute_chat_workflow  (POSTs the workflow webhook directly)
     │  reads N8N_INSTANCE_URL + N8N_MCP_TOKEN from .env
     ├──► n8n MCP API: $N8N_INSTANCE_URL  (e.g. http://localhost:5678/mcp-server/http)
     │       exposes search_workflows / get_workflow_details / execute_workflow / get_execution / ...
     │       (used for discovery: list_workflows, describe_workflow, webhook-path resolution)
     └──► n8n webhook: http://localhost:5678/webhook/<path>
             POST {"chatInput": "..."} → runs the orchestrator → returns final output
     ▼
n8n engine  (self-hosted ./n8n_selfhost on :5678, or a remote enterprise n8n)
     │  EnterpriseOrchestrator AI Agent → policy_guard / task_router / cost_gate sub-workflows
```

> **Why a webhook for execution?** The n8n MCP `execute_workflow` tool does
> **not** inject `chatInput` into webhook-triggered workflows — the webhook node
> fires with an empty body, so the AI Agent gets an empty prompt (`No prompt
> specified`). The wrapper's `execute_chat_workflow` resolves the workflow's
> webhook path (via `get_workflow_details`) and `POST`s `{"chatInput": …}` to it
> directly, returning the final node output synchronously. Discovery
> (`search_workflows` / `get_workflow_details`) still goes through the n8n MCP.

### Key files

| File | Purpose |
|---|---|
| `n8n_selfhost/` | Bundled self-hosted n8n: build script, workflow export, sanitized cred template + redeploy guide (start this first — [Section 3](#3-bring-up-the-self-hosted-n8n-first)) |
| `install.sh` | One-command installer (10 steps, idempotent) |
| `n8n_mcp_server.py` | Host FastMCP wrapper (port 4300) — 3 meta-tools + `execute_chat_workflow` (webhook POST) |
| `n8n_mcp_client.py` | Standalone host-side interactive CLI (workflow picker → query → wait) |
| `requirements.txt` | Host venv deps (fastmcp, httpx, python-dotenv, colorama) |
| `policy/sandbox_policy.yaml` | OpenShell network policy — opens port 4300 to skill venv binaries |
| `n8n_workflow_skills/SKILL.md` | Full tool reference for the agent (loaded on skill activation) |
| `n8n_workflow_skills/HEARTBEAT.md` | Routing rules injected at session start |
| `n8n_workflow_skills/config.json.example` | Template for skill config |
| `n8n_workflow_skills/scripts/setup_config.py` | Interactive + `--non-interactive` config writer |
| `n8n_workflow_skills/scripts/n8n_client.py` | The CLI the agent invokes — 7 tools |

### Tool composition

The host wrapper exposes 3 thin meta-tools (`list_n8n_tools`, `call_n8n_tool`, `n8n_health`) plus 1 webhook tool (`execute_chat_workflow`). The skill CLI composes them into higher-level operations:

| Skill CLI tool | Wrapper calls used |
|---|---|
| `list_workflows` | `call_n8n_tool("search_workflows", {limit})` → filter `canExecute && availableInMCP && active` |
| `describe_workflow` | `call_n8n_tool("get_workflow_details", {workflowId})` with `search_workflows` fallback |
| `execute_workflow` | `execute_chat_workflow({workflow_id, chat_input})` — wrapper resolves the webhook path and POSTs `{"chatInput": …}` synchronously (no polling) |
| `get_execution` | `call_n8n_tool("get_execution", {...})` |
| `list_n8n_tools` | direct |
| `call_n8n_tool` | direct |
| `n8n_health` | direct |

> `--poll-interval` / `--poll-timeout` are still accepted on `execute_workflow` for backward compatibility but are no-ops on the synchronous webhook path; the wrapper's own HTTP timeout (600s) bounds the call.

---

## 9. Troubleshooting

**Self-hosted n8n — sign-in page asks for email/password I don't know**

The UI login is the **owner account** stored in the `n8n_data` Docker volume, not
`admin` / `changeme` from `0_build_and_run_docker.sh`. See
[Sign in to n8n](#sign-in-to-n8n-owner-account) — run `user-management:reset` to
create a fresh owner, or query the DB for the current email.

**Self-hosted n8n — webhook returns `404` (`unknown webhook "POST agent-hub"`)**

The orchestrator webhook is only registered when **EnterpriseOrchestrator** is
**published and active**. Common causes:

1. **Import after activate** — `import:workflow` deactivates all workflows. Always
   import first, then publish, then restart.
2. **Restart without publish** — after import, run `publish:workflow` on all four
   IDs before `docker restart n8n`.

```bash
for id in TzLcGZKuV0TZxXHs 8eFCKIE4qlfhMna0 mAPFaEvgygizLfaY XPYjIUowrNmN5aUj; do
  docker exec n8n n8n publish:workflow --id=$id
done
docker restart n8n
docker logs n8n --since 30s 2>&1 | grep 'Activated workflow'   # expect 4 lines
curl -s -o /dev/null -w "%{http_code}\n" -X POST http://localhost:5678/webhook/agent-hub \
  -H "Content-Type: application/json" -d '{"chatInput":"ping"}'   # 200 = ready
```

**Skill returns "Name or service not known" pointing at `n8n.prd.astra.nvidia.com`** *(remote-n8n only — N/A when using the bundled self-host on `localhost:5678`)*

The wrapper itself is healthy; it just can't resolve the NVIDIA-internal hostname. Verify on the host:

```bash
getent hosts n8n.prd.astra.nvidia.com
# empty → NXDOMAIN
```

`*.astra.nvidia.com` is gated behind NVIDIA VPN / corp DNS. From a brev cloud box you need either:

- a VPN tunnel to the NVIDIA corp network (split DNS will then resolve the host), or
- an SSH stunnel from a VPN-connected machine. Example (pick any free host port — `4301` shown here is illustrative, NOT the MCP wrapper port, NOT in `sandbox_policy.yaml`): `ssh -L 4301:n8n.prd.astra.nvidia.com:443 <vpn-host>` and override `N8N_INSTANCE_URL=https://localhost:4301/mcp-server/http` in `.env`, then restart the wrapper. TLS SNI will be wrong with raw `ssh -L`; use `stunnel`/`ncat --ssl` or `--insecure` on the wrapper httpx client for real use.

**Skill returns HTTP 502 from `host.openshell.internal:4300`**

OpenShell forwarder couldn't reach the host wrapper. Almost always because the wrapper was started with `--host 127.0.0.1` only. Latest `install.sh` binds `0.0.0.0`. Re-run install:

```bash
bash install.sh <sandbox>
```

If the issue persists, confirm:

```bash
ss -ltn | grep 4300   # MUST show 0.0.0.0:4300, not 127.0.0.1:4300
```

**Skill returns "Connection refused" / "All connection attempts failed" from in-sandbox python**

The sandbox network namespace has NO direct route to `host.openshell.internal:4300` — the OpenShell HTTPS proxy at `10.200.0.1:3128` is the only outbound path. Two things must be true:

1. `n8n_client.py` must NOT set `trust_env=False` on its httpx client — that disables proxy use. Latest skill defaults to proxy-aware httpx.
2. The wrapper port must be in the sandbox policy under `mcp_server_host.endpoints` with the binary path that runs the skill in the `binaries:` list. Latest `policy/sandbox_policy.yaml` already lists `python3.10` – `python3.13` and the standard skill venv globs.

If you upgraded the sandbox base image and python jumped to a new minor version, add the matching `/usr/bin/pythonX.Y` entry to `policy/sandbox_policy.yaml` and re-apply:

```bash
openshell policy set <sandbox> --policy policy/sandbox_policy.yaml --wait
```

**`openclaw tui` reports `unauthorized: gateway token mismatch`**

Gateway has a token loaded from `~/.openclaw/openclaw.json`; TUI sends whatever is in `$OPENCLAW_GATEWAY_TOKEN`. Mismatch means one of:

- The TUI env var isn't set. Run `export OPENCLAW_GATEWAY_TOKEN=$(. /tmp/oc-token.env && echo "$TOKEN") ; openclaw tui`.
- The JSON token is empty. Restart gateway via the launcher: `sh /tmp/start_oc_gateway.sh` (writes a real token first).
- You rotated one but not the other. Run `sh /tmp/start_oc_gateway.sh --rotate` then re-source the env file.

Verify with:

```bash
jq -r '.gateway.auth.token' /sandbox/.openclaw/openclaw.json
echo "$OPENCLAW_GATEWAY_TOKEN"
# both should print the same value
```

**`install.sh` fails at Step 2 — `INFERENCE_API_KEY not set in .env`**

Populate the `.env` per [Section 2](#2-environment-setup). All five core keys (`N8N_INSTANCE_URL`, `N8N_MCP_TOKEN`, `INFERENCE_API_KEY`, `INFERENCE_BASE_URL`, `INFERENCE_MODEL`) are required.

**Step 4 sandbox build fails inside OpenClaw patch RUN (`rcf_patch.py` / `Patch 1–5`)**

`nemoclaw v0.0.36` patches `replaceConfigFile` and friends inside OpenClaw's compiled JS dist. OpenClaw 2026.5.22+ refactored those functions — the regex anchors no longer match, the Docker build aborts with messages like:

```
AssertionError: tryWriteSingleTopLevelIncludeMutation/writeConfigFile pattern not found in replaceConfigFile
returned a non-zero code: 1
```

This is an upstream NemoClaw vs OpenClaw version drift, not a bug in this demo. **Local workaround** (applied outside this repo, on the NemoClaw source checkout at `~/NemoClaw/`):

1. `~/NemoClaw/scripts/rcf_patch.py` — replace the `assert m, "..."` line with a warn-and-skip block that appends a sentinel comment containing `OPENSHELL_SANDBOX EACCES` so the Dockerfile's downstream grep still passes:

   ```python
   m = pat.search(fn_src)
   if not m:
       print("WARN: rcf_patch pattern absent — skipping EACCES wrap", file=sys.stderr)
       with open(p, "a") as fh:
           fh.write("\n/* nemoclaw rcf_patch: OPENSHELL_SANDBOX EACCES wrap skipped */\n")
       sys.exit(0)
   ```

2. `~/NemoClaw/Dockerfile` — change the giant `RUN set -eu; ...` patch block (around line 154) to `RUN set -u; ...` and wrap each patch in `if [ -n "$x" ]; then apply; else echo "WARN: skipped"; fi`. Each patch becomes individually skippable. Append `exit 0` to the very end.

Both files are copied into the sandbox build context by `~/NemoClaw/dist/lib/sandbox-build-context.js` at every `nemoclaw onboard` run, so edits to the source files are picked up on the next install.

**Sandbox hardening tradeoff** — skipped patches mean OpenClaw runs without these protections inside the sandbox: fetch-guard strict mode, explicit-proxy assert, lstat→stat (plugin install symlink containment), EACCES wrap, 60s WS handshake timeout. Acceptable for dev/demo, not for production. Remove once upstream nemoclaw ships updated anchors.

**`nemoclaw onboard` fails with auth error (Step 4)**

The `custom` provider posts to whatever `INFERENCE_BASE_URL` resolves to. Verify:

```bash
curl -H "Authorization: Bearer $INFERENCE_API_KEY" "$INFERENCE_BASE_URL/models" | head -20
```

If you get 401: the key is wrong or doesn't have access to that endpoint. If you get 404 on `/models`: `INFERENCE_BASE_URL` must already include the `/v1` suffix (e.g. `https://inference-api.nvidia.com/v1`, not `https://inference-api.nvidia.com`).

**Sandbox shows up but the agent can't pick a model — `openclaw tui` reports "Missing gateway auth token"**

The OpenShell gateway inference provider is not configured. Step 4b handles this, but to re-apply manually:

```bash
source .env
openshell provider create \
  --type  "${INFERENCE_PROVIDER_TYPE:-nvidia}" \
  --name  "${INFERENCE_PROVIDER_NAME:-nvidia}" \
  --credential INFERENCE_API_KEY \
  --config "NVIDIA_BASE_URL=$INFERENCE_BASE_URL"

openshell inference set \
  --provider "${INFERENCE_PROVIDER_NAME:-nvidia}" \
  --model    "$INFERENCE_MODEL"

openshell inference get
```

Re-run `bash install.sh <sandbox>` afterwards so Step 4c re-patches `openclaw.json`.

**Step 4c warns `OpenShell cluster container not found — skipping openclaw model patch`**

The `openshell-cluster-*` Docker container is not running. Start the OpenShell cluster (typically managed by `openshell gateway start` or the NemoClaw bootstrap process), then re-run `bash install.sh`. Without the patch, the agent inside the sandbox will use whatever model was last set via `openclaw onboard`.

**Step 5 — MCP wrapper exits immediately**

```bash
tail -f /tmp/n8n-mcp.log
```

Common causes:
- `N8N_INSTANCE_URL` malformed → fix in `.env`, kill PID, re-run install
- `N8N_MCP_TOKEN` expired / invalid → request a fresh JWT
- Port 4300 already in use → `lsof -iTCP:4300 -sTCP:LISTEN` and kill the holder

**Step 6 — `filesystem read_write path '/sandbox/.openclaw' cannot be removed on a live sandbox`**

The OpenShell policy engine treats `openshell policy set` as a full replacement. If the policy file omits paths the sandbox image declared, they appear "removed" → rejected. The committed `policy/sandbox_policy.yaml` already lists `/sandbox`, `/sandbox/.openclaw`, `/sandbox/.openclaw-data`, `/sandbox/.nemoclaw` explicitly. If you edited the file, restore those entries before re-running.

**Step 10 — `n8n_health` does not return `"status": "ok"`**

```bash
# Reproduce from the host:
source .venv/bin/activate
python3 -c "
import asyncio, json
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

async def main():
    async with Client(transport=StreamableHttpTransport('http://127.0.0.1:4300/mcp')) as c:
        r = await c.call_tool('n8n_health', {})
        print(r.content[0].text)

asyncio.run(main())
"
```

Then from inside the sandbox:

```bash
openshell sandbox exec -n <sandbox> -- \
  /sandbox/.openclaw/workspace/skills/n8n-workflow-skills/venv/bin/python3 \
  /sandbox/.openclaw/workspace/skills/n8n-workflow-skills/scripts/n8n_client.py n8n_health
```

If host succeeds but sandbox fails: network policy not applied — re-run Step 6 manually (`openshell policy set <sandbox> --policy policy/sandbox_policy.yaml --wait`).
If both fail: wrapper not reaching upstream n8n — verify `N8N_INSTANCE_URL` reachable from the host (`curl -H "Authorization: Bearer $N8N_MCP_TOKEN" $N8N_INSTANCE_URL`).

**`list_workflows` returns `[]`**

The current n8n token's user lacks `workflow:execute` permission, or the workflows don't have "Available in MCP" enabled. Use `--include-non-executable` to see what exists (debug only — agent should NEVER invoke this flag):

```bash
$SKILL list_workflows --include-non-executable
```

If the list is non-empty under that flag, ask a project admin to grant `workflow:execute` and toggle "Available in MCP" on the relevant workflows.

**`execute_workflow` times out**

Some workflows (n8n agent nodes with long tool chains) take minutes. Bump both knobs:

```bash
$SKILL execute_workflow --workflow-id <id> --query "..." \
  --poll-interval 5 --poll-timeout 1800
```

Or persist via `setup_config.py`:

```bash
$SKILL_DIR/venv/bin/python3 $SKILL_DIR/scripts/setup_config.py \
  --non-interactive --poll-interval 5 --poll-timeout 1800
```

**`execute_workflow` returns `No prompt specified` (or the agent just echoes its system prompt)**

The workflow ran but the AI Agent received an empty prompt. Checklist:

1. **Webhook path resolved?** `execute_chat_workflow` finds the workflow's webhook
   node via `get_workflow_details`. The orchestrator's AI Agent prompt must read
   the webhook body, e.g. `={{ $json.body?.chatInput ?? $json.chatInput }}`
   (webhook v2.1 nests the POST body under `$json.body`). If the operating
   protocol is pasted into the **prompt** field instead of the **System Message**,
   the agent echoes the protocol — move it to `options.systemMessage`.
2. **All workflows active?** The orchestrator **and** every sub-workflow it calls
   as a tool must be active, or tool calls fail with
   `Workflow is not active and cannot be executed`:
   `docker exec n8n n8n publish:workflow --id=<id>` for each of the four workflow
   IDs, then `docker restart n8n`.
3. **Sub-workflow Code nodes return data?** Empty Code nodes surface as
   `Unknown error`. Each must `return [{ json: {...} }]`.
4. **Code node language = JavaScript.** The stock n8n container has **no Python
   task runner** (`Failed to start Python task runner … Python 3 is missing`), so
   Python Code nodes fail. Use `language: javaScript`.

**Skill not found in sandbox after reconnect**

```bash
bash install.sh <sandbox-name>   # re-uploads + re-applies policy + re-writes config
```

Then disconnect and reconnect in NemoClaw.

**MCP wrapper holds stale n8n connection after `.env` token rotation**

```bash
kill $(cat /tmp/n8n-mcp.pid)
bash install.sh <sandbox-name>   # re-reads .env, restarts wrapper, re-verifies
```

**Cleanup (full wipe)**

```bash
kill $(cat /tmp/n8n-mcp.pid 2>/dev/null) 2>/dev/null
rm -f /tmp/n8n-mcp.pid /tmp/n8n-mcp.log
rm -rf .venv
openshell sandbox exec -n <sandbox> -- rm -rf /sandbox/.openclaw/workspace/skills/n8n-workflow-skills
```
