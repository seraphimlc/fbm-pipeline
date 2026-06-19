# Amazon Workflow T5 Competitor Capture Rereview

- Reviewer: 镜花（agentKey: `jinghua`）
- Time: 2026-06-19 CST
- Related inbox: `MSG-20260618-013`
- Conclusion: `CODE_REVIEW / PASS`

## Scope

- Rereview target: 听云对镜花 T5 P1 `NEEDS_FIX` 的修复。
- Code reviewed:
  - `backend/app/api/amazon_stylesnap.py`
  - `backend/app/task_planners/product_image_analysis.py`
  - `backend/app/product_tasks/actions.py`
  - `scripts/test_project_rules.py`
  - `docs/domain-index/product-flow.md`
- Not covered:
  - Page QA, real StyleSnap / Chrome capture, real product state changes, real task runs through UI, exports, external platforms.

## Index Review

- Used indexes:
  - `docs/project-index.md`
  - `docs/domain-index/product-flow.md`
- Result:
  - `product-flow` still correctly routes T5 review to Product Flow, StyleSnap API, product workflow PRD, and competitor selection/capture.
  - No additional top-level index update is needed for this rereview.

## Evidence

- Protected downstream reselection:
  - `backend/app/api/amazon_stylesnap.py:85` defines `COMPETITOR_DOWNSTREAM_RESELECT_WORKFLOWS` for `image_analysis/*`, `listing_generation/*`, and `flow_done/succeeded`.
  - `backend/app/api/amazon_stylesnap.py:438` now calls `_raise_if_protected_competitor_change(product)` for every downstream reselection workflow before returning allow.
  - `backend/app/api/amazon_stylesnap.py:1269` loads the product, then `backend/app/api/amazon_stylesnap.py:1272` runs the workflow/protected gate before candidate lookup, selected snapshot writes, workflow writes, capture queueing, or image-analysis startup.
- T5 flow boundaries:
  - `backend/app/api/amazon_stylesnap.py:1312` writes `capture_competitor_detail/processing` on selection.
  - `backend/app/api/amazon_stylesnap.py:1326` handles already captured detail and `backend/app/api/amazon_stylesnap.py:1340` starts image analysis through the existing planner.
  - `backend/app/api/amazon_stylesnap.py:1056` background capture writes `capture_competitor_detail/succeeded` then starts image analysis; failure and `CancelledError` write `capture_competitor_detail/failed` with matching capture/product error text.
  - `backend/app/api/amazon_stylesnap.py:1364` `capture-missing` only prefetches missing candidate detail and does not write product workflow.
  - `backend/app/api/amazon_stylesnap.py:1413` single-candidate capture only resumes main workflow for the current selected candidate in `capture_competitor_detail/failed`.
- Tests:
  - `scripts/test_project_rules.py:680` adds a structural guard for the downstream protected evidence check.
  - `scripts/test_project_rules.py:815` adds a fake-object sample for `listing_generation/succeeded + same competitor_asin + Amazon template output + Catalog confirmed/export evidence`, expecting 409 and unchanged workflow/snapshot.
- Verification commands:
  - `make test-project-rules` passed: `OK: 44 project rule test(s)`.
  - `make backend-compile` passed.

## Findings

No P0/P1 findings in this rereview.

## Residual Risk

- T5 still relies on FastAPI in-process `BackgroundTasks` for detail capture, so process-level loss can still strand a processing state. This was already a known boundary risk and is not newly introduced by the P1 fix.
- `_sync_product_competitor_snapshot()` still commits inside the helper. This remains a transaction-boundary cleanup candidate, not a blocker for the repaired protected-evidence path.
- This PASS is code review only. It is not QA PASS, real StyleSnap/Chrome validation, page acceptance, real export validation, or external-platform verification.
