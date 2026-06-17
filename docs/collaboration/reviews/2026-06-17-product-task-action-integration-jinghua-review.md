# Product Task Action Integration Code Review

日期：2026-06-17
Reviewer：镜花（agentKey: `jinghua`）
范围：`MSG-20260617-016` 商品流程与任务框架整合复审
结论：CODE_REVIEW / NEEDS_FIX

## 范围

- 已读：
  - `docs/collaboration/reviews/2026-06-17-product-task-action-integration-review.md`
  - `docs/superpowers/specs/2026-06-16-product-task-action-refactor-prd.md`
  - `docs/project-index.md`
  - `docs/domain-index/product-flow.md`
  - `docs/domain-index/task-runtime.md`
- 审查文件：
  - `backend/app/product_tasks/actions.py`
  - `backend/app/api/products.py`
  - `backend/app/task_runtime/scheduler.py`
  - `backend/app/task_planners/product_bulk_advance.py`
  - `backend/app/task_runtime/product_bulk_advance_workers.py`
  - `frontend/src/pages/ProductList.tsx`
  - `scripts/test_project_rules.py`

## 验证

- 代码级样本复现 P0：
  - `STEP6_CURATING/current_step=5/error_message="图片分析已加入任务中心队列"` -> `workflow.stage_status="interrupted"`、主操作 `retry`。
  - `STEP5_LISTING/current_step=6/error_message="Listing 生成已加入任务中心队列"` -> `workflow.stage_status="interrupted"`、主操作 `retry`。
  - 只有文案包含 `"新任务"` 时才进入 `queued/open_task_center`。
- 已核实：
  - scheduler 只通过 `action_for(step.step_type)` 调用 action hook，未 import `Product` 或商品状态常量。
  - `product_bulk_advance` 已作为 task_run 父任务提交子任务，未看到任务中心读接口动态伪造父任务进度。

## Findings

### P0：ProductTaskAction reserve 后商品 workflow 会误判为已中断

- 位置：
  - `backend/app/product_tasks/actions.py:215`
  - `backend/app/product_tasks/actions.py:350`
  - `backend/app/api/products.py:167`
  - `backend/app/api/products.py:472`
- 事实：
  - `ProductImageAnalysisAction.reserve()` 写 `product.status = STEP6_CURATING`、`product.current_step = 5`、`product.error_message = "图片分析已加入任务中心队列"`。
  - `ProductListingGenerationAction.reserve()` 写 `product.status = STEP5_LISTING`、`product.current_step = 6`、`product.error_message = "Listing 生成已加入任务中心队列"`。
  - `_is_stale_running_product()` 只豁免 `RUNNING_STATUSES` 且 `error_message` 包含 `"新任务"` 的商品；reserve 文案不包含 `"新任务"`。
  - `_workflow_state()` 先调用 `_is_stale_running_product()`，因此入队商品会在旧 `pipeline.engine.is_running(product.id)` 为 false 时被判为 `interrupted`。
- 影响：
  - 商品刚进入新任务中心就可能在商品列表显示“已中断”，主操作变成“重试”。
  - 用户会误以为任务失败或中断，实际 task_run 可能只是 queued/running。
  - 这破坏 PRD 边界：商品 workflow 不应被旧内存 pipeline running map 判定新 task runtime 的运行事实。
- 最小修复建议：
  - 不要靠中文文案 `"新任务"` 判断新任务中心排队态。
  - 增加明确 helper，例如 `_is_product_task_action_queued(product)`，至少识别 `STEP6_CURATING/current_step=5` 的图片分析入队态和 `STEP5_LISTING/current_step=6` 的 Listing 入队态。
  - `_is_stale_running_product()` 应先排除这些新任务中心入队态；`_current_task_status()` 和 `_workflow_state()` 应同源使用该 helper，返回 `queued/open_task_center`。
  - 后续更稳的方案是 reserve 写入结构化 marker 或 workflow 只读引用 active `task_runs.correlation_key`，但 P0 可以先用最小 helper 收口。
- 必须新增测试：
  - 代码级样本：`ProductImageAnalysisAction.reserve()` 投影后的等价 product 调 `_workflow_state()`，必须是 `stage_status="queued"`、`primary_action="open_task_center"`，不能是 `interrupted/retry`。
  - 同样覆盖 `ProductListingGenerationAction.reserve()`。
  - 测试应覆盖 `_current_task_status()` 或商品列表消费的状态文案，防止列表说明仍显示“运行状态已中断”。

## 已确认通过

- `TaskAction` 边界方向基本符合 PRD：`backend/app/task_runtime/scheduler.py` 未直接 import 商品模型或商品状态常量来决定 task 状态，只通过 action registry 调用生命周期 hook。
- `product_image_analysis` / `product_listing_generation` 已有 `validate/dedupe_key/correlation_key/reserve/build_plan/execute_step/on_step_success/on_step_failure/on_step_interrupted/on_cancel_requested` 边界。
- `product_bulk_advance` 当前作为新任务中心父任务，worker 提交图片分析/Listing 子任务；没有看到 task_runs 列表/detail 路径动态伪造商品进度。
- 前端 `ProductList.tsx` 主操作优先消费后端 `workflow.primary_action`，`open_task_center` 会带 `related_correlation_key` 跳转任务中心。

## 非阻断建议

- `_existing_active_run()` 的 step JOIN fallback 可以暂留为旧数据兼容路径，但应补注释说明这是 legacy fallback，移除条件是 ProductTaskAction task_runs 的 `dedupe_key/correlation_key` backfill 覆盖完成并经 QA 确认。长期应回到 run-level key / DB 幂等约束。
- 商品 workflow 仍集中在 `backend/app/api/products.py`，本轮不必阻断 P0 修复；建议下一轮结构任务迁到 `backend/app/product_tasks/workflow.py`，让 `products.py` 只做查询和响应组装。
- `product_bulk_advance` planner/worker 仍引用旧 `pipeline.engine.is_running()` 作兼容判断，暂不阻断本轮，但后续清理旧 pipeline 运行态依赖时应统一处理。

## 未覆盖 / 风险

- 本轮未启动真实服务或点击页面；P0 由函数级样本复现。
- 当前 `scripts/test_project_rules.py` 只锁住 reserve 文案和 action 文件存在，未锁住 reserve 后的 workflow 行为，因此无法防止此类商品列表误判。
