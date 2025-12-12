#!/usr/bin/env python3
"""
datacore-msg-window - Floating message overlay for Datacore

A small always-on-top window that shows messages in real-time.
Supports both local file watching and WebSocket relay for remote messages.

Usage:
    python datacore-msg-window.py

    # Or with custom identity
    DATACORE_USER=gregor python datacore-msg-window.py

Requirements:
    - Python 3.8+ (tkinter included)
    - websockets (optional, for relay support): pip install websockets
"""

import tkinter as tk
import threading
import asyncio
import os
import sys
import json
from pathlib import Path
from datetime import datetime
import subprocess

# Optional websockets for relay
try:
    import websockets
    HAS_WEBSOCKETS = True
except ImportError:
    HAS_WEBSOCKETS = False

# === CONFIG ===

DATACORE_ROOT = Path(os.environ.get("DATACORE_ROOT", Path.home() / "Data"))
POLL_INTERVAL = 2  # seconds
TOKEN_FILE = DATACORE_ROOT / ".datacore/state/relay-token"
DEFAULT_RELAY = "wss://datacore-relay.fly.dev"


def get_settings() -> dict:
    """Load settings from yaml."""
    settings_path = DATACORE_ROOT / ".datacore/settings.local.yaml"
    if settings_path.exists():
        try:
            import yaml
            return yaml.safe_load(settings_path.read_text()) or {}
        except:
            pass
    return {}


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
    return conf.get("messaging", {}).get("relay", {}).get("url", DEFAULT_RELAY)


def is_relay_enabled() -> bool:
    """Check if relay is enabled in settings."""
    conf = get_settings()
    return conf.get("messaging", {}).get("relay", {}).get("enabled", False)


def get_relay_token() -> str | None:
    """Get stored relay token."""
    if TOKEN_FILE.exists():
        return TOKEN_FILE.read_text().strip()
    return None


class RelayClient:
    """WebSocket client for relay server."""

    def __init__(self, url: str, token: str, on_message=None, on_presence=None, on_status=None):
        self.url = url
        self.token = token
        self.ws = None
        self.username = None
        self.online_users = []
        self.on_message = on_message
        self.on_presence = on_presence
        self.on_status = on_status
        self.running = False
        self.loop = None

    async def connect(self):
        """Connect and authenticate with relay."""
        try:
            self.ws = await websockets.connect(self.url)

            # Authenticate
            await self.ws.send(json.dumps({
                "type": "auth",
                "token": self.token
            }))

            response = json.loads(await self.ws.recv())

            if response.get("type") == "auth_error":
                if self.on_status:
                    self.on_status(f"Auth failed: {response.get('message')}")
                return False

            if response.get("type") == "auth_ok":
                self.username = response.get("username")
                self.online_users = response.get("online", [])
                if self.on_status:
                    self.on_status(f"Connected to relay as @{self.username}")
                if self.on_presence:
                    self.on_presence(self.online_users)
                return True

            return False
        except Exception as e:
            if self.on_status:
                self.on_status(f"Connection failed: {e}")
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
                    if self.on_message:
                        self.on_message(data)

                elif msg_type == "presence_change":
                    self.online_users = data.get("online", [])
                    if self.on_presence:
                        self.on_presence(self.online_users)

        except websockets.exceptions.ConnectionClosed:
            if self.on_status:
                self.on_status("Relay disconnected")
        except Exception as e:
            if self.on_status:
                self.on_status(f"Relay error: {e}")

    async def close(self):
        """Close connection."""
        self.running = False
        if self.ws:
            await self.ws.close()


class MessageWindow:
    """Floating message window with real-time updates."""

    def __init__(self):
        self.username = get_username()
        self.default_space = get_default_space()
        self.seen_ids = set()
        self.relay_client = None
        self.relay_connected = False

        # Create window
        self.root = tk.Tk()
        self.root.title(f"Messages @{self.username}")

        # Window properties
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 0.95)

        # Position: top-right corner
        screen_w = self.root.winfo_screenwidth()
        window_w, window_h = 320, 450
        self.root.geometry(f"{window_w}x{window_h}+{screen_w - window_w - 20}+40")

        # Prevent resize below minimum
        self.root.minsize(280, 300)

        # Dark theme colors
        self.bg_color = "#1e1e1e"
        self.fg_color = "#d4d4d4"
        self.accent_color = "#569cd6"
        self.muted_color = "#666666"
        self.unread_bg = "#2d2d30"
        self.input_bg = "#333333"
        self.online_color = "#4ec9b0"
        self.relay_color = "#c586c0"

        self.root.configure(bg=self.bg_color)

        self._build_ui()
        self._load_existing_messages()
        self._start_watcher()
        self._start_relay()

    def _build_ui(self):
        """Build the UI components."""
        # Header with peers
        self.header = tk.Frame(self.root, bg=self.bg_color)
        self.header.pack(fill=tk.X, padx=10, pady=(10, 5))

        self.peers_label = tk.Label(
            self.header,
            text=f"@{self.username}",
            bg=self.bg_color,
            fg=self.accent_color,
            font=("Monaco", 11, "bold"),
            anchor="w",
        )
        self.peers_label.pack(side=tk.LEFT)

        self.status_dot = tk.Label(
            self.header,
            text=" ●",
            bg=self.bg_color,
            fg=self.online_color,
            font=("Monaco", 11),
        )
        self.status_dot.pack(side=tk.LEFT)

        # Relay indicator
        self.relay_indicator = tk.Label(
            self.header,
            text="",
            bg=self.bg_color,
            fg=self.relay_color,
            font=("Monaco", 9),
        )
        self.relay_indicator.pack(side=tk.RIGHT)

        # Online users label
        self.online_label = tk.Label(
            self.header,
            text="",
            bg=self.bg_color,
            fg=self.muted_color,
            font=("Monaco", 9),
        )
        self.online_label.pack(side=tk.RIGHT, padx=(0, 10))

        # Messages area
        self.messages_frame = tk.Frame(self.root, bg=self.bg_color)
        self.messages_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        # Scrollbar
        self.scrollbar = tk.Scrollbar(self.messages_frame)
        self.scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Messages text widget
        self.messages_text = tk.Text(
            self.messages_frame,
            bg=self.bg_color,
            fg=self.fg_color,
            font=("Monaco", 11),
            wrap=tk.WORD,
            state=tk.DISABLED,
            borderwidth=0,
            highlightthickness=0,
            yscrollcommand=self.scrollbar.set,
            cursor="arrow",
        )
        self.messages_text.pack(fill=tk.BOTH, expand=True)
        self.scrollbar.config(command=self.messages_text.yview)

        # Configure text tags for styling
        self.messages_text.tag_configure("sender", foreground=self.accent_color, font=("Monaco", 11, "bold"))
        self.messages_text.tag_configure("sender_you", foreground="#4ec9b0", font=("Monaco", 11, "bold"))
        self.messages_text.tag_configure("sender_claude", foreground="#c586c0", font=("Monaco", 11, "bold"))
        self.messages_text.tag_configure("sender_relay", foreground="#dcdcaa", font=("Monaco", 11, "bold"))
        self.messages_text.tag_configure("time", foreground=self.muted_color, font=("Monaco", 9))
        self.messages_text.tag_configure("unread_marker", foreground="#f48771")
        self.messages_text.tag_configure("message_text", foreground=self.fg_color)
        self.messages_text.tag_configure("priority_high", foreground="#f48771")

        # Separator
        separator = tk.Frame(self.root, height=1, bg=self.input_bg)
        separator.pack(fill=tk.X, padx=10, pady=5)

        # Input area
        self.input_frame = tk.Frame(self.root, bg=self.input_bg)
        self.input_frame.pack(fill=tk.X, padx=10, pady=(0, 5))

        self.input_field = tk.Entry(
            self.input_frame,
            bg=self.input_bg,
            fg="#ffffff",
            font=("Monaco", 11),
            insertbackground="#ffffff",
            borderwidth=0,
            relief=tk.FLAT,
        )
        self.input_field.pack(fill=tk.X, padx=8, pady=8)
        self.input_field.insert(0, "@user message")
        self.input_field.config(fg=self.muted_color)

        # Input field events
        self.input_field.bind("<FocusIn>", self._on_input_focus)
        self.input_field.bind("<FocusOut>", self._on_input_blur)
        self.input_field.bind("<Return>", self._send_message)

        # Status bar
        self.status_bar = tk.Frame(self.root, bg=self.bg_color)
        self.status_bar.pack(fill=tk.X, padx=10, pady=(0, 10))

        self.status_label = tk.Label(
            self.status_bar,
            text=f"Space: {self.default_space}",
            bg=self.bg_color,
            fg=self.muted_color,
            font=("Monaco", 9),
            anchor="w",
        )
        self.status_label.pack(side=tk.LEFT)

        # Keyboard shortcuts
        self.root.bind("<Escape>", lambda e: self.root.iconify())
        self.root.bind("<Command-w>", lambda e: self.root.iconify())

    def _on_input_focus(self, event):
        """Clear placeholder on focus."""
        if self.input_field.get() == "@user message":
            self.input_field.delete(0, tk.END)
            self.input_field.config(fg="#ffffff")

    def _on_input_blur(self, event):
        """Restore placeholder on blur if empty."""
        if not self.input_field.get():
            self.input_field.insert(0, "@user message")
            self.input_field.config(fg=self.muted_color)

    def add_message(self, sender: str, text: str, time_str: str, unread: bool = False,
                    priority: str = "normal", outgoing: bool = False, via_relay: bool = False):
        """Add a message to the display."""
        self.messages_text.config(state=tk.NORMAL)

        # Unread marker
        if unread:
            self.messages_text.insert(tk.END, "● ", "unread_marker")
        else:
            self.messages_text.insert(tk.END, "  ")

        # Sender with appropriate color
        if outgoing:
            self.messages_text.insert(tk.END, f"@{sender} ", "sender_you")
        elif sender == "claude":
            self.messages_text.insert(tk.END, f"@{sender} ", "sender_claude")
        elif via_relay:
            self.messages_text.insert(tk.END, f"@{sender} ", "sender_relay")
        else:
            self.messages_text.insert(tk.END, f"@{sender} ", "sender")

        # Timestamp and relay indicator
        relay_marker = " ↗" if via_relay else ""
        self.messages_text.insert(tk.END, f"{time_str}{relay_marker}\n", "time")

        # Priority indicator
        if priority == "high":
            self.messages_text.insert(tk.END, "  [!] ", "priority_high")
        else:
            self.messages_text.insert(tk.END, "  ")

        # Message text (truncate if too long)
        display_text = text[:200] + "..." if len(text) > 200 else text
        self.messages_text.insert(tk.END, f"{display_text}\n\n", "message_text")

        # Scroll to bottom
        self.messages_text.see(tk.END)
        self.messages_text.config(state=tk.DISABLED)

        # Notify if unread
        if unread:
            self._notify(sender, text)

    def _notify(self, sender: str, text: str):
        """Send system notification and flash window."""
        # Flash window
        self.root.attributes("-alpha", 1.0)
        self.root.after(100, lambda: self.root.attributes("-alpha", 0.95))
        self.root.after(200, lambda: self.root.attributes("-alpha", 1.0))
        self.root.after(300, lambda: self.root.attributes("-alpha", 0.95))

        # Bring to front
        self.root.lift()
        self.root.attributes("-topmost", True)

        # System notification sound (macOS)
        if sys.platform == "darwin":
            try:
                subprocess.Popen(
                    ["afplay", "/System/Library/Sounds/Ping.aiff"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except:
                pass

        # macOS notification center
        if sys.platform == "darwin":
            try:
                preview = text[:50] + "..." if len(text) > 50 else text
                script = f'display notification "{preview}" with title "Datacore" subtitle "@{sender}"'
                subprocess.Popen(
                    ["osascript", "-e", script],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except:
                pass

    def _send_message(self, event=None):
        """Send message from input field."""
        text = self.input_field.get().strip()

        # Validate input
        if not text or text == "@user message":
            return

        if not text.startswith("@"):
            self._show_error("Start with @username")
            return

        # Parse recipient and message
        parts = text.split(" ", 1)
        recipient = parts[0][1:]  # Remove @
        msg_text = parts[1] if len(parts) > 1 else ""

        if not recipient:
            self._show_error("Specify recipient: @user")
            return

        if not msg_text:
            self._show_error("Enter a message")
            return

        # Write to inbox
        msg_id = self._write_to_inbox(recipient, msg_text)

        if msg_id:
            # Try sending via relay if connected
            via_relay = False
            if self.relay_connected and self.relay_client:
                # Send via relay in background
                def send_relay():
                    asyncio.run(self.relay_client.send_message(recipient, msg_text, msg_id))
                threading.Thread(target=send_relay, daemon=True).start()
                via_relay = True

            # Show in UI
            self.add_message(
                f"you→{recipient}",
                msg_text,
                datetime.now().strftime("%H:%M"),
                unread=False,
                outgoing=True,
                via_relay=via_relay,
            )

            # Clear input
            self.input_field.delete(0, tk.END)

            # Update status
            delivery = "relay" if via_relay else "local"
            self.status_label.config(text=f"✓ Sent to @{recipient} ({delivery})")
            self.root.after(3000, lambda: self.status_label.config(text=f"Space: {self.default_space}"))
        else:
            self._show_error("Failed to send")

    def _show_error(self, msg: str):
        """Show error in status bar."""
        self.status_label.config(text=f"⚠ {msg}", fg="#f48771")
        self.root.after(3000, lambda: self.status_label.config(
            text=f"Space: {self.default_space}",
            fg=self.muted_color
        ))

    def _write_to_inbox(self, to: str, text: str) -> str | None:
        """Write message to recipient's org inbox. Returns message ID."""
        try:
            # Find or create inbox
            inbox_dir = DATACORE_ROOT / self.default_space / "org/inboxes"
            inbox_dir.mkdir(parents=True, exist_ok=True)
            inbox = inbox_dir / f"{to}.org"

            # Generate message
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

            # Append to file
            with open(inbox, "a") as f:
                f.write(entry)

            self.seen_ids.add(msg_id)
            return msg_id

        except Exception as e:
            print(f"Error writing message: {e}", file=sys.stderr)
            return None

    def _write_from_relay(self, from_user: str, text: str, priority: str = "normal") -> str | None:
        """Write message received from relay to local inbox."""
        try:
            inbox_dir = DATACORE_ROOT / self.default_space / "org/inboxes"
            inbox_dir.mkdir(parents=True, exist_ok=True)
            inbox = inbox_dir / f"{self.username}.org"

            now = datetime.now()
            msg_id = f"msg-{now.strftime('%Y%m%d-%H%M%S')}-{from_user}"
            timestamp = now.strftime("[%Y-%m-%d %a %H:%M]")

            entry = f"""
* MESSAGE {timestamp} :unread:
:PROPERTIES:
:ID: {msg_id}
:FROM: {from_user}
:TO: {self.username}
:PRIORITY: {priority}
:SOURCE: relay
:END:
{text}
"""

            with open(inbox, "a") as f:
                f.write(entry)

            return msg_id

        except Exception as e:
            print(f"Error writing relay message: {e}", file=sys.stderr)
            return None

    def _load_existing_messages(self):
        """Load last N messages from inbox on startup."""
        messages = []

        for inbox in DATACORE_ROOT.glob(f"*/org/inboxes/{self.username}.org"):
            content = inbox.read_text()

            for block in content.split("\n* MESSAGE ")[1:]:
                msg = self._parse_message_block(block)
                if msg:
                    self.seen_ids.add(msg["id"])
                    messages.append(msg)

        # Sort by time and show last 15
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

            # Extract timestamp from header
            time_str = "earlier"
            if "[" in header and "]" in header:
                ts = header[header.find("[")+1:header.find("]")]
                parts = ts.split(" ")
                if len(parts) >= 4:
                    time_str = parts[3]  # HH:MM

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
                    # Parse property line like ":FROM: gregor"
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
        except Exception as e:
            print(f"Error parsing message: {e}", file=sys.stderr)
            return None

    def _start_watcher(self):
        """Start background thread to watch for new messages."""
        self.watcher_thread = threading.Thread(target=self._watch_inbox, daemon=True)
        self.watcher_thread.start()

    def _watch_inbox(self):
        """Watch inbox files for new messages."""
        import time

        while True:
            time.sleep(POLL_INTERVAL)

            try:
                for inbox in DATACORE_ROOT.glob(f"*/org/inboxes/{self.username}.org"):
                    content = inbox.read_text()

                    for block in content.split("\n* MESSAGE ")[1:]:
                        msg = self._parse_message_block(block)

                        if msg and msg["id"] and msg["id"] not in self.seen_ids:
                            self.seen_ids.add(msg["id"])

                            # Schedule UI update on main thread
                            self.root.after(0, lambda m=msg: self.add_message(
                                m["from"],
                                m["text"],
                                m.get("time", "now"),
                                unread=m.get("unread", True),
                                priority=m.get("priority", "normal"),
                                via_relay=m.get("source") == "relay",
                            ))
            except Exception as e:
                print(f"Watcher error: {e}", file=sys.stderr)

    def _start_relay(self):
        """Start relay connection if enabled."""
        if not HAS_WEBSOCKETS:
            self.relay_indicator.config(text="(no websockets)")
            return

        if not is_relay_enabled():
            self.relay_indicator.config(text="(local only)")
            return

        token = get_relay_token()
        if not token:
            self.relay_indicator.config(text="(not logged in)")
            return

        # Start relay in background thread
        self.relay_thread = threading.Thread(target=self._relay_loop, daemon=True)
        self.relay_thread.start()

    def _relay_loop(self):
        """Run relay client in background."""
        async def run_relay():
            def on_message(data):
                """Handle incoming relay message."""
                from_user = data.get("from", "?")
                text = data.get("text", "")
                priority = data.get("priority", "normal")

                # Write to local inbox
                msg_id = self._write_from_relay(from_user, text, priority)

                if msg_id and msg_id not in self.seen_ids:
                    self.seen_ids.add(msg_id)

                    # Update UI
                    self.root.after(0, lambda: self.add_message(
                        from_user,
                        text,
                        datetime.now().strftime("%H:%M"),
                        unread=True,
                        priority=priority,
                        via_relay=True,
                    ))

            def on_presence(online_users):
                """Handle presence update."""
                count = len(online_users)
                self.root.after(0, lambda: self.online_label.config(
                    text=f"{count} online" if count > 0 else ""
                ))

            def on_status(status):
                """Handle status update."""
                self.root.after(0, lambda: self.relay_indicator.config(text=f"({status[:20]})"))

            self.relay_client = RelayClient(
                get_relay_url(),
                get_relay_token(),
                on_message=on_message,
                on_presence=on_presence,
                on_status=on_status,
            )

            if await self.relay_client.connect():
                self.relay_connected = True
                self.root.after(0, lambda: self.relay_indicator.config(
                    text="● relay",
                    fg=self.online_color
                ))
                await self.relay_client.listen()
            else:
                self.relay_connected = False
                self.root.after(0, lambda: self.relay_indicator.config(
                    text="(relay failed)",
                    fg="#f48771"
                ))

        asyncio.run(run_relay())

    def run(self):
        """Start the application."""
        print(f"Datacore Messages - @{self.username}")
        print(f"Watching: {DATACORE_ROOT}/*/org/inboxes/{self.username}.org")
        if is_relay_enabled():
            print(f"Relay: {get_relay_url()}")
        print("Window opened. Press Cmd+W or Escape to minimize.")
        self.root.mainloop()


def main():
    """Entry point."""
    # Check for help
    if len(sys.argv) > 1 and sys.argv[1] in ["-h", "--help"]:
        print(__doc__)
        sys.exit(0)

    # Ensure DATACORE_ROOT exists
    if not DATACORE_ROOT.exists():
        print(f"Error: DATACORE_ROOT not found: {DATACORE_ROOT}", file=sys.stderr)
        print("Set DATACORE_ROOT environment variable or ensure ~/Data exists.", file=sys.stderr)
        sys.exit(1)

    # Create and run app
    app = MessageWindow()
    app.run()


if __name__ == "__main__":
    main()
