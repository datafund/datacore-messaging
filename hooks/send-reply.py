#!/usr/bin/env python3
"""
Helper script for Claude to send replies via the messaging system.

Usage:
    ./send-reply.py <to_user> <message>

Example:
    ./send-reply.py tex "I've completed the task you requested!"
"""

import os
import sys
import json
import asyncio
from pathlib import Path
from datetime import datetime

# Try websockets for relay
try:
    import websockets
    HAS_WEBSOCKETS = True
except ImportError:
    HAS_WEBSOCKETS = False

DATACORE_ROOT = Path(os.environ.get("DATACORE_ROOT", Path.home() / "Data"))
MODULE_DIR = Path(__file__).parent.parent


def get_settings():
    """Load settings."""
    module_settings = MODULE_DIR / "settings.local.yaml"
    if module_settings.exists():
        try:
            import yaml
            return yaml.safe_load(module_settings.read_text()) or {}
        except:
            pass
    return {}


def get_username():
    """Get Claude's username (user-claude)."""
    conf = get_settings()
    user = conf.get("identity", {}).get("name", os.environ.get("USER", "unknown"))
    return f"{user}-claude"


def get_default_space():
    """Get default space."""
    conf = get_settings()
    space = conf.get("messaging", {}).get("default_space")
    if space:
        return space
    for p in sorted(DATACORE_ROOT.glob("[1-9]-*")):
        if p.is_dir():
            return p.name
    return "1-team"


def write_to_inbox(to_user, text):
    """Write message to local inbox."""
    space = get_default_space()
    inbox_dir = DATACORE_ROOT / space / "org/inboxes"
    inbox_dir.mkdir(parents=True, exist_ok=True)
    inbox = inbox_dir / f"{to_user}.org"

    now = datetime.now()
    username = get_username()
    msg_id = f"msg-{now.strftime('%Y%m%d-%H%M%S')}-{username}"
    timestamp = now.strftime("[%Y-%m-%d %a %H:%M]")

    entry = f"""
* MESSAGE {timestamp} :unread:
:PROPERTIES:
:ID: {msg_id}
:FROM: {username}
:TO: {to_user}
:PRIORITY: normal
:END:
{text}
"""

    with open(inbox, "a") as f:
        f.write(entry)

    return msg_id


async def send_via_relay(to_user, text, msg_id):
    """Send via WebSocket relay."""
    conf = get_settings()
    relay_conf = conf.get("messaging", {}).get("relay", {})
    url = relay_conf.get("url")
    secret = relay_conf.get("secret")

    if not url or not secret:
        return False

    try:
        async with websockets.connect(url) as ws:
            # Auth
            await ws.send(json.dumps({
                "type": "auth",
                "secret": secret,
                "username": get_username()
            }))
            response = json.loads(await ws.recv())

            if response.get("type") != "auth_ok":
                return False

            # Send
            await ws.send(json.dumps({
                "type": "send",
                "to": to_user,
                "text": text,
                "msg_id": msg_id,
                "priority": "normal"
            }))
            response = json.loads(await ws.recv())
            return response.get("delivered", False)

    except Exception as e:
        print(f"Relay error: {e}", file=sys.stderr)
        return False


def main():
    if len(sys.argv) < 3:
        print("Usage: send-reply.py <to_user> <message>", file=sys.stderr)
        sys.exit(1)

    to_user = sys.argv[1]
    text = " ".join(sys.argv[2:])

    # Write to local inbox
    msg_id = write_to_inbox(to_user, text)
    print(f"Message saved to inbox (id: {msg_id})")

    # Try relay
    if HAS_WEBSOCKETS:
        delivered = asyncio.run(send_via_relay(to_user, text, msg_id))
        if delivered:
            print(f"Delivered via relay to @{to_user}")
        else:
            print(f"Queued for @{to_user} (not online)")
    else:
        print("Relay unavailable (no websockets)")


if __name__ == "__main__":
    main()
