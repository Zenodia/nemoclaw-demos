#!/usr/bin/env python3
"""
Setup script for the n8n Workflow skill.

Creates config.json with the wrapper server URL and polling tunables so
n8n_client.py can be invoked without passing them every time.

Usage:
    python3 scripts/setup_config.py [--server-url URL] \
                                    [--poll-interval SECS] \
                                    [--poll-timeout SECS]

If flags are not provided, prompts interactively.
"""

import argparse
import json
import sys
from pathlib import Path

_SKILL_DIR = Path(__file__).resolve().parent.parent
_CONFIG_PATH = _SKILL_DIR / "config.json"

_DEFAULT_SERVER_URL = "http://host.openshell.internal:4300/mcp"
_DEFAULT_POLL_INTERVAL = 3.0
_DEFAULT_POLL_TIMEOUT = 600.0


def _prompt(label: str, default) -> str:
    raw = input(f"{label} [{default}]: ").strip()
    return raw or str(default)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate config.json for the n8n Workflow skill"
    )
    parser.add_argument("--server-url", help=f"MCP wrapper URL (default: {_DEFAULT_SERVER_URL})")
    parser.add_argument("--poll-interval", type=float, help="Polling cadence in seconds (default: 3)")
    parser.add_argument("--poll-timeout", type=float, help="Max time to wait for a run (default: 600)")
    parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="Do not prompt; fall back to defaults / existing values for missing flags",
    )
    args = parser.parse_args()

    existing: dict = {}
    if _CONFIG_PATH.is_file():
        try:
            existing = json.loads(_CONFIG_PATH.read_text())
            print(f"Found existing config at {_CONFIG_PATH}")
        except (json.JSONDecodeError, OSError):
            pass

    # server_url
    server_url = args.server_url
    if not server_url:
        default = existing.get("server_url", _DEFAULT_SERVER_URL)
        server_url = default if args.non_interactive else _prompt("Server URL", default)

    # poll_interval
    poll_interval = args.poll_interval
    if poll_interval is None:
        default = existing.get("poll_interval_sec", _DEFAULT_POLL_INTERVAL)
        if args.non_interactive:
            poll_interval = float(default)
        else:
            poll_interval = float(_prompt("Poll interval (sec)", default))

    # poll_timeout
    poll_timeout = args.poll_timeout
    if poll_timeout is None:
        default = existing.get("poll_timeout_sec", _DEFAULT_POLL_TIMEOUT)
        if args.non_interactive:
            poll_timeout = float(default)
        else:
            poll_timeout = float(_prompt("Poll timeout (sec)", default))

    if poll_interval <= 0:
        print("Error: poll_interval must be > 0", file=sys.stderr)
        sys.exit(1)
    if poll_timeout <= 0:
        print("Error: poll_timeout must be > 0", file=sys.stderr)
        sys.exit(1)

    config = {
        **existing,
        "server_url": server_url,
        "poll_interval_sec": poll_interval,
        "poll_timeout_sec": poll_timeout,
    }
    _CONFIG_PATH.write_text(json.dumps(config, indent=2) + "\n")
    print(f"\n✅ Config written to {_CONFIG_PATH}")
    print(json.dumps(config, indent=2))


if __name__ == "__main__":
    main()
