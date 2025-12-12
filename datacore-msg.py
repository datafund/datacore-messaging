#!/usr/bin/env python3
"""
datacore-msg - Unified messaging app for Datacore

Single process that runs:
- GUI window for sending/receiving messages
- Relay server (if hosting) for real-time delivery
- File watcher for local message sync

Usage:
    python3 datacore-msg.py           # Connect to team relay
    python3 datacore-msg.py --host    # Host relay for team

Requirements:
    pip install PyQt6 websockets pyyaml aiohttp
"""

import sys
import os
import json
import threading
import asyncio
import time
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, field
from typing import Optional

# PyQt6 for GUI
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTextEdit, QLineEdit, QLabel, QFrame
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject
from PyQt6.QtGui import QColor, QTextCursor, QTextCharFormat

# Optional imports
try:
    import websockets
    HAS_WEBSOCKETS = True
except ImportError:
    HAS_WEBSOCKETS = False

try:
    from aiohttp import web, WSMsgType
    HAS_AIOHTTP = True
except ImportError:
    HAS_AIOHTTP = False

try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False

# === CONFIG ===

DATACORE_ROOT = Path(os.environ.get("DATACORE_ROOT", Path.home() / "Data"))
MODULE_DIR = Path(__file__).parent
POLL_INTERVAL = 2000  # ms
RELAY_PORT = 8080


def get_settings() -> dict:
    """Load settings from yaml."""
    if not HAS_YAML:
        return {}

    settings = {}

    # Module settings
    module_settings = MODULE_DIR / "settings.local.yaml"
    if module_settings.exists():
        try:
            settings = yaml.safe_load(module_settings.read_text()) or {}
        except:
            pass

    return settings


def get_username() -> str:
    if "DATACORE_USER" in os.environ:
        return os.environ["DATACORE_USER"]
    conf = get_settings()
    return conf.get("identity", {}).get("name", os.environ.get("USER", "unknown"))


def get_default_space() -> str:
    conf = get_settings()
    space = conf.get("messaging", {}).get("default_space")
    if space:
        return space
    for p in sorted(DATACORE_ROOT.glob("[1-9]-*")):
        if p.is_dir():
            return p.name
    return "1-team"


def get_relay_url() -> str:
    conf = get_settings()
    return conf.get("messaging", {}).get("relay", {}).get("url", "wss://datacore-messaging-relay.datafund.io/ws")


def get_relay_secret() -> str:
    conf = get_settings()
    return conf.get("messaging", {}).get("relay", {}).get("secret", "")


def get_claude_whitelist() -> list:
    conf = get_settings()
    return conf.get("messaging", {}).get("claude_whitelist", [])


def is_relay_enabled() -> bool:
    return bool(get_relay_secret())


# === RELAY SERVER (embedded) ===

@dataclass
class RelayUser:
    username: str
    ws: web.WebSocketResponse
    connected_at: float = field(default_factory=time.time)
    claude_whitelist: list = field(default_factory=list)


class EmbeddedRelay:
    """Lightweight relay server that runs in a thread."""

    def __init__(self, secret: str, port: int = 8080):
        self.secret = secret
        self.port = port
        self.users: dict[str, RelayUser] = {}
        self.app = None
        self.runner = None

    def resolve_claude_target(self, from_user: str, to_user: str) -> tuple:
        if to_user == "claude":
            return (f"{from_user}-claude", True, None)

        if to_user.endswith("-claude"):
            owner = to_user.rsplit("-claude", 1)[0]
            owner_user = self.users.get(owner)
            if owner_user and owner_user.claude_whitelist:
                if from_user not in owner_user.claude_whitelist:
                    return (to_user, False,
                            f"Auto-reply: @{owner}-claude is not accepting messages from @{from_user}.")

        return (to_user, True, None)

    async def route_message(self, from_user: str, to_user: str, message: dict, sender_ws=None):
        resolved, allowed, auto_reply = self.resolve_claude_target(from_user, to_user)

        if not allowed and auto_reply and sender_ws:
            await sender_ws.send_json({
                "type": "message",
                "from": resolved,
                "text": auto_reply,
                "priority": "normal",
                "auto_reply": True
            })
            return "auto_replied"

        recipient = self.users.get(resolved)
        if recipient:
            await recipient.ws.send_json({
                "type": "message",
                "from": from_user,
                **message
            })
            return True
        return False

    async def broadcast_presence(self, username: str, status: str):
        online = list(self.users.keys())
        for user in list(self.users.values()):
            if user.username != username:
                try:
                    await user.ws.send_json({
                        "type": "presence_change",
                        "user": username,
                        "status": status,
                        "online": online
                    })
                except:
                    pass

    async def handle_ws(self, request):
        ws = web.WebSocketResponse(heartbeat=30)
        await ws.prepare(request)
        username = None

        try:
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    try:
                        data = json.loads(msg.data)
                    except:
                        continue

                    msg_type = data.get("type")

                    if msg_type == "auth":
                        if data.get("secret") != self.secret:
                            await ws.send_json({"type": "auth_error", "message": "Invalid secret"})
                            continue

                        username = data.get("username", "")
                        if not username:
                            await ws.send_json({"type": "auth_error", "message": "Username required"})
                            continue

                        # Disconnect old connection
                        if username in self.users:
                            try:
                                await self.users[username].ws.close()
                            except:
                                pass

                        self.users[username] = RelayUser(
                            username=username,
                            ws=ws,
                            claude_whitelist=data.get("claude_whitelist", [])
                        )

                        await ws.send_json({
                            "type": "auth_ok",
                            "username": username,
                            "online": list(self.users.keys())
                        })
                        await self.broadcast_presence(username, "online")

                    elif msg_type == "send" and username:
                        to_user = data.get("to", "").lstrip("@")
                        text = data.get("text", "")

                        if not to_user or not text:
                            continue

                        resolved, _, _ = self.resolve_claude_target(username, to_user)
                        result = await self.route_message(
                            username, to_user,
                            {"text": text, "priority": data.get("priority", "normal"),
                             "msg_id": data.get("msg_id", ""), "timestamp": time.time()},
                            sender_ws=ws
                        )

                        if result == "auto_replied":
                            await ws.send_json({"type": "send_ack", "to": resolved, "delivered": False, "auto_replied": True})
                        else:
                            await ws.send_json({"type": "send_ack", "to": resolved, "delivered": bool(result)})

                    elif msg_type == "presence" and username:
                        await ws.send_json({"type": "presence", "online": list(self.users.keys())})

                    elif msg_type == "ping":
                        await ws.send_json({"type": "pong"})

        finally:
            if username:
                self.users.pop(username, None)
                await self.broadcast_presence(username, "offline")

        return ws

    async def handle_status(self, request):
        return web.json_response({
            "status": "ok",
            "users_online": len(self.users),
            "users": list(self.users.keys())
        })

    async def start(self):
        self.app = web.Application()
        self.app.router.add_get("/", self.handle_status)
        self.app.router.add_get("/status", self.handle_status)
        self.app.router.add_get("/ws", self.handle_ws)

        self.runner = web.AppRunner(self.app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, "0.0.0.0", self.port)
        await site.start()
        print(f"Relay server running on port {self.port}")

    async def stop(self):
        if self.runner:
            await self.runner.cleanup()


# === GUI ===

class SignalBridge(QObject):
    message_received = pyqtSignal(str, str, str, bool, str, bool)
    status_changed = pyqtSignal(str)
    presence_changed = pyqtSignal(list)


class MessageWindow(QMainWindow):
    def __init__(self, host_relay: bool = False):
        super().__init__()

        self.username = get_username()
        self.default_space = get_default_space()
        self.seen_ids = set()
        self.host_relay = host_relay
        self.relay = None
        self.relay_client_ws = None
        self.relay_connected = False
        self.bridge = SignalBridge()

        self.bridge.message_received.connect(self.add_message)
        self.bridge.status_changed.connect(self.update_relay_status)
        self.bridge.presence_changed.connect(self.update_presence)

        self._setup_ui()
        self._load_existing_messages()
        self._start_watcher()
        self._start_relay_thread()

    def _setup_ui(self):
        self.setWindowTitle(f"Messages @{self.username}")
        self.setGeometry(100, 100, 350, 500)
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)

        self.setStyleSheet("""
            QMainWindow { background-color: #1e1e1e; }
            QLabel { color: #d4d4d4; }
            QTextEdit { background-color: #1e1e1e; color: #d4d4d4; border: none; font-family: Menlo; font-size: 12px; }
            QLineEdit { background-color: #333; color: #fff; border: 1px solid #555; border-radius: 4px; padding: 8px; font-family: Menlo; font-size: 12px; }
            QLineEdit:focus { border: 1px solid #569cd6; }
        """)

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        # Header
        header = QHBoxLayout()
        self.user_label = QLabel(f"@{self.username}")
        self.user_label.setStyleSheet("color: #569cd6; font-weight: bold; font-size: 13px;")
        header.addWidget(self.user_label)

        self.status_dot = QLabel(" ●")
        self.status_dot.setStyleSheet("color: #4ec9b0; font-size: 13px;")
        header.addWidget(self.status_dot)
        header.addStretch()

        self.online_label = QLabel("")
        self.online_label.setStyleSheet("color: #666; font-size: 11px;")
        header.addWidget(self.online_label)

        self.relay_label = QLabel("(connecting...)")
        self.relay_label.setStyleSheet("color: #c586c0; font-size: 11px;")
        header.addWidget(self.relay_label)

        layout.addLayout(header)

        # Messages
        self.messages_area = QTextEdit()
        self.messages_area.setReadOnly(True)
        layout.addWidget(self.messages_area, stretch=1)

        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("background-color: #333;")
        layout.addWidget(sep)

        # Input
        self.input_field = QLineEdit()
        self.input_field.setPlaceholderText("@user message (or @claude for your AI)")
        self.input_field.returnPressed.connect(self._send_message)
        layout.addWidget(self.input_field)

        # Status
        mode = "hosting" if self.host_relay else "client"
        self.status_label = QLabel(f"Space: {self.default_space} ({mode})")
        self.status_label.setStyleSheet("color: #666; font-size: 11px;")
        layout.addWidget(self.status_label)

        # Position
        screen = QApplication.primaryScreen().geometry()
        self.move(screen.width() - 370, 40)

    def add_message(self, sender: str, text: str, time_str: str,
                    unread: bool = False, priority: str = "normal", via_relay: bool = False):
        cursor = self.messages_area.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)

        if unread:
            fmt = QTextCharFormat()
            fmt.setForeground(QColor("#f48771"))
            cursor.insertText("● ", fmt)
        else:
            cursor.insertText("  ")

        fmt = QTextCharFormat()
        if sender.startswith("you→"):
            fmt.setForeground(QColor("#4ec9b0"))
        elif sender == "claude" or sender.endswith("-claude"):
            fmt.setForeground(QColor("#c586c0"))
        else:
            fmt.setForeground(QColor("#569cd6"))
        fmt.setFontWeight(700)
        cursor.insertText(f"@{sender} ", fmt)

        fmt = QTextCharFormat()
        fmt.setForeground(QColor("#666"))
        cursor.insertText(f"{time_str}\n", fmt)

        fmt = QTextCharFormat()
        fmt.setForeground(QColor("#d4d4d4"))
        cursor.insertText(f"  {text[:200]}\n\n", fmt)

        self.messages_area.setTextCursor(cursor)
        self.messages_area.ensureCursorVisible()

        if unread:
            self.raise_()
            self.activateWindow()

    def update_relay_status(self, status: str):
        color = "#4ec9b0" if "●" in status else "#c586c0"
        self.relay_label.setStyleSheet(f"color: {color}; font-size: 11px;")
        self.relay_label.setText(f"({status})")

    def update_presence(self, online: list):
        self.online_label.setText(f"{len(online)} online" if online else "")

    def _handle_command(self, cmd: str) -> bool:
        """Handle /commands. Returns True if handled."""
        parts = cmd.strip().split(maxsplit=2)
        cmd_name = parts[0].lower()

        if cmd_name in ("/my-messages", "/messages", "/inbox"):
            self._show_my_messages()
            return True
        elif cmd_name == "/todo":
            self._show_todo_messages()
            return True
        elif cmd_name == "/mark" and len(parts) >= 2:
            # /mark <id> [todo|done|clear]
            msg_id = parts[1]
            action = parts[2].lower() if len(parts) > 2 else "todo"
            self._mark_message(msg_id, action)
            return True
        elif cmd_name == "/clear":
            self.messages_area.clear()
            self.input_field.clear()
            return True
        elif cmd_name in ("/help", "/?"):
            self._show_help()
            return True
        elif cmd_name == "/online":
            self._show_online()
            return True
        return False

    def _show_my_messages(self):
        """Show all unread messages for current user."""
        cursor = self.messages_area.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)

        fmt = QTextCharFormat()
        fmt.setForeground(QColor("#c586c0"))
        fmt.setFontWeight(700)
        cursor.insertText("\n─── My Messages ───\n", fmt)

        unread_count = 0
        messages = []

        # Check all inboxes for this user
        for inbox in DATACORE_ROOT.glob(f"*/org/inboxes/{self.username}.org"):
            try:
                content = inbox.read_text()
                for block in content.split("\n* MESSAGE ")[1:]:
                    msg = self._parse_message(block)
                    if msg and msg.get("unread"):
                        messages.append(msg)
                        unread_count += 1
            except:
                pass

        # Also check claude inbox
        for inbox in DATACORE_ROOT.glob(f"*/org/inboxes/{self.username}-claude.org"):
            try:
                content = inbox.read_text()
                for block in content.split("\n* MESSAGE ")[1:]:
                    msg = self._parse_message(block)
                    if msg and msg.get("unread"):
                        msg["to_claude"] = True
                        messages.append(msg)
                        unread_count += 1
            except:
                pass

        if messages:
            for msg in sorted(messages, key=lambda m: m.get("id", "")):
                fmt = QTextCharFormat()
                fmt.setForeground(QColor("#f48771"))
                cursor.insertText("● ", fmt)

                fmt = QTextCharFormat()
                fmt.setForeground(QColor("#569cd6"))
                fmt.setFontWeight(700)
                cursor.insertText(f"@{msg['from']} ", fmt)

                if msg.get("to_claude"):
                    fmt = QTextCharFormat()
                    fmt.setForeground(QColor("#c586c0"))
                    cursor.insertText("→claude ", fmt)

                fmt = QTextCharFormat()
                fmt.setForeground(QColor("#666"))
                cursor.insertText(f"{msg.get('time', '')}\n", fmt)

                fmt = QTextCharFormat()
                fmt.setForeground(QColor("#d4d4d4"))
                cursor.insertText(f"  {msg['text'][:150]}\n", fmt)
        else:
            fmt = QTextCharFormat()
            fmt.setForeground(QColor("#4ec9b0"))
            cursor.insertText("  No unread messages\n", fmt)

        fmt = QTextCharFormat()
        fmt.setForeground(QColor("#666"))
        cursor.insertText(f"─── {unread_count} unread ───\n\n", fmt)

        self.messages_area.setTextCursor(cursor)
        self.messages_area.ensureCursorVisible()
        self.input_field.clear()

    def _show_help(self):
        """Show available commands."""
        cursor = self.messages_area.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)

        fmt = QTextCharFormat()
        fmt.setForeground(QColor("#c586c0"))
        fmt.setFontWeight(700)
        cursor.insertText("\n─── Commands ───\n", fmt)

        commands = [
            ("@user message", "Send message to user"),
            ("@claude task", "Send task to your Claude"),
            ("/my-messages", "Show unread messages"),
            ("/todo", "Show TODO messages"),
            ("/mark <id> todo", "Mark message as TODO"),
            ("/mark <id> done", "Mark message as done"),
            ("/online", "Show online users"),
            ("/clear", "Clear message area"),
            ("/help", "Show this help"),
        ]

        for cmd, desc in commands:
            fmt = QTextCharFormat()
            fmt.setForeground(QColor("#4ec9b0"))
            cursor.insertText(f"  {cmd:<18}", fmt)

            fmt = QTextCharFormat()
            fmt.setForeground(QColor("#666"))
            cursor.insertText(f" {desc}\n", fmt)

        cursor.insertText("\n")
        self.messages_area.setTextCursor(cursor)
        self.messages_area.ensureCursorVisible()
        self.input_field.clear()

    def _show_online(self):
        """Show online users."""
        cursor = self.messages_area.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)

        fmt = QTextCharFormat()
        fmt.setForeground(QColor("#c586c0"))
        fmt.setFontWeight(700)
        cursor.insertText("\n─── Online Users ───\n", fmt)

        # Request presence from relay
        if self.relay_connected:
            fmt = QTextCharFormat()
            fmt.setForeground(QColor("#4ec9b0"))
            cursor.insertText(f"  (checking relay...)\n", fmt)
        else:
            fmt = QTextCharFormat()
            fmt.setForeground(QColor("#f48771"))
            cursor.insertText("  Not connected to relay\n", fmt)

        cursor.insertText("\n")
        self.messages_area.setTextCursor(cursor)
        self.messages_area.ensureCursorVisible()
        self.input_field.clear()

    def _show_todo_messages(self):
        """Show messages marked as :todo:"""
        cursor = self.messages_area.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)

        fmt = QTextCharFormat()
        fmt.setForeground(QColor("#dcdcaa"))
        fmt.setFontWeight(700)
        cursor.insertText("\n─── TODO Messages ───\n", fmt)

        todo_msgs = []
        done_msgs = []

        # Check all inboxes for this user
        for inbox in DATACORE_ROOT.glob(f"*/org/inboxes/{self.username}.org"):
            try:
                content = inbox.read_text()
                for block in content.split("\n* MESSAGE ")[1:]:
                    msg = self._parse_message(block)
                    if msg:
                        msg["inbox"] = str(inbox)
                        if msg.get("todo"):
                            todo_msgs.append(msg)
                        elif msg.get("done"):
                            done_msgs.append(msg)
            except:
                pass

        # Also check claude inbox
        for inbox in DATACORE_ROOT.glob(f"*/org/inboxes/{self.username}-claude.org"):
            try:
                content = inbox.read_text()
                for block in content.split("\n* MESSAGE ")[1:]:
                    msg = self._parse_message(block)
                    if msg:
                        msg["inbox"] = str(inbox)
                        msg["to_claude"] = True
                        if msg.get("todo"):
                            todo_msgs.append(msg)
                        elif msg.get("done"):
                            done_msgs.append(msg)
            except:
                pass

        if todo_msgs:
            for msg in sorted(todo_msgs, key=lambda m: m.get("id", "")):
                fmt = QTextCharFormat()
                fmt.setForeground(QColor("#dcdcaa"))
                cursor.insertText("☐ ", fmt)

                fmt = QTextCharFormat()
                fmt.setForeground(QColor("#569cd6"))
                fmt.setFontWeight(700)
                cursor.insertText(f"@{msg['from']} ", fmt)

                if msg.get("to_claude"):
                    fmt = QTextCharFormat()
                    fmt.setForeground(QColor("#c586c0"))
                    cursor.insertText("→claude ", fmt)

                fmt = QTextCharFormat()
                fmt.setForeground(QColor("#666"))
                cursor.insertText(f"{msg.get('time', '')}\n", fmt)

                fmt = QTextCharFormat()
                fmt.setForeground(QColor("#d4d4d4"))
                cursor.insertText(f"  {msg['text'][:120]}\n", fmt)

                # Show short ID for marking
                short_id = msg['id'].split('-')[-1] if msg['id'] else ""
                fmt = QTextCharFormat()
                fmt.setForeground(QColor("#666"))
                cursor.insertText(f"  /mark {short_id} done\n", fmt)
        else:
            fmt = QTextCharFormat()
            fmt.setForeground(QColor("#4ec9b0"))
            cursor.insertText("  No TODO messages\n", fmt)

        if done_msgs:
            fmt = QTextCharFormat()
            fmt.setForeground(QColor("#666"))
            cursor.insertText(f"\n  ({len(done_msgs)} done)\n", fmt)

        fmt = QTextCharFormat()
        fmt.setForeground(QColor("#666"))
        cursor.insertText(f"─── {len(todo_msgs)} todo ───\n\n", fmt)

        self.messages_area.setTextCursor(cursor)
        self.messages_area.ensureCursorVisible()
        self.input_field.clear()

    def _mark_message(self, msg_id_part: str, action: str):
        """Mark a message with :todo:, :done:, or clear tags."""
        cursor = self.messages_area.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)

        # Find message by partial ID match
        found = False
        for inbox in DATACORE_ROOT.glob(f"*/org/inboxes/{self.username}*.org"):
            try:
                content = inbox.read_text()
                # Find message with matching ID
                if msg_id_part in content:
                    import re
                    # Match the header line with this message ID
                    pattern = rf'(\* MESSAGE \[[^\]]+\])([^\n]*)(.*?:ID: [^\n]*{re.escape(msg_id_part)}[^\n]*)'

                    def replace_tags(match):
                        header = match.group(1)
                        tags = match.group(2)
                        rest = match.group(3)

                        # Remove existing status tags
                        tags = re.sub(r':(?:unread|todo|done):', '', tags)
                        tags = tags.strip()

                        # Add new tag
                        if action == "todo":
                            new_tag = ":todo:"
                        elif action == "done":
                            new_tag = ":done:"
                        else:  # clear
                            new_tag = ""

                        if new_tag:
                            return f"{header} {new_tag}{rest}"
                        else:
                            return f"{header}{rest}"

                    new_content, count = re.subn(pattern, replace_tags, content, flags=re.DOTALL)
                    if count > 0:
                        inbox.write_text(new_content)
                        found = True

                        fmt = QTextCharFormat()
                        fmt.setForeground(QColor("#4ec9b0"))
                        cursor.insertText(f"\n✓ Marked as {action}: ...{msg_id_part}\n\n", fmt)
                        break
            except Exception as e:
                pass

        if not found:
            fmt = QTextCharFormat()
            fmt.setForeground(QColor("#f48771"))
            cursor.insertText(f"\n✗ Message not found: {msg_id_part}\n\n", fmt)

        self.messages_area.setTextCursor(cursor)
        self.messages_area.ensureCursorVisible()
        self.input_field.clear()

    def _send_message(self):
        text = self.input_field.text().strip()
        if not text:
            return

        # Handle /commands
        if text.startswith("/"):
            if self._handle_command(text):
                return
            # Unknown command, show help
            self._show_help()
            return

        if not text.startswith("@"):
            return

        parts = text.split(" ", 1)
        recipient = parts[0][1:]
        msg_text = parts[1] if len(parts) > 1 else ""

        if not recipient or not msg_text:
            return

        # Resolve @claude locally
        if recipient == "claude":
            recipient = f"{self.username}-claude"

        msg_id = self._write_to_inbox(recipient, msg_text)

        if msg_id:
            # Send via relay
            if self.relay_connected:
                def send():
                    asyncio.run(self._send_via_relay(recipient, msg_text, msg_id))
                threading.Thread(target=send, daemon=True).start()

            self.add_message(f"you→{recipient}", msg_text, datetime.now().strftime("%H:%M"))
            self.input_field.clear()

    async def _send_via_relay(self, to: str, text: str, msg_id: str):
        if not HAS_WEBSOCKETS:
            return
        try:
            async with websockets.connect(get_relay_url()) as ws:
                await ws.send(json.dumps({
                    "type": "auth",
                    "secret": get_relay_secret(),
                    "username": self.username,
                    "claude_whitelist": get_claude_whitelist()
                }))
                await ws.recv()
                await ws.send(json.dumps({
                    "type": "send",
                    "to": to,
                    "text": text,
                    "msg_id": msg_id
                }))
                await ws.recv()
        except:
            pass

    def _write_to_inbox(self, to: str, text: str) -> str:
        try:
            inbox_dir = DATACORE_ROOT / self.default_space / "org/inboxes"
            inbox_dir.mkdir(parents=True, exist_ok=True)
            inbox = inbox_dir / f"{to}.org"

            now = datetime.now()
            msg_id = f"msg-{now.strftime('%Y%m%d-%H%M%S')}-{self.username}"
            timestamp = now.strftime("[%Y-%m-%d %a %H:%M]")

            entry = f"""
* MESSAGE {timestamp} :unread:
:PROPERTIES:
:ID: {msg_id}
:FROM: {self.username}
:TO: {to}
:END:
{text}
"""
            with open(inbox, "a") as f:
                f.write(entry)

            self.seen_ids.add(msg_id)
            return msg_id
        except:
            return None

    def _load_existing_messages(self):
        messages = []
        for inbox in DATACORE_ROOT.glob(f"*/org/inboxes/{self.username}.org"):
            try:
                content = inbox.read_text()
                for block in content.split("\n* MESSAGE ")[1:]:
                    msg = self._parse_message(block)
                    if msg:
                        self.seen_ids.add(msg["id"])
                        messages.append(msg)
            except:
                pass

        for msg in sorted(messages, key=lambda m: m.get("id", ""))[-15:]:
            self.add_message(msg["from"], msg["text"], msg.get("time", ""), msg.get("unread", False))

    def _parse_message(self, block: str) -> dict:
        try:
            lines = block.split("\n")
            header = lines[0]
            is_unread = ":unread:" in header
            is_todo = ":todo:" in header
            is_done = ":done:" in header

            time_str = ""
            if "[" in header and "]" in header:
                ts = header[header.find("[")+1:header.find("]")]
                parts = ts.split(" ")
                if len(parts) >= 4:
                    time_str = parts[3]

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
                    if line.startswith(":"):
                        kv = line[1:].split(": ", 1)
                        if len(kv) == 2:
                            props[kv[0].lower()] = kv[1]
                elif not in_props and line.strip():
                    text_lines.append(line)

            return {
                "id": props.get("id", ""),
                "from": props.get("from", "?"),
                "text": "\n".join(text_lines).strip(),
                "time": time_str,
                "unread": is_unread,
                "todo": is_todo,
                "done": is_done
            }
        except:
            return None

    def _start_watcher(self):
        self.watcher = QTimer(self)
        self.watcher.timeout.connect(self._check_inbox)
        self.watcher.start(POLL_INTERVAL)

    def _check_inbox(self):
        try:
            for inbox in DATACORE_ROOT.glob(f"*/org/inboxes/{self.username}.org"):
                content = inbox.read_text()
                for block in content.split("\n* MESSAGE ")[1:]:
                    msg = self._parse_message(block)
                    if msg and msg["id"] and msg["id"] not in self.seen_ids:
                        self.seen_ids.add(msg["id"])
                        self.add_message(msg["from"], msg["text"], msg.get("time", "now"), True)
        except:
            pass

    def _start_relay_thread(self):
        if not is_relay_enabled():
            self.relay_label.setText("(no secret)")
            return

        if not HAS_WEBSOCKETS:
            self.relay_label.setText("(no websockets)")
            return

        thread = threading.Thread(target=self._relay_thread, daemon=True)
        thread.start()

    def _relay_thread(self):
        async def run():
            # Start embedded relay if hosting
            if self.host_relay and HAS_AIOHTTP:
                self.relay = EmbeddedRelay(get_relay_secret(), RELAY_PORT)
                await self.relay.start()
                self.bridge.status_changed.emit("● hosting")

            # Connect as client
            await self._connect_relay()

        asyncio.run(run())

    async def _connect_relay(self):
        url = get_relay_url()
        secret = get_relay_secret()

        while True:
            try:
                async with websockets.connect(url) as ws:
                    await ws.send(json.dumps({
                        "type": "auth",
                        "secret": secret,
                        "username": self.username,
                        "claude_whitelist": get_claude_whitelist()
                    }))

                    resp = json.loads(await ws.recv())
                    if resp.get("type") == "auth_ok":
                        self.relay_connected = True
                        mode = "● hosting" if self.host_relay else "● relay"
                        self.bridge.status_changed.emit(mode)
                        self.bridge.presence_changed.emit(resp.get("online", []))

                        async for message in ws:
                            data = json.loads(message)
                            if data.get("type") == "message":
                                self.bridge.message_received.emit(
                                    data.get("from", "?"),
                                    data.get("text", ""),
                                    datetime.now().strftime("%H:%M"),
                                    True, "normal", True
                                )
                            elif data.get("type") == "presence_change":
                                self.bridge.presence_changed.emit(data.get("online", []))
                    else:
                        self.bridge.status_changed.emit("auth failed")
                        break

            except Exception as e:
                self.relay_connected = False
                self.bridge.status_changed.emit(f"reconnecting...")
                await asyncio.sleep(5)


def main():
    host_relay = "--host" in sys.argv or "-h" in sys.argv

    if not DATACORE_ROOT.exists():
        print(f"Error: DATACORE_ROOT not found: {DATACORE_ROOT}")
        sys.exit(1)

    app = QApplication(sys.argv)
    app.setApplicationName("Datacore Messages")

    window = MessageWindow(host_relay=host_relay)
    window.show()

    mode = "hosting relay" if host_relay else "connecting"
    print(f"Datacore Messages - @{window.username} ({mode})")

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
