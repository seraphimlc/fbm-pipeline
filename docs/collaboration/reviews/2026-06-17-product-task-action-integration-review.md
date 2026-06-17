# Product Flow / Task Runtime Integration Review

日期：2026-06-17
作者：若命（agentKey: `ruoming`）
范围：商品主流程与新任务框架的整合边界，重点看 `product_image_analysis`、`product_listing_generation`、`product_bulk_advance`、商品列表 workflow、任务中心跳转。

## 结论

当前实现方向基本符合“商品域实现 action，任务框架只调度执行事实”的架构目标，但还不能视为商品流程与任务框架完全收口。

P0 问题：ProductTaskAction 入队后的商品 workflow 可能被误判为“已中断”。这会直接影响商品列表主状态和主按钮，是用户路径级问题。

## 符合预期的部分

1. `backend/app/task_runtime/actions.py` 定义了通用 `TaskAction` 协议、`TaskRunPlan`、`TaskGroupPlan`、`TaskStepPlan` 和注册表。框架层没有在协议里绑定商品字段。

2. `backend/app/product_tasks/actions.py` 已将 `product_image_analysis`、`product_listing_generation` action 化：
   - `validate`
   - `dedupe_key`
   - `correlation_key`
   - `reserve`
   - `build_plan`
   - `execute_step`
   - `on_step_success`
   - `on_step_failure`
   - `on_step_interrupted`
   - `on_cancel_requested`

3. `backend/app/task_runtime/scheduler.py` 只通过 worker registry 和 `action_for(step.step_type)` 调用 action 生命周期钩子，没有直接 import `Product` 或商品状态常量来决定任务状态。

4. `backend/app/task_planners/product_image_analysis.py` 和 `backend/app/task_planners/product_listing.py` 已退化为 wrapper，入口最终走 `create_product_action_runs()`。

5. 商品列表返回 `workflow` 字段，前端主按钮优先消费 `product.workflow.primary_action`，并通过 `related_correlation_key` 跳转任务中心。

6. `product_bulk_advance` 已改成新任务中心的父任务，worker 只提交图片分析或 Listing 子任务，不再在读接口动态伪造父任务追踪到待导出。

## P0 - 新任务中心入队商品会被误判为已中断

文件：

- `backend/app/product_tasks/actions.py`
- `backend/app/api/products.py`

证据：

- `ProductImageAnalysisAction.reserve()` 写入：
  - `Product.status = STEP6_CURATING`
  - `Product.current_step = 5`
  - `Product.error_message = "图片分析已加入任务中心队列"`
- `ProductListingGenerationAction.reserve()` 写入：
  - `Product.status = STEP5_LISTING`
  - `Product.current_step = 6`
  - `Product.error_message = "Listing 生成已加入任务中心队列"`
- `_is_stale_running_product()` 的豁免条件是：`product.status in RUNNING_STATUSES and "新任务" in product.error_message`
- 新 task runtime 不登记旧 `pipeline.engine.is_running(product.id)`。

代码级样本：

```bash
cd backend
.venv/bin/python - <<'PY'
from types import SimpleNamespace
from app.api.products import _workflow_state
from app.models.status import STEP6_CURATING, STEP5_LISTING

for status, step, msg in [
    (STEP6_CURATING, 5, '图片分析已加入任务中心队列'),
    (STEP5_LISTING, 6, 'Listing 生成已加入任务中心队列'),
    (STEP6_CURATING, 5, '图片分析已加入新任务中心队列'),
]:
    product = SimpleNamespace(
        id=999999,
        status=status,
        current_step=step,
        error_message=msg,
        competitor_asin='B000TEST',
        catalog_item=None,
    )
    print(status, msg, '=>', _workflow_state(product, catalog_exported=False))
PY
```

实际结果：

- `"图片分析已加入任务中心队列"` -> `work_status = interrupted`
- `"Listing 生成已加入任务中心队列"` -> `work_status = interrupted`
- 只有包含 `"新任务"` 的文案才进入 queued/open_task_center。

影响：

- 商品刚入新任务中心，商品列表可能显示“已中断”，主操作变成“重试”。
- 用户会误以为任务失败或中断，实际 task_run 可能只是 queued/running。
- 这正好破坏我们想要的边界：商品流程展示不应被旧内存 pipeline running map 误导。

建议修复方向：

- 不要靠中文文案包含 `"新任务"` 判断新任务中心排队态。
- 商品 workflow 应使用明确字段或状态语义，例如：
  - `Product.status in {STEP6_CURATING, STEP5_LISTING}` 且 `error_message` 表示任务中心入队时，直接显示 queued/open_task_center；
  - 或 reserve 写入结构化 marker；
  - 或 workflow 查询/引用 active task_run 的 `correlation_key` 只读状态，但不要在商品页反推或修改 task_run。
- 项目规则需加代码级样本，锁住 ProductTaskAction reserve 后 workflow 必须是 queued/open_task_center，不是 interrupted。

## P1 - 商品 workflow 仍然集中在 `products.py`

文件：

- `backend/app/api/products.py`
- `docs/superpowers/specs/2026-06-16-product-task-action-refactor-prd.md`

PRD 建议 `backend/app/product_tasks/workflow.py` 承接商品 workflow 派生，但当前 `_workflow_state()`、`_current_task_status()`、workbench status、旧错误关键词、任务中心跳转语义仍集中在 `products.py`。

影响：

- 商品 API 文件继续承担过多领域逻辑。
- 后续要支持 TikTok/Amazon 强隔离、任务中心跳转、商品动作矩阵时容易继续堆判断。
- 这不是立即阻断本轮 P0 的问题，但应该作为下一轮结构收敛任务。

建议：

- 把 `_workflow_state()`、`_workflow_for_step()`、`_product_workbench_status()`、`_product_list_work_status()` 迁到 `backend/app/product_tasks/workflow.py`。
- `products.py` 只负责查询、组装响应和调用 domain helper。

## P1/P2 - action 去重仍有 step join 兼容路径

文件：

- `backend/app/product_tasks/actions.py`

`_existing_active_run()` 先按 `TaskRun.dedupe_key` 查 active run；如果没有，再构建 plan 并 JOIN `TaskStep` 按 `step_key` 查 active step。

这条 fallback 可能是为了兼容未回填的旧数据，但从长期设计看不理想：

- action 创建去重应该依赖 run-level opaque key。
- 框架不应为了业务互斥回头理解 step_key。
- 当前全局查询规约已经不鼓励用 JOIN/复杂查询弥补模型缺口。

建议：

- 如果确实为旧数据兼容，给它加注释和明确移除条件。
- 确认 `backfill_product_action_task_run_keys()` 已可靠后，移除 step JOIN fallback。
- 后续考虑 DB 级唯一/约束或应用级幂等键，避免靠查询猜。

## P2 - 旧 pipeline 入口仍有残留

文件：

- `backend/app/api/products.py`
- `backend/app/pipeline/engine.py`

Step 5/6 已迁到 task runtime，`engine.start_pipeline()` 也拒绝 `start_step <= 6`。但 `products.py` 里仍有一些旧 `enqueue_pipeline()` / `is_running()` 分支用于旧步骤或兼容路径。

这不阻断 P0，因为本轮没有要求一次性迁移全部商品流程；但它解释了为什么商品 workflow 仍容易被旧运行态污染。

建议：

- 下一轮先清掉商品列表和 ProductTaskAction 相关路径对旧 `is_running()` 的依赖。
- Step 2-4、竞品搜索/抓详情等是否迁入新任务框架，需要单独 PRD，不要顺手改。

## 建议给镜花复审的问题

1. 是否确认 P0 误判成立。
2. 最小修复应该放在 `_is_stale_running_product()`、`reserve()` 文案，还是 Product workflow 结构化字段。
3. `_existing_active_run()` 的 step JOIN fallback 是否可暂留；如果暂留，需要哪些注释/测试/移除条件。
4. 商品 workflow 是否必须先迁到 `product_tasks/workflow.py`，还是等 P0 修完后另开结构任务。
