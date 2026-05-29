---
name: n8n-workflow-skills
description: Interact with the enterprise n8n workflow platform via the host MCP wrapper. Discover executable workflows the current user can run, describe what each one does, and execute a workflow with a free-form chat query (e.g. "find me files with 'roadmap' in OneDrive", "find NVbugs related to NeMo"). You (the agent) pick the tool — there is no host-side LLM router. Trigger keywords — n8n, workflow, automation, integration, OneDrive, Google Drive, GDrive, SharePoint, NVBug, Jira, Slack, Outlook, list workflows, run workflow, execute workflow.
---

# n8n Workflow Skill

## Overview

Direct tool interface to the enterprise n8n MCP endpoint via a local FastMCP wrapper running on the **host machine** (port 4300). The wrapper exposes three thin meta-tools (`list_n8n_tools`, `call_n8n_tool`, `n8n_health`) plus one webhook tool (`execute_chat_workflow`) — this CLI client composes them into higher-level operations the agent uses every day:

- `list_workflows` — only the ones the current user **can execute** (filters `canExecute && availableInMCP && active`).
- `describe_workflow` — show a single workflow's name, description, and metadata so the agent can answer "what does this workflow do?".
- `execute_workflow` — run a workflow with a chat query and return its consolidated reply. Synchronous: the wrapper POSTs the workflow's n8n webhook (`execute_chat_workflow`) and returns the final node output in one call (no polling).
- `get_execution` — raw status / data for a specific execution id (no polling).
- `list_n8n_tools`, `call_n8n_tool`, `n8n_health` — direct passthroughs to the remote n8n MCP.

## Invocation

Always use the skill venv's Python (required by the sandbox network policy — only the skill venv binary is allowed to reach port 4300):

```bash
SKILL_DIR=~/.openclaw/workspace/skills/n8n-workflow-skills
SKILL="$SKILL_DIR/venv/bin/python3 $SKILL_DIR/scripts/n8n_client.py"
```

Do **not** use bare `python3` — the system Python is blocked by the sandbox policy from reaching port 4300.

## First-Time Setup

```bash
$SKILL_DIR/venv/bin/python3 $SKILL_DIR/scripts/setup_config.py
# or non-interactively:
$SKILL_DIR/venv/bin/python3 $SKILL_DIR/scripts/setup_config.py \
  --server-url http://host.openshell.internal:4300/mcp \
  --poll-interval 3 --poll-timeout 600
```

## Routing — which tool for which intent

| If the user wants to… | Call this tool |
|---|---|
| see what workflows they can run | `list_workflows` |
| understand what a specific workflow does | `describe_workflow --workflow-id <id>` (or pass `--name`) |
| run a workflow with a chat query (find files, search NVbug, etc.) | `execute_workflow --workflow-id <id> --query "..."` |
| inspect a specific execution by id | `get_execution --workflow-id <id> --execution-id <eid>` |
| see every tool the remote n8n MCP exposes | `list_n8n_tools` |
| call any remote n8n tool directly | `call_n8n_tool --name <tool> --arguments '<json>'` |
| confirm the remote n8n MCP is reachable | `n8n_health` |

### Typical conversation flow

1. User: "what workflows can I run?" → `list_workflows`.
2. User: "what does the OneDrive search one do?" → `describe_workflow --workflow-id <id>`.
3. User: "find me files with 'roadmap' in OneDrive" → `execute_workflow --workflow-id <id> --query "find files with 'roadmap' in OneDrive"`. The client polls until terminal status and returns the consolidated text reply. Show it verbatim.
4. If the user later asks "what happened with execution X?" → `get_execution --workflow-id <id> --execution-id X`.

Never invent a workflow id. Always call `list_workflows` first and pick from the returned set.

## Available Tools

### `list_workflows`
Returns the JSON list of workflows the current user can execute (filtered to `canExecute && availableInMCP && active`). Each entry has `id`, `name`, `description`.
**Use when:** the user asks what's available, what workflows exist, or before any `execute_workflow` call.
```bash
$SKILL list_workflows
$SKILL list_workflows --limit 50
$SKILL list_workflows --include-non-executable   # admin / debugging
```

### `describe_workflow`
Returns name + description + metadata for a single workflow. Useful for "what does workflow X do?" questions.
**Use when:** the user picks a workflow and wants more detail before running it.
```bash
$SKILL describe_workflow --workflow-id <id>
$SKILL describe_workflow --name "OneDrive Search"
```

### `execute_workflow`
Runs a workflow with a chat query and returns the consolidated agent/chat output. Under the hood it calls the wrapper's `execute_chat_workflow`, which resolves the workflow's webhook path (via `get_workflow_details`) and `POST`s `{"chatInput": <query>}` to the n8n webhook — returning the final node output **synchronously** (`responseMode=lastNode`, no polling). On error, returns the error message. **This is the tool the agent will call most often.**

> Why not the n8n MCP `execute_workflow` tool? It does not inject `chatInput` into webhook-triggered workflows (the webhook node fires with an empty body → the agent gets an empty prompt). The webhook POST is the reliable path.
> `--poll-interval` / `--poll-timeout` are still accepted for backward compatibility but are no-ops on this synchronous path.
**Use when:** the user has picked a workflow and supplied a query.
```bash
$SKILL execute_workflow --workflow-id <id> --query "find me files containing 'roadmap' in OneDrive"
$SKILL execute_workflow --workflow-id <id> --query "find NVbugs related to NeMo" --poll-interval 5 --poll-timeout 900
```

### `get_execution`
Raw status / data for a specific execution id. Does **not** poll.
```bash
$SKILL get_execution --workflow-id <id> --execution-id <eid>
$SKILL get_execution --workflow-id <id> --execution-id <eid> --include-data
```

### `list_n8n_tools`
Lists every tool the remote n8n MCP exposes. Use when the user asks "what can the n8n MCP do" or you need to discover a new operation.
```bash
$SKILL list_n8n_tools
```

### `call_n8n_tool`
Generic passthrough — invoke any remote n8n tool by name with a JSON arguments object.
```bash
$SKILL call_n8n_tool --name search_workflows --arguments '{"limit": 10}'
$SKILL call_n8n_tool --name get_workflow --arguments '{"id": "abc123"}'
```

### `n8n_health`
Confirms the remote n8n MCP is reachable through the wrapper.
```bash
$SKILL n8n_health
```

## Configuration (`config.json`)

```json
{
  "server_url": "http://host.openshell.internal:4300/mcp",
  "poll_interval_sec": 3,
  "poll_timeout_sec": 600
}
```

`server_url` defaults to the host MCP wrapper. Override per call with `--server-url URL` or the `N8N_MCP_LOCAL_URL` environment variable.

`poll_interval_sec` / `poll_timeout_sec` control `execute_workflow` polling cadence and hard cap.

## Host wrapper (port 4300)

The agent never talks to `https://n8n.prd.astra.nvidia.com/...` directly — sandbox egress to that host is not permitted. All requests flow:

```
sandbox skill venv  ──►  host:4300 (n8n_mcp_server.py wrapper)  ──►  enterprise n8n MCP
```

The wrapper is started by `install.sh` and reads `N8N_INSTANCE_URL` + `N8N_MCP_TOKEN` from the host's `.env`.

## Troubleshooting

If a tool call fails with a connection error:
1. Confirm the wrapper is reachable: `curl http://host.openshell.internal:4300/mcp`
2. Confirm the sandbox policy allows egress to port 4300 (`policy/sandbox_policy.yaml`)
3. If the venv is missing, recreate it:
   ```bash
   python3 -m venv $SKILL_DIR/venv
   $SKILL_DIR/venv/bin/pip install -q fastmcp
   ```
4. If `list_workflows` returns an empty list, the user is missing `workflow:execute` permission in n8n, or the workflows don't have "Available in MCP" enabled — ask a project admin.
