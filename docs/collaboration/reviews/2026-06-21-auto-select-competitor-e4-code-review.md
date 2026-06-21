# Auto Select Competitor E4 Backend Code Review

- Reviewer: 镜花 (`jinghua`)
- Date: 2026-06-21 CST
- Message: `MSG-20260621-029`
- Node: `CODE_REVIEW`
- Result: `NEEDS_FIX`

## Scope

This review covered E4A backend code/data/task-runtime only:

- `backend/app/product_tasks/actions.py`
- `scripts/test_auto_competitor_selection_e4.py`
- `scripts/test_project_rules.py`
- `docs/domain-index/product-flow.md`
- `docs/domain-index/task-runtime.md`
- `docs/superpowers/specs/2026-06-21-auto-select-competitor-e4-plan.md`

Out of scope: page QA, real product task execution, real Amazon/VLM access, API/frontend retry, ProductList action changes, Listing/export/A+/TikTok, commit/push.

## Result

`CODE_REVIEW / NEEDS_FIX`.

The task lifecycle shape is mostly right: `execute_step()` scores only, `on_step_success()` rechecks current set before final writes, downstream image analysis is created through `create_product_action_runs(..., auto_start=False)`, and no E4 API/frontend retry or direct VLM/Amazon execution was found.

However, the scorer can still auto-select a clearly different product type as `medium` when visual/detail/marketplace signals are strong. Because E4 writes final ASIN and advances to image analysis, this is a blocking data-quality/safety issue.

## Findings

### P1 - Different-product candidates can pass as `medium` and be written as final competitor

Evidence:

- `backend/app/product_tasks/actions.py:359` computes title/source fit as `0.25 + overlap * 0.75`, so zero overlap still contributes `0.25`.
- `backend/app/product_tasks/actions.py:375` gives category alignment `0.0` for mismatched category tokens, but `backend/app/product_tasks/actions.py:411` and `backend/app/product_tasks/actions.py:413` only add risks for low title/category alignment.
- `backend/app/product_tasks/actions.py:422` allows any non-hard-rejected candidate with score `>= 0.68` to become `medium`.
- Hard rejects at `backend/app/product_tasks/actions.py:316` only cover missing facts, visual reject/type flag, accessory/replacement/cover, accessory terms, and missing title/bullets. They do not implement the E4 plan requirement to reject product/category facts that clearly indicate a different product type.

Concrete behavior check:

```bash
cd backend && .venv/bin/python - <<'PY'
from types import SimpleNamespace
from app.product_tasks.actions import _score_auto_competitor_candidates
from app.task_runtime.json_utils import json_dumps

product = SimpleNamespace(data=SimpleNamespace(
    title="Modern modular sofa with chaise storage",
    material="linen wood",
    product_type="modular sofa",
    description="A modular living room sofa with storage chaise.",
    features=json_dumps(["modular couch", "storage chaise", "linen upholstery"]),
    leaf_category=None,
))
row = SimpleNamespace(
    id=1, asin="B0CHAIRTEST", url="https://www.amazon.com/dp/B0CHAIRTEST",
    title="Ergonomic office chair with adjustable arms",
    image_url="https://images.example/chair.jpg", main_image_url="https://images.example/chair-main.jpg",
    price="$199.99", rating=4.8, review_count=1200, sponsored=False, search_rank=1,
    visual_task_run_id=10, visual_task_step_id=11, visual_rank=1,
    visual_similarity_score=0.99, visual_attribute_match_score=0.99, visual_title_match_score=0.99,
    visual_reject=False, visual_same_product_type=1, visual_reject_reason=None,
    is_accessory=0, is_replacement_part=0, is_cover_only=0, capture_status="succeeded",
    bullets_json=json_dumps(["Office chair for desk work", "Adjustable seat and arms", "Mesh back support"]),
    description="Detailed office chair listing copy.",
    product_details_json=json_dumps({"material": "mesh", "room": "office"}),
    aplus_text="Chair lifestyle detail text",
    category_rank="#12 in Office Chairs",
    leaf_category="Office Products > Furniture > Office Chairs",
)
print(_score_auto_competitor_candidates(product, [row])["selected"])
PY
```

Observed result:

```text
{'asin': 'B0CHAIRTEST', 'score': 0.747, 'confidence': 'medium', 'dimensions': {'title_source_fit': 0.25, 'category_alignment': 0.0, ...}, 'risks': ['limited_source_title_overlap', 'limited_category_alignment', ...], 'hard_rejects': []}
```

This violates the plan's hard-reject intent for clearly different product/category facts and can write a wrong final competitor through `on_step_success()`.

Minimum fix:

- Add an explicit deterministic guard before `medium` qualification. For example: if source product type/title tokens and candidate title/category tokens show a clear type mismatch, hard reject; or, at minimum, fail candidates when both `title_source_fit` and `category_alignment` are below the agreed floor even if visual/detail/marketplace evidence is high.
- Add DB behavior coverage in `scripts/test_auto_competitor_selection_e4.py` for a high-visual, detail-complete different-product candidate such as source sofa vs candidate office chair/table. Expected: task fails or candidate is hard-rejected, and no final Product/Catalog/snapshot competitor facts are written.

## Verified Good

- Current-set resolution uses latest successful visual run/step, selected visual rows, non-null visual rank, then filters `capture_status == "succeeded"` in a small current set.
- `execute_step()` does not write final DB facts; it returns structured scoring and progress only.
- `on_step_success()` checks result evidence, protection, current-set membership, and rescoring consistency before writing final facts.
- Failure/cancel/interrupted clear final selection facts with `clear_product_fact=False` and do not clear search/visual/detail facts.
- Downstream image analysis creation goes through ProductTaskAction via `create_product_action_runs()` with `auto_start=False`; `kick_task_runtime()` is only called when `auto_start=True`.
- Scoped boundary scan did not find new E4 API/frontend retry exposure, ProductList action changes, direct Amazon/VLM execution, export/A+/TikTok expansion, or direct worker calls from auto competitor selection.
- Domain indexes were updated to describe E4A backend behavior and still mark real retry/frontend/real image analysis as not enabled.

## Verification

- `cd backend && python -m compileall -q app` PASS.
- `make test-project-rules` PASS, 56 tests.
- `cd backend && .venv/bin/python ../scripts/test_auto_competitor_selection_e4.py` PASS.
- `git diff --check` PASS.

## Gate Meaning

`NEEDS_FIX` blocks scoped commit gate for E4A. It does not ask for QA, does not authorize real Amazon/VLM/product full-chain execution, and does not require API/frontend work. After the scorer guard and test are fixed, rerun the four verification commands above and request a focused rereview.
