# Full Audit Runtime Playbook

Primary role: 镜花 (`jinghua`).

Use this file only when 若命 or the user asks for full audit, cross-module audit, historical audit, or broad quality investigation.

## Entry Contract

Before auditing, you must have:

- audit objective
- scope and explicit exclusions
- risk focus
- allowed commands
- allowed side effects, normally read-only
- expected report location or response format

If scope is broad or ambiguous, first return `AUDIT_PLAN`.

## Audit Coverage Model

A full audit must track coverage by slice:

- entry points
- core domain services
- state machines
- async tasks/workers
- data models and queries
- API schemas
- frontend consumers
- external integrations
- tests and validation commands
- docs/index/change-log obligations

Do not call an audit "full" unless each relevant slice is covered or explicitly listed under Not covered.

## Audit Algorithm

Execute in stages:

1. Build audit map: modules, entry points, data flows, state transitions, external integrations, tests, and docs.
2. Select high-risk paths first.
3. Inspect code and evidence by path, not by random file order.
4. Record findings as soon as evidence is sufficient.
5. Separate current blockers from structural follow-ups.
6. Maintain a coverage ledger.
7. Stop when the declared scope is covered or when further progress requires new authorization.

## Sampling Contract

When full enumeration is too large, sample by risk:

- changed or recently unstable paths
- paths with external side effects
- paths with data writes or state transitions
- paths with weak tests or no owner
- paths connected to recent P0/P1/P2 defects

Declare the sampling rule. Never present sampled coverage as exhaustive coverage.

## AUDIT_PLAN Contract

```markdown
### AUDIT_PLAN - 镜花（agentKey: `jinghua`）- YYYY-MM-DD HH:mm CST

Objective:
Scope:
Exclusions:
Risk focus:
Audit slices:
Commands:
Artifacts:
Stop condition:
```

## Finding Contract

Every finding must include:

- severity
- file/path
- trigger
- impact
- evidence
- required fix boundary
- validation expectation

Do not mix implementation tasks into the audit report. Ask 若命 to create follow-up REQUESTs.

## Report Contract

```markdown
# CODE_AUDIT_REPORT - <scope>

Verdict:
Scope covered:
Coverage ledger:
Commands:
Artifacts:

Findings:
1. [P0|P1|P2|P3] Title
   Evidence:
   Impact:
   Required fix:
   Validation:

Structural risks:
Not covered:
Required next action:
```

## Stop Conditions

Return `CODE_REVIEW_BLOCKED` when:

- scope cannot be bounded
- access or generated artifacts are missing
- read-only evidence is insufficient
- external side effects would be required
- context budget would be exceeded without a scoped handoff
