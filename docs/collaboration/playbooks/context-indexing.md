# Context Indexing Runtime Playbook

Use this file when a role must find code, API, DB, page, task, artifact, or validation routes without loading excessive context.

## Search Contract

You must route investigation in this order:

1. current user request
2. `git status --short`
3. `AGENTS.md`
4. current role file
5. `docs/project-index.md`
6. one or two relevant `docs/domain-index/*.md`
7. scoped `rg`
8. direct file reads around relevant lines

Do not read full inbox, full archives, full logs, large generated files, or all domain indexes unless the task explicitly requires it.

## Project Index Contract

`docs/project-index.md` must answer:

- major domains
- main code roots
- main API/page/task/data routes
- validation commands
- hard project boundaries
- domain-index map

It must not become a full architecture document.

## Domain Index Contract

Each `docs/domain-index/*.md` must use this shape:

```markdown
# Domain Index: <Name>

## Scope
## Current Contract
## Key Entrypoints
## Key Flows
## Related Docs
## Validation Entrypoints
## Search Hints
## Maintenance Rules
```

Keep domain indexes short and route-oriented.

## Update Triggers

Update project/domain indexes when you add or change:

- page or route
- API endpoint
- task type or worker flow
- state machine
- database table or important field contract
- export/import path
- external integration
- main validation command
- major generated artifact location

If no index update is needed, be able to state why.

## Context Budget Rules

Before opening a long file, search for:

- `agentKey`
- message ID
- function/class name
- route/path
- status/action key
- template/category key
- artifact filename

Read the smallest useful span. If history is required, create or request a scoped summary instead of loading everything.

## Output Contract

When reporting route discovery, use:

```markdown
Route:
Files read:
Facts found:
Files to inspect next:
Validation entry:
Not checked:
```
