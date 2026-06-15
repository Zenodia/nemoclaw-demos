#!/usr/bin/env python3
"""
Haystack RAG client — sandbox skill component.

The OpenClaw agent (which already has an LLM) decides which operation to call
and with what arguments. This script makes a single HTTP request to the host-side
Haystack RAG server and prints the result to stdout. No NVIDIA_API_KEY needed
in the sandbox — all inference happens on the host.

Usage:
  <skill_dir>/venv/bin/python3 haystack_client.py <command> [options]

Commands:
  index             [--data-dir PATH]
  query             --question TEXT [--top-k N]
  list-documents

Server URL (resolved in order):
  1. --server-url flag
  2. RAG_SERVER_URL env var
  3. Default: http://host.openshell.internal:9004

Always run with the skill venv's Python so the sandbox policy allows the
outbound connection to port 9004. Do NOT use bare python3.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

try:
    import requests
except ImportError as e:
    _skill_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _venv_python = os.path.join(_skill_dir, "venv", "bin", "python3")
    print(
        f"\nMissing dependency: {e}\n"
        "Run this script with the skill venv's Python, not bare python3:\n\n"
        f"  {_venv_python} {__file__} <command> [args]\n\n"
        "If the venv doesn't exist yet, recreate it with:\n\n"
        f"  python3 -m venv {_skill_dir}/venv\n"
        f"  {_skill_dir}/venv/bin/pip install -q requests\n",
        file=sys.stderr,
    )
    sys.exit(1)

_DEFAULT_URL = "http://host.openshell.internal:9004"


def _call(server_url: str, method: str, path: str, payload: dict | None = None) -> dict:
    url = f"{server_url.rstrip('/')}{path}"
    try:
        if method == "GET":
            resp = requests.get(url, timeout=120)
        else:
            resp = requests.post(url, json=payload or {}, timeout=120)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.ConnectionError:
        print(
            f"Error: cannot connect to Haystack RAG server at {server_url}\n"
            "Is the server running on the host? Check: curl http://host.openshell.internal:9004/health\n"
            "Confirm the sandbox policy allows egress to port 9004.",
            file=sys.stderr,
        )
        sys.exit(1)
    except requests.exceptions.HTTPError as exc:
        detail = ""
        try:
            detail = exc.response.json().get("detail", "")
        except Exception:
            pass
        print(f"Error from server: {detail or exc}", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        print(f"Unexpected error: {exc}", file=sys.stderr)
        sys.exit(1)


def main() -> None:
    root = argparse.ArgumentParser(
        description="Call the Haystack RAG server running on the host.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    root.add_argument(
        "--server-url",
        default=os.environ.get("RAG_SERVER_URL", _DEFAULT_URL),
        help="Base URL of the Haystack RAG server.",
    )

    sub = root.add_subparsers(dest="command", metavar="<command>", required=True)

    # index
    p_index = sub.add_parser(
        "index",
        help="Embed and index documents from the server's data directory.",
    )
    p_index.add_argument(
        "--data-dir",
        default=None,
        help="Override the server's default data directory (host-side path).",
    )

    # query
    p_query = sub.add_parser(
        "query",
        help="Answer a question using RAG over the indexed documents.",
    )
    p_query.add_argument("--question", required=True, help="Natural language question.")
    p_query.add_argument(
        "--top-k",
        type=int,
        default=5,
        help="Number of document chunks to retrieve.",
    )

    # list-documents
    sub.add_parser(
        "list-documents",
        help="List all indexed source files and their chunk counts.",
    )

    parsed = root.parse_args()
    server_url = parsed.server_url

    if parsed.command == "index":
        payload: dict = {}
        if parsed.data_dir:
            payload["data_dir"] = parsed.data_dir
        result = _call(server_url, "POST", "/index", payload)
        print(
            f"Indexed {result['indexed']} new chunk(s) from {result['files']} file(s).\n"
            f"Total chunks in store: {result['total']}\n"
            f"Store: {result['store_path']}"
        )

    elif parsed.command == "query":
        result = _call(server_url, "POST", "/query", {
            "question": parsed.question,
            "top_k": parsed.top_k,
        })
        print(result["answer"])
        if result.get("sources"):
            print("\nSources:")
            for src in result["sources"]:
                print(f"  {src}")

    elif parsed.command == "list-documents":
        result = _call(server_url, "GET", "/documents")
        if not result["sources"]:
            print("No documents indexed.")
        else:
            print(f"Total chunks: {result['total_chunks']}")
            print(f"Sources ({len(result['sources'])}):")
            for src, count in sorted(result["sources"].items()):
                print(f"  {src}: {count} chunk(s)")


if __name__ == "__main__":
    main()
