# Datacore Module: Messaging

Inter-user and human-to-agent messaging via org-workspace state machine.

## Features

- **Team messaging**: Send/receive messages between Datacore users
- **Agent inbox**: `@yourname-claude` receives tasks with full lifecycle governance
- **Task governance**: Trust tiers, per-sender budgets, rate limiting, queue depth control
- **org-workspace backed**: All state in org-mode files under `org/messaging/`
- **Relay transport**: Real-time delivery via configurable WebSocket relay
- **Claude Code hook**: Agent tasks surface on next prompt; Claude replies inline

## Requirements

- Python 3.10+
- [org-workspace](https://github.com/datafund/org-workspace) >= 0.3.0
- websockets, pyyaml, aiohttp, filelock

## Installation

```bash
cd ~/Data/.datacore/modules
git clone https://github.com/datafund/datacore-messaging.git messaging
cd messaging
./install.sh
```

The installer will:
- Install Python dependencies (see `requirements.txt`)
- Create `settings.local.yaml` from template
- Add Claude Code hook to `~/.claude/settings.json`

## Configuration

Edit `settings.local.yaml`:

```yaml
identity:
  name: yourname              # Your username (required)

messaging:
  default_space: 1-datafund   # Space where org/messaging/ lives

  relay:
    url: "wss://your-relay-host/ws"   # Configurable relay endpoint
    secret: "your-team-secret"        # Shared secret for relay auth

  trust_tiers:                # Optional: override per-tier defaults
    team:
      daily_token_limit: 200000
    unknown:
      auto_accept: false

  trust_overrides:            # Optional: per-actor tier assignment
    "tex@team.example.com": team
    "stranger@other.com": unknown
```

See `settings.local.yaml.example` for all options.

## Storage Layout

All messaging state lives under the space's `org/messaging/` directory:

```
{space}/org/messaging/
├── inbox.org                 # Universal inbox (all incoming messages)
├── outbox.org                # Sent message log
└── agents/
    └── {username}-claude.org # Agent task inbox (task state machine)
```

Messages are org-mode headings with property drawers. The agent inbox uses
org-workspace's state machine: `WAITING → QUEUED → WORKING → DONE → ARCHIVED`.

## Contacts

Known actors are stored in `templates/contacts.yaml` (copy to your space):

```yaml
actors:
  - id: "tex@team.example.com"
    name: "Tex"
    trust_tier: team
    added: 2026-03-11
```

Add actors via `/msg-trust` or edit the file directly.

## Usage

### Send a Message

```bash
python3 datacore-msg.py send @gregor "Hey, can you review the PR?"
python3 datacore-msg.py send @tex-claude "Research competitor pricing"
```

### Check Inbox

```bash
python3 datacore-msg.py inbox
```

### Start the GUI

```bash
python3 datacore-msg.py gui
# Or: ./start.sh
```

### GUI Commands

Type in the input field:

| Command | Description |
|---------|-------------|
| `/mine` | Show my unread messages |
| `/todos` | Show my TODO messages |
| `/tasks` | Show Claude task queue |
| `/context <id>` | Show thread context |
| `/online` | Show online users |
| `/status [val]` | Get/set status |
| `/relay` | Show relay connection info |
| `/clear` | Clear display |
| `/help` | Show available commands |

## Agent Inbox (Claude Code Integration)

Claude Code doesn't maintain a persistent relay connection. Instead, a hook
checks the agent inbox each time you submit a prompt.

### Task Lifecycle

```
WAITING   -> sender submits a task request
QUEUED    -> owner approves (auto-accept for trusted tiers)
WORKING   -> Claude claims and begins execution
DONE      -> execution complete, result posted
ARCHIVED  -> owner confirms result
CANCELLED -> rejected or timed out at any stage
```

### How Claude Receives Tasks

1. Sender sends `@tex-claude do something` via GUI or CLI
2. Message stored in `{space}/org/messaging/agents/tex-claude.org`
3. Governor checks trust tier — auto-accepts or holds for approval
4. On next Claude Code prompt, hook surfaces the queued task
5. Claude executes and replies via `hooks/send-reply.py`

### Hook Output

```
📬 New task for @tex-claude:

From @gregor (14:30) [QUEUED]:
  Can you help debug the auth flow?
  [msg-id: msg-20251212-143000-gregor]

---
To reply: hooks/send-reply.py <user> <message>
```

### Task Governance

The governor enforces resource limits per sender before accepting tasks:

- **Trust tiers**: `owner`, `team`, `trusted`, `unknown`
- **Daily token budgets**: per-tier and global caps
- **Rate limits**: tasks per hour per actor
- **Queue depth**: max concurrent active tasks
- **Auto-accept**: trusted tiers bypass approval queue

Configure via `trust_tiers` and `trust_overrides` in settings.

### Sending Replies from Claude

```bash
# Reply to a sender
python3 hooks/send-reply.py gregor "Fixed! Check the PR."

# Reply to a specific message (creates thread)
python3 hooks/send-reply.py --reply-to msg-20251212-143000-gregor gregor "Follow-up"

# Mark task complete and reply
python3 hooks/send-reply.py --complete msg-20251212-143000-gregor gregor "Task done."
```

### Managing the Task Queue

```bash
# Approve a waiting task
python3 hooks/task-queue.py approve msg-20251212-143000-gregor

# Reject a task
python3 hooks/task-queue.py reject msg-20251212-143000-gregor

# Cancel a running task
python3 hooks/task-queue.py cancel msg-20251212-143000-gregor
```

## Relay Server

The relay provides real-time delivery between team members. It is optional —
the module works offline using the org-workspace store alone.

**Deploy your own** (see `relay/README.md`):

```bash
cd relay/
echo "RELAY_SECRET=your-secret" > .env
docker-compose up -d --build
```

Configure the URL in `settings.local.yaml` under `messaging.relay.url`.

## File Layout

```
datacore-msg.py           # Unified CLI/GUI entry point
install.sh                # Interactive installer
settings.local.yaml       # Your settings (gitignored)

lib/
├── config.py             # Settings, trust tiers, paths
├── message_store.py      # org-workspace message CRUD
├── agent_inbox.py        # Agent task state machine
├── governor.py           # Task acceptance policy
└── relay.py              # WebSocket relay client

hooks/
├── inbox-watcher.py      # Claude Code hook (prompt check)
├── send-reply.py         # Reply helper for Claude
├── mark-message.py       # Mark messages read/todo/done
└── task-queue.py         # Approve/reject/cancel tasks

templates/
└── contacts.yaml         # Known actors template

relay/
├── Dockerfile
├── docker-compose.yml
├── datacore-msg-relay.py
└── README.md
```

## License

MIT
