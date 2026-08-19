# Domain Index: Export Flow

## 范围

- Amazon 导出、导出中心、导入模板、类目映射。
- Step 10、UPC、导出任务和模板校验。
- 不覆盖平台实际上传后的运营状态。

## 当前口径

- 导出只生成导入表格和风险提示，不代表平台上架成功。
- 已有真实 Amazon ASIN 的商品，不允许再次导出 Amazon 导入表格。
- 改模板、类目映射、Step 10 或导出字段时，必须更新 `docs/template-mapping-change-log.md`。
- Lingxing A+ 发布 T2 后，Amazon 导出成功路径会把实际写入 Amazon 模板 `sku` 字段的 seller SKU/MSKU 持久化到 `CatalogProduct.amazon_seller_sku` / `Product.amazon_seller_sku`，并在导出 result rows 写 `seller_sku` 证据；这不改变模板字段映射或类目映射本身。T3 的 `POST /api/task-runs/lingxing-aplus-publish` 只消费已对齐 ASIN/seller SKU 和本地 A+ done 事实来保存领星草稿，不改变 Amazon 导出模板、类目映射、导出文件或商品主 workflow。
- 不覆盖真实导出文件、模板文件或已生成素材，除非用户明确要求。
- Catalog export parser 先保留 `json_valid/material/malformed` provenance，再由 raw selector 选择 parse-valid material summary 或按 step id 倒序的最新 parse-valid material step；invalid JSON、非有限/溢出数值、深度或内存解析失败是 nonmaterial，不形成 barrier，会继续回退更旧有效 step。选中的 raw payload 只生成一次 validated outcome；invalid-only 不制造 authoritative failed，parse-valid unsafe row 仍 fail closed。rows 非空时以 normalized rows 重算 `requested/success/skipped/failed/report` 和 `done|partial_failed|failed`；显式 `artifact_available=false|null|malformed` 强制 failed，rows 缺失时保留有限 legacy 兼容。
- `TaskRunCenter.tsx` 直接展示 `catalog_export_result` 的结果状态、五类计数和逐商品 rows；`CatalogList.tsx` 已导出列表展开同源 rows。TaskRun list/detail、OfflineTask、Export Files、download action、categories 和 existing-result 复用均消费同一 validated outcome，每行携带稳定 1-based `row_ordinal`；artifact resolver 只在该 outcome 上按 allowed-root local -> object key/cache -> validated redirect 解析来源。failed 保持不可下载，正常 done/partial 与缺少 availability flag 的 legacy safe refs 继续可下载；页面不解析 `summary_json` 或原始状态自行授权。
- Catalog 外层终态只在有 parse-valid material evidence 的业务终态上采用 validated outcome；无 material 的 raw terminal 保持原值，status-only legacy partial 继续兼容。TaskRun/OfflineTask 列表及 Export Files/Categories 都按 owner kind 复用一次全历史 scalar + newest-valid-material step batch 生成的 `records_by_id` 和 terminal ID sets；Export row builder 不再自行 selector/normalize/project。raw canceled/interrupted/paused 即使 payload 为 done 也保持 raw、不可下载且不进入 Export Files/Categories；不使用 legacy partial helper、JSON SQL、step JOIN/N+1 或分页后过滤。
- Step 10 的 in-session 路径和 `build_catalog_export_zip()` 只 flush、不 commit/rollback：每个 catalog row 的 semantic/Step10/UPC/ProductFile/Catalog 变更放在 nested transaction/savepoint 中，业务失败只回滚当前行，系统异常回滚整个 outer transaction。新任务路径由 scheduler 连同成功 catalog 事实与终态投影一次 commit，旧同步导出 API 只在 builder 成功后由 API caller 一次 commit。

## 关键入口

- 导出中心页面：`frontend/src/pages/CatalogList.tsx`
- 导出 planner：`backend/app/task_planners/catalog_export.py`
- 导出 worker：`backend/app/task_runtime/catalog_export_workers.py`
- 商品 API：`backend/app/api/products.py`
- Amazon 模板旧入口：`backend/app/pipeline/step10_amazon_template.py`
- Amazon 导出规则层：`backend/app/pipeline/amazon_export/`
- 模板映射：`backend/app/pipeline/template_mappings/*.json`
- 模板文件：`backend/app/pipeline/templates/*.xlsm`
- 床架专用导出：`vindhvisk_bed_frame.json` -> `BED_FRAME.xlsm` -> `amazon_export/strategies/bed_frame.py`。该路径仅填有证据的普通床架字段；关键事实缺失会以逐字段原因失败，不能以通用家具默认值生成表面成功的导出。
- UPC：`frontend/src/pages/UpcPoolPage.tsx`, `backend/app/services/upc_pool.py`
- 表：`catalog_products`, `task_runs`, `task_steps`, `task_step_events`, `products`, `product_data`

## 关键流程

- 导出中心：`CatalogList.tsx` -> 商品 API/导出任务 -> 任务中心。
- Amazon 导出：planner -> worker -> `backend/app/pipeline/amazon_export/`。
- 导出 outcome：`backend/app/services/offline_tasks.py` canonicalizer -> `backend/app/task_runtime/catalog_export_workers.py` envelope -> `backend/app/task_runtime/scheduler.py` 单事务终态投影 -> Task Center / Export Center API。
- Seller SKU 持久化：`backend/app/pipeline/amazon_export/listing_fill.py` 的 `amazon_seller_sku_for_export()` 与导出 worker 的成功写库路径同源，后续 Lingxing Listing sync 只能以该 seller SKU/MSKU exact match 作为 ASIN 主匹配依据。
- 领星 A+ 草稿保存 T3：`POST /api/task-runs/lingxing-aplus-publish` -> `backend/app/task_planners/lingxing_aplus_publish.py` -> `backend/app/task_runtime/lingxing_aplus_publish_workers.py`，只写 A+ 发布状态/证据，不生成或修改导出文件。
- 模板/类目：template mappings -> templates -> Step 10/导出规则层。
- UPC：导出前按当前 UPC service/model 逻辑定位。

## 相关文档

- `docs/template-mapping-spec.md`
- `docs/template-mapping-change-log.md`
- `docs/add-category-template-sop.md`
- `docs/main-flow-user-path.md`
- `docs/main-flow-qa-checklist.md`
- `docs/superpowers/specs/2026-06-16-task-center-state-action-prd.md`

## 验证入口

- 导出中心：`http://localhost:3190/export-center`
- 任务中心：`http://localhost:3190/task-runs`
- 模板映射校验：`make validate-template-mappings`
- 项目规则校验：普通静态/非 DB 段可用 `make test-project-rules`；完整 R1 DB gate 固定用 `R1_TEST_MYSQL_ADMIN_URL='mysql+asyncmy://root@127.0.0.1:3306/' python3 scripts/testing/run_with_r1_mysql.py -- make test-project-rules`。只有该字面 argv 会被改写为固定 system make + repo Makefile 并获得 marker secrets；PATH/绝对/相对 fake make 均不能伪造 VERIFIED。
- Catalog export outcome/MySQL：`cd backend && R1_TEST_MYSQL_ADMIN_URL='mysql+asyncmy://root@127.0.0.1:3306/' .venv/bin/python ../scripts/test_stability_repair_r1_catalog_export.py`
- Catalog export 前端真实 API/Chromium：`R1_TEST_MYSQL_ADMIN_URL='mysql+asyncmy://root@127.0.0.1:3306/' backend/.venv/bin/python scripts/test_stability_repair_r1_catalog_frontend.py`；脚本建立并 finally 删除专用 `fbm_pipeline_r1_*`，启动真实 FastAPI/Vite，不使用 route/HAR/API mock。
- 领星 A+ 草稿保存行为脚本：`cd backend && .venv/bin/python ../scripts/test_lingxing_aplus_publish_policy.py`、`cd backend && .venv/bin/python ../scripts/test_lingxing_aplus_publish_tasks.py`

## 常见定位

- 导出任务状态：先看 `catalog_export.py`、`catalog_export_workers.py` 和 `task_runs` 事件。
- 模板字段问题：先看 `backend/app/pipeline/amazon_export/` 和 `template_mappings/*.json`。
- 类目映射问题：先看 `docs/template-mapping-spec.md` 和 `docs/template-mapping-change-log.md`。
- UPC 问题：先看 `backend/app/services/upc_pool.py`。

## 维护规则

只有页面/API/核心 service/action/table/导出字段/模板映射/验证入口变化时更新本文。普通 bug fix、函数内部重构、样式微调、测试补充不需要更新。
