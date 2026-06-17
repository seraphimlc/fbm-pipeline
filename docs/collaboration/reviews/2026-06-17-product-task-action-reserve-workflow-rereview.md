# ProductTaskAction Reserve Workflow Re-Review

日期：2026-06-17
Reviewer：镜花（agentKey: `jinghua`）
范围：`MSG-20260617-018` ProductTaskAction reserve workflow 返工复验
结论：CODE_REVIEW / PASS

## 范围

- 已按索引建立范围：
  - `docs/project-index.md`
  - `docs/domain-index/product-flow.md`
  - `docs/domain-index/task-runtime.md`
- 审查文件：
  - `backend/app/api/products.py`
  - `backend/app/product_tasks/actions.py`
  - `scripts/test_project_rules.py`
  - `docs/domain-index/product-flow.md`

## 验证

- 函数级样本：
  - `STEP6_CURATING/current_step=5/error_message="图片分析已加入任务中心队列"` -> `stage=image_analysis`、`stage_status=queued`、`primary_action=open_task_center`。
  - `STEP5_LISTING/current_step=6/error_message="Listing 生成已加入任务中心队列"` -> `stage=listing_generation`、`stage_status=queued`、`primary_action=open_task_center`。
- `make backend-compile`：PASS。
- `make test-project-rules`：PASS，37 tests。
- `git diff --check -- backend/app/api/products.py scripts/test_project_rules.py docs/domain-index/product-flow.md docs/collaboration/inbox.md`：PASS。

## Findings

未发现 P0/P1 阻断问题。

## 已确认通过

- `backend/app/api/products.py` 新增 `_product_task_action_queued_stage(product)`，用 `status/current_step/error_message` 识别 ProductTaskAction reserve 后的图片分析和 Listing 入队态。
- `_is_stale_running_product()` 先排除上述入队态，旧 `pipeline.engine.is_running(product.id)` 不再把它们判成 `interrupted/retry`。
- `_current_task_status()` 与 `_workflow_state()` 共用同一个 helper；两个 reserve 等价状态都返回 `queued/open_task_center`，不再显示“运行状态已中断”。
- `scripts/test_project_rules.py` 新增 `test_product_task_action_reserve_states_are_not_marked_interrupted`，覆盖图片分析和 Listing 两个 reserve 等价状态。
- `docs/domain-index/product-flow.md` 已同步当前口径：ProductTaskAction reserve 入队态属于新任务中心排队态，不能由旧 pipeline running map 判为中断。

## 非阻断建议

- 当前 helper 仍依赖 reserve 文案中的 `"任务中心队列"` 作为 marker。作为本轮 P0 最小修复可以接受，因为 reserve 写入点和 workflow 识别点已被规则测试同时锁住；后续结构化治理时应优先改为显式字段、task_run correlation 或统一 workflow 投影，减少中文文案耦合。

## 未覆盖 / 风险

- 本轮是代码级复验；未启动真实服务、未点击页面、未触发真实任务、未访问 GIGA/A+/StyleSnap/导出链路。
- `backend/app/api/products.py` 仍承载较多 workflow 组装逻辑；这是结构债，不阻断本轮 P0 修复。
