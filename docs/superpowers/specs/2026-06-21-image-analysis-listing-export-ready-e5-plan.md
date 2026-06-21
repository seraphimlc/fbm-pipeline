# Image Analysis Listing Export Ready E5 Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `product_image_analysis -> product_listing_generation -> flow_done/succeeded` reliably land safe Amazon products in `Product.status=completed` / product-list `export_ready`, without export, upload, A+, TikTok, or fake completion.

**Architecture:** Keep Product workflow as the business-state source and task center as the async execution source. Reuse the existing ProductTaskAction chain, but harden it with explicit downstream failure projection, explicit retry action mapping, idempotency tests, and irreversible-result protection at image/listing boundaries. Completion is produced only by Listing success through `_project_listing_completed()`.

**Tech Stack:** FastAPI, SQLAlchemy async ORM, ProductTaskAction, task_runs/task_steps/task_step_events, Product workflow service, React ProductList workflow actions.

---

## Current Code Facts

- `ProductImageAnalysisAction` is registered in `backend/app/product_tasks/actions.py` and uses `product_image_analysis` as task type.
- `ProductImageAnalysisAction.validate()` checks Step 5 prerequisites through `_assert_step_prerequisites(product_id, 5)`.
- `ProductImageAnalysisAction.reserve()` projects `workflow_node=image_analysis`, `workflow_status=processing`, `Product.status=STEP6_CURATING`, `current_step=5`.
- `ProductImageAnalysisAction.execute_step()` calls `run_image_analysis(product_id)`.
- `ProductImageAnalysisAction.on_step_success()` currently projects `image_analysis/succeeded`, then calls `create_product_action_runs(..., "product_listing_generation", [{"product_id": product_id, "created_by": "product_image_analysis"}])` and writes listing run ids to the task summary.
- `ProductImageAnalysisAction.on_step_failure()`, `on_step_interrupted()`, and `on_cancel_requested()` project failure/paused state through shared product projection helpers.
- `ProductListingGenerationAction` is registered in `backend/app/product_tasks/actions.py` and uses `product_listing_generation` as task type.
- `ProductListingGenerationAction.validate()` checks Step 6 prerequisites through `_assert_step_prerequisites(product_id, 6)`.
- `ProductListingGenerationAction.reserve()` projects `workflow_node=listing_generation`, `workflow_status=processing`, `Product.status=STEP5_LISTING`, `current_step=6`, and currently clears `catalog_item.confirmed_at`.
- `ProductListingGenerationAction.execute_step()` calls `run_listing(product_id)`.
- `ProductListingGenerationAction.on_step_success()` calls `_project_listing_completed(product)`.
- `_project_listing_completed()` sets `Product.status=completed`, `current_step=6`, clears `error_message`, projects `workflow_node=flow_done`, `workflow_status=succeeded`, syncs `CatalogProduct`, and sets `CatalogProduct.confirmed_at = item.confirmed_at or now`.
- Product workflow failed overrides already expose `retry_image_analysis` and `retry_listing_generation`, but `frontend/src/pages/ProductList.tsx` does not currently map these two action names; only generic `retry` calls `retryStep(product.id)`.
- `ProductList` computes `export_ready` from backend workflow `work_status` first, then falls back to `product.status === "completed"` and no catalog export evidence.
- `_require_generation_prerequisites()` in `backend/app/api/products.py` requires main image and competitor ASIN for Step 5, and image analysis for Step 6; Step 7 is blocked because A+ is separated.
- Existing `product_external_result_protection_reasons()` blocks real Amazon ASIN, catalog export history, template output evidence, A+ evidence, and `CatalogProduct.confirmed_at`. This is correct for upstream destructive rewrites, but E5 must distinguish pre-existing manual confirmation from the controlled `confirmed_at` created by Listing success.

## Scope

### In Scope

- Harden image-analysis success to create or reuse exactly one listing run through ProductTaskAction/planner behavior.
- Ensure downstream listing creation failure is visible as `listing_generation/failed` with a retry path.
- Ensure listing success is the only code path that projects `flow_done/succeeded` and `Product.status=completed`.
- Add explicit API/frontend action mapping for `retry_image_analysis` and `retry_listing_generation`, or intentionally map them to a shared safe retry endpoint with tests.
- Add DB behavior / project-rule tests for success, failure, cancel/interrupted, repeated hooks, active runs, already completed products, and protection gates.
- Keep ProductList, ProductDetail, and Task Center status sourced from backend workflow/task correlation.

### Out of Scope

- Amazon export workbook generation.
- Amazon upload / Seller Central automation.
- A+ generation or upload.
- TikTok listing flow.
- Real external platform calls.
- Any code path that marks a product completed without a successful listing task.

## File Scope

- Modify: `backend/app/product_tasks/actions.py`
  - Add E5 protection helpers and downstream failure projection around image/listing hooks.
  - Keep `_project_listing_completed()` as the single completion projection.
- Modify: `backend/app/product_tasks/workflow.py`
  - Keep `image_analysis`, `listing_generation`, and `flow_done` workflow projections authoritative.
  - Confirm failed overrides expose only implemented actions.
- Modify: `backend/app/api/products.py`
  - Add or reuse explicit safe retry/start endpoints for image analysis and listing generation.
  - Keep `_require_generation_prerequisites()` as the Step 5/6 input gate.
- Modify: `frontend/src/api/index.ts`
  - Add explicit client functions only if backend routes are added.
- Modify: `frontend/src/pages/ProductList.tsx`
  - Map `retry_image_analysis` and `retry_listing_generation` to implemented backend calls.
  - Keep `export_ready` display based on backend workflow first, then `completed` plus no export evidence fallback.
- Modify: `scripts/test_project_rules.py`
  - Add structural/project-rule checks for no fake completion, no ghost actions, and no E5 export/A+/upload side effects.
- Add if accepted: DB behavior tests under the existing test harness location. If no pytest harness exists, either extend `scripts/test_project_rules.py` with deterministic object-level tests or first create a small documented DB test harness before implementing behavior changes.
- Docs: update `docs/domain-index/product-flow.md` and `docs/domain-index/task-runtime.md` only if action names/routes/status semantics change.

## State And Field Contract

### Image Analysis

- Queue/reserve state:
  - `Product.status = STEP6_CURATING`
  - `Product.current_step = 5`
  - `workflow_node = image_analysis`
  - `workflow_status = processing`
  - related correlation key: `product:{id}:image_analysis`
- Success state:
  - `Product.status = STEP6_DONE`
  - `Product.current_step = 5`
  - `workflow_node = image_analysis`
  - `workflow_status = succeeded`
  - creates/reuses `product_listing_generation` task run.
- Failure/cancel/interrupted:
  - project through shared failure/paused helper to `image_analysis/failed` or paused/interrupted equivalent.
  - expose retry through implemented image-analysis retry/start path.

### Listing Generation

- Queue/reserve state:
  - `Product.status = STEP5_LISTING`
  - `Product.current_step = 6`
  - `workflow_node = listing_generation`
  - `workflow_status = processing`
  - related correlation key: `product:{id}:listing_generation`
- Success state:
  - only `_project_listing_completed()` may set:
    - `Product.status = completed`
    - `Product.current_step = 6`
    - `workflow_node = flow_done`
    - `workflow_status = succeeded`
    - `CatalogProduct.confirmed_at` as controlled export-ready evidence.
- Failure/cancel/interrupted:
  - project to `listing_generation/failed` or paused/interrupted equivalent.
  - do not leave product at `completed`.
  - do not create export/A+/upload side effects.

### Export Ready

- Product-list `export_ready` means:
  - `workflow_node=flow_done`
  - `workflow_status=succeeded`
  - `Product.status=completed`
  - no catalog export evidence, so ProductList does not classify the row as exported.
- Export-ready is not an Amazon file, not an upload, and not A+.

## Automatic Chaining Design

### Image Analysis Success Creates Listing

- Keep `ProductImageAnalysisAction.on_step_success()` as the default chaining point.
- Call `create_product_action_runs()` or `create_product_listing_runs()` only; do not call worker functions, `BackgroundTasks`, raw threads, or old pipeline enqueue.
- The action must handle three cases:
  - No active listing run: create one and reserve it, projecting `listing_generation/processing`.
  - Existing active listing run: reuse it, ensure pending step is ready if `auto_start=True`, and keep correlation key stable.
  - Product already completed: do not create another listing run from the automatic success hook; report idempotent no-op in summary.

### Downstream Creation Failure

- If image analysis result is valid but listing run creation fails, do not pretend the whole product reached completion.
- Recommended implementation:
  - Commit or project image analysis success only if downstream creation succeeds in the same controlled transaction.
  - If downstream creation fails after image success has to be preserved, explicitly project `listing_generation/failed` with an error like `图片分析已完成，但 Listing 任务创建失败: ...`.
  - Expose `retry_listing_generation` so the user can restart the downstream node.
- Avoid leaving `image_analysis/succeeded` with no visible next action.

### Listing Success Completes The Flow

- Keep `_project_listing_completed()` as the single completion function.
- Do not add any other `Product.status=completed` writers for E5.
- Completion must not create export tasks, A+ tasks, Amazon upload tasks, or TikTok tasks.

## Idempotency And Consistency

- Repeated image-analysis success hook:
  - Must not create duplicate active listing runs.
  - Must either reuse the active listing run or no-op if product is already completed.
- Duplicate user clicks:
  - Retry/start endpoints must use existing planner/ProductTaskAction dedupe key and active-run lookup.
  - ProductList should disable/loading only as UI polish; correctness belongs to backend dedupe.
- Existing active runs:
  - `create_product_action_runs()` already looks up active runs by action dedupe/correlation; E5 tests must lock this behavior for image/listing.
- Already completed products:
  - Automatic chain should no-op and keep `flow_done/succeeded`.
  - Manual rerun from Step 6, if preserved, must be a separate explicit user action and must not be triggered by the auto chain.
- Task center consistency:
  - Product workflow points to the current business node.
  - Task center retains run/step/event evidence.
  - ProductList/Detail should use backend workflow `related_correlation_key` for task-center navigation.

## Protection Boundaries

- Before creating image/listing runs in the auto chain, block products with irreversible external results:
  - Product or catalog real Amazon ASIN.
  - Catalog export history or export file/task id.
  - Amazon template output evidence.
  - A+ uploaded or upload-in-progress evidence.
- Do not clear `CatalogProduct.confirmed_at` unless the system can prove it is the controlled listing-generation pending state and not a pre-existing manual/export confirmation.
- Add a focused E5 helper rather than reusing auto-image reset semantics directly:
  - Example intent: `ensure_export_ready_projection_allowed(product, phase="listing_reserve|listing_success|auto_chain")`.
  - It should allow the current listing success to create `confirmed_at`.
  - It should block overwriting a pre-existing `confirmed_at` that did not come from the active listing run.
- E5 must not overwrite real ASIN, export history, manual confirmation, Amazon template outputs, or A+ evidence.

## API And Frontend Plan

- Backend options:
  - Preferred: add explicit routes for `retry_image_analysis` and `retry_listing_generation`, both using the existing `_queue_product_image_analysis()` / `_queue_product_listing_generation()` helpers and current workflow state checks.
  - Acceptable: map both actions to existing `retryStep(product.id)` only if backend workflow status/current_step guarantee the correct node and tests prove it.
- Frontend:
  - Add `retry_image_analysis` and `retry_listing_generation` handling in `ProductList.renderPrimaryRowAction()`.
  - Keep ProductList from inventing business rules; use `product.workflow.primary_action`.
  - Keep `export_ready` and `exported` split based on backend workflow/status plus catalog export evidence.
- Detail page:
  - If it already renders backend workflow consistently, no E5-specific UI change is required.
  - If retry actions appear on details later, use the same backend route/client function as ProductList.
- Task center:
  - No new task-center concept is needed; image/listing runs already use `task_runs/task_groups/task_steps/task_step_events`.

## Testing Strategy

### Structural / Project Rule Tests

- Assert `ProductListingGenerationAction.on_step_success()` is the only E5 path to `_project_listing_completed()`.
- Assert E5 code does not import or call export, A+, upload, Seller Central, TikTok, `BackgroundTasks`, raw thread, or direct worker entrypoints.
- Assert workflow failed actions exposed in `backend/app/product_tasks/workflow.py` are mapped in ProductList or intentionally hidden.
- Assert ProductList has explicit handling for `retry_image_analysis` and `retry_listing_generation` if workflow exposes them.

### DB Behavior Tests

- Image-analysis success creates one listing run and projects listing processing.
- Image-analysis repeated success with existing active listing run reuses it.
- Image-analysis success when product is already completed no-ops and keeps `flow_done/succeeded`.
- Listing success projects exactly `flow_done/succeeded`, `Product.status=completed`, `current_step=6`, and controlled `CatalogProduct.confirmed_at`.
- Listing failure does not set completed and exposes `listing_generation/failed`.
- Image/listing cancel and interrupted states do not set completed.
- Listing reserve/success blocks protected products with real ASIN, export history, template output, A+ evidence, or pre-existing manual `confirmed_at`.
- Downstream creation failure after image analysis is visible as a retryable listing failure, not a hidden succeeded state.

### API Samples

- `POST /api/products/{id}/retry-step` or explicit image/listing retry endpoints:
  - failed image analysis -> queues image run.
  - failed listing -> queues listing run.
  - processing state -> returns current product/task correlation or rejects with clear message.
  - completed product -> no automatic duplicate run.
- `GET /api/products?page=1&page_size=5`:
  - completed unexported rows show `export_ready`.
  - exported rows show `exported`.
- `GET /api/task-runs?correlation_key=product:{id}:listing_generation`:
  - shows the active or completed listing run for ProductList navigation.

### Commands

```bash
python -m compileall backend/app
make test-project-rules
<E5 DB behavior test command, once the accepted harness path is chosen>
cd frontend && npm run build
git diff --check
```

## Implementation Tasks

### Task 1: Lock Existing E5 Facts

- [ ] Read `backend/app/product_tasks/actions.py`, `backend/app/product_tasks/workflow.py`, `backend/app/api/products.py`, `frontend/src/pages/ProductList.tsx`.
- [ ] Add or update tests documenting current image/listing success and failed workflow facts.
- [ ] Run the tests and verify they fail only where E5 gaps exist.

### Task 2: Add E5 Protection Helper

- [ ] Add a focused helper for export-ready projection protection.
- [ ] Block real ASIN, export history, template output, A+ evidence, and pre-existing manual confirmation.
- [ ] Allow listing success to create controlled `confirmed_at`.
- [ ] Add tests for protected and allowed products.

### Task 3: Harden Image Success Downstream Creation

- [ ] Keep ProductTaskAction/planner creation only.
- [ ] Reuse active listing run.
- [ ] No-op for already completed products.
- [ ] Project downstream creation failure to a visible listing retry state.
- [ ] Add repeated-hook and active-run tests.

### Task 4: Harden Listing Completion

- [ ] Keep `_project_listing_completed()` as the only E5 completion projector.
- [ ] Ensure listing failure/cancel/interrupted never set completed.
- [ ] Ensure success does not create export/A+/upload tasks.
- [ ] Add tests for success/failure/cancel/interrupted.

### Task 5: Expose Safe Retry Actions

- [ ] Choose explicit routes or proven generic retry mapping.
- [ ] Backend must use existing queue helpers/planners.
- [ ] ProductList must map backend workflow actions without frontend business inference.
- [ ] Add project-rule tests to prevent ghost actions.

### Task 6: Verify End To End Locally

- [ ] Run compile and project-rule tests.
- [ ] Run E5 DB behavior tests.
- [ ] Run frontend build if ProductList/API client changes.
- [ ] Smoke product list, product detail, and task-center correlation on a safe local sample.
- [ ] Confirm no export/A+/upload/TikTok side effects.

## Gates

- 若命 reviews this E5 technical plan.
- 镜花 performs code review after implementation.
- 观止 performs QA on at least:
  - one safe product reaching `export_ready`;
  - one failure sample with retry reason/action;
  - one protected sample blocked;
  - ProductList, ProductDetail, and Task Center state consistency.

## Risks And Decisions Needed

- Test harness decision: current repo appears to rely heavily on `scripts/test_project_rules.py`; E5 should still get behavior tests. If no DB test harness is accepted, write `REQUEST / TEST_HARNESS_GAP` before replacing DB behavior with text-only assertions.
- `CatalogProduct.confirmed_at` has dual meaning today: export-ready evidence created by Listing success and protection evidence for pre-existing/manual confirmation. E5 implementation must make that distinction explicit before changing reserve/success behavior.
- Existing generic `retryStep` may be sufficient technically, but explicit `retry_image_analysis` / `retry_listing_generation` routes are clearer and reduce frontend action ambiguity.
- E5 can be implemented after E4 or tested with a mocked/safe upstream that sets image/listing prerequisites; it must not depend on real Amazon or real external VLM.
