# Task Center State and Action PRD Draft

状态：执行版；听云按本文实施，遇到产品口径或代码现实冲突时先写 `REQUEST` 给若命或直接向用户确认。
更新：2026-06-16
负责人：若命（产品经理）

## 1. 背景

当前 `/task-runs` 新任务中心已经承载 GIGA 拉品、图片分析、Listing、导出、A+、库存/价格同步、批量推进等任务。但页面直接展示底层 `task_runs.status`、`task_steps.status` 和 `summary_json`，导致用户看到的状态和可操作动作不一致。

现场问题样本：

- `#45 product_image_analysis product #93`：`task_runs.status=pending`，但 step 已是 `ready`。页面展示“待执行/等待规划”，且没有操作按钮。用户真实需要看到“排队中，等待执行器领取”，并可以唤醒执行器或取消。
- `#30 product_image_analysis product #93`：历史失败任务，后续已创建 `#45`。页面仍展示失败并给“重跑失败”，容易让用户误以为它还是当前要处理的任务。
- `#31 product_image_analysis product #94`：同上，后续已创建 `#44`。
- `#36 product_image_analysis product #101`：历史失败任务，后续已有 `#41`。旧任务不应继续作为当前失败任务刺激用户处理。

用户目标不是“看到更多技术字段”，而是能回答三个问题：

1. 这个任务现在到底在等什么、跑什么、失败什么？
2. 我现在能做什么？
3. 如果这是历史任务，它当前对应的新任务是哪一个？

## 2. 本轮目标

P0 目标：把任务中心状态和操作修到可理解、可处理、可追溯。

本轮完成定义：

- 后端 API 返回用户可理解的派生展示状态，而不是要求前端拼底层状态。
- 同一个业务对象的历史失败任务能识别“已被新任务取代”。
- 每个展示状态都有明确操作矩阵，页面只展示当前状态可执行的按钮。
- 默认列表优先展示当前任务和需要用户处理的任务；历史完成/已取代任务不再干扰主视图。
- #45/#30/#31/#36/#41 这类现场样本能按 PRD 展示。

## 3. 非目标

- 本轮不重写整个任务调度框架。
- 本轮不迁移更多业务任务到新任务中心。
- 本轮不改 Step 10、Amazon 模板、`template_mappings`、真实 ASIN、人工类目、已生成导出文件。
- 本轮不删除历史任务记录。
- 本轮不支持并发 worker pool；任务 runtime 仍保持当前串行策略。

## 4. 关键概念

### 4.1 运行状态和展示状态分离

底层运行状态继续保留在 `task_runs.status`、`task_groups.status`、`task_steps.status`。

页面只能使用后端返回的派生字段展示：

- `display_status`
- `display_status_label`
- `display_reason`
- `error_summary`
- `available_actions`
- `dedupe_key`
- `correlation_key`
- `current_effective_run_id`
- `superseded_by_run_id`

前端不再自行根据原始 `status` 猜“等待规划/重跑失败/执行中”。

### 4.2 框架层 key 设计

任务框架只定义抽象 key，不定义商品、店铺、类目、导出文件等业务语义。

框架层 key：

| key | 框架含义 | 谁生成 | 框架如何使用 |
|---|---|---|---|
| `dedupe_key` | 同一时间只允许一个 active run 的互斥键 | 业务域 action 实现 | 创建任务时查重、复用 active run、防重复执行 |
| `correlation_key` | 用于把历史 run 串起来的追踪键 | 业务域 action 实现 | 判断 current run、superseded、历史追溯 |
| `idempotency_key` | 同一次用户请求的幂等键，可选 | 调用方或业务域 action 实现 | 防止前端重复提交同一个创建请求 |
| `source_ref` | 创建来源引用，可选 | 调用方 | 展示创建来源、排查问题 |

规则：

- 框架只存储和比较这些 key，不解析 key 内部语义。
- key 格式对框架是不透明字符串；框架不能写 `if product_id...`、`if data_source_id...` 这类业务判断。
- 是否需要互斥、互斥粒度是什么，由业务域 action 决定。
- `superseded` 判断使用 `correlation_key`，不使用商品状态反推。
- `active run` 查重使用 `dedupe_key`，只看 run/step 是否仍处于 active 状态。
- 如果某类任务没有天然互斥对象，可以不提供 `dedupe_key`；框架仍能执行，只是不做同对象互斥。

P0 框架字段使用 `dedupe_key/correlation_key`；若现有代码短期已用了 `business_key`，可以作为兼容别名保留，但 PRD 新设计不再使用 `business_key` 作为框架概念。

### 4.3 任务框架和业务域的边界

任务框架不是商品状态机。任务框架只负责调度、锁、重试、取消、事件、进度和结果追踪；商品域负责解释“这个任务对商品意味着什么”，并在标准接口里实现商品状态变更。

边界：

| 层 | 负责 | 不负责 |
|---|---|---|
| Task Runtime Framework | 创建/保存 run/group/step，按依赖执行 step，claim/lock/heartbeat，retry/cancel/wake，记录 event，派生 task display status | 不硬编码商品步骤，不直接决定商品该显示“待选图/待竞品/待导出”，不把商品 status 当任务事实源 |
| Product Domain Action | 定义商品动作、前置条件、框架 key、payload、商品状态投影、成功/失败/取消后的商品状态变化 | 不自己实现调度循环，不自己管理锁，不绕过 task_runs 写异步执行状态 |
| Frontend | 展示后端给出的商品 workflow 和 task display status，触发允许的 action | 不推导 task 状态，不用商品状态反推 task 状态 |

一句话规则：

- 商品列表问 Product Domain：这个商品下一步该做什么。
- 任务中心问 Task Runtime：这个任务现在发生了什么、能做什么。
- 商品动作可以创建任务，但任务状态不能靠商品状态反推。

### 4.4 Action 抽象接口

框架以 action 为最小业务动作。每个 action 由业务域注册，框架按统一接口调度。

建议接口：

```python
class TaskAction:
    action_type: str

    async def validate(self, db, payload) -> None:
        """校验前置条件；失败时不创建任务。"""

    def dedupe_key(self, payload) -> str | None:
        """返回互斥键；框架只用于查重和 active run 复用，不解析语义。"""

    def correlation_key(self, payload) -> str | None:
        """返回追踪键；框架只用于历史串联和 superseded 判断，不解析语义。"""

    async def reserve(self, db, payload, run) -> None:
        """任务创建成功后，同一事务内写入业务域的排队态。"""

    def build_plan(self, payload) -> TaskRunPlan:
        """返回 groups/steps/payload/progress 计划，框架落表。"""

    async def on_step_start(self, db, context) -> None:
        """可选：step 开始时写业务域运行态。"""

    async def execute_step(self, db, context) -> dict:
        """执行业务 step，返回 result_json。"""

    async def on_step_success(self, db, context, result) -> None:
        """step 成功后写业务域成功态。"""

    async def on_step_failure(self, db, context, error) -> None:
        """step 失败后写业务域失败态和可读原因。"""

    async def on_cancel_requested(self, db, context, reason) -> None:
        """取消请求进入业务域；默认不硬杀当前外部调用。"""
```

P0 不要求一次性把所有任务类型都改成这个接口，但新的任务中心状态/操作修复必须按这个边界设计，不能继续在商品 API、task planner、task runtime、前端页面之间散落同一套状态判断。

### 4.5 商品域 action 首批实现

P0 首批只要求 product 类动作对齐：

| action_type | 业务对象 | dedupe_key | correlation_key | reserve 商品状态 | 成功投影 | 失败投影 |
|---|---|---|---|---|---|---|
| `product_image_analysis` | `Product` | `product_image_analysis:product:{product_id}` | `product:{product_id}:image_analysis` | `Product.status=step6_curating`、`current_step=5`、`error_message=图片分析已加入任务中心队列` | `Product.status=step6_done`，并同步 catalog item | `Product.status=failed`，`error_message=图片分析失败摘要` |
| `product_listing_generation` | `Product` | `product_listing_generation:product:{product_id}` | `product:{product_id}:listing_generation` | `Product.status=step5_listing`、`current_step=6`、`error_message=Listing 生成已加入任务中心队列` | `Product.status=completed` 或当前既有待导出态，并同步 catalog item | `Product.status=failed`，`error_message=Listing 生成失败摘要` |

注意：

- `reserve` 是“业务域知道动作已排队”，不是任务执行事实。任务是否排队、运行、失败、卡住，以 task_run/step 为准。
- 如果 task_run 后续被取消、取代或中断，Product Domain 必须通过接口收到事件并决定商品状态如何投影，不能由任务框架硬写商品字段。
- 商品 `workflow.stage/stage_status` 应由商品域根据商品事实和关联 task 当前 display status 派生；任务中心 `display_status` 只由 task 事实派生。两者可以互相引用 ID，但不能互相覆盖。

## 5. 表结构设计

### 5.1 现有表继续使用

现有四张表继续作为任务事实源：

#### `task_runs`

当前字段：

| 字段 | 用途 |
|---|---|
| `id` | 任务 ID |
| `task_type` | 任务类型 |
| `title` | 任务标题 |
| `status` | 底层运行状态 |
| `payload_json` | 创建参数 |
| `summary_json` | 任务结果摘要 |
| `created_by` | 创建来源 |
| `started_at` | 开始时间 |
| `finished_at` | 结束时间 |
| `created_at` | 创建时间 |
| `updated_at` | 更新时间 |

新增字段：

| 字段 | 类型 | 可空 | 说明 |
|---|---|---|---|
| `dedupe_key` | string(200) | yes | 框架互斥键；只用于 active run 查重和复用，不解析业务语义 |
| `correlation_key` | string(200) | yes | 框架追踪键；只用于 current/superseded/历史追溯，不解析业务语义 |
| `idempotency_key` | string(200) | yes | 创建请求幂等键，可选 |
| `source_ref` | string(200) | yes | 创建来源引用，可选 |
| `superseded_by_run_id` | int FK task_runs.id | yes | 被哪个新任务取代 |
| `superseded_at` | datetime | yes | 被取代时间 |
| `cancel_requested_at` | datetime | yes | 用户请求取消时间 |
| `cancel_requested_by` | string(100) | yes | 取消来源，默认 `user` |
| `cancel_reason` | text | yes | 取消原因 |

索引：

- `idx_task_runs_dedupe_key_status_created_at (dedupe_key, status, created_at)`
- `idx_task_runs_correlation_key_created_at (correlation_key, created_at)`
- `idx_task_runs_idempotency_key (idempotency_key)`
- `idx_task_runs_task_type_status_created_at (task_type, status, created_at)`
- `idx_task_runs_superseded_by_run_id (superseded_by_run_id)`

#### `task_groups`

现有字段保留。P0 不新增字段。

#### `task_steps`

现有字段保留。P0 不新增字段。

字段语义补充：

| 字段 | 语义 |
|---|---|
| `status=ready` | 已满足依赖，等待 runtime claim |
| `status=running` + `locked_until >= now` | 正在执行 |
| `status=running` + `locked_until < now` | 疑似卡住或服务中断 |
| `heartbeat_at` | 页面展示“最后心跳”来源 |
| `error_message` | `error_summary` 来源之一 |

#### `task_step_events`

现有字段保留。P0 不新增字段。

事件规范：

| event_type | 用途 |
|---|---|
| `status` | 状态变化，例如开始、重试、取消、中断 |
| `progress` | 进度变化 |
| `error` | 失败原因 |
| `action` | 用户动作，例如取消、唤醒、标记中断 |

### 5.2 历史数据回填规则

迁移脚本只回填任务元数据，不删除任务，不改业务商品状态。

回填逻辑：

1. 对 product 类任务，从 `payload_json.product_id`、`summary_json.product_id` 或 step_key `product:{id}:...` 提取 `product_id`。
2. 调用对应 Product Domain Action 的 key 生成器，写入 `dedupe_key` 和 `correlation_key`。
3. 对相同 `correlation_key` 的任务按 `created_at/id` 升序排列。
4. 如果旧任务是 `failed/interrupted`，且后面存在同 `correlation_key` 的任务，则旧任务写 `superseded_by_run_id=后续最近任务 id`。
5. 如果后续任务本身也失败，旧任务仍展示“已被新任务取代”，最新任务展示“失败”。
6. 不把 `succeeded` 任务标记为被失败重试取代；成功任务是历史成功，不参与当前失败判断。

## 6. 状态机设计

### 6.1 底层 run status

| run.status | 含义 |
|---|---|
| `pending` | 已创建，可能还未激活，或已有 ready step 等待 runtime |
| `running` | 至少一个 group/step 已进入执行链 |
| `succeeded` | 全部必要步骤成功 |
| `partial_failed` | 部分成功，部分失败，且任务允许部分成功 |
| `failed` | 任务失败 |
| `interrupted` | 服务中断、锁过期恢复或人工标记中断 |
| `paused` | 暂停，P0 暂不主动新增 |
| `canceled` | 用户取消 |
| `superseded` | 已被新任务取代 |

### 6.2 step status

| step.status | 含义 |
|---|---|
| `pending` | 等待前置 group/step 完成 |
| `ready` | 可执行，等待 runtime claim |
| `running` | 已被 runtime claim |
| `succeeded` | 执行成功 |
| `failed` | 执行失败 |
| `interrupted` | 中断，可重试 |
| `skipped` | 跳过 |
| `canceled` | 用户取消 |

### 6.3 展示状态 `display_status`

展示状态由后端派生，前端只负责渲染。

派生优先级从上到下：

| display_status | label | 条件 | display_reason |
|---|---|---|---|
| `superseded` | 已被新任务取代 | `superseded_by_run_id` 非空，或同 `correlation_key` 有更新任务 | `已创建新任务 #X` |
| `cancel_requested` | 正在取消 | `cancel_requested_at` 非空且仍有 running step | `已请求取消，等待当前步骤结束` |
| `canceled` | 已取消 | run.status=`canceled` | `用户已取消` |
| `stale_running` | 疑似卡住 | 有 running step 且 `locked_until < now` 或心跳超过阈值 | `执行锁已过期，可能服务中断` |
| `running` | 执行中 | 有 running step 且锁/心跳有效 | `正在执行：{step_label}` |
| `queued` | 排队中 | 有 ready step | `已就绪，等待执行器领取` |
| `waiting_dependency` | 等待前置步骤 | 有 pending step，但没有 ready/running/failed | `等待前置步骤完成` |
| `planned` | 待规划 | run 已创建但没有 group/step | `任务已创建，等待生成步骤` |
| `failed` | 失败 | run.status=`failed` 且没有更新任务取代 | `失败：{error_summary}` |
| `partial_failed` | 部分失败 | run.status=`partial_failed` | `部分完成，存在失败项` |
| `interrupted` | 已中断 | run.status=`interrupted` | `任务未完成，可重试或标记处理` |
| `paused` | 已挂起 | run.status=`paused` | `任务已挂起` |
| `succeeded` | 已完成 | run.status=`succeeded` | `任务完成` |

阈值：

- `stale_running` 默认阈值：`locked_until < now` 直接成立。
- 如果 `locked_until` 为空但 `heartbeat_at` 超过 10 分钟，也视为 `stale_running`。

## 7. 操作矩阵

`available_actions` 由后端返回，前端不自行判断。

动作枚举：

| action | 按钮文案 | 用途 |
|---|---|---|
| `view_detail` | 详情 | 展开/打开详情 |
| `refresh` | 刷新 | 重新拉取列表/详情 |
| `wake_runtime` | 唤醒执行器 | 对 ready/queued 任务调用 runtime kick |
| `cancel` | 取消 | 取消未执行或请求取消运行中任务 |
| `mark_interrupted` | 标记中断 | 处理 stale running |
| `retry_failed_steps` | 重试失败步骤 | 对当前失败任务重试失败/中断 step |
| `retry_step` | 重试此步骤 | 详情页针对单个 failed/interrupted step |
| `go_current_run` | 查看当前任务 | 跳转 superseded_by_run_id |
| `download_result` | 下载结果 | 导出任务成功或部分成功时下载 |
| `copy_error` | 复制错误 | 复制错误摘要 |

状态到操作：

| display_status | 主操作 | 次操作 | 不允许 |
|---|---|---|---|
| `planned` | 刷新 | 取消、详情 | 重试 |
| `waiting_dependency` | 刷新 | 取消、详情 | 重试 |
| `queued` | 唤醒执行器 | 取消、详情、刷新 | 重试 |
| `running` | 详情 | 刷新、取消 | 重试、标记中断 |
| `stale_running` | 标记中断 | 唤醒执行器、详情、刷新 | 下载 |
| `failed` | 重试失败步骤 | 复制错误、详情、刷新 | 查看当前任务 |
| `partial_failed` | 详情 | 下载结果（如有）、重试失败步骤、复制错误 | 无脑重跑整个任务 |
| `interrupted` | 重试失败步骤 | 详情、刷新 | 下载 |
| `cancel_requested` | 详情 | 刷新 | 重试、再次取消 |
| `canceled` | 详情 | 复制错误（如有） | 重试，除非业务入口重新创建新任务 |
| `superseded` | 查看当前任务 | 查看历史、复制错误 | 重试 |
| `succeeded` | 下载结果（仅导出） | 详情、刷新 | 重试失败步骤 |

按钮展示原则：

- 列表每行最多展示 3 个显式按钮：主操作、详情、更多。
- 非当前任务不展示“重试失败步骤”。
- `succeeded` 非导出任务只展示“详情”，不展示 disabled 的“重跑”。
- `copy_error` 放到更多菜单，不占主按钮。

## 8. API 设计

### 8.1 列表接口

`GET /api/task-runs`

新增查询参数：

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `view` | `current/history/all` | `current` | current 隐藏 superseded 和大部分 succeeded |
| `display_status` | string | 空 | 按展示状态过滤 |
| `task_type` | string | 空 | 任务类型 |
| `dedupe_key` | string | 空 | 框架互斥 key |
| `correlation_key` | string | 空 | 框架追踪 key |
| `q` | string | 空 | run id、商品 id、标题模糊搜索 |
| `page` | int | 1 | 页码 |
| `page_size` | int | 20 | 每页数量 |

响应新增字段：

```json
{
  "id": 45,
  "task_type": "product_image_analysis",
  "task_type_label": "图片分析",
  "title": "图片分析：商品 #93",
  "object_type": "product",
  "object_id": 93,
  "object_label": "商品 #93",
  "dedupe_key": "product_image_analysis:product:93",
  "correlation_key": "product:93:image_analysis",
  "status": "pending",
  "display_status": "queued",
  "display_status_label": "排队中",
  "display_reason": "已就绪，等待执行器领取",
  "current_step_label": "图片分析",
  "progress_current": 0,
  "progress_total": 1,
  "progress_percent": 0,
  "error_summary": null,
  "latest_event_message": null,
  "last_heartbeat_at": null,
  "superseded_by_run_id": null,
  "current_effective_run_id": 45,
  "available_actions": ["view_detail", "refresh", "wake_runtime", "cancel"],
  "created_at": "2026-06-16T14:59:57",
  "updated_at": "2026-06-16T14:59:57"
}
```

### 8.2 详情接口

`GET /api/task-runs/{run_id}`

详情返回同列表字段，并返回 groups/steps/events。每个 group/step 也要有展示字段：

```json
{
  "id": 51,
  "step_type": "product_image_analysis",
  "step_label": "图片分析",
  "status": "ready",
  "display_status": "queued",
  "display_status_label": "排队中",
  "display_reason": "已就绪，等待执行器领取",
  "error_summary": null,
  "available_actions": ["retry_step"],
  "attempt_count": 0,
  "max_attempts": 2
}
```

### 8.3 唤醒执行器

`POST /api/task-runs/{run_id}/wake`

行为：

- 仅允许 `queued/stale_running`。
- 对 queued：调用 `kick_task_runtime()`。
- 对 stale_running：先不自动改状态；只触发 recover 或 kick，并返回最新展示状态。
- 写 `task_step_events.event_type=action`，message=`用户唤醒执行器`。

响应：

```json
{
  "status": "ok",
  "run": { "...": "TaskRunDetailResponse" }
}
```

### 8.4 取消任务

`POST /api/task-runs/{run_id}/cancel`

请求：

```json
{ "reason": "用户取消" }
```

行为：

- `planned/waiting_dependency/queued`：直接把 run/group/未开始 step 标为 `canceled`。
- `running`：写 `cancel_requested_at`，展示为 `cancel_requested`；当前 step 不做硬杀，避免破坏外部调用和数据库一致性。当前 step 完成后不再推进后续 pending step。
- `succeeded/failed/superseded/canceled`：返回 400，说明不可取消。
- 写 action event。

### 8.5 标记中断

`POST /api/task-runs/{run_id}/mark-interrupted`

请求：

```json
{ "reason": "锁超时，人工标记中断" }
```

行为：

- 仅允许 `stale_running`。
- 把 stale running steps 标为 `interrupted`。
- 刷新 group/run 状态。
- 写 action event。

### 8.6 重试

沿用并收敛现有接口：

- `POST /api/task-runs/{run_id}/retry-failed`
- `POST /api/task-runs/steps/{step_id}/retry`

规则：

- 只允许当前有效任务。
- `superseded` 历史任务不允许重试，返回 400：`该任务已被 #X 取代，请处理当前任务`。
- `attempt_count >= max_attempts` 时，按钮隐藏或接口返回明确错误：`已达到最大尝试次数，请重新创建任务或调整配置`。

## 9. 页面设计

页面：`/task-runs`

### 9.1 顶部结构

顶部只保留必要信息：

- 标题：`任务中心`
- 右侧：刷新按钮
- 筛选：任务类型、状态、视图、搜索框

视图：

| 视图 | 含义 |
|---|---|
| 当前任务 | 默认。展示 active、failed、partial_failed、interrupted、stale_running、cancel_requested |
| 历史任务 | 展示 succeeded、canceled、superseded |
| 全部任务 | 展示全部，用于排查 |

### 9.2 列表字段

列表列：

| 列名 | 内容 | 规则 |
|---|---|---|
| ID | `#45` | 可点击详情 |
| 对象 | `图片分析 / 商品 #93` | task_type_label + object_label |
| 状态 | `排队中` | 使用 `display_status_label` |
| 当前步骤 | `图片分析` | 使用 `current_step_label` |
| 进度 | `0/1` + 进度条 | 不要只显示百分比 |
| 摘要 | `已就绪，等待执行器领取` 或错误摘要 | 单行，超出省略，hover 可看完整 |
| 更新时间 | `updated_at` + 心跳 | running 显示 heartbeat |
| 操作 | 状态矩阵按钮 | 不展示 disabled 噪音按钮 |

### 9.3 详情展开

详情区块：

1. 基本信息：run id、dedupe key、correlation key、创建来源、创建/开始/结束时间。
2. 当前解释：`display_status_label`、`display_reason`、`error_summary`。
3. Groups/Steps 表：group title、step label、底层状态、展示状态、尝试次数、心跳、错误摘要、操作。
4. Events：默认展示最近 10 条，支持展开全部。

详情页/展开中可以展示底层 raw status，但必须放在“调试信息”区域，不作为用户主文案。

## 10. 文案规则

必须替换的错误文案：

| 旧文案 | 新文案 |
|---|---|
| 等待规划 | 按场景显示：待规划 / 排队中 / 等待前置步骤 |
| 重跑失败 | 重试失败步骤 |
| 待执行 | 排队中，或待规划 |
| 执行中但无心跳 | 疑似卡住 |

错误摘要提取：

- 优先取当前失败 step 的 `error_message`。
- 去掉 Python 异常前缀可读化，但保留关键错误类型。
- 最长 80 个中文字符；完整错误放详情。

示例：

原始：

`RuntimeError: VLM 未返回任何真实图片分析结果... APITimeoutError: Request timed out...`

列表摘要：

`VLM 未返回真实图片分析结果，Contact Sheet 兜底超时`

## 11. 现场样本验收

### 11.1 #45

当前事实：

- run status: `pending`
- step status: `ready`
- product: `#93`

期望：

- `display_status=queued`
- label：`排队中`
- 摘要：`已就绪，等待执行器领取`
- 操作：`唤醒执行器`、`取消`、`详情`
- 不显示：`等待规划`、`重试失败步骤`

### 11.2 #30

当前事实：

- product: `#93`
- 旧任务失败
- 后续已有 #45

期望：

- `display_status=superseded`
- label：`已被新任务取代`
- 摘要：`已创建新任务 #45`
- 操作：`查看当前任务 #45`、`查看历史`、`复制错误`
- 不显示：`重试失败步骤`

### 11.3 #31

当前事实：

- product: `#94`
- 旧任务失败
- 后续已有 #44

期望：

- `display_status=superseded`
- 摘要：`已创建新任务 #44`
- 不显示：`等待规划`、`重试失败步骤`

### 11.4 #36 和 #41

当前事实：

- product: `#101`
- #36 是更旧失败任务
- #41 是更新失败任务

期望：

- #36：`display_status=superseded`，摘要 `已创建新任务 #41`。
- #41：如果没有更新任务，`display_status=failed`，摘要为图片分析失败原因，操作为 `重试失败步骤`、`复制错误`、`详情`。

## 12. 工程边界

允许修改：

- `backend/app/models/models.py`
- `backend/app/api/schemas.py`
- `backend/app/api/task_runs.py`
- `backend/app/task_runtime/constants.py`
- `backend/app/task_runtime/scheduler.py`
- `backend/app/task_planners/*`
- `frontend/src/api/index.ts`
- `frontend/src/pages/TaskRunCenter.tsx`
- 项目规则测试文件
- 必要的迁移脚本或启动期 schema 补齐逻辑

禁止修改：

- `data/`
- `backend/data/`
- Amazon 模板文件
- `backend/app/pipeline/template_mappings/*.json`
- `backend/app/pipeline/step10_amazon_template.py`
- 真实商品确认态、真实 ASIN、人工类目、已生成素材

## 13. 验证要求

后端验证：

```bash
python -m py_compile backend/app/api/task_runs.py backend/app/task_runtime/scheduler.py
make test-project-rules
```

前端验证：

```bash
cd frontend && npm run build
```

API 样本验证：

```bash
curl -sS 'http://127.0.0.1:8190/api/task-runs?page=1&page_size=100' | jq '.items[] | select(.id==45 or .id==30 or .id==31 or .id==36 or .id==41) | {id, display_status, display_status_label, display_reason, available_actions, dedupe_key, correlation_key, superseded_by_run_id}'
```

页面验证：

- 打开 `http://127.0.0.1:3190/task-runs`。
- 默认视图不应被大量历史 succeeded/superseded 淹没。
- #45 展示排队中，并有唤醒/取消。
- #30/#31/#36 展示已被新任务取代，不提供重试。
- #41 展示失败原因和重试失败步骤。

## 14. 给听云的实施顺序

严格按顺序执行，前一步没完成不要跳到下一步。

1. 阅读本文和 `docs/superpowers/specs/2026-06-16-product-task-action-refactor-prd.md`，确认任务框架和商品域解耦边界。
2. 补 `task_runs` 框架字段：`dedupe_key`、`correlation_key`、`idempotency_key`、`source_ref`、`superseded_by_run_id`、`superseded_at`、`cancel_requested_at`、`cancel_requested_by`、`cancel_reason`。如项目当前没有 Alembic，使用现有项目约定的启动期 schema 补齐方式，但必须可重复执行。
3. 建立 task action 抽象和注册表；框架层只调用 action 接口，不解析商品字段。
4. 按商品任务重构 PRD，把 `product_image_analysis` 和 `product_listing_generation` 接到 ProductTaskAction。
5. 在 task run API 层实现展示派生：`display_status`、`display_status_label`、`display_reason`、`error_summary`、`available_actions`、`current_effective_run_id`、`superseded_by_run_id`。
6. 实现操作接口：`wake`、`cancel`、`mark-interrupted`，并收敛现有 retry 接口，禁止 superseded 历史任务重试。
7. 更新 `/task-runs` 前端：状态、摘要、按钮全部使用后端派生字段；不再用原始 `status/summary_json` 推导主文案。
8. 补项目规则或测试，锁住：ready step 显示 queued、superseded 不显示 retry、任务中心响应包含派生字段。
9. 用 #45/#30/#31/#36/#41 样本完成 API 和页面验收。

DONE_CLAIMED 必须包含：

- 改动文件清单。
- 后端 compile、`make test-project-rules`、前端 build 结果。
- #45/#30/#31/#36/#41 的 API 输出摘要。
- `/task-runs` 页面展示证据。
- 未覆盖风险。

## 15. P0 默认产品决策

1. 运行中任务点击“取消”时，不硬杀当前外部调用，只标记“正在取消”，等当前 step 结束后停止后续步骤。
2. 默认视图隐藏 `succeeded/canceled/superseded`，只在“历史任务”里看。
3. `catalog_export` 成功任务只保留“下载结果/详情”，不提供任何重跑旧任务按钮。
4. 如实现中发现这些默认决策和现有代码冲突，或仍需确认字段、状态、按钮、异常口径，听云写 `REQUEST` 给若命或直接向用户确认；不要自行改产品边界。
