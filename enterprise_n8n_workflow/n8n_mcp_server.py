import argparse
import json
import os
from typing import Optional
from urllib.parse import urlparse

from dotenv import load_dotenv
from fastmcp import Client, FastMCP
from fastmcp.client.transports import StreamableHttpTransport

load_dotenv()

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_N8N_URL = os.environ.get("N8N_INSTANCE_URL", "")
_N8N_TOKEN = os.environ.get("N8N_MCP_TOKEN", "")
_MCP_HOST = os.environ.get("N8N_MCP_HOST", "0.0.0.0")
_MCP_PORT = int(os.environ.get("N8N_MCP_PORT", "4300"))
_MCP_PATH = os.environ.get("N8N_MCP_PATH", "/mcp")

mcp = FastMCP("n8nMCP")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _n8n_client() -> Client:
    """Build a fastmcp Client pointed at the remote n8n MCP endpoint."""
    if not _N8N_URL:
        raise RuntimeError("N8N_INSTANCE_URL is not set")
    headers = {}
    if _N8N_TOKEN:
        headers["Authorization"] = f"Bearer {_N8N_TOKEN}"
    return Client(transport=StreamableHttpTransport(_N8N_URL, headers=headers))


def _content_to_text(content) -> str:
    if not content:
        return ""
    parts = []
    for item in content:
        text = getattr(item, "text", None)
        parts.append(text if text is not None else str(item))
    return "\n".join(parts)


# ===========================================================================
# Tools
# ===========================================================================

@mcp.tool()
async def list_n8n_tools() -> str:
    """List all tools exposed by the remote n8n MCP server.

    Returns:
        JSON array of {name, description, input_schema} for every n8n tool.
    """
    try:
        async with _n8n_client() as client:
            tools = await client.list_tools()
        payload = [
            {
                "name": getattr(t, "name", ""),
                "description": getattr(t, "description", "") or "",
                "input_schema": getattr(t, "inputSchema", None)
                or getattr(t, "input_schema", None),
            }
            for t in tools
        ]
        return json.dumps(payload, indent=2, default=str)
    except Exception as ex:
        return f"Error: {type(ex).__name__}: {ex}"


@mcp.tool()
async def call_n8n_tool(tool_name: str, arguments: Optional[str] = None) -> str:
    """Invoke any tool on the remote n8n MCP server by name.

    Args:
        tool_name: Name of an n8n MCP tool (use list_n8n_tools to discover).
        arguments: JSON-encoded object of arguments for the tool. Optional.

    Returns:
        The textual content returned by the remote tool, or an error message.
    """
    try:
        args: dict = {}
        if arguments:
            args = json.loads(arguments)
            if not isinstance(args, dict):
                return "Error: 'arguments' must be a JSON object."
        async with _n8n_client() as client:
            result = await client.call_tool(tool_name, args)
        return _content_to_text(result.content) or "(no content)"
    except json.JSONDecodeError as ex:
        return f"Error: invalid JSON in 'arguments': {ex}"
    except Exception as ex:
        return f"Error: {type(ex).__name__}: {ex}"


def _n8n_base() -> str:
    """Derive the n8n HTTP base (scheme://host:port) from N8N_INSTANCE_URL."""
    p = urlparse(_N8N_URL)
    return f"{p.scheme}://{p.netloc}"


async def _resolve_webhook_path(workflow_id: str) -> Optional[str]:
    """Look up a workflow's production webhook path via the remote n8n MCP."""
    async with _n8n_client() as client:
        result = await client.call_tool("get_workflow_details", {"workflowId": workflow_id})
    text = _content_to_text(result.content)
    try:
        wf = json.loads(text)
    except json.JSONDecodeError:
        return None

    # get_workflow_details nests the workflow (and its nodes) under "workflow";
    # walk the whole payload to find the webhook node regardless of shape.
    found: list[str] = []

    def walk(obj):
        if isinstance(obj, dict):
            if obj.get("type") == "n8n-nodes-base.webhook":
                path = (obj.get("parameters") or {}).get("path")
                if path:
                    found.append(path)
            for v in obj.values():
                walk(v)
        elif isinstance(obj, list):
            for v in obj:
                walk(v)

    walk(wf)
    return found[0] if found else None


@mcp.tool()
async def execute_chat_workflow(
    chat_input: str,
    webhook_path: Optional[str] = None,
    workflow_id: Optional[str] = None,
    session_id: Optional[str] = None,
) -> str:
    """Execute a chat/agent workflow by POSTing its n8n webhook (synchronous).

    n8n's MCP `execute_workflow` does NOT inject chatInput into webhook-triggered
    workflows (the webhook node fires with an empty body), so this posts to the
    production webhook directly and returns the final node output
    (the orchestrator uses responseMode=lastNode, so the reply is synchronous).

    Args:
        chat_input: user query, forwarded as {"chatInput": ...}.
        webhook_path: webhook path segment (e.g. "agent-hub"). If omitted and
            workflow_id is given, it is resolved from the workflow's webhook node.
        workflow_id: optional; used to resolve webhook_path when not supplied.
        session_id: optional conversation id, passed through as sessionId.

    Returns:
        JSON string of the webhook response (e.g. {"output": "..."}), or an error.
    """
    try:
        import httpx

        path = webhook_path
        if not path and workflow_id:
            path = await _resolve_webhook_path(workflow_id)
        if not path:
            return "Error: webhook_path could not be determined (pass webhook_path or a workflow_id with a webhook node)."

        url = f"{_n8n_base()}/webhook/{path.lstrip('/')}"
        body: dict = {"chatInput": chat_input}
        if session_id:
            body["sessionId"] = session_id

        async with httpx.AsyncClient(timeout=httpx.Timeout(600.0)) as hc:
            resp = await hc.post(url, json=body)

        try:
            data = resp.json()
        except ValueError:
            return json.dumps(
                {"status": "error", "http_status": resp.status_code, "body": resp.text[:2000]},
                indent=2,
            )
        return json.dumps(data, indent=2, default=str)
    except Exception as ex:
        return f"Error: {type(ex).__name__}: {ex}"


@mcp.tool()
async def wrapper_ping() -> str:
    """Confirm the host wrapper itself is reachable — no upstream call.

    Use this to isolate sandbox→wrapper path from wrapper→n8n path when
    diagnosing connectivity. Returns JSON with the wrapper's own view of
    the bind address and the configured upstream URL (without contacting it).
    """
    return json.dumps(
        {
            "status": "ok",
            "wrapper_listen": f"{_MCP_HOST}:{_MCP_PORT}{_MCP_PATH}",
            "upstream_n8n_url": _N8N_URL or "(not set)",
            "upstream_n8n_token_set": bool(_N8N_TOKEN),
            "note": "This tool does NOT contact n8n. Use n8n_health to test upstream.",
        },
        indent=2,
    )


@mcp.tool()
async def n8n_health() -> str:
    """Check that the remote n8n MCP endpoint is reachable.

    Returns:
        JSON status with tool count, or an error message.
    """
    try:
        async with _n8n_client() as client:
            tools = await client.list_tools()
        return json.dumps(
            {"status": "ok", "url": _N8N_URL, "tool_count": len(tools)},
            indent=2,
        )
    except Exception as ex:
        return json.dumps(
            {"status": "error", "url": _N8N_URL, "error": f"{type(ex).__name__}: {ex}"},
            indent=2,
        )


# ===========================================================================
# Entry point
# ===========================================================================

def _parse_args():
    parser = argparse.ArgumentParser(description="n8n MCP Server (FastMCP wrapper)")
    parser.add_argument("--host", default=_MCP_HOST, help=f"Bind host (default: {_MCP_HOST})")
    parser.add_argument("--port", type=int, default=_MCP_PORT, help=f"Bind port (default: {_MCP_PORT})")
    parser.add_argument("--path", default=_MCP_PATH, help=f"URL path (default: {_MCP_PATH})")
    parser.add_argument("--n8n-url", default=_N8N_URL, help="Remote n8n MCP URL")
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()

    # Override env-driven defaults if --n8n-url was passed explicitly.
    if args.n8n_url:
        _N8N_URL = args.n8n_url

    print("[MCP] n8n FastMCP wrapper")
    print(f"[MCP] n8n URL : {_N8N_URL or '(not set)'}")
    print(f"[MCP] Listen  : http://{args.host}:{args.port}{args.path}")

    mcp.run(
        transport="streamable-http",
        host=args.host,
        port=args.port,
        path=args.path,
        log_level="debug",
    )
