#!/usr/bin/env python3
"""Inbox watcher hook — checks for queued tasks and claims the next one.

Claude Code hook: runs on prompt_submit to inject task context.
Uses lib/ modules instead of raw file parsing.
"""

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from lib.config import get_username, get_default_space, datacore_root
from lib.agent_inbox import AgentInbox


def main() -> None:
    username = get_username()
    space = get_default_space()
    space_root = datacore_root() / space
    inbox = AgentInbox(space_root, f"{username}-claude")

    working = inbox.find_by_state("WORKING")
    if working:
        task = working[0]
        print(f"[messaging] Task in progress: {task.heading}")
        return

    queued = inbox.find_by_state("QUEUED")
    if not queued:
        return

    task = queued[0]
    inbox.claim(task)
    print(f"[messaging] Claimed task: {task.heading}")
    print(f"  From: {task.properties.get('FROM', 'unknown')}")
    print(f"  Tier: {task.properties.get('TRUST_TIER', 'unknown')}")


if __name__ == "__main__":
    main()
