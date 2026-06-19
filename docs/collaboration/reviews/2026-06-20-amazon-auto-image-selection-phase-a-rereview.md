# Amazon Auto Image Selection Phase A Rereview

- Reviewer: 镜花（agentKey: `jinghua`）
- Time: 2026-06-20 CST
- Related inbox: `MSG-20260619-004`
- Previous review: `docs/collaboration/reviews/2026-06-19-amazon-auto-image-selection-phase-a-code-review.md`
- Conclusion: `CODE_REVIEW / PASS`

## Scope

- Rereview target:
  - 听云 `DONE_CLAIMED` for `MSG-20260619-004`
  - Previous P1: protected products could be moved into `auto_select_images/processing` before protected evidence was checked.
- Code checked:
  - `backend/app/product_tasks/actions.py`
  - `backend/app/task_planners/product_auto_image_selection.py`
  - `scripts/test_project_rules.py`
  - `docs/project-index.md`
  - `docs/domain-index/product-flow.md`
  - `docs/domain-index/task-runtime.md`
- Not covered:
  - Page QA, real product task execution, real VLM/StyleSnap/Chrome, real exports, external platforms.

## Index Review

- Used indexes:
  - `docs/project-index.md`
  - `docs/domain-index/product-flow.md`
  - `docs/domain-index/task-runtime.md`
- Result:
  - Indexes correctly route automatic image selection review to Product Flow and Task Runtime.
  - Domain indexes mention `auto_select_images`, `product_auto_image_selection`, the planner, ProductTaskAction, candidate service, shared VLM service, and Phase A boundary.

## Evidence

- `backend/app/product_tasks/actions.py:141` `_auto_image_selection_protection_reasons()` covers:
  - product real Amazon ASIN,
  - product A+ uploaded/uploading state,
  - Catalog real ASIN,
  - Catalog `confirmed_at`,
  - Catalog export evidence,
  - Catalog A+ uploaded/uploading state,
  - Amazon template output evidence.
- `backend/app/product_tasks/actions.py:407` `ProductAutoImageSelectionAction.validate()` now loads the product and calls `_raise_if_auto_image_selection_protected(product)` before task creation proceeds.
- `backend/app/product_tasks/actions.py:418` `reserve()` repeats the same protected check before writing `status="created"`, `current_step=1`, or `auto_select_images/processing`.
- `backend/app/product_tasks/actions.py:475` keeps the success-projection protection gate as a final race defense.
- `backend/app/product_tasks/actions.py:1005` `create_product_action_runs()` calls `validate()` before looking up active runs, and `backend/app/product_tasks/actions.py:1018` calls `reserve()` on existing active runs, so the active-run reuse path is covered by the second guard.
- `scripts/test_project_rules.py:3021` covers real-ASIN protected `validate()` and `reserve()` rejection while preserving legacy status/current_step/workflow.
- `scripts/test_project_rules.py:3044` covers Catalog `confirmed_at/exported_at` protected `validate()` rejection and state preservation.
- Additional function-level sample covered Catalog `confirmed_at/exported_at` protected `reserve()` rejection and state preservation.

## Verification

```bash
python -m compileall backend/app
# PASS

make test-project-rules
# PASS: OK: 47 project rule test(s)

git diff --check
# PASS
```

Additional sample:

```bash
cd backend && .venv/bin/python - <<'PY'
# Catalog confirmed/exported product calls ProductAutoImageSelectionAction.reserve()
# with _load_product patched to an in-memory fake product.
PY
# catalog reserve protected: PASS
```

## Findings

No P0/P1 findings in this rereview.

The previous P1 is fixed: protected products are rejected before task creation can proceed and before reserve can project `auto_select_images/processing`; the existing active-run reuse path is also protected by the `reserve()` guard.

## Architecture Notes

- `backend/app/product_tasks/actions.py` still contains substantial domain reset/cleanup semantics for automatic image selection, image analysis, listing, competitor cleanup, and legacy compatibility. That duplication is not a current blocker, but the repeated protected evidence / reset / workflow projection pattern should be considered for a later domain service extraction if the same risk appears again.
- Current Phase A still does not exercise real VLM quality, default product creation flow, page behavior, or external platform effects. Those remain QA / later-phase validation concerns, not mirror code-review evidence.

## Review Result

`CODE_REVIEW / PASS`

This means the Phase A code gate passes for the reviewed scope. It does not mean QA PASS, user-path acceptance, real VLM quality acceptance, or external platform validation.
