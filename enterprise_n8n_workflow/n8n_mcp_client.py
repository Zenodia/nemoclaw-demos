import asyncio
import json
import os
import time

from colorama import Fore
from dotenv import load_dotenv
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

load_dotenv()

_MCP_HOST = os.environ.get("N8N_MCP_HOST", "127.0.0.1")
_MCP_PORT = int(os.environ.get("N8N_MCP_PORT", "4300"))
_MCP_PATH = os.environ.get("N8N_MCP_PATH", "/mcp")
MCP_URL = os.environ.get(
    "N8N_MCP_LOCAL_URL", f"http://{_MCP_HOST}:{_MCP_PORT}{_MCP_PATH}"
)

POLL_INTERVAL_SEC = float(os.environ.get("N8N_POLL_INTERVAL_SEC", "3"))
POLL_TIMEOUT_SEC = float(os.environ.get("N8N_POLL_TIMEOUT_SEC", "600"))

TERMINAL_STATUSES = frozenset({"success", "error", "crashed", "canceled"})


async def call_n8n_tool(client: Client, tool_name: str, arguments: dict) -> dict:
    """Invoke a remote n8n MCP tool via the local wrapper."""
    result = await client.call_tool(
        "call_n8n_tool",
        {"tool_name": tool_name, "arguments": json.dumps(arguments)},
    )
    text = result.content[0].text
    if text.startswith("Error:"):
        raise RuntimeError(text)
    try:
        return json.loads(text)
    except json.JSONDecodeError as ex:
        raise RuntimeError(f"Non-JSON response from {tool_name}: {text[:500]}") from ex


def filter_executable_workflows(workflows: list[dict]) -> list[dict]:
    """Keep workflows the current user can run via execute_workflow."""
    return [
        w
        for w in workflows
        if w.get("canExecute")
        and w.get("availableInMCP")
        and w.get("active")
    ]


def print_executable_workflows(workflows: list[dict]) -> None:
    print(Fore.CYAN + "\nWorkflows you can execute via MCP:\n" + Fore.RESET)
    for i, w in enumerate(workflows, start=1):
        name = w.get("name") or "(unnamed)"
        desc = w.get("description") or ""
        line = f"  [{i}] {name}  (id={w['id']})"
        print(Fore.GREEN + line + Fore.RESET)
        if desc:
            print(Fore.WHITE + f"      {desc[:120]}{'…' if len(desc) > 120 else ''}" + Fore.RESET)
    print()


def prompt_workflow_choice(workflows: list[dict]) -> dict:
    while True:
        raw = input(
            Fore.YELLOW
            + "Select workflow number (or 'exit'): "
            + Fore.RESET
        ).strip()
        if raw.lower() in {"exit", "quit", "q"}:
            raise SystemExit(0)
        if raw.isdigit():
            idx = int(raw) - 1
            if 0 <= idx < len(workflows):
                return workflows[idx]
        print(Fore.RED + f"Enter a number between 1 and {len(workflows)}." + Fore.RESET)


def prompt_query() -> str:
    while True:
        query = input(Fore.YELLOW + "Enter your query: " + Fore.RESET).strip()
        if query.lower() in {"exit", "quit", "q"}:
            raise SystemExit(0)
        if query:
            return query
        print(Fore.RED + "Query cannot be empty." + Fore.RESET)


def extract_execution_status(payload: dict) -> str | None:
    execution = payload.get("execution")
    if isinstance(execution, dict):
        return execution.get("status")
    return payload.get("status")


def extract_error_message(payload: dict, trigger: dict | None = None) -> str:
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
    return extract_response_text(payload)


def extract_response_text(payload: dict) -> str:
    """Best-effort extraction of agent/chat output from execution data."""
    data = payload.get("data")
    if not data:
        return json.dumps(payload, indent=2, default=str)

    chunks: list[str] = []

    def walk(obj) -> None:
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


async def wait_for_execution(
    client: Client,
    workflow_id: str,
    execution_id: str,
) -> dict:
    """Poll get_execution until the run reaches a terminal status."""
    deadline = time.monotonic() + POLL_TIMEOUT_SEC
    last_status: str | None = None

    while time.monotonic() < deadline:
        payload = await call_n8n_tool(
            client,
            "get_execution",
            {
                "workflowId": workflow_id,
                "executionId": execution_id,
                "includeData": True,
            },
        )
        status = extract_execution_status(payload)
        if status and status != last_status:
            print(Fore.CYAN + f"  status: {status}" + Fore.RESET)
            last_status = status

        if status in TERMINAL_STATUSES:
            return payload

        await asyncio.sleep(POLL_INTERVAL_SEC)

    raise TimeoutError(
        f"Execution {execution_id} did not finish within {POLL_TIMEOUT_SEC}s "
        f"(last status: {last_status!r})"
    )


async def execute_workflow_and_wait(
    client: Client,
    workflow_id: str,
    query: str,
) -> None:
    """Trigger execute_workflow, poll until done, print result or error."""
    print(Fore.YELLOW + "\nTriggering workflow..." + Fore.RESET)
    trigger = await call_n8n_tool(
        client,
        "execute_workflow",
        {
            "workflowId": workflow_id,
            "inputs": {
                "type": "chat",
                "chatInput": query,
            },
        },
    )

    if trigger.get("status") == "error" or not trigger.get("executionId"):
        msg = trigger.get("error") or json.dumps(trigger)
        print(Fore.RED + f"\nFailed to start execution:\n{msg}" + Fore.RESET)
        return

    execution_id = trigger["executionId"]
    print(
        Fore.GREEN
        + f"  Execution {execution_id} started (poll every {POLL_INTERVAL_SEC}s)"
        + Fore.RESET
    )

    print(Fore.YELLOW + "Waiting for workflow to finish..." + Fore.RESET)
    final = await wait_for_execution(client, workflow_id, execution_id)

    final_status = extract_execution_status(final) or "unknown"
    print(Fore.CYAN + f"\n--- Status: {final_status} ---\n" + Fore.RESET)

    if final_status == "success":
        print(Fore.GREEN + extract_response_text(final) + Fore.RESET)
    else:
        print(Fore.RED + extract_error_message(final, trigger) + Fore.RESET)


async def main() -> None:
    client = Client(transport=StreamableHttpTransport(MCP_URL))
    async with client:
        print(Fore.CYAN + f"Connected to {MCP_URL}" + Fore.RESET)
        print(Fore.WHITE + "Type 'exit' at any prompt to quit.\n" + Fore.RESET)

        print(Fore.YELLOW + "Loading workflows you can execute..." + Fore.RESET)
        search = await call_n8n_tool(client, "search_workflows", {"limit": 200})
        all_workflows = search.get("data") or []
        executable = filter_executable_workflows(all_workflows)

        if not executable:
            print(
                Fore.RED
                + "No executable workflows found.\n"
                "  Need: canExecute=true, availableInMCP=true, active=true.\n"
                "  Ask a project admin for workflow:execute, and enable "
                "'Available in MCP' on the workflow."
                + Fore.RESET
            )
            return

        print_executable_workflows(executable)
        workflow = prompt_workflow_choice(executable)
        workflow_id = workflow["id"]
        workflow_name = workflow.get("name", workflow_id)
        print(Fore.GREEN + f"\nSelected: {workflow_name}" + Fore.RESET)

        query = prompt_query()
        await execute_workflow_and_wait(client, workflow_id, query)


if __name__ == "__main__":
    asyncio.run(main())
