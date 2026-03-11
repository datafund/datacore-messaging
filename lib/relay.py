"""WebSocket relay server — single consolidated implementation.

Replaces the three duplicate relay files (lib/, relay/, embedded in GUI).
Fixes: auth leak on /status, -h flag collision, empty secret startup.
"""

import argparse
import json
import logging
import os
import time
from dataclasses import dataclass, field

from aiohttp import web, WSMsgType

logger = logging.getLogger(__name__)


@dataclass
class User:
    username: str
    ws: web.WebSocketResponse
    connected_at: float = field(default_factory=time.time)
    status: str = "online"


class RelayServer:
    def __init__(self, secret: str, claude_whitelist: dict | None = None):
        self.secret = secret
        self.users: dict[str, User] = {}
        self.claude_whitelist = claude_whitelist or {}

    def add_user(self, username: str, ws: web.WebSocketResponse) -> None:
        self.users[username] = User(username=username, ws=ws)

    def remove_user(self, username: str) -> None:
        self.users.pop(username, None)

    def list_users(self) -> list[str]:
        return list(self.users.keys())

    def connected_count(self) -> int:
        return len(self.users)

    async def route_message(self, msg: dict, sender: str) -> bool:
        target = msg.get("to", "")
        if not target or target not in self.users:
            return False
        try:
            await self.users[target].ws.send_json(msg)
            return True
        except Exception:
            logger.warning("Failed to deliver message to %s", target)
            return False

    async def broadcast_presence(self, username: str, status: str) -> None:
        event = {"type": "presence", "username": username, "status": status}
        for user in self.users.values():
            if user.username != username:
                try:
                    await user.ws.send_json(event)
                except Exception:
                    pass


def create_relay_app(relay_secret: str) -> web.Application:
    """Create the aiohttp relay application. Raises ValueError if relay_secret is empty."""
    if not relay_secret:
        raise ValueError(
            "RELAY_SECRET must be set. "
            "Generate one with: python -c 'import secrets; print(secrets.token_hex(32))'"
        )

    relay = RelayServer(secret=relay_secret)
    app = web.Application()
    app["relay"] = relay

    async def handle_status(request: web.Request) -> web.Response:
        """Status endpoint — shows connected count only, never usernames."""
        return web.json_response({"status": "ok", "connected": relay.connected_count()})

    async def handle_ws(request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        username = None
        try:
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    try:
                        data = json.loads(msg.data)
                    except json.JSONDecodeError:
                        continue
                    msg_type = data.get("type")
                    if msg_type == "auth":
                        if data.get("secret") != relay.secret:
                            await ws.send_json({"type": "error", "message": "Invalid secret"})
                            await ws.close()
                            return ws
                        username = data.get("username", "")
                        if not username:
                            await ws.send_json({"type": "error", "message": "Username required"})
                            await ws.close()
                            return ws
                        relay.add_user(username, ws)
                        await ws.send_json({"type": "auth_ok"})
                        await relay.broadcast_presence(username, "online")
                        logger.info("User connected: %s", username)
                    elif msg_type == "send" and username:
                        payload = {
                            "type": "message", "from": username, "to": data.get("to"),
                            "content": data.get("content", ""), "id": data.get("id", ""),
                            "thread": data.get("thread"), "reply_to": data.get("reply_to"),
                            "timestamp": data.get("timestamp", time.strftime("%Y-%m-%dT%H:%M:%S")),
                        }
                        delivered = await relay.route_message(payload, username)
                        if not delivered:
                            await ws.send_json({"type": "error", "message": f"User {data.get('to')} not online"})
                    elif msg_type == "status_change" and username:
                        new_status = data.get("status", "online")
                        if username in relay.users:
                            relay.users[username].status = new_status
                        await relay.broadcast_presence(username, new_status)
                    elif msg_type == "ping":
                        await ws.send_json({"type": "pong"})
                elif msg.type == WSMsgType.ERROR:
                    logger.error("WS error: %s", ws.exception())
        finally:
            if username:
                relay.remove_user(username)
                await relay.broadcast_presence(username, "offline")
                logger.info("User disconnected: %s", username)
        return ws

    app.router.add_get("/status", handle_status)
    app.router.add_get("/ws", handle_ws)
    return app


def parse_relay_args(args: list[str] | None = None) -> argparse.Namespace:
    """Parse relay CLI arguments. Uses --host (not -h) for hosting."""
    parser = argparse.ArgumentParser(description="Datacore messaging relay")
    parser.add_argument("--host", action="store_true", help="Host relay server")
    parser.add_argument("--port", type=int, default=8080, help="Port (default: 8080)")
    parser.add_argument("--bind", default="0.0.0.0", help="Bind address")
    return parser.parse_args(args)


def run_relay() -> None:
    """Entry point for standalone relay server."""
    args = parse_relay_args()
    secret = os.environ.get("RELAY_SECRET", "")
    app = create_relay_app(relay_secret=secret)
    web.run_app(app, host=args.bind, port=args.port)


if __name__ == "__main__":
    run_relay()
