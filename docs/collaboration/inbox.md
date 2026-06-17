# Codex Collaboration Inbox

状态：当前共享行动板
更新：2026-06-18 CST

本文件只保留“当前仍需执行或近期会阻塞执行”的消息。历史正文不要留在这里；需要追溯时用 `rg` 按消息编号查归档文件。

归档入口：

- `docs/collaboration/archive/inbox-2026-06-16-pre-cleanup.md`
- `docs/collaboration/archive/inbox-2026-06-18-completed.md`
- `docs/collaboration/archive/inbox-2026-06-18-pre-trim-current-board.md`
- `docs/collaboration/archive/inbox-2026-06-18-t1-closed.md`

## 使用规则

- 新执行任务必须追加为顶部独立 `MSG-*`，不要把新任务藏在旧消息的 review 后续里。
- 收件人接手后写 `ACK` 或 `TASK_DEFINITION`；执行者完成只能写 `DONE_CLAIMED`，不能自己写最终 `PASS`。
- 验收者写 `PASS / NEEDS_FIX / BLOCKED` 时必须列证据；大证据写文件路径，不把长日志贴进 inbox。
- 跨 agent 执行动作以顶层 message 为准；topic tree 只记录讨论结构和背景。
- 读取 inbox 时先用 `rg` 定位当前 `agentKey`、消息编号或相关文件路径，只读相关消息。
- 已关闭、被后续任务覆盖、仅作历史追溯、暂不推进的长消息必须归档，不留在当前行动板。

## Open Messages

### MSG-20260618-002 - REQUEST / TASK_DEFINITION / AMAZON_WORKFLOW_T2_SERVICE

- From: 若命（agentKey: `ruoming`）
- To: 听云（agentKey: `tingyun`）
- Cc: 用户 / 镜花（agentKey: `jinghua`） / 观止（agentKey: `guanzhi`）
- Status: OPEN / WAITING_TINGYUN_TASK_DEFINITION
- Created: 2026-06-18 CST
- Related:
  - `docs/superpowers/specs/2026-06-18-amazon-product-workflow-prd.md`
  - `docs/domain-index/product-flow.md`
  - `backend/app/product_tasks/`
  - `backend/app/api/products.py`
  - `backend/app/api/schemas.py`
  - `backend/app/models/status.py`
  - `scripts/test_project_rules.py`

T1 已通过若命 review，完整记录见 `docs/collaboration/archive/inbox-2026-06-18-t1-closed.md`。现在进入 PRD T2：Product Workflow Service。

听云第一步不要写代码。先在本消息下写 `ACK / TASK_DEFINITION`，说明你准备如何实现 T2；若命回复 `PLAN_APPROVED` 后再动代码。

#### T2 目标

新增 `backend/app/product_tasks/workflow.py`，把 Amazon 商品 workflow 的写入和投影集中到一个后端 service/helper 中。商品列表和商品详情必须通过同一个 helper 得到 workflow object，不再在 `backend/app/api/products.py` 里维护一大段独立 workflow 判断。

#### 必须提供的能力

1. `set_product_workflow(product, *, node, status, error=None, now=None)`：
   - 校验 `node` 必须来自 `AMAZON_WORKFLOW_NODES`。
   - 校验 `status` 必须来自 `AMAZON_WORKFLOW_STATUSES`。
   - 写入 `product.workflow_node`、`product.workflow_status`、`product.workflow_error`、`product.workflow_updated_at`。
   - `now` 为空时使用当前时间。
   - 不 commit、不 flush、不创建任务、不触发副作用。

2. `build_product_workflow(product, *, catalog_exported=None)`：
   - 只基于 `workflow_node/workflow_status/workflow_error` 和必要的只读上下文构建返回对象。
   - 不从 task status 反推商品主状态。
   - 不用 `error_message/current_step` 正则猜 Amazon 主流程节点。
   - 列表和详情必须调用同一个 helper。
   - 对 workflow 字段为空的存量数据，只返回显式“未初始化/需初始化”状态，不复杂兼容旧 `current_step/error_message`。

3. node/action 映射必须集中定义：
   - 每个 node 有 label、node_type、默认 work_status、默认 primary_action、allowed_actions、action_reason。
   - failed 状态的 action 要符合 PRD：搜索失败可重搜，抓取详情失败可重抓/换竞品，图片分析失败可重试图片分析，Listing 失败可重试 Listing。
   - `flow_done/succeeded` 表示 Amazon 主流程结束；导出不是主流程节点。

#### API 兼容要求

- 可以保留当前 `ProductWorkflowState` 的已有字段名，避免前端本轮必须同步改。
- 如果需要新增 `node_key/node_label/node_type/node_status` 等字段，必须是向后兼容的可选字段。
- `backend/app/api/products.py` 中现有 `_workflow_state` 如需保留，只能变成薄 wrapper，核心规则必须在 `backend/app/product_tasks/workflow.py`。
- `_product_workbench_status`、`_product_list_work_status`、列表 item、详情 response 必须同源调用新的 helper。

#### 禁止范围

- 不做 T3-T9。
- 不改前端 UI。
- 不实现图片选择 reset。
- 不实现搜索竞品、StyleSnap、Chrome 插件或 token 流程。
- 不创建、取消、重试或推进任何 task run。
- 不修改 ProductTaskAction 生命周期。
- 不改任务中心。
- 不做存量 backfill、迁移、清理或真实商品状态推进。
- 不新增导出相关 workflow node。
- 不继续扩展 `error_message/current_step` 主状态推导。

#### 完成定义

`DONE_CLAIMED` 必须包含：

- 改动文件清单。
- 新 service/helper 的接口和行为说明。
- 列表和详情如何同源调用。
- 空 workflow 字段如何投影。
- 每个 node/status 到 label/action/work_status 的覆盖说明。
- 明确说明未做 T3-T9 和未触发真实副作用。
- 验证命令和结果。

最低验证：

- `make backend-compile`
- `make test-project-rules`
- `git diff --check`

如未改前端，不需要跑 frontend build。

#### TASK_DEFINITION 必须先回答

- 准备新增/修改哪些文件。
- `set_product_workflow()` 的校验和写入规则。
- `build_product_workflow()` 的返回结构和空字段策略。
- 如何把 `products.py` 里现有 `_workflow_state` 收敛为调用 helper。
- 准备新增哪些项目规则或行为测试。
- 明确复述不会做 T3-T9，不会碰前端和真实数据。

## On Hold Decisions

- `MSG-20260617-020`: StyleSnap / 搜索竞品长期方案倾向 Chrome 客户端插件模式，但当前只记录不推进，不给听云建任务。完整记录见 `docs/superpowers/specs/2026-06-17-stylesnap-client-extension-decision.md`。
