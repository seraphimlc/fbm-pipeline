# Collaboration Inbox

Status: current cross-context board
Updated: 2026-07-25

Use this file only when a task, blocker, result, or handoff must persist across runtime contexts or manual sessions. Do not use it as chat history.

## Message Shape

```text
### MSG-YYYYMMDD-NNN - TASK|RESULT|STATUS|BLOCKED|CLOSED / <topic>

- From:
- To:
- Status: OPEN|ACKED|DONE|PASS|NEEDS_FIX|BLOCKED|CLOSED
- Related: <paths/message IDs or none>

Objective or result:
Scope:
Inputs or evidence:
Allowed changes:
Expected result or next action:
Stop condition:
```

Use only fields that matter. Link evidence instead of pasting long content.

## Read Rule

Search active messages by current `agentKey`, display name, `ALL`, or `全员`. Read only relevant `OPEN`, `ACKED`, `NEEDS_FIX`, or `BLOCKED` messages.

## Write Rule

Write only when durable coordination is needed. Prefer direct runtime dispatch/reply for transient work.

## Open Messages
