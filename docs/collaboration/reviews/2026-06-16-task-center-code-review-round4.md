# Task Center Code Review Round 4

日期：2026-06-16
Reviewer：若命（agentKey: `ruoming`）
范围：任务框架核心、任务中心 API/前端、ProductTaskAction、批量推进任务。
结论：当前实现仍不能交给观止 QA。不是文案问题，是任务语义、分页口径、superseded 识别和父子任务完成语义存在结构性问题。

## Review 边界

本轮已看：

- `backend/app/task_runtime/scheduler.py`
- `backend/app/task_runtime/actions.py`
- `backend/app/task_runtime/display.py`
- `backend/app/task_runtime/events.py`
- `backend/app/task_runtime/registry.py`
- `backend/app/api/task_runs.py`
- `frontend/src/pages/TaskRunCenter.tsx`
- `frontend/src/api/index.ts`
- `backend/app/product_tasks/actions.py`
- `backend/app/task_planners/product_image_analysis.py`
- `backend/app/task_planners/product_listing.py`
- `backend/app/task_planners/product_bulk_advance.py`
- `backend/app/task_runtime/product_bulk_advance_workers.py`
- 相关 PRD：
  - `docs/superpowers/specs/2026-06-16-task-center-state-action-prd.md`
  - `docs/superpowers/specs/2026-06-16-product-task-action-refactor-prd.md`
  - `docs/superpowers/specs/2026-06-13-task-runtime-giga-pull-design.md`

本轮未做：

- 未执行真实 GIGA 拉品、导出、A+、商品状态推进。
- 未做浏览器页面全链路 QA。
- 未审完所有非任务中心页面交互。

## P0 Findings

### 1. `superseded` SQL 逻辑会把无关任务误判为“已被取代”

位置：

- `backend/app/api/task_runs.py:398-413`
- `backend/app/task_planners/giga_pull.py:86`
- `backend/app/task_planners/catalog_export.py:156`

问题：

`_superseded_sql_condition()` 里有 `step_key_superseded` 兜底逻辑：只要 failed/interrupted 任务里某个 `step_key` 后续又出现在更大的 `task_run_id`，旧任务就被视为 superseded。

这在商品 action 的 `step_key=product:{id}:...` 上勉强能工作，但它被用在所有 task_run 上。通用任务的 step_key 并不全局唯一：

- GIGA 拉品的 plan step 固定是 `step_key="plan"`。
- 导出任务的 step 固定是 `step_key="catalog_export_template"`。

结果：一个失败的 GIGA 拉品或导出任务，只要后面有任何同类/甚至同 step_key 的新任务，就可能在 current/history 视图里被错误标成 superseded，即使它不是同一个店铺、同一批商品、同一业务对象。

影响：

- current 视图会漏掉真实失败任务。
- history 视图会出现错误的“已被新任务取代”。
- 用户会被引导去处理并不存在的“当前任务”。
- 这不是 UI 表达问题，是任务事实错误。

修复要求：

- 删除通用 `step_key` superseded 兜底，或严格限制在明确 action 类型且 `correlation_key` 可推导的商品任务范围内。
- 通用框架层不能靠解析 step_key 推业务对象。
- 对 GIGA 拉品、导出、A+、库存/价格同步这类任务，如果需要 superseded，必须由业务 planner 写入明确 `correlation_key`，再由框架比较不透明 key。
- 补测试：两个不同 GIGA 拉品 run 都含 `step_key=plan` 时，后一个不能让前一个自动 superseded，除非两者有相同 correlation_key 且业务规则允许。

### 2. `display_status` 筛选仍存在 scan-limit + 内存分页路径

位置：

- `backend/app/api/task_runs.py:774-804`
- `backend/app/task_runtime/display.py:1-20`
- `frontend/src/pages/TaskRunCenter.tsx:440-449`

问题：

后端虽然给常用状态加了一部分 SQL 条件，但仍保留 fallback：

```python
scan_query = base_query.limit(DISPLAY_SCAN_LIMIT)
...
filtered_responses.append(response)
...
items=filtered_responses[start:end]
total=len(filtered_responses)
```

前端状态筛选里包含 `stale_running`，而 `display.py` 没把 `stale_running` 放进 DB pageable，`_display_status_sql_condition()` 也没有 SQL 条件。这意味着用户筛“疑似卡住”时，仍然只扫前 1000 条再内存过滤、内存分页。

影响：

- 超过 scan limit 后会漏任务。
- `total/filtered_total` 不是数据库真实总数。
- 用户看到的分页和统计仍然不可信。
- 这正是之前明确禁止的反面 case：内存过滤分页。

修复要求：

- 页面暴露的每一个 `display_status` 都必须有明确策略：
  - 能 SQL 化的，必须 SQL 化。
  - 暂不能 SQL 化的，不要放进普通筛选；或接口必须明确返回 limited 口径且页面文案不能写成真实 total。
- `stale_running` 可以 SQL 化：running step 的 `locked_until < now`，或无 lock 但 `heartbeat_at < now - threshold`。
- `cancel_requested` 也应 SQL 化：`cancel_requested_at is not null` 且仍存在 running step。
- 删除普通路径里的内存分页；确实要保留排障路径，也要单独命名成 debug/limited，不要作为任务中心主列表能力。

### 3. `display_status` SQL 条件和真实展示状态不一致

位置：

- `backend/app/api/task_runs.py:250-323`
- `backend/app/api/task_runs.py:447-498`

问题：

`_run_display()` 的展示状态优先级是根据 step 事实推导：

- 有过期 running step -> `stale_running`
- 有 running step -> `running`
- 有 ready step -> `queued`
- 有 pending step -> `waiting_dependency`

但 `_display_status_sql_condition()` 不是同一套语义：

- `running` 只看 `TaskRun.status == running`，没有排除 stale，也没有要求存在非过期 running step。
- `queued` 要求 `TaskRun.status == pending` 且存在 ready step。
- `waiting_dependency` 要求 `TaskRun.status == pending`，但真实展示可能因为 group/run 刷新后处于 running。

影响：

- 用户筛“执行中”可能看到展示为“排队中”或“疑似卡住”的任务。
- 用户筛“排队中”可能漏掉 run.status 已是 running 但当前 step 是 ready 的任务。
- 这会让状态筛选和列表标签互相打架。

修复要求：

- 把展示状态定义成单一来源：`_run_display()` 和 SQL 条件必须用同一张状态矩阵实现。
- SQL 条件不能只看 `task_runs.status`；必须按当前 step 事实匹配。
- 给每个前端可筛状态加样例测试：接口返回的每一条 item，其 `display_status` 必须等于请求的 `display_status`。

### 4. 任务中心框架层仍在解析商品语义，违反 PRD 边界

位置：

- `backend/app/api/task_runs.py:137-190`
- `backend/app/api/task_runs.py:644-674`
- PRD：`docs/superpowers/specs/2026-06-16-task-center-state-action-prd.md` 4.2/4.3

问题：

任务中心 API 里有这些商品域解析：

- 从 `correlation_key` 正则提取 `product_id`。
- 从 `payload_json`、`summary_json`、`step_key` 推断 product_id。
- 根据 product_id 拼 `product:{id}:image_analysis` / `product:{id}:listing`。
- `_load_runs_for_lineage()` 只针对 `product_image_analysis/product_listing_generation` 写特殊 lineage 查询。

PRD 明确要求框架层 key 是不透明字符串，框架不能写 `if product_id...` 这类业务判断。当前实现把商品域补丁塞回 task center API，短期能救几个样本，长期会让每个业务域都往框架里加 if。

影响：

- 任务中心无法作为通用任务框架稳定扩展。
- 商品任务和通用任务的 superseded/lineage 行为不一致。
- 后续 TikTok、导出、A+、GIGA 店铺任务都会继续复制这种业务泄漏。

修复要求：

- 框架层只比较落表的 `dedupe_key/correlation_key/idempotency_key/source_ref`。
- 历史数据缺 key 的修复应该做一次 migration/backfill 或业务域 resolver 插件，而不是在 task center API 写商品正则。
- 如果保留兼容逻辑，必须移动到 Product Domain adapter，框架通过接口调用，不直接解析商品语义。

### 5. Product image success hook 在当前 step 完成前创建并启动 Listing 子任务，存在状态分裂和竞态

位置：

- `backend/app/product_tasks/actions.py:238-276`
- `backend/app/product_tasks/actions.py:474-568`
- `backend/app/task_runtime/scheduler.py:249-265`

问题：

图片分析 worker 成功后，`ProductImageAnalysisAction.on_step_success()` 内部直接调用 `create_product_action_runs()` 创建 Listing run。`create_product_action_runs()` 会 `db.commit()`，并在 `auto_start=True` 时 `kick_task_runtime()`。

但此时 scheduler 还没有把当前 image step 写成 `succeeded`，也还没有写 `result_json`。真实顺序是：

1. image worker 执行业务成功。
2. success hook 创建 Listing run、commit、kick runtime。
3. 之后 scheduler 才把 image step 标记 succeeded。

影响：

- Listing 任务可能在图片分析 task_run/step 仍显示 running 时就已经开始。
- 如果 success hook 创建 Listing 后，scheduler 后续写当前 step 结果失败，会出现商品/Listing 已推进，但 image task 事实未完成的分裂状态。
- success hook 里 commit 子任务，使 runtime 对“当前 step 成功”和“后续任务创建”无法原子化。

修复要求：

- 不要在当前 step 成功投影里直接 commit 并 kick 下一段任务。
- 两种可接受方向：
  - 把 image -> listing 做成同一个 task_run 内的后续 group/step，依赖由 runtime 管。
  - 或 scheduler 支持 step 成功落表后再执行 after-commit follow-up，且 follow-up 失败要有独立可见事件/状态。
- 最低限度：`on_step_success()` 不得提前启动下一 run；必须让当前 step 的成功事实先落表。

### 6. 批量推进父任务只负责“提交子任务”，却会显示成任务完成

位置：

- `backend/app/task_runtime/product_bulk_advance_workers.py:87-118`
- `backend/app/task_planners/product_bulk_advance.py:130-187`
- `backend/app/api/task_runs.py:549-589`

问题：

`product_bulk_advance_product` step 只做一件事：创建 `product_image_analysis` 或 `product_listing_generation` 子任务。创建成功后它返回 success，scheduler 会把批量推进 step/run 标为 succeeded。

但用户理解的“批量推进商品到待导出”不是“子任务已入队”，而是这些商品真的走到待导出。当前实现用 `_with_product_bulk_advance_progress()` 在读取列表时动态查商品状态，往 `summary_json` 塞 `latest_counts`，试图补真实进度。

这导致任务事实和业务完成度分裂：

- task_run 可能是 succeeded。
- rows 里商品仍然 `in_progress/failed/paused`。
- 页面主状态会显示“任务完成”，但明细告诉用户还没完成。

影响：

- 用户无法信任任务中心状态。
- 观止无法用 task_run.status 判断批量推进是否完成。
- 失败/重试/取消语义都不清楚：父任务成功后，子任务失败应该算谁失败？

修复要求：

- 明确产品语义：
  - 如果该任务只是“批量提交生成任务”，标题和状态必须改成“提交完成”，不要叫“推进到待导出”。
  - 如果该任务语义是“推进到待导出”，父任务必须追踪子任务完成，不能提交即成功。
- 推荐改法：把批量推进变成 task group 编排，每个商品的 image/listing 是真实 step 或依赖 group；父 run 的状态由所有商品真实终态决定。
- 不要用读接口动态改 `summary_json` 来弥补任务事实缺失。

## P1 Findings

### 7. `max_attempts` 字段展示了，但 runtime 没有执行约束

位置：

- `backend/app/models/models.py:233-234`
- `backend/app/task_runtime/scheduler.py:368-397`
- `backend/app/task_runtime/scheduler.py:400-412`
- `frontend/src/pages/TaskRunCenter.tsx:629`

问题：

`TaskStep.max_attempts` 被建模、planner 也设置了 `max_attempts=2/3`，前端还展示 `attempt_count/max_attempts`。但 `retry_step()` 只判断状态是否可重试，没有判断 `attempt_count >= max_attempts`。

影响：

- 页面展示“2/2”后仍可继续重试。
- max_attempts 变成假字段，用户和 QA 都会误判系统保护能力。

修复要求：

- `retry_step()` 必须拒绝超过 max_attempts 的 step，或 PRD 明确 max_attempts 只用于自动重试、不限制人工重试。
- 如果允许人工超限，前端和 API 文案必须显示“人工重试不受 max_attempts 限制”，不要现在这样误导。

### 8. `dedupe_key` 只靠 select-before-insert，不能防并发重复创建

位置：

- `backend/app/product_tasks/actions.py:427-454`
- `backend/app/product_tasks/actions.py:492-523`

问题：

`create_product_action_runs()` 先查 active run，再插入新 run。没有唯一约束、没有业务对象锁、没有事务级互斥。两个并发请求可以同时查不到 active run，然后各自插入同一 `dedupe_key` 的任务。

影响：

- 用户连点、前端重试、两个入口同时触发时，仍可能生成重复图片分析/Listing 任务。
- 商品状态会被多个 run 竞争投影，后续 superseded 也会变复杂。

修复要求：

- 对 Product action 至少在同一事务中锁商品行，或引入 active-run guard 表/唯一约束策略。
- API 需要并发创建测试：同一 product_id 并发请求只产生一个 active run。
- 如果短期不做 DB 约束，至少要在 action 创建入口加 `SELECT ... FOR UPDATE` 锁定业务对象。

### 9. 前端操作只展示一个 primary action，会隐藏同状态下其它可用动作

位置：

- `frontend/src/pages/TaskRunCenter.tsx:527-586`

问题：

前端从 `available_actions` 里挑一个 `primaryAction`，只渲染一个主按钮。其它动作只有 cancel/refresh/copy_error 进入更多菜单。比如一个任务如果同时有 `download_result` 和 `retry_failed_steps`，只会显示优先级更高的 download，重试入口可能消失。

影响：

- 后端动作矩阵给了多个可用动作，前端实际只暴露其中一个。
- 用户遇到 partial_failed catalog_export 时可能只能下载，不能直接重试失败步骤。

修复要求：

- 前端必须按动作矩阵渲染所有允许动作，或后端明确区分 `primary_action` 和 `secondary_actions`。
- 不要在前端用硬编码优先级吞掉后端给出的可用动作。

### 10. 商品 workflow 仍未引用关联 task_run，无法让用户从商品跳到具体任务

位置：

- `backend/app/api/products.py:411-691`
- PRD：`docs/superpowers/specs/2026-06-16-product-task-action-refactor-prd.md` 7

问题：

PRD 要求商品 workflow 可以引用关联当前 task 的 `related_task_run_id` 或筛选条件。当前 `_workflow_state()` 仍主要靠 `Product.status/current_step/error_message` 推断，只返回 `open_task_center`，没有具体 task_run_id。

影响：

- 商品列表点击“任务中心”不能定位到该商品当前 run。
- 用户仍需要在任务中心搜索/猜是哪条任务。
- 商品状态和任务事实没有形成可靠连接。

修复要求：

- Product Domain workflow 需要查询或接收当前 active task_run，并返回 `related_task_run_id` / `related_correlation_key`。
- 前端打开任务中心时带 `#run_id` 或 `correlation_key`。

## P2 Findings

### 11. `_with_product_bulk_advance_progress()` 在读接口里改 response summary，职责不清

位置：

- `backend/app/api/task_runs.py:549-589`

问题：

这个函数在 list/detail API 中读取商品现状，然后改写 response 的 `summary_json`。虽然没有写 DB，但语义上把“任务执行结果”和“当前商品投影”混在一个字段里。

影响：

- `summary_json` 在 DB 和 API response 中含义不同。
- 前端/QA 不知道 rows 是任务完成时的结果，还是读取时动态结果。

修复要求：

- 动态投影应放到独立字段，例如 `derived_summary` / `domain_projection`。
- `summary_json` 保持任务执行时写入的审计结果，不要在 response 层改写。

### 12. 任务框架状态常量和展示状态缺少集中测试矩阵

位置：

- `backend/app/task_runtime/constants.py`
- `backend/app/api/task_runs.py:214-323`
- `backend/app/api/task_runs.py:447-498`

问题：

底层 status、display status、available actions、SQL filter 分散在多个函数里，没有一个测试矩阵证明它们一致。

修复要求：

- 建一个轻依赖测试矩阵：
  - 输入 run/step facts。
  - 期望 display_status。
  - 期望 available_actions。
  - 期望 SQL filter 能包含/排除同一状态。

## 本轮修复门槛

听云下一轮不要直接“解释现状”。需要先给出修复计划，再改代码。

最低修复项：

1. 修掉 P0-1：删除或收窄 step_key superseded 误判。
2. 修掉 P0-2/P0-3：状态筛选不能再走主路径 scan-limit 内存分页；SQL 条件必须和展示状态一致。
3. 修掉 P0-4：框架层商品语义解析移出或降级为 Product Domain adapter，不再散在 task center API。
4. 修掉 P0-5/P0-6：明确父子任务语义，不能让“提交子任务成功”冒充“业务推进完成”。

验证要求：

- `make backend-compile`
- `make test-project-rules`
- `make frontend-build`
- `git diff --check`
- API 样本：
  - `/api/task-runs?display_status=queued` 返回的每条 item 都是 `display_status=queued`。
  - `/api/task-runs?display_status=running` 返回的每条 item 都是 `display_status=running`，不含 stale/queued。
  - 两个不同 GIGA 拉品 run 共享 `step_key=plan` 时，不会互相 superseded。
  - 批量推进任务如果只是提交子任务，页面和 API 不得显示成“推进到待导出已完成”。

## 给听云的执行提醒

- 不要再用“受控 scan limit”包装内存分页。
- 不要再用商品正则补框架设计缺口。
- 不要把创建子任务当作父任务业务完成。
- 不要只修页面文案。这里的问题在后端事实模型和状态矩阵。
- 做不明白先 `REQUEST/BLOCKED`，不要硬写。
