# Task Center Shrink Route Rework Implementation Plan

> **For agentic workers:** REQUIRED: Do not implement this plan until 若命 and 镜花 review it. After approval, use superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rework `MSG-20260617-010` from the rejected projection route to the approved shrink route: task-run list filters must not expose `stale_running`, `waiting_dependency`, or `planned`; details may keep those as diagnostic states.

**Architecture:** Keep the task center list as a lightweight `task_runs` single-table view with DB-level pagination and true totals. Keep step-derived diagnostic states in detail responses only, where groups/steps/events are already loaded. Remove unreviewed run-level projection storage, schema ensure, startup backfill, list filter usage, and tests that lock the rejected projection route.

**Tech Stack:** FastAPI, SQLAlchemy async ORM, React/Ant Design, project-rule tests in `scripts/test_project_rules.py`.

---

## Scope And Current Facts

This plan follows `docs/project-index.md -> docs/domain-index/task-runtime.md -> scoped rg`.

Relevant files:

- `backend/app/api/task_runs.py`
- `backend/app/task_runtime/display.py`
- `backend/app/task_runtime/scheduler.py`
- `backend/app/models/models.py`
- `backend/app/database.py`
- `backend/app/main.py`
- `frontend/src/pages/TaskRunCenter.tsx`
- `scripts/test_project_rules.py`
- `docs/domain-index/task-runtime.md`
- `docs/collaboration/inbox.md`

Current rejected projection route facts:

- `TaskRun` currently has projection fields such as `display_status`, `display_reason`, `available_actions_json`, and `projection_updated_at`.
- MySQL schema ensure currently adds those projection fields and `idx_task_runs_display_status_id`.
- `main.py` currently imports and calls `backfill_task_run_display_projections()` under `STARTUP_RUN_BACKFILLS`.
- `scheduler.py` currently refreshes display projection after claim/start/retry/recover paths.
- `api/task_runs.py` currently lets `_display_status_sql_condition("stale_running"|"waiting_dependency"|"planned")` read `TaskRun.display_status`.
- `TaskRunCenter.tsx` still exposes `{ value: 'stale_running', label: '疑似卡住' }`.
- `scripts/test_project_rules.py` currently contains projection-route tests that require `stale_running` to be DB pageable and force projection fields to exist.

Product decision from `MSG-20260617-009/010`:

- This round uses the shrink route, not the projection route.
- List/filter/total must not expose `stale_running`, `waiting_dependency`, or `planned`.
- Details may show those states as diagnostics.
- No step JOIN/`EXISTS`/subquery/in-memory pagination may be added to list endpoints.

## Explicit Keep / Remove Decision For Review

Remove in this rework:

- `task_runs` projection ORM fields added for the rejected route.
- MySQL ensure columns and `idx_task_runs_display_status_id`.
- `backfill_task_run_display_projections()` and its startup hook.
- scheduler/API calls that persist projection snapshots.
- list response logic that prefers stored projection fields.
- list filter support for `stale_running`, `waiting_dependency`, and `planned`.
- frontend `stale_running` filter option and URL propagation for unsupported filters.
- project-rule tests that require projection route.

Keep:

- Existing task status labels and detail diagnostic display for `stale_running`, `waiting_dependency`, and `planned`.
- Detail actions such as `wake_runtime` and `mark_interrupted` when a loaded detail response is truly `stale_running`.
- Lightweight list fallback based on trusted `TaskRun.status`, `cancel_requested_at`, and `superseded_by_run_id`.
- DB pageable list shape: `task_runs` single table `where + order + offset + limit` plus true count.

Open review point:

- A pure helper that computes detail display from loaded steps may live in `backend/app/task_runtime/display.py` or be inlined in `backend/app/api/task_runs.py`; it must not persist projection, feed list filters, or run backfill. The implementer should pick the smaller diff after review.

## Chunk 1: Tests And Guardrails

### Task 1: Replace Projection Route Tests With Shrink Route Tests

**Files:**
- Modify: `scripts/test_project_rules.py`
- Read: `backend/app/api/task_runs.py`
- Read: `frontend/src/pages/TaskRunCenter.tsx`

- [ ] **Step 1: Remove or rewrite projection-route assertions**
  Remove assertions that require:
  - `TaskRun.display_status` / `available_actions_json` / `projection_updated_at`
  - `idx_task_runs_display_status_id`
  - `TaskRun.display_status == display_status`
  - `stale_running` DB pageable
  - list response preferring stored projection

- [ ] **Step 2: Add API unsupported-filter guard test**
  Add a test that runs a backend Python snippet:
  ```python
  from fastapi import HTTPException
  from app.api.task_runs import _display_status_sql_condition

  for value in ("stale_running", "waiting_dependency", "planned"):
      try:
          _display_status_sql_condition(value)
      except HTTPException as exc:
          assert exc.status_code == 400
          assert "仅在详情诊断" in str(exc.detail)
      else:
          raise AssertionError(f"{value} must be rejected for list filtering")
  ```

- [ ] **Step 3: Add frontend filter guard test**
  Add static assertions:
  - `"{ value: 'stale_running'" not in TaskRunCenter.tsx`
  - `UNSUPPORTED_LIST_DISPLAY_STATUSES` exists or equivalent sanitize helper exists
  - `searchParams.get('display_status')` is passed through a sanitizer before state initialization

- [ ] **Step 4: Keep detail diagnostic behavior test**
  Keep or add a code-level test proving `_run_display()` still returns `stale_running` for `RUN_STATUS_RUNNING + STEP_STATUS_RUNNING + locked_until < now`, with `wake_runtime` and `mark_interrupted`.

- [ ] **Step 5: Run project rules and confirm expected failure before implementation**
  Run: `make test-project-rules`
  Expected: FAIL until code is changed.

## Chunk 2: Backend Shrink Route

### Task 2: Remove Stored Projection Schema And Backfill

**Files:**
- Modify: `backend/app/models/models.py`
- Modify: `backend/app/database.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/task_runtime/display.py`
- Modify: `backend/app/task_runtime/scheduler.py`

- [ ] **Step 1: Remove projection ORM fields**
  Remove from `TaskRun`:
  - `display_status`
  - `display_reason`
  - `current_step_id`
  - `current_step_status`
  - `current_step_label`
  - `available_actions_json`
  - `error_summary`
  - `latest_event_message`
  - `last_heartbeat_at`
  - `progress_current`
  - `progress_total`
  - `progress_percent`
  - `projection_updated_at`

- [ ] **Step 2: Remove MySQL projection ensure and index**
  Remove those column additions from `_ensure_mysql_task_run_action_columns()`.
  Remove `idx_task_runs_display_status_id` from `_ensure_mysql_hot_path_indexes()`.

- [ ] **Step 3: Remove startup display projection backfill**
  Remove `backfill_task_run_display_projections` import and call from `backend/app/main.py`.
  Remove the backfill function from `backend/app/task_runtime/display.py`.

- [ ] **Step 4: Remove scheduler projection persistence calls**
  Remove `refresh_task_run_projection` import and calls from `backend/app/task_runtime/scheduler.py`.
  State changes should continue to update canonical run/group/step status fields as before.

- [ ] **Step 5: Run backend compile**
  Run: `make backend-compile`
  Expected: PASS.

### Task 3: Make List Filtering Reject Unsupported Diagnostic States

**Files:**
- Modify: `backend/app/api/task_runs.py`
- Modify: `backend/app/task_runtime/display.py`

- [ ] **Step 1: Remove list display dependency on stored projection**
  In `_run_list_display()`, remove `task_run_projection_from_fields()` and stored `available_actions_json` usage.
  Return list status/actions from trusted run-level fields only.

- [ ] **Step 2: Keep detail diagnostic display**
  Ensure `_run_display()` still computes:
  - `stale_running` from loaded running step lock/heartbeat
  - `waiting_dependency` from loaded pending step
  - `planned` from pending run with no steps

- [ ] **Step 3: Reject unsupported list filters**
  In `_display_status_sql_condition()`:
  ```python
  if display_status in {"stale_running", "waiting_dependency", "planned"}:
      raise HTTPException(400, "该状态仅在详情诊断中展示，当前列表不支持筛选")
  ```

- [ ] **Step 4: Keep list SQL single-table**
  Ensure `list_task_runs()` has no `selectinload`, JOIN, `exists`, step query, scan window, or in-memory pagination.

- [ ] **Step 5: Run focused project rules**
  Run: `make test-project-rules`
  Expected: PASS after frontend task is complete, or fail only on frontend guard until Chunk 3 lands.

## Chunk 3: Frontend Shrink Route

### Task 4: Remove Unsupported List Filters From TaskRunCenter

**Files:**
- Modify: `frontend/src/pages/TaskRunCenter.tsx`

- [ ] **Step 1: Add unsupported status sanitizer**
  Add a local constant:
  ```ts
  const UNSUPPORTED_LIST_DISPLAY_STATUSES = new Set(['stale_running', 'waiting_dependency', 'planned']);
  ```
  Add a helper:
  ```ts
  const sanitizeDisplayStatusParam = (value: string | null) =>
    value && !UNSUPPORTED_LIST_DISPLAY_STATUSES.has(value) ? value : undefined;
  ```

- [ ] **Step 2: Sanitize URL initialization**
  Change:
  ```ts
  const [displayStatus, setDisplayStatus] = useState<string | undefined>(() => searchParams.get('display_status') || undefined);
  ```
  to use the sanitizer.

- [ ] **Step 3: Remove stale running filter option**
  Delete:
  ```ts
  { value: 'stale_running', label: '疑似卡住' },
  ```

- [ ] **Step 4: Preserve polling and detail diagnostics**
  Do not remove `stale_running` from tag coloring or detail action rendering.
  `hasActiveRun` may continue treating diagnostic states as active if they appear in detail/list responses, but this must not create a filter option.

- [ ] **Step 5: Run frontend build**
  Run: `cd frontend && npm run build`
  Expected: PASS, with existing Vite chunk-size warning acceptable if unchanged.

## Chunk 4: Documentation And Final Verification

### Task 5: Update Collaboration And Domain Index

**Files:**
- Modify: `docs/domain-index/task-runtime.md`
- Modify: `docs/collaboration/inbox.md`

- [ ] **Step 1: Update task-runtime domain index**
  Keep the 2026-06-17 product boundary:
  - task center is async execution fact center
  - product flow remains business state/action center
  - `stale_running/waiting_dependency/planned` are detail diagnostics, not list filter/total states this round

- [ ] **Step 2: Write DONE_CLAIMED only after implementation and verification**
  Under `MSG-20260617-010`, include:
  - files changed
  - projection route changes removed/kept
  - frontend filter changes
  - API unsupported behavior
  - tests and commands
  - no-side-effect statement
  - index update status

### Task 6: Final Verification

Run all required commands:

- [ ] `make backend-compile`
- [ ] `make test-project-rules`
- [ ] `git diff --check`
- [ ] `cd frontend && npm run build`

Expected:

- Backend compile PASS.
- Project rules PASS.
- Diff check PASS.
- Frontend build PASS, existing chunk warning acceptable if no new failure.

## Non-Goals During Implementation

- Do not migrate old `offline_tasks`.
- Do not trigger real task actions, GIGA pull, exports, A+, product status advancement, or external platforms.
- Do not use step JOIN/`EXISTS`/subqueries or in-memory pagination for the list endpoint.
- Do not make task center infer product business state.
- Do not declare projection route accepted or complete.
