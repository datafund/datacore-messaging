# Messaging Module Context

This module adds inter-user and human-to-agent messaging to Datacore via org-workspace backed storage.

## Overview

Messages are org-mode entries managed by `lib/message_store.py` and stored in `[space]/org/messaging/inbox.org`. Users send messages with `/msg`, read with `/my-messages`, and reply with `/reply`. Messages addressed to `@claude` are routed as agent tasks with trust tier enforcement.

## Key Concepts

### Identity

Each user configures their identity in `.datacore/settings.local.yaml`:

```yaml
identity:
  name: gregor                    # Canonical username
  handles: ["@gregor", "@gz"]     # Aliases for receiving messages
```

### Storage Layout

```
[space]/org/messaging/
├── inbox.org             # Universal inbox (all incoming messages and file deliveries)
├── outbox.org            # Sent message log
└── agents/
    ├── gregor-claude.org # Gregor's Claude agent task inbox
    └── crt-claude.org    # Črt's Claude agent task inbox
```

Agent inbox filenames are `{username}-claude.org` — one per user. There is no generic `claude.org`.

### Message Format

Messages in `inbox.org` use TODO state with `:message:` and `:unread:` tags:

```org
* TODO [2025-12-11 Thu 13:00] :unread:message:
:PROPERTIES:
:ID:       msg-20251211-130000-a1b2c3d4
:FROM:     sender_name
:TO:       recipient_name
:REPLY_TO: nil
:THREAD:   nil
:END:
Message content here.
```

File deliveries use the `:file_delivery:` tag instead of `:message:`.

### State Machine

Messages and tasks go through org-workspace states:

**Messages** (`inbox.org`):
- `TODO` (unread) → `DONE` (read) → `ARCHIVED`

**Agent tasks** (`agents/{username}-claude.org`):
- `WAITING` → `QUEUED` → `WORKING` → `DONE` → `ARCHIVED`
- Terminal states: `CANCELLED`, `ARCHIVED`

### Tags

- `:unread:` + `TODO` state — not yet viewed
- `:message:` — standard text message
- `:file_delivery:` — file delivered via Fairdrop/Swarm
- `:AI:` — task for agent processing
- `:AI:research:`, `:AI:content:`, `:AI:data:`, `:AI:pm:` — routed subtypes

## lib/ Modules

All message operations go through the lib modules. No direct file manipulation.

| Module | Purpose |
|--------|---------|
| `lib/config.py` | Settings, identity, trust tier resolution, compute config |
| `lib/message_store.py` | CRUD for `inbox.org` — create, find, mark_read, archive |
| `lib/agent_inbox.py` | Task lifecycle for `agents/{username}-claude.org` |
| `lib/governor.py` | Trust tier enforcement, token budgets, rate limits |
| `lib/relay.py` | WebSocket relay client for cross-instance messaging |

### MessageStore

```python
store = MessageStore(space_root)
msg = store.create_message(from_actor="gregor", to_actor="crt", content="Hello")
unread = store.find_unread()       # reloads from disk
store.mark_read(unread[0])         # TODO -> DONE
store.archive(unread[0])           # DONE -> ARCHIVED
```

### AgentInbox

```python
inbox = AgentInbox(space_root, "gregor-claude")
task = inbox.create_task(from_actor="gregor", content="Research X", trust_tier="owner", tags=["AI", "research"])
queued = inbox.find_by_state("QUEUED")
inbox.claim(queued[0])             # QUEUED -> WORKING
inbox.complete(queued[0], tokens_used=1200)  # WORKING -> DONE
```

### TaskGovernor

```python
gov = TaskGovernor(state_dir=Path(".datacore/state/messaging"))
result = gov.check_and_record("gregor", estimated_tokens=5000, effort=3)
if result.allowed:
    # create task
    gov.record_usage("gregor", tokens=1150)
    gov.record_task_completion("gregor")
```

## Commands

### /msg

Send a message to another user.

**Resolution order for recipient:**
1. Check `contacts.yaml` for handle → username mapping
2. If not found, treat handle as username
3. If user doesn't exist in contacts, create inbox entry and add to `contacts.yaml`

**Space selection:**
1. Explicit: `--space datafund`
2. From settings: `messaging.default_space`
3. Current directory detection

### /my-messages

Display inbox for current user.

**Steps:**
1. Read `identity.name` from settings via `lib/config.get_username()`
2. Open `[space]/org/messaging/inbox.org` via `MessageStore`
3. Call `MessageStore.find_unread()` — returns org-workspace NodeViews
4. Display grouped by sender, sorted by timestamp

### /reply

Reply to a message, creating a thread.

**Steps:**
1. Find original message by ID (or "last") via `MessageStore.find_by_id()`
2. Create reply via `MessageStore.create_message(reply_to=original_id)`
3. `REPLY_TO` and `THREAD` properties are set automatically by `message_store.py`
4. Mark original as read via `MessageStore.mark_read()`

## Claude Integration

Messages to `@claude` follow the agent task pathway:
1. Message arrives in `org/messaging/inbox.org` with `:AI:` tag
2. `inbox-watcher.py` hook routes it to the `AgentInbox` for `{username}-claude`
3. Trust tier checked by `TaskGovernor` — auto-accept for owner/team, WAITING for others
4. Task entered as QUEUED or WAITING in `org/messaging/agents/{username}-claude.org`
5. Agent claims task (QUEUED → WORKING), executes, completes
6. Reply sent back to sender via `MessageStore.create_message()`

See `agents/message-task-intake.md` for full agent specification.

## Contacts Registry

```yaml
# contacts.yaml
contacts:
  gregor:
    handles: ["@gregor", "@gz"]
    relay: "wss://relay.example.com/ws"
    added: "2025-12-11"
  crt:
    handles: ["@crt"]
    relay: ""
    added: "2025-12-11"
```

Previously `USERS.yaml` — renamed to `contacts.yaml` in v0.2.0.

## Settings Schema

```yaml
identity:
  name: string            # Required
  handles: [string]       # Optional, defaults to ["@{name}"]

messaging:
  default_space: string   # Optional, defaults to "0-personal"
  show_in_today: bool     # Optional, defaults to true
  auto_mark_read: bool    # Optional, defaults to false

  relay:
    url: string           # WebSocket relay URL
    secret: string        # Relay auth secret

  trust_tiers:            # Per-tier config overrides
    owner:
      priority_boost: 2.0
      daily_token_limit: 0       # 0 = unlimited
      max_task_effort: 0         # 0 = unlimited
      auto_accept: true
    team:
      priority_boost: 1.5
      daily_token_limit: 100000
      max_task_effort: 8
      auto_accept: true
    trusted:
      priority_boost: 1.0
      daily_token_limit: 50000
      max_task_effort: 5
      auto_accept: false
    unknown:
      priority_boost: 0.5
      daily_token_limit: 10000
      max_task_effort: 3
      auto_accept: false

  trust_overrides:        # Per-actor tier assignments
    crt: team
    external-partner: trusted

  compute:
    daily_budget_tokens: 500000
    per_sender_daily_max: 100000
    per_task_max_tokens: 50000
    per_task_timeout_minutes: 30
    max_queue_depth: 20
    rate_limits:
      tasks_per_hour: 5

  inbox_feeds: []         # External relay WebSocket endpoints to poll
```

## Error Handling

- **Unknown recipient**: Create inbox entry, add to `contacts.yaml`, warn user
- **No identity configured**: Prompt to add `identity.name` to settings
- **Space not found**: List available spaces, ask user to specify
- **Governance rejected**: Reply to sender with rejection reason and current budget status
- **Relay unreachable**: Queue messages locally, retry on next connection
