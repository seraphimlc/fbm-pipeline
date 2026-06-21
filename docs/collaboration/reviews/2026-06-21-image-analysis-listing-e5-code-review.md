# E5 Image Analysis -> Listing -> Export Ready Code Review

- Reviewer: 镜花 (`jinghua`)
- Time: 2026-06-21 22:32 CST
- Inbox: `MSG-20260621-033`
- Result: `CODE_REVIEW / PASS`

## Scope

Reviewed only E5 code/data/task-runtime behavior for:

- `product_image_analysis -> product_listing_generation`
- `listing_generation -> flow_done/succeeded -> Product.status=completed`
- E5 irreversible-result protection gate
- ProductList retry action mapping
- E5 DB behavior script and project-rule guard
- Related project/domain indexes

Out of scope: page QA, real Amazon/Seller Central/A+ upload, TikTok, real VLM/listing content quality, commit/push.

## Blocking Findings

None.

## Passed Checks

1. E5 protection gate blocks irreversible external results before image/listing action start and listing completion.
   Evidence: `backend/app/product_tasks/actions.py` defines `_e5_export_ready_protection_reasons()` / `_raise_if_e5_export_ready_protected()` and uses them in `ProductImageAnalysisAction.validate/reserve`, `ProductListingGenerationAction.validate/reserve`, and listing success projection. The helper delegates to `product_external_result_protection_reasons()` in `backend/app/services/product_protection.py`, which checks Product/Catalog ASIN, Catalog `confirmed_at`, export history, Amazon template output/file, and A+ uploaded/running state.

2. Controlled listing success can still write export-ready state.
   Evidence: `_project_listing_completed()` checks protection before writing, then sets `flow_done/succeeded`, `Product.status=completed`, and `CatalogProduct.confirmed_at = item.confirmed_at or now`. `scripts/test_image_analysis_listing_e5.py` covers listing success reaching completed/export-ready with previously empty `confirmed_at`.

3. Image-analysis success creates/reuses listing through task runtime, not a direct worker call.
   Evidence: `ProductImageAnalysisAction.on_step_success()` calls `create_product_action_runs(... self._listing_action_type() ...)`. `backend/app/task_planners/product_listing.py` also funnels listing creation through `create_product_action_runs()`.

4. Repeated success, completed no-op, and downstream listing-creation failure are visible.
   Evidence: image success has an `already_completed` branch for `flow_done/succeeded`; listing creation exceptions roll back and project `listing_generation/failed` with `downstream_failed`. The DB script covers create, reuse, completed no-op, and forced listing planner failure.

5. Listing failure/cancel/interrupted do not complete the product.
   Evidence: `ProductListingGenerationAction.on_step_success()` is the E5 ProductTaskAction path calling `_project_listing_completed()`; failure/interrupted/cancel call failure/paused projection helpers. The DB script verifies those modes leave `CatalogProduct.confirmed_at` empty and do not set completed.

6. ProductList retry actions consume backend workflow actions.
   Evidence: `backend/app/product_tasks/workflow.py` exposes `retry_image_analysis` / `retry_listing_generation`; `frontend/src/pages/ProductList.tsx` maps both to `retryStep(product.id)` and refreshes rows. No frontend business-state projection was added.

7. No E5 action-side export/upload/TikTok/naked-thread side effect found.
   Evidence: scoped scan of the image/listing action sections found no `create_catalog_export_tasks`, `run_amazon_template`, A+ upload invocation, Seller Central, TikTok, `BackgroundTasks`, `threading.Thread`, or `enqueue_pipeline()` usage. The only direct calls in the action execute steps are the expected `run_image_analysis()` and `run_listing()`.

8. Index updates match the implemented scope.
   Evidence: `docs/project-index.md`, `docs/domain-index/product-flow.md`, and `docs/domain-index/task-runtime.md` point to E5 entry files and behavior script without claiming export/upload/A+/TikTok execution.

## Non-blocking Risks

1. The E5 protection helper is a thin alias over the shared external-result protection helper. This is safe for current E5 because controlled success checks before writing `confirmed_at`, and the DB script covers that path. It does mean the "pre-existing confirmed_at vs controlled confirmed_at" distinction is enforced by call order, not by a richer domain token or run provenance.

2. "Listing success is the only completion path" is true for the E5 ProductTaskAction automatic main chain, not globally across the legacy API surface. Existing manual/old endpoints such as `confirm_product`, `resume_pipeline` pending-review completion, `run_single_step(step=6)`, and old pipeline engine completion still exist. I did not treat these as blockers because `MSG-20260621-033` is scoped to E5 and those are not newly introduced by this change.

3. `ProductListingGenerationAction.on_step_success()` and `_project_listing_completed()` both run the E5 protection check. This is redundant but not behaviorally unsafe.

4. The DB behavior script validates action hooks and DB state transitions, but it does not execute real `run_image_analysis()` / `run_listing()` or assess generated content quality. That remains outside this code review and belongs to later QA/real-sample validation if 若命 assigns it.

## Verification

- `cd backend && python -m compileall -q app` PASS
- `make test-project-rules` PASS, 57 project rule tests
- `cd backend && .venv/bin/python ../scripts/test_image_analysis_listing_e5.py` PASS
- `cd frontend && npm run build` PASS, only Vite chunk-size warning
- `git diff --check` PASS

## Gate Meaning

`CODE_REVIEW / PASS` means the scoped E5 code/data/task-runtime gate is acceptable for 若命's next scoped commit/push decision. It does not mean QA PASS, real external platform PASS, content-quality PASS, or permission to merge to `main`.
