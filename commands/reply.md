# /reply

Reply to a message, creating a threaded conversation.

## Usage

```
/reply last "Your reply here"
/reply [message-id] "Your reply here"
/reply last "reply" --priority high
```

## Arguments

- `last` or `[message-id]` - Which message to reply to (required)
- `"reply"` - Your reply content (required)
- `--priority` - Reply priority: low, normal, high (optional)

## Behavior

1. **Find original message**
   - If `last`: Find most recent unread message in any inbox
   - If `[message-id]`: Search all inboxes for matching ID

2. **Validate original message**
   - Confirm message exists
   - Get sender (becomes recipient of reply)
   - Get space (reply goes to same space)

3. **Create reply message**
   - Set `THREAD` property to original message ID
   - Set `TO` to original sender
   - Set `FROM` to current user

4. **Append to original sender's inbox**
   - File: `[space]/org/inboxes/{original_sender}.org`

5. **Mark original as replied**
   - Add `:replied:` tag to original message heading

6. **Confirm**
   ```
   ✓ Reply sent to @gregor
     Thread: msg-20251211-143000-gregor
     File: 1-datafund/org/inboxes/gregor.org

   Run ./sync push to deliver.
   ```

## Reply Format

```org
* MESSAGE [2025-12-11 Thu 15:00] :unread:
:PROPERTIES:
:ID: msg-20251211-150000-crt
:FROM: crt
:TO: gregor
:PRIORITY: normal
:THREAD: msg-20251211-143000-gregor
:END:
Got it, will set up the OAuth keys today.
```

## Thread Display

When viewing messages, threads are shown together:

```
● [@gregor 10 min ago] (msg-20251211-143000-gregor)
  Need OAuth keys for Google/Apple

  └─ [@crt 5 min ago] (msg-20251211-145000-crt)
     Got it, will set up today.

     └─ [@gregor 2 min ago] (msg-20251211-145800-gregor)
        Thanks! Let me know if you need help.
```

## Examples

```bash
# Reply to most recent message
/reply last "Thanks, I'll take a look"

# Reply to specific message
/reply msg-20251211-143000-gregor "Got it, will do"

# Urgent reply
/reply last "On it!" --priority high
```

## Error Handling

- **Message not found**: "Message 'x' not found. Run /my-messages to see your inbox."
- **No messages**: "No messages to reply to."
- **Empty reply**: "Reply cannot be empty"
