# /my-messages

Display your inbox - unread and recent messages.

## Usage

```
/my-messages
/my-messages --all
/my-messages --space datafund
/my-messages --from @gregor
```

## Arguments

- `--all` - Show all messages, not just unread (optional)
- `--space` - Filter to specific space (optional)
- `--from` - Filter by sender (optional)
- `--limit N` - Limit to N most recent messages (optional, default 20)

## Behavior

1. **Get current user identity**
   - Read `identity.name` from `.datacore/settings.local.yaml`
   - If not set, prompt user to configure

2. **Find all inbox files**
   - Scan all spaces: `*/org/inboxes/{identity.name}.org`
   - Include personal space if exists: `0-personal/org/inboxes/{name}.org`

3. **Parse messages**
   - Read org-mode entries from each inbox
   - Extract metadata from PROPERTIES drawer
   - Track unread (`:unread:` tag) vs read

4. **Filter messages**
   - By space if `--space` specified
   - By sender if `--from` specified
   - By read status unless `--all`

5. **Sort and group**
   - Group by space
   - Sort by timestamp (newest first)

6. **Display output**

## Output Format

```
MESSAGES (3 unread)
═══════════════════

datafund (2 unread)
───────────────────
● [@gregor 10 min ago] Need OAuth keys for Google/Apple - see issue #25
● [@gregor 2h ago] PR #24 ready for review
  [@crt yesterday] Thanks for the update

personal (1 unread)
───────────────────
● [@system 1d ago] Weekly review reminder

───────────────────
● = unread

Commands:
  /reply last "message"     Reply to most recent
  /reply [id] "message"     Reply to specific message
```

## Reading a Specific Message

When showing messages, include the message ID for reference:

```
● [@gregor 10 min ago] (msg-20251211-143000-gregor)
  Need OAuth keys for Google/Apple - see issue #25
```

## Mark as Read

By default, viewing messages does NOT mark them as read.

If `messaging.auto_mark_read: true` in settings, messages are marked read after display.

To manually mark as read:
```
/mark-read msg-20251211-143000-gregor
/mark-read all
```

## Empty Inbox

```
MESSAGES (0 unread)
═══════════════════

No messages.

Send a message: /msg @username "message"
```

## Integration with /today

When `messaging.show_in_today: true`, the daily briefing includes:

```markdown
### Messages
3 unread messages from 2 people
- @gregor (2): OAuth keys, PR review
- @system (1): Weekly reminder

Run `/my-messages` to read.
```
