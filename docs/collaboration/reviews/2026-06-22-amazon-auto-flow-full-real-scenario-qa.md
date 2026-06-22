# Amazon Auto Flow Full Real Scenario QA

Date: 2026-06-22 CST
Agent: 观止（agentKey: `guanzhi`）
Message: `MSG-20260622-052`, reruns `MSG-20260622-060`, `MSG-20260622-065`, `MSG-20260622-066`, and `MSG-20260622-068`
Result: `QA / BLOCKED / REAL_EXTERNAL_DEPENDENCY` as of `MSG-20260622-068`

## Scope

This QA checked the current Amazon product main flow from the user-visible workbench perspective:

- Product list `/products`: data source, `work_status` filters, row workflow/action.
- Product detail `/products/<id>`: workflow status/action and GET read-only material behavior.
- Task center `/task-runs`: related task evidence for running, succeeded and failed product tasks.
- Export center/API: `export_ready` and `exported` entry consistency.
- Behavior script for E5 image analysis -> listing -> export-ready.

Not triggered in this pass: real Amazon, Seller Central, A+ upload, TikTok publish, real export upload, real Amazon import creation, retry/start/cancel/wake clicks, or judgment of real VLM/listing content quality.

Authorization update after this pass: the user now allows real external platform calls and even full product-status reset, but forbids mocked interface calls or fake generated results. Therefore the staged-status evidence below is diagnostic only and must not be treated as final full-real-chain PASS evidence. The next full QA rerun should use real planner/action/task-runtime execution and real external adapter results, or report the real blocker if an external dependency cannot be reached.

## Conclusion

Final result after user-authorized staged-status rerun: `QA / NEEDS_FIX`.

The first pass was blocked by `SAMPLE_GAP`. The user then clarified that current DB rows are test data and authorized changing existing product statuses, while forbidding new test data/products. I reran the missing-stage UI/API coverage using existing source 1 products only, changing workflow status fields on products `1-16` and preserving the original snapshot in the evidence directory.

Later user clarification supersedes the external-call boundary: external platforms may be called for real, product statuses may be reset, and mocked/fake external results are not acceptable. That means this report remains useful for the ProductDetail consistency bug, but not as the final full-real-chain QA closure.

Covered paths are consistent for the current source 1 Amazon sample pool:

- `data_source_id=1` overview returned 200 with `export_ready=9`, `exported=7`, `failed=2`, `needs_initialization=92`.
- `work_status=export_ready` returned 9 rows; product `100 / W808P390791` is `flow_done/succeeded`, `work_status=export_ready`, action `open_detail`.
- `work_status=failed` returned 2 rows; products `94` and `93` expose `retry_image_analysis`.
- `work_status=exported` returned 7 rows and exported samples are read-only protected candidates.
- Product detail, task center and export center were reachable and aligned for sampled covered states.

However, the current test data does not contain enough safe samples to prove the full real-scenario chain requested by `MSG-20260622-052`. Missing in the current source 1 page/API sample pool:

- `auto_select_images`
- `competitor_searching`
- `select_competitor`
- `ready_to_generate`
- true page/API samples for visual-match succeeded and auto-competitor succeeded
- real ASIN protection sample
- A+ uploading/uploaded protection sample

I did not manually rewrite product workflow fields to fabricate these states, and I did not click retry/start to create new tasks because the current QA target asks to judge the current real test data rather than make unrelated samples fit the PASS criteria.

## Environment

- Backend: `http://127.0.0.1:8190`
- Frontend: `http://127.0.0.1:3190`
- Health: `GET /api/health` -> 200, `{"status":"ok","version":"0.1.0"}`
- Frontend `/products`: HTTP 200
- Evidence directory: `tmp/qa-evidence-20260622-full-real-scenario/`

## Cases Covered

- `TC-SMOKE-001`
- `TC-SMOKE-002`
- `TC-SMOKE-003`
- `TC-PAGE-002`
- `TC-PAGE-003`
- `TC-PAGE-004`
- `TC-PAGE-005`
- `TC-API-DATA-001`
- `TC-API-DATA-002`
- `TC-API-DATA-004`
- `TC-DATA-SEED-001`
- `TC-DATA-SEED-002`
- `TC-E5-001`
- `TC-E5-002`
- `TC-E5-003`
- `TC-TASK-003`
- `TC-TASK-006`
- `TC-ARTIFACT-002`
- `TC-EXPORT-001`
- `TC-EXPORT-003`
- `TC-PROTECTION-001`
- `TC-PROTECTION-002`
- `TC-PROTECTION-003`
- `TC-DATA-SAFETY-001`
- `TC-EXTERNAL-GATE-001`
- `TC-EXTERNAL-GATE-002`

Blocked by sample gap:

- `TC-AUTO-FLOW-001`
- `TC-AUTO-IMAGE-001`
- `TC-COMPETITOR-SEARCH-001`
- `TC-VISUAL-MATCH-001`
- `TC-CANDIDATE-CAPTURE-001`
- `TC-AUTO-COMPETITOR-001`
- `TC-IMAGE-ANALYSIS-001`
- `TC-LISTING-001`
- `TC-FLOW-FAILURE-001` beyond existing image/listing failed samples
- real ASIN / A+ upload protection cases

## API Evidence

### Source 1 Overview

`GET /api/products/overview?data_source_id=1`:

- HTTP 200
- time `9.601583s`
- `total_products=110`
- `needs_initialization=92`
- `capture_detail=0`
- `ready_to_generate=0`
- `running=0`
- `export_ready=9`
- `export_ready_unexported=9`
- `export_ready_exported=7`
- `failed=2`

Evidence:

- `tmp/qa-evidence-20260622-full-real-scenario/api/products-overview-source1.json`
- `tmp/qa-evidence-20260622-full-real-scenario/api/products-overview-source1.meta`

### Product List Filters

All below are `data_source_id=1`.

- `work_status=needs_initialization`: HTTP 200, total 92. Sample rows include `95`, `92`, `101`, all with action `open_detail`.
- `work_status=failed`: HTTP 200, total 2. Products `94` and `93` expose `retry_image_analysis`.
- `work_status=export_ready`: HTTP 200, total 9. Products `100`, `99`, `90`, `91`, `104`, `103`, `98`, `97`, `96`.
- `work_status=exported`: HTTP 200, total 7. Products `102`, `106`, `107`, `108`, `110`, `109`, `105`.
- `work_status=capture_detail`: HTTP 200, total 0 for source 1.
- `work_status=ready_to_generate`: HTTP 200, total 0 for source 1.
- `work_status=running`: HTTP 200, total 0 for source 1.
- `work_status=select_competitor`: HTTP 200, total 0 for source 1.

Unsupported status guards:

- `work_status=stale_running` -> 400
- `work_status=manual_review` -> 400
- `work_status=unknown_status` -> 400

Evidence:

- `tmp/qa-evidence-20260622-full-real-scenario/api/products-source1-*.json`
- `tmp/qa-evidence-20260622-full-real-scenario/api/products-source1-*.meta`

### Product Details

Sample details returned 200:

- Product `100`: `status=completed`, `work_status=export_ready`, action `open_detail`.
- Product `99`: `status=completed`, `work_status=export_ready`, action `open_detail`.
- Product `94`: `status=failed`, `work_status=failed`, action `retry_image_analysis`, correlation `product:94:image_analysis`.
- Product `93`: `status=failed`, `work_status=failed`, action `retry_image_analysis`, correlation `product:93:image_analysis`.
- Product `102`: `status=completed`, `work_status=exported`, action `open_detail`.
- Product `106`: `status=completed`, `work_status=exported`, action `open_detail`.
- Product `121`: `work_status=capture_detail`, correlation `product:121:competitor_candidate_capture`, but it is not part of source 1 and does not close the source 1 full-chain sample gap.

Evidence:

- `tmp/qa-evidence-20260622-full-real-scenario/api/product-100.json`
- `tmp/qa-evidence-20260622-full-real-scenario/api/product-94.json`
- `tmp/qa-evidence-20260622-full-real-scenario/api/product-121.json`
- Other sampled product files in the same directory.

### Task Center Evidence

- Task `47`: `product_listing_generation`, `succeeded`, correlation `product:100:listing_generation`, one succeeded step with 4 events.
- Task `49`: `product_image_analysis`, `failed`, correlation `product:94:image_analysis`, failed step has readable VLM timeout / no-result error.
- Task `80`: `product_competitor_candidate_capture`, `running`, correlation `product:121:competitor_candidate_capture`, but this is not a source 1 sample.
- Task list total 12. Several queued image/listing runs point to product IDs `286/283/280/175/174` that are not valid product detail samples in current API, so they were not used as product-page QA samples.

Task diagnostic list filters:

- `display_status=stale_running` -> 400 with detail-only diagnostic message.
- `display_status=waiting_dependency` -> 400.
- `display_status=planned` -> 400.

Evidence:

- `tmp/qa-evidence-20260622-full-real-scenario/api/task-run-47.json`
- `tmp/qa-evidence-20260622-full-real-scenario/api/task-run-49.json`
- `tmp/qa-evidence-20260622-full-real-scenario/api/task-run-80.json`
- `tmp/qa-evidence-20260622-full-real-scenario/api/task-runs-all-page1.json`

### Export Entry

Catalog pending/exported APIs returned 200:

- Pending export catalog total 9, item codes match the source 1 `export_ready` product set.
- Exported catalog total 7, item codes match source 1 `exported` product set.

Evidence:

- `tmp/qa-evidence-20260622-full-real-scenario/api/catalog-pending.json`
- `tmp/qa-evidence-20260622-full-real-scenario/api/catalog-exported.json`

## Browser Evidence

Screenshots:

- `tmp/qa-evidence-20260622-full-real-scenario/screenshots/products-export-ready.png`
- `tmp/qa-evidence-20260622-full-real-scenario/screenshots/products-failed.png`
- `tmp/qa-evidence-20260622-full-real-scenario/screenshots/products-capture-detail.png`
- `tmp/qa-evidence-20260622-full-real-scenario/screenshots/product-100-detail.png`
- `tmp/qa-evidence-20260622-full-real-scenario/screenshots/product-94-detail.png`
- `tmp/qa-evidence-20260622-full-real-scenario/screenshots/product-121-detail.png`
- `tmp/qa-evidence-20260622-full-real-scenario/screenshots/task-runs-121-correlation.png`
- `tmp/qa-evidence-20260622-full-real-scenario/screenshots/export-center.png`

Browser event file:

- `tmp/qa-evidence-20260622-full-real-scenario/browser-events.json`

Observed page timings in browser automation:

- product list `export_ready`: 14.065s
- product list `failed`: 16.723s
- product list `capture_detail`: 26.122s
- product detail `100`: 6.271s
- product detail `94`: 33.346s
- product detail `121`: 2.603s
- task center correlation page: 1.324s
- export center: 1.557s

No `/api` 4xx/5xx was captured by browser automation. One non-API console 404 was observed on the first product list page.

## Material Read-Only Check

Sample product: `101 / W808P390792`

Material dir: `data/products/GIGA/US/W808P390792`

Procedure:

1. Hash and file-count material directory.
2. Call `GET /api/products/101` twice.
3. Hash and file-count the same directory again.

Result:

- before count: 7
- after count: 7
- no hash diff output

Evidence:

- `tmp/qa-evidence-20260622-full-real-scenario/material-101-before.sha256`
- `tmp/qa-evidence-20260622-full-real-scenario/material-101-after.sha256`
- `tmp/qa-evidence-20260622-full-real-scenario/material-101-before.count`
- `tmp/qa-evidence-20260622-full-real-scenario/material-101-after.count`

## Behavior Script

Command:

```bash
cd backend && .venv/bin/python ../scripts/test_image_analysis_listing_e5.py
```

Result:

```text
E5 image analysis -> listing -> export_ready behavior checks passed
```

Side effect note: the script creates deterministic `E5_TEST_*` rows during execution and cleans them up. After completion, `GET /api/products/752` and `GET /api/products/753` returned 404, and global `work_status=export_ready` returned 9 rows again.

## Findings

### Superseded Initial Blocker: SAMPLE_GAP

Severity: Superseded by user-authorized existing-product status staging

Current source 1 test data does not contain safe page/API samples for the earlier automatic chain stages:

- automatic image selection
- competitor search
- visual match
- select competitor
- ready to generate
- real ASIN protection
- A+ upload protection

Impact:

- I can verify stable source 1 export-ready/failed/exported states and E5 behavior-script logic.
- I cannot honestly claim the full current real-scenario chain from automatic image selection through auto competitor selection into E5 has passed on current page/API samples.

Expected unblock:

- Provide or create, under 若命/user-approved test-data rules, a safe staged sample matrix for the missing work statuses.
- Alternatively authorize a scoped test-data seeding/backfill script whose only purpose is to create reversible QA samples for each stage.

### Performance Risk: overview/list/detail calls are slow

Severity: P2 / performance risk

Observed:

- `GET /api/products/overview` all-data after cleanup: 8.652s.
- `GET /api/products/overview?data_source_id=1`: 9.602s.
- Product list browser pages took 14-26s to reach network idle.
- Product detail `94` browser page took 33.346s to network idle.

Impact:

- The covered pages eventually render and APIs return 200.
- This does not block functional QA by itself, but it is slow enough to affect repeated QA and user perception.

## Side Effects

Allowed side effects used:

- Read-only API calls.
- Browser screenshots.
- Local material file hashing.
- E5 deterministic behavior script, which created temporary `E5_TEST_*` test rows and cleaned them up.
- User-authorized status staging on existing source 1 products `1-16`: only `products.workflow_node`, `workflow_status`, `workflow_error`, `workflow_updated_at`, and `updated_at` were changed.

Forbidden side effects avoided:

- No retry/start/cancel/wake clicks.
- No new Amazon export task.
- No Amazon/Seller Central/A+ upload/TikTok publish.
- No real ASIN overwrite.
- No new product rows, task rows, ASIN evidence, A+ upload evidence, export evidence, or external-result fabrication.
- No historical artifact overwrite.

## Rerun: User-Authorized Existing-Product Status Samples

User instruction at rerun time: existing DB data is test data; I may change existing product statuses, but must not create new test data. I staged existing source 1 products `1-16` only by changing workflow state fields.

Later user instruction: external platforms may be called for real and product statuses may be reset; mocked calls and fake generated results are forbidden. Treat this section as staged UI/API diagnosis, not full-real-chain proof.

Evidence:

- Before snapshot: `tmp/qa-evidence-20260622-full-real-scenario/staged-samples-before.json`
- API summary: `tmp/qa-evidence-20260622-full-real-scenario/api/staged-summary.json`
- API payloads: `tmp/qa-evidence-20260622-full-real-scenario/api/staged-products-source1-*.json`, `tmp/qa-evidence-20260622-full-real-scenario/api/staged-product-*.json`
- Screenshots: `tmp/qa-evidence-20260622-full-real-scenario/screenshots/staged/`
- Browser events: `tmp/qa-evidence-20260622-full-real-scenario/browser-events-staged.json`

Staged sample matrix:

| Product | Item code | Staged workflow | API work_status |
|---:|---|---|---|
| 1 | `N726P248345Y` | `auto_select_images/pending` | `auto_select_images` |
| 2 | `W1019138605` | `auto_select_images/processing` | `running` |
| 3 | `W1019P165868` | `auto_select_images/succeeded` | `select_competitor` |
| 4 | `W1019P263557` | `search_competitor/processing` | `competitor_searching` |
| 5 | `W1019P289651` | `search_competitor/pending` | `select_competitor` |
| 6 | `W1019P326440` | `search_competitor/failed` | `select_competitor` |
| 7 | `W1019P326446` | `visual_match_competitors/processing` | `competitor_searching` |
| 8 | `W1019P352615` | `visual_match_competitors/pending` | `select_competitor` |
| 9 | `W1019P352638` | `visual_match_competitors/succeeded` | `capture_detail` |
| 10 | `W1019P352663` | `capture_competitor_candidates/pending` | `capture_detail` |
| 11 | `W1019P352739` | `capture_competitor_candidates/processing` | `capture_detail` |
| 12 | `W1019P352906` | `capture_competitor_candidates/succeeded` | `ready_to_generate` |
| 13 | `W1019P363878` | `auto_select_competitor/pending` | `select_competitor` |
| 14 | `W1019P449193` | `auto_select_competitor/processing` | `select_competitor` |
| 15 | `W1019P454419` | `auto_select_competitor/succeeded` | `ready_to_generate` |
| 16 | `W2563P156283` | `listing_generation/pending` | `ready_to_generate` |

API rerun result:

- `GET /api/products/overview?data_source_id=1` returned 200 and consistent staged counts: `needs_initialization=76`, `auto_select_images=1`, `competitor_searching=2`, `select_competitor=6`, `capture_detail=3`, `ready_to_generate=3`, `running=1`, `export_ready=9`, `exported=7`, `failed=2`.
- Each staged `work_status` list returned HTTP 200 and only rows with matching `workflow.work_status`.
- Product detail APIs for products `1-16`, `93`, `94`, `100`, and `102` returned HTTP 200 and the expected `workflow.stage`, `stage_status`, `work_status`, `primary_action`, and `related_correlation_key`.
- Browser screenshot pass found no `/api` 4xx/5xx.

### P1: Product Detail UI Ignores New Workflow State

Affected page: `/products/<id>`

Code evidence:

- `frontend/src/pages/ProductDetail.tsx` still derives the stepper from `product.status`, `current_step`, image facts, competitor ASIN, image analysis, and listing content.
- The page renders `pipelineSteps` through Ant `Steps` without consuming `product.workflow.work_status`, `workflow.stage`, or `workflow.stage_status`.
- By contrast, `frontend/src/pages/ProductList.tsx` uses `product.workflow?.work_status` first, so list filters and overview agree with the API.

Reproduction:

1. Use existing staged product `16 / W2563P156283`.
2. API: `GET /api/products/16` returns `workflow.stage=listing_generation`, `stage_status=pending`, `work_status=ready_to_generate`, `primary_action=open_task_center`.
3. Product list `/products?work_status=ready_to_generate` shows product `16` under `待自动生成`, total 3.
4. Product detail `/products/16` still shows the first step as active and the top alert says `待确认商品图片`, which contradicts the API workflow.

Additional affected staged samples:

- Product `1` API says `auto_select_images/pending`, but detail page still shows old image-confirmation state.
- Product `9` API says `visual_match_competitors/succeeded -> capture_detail`, but detail page still shows old image-confirmation state.

Impact:

- The workbench list, overview, and backend detail API are aligned, but the detail page misleads the operator about the current automated workflow node.
- This violates `MSG-20260622-052` detail-page consistency requirements and blocks `PASS_WITH_SCOPE`.

Expected fix:

- Product detail should render the main workflow stepper/status/action from `product.workflow` when present.
- Legacy `status/current_step` inference should be fallback-only for rows without workflow projection.
- After fixing, rerun staged product details for at least products `1`, `9`, `16`, plus existing `93/94/100/102`.

## MSG-20260622-060 Rerun: Real External Boundary

Result: `QA / BLOCKED / REAL_EXTERNAL_DEPENDENCY`.

This rerun used the new `MSG-20260622-057/060` authorization: real planner/action/task runtime and real external adapter only; no mock interface calls, no fixture adapter, no fake external result. The previous ProductDetail display P1 is already covered by `MSG-058` QA rerun and `MSG-059` code review, so this rerun focused on whether the main Amazon product chain can truly advance under real external boundaries.

Evidence directory:

- `tmp/qa-evidence-20260622-real-external-rerun/`

### Test Matrix Summary

| Case | Target | Sample / entry | Actual | Result | Evidence |
|---|---|---|---|---|---|
| TC-060-ENV | Services and current data | backend `8190`, frontend `3190`, source 1 | health and pages reachable; APIs slow but returned 2xx | PASS | `api/products-overview-source1-before.json`, browser screenshots |
| TC-060-SAMPLE | Find safe real sample | products with main image and no irreversible external facts | product `92 / W808P389332` chosen; no real ASIN, no export, no confirmed catalog, no A+ upload; has main image | PASS_WITH_NOTE | `db/safe-main-image-candidates.json`, `db/product-92-db-before-reset.json` |
| TC-060-RESET | Authorized reset | product `92` | workflow reset from empty legacy state to `search_competitor/pending`; old `competitor_asin` retained; no ASIN/export/A+ facts changed | PASS | `db/product-92-reset-operation.json`, `api/product-92-after-reset-before-trigger.json` |
| TC-060-SEARCH | Real planner/action/task runtime | `POST /api/products/92/competitor-search/retry` | task run `746` created, correlation `product:92:competitor_search`; product entered `search_competitor/processing` | PASS | `api/product-92-competitor-search-trigger-response.json`, `api/task-runs-product-92-competitor-search-poll-*.json` |
| TC-060-EXTERNAL | Real Amazon search adapter | task run `746`, step `752` | runtime failed with `AmazonSearchPageError: adapter_not_configured`; message says real Amazon search requires explicit browser authorization | BLOCKED | `api/task-run-746-final.json` |
| TC-060-PAGE | Page/API/task visibility | `/products/92`, `/task-runs?run_id=746`, `/export-center` | product detail shows retryable Amazon search failure; task center shows failed run; browser captured no API 4xx/5xx | PASS_FOR_VISIBILITY | `screenshots/product-92-detail.png`, `screenshots/task-run-746-detail.png`, `browser-events.json` |
| TC-060-EXPORT | Export entry unchanged | pending/exported catalog APIs | pending total remains 9; exported total remains 7; product 92 did not enter export-ready | PASS | `api/catalog-pending-after-task.json`, `api/catalog-exported-after-task.json` |

### Sample Product

- Product: `92 / W808P389332`
- Source: `data_source_id=1`
- Selection reason: existing test data with `images.main_image_path`, no real Amazon ASIN, no catalog export, no catalog confirmed row, no A+ upload evidence.
- Caveat: it has legacy `competitor_asin=B0DHS4FYCL`; this was retained and not treated as a real Amazon ASIN or irreversible external publication result.

### State Reset List

Only product `92` was reset.

Before:

- `status=step5_listing`
- `current_step=6`
- `workflow_node=null`
- `workflow_status=null`
- `amazon_asin=null`
- `catalog_exported_at=null`
- `catalog_confirmed_at=null`
- `aplus_upload_status=not_uploaded`
- `main_image_path` present

After reset:

- `status=created`
- `current_step=2`
- `workflow_node=search_competitor`
- `workflow_status=pending`
- `workflow_error=null`
- `competitor_asin` retained

Evidence:

- `tmp/qa-evidence-20260622-real-external-rerun/db/product-92-reset-operation.json`

### Task Run / External Result

- Trigger: `POST /api/products/92/competitor-search/retry`
- Task run: `746`
- Step: `752`
- Task type: `product_competitor_search`
- Correlation key: `product:92:competitor_search`
- Runtime path: official API -> ProductTaskAction -> task runtime; no fixture or mock adapter used.
- Result: `failed`
- External blocker: `AmazonSearchPageError: Amazon search page adapter is not configured; real Amazon search requires explicit browser authorization`

Product final state:

- `status=failed`
- `current_step=2`
- `workflow_node=search_competitor`
- `workflow_status=failed`
- `work_status=select_competitor`
- `primary_action=retry_competitor_search`

Evidence:

- `tmp/qa-evidence-20260622-real-external-rerun/api/task-run-746-final.json`
- `tmp/qa-evidence-20260622-real-external-rerun/api/product-92-after-task-final.json`

### Page / API / DB / Artifact Evidence

Page evidence:

- `tmp/qa-evidence-20260622-real-external-rerun/screenshots/product-92-detail.png`
- `tmp/qa-evidence-20260622-real-external-rerun/screenshots/task-run-746-detail.png`
- `tmp/qa-evidence-20260622-real-external-rerun/screenshots/export-center.png`
- `tmp/qa-evidence-20260622-real-external-rerun/browser-page-summaries.json`
- `tmp/qa-evidence-20260622-real-external-rerun/browser-events.json`

API evidence:

- `tmp/qa-evidence-20260622-real-external-rerun/api/product-92-before-reset.json`
- `tmp/qa-evidence-20260622-real-external-rerun/api/product-92-after-reset-before-trigger.json`
- `tmp/qa-evidence-20260622-real-external-rerun/api/product-92-competitor-search-trigger-response.json`
- `tmp/qa-evidence-20260622-real-external-rerun/api/product-92-after-task-final.json`
- `tmp/qa-evidence-20260622-real-external-rerun/api/task-run-746-final.json`
- `tmp/qa-evidence-20260622-real-external-rerun/api/products-overview-source1-after-task.json`
- `tmp/qa-evidence-20260622-real-external-rerun/api/catalog-pending-after-task.json`
- `tmp/qa-evidence-20260622-real-external-rerun/api/catalog-exported-after-task.json`

DB evidence:

- `tmp/qa-evidence-20260622-real-external-rerun/db/product-flow-counts.json`
- `tmp/qa-evidence-20260622-real-external-rerun/db/products-with-main-image.json`
- `tmp/qa-evidence-20260622-real-external-rerun/db/safe-main-image-candidates.json`
- `tmp/qa-evidence-20260622-real-external-rerun/db/product-92-db-before-reset.json`
- `tmp/qa-evidence-20260622-real-external-rerun/db/product-92-reset-operation.json`

Artifact / product output:

- No Amazon import, no new export file, no A+ output, no TikTok output, and no Seller Central publication was generated.
- Evidence artifacts are QA screenshots/API/DB JSON only under `tmp/qa-evidence-20260622-real-external-rerun/`.

### Write Side Effects

Allowed writes performed:

- Product `92` workflow reset to `search_competitor/pending`.
- Product `92` official competitor search trigger created task run `746`.
- Task run `746` was manually woken via `POST /api/task-runs/746/wake` after it stayed queued during polling; this added a task action event.
- Runtime executed step `752`, failed on the real Amazon search adapter boundary, and projected product `92` to retryable `search_competitor/failed`.

Forbidden writes avoided:

- No mock/fixture result.
- No fake search candidates.
- No visual-match/candidate-detail/auto-competitor/image-analysis/listing downstream fabrication.
- No Amazon import/export generation.
- No Seller Central, A+ upload, TikTok publish, real ASIN overwrite, historical export overwrite, or template artifact overwrite.

### Findings

#### BLOCKER: Real Amazon search adapter is not configured

Severity: `BLOCKED / REAL_EXTERNAL_DEPENDENCY`

The first real external boundary in the full chain, Amazon competitor search, cannot execute in this environment. The code path uses `UnconfiguredAmazonSearchPageAdapter`, and the actual task runtime failure confirms:

`Amazon search page adapter is not configured; real Amazon search requires explicit browser authorization`

Impact:

- The chain cannot honestly prove `automatic image selection -> competitor search -> visual match -> candidate detail -> auto competitor -> image analysis -> listing -> export_ready`.
- This is not a mockable gap under `MSG-060`; using fixture HTML or fake candidates would violate the QA boundary.

Next owner:

- 若命 to decide whether to provide real browser/Amazon adapter authorization and environment.
- 听云 to implement/configure the real Amazon search adapter path if this is expected to run unattended.

#### P2: Runtime did not auto-pick the new run until wake

Task run `746` stayed `queued` during the first polling window after `auto_start=True`; `POST /api/task-runs/746/wake` caused it to run and expose the external adapter blocker.

Impact:

- Not the final blocker in this run, because the run was traceable and recoverable.
- Worth follow-up if automatic progression is expected without task-center wake.

Next owner:

- 听云 if 若命 decides this is a task runtime reliability issue, not just local startup/runtime state.

### Uncovered

Blocked by real external dependency:

- Real Amazon search candidate capture.
- Real visual initial screening after real search candidates.
- Real candidate detail fetch.
- Real auto competitor selection based on real detail facts.
- Real image analysis after auto competitor selection.
- Real Listing generation after image analysis.
- Real `flow_done/succeeded` projection from this sample.
- New export-ready row from this full chain sample.

Still out of scope by `MSG-060` even if the main chain later passes:

- A+ auto trigger/upload.
- TikTok flow.
- Seller Central upload/publication.
- Human final operation review.

## MSG-20260622-065 S4 Rerun: After Code Gate

Result: `QA / BLOCKED / REAL_EXTERNAL_DEPENDENCY`.

This rerun was executed after 镜花 `CODE_REVIEW_REREVIEW / PASS_WITH_SCOPE` for the `empty_results` evidence fix. It used the same existing safe sample as `MSG-060`, product `92 / W808P389332`, and triggered the official API path only. No mock, fixture, cached HTML, manual DB success write, export, Seller Central upload, A+ upload, TikTok publish, or external write operation was used.

Evidence directory:

- `tmp/qa-evidence-20260622-s4-after-code-gate/`

### S4 Test Matrix

| Case | Target | Sample / entry | Actual | Result | Evidence |
|---|---|---|---|---|---|
| TC-065-ENV | Local backend and adapter config | `GET /api/health`, settings snapshot | backend returned 200; adapter config remained `AMAZON_SEARCH_PAGE_ADAPTER=unconfigured`, `AMAZON_SEARCH_ENABLE_REAL_BROWSER=false` | PASS_FOR_ENV | `api/health.json`, `db/before-trigger-db-summary.json` |
| TC-065-SAMPLE | Existing safe sample reuse | product `92 / W808P389332` | product existed, had no `amazon_asin`, no catalog export item in product API, A+ status `not_uploaded`; it was already in retryable `search_competitor/failed` from `MSG-060` | PASS_WITH_NOTE | `api/product-92-before-trigger.json`, `db/before-trigger-db-summary.json` |
| TC-065-TRIGGER | Official API retry path | `POST /api/products/92/competitor-search/retry` | HTTP 200; product moved to `competitor_searching`, `search_competitor/processing` | PASS | `api/product-92-competitor-search-retry-response.raw`, `api/product-92-competitor-search-retry-response.json` |
| TC-065-RUNTIME | Runtime auto execution to adapter boundary | poll without `POST /api/task-runs/755/wake` | task run `755` was created and automatically executed; DB/logs show step `761` was claimed by runtime and failed at Amazon search adapter boundary | PASS_FOR_RUNTIME_BOUNDARY | `api/task-runs-product-92-poll-1.json`, `api/task-run-755-detail.json`, `db/after-task-db-summary.json` |
| TC-065-EXTERNAL | Real Amazon search adapter boundary | run `755`, step `761` | failed with `AmazonSearchPageError: Amazon search page adapter is not configured; real Amazon search requires explicit browser authorization` | BLOCKED | `api/task-run-755-detail.json`, `db/after-task-db-summary.json` |
| TC-065-CANDIDATES | Candidate landing | product `92` candidate table | candidate count stayed `0`; no real Amazon candidates landed | BLOCKED_EXPECTED | `db/after-task-db-summary.json` |
| TC-065-FINAL-STATE | Product workflow/status | `GET /api/products/92` after run | product final state is `status=failed`, `workflow.stage=search_competitor`, `workflow.stage_status=failed`, `work_status=select_competitor`, primary action `retry_competitor_search` | PASS_FOR_TRACEABLE_FAILURE | `api/product-92-after-task-final.json` |

### Product / Trigger / Task Facts

- Product: `92 / W808P389332`
- Trigger command: `POST http://127.0.0.1:8190/api/products/92/competitor-search/retry`
- Trigger response: HTTP 200
- New task run: `755`
- New task step: `761`
- Task type: `product_competitor_search`
- Correlation key: `product:92:competitor_search`
- Query count observed in progress event: `3`
- Runtime wake: not used in this rerun. First poll already showed run `755` as `failed`.

Task runtime evidence:

- API detail: `tmp/qa-evidence-20260622-s4-after-code-gate/api/task-run-755-detail.json`
- DB detail: `tmp/qa-evidence-20260622-s4-after-code-gate/db/after-task-db-summary.json`
- Observed server log excerpt in terminal:
  - `[TaskRuntime] scheduling runner task`
  - `[TaskRuntime] runner claimed step: ... run_id=755 step_id=761 step_type=product_competitor_search`
  - `[TaskRuntime] step failed: step_id=761 type=product_competitor_search`
  - `AmazonSearchPageError: Amazon search page adapter is not configured; real Amazon search requires explicit browser authorization`

### Final Product / Candidate State

Before S4 trigger:

- `status=failed`
- `current_step=2`
- `workflow_node=search_competitor`
- `workflow_status=failed`
- `workflow_error=自动竞品搜索失败: adapter_not_configured: Amazon search page adapter is not configured; real Amazon search requires explicit browser authorization`
- candidate summary: `total=0`
- latest prior run: `746`, step `752`, both failed from `MSG-060`

After S4 trigger:

- `status=failed`
- `current_step=2`
- `workflow_node=search_competitor`
- `workflow_status=failed`
- `workflow_error=自动竞品搜索失败: adapter_not_configured: Amazon search page adapter is not configured; real Amazon search requires explicit browser authorization`
- API workflow: `stage=search_competitor`, `stage_status=failed`, `work_status=select_competitor`, `primary_action=retry_competitor_search`
- candidate summary: `total=0`, `latest_task_run_id=null`, `latest_task_step_id=null`

### Evidence Paths

API evidence:

- `tmp/qa-evidence-20260622-s4-after-code-gate/api/health.json`
- `tmp/qa-evidence-20260622-s4-after-code-gate/api/product-92-before-trigger.json`
- `tmp/qa-evidence-20260622-s4-after-code-gate/api/task-runs-product-92-before.json`
- `tmp/qa-evidence-20260622-s4-after-code-gate/api/product-92-competitor-search-retry-response.raw`
- `tmp/qa-evidence-20260622-s4-after-code-gate/api/product-92-competitor-search-retry-response.json`
- `tmp/qa-evidence-20260622-s4-after-code-gate/api/task-runs-product-92-poll-1.json`
- `tmp/qa-evidence-20260622-s4-after-code-gate/api/task-run-755-detail.json`
- `tmp/qa-evidence-20260622-s4-after-code-gate/api/product-92-after-task-final.json`

DB evidence:

- `tmp/qa-evidence-20260622-s4-after-code-gate/db/before-trigger-db-summary.json`
- `tmp/qa-evidence-20260622-s4-after-code-gate/db/after-task-db-summary.json`

Adapter page evidence:

- Configured path from settings: `data/task_evidence/amazon_search_page`
- This path did not exist after the S4 run because the active adapter was `unconfigured`; execution failed before any real Chrome/Amazon page navigation or parser evidence could be produced.
- This is acceptable for the S4 `REAL_EXTERNAL_DEPENDENCY` conclusion because the blocker is typed, readable and traceable through task run `755`, step `761`, DB events and API state. It is not a real Amazon page success or page-level blocker such as captcha/bot check.

Screenshots/log files:

- No screenshots were captured in this S4 rerun.
- Backend log was observed from the temporary uvicorn terminal session but not separately persisted as a file.

### S4 Write Side Effects

Allowed writes performed:

- Product `92` official retry API was triggered.
- New task run `755`, task group `764`, task step `761` and events `637-639` were created.
- Product `92` briefly moved to `competitor_searching/search_competitor/processing`, then back to retryable `search_competitor/failed`.

Forbidden writes avoided:

- No fake candidates.
- No fixture/cache/evidence replay.
- No manual DB success mutation.
- No Amazon import/export generation.
- No Seller Central upload, A+ upload, TikTok publish, real ASIN overwrite, or historical export overwrite.

### S4 Conclusion

`MSG-20260622-065` cannot pass as `QA / PASS_WITH_SCOPE` because no real Amazon candidates landed and the product did not advance to the next workflow node.

The correct conclusion is `QA / BLOCKED / REAL_EXTERNAL_DEPENDENCY`: the official API and task runtime path worked and automatically reached the Amazon search adapter boundary, but the runtime still used the fail-closed unconfigured adapter. The blocking error is typed and traceable:

`AmazonSearchPageError: Amazon search page adapter is not configured; real Amazon search requires explicit browser authorization`

Residual risks:

- This rerun does not prove real Chrome authorization, Amazon search parsing, captcha/bot-check handling, empty-results page evidence, candidate landing, visual match, detail capture, auto-competitor, image analysis, listing generation, or export-ready transition.
- Since the adapter did not reach a real Amazon page, there is no new page-level evidence file under `data/task_evidence/amazon_search_page`.
- Product `92` remains a retryable failed test sample; repeated retry will keep failing until real browser adapter config/authorization is provided.

## MSG-20260622-066 - Real Chrome Adapter Authorized S4 Rerun

Date/time: 2026-06-22 CST

Conclusion: `QA / BLOCKED / REAL_EXTERNAL_DEPENDENCY`.

This rerun used the user-authorized real Chrome adapter path. It cannot be `PASS_WITH_SCOPE` because no real Amazon candidates landed and product `92` did not advance to the next workflow node. It is not `NEEDS_FIX` because the official API created the task, task runtime auto-executed the step, the active adapter was `ChromeAmazonSearchPageAdapter`, the adapter reached an Amazon search URL, and the blocker is typed and traceable with run/step/query evidence.

### Environment Snapshot

- Backend: temporary QA uvicorn process on `http://127.0.0.1:8190`; 8190 was not listening before this QA run.
- Runtime env from process `75023`:
  - `AMAZON_SEARCH_PAGE_ADAPTER=chrome`
  - `AMAZON_SEARCH_ENABLE_REAL_BROWSER=true`
  - `AMAZON_SEARCH_EVIDENCE_DIR=../tmp/qa-evidence-20260622-s4-real-chrome/amazon-search-page`
- Health: `GET /api/health` returned 200, `{"status":"ok","version":"0.1.0"}`.
- Evidence root: `tmp/qa-evidence-20260622-s4-real-chrome/`.
- Note: a separate one-off Python settings probe without the uvicorn inline env still showed `.env` defaults; the authoritative runtime config for this run is the uvicorn process env above plus the adapter evidence file showing `adapter=ChromeAmazonSearchPageAdapter`.

### Product And Trigger

- Product: `92 / W808P389332`.
- Trigger API: `POST /api/products/92/competitor-search/retry`.
- Trigger response: HTTP 200; product moved to `competitor_searching` with action `open_task_center`.
- API evidence:
  - `tmp/qa-evidence-20260622-s4-real-chrome/api/competitor-search-retry-response.json`
  - `tmp/qa-evidence-20260622-s4-real-chrome/api/product-92-before.json`
  - `tmp/qa-evidence-20260622-s4-real-chrome/api/product-92-after.json`

### Task Runtime Evidence

- Task run: `756`
  - `task_type=product_competitor_search`
  - `correlation_key=product:92:competitor_search`
  - `status=failed`
  - `started_at=2026-06-22 17:44:05`
  - `finished_at=2026-06-22 17:44:14`
- Task step: `762`
  - `step_key=product:92:competitor_search`
  - `step_type=product_competitor_search`
  - `status=failed`
  - `error_message=AmazonSearchPageError: Amazon search page blocked or unsupported: region_page`
- Task events:
  - `640`: start step
  - `641`: progress, `item_code=W808P389332`, `query_count=3`
  - `642`: error, `AmazonSearchPageError: Amazon search page blocked or unsupported: region_page`
- Backend log observed in the temporary uvicorn session:
  - runtime scheduled runner task
  - runner claimed `run_id=756 step_id=762 step_type=product_competitor_search`
  - step failed with `AmazonSearchPageError: Amazon search page blocked or unsupported: region_page`
- API/DB evidence:
  - `tmp/qa-evidence-20260622-s4-real-chrome/api/task-runs-product-92-competitor-search.json`
  - `tmp/qa-evidence-20260622-s4-real-chrome/api/task-run-756.json`
  - `tmp/qa-evidence-20260622-s4-real-chrome/db/after.json`

### Product Final State And Candidates

- Final product DB state:
  - `status=failed`
  - `workflow_node=search_competitor`
  - `workflow_status=failed`
- Final product API state:
  - `status=failed`
  - `primary_action=retry_competitor_search`
  - `action_reason=自动竞品搜索失败: region_page: Amazon search page blocked or unsupported: region_page`
- Candidate landing:
  - `amazon_competitor_search_candidates` count for product `92`: `0`
  - candidate sample: empty

### Adapter Evidence

- Page evidence file: `tmp/qa-evidence-20260622-s4-real-chrome/amazon-search-page/run-756/step-762/query-1.json`
- Adapter: `ChromeAmazonSearchPageAdapter`
- Query: `cabinet adjustable freestanding mdf bathroom`
- Amazon URL: `https://www.amazon.com/s?k=cabinet+adjustable+freestanding+mdf+bathroom&language=en_US&ref=nb_sb_noss`
- Page title: `Amazon.com : cabinet adjustable freestanding mdf bathroom`
- Classification/error type: `region_page`
- Error message: `Amazon search page blocked or unsupported: region_page`
- DOM summary existed and recorded `html_length=2536888`, body text sample, and `result_count_hint=48`.

### Error Type

`region_page` is a real external/page-structure boundary for this QA run. The browser reached Amazon and collected page evidence, but the adapter classified the page as blocked/unsupported for the current real search flow and failed closed without candidate landing.

### Write Side Effects

Allowed writes performed:

- Official retry API was triggered for product `92`.
- New task run `756`, task group `765`, task step `762`, and task events `640-642` were created.
- Product `92` briefly moved to processing and then returned to retryable failed state.

Forbidden writes avoided:

- No mock, fixture, cache HTML, old evidence replay, or manual DB success mutation.
- No new test product.
- No Amazon import/export generation.
- No Seller Central upload, A+ upload, TikTok publish, real ASIN overwrite, or external write operation.

### Residual Risks

- This QA does not prove real candidate parsing/landing, visual match, detail capture, auto-competitor selection, image analysis, listing generation, or export-ready transition.
- This QA does not prove behavior after resolving the `region_page` boundary; a later rerun could hit captcha, bot check, rate limit, unsupported structure, empty results, or parser behavior.
- The page evidence for this classification does not include `finished_at` or `candidate_count` fields; it is still traceable by `task_run_id=756`, `task_step_id=762`, `query_index=1`, URL, page title, DOM summary, and typed error.

## MSG-20260622-068 - Real Chrome S4 Rerun After Region False-Positive Fix

Date/time: 2026-06-22 CST

Conclusion: `QA / BLOCKED / REAL_EXTERNAL_DEPENDENCY`.

This rerun used the same official API and existing safe sample after the `region_page` false-positive fix passed focused code review. The previous false positive did not reproduce: the new adapter evidence has `classification=null`, not `region_page`, even though the page still contains Amazon delivery/navigation text and `result_count_hint=48`. The chain still cannot be `PASS_WITH_SCOPE` because no real Amazon candidates landed and product `92` did not advance to the next workflow node. The current blocker is typed and traceable as `empty_results`.

### Environment Snapshot

- Backend: temporary QA uvicorn process on `http://127.0.0.1:8190`; port 8190 was not listening before this QA run.
- Runtime process: PID `17373`.
- Runtime env from process snapshot:
  - `AMAZON_SEARCH_PAGE_ADAPTER=chrome`
  - `AMAZON_SEARCH_ENABLE_REAL_BROWSER=true`
  - `AMAZON_SEARCH_EVIDENCE_DIR=../tmp/qa-evidence-20260622-s4-after-region-fix/amazon-search-page`
- Health: `GET /api/health` returned 200, `{"status":"ok","version":"0.1.0"}`.
- Evidence root: `tmp/qa-evidence-20260622-s4-after-region-fix/`.
- Startup log note: startup DB maintenance/backfills/recovery/runtime kick were disabled, but the retry API still scheduled and ran the task runtime automatically for the new run.

### Product And Trigger

- Product: `92 / W808P389332`.
- Trigger API: `POST /api/products/92/competitor-search/retry`.
- Trigger response: HTTP 200; product moved to `competitor_searching`, workflow `search_competitor/processing`, action `open_task_center`.
- No `POST /api/task-runs/761/wake` was used.

### Task Runtime Evidence

- Task run: `761`
  - `task_type=product_competitor_search`
  - `title=自动竞品搜索：商品 #92`
  - `correlation_key=product:92:competitor_search`
  - `created_by=web`
  - `status=failed`
  - `created_at=2026-06-22 18:08:31`
  - `started_at=2026-06-22 18:08:33`
  - `finished_at=2026-06-22 18:08:47`
- Task group: `770`, `group_key=competitor_search`, `status=failed`.
- Task step: `767`
  - `step_key=product:92:competitor_search`
  - `step_type=product_competitor_search`
  - `status=failed`
  - `attempt_count=1`
  - `progress_total=3`
  - `started_at=2026-06-22 18:08:32`
  - `finished_at=2026-06-22 18:08:46`
  - `error_message=AmazonSearchPageError: Amazon search returned no recognizable natural results`
- Task events:
  - `651`: status, `开始执行 step`
  - `652`: progress, `开始自动竞品搜索`, data includes `item_code=W808P389332`, `product_id=92`, `query_count=3`
  - `653`: error, `AmazonSearchPageError: Amazon search returned no recognizable natural results`
- Backend log observed from the temporary uvicorn session:
  - `[TaskRuntime] scheduling runner task`
  - `[TaskRuntime] runner claimed step: worker_id=task-runtime-cc135ad2 run_id=761 step_id=767 step_type=product_competitor_search`
  - Chrome workflow released browser slot for `amazon_search query_index=1`
  - `[TaskRuntime] step failed: step_id=767 type=product_competitor_search`
  - stack trace raised `AmazonSearchPageError("empty_results", "Amazon search returned no recognizable natural results")`
  - `[TaskRuntime] runner drain finished: worker_id=task-runtime-cc135ad2 claimed=1`

### Product Final State And Candidates

- Final product DB state:
  - `status=failed`
  - `current_step=2`
  - `workflow_node=search_competitor`
  - `workflow_status=failed`
  - `workflow_error=自动竞品搜索失败: empty_results: Amazon search returned no recognizable natural results`
  - `error_message=自动竞品搜索失败: empty_results: Amazon search returned no recognizable natural results`
  - `competitor_asin=B0DHS4FYCL` remained from existing sample history
  - `amazon_asin=null`
  - `aplus_upload_status=not_uploaded`
- Final product API state:
  - `status=failed`
  - workflow `stage=search_competitor`
  - workflow `stage_status=failed`
  - `work_status=select_competitor`
  - `primary_action=retry_competitor_search`
  - `action_reason=自动竞品搜索失败: empty_results: Amazon search returned no recognizable natural results`
- Candidate landing:
  - `amazon_competitor_search_candidates` count for product `92`: `0`
  - candidate sample: empty

### Adapter Evidence

- Page evidence file: `tmp/qa-evidence-20260622-s4-after-region-fix/amazon-search-page/run-761/step-767/query-1.json`
- Adapter: `ChromeAmazonSearchPageAdapter`
- Query: `cabinet adjustable freestanding mdf bathroom`
- Page URL: `https://www.amazon.com/s?k=cabinet+adjustable+freestanding+mdf+bathroom&language=en_US&ref=nb_sb_noss`
- Page title: `Amazon.com : cabinet adjustable freestanding mdf bathroom`
- Classification: `null`
- Error type: `empty_results`
- Error message: `Amazon search returned no recognizable natural results`
- Candidate count: `0`
- Finished at: `2026-06-22T10:08:45.152231`
- DOM summary:
  - `html_length=2908734`
  - `result_count_hint=48`
  - body text sample starts with `卖家精灵`, `Skip to`, `Main content`, `Results`, `Filters`, and delivery/navigation text.

### Error Type

The blocker changed from the prior `region_page` false positive to `empty_results`. This supports the specific regression target: a normal-looking Amazon search page with delivery/navigation text and `result_count_hint=48` was no longer classified as `region_page`.

This run is still blocked at a real Chrome/Amazon page boundary because the parser found no recognizable natural result candidates to land. The failure is typed, readable, and traceable by task run `761`, step `767`, event `653`, product workflow error, backend log, and the adapter evidence file.

### Write Side Effects

Allowed writes performed:

- Official retry API was triggered for product `92`.
- New task run `761`, task group `770`, task step `767`, and task events `651-653` were created.
- Product `92` briefly moved to processing and then returned to retryable failed state.
- Adapter page evidence was written under the configured QA evidence directory.

Forbidden writes avoided:

- No mock, fixture, cached HTML, old evidence replay, or manual DB success mutation.
- No new test product.
- No Amazon import/export generation.
- No Seller Central upload, A+ upload, TikTok publish, real ASIN overwrite, or external write operation.
- No inbox or code files were changed by this QA pass.

### Residual Risks

- This QA does not prove real Amazon candidate parsing/landing, visual match, detail capture, auto-competitor selection, image analysis, listing generation, or export-ready transition.
- `empty_results` may represent an Amazon page-structure/parser support boundary rather than a stable business-empty result. It is typed and evidenced, so it fits the current QA blocker standard, but it is not a successful search result flow.
- Only query index `1` produced page evidence before the step failed; queries `2-3` were not reached.
- Product `92` remains a retryable failed sample and still carries legacy `competitor_asin=B0DHS4FYCL`; this was not treated as a new real Amazon candidate landing.

## Final Status

Latest status for `MSG-20260622-068`: `QA / BLOCKED / REAL_EXTERNAL_DEPENDENCY`.

Stop condition reached. Do not treat this as `PASS_WITH_SCOPE`. The product main chain reached the real Chrome/Amazon search adapter through the official API and task runtime, no longer stopped at the previous `region_page` false positive, then stopped at typed external/page parsing boundary `empty_results` with page-level evidence and no candidate landing.

## MSG-20260622-071 - Real Chrome S4 Rerun After Parser Safety Fix

Date: 2026-06-22 CST
Agent: 观止（agentKey: `guanzhi`）
Result: `QA / PASS_WITH_SCOPE`

### Scope

This rerun verified only the `MSG-20260622-071` gate:

- Product `92 / W808P389332`.
- Official API: `POST /api/products/92/competitor-search/retry`.
- Real Chrome Amazon search adapter with current parser safety fix.
- Candidate landing into `amazon_competitor_search_candidates`.
- Product workflow transition to the next continuable state.

Out of scope and not triggered: export, A+, TikTok, Seller Central, real upload/publish, visual match execution, detail capture, auto competitor selection, image analysis, listing generation, or export-ready transition.

### Environment Snapshot

- Backend: temporary local service on `http://127.0.0.1:8190`.
- Startup config:
  - `AMAZON_SEARCH_PAGE_ADAPTER=chrome`
  - `AMAZON_SEARCH_ENABLE_REAL_BROWSER=true`
  - `AMAZON_SEARCH_EVIDENCE_DIR=/Users/liuchang/Documents/gitproject/fbm-pipeline/tmp/qa-evidence-20260622-s4-after-parser-safety-fix/amazon-search-page`
  - `AMAZON_SEARCH_PER_QUERY_LIMIT=12`
  - `AMAZON_SEARCH_MAX_CANDIDATES=20`
- Health: `GET /api/health` returned 200.
- Evidence root: `tmp/qa-evidence-20260622-s4-after-parser-safety-fix/`

### Trigger And Task Runtime

- Trigger API: `POST /api/products/92/competitor-search/retry`
- Trigger response: HTTP 200, saved at `tmp/qa-evidence-20260622-s4-after-parser-safety-fix/api/post-product-92-competitor-search-retry.json`
- New task run: `769`
- New task step: `775`
- Task run status: `succeeded`
- Task step status: `succeeded`
- Step progress: `3 / 3`
- Task summary: `candidate_count=20`, `query_count=3`, `next_node=visual_match_competitors`
- Task events: 6 events; tail includes `自动竞品搜索页面解析完成`, `自动竞品搜索完成，已进入待视觉初筛`, and `step 成功投影完成`.
- DB/API evidence summary:
  - `tmp/qa-evidence-20260622-s4-after-parser-safety-fix/db-final-summary.json`
  - `tmp/qa-evidence-20260622-s4-after-parser-safety-fix/api/product-92-final-summary.json`
  - `tmp/qa-evidence-20260622-s4-after-parser-safety-fix/env-config.json`

### Product Final State

- DB final state:
  - `status=created`
  - `workflow_node=visual_match_competitors`
  - `workflow_status=pending`
  - `workflow_error=null`
  - `competitor_asin=B0DHS4FYCL` remained from existing sample history and was not overwritten by this search rerun.
- API final state:
  - `workflow.stage=visual_match_competitors`
  - `workflow.stage_status=pending`
  - `workflow.work_status=select_competitor`
  - `workflow.primary_action=retry_competitor_visual_match`
  - `workflow.allowed_actions=["open_detail","retry_competitor_visual_match","restart_competitor_search"]`
  - `current_task_status=Amazon 搜索候选已保存，等待视觉初筛任务`

This satisfies the MSG-071 continuation requirement: real Amazon search candidates landed and the product moved from retryable search failure into the next continuable workflow state.

### Candidate Landing

- Latest run candidate rows: `20`.
- Candidate source: `amazon_search_page`.
- Candidate count by query in DB:
  - query `1`: 12 rows
  - query `2`: 8 rows
  - query `3`: 0 rows landed because `AMAZON_SEARCH_MAX_CANDIDATES=20` was already reached after query 2.
- ASIN/URL consistency check:
  - `asin_url_mismatch_count=0`
  - `missing_url_count=0`
- Sample landed ASINs include `B0FF4STK4S`, `B0BYHVLXTV`, `B0DD451693`, `B0DQ8GBD6K`, `B0B8GFW1WX`, `B09SWL5XJL`, `B0DRC2LWSR`, `B0DKX2KXJK`, `B0FPQDH1JR`, and `B0DQXYR5KP`.

### Adapter Evidence

Adapter evidence files:

- `tmp/qa-evidence-20260622-s4-after-parser-safety-fix/amazon-search-page/run-769/step-775/query-1.json`
- `tmp/qa-evidence-20260622-s4-after-parser-safety-fix/amazon-search-page/run-769/step-775/query-2.json`
- `tmp/qa-evidence-20260622-s4-after-parser-safety-fix/amazon-search-page/run-769/step-775/query-3.json`
- Summary: `tmp/qa-evidence-20260622-s4-after-parser-safety-fix/adapter-evidence-summary.json`

Observed evidence:

- Adapter: `ChromeAmazonSearchPageAdapter`
- Query 1:
  - classification `null`
  - error type `null`
  - `candidate_count=12`
  - `result_count_hint=48`
  - `data_asin_hint=48`
  - `dp_link_hint=48`
  - `asin_url_mismatch_count=0`
- Query 2:
  - classification `null`
  - error type `null`
  - `candidate_count=12`
  - `result_count_hint=48`
  - `data_asin_hint=48`
  - `dp_link_hint=48`
  - `asin_url_mismatch_count=0`
- Query 3:
  - classification `null`
  - error type `null`
  - `candidate_count=12`
  - `result_count_hint=48`
  - `data_asin_hint=48`
  - `dp_link_hint=48`
  - `asin_url_mismatch_count=0`

The previous `region_page` false positive did not reproduce. The previous `empty_results` parser failure did not reproduce. The evidence contains result-block hints and snippets, but they were not needed for blocker diagnosis because parsing succeeded.

### Parser Safety Observations

- No candidate ASIN/URL mismatches were observed in adapter evidence or landed DB rows.
- The landed candidates all have product URLs whose `/dp/{ASIN}` value matches the candidate ASIN.
- No evidence indicated candidates were fabricated from nav/script/promo content. Candidate extraction produced normal result candidates with `source=amazon_search_page`, image URLs, product titles, prices or ratings where available, and matching Amazon product URLs.

### Write Side Effects

Allowed writes performed:

- Official retry API created task run `769`, task step `775`, task events, adapter page evidence, and 20 `amazon_competitor_search_candidates` rows for product `92`.
- Product `92` moved to `visual_match_competitors/pending`.

Forbidden writes avoided:

- No mock, fixture, cached HTML, old evidence replay, or manual DB success mutation.
- No export/import file generation.
- No Seller Central, A+, TikTok, upload, publish, or real ASIN overwrite.
- No business code edit, commit, or push.

### Residual Risks

- This is a scoped PASS for the real Chrome Amazon search rerun only. It does not prove visual match, detail capture, auto competitor selection, image analysis, listing generation, export-ready, export, A+, TikTok, or Seller Central behavior.
- Product `92` still carries legacy `competitor_asin=B0DHS4FYCL`; this run did not overwrite it and did not treat it as new search success.
- Query 3 evidence has a traceability caveat: the intended URL was `cabinet bathroom adjustable freestanding mdf`, but the captured `page_url/page_title` still showed query 2 (`cabinet mdf 32 inch adjustable`). Because `AMAZON_SEARCH_MAX_CANDIDATES=20` had already been reached after query 2, this did not affect candidate landing or MSG-071 PASS criteria. It should be watched if exact per-query attribution becomes a gate.

### Conclusion

`QA / PASS_WITH_SCOPE`.

The official API and task runtime reached the real Chrome Amazon adapter, parsed real Amazon search pages, landed 20 traceable candidates without observed ASIN/URL mismatch, and advanced product `92 / W808P389332` to `visual_match_competitors/pending`. This closes the MSG-071 QA gate within the stated S4 scope.
