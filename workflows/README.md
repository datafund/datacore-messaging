# Messaging Workflows

Process documentation for messaging module.

## Message Delivery Flow

```
1. SEND
   User runs /msg @recipient "message"
        │
        ▼
2. RESOLVE
   Look up recipient in USERS.yaml
   Determine target space
        │
        ▼
3. WRITE
   Append message to recipient's inbox
   [space]/org/inboxes/[recipient].org
        │
        ▼
4. SYNC
   User runs ./sync push (or /wrap-up)
   Changes pushed to shared repo
        │
        ▼
5. DELIVER
   Recipient runs ./sync (or /today)
   Changes pulled to their machine
        │
        ▼
6. NOTIFY
   /today briefing shows unread count
   User runs /my-messages to read
```

## AI Task Routing Flow

```
1. USER SENDS TO @CLAUDE
   /msg @claude "Research X"
        │
        ▼
2. STORED IN CLAUDE INBOX
   [space]/org/inboxes/claude.org
   Tagged :AI:
        │
        ▼
3. AI-TASK-EXECUTOR PROCESSES
   Reads claude.org during nightly run
   Routes to appropriate agent
        │
        ▼
4. AGENT EXECUTES
   gtd-research-processor, gtd-content-writer, etc.
   Creates output files
        │
        ▼
5. REPLY SENT
   Result added to sender's inbox
   Tagged :from-ai:
        │
        ▼
6. USER NOTIFIED
   Next /today shows AI reply in messages
```

## Weekly Review Integration

During `/gtd-weekly-review`:
- Review unread messages
- Archive old threads (>30 days)
- Check for unanswered messages
