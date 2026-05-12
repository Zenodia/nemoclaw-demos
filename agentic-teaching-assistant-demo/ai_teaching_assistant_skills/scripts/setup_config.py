#!/usr/bin/env python3
"""
Setup script for the AI Teaching Assistant skill.

Creates config.json with mandatory variables (user_id, server_url) so the
ta_client.py script can be invoked without passing them every time.

Usage:
    python3 scripts/setup_config.py [--user-id USER] [--server-url URL]

If flags are not provided, prompts interactively.
"""

import argparse
import json
import sys
from pathlib import Path

_SKILL_DIR = Path(__file__).resolve().parent.parent
_CONFIG_PATH = _SKILL_DIR / "config.json"
_DEFAULT_SERVER_URL = "http://host.openshell.internal:8999/mcp"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate config.json for the AI Teaching Assistant skill"
    )
    parser.add_argument("--user-id", help="Your user ID on the Teaching Assistant platform")
    parser.add_argument("--server-url", help=f"MCP server URL (default: {_DEFAULT_SERVER_URL})")
    args = parser.parse_args()

    # Load existing config if present (to preserve any extra fields)
    existing: dict = {}
    if _CONFIG_PATH.is_file():
        try:
            existing = json.loads(_CONFIG_PATH.read_text())
            print(f"Found existing config at {_CONFIG_PATH}")
        except (json.JSONDecodeError, OSError):
            pass

    # Resolve user_id
    user_id = args.user_id
    if not user_id:
        default = existing.get("user_id", "")
        prompt = f"User ID [{default}]: " if default else "User ID (required): "
        user_id = input(prompt).strip() or default
    if not user_id:
        print("Error: user_id is required.", file=sys.stderr)
        sys.exit(1)

    # Resolve server_url
    server_url = args.server_url
    if not server_url:
        default = existing.get("server_url", _DEFAULT_SERVER_URL)
        server_url = input(f"Server URL [{default}]: ").strip() or default

    # Write config
    config = {**existing, "user_id": user_id, "server_url": server_url}
    _CONFIG_PATH.write_text(json.dumps(config, indent=2) + "\n")
    print(f"\n✅ Config written to {_CONFIG_PATH}")
    print(json.dumps(config, indent=2))


if __name__ == "__main__":
    main()
