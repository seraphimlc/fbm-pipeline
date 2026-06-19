# Amazon Auto Image Selection Phase A Code Review

- Reviewer: 镜花（agentKey: `jinghua`）
- Time: 2026-06-19 CST
- Related inbox: `MSG-20260619-004`
- Conclusion: `CODE_REVIEW / NEEDS_FIX`

## Scope

- PRD / request:
  - `docs/superpowers/specs/2026-06-19-amazon-auto-image-selection-prd.md`
  - `MSG-20260619-003`
  - `MSG-20260619-004`
- Code reviewed:
  - `backend/app/product_tasks/actions.py`
  - `backend/app/product_tasks/auto_image_selection.py`
  - `backend/app/services/product_image_candidates.py`
  - `backend/app/services/product_image_vlm.py`
  - `backend/app/pipeline/step6_image.py`
  - `backend/app/product_tasks/workflow.py`
  - `backend/app/task_planners/product_auto_image_selection.py`
  - `backend/app/api/task_runs.py`
  - `backend/app/models/status.py`
  - `backend/app/models/models.py`
  - `backend/app/database.py`
  - `backend/app/api/schemas.py`
  - `scripts/test_project_rules.py`
  - `docs/domain-index/product-flow.md`
  - `docs/domain-index/task-runtime.md`
- Not covered:
  - Page QA, real VLM/StyleSnap/Chrome execution, real product state mutation, real exports, external platforms.

## Index Review

- Used indexes:
  - `docs/project-index.md`
  - `docs/domain-index/product-flow.md`
  - `docs/domain-index/task-runtime.md`
- Result:
  - Indexes route this review to Product Flow and Task Runtime correctly.
  - `product-flow` and `task-runtime` include the new automatic image selection entries.

## Evidence

- Static review:
  - `backend/app/product_tasks/actions.py:401` `ProductAutoImageSelectionAction.validate()` only loads the product.
  - `backend/app/product_tasks/actions.py:411` `reserve()` writes `auto_select_images/processing`, `status="created"`, and `current_step=1` without calling `_auto_image_selection_protection_reasons()`.
  - `backend/app/product_tasks/actions.py:467` calls the protection gate only in `on_step_success()`, after `execute_step()` has already run VLM work and after the task run has already reserved the product into processing.
  - `backend/app/product_tasks/actions.py:553`, `:563`, and `:573` failure/interrupted/cancel paths also project `auto_select_images/failed` without a protected-state gate.
- Minimal fake-object sample:
  - A product with `amazon_asin="B0REALASIN"` and existing `flow_done/succeeded` was passed to `ProductAutoImageSelectionAction.reserve()`.
  - Result: workflow became `auto_select_images/processing`, legacy status became `created`, and `current_step` became `1`.
- Verification commands:
  - `python -m compileall backend/app` passed.
  - `make test-project-rules` passed: `OK: 47 project rule test(s)`.
  - `git diff --check` passed.

## Findings

### P1 - Protected products can be moved into automatic image selection before the protection gate runs

`backend/app/product_tasks/actions.py:401` and `backend/app/product_tasks/actions.py:411`

The approved Phase A boundary says existing real ASIN, Catalog ASIN, manual confirmation, export history, Amazon template output, and A+ upload/uploading evidence must not be silently overwritten, and this stage must not advance real historical products. The current guard for those facts is only applied in `on_step_success()`.

That is too late. Creating or reusing a `product_auto_image_selection` run calls `reserve()`, which immediately writes the product to `auto_select_images/processing`, resets legacy status to `created`, and sets `current_step=1`. This happens even for products that already have protected external results. If the task is then canceled, interrupted, or fails before success projection, the product can be left in `auto_select_images/failed`. Even if success projection later blocks the destructive reset, the protected product has already had its workflow/status overwritten.

Minimum fix requirement:

- Move the protected evidence check into `validate()` and/or the beginning of `reserve()` so protected products cannot create/reuse an automatic image selection run or be written to `auto_select_images/processing`.
- Apply the same precondition consistently to retry/reuse paths, because `create_product_action_runs()` calls `reserve()` for existing active runs too.
- Add a behavior test with a protected product, for example real `Product.amazon_asin` or Catalog `confirmed_at/exported_at`, proving that automatic image selection creation/reserve is rejected and leaves workflow/status/current_step unchanged.
- Keep the existing `on_step_success()` protection as a final defense for races where protected evidence appears after reserve.

## Notes

- The shared `product_image_vlm` extraction keeps old Step6 and automatic image selection using separate prompts, which is the right direction; I did not find a blocker in that split during this pass.
- The action still duplicates reset/cleanup logic that also exists in `backend/app/api/products.py` and `backend/app/api/amazon_stylesnap.py`. This is a maintainability risk for a later cleanup, but the P1 above is the blocking issue.
- The current project-rule tests cover useful behavior, but they do not catch protected-product reserve/status overwrite.

## Review Result

`CODE_REVIEW / NEEDS_FIX`

Do not move Phase A forward yet. 听云 should fix the pre-reserve protection boundary and add the targeted behavior test, then return for mirror review.
