#!/usr/bin/env python3
"""Send reply hook — creates outgoing messages and completes agent tasks."""

import sys
import argparse
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from lib.config import get_username, get_default_space, datacore_root
from lib.message_store import MessageStore
from lib.agent_inbox import AgentInbox


def main() -> None:
    parser = argparse.ArgumentParser(description="Send a reply")
    parser.add_argument("to", help="Recipient actor ID")
    parser.add_argument("content", help="Message content")
    parser.add_argument("--reply-to", help="Message ID to reply to")
    parser.add_argument("--complete-task", help="Task ID to mark complete")
    parser.add_argument("--tokens", type=int, default=0, help="Tokens used")
    args = parser.parse_args()

    username = get_username()
    space = get_default_space()
    space_root = datacore_root() / space

    store = MessageStore(space_root)
    msg = store.create_message(
        from_actor=username, to_actor=args.to,
        content=args.content, reply_to=args.reply_to,
    )
    print(f"[messaging] Sent: {msg.properties['ID']}")

    if args.complete_task:
        inbox = AgentInbox(space_root, f"{username}-claude")
        node = inbox.find_by_id(args.complete_task)
        if node and node.todo == "WORKING":
            inbox.complete(node, tokens_used=args.tokens)
            print(f"[messaging] Completed task: {args.complete_task}")


if __name__ == "__main__":
    main()
