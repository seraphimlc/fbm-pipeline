# QA / PASS_WITH_SCOPE - A+ Auto Trigger A2

观止（agentKey: `guanzhi`）于 2026-06-22 执行 `MSG-20260622-075 - APLUS_AUTO_AFTER_EXPORT_READY_A2_HOOK` QA gate。

## 结论

`QA / PASS_WITH_SCOPE`

本轮验证通过：Listing success 后的 A+ A2 hook 在默认关闭时 no-op 且可追踪；配置开启时可为待导出商品创建单品 `aplus_generate` / `aplus_generate_product` 任务并写 `ProductAplus.aplus_status=queued`；重复触发复用 active A+ task；A+ planner/触发失败只写 `aplus_auto_trigger.trigger_failed`，不回滚商品 `flow_done/succeeded` / `export_ready` 主结果；未发现本轮新增 Amazon 导出、A+ 上传、Seller Central、TikTok 或前端按钮入口。

本 PASS 只覆盖 A2 hook 与本地任务创建/复用/失败隔离行为，不代表 A+ 内容质量、真实 worker 全流程出图质量、Amazon A+ 上传、Seller Central 或导出中心验收通过。

## 范围与环境

- 任务来源：`docs/collaboration/inbox.md` 中 `MSG-20260622-075`。
- 参考文档：`docs/superpowers/specs/2026-06-21-amazon-aplus-auto-after-export-ready-prd.md`、`docs/superpowers/specs/2026-06-21-aplus-auto-after-export-ready-a1-a2-plan.md`、`docs/collaboration/reviews/2026-06-22-aplus-auto-trigger-a2-code-review.md`。
- 代码范围：`backend/app/services/aplus_auto_trigger.py`、`backend/app/product_tasks/actions.py`、`backend/app/task_planners/aplus_generate.py`、`scripts/test_aplus_auto_trigger_a1_a2.py`、`scripts/test_image_analysis_listing_e5.py`、`scripts/test_project_rules.py`。
- 环境：本地 dirty worktree；未启动本地服务；未访问外部平台；行为脚本使用 `APLUS_A1_TEST_` marker 安全样本并在结束时清理。
- 禁止范围遵守：未编辑业务代码、未提交、未 push、未编辑 `docs/collaboration/inbox.md`，未触发 Amazon 导出/A+ 上传/Seller Central/TikTok。

## 测试矩阵

| 用例 | 目标 | 操作/证据 | 结果 |
|---|---|---|---|
| TC-A2-001 | 默认关闭 no-op | `cd backend && .venv/bin/python ../scripts/test_aplus_auto_trigger_a1_a2.py --stage a2`；脚本断言 default-off Listing success 后无 A+ step、无 `ProductAplus`，summary/result 写 `disabled_by_config` | PASS |
| TC-A2-002 | 开启后创建 A+ task | 同一命令；脚本断言商品完成 `flow_done/succeeded`、`CatalogProduct.confirmed_at` 存在、`ProductAplus.aplus_status=queued`、创建 1 个 `aplus_generate_product` step | PASS |
| TC-A2-003 | 幂等/复用 | 同一命令；脚本重复调用 helper，断言返回 `active_aplus_task` / `reused`，run id 不变且仍只有 1 条 A+ step | PASS |
| TC-A2-004 | 失败隔离 | 同一命令；脚本 monkey patch planner 抛 `forced aplus planner failure`，断言 summary/result 为 `trigger_failed`，商品仍 completed / `flow_done/succeeded`，`workflow_error` 未污染 | PASS |
| TC-A2-005 | 主链路不回退 | `cd backend && .venv/bin/python ../scripts/test_image_analysis_listing_e5.py` | PASS，输出 `E5 image analysis -> listing -> export_ready behavior checks passed` |
| TC-A2-006 | 结构防线 | `make test-project-rules` | PASS，62 项，其中 `test_aplus_auto_after_export_ready_a1_a2_contract` 通过 |
| TC-A2-007 | 越界入口检查 | `git diff --stat -- frontend backend/app/api backend/app/task_runtime backend/app/task_planners/catalog_export.py` 与 `git diff -- frontend/src backend/app/api` | PASS，未发现本轮新增前端/API 自动触发、导出或上传入口；输出仅显示既有 `frontend/tsconfig.tsbuildinfo` 缓存改动 |

## 命令证据

- `cd backend && python -m compileall -q app`：PASS，无输出。
- `cd backend && .venv/bin/python ../scripts/test_aplus_auto_trigger_a1_a2.py --stage a2`：PASS，输出 `A+ auto trigger A1/A2 behavior checks passed`。
- `cd backend && .venv/bin/python ../scripts/test_image_analysis_listing_e5.py`：PASS，输出 `E5 image analysis -> listing -> export_ready behavior checks passed`。
- `make test-project-rules`：PASS，输出 `OK: 62 project rule test(s)`。
- `cd backend && .venv/bin/python ../scripts/test_aplus_auto_trigger_a1_a2.py`：PASS，输出 `A+ auto trigger A1 policy behavior checks passed`。该命令默认只跑 A1；A2 证据以上方 `--stage a2` 为准。

## 关键事实

- 默认关闭事实：`backend/app/config.py:77` 为 `AUTO_APLUS_AFTER_EXPORT_READY: bool = False`，`backend/.env.example:58-59` 记录默认关闭；policy 在关闭时返回 `disabled_by_config`（`backend/app/services/aplus_auto_trigger.py:192-194`）。
- Hook 顺序：Listing success 先 `_project_listing_completed(product)`，写 listing summary，再 `await db.commit()`；之后才 best-effort 调 `try_auto_start_aplus_after_export_ready(...)`（`backend/app/product_tasks/actions.py:2633-2648`）。这支撑 A+ 失败不回滚待导出。
- Summary/progress 可追踪：hook 把 `aplus_auto_trigger` 写入 `TaskRun.summary_json`、step progress data 和 result（`backend/app/product_tasks/actions.py:2664-2696`）。
- 开启后任务创建：helper 调 `create_aplus_generate_runs(... created_by="auto_after_export_ready", auto_start=True)` 并返回 `queued` / `task_run_ids`（`backend/app/services/aplus_auto_trigger.py:342-378`）；planner 创建 `task_type="aplus_generate"`、`step_type="aplus_generate_product"`，并将 `ProductAplus.aplus_status` 置为 `queued`（`backend/app/task_planners/aplus_generate.py:96-115`, `:145-164`）。
- 幂等/复用：policy 检查 active A+ task 和 A+ active status，helper 将 `active_aplus_task` 映射为 `reused`（`backend/app/services/aplus_auto_trigger.py:224-235`, `:277-286`）；auto 单品 run 写 `dedupe_key` / `correlation_key`（`backend/app/task_planners/aplus_generate.py:107-121`）。
- 失败隔离：helper 捕获 planner 异常后 `rollback` 当前 A+ 事务并返回 `trigger_failed`（`backend/app/services/aplus_auto_trigger.py:350-362`）；outer hook 也 catch all 并继续写结构化结果（`backend/app/product_tasks/actions.py:2649-2664`）。
- 行为脚本直接断言：default-off 无 A+ row 且写 `disabled_by_config`（`scripts/test_aplus_auto_trigger_a1_a2.py:325-350`）；enabled 创建 1 条 A+ task 且 `aplus_status=queued`（`:355-389`）；重复触发复用（`:396-412`）；planner failure 不污染主流程（`:417-452`）。
- 越界边界：A+ worker 仅执行 plan/script/image 并写 A+ derived status（`backend/app/task_runtime/aplus_generate_workers.py:63-132`），本轮 hook 未调用 `catalog_export`、A+ upload、Seller Central 或 TikTok 入口；A+ 上传仍只存在于既有显式 API `createAplusUploadBatch` / `/products/catalog/aplus-upload`，本轮无 API/frontend diff。

## 问题

未发现 P0/P1/P2。

## 残余风险

- 失败隔离证据中的 planner failure 是脚本 monkey patch 模拟，只证明本地 hook/事务隔离行为，不代表外部平台或真实 A+ 生成依赖验收。
- 幂等证据覆盖顺序重复触发、active task/status 复用和 auto run metadata；未证明跨进程并发下有数据库唯一约束级防重。A2 当前作为 Listing success 后 best-effort 派生任务，此风险不阻断本 gate。
- 配置开启且真实服务运行时，planner 传 `auto_start=True`，任务可能被 runtime 拉起并从 `queued` 进入 `planning/scripting/imaging/done/failed`；本轮只验创建/复用和不上传，不验 A+ 内容质量。
- 未做浏览器页面人工视觉验收，因为 A2 未新增前端展示/按钮；后续 A3 管理页自动补齐需要单独页面 QA。

## Gate Meaning

- 允许若命将 `MSG-20260622-075` 作为 `QA / PASS_WITH_SCOPE` 处理。
- 不授权提交、push 或合并；最终 inbox 由若命合并。
