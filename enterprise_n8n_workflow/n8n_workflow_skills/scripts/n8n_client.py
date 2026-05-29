"""
n8n Workflow — MCP Skill Client

Invoked by the NemoClaw sandbox agent as:
    python3 n8n_client.py <tool_name> [--arg value ...]

Talks to the host MCP wrapper (n8n_mcp_server.py) which proxies to the
enterprise n8n MCP endpoint. The wrapper only exposes thin meta-tools
(list_n8n_tools, call_n8n_tool, n8n_health) — this client composes them
into higher-level operations the agent uses most often: list_workflows,
describe_workflow, execute_workflow, get_execution.

Configuration is loaded from config.json (next to scripts/ dir).
Override with CLI flags or environment variables.
"""

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

try:
    import httpx
    from fastmcp import Client
    from fastmcp.client.transports import StreamableHttpTransport
except ImportError:
    print(
        "ERROR: fastmcp is not installed. Run: pip install fastmcp",
        file=sys.stderr,
    )
    sys.exit(1)


def _no_proxy_httpx_client(
    headers: dict | None = None,
    timeout: httpx.Timeout | None = None,
    auth: httpx.Auth | None = None,
    **kwargs,
) -> httpx.AsyncClient:
    """httpx.AsyncClient with proxy env vars (HTTP_PROXY etc.) disabled.

    The OpenClaw sandbox sets HTTP_PROXY=http://10.200.0.1:3128 for outbound
    traffic, but our wrapper at host.openshell.internal:4300 must be reached
    directly. trust_env=False makes httpx ignore all *_PROXY / NO_PROXY env
    vars so the request goes straight to the wrapper.

    Extra kwargs from fastmcp/mcp (e.g. follow_redirects on newer versions)
    are forwarded to httpx.AsyncClient verbatim.
    """
    return httpx.AsyncClient(
        headers=headers,
        timeout=timeout if timeout is not None else httpx.Timeout(30.0),
        auth=auth,
        trust_env=False,
        **kwargs,
    )

# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

_SKILL_DIR = Path(__file__).resolve().parent.parent
_CONFIG_PATH = _SKILL_DIR / "config.json"


def _load_config() -> dict:
    if _CONFIG_PATH.is_file():
        try:
            return json.loads(_CONFIG_PATH.read_text())
        except (json.JSONDecodeError, OSError) as e:
            print(f"Warning: failed to load {_CONFIG_PATH}: {e}", file=sys.stderr)
    return {}


_CONFIG = _load_config()

_DEFAULT_URL = os.environ.get(
    "N8N_MCP_LOCAL_URL",
    _CONFIG.get("server_url", "http://host.openshell.internal:4300/mcp"),
)
_DEFAULT_POLL_INTERVAL = float(
    os.environ.get("N8N_POLL_INTERVAL_SEC", _CONFIG.get("poll_interval_sec", 3.0))
)
_DEFAULT_POLL_TIMEOUT = float(
    os.environ.get("N8N_POLL_TIMEOUT_SEC", _CONFIG.get("poll_timeout_sec", 600.0))
)

# execute_workflow may stream for several minutes; per-tool timeouts.
_TOOL_TIMEOUTS: dict[str, float] = {
    "execute_workflow": max(_DEFAULT_POLL_TIMEOUT + 60.0, 660.0),
    "list_workflows": 60.0,
    "describe_workflow": 60.0,
    "get_execution": 60.0,
    "list_n8n_tools": 60.0,
    "call_n8n_tool": 300.0,
    "n8n_health": 30.0,
}
_DEFAULT_TIMEOUT = 60.0

TERMINAL_STATUSES = frozenset({"success", "error", "crashed", "canceled"})


# ---------------------------------------------------------------------------
# Wrapper helpers
# ---------------------------------------------------------------------------

def _connect(server_url: str, tool_name: str) -> Client:
    timeout = _TOOL_TIMEOUTS.get(tool_name, _DEFAULT_TIMEOUT)
    # The OpenClaw sandbox sets HTTP_PROXY=http://10.200.0.1:3128 and the
    # in-sandbox netns has NO direct route to host.openshell.internal:4300 —
    # the proxy is the only outbound path. httpx defaults (trust_env=True)
    # already do the right thing. If you ever run this outside the sandbox
    # and want to bypass a local proxy, instantiate StreamableHttpTransport
    # with httpx_client_factory=_no_proxy_httpx_client.
    transport = StreamableHttpTransport(server_url)
    return Client(transport=transport, timeout=timeout)


def _result_text(result) -> str:
    """Extract text from a CallToolResult or list of content blocks."""
    blocks = result.content if hasattr(result, "content") else result
    parts = []
    for block in blocks or []:
        text = getattr(block, "text", None)
        parts.append(text if text is not None else str(block))
    return "\n".join(parts)


async def _wrapper_call(client: Client, wrapper_tool: str, args: dict) -> str:
    """Invoke a wrapper-side tool (list_n8n_tools / call_n8n_tool / n8n_health)."""
    result = await client.call_tool(wrapper_tool, args)
    text = _result_text(result)
    if text.startswith("Error:"):
        raise RuntimeError(text)
    return text


async def _remote_call(client: Client, remote_tool: str, arguments: dict) -> dict:
    """Invoke an n8n MCP tool via the wrapper's call_n8n_tool passthrough."""
    text = await _wrapper_call(
        client,
        "call_n8n_tool",
        {"tool_name": remote_tool, "arguments": json.dumps(arguments)},
    )
    try:
        return json.loads(text)
    except json.JSONDecodeError as ex:
        raise RuntimeError(f"Non-JSON response from {remote_tool}: {text[:500]}") from ex


# ---------------------------------------------------------------------------
# Workflow filtering / response extraction (mirrors n8n_mcp_client.py)
# ---------------------------------------------------------------------------

def _filter_executable(workflows: list[dict]) -> list[dict]:
    return [
        w
        for w in workflows
        if w.get("canExecute") and w.get("availableInMCP") and w.get("active")
    ]


def _summarise_workflows(workflows: list[dict]) -> list[dict]:
    out = []
    for w in workflows:
        out.append({
            "id": w.get("id"),
            "name": w.get("name") or "(unnamed)",
            "description": w.get("description") or "",
            "active": w.get("active"),
            "canExecute": w.get("canExecute"),
            "availableInMCP": w.get("availableInMCP"),
        })
    return out


def _extract_execution_status(payload: dict) -> str | None:
    execution = payload.get("execution")
    if isinstance(execution, dict):
        return execution.get("status")
    return payload.get("status")


def _extract_response_text(payload: dict) -> str:
    """Best-effort extraction of agent/chat output from execution data."""
    data = payload.get("data")
    if not data:
        return json.dumps(payload, indent=2, default=str)

    chunks: list[str] = []

    def walk(obj):
        if isinstance(obj, dict):
            for key in ("output", "text", "response", "message"):
                val = obj.get(key)
                if isinstance(val, str) and val.strip():
                    chunks.append(val.strip())
            for val in obj.values():
                walk(val)
        elif isinstance(obj, list):
            for item in obj:
                walk(item)

    walk(data)
    if chunks:
        return "\n\n".join(dict.fromkeys(chunks))
    return json.dumps(data, indent=2, default=str)


def _extract_error_message(payload: dict, trigger: dict | None = None) -> str:
    for source in (payload, trigger or {}):
        err = source.get("error")
        if isinstance(err, str) and err.strip():
            return err.strip()
    data = payload.get("data")
    if isinstance(data, dict):
        for node_output in data.values():
            if not isinstance(node_output, list):
                continue
            for item in node_output:
                if not isinstance(item, dict):
                    continue
                err = item.get("error")
                if isinstance(err, dict):
                    msg = err.get("message") or err.get("description")
                    if msg:
                        return str(msg)
                json_body = item.get("json") if isinstance(item.get("json"), dict) else item
                if isinstance(json_body, dict):
                    for key in ("error", "errorMessage", "message"):
                        val = json_body.get(key)
                        if isinstance(val, str) and "error" in key.lower():
                            return val
    return _extract_response_text(payload)


# ---------------------------------------------------------------------------
# Composite operations
# ---------------------------------------------------------------------------

async def _op_list_workflows(client: Client, limit: int, include_non_executable: bool) -> None:
    payload = await _remote_call(client, "search_workflows", {"limit": limit})
    workflows = payload.get("data") or []
    if not include_non_executable:
        workflows = _filter_executable(workflows)
    print(json.dumps(_summarise_workflows(workflows), indent=2))


async def _op_describe_workflow(
    client: Client, workflow_id: str | None, name: str | None
) -> None:
    if not workflow_id and not name:
        raise SystemExit("describe_workflow: provide --workflow-id or --name")

    if not workflow_id:
        # Look up by name
        payload = await _remote_call(client, "search_workflows", {"limit": 200})
        workflows = payload.get("data") or []
        match = next(
            (w for w in workflows if (w.get("name") or "").strip().lower() == name.strip().lower()),
            None,
        )
        if not match:
            raise SystemExit(f"describe_workflow: no workflow named {name!r}")
        workflow_id = match["id"]
        print(json.dumps(match, indent=2, default=str))
        return

    # Fetch full workflow detail via the remote get_workflow tool (if available)
    try:
        detail = await _remote_call(client, "get_workflow", {"id": workflow_id})
        print(json.dumps(detail, indent=2, default=str))
        return
    except RuntimeError:
        pass  # fall back to search

    payload = await _remote_call(client, "search_workflows", {"limit": 200})
    workflows = payload.get("data") or []
    match = next((w for w in workflows if w.get("id") == workflow_id), None)
    if not match:
        raise SystemExit(f"describe_workflow: workflow id {workflow_id!r} not found")
    print(json.dumps(match, indent=2, default=str))


async def _op_execute_workflow(
    client: Client,
    workflow_id: str,
    query: str,
    poll_interval: float,
    poll_timeout: float,
) -> None:
    # n8n's MCP execute_workflow does NOT pass chatInput into webhook-triggered
    # workflows (the webhook node fires with an empty body), so we go through the
    # wrapper's execute_chat_workflow tool, which POSTs the production webhook
    # directly and returns the final node output synchronously (responseMode=lastNode).
    text = await _wrapper_call(
        client,
        "execute_chat_workflow",
        {"workflow_id": workflow_id, "chat_input": query},
    )
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Non-JSON body — treat as raw output.
        print(json.dumps({"status": "success", "workflowId": workflow_id, "output": text}, indent=2))
        return

    if isinstance(data, dict) and isinstance(data.get("output"), str):
        print(json.dumps(
            {"status": "success", "workflowId": workflow_id, "output": data["output"]},
            indent=2,
        ))
        return

    # n8n returns {"message": "Error in workflow"} (or similar) on failure.
    if isinstance(data, dict) and (
        data.get("status") == "error" or "error" in data or data.get("message") == "Error in workflow"
    ):
        print(json.dumps(
            {
                "status": "error",
                "workflowId": workflow_id,
                "error": data.get("error") or data.get("message") or json.dumps(data),
            },
            indent=2,
        ))
        sys.exit(1)

    # Unknown shape — surface it verbatim under success.
    print(json.dumps(
        {"status": "success", "workflowId": workflow_id, "output": json.dumps(data, indent=2)},
        indent=2,
    ))


async def _op_get_execution(
    client: Client, workflow_id: str, execution_id: str, include_data: bool
) -> None:
    payload = await _remote_call(
        client,
        "get_execution",
        {"workflowId": workflow_id, "executionId": execution_id, "includeData": include_data},
    )
    print(json.dumps(payload, indent=2, default=str))


async def _op_list_n8n_tools(client: Client) -> None:
    print(await _wrapper_call(client, "list_n8n_tools", {}))


async def _op_call_n8n_tool(client: Client, name: str, arguments: str) -> None:
    args_str = arguments or ""
    if args_str:
        try:
            json.loads(args_str)
        except json.JSONDecodeError as ex:
            raise SystemExit(f"call_n8n_tool: --arguments must be valid JSON ({ex})")
    print(await _wrapper_call(client, "call_n8n_tool", {"tool_name": name, "arguments": args_str}))


async def _op_n8n_health(client: Client) -> None:
    print(await _wrapper_call(client, "n8n_health", {}))


async def _op_wrapper_ping(client: Client) -> None:
    print(await _wrapper_call(client, "wrapper_ping", {}))


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

async def _dispatch(args: argparse.Namespace) -> None:
    async with _connect(args.server_url, args.tool) as client:
        if args.tool == "list_workflows":
            await _op_list_workflows(client, args.limit, args.include_non_executable)
        elif args.tool == "describe_workflow":
            await _op_describe_workflow(client, args.workflow_id, args.name)
        elif args.tool == "execute_workflow":
            await _op_execute_workflow(
                client,
                args.workflow_id,
                args.query,
                args.poll_interval,
                args.poll_timeout,
            )
        elif args.tool == "get_execution":
            await _op_get_execution(
                client, args.workflow_id, args.execution_id, args.include_data
            )
        elif args.tool == "list_n8n_tools":
            await _op_list_n8n_tools(client)
        elif args.tool == "call_n8n_tool":
            await _op_call_n8n_tool(client, args.name, args.arguments)
        elif args.tool == "n8n_health":
            await _op_n8n_health(client)
        elif args.tool == "wrapper_ping":
            await _op_wrapper_ping(client)
        else:
            raise SystemExit(f"Unknown tool: {args.tool}")


def build_parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        prog="n8n_client",
        description="n8n Workflow MCP skill client",
    )
    root.add_argument(
        "--server-url",
        default=_DEFAULT_URL,
        help=f"MCP wrapper URL (default: {_DEFAULT_URL})",
    )
    sub = root.add_subparsers(dest="tool", required=True)

    p = sub.add_parser("list_workflows", help="List workflows the current user can execute")
    p.add_argument("--limit", type=int, default=200, help="Max workflows to fetch (default 200)")
    p.add_argument(
        "--include-non-executable",
        action="store_true",
        help="Skip the canExecute/availableInMCP/active filter (admin/debug only)",
    )

    p = sub.add_parser("describe_workflow", help="Show metadata for a single workflow")
    p.add_argument("--workflow-id", help="Workflow id (preferred)")
    p.add_argument("--name", help="Workflow name (case-insensitive exact match)")

    p = sub.add_parser(
        "execute_workflow",
        help="Run a workflow with a chat query and wait for terminal status",
    )
    p.add_argument("--workflow-id", required=True)
    p.add_argument("--query", required=True, help="Chat input forwarded to the workflow")
    p.add_argument("--poll-interval", type=float, default=_DEFAULT_POLL_INTERVAL)
    p.add_argument("--poll-timeout", type=float, default=_DEFAULT_POLL_TIMEOUT)

    p = sub.add_parser("get_execution", help="Fetch a single execution's status / data")
    p.add_argument("--workflow-id", required=True)
    p.add_argument("--execution-id", required=True)
    p.add_argument("--include-data", action="store_true", help="Include full node data")

    sub.add_parser("list_n8n_tools", help="List every tool the remote n8n MCP exposes")

    p = sub.add_parser("call_n8n_tool", help="Invoke any remote n8n MCP tool by name")
    p.add_argument("--name", required=True, help="Remote tool name")
    p.add_argument("--arguments", default="", help="JSON-encoded arguments object")

    sub.add_parser("n8n_health", help="Check the remote n8n MCP endpoint is reachable")

    sub.add_parser(
        "wrapper_ping",
        help="Verify ONLY the sandbox→wrapper path (no upstream n8n call). "
        "Use this first when triaging connectivity.",
    )

    return root


def main() -> None:
    args = build_parser().parse_args()
    try:
        asyncio.run(_dispatch(args))
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
