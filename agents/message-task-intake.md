# Claude Inbox Agent

Processes messages sent to `@claude` and routes them as AI tasks.

## Purpose

When users send messages to `@claude`, this agent:
1. Parses the message as an AI task
2. Routes to appropriate specialized agent
3. Sends results back to the sender's inbox

## Trigger

- Called by `ai-task-executor` when processing `claude.org` inbox
- Messages have `:AI:` tag in addition to `:unread:`

## Inbox Location

```
[space]/org/inboxes/claude.org
```

## Message Format (Input)

```org
* MESSAGE [2025-12-11 Thu 14:30] :unread:AI:
:PROPERTIES:
:ID: msg-20251211-143000-gregor
:FROM: gregor
:TO: claude
:PRIORITY: normal
:END:
Research competitor pricing for Verity and add findings to research/
```

## Behavior

1. **Parse message**
   - Extract sender from `:FROM:`
   - Extract task description from body
   - Determine task type from content

2. **Route to specialized agent**

   | Content Pattern | Agent | Tag |
   |-----------------|-------|-----|
   | "research", URL | gtd-research-processor | :AI:research: |
   | "write", "draft", "create content" | gtd-content-writer | :AI:content: |
   | "analyze", "report", "metrics" | gtd-data-analyzer | :AI:data: |
   | "track", "status", "blockers" | gtd-project-manager | :AI:pm: |
   | Default | general processing | :AI: |

3. **Execute task**
   - Pass message content to specialized agent
   - Capture output/results

4. **Send reply to sender**
   - Create message in sender's inbox
   - Include task results or summary
   - Tag with `:from-ai:`
   - Reference original message in `:THREAD:`

5. **Mark original as processed**
   - Change `:unread:` to `:processed:`
   - Add `:done:` tag

## Reply Format (Output)

```org
* MESSAGE [2025-12-11 Thu 15:00] :unread:from-ai:
:PROPERTIES:
:ID: msg-20251211-150000-claude
:FROM: claude
:TO: gregor
:THREAD: msg-20251211-143000-gregor
:TASK_STATUS: completed
:END:
✓ Research completed

Added 3 competitor analyses:
- research/competitor-chainlink.md
- research/competitor-ocean.md
- research/competitor-streamr.md

**Summary:**
Chainlink: Enterprise focus, $50K+ deals
Ocean Protocol: Token-based access, DeFi integration
Streamr: Real-time data streams, pub/sub model

Verity differentiation: RWA tokenization + provenance verification
```

## Error Handling

If task fails:

```org
* MESSAGE [2025-12-11 Thu 15:00] :unread:from-ai:
:PROPERTIES:
:ID: msg-20251211-150000-claude
:FROM: claude
:TO: gregor
:THREAD: msg-20251211-143000-gregor
:TASK_STATUS: failed
:END:
⚠️ Task could not be completed

Error: Could not access URL https://example.com (403 Forbidden)

Original request: Research competitor pricing...

Please verify the URL is accessible or provide alternative sources.
```

## Example Interactions

### Research Request

**User sends:**
```
/msg @claude "Research MCP protocol best practices and create summary in notes/"
```

**Claude replies:**
```
✓ Research completed

Created: notes/mcp-protocol-best-practices.md

Key findings:
- Security: Use scoped permissions, validate all inputs
- Performance: Batch requests, cache responses
- UX: Provide clear error messages, progress indicators
```

### Content Request

**User sends:**
```
/msg @claude "Draft a blog post about data tokenization benefits"
```

**Claude replies:**
```
✓ Draft created

File: content/drafts/data-tokenization-benefits.md

Outline:
1. Introduction to data as an asset
2. Traditional vs tokenized data ownership
3. Benefits: liquidity, fractional ownership, provenance
4. Use cases: healthcare, finance, research
5. Getting started with Verity

Ready for your review and edits.
```

## Integration with ai-task-executor

The `ai-task-executor` should:

1. Check `[space]/org/inboxes/claude.org` for `:unread:AI:` messages
2. Process each message through this agent
3. Ensure replies are sent back
4. Log completion to journal

## Notes

- Messages to @claude are processed during AI task execution cycles
- Not real-time - delivery depends on when ai-task-executor runs
- Complex tasks may be broken into subtasks
- Results always sent back to sender's inbox
