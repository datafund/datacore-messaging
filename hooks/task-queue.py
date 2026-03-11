#!/usr/bin/env python3
"""Task queue hook — query and manage agent task queue."""

import sys
import argparse
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from lib.config import get_username, get_default_space, datacore_root
from lib.agent_inbox import AgentInbox


def main() -> None:
    parser = argparse.ArgumentParser(description="Task queue management")
    parser.add_argument("action", choices=["status", "approve", "reject", "cancel"], help="Queue action")
    parser.add_argument("--task-id", help="Task ID (for approve/reject/cancel)")
    parser.add_argument("--reason", default="", help="Reason (for reject/cancel)")
    args = parser.parse_args()

    username = get_username()
    space = get_default_space()
    space_root = datacore_root() / space
    inbox = AgentInbox(space_root, f"{username}-claude")

    if args.action == "status":
        counts = inbox.counts()
        print(f"Task queue for {username}-claude:")
        print(f"  Queued:  {counts['queued']}")
        print(f"  Working: {counts['working']}")
        print(f"  Waiting: {counts['waiting']}")
        print(f"  Done:    {counts['done']}")
        print(f"  Total:   {counts['total']}")
    elif args.action == "approve" and args.task_id:
        node = inbox.find_by_id(args.task_id)
        if node:
            inbox.approve(node)
            print(f"[messaging] Approved: {args.task_id}")
    elif args.action == "reject" and args.task_id:
        node = inbox.find_by_id(args.task_id)
        if node:
            inbox.reject(node, reason=args.reason)
            print(f"[messaging] Rejected: {args.task_id}")
    elif args.action == "cancel" and args.task_id:
        node = inbox.find_by_id(args.task_id)
        if node:
            inbox.cancel(node, reason=args.reason)
            print(f"[messaging] Cancelled: {args.task_id}")


if __name__ == "__main__":
    main()
