#!/usr/bin/env python3
"""
Helper script for Claude to send replies via the messaging system.

Usage:
    ./send-reply.py <to_user> <message>
    ./send-reply.py --reply-to <msg-id> <to_user> <message>
    ./send-reply.py --complete <msg-id> <to_user> <message>
    ./send-reply.py --route <dest> <to_user> <message>

Routing destinations:
    --route github:123          Post to GitHub issue #123
    --route file:path/to.md     Append to file
    --route @user               CC to another user

Example:
    ./send-reply.py tex "I've completed the task you requested!"
    ./send-reply.py --reply-to msg-20251212-143000-tex tex "Here's the follow-up"
    ./send-reply.py --complete msg-20251212-143000-gregor gregor "Task complete! See results."
    ./send-reply.py --route github:42 gregor "Fixed in PR #50"
    ./send-reply.py --route file:research/analysis.md gregor "Research complete"
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


def get_thread_for_message(msg_id):
    """Find thread ID for a message."""
    for inbox in DATACORE_ROOT.glob("*/org/inboxes/*.org"):
        try:
            content = inbox.read_text()
            if msg_id not in content:
                continue
            for block in content.split("\n* MESSAGE ")[1:]:
                if msg_id in block:
                    for line in block.split("\n"):
                        if ":THREAD:" in line:
                            return line.split(":THREAD:")[1].strip()
                    return None
        except:
            pass
    return None


def mark_task_done(msg_id):
    """Mark a task message as done with completion timestamp."""
    now = datetime.now().strftime("[%Y-%m-%d %a %H:%M]")

    for inbox in DATACORE_ROOT.glob("*/org/inboxes/*.org"):
        try:
            content = inbox.read_text()
            if msg_id not in content:
                continue

            lines = content.split('\n')
            new_lines = []
            modified = False
            i = 0

            while i < len(lines):
                line = lines[i]

                # Check if this MESSAGE block contains our msg_id
                if line.startswith('* MESSAGE ['):
                    block_end = min(i + 20, len(lines))
                    block_has_id = any(msg_id in lines[j] for j in range(i, block_end))

                    if block_has_id:
                        # Add :done: tag if not present
                        if ':done:' not in line:
                            line = line.rstrip() + ' :done:'
                        new_lines.append(line)
                        i += 1

                        # Process properties block
                        while i < len(lines):
                            prop_line = lines[i]

                            # Update TASK_STATUS if present
                            if ':TASK_STATUS:' in prop_line:
                                new_lines.append(':TASK_STATUS: done')
                                i += 1
                                continue

                            if ':END:' in prop_line:
                                # Add COMPLETED_AT before :END:
                                new_lines.append(f":COMPLETED_AT: {now}")
                                new_lines.append(prop_line)
                                i += 1
                                break

                            new_lines.append(prop_line)
                            i += 1

                        modified = True
                        continue

                new_lines.append(line)
                i += 1

            if modified:
                inbox.write_text('\n'.join(new_lines))
                return True

        except Exception as e:
            pass

    return False


def write_to_inbox(to_user, text, reply_to=None):
    """Write message to local inbox."""
    space = get_default_space()
    inbox_dir = DATACORE_ROOT / space / "org/inboxes"
    inbox_dir.mkdir(parents=True, exist_ok=True)
    inbox = inbox_dir / f"{to_user}.org"

    now = datetime.now()
    username = get_username()
    msg_id = f"msg-{now.strftime('%Y%m%d-%H%M%S')}-{username}"
    timestamp = now.strftime("[%Y-%m-%d %a %H:%M]")

    # Build properties
    props = [
        f":ID: {msg_id}",
        f":FROM: {username}",
        f":TO: {to_user}",
        ":PRIORITY: normal"
    ]

    # Handle threading
    thread_id = None
    if reply_to:
        thread_id = get_thread_for_message(reply_to)
        if not thread_id:
            thread_id = f"thread-{reply_to}"
        props.append(f":THREAD: {thread_id}")
        props.append(f":REPLY_TO: {reply_to}")

    props_str = "\n".join(props)
    entry = f"""
* MESSAGE {timestamp} :unread:
:PROPERTIES:
{props_str}
:END:
{text}
"""

    with open(inbox, "a") as f:
        f.write(entry)

    return msg_id, thread_id


def route_to_github(issue_num, text, username):
    """Post comment to GitHub issue."""
    import subprocess

    try:
        # Use gh CLI to post comment
        result = subprocess.run(
            ["gh", "issue", "comment", str(issue_num), "--body", text],
            capture_output=True,
            text=True
        )
        if result.returncode == 0:
            print(f"✓ Posted to GitHub issue #{issue_num}")
            return True
        else:
            print(f"⚠ GitHub error: {result.stderr}")
            return False
    except FileNotFoundError:
        print("⚠ GitHub CLI (gh) not found. Install with: brew install gh")
        return False
    except Exception as e:
        print(f"⚠ GitHub routing failed: {e}")
        return False


def route_to_file(filepath, text, username):
    """Append message to file."""
    try:
        # Resolve path relative to DATACORE_ROOT
        if not filepath.startswith("/"):
            full_path = DATACORE_ROOT / get_default_space() / filepath
        else:
            full_path = Path(filepath)

        full_path.parent.mkdir(parents=True, exist_ok=True)

        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        entry = f"\n\n## {username} ({now})\n\n{text}\n"

        with open(full_path, "a") as f:
            f.write(entry)

        print(f"✓ Appended to {full_path}")
        return True
    except Exception as e:
        print(f"⚠ File routing failed: {e}")
        return False


def route_to_user(cc_user, text, reply_to=None):
    """CC message to another user."""
    msg_id, thread_id = write_to_inbox(cc_user, text, reply_to=reply_to)
    print(f"✓ CC'd to @{cc_user} (id: {msg_id})")
    return msg_id, thread_id


async def send_via_relay(to_user, text, msg_id, thread_id=None, reply_to=None):
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
            msg = {
                "type": "send",
                "to": to_user,
                "text": text,
                "msg_id": msg_id,
                "priority": "normal"
            }
            if thread_id:
                msg["thread"] = thread_id
            if reply_to:
                msg["reply_to"] = reply_to

            await ws.send(json.dumps(msg))
            response = json.loads(await ws.recv())
            return response.get("delivered", False)

    except Exception as e:
        print(f"Relay error: {e}", file=sys.stderr)
        return False


def main():
    args = sys.argv[1:]
    reply_to = None
    complete_id = None
    route_dest = None

    # Parse --reply-to flag
    if "--reply-to" in args:
        idx = args.index("--reply-to")
        if idx + 1 < len(args):
            reply_to = args[idx + 1]
            args = args[:idx] + args[idx + 2:]

    # Parse --complete flag
    if "--complete" in args:
        idx = args.index("--complete")
        if idx + 1 < len(args):
            complete_id = args[idx + 1]
            # --complete implies --reply-to for threading
            if not reply_to:
                reply_to = complete_id
            args = args[:idx] + args[idx + 2:]

    # Parse --route flag
    if "--route" in args:
        idx = args.index("--route")
        if idx + 1 < len(args):
            route_dest = args[idx + 1]
            args = args[:idx] + args[idx + 2:]

    if len(args) < 2:
        print("Usage: send-reply.py [--reply-to <msg-id>] [--complete <msg-id>] [--route <dest>] <to_user> <message>", file=sys.stderr)
        print("\nRouting destinations:")
        print("  github:123    Post to GitHub issue #123")
        print("  file:path.md  Append to file")
        print("  @user         CC to another user")
        sys.exit(1)

    to_user = args[0]
    text = " ".join(args[1:])
    username = get_username()

    # Mark original task as done if --complete specified
    if complete_id:
        if mark_task_done(complete_id):
            print(f"✓ Task {complete_id} marked as done")
        else:
            print(f"⚠ Could not find task {complete_id} to mark done")

    # Handle routing
    if route_dest:
        if route_dest.startswith("github:"):
            issue_num = route_dest.split(":")[1]
            route_to_github(issue_num, text, username)
        elif route_dest.startswith("file:"):
            filepath = route_dest.split(":", 1)[1]
            route_to_file(filepath, text, username)
        elif route_dest.startswith("@"):
            cc_user = route_dest[1:]
            route_to_user(cc_user, text, reply_to=reply_to)

    # Write to local inbox (primary recipient)
    msg_id, thread_id = write_to_inbox(to_user, text, reply_to=reply_to)
    print(f"Message saved to inbox (id: {msg_id})")
    if thread_id:
        print(f"Thread: {thread_id}")

    # Try relay
    if HAS_WEBSOCKETS:
        delivered = asyncio.run(send_via_relay(to_user, text, msg_id, thread_id, reply_to))
        if delivered:
            print(f"Delivered via relay to @{to_user}")
        else:
            print(f"Queued for @{to_user} (not online)")
    else:
        print("Relay unavailable (no websockets)")


if __name__ == "__main__":
    main()
