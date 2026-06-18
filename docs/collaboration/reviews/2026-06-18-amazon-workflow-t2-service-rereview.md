# Amazon Workflow T2 Service Re-Review

日期：2026-06-18
Reviewer：镜花（agentKey: `jinghua`）
范围：`MSG-20260618-004` 听云按镜花 `NEEDS_FIX` 后的返工复审
结论：CODE_REVIEW / PASS

## 范围

- 本轮复审：
  - `MSG-20260618-004`
  - `docs/collaboration/reviews/2026-06-18-amazon-workflow-t2-service-code-review.md`
  - `docs/superpowers/specs/2026-06-18-amazon-product-workflow-prd.md`
- 使用索引：
  - `docs/project-index.md`
  - `docs/domain-index/product-flow.md`
- 审查文件：
  - `backend/app/product_tasks/actions.py`
  - `backend/app/product_tasks/workflow.py`
  - `backend/app/api/products.py`
  - `backend/app/api/schemas.py`
  - `scripts/test_project_rules.py`
  - `docs/domain-index/product-flow.md`

## 验证

- `make backend-compile`：PASS。
- `make test-project-rules`：PASS，41 tests。
- `git diff --check -- backend/app/product_tasks/actions.py backend/app/product_tasks/workflow.py backend/app/api/products.py backend/app/api/schemas.py scripts/test_project_rules.py docs/domain-index/product-flow.md docs/collaboration/inbox.md docs/collaboration/reviews/2026-06-18-amazon-workflow-t2-service-code-review.md`：PASS。
- 函数级样本：
  - `ProductImageAnalysisAction.reserve()` 真实调用后写 `workflow_node=image_analysis`、`workflow_status=processing`，`_workflow_state()` 返回 `open_task_center`。
  - `ProductListingGenerationAction.reserve()` 真实调用后写 `workflow_node=listing_generation`、`workflow_status=processing`，`_workflow_state()` 返回 `open_task_center`。
  - `flow_done/succeeded` 未导出时返回 `export_ready`；`catalog_exported=True` 时返回 `exported`，且 `stage` 仍为 `flow_done`、`node_type` 仍为 `done`、`primary_action` 仍为 `open_detail`。

## Findings

未发现 P0/P1 阻断问题。

## 已确认通过

- P0 返工已闭环：ProductTaskAction reserve 的真实写入面现在同步写 workflow 字段，不再依赖测试手工预填 `workflow_node/workflow_status`。
- ProductTaskAction 生命周期投影已覆盖失败、中断/取消和 Listing 完成：
  - image analysis / listing reserve -> 对应节点 `processing`。
  - failure / interrupted / canceled -> 对应节点 `failed`，`workflow_error` 使用业务错误文案。
  - Listing success -> `flow_done/succeeded`。
- P1 返工已闭环：`build_product_workflow(product, catalog_exported=True)` 只在 `flow_done/succeeded` 的导出上下文下返回 `work_status="exported"`，未新增导出 workflow node 或导出 action。
- `set_product_workflow()` 仍保持无 commit/flush/task run/外部副作用；事务边界沿用调用方 lifecycle。
- `_workflow_state()` 仍是 Product Workflow Service 的薄 wrapper；列表、详情、overview/work_status 同源。
- `GET /api/products/overview` 仍显式支持 `needs_initialization`，并预加载 workflow 字段以避免 async lazy-load。
- `scripts/test_project_rules.py` 已新增/加强行为样本，覆盖真实 reserve 路径、lifecycle writer 和 exported list work_status。

## 未覆盖 / 风险

- 本轮是代码级复审；未做页面 QA、未启动服务、未触发真实任务、未访问真实商品路径或外部平台。
- T3 仍依赖 `MSG-20260618-004` 完成后续提交/推送 gate；本结论只表示镜花代码 review 通过，不表示 T2 已提交/推送，也不替观止或用户做业务验收。
