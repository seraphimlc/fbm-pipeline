# Amazon Workflow T4 Competitor Search Code Review

- Reviewer: 镜花（agentKey: `jinghua`）
- Time: 2026-06-18 16:16 CST
- Related inbox: `MSG-20260618-011`
- Conclusion: `CODE_REVIEW / PASS`

## Scope

- PRD / request: `docs/superpowers/specs/2026-06-18-amazon-product-workflow-prd.md` T4, `MSG-20260618-010`, `MSG-20260618-011`
- Code reviewed:
  - `backend/app/api/amazon_stylesnap.py`
  - `backend/app/api/products.py`
  - `backend/app/api/schemas.py`
  - `frontend/src/api/index.ts`
  - `frontend/src/pages/ProductCompetitorReview.tsx`
  - `scripts/test_project_rules.py`
  - `docs/domain-index/product-flow.md`
- Not covered:
  - Page QA, real StyleSnap / Chrome search, real product state changes, real task runs, exports, external platforms.

## Index Review

- Used indexes:
  - `docs/project-index.md`
  - `docs/domain-index/product-flow.md`
- Result:
  - `product-flow` correctly routes this review to product flow, StyleSnap API, competitor review page, schemas, and workflow PRD.
  - T4 behavior was added to `docs/domain-index/product-flow.md`.
  - `docs/project-index.md` does not need an update because no top-level route/domain entry changed.

## Evidence

- Static review:
  - `backend/app/api/amazon_stylesnap.py:965` search endpoint writes `search_competitor/processing` before scheduling the one-shot `BackgroundTasks` search.
  - `backend/app/api/amazon_stylesnap.py:989` missing image / batch / item preconditions on an allowed search node write `search_competitor/failed` and return a workflow-bearing response.
  - `backend/app/api/amazon_stylesnap.py:1015` existing candidates with `force=false` write `select_competitor/pending` and do not call `background_tasks.add_task`.
  - `backend/app/api/amazon_stylesnap.py:681` background search writes success to `select_competitor/pending`, ordinary empty/error results to `search_competitor/failed`, token/browser failures to `get_stylesnap_token/pending`, and `CancelledError` to `search_competitor/failed` before re-raising.
  - `backend/app/api/products.py:325` and `backend/app/api/products.py:2931` make competitor queue selection workflow-based instead of using `error_message` regex as the main queue source.
  - `backend/app/api/products.py:3001` competitor detail includes workflow fields and derives `current_task_status` from workflow.
  - `frontend/src/pages/ProductCompetitorReview.tsx:67` reads workflow node/status for failed and token-pending decisions; no page redesign was included.
  - Scoped search found no `TaskRun` / `task_runs` creation in `backend/app/api/amazon_stylesnap.py`; T4 still uses only FastAPI `BackgroundTasks`.
- Verification commands:
  - `make backend-compile` passed.
  - `make test-project-rules` passed: `OK: 43 project rule test(s)`.
  - `npm run build` passed; Vite reported only the existing chunk-size warning.
  - `git diff --check -- backend/app/api/amazon_stylesnap.py backend/app/api/products.py backend/app/api/schemas.py frontend/src/api/index.ts frontend/src/pages/ProductCompetitorReview.tsx scripts/test_project_rules.py docs/domain-index/product-flow.md docs/collaboration/inbox.md` passed.
  - Additional local function-level sample with fake DB / monkeypatching passed for `_run_product_competitor_search_background()`:
    - success -> `select_competitor/pending`
    - ordinary empty/error -> `search_competitor/failed`
    - token/browser error -> `get_stylesnap_token/pending`
    - `CancelledError` -> `search_competitor/failed`

## Findings

No P0/P1 findings.

## Confirmed Passed

- Search start, existing-candidate reuse, background success, ordinary failure, token/browser failure, and cancellation all have deterministic workflow write paths.
- No `search_competitor/succeeded` write path was introduced by T4; the old T2 projection compatibility remains unused as a main fact.
- Competitor queue and detail now select/read workflow fields and return workflow to the frontend.
- Frontend changes are limited to type additions and lightweight workflow-based status/failure/token checks.
- The implementation does not write `task_runs`, does not enter task center, does not add a persistent queue/worker pool, and does not implement T5-T9.

## Residual Risk

- FastAPI `BackgroundTasks` remains an in-process one-shot executor. The implementation handles normal exceptions and cancellation when the coroutine runs, but a process crash can still strand a product in `search_competitor/processing`. This is an accepted T4 boundary risk and needs a separately authorized durable scheduler/plugin design to eliminate.
- Tests still rely partly on structural guards, but the added helper test plus this review's function-level background sample cover the highest-risk workflow state transitions sufficiently for code review. Broader endpoint/API behavior remains QA or a later backend test-hardening task.
- This PASS is code review only. It is not QA PASS, real StyleSnap/Chrome validation, page acceptance, or external-platform verification.
