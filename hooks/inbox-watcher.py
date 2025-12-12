#!/usr/bin/env python3
"""
Claude Code hook: Watch tex-claude inbox for new messages.

This hook runs on UserPromptSubmit and checks for unread messages
in the user's Claude inbox. If found, it injects them into context.

Install:
  Add to ~/.claude/settings.json or .claude/settings.local.json:

  {
    "hooks": {
      "UserPromptSubmit": [
        {
          "hooks": [
            {
              "type": "command",
              "command": "/path/to/datacore-messaging/hooks/inbox-watcher.py"
            }
          ]
        }
      ]
    }
  }
"""

import os
import sys
import re
from pathlib import Path
from datetime import datetime

# Config
DATACORE_ROOT = Path(os.environ.get("DATACORE_ROOT", Path.home() / "Data"))

def get_username():
    """Get username from settings or environment."""
    # Try module settings first
    module_settings = Path(__file__).parent.parent / "settings.local.yaml"
    if module_settings.exists():
        try:
            import yaml
            conf = yaml.safe_load(module_settings.read_text()) or {}
            name = conf.get("identity", {}).get("name")
            if name:
                return name
        except:
            pass

    # Fallback to system user
    return os.environ.get("USER", "unknown")

def get_claude_inbox():
    """Get path to user's Claude inbox."""
    username = get_username()
    claude_name = f"{username}-claude"

    # Search all spaces for the inbox
    for inbox in DATACORE_ROOT.glob(f"*/org/inboxes/{claude_name}.org"):
        return inbox

    return None

def parse_messages(content):
    """Parse MESSAGE blocks from org content."""
    messages = []

    for block in content.split("\n* MESSAGE ")[1:]:
        lines = block.split("\n")
        header = lines[0] if lines else ""

        # Check if unread
        if ":unread:" not in header:
            continue

        # Extract timestamp
        time_str = ""
        if "[" in header and "]" in header:
            ts = header[header.find("[")+1:header.find("]")]
            time_str = ts

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
                    key_val = line[1:].split(": ", 1)
                    if len(key_val) == 2:
                        props[key_val[0].lower()] = key_val[1]
            elif not in_props and line.strip():
                text_lines.append(line)

        msg_id = props.get("id", "")
        if msg_id:
            messages.append({
                "id": msg_id,
                "from": props.get("from", "?"),
                "text": "\n".join(text_lines).strip(),
                "time": time_str,
                "priority": props.get("priority", "normal"),
            })

    return messages

def mark_messages_as_working(inbox_path, message_ids):
    """Mark messages as 'working' - remove :unread:, add TASK_STATUS and STARTED_AT."""
    if not inbox_path.exists():
        return

    content = inbox_path.read_text()
    modified = False
    now = datetime.now().strftime("[%Y-%m-%d %a %H:%M]")

    for msg_id in message_ids:
        # Find the message block and update it
        lines = content.split('\n')
        new_lines = []
        i = 0

        while i < len(lines):
            line = lines[i]

            # Check if this MESSAGE block contains our msg_id
            if line.startswith('* MESSAGE [') and ':unread:' in line:
                block_end = min(i + 15, len(lines))
                block_has_id = any(msg_id in lines[j] for j in range(i, block_end))

                if block_has_id:
                    # Remove :unread: tag
                    header = line.replace(' :unread:', '')
                    new_lines.append(header)
                    i += 1

                    # Process properties block
                    while i < len(lines):
                        prop_line = lines[i]
                        new_lines.append(prop_line)

                        if ':END:' in prop_line:
                            # Insert task status properties before :END:
                            new_lines.pop()  # Remove :END: temporarily
                            new_lines.append(f":TASK_STATUS: working")
                            new_lines.append(f":STARTED_AT: {now}")
                            new_lines.append(prop_line)  # Put :END: back
                            i += 1
                            break
                        i += 1

                    modified = True
                    continue

            new_lines.append(line)
            i += 1

        if modified:
            content = '\n'.join(new_lines)

    if modified:
        inbox_path.write_text(content)


def main():
    inbox = get_claude_inbox()

    if not inbox or not inbox.exists():
        # No inbox, nothing to inject
        sys.exit(0)

    try:
        content = inbox.read_text()
    except:
        sys.exit(0)

    messages = parse_messages(content)

    if not messages:
        sys.exit(0)

    # All unread messages are new (we mark them read after showing)
    new_messages = messages

    if not new_messages:
        sys.exit(0)

    # Output new messages to inject into context
    username = get_username()
    print(f"\n📬 New messages for @{username}-claude:\n")

    for msg in new_messages:
        priority_marker = " [!]" if msg["priority"] == "high" else ""
        print(f"From @{msg['from']} ({msg['time']}){priority_marker}:")
        print(f"  {msg['text']}")
        print(f"  [msg-id: {msg['id']}]")
        print()

    print("---")
    print("To reply: use hooks/send-reply.py <user> <message>")
    print("To mark done: use hooks/send-reply.py --complete <msg-id> <user> <message>")
    print("Tasks are now marked as 'working'.")

    # Mark messages as working in the org file
    mark_messages_as_working(inbox, [m["id"] for m in new_messages])

    sys.exit(0)

if __name__ == "__main__":
    main()
