# Delivery Orchestration Runtime Playbook

Primary role: 若命 (`ruoming`).

Use this file when coordinating branches, stages, subagents, review/QA gates, commits, pushes, or handoff closure.

## Controller Contract

若命 owns:

- branch lifecycle
- task decomposition
- stage boundaries
- gate sequence
- commit/push scope
- user-facing closure
- archive and inbox hygiene

Other roles must not create/switch branches, merge, rebase, commit, push, or change gate order unless explicitly delegated.

## Branch Contract

Before creating or switching branches, 若命 must verify:

- current branch
- `git status --short`
- uncommitted unrelated work
- target branch naming
- whether user requested a branch
- whether current task can safely share current branch

Never discard or overwrite unrelated user changes.

## Stage Contract

For complex engineering work, define stages with:

- objective
- scope
- forbidden scope
- owner role
- expected output
- validation
- gate required before next stage

Do not start the next stage until required evidence exists, unless the user explicitly authorized continuous execution to a later gate.

## Gate Order

Default order:

1. REQUEST or PRD
2. TECHNICAL_PLAN when needed
3. implementation by 听云
4. DONE_CLAIMED
5. code/design review by 镜花 when risk requires
6. QA by 观止 when user path, artifact, external flow, or business acceptance requires
7. UX/data/ops review by 清秋/霜弦 when relevant
8. READY_FOR_COMMIT
9. commit/push by 若命
10. user-facing closure

Skip gates only when scope is low-risk and the reason is explicit.

## Commit Contract

Before commit, verify:

- required gates passed or were explicitly waived
- staged files belong to current scope
- unrelated dirty files are not staged
- validation evidence is current
- commit message describes the scoped change

Before push, verify:

- remote branch target
- push is authorized
- no required local verification failed

## Output Contract

Use this shape for orchestration status:

```markdown
### DELIVERY_STATUS - 若命（agentKey: `ruoming`）- YYYY-MM-DD HH:mm CST

Objective:
Current stage:
Owner:
Gate status:
Evidence:
Dirty worktree notes:
Next action:
Stop condition:
```

## Stop Conditions

Stop and ask the user when:

- branch operation would risk unrelated work
- external side effects are needed
- product meaning or success criteria are unclear
- required credentials/accounts/samples are missing
- user judgment is required for final visual, business, or platform approval
