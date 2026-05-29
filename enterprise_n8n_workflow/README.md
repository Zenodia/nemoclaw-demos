# Enterprise n8n Workflow Demo

Run enterprise n8n workflows from inside a NemoClaw sandbox. Agent picks tool, host wrapper proxies, remote n8n executes.

```
sandbox skill venv  ──►  host:4300 (n8n_mcp_server.py)  ──►  n8n.prd.astra.nvidia.com/mcp-server/http
```

## Prereqs

Host machine needs:

- `python3` (3.10+)
- `curl`
- NemoClaw CLI (`openshell`, `nemoclaw`) — already onboarded with a live sandbox (`nemoclaw onboard` done)
- `uv` — auto-installed by `install.sh` if missing

No Docker, no GPU.

## Step 1 — Populate `.env`

`enterprise_n8n_workflow/.env` must contain:

```bash
# n8n MCP wrapper
N8N_INSTANCE_URL=https://n8n.prd.astra.nvidia.com/mcp-server/http
N8N_MCP_TOKEN=<your-jwt-from-n8n>

# Inference (drives nemoclaw onboard + OpenShell provider + openclaw.json patch)
INFERENCE_API_KEY=nvapi-...
INFERENCE_BASE_URL=https://inference-api.nvidia.com/v1
INFERENCE_MODEL=aws/anthropic/bedrock-claude-sonnet-4-6
```

`install.sh` validates all five keys exist. Missing → fail fast.

The `INFERENCE_*` triple lets `install.sh` run `nemoclaw onboard` **non-interactively** (no provider/model picker), wire up the OpenShell gateway inference provider, and patch `openclaw.json` inside the sandbox to make `inference/$INFERENCE_MODEL` the primary model.

Optional overrides (env vars or `.env`):

| Var | Default | Purpose |
|---|---|---|
| `N8N_MCP_PORT` | `4300` | Host wrapper listen port |
| `N8N_MCP_HOST` | `0.0.0.0` | Wrapper bind host (must be `0.0.0.0` for sandbox reach via openshell forwarder) |
| `N8N_MCP_PATH` | `/mcp` | URL path |
| `N8N_POLL_INTERVAL_SEC` | `3` | `execute_workflow` poll cadence |
| `N8N_POLL_TIMEOUT_SEC` | `600` | `execute_workflow` hard cap |

## Step 2 — Verify sandbox exists (optional)

```bash
openshell sandbox list
```

If empty: `install.sh` auto-runs `nemoclaw onboard --non-interactive` using `INFERENCE_*` from `.env`. No prompts.

If multiple sandboxes: pass name as positional arg to `install.sh`, or set `defaultSandbox` in `~/.nemoclaw/sandboxes.json`.

## Step 3 — Run one-command installer

```bash
cd /home/ubuntu/nemoclaw-demos/enterprise_n8n_workflow
bash install.sh                    # auto-detect sandbox
# or
bash install.sh my-sandbox-name    # explicit
```

What it does (idempotent — safe to re-run):

| Step | Action |
|---|---|
| 0 | Kill stale wrapper (`/tmp/n8n-mcp.pid` + `pgrep n8n_mcp_server`) |
| 1 | Verify python3, openshell, curl, uv (install uv if missing) |
| 2 | Validate `.env` (`N8N_INSTANCE_URL`, `N8N_MCP_TOKEN`, `INFERENCE_API_KEY`, `INFERENCE_BASE_URL`, `INFERENCE_MODEL`) |
| 3 | Host venv at `.venv` + `pip install -r requirements.txt` |
| 4 | Auto-detect sandbox; if none, run `nemoclaw onboard --non-interactive` with `NEMOCLAW_PROVIDER=custom`, `NEMOCLAW_ENDPOINT_URL=$INFERENCE_BASE_URL`, `NEMOCLAW_MODEL=$INFERENCE_MODEL`, `COMPATIBLE_API_KEY=$INFERENCE_API_KEY` |
| 4b | `openshell provider create/update` + `openshell inference set` with INFERENCE_* values |
| 4c | Patch `/sandbox/.openclaw/openclaw.json` → primary model = `inference/$INFERENCE_MODEL` |
| 4d | Upload `scripts/set_oc_token.py` + `scripts/start_oc_gateway.sh`, persist a random hex token into `/sandbox/.openclaw/openclaw.json` `gateway.auth.token`, start OpenClaw gateway detached on `127.0.0.1:18789`, start `openshell forward 18789` |
| 5 | Start `n8n_mcp_server.py` on `0.0.0.0:4300/mcp` (background, auto-restart, logs `/tmp/n8n-mcp.log`) — binds `0.0.0.0` so the openshell forwarder can route sandbox traffic to it |
| 6 | Apply `policy/sandbox_policy.yaml` (sandbox skill venv → port 4300; python3.10–3.13 allowlisted) |
| 7 | Upload `n8n_workflow_skills/` → `/sandbox/.openclaw/workspace/skills/n8n-workflow-skills`, HEARTBEAT.md → workspace root |
| 8 | Write `config.json` with server_url + polling tunables |
| 9 | Bootstrap sandbox skill venv + `pip install fastmcp` |
| 10 | E2E verify — runs `n8n_health` from sandbox, asserts `"status": "ok"` |

Expected final output:

```
✓ Skill end-to-end: n8n_health → status ok
  ╔══════════════════════════════════════════════════════════╗
  ║  Installation complete!                                  ║
  ╚══════════════════════════════════════════════════════════╝

  ── OpenClaw chat UI ──────────────────────────────────────
  Browser URL  : http://127.0.0.1:18789/#token=<HEX>
  TUI env      : export OPENCLAW_GATEWAY_TOKEN=<HEX>
                 openclaw tui      (inside sandbox)
```

If your host is not on NVIDIA VPN, `n8n_health` will return
`Name or service not known` — that means the wrapper → upstream n8n hop fails because
`n8n.prd.astra.nvidia.com` is internal DNS. The skill itself is healthy. Verify with
`wrapper_ping` (no upstream call):

```bash
openshell sandbox exec -n <sandbox> -- \
  /sandbox/.openclaw/workspace/skills/n8n-workflow-skills/venv/bin/python3 \
  /sandbox/.openclaw/workspace/skills/n8n-workflow-skills/scripts/n8n_client.py wrapper_ping
```

Expect `status: ok` even when n8n_health is failing.

If Step 10 warns instead of ok, check `tail -f /tmp/n8n-mcp.log` and `openshell sandbox exec -n <sandbox> -- /sandbox/.openclaw/workspace/skills/n8n-workflow-skills/venv/bin/python3 /sandbox/.openclaw/workspace/skills/n8n-workflow-skills/scripts/n8n_client.py n8n_health`.

## Step 4 — Connect to sandbox and talk to agent

```bash
nemoclaw <sandbox-name> connect
```

Agent auto-loads `HEARTBEAT.md` → knows skill routing.

### Sample conversation

```
You:    what n8n workflows can I run?
Agent:  [runs $SKILL list_workflows → returns id+name+description list]

You:    what does the OneDrive search one do?
Agent:  [runs $SKILL describe_workflow --workflow-id <id>]

You:    find me files containing 'roadmap' in OneDrive
Agent:  [runs $SKILL execute_workflow --workflow-id <id> --query "find files containing 'roadmap' in OneDrive"
         polls every 3s until terminal status
         returns consolidated output]

You:    find NVbugs related to NeMo
Agent:  [picks the right workflow id, runs execute_workflow with that query]
```

Agent never invents workflow ids — always `list_workflows` first.

## Available skill tools

`SKILL=$SKILL_DIR/venv/bin/python3 $SKILL_DIR/scripts/n8n_client.py` where `SKILL_DIR=/sandbox/.openclaw/workspace/skills/n8n-workflow-skills`.

| Tool | Purpose |
|---|---|
| `list_workflows` | Executable workflows only (`canExecute && availableInMCP && active`) |
| `describe_workflow --workflow-id <id>` | Workflow metadata (also accepts `--name`) |
| `execute_workflow --workflow-id <id> --query "..."` | Trigger + poll + return result |
| `get_execution --workflow-id <id> --execution-id <eid>` | Raw status/data, no poll |
| `list_n8n_tools` | Every tool remote n8n MCP exposes |
| `call_n8n_tool --name X --arguments '<json>'` | Generic passthrough |
| `n8n_health` | Upstream reachability check (sandbox → wrapper → n8n) |
| `wrapper_ping` | Wrapper-only reachability — no upstream call. Run FIRST when diagnosing. |

Full reference: [`n8n_workflow_skills/SKILL.md`](n8n_workflow_skills/SKILL.md).

## Common operations

### Restart MCP wrapper

```bash
kill $(cat /tmp/n8n-mcp.pid) && bash install.sh <sandbox-name>
```

### Tail wrapper logs

```bash
tail -f /tmp/n8n-mcp.log
```

### Update polling tunables

```bash
openshell sandbox exec -n <sandbox> -- \
  /sandbox/.openclaw/workspace/skills/n8n-workflow-skills/venv/bin/python3 \
  /sandbox/.openclaw/workspace/skills/n8n-workflow-skills/scripts/setup_config.py \
  --poll-interval 5 --poll-timeout 900
```

### Re-upload skill after editing source

```bash
bash install.sh <sandbox-name>     # idempotent — re-uploads + skips already-done steps
```

### Test from host (bypass sandbox)

```bash
source .venv/bin/activate
python3 n8n_mcp_client.py          # interactive prompt: pick workflow → enter query → wait
```

## Layout

```
enterprise_n8n_workflow/
├── README.md                       # this file
├── n8n-workflow-openclaw-guide.md  # full walkthrough — prereqs, env, install, tui, troubleshooting
├── install.sh                      # one-command installer (Step 0 → Step 10, idempotent)
├── requirements.txt                # fastmcp httpx python-dotenv colorama
├── .env                            # 5 keys you provide — see Step 1
├── n8n_mcp_server.py               # host wrapper (port 4300, binds 0.0.0.0)
├── n8n_mcp_client.py               # standalone host-side CLI (interactive picker)
├── scripts/
│   ├── set_oc_token.py             # writes random token into /sandbox/.openclaw/openclaw.json
│   └── start_oc_gateway.sh         # token + gateway launcher (run inside sandbox)
├── policy/
│   └── sandbox_policy.yaml         # opens port 4300 to skill venv (python3.10–3.13 allowlist)
└── n8n_workflow_skills/
    ├── SKILL.md                    # full tool reference for the agent
    ├── HEARTBEAT.md                # routing rules + error-hop diagnostic table
    ├── config.json.example
    └── scripts/
        ├── setup_config.py
        └── n8n_client.py           # 8-tool CLI (includes wrapper_ping)
```

## Troubleshooting

Quick table — for deeper triage see [`n8n-workflow-openclaw-guide.md`](n8n-workflow-openclaw-guide.md) §8.

| Symptom | Likely cause | Fix |
|---|---|---|
| `N8N_INSTANCE_URL not set in .env` | Missing key | Populate `.env` per Step 1 — all 5 keys required |
| `nemoclaw onboard` fails at the OpenClaw plugin patch step (rcf_patch / Patch 1–5 in Docker build) | NemoClaw v0.0.36 patches don't match OpenClaw 2026.5.22+ | Apply the local NemoClaw patches — see [guide §8 "Step 4 sandbox build fails inside OpenClaw patch RUN"](n8n-workflow-openclaw-guide.md) |
| `openclaw tui` reports `gateway token mismatch` | Token in `~/.openclaw/openclaw.json` empty OR env var not set | Re-run `sh /tmp/start_oc_gateway.sh` inside sandbox; then `export OPENCLAW_GATEWAY_TOKEN=$(. /tmp/oc-token.env && echo "$TOKEN") ; openclaw tui` |
| Skill returns HTTP 502 from `host.openshell.internal:4300` | Wrapper bound `127.0.0.1` only | Re-run `bash install.sh` — Step 5 binds `0.0.0.0` |
| Skill returns `Connection refused` from inside sandbox | Sandbox has no direct route — proxy is the only path | Don't bypass proxy. `n8n_client.py` already uses proxy via default httpx `trust_env=True`. If you've edited it, restore default behaviour. |
| `wrapper_ping` ok but `n8n_health` says `Name or service not known` | Host can't resolve `n8n.prd.astra.nvidia.com` | **Environmental.** Host needs NVIDIA VPN / split DNS. Skill is healthy. |
| `list_workflows` returns `[]` | Permissions in n8n | User lacks `workflow:execute` OR workflows missing "Available in MCP" toggle — ask project admin |
| `execute_workflow` times out | Default 600s too short for slow agent workflows | `--poll-timeout 900` or persist via `setup_config.py --poll-timeout 1800` |
| Sandbox can't reach port 4300 | Stale policy | Re-apply: `openshell policy set <sandbox> --policy policy/sandbox_policy.yaml --wait` |
| `fastmcp` import error in sandbox | Skill venv corrupted | `bash install.sh <sandbox>` — Step 9 rebuilds skill venv |
| New python minor in sandbox base image | `python3.14+` not in policy allowlist | Add `/usr/bin/python3.14` + skill-venv glob to `policy/sandbox_policy.yaml`, re-apply |

## Cleanup

End-of-session shutdown (frees ports, stops gateway, sandbox, openshell cluster):

```bash
# Stop OpenClaw gateway inside sandbox
openshell sandbox exec -n <sandbox> -- openclaw gateway stop

# Stop host MCP wrapper
kill $(cat /tmp/n8n-mcp.pid 2>/dev/null) 2>/dev/null
pkill -9 -f n8n_mcp_server 2>/dev/null
rm -f /tmp/n8n-mcp.pid /tmp/n8n-mcp.log

# Stop openshell port forward
openshell forward stop 18789 <sandbox> 2>/dev/null

# Stop sandbox
openshell sandbox stop <sandbox>

# Stop NemoClaw gateway (openshell-cluster-* docker container)
docker stop $(docker ps --filter "name=openshell-cluster-" --format "{{.Names}}") 2>/dev/null
```

Full wipe (also nukes host venv and sandbox skill files):

```bash
rm -rf .venv
openshell sandbox exec -n <sandbox> -- rm -rf /sandbox/.openclaw/workspace/skills/n8n-workflow-skills
openshell sandbox delete <sandbox>
```
