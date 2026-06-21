# Auto Select Competitor E4 Product-Type Guard Rereview

- Reviewer: 镜花 (`jinghua`)
- Date: 2026-06-21 CST
- Message: `MSG-20260621-031`
- Node: `CODE_REVIEW_REREVIEW`
- Result: `PASS`

## Scope

This rereview only checked the `MSG-20260621-029` P1 blocker fixed by `MSG-20260621-030`: E4A scorer must not auto-select a clearly different product type when visual/detail/marketplace signals are high.

Reviewed:

- `backend/app/product_tasks/actions.py`
- `scripts/test_auto_competitor_selection_e4.py`
- `scripts/test_project_rules.py`
- Prior report: `docs/collaboration/reviews/2026-06-21-auto-select-competitor-e4-code-review.md`

Out of scope: page QA, real Amazon/VLM execution, API/frontend retry, E5, Listing/export/A+/TikTok, commit/push.

## Result

`CODE_REVIEW_REREVIEW / PASS`.

The previous P1 blocker is fixed. The scorer now adds `different_product_type_low_title_and_category_alignment` to `hard_rejects` before confidence qualification when source/candidate tokens exist and both `title_source_fit <= 0.35` and `category_alignment <= 0.25`. Because qualified candidates require `not item["hard_rejects"]`, the prior sofa vs office-chair反例 can no longer become `medium`.

## Evidence

- Guard location: `backend/app/product_tasks/actions.py:396`.
- Rejection reason: `different_product_type_low_title_and_category_alignment` is appended before score qualification.
- Qualification still excludes hard rejects at `backend/app/product_tasks/actions.py:464`.
- Local scorer check for source sofa vs office chair now returns:

```text
confidence='rejected'
score=0.747
hard_rejects=['different_product_type_low_title_and_category_alignment']
```

and `_score_auto_competitor_candidates()` raises instead of returning a selected `medium` candidate.

## Test Coverage

`scripts/test_auto_competitor_selection_e4.py` now includes `_test_different_product_type_rejected_without_final_write()`:

- Source product remains sofa / modular couch.
- Candidate is `Ergonomic office chair with adjustable arms`.
- Candidate keeps high visual score `0.99`, complete details, category, price/rating/reviews.
- The test asserts workflow fails at `auto_select_competitor/failed`, and no final write happens to:
  - `AmazonCompetitorSearchCandidate.final_selected`
  - `Product.competitor_asin`
  - `CatalogProduct.competitor_asin`
  - snapshot `selected_competitor`
- It also asserts no `product_image_analysis` downstream run is created for that product.

Existing positive and lifecycle coverage still runs: high success, medium success, low/insufficient failure, protection gate, old visual run exclusion, active run reuse, and downstream image creation failure.

## Verification

- `cd backend && python -m compileall -q app` PASS.
- `make test-project-rules` PASS, 56 tests.
- `cd backend && .venv/bin/python ../scripts/test_auto_competitor_selection_e4.py` PASS.
- `git diff --check` PASS.

## Boundary Check

No new E4 API/frontend retry, ProductList action, real Amazon/VLM execution, direct worker call from auto competitor selection, export, A+, TikTok, or E5 implementation was introduced by this fix.

## Residual Risk

The guard is still deterministic and heuristic. It handles the reviewed dual-low title/category mismatch class, not every possible semantic mismatch. That is acceptable for E4A because the gate only covers the previous blocker and the implementation still records risks for weaker medium cases.

## Gate Meaning

`PASS` means the `MSG-20260621-029` P1 product-type guard blocker is closed for E4A code/data/task-runtime review. It is not QA PASS and does not authorize real Amazon/VLM/product full-chain execution by itself.
