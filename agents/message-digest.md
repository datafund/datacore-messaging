# Message Digest Agent

Generates message summary for `/today` daily briefing integration.

## Purpose

When the `/today` command runs, this agent provides unread message counts and summaries for inclusion in the daily briefing.

## Trigger

Called by `/today` command when `messaging.show_in_today: true` (default).

## Behavior

1. **Get current user identity**
   - Read `identity.name` from settings

2. **Scan all inboxes**
   - Find `*/org/inboxes/{identity.name}.org` in all spaces

3. **Count unread messages**
   - Parse org entries with `:unread:` tag
   - Group by sender
   - Sort by count (descending)

4. **Generate summary**

## Output Format

### When there are unread messages:

```markdown
### Messages
3 unread messages from 2 people
- @gregor (2): OAuth keys, PR review
- @system (1): Weekly reminder

Run `/my-messages` to read.
```

### When there are no unread messages:

```markdown
### Messages
No unread messages.
```

### When there are high-priority messages:

```markdown
### Messages
⚠️ 1 high-priority message
3 unread messages from 2 people
- @gregor (2): [HIGH] Server issue, PR review
- @system (1): Weekly reminder

Run `/my-messages` to read.
```

## Summary Generation

For each sender, show preview of most recent message:
- Truncate to ~30 characters
- Prefix with [HIGH] if priority: high
- Include count if multiple messages

## Integration

The `/today` command should:

1. Check if messaging module is installed
2. If `messaging.show_in_today: true`:
   - Call this agent
   - Include output in briefing after "Calendar" section
3. If no messages, can optionally omit section entirely

## Example Integration in /today

```markdown
## Daily Briefing

### Focus
Deep work on Verity API refactor

### Priority Tasks
- [ ] Review PR #24
- [ ] Update SPECIFICATION.md

### Calendar
- 10:00 Team standup
- 14:00 Client call

### Messages
3 unread messages from 2 people
- @gregor (2): OAuth keys, PR review
- @crt (1): Deployment question

Run `/my-messages` to read.

### This Week
...
```
