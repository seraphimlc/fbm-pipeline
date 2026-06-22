# E5 Image Analysis -> Listing -> Export Ready QA

Date: 2026-06-21 CST
Agent: 观止（agentKey: `guanzhi`）
Message: `MSG-20260621-034`
Result: `QA / NEEDS_FIX`

## Scope

This QA covered the E5 user-visible path after engineering gate:

- `product_image_analysis -> product_listing_generation -> flow_done/succeeded -> Product.status=completed`
- Product list/detail/export-center visibility for `export_ready / 待导出`
- Task center evidence for image/listing runs
- Failed image/listing samples and retry visibility

Out of scope: real Amazon, Seller Central, A+, TikTok, real upload/publish, real VLM/listing quality judgment, and creating new export files.

## Environment

- Frontend: `http://127.0.0.1:3190`
- Backend: `http://127.0.0.1:8190`
- Startup: `./scripts/start.sh`
- Evidence dir: `tmp/qa-evidence-20260621-e5/`

## Temporary Execution Checklist

The reusable QA case library does not yet have E5-specific cases, so this run used a temporary checklist:

1. Core smoke: health API, product list, product detail, task center, export center.
2. White-box E5 behavior script.
3. Export-ready visibility in product detail and export center.
4. Product list `export_ready` count/filter consistency.
5. Failed image/listing sample visibility and retry action.
6. Task center run/correlation evidence.
7. Boundary check: no real external platform/upload/export creation.

## Evidence Summary

### Passed / usable evidence

- `cd backend && .venv/bin/python ../scripts/test_image_analysis_listing_e5.py` PASS:
  - output: `E5 image analysis -> listing -> export_ready behavior checks passed`
- `GET /api/health` -> 200.
- `GET /api/products?page=1&page_size=5` -> 200.
- `GET /api/task-runs?page=1&page_size=3` -> 200.
- Product detail for product `90` shows the stepper at `待导出 / 已加入待导出`.
  - Screenshot: `tmp/qa-evidence-20260621-e5/product-90-detail.png`
- Export center shows 16 selectable products, including 9 unexported `待导出` products and 7 already exported products.
  - Screenshot: `tmp/qa-evidence-20260621-e5/export-center.png`
- Task API detail for listing run `47` returned 200 with:
  - `task_type=product_listing_generation`
  - `status=succeeded`
  - `correlation_key=product:100:listing_generation`
  - event message `Listing 生成完成，已进入待导出`
- Task center page renders current image/listing runs without relevant API 4xx/5xx.
  - Screenshot: `tmp/qa-evidence-20260621-e5/task-runs.png`

### P1 findings

#### P1-1 Product list export-ready filter is inconsistent with E5/export-center facts

User impact: the dashboard cards and export center say there are products ready to export, but filtering the product list by `待导出` returns an empty table. A user cannot reliably find export-ready products from the product workbench filter.

Evidence:

- `GET /api/products/overview?data_source_id=1` returned:
  - `total_products=110`
  - `needs_initialization=110`
  - `export_ready=0`
  - `export_ready_unexported=9`
  - `export_ready_exported=7`
- `GET /api/products?data_source_id=1&work_status=export_ready&page=1&page_size=10` returned `total=0`.
- Product list source `1` all view shows the status card `待导出 9` and `已导出 7`, but rows including product `100` still display `Workflow 待初始化`.
  - Screenshot: `tmp/qa-evidence-20260621-e5/products-source1-all.png`
- Product list `work_status=export_ready` view shows `待导出：当前筛选 0 条`.
  - Screenshot: `tmp/qa-evidence-20260621-e5/products-source1-export-ready.png`
- Product detail and export center both prove export-ready facts exist:
  - product `90` detail: `待导出 / 已加入待导出`
  - export center: product `100` and others listed as `待导出`

Likely behavior cause from observed API/page facts: completed/export-ready products with empty `workflow_node/workflow_status` are still projected by product-list API as `workflow_uninitialized / needs_initialization`, while frontend cards/export center use completed/export facts.

Expected:

- Products that are completed and not exported should be findable through the product list `export_ready / 待导出` filter.
- The list row status should not show `Workflow 待初始化` for products already visible as export-ready in detail/export center.

#### P1-2 Existing failed image-analysis samples do not expose E5 retry action in product list

User impact: current test data has failed image-analysis products, but product list filtering/actions do not expose `retry_image_analysis` or an equivalent safe retry entry.

Evidence:

- `GET /api/products?data_source_id=1&work_status=failed&page=1&page_size=10` returned `total=0`.
- Product source `1` all view shows status card `失败 0`, while direct status query `GET /api/products?status=failed&page=1&page_size=10` returned product `94` and `93`.
- Product `94` has `status=failed` and image-analysis failure text:
  - `图片分析失败: RuntimeError: VLM 未返回任何真实图片分析结果...`
- Product `94` API workflow is `workflow_uninitialized / needs_initialization`, primary action `open_detail`, not `retry_image_analysis`.
- Product list failed filter screenshot:
  - `tmp/qa-evidence-20260621-e5/products-source1-failed.png`

Expected:

- A product that is visibly failed due to image analysis should either expose a safe retry action, or the UI/API should clearly explain why it is not an E5 retryable sample.
- Failed image/listing samples should not disappear from the workbench failed bucket when current data contains such failures.

Note: I did not create synthetic failed samples for the page path because `MSG-20260621-034` asks to report data gaps instead of fabricating conclusions. The white-box script covers E5 failed/cancel/interrupted behavior, but the current page/API data does not provide a clean E5 workflow failed sample for a full user-path PASS.

## Blocked / Not Fully Covered

- Current DB has no clean page/API sample with `workflow_node=image_analysis|listing_generation` and `workflow_status=failed`; historical failed products have null workflow fields.
- Current DB has no clean page/API sample with `workflow_node=flow_done` and `workflow_status=succeeded`; historical completed products have null workflow fields.
- Therefore I cannot write `PASS_WITH_SCOPE` for E5 page/list filter/action consistency, even though the deterministic behavior script passes.

## Side Effects

- Ran `scripts/test_image_analysis_listing_e5.py`, which creates deterministic `E5_TEST_%` products/runs and cleans them up.
- No real Amazon/Seller Central/A+/TikTok calls.
- No export file creation.
- No upload/publish.
- No manual click on retry/cancel/wake/export actions.

## Recommendation

Fix product-list API/workflow projection so completed/export-ready and failed image/listing states are consistent across:

- `GET /api/products`
- `GET /api/products/overview`
- Product list status cards
- Product list work-status filters
- Product row action
- Product detail/export center facts

After the fix, rerun:

```bash
cd backend && .venv/bin/python ../scripts/test_image_analysis_listing_e5.py
curl 'http://127.0.0.1:8190/api/products/overview?data_source_id=1'
curl 'http://127.0.0.1:8190/api/products?data_source_id=1&work_status=export_ready&page=1&page_size=10'
curl 'http://127.0.0.1:8190/api/products?data_source_id=1&work_status=failed&page=1&page_size=10'
```

Then rerun the product list/detail/task center/export center browser checks.
