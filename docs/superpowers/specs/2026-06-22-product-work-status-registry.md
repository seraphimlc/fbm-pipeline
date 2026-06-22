# ProductWorkStatus Registry 技术设计

状态：S2/S3 实现对账
日期：2026-06-22
范围：商品工作台 `work_status` 语义、后端筛选/overview、前端消费和闭包测试。

## 背景

`work_status` 曾散落在 workflow 投影、商品 API、overview schema、前端 union/meta/filter 和项目规则测试里。`ready_to_search_competitor` 与 `needs_initialization` 的闭包问题说明：只修某个消费端会让生产端和消费端继续靠人工同步。

本设计把商品工作状态收敛为后端领域 registry。workflow 生产端只引用 registry key；API 从 registry 派生 accepted keys；测试从 `build_product_workflow()` 的实际输出反查所有消费端是否闭合。

## Registry 入口

入口文件：

- `backend/app/product_tasks/work_status.py`

核心结构：

- `key`：正式 ProductWorkStatus key。
- `label` / `short_label` / `color`：前端展示元信息的后端事实源。
- `overview_bucket`：overview 对应字段；`export_ready/exported` 可映射到派生 bucket。
- `is_list_filterable`：是否允许 `GET /api/products?work_status=...` 和同源筛选入口使用。
- `is_workbench_bucket`：是否进入商品工作台 overview 的普通状态计数。
- `frontend_visible`：前端是否必须接住该状态。
- `primary_metric`：是否出现在商品工作台主指标卡。
- `db_filter_name`：API 层 predicate 绑定名；registry 不依赖 SQLAlchemy。
- `fact_source` / `producer_note`：说明状态事实源和 producer 约束。

## 正式状态清单

正式 ProductWorkStatus：

- `needs_initialization`
- `auto_select_images`
- `select_images`
- `competitor_searching`
- `select_competitor`
- `capture_detail`
- `ready_to_generate`
- `running`
- `export_ready`
- `exported`
- `failed`

`WORKBENCH_STATUS_KEYS` 从 `PRODUCT_WORKBENCH_STATUS_KEYS` 派生；`PRODUCT_LIST_WORK_STATUS_KEYS` 从 `PRODUCT_LIST_FILTER_STATUS_KEYS` 派生。后端 API 不再手写状态全集。

## Legacy Diagnostic 口径

`interrupted` / `suspended` / `manual_review` 不再属于正式 ProductWorkStatus，也不再作为列表 `work_status` 筛选项。

保留范围：

- 前端 row fallback 仍能把旧 `paused`、`pending_review`、旧运行中断状态显示为对应诊断标签。
- 这些诊断状态不进入后端 registry、不进入 `WORKBENCH_STATUS_KEYS`、不进入 `PRODUCT_LIST_WORK_STATUS_KEYS`、不进入 overview schema、不进入全库状态 filter。

理由：

- 当前 Product Workflow Service 不生产这些状态。
- 旧实现的 DB predicate 是 `false()`，会把它们伪装成可筛选状态但永远返回空集合。
- 任务运行态和旧 pipeline 诊断应归到 task runtime / legacy fallback，不应混入正式商品工作状态。

## `export_ready` / `exported`

`export_ready` 和 `exported` 以稳定业务事实为准，不靠单个 workflow node/status 猜测：

- `export_ready`：`Product.status=completed` + `CatalogProduct.confirmed_at` + 无 `exported_at/export_task_id`。
- `exported`：`Product.status=completed` + `CatalogProduct.confirmed_at` + 有 `exported_at/export_task_id`。

overview 口径：

- `export_ready` 映射到 `export_ready_unexported`，同时保留兼容字段 `export_ready`。
- `exported` 映射到 `export_ready_exported`，不是普通 workbench bucket。

列表筛选：

- 两者都是 `is_list_filterable=True`。
- API predicate 必须 join `CatalogProduct` 并按上述稳定事实筛选。

## Producer-Consumer 闭包

生产端：

- `backend/app/product_tasks/workflow.py`
- `build_product_workflow()` 的所有输出必须属于 registry。
- workflow 中不再散写 ProductWorkStatus 字符串，改用 registry 常量。

后端消费端：

- `backend/app/api/products.py`
- `WORKBENCH_STATUS_KEYS` / `PRODUCT_LIST_WORK_STATUS_KEYS` 从 registry 派生。
- `_work_status_condition()` 通过 registry `db_filter_name` dispatch 到 API 层 SQLAlchemy predicate。
- 不可筛选状态必须 400 或不进入 accepted set；不得用 `false()` 假装支持。
- `bulk-advance-task/by-filter` 的 `work_status` 也复用同一个 DB predicate，不再取出商品后内存过滤。

Schema / 前端：

- `backend/app/api/schemas.py` 的 `WorkbenchOverview` 与 registry overview bucket 对齐。
- `frontend/src/api/index.ts` 的 `WorkbenchOverview` 与后端 schema 对齐。
- `frontend/src/pages/ProductList.tsx` 继续手写 `WorkStatus` / `WORK_STATUS_META` / `WORK_STATUS_FILTERS` / `PRIMARY_WORK_STATUS`，但由项目规则测试与 registry 对齐。

## 验证入口

必须覆盖：

- `cd backend && python -m compileall -q app`
- `make test-project-rules`
- `cd backend && .venv/bin/python ../scripts/test_image_analysis_listing_e5.py`
- `cd frontend && npm run build`
- scoped `git diff --check`

关键项目规则：

- `test_product_work_status_producer_outputs_are_registered`
  - 从 `build_product_workflow()` 反推 producer outputs。
  - 验证 registry、overview schema、前端 interface、前端 union/meta/filter/primary metric。
  - 验证 `ready_to_search_competitor` 不被生产或消费。
  - 验证 legacy diagnostic 状态不进入正式 registry/list filter/overview。
- `test_auto_image_selection_phase_b_work_status_behaviour`
  - 验证每个 `PRODUCT_LIST_WORK_STATUS_KEYS` 都有 DB predicate。
  - 验证 legacy diagnostic 状态被拒绝。
- `test_product_bulk_advance_runs_in_task_run_queue`
  - 验证按筛选批量推进复用 DB predicate，不做内存 `work_status` 过滤。

## 边界

本轮不做：

- 新增状态元数据 API 或前端生成链路。
- 改表或迁移。
- A+、TikTok、真实 Amazon、真实导出/上传/发布。
- 商品列表视觉重设计。
