# Offline Task Center Design

日期：2026-06-03

## 目标

把商品中心里的长耗时操作交给统一的任务中心承载。商品中心只负责提交业务动作和展示商品状态；任务中心负责离线任务的进度、失败原因、子步骤和重跑入口。

第一版先接入“商品中心拉取大健商品”链路，并预留历史图片下载、Excel 导出、Amazon Listing 抓取、A+ 生成等任务类型。

## 范围

- 商品中心拉品必须选择数据源，支持多选。
- 每次多选拉品创建一个父任务，父任务下按数据源创建子步骤。
- 每个数据源子步骤创建独立 GIGA sync batch。
- GIGA 主数据拉取只保存商品、SKU、库存、价格和图片 URL 候选，不在拉品后自动全量下载图片。
- `giga_image_download` 仅用于历史任务兼容或人工维护场景；新拉品任务不应把它表达为必经步骤。
- 任务中心页面展示任务列表和步骤详情。
- 第一版不做任务取消，不做跨进程队列，不重写已有 GIGA 数据表。

## 数据模型

### `offline_tasks`

父任务表。

- `id`
- `task_type`：如 `giga_pull`
- `title`
- `status`：`pending`、`running`、`done`、`failed`、`partial_failed`、`interrupted`
- `total_steps`
- `success_steps`
- `failed_steps`
- `running_steps`
- `created_by`
- `payload_json`
- `result_json`
- `error_message`
- `created_at`
- `started_at`
- `finished_at`
- `updated_at`

### `offline_task_steps`

步骤/子任务表。

- `id`
- `task_id`
- `step_type`：如 `giga_sync`、`giga_image_download`
- `title`
- `status`
- `data_source_id`
- `data_source_name`
- `site`
- `batch_id`
- `progress_current`
- `progress_total`
- `payload_json`
- `result_json`
- `error_message`
- `started_at`
- `finished_at`
- `updated_at`

## 后端 API

- `POST /api/offline-tasks/giga-pull`
  - 入参：`data_source_ids: number[]`
  - 行为：创建父任务和每个数据源的拉品步骤，并异步启动执行。

- `GET /api/offline-tasks`
  - 支持按类型、状态分页查询。

- `GET /api/offline-tasks/{task_id}`
  - 返回父任务和步骤明细。

- `POST /api/offline-tasks/{task_id}/rerun`
  - 第一版只允许失败/中断的 `giga_pull` 任务重跑失败步骤。

## 执行流程

1. 商品中心选择多个启用的数据源。
2. 提交 `POST /api/offline-tasks/giga-pull`。
3. 后端创建父任务，按数据源创建 `giga_sync` 步骤。
4. 每个 `giga_sync` 步骤执行 `sync_giga_products(skip_existing=True, download_images=False)`。
5. 主数据成功后 upsert Product 草稿；图片先以 URL 候选保留。
6. 用户在商品详情确认主图/展示图后，StyleSnap、图片分析和 A+ 等节点按需下载已选图片。
7. 每个步骤完成后刷新父任务统计。
8. 商品中心刷新商品数据；任务中心展示离线任务进度。

## 前端

- 商品中心数据源选择改为 `mode="multiple"`。
- 没选数据源时不能提交拉品。
- 提交成功后提示任务 ID，并提供跳转任务中心。
- 新增“任务中心”菜单和页面。
- 任务中心第一版展示任务列表，展开后看步骤明细、batch、数据源、错误信息。

## 验证

- 后端 `compileall`。
- 前端 `npm run build`。
- 本地启动后验证：
  - 未选择数据源时页面提示不能拉品。
  - 多选数据源可创建一个父任务和多个步骤。
  - 任务列表能看到状态和步骤。
