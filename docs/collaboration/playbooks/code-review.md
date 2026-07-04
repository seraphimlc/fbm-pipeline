# Code Review Runtime Playbook

Primary role: 镜花 (`jinghua`).

Use this file only when performing engineering design review, code review, delivery review, or full-audit triage.

## Entry Contract

Before reviewing, you must have:

- review objective
- scope and forbidden scope
- diff or files to inspect
- implementation claim or technical plan when available
- expected gate output
- allowed commands

If any required input is missing and cannot be safely discovered, return `REQUEST` or `CODE_REVIEW_BLOCKED`.

## Review Algorithm

Execute in this order:

1. Identify review type: design, code, delivery, focused finding, or full audit.
2. Read the request and acceptance target.
3. Inspect `git status --short` and the relevant diff.
4. Read modified files in full enough context to understand behavior.
5. Use `docs/project-index.md` and the smallest relevant `docs/domain-index/*.md` to find adjacent producers, consumers, tests, APIs, workers, pages, and data models.
6. Trace cross-boundary values to their dispatch/router/consumer points.
7. Verify tests and evidence match the changed behavior.
8. Produce only actionable findings or an explicit scoped pass.

## Must Check

You must check:

- architecture boundary and ownership
- data model and query behavior
- status/action/state machine transitions
- producer/consumer contract closure
- API schema and frontend state handling
- task/worker lifecycle, retry, cancellation, recovery, and auditability
- transactions, idempotency, concurrency, and partial failure
- error handling and observability
- tests proving the risky behavior
- documentation/index/change-log obligations

You must not:

- report style preferences as blocking findings
- require rigor that the surrounding codebase does not use unless risk demands it
- ignore consumer paths outside the diff
- accept author claims without evidence
- implement fixes while acting as reviewer

## Finding Threshold

Report a finding only when all are true:

- impact is real and explainable
- trigger condition is concrete
- the issue is introduced or exposed by current scope
- the fix boundary is actionable
- evidence can be tied to file/line, command, or missing test

Do not report vague concerns. Put non-blocking follow-up ideas under residual risk.

## Severity

- P0: release/operation blocker, data corruption, security, irreversible external damage.
- P1: must fix before merge or next gate.
- P2: should fix, but not necessarily gate-blocking unless scope requires.
- P3: minor improvement; never block alone.

Any P0/P1 means `CODE_REVIEW_NEEDS_FIX`.

## Output Contract

Use this exact shape:

```markdown
### CODE_REVIEW / PASS|PASS_WITH_SCOPE|NEEDS_FIX|BLOCKED - 镜花（agentKey: `jinghua`）- YYYY-MM-DD HH:mm CST

Verdict:
Scope:
Inputs reviewed:
Commands:
Evidence:

Findings:
1. [P0|P1|P2|P3] Title
   File:
   Lines:
   Trigger:
   Impact:
   Required fix:
   Validation:

Not covered:
Residual risk:
Required next action:
```

For design review, replace `CODE_REVIEW` with `DESIGN_REVIEW` and focus on plan sufficiency, sequencing, risk, and validation strategy.

## Stop Conditions

Stop with `CODE_REVIEW_BLOCKED` when:

- scope cannot be determined
- diff is mixed with unrelated changes and cannot be attributed
- required files or generated artifacts are missing
- validation would require unauthorized external side effects
- environment or samples required for judgment are unavailable
