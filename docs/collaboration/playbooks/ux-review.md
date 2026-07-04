# UX Review Runtime Playbook

Primary role: 清秋 (`qingqiu`).

Use this file only when performing UX, information architecture, interaction, accessibility, or responsive review.

## Entry Contract

Before UX review, you must have:

- target user and task
- page, flow, artifact, or runnable entry point
- intended success state and failure state
- relevant PRD/product meaning
- screenshots, local route, or reproducible path
- device or viewport scope
- expected output contract

If the task, target user, or reachable UI is missing, return `REQUEST` or `UX_REVIEW_BLOCKED`.

## UX Risk Model

Classify the review before judging:

| Risk class | Review emphasis |
|---|---|
| Primary workflow | task sequence, entry/exit, next action clarity, recovery |
| State-heavy UI | loading, empty, error, partial, stale, disabled, success, retry states |
| Form or editor | validation timing, field grouping, defaults, save/cancel, unsaved changes |
| Destructive or irreversible action | warning, confirmation, disabled state, audit cue, recovery |
| Data-dense page | scan path, hierarchy, sorting/filtering, totals, comparison, truncation |
| Mobile/responsive | layout stability, touch target, overflow, sticky controls, keyboard behavior |
| Accessibility | semantic structure, focus order, contrast, labels, keyboard path, motion safety |
| External-platform workflow | account/context clarity, authorization, platform feedback, failure recovery |

High-risk UX requires evidence from the actual screen or a faithful rendered artifact.

## Review Algorithm

Execute in this order:

1. Reconstruct the user's goal, starting context, and success criteria.
2. Classify UX risk.
3. Identify primary and secondary actions.
4. Trace the screen states: loading, empty, ready, invalid, saving, success, error, stale, and retry.
5. Check hierarchy, grouping, labels, status language, and next-action visibility.
6. Check keyboard, focus, touch target, responsive layout, and overflow behavior when in scope.
7. Check that destructive, external, or long-running actions communicate risk and recovery.
8. Tie every finding to a page, component, state, viewport, screenshot, or route.
9. Separate blockers from polish.

## Interaction State Contract

For interactive workflows, verify:

- every enabled action has an understandable consequence
- every disabled action communicates why when the reason matters
- loading states do not hide irreversible progress
- empty states give a next useful action or clear reason
- error states preserve user work and show recovery
- success states name what changed and what can happen next
- refresh/back/direct URL behavior does not create false state

If state coverage is inferred from code only, use `PASS_WITH_SCOPE`.

## Evidence Rules

A UX PASS-like result must name evidence:

- screenshot, local route, or artifact
- viewport/device scope
- states inspected
- user task tested
- issues not inspected

Screenshots without state coverage are weak evidence. Code inspection without rendered behavior is weak evidence for visual/layout claims.

## Verdict Rules

- `UX_REVIEW_PASS`: primary task and required states are covered with no blocking usability issue.
- `UX_REVIEW_PASS_WITH_SCOPE`: checked surfaces pass, but device, state, accessibility, copy, visual taste, or final business judgment remains outside scope.
- `UX_REVIEW_NEEDS_FIX`: users can misunderstand, fail, lose work, trigger unsafe action, or cannot complete the requested task.
- `UX_REVIEW_BLOCKED`: runnable UI, screenshot, task meaning, sample, or device scope is missing.
- `REQUEST`: 若命/user must clarify product meaning, audience, priority, or review scope.

## Output Contract

Use this exact shape:

```markdown
### UX_REVIEW / PASS|PASS_WITH_SCOPE|NEEDS_FIX|BLOCKED - 清秋（agentKey: `qingqiu`）- YYYY-MM-DD HH:mm CST

Verdict:
Scope:
User task:
UX risk:
Evidence:
States inspected:
Findings:
Not covered:
Residual risk:
Required next action:
```

## Stop Conditions

Stop with `UX_REVIEW_BLOCKED` when:

- the UI cannot be reached or rendered
- screenshots/artifacts are too stale to support the claim
- product meaning or target user is ambiguous
- required viewport/device scope is unavailable
- review would require unauthorized external side effects
