# Datacore Module: Messaging

Inter-user messaging for Datacore via shared space inboxes.

## Features

- **Direct messages**: Send messages to team members via `/msg @user "message"`
- **Inbox management**: View your messages with `/my-messages`
- **Threaded replies**: Reply to messages with `/reply`
- **Claude Code integration**: Message `@claude` to delegate AI tasks
- **Daily briefing**: Unread count shown in `/today` output
- **Git-based delivery**: Messages sync via existing `./sync` workflow

## Installation

```bash
cd ~/Data/.datacore/modules
git clone https://github.com/datafund/datacore-module-messaging.git messaging
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

### Send a Message

```bash
/msg @crt "Need API keys for OAuth - see issue #25"
/msg @crt "Urgent: server down" --priority high
/msg @crt "message" --space datafund
```

### Read Messages

```bash
/my-messages              # Show all unread
/my-messages --all        # Include read messages
/my-messages --space datafund
```

### Reply to a Message

```bash
/reply last "Got it, will do"
/reply msg-20251211-130000-crt "Thanks!"
```

### Message Claude Code

```bash
/msg @claude "Research competitor pricing and add to research/"
```

Messages to `@claude` are processed as AI tasks and results are sent back to your inbox.

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

### User Registration

Users are auto-registered when they first send a message. The `USERS.yaml` file tracks all users:

```yaml
users:
  gregor:
    handles: ["@gregor", "@gz"]
    added: 2025-12-11
  crt:
    handles: ["@crt", "@crtahlin"]
    added: 2025-12-11
```

### Delivery

Messages are delivered via git:
1. Sender runs `/msg` → message appended to recipient's inbox
2. Sender runs `./sync push` (or `/wrap-up`)
3. Recipient runs `./sync` (or `/today`) → pulls new messages
4. Recipient's `/today` shows unread count

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

## Roadmap

- [x] Phase 1: Core messaging (`/msg`, `/my-messages`, `/reply`)
- [ ] Phase 2: Message status, mentions, broadcast, search
- [ ] Phase 3: Slack/email notifications, webhooks
- [ ] Phase 4: Encryption, expiring messages, channels

## License

MIT
