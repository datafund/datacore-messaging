# Upgrading datacore-messaging

## v0.1.0 → v0.2.0

This release changes the storage layout and contact registry format.

### Breaking changes

| What | v0.1.0 | v0.2.0 |
|------|--------|--------|
| Messaging directory | `{space}/org/inboxes/` | `{space}/org/messaging/` |
| Per-user inbox files | `org/inboxes/{username}.org` | `org/messaging/inbox.org` (universal inbox) |
| Contact registry | `org/inboxes/USERS.yaml` | `contacts.yaml` (space root) |

### Migration steps

**1. Move the messaging directory**

```bash
# For each space (e.g. 1-datafund):
mv 1-datafund/org/inboxes 1-datafund/org/messaging
```

**2. Merge per-user inbox files into the universal inbox**

v0.1.0 stored messages in separate per-user files (`gregor.org`, `crt.org`, etc.).
v0.2.0 uses a single `inbox.org` with a `TO:` property on each entry.

If you have existing messages you want to preserve, concatenate them:

```bash
cd 1-datafund/org/messaging
cat gregor.org crt.org tex.org >> inbox.org
# Then remove the per-user files:
rm gregor.org crt.org tex.org
```

Review the merged `inbox.org` to ensure headings are valid org-mode and
each entry has a `TO:` property in its `:PROPERTIES:` drawer.

**3. Convert USERS.yaml → contacts.yaml**

Old format (`org/inboxes/USERS.yaml`):

```yaml
users:
  gregor:
    handles: ["@gregor", "@gz"]
    added: 2025-12-11
```

New format (`{space}/contacts.yaml`):

```yaml
actors:
  - id: "gregor@team.example.com"
    name: "gregor"
    handles: ["@gregor", "@gz"]
    trust_tier: team
    added: 2025-12-11
```

Copy the template and fill in your actors:

```bash
cp templates/contacts.yaml 1-datafund/contacts.yaml
# Edit 1-datafund/contacts.yaml and add your actors
```

**4. Remove the old registry file**

```bash
rm 1-datafund/org/messaging/USERS.yaml
```

**5. Verify**

```bash
# Check the new layout
ls 1-datafund/org/messaging/
# Expected: inbox.org  outbox.org  agents/

ls 1-datafund/contacts.yaml
# Expected: contacts.yaml
```

### What's new in v0.2.0

- Universal inbox (`inbox.org`) replaces per-user files — simpler to sync
- `contacts.yaml` at space root with trust tier support
- Agent task inboxes under `org/messaging/agents/{username}-claude.org`
- WebSocket relay for real-time delivery (optional)
- Task governance: trust tiers, token budgets, rate limiting

### GUI app (`datacore-msg.py`) status

`datacore-msg.py` is **not compatible with v0.2.0**. It still references
the old `org/inboxes/` storage layout and `claude_whitelist` settings.

A rewritten GUI is planned for Phase 2. Until then:

- Use `hooks/` scripts for message delivery
- Use `lib/` API directly for programmatic access
- Running `datacore-msg.py` will print a warning to stderr and continue
  in degraded mode (display only — writes may fail silently)
