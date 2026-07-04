# Project Runtime Index

Status: route map, not source of truth
Updated: 2026-07-04

Use this file to route investigation. Do not treat it as proof. Verify facts in code, commands, APIs, DB read-only evidence, pages, artifacts, or explicit user decisions.

## Read Contract

Before broad code search, read this file and then the smallest relevant `docs/domain-index/*.md`.

If this file is stale, update it only for the routes affected by the current task.

## Domain Map

| Domain | Domain index | Main roots | Validation |
|---|---|---|---|
| Amazon template/export | `docs/domain-index/README.md` | `backend/app/pipeline/` | mapping/template checks |
| Product flow / A+ | `docs/domain-index/product-flow.md` | `backend/app/pipeline/`, `backend/app/product_tasks/`, `backend/app/task_planners/` | A+ pipeline/task checks |
| Task runtime | `docs/domain-index/task-runtime.md` | `backend/app/task_runtime/`, `backend/app/task_planners/` | task runtime scripts |
| Runtime security | `docs/domain-index/runtime-security.md` | `backend/app/main.py`, `backend/app/services/` | security/startup checks |
| Collaboration | `docs/collaboration.md` | `docs/collaboration/` | `init_collaboration.py --validate-only` |

## Main Entrypoints

Fill or update with stable routes only:

- Backend: `backend/app/`
- Frontend: `frontend/`
- Workers/tasks: `backend/app/tasks/`, `backend/app/pipeline/`
- A+ narrative diagnosis: `backend/app/pipeline/aplus_narrative_diagnosis.py`
- Templates/exports: `backend/app/pipeline/template_mappings/`, `backend/app/pipeline/templates/`
- Lingxing enhanced A+ readiness: `scripts/check_lingxing_enhanced_aplus_qa_readiness.py`
- Lingxing enhanced A+ sample dry-run: `scripts/prepare_lingxing_enhanced_aplus_qa_sample.py`
- Data/migrations:
- Tests:

## Validation Entrypoints

Fill with commands that agents may run locally:

```bash
python3 /Users/liuchang/.codex/skills/multi-agent-collaboration/scripts/init_collaboration.py --project . --validate-only
```

## Hard Boundaries

Agents must not:

- overwrite real product data, manual categories, true ASINs, generated assets, exports, or templates unless the task explicitly requires it
- run irreversible external-platform actions without explicit authorization
- use this index as a substitute for code or runtime evidence

## Maintenance Contract

Update this index when adding or changing:

- major page or route
- API endpoint
- task/worker type
- state machine
- DB table or important field contract
- export/import path
- external integration
- primary validation command
- generated artifact location

Keep entries short and path-oriented.
