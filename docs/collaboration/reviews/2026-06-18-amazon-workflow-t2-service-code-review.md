# Amazon Workflow T2 Service Code Review

日期：2026-06-18
Reviewer：镜花（agentKey: `jinghua`）
范围：`MSG-20260618-004` Amazon workflow T2 Product Workflow Service
结论：CODE_REVIEW / NEEDS_FIX

## 范围

- 本轮审查：
  - `MSG-20260618-002`
  - `MSG-20260618-003`
  - `MSG-20260618-004`
  - `docs/superpowers/specs/2026-06-18-amazon-product-workflow-prd.md`
- 使用索引：
  - `docs/project-index.md`
  - `docs/domain-index/product-flow.md`
- 审查文件：
  - `backend/app/product_tasks/workflow.py`
  - `backend/app/api/products.py`
  - `backend/app/api/schemas.py`
  - `backend/app/product_tasks/actions.py`
  - `scripts/test_project_rules.py`
  - `docs/domain-index/product-flow.md`

## 验证

- `make backend-compile`：PASS。
- `make test-project-rules`：PASS，40 tests。
- `git diff --check -- backend/app/product_tasks/workflow.py backend/app/api/products.py backend/app/api/schemas.py scripts/test_project_rules.py docs/domain-index/product-flow.md docs/project-index.md docs/collaboration/inbox.md`：PASS。
- 函数级代码事实：
  - ProductTaskAction reserve 等价对象，但 `workflow_node/workflow_status` 为空 -> `workflow_uninitialized / needs_initialization / open_detail`。
  - `flow_done/succeeded` 且 `catalog_item.exported_at` 非空 -> `_product_list_work_status(product)` 返回 `export_ready`，不是仍被 API/前端允许的 `exported`。

## 索引审查

- `docs/domain-index/product-flow.md` 已补充 T2 service 入口，方向正确。
- 但索引同时保留“ProductTaskAction reserve 入队态不能再被误判”的口径；当前 T2 代码让实际 reserve 态变成 `needs_initialization/open_detail`，与索引当前口径冲突。该冲突来自实现，不是索引本身。

## Findings

### P0：T2 切到新 helper 后，实际 ProductTaskAction reserve 态会丢失任务中心入口

- 位置：
  - `backend/app/api/products.py:423`
  - `backend/app/product_tasks/workflow.py:142`
  - `backend/app/product_tasks/actions.py:215`
  - `backend/app/product_tasks/actions.py:350`
  - `scripts/test_project_rules.py:1930`
- 事实：
  - `_workflow_state()` 现在只是 `build_product_workflow(product, catalog_exported=catalog_exported)` 的薄 wrapper。
  - `build_product_workflow()` 在 `workflow_node/workflow_status` 为空时返回 `stage="workflow_uninitialized"`、`work_status="needs_initialization"`、`primary_action="open_detail"`。
  - `ProductImageAnalysisAction.reserve()` 仍只写旧字段：`status=STEP6_CURATING/current_step=5/error_message="图片分析已加入任务中心队列"`，没有写 `workflow_node/workflow_status`。
  - `ProductListingGenerationAction.reserve()` 同样只写旧字段：`status=STEP5_LISTING/current_step=6/error_message="Listing 生成已加入任务中心队列"`，没有写 `workflow_node/workflow_status`。
  - 当前项目规则 `test_product_task_action_reserve_states_are_not_marked_interrupted` 人工给样本补了 `workflow_node/workflow_status`，没有覆盖真实 reserve 投影后的字段状态。
- 最小复现：
  - `STEP6_CURATING/current_step=5/error_message="图片分析已加入任务中心队列"` 且 workflow 字段为空 -> `workflow_uninitialized needs_initialization open_detail`。
  - `STEP5_LISTING/current_step=6/error_message="Listing 生成已加入任务中心队列"` 且 workflow 字段为空 -> `workflow_uninitialized needs_initialization open_detail`。
- 影响：
  - 商品刚被图片分析或 Listing 任务 reserve 后，列表/详情不再显示 `open_task_center`，而是“Workflow 待初始化/查看”。
  - 这会把实际已入队的新任务中心状态误导成未初始化，破坏之前刚修过的 ProductTaskAction reserve workflow 口径。
- 修复要求：
  - 不能用测试样本手工补 workflow 字段掩盖真实 writer 没写的问题。
  - 要么在本轮切换读 projection 前保证相关 writer 同步写入 workflow 字段；要么收住 T2 读路径切换范围，避免 T6/T7 未实现前影响 ProductTaskAction reserve 态。
  - 必须补行为护栏：以真实 reserve 等价字段为样本，不预填 `workflow_node/workflow_status`，证明不会丢失任务中心入口；或者明确 T2 不切换该路径，等 T6/T7 接入后再启用。

### P1：`work_status=exported` 仍被 API/前端允许，但 T2 后端不再可能返回该状态

- 位置：
  - `backend/app/api/products.py:162`
  - `backend/app/api/products.py:638`
  - `backend/app/product_tasks/workflow.py:142`
  - `frontend/src/pages/ProductList.tsx:50`
- 事实：
  - `PRODUCT_LIST_WORK_STATUS_KEYS` 仍允许 `exported`。
  - 前端 `ProductList.tsx` 仍有 `exported` filter/status。
  - `_product_list_work_status()` 计算 `catalog_exported` 后传给 `_workflow_state()`。
  - 但 `build_product_workflow()` 完全没有使用 `catalog_exported`，`flow_done/succeeded` 始终返回 `work_status="export_ready"`。
- 最小复现：
  - `workflow_node=flow_done/workflow_status=succeeded`，且 `catalog_item.exported_at` 非空 -> `_product_list_work_status(product)` 返回 `export_ready`。
- 影响：
  - 用户/API 仍能请求 `work_status=exported`，但后端过滤不会匹配已导出商品，形成允许值、前端选项、后端计数/过滤三者不一致。
  - `_build_list_item()` 的 `current_task_status` 会显示已导出，但同一条记录的 `workflow.work_status` 仍是 `export_ready`，状态字段自相矛盾。
- 修复要求：
  - 如果本阶段仍保留 `exported` 作为列表筛选/展示状态，`_product_list_work_status()` 或同源 helper 必须在不把导出做成 workflow node 的前提下保留 exported 投影口径。
  - 如果产品口径决定 T2 移除 exported work_status，必须同步 API 允许值、前端选项和 overview/list 口径；不能只让后端过滤静默返回 0。
  - 补项目规则或行为样本覆盖已导出商品的列表 work_status 口径。

## 已确认通过

- `set_product_workflow()` 只校验并写 `workflow_node/workflow_status/workflow_error/workflow_updated_at`，未看到 commit/flush/task run/外部副作用。
- `build_product_workflow()` 的核心投影只读 workflow 字段，没有从 task status 反推商品主状态。
- `flow_done` 的 `node_type` 已是 PRD 口径 `done`。
- `GET /api/products/overview` 已把 `needs_initialization` 作为显式 bucket，并在 `load_only()` 中预加载 workflow 字段。
- `ProductWorkflowState` 新增 `node_key/node_label/node_type/node_status` 为可选字段，schema 兼容方向正确。

## 未覆盖 / 风险

- 本轮未做页面 QA、未启动服务、未触发真实任务或真实商品路径。
- `scripts/test_project_rules.py` 中 T2 结构检查仍有较多字符串断言；建议把上述两个回归补成函数级行为样本，避免再次被“手工补字段”的测试绕过。
