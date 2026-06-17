# Task Runtime Rewrite: GIGA Pull V1

日期：2026-06-13
状态：设计草案，待用户确认后再派发实现任务

## 目标

新增一套任务调度框架，用新表承载可跟踪、可恢复、可重试的任务执行。第一版只迁移 GIGA 拉品。其它离线任务（库存同步、价格同步、A+、导出、批量推进）暂时继续走旧 `offline_tasks` 框架。

新框架第一版只做串行执行：一次只执行一个 ready step。先把稳定性、恢复能力和页面可解释性做好，不做并发、不做 worker pool、不做复杂调度优化。

## 核心边界

业务事件负责生成任务图；任务框架只负责执行任务图。

- 业务事件：例如用户点击“同步店铺商品”。
- Planner：把业务事件转换成父任务、子任务组和 step。
- Runtime：只负责依赖判断、claim、执行、心跳、状态流转、重试和恢复。
- Worker：执行具体 step，例如拉详情 chunk、拉库存 chunk、聚合商品。
- 业务数据表：仍是事实源，例如 GIGA snapshot、Product 草稿等。任务表只做调度和审计。

不要继续把复杂业务编排塞进旧 `backend/app/services/offline_tasks.py`。

## 数据表

### `task_runs`

父任务，一次用户发起的业务操作。

- `id`
- `task_type`：第一版只支持 `giga_pull`
- `title`
- `status`：`pending` / `running` / `succeeded` / `failed` / `partial_failed` / `interrupted` / `paused`
- `payload_json`
- `summary_json`
- `created_by`
- `started_at`
- `finished_at`
- `created_at`
- `updated_at`

### `task_groups`

子任务组，表达一个阶段。

- `id`
- `task_run_id`
- `group_key`：`plan` / `details` / `inventory` / `prices` / `finalize` / `aggregate` / `materialize`
- `title`
- `status`
- `sort_order`
- `depends_on_group_keys_json`
- `failure_policy`：V1 默认 `require_all_success`
- `retry_policy`：V1 默认 `failed_steps_only`
- `progress_current`
- `progress_total`
- `summary_json`
- `started_at`
- `finished_at`
- `created_at`
- `updated_at`

### `task_steps`

具体可执行节点。

- `id`
- `task_run_id`
- `task_group_id`
- `step_key`
- `step_type`
- `status`：`pending` / `ready` / `running` / `succeeded` / `failed` / `interrupted` / `skipped`
- `sort_order`
- `payload_json`
- `result_json`
- `error_message`
- `progress_current`
- `progress_total`
- `attempt_count`
- `max_attempts`
- `locked_by`
- `locked_until`
- `heartbeat_at`
- `started_at`
- `finished_at`
- `created_at`
- `updated_at`

### `task_step_events`

执行日志和状态变化。

- `id`
- `task_run_id`
- `task_group_id`
- `task_step_id`
- `event_type`：`status` / `progress` / `log` / `error`
- `message`
- `data_json`
- `created_at`

## GIGA 拉品任务图

第一版固定为阶段串行：

```text
plan
  -> details chunks
  -> inventory chunks
  -> price chunks
  -> finalize
  -> aggregate
  -> materialize
```

### `plan`

Step type：`giga_pull_plan`

职责：

- 分页读取 GIGA SKU list。
- 拿远端 total。
- 生成本次 batch_id。
- 生成 SKU manifest 和 chunk plan。
- 写入后续 details / inventory / prices 组的 chunk steps。

### `details`

Step type：`giga_pull_detail_chunk`

职责：

- 按 100-200 个 SKU 一个 chunk 拉详情。
- 保存 raw detail、SKU 基础信息、图片 URL 候选。
- 不做 item/group 闭包聚合。

### `inventory`

Step type：`giga_pull_inventory_chunk`

职责：

- 按 chunk 拉库存。
- 保存库存 snapshot。
- 保留分仓库存数据。

### `prices`

Step type：`giga_pull_price_chunk`

职责：

- 按 chunk 拉价格。
- 保存价格 snapshot。

### `finalize`

Step type：`giga_pull_finalize_snapshot`

职责：

- 检查 details / inventory / prices 是否完整。
- 汇总缺失 SKU、失败 SKU 和可继续策略。
- V1 默认 `require_all_success`，即有 chunk 失败则不进入聚合。

### `aggregate`

Step type：`giga_pull_aggregate_items`

职责：

- 基于完整 SKU snapshot 统一做 item/group 闭包聚合。
- 生成 `giga_items` / `giga_groups`。
- 这里才处理关联 SKU / 变体聚合。

### `materialize`

Step type：`giga_pull_materialize_products`

职责：

- 从聚合后的 GIGA 数据生成或更新 Product 草稿。
- 保持当前产品边界：拉品只保存图片 URL 候选，不全量下载图片。

## 串行调度规则

V1 调度器只做串行：

1. 查找当前 task_run 下第一个 `ready` step。
2. 用条件更新 claim：`status = ready` 且锁已过期。
3. claim 成功后置为 `running`，写 `locked_by`、`locked_until`、`heartbeat_at`。
4. 执行 step worker。
5. worker 定期写 progress 和 heartbeat。
6. 成功置 `succeeded`。
7. 失败置 `failed`，记录 error 和 event。
8. 每个 step 结束后重新计算 group / run 状态。
9. 当前 group 全部成功后，释放下一个 group 的第一个 step 为 `ready`。

不做并发。details 全部完成后才开始 inventory；inventory 全部完成后才开始 prices；prices 全部完成后才进入 finalize。

## 恢复与重试

任务状态必须以 DB 为准，不能依赖内存 task。

服务启动时：

- 扫描 `running` 且 `locked_until` 已过期的 step。
- 标记为 `interrupted`，或按策略重新置为 `ready`。
- 重新计算 group / run 状态。

重试规则：

- 支持重跑失败 step。
- 支持重跑失败 group 中的失败 step。
- 不重跑已经 `succeeded` 的 chunk。
- plan 失败可重跑 plan。
- finalize / aggregate / materialize 失败可单独重跑。

## 页面

新任务中心只展示新框架任务，不展示旧 `offline_tasks` 历史任务。

父任务列表展示：

- 任务名
- 状态
- 当前阶段
- 总体进度
- 最近心跳
- 成功/失败/中断摘要

任务详情展示：

- 子任务组列表
- 每个组的进度：如 `详情 8/12`、`库存 8/12`、`价格 7/12`
- 展开组后展示 chunk step
- 失败 step 展示错误摘要和重跑入口

## 旧框架关系

旧框架保留，未迁移任务继续走旧框架：

- GIGA 库存同步
- GIGA 价格同步
- A+ 生成
- Amazon 导出
- 批量推进

新旧任务没有展示关系。新任务中心只展示新表任务。旧任务不需要在新页面继续展示。

## 验收标准

- 新建 GIGA 拉品任务后，DB 中有 `task_runs`、`task_groups`、`task_steps`。
- 页面能看到父任务、子任务组和 step。
- plan 能生成 chunk steps。
- 串行执行顺序正确：details -> inventory -> prices -> finalize -> aggregate -> materialize。
- 任一 chunk 失败后，后续依赖组不启动。
- 可只重跑失败 chunk。
- 服务重启后不会出现永久 running；过期 running step 可恢复或中断。
- 不全量下载 GIGA 图片。
- 其它旧任务仍可走旧框架，不受新框架影响。

## 非目标

- 不做并发。
- 不做 worker pool。
- 不迁移历史旧任务。
- 不同时迁移库存同步、价格同步、A+、导出、批量推进。
- 不接 TikTok Open API。
- 不改变 Amazon Step 10 / template mappings。
