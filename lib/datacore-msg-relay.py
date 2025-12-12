#!/usr/bin/env python3
"""
datacore-msg-relay - WebSocket relay server for Datacore messaging

Deployed on fly.io, authenticates users via GitHub OAuth.

Environment variables:
    GITHUB_CLIENT_ID     - GitHub OAuth app client ID
    GITHUB_CLIENT_SECRET - GitHub OAuth app client secret
    RELAY_SECRET         - Secret for signing session tokens
    ALLOWED_ORG          - (optional) Restrict to GitHub org members

Usage:
    # Local development
    python datacore-msg-relay.py

    # Production (fly.io)
    fly deploy
"""

import asyncio
import hashlib
import hmac
import json
import os
import secrets
import time
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import parse_qs, urlencode

import aiohttp
from aiohttp import web, WSMsgType

# === CONFIG ===

GITHUB_CLIENT_ID = os.environ.get("GITHUB_CLIENT_ID", "")
GITHUB_CLIENT_SECRET = os.environ.get("GITHUB_CLIENT_SECRET", "")
RELAY_SECRET = os.environ.get("RELAY_SECRET", secrets.token_hex(32))
ALLOWED_ORG = os.environ.get("ALLOWED_ORG", "")  # e.g., "datafund"
PORT = int(os.environ.get("PORT", 8080))

# Token validity: 7 days
TOKEN_EXPIRY = 7 * 24 * 60 * 60


# === DATA STRUCTURES ===

@dataclass
class User:
    """Connected user."""
    username: str
    ws: web.WebSocketResponse
    github_id: int
    avatar_url: str = ""
    connected_at: float = field(default_factory=time.time)


@dataclass
class RelayServer:
    """Manages WebSocket connections and message routing."""
    users: dict[str, User] = field(default_factory=dict)
    pending_auth: dict[str, dict] = field(default_factory=dict)  # state -> callback info

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

    async def route_message(self, from_user: str, to_user: str, message: dict):
        """Route message to recipient if online."""
        recipient = self.users.get(to_user)
        if recipient:
            await recipient.ws.send_json({
                "type": "message",
                "from": from_user,
                **message
            })
            return True
        return False


relay = RelayServer()


# === AUTH ===

def generate_token(username: str, github_id: int) -> str:
    """Generate signed session token."""
    expires = int(time.time()) + TOKEN_EXPIRY
    payload = f"{username}:{github_id}:{expires}"
    sig = hmac.new(
        RELAY_SECRET.encode(),
        payload.encode(),
        hashlib.sha256
    ).hexdigest()[:16]
    return f"{payload}:{sig}"


def verify_token(token: str) -> Optional[tuple[str, int]]:
    """Verify token and return (username, github_id) or None."""
    try:
        parts = token.split(":")
        if len(parts) != 4:
            return None

        username, github_id, expires, sig = parts
        expires = int(expires)
        github_id = int(github_id)

        # Check expiry
        if time.time() > expires:
            return None

        # Verify signature
        payload = f"{username}:{github_id}:{expires}"
        expected_sig = hmac.new(
            RELAY_SECRET.encode(),
            payload.encode(),
            hashlib.sha256
        ).hexdigest()[:16]

        if not hmac.compare_digest(sig, expected_sig):
            return None

        return (username, github_id)
    except:
        return None


async def check_org_membership(token: str, org: str) -> bool:
    """Check if user is member of GitHub org."""
    if not org:
        return True

    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"https://api.github.com/user/orgs",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github.v3+json"
            }
        ) as resp:
            if resp.status != 200:
                return False
            orgs = await resp.json()
            return any(o.get("login") == org for o in orgs)


# === HTTP HANDLERS ===

async def handle_auth_start(request: web.Request) -> web.Response:
    """Start GitHub OAuth flow."""
    if not GITHUB_CLIENT_ID:
        return web.json_response(
            {"error": "OAuth not configured"},
            status=500
        )

    # Generate state for CSRF protection
    state = secrets.token_urlsafe(32)
    callback_url = request.query.get("callback", "")

    relay.pending_auth[state] = {
        "callback": callback_url,
        "created": time.time()
    }

    # Clean old pending auth states
    now = time.time()
    relay.pending_auth = {
        k: v for k, v in relay.pending_auth.items()
        if now - v["created"] < 600  # 10 minute expiry
    }

    params = urlencode({
        "client_id": GITHUB_CLIENT_ID,
        "redirect_uri": f"{request.scheme}://{request.host}/auth/callback",
        "scope": "read:user read:org",
        "state": state
    })

    return web.HTTPFound(f"https://github.com/login/oauth/authorize?{params}")


async def handle_auth_callback(request: web.Request) -> web.Response:
    """Handle GitHub OAuth callback."""
    code = request.query.get("code")
    state = request.query.get("state")

    if not code or not state:
        return web.Response(text="Missing code or state", status=400)

    # Verify state
    auth_info = relay.pending_auth.pop(state, None)
    if not auth_info:
        return web.Response(text="Invalid or expired state", status=400)

    # Exchange code for token
    async with aiohttp.ClientSession() as session:
        async with session.post(
            "https://github.com/login/oauth/access_token",
            headers={"Accept": "application/json"},
            data={
                "client_id": GITHUB_CLIENT_ID,
                "client_secret": GITHUB_CLIENT_SECRET,
                "code": code,
                "redirect_uri": f"{request.scheme}://{request.host}/auth/callback"
            }
        ) as resp:
            if resp.status != 200:
                return web.Response(text="Token exchange failed", status=500)
            token_data = await resp.json()

        access_token = token_data.get("access_token")
        if not access_token:
            error = token_data.get("error_description", "Unknown error")
            return web.Response(text=f"Auth failed: {error}", status=400)

        # Get user info
        async with session.get(
            "https://api.github.com/user",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/vnd.github.v3+json"
            }
        ) as resp:
            if resp.status != 200:
                return web.Response(text="Failed to get user info", status=500)
            user_data = await resp.json()

        # Check org membership if required
        if ALLOWED_ORG:
            is_member = await check_org_membership(access_token, ALLOWED_ORG)
            if not is_member:
                return web.Response(
                    text=f"Access denied: not a member of {ALLOWED_ORG}",
                    status=403
                )

    username = user_data["login"]
    github_id = user_data["id"]

    # Generate relay token
    relay_token = generate_token(username, github_id)

    # Return token (either via callback or directly)
    callback = auth_info.get("callback")
    if callback:
        # Redirect to callback with token
        return web.HTTPFound(f"{callback}?token={relay_token}&username={username}")

    # Return HTML page that can be read by CLI
    html = f"""<!DOCTYPE html>
<html>
<head><title>Datacore Auth Success</title></head>
<body>
<h1>Authentication Successful</h1>
<p>You are signed in as <strong>@{username}</strong></p>
<p>Token: <code id="token">{relay_token}</code></p>
<p>You can close this window and return to the terminal.</p>
<script>
// Try to copy token to clipboard
navigator.clipboard.writeText("{relay_token}").catch(() => {{}});
</script>
</body>
</html>"""
    return web.Response(text=html, content_type="text/html")


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
    github_id = None

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
                    token = data.get("token")
                    result = verify_token(token)

                    if not result:
                        await ws.send_json({
                            "type": "auth_error",
                            "message": "Invalid or expired token"
                        })
                        continue

                    username, github_id = result

                    # Add to relay
                    relay.add_user(User(
                        username=username,
                        ws=ws,
                        github_id=github_id
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

                    # Try to deliver
                    delivered = await relay.route_message(
                        from_user=username,
                        to_user=to_user,
                        message={
                            "text": text,
                            "priority": priority,
                            "msg_id": msg_id,
                            "timestamp": time.time()
                        }
                    )

                    await ws.send_json({
                        "type": "send_ack",
                        "to": to_user,
                        "msg_id": msg_id,
                        "delivered": delivered,
                        "queued": not delivered  # If not delivered, it's queued locally
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
    app.router.add_get("/auth/start", handle_auth_start)
    app.router.add_get("/auth/callback", handle_auth_callback)
    app.router.add_get("/ws", handle_websocket)

    return app


def main():
    """Run the relay server."""
    if not GITHUB_CLIENT_ID or not GITHUB_CLIENT_SECRET:
        print("Warning: GITHUB_CLIENT_ID/SECRET not set. OAuth disabled.")
        print("Set these environment variables for production use.")

    app = create_app()
    print(f"Starting relay server on port {PORT}")
    print(f"Allowed org: {ALLOWED_ORG or '(any)'}")
    web.run_app(app, port=PORT)


if __name__ == "__main__":
    main()
