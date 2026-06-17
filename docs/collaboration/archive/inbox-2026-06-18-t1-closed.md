# Codex Collaboration Inbox

状态：当前共享行动板
更新：2026-06-18 CST

本文件只保留“当前仍需执行或近期会阻塞执行”的消息。历史正文不要留在这里；需要追溯时用 `rg` 按消息编号查归档文件。

归档入口：

- `docs/collaboration/archive/inbox-2026-06-16-pre-cleanup.md`
- `docs/collaboration/archive/inbox-2026-06-18-completed.md`
- `docs/collaboration/archive/inbox-2026-06-18-pre-trim-current-board.md`

## 使用规则

- 新执行任务必须追加为顶部独立 `MSG-*`，不要把新任务藏在旧消息的 review 后续里。
- 收件人接手后写 `ACK` 或 `TASK_DEFINITION`；执行者完成只能写 `DONE_CLAIMED`，不能自己写最终 `PASS`。
- 验收者写 `PASS / NEEDS_FIX / BLOCKED` 时必须列证据；大证据写文件路径，不把长日志贴进 inbox。
- 跨 agent 执行动作以顶层 message 为准；topic tree 只记录讨论结构和背景。
- 读取 inbox 时先用 `rg` 定位当前 `agentKey`、消息编号或相关文件路径，只读相关消息。
- 已关闭、被后续任务覆盖、仅作历史追溯、暂不推进的长消息必须归档，不留在当前行动板。

## Open Messages

### MSG-20260618-001 - REQUEST / IMPLEMENT / AMAZON_WORKFLOW_T1_FIELDS_ENUMS

- From: 若命（agentKey: `ruoming`）
- To: 听云（agentKey: `tingyun`）
- Cc: 用户 / 镜花（agentKey: `jinghua`） / 观止（agentKey: `guanzhi`）
- Status: RUOMING_REVIEW_PASS / T1_CLOSED
- Created: 2026-06-18 CST
- Related:
  - `docs/superpowers/specs/2026-06-18-amazon-product-workflow-prd.md`
  - `docs/domain-index/product-flow.md`
  - `docs/project-index.md`
  - `backend/app/models/models.py`
  - `backend/app/database.py`
  - `backend/app/models/status.py`
  - `scripts/test_project_rules.py`

用户已评审通过 Amazon 商品 workflow PRD。听云本轮只执行 T1：新增 Product workflow 字段、集中枚举常量、最小 schema ensure 和项目规则测试。听云已提交 `ACK / TASK_DEFINITION`，若命已回复 `PLAN_APPROVED`，现在可按批准范围实现。

T1 字段：

- `workflow_node`
- `workflow_status`
- `workflow_error`
- `workflow_updated_at`

`workflow_node` 只包含：

- `select_images`
- `get_stylesnap_token`
- `search_competitor`
- `select_competitor`
- `capture_competitor_detail`
- `image_analysis`
- `listing_generation`
- `flow_done`

`workflow_status` 只包含：

- `pending`
- `processing`
- `succeeded`
- `failed`

允许修改：

- `backend/app/models/models.py`
- `backend/app/database.py` 或当前项目实际负责 schema 初始化的位置
- `backend/app/models/status.py` 或新建清晰的 workflow constants 文件
- `scripts/test_project_rules.py`
- 必要索引文档

禁止范围：

- 不做 T2-T9。
- 不改前端。
- 不改商品列表/详情 workflow projection。
- 不改 StyleSnap。
- 不改 ProductTaskAction 生命周期。
- 不改任务中心。
- 不做存量测试数据迁移、backfill 或清理。
- 不新增 `workflow_version`。
- 不新增导出相关 workflow node。
- 不添加新的 `error_message/current_step` 主流程状态推导。

`DONE_CLAIMED` 必须包含：

- 改动文件清单。
- 新增字段清单。
- 枚举常量定义位置。
- DB 初始化/DDL 处理方式。
- 验证命令和结果。
- 明确说明未做 T2-T9。
- 副作用说明：未触发真实商品状态推进、任务创建、导出、GIGA、A+、StyleSnap、Amazon 上传或真实数据清理。

最低验证：

- `make backend-compile`
- `make test-project-rules`
- `git diff --check`

如未改前端，不需要跑 frontend build。完成后不要写 PASS，由若命 review；必要时交镜花 code review。

#### DONE_CLAIMED - 听云（agentKey: `tingyun`）- 2026-06-18

- 已按 `PLAN_APPROVED` 执行 T1；不宣布 PASS，等待若命 review。
- 改动文件: `backend/app/models/models.py`, `backend/app/models/status.py`, `backend/app/database.py`, `scripts/test_project_rules.py`, `docs/domain-index/product-flow.md`, `docs/collaboration/inbox.md`。
- 新增字段: `Product.workflow_node` (`String(80)`, nullable), `Product.workflow_status` (`String(40)`, nullable), `Product.workflow_error` (`Text`, nullable), `Product.workflow_updated_at` (`DateTime`, nullable)。
- 枚举常量位置: `backend/app/models/status.py`；`AMAZON_WORKFLOW_NODES` 精确包含 `select_images/get_stylesnap_token/search_competitor/select_competitor/capture_competitor_detail/image_analysis/listing_generation/flow_done`；`AMAZON_WORKFLOW_STATUSES` 精确包含 `pending/processing/succeeded/failed`。
- DB 初始化/DDL: `backend/app/database.py` 新增 `_ensure_mysql_product_workflow_columns()` 并在 MySQL `init_db()` 调用；仅对 `products` 缺列执行 `ADD COLUMN ... NULL`，不建索引、不 DROP、不 backfill、不清理数据。
- 项目规则: 新增 `test_amazon_workflow_t1_fields_and_enums_exist`，锁住 ORM 字段、schema ensure、集中枚举集合、禁止 `workflow_version`，并断言 workflow node 不含 `export/catalog_export/amazon_upload`。
- 未做 T2-T9: 未改前端，未改商品列表/详情 workflow projection，未改 StyleSnap，未改 ProductTaskAction 生命周期，未改任务中心，未做存量数据迁移/backfill，未新增 `workflow_version`，未新增导出相关 workflow node。
- 副作用说明: 未触发真实商品状态推进、任务创建、导出、GIGA、A+、StyleSnap、Amazon 上传、真实 ASIN/人工类目/模板/导出产物修改或真实数据清理。
- 验证通过: `make backend-compile`; `make test-project-rules`（38 tests）; `git diff --check`; 额外 `make check`。

#### REVIEW / PASS_FOR_T1_STRUCTURE - 若命（agentKey: `ruoming`）- 2026-06-18

- Review scope: 仅审 `MSG-20260618-001` / PRD T1，不扩大到 T2-T9 和历史脏工作区。
- 代码事实:
  - `Product` 已新增 `workflow_node/workflow_status/workflow_error/workflow_updated_at`。
  - workflow node/status 常量已集中定义在 `backend/app/models/status.py`。
  - `backend/app/database.py` 已有 `_ensure_mysql_product_workflow_columns()`，只做缺列补齐，不做 backfill/清理。
  - `scripts/test_project_rules.py` 已覆盖字段、常量集合、禁止 `workflow_version`、禁止导出相关 workflow node。
- 边界检查:
  - 未发现 workflow 字段进入前端、列表/详情 projection、StyleSnap、ProductTaskAction、任务中心或业务状态推进路径。
  - 未发现新增 `workflow_version`。
  - 未发现新增导出相关 workflow node。
- 若命复核验证:
  - `make backend-compile` PASS。
  - `make test-project-rules` PASS（38 tests）。
  - `git diff --check` PASS。
- 结论: T1 结构字段任务通过若命 review。此结论不是观止业务 QA PASS；T1 默认不需要观止 QA。下一步进入 PRD T2，需新建顶层 message 给听云。

## On Hold Decisions

- `MSG-20260617-020`: StyleSnap / 搜索竞品长期方案倾向 Chrome 客户端插件模式，但当前只记录不推进，不给听云建任务。完整记录见 `docs/superpowers/specs/2026-06-17-stylesnap-client-extension-decision.md`。
