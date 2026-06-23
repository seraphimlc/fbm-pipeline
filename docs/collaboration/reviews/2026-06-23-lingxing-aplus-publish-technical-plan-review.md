# Lingxing A+ Publish Technical Plan Review

结论：`TECHNICAL_PLAN_REVIEW / PASS_WITH_CONSTRAINTS`

本结论允许进入 T1「Data, Registry, And Bootstrap」，但只允许做数据字段、状态 registry、统一写入 service、bootstrap/project-rule 闭包和索引更新。不得跳到 T2+ 的 Listing 同步、领星保存草稿、A+ done 自动触发、页面提交审批或真实外部调用。

## Review Scoping

- 节点：`SOLUTION_REVIEW + ARCHITECTURE_REVIEW + DATA_REVIEW + TEST_REVIEW`
- 审查对象：`docs/superpowers/specs/2026-06-23-lingxing-aplus-publish-technical-plan.md`
- 需求来源：`docs/superpowers/specs/2026-06-23-lingxing-aplus-publish-after-aplus-done-prd.md`、`docs/collaboration/inbox.md` 的 `MSG-20260623-002`
- 代码事实：`backend/app/services/aplus_upload.py`、`backend/app/services/asin_sync.py`、`backend/app/models/models.py`，以及 task runtime / `aplus_generate` / `aplus_auto_trigger` / catalog export 相关 scoped `rg`
- 不审：不做 QA，不验证真实领星/Amazon 页面，不跑服务，不审实现 diff，不改业务代码，不提交，不 push
- 通过标准：方案必须能把商品主链路、本地 A+、ASIN/Listing 同步、领星发布、task runtime、外部能力层分开；状态/事实源闭合；seller SKU/MSKU 对齐可信；旧路径不继续承载新链路；阶段可 review、可验证、可提交。

## Passed Checks

1. 分层边界成立。
   - PRD 明确商品主流程、A+ 生成、ASIN 回流、领星发布分属不同层，且领星失败不能回退商品 workflow：`docs/superpowers/specs/2026-06-23-lingxing-aplus-publish-after-aplus-done-prd.md:52`、`:74`、`:81`。
   - 技术方案把 execution、external publish evidence、CatalogProduct、Product mirror、ProductAplus 分成不同事实源：`docs/superpowers/specs/2026-06-23-lingxing-aplus-publish-technical-plan.md:56`。
   - 现有 `ProductAplus` 只保存本地 A+ 内容和 `aplus_status`，不保存外部发布结果：`backend/app/models/models.py:541`。

2. 事实源方案可以闭合。
   - 当前代码确实存在 Product/Catalog 双字段：`Product.aplus_upload_status` 在 `backend/app/models/models.py:21`，`CatalogProduct.aplus_upload_status` 在 `backend/app/models/models.py:293`。
   - 方案要求所有 `Product.aplus_upload_status` / `CatalogProduct.aplus_upload_status` 写入通过单一 service，CatalogProduct 为主、Product 为兼容镜像：`docs/superpowers/specs/2026-06-23-lingxing-aplus-publish-technical-plan.md:66`。
   - 这正面覆盖旧实现中 `_set_aplus_upload_status()` 和 `_finish_item()` 分散直接写 Product/Catalog 的事实：`backend/app/services/aplus_upload.py:73`、`:224`。

3. 状态语义覆盖了关键生产端和消费端。
   - PRD 定义 `draft_saved`、`draft_visible`、`submitted` 的不同证据，禁止用保存成功冒充可见：`docs/superpowers/specs/2026-06-23-lingxing-aplus-publish-after-aplus-done-prd.md:201`。
   - 方案列出状态 registry、terminal/retryable/protection/unknown legacy 策略：`docs/superpowers/specs/2026-06-23-lingxing-aplus-publish-technical-plan.md:112`。
   - 方案要求 T1 用 `scripts/test_project_rules.py` 锁 ORM 字段、schema/index/status registry 闭包：`docs/superpowers/specs/2026-06-23-lingxing-aplus-publish-technical-plan.md:148`、`:412`。

4. seller SKU/MSKU 对齐风险被正面处理。
   - 当前 Amazon export 的 `sku` 来自 `ProductData.item_code`：`backend/app/pipeline/amazon_export/listing_fill.py:18`，catalog export success 只写 `exported_at/export_task_id/export_file_path`，没有持久化真实 seller SKU：`backend/app/task_runtime/catalog_export_workers.py:119`。
   - 现有 `asin_sync.py` 的 `build_sync_item()` 仍然 `upc or item_code` 且 UPC 时使用商品编码查询：`backend/app/services/asin_sync.py:445`。
   - 方案要求新增 `amazon_seller_sku` 并在导出成功时持久化实际写入模板的 `sku`，匹配优先级改为 seller SKU 精确匹配，UPC 只能辅助诊断：`docs/superpowers/specs/2026-06-23-lingxing-aplus-publish-technical-plan.md:68`。

5. 旧路径拆分和安全闸方向正确。
   - 旧 `aplus_upload.py` 使用 `_running_batches` 和 `asyncio.create_task()`：`backend/app/services/aplus_upload.py:30`、`:39`；旧 `asin_sync.py` 同样如此：`backend/app/services/asin_sync.py:28`、`:36`。
   - 旧 A+ API/schema/frontend 仍默认提交审批：`backend/app/api/schemas.py:1201`、`frontend/src/api/index.ts:1435`、`backend/app/api/products.py:4605`。
   - 方案明确新链路不得调用 `start_aplus_upload_batch()`，不得依赖 `asyncio.create_task()`，旧默认提交不得泄漏到新端点：`docs/superpowers/specs/2026-06-23-lingxing-aplus-publish-technical-plan.md:239`。

6. task runtime 设计方向可恢复、可重试、可审计。
   - 现有 `task_runs/task_groups/task_steps/task_step_events` 支持 `dedupe_key/correlation_key/idempotency_key` 和 step event：`backend/app/models/models.py:151`、`:226`、`:261`。
   - runtime claim、执行、失败、retry 都有持久化状态和 event：`backend/app/task_runtime/scheduler.py:71`、`:233`、`:454`。
   - 方案要求 Lingxing 任务使用 planner/worker、dedupe/correlation/idempotency、外部调用写 sanitized event，重试 draft/visibility/submit 时复用 `idHash`：`docs/superpowers/specs/2026-06-23-lingxing-aplus-publish-technical-plan.md:175`。

7. UI/API 与 QA 边界没有污染商品主链路。
   - PRD 禁止商品列表 `work_status` 增加领星发布状态：`docs/superpowers/specs/2026-06-23-lingxing-aplus-publish-after-aplus-done-prd.md:107`。
   - 方案要求新增 task-run based API，不从 product list/detail GET、A+ 管理页加载或主 workflow retry 触发发布，并要求 A+ 管理页区分 `draft_saved`/`draft_visible`：`docs/superpowers/specs/2026-06-23-lingxing-aplus-publish-technical-plan.md:295`。
   - 当前 `/aplus-upload` 已重定向到 `/aplus`，A+ 管理页只展示 upload status 和生成/重跑，不存在新发布入口：`frontend/src/App.tsx:37`、`frontend/src/pages/AplusManagement.tsx:166`。

8. 分阶段计划可 review、可验证、可提交。
   - T1 到 T7 按数据基础、seller SKU/Listing 同步、草稿保存、草稿可见性、自动触发、UI、提交审批拆分，每阶段有文件、步骤、验证、DONE_CLAIMED 证据和 gate：`docs/superpowers/specs/2026-06-23-lingxing-aplus-publish-technical-plan.md:390`。
   - 阶段顺序没有把真实外部发布提前到数据/状态/seller SKU 之前，符合 PRD 的推荐派工：`docs/superpowers/specs/2026-06-23-lingxing-aplus-publish-after-aplus-done-prd.md:663`。

## Must-Keep Constraints

1. T1 必须先锁定发布证据表选型。
   - 方案允许扩展 `AplusUploadItem` 或新建 `lingxing_aplus_publish_items`：`docs/superpowers/specs/2026-06-23-lingxing-aplus-publish-technical-plan.md:94`、`:110`。
   - 进入 T1 可以接受这个选择尚未在方案里定死，但 T1 实现前必须在 T1 `DONE_CLAIMED` 里说明最终选择、字段、索引、迁移/兼容口径和为什么不会与 `task_runs` 形成双执行事实源。

2. T1 必须先完成 status registry + single writer，不能先让旧 API/worker 生产新状态。
   - 旧 API 会直接写 `pending/skipped` 并启动旧 batch：`backend/app/api/products.py:4620`、`:4650`。
   - 新状态只允许通过 T1 的 `aplus_publish_state.py` 写入；旧 `pending/running/success` 必须按方案 legacy mapping 处理，不得继续作为新 Product/Catalog 状态生产值。

3. T2 是 T3 的硬前置。
   - 旧 `asin_sync.py` 的 UPC 优先风险是代码事实：`backend/app/services/asin_sync.py:445`。
   - 在 `amazon_seller_sku` 持久化和 seller SKU/MSKU 精确匹配通过镜花 review 前，不允许实现或触发领星 A+ 草稿保存任务。

4. `draft_saved` 不能作为 PRD 级外部成功。
   - 方案已把 T3 定义为 `draft_saved only`，T4 才能产生 `draft_visible`：`docs/superpowers/specs/2026-06-23-lingxing-aplus-publish-technical-plan.md:48`、`:517`。
   - 若用户/若命只接受 `draft_saved` 作为第一版阶段终点，交付说明必须写成“保存领星草稿”，不能写“Amazon A+ 草稿箱可见/已发布”。

5. T3 必须显式处理“外部保存成功但本地提交前崩溃”的重复草稿风险。
   - 方案已有“retry `draft_saved` 不得创建第二个草稿”的原则：`docs/superpowers/specs/2026-06-23-lingxing-aplus-publish-technical-plan.md:232`。
   - 实现时还必须用确定性 document name / seller SKU / ASIN / store / site / `idHash` 查询恢复，或在证据不确定时阻断并要求人工选择“复用/新建”，不能静默再创建一个草稿。

6. 旧 `aplus_upload.py` / `asin_sync.py` 在新链路中只能作为能力拆分来源。
   - 旧 A+ 模块仍有硬编码店铺、Chrome auth、空 headline/body、`settings` 未导入风险和默认提交路径：`backend/app/services/aplus_upload.py:24`、`:208`、`:424`。
   - T3 前必须证明新 planner/worker 不调用 `start_aplus_upload_batch()`；旧 API 如保留，只能 legacy/read-only 或显式标记，不得成为 A+ done 自动链路入口。

7. 真实 QA 结论必须分层。
   - fixture 只能证明内部规则；真实 auth、保存草稿、draft visibility、submit 分别由观止/用户 gate：`docs/superpowers/specs/2026-06-23-lingxing-aplus-publish-technical-plan.md:353`、`:372`。

## Non-blocking Risks

- 首版店铺配置仍需确认。PRD 示例 `Andy店-US / 17983` 与真实测试店铺 `idea_lc@163.com-US` 不同，方案已列 open question：`docs/superpowers/specs/2026-06-23-lingxing-aplus-publish-technical-plan.md:681`。
- 旧 A+ 内容模块只提交图片型模块且标题/body 为空，技术保存不等于内容质量合格；方案已把内容质量列为业务验收问题：`docs/superpowers/specs/2026-06-23-lingxing-aplus-publish-technical-plan.md:685`。
- 当前 task runtime 是进程内 runner + 持久化 task state，不是跨进程 durable worker；方案已限定 v1 单实例、并发 1：`docs/superpowers/specs/2026-06-23-lingxing-aplus-publish-technical-plan.md:671`。

## Out of Scope

- 未验证真实领星 API 网关是否与旧代码 payload 兼容。
- 未验证 Amazon Seller Central A+ 草稿箱可见性。
- 未审任何后续实现 diff。
- 未授权修改 inbox、业务代码、模板或真实外部数据。

## Gate Meaning

- 允许：进入 T1「Data, Registry, And Bootstrap」。
- 不允许：进入 T2-T7、触发真实领星/Amazon 调用、启用自动发布、提交审批、修改商品主 workflow `work_status`。
- 本 PASS 不代表：代码 review PASS、QA PASS、真实领星保存草稿 PASS、`draft_visible` PASS、submit PASS、commit/push 授权。
