# Messaging Module Context

This module adds inter-user messaging to Datacore via shared space inboxes.

## Overview

Messages are org-mode entries stored in `[space]/org/inboxes/[username].org`. Users send messages with `/msg`, read with `/my-messages`, and reply with `/reply`.

## Key Concepts

### Identity

Each user configures their identity in `.datacore/settings.local.yaml`:

```yaml
identity:
  name: gregor                    # Canonical username
  handles: ["@gregor", "@gz"]     # Aliases for receiving messages
```

### Inbox Location

```
[space]/org/inboxes/
├── USERS.yaml        # Registry of all users and handles
├── gregor.org        # Gregor's inbox
├── crt.org           # Črt's inbox
└── claude.org        # AI task inbox (special)
```

### Message Format

```org
* MESSAGE [2025-12-11 Thu 13:00] :unread:
:PROPERTIES:
:ID: msg-{timestamp}-{sender}
:FROM: sender_name
:TO: recipient_name
:PRIORITY: normal|high|low
:THREAD: nil|parent_message_id
:END:
Message content here.
```

### Tags

- `:unread:` - Not yet viewed
- `:read:` - Viewed by recipient
- `:replied:` - Recipient has replied
- `:from-ai:` - Response from Claude
- `:AI:` - Task for AI processing (claude.org only)

## Commands

### /msg

Send a message to another user.

**Resolution order for recipient:**
1. Check USERS.yaml for handle → username mapping
2. If not found, treat handle as username
3. If user doesn't exist, create inbox and add to USERS.yaml

**Space selection:**
1. Explicit: `--space datafund`
2. From settings: `messaging.default_space`
3. Current directory detection

### /my-messages

Display inbox for current user.

**Steps:**
1. Read `identity.name` from settings
2. Find all `*/org/inboxes/{name}.org` files
3. Parse org entries, filter by tags
4. Display grouped by space, sorted by time

### /reply

Reply to a message, creating a thread.

**Steps:**
1. Find original message by ID (or "last")
2. Create new message with `THREAD` property set to original ID
3. Append to sender's inbox (reverse direction)
4. Add `:replied:` tag to original message

## Claude Integration

Messages to `@claude` are special:
1. Stored in `[space]/org/inboxes/claude.org`
2. Tagged with `:AI:` for ai-task-executor
3. Agent processes and sends reply to sender's inbox
4. Reply tagged `:from-ai:`

## File Operations

### Creating a message

```python
# Append to recipient's inbox
with open(f"{space}/org/inboxes/{recipient}.org", "a") as f:
    f.write(message_org_format)
```

### Marking as read

Replace `:unread:` tag with `:read:` in the heading line.

### User registry

```yaml
# USERS.yaml
users:
  username:
    handles: ["@handle1", "@handle2"]
    added: YYYY-MM-DD
```

## Settings Schema

```yaml
identity:
  name: string          # Required
  handles: [string]     # Optional, defaults to ["@{name}"]

messaging:
  default_space: string # Optional, defaults to first team space
  show_in_today: bool   # Optional, defaults to true
  auto_mark_read: bool  # Optional, defaults to false
```

## Error Handling

- **Unknown recipient**: Create inbox, add to USERS.yaml, warn user
- **No identity configured**: Prompt to add `identity.name` to settings
- **Space not found**: List available spaces, ask user to specify
