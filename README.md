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

## Installation

```bash
cd ~/Data/.datacore/modules
git clone https://github.com/datafund/datacore-messaging.git messaging
```

## Configuration

Add to `.datacore/settings.local.yaml`:

```yaml
identity:
  name: yourname                   # Your username (required)
  handles: ["@yourname", "@yn"]    # Aliases others can use to reach you

messaging:
  default_space: datafund          # Default space for /msg
  show_in_today: true              # Include unread count in /today briefing
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
- Dark theme
- Real-time updates (watches inbox files)
- System notifications with sound
- Send messages inline
- macOS native notifications

```
┌─ Messages @gregor ─────────────────────[─][□][×]─┐
│                                                   │
│ ● @crt 14:30                                      │
│   Need OAuth keys - see issue #25                 │
│                                                   │
│ ● @claude 14:35                                   │
│   Research complete. See research/competitors.md  │
│                                                   │
│   @you→crt 14:40                                  │
│   Keys are in the vault                           │
│                                                   │
├───────────────────────────────────────────────────┤
│ @crt Thanks! ____________________________         │
├───────────────────────────────────────────────────┤
│ Space: datafund                                   │
└───────────────────────────────────────────────────┘
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
```

Interactive mode:
```
datacore-msg | @gregor
Commands: @user msg | /read | /peers | /quit

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
:THREAD: nil
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

Online peers discovered by checking socket existence:
```
/tmp/datacore-msg-gregor.sock  → @gregor online
/tmp/datacore-msg-crt.sock     → @crt online
/tmp/datacore-msg-claude.sock  → @claude agent running
```

## Commands Reference

| Command | Description |
|---------|-------------|
| `/msg @user "text"` | Send message to user |
| `/my-messages` | Show your inbox |
| `/reply [id] "text"` | Reply to a message |
| `/msg-add-user name` | Add user to registry |
| `/broadcast "text"` | Message all team members |

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

### Claude Code Session

When running `datacore-msg daemon` as claude, messages are forwarded to:
```
/tmp/datacore-claude.pipe
```

Claude Code can read this pipe to receive messages in real-time.

## Files

```
lib/
├── datacore-msg           # Terminal CLI (Python)
└── datacore-msg-window.py # Floating GUI window (Tkinter)
```

## Requirements

- Python 3.8+
- tkinter (included with Python, for GUI window)
- No external dependencies

## Roadmap

- [x] Phase 1: Core messaging (`/msg`, `/my-messages`, `/reply`)
- [x] Phase 2: Real-time GUI window
- [x] Phase 2: Terminal CLI with socket notifications
- [ ] Phase 3: Slack/email notifications, webhooks
- [ ] Phase 4: Encryption, expiring messages, channels

## License

MIT
