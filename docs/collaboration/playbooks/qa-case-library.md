# QA Case Library Runtime Playbook

Primary role: 观止 (`guanzhi`).

Use this file when selecting, creating, updating, or retiring reusable QA cases.

## Case Contract

Every reusable QA case must include:

```markdown
### QA-CASE-<domain>-<slug>

Status: active | draft | retired
Owner: 观止（agentKey: `guanzhi`）
Domain:
Risk covered:
Preconditions:
Sample requirements:
Steps:
Expected results:
Evidence to capture:
Side effects:
Cleanup:
Last validated:
Related bugs / messages:
```

## Selection Rules

For each QA task, select cases by:

- changed domain
- user path
- risk type
- historical bug class
- side effect profile
- artifact/export/platform involvement

Add ad hoc cases when the request has new risk not covered by the library.

## Admission Rules

Add a case only when:

- it catches a realistic regression
- steps are reproducible
- expected result is objective
- sample requirements are explicit
- side effects and cleanup are clear

Do not add vague checklist items.

## Maintenance Rules

Update a case when product behavior, API contract, UI flow, template, external-platform rule, or sample requirement changes.

Retire a case when:

- path no longer exists
- risk is obsolete
- replacement case covers the same risk better

Never delete retired cases without 若命/user authorization; mark them retired with reason.
