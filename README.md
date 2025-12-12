# Datacore Module: Messaging

Real-time team messaging with Claude Code integration.

## Features

- **GUI Window**: Floating always-on-top window for sending/receiving messages
- **Claude Code integration**: Message `@claude` to delegate AI tasks to your personal Claude
- **Namespaced agents**: `@tex-claude`, `@gregor-claude` - each user has their own Claude
- **Whitelist control**: Choose who can message your Claude (others get auto-reply)
- **WebSocket relay**: Real-time delivery via `datacore-messaging-relay.datafund.io`
- **Local storage**: Messages saved as org-mode entries for offline access

## Installation

```bash
cd ~/Data/.datacore/modules
git clone https://github.com/datafund/datacore-messaging.git messaging
cd messaging
./install.sh
```

The installer will:
- Install Python dependencies (PyQt6, websockets, pyyaml, aiohttp)
- Create `settings.local.yaml` from template
- Add Claude Code hook to `~/.claude/settings.json`

## Configuration

Edit `settings.local.yaml`:

```yaml
identity:
  name: yourname                   # Your username (required)

messaging:
  default_space: 1-datafund        # Space for message inboxes

  claude_whitelist:                # Who can message @yourname-claude
    - gregor
    - crt

  relay:
    secret: "your-team-secret"     # Same for all team members
    url: "wss://datacore-messaging-relay.datafund.io/ws"
```

## Usage

### Start the GUI

```bash
./start.sh
# Or directly:
python3 datacore-msg.py
```

### Send Messages

In the GUI input field:
- `@gregor Hey, can you review the PR?` - Message a teammate
- `@claude Research competitor pricing` - Message your Claude agent
- `@gregor-claude Help with code review` - Message someone else's Claude (if whitelisted)

### GUI Features

- Always-on-top floating window
- Dark theme
- Real-time message updates
- Online users count
- System notifications (macOS)
- `@claude` automatically routes to your personal `@yourname-claude`

```
┌─ Messages @tex ──────────── ● relay ─┐
│                              2 online │
│ ● @gregor 14:30                       │
│   Need OAuth keys - see issue #25     │
│                                       │
│ ● @tex-claude 14:35                   │
│   Research complete. See research/    │
│                                       │
│   @you→gregor 14:40                   │
│   Keys are in the vault               │
│                                       │
├───────────────────────────────────────┤
│ @gregor message here...               │
├───────────────────────────────────────┤
│ Space: 1-datafund                     │
└───────────────────────────────────────┘
```

## Claude Code Integration

### Receiving Messages

The installer adds a hook that shows new messages when you interact with Claude:

```
📬 New messages for @tex-claude:

From @gregor (14:30):
  Can you help debug the auth flow?

---
Reply using the messaging system or directly in conversation.
```

### Sending Replies from Claude

```bash
# Claude can reply via the send-reply script
python3 hooks/send-reply.py gregor "Fixed! Check the PR."
```

## How It Works

### Message Flow

1. You type `@gregor hello` in GUI
2. Message saved to `~/Data/1-datafund/org/inboxes/gregor.org`
3. Message sent via WebSocket relay (if online)
4. Gregor's GUI shows notification instantly

### @claude Routing

- `@claude do this` → routes to `@yourname-claude`
- Each user's Claude is separate
- Whitelist controls who can message your Claude
- Non-whitelisted users get: "Auto-reply: @tex-claude is not accepting messages from @bob"

### Message Storage (org-mode)

```org
* MESSAGE [2025-12-12 Fri 14:30] :unread:
:PROPERTIES:
:ID: msg-20251212-143000-gregor
:FROM: gregor
:TO: tex
:PRIORITY: normal
:END:
Can you review PR #24?
```

## Relay Server

The relay enables real-time messaging between team members.

**Default relay**: `wss://datacore-messaging-relay.datafund.io/ws`

### Deploy Your Own

See `relay/README.md` for Docker deployment instructions.

```bash
cd relay/
echo "RELAY_SECRET=your-secret" > .env
docker-compose up -d --build
```

## Files

```
datacore-msg.py           # Unified GUI app
install.sh                # Interactive installer
settings.local.yaml       # Your settings (gitignored)

hooks/
├── inbox-watcher.py      # Claude Code hook
└── send-reply.py         # Reply helper for Claude

relay/
├── Dockerfile
├── docker-compose.yml
├── datacore-msg-relay.py
└── README.md

lib/
├── datacore-msg-relay.py # Relay server
└── datacore-msg-window.py # Legacy GUI (PyQt6)
```

## Requirements

- Python 3.8+
- PyQt6: `pip install PyQt6`
- websockets: `pip install websockets`
- pyyaml: `pip install pyyaml`

## License

MIT
