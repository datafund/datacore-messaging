# /msg

Send a message to another user in a shared space.

## Usage

```
/msg @recipient "Your message here"
/msg @recipient "message" --space spacename
/msg @recipient "message" --priority high
```

## Arguments

- `@recipient` - Username or handle of the recipient (required)
- `"message"` - Message content (required)
- `--space` - Target space (optional, defaults to messaging.default_space)
- `--priority` - Message priority: low, normal, high (optional, defaults to normal)

## Behavior

1. **Validate sender identity**
   - Read `identity.name` from `.datacore/settings.local.yaml`
   - If not set, prompt user to configure identity

2. **Resolve recipient**
   - Read `[space]/org/inboxes/USERS.yaml`
   - Match `@recipient` against handles or usernames
   - If not found, treat as new user (create inbox)

3. **Determine target space**
   - Use `--space` if provided
   - Otherwise use `messaging.default_space` from settings
   - Otherwise detect from current directory
   - Otherwise prompt user to specify

4. **Create inbox directory if needed**
   ```
   [space]/org/inboxes/
   ```

5. **Generate message ID**
   ```
   msg-{YYYYMMDD}-{HHMMSS}-{sender}
   ```

6. **Append message to recipient's inbox**
   - File: `[space]/org/inboxes/{recipient}.org`
   - Create file if doesn't exist

7. **Update USERS.yaml if new user**
   - Add recipient to registry with handle

8. **Confirm delivery**
   ```
   ✓ Message sent to @recipient
     Space: datafund
     File: 1-datafund/org/inboxes/recipient.org

   Run ./sync push to deliver.
   ```

## Message Format

```org
* MESSAGE [2025-12-11 Thu 14:30] :unread:
:PROPERTIES:
:ID: msg-20251211-143000-sender
:FROM: sender
:TO: recipient
:PRIORITY: normal
:THREAD: nil
:END:
Your message content here.
```

## Special Recipients

### @claude

Messages to `@claude` are AI tasks:

```org
* MESSAGE [2025-12-11 Thu 14:30] :unread:AI:
:PROPERTIES:
:ID: msg-20251211-143000-sender
:FROM: sender
:TO: claude
:PRIORITY: normal
:END:
Research competitor pricing and summarize findings.
```

The `ai-task-executor` agent processes these and sends results back to sender's inbox.

## Examples

```bash
# Simple message
/msg @crt "PR #24 is ready for review"

# Urgent message
/msg @gregor "Server is down!" --priority high

# Specify space
/msg @tex "See the new research doc" --space datafund

# Message to AI
/msg @claude "Research Chainlink competitor pricing"
```

## Error Handling

- **No identity configured**: "Please add identity.name to .datacore/settings.local.yaml"
- **Space not found**: "Space 'x' not found. Available: datafund, personal"
- **Empty message**: "Message cannot be empty"
