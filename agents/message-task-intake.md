# Message Task Intake Agent

Receives messages addressed to Claude, validates them through TaskGovernor, and routes them as agent tasks via the org-workspace state machine.

## Purpose

When users send messages to `@claude` (or the local Claude instance), this agent:
1. Validates the sender against trust tiers via TaskGovernor
2. Creates a task entry in the agent inbox with the appropriate initial state
3. Routes to the correct specialized agent based on message content and tags
4. Sends results back to the sender's inbox when the task completes

## Trigger

- Called by `ai-task-executor` when processing `org/messaging/agents/{username}-claude.org`
- Tasks in QUEUED state are claimed on the next prompt submit (via `hooks/inbox-watcher.py`)
- Tasks in WAITING state require owner approval before execution

## Inbox Location

```
[space]/org/messaging/agents/{username}-claude.org
```

The filename is `{username}-claude.org` where `username` is `identity.name` from settings. There is no generic `claude.org` — each user's local Claude instance has its own per-user file.

## Task State Machine

States follow DIP-0023 Section 5.2, managed by `lib/agent_inbox.py` via org-workspace:

```
WAITING  -> QUEUED     (owner approves via task-queue.py approve)
WAITING  -> CANCELLED  (owner rejects via task-queue.py reject)
QUEUED   -> WORKING    (agent claims via inbox-watcher.py on prompt submit)
QUEUED   -> CANCELLED  (owner cancels via task-queue.py cancel)
WORKING  -> DONE       (execution completes)
WORKING  -> QUEUED     (retry on failure)
DONE     -> ARCHIVED   (owner approves result)
DONE     -> QUEUED     (owner requests revision)
```

DONE is **not** terminal — it is an active review state. Only CANCELLED and ARCHIVED are terminal.

### Auto-accept by trust tier

Trust tiers configured in `messaging.trust_tiers` (and default overrides in `lib/config.py`):

| Tier | auto_accept | Initial state |
|------|-------------|---------------|
| owner | true | QUEUED |
| team | true | QUEUED |
| trusted | false | WAITING |
| unknown | false | WAITING |

## Task Format (org-workspace entry)

```org
* QUEUED Research competitor pricing for Verity :AI:research:
:PROPERTIES:
:ID:         msg-20251211-143000-a1b2c3d4
:FROM:       gregor
:TRUST_TIER: owner
:SUBMITTED:  [2025-12-11 Thu 14:30]
:APPROVAL:   auto_accepted
:EFFORT:     3
:END:
```

For tasks requiring approval (trust tier without auto_accept):

```org
* WAITING Draft blog post about data tokenization :AI:content:
:PROPERTIES:
:ID:         msg-20251211-144500-e5f6a7b8
:FROM:       external-user
:TRUST_TIER: unknown
:SUBMITTED:  [2025-12-11 Thu 14:45]
:AWAITING:   owner-approval
:ESTIMATED_TOKENS: 5000
:ESTIMATED_COST:   $0.08
:END:
```

## Agent Routing

Routing is based on org-mode tags present in the message entry:

| Tag | Agent | Description |
|-----|-------|-------------|
| `:AI:research:` | research-orchestrator | URL or topic research |
| `:AI:content:` | gtd-content-writer | Blog posts, emails, social copy |
| `:AI:data:` | gtd-data-analyzer | Analysis, metrics, reports |
| `:AI:pm:` | gtd-project-manager | Project status, blockers |
| `:AI:` (no subtype) | general processing | Default task execution |

Tag patterns are matched from the task entry's org tags. A task with `:AI:research:` will be routed to `research-orchestrator` regardless of message phrasing.

## Governance (TaskGovernor)

Before accepting a task, `lib/governor.py` checks:
- **Effort limit**: task effort vs. tier's `max_task_effort`
- **Per-sender token budget**: `sender.tokens_today` vs. tier's `daily_token_limit`
- **Global daily budget**: total tokens across all senders vs. `compute.daily_budget_tokens`
- **Rate limit**: tasks submitted in the last hour vs. `compute.rate_limits.tasks_per_hour`
- **Queue depth**: active tasks vs. `compute.max_queue_depth`

If governance check fails, the task is rejected and a reply is sent to the sender explaining the reason.

## Reply Format

When a task completes, a message is created in the sender's inbox via `MessageStore.create_message()`:

```org
* TODO [2025-12-11 Thu 15:00] :unread:message:
:PROPERTIES:
:ID:       msg-20251211-150000-c9d0e1f2
:FROM:     claude
:TO:       gregor
:REPLY_TO: msg-20251211-143000-a1b2c3d4
:THREAD:   msg-20251211-143000-a1b2c3d4
:END:
Research completed.

Added 3 competitor analyses to research/:
- research/competitor-chainlink.md
- research/competitor-ocean.md
- research/competitor-streamr.md
```

## Approval Workflow

For WAITING tasks, the owner uses `hooks/task-queue.py`:

```bash
# View pending approvals
python hooks/task-queue.py status

# Approve a task
python hooks/task-queue.py approve --task-id msg-20251211-144500-e5f6a7b8

# Reject a task
python hooks/task-queue.py reject --task-id msg-20251211-144500-e5f6a7b8 --reason "Not relevant"
```

## Integration with ai-task-executor

The `ai-task-executor` should:
1. Check `[space]/org/messaging/agents/{username}-claude.org` for QUEUED tasks
2. Claim the first QUEUED task (transitions to WORKING via `AgentInbox.claim()`)
3. Execute via the appropriate routed agent
4. Call `AgentInbox.complete()` with token usage and result path
5. Send reply to sender via `MessageStore.create_message()`
6. Record token usage via `TaskGovernor.record_usage()`

## Notes

- Tasks are not real-time — execution depends on when ai-task-executor or inbox-watcher runs
- Complex tasks may be broken into subtasks; each subtask creates its own entry
- Token usage is tracked per-sender per-day for budget enforcement
- The `{username}-claude.org` file is created automatically by `AgentInbox._ensure_file()`
