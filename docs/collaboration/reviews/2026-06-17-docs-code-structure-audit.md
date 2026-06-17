# CODE_AUDIT_REPORT - Docs And Code Structure Full Audit

- Reviewer: 镜花（agentKey: `jinghua`）
- Time: 2026-06-17 16:47 CST
- Trigger: 用户要求“其它的你也看看；代码别改，让听云改”，并要求 review/全量审计先用索引建范围，再 scoped `rg` 核实代码事实。
- Scope: docs 当前结构、project/domain index 准确性、后端 API/service/task/pipeline 边界、前端 API/page 边界、任务运行时状态、测试防线。
- Out of scope: 不修改业务代码，不触发任务、导出、上传、外部平台调用、DB 写入或真实数据变更。
- Read-only statement: 本轮代码审计只读；仅新增本报告和 inbox 消息。
- Sub-agents used: 无。
- Summary: `NEEDS_FIX`。文档清理方向正确，但代码结构仍有 P0/P1：读接口会移动用户素材文件；`products.py` 仍是 5807 行 god router 并被 service/planner/worker 反向依赖；任务中心列表/筛选与详情状态口径仍不一致；多个新旧后台任务仍用进程内 `asyncio.create_task`/`BackgroundTasks`；dedupe/idempotency 只有应用层检查和普通索引；测试大量依赖字符串扫描，挡不住结构回退。

## Audit Plan And Progress

- [done] 读取 `AGENTS.md`、`docs/collaboration.md`、`docs/collaboration/roles/jinghua.md`、`docs/project-index.md`、相关 domain index 和 full-audit/code-review playbook。
- [done] 用 `rg --files docs -g '*.md'` 和 scoped `rg` 检查剩余 docs、旧文档引用和候选背景标注。
- [done] 用 `wc -l`、decorator/function 扫描、反向 import 扫描、任务/后台任务模式扫描核实结构风险。
- [done] 抽关键片段确认 P0/P1 证据。
- [done] 生成本报告，准备 inbox 交给若命/听云 triage。

## System Map

- Docs route: `docs/README.md`, `docs/project-index.md`, `docs/domain-index/*.md`, `docs/documentation-rewrite-brief.md`.
- Product flow: `frontend/src/pages/ProductList.tsx`, `frontend/src/pages/ProductDetail.tsx`, `backend/app/api/products.py`.
- Task runtime: `frontend/src/pages/TaskRunCenter.tsx`, `backend/app/api/task_runs.py`, `backend/app/task_runtime/`, `backend/app/task_planners/`.
- Export flow: `frontend/src/pages/CatalogList.tsx`, `backend/app/task_planners/catalog_export.py`, `backend/app/task_runtime/catalog_export_workers.py`, `backend/app/pipeline/step10_amazon_template.py`.
- Runtime/security: `scripts/start.sh`, `backend/app/main.py`, `backend/app/config.py`, `backend/app/database.py`.
- Frontend/API contract: `frontend/src/App.tsx`, `frontend/src/api/index.ts`, `frontend/src/components/MainLayout.tsx`.
- Tests/rules: `scripts/test_project_rules.py`;未发现独立 `tests/` 目录。

## Index Review

Used indexes:

- `docs/project-index.md`
- `docs/domain-index/task-runtime.md`
- `docs/domain-index/product-flow.md`
- `docs/domain-index/data-sources.md`
- `docs/domain-index/export-flow.md`
- `docs/domain-index/frontend-pages.md`
- `docs/domain-index/runtime-security.md`

Findings:

- [P2] `frontend-pages` / `project-index` 没有明确覆盖 `/config`, `/upc-pool`, `/asin-sync`, `/aplus` 等仍在 `frontend/src/App.tsx:37-43` 注册的页面；后续 agent 只按索引 scoped search 时会漏掉配置、UPC、ASIN、A+ 维护入口。
- [P2] docs 清理后的候选背景标注是对的：`docs/configuration.md`, `docs/runbook.md`, `docs/main-flow-user-path.md`, `docs/main-flow-qa-checklist.md`, `docs/giga-inventory-sync.md`, `docs/item-workbench-redesign-plan.md` 已标注不能直接当当前事实源。若命/听云重写前，应继续只作背景。
- [P3] 历史 review/change-log 中仍引用已删除旧文档，这是历史证据可接受；新文档不得把这些路径当当前入口。

## Findings

### P0-1 GET 商品详情会静默移动用户素材目录文件

- 位置: `backend/app/api/products.py:4930`, `backend/app/api/products.py:4963`, `backend/app/services/material_assets.py:46`
- 事实: `GET /api/products/{product_id}` 构建详情时调用 `organize_video_files(material_dir)`；该函数扫描 `material_dir.rglob("*")`，再用 `shutil.move()` 把视频文件移动到 `material_dir/video`。
- 影响: 读接口有本地文件系统写副作用。用户打开详情页或前端轮询详情，就可能改变真实素材目录结构；这类副作用不可审计、不可回滚，也会破坏“只读查看”和素材路径稳定性。
- 期望: GET 详情只读。视频整理应改成显式 POST action，并写清目标目录、预览变更、确认和结果；或完全移到导入/素材管理阶段。
- 修复要求: 听云先从详情读取链路移除 `organize_video_files()`，保留只读 folder summary；如仍需要整理视频，另建受控 mutating endpoint 和行为测试。

### P1-1 `products.py` 是 god router，且下层模块反向依赖 API 私有函数

- 位置: `backend/app/api/products.py:1`, `backend/app/api/products.py:2632`, `backend/app/api/products.py:4122`; 反向依赖见 `backend/app/task_planners/catalog_export.py:69`, `backend/app/task_runtime/catalog_export_workers.py:51`, `backend/app/services/offline_tasks.py:1088`, `backend/app/services/offline_tasks.py:1545`
- 事实: `products.py` 5807 行，混合商品 CRUD、状态推导、图片/竞品、UPC、导出中心、模板上传/下载、库存同步、ASIN/A+、本地文件操作、workbook/zip 构建。catalog planner/worker/offline service 从 `app.api.products` import `_catalog_category`、`_template_status_for_catalog`、`build_catalog_export_zip`、`CatalogExportBuildError`。
- 影响: API/router 变成业务核心和导出 service，导致 service/planner/worker 依赖路由层，无法独立测试，任何导出/商品逻辑改动都容易牵动巨型文件和循环边界。
- 期望: router 只处理协议；导出构建、模板状态、商品 workflow、素材操作、UPC/库存/ASIN/A+ 编排移到 domain/service 模块。
- 修复要求: 听云分阶段拆：先抽 `catalog_export_builder/template_status`，消除 planner/worker/service 对 `app.api.products` 的 import；再拆商品 workflow 和素材文件 action；每步保持 API 合同不变并补行为测试。

### P1-2 任务中心列表状态与详情状态仍不同源，`stale_running` 筛选不可用

- 位置: `backend/app/api/task_runs.py:196`, `backend/app/api/task_runs.py:243`, `backend/app/api/task_runs.py:301`, `backend/app/api/task_runs.py:315`, `backend/app/api/task_runs.py:439`, `frontend/src/pages/TaskRunCenter.tsx:462`
- 事实: 详情 `_run_display()` 会根据 running step 的 `locked_until/heartbeat_at` 派生 `stale_running`；列表 `_run_list_display()` 只看 `TaskRun.status == RUN_STATUS_RUNNING`，不会判定 stale；`_display_status_sql_condition("stale_running")` 直接 `and_(False)`，但前端仍提供“疑似卡住”筛选。
- 影响: 同一个任务在列表和详情可能显示不同状态；用户在列表看不到卡住任务，筛选永远查不出真实 stale running，还可能看到普通 running 的 cancel 操作而非 wake/mark interrupted。
- 期望: 列表、详情、筛选、按钮都消费同一组可索引投影字段；如果暂不支持 DB 级 stale 筛选，前端不要暴露该筛选和操作。
- 修复要求: 听云按若命已有 task center projection 口径补 `task_runs` 投影/状态字段，或收缩 UI 能力；禁止用 correlated EXISTS、内存扫描或假 total 补。

### P1-3 多套后台任务仍绕过新 task runtime，进程内任务丢失和状态分裂风险未收敛

- 位置: `backend/app/api/products.py:5143`, `backend/app/api/products.py:5236`, `backend/app/api/amazon_stylesnap.py:801`, `backend/app/api/amazon_stylesnap.py:859`, `backend/app/services/giga_sync_tasks.py:148`, `backend/app/services/aplus_regenerate.py:131`, `backend/app/task_runtime/scheduler.py:348`
- 事实: 商品图片确认/重启和 StyleSnap 入口用 FastAPI `BackgroundTasks` 触发竞品搜索；GIGA sync、A+ regenerate 等 service 仍保存 `_active_*` dict 并 `asyncio.create_task()`；新 runtime 自身也由 `kick_task_runtime()` 在当前进程 `call_later/create_task` drain ready steps。
- 影响: 任务可观测性、恢复、取消、幂等、重启行为分裂。部分流程进入 `task_runs`，部分流程进入旧 service 内存任务或 BackgroundTasks，页面和 QA 很难判断哪个状态是真实事实源。
- 期望: 所有耗时、可失败、需要恢复/重试/取消的流程都进入可持久化 task runtime，或明确标为 legacy 并有冻结/迁移计划。
- 修复要求: 听云列出现存 `create_task/BackgroundTasks` 清单，若命确认保留/迁移边界；优先迁移竞品搜索/抓取这类会改变商品状态的任务。

### P1-4 TaskRun dedupe/idempotency 没有 DB 强约束，重复提交只能靠应用层查询

- 位置: `backend/app/models/models.py:152`, `backend/app/models/models.py:154`, `backend/app/database.py:178`, `backend/app/product_tasks/actions.py:453`, `backend/app/product_tasks/actions.py:575`
- 事实: `TaskRun.dedupe_key`、`idempotency_key` 是普通 nullable 字段；启动维护只加普通 index；`create_product_action_runs()` 先查询 active run 再创建，依赖同一进程/事务时序。
- 影响: 并发点击、多进程、重试请求或未来 worker 拆分时可能创建重复 active run。`idempotency_key` 字段存在但没有唯一语义和冲突响应合同。
- 期望: 明确幂等模型：active dedupe 需要 DB 可执行的唯一约束/锁策略，idempotency key 需要请求级唯一约束、响应复用和过期策略。
- 修复要求: 听云不要只补字符串测试；先让若命确认 dedupe/idempotency 语义，再设计 MySQL 约束或事务锁方案和并发测试。

### P1-5 测试防线偏字符串扫描，不能证明关键行为和结构边界

- 位置: `scripts/test_project_rules.py:88`, `scripts/test_project_rules.py:331`, `scripts/test_project_rules.py:1112`; 文件体量 `scripts/test_project_rules.py` 1681 行；未发现独立 `tests/` 目录。
- 事实: 项目规则测试大量 `read_text()` 后检查字符串存在/不存在，例如真实 ASIN guard、任务中心字段、`and_(False)`/`scan_query` 等。虽然后半部分有少量 subprocess 行为样本，但大部分核心防线不是 API/DB/函数行为测试。
- 影响: 代码可以通过保留字符串、移动逻辑或写无效分支绕过测试；结构拆分后也容易被旧字符串测试误伤，阻碍真正模块化。
- 期望: P0/P1 行为用函数级/API级/DB事务级测试证明：GET 无副作用、任务状态投影一致、dedupe 并发、导出报告、模板映射等。
- 修复要求: 听云在修 P0/P1 时同步补最小行为测试；若必须保留 project rules 字符串扫描，只作为辅助手段，不作为 PASS 依据。

### P2-1 前端 API client 和页面层仍承载过多业务标签/状态映射

- 位置: `frontend/src/api/index.ts:1240`, `frontend/src/api/index.ts:1285`, `frontend/src/pages/TaskRunCenter.tsx:20`, `frontend/src/pages/TaskRunCenter.tsx:59`, `frontend/src/pages/TaskRunCenter.tsx:99`
- 事实: `frontend/src/api/index.ts` 1658 行，集中定义大量类型、标签和所有领域 API；`TaskRunCenter.tsx` 也维护 status/group/step/task type label 映射。
- 影响: 后端 display fields 与前端本地映射长期并存，容易出现标签、状态、按钮语义不一致。API client 成为前端 god module。
- 期望: API client 按领域拆分；任务状态/动作优先消费后端 display label/action，前端只做轻量 fallback。
- 修复要求: 听云在任务中心投影修复后，把前端状态映射收敛为 fallback，并规划 API client 分域拆分。

### P2-2 Amazon export 新规则层仍大量回调 legacy Step10

- 位置: `backend/app/pipeline/amazon_export/writer.py:22`, `backend/app/pipeline/amazon_export/strategies/sofa_chair.py:7`, `backend/app/pipeline/amazon_export/validators.py:87`, `backend/app/pipeline/step10_amazon_template.py:2240`
- 事实: `amazon_export/` 已有规则层，但 writer、strategies、validators 仍大量 `from app.pipeline import step10_amazon_template as legacy` 调用旧 2325 行 Step10 私有函数。
- 影响: 新规则层还不是独立边界；字段填充、校验、图片上传、模板写入仍被旧巨型模块牵引，后续新增类目难以判断该改新层还是旧层。
- 期望: 明确迁移路线：哪些 legacy helper 保留为 shared utility，哪些要迁入 `amazon_export/`；新增类目只走一个入口。
- 修复要求: 若命定义 Step10/amazon_export 分层目标；听云按目标逐步迁移，不在一次修复里大拆模板逻辑。

## Passed Checks

- P0 security/startup 的代码事实已较旧报告改善：默认 host 为 `127.0.0.1`，mutating API 有本机/dev token guard，startup DDL/backfill/recover/kick 均有 `STARTUP_RUN_*` 开关，外部 HTTP 默认走 `settings.external_http_verify`。
- `docs/codex*.md` 根目录只保留 `docs/codex-cold-start.md`；旧 `01-06` 文档和旧 handoff 文件已删除。
- `docs/README.md` 和 `docs/documentation-rewrite-brief.md` 已明确“候选背景/待重写/不能直接当事实源”。

## Test And Verification Evidence

Commands/evidence used:

- `git status --short`
- `sed -n` 读取协作规约、身份、playbook、project/domain index。
- `wc -l` 关键文件体量：`products.py` 5807 行，`task_runs.py` 870 行，`frontend/src/api/index.ts` 1658 行，`scripts/test_project_rules.py` 1681 行。
- `rg -n "from app\\.api\\.products import"` 核实 planner/worker/service 反向依赖 API 层。
- `rg -n "BackgroundTasks|asyncio\\.create_task|call_later"` 核实进程内后台任务。
- `rg -n "dedupe_key|idempotency_key|UniqueConstraint|and_\\(False\\)"` 核实 dedupe/index 和 stale filter。
- `rg --files docs -g '*.md'` 核实当前 docs 文件集合。

Not run:

- 未运行 `make check`、前端 build、API/DB 现场样本。本轮目标是只读结构审计，且用户明确代码让听云改；运行全量检查可能受当前多会话脏工作区和本地 DB 状态影响。听云修复后应按每条 finding 补行为级验证。

## Uncovered Areas

- 未做数据库只读样本查询；未验证真实 task_run/product 样本。
- 未打开浏览器做 UI 截图/交互 QA；这应交给观止。
- 未逐行审完所有 pipeline step、GIGA OpenAPI 字段语义和 Amazon 模板每个字段规则；本轮只做结构和高风险路径抽样。

## Recommended Repair Order

1. 听云先修 P0：移除 `GET /api/products/{id}` 的文件移动副作用，补只读行为测试。
2. 若命确认 task center projection/dedupe/idempotency 语义；听云修 P1-2/P1-4。
3. 听云抽 `catalog_export_builder/template_status`，消除下层对 `app.api.products` 的反向依赖。
4. 若命/听云列旧后台任务迁移表，先迁移会改商品状态的竞品搜索/抓取。
5. 听云补行为测试；再按领域拆前端 API client 和后端 god modules。
6. 若命/听云重写 docs，并补 `frontend-pages` / `project-index` 缺失页面入口。

## Next Actions

- 发 inbox 顶层消息给若命/听云：`CODE_AUDIT / NEEDS_FIX / DOCS_CODE_STRUCTURE_FULL_AUDIT`。
- 听云不要直接大改；先按修复顺序拆小任务，P0 独立修。
- 若命先定 task projection、dedupe/idempotency、legacy task migration 和 Step10/amazon_export 边界。
