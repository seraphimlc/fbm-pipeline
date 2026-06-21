# Core Smoke and Task Center QA - 2026-06-21

观止（agentKey: `guanzhi`）

## Conclusion

Latest rerun for `MSG-20260621-025`: `QA_RERUN / PASS` with `SMOKE_PASS + TASK_RUNTIME_PASS`.

Initial run for `MSG-20260621-014`: `NEEDS_FIX`.

The schema/bootstrap blocker found in the first run is no longer reproduced. Product list API, product detail API, product detail page, task center list/detail, task center pagination/diagnostic filters, and product detail material-directory read-only checks all passed in the rerun.

This PASS only covers the `MSG-20260621-025` smoke/rerun scope. It does not prove automatic competitor selection, export-ready full chain, A+, TikTok, ProductTaskAction write paths, or any real external platform flow.

## Rerun - 2026-06-21 Schema Bootstrap Fix

### Rerun Environment

- Backend: `http://127.0.0.1:8190`
- Frontend: `http://127.0.0.1:3190`
- Started with: `./scripts/start.sh`
- Startup behavior observed: `scripts/start.sh` ran `python -m app.database` before uvicorn; FastAPI lifespan still logged DB maintenance/backfills/recovery/runtime kick as disabled.
- Health: `GET /api/health` -> `200`, `{"status":"ok","version":"0.1.0"}`

### Rerun Evidence

- Page screenshots:
  - `/Users/liuchang/Documents/gitproject/fbm-pipeline/tmp/qa-evidence-20260621-rerun/products.png`
  - `/Users/liuchang/Documents/gitproject/fbm-pipeline/tmp/qa-evidence-20260621-rerun/product-101.png`
  - `/Users/liuchang/Documents/gitproject/fbm-pipeline/tmp/qa-evidence-20260621-rerun/task-runs.png`
  - `/Users/liuchang/Documents/gitproject/fbm-pipeline/tmp/qa-evidence-20260621-rerun/export-center.png`
- Schema/API:
  - DB columns exist: `products.workflow_node`, `workflow_status`, `workflow_error`, `workflow_updated_at`.
  - `GET /api/products?page=1&page_size=5` -> `200`, `total=110`, `items=5`, first page includes product ids `95, 92, 101, 94, 93`.
  - `GET /api/products/101` -> `200`, product `101`, item code `W808P390792`, workflow stage `workflow_uninitialized`.
  - Browser product detail `/products/101` rendered without API 4xx/5xx.
  - Browser product list `/products` rendered without product API 4xx/5xx. It selected data source `3` (`大健日本`) which currently has `0` products; DB product counts show all `110` products under source `1`, so the empty default page is data-source state, not the previous API-500 failure.
- Material read-only sample:
  - Sample: product `101`, item code `W808P390792`, material dir `/Users/liuchang/Documents/gitproject/fbm-pipeline/data/products/GIGA/US/W808P390792`.
  - Before file hash: `0ac228e09cfe1c9dd090cef83ffc71440afb8729e9d62097a7a81649fa53ee58`, file count `7`.
  - After two `GET /api/products/101` calls: same hash `0ac228e09cfe1c9dd090cef83ffc71440afb8729e9d62097a7a81649fa53ee58`, same file count `7`.
  - DB before/after stable: product row `(101, step6_curating, current_step=5, workflow_node=None, workflow_status=None, updated_at=2026-06-17 20:46:22)`, `product_images` count `1`.
- Task center:
  - `GET /api/task-runs?page=1&page_size=1` -> `total=6`, item `#52`.
  - `GET /api/task-runs?page=2&page_size=1` -> `total=6`, item `#51`, no duplicate with page 1.
  - `GET /api/task-runs?view=all&page=1&page_size=1` -> `total=45`, matching DB `select count(*) from task_runs` -> `45`.
  - `GET /api/task-runs/52` -> `200`, includes run/group/step hierarchy.
  - `display_status=stale_running|waiting_dependency|planned` list filters all returned `400`, with detail-only diagnostic message.

### Rerun Case Matrix

| Case | Result | Evidence / Notes |
|---|---|---|
| `TC-SMOKE-001` | PASS | Health 200; `/products`, `/task-runs`, `/export-center` frontend routes render; product/task APIs return 2xx. |
| `TC-SMOKE-002` | PASS | `GET /api/products` and `GET /api/products/101` return 200; `/products/101` page renders without API 4xx/5xx. Product list default data source is empty but no longer caused by API 500. |
| `TC-SMOKE-003` | PASS | `/task-runs` page renders current task list; `GET /api/task-runs/52` returns run/group/step detail. |
| `TC-FUNCTIONAL-PRODUCT-002` | PASS | Product detail GET for sample `101` leaves material file hash/count and DB facts unchanged. |
| `TC-REGRESSION-002` | PASS | Two consecutive detail GETs did not move/create/delete files, did not upload/generate new contact sheet evidence, and did not write product/product_images facts. |
| `TC-REGRESSION-003` | PASS | workflow schema columns exist; product list/detail API restored to 2xx after standard startup schema maintenance. |
| `TC-TASK-001` | PASS | Current view pagination total is stable; `view=all` total matches DB count; no scan-limit/fake-total evidence. |
| `TC-TASK-002` | PASS | Detail-only diagnostic statuses are rejected as list filters with 400. |

### Rerun Side Effects

- Allowed side effects used:
  - Started local backend/frontend through standard `./scripts/start.sh`.
  - `start.sh` executed the approved schema maintenance entrypoint before uvicorn.
  - Performed GET API requests, read-only DB queries, page screenshots, and local file stat/hash checks.
- Forbidden side effects avoided:
  - No mutating API calls.
  - No ProductTaskAction trigger.
  - No new Amazon export.
  - No external platform upload/publish.
  - No real ASIN, store, historical export, or manual confirmation state changes.

### Rerun Not Covered

- ProductTaskAction入队态 was not rerun; `MSG-20260621-025` did not require triggering a write path.
- Automatic competitor selection, export-ready full chain, A+, TikTok, real Amazon/VLM and external platform checks remain out of scope.

## Initial Run - 2026-06-21

本轮不能写 `SMOKE_PASS`。后端健康检查、前端 shell、任务中心和已有导出产物抽样可用，但商品列表和商品详情核心 API 均返回 500，当前页面把商品 API 失败吞成“全库 0 条 / 暂无数据”，会误导用户并阻断商品主路径。

任务中心子集可记为本轮 `TASK_RUNTIME_PASS`：列表、详情、分页 total、诊断态筛选边界符合本轮验证目标。

已有导出产物抽样可记为本轮 `ARTIFACT_PASS`：只抽样已有 task_run 17 zip，未创建新导出，未上传外部平台。

## Environment

- Backend: `http://127.0.0.1:8190`
- Frontend: `http://127.0.0.1:3190`
- Started with: `./scripts/start.sh`
- Startup side effects observed: DB maintenance, backfills, task recovery and task runtime kick all logged as disabled.
- Health: `GET /api/health` -> `200`, `{"status":"ok","version":"0.1.0"}`

## Evidence

- Page screenshots:
  - `/Users/liuchang/Documents/gitproject/fbm-pipeline/tmp/qa-evidence-20260621/products.png`
  - `/Users/liuchang/Documents/gitproject/fbm-pipeline/tmp/qa-evidence-20260621/task-runs.png`
  - `/Users/liuchang/Documents/gitproject/fbm-pipeline/tmp/qa-evidence-20260621/export-center.png`
- Product API:
  - `GET /api/products?page=1&page_size=5` -> `500 Internal Server Error`
  - backend stack: MySQL error `Unknown column 'products.workflow_node' in 'field list'`
  - `GET /api/products/101` -> `500 Internal Server Error`
  - read-only DB check: `SHOW COLUMNS FROM products LIKE 'workflow_node'` -> no row
- Task center API:
  - `GET /api/task-runs?page=1&page_size=1` -> `total=6`, item `#52`, `display_status=failed`
  - `GET /api/task-runs?page=2&page_size=1` -> `total=6`, item `#51`, no duplicate with page 1
  - `GET /api/task-runs?view=all&page=1&page_size=1` -> `total=45`
  - read-only DB count: `select count(*) from task_runs` -> `45`
  - API source check: default `view=current` excludes history; `view=all` matches DB full table
  - `GET /api/task-runs/52` -> `200`, includes run/group/step/event hierarchy and failed error details
  - `GET /api/task-runs?display_status=stale_running|waiting_dependency|planned` -> `400`, message says these statuses are detail-only diagnostics
- Artifact sample:
  - `GET /api/products/catalog/export-files?page=1&page_size=1` -> task `17`, `can_download=true`, `success_count=4`, `exported_count=4`, `skipped_count=0`, `failed_count=0`, `report_count=4`
  - local file exists: `/Users/liuchang/Documents/gitproject/fbm-pipeline/data/exports/task_run_17/catalog_export_r17_s23.zip`
  - zip contains one `.xlsm` and `导出报告.xlsx`
  - bundled openpyxl read-only parse:
    - report workbook sheet `导出报告`, size `5 x 8`, first data rows include `已导出`, product ids `110`, `107`
    - xlsm workbook opens and includes sheets `Changes to the template`, `Instructions`, `Images`, `Data Definitions`, `Template`

## Case Matrix

| Case | Result | Evidence / Notes |
|---|---|---|
| `TC-SMOKE-001` | FAIL | Health and frontend shell work, but required product API returns 500. Product page screenshot shows empty data plus console 500. |
| `TC-SMOKE-002` | FAIL | `GET /api/products` and `GET /api/products/101` return 500 due missing `products.workflow_node`. Product list/detail cannot be trusted. |
| `TC-SMOKE-003` | PASS | `/task-runs` page renders current task list; `GET /api/task-runs/52` returns run/group/step/event detail. |
| `TC-TASK-001` | PASS | Default current view returns total 6 with DB-backed pagination; `view=all` total 45 matches DB count 45; no scan-limit/fake-total indication. |
| `TC-TASK-002` | PASS | `stale_running`, `waiting_dependency`, `planned` list filters return 400 and remain detail-only diagnostics. |
| `TC-FUNCTIONAL-PRODUCT-001` | BLOCKED | Product API/schema failure prevents safe sample selection; no ProductTaskAction was triggered. |
| `TC-FUNCTIONAL-PRODUCT-002` | BLOCKED | Product detail GET returns 500 before material directory can be verified. |
| `TC-REGRESSION-002` | BLOCKED | Same blocker as above; GET detail path cannot reach material read-only checks. |
| `TC-ARTIFACT-001` | PASS | Existing task_run 17 zip/report/xlsm sampled read-only; no new export created. |

## Issues

### P0 - Product list and detail APIs fail on current test DB schema

- Repro:
  1. Start local services with `./scripts/start.sh`.
  2. Request `GET http://127.0.0.1:8190/api/products?page=1&page_size=5`.
  3. Request `GET http://127.0.0.1:8190/api/products/101`.
- Actual:
  - Both return `500 Internal Server Error`.
  - Backend stack shows MySQL `1054 Unknown column 'products.workflow_node' in 'field list'`.
  - Read-only DB check confirms `products.workflow_node` is absent.
  - `/products` frontend renders “全库 0 条 / 暂无数据” while console records API 500.
- Expected:
  - Product list/detail should return 2xx with current test data, or expose a clear schema/environment blocker instead of silently showing empty data.
- User impact:
  - Core product workbench appears empty even though DB has products.
  - Product detail, material read-only regression QA, and safe ProductTaskAction sample selection are blocked.

## Side Effects

- Allowed side effects used:
  - Started local backend/frontend services.
  - Performed GET API requests, read-only DB queries, page screenshots and local artifact parsing.
- Forbidden side effects avoided:
  - No mutating API calls.
  - No ProductTaskAction trigger.
  - No new Amazon export.
  - No Seller Central / real Amazon upload or publication.
  - No real ASIN state changes.

## Not Covered

- ProductTaskAction入队态：blocked by product API/schema failure and no safe sample selection.
- 商品详情素材目录只读前后对比：blocked by product detail 500.
- 真实 Amazon / Seller Central / external platform: explicitly out of scope.
- Full release QA: out of scope.

## Next Action

听云需要先修复或迁移当前测试 DB schema 与代码模型不一致的问题，至少让商品列表和详情 API 在当前测试数据上恢复 2xx。修复后建议观止重跑 `TC-SMOKE-001`、`TC-SMOKE-002`、`TC-FUNCTIONAL-PRODUCT-002`、`TC-REGRESSION-002`，再决定是否触发一次安全的 ProductTaskAction 入队验证。
