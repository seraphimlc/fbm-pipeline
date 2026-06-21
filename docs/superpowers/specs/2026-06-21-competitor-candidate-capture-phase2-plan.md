# Competitor Candidate Capture Phase 2 Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement candidate competitor detail capture so the product workflow can move from visual Top candidates to `auto_select_competitor/pending` without mixing old runs, fake successes, or final ASIN writes.

**Architecture:** Keep `amazon_competitor_search_candidates` as the current candidate fact table. `execute_step()` only collects structured adapter results; `on_step_success()` writes candidate detail current facts and workflow progression in one transaction. Real Amazon access remains behind an explicit adapter/config gate and is not part of the first implementation phase.

**Tech Stack:** FastAPI, SQLAlchemy async ORM, MySQL startup schema ensure, ProductTaskAction task runtime, Product workflow projection, deterministic fixture adapter tests.

---

## Current Code Facts

- `ProductCompetitorCandidateCaptureAction` is currently a strict skeleton in `backend/app/product_tasks/actions.py`: `validate()` checks workflow and selected count, `reserve()` clears current capture/final facts and projects processing, `execute_step()` raises, and success projects failure.
- `amazon_competitor_search_candidates` already has Phase 1 detail fields: `detail_task_run_id`, `detail_task_step_id`, `detail_captured_at`, `brand`, `seller`, `category_rank`, `leaf_category`, `main_image_url`, `bullets_json`, `description`, `product_details_json`, `aplus_text`, `capture_status`, `capture_error`, `capture_raw_json`.
- Existing visual selection fields identify the source search run/step via `task_run_id` and `task_step_id`, and Top candidates via `visual_rank` plus `visual_selected_for_capture`.
- Existing fields do not explicitly record the visual-match task run/step that produced the current Top set. For Phase 2, that is insufficient for an auditable "current comparison set" boundary.
- `backend/app/services/amazon_listing_detail.py` has an unconfigured default adapter that never accesses Amazon, plus a fixture HTML adapter and parser.
- API/frontend retry entry points currently stop at competitor search and visual match; there is no candidate-capture retry API or button mapping.
- There is no backend DB behavior test harness covering this chain; `scripts/test_project_rules.py` is useful but cannot replace behavior tests for current-run selection and transaction semantics.

## Non-Negotiable Boundaries

- Do not trigger real Amazon, real VLM, real product task runs, or external platforms without a later explicit gate.
- Do not write `products.competitor_asin`, `catalog_products.competitor_asin`, snapshot final selected competitor, Step 10 output, Amazon templates, real ASIN confirmation state, A+, or export files.
- Do not make all-failure captures look successful.
- Do not read candidates by product history or in-memory filtering. The selected set must be DB-queryable by current run evidence.
- Do not expose `retry_auto_competitor_selection` in this phase.

## Data Contract

### Current Comparison Set

Phase 2 should harden the visual Top set before enabling capture:

- Add nullable fields to `AmazonCompetitorSearchCandidate`:
  - `visual_task_run_id`
  - `visual_task_step_id`
- Add MySQL ensure columns in `backend/app/database.py`.
- Add an index such as:
  - `ix_amz_comp_visual_capture_set(product_id, visual_task_run_id, visual_task_step_id, visual_selected_for_capture, visual_rank, id)`
- Update visual-match success writing so every row touched by the current visual run records `visual_task_run_id=step.task_run_id` and `visual_task_step_id=step.id`.
- Candidate capture must select from the latest successful `product_competitor_visual_match` run/step for this product correlation, not from product history:
  - `product_id = :product_id`
  - `visual_task_run_id = latest_visual_run.id`
  - `visual_task_step_id = latest_visual_step.id`
  - `task_run_id/task_step_id` still point to the source successful competitor-search run/step used by that visual match
  - `visual_selected_for_capture = 1`
  - `visual_rank IS NOT NULL`
  - order by `visual_rank ASC, id ASC`
  - expected size Top 4-6; allow 1-6 only when upstream produced fewer valid candidates

This makes the comparison set explicit and prevents old search runs, old visual results, and stale selected rows from entering detail capture.

### Capture Result Fields

On task success, write only current selected candidates from the resolved visual set:

- `detail_task_run_id`: current capture task run id
- `detail_task_step_id`: current capture task step id
- `detail_captured_at`: capture success timestamp
- `brand`, `seller`, `category_rank`, `leaf_category`, `main_image_url`
- `bullets_json`: JSON array of bullet strings
- `description`
- `product_details_json`: JSON object from detail page facts
- `aplus_text`
- `capture_status`: `succeeded` or `failed`
- `capture_error`: error type/message for per-candidate failure in a partial-success run
- `capture_raw_json`: normalized adapter result or sanitized failure diagnostics

Do not add detail-specific `price`, `rating`, or `review_count` fields in Phase 2. The search table already stores these from the search page, and the detail adapter result can preserve parsed detail-page values in `capture_raw_json`. Add dedicated detail price/rating fields later only if parser evidence shows materially different values are needed for scoring.

## Adapter Design

### Default Behavior

- `get_amazon_listing_detail_adapter()` must remain unconfigured by default.
- Fixture adapter is allowed for tests and local deterministic execution.
- No empty fake success is allowed. Missing fixture or unavailable real adapter is a typed failure, not success.

### Real Adapter Shape

Real Amazon capture should be a separate adapter, for example `BrowserAmazonListingDetailAdapter`, behind explicit config:

- `AMAZON_LISTING_DETAIL_ADAPTER=browser` or equivalent.
- `AMAZON_LISTING_DETAIL_TIMEOUT_SECONDS`, per-candidate timeout.
- `AMAZON_LISTING_DETAIL_MIN_DELAY_MS` / `MAX_DELAY_MS`, throttling between candidates.
- `AMAZON_LISTING_DETAIL_MAX_CANDIDATES`, default no more than 6.
- Optional existing browser/session service if one exists at implementation time; otherwise use a dedicated adapter boundary that returns HTML and never owns workflow state.

Error types must be structured:

- `adapter_not_configured`
- `blocked`
- `captcha`
- `timeout`
- `network_error`
- `parse_error`
- `not_found`
- `login_required`
- `unsupported_page_structure`
- `fixture_missing`

Real Amazon small-sample validation requires separate 若命/用户 authorization before enabling or running it. 观止 QA should review any real-browser evidence separately; fixture tests are not proof of production Amazon accessibility.

## Task Lifecycle

### `validate()`

- Load product and external-result protection reasons.
- Require `workflow_node == capture_competitor_candidates`.
- Allow only `workflow_status in {pending, failed}`.
- Resolve the latest successful visual-match run/step by correlation key `product:{product_id}:competitor_visual_match`.
- Query the selected set using `visual_task_run_id`, `visual_task_step_id`, `visual_selected_for_capture`, and `visual_rank`.
- Reject if zero selected candidates.
- Reject if selected set exceeds 6.
- Warn through run summary, not rejection, if fewer than 4 candidates exist because upstream may have had fewer valid candidates.

### `reserve()`

- Call `clear_current_competitor_capture(db, product_id, now=now)`.
- Call `clear_current_auto_competitor_selection(db, product_id, now=now, clear_product_fact=False)`.
- Project product to `capture_competitor_candidates/processing`.
- Do not write candidate detail fields here.

### `execute_step()`

- Re-resolve the selected visual set. Do not trust payload candidate ids.
- For each selected candidate, call the configured adapter with ASIN and URL.
- Update task-step progress and event diagnostics only.
- Return a structured result:
  - selected visual run/step ids
  - candidate ids
  - per-candidate status
  - normalized detail dict or structured error
  - quality warnings
- If all candidates fail, or no successful candidate has `title` or non-empty `bullets`, raise a typed task error with diagnostics in task events/run summary.
- Do not write `amazon_competitor_search_candidates` in `execute_step()`.

### `on_step_success()`

- Open one transaction with the task runtime session.
- Re-load product and selected candidate rows by the visual run/step evidence from the result.
- Verify the result candidate ids are still inside the selected set.
- Write success rows with detail fields and `capture_status="succeeded"`.
- In partial success, write failed selected candidates as `capture_status="failed"` with `capture_error` and sanitized `capture_raw_json`.
- Require at least one qualified success with `title` or non-empty `bullets`.
- Project the product through capture success and leave the persisted final workflow state as `auto_select_competitor/pending`.
- Do not create or run the auto-selection task in Phase 2.
- Do not write final ASIN fields.

### `on_step_failure()`

- Project product to `capture_competitor_candidates/failed`.
- Leave no current successful capture facts. Because `reserve()` already cleared current facts and `execute_step()` does not write candidate rows, all-failure diagnostics stay in task events/run summary.

### `on_step_interrupted()` and `on_cancel_requested()`

- Project product to `capture_competitor_candidates/failed` with a clear reason.
- Leave no current successful capture facts.
- Do not write per-candidate DB diagnostics unless a later separate design approves incremental diagnostic writes.

## Success and Quality Rules

- Minimum success: at least 1 selected candidate captures detail with `title` or non-empty `bullets`.
- Preferred success: 3 or more selected candidates have title/bullets, and at least one of the top 2 visual ranks succeeded.
- Partial success is allowed but must carry warnings in the task result summary, such as:
  - `partial_capture`
  - `top_rank_failed`
  - `low_success_count`
  - `missing_bullets`
- Overall all-failure is task failure, not a succeeded task with empty rows.
- A single weak success may move to `auto_select_competitor/pending`, but the next auto-selection phase must treat `successful_detail_count=1` as low-confidence input.

## API and Frontend Plan

Add the retry entry only after backend fixture/DB behavior is passing.

Backend route:

- Add `POST /api/products/{product_id}/competitor-candidate-capture/retry`.
- Response model: current `ProductResponse`.
- Allowed only when product workflow node is `capture_competitor_candidates`.
- If status is `processing`, return the current product workflow/task-center correlation without creating a new run.
- If status is `pending` or `failed`, call `create_product_competitor_candidate_capture_runs(db, [product.id], created_by="web", auto_start=True)`.
- Return 404 for missing product.
- Return 400 for wrong node/status or validation errors.
- Return 502 for task creation infrastructure failures.

Workflow action:

- For `capture_competitor_candidates/pending`, expose primary action `retry_competitor_candidate_capture`, label `抓取候选详情`.
- For `capture_competitor_candidates/failed`, expose primary action `retry_competitor_candidate_capture`, label `重试抓取详情`.
- For `processing`, continue to expose `open_task_center`.
- Keep `restart_competitor_search` as a secondary recovery action.
- Do not expose `retry_auto_competitor_selection`.

Frontend:

- Add API client helper `retryProductCompetitorCandidateCapture`.
- Add ProductList workflow action mapping for `retry_competitor_candidate_capture`.
- On click, call the retry API, refresh rows, and navigate to task center only if backend returns/keeps `open_task_center` correlation or if the existing UI pattern chooses to stay on list. Prefer task-center navigation after trigger for visibility.
- Button text comes from backend label, not hard-coded business rules.

## Implementation Phases

### Phase 2A: Backend Fixture Execution and Current-Set Contract

**Goal:** Replace skeleton failure with deterministic fixture-backed capture execution and DB behavior tests. No real Amazon, no API/frontend button.

**Files:**

- Modify: `backend/app/models/models.py`
- Modify: `backend/app/database.py`
- Modify: `backend/app/product_tasks/actions.py`
- Modify: `backend/app/services/amazon_listing_detail.py` only if adapter injection helpers are needed
- Test: `scripts/test_project_rules.py`
- Test: add a backend behavior test entry, for example `backend/tests/product_tasks/test_competitor_candidate_capture.py` or an equivalent isolated script if the project keeps avoiding pytest
- Docs: `docs/superpowers/specs/2026-06-19-amazon-auto-competitor-selection-prd.md`
- Docs: `docs/domain-index/product-flow.md`
- Docs: `docs/domain-index/task-runtime.md`

- [ ] Add `visual_task_run_id` / `visual_task_step_id` ORM fields and MySQL ensure columns.
- [ ] Add the current visual capture set index.
- [ ] Update visual-match success writing to record visual task run/step ids.
- [ ] Add helper `latest_successful_competitor_visual_match_ids(product_id)`.
- [ ] Add helper `current_visual_selected_for_capture(product_id)` returning exact rows, not just count.
- [ ] Rewrite candidate capture `validate()` to use exact selected rows.
- [ ] Rewrite `execute_step()` to call the configured adapter and return structured per-candidate results without candidate-table writes.
- [ ] Rewrite `on_step_success()` to write candidate detail fields in one transaction and progress to `auto_select_competitor/pending`.
- [ ] Keep failure/cancel/interrupted as no-current-success-fact projections.
- [ ] Add DB behavior tests for current run/step selection, old run exclusion, partial success, full failure, success hook transaction, cancel/interrupted cleanup, and no final ASIN writes.
- [ ] Keep project-rule tests as contract smoke, but do not rely on them as the only evidence.

**Verification:**

```bash
python -m compileall backend/app
make test-project-rules
python -m pytest backend/tests/product_tasks/test_competitor_candidate_capture.py -q
git diff --check
```

If pytest/dev dependencies are not yet part of the project, Phase 2A must either add a minimal dev test dependency document or provide an equivalent deterministic DB behavior script and command. Do not skip the behavior coverage.

**Review Gate:** 若命 review required. 镜花 design/code review recommended because this phase changes current-set evidence and transaction semantics. 观止 QA not required.

### Phase 2B: Retry API, Workflow Action, and Frontend Button

**Goal:** Let users start/retry candidate detail capture through the product workflow after Phase 2A is behavior-tested.

**Files:**

- Modify: `backend/app/api/products.py`
- Modify: `backend/app/product_tasks/workflow.py`
- Modify: `frontend/src/api/index.ts`
- Modify: `frontend/src/pages/ProductList.tsx`
- Test: `scripts/test_project_rules.py`
- Docs: `docs/domain-index/product-flow.md`
- Docs: `docs/domain-index/task-runtime.md`
- Docs: `docs/project-index.md` only if navigation/API routing guidance changes

- [ ] Add `POST /api/products/{product_id}/competitor-candidate-capture/retry`.
- [ ] Add processing bypass behavior matching visual-match retry.
- [ ] Expose `retry_competitor_candidate_capture` only for capture pending/failed.
- [ ] Add frontend API client helper.
- [ ] Add ProductList action mapping and loading behavior.
- [ ] Add project-rule coverage that the retry action is not exposed before the API/client mapping exists.
- [ ] Confirm `retry_auto_competitor_selection` remains absent.

**Verification:**

```bash
python -m compileall backend/app
make test-project-rules
cd frontend && npm run build
git diff --check
```

**Review Gate:** 若命 review required. 镜花 review recommended for workflow/API/frontend action mapping. 观止 QA required only if the button is manually verified in browser.

### Phase 2C: Real Amazon Adapter Gate and Small-Sample Validation

**Goal:** Add a real detail adapter path without making it the default and without treating external access as guaranteed.

**Files:**

- Modify or create: `backend/app/services/amazon_listing_detail.py` or a focused adapter module under `backend/app/services/`
- Modify: `backend/app/config.py` if config flags are introduced
- Test: adapter unit tests with saved HTML/error fixtures
- Docs: PRD and domain indexes

- [ ] Add explicit config for real adapter enablement, timeout, throttling, and max candidates.
- [ ] Implement browser or HTML-fetch adapter behind the existing `AmazonListingDetailAdapter` protocol.
- [ ] Map blocked/captcha/timeout/network/parse/not-found/login errors to structured `AmazonListingDetailError.error_type`.
- [ ] Add no-real-network tests using fixture HTML and fake blocked pages.
- [ ] Request separate 若命/用户 authorization before any real Amazon small sample.
- [ ] After authorization, run a tiny sample and record evidence separately for review; do not fold real Amazon availability into fixture test claims.

**Verification before real sample:**

```bash
python -m compileall backend/app
make test-project-rules
python -m pytest backend/tests/product_tasks/test_competitor_candidate_capture.py -q
git diff --check
```

**Real-sample Gate:** Requires explicit 若命/用户 authorization. 观止 QA recommended for evidence review. Do not make real adapter the production default until review accepts the evidence and operational risk.

## Recommended First Implementation Scope

Start with Phase 2A only.

Reason: Phase 2A removes the main correctness risk by making the current visual comparison set explicit and proving success/failure transaction behavior with deterministic data. API/frontend can wait until the backend no longer has skeleton semantics. Real Amazon access should remain a separately authorized gate because fixture success does not prove Amazon accessibility.

## Required Confirmations

暂无必须确认，以下真实 Amazon 小样本需另行授权：

- Whether 若命/用户 approve enabling a real Amazon detail adapter for a tiny sample.
- Which real adapter mechanism is acceptable at that time: existing browser service, a new browser adapter, or controlled HTML fetch.
- Whether 观止 should perform browser QA before the adapter can be enabled outside local authorized tests.

