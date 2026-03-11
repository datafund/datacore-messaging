#!/usr/bin/env python3
"""Mark message hook — mark messages as read or archived."""

import sys
import argparse
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from lib.config import get_default_space, datacore_root
from lib.message_store import MessageStore


def main() -> None:
    parser = argparse.ArgumentParser(description="Mark message state")
    parser.add_argument("msg_id", help="Message ID")
    parser.add_argument("action", choices=["read", "archive"], help="Action")
    args = parser.parse_args()

    space = get_default_space()
    space_root = datacore_root() / space
    store = MessageStore(space_root)
    node = store.find_by_id(args.msg_id)
    if not node:
        print(f"[messaging] Message not found: {args.msg_id}")
        return

    if args.action == "read":
        store.mark_read(node)
        print(f"[messaging] Marked read: {args.msg_id}")
    elif args.action == "archive":
        store.archive(node)
        print(f"[messaging] Archived: {args.msg_id}")


if __name__ == "__main__":
    main()
