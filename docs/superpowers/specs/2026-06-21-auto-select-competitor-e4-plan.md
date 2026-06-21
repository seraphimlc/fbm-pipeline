# Auto Select Competitor E4 Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement `auto_select_competitor` so the system chooses a final Amazon competitor from current search, visual, detail, and source-product facts, writes protected final facts, and creates or reuses image analysis.

**Architecture:** Keep `amazon_competitor_search_candidates` as the candidate/current-fact table and Product workflow as the business-state source. Use a deterministic rule scorer first; no real LLM/VLM scoring in E4. `execute_step()` computes a structured score result only, while `on_step_success()` performs the protected final write and downstream task creation in controlled ProductTaskAction lifecycle.

**Tech Stack:** FastAPI, SQLAlchemy async ORM, ProductTaskAction, task_runs/task_steps/task_step_events, Product workflow service, deterministic DB behavior script, React ProductList workflow actions if retry is exposed.

---

## Current Code Facts

- `ProductAutoCompetitorSelectionAction` exists in `backend/app/product_tasks/actions.py`, but it is still a strict skeleton: `validate()` checks product workflow and captured detail count, `reserve()` clears final current facts, `execute_step()` raises, and success projects failure.
- `clear_current_auto_competitor_selection()` clears `final_selected/final_*` rows. With `clear_product_fact=True`, it also clears `Product.competitor_asin`, `CatalogProduct.competitor_asin`, and snapshot `selected_competitor/auto_competitor_selection` after `product_external_result_protection_reasons()`.
- Phase 2A added `visual_task_run_id/visual_task_step_id` and made candidate capture write `detail_* / capture_*` facts only for the current visual set. E4 must reuse that current-set boundary.
- Candidate detail facts live in `amazon_competitor_search_candidates`: search fields, visual fields, `detail_task_run_id/detail_task_step_id`, `brand`, `seller`, `category_rank`, `leaf_category`, `main_image_url`, `bullets_json`, `description`, `product_details_json`, `aplus_text`, `capture_status`, `capture_raw_json`.
- Final selection fields already exist: `final_selected`, `final_rank`, `final_score`, `final_confidence`, `final_dimension_scores_json`, `final_reason`, `final_risks_json`, `final_model`, `final_rule_version`, `final_raw_json`, `final_selected_at`.
- `product_auto_competitor_selection` planner already delegates to `create_product_action_runs()`.
- `product_image_analysis` planner already exists and uses ProductTaskAction dedupe/correlation.
- Workflow currently hides `retry_auto_competitor_selection` and exposes `open_detail/restart_competitor_search` for `auto_select_competitor/failed`; ProductList has no mapping for `retry_auto_competitor_selection`.
- Protection helper blocks real Amazon ASIN, Catalog confirmation/export evidence, Amazon template output, and A+ evidence.

## Scope

### In Scope

- Resolve current comparison set from latest successful visual run/step plus captured detail facts.
- Score qualified candidates deterministically.
- Write final candidate facts to exactly one selected row.
- Write protected final competitor facts to Product, Catalog, and source snapshot.
- On success, create or reuse `product_image_analysis` through ProductTaskAction/planner.
- Add behavior tests for high-confidence success, low-confidence failure, facts missing, protection gate, old run exclusion, repeated trigger, and downstream task creation failure.
- Optionally expose backend/frontend retry action in a separate E4B sub-stage after backend behavior is stable.

### Out of Scope

- Real Amazon access.
- Real VLM/LLM scoring.
- Candidate detail fetching beyond existing Phase 2A facts.
- Listing generation, export, Amazon upload, A+, TikTok.
- Selecting a low-confidence candidate just to keep the chain moving.

## Input Facts

E4 reads:

- Product/source facts:
  - `products.id`, `products.competitor_asin`, `products.workflow_node/status/error`
  - `product_data.title`, `description`, `features`, `material`, `product_type`, dimensions, `gigab2b_raw_snapshot`
  - `product_images.main_image_path` only as evidence that upstream image selection exists, not for new VLM work
- Current search/visual/detail facts:
  - `amazon_competitor_search_candidates.product_id`
  - `task_run_id/task_step_id` for source search evidence
  - `visual_task_run_id/visual_task_step_id` for current comparison set
  - `visual_selected_for_capture=1`, `visual_rank`, visual score fields, visual reject fields
  - search facts: `asin`, `url`, `title`, `image_url`, `price`, `rating`, `review_count`, accessory/replacement/cover flags
  - detail facts: `capture_status=succeeded`, `detail_task_run_id/detail_task_step_id`, `brand`, `seller`, `category_rank`, `leaf_category`, `main_image_url`, `bullets_json`, `description`, `product_details_json`, `aplus_text`, `capture_raw_json`

Current set resolution:

- Find latest successful `product_competitor_visual_match` by `correlation_key = product:{id}:competitor_visual_match`.
- Select rows with that visual run/step, `visual_selected_for_capture=1`, `visual_rank IS NOT NULL`.
- Require `capture_status="succeeded"` for scoring.
- Exclude rows from older visual run/step even if their capture facts are still present.

## Scoring Rules

Use deterministic rules first, with explicit score components totaling 1.0.

Hard reject:

- Missing ASIN or URL.
- `capture_status != "succeeded"`.
- `visual_reject=1` or `visual_same_product_type=0`.
- Accessory/replacement/cover-only flags are set.
- Missing both candidate title and detail bullets.
- Product/category facts clearly indicate a different product type by simple blocked terms.
- Protection gate blocks writing final product facts.

Score dimensions:

- Visual fit, weight 0.35:
  - normalized `visual_similarity_score`
  - bonus for top visual ranks
  - penalty for visual warnings/reject reasons
- Title/source semantic fit, weight 0.20:
  - token overlap between source title/product type/material and candidate search/detail title
  - penalty for accessory/replacement terms
- Detail completeness, weight 0.15:
  - title present
  - bullets count
  - product details present
  - main image present
  - description/A+ available as small bonus
- Category/leaf alignment, weight 0.10:
  - source product type/category tokens overlap with `leaf_category/category_rank`
  - no penalty if source category is unavailable
- Marketplace evidence, weight 0.10:
  - rating/review count parseable and non-trivial
  - price present
  - no sponsored penalty beyond small risk note
- Stability and rank, weight 0.10:
  - lower visual rank and search rank are better
  - same-ASIN duplicate handled by unique row, not by multiplying score

Confidence:

- `high`: score >= 0.78 and no hard/major risk, at least 2 detail-success candidates in comparison set or top-1/top-2 detail candidate succeeds.
- `medium`: score >= 0.68 and no hard reject. E4 may select medium by default, but `final_risks_json` must include why not high.
- `low`: score < 0.68 or only one weak detail success. Fail the task with readable reason; do not write final competitor.

Default decision: allow `medium` and `high`, reject `low`. This avoids blocking on product choice while preserving low-confidence safety.

## Write Contract

On success, write one selected row:

- selected row:
  - `final_selected=1`
  - `final_rank=1`
  - `final_score`
  - `final_confidence`
  - `final_dimension_scores_json`
  - `final_reason`
  - `final_risks_json`
  - `final_model="rule_based_auto_competitor_v1"`
  - `final_rule_version="auto_competitor_selection_v1"`
  - `final_raw_json`
  - `final_selected_at=now`
- non-selected current rows:
  - `final_selected=0`
  - `final_rank` ordered by score if useful, or null outside current set
  - `final_*` rationale may be written for current set only if tests cover it; simplest implementation writes final details only to selected row
- Product:
  - `products.competitor_asin = selected.asin`
  - workflow moves to `image_analysis/processing` if downstream image task creation succeeds
- Catalog:
  - `catalog_products.competitor_asin = selected.asin` if catalog item exists or is synced by local helper
- Snapshot:
  - `product_data.gigab2b_raw_snapshot.selected_competitor`
  - `product_data.gigab2b_raw_snapshot.auto_competitor_selection`

Protection:

- Run `product_external_result_protection_reasons(product)` before clearing/writing final product facts.
- If blocked, task fails at `auto_select_competitor/failed`; no final row and no Product/Catalog/snapshot competitor overwrite.
- Do not write real Amazon ASIN, export fields, Amazon template evidence, or A+ fields.

## Task Lifecycle

### `validate()`

- Load product with data/images/catalog/files.
- Require `workflow_node == auto_select_competitor`.
- Allow `workflow_status in {pending, failed}`.
- Apply protection gate before clearing/writing final facts.
- Resolve current visual set and require at least one `capture_status="succeeded"` row.
- Reject if no qualified candidates after hard rejects.

### `reserve()`

- Clear existing final current facts with `clear_product_fact=True`.
- Project `auto_select_competitor/processing`.
- Do not write selected competitor yet.

### `execute_step()`

- Re-resolve current visual set.
- Score candidates in pure service/helper code.
- Return structured result:
  - visual run/step evidence
  - scored candidates
  - selected candidate id/asin
  - score dimensions
  - confidence
  - risks/warnings
- If low confidence, facts insufficient, or no qualified candidate, raise typed error with diagnostics.
- Do not write candidate rows or Product/Catalog/snapshot facts.

### `on_step_success()`

- Re-load current visual set by result visual run/step.
- Verify selected candidate id is inside current set and still `capture_status=succeeded`.
- Re-run protection gate.
- Write final facts and protected Product/Catalog/snapshot facts.
- Create or reuse `product_image_analysis` through planner/ProductTaskAction.
- If image task creation succeeds, final workflow should be `image_analysis/processing` because reserve of downstream task projects it.
- If image task creation fails, leave final competitor facts written but project `image_analysis/failed` with a clear retry path; do not pretend image analysis started.

### Failure / Cancel / Interrupted

- Project `auto_select_competitor/failed`.
- Clear final current facts with `clear_product_fact=False` on failure/cancel/interrupted, unless the task failed after final product write; for that case the implementation must preserve already-committed selected competitor and project downstream `image_analysis/failed` instead.
- Do not clear search/visual/detail facts.

## API And Frontend

Recommended staging:

- E4A backend behavior first:
  - Auto-start `product_auto_competitor_selection` from candidate capture success after Phase 2A data contract is accepted, or provide a backend-only deterministic script to create the run.
  - Do not expose frontend retry until backend behavior passes.
- E4B API/frontend:
  - Add `POST /api/products/{id}/auto-competitor-selection/retry`.
  - Expose `retry_auto_competitor_selection` only for `auto_select_competitor/pending|failed` after API and ProductList mapping exist.
  - `processing` continues to use `open_task_center`.
  - ProductList button text comes from backend workflow label.

If E4 implementation wants full automatic main flow, update `ProductCompetitorCandidateCaptureAction.on_step_success()` to create/reuse `product_auto_competitor_selection` after it projects/validates capture success. If that hook fails to create downstream task, project `auto_select_competitor/failed` with retry reason.

## Testing Strategy

Use a deterministic DB behavior script similar to `scripts/test_competitor_candidate_capture_phase2a.py`, plus project rules.

Required behavior coverage:

- High-confidence success:
  - current set has multiple successful detail rows
  - selected row gets `final_selected=1`
  - Product/Catalog/snapshot competitor facts are written
  - image analysis run is created or reused
- Medium-confidence success:
  - writes final facts with risk notes
- Low-confidence failure:
  - no final Product/Catalog/snapshot write
  - workflow `auto_select_competitor/failed`
- Facts insufficient:
  - missing successful detail rows fails
  - missing ASIN/title/bullets hard-rejects candidate
- Protection gate:
  - existing real ASIN/export/template/A+ evidence blocks writes
- Old run exclusion:
  - older visual/detail facts do not participate if not in latest visual run/step set
- Repeated trigger:
  - active run is reused
  - repeated success does not duplicate image-analysis active run
- Downstream creation failure:
  - final competitor facts are not lost
  - workflow lands at `image_analysis/failed` or an explicitly retryable downstream state

Commands:

```bash
cd backend && python -m compileall -q app
make test-project-rules
cd backend && .venv/bin/python ../scripts/test_auto_competitor_selection_e4.py
git diff --check
```

If E4B touches frontend:

```bash
cd frontend && npm run build
```

## Implementation Tasks

### Task 1: Scoring Service

- [ ] Add a focused rule scorer, preferably in `backend/app/product_tasks/actions.py` first or a new `backend/app/services/amazon_auto_competitor_selection.py` if the helper becomes large.
- [ ] Parse numeric rating/review/price safely.
- [ ] Parse `bullets_json`, `product_details_json`, and source product facts.
- [ ] Return deterministic score dimensions, confidence, reason, and risks.
- [ ] Add unit/behavior checks in the E4 deterministic script.

### Task 2: Current Set Resolution

- [ ] Reuse Phase 2A visual run/step helpers.
- [ ] Add helper returning current captured successful rows ordered by visual rank.
- [ ] Ensure old run rows are excluded.
- [ ] Add DB behavior test.

### Task 3: ProductTaskAction Lifecycle

- [ ] Rewrite `ProductAutoCompetitorSelectionAction.validate()`.
- [ ] Keep `reserve()` clearing only final current facts and projecting processing.
- [ ] Rewrite `execute_step()` to score only.
- [ ] Rewrite `on_step_success()` to write final facts, Product/Catalog/snapshot facts, and create/reuse image analysis.
- [ ] Harden failure/cancel/interrupted behavior.

### Task 4: Downstream Image Analysis Creation

- [ ] Use `create_product_action_runs()` or `create_product_image_analysis_runs()` only.
- [ ] Reuse active image-analysis run through existing dedupe.
- [ ] Project image-analysis task creation failure visibly.
- [ ] Add behavior test for success and forced failure.

### Task 5: Optional API/Frontend Retry

- [ ] Add route only after backend behavior passes.
- [ ] Add API client helper and ProductList action mapping.
- [ ] Update workflow failed/pending overrides to expose `retry_auto_competitor_selection`.
- [ ] Run frontend build.

### Task 6: Docs And Gates

- [ ] Update PRD/domain indexes if action/API/status semantics change.
- [ ] Run compile, project rules, E4 behavior script, diff check.
- [ ] Write `DONE_CLAIMED`; do not write PASS or commit.

## Gates And Risks

- 若命 should review this plan before implementation.
- 镜花 design/code review recommended because this writes final competitor facts and triggers image analysis.
- 观止 QA only after API/frontend or an end-to-end safe sample is available.
- Main risk: `CatalogProduct.confirmed_at` protection may block products already considered export-ready; E4 should treat that as protection failure, not override it.
- Main product risk: deterministic scoring can be conservative. Low-confidence failures are preferable to wrong competitor ASIN writes.
