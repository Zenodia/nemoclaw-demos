#!/usr/bin/env python3
"""
Persist a random gateway auth token into /sandbox/.openclaw/openclaw.json.

The OpenClaw gateway loads its auth.token from this config file, NOT from the
CLI --token flag alone (which only sets, not overrides an existing empty value
under mode=token). The TUI sends OPENCLAW_GATEWAY_TOKEN over the wire — it must
match what the gateway reads from this file or the handshake fails with
"unauthorized: gateway token mismatch".

Idempotent: if the file already has a non-empty token, it is preserved unless
--rotate is passed.

Usage (inside the sandbox):
    python3 set_oc_token.py [--rotate]
Prints the token (existing or newly written) on stdout.
"""

import argparse
import json
import pathlib
import secrets
import sys

CFG = pathlib.Path("/sandbox/.openclaw/openclaw.json")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--rotate",
        action="store_true",
        help="Overwrite any existing token with a fresh one",
    )
    args = parser.parse_args()

    if not CFG.is_file():
        print(f"ERROR: {CFG} not found", file=sys.stderr)
        return 1

    data = json.loads(CFG.read_text())
    gateway = data.setdefault("gateway", {})
    auth = gateway.setdefault("auth", {})

    existing = auth.get("token") or ""
    if existing and not args.rotate:
        # Keep existing token to avoid invalidating open sessions
        print(existing)
        return 0

    auth["token"] = secrets.token_hex(32)
    auth["mode"] = "token"
    CFG.write_text(json.dumps(data, indent=2) + "\n")
    print(auth["token"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
