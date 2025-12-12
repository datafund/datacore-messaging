#!/usr/bin/env python3
"""
Helper script for Claude to mark messages as todo/done/read.

Usage:
    ./mark-message.py <msg-id> <status>

    status: todo, done, read (clears tags)

Example:
    ./mark-message.py 151230 todo
    ./mark-message.py msg-20251212-151230-tex done
"""

import os
import sys
import re
from pathlib import Path

DATACORE_ROOT = Path(os.environ.get("DATACORE_ROOT", Path.home() / "Data"))
MODULE_DIR = Path(__file__).parent.parent


def get_username():
    """Get username from settings."""
    module_settings = MODULE_DIR / "settings.local.yaml"
    if module_settings.exists():
        try:
            import yaml
            conf = yaml.safe_load(module_settings.read_text()) or {}
            name = conf.get("identity", {}).get("name")
            if name:
                return name
        except:
            pass
    return os.environ.get("USER", "unknown")


def mark_message(msg_id_part: str, action: str) -> bool:
    """Mark a message with the given status."""
    username = get_username()

    for inbox in DATACORE_ROOT.glob(f"*/org/inboxes/{username}*.org"):
        try:
            content = inbox.read_text()
            if msg_id_part in content:
                pattern = rf'(\* MESSAGE \[[^\]]+\])([^\n]*)(.*?:ID: [^\n]*{re.escape(msg_id_part)}[^\n]*)'

                def replace_tags(match):
                    header = match.group(1)
                    tags = match.group(2)
                    rest = match.group(3)
                    tags = re.sub(r':(?:unread|todo|done):', '', tags).strip()

                    if action == "todo":
                        return f"{header} :todo:{rest}"
                    elif action == "done":
                        return f"{header} :done:{rest}"
                    else:  # read/clear
                        return f"{header}{rest}"

                new_content, count = re.subn(pattern, replace_tags, content, flags=re.DOTALL)
                if count > 0:
                    inbox.write_text(new_content)
                    return True
        except Exception as e:
            print(f"Error processing {inbox}: {e}", file=sys.stderr)

    return False


def main():
    if len(sys.argv) < 3:
        print("Usage: mark-message.py <msg-id> <status>", file=sys.stderr)
        print("  status: todo, done, read", file=sys.stderr)
        sys.exit(1)

    msg_id = sys.argv[1]
    action = sys.argv[2].lower()

    if action not in ("todo", "done", "read", "clear"):
        print(f"Invalid status: {action}", file=sys.stderr)
        print("  Use: todo, done, or read", file=sys.stderr)
        sys.exit(1)

    if action == "clear":
        action = "read"

    if mark_message(msg_id, action):
        print(f"✓ Marked as {action}: {msg_id}")
    else:
        print(f"✗ Message not found: {msg_id}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
