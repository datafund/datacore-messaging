#!/usr/bin/env python3
"""
datacore-msg-relay - WebSocket relay server for Datacore messaging

Simple shared-secret authentication for team messaging.

Environment variables:
    RELAY_SECRET - Shared secret for authentication (required)
    PORT         - Server port (default: 8080)

Usage:
    # Local development
    RELAY_SECRET=mysecret python datacore-msg-relay.py

    # Production (fly.io)
    fly secrets set RELAY_SECRET=$(openssl rand -hex 32)
    fly deploy
"""

import asyncio
import json
import os
import time
from dataclasses import dataclass, field
from typing import Optional

from aiohttp import web, WSMsgType

# === CONFIG ===

RELAY_SECRET = os.environ.get("RELAY_SECRET", "")
PORT = int(os.environ.get("PORT", 8080))


# === DATA STRUCTURES ===

@dataclass
class User:
    """Connected user."""
    username: str
    ws: web.WebSocketResponse
    connected_at: float = field(default_factory=time.time)
    claude_whitelist: list = field(default_factory=list)  # Users allowed to message this user's Claude


@dataclass
class RelayServer:
    """Manages WebSocket connections and message routing."""
    users: dict[str, User] = field(default_factory=dict)

    def add_user(self, user: User):
        """Add connected user."""
        # Disconnect existing connection if any
        if user.username in self.users:
            old = self.users[user.username]
            asyncio.create_task(old.ws.close())
        self.users[user.username] = user

    def remove_user(self, username: str):
        """Remove disconnected user."""
        self.users.pop(username, None)

    def get_user(self, username: str) -> Optional[User]:
        """Get user by username."""
        return self.users.get(username)

    def list_users(self) -> list[str]:
        """List connected usernames."""
        return list(self.users.keys())

    def resolve_claude_target(self, from_user: str, to_user: str) -> tuple:
        """
        Resolve @claude to the sender's personal Claude agent.
        Returns (resolved_target, is_allowed, auto_reply_msg).
        """
        if to_user == "claude":
            # Route @claude to sender's personal Claude: @<sender>-claude
            resolved = f"{from_user}-claude"
            return (resolved, True, None)

        # Check if messaging someone else's Claude (e.g., @gregor-claude)
        if to_user.endswith("-claude"):
            owner = to_user.rsplit("-claude", 1)[0]
            owner_user = self.users.get(owner)

            # Check if owner has a whitelist configured
            if owner_user and owner_user.claude_whitelist:
                if from_user not in owner_user.claude_whitelist:
                    # Not whitelisted - return auto-reply
                    return (to_user, False,
                            f"Auto-reply: @{owner}-claude is not accepting messages from @{from_user}. "
                            f"Please contact @{owner} directly.")

        return (to_user, True, None)

    async def route_message(self, from_user: str, to_user: str, message: dict, sender_ws=None):
        """Route message to recipient if online."""
        # Resolve @claude and check permissions
        resolved_target, is_allowed, auto_reply = self.resolve_claude_target(from_user, to_user)

        if not is_allowed and auto_reply and sender_ws:
            # Send auto-reply back to sender
            await sender_ws.send_json({
                "type": "message",
                "from": resolved_target,
                "text": auto_reply,
                "priority": "normal",
                "auto_reply": True
            })
            return "auto_replied"

        recipient = self.users.get(resolved_target)
        if recipient:
            await recipient.ws.send_json({
                "type": "message",
                "from": from_user,
                **message
            })
            return True
        return False


relay = RelayServer()


# === HTTP HANDLERS ===

async def handle_status(request: web.Request) -> web.Response:
    """Return relay status."""
    return web.json_response({
        "status": "ok",
        "users_online": len(relay.users),
        "users": relay.list_users()
    })


# === WEBSOCKET HANDLER ===

async def handle_websocket(request: web.Request) -> web.WebSocketResponse:
    """Handle WebSocket connections."""
    ws = web.WebSocketResponse(heartbeat=30)
    await ws.prepare(request)

    username = None

    try:
        async for msg in ws:
            if msg.type == WSMsgType.TEXT:
                try:
                    data = json.loads(msg.data)
                except json.JSONDecodeError:
                    await ws.send_json({"type": "error", "message": "Invalid JSON"})
                    continue

                msg_type = data.get("type")

                # === AUTH ===
                if msg_type == "auth":
                    secret = data.get("secret", "")
                    claimed_username = data.get("username", "")

                    # Verify shared secret
                    if not RELAY_SECRET:
                        await ws.send_json({
                            "type": "auth_error",
                            "message": "Server not configured (no RELAY_SECRET)"
                        })
                        continue

                    if secret != RELAY_SECRET:
                        await ws.send_json({
                            "type": "auth_error",
                            "message": "Invalid secret"
                        })
                        continue

                    if not claimed_username:
                        await ws.send_json({
                            "type": "auth_error",
                            "message": "Username required"
                        })
                        continue

                    username = claimed_username
                    claude_whitelist = data.get("claude_whitelist", [])

                    # Add to relay
                    relay.add_user(User(
                        username=username,
                        ws=ws,
                        claude_whitelist=claude_whitelist
                    ))

                    await ws.send_json({
                        "type": "auth_ok",
                        "username": username,
                        "online": relay.list_users()
                    })

                    # Broadcast presence
                    await broadcast_presence(username, "online")

                # === PRESENCE ===
                elif msg_type == "presence":
                    if not username:
                        await ws.send_json({"type": "error", "message": "Not authenticated"})
                        continue

                    await ws.send_json({
                        "type": "presence",
                        "online": relay.list_users()
                    })

                # === SEND MESSAGE ===
                elif msg_type == "send":
                    if not username:
                        await ws.send_json({"type": "error", "message": "Not authenticated"})
                        continue

                    to_user = data.get("to", "").lstrip("@")
                    text = data.get("text", "")
                    priority = data.get("priority", "normal")
                    msg_id = data.get("msg_id", "")

                    if not to_user or not text:
                        await ws.send_json({
                            "type": "error",
                            "message": "Missing 'to' or 'text'"
                        })
                        continue

                    # Resolve @claude to sender's personal Claude
                    resolved_target, _, _ = relay.resolve_claude_target(username, to_user)

                    # Try to deliver
                    result = await relay.route_message(
                        from_user=username,
                        to_user=to_user,
                        message={
                            "text": text,
                            "priority": priority,
                            "msg_id": msg_id,
                            "timestamp": time.time()
                        },
                        sender_ws=ws
                    )

                    if result == "auto_replied":
                        await ws.send_json({
                            "type": "send_ack",
                            "to": resolved_target,
                            "msg_id": msg_id,
                            "delivered": False,
                            "auto_replied": True
                        })
                    else:
                        await ws.send_json({
                            "type": "send_ack",
                            "to": resolved_target,
                            "msg_id": msg_id,
                            "delivered": bool(result),
                            "queued": not result
                        })

                # === PING/PONG ===
                elif msg_type == "ping":
                    await ws.send_json({"type": "pong"})

            elif msg.type == WSMsgType.ERROR:
                print(f"WebSocket error: {ws.exception()}")

    finally:
        if username:
            relay.remove_user(username)
            await broadcast_presence(username, "offline")

    return ws


async def broadcast_presence(username: str, status: str):
    """Broadcast user presence change to all connected users."""
    message = {
        "type": "presence_change",
        "user": username,
        "status": status,
        "online": relay.list_users()
    }

    for user in list(relay.users.values()):
        if user.username != username:
            try:
                await user.ws.send_json(message)
            except:
                pass


# === APP ===

def create_app() -> web.Application:
    """Create aiohttp application."""
    app = web.Application()

    app.router.add_get("/", handle_status)
    app.router.add_get("/status", handle_status)
    app.router.add_get("/ws", handle_websocket)

    return app


def main():
    """Run the relay server."""
    if not RELAY_SECRET:
        print("WARNING: RELAY_SECRET not set!")
        print("Set RELAY_SECRET environment variable for authentication.")
        print("Example: RELAY_SECRET=mysecret python datacore-msg-relay.py")
        print()

    app = create_app()
    print(f"Starting relay server on port {PORT}")
    print(f"Secret configured: {'yes' if RELAY_SECRET else 'NO'}")
    web.run_app(app, port=PORT)


if __name__ == "__main__":
    main()
