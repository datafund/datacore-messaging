#!/usr/bin/env python3
"""
datacore-msg-window - Floating message overlay for Datacore (PyQt6 version)

A small always-on-top window that shows messages in real-time.
Supports both local file watching and WebSocket relay for remote messages.

Usage:
    python datacore-msg-window.py

Requirements:
    - Python 3.8+
    - PyQt6: pip install PyQt6
    - websockets (optional): pip install websockets
"""

import sys
import os
import json
import threading
import asyncio
from pathlib import Path
from datetime import datetime

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTextEdit, QLineEdit, QLabel, QFrame, QScrollArea
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject
from PyQt6.QtGui import QFont, QColor, QTextCursor, QTextCharFormat

# Optional websockets for relay
try:
    import websockets
    HAS_WEBSOCKETS = True
except ImportError:
    HAS_WEBSOCKETS = False

# === CONFIG ===

DATACORE_ROOT = Path(os.environ.get("DATACORE_ROOT", Path.home() / "Data"))
MODULE_DIR = Path(__file__).parent.parent  # datacore-messaging/
POLL_INTERVAL = 2000  # milliseconds


def get_settings() -> dict:
    """Load settings from yaml. Module settings take precedence."""
    try:
        import yaml
    except ImportError:
        return {}

    settings = {}

    # First load from datacore root (base settings)
    root_settings = DATACORE_ROOT / ".datacore/settings.local.yaml"
    if root_settings.exists():
        try:
            settings = yaml.safe_load(root_settings.read_text()) or {}
        except:
            pass

    # Then overlay module-specific settings
    module_settings = MODULE_DIR / "settings.local.yaml"
    if module_settings.exists():
        try:
            mod = yaml.safe_load(module_settings.read_text()) or {}
            for key, value in mod.items():
                if key in settings and isinstance(settings[key], dict) and isinstance(value, dict):
                    settings[key].update(value)
                else:
                    settings[key] = value
        except:
            pass

    return settings


def get_username() -> str:
    """Get current user's identity from settings or environment."""
    if "DATACORE_USER" in os.environ:
        return os.environ["DATACORE_USER"]

    conf = get_settings()
    name = conf.get("identity", {}).get("name")
    if name:
        return name

    return os.environ.get("USER", "unknown")


def get_default_space() -> str:
    """Get default space for sending messages."""
    conf = get_settings()
    space = conf.get("messaging", {}).get("default_space")
    if space:
        return space

    for p in sorted(DATACORE_ROOT.glob("[1-9]-*")):
        if p.is_dir():
            return p.name

    return "1-team"


def get_relay_url() -> str:
    """Get relay server URL from settings."""
    conf = get_settings()
    return conf.get("messaging", {}).get("relay", {}).get("url", "wss://datacore-relay.fly.dev")


def get_relay_secret() -> str:
    """Get relay shared secret from settings."""
    conf = get_settings()
    return conf.get("messaging", {}).get("relay", {}).get("secret")


def is_relay_enabled() -> bool:
    """Check if relay is enabled in settings."""
    conf = get_settings()
    relay_conf = conf.get("messaging", {}).get("relay", {})
    return relay_conf.get("enabled", False) or bool(relay_conf.get("secret"))


def get_claude_whitelist() -> list:
    """Get list of users allowed to message this user's Claude."""
    conf = get_settings()
    return conf.get("messaging", {}).get("claude_whitelist", [])


class SignalBridge(QObject):
    """Bridge for thread-safe UI updates."""
    message_received = pyqtSignal(str, str, str, bool, str, bool)
    status_changed = pyqtSignal(str)
    presence_changed = pyqtSignal(list)


class RelayClient:
    """WebSocket client for relay server."""

    def __init__(self, url: str, secret: str, username: str, bridge: SignalBridge, claude_whitelist: list = None):
        self.url = url
        self.secret = secret
        self.local_username = username
        self.bridge = bridge
        self.claude_whitelist = claude_whitelist or []
        self.ws = None
        self.username = None
        self.online_users = []
        self.running = False

    async def connect(self):
        """Connect and authenticate with relay."""
        try:
            self.ws = await websockets.connect(self.url)

            await self.ws.send(json.dumps({
                "type": "auth",
                "secret": self.secret,
                "username": self.local_username,
                "claude_whitelist": self.claude_whitelist
            }))

            response = json.loads(await self.ws.recv())

            if response.get("type") == "auth_error":
                self.bridge.status_changed.emit(f"Auth failed: {response.get('message')}")
                return False

            if response.get("type") == "auth_ok":
                self.username = response.get("username")
                self.online_users = response.get("online", [])
                self.bridge.status_changed.emit(f"● relay @{self.username}")
                self.bridge.presence_changed.emit(self.online_users)
                return True

            return False
        except Exception as e:
            self.bridge.status_changed.emit(f"Connection failed: {str(e)[:30]}")
            return False

    async def send_message(self, to: str, text: str, msg_id: str, priority: str = "normal") -> bool:
        """Send message via relay."""
        if not self.ws:
            return False

        try:
            await self.ws.send(json.dumps({
                "type": "send",
                "to": to,
                "text": text,
                "msg_id": msg_id,
                "priority": priority
            }))

            response = json.loads(await self.ws.recv())
            return response.get("delivered", False)
        except:
            return False

    async def listen(self):
        """Listen for incoming messages."""
        self.running = True
        try:
            async for message in self.ws:
                if not self.running:
                    break

                data = json.loads(message)
                msg_type = data.get("type")

                if msg_type == "message":
                    self.bridge.message_received.emit(
                        data.get("from", "?"),
                        data.get("text", ""),
                        datetime.now().strftime("%H:%M"),
                        True,  # unread
                        data.get("priority", "normal"),
                        True  # via_relay
                    )

                elif msg_type == "presence_change":
                    self.online_users = data.get("online", [])
                    self.bridge.presence_changed.emit(self.online_users)

        except Exception as e:
            self.bridge.status_changed.emit(f"Relay error: {str(e)[:20]}")

    async def close(self):
        """Close connection."""
        self.running = False
        if self.ws:
            await self.ws.close()


class MessageWindow(QMainWindow):
    """Main message window."""

    def __init__(self):
        super().__init__()

        self.username = get_username()
        self.default_space = get_default_space()
        self.seen_ids = set()
        self.relay_client = None
        self.relay_connected = False
        self.bridge = SignalBridge()

        # Connect signals
        self.bridge.message_received.connect(self.add_message)
        self.bridge.status_changed.connect(self.update_relay_status)
        self.bridge.presence_changed.connect(self.update_presence)

        self._setup_ui()
        self._load_existing_messages()
        self._start_watcher()
        self._start_relay()

    def _setup_ui(self):
        """Setup the user interface."""
        self.setWindowTitle(f"Messages @{self.username}")
        self.setGeometry(100, 100, 350, 500)

        # Always on top
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)

        # Dark theme stylesheet
        self.setStyleSheet("""
            QMainWindow {
                background-color: #1e1e1e;
            }
            QLabel {
                color: #d4d4d4;
            }
            QTextEdit {
                background-color: #1e1e1e;
                color: #d4d4d4;
                border: none;
                font-family: Menlo, Monaco, monospace;
                font-size: 12px;
            }
            QLineEdit {
                background-color: #333333;
                color: #ffffff;
                border: 1px solid #555555;
                border-radius: 4px;
                padding: 8px;
                font-family: Menlo, Monaco, monospace;
                font-size: 12px;
            }
            QLineEdit:focus {
                border: 1px solid #569cd6;
            }
        """)

        # Central widget
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
        self.online_label.setStyleSheet("color: #666666; font-size: 11px;")
        header.addWidget(self.online_label)

        self.relay_label = QLabel("(connecting...)")
        self.relay_label.setStyleSheet("color: #c586c0; font-size: 11px;")
        header.addWidget(self.relay_label)

        layout.addLayout(header)

        # Messages area
        self.messages_area = QTextEdit()
        self.messages_area.setReadOnly(True)
        self.messages_area.setMinimumHeight(200)
        layout.addWidget(self.messages_area, stretch=1)

        # Separator
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setStyleSheet("background-color: #333333;")
        layout.addWidget(separator)

        # Input field
        self.input_field = QLineEdit()
        self.input_field.setPlaceholderText("@user message")
        self.input_field.returnPressed.connect(self._send_message)
        layout.addWidget(self.input_field)

        # Status bar
        self.status_label = QLabel(f"Space: {self.default_space}")
        self.status_label.setStyleSheet("color: #666666; font-size: 11px;")
        layout.addWidget(self.status_label)

        # Position window at top-right
        screen = QApplication.primaryScreen().geometry()
        self.move(screen.width() - 370, 40)

    def add_message(self, sender: str, text: str, time_str: str,
                    unread: bool = False, priority: str = "normal", via_relay: bool = False):
        """Add a message to the display."""
        cursor = self.messages_area.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)

        # Unread marker
        if unread:
            fmt = QTextCharFormat()
            fmt.setForeground(QColor("#f48771"))
            cursor.insertText("● ", fmt)
        else:
            cursor.insertText("  ")

        # Sender
        fmt = QTextCharFormat()
        if sender.startswith("you→"):
            fmt.setForeground(QColor("#4ec9b0"))
        elif sender == "claude":
            fmt.setForeground(QColor("#c586c0"))
        elif via_relay:
            fmt.setForeground(QColor("#dcdcaa"))
        else:
            fmt.setForeground(QColor("#569cd6"))
        fmt.setFontWeight(700)
        cursor.insertText(f"@{sender} ", fmt)

        # Time
        fmt = QTextCharFormat()
        fmt.setForeground(QColor("#666666"))
        relay_marker = " ↗" if via_relay else ""
        cursor.insertText(f"{time_str}{relay_marker}\n", fmt)

        # Priority
        if priority == "high":
            fmt = QTextCharFormat()
            fmt.setForeground(QColor("#f48771"))
            cursor.insertText("  [!] ", fmt)
        else:
            cursor.insertText("  ")

        # Message text
        fmt = QTextCharFormat()
        fmt.setForeground(QColor("#d4d4d4"))
        display_text = text[:200] + "..." if len(text) > 200 else text
        cursor.insertText(f"{display_text}\n\n", fmt)

        # Scroll to bottom
        self.messages_area.setTextCursor(cursor)
        self.messages_area.ensureCursorVisible()

        # Notify
        if unread:
            self._notify(sender, text)

    def _notify(self, sender: str, text: str):
        """Send notification."""
        self.raise_()
        self.activateWindow()

        # macOS notification
        if sys.platform == "darwin":
            import subprocess
            try:
                preview = text[:50] + "..." if len(text) > 50 else text
                script = f'display notification "{preview}" with title "Datacore" subtitle "@{sender}"'
                subprocess.Popen(["osascript", "-e", script],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                subprocess.Popen(["afplay", "/System/Library/Sounds/Ping.aiff"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except:
                pass

    def update_relay_status(self, status: str):
        """Update relay status label."""
        if "●" in status:
            self.relay_label.setStyleSheet("color: #4ec9b0; font-size: 11px;")
        elif "failed" in status or "error" in status:
            self.relay_label.setStyleSheet("color: #f48771; font-size: 11px;")
        else:
            self.relay_label.setStyleSheet("color: #c586c0; font-size: 11px;")
        self.relay_label.setText(f"({status})")

    def update_presence(self, online_users: list):
        """Update online users count."""
        count = len(online_users)
        self.online_label.setText(f"{count} online" if count > 0 else "")

    def _send_message(self):
        """Send message from input field."""
        text = self.input_field.text().strip()

        if not text:
            return

        if not text.startswith("@"):
            self._show_error("Start with @username")
            return

        parts = text.split(" ", 1)
        recipient = parts[0][1:]
        msg_text = parts[1] if len(parts) > 1 else ""

        if not recipient:
            self._show_error("Specify recipient: @user")
            return

        if not msg_text:
            self._show_error("Enter a message")
            return

        msg_id = self._write_to_inbox(recipient, msg_text)

        if msg_id:
            via_relay = False
            if self.relay_connected and self.relay_client:
                def send_relay():
                    asyncio.run(self.relay_client.send_message(recipient, msg_text, msg_id))
                threading.Thread(target=send_relay, daemon=True).start()
                via_relay = True

            self.add_message(
                f"you→{recipient}",
                msg_text,
                datetime.now().strftime("%H:%M"),
                unread=False,
                via_relay=via_relay,
            )

            self.input_field.clear()

            delivery = "relay" if via_relay else "local"
            self.status_label.setText(f"✓ Sent to @{recipient} ({delivery})")
            QTimer.singleShot(3000, lambda: self.status_label.setText(f"Space: {self.default_space}"))
        else:
            self._show_error("Failed to send")

    def _show_error(self, msg: str):
        """Show error in status bar."""
        self.status_label.setStyleSheet("color: #f48771; font-size: 11px;")
        self.status_label.setText(f"⚠ {msg}")
        QTimer.singleShot(3000, lambda: (
            self.status_label.setStyleSheet("color: #666666; font-size: 11px;"),
            self.status_label.setText(f"Space: {self.default_space}")
        ))

    def _write_to_inbox(self, to: str, text: str) -> str:
        """Write message to recipient's org inbox."""
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
:PRIORITY: normal
:END:
{text}
"""

            with open(inbox, "a") as f:
                f.write(entry)

            self.seen_ids.add(msg_id)
            return msg_id

        except Exception as e:
            print(f"Error writing message: {e}", file=sys.stderr)
            return None

    def _load_existing_messages(self):
        """Load last N messages from inbox on startup."""
        messages = []

        for inbox in DATACORE_ROOT.glob(f"*/org/inboxes/{self.username}.org"):
            try:
                content = inbox.read_text()
                for block in content.split("\n* MESSAGE ")[1:]:
                    msg = self._parse_message_block(block)
                    if msg:
                        self.seen_ids.add(msg["id"])
                        messages.append(msg)
            except:
                pass

        messages.sort(key=lambda m: m.get("id", ""))
        for msg in messages[-15:]:
            self.add_message(
                msg["from"],
                msg["text"],
                msg.get("time", "earlier"),
                unread=msg.get("unread", False),
                priority=msg.get("priority", "normal"),
            )

    def _parse_message_block(self, block: str) -> dict:
        """Parse a MESSAGE block from org file."""
        try:
            lines = block.split("\n")
            header = lines[0] if lines else ""

            is_unread = ":unread:" in header

            time_str = "earlier"
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
                    if line.startswith(":") and ": " in line[1:]:
                        key_val = line[1:].split(": ", 1)
                        if len(key_val) == 2:
                            props[key_val[0].lower()] = key_val[1]
                elif not in_props and line.strip():
                    text_lines.append(line)

            return {
                "id": props.get("id", ""),
                "from": props.get("from", "?"),
                "to": props.get("to", ""),
                "text": "\n".join(text_lines).strip(),
                "time": time_str,
                "unread": is_unread,
                "priority": props.get("priority", "normal"),
                "source": props.get("source", "local"),
            }
        except:
            return None

    def _start_watcher(self):
        """Start timer to watch for new messages."""
        self.watcher_timer = QTimer(self)
        self.watcher_timer.timeout.connect(self._check_inbox)
        self.watcher_timer.start(POLL_INTERVAL)

    def _check_inbox(self):
        """Check inbox for new messages."""
        try:
            for inbox in DATACORE_ROOT.glob(f"*/org/inboxes/{self.username}.org"):
                content = inbox.read_text()

                for block in content.split("\n* MESSAGE ")[1:]:
                    msg = self._parse_message_block(block)

                    if msg and msg["id"] and msg["id"] not in self.seen_ids:
                        self.seen_ids.add(msg["id"])
                        self.add_message(
                            msg["from"],
                            msg["text"],
                            msg.get("time", "now"),
                            unread=msg.get("unread", True),
                            priority=msg.get("priority", "normal"),
                            via_relay=msg.get("source") == "relay",
                        )
        except Exception as e:
            print(f"Watcher error: {e}", file=sys.stderr)

    def _start_relay(self):
        """Start relay connection if enabled."""
        if not HAS_WEBSOCKETS:
            self.relay_label.setText("(no websockets)")
            return

        if not is_relay_enabled():
            self.relay_label.setText("(local only)")
            return

        secret = get_relay_secret()
        if not secret:
            self.relay_label.setText("(no secret)")
            return

        thread = threading.Thread(target=self._relay_loop, daemon=True)
        thread.start()

    def _relay_loop(self):
        """Run relay client in background."""
        async def run_relay():
            self.relay_client = RelayClient(
                get_relay_url(),
                get_relay_secret(),
                self.username,
                self.bridge,
                get_claude_whitelist(),
            )

            if await self.relay_client.connect():
                self.relay_connected = True
                await self.relay_client.listen()
            else:
                self.relay_connected = False

        asyncio.run(run_relay())


def main():
    if len(sys.argv) > 1 and sys.argv[1] in ["-h", "--help"]:
        print(__doc__)
        sys.exit(0)

    if not DATACORE_ROOT.exists():
        print(f"Error: DATACORE_ROOT not found: {DATACORE_ROOT}", file=sys.stderr)
        sys.exit(1)

    app = QApplication(sys.argv)
    app.setApplicationName("Datacore Messages")

    window = MessageWindow()
    window.show()

    print(f"Datacore Messages - @{window.username}")
    print(f"Watching: {DATACORE_ROOT}/*/org/inboxes/{window.username}.org")
    if is_relay_enabled():
        print(f"Relay: {get_relay_url()}")

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
