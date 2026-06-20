# Amazon Competitor Visual Match Phase B Design Review

- Reviewer: 镜花 (`jinghua`)
- Date: 2026-06-20 CST
- Source message: `docs/collaboration/inbox.md` / `MSG-20260620-008`
- Review nodes: `SOLUTION_REVIEW`, `ARCHITECTURE_REVIEW`, `DATA_REVIEW`, `TASK_LIFECYCLE_REVIEW`, `TEST_REVIEW`

## Scope

This review covers Tingyun's `ACK / TECHNICAL_PLAN` for Amazon automatic competitor visual matching Phase B.

In scope:

- Data contract for visual matching fields on `amazon_competitor_search_candidates`.
- Candidate selection semantics from Phase A to Phase B.
- `product_competitor_visual_match` task/action/planner lifecycle.
- Workflow node/action mapping for `visual_match_competitors` and `capture_competitor_candidates`.
- Service boundary for visual matching and fake VLM tests.
- Minimum frontend/API/documentation/index plan.

Out of scope:

- Code implementation review.
- Page QA or UX acceptance.
- Real product, real task run, real Amazon image download, real VLM, StyleSnap/Chrome, external platform validation.
- Old StyleSnap compatibility; old active path is no longer an accepted target.

## Gate

`DESIGN_REVIEW / NEEDS_ADJUST`

The plan is directionally sound and mostly specific enough to implement, but two P1 design contracts must be fixed before implementation starts.

## Blocking Findings

### P1. Phase B candidate input must be restricted to the current successful Phase A run

Standard: Phase B must consume a deterministic candidate set from the current successful competitor-search result. It cannot read all candidates for the product and sort them opportunistically, because old Phase A retries may leave historical ASINs in the same table.

Evidence:

- `AmazonCompetitorSearchCandidate` is unique on `(product_id, asin)` in `backend/app/models/models.py`.
- `_upsert_competitor_search_candidates()` in `backend/app/product_tasks/actions.py` only upserts ASINs present in the new search result. It does not delete or mark stale ASINs from older search runs.
- `ProductCompetitorSearchAction.on_step_success()` moves the product to `visual_match_competitors/pending`, but the plan only says Phase B reads Phase A candidates and caps to 20 candidates. It does not define a query such as `task_run_id == current_search_run_id`, `task_step_id == current_search_step_id`, or another explicit current-run marker.

Risk: A visual-match retry after a competitor-search retry can mix stale candidates from an older search run with candidates from the latest successful run. That would make Top 4-6 neither reproducible nor traceable to the current Phase A evidence.

Minimum adjustment:

- Define the Phase B input query as "candidates from the current successful Phase A run" and state how the current search run is found.
- Acceptable designs include using the latest successful `product_competitor_search` run/step evidence, storing a current search batch/run marker on candidates, or marking older product candidates stale during Phase A success.
- Downstream `visual_selected_for_capture=1` must only be written for candidates in that current input set.

### P1. Processing-state active-run reuse conflicts with current planner execution order unless the plan defines the bypass

Standard: retry/start API must be idempotent in `processing` and must not create duplicate task runs. The design must match the existing `create_product_action_runs()` call order.

Evidence:

- `create_product_action_runs()` in `backend/app/product_tasks/actions.py` calls `action.validate(db, payload)` before `_existing_active_run(db, action, payload)`.
- Tingyun's plan says `validate` allows `visual_match_competitors/pending|failed|processing`, where `processing` is only allowed to reuse an active run and must not create a second run.
- Because active-run lookup happens after validate, `validate()` cannot by itself know whether a processing product has an active reusable run unless the API handles processing before calling the planner, or the planner order/validation contract changes.
- Existing `POST /api/products/{id}/competitor-search/retry` handles `WORKFLOW_STATUS_PROCESSING` in the API before calling the planner.

Risk: If implemented literally, either processing retries are rejected even when an active run exists, or processing is allowed broadly enough that a missing/failed active run can still pass validation and reserve unexpectedly.

Minimum adjustment:

- Choose one concrete contract before implementation:
  - API-level bypass: if workflow is `visual_match_competitors/processing`, return the current product/workflow and task-center correlation without calling `create_product_action_runs()`.
  - Planner-level change: move active-run lookup before action validation, with regression coverage for existing product actions.
- Document the chosen behavior and add a project-rule or unit test proving processing does not create a duplicate run.

## Non-blocking Adjustments

### P2. Replace the ambiguous protection-helper choice with a concrete product protection contract

The plan says visual matching can reuse `auto_image_selection_protection_reasons()` or split a more accurate helper. The returned reasons are currently about irreversible external results and are semantically reusable, but the helper name is tied to auto image selection.

Minimum adjustment: pick one contract in the plan. Prefer a neutral helper such as `product_external_result_protection_reasons()` with existing callers delegated to it, or explicitly justify reusing the old helper without changing behavior in this phase.

### P2. Make candidate-image download limits testable

The service design correctly mentions max candidate count, content type, size, timeout, and failure classification. Current low-level `download_remote_image()` does not enforce content-type or byte-size limits, so Phase B must implement those limits in the new service or a shared helper.

Minimum adjustment: include at least one fake/service test or project-rule assertion proving oversized/invalid-content images do not become successful candidate evidence.

### P2. Define retry invalidation visibility

The plan clears old visual fields in `reserve()`. That prevents stale `visual_selected_for_capture=1`, but it also means a failed retry intentionally invalidates the previous successful visual result. This can be acceptable if the product is visibly returned to `visual_match_competitors/failed`, but it must be stated as product behavior.

Minimum adjustment: document that starting a retry invalidates previous Phase B selection, and that failure/cancel/interruption leaves no current selected candidates.

## Passed Checks

- Keeping candidate-level visual facts on `amazon_competitor_search_candidates` is acceptable for Phase B. The table is already the Phase A candidate fact source, and the proposed fields separate sortable/filterable facts from large JSON evidence.
- Adding `visual_selected_for_capture` as the only downstream Top candidate marker is the right contract. It avoids later stages guessing from all scores.
- A separate `amazon_competitor_visual_match.py` service is the right boundary. Existing `product_image_vlm.py` utilities can be reused, but the auto-image-selection contact-sheet semantics should not be reused as the competitor visual-match domain model.
- The plan correctly keeps `execute` side-effect light and writes DB results in `on_step_success()`, matching Phase A's task-action pattern.
- `capture_competitor_candidates` is the right new success node for the new chain. Keeping `capture_competitor_detail` only as old-data compatibility is acceptable under the user's latest StyleSnap-retirement boundary.
- Delaying Phase A to Phase B auto-chaining to a separate gate is a sound risk reduction. The retry/start entrance is enough for the first implementation slice.
- The test plan covers the important behavior classes: fake VLM, Top marking, failure without half-success, no bare background task, workflow projection, and no Step 10/template side effects.

## Gate Meaning

This review only gates the technical plan. It does not approve code, QA, real VLM quality, real Amazon image download, real product/task execution, external platform behavior, or final submission.

Implementation should not start until the P1 plan adjustments are written back under `MSG-20260620-008` or a follow-up plan message and accepted by Ruoming.
