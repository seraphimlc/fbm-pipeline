# Lingxing A+ Publish T1 Code Review

结论：`CODE_REVIEW / PASS_WITH_SCOPE`

允许若命对 T1 实现做 scoped commit，并允许进入 T2「Seller SKU Persistence And Lingxing Listing Sync Task」。本 PASS 只覆盖 T1 data/registry/single-writer/bootstrap/project-rule/index 范围；不代表 QA PASS、不代表真实领星/Amazon 路径可用、不允许跳过 T2 直接做 T3 草稿保存。

## Review Scoping

- 身份：镜花（agentKey: `jinghua`）。
- 审查对象：`MSG-20260623-003` T1 `DONE_CLAIMED` 与 `MSG-20260623-004` code review 请求。
- 审查节点：`IMPLEMENTATION_REVIEW + DATA_REVIEW + STATUS_REVIEW + BOOTSTRAP_REVIEW + DOCUMENTATION_REVIEW`。
- 审查范围：`backend/app/models/models.py`、`backend/app/database.py`、`backend/app/aplus_publish/status.py`、`backend/app/services/aplus_publish_state.py`、`backend/app/api/schemas.py`、`backend/app/api/products.py`、`frontend/src/api/index.ts`、`scripts/test_project_rules.py`、`docs/project-index.md`、`docs/domain-index/product-flow.md`、`docs/domain-index/task-runtime.md`、`docs/domain-index/runtime-security.md`。
- 不审：不做页面/真实外部 QA，不验证真实领星登录、保存草稿、Amazon draft visibility 或提交审批；不改代码、不提交、不 push。
- 通过标准：T1 必须只建立 durable 字段、`aplus_upload_status` registry、统一写入 service、MySQL bootstrap/index、反向 project rules 和索引文档；不能新增 Lingxing planner/worker/API、A+ done 自动触发、旧 batch runner 行为迁移、页面按钮或真实外部调用。

## Blocking Findings

无 P0/P1/P2 阻断项。

## Passed Checks

1. T1 范围没有越界。
   - 当前新增执行模块只有 `backend/app/aplus_publish/status.py` 和 `backend/app/services/aplus_publish_state.py`；scoped `rg` 未发现新增 `lingxing_listing_sync` / `lingxing_aplus_publish` planner、worker、task API 或 `AUTO_LINGXING_APLUS_AFTER_DONE` 触发入口。
   - `backend/app/api/products.py:4614` 之后的旧 `/catalog/aplus-upload` 入口仍调用旧 `start_aplus_upload_batch(batch.id)`，但本 T1 没扩展旧 batch runner；这是计划允许的 legacy 边界，不是新链路。
   - `docs/domain-index/task-runtime.md:19` 明确记录当前尚未注册 Lingxing task type、planner、worker 或 API，T2+ 才能引入任务中心执行链路。

2. Product/CatalogProduct 字段合理，能支撑 T2 seller SKU/ASIN 对齐。
   - `Product` 增加 `amazon_seller_sku: String(100)`、`asin_match_source: String(50)`、`asin_match_evidence_json: Text`：`backend/app/models/models.py:15`、`:19`、`:20`。
   - `CatalogProduct` 增加同名字段：`backend/app/models/models.py:290`、`:294`、`:295`。
   - 长度选择符合 T1 计划：seller SKU 100、match source 50、证据 JSON 用 Text；字段均按 Optional 映射为可空，避免启动后要求历史数据立即回填。

3. AplusUploadItem 扩展字段足够承载外部发布证据，不与 task runtime 混成双执行事实源。
   - 证据字段覆盖 `idHash`、领星状态文本、草稿可见性、draft/submit 时间、publish evidence、source task run/step、ProductAplus、fingerprint、seller SKU、store/site：`backend/app/models/models.py:402` 到 `:414`。
   - `aplus_publish_state.py` 明确写入的是 external evidence，不推断 task success；task lifecycle 仍归 `task_runs`：`backend/app/services/aplus_publish_state.py:1` 到 `:8`、`:113` 到 `:119`。
   - `source_task_run_id/source_task_step_id` 是证据关联字段，不在 T1 中创建或调度任务。

4. MySQL schema ensure 和索引顺序合理，没有明显启动风险。
   - `init_db()` 在 `create_all` 和通用字段 ensure 后调用 `_ensure_mysql_lingxing_aplus_publish_columns()`，再进入 hot path index ensure：`backend/app/database.py:31` 到 `:45`。
   - Product/Catalog 新字段和 AplusUploadItem 字段均在 `_ensure_mysql_lingxing_aplus_publish_columns()` 中按缺列增量添加：`backend/app/database.py:121` 到 `:147`。
   - 索引覆盖计划要求：`ix_catalog_amazon_seller_sku`、`ix_catalog_amazon_asin`、`ix_catalog_aplus_upload_status`、`ix_aplus_upload_items_lingxing_id_hash`、`ix_aplus_upload_items_draft_visibility`、`ix_aplus_upload_items_product_aplus`：`backend/app/database.py:290` 到 `:295`。
   - 没有 broad production backfill；新增 `amazon_draft_visibility` 用 `NOT NULL DEFAULT 'unconfirmed'` 对历史行安全补齐：`backend/app/database.py:134`。

5. `status.py` 可以作为新的 Product/Catalog `aplus_upload_status` registry。
   - registry 覆盖 T1 必需状态全集：`not_uploaded`、`checking`、`waiting_listing`、`syncing_listing`、`ready_to_upload`、`uploading`、`draft_saved`、`draft_confirming`、`draft_visible`、`submitted`、`failed`、`skipped`、`auth_required`：`backend/app/aplus_publish/status.py:13` 到 `:25`、`:34` 到 `:47`。
   - terminal/retryable/protected/visibility endpoint 分类由 `AplusPublishStatus` 和 derived sets 统一导出：`backend/app/aplus_publish/status.py:28` 到 `:55`。
   - legacy 策略明确：Product/Catalog 旧 `pending` -> `checking`、`running` -> `uploading`；item-only `success` 被拒绝进入 Product/Catalog status：`backend/app/aplus_publish/status.py:58` 到 `:78`。
   - writer 使用 `allow_legacy=False`，防止新代码继续生产 `pending/running/success`：`backend/app/services/aplus_publish_state.py:68`。

6. `aplus_publish_state.py` 符合 single writer 边界。
   - 只导入 JSON/datetime/type、SQLAlchemy、status registry 和 ORM models；没有 HTTP、Chrome、planner、worker、runtime kick 或 workflow writer import：`backend/app/services/aplus_publish_state.py:12` 到 `:22`。
   - `_load_catalog_for_publish_state()` 要求必须能定位 `CatalogProduct`，否则报错；CatalogProduct 是主事实：`backend/app/services/aplus_publish_state.py:24` 到 `:43`。
   - `set_aplus_publish_status()` 先写 CatalogProduct，再镜像 Product，并只 `flush()` 不 `commit()`：`backend/app/services/aplus_publish_state.py:59` 到 `:91`。
   - `update_aplus_publish_item_evidence()` 只更新 AplusUploadItem 外部证据字段，不写 Product/Catalog 状态，不创建 task，不外呼：`backend/app/services/aplus_publish_state.py:94` 到 `:158`。

7. API/schema/frontend 只是字段透出，没有引入页面行为或发布入口。
   - Product response 增加 seller SKU 和 ASIN match evidence：`backend/app/api/schemas.py:730` 到 `:735`；Product list item 同步返回这些字段：`backend/app/api/products.py:560` 到 `:566`。
   - Catalog response 增加同名字段：`backend/app/api/schemas.py:974` 到 `:979`；Catalog 同步 helper 将 Product 兼容镜像带入 Catalog：`backend/app/api/products.py:969` 到 `:975`。
   - AplusUploadItem response 只暴露证据字段：`backend/app/api/schemas.py:1246` 到 `:1258`；frontend type 同步增加 nullable/optional 字段：`frontend/src/api/index.ts:1027` 到 `:1039`。
   - 未修改 `frontend/src/pages/AplusManagement.tsx`，未新增 manual publish/retry/submit UI。

8. project rules 提供了足够的 T1 反向不变量。
   - 字段、schema ensure、schema/frontend 透出检查覆盖 Product/Catalog/AplusUploadItem：`scripts/test_project_rules.py:2759` 到 `:2785`。
   - 索引和状态 registry 闭包检查覆盖 T1 关键对象：`scripts/test_project_rules.py:2787` 到 `:2823`。
   - single writer 检查要求 Catalog 主事实、Product mirror、item evidence、`flush()` 且无 `commit()`：`scripts/test_project_rules.py:2825` 到 `:2835`。
   - 反向禁止项覆盖 HTTP/Chrome/task planner/runtime kick/workflow writer，以及禁止新增 Lingxing planner/worker/task API/A+ done auto trigger：`scripts/test_project_rules.py:2836` 到 `:2864`。

9. 索引文档能帮助后续 agent 找到 T1 边界。
   - `docs/project-index.md` 增加 A+ 生成/管理/领星 ERP A+ 上传发布入口和 T1 status/state service 路径。
   - `docs/domain-index/product-flow.md:32` 说明 T1 只新增数据基础，当前尚未新增 planner/worker/API/自动触发，且不能并入 Amazon 主 workflow。
   - `docs/domain-index/runtime-security.md` 增加领星 A+ 发布风险导航，提示 Chrome 登录态、真实外部请求、自动提交审批和 task/runtime 审计边界。

## Residual Risks

- 旧 `aplus_upload.py` 仍是 legacy 外部调用入口，且直接写 `pending/running/skipped/draft_saved/submitted/failed` 并 `commit()`：`backend/app/services/aplus_upload.py:73` 到 `:90`、`:224` 到 `:260`；旧 API 也直接写 `pending/skipped`：`backend/app/api/products.py:4614` 到 `:4660`。这不阻断 T1，因为 `MSG-20260623-003` 明确本阶段不迁移旧行为链路；但 T3 前必须迁移或隔离，不能让新链路复用旧 batch runner。
- 代码库测试夹具中仍有 `uploaded` 作为历史保护态样本：`scripts/test_image_analysis_listing_e5.py:114`、`:149`。新 registry 未把 `uploaded` 列为合法或 legacy 映射。当前没有新读路径调用 registry 处理这些 fixture 值，不阻断 T1；T2/T3 如果要把 registry 接入更宽读路径，应先决定 `uploaded` 是显式拒绝、迁移成 `draft_saved`，还是单独 backfill。
- `amazon_draft_visibility` ORM 使用 Python-side default：`backend/app/models/models.py:404`；MySQL 缺列补齐使用 server default：`backend/app/database.py:134`。当前 ORM 插入路径安全；若后续 T3/T4 增加 raw SQL/backfill，需要显式写 `unconfirmed` 或补 server_default。
- `update_aplus_publish_item_evidence()` 暂不校验 `amazon_draft_visibility` 枚举值：`backend/app/services/aplus_publish_state.py:100`、`:129`。T1 没有生产者，不阻断；T4 实现 draft visibility 时应收敛为明确值集，避免把未知可见性状态写成事实。

## Verification

- `cd backend && .venv/bin/python -m compileall -q app`：PASS。
- `make test-project-rules`：PASS，63 tests。
- `git diff --check`：PASS。
- scoped `rg`：未发现新增 Lingxing planner/worker/task API/A+ done auto trigger；仅命中 T1 project-rule forbidden checks 和旧 legacy batch entry。

## Gate Meaning

- 允许：若命 scoped commit T1 实现；进入 T2 seller SKU persistence / Lingxing Listing sync 设计与实现。
- 不允许：跳过 T2 直接保存领星草稿；启用 A+ done 自动发布；新增提交审批默认路径；把 `draft_saved` 当作 Amazon A+ draft visibility；把领星发布状态并入商品主 workflow `work_status`。
- T2 前置提醒：必须持久化 Amazon export 实际 seller SKU，并把 Lingxing Listing/ASIN 匹配改成 seller SKU/MSKU first；UPC 只能作为辅助诊断，不能作为 A+ publish 主匹配依据。
