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
Risk class:
Test design technique:
Preconditions:
Sample requirements:
Steps:
Expected results:
Evidence to capture:
Evidence strength required:
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
- risk class and design technique are named
- evidence required is strong enough for the risk class

Do not add vague checklist items.

## Library Quality Bar

A mature QA library must include cases for:

- smoke path
- main user path
- negative path
- permission/destructive action path
- state transition or async path when the domain has tasks
- data consistency path when UI/API/DB/artifact must agree
- artifact/export path when generated outputs exist
- regression path for recent P0/P1/P2 bugs

If a domain lacks these categories, mark the gap in the QA result instead of pretending the library is complete.

## Maintenance Rules

Update a case when product behavior, API contract, UI flow, template, external-platform rule, or sample requirement changes.

Retire a case when:

- path no longer exists
- risk is obsolete
- replacement case covers the same risk better

Never delete retired cases without 若命/user authorization; mark them retired with reason.
