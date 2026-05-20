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

3. **Create messaging directory if needed**
   - Path: `[space]/org/messaging/`
   - Agent inbox: `[space]/org/messaging/agents/{username}-claude.org`

4. **Update contacts.yaml**
   - Add actor entry with handles and trust tier
   - Set `added` date

5. **Confirm**
   ```
   ✓ User 'crt' added to messaging
     Spaces: datafund
     Handles: @crt, @crtahlin
     Contacts: 1-datafund/contacts.yaml
   ```

## contacts.yaml Format

```yaml
actors:
  - id: "gregor@team.example.com"
    name: "gregor"
    handles: ["@gregor", "@gz"]
    trust_tier: owner
    added: 2025-12-11
  - id: "crt@team.example.com"
    name: "crt"
    handles: ["@crt", "@crtahlin"]
    trust_tier: team
    added: 2025-12-11
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
