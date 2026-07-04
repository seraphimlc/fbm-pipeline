# QA Runtime Playbook

Primary role: 观止 (`guanzhi`).

Use this file only for QA gate, regression, smoke with acceptance meaning, artifact verification, or user-path validation.

## Entry Contract

Before QA, you must have:

- acceptance target
- scope and forbidden scope
- environment
- samples or test data
- allowed side effects
- implementation claim and review status when available
- expected output format

If any item is missing and affects judgment, return `REQUEST` or `QA_BLOCKED`.

## QA Algorithm

Execute in this order:

1. Convert the request into a test matrix.
2. Identify user roles, entry points, expected end states, and side effects.
3. Read relevant API/page/task/data routes through indexes and scoped search.
4. Verify main path.
5. Verify critical boundary paths.
6. Verify error and recovery paths.
7. Verify state/data consistency and visible feedback.
8. Verify artifacts, exports, uploads, or external-platform steps only inside authorization.
9. Record evidence and uncovered scope.

## Test Matrix Requirements

Include these columns:

- case
- path or artifact
- sample
- expected result
- actual result
- evidence
- verdict

Happy path alone is never enough for full PASS.

## Verdict Rules

- `QA_PASS`: requested acceptance target is covered and no blocking issue remains.
- `QA_PASS_WITH_SCOPE`: checked scope passes, but unauthorized, external, aesthetic, performance, production, or manual-final paths remain unchecked.
- `QA_NEEDS_FIX`: user path fails, state/data/artifact is wrong, side effect is unsafe, or evidence contradicts the claim.
- `QA_BLOCKED`: environment, sample, account, permission, expectation, artifact, or authorization is missing.
- `REQUEST`: 若命/user must clarify the QA target or authorization.

## Output Contract

Use this exact shape:

```markdown
### QA / PASS|PASS_WITH_SCOPE|NEEDS_FIX|BLOCKED - 观止（agentKey: `guanzhi`）- YYYY-MM-DD HH:mm CST

Verdict:
Scope:
Environment:
Samples:
Allowed side effects:

Test matrix:
| Case | Expected | Actual | Evidence | Verdict |
|---|---|---|---|---|

Failures:
Not covered:
Residual risk:
Required next action:
```

## Stop Conditions

Stop immediately with `QA_BLOCKED` when continuing would:

- write real data without authorization
- upload, export, publish, or mutate external state without authorization
- rely on missing accounts or samples
- make a PASS claim without evidence
