# Enterprise n8n Workflow Demo

Run a guardrailed **EnterpriseOrchestrator** n8n workflow from inside a NemoClaw
sandbox via OpenClaw chat. You type a task; the agent runs it through
`policy_guard → task_router → cost_gate → execution plan` and returns the result.

```
OpenClaw chat (sandbox) ─► skill venv ─► host:4300 (n8n_mcp_server.py)
                                          ├─► n8n MCP API   (discovery)
                                          └─► n8n webhook   (execution, synchronous)
                                              └─ n8n: self-hosted ./n8n_selfhost on :5678
                                                      (or a remote enterprise n8n)
```

> **📖 Full walkthrough — prereqs, env, install, TUI, sample queries, troubleshooting:
> [`n8n-workflow-openclaw-guide.md`](n8n-workflow-openclaw-guide.md).** This README is
> just the map.

## Quickstart

1. **Populate `.env`** (5 keys: `N8N_INSTANCE_URL`, `N8N_MCP_TOKEN`, `INFERENCE_API_KEY`,
   `INFERENCE_BASE_URL`, `INFERENCE_MODEL`) — [guide §2](n8n-workflow-openclaw-guide.md#2-environment-setup).
2. **Bring up the self-hosted n8n FIRST** (it must be reachable before the wrapper) —
   `cd n8n_selfhost && bash 0_build_and_run_docker.sh`, import workflows, then
   `bash fix_n8n_setup.sh` (wires your `nvapi-…` key into n8n) —
   [guide §3](n8n-workflow-openclaw-guide.md#3-bring-up-the-self-hosted-n8n-first)
   / [`n8n_selfhost/preserving_n8n_workflow_for_reuse_steps.md`](n8n_selfhost/preserving_n8n_workflow_for_reuse_steps.md).
3. **Install the OpenClaw + MCP stack:** `bash install.sh [sandbox-name]` —
   [guide §4](n8n-workflow-openclaw-guide.md#4-one-command-install-openclaw--mcp).
4. **Chat:** `nemoclaw <sandbox> connect`, then try the
   [sample queries](n8n-workflow-openclaw-guide.md#sample-queries-to-try)
   (incident / finance / blocked-policy).

## Layout

```
enterprise_n8n_workflow/
├── README.md                       # this map
├── n8n-workflow-openclaw-guide.md  # full walkthrough (authoritative)
├── install.sh                      # one-command installer (Step 0 → 10, idempotent)
├── requirements.txt                # fastmcp httpx python-dotenv colorama
├── .env                            # 5 keys you provide (gitignored — never commit)
├── n8n_mcp_server.py               # host wrapper (port 4300): meta-tools + execute_chat_workflow
├── n8n_mcp_client.py               # standalone host-side CLI (interactive picker)
├── scripts/                        # set_oc_token.py, start_oc_gateway.sh
├── policy/sandbox_policy.yaml      # opens port 4300 to skill venv (python3.10–3.13)
├── n8n_workflow_skills/            # the agent's skill: SKILL.md, HEARTBEAT.md, scripts/n8n_client.py
└── n8n_selfhost/                   # bundled self-hosted n8n: build script, workflow export,
                                    #   fix_n8n_setup.sh, redeploy guide
```

## Skill tools (agent-facing)

`list_workflows`, `describe_workflow`, `execute_workflow` (synchronous webhook),
`get_execution`, `list_n8n_tools`, `call_n8n_tool`, `n8n_health`, `wrapper_ping`.
Full reference: [`n8n_workflow_skills/SKILL.md`](n8n_workflow_skills/SKILL.md) ·
routing in [`n8n_workflow_skills/HEARTBEAT.md`](n8n_workflow_skills/HEARTBEAT.md).

## Operations & troubleshooting

Daily ops (restart wrapper / systemd service / logs / re-upload skill) and the full
symptom→fix table live in the guide:
[§7 Daily Operations](n8n-workflow-openclaw-guide.md#7-daily-operations) ·
[§9 Troubleshooting](n8n-workflow-openclaw-guide.md#9-troubleshooting).

**Known install gotchas** (see guide for full steps):

| Issue | Cause | Fix location |
|-------|--------|--------------|
| Sandbox Docker build fails at step 18 (`rcf_patch.py` assertion) | Fresh `sandbox-base` ships OpenClaw ≥ 2026.5.22; NemoClaw 0.0.36 patch anchors target ≤ 2026.4.24 (`min_openclaw_version: "2026.4.24"`) | Option B patches in `~/.nemoclaw/source/scripts/rcf_patch.py` + `~/.nemoclaw/source/Dockerfile` — [guide §9](n8n-workflow-openclaw-guide.md#9-troubleshooting) |
| Step 4b `openshell inference set` verify timeout | Gateway probe slower than direct `curl` for large models | `install.sh` uses `--no-verify`; validate endpoint manually if needed |

> 🔐 Never commit `.env` or real keys. The bundled `n8n_selfhost/` ships **sanitized**
> credential templates only — each user plugs in their own key at deploy time.
