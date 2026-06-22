### CODE_REVIEW / PASS_WITH_SCOPE - 镜花（agentKey: `jinghua`）- 2026-06-22 20:05 CST

结论：PASS_WITH_SCOPE。A+ A2 hook 的当前实现满足 `MSG-20260622-074` 指定的 code/data/task-runtime/test/doc review gate；未发现阻断观止 A+ A2 QA 的 P0/P1。

范围：

- 审查对象：`MSG-20260622-073/074`、A+ auto trigger PRD/plan、A2 diff、行为脚本、project rules、product-flow/task-runtime/project index。
- 代码范围：`backend/app/product_tasks/actions.py`、`backend/app/services/aplus_auto_trigger.py`、`backend/app/task_planners/aplus_generate.py`。
- 测试/文档范围：`scripts/test_aplus_auto_trigger_a1_a2.py`、`scripts/test_image_analysis_listing_e5.py`、`scripts/test_project_rules.py`、`docs/domain-index/product-flow.md`、`docs/domain-index/task-runtime.md`、`docs/project-index.md`。
- 未审范围：不做观止 QA；不验前端页面；不触发 Amazon/A+ 上传、Seller Central、TikTok、真实导出或真实外部平台。

验证：

- `cd backend && python -m compileall -q app`：PASS。
- `cd backend && .venv/bin/python ../scripts/test_aplus_auto_trigger_a1_a2.py --stage a2`：PASS，输出 `A+ auto trigger A1/A2 behavior checks passed`。
- `cd backend && .venv/bin/python ../scripts/test_image_analysis_listing_e5.py`：PASS，输出 `E5 image analysis -> listing -> export_ready behavior checks passed`。
- `make test-project-rules`：PASS，62 tests。
- scoped `git diff --check -- backend/app/services/aplus_auto_trigger.py backend/app/product_tasks/actions.py backend/app/task_planners/aplus_generate.py scripts/test_aplus_auto_trigger_a1_a2.py scripts/test_image_analysis_listing_e5.py scripts/test_project_rules.py docs/domain-index/product-flow.md docs/domain-index/task-runtime.md docs/project-index.md`：PASS。

索引审查：

- 使用的索引文件：`docs/project-index.md`、`docs/domain-index/product-flow.md`、`docs/domain-index/task-runtime.md`。
- 结论：索引总体准确表达 A2 已启用 Listing success hook，并明确不包含 A+ 上传、前端/A+ 管理页批量补齐、TikTok 或外部平台动作。
- P2 文档建议：`docs/domain-index/product-flow.md` 的“验证入口”仍只列 `test_aplus_auto_trigger_a1_a2.py --stage a1`，而当前 A2 行为验证入口应优先指向 `--stage a2`。不阻断 QA，因为同文件当前口径/关键流程/常见定位已经写明 A2 hook，且 `docs/domain-index/task-runtime.md` 已列 A2 验证入口。

Findings：

- 无 P0/P1。
- [P2] Product-flow 验证入口仍偏 A1
  - 位置：`docs/domain-index/product-flow.md:89`
  - 事实：该行仍写 “A+ 自动触发 A1 policy 行为脚本：... --stage a1”；同文件 `:31`、`:61`、`:100` 和 `docs/domain-index/task-runtime.md:78` 已表达 A2 hook 与 `--stage a2`。
  - 影响：后续 agent 如果只看 product-flow 的验证入口，可能少跑 A2 行为脚本。
  - 建议：若命后续合并文档时把该验证入口更新为 A1/A2 或 A2 `--stage a2`。

已确认通过：

- E5 commit 后触发：`ProductListingGenerationAction.on_step_success()` 先 `_project_listing_completed(product)`，写保留原字段的 listing summary，并 `await db.commit()`；随后才调用 `try_auto_start_aplus_after_export_ready(...)`。证据：`backend/app/product_tasks/actions.py:2633-2648`。
- 失败不回滚商品待导出：A+ helper 捕获 planner 异常后 `rollback` 当前 A+ 事务并返回 `trigger_failed`，E5 已在 hook 调用前提交；outer hook 也兜底捕获异常。证据：`backend/app/services/aplus_auto_trigger.py:342-362`、`backend/app/product_tasks/actions.py:2641-2664`；行为脚本断言 `Product.status=completed`、`flow_done/succeeded`、`CatalogProduct.confirmed_at` 保留且 `workflow_error` 不污染，见 `scripts/test_aplus_auto_trigger_a1_a2.py:417-452`。
- 默认关闭 no-op：配置默认 `AUTO_APLUS_AFTER_EXPORT_READY=false`，policy 在 disabled 时直接返回 `disabled_by_config`，行为脚本断言不创建 A+ step、不写 `ProductAplus`。证据：`backend/app/config.py:77`、`backend/.env.example:59`、`backend/app/services/aplus_auto_trigger.py:192-194`、`scripts/test_aplus_auto_trigger_a1_a2.py:325-350`。
- 开启后创建/复用幂等：eligibility 检查 active 主流程 task、active A+ step、active A+ status、done/retryable 状态；auto single-product run 带 `dedupe_key=aplus_generate:product:{id}` 和 `correlation_key=product:{id}:aplus_generate`。证据：`backend/app/services/aplus_auto_trigger.py:220-235`、`backend/app/task_planners/aplus_generate.py:107-122`、`scripts/test_aplus_auto_trigger_a1_a2.py:355-412`。
- A+ 结果落点受控：hook 只把结果作为 `aplus_auto_trigger` 子对象写入 listing task summary、progress data 和内存 result，保留 `product_id/item_code/status/next_step`。证据：`backend/app/product_tasks/actions.py:2634-2640`、`:2664-2696`。
- failure/skip reason 结构化：decision/helper 返回 `status/code/message/details/source_task_*`，并覆盖 disabled、missing facts、active task/status、保护门、planner failure。证据：`backend/app/services/aplus_auto_trigger.py:184-390`、`scripts/test_project_rules.py:2635-2705`。
- 手动单个/批量 A+ 语义未被 A2 改写：planner 只在 `created_by == "auto_after_export_ready"` 且单品 eligible 时增加 auto dedupe/correlation；手动 `product_aplus_generate`、`aplus_generate_batch`、task-center `aplus-generate` 仍调用同一 planner，`created_by` 不满足 auto 条件。证据：`backend/app/task_planners/aplus_generate.py:45-122`。
- 防回归覆盖足够支撑本 gate：行为脚本覆盖 default-off、enabled create、active reuse、planner failure isolation；project rules 覆盖默认关闭、helper/hook 顺序、summary 写入、dedupe/correlation、禁止旧任务/主 workflow 污染。证据：`scripts/test_aplus_auto_trigger_a1_a2.py:325-458`、`scripts/test_project_rules.py:2609-2738`。

残余风险：

- 当前幂等证据覆盖顺序重复和 active task/status，不等于数据库唯一约束级别的跨进程并发防重；A2 gate 可接受，因为触发点是单个 Listing success 后的派生 best-effort，且已有 active 检查与 dedupe/correlation 元数据。
- 本 review 不代表观止 QA PASS，不覆盖真实 worker 完整生成图片内容质量、前端展示、A+ 管理页批量补齐、A+ 上传或外部平台验收。

Gate Meaning：

- 允许进入观止 A+ A2 QA。
- 本 PASS_WITH_SCOPE 只代表 A2 code/data/task-runtime/test/doc gate 通过；不代表可提交、可 push、可合并或用户路径最终通过。
