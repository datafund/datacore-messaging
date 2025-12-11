# /broadcast

Send a message to all users in a space.

## Usage

```
/broadcast "Your announcement here"
/broadcast "message" --space datafund
/broadcast "message" --priority high
/broadcast "message" --exclude @user1,@user2
```

## Arguments

- `"message"` - Broadcast content (required)
- `--space` - Target space (optional, defaults to messaging.default_space)
- `--priority` - Message priority: low, normal, high (optional)
- `--exclude` - Comma-separated users to exclude (optional)

## Behavior

1. **Get sender identity**
   - Read `identity.name` from settings
   - Sender is excluded from broadcast automatically

2. **Determine target space**
   - Use `--space` if provided
   - Otherwise use `messaging.default_space`
   - Otherwise prompt

3. **Get all users in space**
   - Read `[space]/org/inboxes/USERS.yaml`
   - Exclude sender
   - Exclude `--exclude` list
   - Exclude AI users (type: ai)

4. **Send to each user**
   - Append message to each user's inbox
   - Use special `:broadcast:` tag

5. **Confirm**
   ```
   ✓ Broadcast sent to 5 users in datafund
     Recipients: @crt, @tex, @andrej, @jan, @marko

   Run ./sync push to deliver.
   ```

## Broadcast Format

```org
* MESSAGE [2025-12-11 Thu 16:00] :unread:broadcast:
:PROPERTIES:
:ID: msg-20251211-160000-gregor-broadcast
:FROM: gregor
:TO: all
:PRIORITY: normal
:RECIPIENTS: crt,tex,andrej,jan,marko
:END:
Team meeting moved to 3 PM today.
```

## Examples

```bash
# Simple broadcast
/broadcast "Team meeting at 3 PM"

# Urgent broadcast
/broadcast "Server maintenance in 1 hour" --priority high

# Broadcast to specific space
/broadcast "New documentation ready" --space datafund

# Exclude some users
/broadcast "Dev sync at 2 PM" --exclude @jan,@marko
```

## Display in /my-messages

Broadcasts are shown with indicator:

```
📢 [@gregor 1h ago] (broadcast)
   Team meeting moved to 3 PM today.
```

## Notes

- Broadcasts go to all human users (not @claude)
- Sender is automatically excluded
- Use sparingly - prefer direct messages for non-announcements
