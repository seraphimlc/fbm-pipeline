# E5 Product Work Status QA Rerun

Date: 2026-06-22 CST
Agent: 观止（agentKey: `guanzhi`）
Message: `MSG-20260622-047`
Result: `QA_RERUN / PASS_WITH_SCOPE`

## Scope

This rerun verified the user-visible closure for the previous E5 P1:

- Product list overview counts.
- `work_status` filters for `export_ready`, `exported`, `failed`, and `needs_initialization`.
- Row workflow status/action.
- Product detail, task center evidence, and export center consistency.

Out of scope: real Amazon, Seller Central, A+, TikTok, upload/publish, new Amazon export creation, real VLM/listing quality, and destructive retry/cancel/wake actions.

## Environment

- Frontend: `http://127.0.0.1:3190`
- Backend: `http://127.0.0.1:8190`
- Startup: `./scripts/start.sh`
- Evidence dir: `tmp/qa-evidence-20260622-e5-rerun/`

## Cases Covered

- `TC-E5-001`
- `TC-E5-002`
- `TC-E5-003`
- `TC-TASK-003`
- `TC-DATA-SAFETY-001`
- `TC-MIGRATION-001`
- `TC-DATA-SEED-001`

## Result Summary

PASS with scope. The previous P1 is closed for the current test data:

- `overview` now reports `export_ready=9`, `export_ready_unexported=9`, `export_ready_exported=7`, `failed=2`, `needs_initialization=92`.
- `work_status=export_ready` returns 9 rows. Sample product `100` is `flow_done/succeeded`, `work_status=export_ready`, primary action `open_detail`.
- `work_status=exported` returns 7 rows. Samples are `flow_done/succeeded`, `work_status=exported`.
- `work_status=failed` returns 2 rows. Sample product `94` is `image_analysis/failed`, `work_status=failed`, primary action `retry_image_analysis`.
- `work_status=needs_initialization` returns 92 rows. Sample product `95` is `workflow_uninitialized/pending`, `work_status=needs_initialization`, primary action `open_detail`.
- Product detail and export center are consistent with the same export-ready/exported facts.
- Task evidence exists for both sides:
  - Listing success run `47`: `product_listing_generation`, `succeeded`, `correlation_key=product:100:listing_generation`.
  - Image analysis failed run `49`: `product_image_analysis`, `failed`, `correlation_key=product:94:image_analysis`.

## Evidence

Commands:

- `GET /api/health` -> 200.
- `cd backend && .venv/bin/python ../scripts/test_image_analysis_listing_e5.py` -> PASS, `E5 image analysis -> listing -> export_ready behavior checks passed`.
- `GET /api/products/overview?data_source_id=1` -> 200 with counts above.
- `GET /api/products?data_source_id=1&work_status=export_ready&page=1&page_size=5` -> total 9.
- `GET /api/products?data_source_id=1&work_status=exported&page=1&page_size=5` -> total 7.
- `GET /api/products?data_source_id=1&work_status=failed&page=1&page_size=5` -> total 2.
- `GET /api/products?data_source_id=1&work_status=needs_initialization&page=1&page_size=5` -> total 92.
- `GET /api/task-runs/47` -> listing success detail.
- `GET /api/task-runs/49` -> image-analysis failed detail with events.

Saved API evidence:

- `tmp/qa-evidence-20260622-e5-rerun/api-products-export-ready.json`
- `tmp/qa-evidence-20260622-e5-rerun/api-products-exported.json`
- `tmp/qa-evidence-20260622-e5-rerun/api-products-failed.json`
- `tmp/qa-evidence-20260622-e5-rerun/api-products-needs-initialization.json`
- `tmp/qa-evidence-20260622-e5-rerun/api-product-100.json`
- `tmp/qa-evidence-20260622-e5-rerun/api-product-94.json`
- `tmp/qa-evidence-20260622-e5-rerun/api-product-95.json`
- `tmp/qa-evidence-20260622-e5-rerun/api-task-run-47.json`
- `tmp/qa-evidence-20260622-e5-rerun/api-task-run-49.json`

Screenshots:

- `tmp/qa-evidence-20260622-e5-rerun/products-source1-export-ready-us-amazon.png`
- `tmp/qa-evidence-20260622-e5-rerun/products-source1-exported-us-amazon.png`
- `tmp/qa-evidence-20260622-e5-rerun/products-source1-failed-us-amazon.png`
- `tmp/qa-evidence-20260622-e5-rerun/products-source1-needs-initialization-us-amazon.png`
- `tmp/qa-evidence-20260622-e5-rerun/product-100-detail.png`
- `tmp/qa-evidence-20260622-e5-rerun/product-94-detail.png`
- `tmp/qa-evidence-20260622-e5-rerun/task-runs-list.png`
- `tmp/qa-evidence-20260622-e5-rerun/export-center.png`

Browser automation:

- Source 1 product-list screenshots used `localStorage.fbm.productList.dataSourceId=1` to select `大健美国-亚马逊`.
- `browser-events-products-us-amazon.json` and `browser-events-task-runs.json` contain no API 4xx/5xx or console errors.

## Side Effects

- Ran `scripts/test_image_analysis_listing_e5.py`, which creates deterministic `E5_TEST_%` data and cleans it up.
- Opened local pages and called read APIs.
- Did not click retry/wake/cancel/export/upload actions.
- Task run total was 12 before and after page/API checks.
- No real Amazon/Seller Central/A+/TikTok calls.
- No export file creation.
- No upload/publish.

## Limitations

- Retry write path was not clicked. Product `94` exposes `retry_image_analysis`, but clicking it could trigger a new task; this rerun stayed read-only because the task only allowed retry when the sample is demonstrably low risk and recoverable.
- This PASS does not cover real VLM/listing content quality, real Amazon/A+/TikTok, external uploads, or new export generation.
- Product list data source is persisted by UI state; URL `data_source_id=1` alone did not select source 1 in the browser. This was handled by selecting source 1 via stored UI state for screenshots and is not treated as an E5 P1 blocker.

## Conclusion

`MSG-20260622-047` passes with scope. The previous user-visible E5 list/filter/action inconsistency is no longer reproducible on the current test data.
