# Lingxing A+ Publish T3 Real Save QA

结论：`QA / PASS_WITH_SCOPE`

## Scope

- 本轮只验证 T3 真实 Lingxing A+ 保存草稿：`draft_saved + amazon_draft_visibility=unconfirmed`。
- 不验证 `draft_visible`，不代表 Amazon Seller Central A+ 草稿箱可见。
- 不提交审批，不启用 submit approval，不调用 edit/submit。
- 不修改既有业务商品主 workflow / `work_status`；本轮仅新建 `QA_ONLY` 测试样本并触发 T3 task runtime。

## Environment

- Branch: `codex/amazon-auto-competitor-search-phase-a`
- T2 commit: `cef3c72 feat: add Lingxing listing sync task`
- T3 commit: `ab2a99b feat: add Lingxing A+ draft save task`
- Chrome Lingxing login: 可用；`https://erp.lingxing.com/erp/aplusList#fbm-pipeline-worker` 页面登录态有效，A+ 页面可见。
- Store discovery:
  - 只读调用 `https://erp.lingxing.com/api/module/scmPlatformStore/PlatformStore/getStoreDropDown`
  - 匹配店铺：`idea_lc@163.com-US`
  - `store_id=10372`, `country_code=US`
- Runtime env for real save:
  - `LINGXING_APLUS_ALLOW_REAL_EXTERNAL_CALLS=true`
  - `LINGXING_APLUS_SUBMIT_FOR_APPROVAL=false`
  - `LINGXING_APLUS_STORE_ID=10372`
  - `LINGXING_APLUS_STORE_NAME=idea_lc@163.com-US`
  - `LINGXING_APLUS_SITE=US`

## Basic Verification

- `cd backend && .venv/bin/python -m compileall -q app`: PASS.
- `cd backend && .venv/bin/python ../scripts/test_lingxing_aplus_publish_policy.py`: PASS.
- `cd backend && .venv/bin/python ../scripts/test_lingxing_aplus_publish_tasks.py`: PASS, exit 0. Expected fake external failure tracebacks appeared for `auth_required`, `api_failed`, and `request_failed`.
- `make test-project-rules`: PASS, 65 project rule tests.

## Sample

当前业务库没有可直接使用的 T3 前置样本：

- `product_aplus`: 110 rows; `done=0`, `failed=1`, `null=109`.
- `catalog_products`: 21 rows; all `asin_sync_status=not_synced`.
- `aplus_upload_items`: 0 rows before this QA.

因此本轮创建明确测试样本：

- Marker: `QA_ONLY_LINGXING_APLUS_T3_REAL_SAVE_20260623`
- Product id: `1435`
- CatalogProduct id: `1300`
- ProductAplus id: `838`
- A+ image directory: `/Users/liuchang/Documents/gitproject/fbm-pipeline/tmp/lingxing-aplus-t3-real-save-qa`
- Real Lingxing listing read used for sample:
  - Store: `idea_lc@163.com-US` / `10372`
  - ASIN: `B0GX2GFR73`
  - MSKU: `N726P248345C`
  - Listing status: `在售`
  - `is_delete=0`
- Product/Catalog sample facts before publish:
  - `ProductAplus.aplus_status=done`
  - 5 local A+ images, each `970x600`, `status=done`
  - `CatalogProduct.amazon_seller_sku=N726P248345C`
  - `CatalogProduct.amazon_asin=B0GX2GFR73`
  - `CatalogProduct.asin_sync_status=synced`
  - `CatalogProduct.aplus_upload_status=not_uploaded`

## Execution Evidence

The local backend server was not running, so this QA used the equivalent planner/runtime path rather than a live HTTP `POST`:

1. Registered `lingxing_aplus_publish_product` worker.
2. Called `create_lingxing_aplus_publish_runs(...)` for catalog `1300`.
3. Created task run `1244`, step `1250`.
4. The QA script initially used `auto_start=False`, producing a pending step. I corrected only this QA run by marking step `1250` ready to match the API default auto-start behavior, then executed `drain_ready_steps()`.
5. Runtime executed the real T3 worker and made real Lingxing external calls.

Task result:

- TaskRun id: `1244`
- TaskStep id: `1250`
- Run status: `succeeded`
- Step status: `succeeded`
- Attempt count: `1`
- Step result:
  - `status=draft_saved`
  - `lingxing_aplus_id_hash=c0ae094b6a9609107a5842d694dcc31c`
  - `amazon_draft_visibility=unconfirmed`
  - `source_task_run_id=1244`
  - `source_task_step_id=1250`

## DB Facts

After execution:

- `Product.aplus_upload_status=draft_saved`
- `CatalogProduct.aplus_upload_status=draft_saved`
- `AplusUploadBatch.id=26`
- `AplusUploadBatch.status=completed`
- `AplusUploadBatch.submit_for_approval=0`
- `AplusUploadItem.id=26`
- `AplusUploadItem.status=success`
- `AplusUploadItem.lingxing_aplus_id_hash=c0ae094b6a9609107a5842d694dcc31c`
- `AplusUploadItem.amazon_draft_visibility=unconfirmed`
- `AplusUploadItem.store_id=10372`
- `AplusUploadItem.site=US`
- `AplusUploadItem.seller_sku_used=N726P248345C`
- `publish_evidence_json` includes:
  - `endpoint_family=lingxing_aplus_add`
  - `submitFlag=0`
  - `idHash=c0ae094b6a9609107a5842d694dcc31c`
  - `status_text=草稿`
  - Lingxing response summary: `code=1`, `success=true`, `message=操作成功`, `statusName=草稿`
  - `uploaded_image_count=5`
  - `amazon_draft_visibility=unconfirmed`
  - `source_task_run_id=1244`
  - `source_task_step_id=1250`

## Task Events

Task events for run `1244`:

- `external_call`: prepared `lingxing_aplus_add`, ASIN `B0GX2GFR73`, seller SKU `N726P248345C`, store `10372`, site `US`, image count `5`, `submitFlag=0`.
- `external_result`: `draft_saved`, `idHash=c0ae094b6a9609107a5842d694dcc31c`, `amazon_draft_visibility=unconfirmed`, `submitFlag=0`.
- `progress`: `领星 A+ 草稿已保存；Amazon 草稿可见性未确认`.
- `status`: step succeeded with `draft_saved` result.

Event secret scan:

- Checked event messages/data for `cookie`, `auth-token`, `authorization`, `x-ak-uid`, `x-ak-company-id`, `x-ak-env-key`, `x-ak-zid`, `headers`.
- Result: no hits.

## Real Lingxing Save

真实 Lingxing 保存草稿发生。

Evidence:

- Real external calls were enabled only for this run.
- Lingxing `amazon/aplus/add` response summary returned `code=1`, `success=true`, `message=操作成功`, `idHash=c0ae094b6a9609107a5842d694dcc31c`, `statusName=草稿`.
- Local DB and task runtime recorded the same `idHash` and `draft_saved` state.

## Boundaries

- This QA does not prove `draft_visible`.
- This QA does not prove Amazon Seller Central A+ draft-box visibility.
- This QA does not prove submit approval.
- `LINGXING_APLUS_SUBMIT_FOR_APPROVAL=false` was kept throughout the real save run.
- `AplusUploadBatch.submit_for_approval=0` and evidence `submitFlag=0`.
- No `draft_visible_at` or `submitted_at` evidence was claimed.

## Residual Risks

- The live backend HTTP server was not running, so the QA used planner + task runtime directly instead of live `POST /api/task-runs/lingxing-aplus-publish`. This still covered the same planner/worker/runtime save path, but not FastAPI request serialization/middleware.
- The QA run included a start correction because I created the run with `auto_start=False`; real API creation uses planner default `auto_start=True`.
- Lingxing page/list visual confirmation was not performed in this report. The real save evidence is from the Lingxing add API response and DB/task facts.
- The generated Lingxing document name is T3 code's fixed format `{asin}_{seller_sku}_{product_id}`, so the external draft name itself is not prefixed `QA_ONLY`; the local sample, images, and evidence are marked `QA_ONLY`.
- This does not cover T4 draft visibility, sync timing, duplicate save behavior after this real draft, or submit approval.
