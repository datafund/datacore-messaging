# /msg-add-user

Add a new user to the messaging system.

## Usage

```
/msg-add-user username
/msg-add-user username --handles @handle1,@handle2
/msg-add-user username --space datafund
```

## Arguments

- `username` - The canonical username (required)
- `--handles` - Comma-separated list of handles/aliases (optional)
- `--space` - Target space (optional, defaults to all team spaces)

## Behavior

1. **Validate username**
   - Must be alphanumeric with hyphens/underscores
   - Cannot be "claude" (reserved for AI)

2. **Determine target space(s)**
   - If `--space` specified, use that space only
   - Otherwise, add to all team spaces

3. **Create inbox file**
   - Path: `[space]/org/inboxes/{username}.org`
   - Use template from `templates/inbox.org`

4. **Update USERS.yaml**
   - Add user entry with handles
   - Set `added` date

5. **Confirm**
   ```
   ✓ User 'crt' added to messaging
     Spaces: datafund
     Handles: @crt, @crtahlin
     Inbox: 1-datafund/org/inboxes/crt.org
   ```

## USERS.yaml Format

```yaml
users:
  gregor:
    handles: ["@gregor", "@gz"]
    added: 2025-12-11
  crt:
    handles: ["@crt", "@crtahlin"]
    added: 2025-12-11
  claude:
    handles: ["@claude", "@ai"]
    added: 2025-12-11
    type: ai
```

## Examples

```bash
# Add user with default handle
/msg-add-user crt
# Creates @crt handle automatically

# Add user with custom handles
/msg-add-user crt --handles @crt,@crtahlin,@cert

# Add to specific space only
/msg-add-user newuser --space datafund
```

## Notes

- Users are auto-added when they first send a message
- This command is for pre-registering users or adding handles
- The `claude` user is auto-created with `:type: ai` marker
