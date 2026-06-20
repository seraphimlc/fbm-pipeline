# Amazon Auto Competitor Search Phase A Design Review

日期：2026-06-20 CST

审查人：镜花（agentKey: `jinghua`）

关联消息：`MSG-20260620-006`

结论：`DESIGN_REVIEW / NEEDS_ADJUST`

## Scope

本次只审听云在 `MSG-20260620-006` 下写的 `ACK / TASK_DEFINITION`，以及若命随后 `PLAN_APPROVED` 的收紧口径。审查对象是设计方案能否支撑后续实现，不做完整代码 review，不做页面 QA，不触发真实 Amazon 搜索、真实 task run、真实商品路径、StyleSnap/Chrome 或外部平台。

本次按 `docs/project-index.md` 定位到 `product-flow` 和 `task-runtime`，再用 scoped `rg` / 关键文件片段核实现有代码事实。

## Gate Standard

- 自动竞品搜索 Phase A 必须进入任务中心，不能复用旧 `BackgroundTasks` 主流程。
- 新自动搜索候选必须是清楚的主事实源，旧 StyleSnap/manual 事实源不能和新链路互相污染。
- 商品 workflow/action 必须能区分旧人工/StyleSnap 路径和新自动搜索路径，不能让同一个按钮误走另一套副作用。
- 候选落库、任务成功/失败、workflow 投影必须事务边界清楚，不能出现失败任务留下“可被后续消费”的半成功候选。
- 测试计划必须能证明上述边界，而不是只证明字段存在。

## Blocking Findings

1. [P1] `search_competitor` 同时承载旧 StyleSnap 和新自动搜索，方案没有给出可执行的分派判据。

   - 位置：`docs/collaboration/inbox.md:1152-1162`
   - 代码事实：旧入口 `backend/app/api/amazon_stylesnap.py:1152-1257` 仍通过 `BackgroundTasks` 调 `_run_product_competitor_search_background()`，并写 `WORKFLOW_NODE_SEARCH_COMPETITOR` 的 `processing/failed`。
   - 代码事实：当前 workflow projection 对 `search_competitor/processing` 和 `search_competitor/failed` 给出的 action 也是同一类“竞品搜索/重试”语义，见 `backend/app/product_tasks/workflow.py:321-329` 和 `backend/app/product_tasks/workflow.py:364-372`。
   - 设计事实：听云方案写“如果复用 `retry_competitor_search`，后端必须按 workflow node/status 明确分派到新 task run”，若命也要求“按 workflow 明确分派到新 `product_competitor_search` task run”。但仅靠 `workflow_node=search_competitor` 与 `workflow_status=failed|processing` 无法区分旧 StyleSnap/manual 失败和新自动搜索失败。
   - 影响：商品列表或 API 重试可能把旧 StyleSnap 失败商品送进新自动搜索 task run，或者把新自动搜索商品带回旧 `BackgroundTasks` 路径；这会直接违反本阶段“不复用旧 BackgroundTasks 主流程”和“旧 StyleSnap 只做人工兼容”的核心边界。
   - 最小调整要求：实现前必须在设计中补一个明确、可测试的分派/隔离规则。可选方向包括但不限于：新增显式的 workflow source/mode 字段；让 workflow projection 能基于 active `product_competitor_search` correlation/task evidence 区分新链路；或把旧 StyleSnap action 与新自动搜索 action/API 完全分开，并规定旧 StyleSnap `search_competitor/failed` 只能进入人工页而不能调用新 task run。无论采用哪种，测试必须覆盖“旧 StyleSnap failed 不会误走新 task run”和“新自动搜索 failed 不会误走旧 BackgroundTasks”。

2. [P1] 候选表按 `product_id+asin` upsert，但方案没有定义“哪一次成功 run 的候选可被下游消费”。

   - 位置：`docs/collaboration/inbox.md:994-997`、`docs/collaboration/inbox.md:1125-1136`、`docs/collaboration/inbox.md:1257-1263`
   - 代码事实：当前实现草稿中的 `AmazonCompetitorSearchCandidate` 已有 `task_run_id/task_step_id`，但唯一约束是 `product_id + asin`，见 `backend/app/models/models.py:921-960`；索引也已有 `task_run_id`，见 `backend/app/database.py:210-214`。
   - 设计事实：听云方案一处写 `execute_step()` “最多写 20 个候选”，另一处写 `on_step_success()` “写候选表”；若命补充要求不能出现“候选已写入但 task 最终失败仍显示成功候选可用”的半状态，但方案没有具体落地规则。
   - 影响：如果 execute 阶段或中途重试已经 upsert 主候选，随后 adapter 超时、验证码、zero candidates 或 success hook 失败，商品 workflow 会落 `search_competitor/failed`，但候选表可能留下带最新 `task_run_id` 的候选。后续视觉初筛如果只按 `product_id` 或 `product_id+is_excluded` 读取，就会消费失败 run 的半结果。反过来，如果后续失败 retry 覆盖了 `product_id+asin` 的 rank/query 证据，也会污染上一次成功候选的可解释性。
   - 最小调整要求：设计必须补清候选写入事务策略和消费口径。推荐二选一：
     - adapter/execute 只返回结构化结果，不写主候选表；`on_step_success()` 在同一事务中写候选、写 summary、投影 `visual_match_competitors/pending`。失败路径只写 task event / summary，不写主候选表。
     - 如果必须边执行边落库，则候选表必须有 `run_status` / `candidate_status` / `is_current` 或等价字段，并规定失败/中断/取消时如何标记或清理；下游只能读取“最后一次成功 run 且当前商品 workflow 已进入 `visual_match_competitors/pending`”的候选。
   - 必要测试：失败分类、zero candidates、success hook 抛错、retry 覆盖同 ASIN、下游候选读取口径都要有函数级或项目规则测试。

## Passed Checks

- 新建专门候选表的方向是对的。现有 `AmazonStyleSnapCandidate` 绑定 `batch_id/site/item_code/sku_code/rank/asin`，不适合作为自动 Amazon 页面搜索主事实源；听云在 `docs/collaboration/inbox.md:950-958` 的判断成立。
- Query 生成服务选择确定性规则 V1 是合理的。`ProductData` 当前有 `title/material/dimension_*/packages/features/description/variants` 等字段，见 `backend/app/models/models.py:442-468`，足以支持可测试的 2-3 组 query 生成。
- adapter 边界方向正确：页面访问/解析/异常分类归 adapter，workflow/候选落库/任务生命周期归 ProductTaskAction，见 `docs/collaboration/inbox.md:1063-1089` 和若命收紧口径 `docs/collaboration/inbox.md:1261`。
- 不做真实 Amazon 搜索作为完成条件是正确边界，见 `docs/collaboration/inbox.md:1264`。

## Non-blocking Risks

- `product_id+asin` 唯一约束会把同一 ASIN 在多个 query 下的证据压成一条记录。若只保存单个 `search_query/query_intent/search_rank`，会丢失“这个候选被哪些 query 召回、每个 query 排名如何”的解释链。建议补 `matched_queries_json` / `best_query_*` / 独立 query-result 证据表之一；不一定阻断 Phase A，但会影响后续视觉/自动选择解释力。
- 保护门建议复用或扩展 `backend/app/services/product_protection.py`，不要在 `ProductCompetitorSearchAction.validate()` 里重新拼一套真实 ASIN、Catalog、模板、A+ 判断。否则自动选图、手动调图、自动竞品三处保护规则会漂移。
- 当前 `ProductList.tsx` 仍有 legacy fallback 用 `product.status/current_step/error_message` 推工作状态，见 `frontend/src/pages/ProductList.tsx:245-260`。本轮只要求新自动竞品 action 不走这套推导，不要求立刻全量治理；但实现时必须保证新 action 分支只消费后端 workflow。

## Suggested Adjustment

建议若命让听云在继续实现前补一个 `TASK_DEFINITION_ADDENDUM`，只回答两个问题：

1. 新自动搜索和旧 StyleSnap/manual 在 API、workflow action、前端按钮、retry 入口上的分派规则是什么；用什么字段或证据区分；哪些测试锁住“不误走旧/新路径”。
2. 候选写入在 execute/success/failure/cancel/interrupted/retry 中的事务策略是什么；下游视觉初筛未来读取哪一组候选；失败 run 的候选如何避免被消费。

## Verification

本次是设计 review，未运行后端/前端测试，未启动服务，未触发真实外部路径。

已做只读核实：

- `docs/collaboration/inbox.md:913-1267`
- `docs/domain-index/product-flow.md`
- `docs/domain-index/task-runtime.md`
- `backend/app/api/amazon_stylesnap.py`
- `backend/app/product_tasks/workflow.py`
- `backend/app/models/models.py`
- `backend/app/database.py`
- `frontend/src/pages/ProductList.tsx`

## Gate Meaning

`DESIGN_REVIEW / NEEDS_ADJUST` 表示当前任务定义方向可取，但两个 P1 设计缺口会影响实现边界和后续 code review。它不是代码 review 结论，也不是 QA 结论。
