# Product Task Action Refactor PRD Draft

状态：执行版；听云按本文实施，遇到产品口径或代码现实冲突时先写 `REQUEST` 给若命或直接向用户确认。
更新：2026-06-16
负责人：若命（产品经理）
关联文档：`docs/superpowers/specs/2026-06-16-task-center-state-action-prd.md`

## 1. 一句话结论

商品相关任务必须改成“商品域实现 TaskAction，任务框架调度 TaskAction”的结构。

任务框架不认识商品状态；商品域不自己实现异步调度。两者只通过 action 接口交互。

## 1.1 2026-06-17 补充口径：任务中心与商品流程边界

任务中心不是商品流程页面。

- 任务中心负责异步执行事实：任务类型、运行状态、进度、失败原因、事件、心跳、当前 step，以及取消、重试、唤醒、标记中断、详情等任务级操作。
- 商品流程负责业务状态和用户决策：待选图、待选竞品、待生成 Listing、待导出、已导出等商品业务阶段，以及选图、确认竞品、生成文案、导出等商品动作。
- 商品页可以展示最近任务摘要，并通过 `related_task_run_id`、`dedupe_key` 或 `correlation_key` 跳转任务中心。
- 任务中心不能用商品状态定义 task display status；商品流程也不能用 task display status 直接覆盖商品业务状态。
- 商品任务成功/失败/取消后，必须由 ProductTaskAction 的生命周期钩子明确投影商品业务状态，不能由任务框架自动猜商品下一阶段。

## 2. 当前问题

听云当前实现把问题做成了商品状态流转补丁：

- 商品列表通过 `Product.status/current_step/error_message` 派生 `workflow`。
- 创建图片分析和 Listing 任务时同步回写商品状态。
- 前端商品列表按 `workflow.primary_action` 给按钮。

这只能缓解商品列表显示不一致，不能解决任务中心和任务框架问题。

真正的问题是：

- 商品域逻辑、任务创建逻辑、任务执行逻辑、状态展示逻辑散在 `products.py`、`task_planners/*`、`task_runtime/*`、前端页面里。
- 任务框架没有统一 action 抽象，导致每迁一个商品任务都要手写一套 planner/worker/status 同步。
- 商品状态和任务状态互相反推，容易出现商品显示“待启动”，但 task_run 已经 ready/running 的错位。

## 3. 设计目标

P0 目标：

- 建立 Product Domain Action 层，先接管 `product_image_analysis` 和 `product_listing_generation`。
- Task Runtime Framework 只负责通用调度，不写商品专用判断。
- 商品状态变化只发生在 Product Domain Action 的生命周期钩子里。
- 商品列表 `workflow` 由商品域派生，但可以引用关联 task 的 `display_status`；不能反推 task 状态。

非目标：

- 不一次性重写全部商品流程。
- 不迁移 A+、导出、竞品搜索到同一批 P0。
- 不改 Step 10、Amazon 模板、`template_mappings`。
- 不碰真实 ASIN、人工类目、已生成素材或导出产物。

## 4. 分层设计

### 4.1 Task Runtime Framework

框架层只负责：

- 接收 action 创建请求。
- 调用 action 的 `validate`、`dedupe_key`、`correlation_key`、`reserve`、`build_plan`。
- 落表 `task_runs/task_groups/task_steps/task_step_events`。
- 串行 claim ready step。
- 执行 step 时调用 action 的 step handler。
- 维护 lock、heartbeat、retry、cancel、wake、superseded。
- 派生 task center 的 `display_status` 和 `available_actions`。

框架层禁止：

- import 商品状态常量来决定任务展示状态。
- 读取 `Product.status` 来判断 task_run 是否 queued/running/failed。
- 在 scheduler 里硬编码 `product_id`、`current_step`、`competitor_asin`。
- 直接把商品改成待导出、失败、挂起。

### 4.2 Product Domain Action

商品域 action 负责：

- 定义商品动作类型。
- 校验商品是否满足前置条件。
- 生成 `dedupe_key/correlation_key`。
- 在任务创建成功时投影商品排队态。
- 业务 step 开始/成功/失败/取消时投影商品状态。
- 给商品列表提供 `workflow.stage/stage_status/label/primary_action`。

商品域 action 禁止：

- 自己启动后台 task loop。
- 自己管理 step lock 和 heartbeat。
- 绕过 `task_runs` 表记录异步执行事实。
- 用商品状态覆盖任务中心的 task display status。

## 5. ProductTaskAction 接口

建议新增文件：

- `backend/app/task_runtime/actions.py`：定义通用 action 协议和注册表。
- `backend/app/product_tasks/actions.py`：注册商品域 actions。
- `backend/app/product_tasks/workflow.py`：商品列表 workflow 派生。
- `backend/app/product_tasks/state_projection.py`：商品状态投影函数。

接口：

```python
class TaskAction:
    action_type: str

    async def validate(self, db, payload) -> None:
        """创建任务前校验；失败则不落 task_run。"""

    def dedupe_key(self, payload) -> str | None:
        """同一时刻互斥键；框架只比较，不解析。"""

    def correlation_key(self, payload) -> str | None:
        """历史追踪键；框架只比较，不解析。"""

    async def reserve(self, db, payload, run) -> None:
        """task_run 已创建，同事务内写业务域排队态。"""

    def build_plan(self, payload) -> TaskRunPlan:
        """返回 groups/steps。"""

    async def execute_step(self, db, context) -> dict:
        """执行业务 step。"""

    async def on_step_success(self, db, context, result) -> None:
        """成功后投影业务状态。"""

    async def on_step_failure(self, db, context, error) -> None:
        """失败后投影业务状态。"""

    async def on_cancel_requested(self, db, context, reason) -> None:
        """取消请求后投影业务状态。"""
```

P0 可以只实现接口子集，但文件边界要先放对。

## 6. P0 商品 actions

### 6.1 `product_image_analysis`

业务对象：`Product`

输入 payload：

| 字段 | 必填 | 说明 |
|---|---|---|
| `product_id` | 是 | 商品 ID |
| `created_by` | 否 | 创建来源 |
| `force` | 否 | 是否强制重新分析，默认 false |

Key：

| key | 值 |
|---|---|
| `dedupe_key` | `product_image_analysis:product:{product_id}` |
| `correlation_key` | `product:{product_id}:image_analysis` |

Validate：

- 商品必须存在。
- 商品必须已完成图片选择和竞品选择所需前置条件。
- 若存在同 `dedupe_key` 的 active run，返回现有 run，不新建。

Reserve：

- `Product.status = step6_curating`
- `Product.current_step = 5`
- `Product.error_message = 图片分析已加入任务中心队列`
- 同步 `CatalogProduct.status`，但不修改导出状态、ASIN、人工类目。

Plan：

- run type: `product_image_analysis`
- group: `image_analysis`
- step: `product_image_analysis`
- max attempts: 2

Success projection：

- `Product.status = step6_done`
- `Product.current_step = 5`
- 清空图片分析相关错误。
- 同步 catalog item 状态。
- 如系统要自动接 Listing，不由此 action 直接执行；应创建下一段 `product_listing_generation` action。

Failure projection：

- `Product.status = failed`
- `Product.current_step = 5`
- `Product.error_message = 图片分析失败摘要`
- task step 保存完整错误。

### 6.2 `product_listing_generation`

业务对象：`Product`

输入 payload：

| 字段 | 必填 | 说明 |
|---|---|---|
| `product_id` | 是 | 商品 ID |
| `created_by` | 否 | 创建来源 |
| `force` | 否 | 是否强制重新生成，默认 false |

Key：

| key | 值 |
|---|---|
| `dedupe_key` | `product_listing_generation:product:{product_id}` |
| `correlation_key` | `product:{product_id}:listing_generation` |

Validate：

- 商品必须存在。
- 图片分析必须完成，或已有可用于 Listing 的图片/分析结果。
- 若存在同 `dedupe_key` 的 active run，返回现有 run，不新建。

Reserve：

- `Product.status = step5_listing`
- `Product.current_step = 6`
- `Product.error_message = Listing 生成已加入任务中心队列`
- 同步 `CatalogProduct.status`。

Plan：

- run type: `product_listing_generation`
- group: `listing`
- step: `product_listing_generation`
- max attempts: 2

Success projection：

- `Product.status = completed`
- `Product.current_step = 6`
- 清空 Listing 生成相关错误。
- 同步 catalog item，商品进入待导出。

Failure projection：

- `Product.status = failed`
- `Product.current_step = 6`
- `Product.error_message = Listing 生成失败摘要`
- task step 保存完整错误。

## 7. 商品 workflow 派生

商品列表 `workflow` 不是任务框架字段，是 Product Domain 的视图模型。

字段：

| 字段 | 说明 |
|---|---|
| `stage` | 商品当前业务阶段，如 `image_review`、`competitor_select`、`image_analysis`、`listing_generation`、`export` |
| `stage_status` | 业务阶段状态，如 `pending`、`queued`、`running`、`failed`、`succeeded` |
| `label` | 给商品列表看的业务文案 |
| `primary_action` | 商品列表主按钮 |
| `primary_action_label` | 主按钮文案 |
| `action_reason` | 状态说明 |
| `related_task_run_id` | 关联当前 task_run，可空 |

规则：

- 如果商品当前阶段有关联 active task_run，`workflow.stage_status` 可以引用 task_run 的 `display_status` 映射，但不能修改 task_run。
- 商品列表点击“任务中心”时，应带上 `related_task_run_id` 或筛选条件，进入任务中心定位对应任务。
- `work_status` 老字段只做兼容筛选，不再作为新设计主字段。

## 8. 旧逻辑收敛要求

需要收敛的旧位置：

| 当前位置 | 问题 | 目标 |
|---|---|---|
| `backend/app/api/products.py` | 商品 API 里混有状态判断、任务创建、workflow 派生 | 只保留入口编排，具体动作交给 ProductTaskAction |
| `backend/app/task_planners/product_image_analysis.py` | planner 直接写商品状态并创建 steps | 迁到 `ProductImageAnalysisAction.reserve/build_plan` |
| `backend/app/task_planners/product_listing.py` | 同上 | 迁到 `ProductListingGenerationAction.reserve/build_plan` |
| `backend/app/task_runtime/product_image_analysis_workers.py` | worker 自己决定商品成功/失败态 | 迁到 action `execute_step/on_step_success/on_step_failure` |
| `backend/app/task_runtime/product_listing_workers.py` | 同上 | 迁到 action lifecycle |
| `frontend/src/pages/ProductList.tsx` | 商品列表直接处理过多 action 分支 | 只渲染后端 workflow，不推导任务状态 |

P0 不要求删光旧文件，但新增逻辑必须走 action 边界，旧函数只能作为 wrapper 调用 action。

## 9. 与任务中心 PRD 的关系

任务中心 PRD 定义：

- task 表字段。
- task display status。
- task available actions。
- wake/cancel/mark-interrupted/retry/download。
- superseded/current run 展示。

本文件定义：

- 商品域如何实现 TaskAction。
- 商品状态什么时候变。
- 商品 workflow 如何引用 task，但不反推 task。

两份文档不能互相覆盖：

- 任务中心展示以 task_run 为事实源。
- 商品列表展示以 Product Domain workflow 为事实源。
- 两者通过 `related_task_run_id`、`dedupe_key`、`correlation_key` 建立关联。

## 10. P0 验收样本

### 图片分析排队

操作：为 product #93 创建图片分析 action。

期望：

- 创建或复用一个 `task_type=product_image_analysis` 的 task_run。
- task_run 返回 `dedupe_key`、`correlation_key`。
- Product 投影为图片分析排队态。
- 商品列表主按钮为“任务中心”，并能定位到该 task_run。
- 任务中心 #45 展示 `排队中`，不是“待启动/等待规划”。

### 历史图片分析失败被新任务取代

样本：`#30 -> #45`、`#31 -> #44`、`#36 -> #41`。

期望：

- 旧 run 通过 `correlation_key` 识别为 superseded。
- 旧 run 不暴露 retry。
- 当前 run 才暴露当前可用 action。

### Listing 生成排队

操作：图片分析完成后创建 Listing action。

期望：

- Product 投影为 Listing 排队态。
- task_run 独立展示 queued/running/failed/succeeded。
- Product workflow 可以显示“Listing 排队中”，但不替代 task_run display status。

## 11. 给听云的实施顺序

1. 先不要继续扩展商品 `workflow`。
2. 先建通用 TaskAction 协议和注册表。
3. 把 `product_image_analysis` 迁成 ProductTaskAction。
4. 把 `product_listing_generation` 迁成 ProductTaskAction。
5. 再接任务中心 PRD 的 display/action 派生。
6. 最后调整商品列表 workflow 只消费 Product Domain 输出。

每一步完成后都要能跑：

```bash
cd backend && .venv/bin/python -m compileall -q app
make test-project-rules
cd frontend && npm run build
```

如果实现过程中发现现有代码结构和本文冲突，或仍需确认字段、状态、按钮、异常口径，听云必须写 `REQUEST` 给若命或直接向用户确认；不要自行改产品边界。
