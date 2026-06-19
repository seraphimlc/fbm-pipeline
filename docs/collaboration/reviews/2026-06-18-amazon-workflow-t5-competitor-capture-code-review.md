# Amazon Workflow T5 Competitor Capture Code Review

- Reviewer: 镜花（agentKey: `jinghua`）
- Time: 2026-06-18 CST
- Related inbox: `MSG-20260618-013`
- Conclusion: `CODE_REVIEW / NEEDS_FIX`

## Scope

- PRD / request: `docs/superpowers/specs/2026-06-18-amazon-product-workflow-prd.md` T5, `MSG-20260618-012`, `MSG-20260618-013`
- Code reviewed:
  - `backend/app/api/amazon_stylesnap.py`
  - `backend/app/task_planners/product_image_analysis.py`
  - `backend/app/product_tasks/actions.py`
  - `backend/app/pipeline/engine.py`
  - `backend/app/services/amazon_listing_capture.py`
  - `scripts/test_project_rules.py`
  - `docs/domain-index/product-flow.md`
- Not covered:
  - Page QA, real StyleSnap / Chrome capture, real product state changes, real task runs, exports, external platforms.

## Index Review

- Used indexes:
  - `docs/project-index.md`
  - `docs/domain-index/product-flow.md`
- Result:
  - `product-flow` correctly routes this review to Product Flow, StyleSnap API, product workflow PRD, and the competitor selection/capture chain.
  - T5 behavior was added to `docs/domain-index/product-flow.md`.
  - `docs/project-index.md` does not need an update because no top-level route/domain entry changed.

## Evidence

- Static review:
  - `backend/app/api/amazon_stylesnap.py:429` allows downstream re-selection for `image_analysis/*`, `listing_generation/*`, and `flow_done/succeeded`; only `flow_done/succeeded` calls the protected evidence gate there.
  - `backend/app/api/amazon_stylesnap.py:1286` only calls `_raise_if_protected_competitor_change()` when `switching` or `force_capture` is true.
  - `backend/app/api/amazon_stylesnap.py:1303` then rewrites selected competitor snapshot and workflow to `capture_competitor_detail/processing`.
  - `backend/app/api/amazon_stylesnap.py:1316` queues or reuses listing capture, and `backend/app/api/amazon_stylesnap.py:1330` can continue into image analysis after an already captured listing.
  - `backend/app/api/amazon_stylesnap.py:840` still commits inside `_sync_product_competitor_snapshot()`, so selection/workflow writes can be persisted before later capture/image-analysis work runs.
- Minimal function-level sample with a fake product object:
  - Given `listing_generation/succeeded`, same `competitor_asin`, and `ProductData.amazon_template_path` / template metadata present, `_ensure_select_competitor_workflow_allowed()` returned `allowed`.
- Verification commands observed for this review round:
  - `make backend-compile` passed.
  - `make test-project-rules` passed: `OK: 44 project rule test(s)`.
  - `git diff --check -- backend/app/api/amazon_stylesnap.py scripts/test_project_rules.py docs/domain-index/product-flow.md docs/collaboration/inbox.md` passed before this report.

## Findings

### P1 - Downstream same-competitor reselection bypasses protected evidence

`backend/app/api/amazon_stylesnap.py:429` and `backend/app/api/amazon_stylesnap.py:1286`

T5's approved boundary says downstream competitor changes may only touch current derived state, and must block when the product has real ASIN, manual confirmation, export history, Amazon template output evidence, or A+ upload evidence. The current implementation enforces that gate only for `flow_done/succeeded` at workflow-entry time, and later only when the selected ASIN changes or `force_capture=true`.

That leaves a bypass: if a product is already downstream, for example `listing_generation/succeeded`, has Amazon template output evidence, and the user re-selects the same ASIN with `force_capture=false`, `switching` is false. The endpoint passes `_ensure_select_competitor_workflow_allowed()`, skips `_raise_if_protected_competitor_change()`, rewrites the selected competitor snapshot, writes `capture_competitor_detail/processing`, and can queue or reuse detail capture. This silently rolls a protected downstream product back into T5 despite the protected evidence.

Fix requirement:

- Before any selected snapshot, workflow, capture, or image-analysis write, block downstream re-selection whenever protected evidence exists, regardless of whether the ASIN changes.
- Or narrow same-ASIN re-selection to explicitly safe workflow nodes that cannot already contain protected Amazon output/export/manual-confirmation evidence.
- Add a behavior test for the same-ASIN downstream case with Amazon template/export/manual-confirmation evidence: the endpoint/helper must return 409 and must not write workflow or selection state.

## Secondary Risk

- `_sync_product_competitor_snapshot()` commits inside the helper at `backend/app/api/amazon_stylesnap.py:840`. This is not the primary blocker by itself because the file already had helper-level commits, but T5 now uses that helper before capture queueing and before image-analysis startup. After the P1 gate is fixed, consider whether this split transaction boundary is acceptable for T5, or whether the endpoint/background entrypoint should own the commit boundary.

## Review Result

`CODE_REVIEW / NEEDS_FIX`

Do not submit this T5 change yet. 听云 should fix the protected same-ASIN downstream reselection path and add a targeted project-rule or backend behavior test for it, then return for mirror review.
