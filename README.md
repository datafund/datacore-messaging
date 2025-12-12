# Datacore Module: Messaging

Inter-user messaging for Datacore via shared space inboxes.

## Features

- **Direct messages**: Send messages to team members via `/msg @user "message"`
- **Inbox management**: View your messages with `/my-messages`
- **Threaded replies**: Reply to messages with `/reply`
- **Claude Code integration**: Message `@claude` to delegate AI tasks
- **Daily briefing**: Unread count shown in `/today` output
- **Git-based delivery**: Messages sync via existing `./sync` workflow
- **Real-time UI**: Floating window shows messages as they arrive
- **Terminal CLI**: Pure terminal messaging with socket notifications
- **Internet relay**: Connect remote users via WebSocket relay with shared secret
- **Namespaced agents**: `@tex-claude`, `@gregor-claude` for per-user AI agents

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

After install, edit `settings.local.yaml` with your username and relay secret.

## Configuration

Add to `.datacore/settings.local.yaml`:

```yaml
identity:
  name: yourname                   # Your username (required)
  handles: ["@yourname", "@yn"]    # Aliases others can use to reach you

messaging:
  default_space: datafund          # Default space for /msg
  show_in_today: true              # Include unread count in /today briefing
  relay:
    secret: "your-team-shared-secret"    # Shared secret (same for all team members)
    url: "wss://datacore-messaging-relay.datafund.io"  # Relay server URL (optional)
```

## Usage

### Claude Code Commands

```bash
# Send a message
/msg @crt "Need API keys for OAuth - see issue #25"
/msg @crt "Urgent: server down" --priority high

# Read messages
/my-messages              # Show all unread
/my-messages --all        # Include read messages

# Reply to a message
/reply last "Got it, will do"

# Message AI
/msg @claude "Research competitor pricing and add to research/"
```

### Real-Time Message Window

Launch a floating window that shows messages in real-time:

```bash
python ~/.datacore/modules/messaging/lib/datacore-msg-window.py
```

Features:
- Always-on-top floating window (top-right corner)
- Dark theme with relay status indicator
- Real-time updates (local + relay)
- System notifications with sound
- Send messages inline
- macOS native notifications
- Shows online users count when relay connected

```
┌─ Messages @gregor ─────────────────● relay─┐
│                                 3 online   │
│ ● @crt 14:30 ↗                             │
│   Need OAuth keys - see issue #25          │
│                                            │
│ ● @claude 14:35                            │
│   Research complete. See research/         │
│                                            │
│   @you→crt 14:40 ↗                         │
│   Keys are in the vault                    │
│                                            │
├────────────────────────────────────────────┤
│ @crt Thanks! ____________________          │
├────────────────────────────────────────────┤
│ ✓ Sent to @crt (relay)                     │
└────────────────────────────────────────────┘
```

### Terminal CLI

Pure terminal messaging with socket-based notifications:

```bash
# Interactive mode
~/.datacore/modules/messaging/lib/datacore-msg

# One-shot commands
datacore-msg send @crt "Check PR #24"
datacore-msg read
datacore-msg read --all
datacore-msg peers
datacore-msg watch      # Watch for new messages
datacore-msg daemon     # Run notification daemon (background)
datacore-msg connect    # Connect to relay in interactive mode
```

Interactive mode:
```
datacore-msg | @gregor (relay: wss://datacore-messaging-relay.datafund.io)
Online: @crt, @claude, @gregor
Commands: @user msg | /read | /peers | /local | /quit

> @crt Need those OAuth keys
  ✓ delivered
> /peers
Online: @crt, @claude
> /read
```

### Run Notification Daemon

For real-time terminal notifications, run the daemon in background:

```bash
# Start daemon
~/.datacore/modules/messaging/lib/datacore-msg daemon &

# Or for Claude agent
DATACORE_USER=claude datacore-msg daemon &
```

The daemon:
- Listens on Unix socket (`/tmp/datacore-msg-{user}.sock`)
- Receives pings when messages arrive
- Forwards @claude messages to Claude Code session via named pipe

## Relay Server

The relay server enables messaging between users on different machines over the internet.

### Architecture

```
┌─────────────┐     WebSocket      ┌─────────────┐
│   User A    │◄──────────────────►│   Relay     │
│  (macOS)    │                    │  (fly.io)   │
└─────────────┘                    └──────┬──────┘
                                          │
┌─────────────┐     WebSocket             │
│   User B    │◄──────────────────────────┘
│  (Linux)    │
└─────────────┘
```

### Deploy Your Own Relay

1. **Generate a shared secret**

   ```bash
   # Generate a random secret
   openssl rand -hex 32
   # Example output: a1b2c3d4e5f6...
   ```

   Share this secret with your team members (via secure channel).

2. **Deploy to fly.io**

   ```bash
   # Install flyctl
   curl -L https://fly.io/install.sh | sh

   # Login to fly.io
   fly auth login

   # Create app
   cd ~/.datacore/modules/messaging
   fly launch --copy-config --name datacore-relay

   # Set the shared secret
   fly secrets set RELAY_SECRET=your-shared-secret

   # Deploy
   fly deploy
   ```

3. **Configure Clients**

   Each team member adds to their `settings.local.yaml`:
   ```yaml
   messaging:
     relay:
       secret: "your-shared-secret"  # Same secret for everyone
       url: "wss://datacore-messaging-relay.datafund.io"
   ```

4. **Connect**

   ```bash
   datacore-msg connect
   # Or just run datacore-msg - it auto-connects if secret is configured
   ```

### Relay Protocol

The relay uses JSON over WebSocket:

```json
// Authentication (shared secret)
{"type": "auth", "secret": "your-shared-secret", "username": "gregor"}
{"type": "auth_ok", "username": "gregor", "online": ["crt", "claude"]}

// Send message
{"type": "send", "to": "crt", "text": "Hello!", "msg_id": "...", "priority": "normal"}
{"type": "send_ack", "to": "crt", "delivered": true}

// Receive message
{"type": "message", "from": "crt", "text": "Hello!", "priority": "normal"}

// Presence
{"type": "presence"}
{"type": "presence", "online": ["gregor", "crt", "claude"]}
{"type": "presence_change", "user": "crt", "status": "offline", "online": ["gregor"]}
```

## How It Works

### Message Storage

Messages are stored as org-mode entries in shared space inboxes:

```
1-datafund/
└── org/
    └── inboxes/
        ├── USERS.yaml        # User registry
        ├── gregor.org        # Gregor's inbox
        ├── crt.org           # Črt's inbox
        └── claude.org        # AI task inbox
```

### Message Format

```org
* MESSAGE [2025-12-11 Thu 13:00] :unread:
:PROPERTIES:
:ID: msg-20251211-130000-gregor
:FROM: gregor
:TO: crt
:PRIORITY: normal
:SOURCE: relay
:END:
Your message content here.
```

### Delivery Modes

**Git-based (reliable, offline-capable):**
1. Sender runs `/msg` → message written to org file
2. Sender runs `./sync push`
3. Recipient runs `./sync` → pulls new messages
4. `/today` briefing shows unread count

**Socket-based (real-time, same machine):**
1. Sender writes message to org file
2. Sender pings recipient's socket
3. Recipient's daemon/window shows notification immediately

**Relay-based (real-time, internet):**
1. Sender writes message to local org file
2. Sender sends via WebSocket to relay
3. Relay routes to recipient if online
4. Recipient receives instantly + writes to local inbox

### User Discovery

Users are auto-registered when they first send a message:

```yaml
# USERS.yaml
users:
  gregor:
    handles: ["@gregor", "@gz"]
    added: 2025-12-11
  claude:
    handles: ["@claude", "@ai"]
    added: 2025-12-11
    type: ai
```

Online peers discovered via:
- Local: Socket existence (`/tmp/datacore-msg-*.sock`)
- Relay: Presence query to relay server

## Commands Reference

| Command | Description |
|---------|-------------|
| `/msg @user "text"` | Send message to user |
| `/my-messages` | Show your inbox |
| `/reply [id] "text"` | Reply to a message |
| `/msg-add-user name` | Add user to registry |
| `/broadcast "text"` | Message all team members |

## CLI Reference

| Command | Description |
|---------|-------------|
| `datacore-msg` | Interactive mode (auto-detects relay) |
| `datacore-msg send @user "msg"` | Send message |
| `datacore-msg read` | Read unread messages |
| `datacore-msg read --all` | Read all messages |
| `datacore-msg peers` | List online peers |
| `datacore-msg watch` | Watch for new messages |
| `datacore-msg daemon` | Run notification daemon |
| `datacore-msg connect` | Connect to relay server |

## Integration

### Daily Briefing (/today)

When `messaging.show_in_today: true`, your briefing includes:

```markdown
### Messages
3 unread messages from 2 people
- @gregor (2): OAuth keys, PR review
- @system (1): Weekly reminder
```

### AI Task Routing

Messages to `@claude` are tagged `:AI:` and processed by `ai-task-executor`:

```bash
/msg @claude "Research X and write summary"
# → Creates task in claude.org inbox
# → ai-task-executor routes to appropriate agent
# → Result sent back to your inbox
```

### Claude Code Hook Integration

Install the inbox watcher hook to receive messages directly in Claude Code sessions:

**1. Add to `~/.claude/settings.json` or `.claude/settings.local.json`:**

```json
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
```

**2. How it works:**
- Hook runs before each user prompt
- Checks `<user>-claude.org` inbox for unread messages
- Injects new messages into Claude's context
- Tracks seen messages to avoid duplicates

**3. Send replies from Claude:**

```bash
# Claude can reply using the send-reply script
./hooks/send-reply.py tex "Task completed!"
```

### User Naming Convention

Each user has a personal Claude agent with namespaced identity:

| User | Human Identity | Claude Agent |
|------|----------------|--------------|
| tex | `@tex` | `@tex-claude` |
| gregor | `@gregor` | `@gregor-claude` |

This prevents conflicts when multiple users run Claude agents simultaneously.

## Files

```
lib/
├── datacore-msg           # Terminal CLI (Python)
├── datacore-msg-window.py # Floating GUI window (PyQt6)
└── datacore-msg-relay.py  # WebSocket relay server (aiohttp)

hooks/
├── inbox-watcher.py       # Claude Code hook for receiving messages
└── send-reply.py          # Helper script for Claude to send replies

fly.toml                   # fly.io deployment config
requirements.txt           # Python dependencies
settings.local.yaml.example # Example settings
```

## Requirements

**Client (CLI/GUI):**
- Python 3.8+
- PyQt6 (for GUI window): `pip install PyQt6`
- websockets (for relay): `pip install websockets`
- pyyaml (for settings): `pip install pyyaml`

**Relay Server:**
- Python 3.8+
- aiohttp
- websockets

## Roadmap

- [x] Phase 1: Core messaging (`/msg`, `/my-messages`, `/reply`)
- [x] Phase 2: Real-time GUI window
- [x] Phase 2: Terminal CLI with socket notifications
- [x] Phase 3: Internet relay with GitHub OAuth
- [ ] Phase 4: Slack/email notifications, webhooks
- [ ] Phase 5: Encryption, expiring messages, channels

## License

MIT
