#!/usr/bin/env python3
"""
Task queue manager for Claude Code.

Ensures Claude only processes one task at a time.
Other tasks stay queued until the current one completes.

Usage:
    ./task-queue.py next       # Get next task (returns JSON or empty)
    ./task-queue.py status     # Show queue status
    ./task-queue.py clear      # Clear completed tasks
"""

import os
import sys
import json
from pathlib import Path
from datetime import datetime

DATACORE_ROOT = Path(os.environ.get("DATACORE_ROOT", Path.home() / "Data"))
MODULE_DIR = Path(__file__).parent.parent
STATE_FILE = MODULE_DIR / ".queue-state.json"


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


def get_state():
    """Load queue state."""
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except:
            pass
    return {"current_task": None, "completed": []}


def save_state(state):
    """Save queue state."""
    STATE_FILE.write_text(json.dumps(state, indent=2))


def get_pending_tasks():
    """Get all pending (unread) tasks from Claude inbox."""
    username = get_username()
    tasks = []

    for inbox in DATACORE_ROOT.glob(f"*/org/inboxes/{username}-claude.org"):
        try:
            content = inbox.read_text()
            for block in content.split("\n* MESSAGE ")[1:]:
                lines = block.split("\n")
                header = lines[0] if lines else ""

                if ":unread:" not in header:
                    continue

                # Parse properties
                props = {}
                text_lines = []
                in_props = False

                for line in lines[1:]:
                    if ":PROPERTIES:" in line:
                        in_props = True
                    elif ":END:" in line:
                        in_props = False
                    elif in_props and ": " in line:
                        line = line.strip()
                        if line.startswith(":") and ": " in line[1:]:
                            kv = line[1:].split(": ", 1)
                            if len(kv) == 2:
                                props[kv[0].lower()] = kv[1]
                    elif not in_props and line.strip():
                        text_lines.append(line)

                msg_id = props.get("id", "")
                if msg_id:
                    tasks.append({
                        "id": msg_id,
                        "from": props.get("from", "?"),
                        "text": "\n".join(text_lines).strip(),
                        "priority": props.get("priority", "normal"),
                        "inbox": str(inbox)
                    })
        except:
            pass

    # Sort: high priority first, then by ID (chronological)
    tasks.sort(key=lambda t: (0 if t["priority"] == "high" else 1, t["id"]))
    return tasks


def get_working_tasks():
    """Get tasks currently being worked on."""
    username = get_username()
    tasks = []

    for inbox in DATACORE_ROOT.glob(f"*/org/inboxes/{username}-claude.org"):
        try:
            content = inbox.read_text()
            for block in content.split("\n* MESSAGE ")[1:]:
                if ":TASK_STATUS: working" in block:
                    # Parse ID
                    for line in block.split("\n"):
                        if ":ID:" in line:
                            msg_id = line.split(":ID:")[1].strip()
                            tasks.append(msg_id)
                            break
        except:
            pass

    return tasks


def cmd_next():
    """Get next task to process."""
    state = get_state()

    # Check if there's already a task being worked on
    working = get_working_tasks()
    if working:
        print(json.dumps({"status": "busy", "working": working[0]}))
        return

    # Get pending tasks
    pending = get_pending_tasks()
    if not pending:
        print(json.dumps({"status": "empty"}))
        return

    # Return next task
    next_task = pending[0]
    state["current_task"] = next_task["id"]
    save_state(state)

    print(json.dumps({
        "status": "ok",
        "task": next_task,
        "queued": len(pending) - 1
    }))


def cmd_status():
    """Show queue status."""
    working = get_working_tasks()
    pending = get_pending_tasks()
    state = get_state()

    print("Claude Task Queue Status")
    print("=" * 40)

    if working:
        print(f"🔄 Working: {working[0]}")
    else:
        print("🔄 Working: None")

    print(f"📋 Pending: {len(pending)} tasks")
    for task in pending[:5]:
        priority = "[!] " if task["priority"] == "high" else ""
        text = task["text"][:40] + "..." if len(task["text"]) > 40 else task["text"]
        print(f"   {priority}{text}")
        print(f"   └─ from @{task['from']}")

    if len(pending) > 5:
        print(f"   ... and {len(pending) - 5} more")

    print(f"✓ Completed: {len(state.get('completed', []))}")


def cmd_clear():
    """Clear completed tasks from state."""
    state = get_state()
    cleared = len(state.get("completed", []))
    state["completed"] = []
    save_state(state)
    print(f"Cleared {cleared} completed tasks from state")


def main():
    if len(sys.argv) < 2:
        print("Usage: task-queue.py <next|status|clear>")
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == "next":
        cmd_next()
    elif cmd == "status":
        cmd_status()
    elif cmd == "clear":
        cmd_clear()
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)


if __name__ == "__main__":
    main()
