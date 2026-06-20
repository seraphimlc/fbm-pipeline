# Amazon Auto Competitor Search Phase A Code Review

日期：2026-06-20 CST

审查人：镜花（agentKey: `jinghua`）

关联消息：`MSG-20260620-009`

结论：`CODE_REVIEW / PASS`

## Scope

本次审查对象是听云完成的 Amazon 自动竞品搜索 Phase A 与旧 StyleSnap 退役实现。审查节点为 `IMPLEMENTATION_REVIEW + DATA_REVIEW + TASK_LIFECYCLE_REVIEW + TEST_REVIEW + DOCUMENTATION_REVIEW`。

本次覆盖：

- `POST /api/products/{id}/competitor-search/retry` 到 `product_competitor_search` task run 的入口、planner、action、worker、scheduler success hook。
- `amazon_competitor_search_candidates` 数据模型、索引、upsert 口径和后续视觉初筛的最低事实源。
- `search_competitor -> visual_match_competitors` workflow 投影和前端 action 消费。
- 旧 StyleSnap active runtime/UI path、旧 ORM/snapshot/export 兼容读取退役。
- 与本任务直接相关的 PRD/domain index/项目规则测试。

本次不覆盖：

- 页面 QA、真实商品执行、真实 task run、真实 Amazon 搜索、真实 VLM、StyleSnap/Chrome、导出、Amazon 上传或外部平台验收。
- `docs/collaboration/roles/jinghua.md` 等角色设定改动。
- `tmp/`。

## Gate Standard

- 新自动竞品搜索必须只走任务中心 planner/action，不复用旧 StyleSnap `BackgroundTasks` 主流程。
- Phase A 成功只能写候选并推进到 `visual_match_competitors/pending`，不能启动视觉初筛、抓详情、选竞品、图片分析、Listing、A+、导出或 Step 10。
- 候选主事实源必须是结构化表，包含商品归属、task run/step 证据、搜索证据、候选证据和排除标记；不能依赖旧 snapshot key 或运行时猜状态。
- 失败、取消、中断、空候选和 success projection 失败不能留下可被下游当作成功消费的半状态。
- 旧 StyleSnap active runtime/UI path 可以退役，且代码层旧 ORM/snapshot/export/listing prompt 兼容读取按用户补充口径不再保留。

## Blocking Findings

无阻断项。

## Passed Checks

1. 新入口没有复用旧 BackgroundTasks。

- 证据：`backend/app/api/products.py:4810` 定义 `POST /{product_id}/competitor-search/retry`；`backend/app/api/products.py:4835` 调用 `create_product_competitor_search_runs()`；该 endpoint 区段不包含 `BackgroundTasks` 或旧 `_run_product_competitor_search_background`。
- 证据：`backend/app/task_planners/product_competitor_search.py:8` 只包装 `create_product_action_runs(..., "product_competitor_search", ...)`。

2. 任务生命周期闭环成立。

- 证据：`ProductCompetitorSearchAction.validate()` 在 `backend/app/product_tasks/actions.py:567` 检查保护门、workflow node/status、主图和 query 生成；`reserve()` 在 `backend/app/product_tasks/actions.py:589` 写 `search_competitor/processing`。
- 证据：`execute_step()` 在 `backend/app/product_tasks/actions.py:627` 只生成 query、调用 adapter 并返回结构化 `search_results`，没有写 `amazon_competitor_search_candidates`。
- 证据：候选 upsert 和成功 workflow 投影在 `on_step_success()`，见 `backend/app/product_tasks/actions.py:673`；成功后只进入 `visual_match_competitors/pending`，见 `backend/app/product_tasks/actions.py:693`。
- 证据：失败、取消、中断均投影到 `search_competitor/failed`，见 `backend/app/product_tasks/actions.py:723`、`backend/app/product_tasks/actions.py:735`、`backend/app/product_tasks/actions.py:745`。
- 证据：scheduler 在 success hook 异常时 rollback 并把 run 标为 `partial_failed`，见 `backend/app/task_runtime/scheduler.py:306` 到 `backend/app/task_runtime/scheduler.py:334`。由于候选只在 success hook 内写，success projection 失败不会把本次候选提交为成功事实。

3. 候选表满足 Phase A 最低数据契约。

- 证据：`AmazonCompetitorSearchCandidate` 定义在 `backend/app/models/models.py:869`，`product_id + asin` 唯一约束在 `backend/app/models/models.py:871`。
- 证据：表字段包含 `task_run_id/task_step_id`、source 归属、query/rank、ASIN/title/image/price/rating/review、广告/配件/替换件/cover-only 排除标记和 raw evidence，见 `backend/app/models/models.py:875` 到 `backend/app/models/models.py:906`。
- 证据：MySQL ensure 索引覆盖 product/rank、product/query、product/excluded、asin、task_run，见 `backend/app/database.py:201` 到 `backend/app/database.py:205`。

4. workflow 和前端 action 没有用前端字符串推导启动新搜索。

- 证据：workflow service 集中给 `search_competitor/pending` 默认 `start_competitor_search`，失败自动搜索给 `retry_competitor_search`，见 `backend/app/product_tasks/workflow.py:61` 到 `backend/app/product_tasks/workflow.py:69`、`backend/app/product_tasks/workflow.py:386` 到 `backend/app/product_tasks/workflow.py:405`。
- 证据：商品列表只消费后端 `workflow.primary_action`，见 `frontend/src/pages/ProductList.tsx:729` 到 `frontend/src/pages/ProductList.tsx:768`；API client 只新增 `retryProductCompetitorSearch()`，见 `frontend/src/api/index.ts:1478`。

5. 旧 StyleSnap active runtime/UI path 已退役。

- 证据：`backend/app/main.py` 不再 import/register `amazon_stylesnap_router`；旧文件 `backend/app/api/amazon_stylesnap.py`、`backend/app/services/amazon_stylesnap_search.py`、`backend/app/services/amazon_listing_capture.py`、`frontend/src/pages/ProductCompetitorReview.tsx` 已删除。
- 证据：scoped `rg` 未发现运行代码继续保留 `/api/amazon-stylesnap`、旧 API client、旧页面 import、旧 ORM 模型、旧 snapshot key 或 Step10/export 兼容读取；残留 StyleSnap 文本主要在历史 PRD/review 文档和项目规则退役断言中。

6. 连带文件未发现阻断性夹带。

- `giga_product_drafts.py` 是原 active GIGA draft/自动选图入口服务去 StyleSnap 命名后的承接，调用方 import 同步合理。
- `pipeline/engine.py`、`step10_amazon_template.py`、`amazon_export/writer.py`、`step5_listing.py` 删除旧 `selected_stylesnap` / `amazon_listing_capture` 兼容读取，和用户“历史兼容表/字段/snapshot key 不需要了”的边界一致。
- Phase A 成功落点仍是 `visual_match_competitors/pending`，未在代码中启动图片分析、Listing、A+、导出或 Step 10。

## Non-blocking Risks

1. 自动/旧竞品搜索区分仍依赖中文 marker。

- 证据：`backend/app/product_tasks/actions.py:880` 和 `backend/app/product_tasks/workflow.py:466` 都用 `"自动竞品搜索"` 判断是否属于新自动搜索状态。
- 当前不阻断原因：旧 active StyleSnap runtime/UI path 已退役；新 action 的 reserve/failure/cancel/interrupted 写入都包含该 marker；`search_competitor/pending` 本身允许作为新自动搜索启动态。
- 后续要求：Phase B 或后续链路若继续扩展，建议改成显式 workflow source/mode、task correlation evidence 或最后成功 run evidence，不要继续扩大中文文案判据。

2. Phase B 下游读取候选前仍需要补“当前成功 run”的消费口径。

- 证据：当前 Phase A 只写候选，不提供下游读取 API；表以 `product_id + asin` upsert，会更新同 ASIN 的 query/rank/task evidence。
- 当前不阻断原因：本阶段没有下游消费代码；候选写入与 `visual_match_competitors/pending` 投影同在 success hook 内，失败路径不会写主候选。
- 后续要求：视觉初筛任务必须至少以 `workflow_node=visual_match_competitors` 且 `workflow_status=pending` 作为读取前置，并明确读取最新成功 `task_run_id` 或当前候选集合的排序/去重口径。

3. 测试仍偏项目规则和函数级样本，缺少一个端到端内存 DB 行为测试。

- 已覆盖：退役断言、入口/planner/action/string contract、query 生成、fixture HTML 解析、workflow projection。
- 缺口：没有直接构造 `ProductCompetitorSearchAction.on_step_success()` 成功/空候选/异常 rollback 的行为测试。
- 当前不阻断原因：代码路径和 scheduler 事务边界已经可读核实，验证命令通过；但 Phase B 开始消费候选前，应补行为测试锁住“失败不留可消费候选”。

4. 历史 StyleSnap PRD/决策文档仍有旧口径。

- 证据：`docs/superpowers/specs/2026-06-17-stylesnap-client-extension-decision.md`、`docs/superpowers/specs/2026-06-18-amazon-product-workflow-prd.md` 等历史文档仍描述 StyleSnap/token 旧方案。
- 当前不阻断原因：`docs/project-index.md`、`docs/domain-index/product-flow.md` 和当前自动竞品 PRD 已给出最新入口与退役口径；历史文档没有作为当前索引入口。
- 后续建议：若命后续可另开文档治理，把旧 PRD 标注为历史/被新 PRD 覆盖，降低后续 agent 误读概率。

## Verification

已执行：

```bash
python -m compileall backend/app
make test-project-rules
cd frontend && npm run build
git diff --check
```

结果：

- `python -m compileall backend/app` 通过。
- `make test-project-rules` 通过，`OK: 52 project rule test(s)`。
- `cd frontend && npm run build` 通过，仅有既有 Vite chunk-size warning。
- `git diff --check` 通过。

## Gate Meaning

`CODE_REVIEW / PASS` 表示 `MSG-20260620-009` 指定的代码、数据契约、任务生命周期、测试和文档索引 gate 通过。它不代表页面 QA PASS、真实商品/真实任务执行验收、真实 Amazon 搜索/VLM/StyleSnap/Chrome 验收、外部平台验收或用户最终验收。

建议若命可以基于本报告判断 `MSG-20260620-009` 进入提交许可流程；提交时应只纳入本任务相关文件，继续排除 `docs/collaboration/roles/jinghua.md` 等角色规则线和 `tmp/`，除非用户/若命另行授权。
