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
    QTextEdit, QLineEdit, QLabel, QFrame, QScrollArea, QPushButton,
    QSizePolicy
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
    return conf.get("messaging", {}).get("relay", {}).get("url", "wss://datacore-messaging-relay.datafund.ai/ws")


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
    status: str = "online"  # online, busy, away, focusing


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
        """Broadcast presence/status change to all connected users."""
        # Build online list with statuses
        online_with_status = {u: self.users[u].status for u in self.users}
        for user in list(self.users.values()):
            if user.username != username:
                try:
                    await user.ws.send_json({
                        "type": "presence_change",
                        "user": username,
                        "status": status,
                        "online": list(self.users.keys()),
                        "statuses": online_with_status
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

                        initial_status = data.get("status", "online")
                        self.users[username] = RelayUser(
                            username=username,
                            ws=ws,
                            claude_whitelist=data.get("claude_whitelist", []),
                            status=initial_status
                        )

                        # Build online list with statuses
                        online_with_status = {u: self.users[u].status for u in self.users}
                        await ws.send_json({
                            "type": "auth_ok",
                            "username": username,
                            "online": list(self.users.keys()),
                            "statuses": online_with_status
                        })
                        await self.broadcast_presence(username, initial_status)

                    elif msg_type == "send" and username:
                        to_user = data.get("to", "").lstrip("@")
                        text = data.get("text", "")

                        if not to_user or not text:
                            continue

                        resolved, _, _ = self.resolve_claude_target(username, to_user)
                        msg_payload = {
                            "text": text,
                            "priority": data.get("priority", "normal"),
                            "msg_id": data.get("msg_id", ""),
                            "timestamp": time.time()
                        }
                        # Include threading info if present
                        if data.get("thread"):
                            msg_payload["thread"] = data["thread"]
                        if data.get("reply_to"):
                            msg_payload["reply_to"] = data["reply_to"]

                        result = await self.route_message(
                            username, to_user, msg_payload, sender_ws=ws
                        )

                        if result == "auto_replied":
                            await ws.send_json({"type": "send_ack", "to": resolved, "delivered": False, "auto_replied": True})
                        else:
                            await ws.send_json({"type": "send_ack", "to": resolved, "delivered": bool(result)})

                    elif msg_type == "presence" and username:
                        online_with_status = {u: self.users[u].status for u in self.users}
                        await ws.send_json({
                            "type": "presence",
                            "online": list(self.users.keys()),
                            "statuses": online_with_status
                        })

                    elif msg_type == "status_change" and username:
                        new_status = data.get("status", "online")
                        if new_status in ("online", "busy", "away", "focusing"):
                            self.users[username].status = new_status
                            await self.broadcast_presence(username, new_status)
                            await ws.send_json({"type": "status_ok", "status": new_status})

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

class MessageRow(QFrame):
    """A message row with status button and delete button."""
    status_clicked = pyqtSignal(str, str)  # msg_id, current_status
    delete_clicked = pyqtSignal(str)  # msg_id

    def __init__(self, msg_data: dict, parent=None):
        super().__init__(parent)
        self.msg_data = msg_data
        self.msg_id = msg_data.get("id", "")

        self.setStyleSheet("""
            MessageRow { background-color: #252526; border-radius: 4px; margin: 2px 0; }
            MessageRow:hover { background-color: #2d2d2d; }
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(8)

        # Status button (left side)
        self.status_btn = QPushButton()
        self.status_btn.setFixedSize(24, 24)
        self.status_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.status_btn.clicked.connect(self._on_status_click)
        self._update_status_button()
        layout.addWidget(self.status_btn)

        # Message content (middle)
        content = QVBoxLayout()
        content.setSpacing(2)

        # Header: sender + time
        header = QHBoxLayout()
        sender = msg_data.get("from", "?")
        sender_label = QLabel(f"@{sender}")
        sender_color = "#c586c0" if sender.endswith("-claude") else "#569cd6"
        sender_label.setStyleSheet(f"color: {sender_color}; font-weight: bold; font-size: 12px;")
        header.addWidget(sender_label)

        if msg_data.get("to_claude"):
            claude_label = QLabel("→claude")
            claude_label.setStyleSheet("color: #c586c0; font-size: 11px;")
            header.addWidget(claude_label)

        header.addStretch()

        time_label = QLabel(msg_data.get("time", ""))
        time_label.setStyleSheet("color: #666; font-size: 11px;")
        header.addWidget(time_label)

        content.addLayout(header)

        # Message text
        text = msg_data.get("text", "")[:150]
        text_label = QLabel(text)
        text_label.setWordWrap(True)
        text_label.setStyleSheet("color: #d4d4d4; font-size: 12px;")
        content.addWidget(text_label)

        layout.addLayout(content, stretch=1)

        # Delete button (right side)
        self.delete_btn = QPushButton("×")
        self.delete_btn.setFixedSize(24, 24)
        self.delete_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.delete_btn.setStyleSheet("""
            QPushButton { background: transparent; color: #666; font-size: 16px; border: none; }
            QPushButton:hover { color: #f48771; }
        """)
        self.delete_btn.clicked.connect(self._on_delete_click)
        layout.addWidget(self.delete_btn)

    def _update_status_button(self):
        """Update button appearance based on message status."""
        if self.msg_data.get("unread"):
            self.status_btn.setText("●")
            self.status_btn.setStyleSheet("""
                QPushButton { background: transparent; color: #f48771; font-size: 16px; border: none; }
                QPushButton:hover { color: #dcdcaa; }
            """)
            self.status_btn.setToolTip("Click to mark as TODO")
        elif self.msg_data.get("todo"):
            self.status_btn.setText("☐")
            self.status_btn.setStyleSheet("""
                QPushButton { background: transparent; color: #dcdcaa; font-size: 16px; border: none; }
                QPushButton:hover { color: #4ec9b0; }
            """)
            self.status_btn.setToolTip("Click to mark as done")
        elif self.msg_data.get("done"):
            self.status_btn.setText("✓")
            self.status_btn.setStyleSheet("""
                QPushButton { background: transparent; color: #4ec9b0; font-size: 16px; border: none; }
                QPushButton:hover { color: #666; }
            """)
            self.status_btn.setToolTip("Click to clear")
        else:
            self.status_btn.setText("○")
            self.status_btn.setStyleSheet("""
                QPushButton { background: transparent; color: #666; font-size: 16px; border: none; }
                QPushButton:hover { color: #dcdcaa; }
            """)
            self.status_btn.setToolTip("Click to mark as TODO")

    def _on_status_click(self):
        status = "unread" if self.msg_data.get("unread") else \
                 "todo" if self.msg_data.get("todo") else \
                 "done" if self.msg_data.get("done") else "read"

        # Cycle visual status immediately
        self._cycle_status_visual()

        # Emit signal to update the org file
        self.status_clicked.emit(self.msg_id, status)

    def _cycle_status_visual(self):
        """Cycle to next status visually."""
        # Update internal data
        if self.msg_data.get("unread"):
            self.msg_data["unread"] = False
            self.msg_data["todo"] = True
        elif self.msg_data.get("todo"):
            self.msg_data["todo"] = False
            self.msg_data["done"] = True
        elif self.msg_data.get("done"):
            self.msg_data["done"] = False
        else:
            self.msg_data["todo"] = True
        # Update button appearance
        self._update_status_button()

    def _on_delete_click(self):
        self.delete_clicked.emit(self.msg_id)


class SignalBridge(QObject):
    message_received = pyqtSignal(str, str, str, bool, str, bool)
    status_changed = pyqtSignal(str)
    presence_changed = pyqtSignal(list, dict)  # online list, statuses dict


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
        self.current_view = "mine"  # Track current view: "mine" or "todos"
        self.my_status = "online"  # Current user's status
        self.user_statuses = {}  # {username: status} for online users
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

        # Single scrollable stream - contains both text and message widgets
        self.stream_scroll = QScrollArea()
        self.stream_scroll.setWidgetResizable(True)
        self.stream_scroll.setStyleSheet("""
            QScrollArea { background-color: #1e1e1e; border: none; }
            QScrollBar:vertical { background: #1e1e1e; width: 8px; }
            QScrollBar::handle:vertical { background: #555; border-radius: 4px; }
        """)
        self.stream_widget = QWidget()
        self.stream_widget.setStyleSheet("background-color: #1e1e1e;")
        self.stream_layout = QVBoxLayout(self.stream_widget)
        self.stream_layout.setContentsMargins(8, 8, 8, 8)
        self.stream_layout.setSpacing(4)
        self.stream_layout.addStretch()
        self.stream_scroll.setWidget(self.stream_widget)
        layout.addWidget(self.stream_scroll, stretch=1)

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

    def _add_text_to_stream(self, text: str, color: str = "#d4d4d4", bold: bool = False):
        """Add a text label to the stream."""
        label = QLabel(text)
        style = f"color: {color}; font-size: 12px;"
        if bold:
            style += " font-weight: bold;"
        label.setStyleSheet(style)
        label.setWordWrap(True)
        # Insert before the stretch
        self.stream_layout.insertWidget(self.stream_layout.count() - 1, label)
        self._scroll_to_bottom()

    def _add_widget_to_stream(self, widget):
        """Add any widget to the stream."""
        self.stream_layout.insertWidget(self.stream_layout.count() - 1, widget)
        self._scroll_to_bottom()

    def _scroll_to_bottom(self):
        """Scroll stream to bottom."""
        QTimer.singleShot(10, lambda: self.stream_scroll.verticalScrollBar().setValue(
            self.stream_scroll.verticalScrollBar().maximum()))

    def add_message(self, sender: str, text: str, time_str: str,
                    unread: bool = False, priority: str = "normal", via_relay: bool = False):
        """Add a simple text message to the stream."""
        # Determine sender color
        if sender.startswith("you→"):
            sender_color = "#4ec9b0"
        elif sender == "claude" or sender.endswith("-claude"):
            sender_color = "#c586c0"
        else:
            sender_color = "#569cd6"

        # Build message widget
        msg_widget = QWidget()
        msg_layout = QHBoxLayout(msg_widget)
        msg_layout.setContentsMargins(0, 4, 0, 4)
        msg_layout.setSpacing(8)

        # Status indicator
        if unread:
            dot = QLabel("●")
            dot.setStyleSheet("color: #f48771; font-size: 12px;")
            dot.setFixedWidth(16)
            msg_layout.addWidget(dot)
        else:
            spacer = QLabel("")
            spacer.setFixedWidth(16)
            msg_layout.addWidget(spacer)

        # Content
        content = QVBoxLayout()
        content.setSpacing(2)

        header = QLabel(f"<span style='color:{sender_color}; font-weight:bold;'>@{sender}</span> <span style='color:#666;'>{time_str}</span>")
        content.addWidget(header)

        body = QLabel(text[:200])
        body.setStyleSheet("color: #d4d4d4; font-size: 12px;")
        body.setWordWrap(True)
        content.addWidget(body)

        msg_layout.addLayout(content, stretch=1)
        self._add_widget_to_stream(msg_widget)

        if unread:
            self.raise_()
            self.activateWindow()

    def update_relay_status(self, status: str):
        color = "#4ec9b0" if "●" in status else "#c586c0"
        self.relay_label.setStyleSheet(f"color: {color}; font-size: 11px;")
        self.relay_label.setText(f"({status})")

    def update_presence(self, online: list, statuses: dict = None):
        self.user_statuses = statuses or {}
        self.online_label.setText(f"{len(online)} online" if online else "")

    def _handle_command(self, cmd: str) -> bool:
        """Handle /commands. Returns True if handled."""
        parts = cmd.strip().split(maxsplit=2)
        cmd_name = parts[0].lower()

        if cmd_name in ("/mine", "/my-messages", "/messages", "/inbox"):
            self._show_my_messages()
            return True
        elif cmd_name == "/todos":
            self._show_todo_messages()
            return True
        elif cmd_name == "/todo" and len(parts) >= 2:
            # /todo <id> - mark as TODO
            self._mark_message_by_id(parts[1], "todo")
            return True
        elif cmd_name == "/done" and len(parts) >= 2:
            # /done <id> - mark as done
            self._mark_message_by_id(parts[1], "done")
            return True
        elif cmd_name == "/read" and len(parts) >= 2:
            # /read <id> - mark as read (clear unread)
            self._mark_message_by_id(parts[1], "clear")
            return True
        elif cmd_name == "/clear":
            # Clear all widgets from stream except the stretch
            while self.stream_layout.count() > 1:
                item = self.stream_layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
            self.input_field.clear()
            return True
        elif cmd_name == "/relay":
            self._show_relay_info()
            return True
        elif cmd_name in ("/help", "/?"):
            self._show_help()
            return True
        elif cmd_name == "/online":
            self._show_online()
            return True
        elif cmd_name == "/status":
            if len(parts) >= 2:
                self._set_status(parts[1])
            else:
                self._show_status()
            return True
        elif cmd_name == "/context" and len(parts) >= 2:
            self._show_context(parts[1])
            return True
        elif cmd_name == "/tasks":
            self._show_tasks()
            return True
        elif cmd_name == "/queue":
            self._show_tasks()  # Same as /tasks
            return True
        return False

    def _on_status_change(self, msg_id: str, current_status: str):
        """Handle status button click - cycle to next status."""
        if current_status == "unread":
            new_action = "todo"
        elif current_status == "todo":
            new_action = "done"
        elif current_status == "done":
            new_action = "clear"
        else:
            new_action = "todo"

        success = self._mark_message_by_id(msg_id, new_action)
        # Show confirmation
        if success:
            action_labels = {"todo": "→ TODO", "done": "→ Done", "clear": "→ Cleared"}
            self._add_text_to_stream(f"  ✓ {action_labels.get(new_action, new_action)}", "#4ec9b0")
        else:
            self._add_text_to_stream(f"  ✗ Failed to update", "#f48771")

    def _on_delete_message(self, msg_id: str):
        """Handle delete button click - remove message from org file."""
        import re
        for inbox in DATACORE_ROOT.glob(f"*/org/inboxes/{self.username}*.org"):
            try:
                content = inbox.read_text()
                if msg_id not in content:
                    continue
                # Remove the entire MESSAGE block
                pattern = rf'\n\* MESSAGE \[[^\]]+\][^\n]*\n:PROPERTIES:.*?:ID: {re.escape(msg_id)}.*?:END:\n.*?(?=\n\* |\Z)'
                new_content = re.sub(pattern, '', content, flags=re.DOTALL)
                if new_content != content:
                    inbox.write_text(new_content)
                    self._add_text_to_stream("  ✓ Deleted", "#f48771")
                    break
            except:
                pass

    def _show_my_messages(self):
        """Show all unread messages for current user - appends to stream."""
        self.current_view = "mine"

        messages = []

        # Check all inboxes for this user
        for inbox in DATACORE_ROOT.glob(f"*/org/inboxes/{self.username}.org"):
            try:
                content = inbox.read_text()
                for block in content.split("\n* MESSAGE ")[1:]:
                    msg = self._parse_message(block)
                    if msg and msg.get("unread"):
                        messages.append(msg)
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
            except:
                pass

        # Add header to stream
        self._add_text_to_stream(f"─── {len(messages)} unread ───", "#c586c0", bold=True)

        if messages:
            for msg in sorted(messages, key=lambda m: m.get("id", "")):
                row = MessageRow(msg)
                row.status_clicked.connect(self._on_status_change)
                row.delete_clicked.connect(self._on_delete_message)
                self._add_widget_to_stream(row)
        else:
            self._add_text_to_stream("  No unread messages", "#4ec9b0")

        self.input_field.clear()

    def _show_help(self):
        """Show available commands."""
        self._add_text_to_stream("─── Commands ───", "#c586c0", bold=True)

        commands = [
            ("@user message", "Send message to user"),
            ("@claude task", "Send task to your Claude"),
            ("@user >id text", "Reply to message (thread)"),
            ("/mine", "Show unread messages"),
            ("/todos", "Show TODO messages"),
            ("/tasks", "Show Claude task queue"),
            ("/context <id>", "Show thread context"),
            ("/online", "Show online users"),
            ("/status [val]", "Set status (busy/away/focusing)"),
            ("/relay", "Show relay info"),
            ("/clear", "Clear display"),
        ]

        for cmd, desc in commands:
            self._add_text_to_stream(f"  {cmd:<16} {desc}", "#4ec9b0")

        self.input_field.clear()

    def _show_online(self):
        """Show online users with status icons."""
        self._add_text_to_stream("─── Online ───", "#c586c0", bold=True)

        if not self.relay_connected:
            self._add_text_to_stream("  Not connected to relay", "#f48771")
            self.input_field.clear()
            return

        status_icons = {
            "online": "🟢",
            "busy": "🔴",
            "away": "🟡",
            "focusing": "🟣"
        }

        if self.user_statuses:
            for user, status in sorted(self.user_statuses.items()):
                icon = status_icons.get(status, "⚪")
                is_me = " (you)" if user == self.username else ""
                self._add_text_to_stream(f"  {icon} @{user}{is_me} - {status}", "#4ec9b0")
        else:
            self._add_text_to_stream("  No users online", "#666")

        self.input_field.clear()

    def _show_status(self):
        """Show current status options."""
        self._add_text_to_stream("─── Status ───", "#c586c0", bold=True)

        status_icons = {"online": "🟢", "busy": "🔴", "away": "🟡", "focusing": "🟣"}
        icon = status_icons.get(self.my_status, "⚪")
        self._add_text_to_stream(f"  Current: {icon} {self.my_status}", "#4ec9b0")
        self._add_text_to_stream("", "#666")
        self._add_text_to_stream("  Set with: /status <value>", "#666")
        self._add_text_to_stream("  Values: online, busy, away, focusing", "#666")

        self.input_field.clear()

    def _set_status(self, new_status: str):
        """Set user's presence status."""
        new_status = new_status.lower().strip()
        valid_statuses = ("online", "busy", "away", "focusing")

        if new_status not in valid_statuses:
            self._add_text_to_stream(f"  Invalid status: {new_status}", "#f48771")
            self._add_text_to_stream(f"  Valid: {', '.join(valid_statuses)}", "#666")
            self.input_field.clear()
            return

        self.my_status = new_status
        status_icons = {"online": "🟢", "busy": "🔴", "away": "🟡", "focusing": "🟣"}
        icon = status_icons.get(new_status, "⚪")

        # Update local status dot color
        dot_colors = {"online": "#4ec9b0", "busy": "#f48771", "away": "#dcdcaa", "focusing": "#c586c0"}
        self.status_dot.setStyleSheet(f"color: {dot_colors.get(new_status, '#4ec9b0')}; font-size: 13px;")

        self._add_text_to_stream(f"  {icon} Status set to: {new_status}", "#4ec9b0")

        # Send status change to relay
        if self.relay_connected:
            self._send_status_change(new_status)

        self.input_field.clear()

    def _send_status_change(self, new_status: str):
        """Send status change to relay server."""
        if hasattr(self, '_status_change_pending'):
            self._status_change_pending = new_status
        else:
            self._status_change_pending = new_status

    def _show_tasks(self):
        """Show Claude task queue status."""
        self._add_text_to_stream("─── Claude Tasks ───", "#c586c0", bold=True)

        tasks = {"working": [], "pending": [], "done": []}

        # Check Claude inbox for tasks
        for inbox in DATACORE_ROOT.glob(f"*/org/inboxes/{self.username}-claude.org"):
            try:
                content = inbox.read_text()
                for block in content.split("\n* MESSAGE ")[1:]:
                    msg = self._parse_message(block)
                    if not msg:
                        continue

                    # Check task status from properties
                    task_status = None
                    for line in block.split("\n"):
                        if ":TASK_STATUS:" in line:
                            task_status = line.split(":TASK_STATUS:")[1].strip()
                            break

                    if task_status == "working":
                        tasks["working"].append(msg)
                    elif task_status == "done":
                        tasks["done"].append(msg)
                    elif msg.get("unread"):
                        tasks["pending"].append(msg)
            except:
                pass

        # Display working tasks
        if tasks["working"]:
            for msg in tasks["working"]:
                text = msg["text"][:50] + "..." if len(msg["text"]) > 50 else msg["text"]
                self._add_text_to_stream(f"  🔄 {text}", "#dcdcaa")
                self._add_text_to_stream(f"     from @{msg['from']} ({msg.get('time', '?')})", "#666")
        else:
            self._add_text_to_stream("  No tasks in progress", "#666")

        # Display pending tasks
        if tasks["pending"]:
            self._add_text_to_stream(f"  📋 {len(tasks['pending'])} pending:", "#4ec9b0")
            for msg in tasks["pending"][:3]:
                text = msg["text"][:40] + "..." if len(msg["text"]) > 40 else msg["text"]
                self._add_text_to_stream(f"     • {text}", "#666")
            if len(tasks["pending"]) > 3:
                self._add_text_to_stream(f"     ... and {len(tasks['pending']) - 3} more", "#666")

        # Display recently done
        if tasks["done"]:
            self._add_text_to_stream(f"  ✓ {len(tasks['done'])} completed", "#4ec9b0")

        self.input_field.clear()

    def _show_context(self, msg_id_fragment: str):
        """Show conversation context for a message or thread."""
        # Find the message and its thread
        target_msg = None
        thread_id = None

        for inbox in DATACORE_ROOT.glob("*/org/inboxes/*.org"):
            try:
                content = inbox.read_text()
                if msg_id_fragment not in content:
                    continue
                for block in content.split("\n* MESSAGE ")[1:]:
                    if msg_id_fragment in block:
                        target_msg = self._parse_message(block)
                        if target_msg:
                            thread_id = target_msg.get("thread")
                            if not thread_id:
                                # No thread - just show this message
                                thread_id = f"thread-{target_msg['id']}"
                        break
            except:
                pass
            if target_msg:
                break

        if not target_msg:
            self._add_text_to_stream(f"  Message not found: {msg_id_fragment}", "#f48771")
            self.input_field.clear()
            return

        # Find all messages in this thread
        thread_messages = []
        for inbox in DATACORE_ROOT.glob("*/org/inboxes/*.org"):
            try:
                content = inbox.read_text()
                for block in content.split("\n* MESSAGE ")[1:]:
                    msg = self._parse_message(block)
                    if msg:
                        # Include if in same thread or is the target
                        if msg.get("thread") == thread_id or msg["id"] == target_msg["id"]:
                            thread_messages.append(msg)
                        # Also include parent messages
                        elif msg["id"] == target_msg.get("reply_to"):
                            thread_messages.append(msg)
            except:
                pass

        # Sort by message ID (chronological)
        thread_messages = sorted(thread_messages, key=lambda m: m.get("id", ""))

        # Remove duplicates
        seen = set()
        unique_msgs = []
        for msg in thread_messages:
            if msg["id"] not in seen:
                seen.add(msg["id"])
                unique_msgs.append(msg)

        self._add_text_to_stream(f"─── Thread ({len(unique_msgs)} messages) ───", "#c586c0", bold=True)

        for msg in unique_msgs:
            is_target = msg["id"] == target_msg["id"] or msg_id_fragment in msg["id"]
            prefix = "► " if is_target else "  "
            color = "#dcdcaa" if is_target else "#569cd6"

            # Show reply indicator
            reply_info = ""
            if msg.get("reply_to"):
                reply_info = " ↩"

            self._add_text_to_stream(
                f"{prefix}@{msg['from']} ({msg.get('time', '?')}){reply_info}",
                color
            )
            # Truncate long messages
            text = msg["text"][:100] + "..." if len(msg["text"]) > 100 else msg["text"]
            self._add_text_to_stream(f"    {text}", "#d4d4d4")

        self.input_field.clear()

    def _show_relay_info(self):
        """Show current relay connection info."""
        self._add_text_to_stream("─── Relay ───", "#c586c0", bold=True)

        relay_url = get_relay_url()
        mode = "hosting" if self.host_relay else "client"

        if self.relay_connected:
            self._add_text_to_stream(f"  Status: Connected ({mode})", "#4ec9b0")
        else:
            self._add_text_to_stream(f"  Status: Disconnected ({mode})", "#f48771")

        self._add_text_to_stream(f"  URL: {relay_url}", "#d4d4d4")

        self.input_field.clear()

    def _show_todo_messages(self):
        """Show messages marked as :todo: - appends to stream."""
        self.current_view = "todos"

        todo_msgs = []
        done_count = 0

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
                            done_count += 1
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
                            done_count += 1
            except:
                pass

        # Add header to stream
        header_text = f"─── {len(todo_msgs)} todo"
        if done_count:
            header_text += f" ({done_count} done)"
        header_text += " ───"
        self._add_text_to_stream(header_text, "#dcdcaa", bold=True)

        if todo_msgs:
            for msg in sorted(todo_msgs, key=lambda m: m.get("id", "")):
                row = MessageRow(msg)
                row.status_clicked.connect(self._on_status_change)
                row.delete_clicked.connect(self._on_delete_message)
                self._add_widget_to_stream(row)
        else:
            self._add_text_to_stream("  No TODO messages", "#4ec9b0")

        self.input_field.clear()

    def _mark_message_by_id(self, msg_id: str, action: str):
        """Mark a message by ID with :todo:, :done:, or clear tags."""
        import re

        for inbox in DATACORE_ROOT.glob(f"*/org/inboxes/{self.username}*.org"):
            try:
                content = inbox.read_text()
                if msg_id not in content:
                    continue

                # Find the MESSAGE block containing this ID and update its tags
                # Pattern: * MESSAGE [timestamp] :tags:\n:PROPERTIES:\n:ID: msg_id
                lines = content.split('\n')
                new_lines = []
                found = False
                i = 0

                while i < len(lines):
                    line = lines[i]

                    # Check if this is a MESSAGE header and the ID matches in upcoming lines
                    if line.startswith('* MESSAGE ['):
                        # Look ahead for the ID in the PROPERTIES block
                        block_end = min(i + 10, len(lines))
                        block_has_id = any(msg_id in lines[j] for j in range(i, block_end))

                        if block_has_id:
                            # Remove existing status tags and add new one
                            header = re.sub(r' :(unread|todo|done):', '', line)
                            if action == "todo":
                                header = header.rstrip() + " :todo:"
                            elif action == "done":
                                header = header.rstrip() + " :done:"
                            # else: clear - no tag added
                            new_lines.append(header)
                            found = True
                            i += 1
                            continue

                    new_lines.append(line)
                    i += 1

                if found:
                    inbox.write_text('\n'.join(new_lines))
                    return True

            except Exception as e:
                pass
        return False

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

        # Check for reply syntax: @user >msg-id text
        reply_to = None
        thread_id = None
        if msg_text.startswith(">"):
            reply_parts = msg_text.split(" ", 1)
            if len(reply_parts) >= 2:
                reply_to = reply_parts[0][1:]  # Remove >
                msg_text = reply_parts[1]
                # Find thread ID from parent message
                thread_id = self._get_thread_for_message(reply_to)
                if not thread_id:
                    # Start new thread from parent message
                    thread_id = f"thread-{reply_to}"

        msg_id = self._write_to_inbox(recipient, msg_text, reply_to=reply_to, thread_id=thread_id)

        if msg_id:
            # Send via relay
            if self.relay_connected:
                def send():
                    asyncio.run(self._send_via_relay(recipient, msg_text, msg_id, thread_id, reply_to))
                threading.Thread(target=send, daemon=True).start()

            display_text = f"↩ {msg_text}" if reply_to else msg_text
            self.add_message(f"you→{recipient}", display_text, datetime.now().strftime("%H:%M"))
            self.input_field.clear()

    async def _send_via_relay(self, to: str, text: str, msg_id: str, thread_id: str = None, reply_to: str = None):
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
                msg = {
                    "type": "send",
                    "to": to,
                    "text": text,
                    "msg_id": msg_id
                }
                if thread_id:
                    msg["thread"] = thread_id
                if reply_to:
                    msg["reply_to"] = reply_to
                await ws.send(json.dumps(msg))
                await ws.recv()
        except:
            pass

    def _write_to_inbox(self, to: str, text: str, reply_to: str = None, thread_id: str = None) -> str:
        try:
            inbox_dir = DATACORE_ROOT / self.default_space / "org/inboxes"
            inbox_dir.mkdir(parents=True, exist_ok=True)
            inbox = inbox_dir / f"{to}.org"

            now = datetime.now()
            msg_id = f"msg-{now.strftime('%Y%m%d-%H%M%S')}-{self.username}"
            timestamp = now.strftime("[%Y-%m-%d %a %H:%M]")

            # Build properties
            props = [
                f":ID: {msg_id}",
                f":FROM: {self.username}",
                f":TO: {to}",
            ]
            if thread_id:
                props.append(f":THREAD: {thread_id}")
            if reply_to:
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

            self.seen_ids.add(msg_id)
            return msg_id
        except:
            return None

    def _get_thread_for_message(self, msg_id: str) -> str:
        """Find thread ID for a message, or None if not in a thread."""
        for inbox in DATACORE_ROOT.glob("*/org/inboxes/*.org"):
            try:
                content = inbox.read_text()
                if msg_id not in content:
                    continue
                for block in content.split("\n* MESSAGE ")[1:]:
                    if msg_id in block:
                        # Parse properties
                        for line in block.split("\n"):
                            if ":THREAD:" in line:
                                return line.split(":THREAD:")[1].strip()
                        return None
            except:
                pass
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
                "done": is_done,
                "thread": props.get("thread"),
                "reply_to": props.get("reply_to")
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
                    self.relay_client_ws = ws
                    await ws.send(json.dumps({
                        "type": "auth",
                        "secret": secret,
                        "username": self.username,
                        "status": self.my_status,
                        "claude_whitelist": get_claude_whitelist()
                    }))

                    resp = json.loads(await ws.recv())
                    if resp.get("type") == "auth_ok":
                        self.relay_connected = True
                        mode = "● hosting" if self.host_relay else "● relay"
                        self.bridge.status_changed.emit(mode)
                        self.bridge.presence_changed.emit(
                            resp.get("online", []),
                            resp.get("statuses", {})
                        )

                        async for message in ws:
                            # Check for pending status change
                            if hasattr(self, '_status_change_pending') and self._status_change_pending:
                                await ws.send(json.dumps({
                                    "type": "status_change",
                                    "status": self._status_change_pending
                                }))
                                self._status_change_pending = None

                            data = json.loads(message)
                            if data.get("type") == "message":
                                self.bridge.message_received.emit(
                                    data.get("from", "?"),
                                    data.get("text", ""),
                                    datetime.now().strftime("%H:%M"),
                                    True, "normal", True
                                )
                            elif data.get("type") == "presence_change":
                                self.bridge.presence_changed.emit(
                                    data.get("online", []),
                                    data.get("statuses", {})
                                )
                            elif data.get("type") == "status_ok":
                                pass  # Status change confirmed
                    else:
                        self.bridge.status_changed.emit("auth failed")
                        break

            except Exception as e:
                self.relay_connected = False
                self.relay_client_ws = None
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
