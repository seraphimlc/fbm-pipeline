# Lingxing A+ Publish T2 Code Review

结论：`CODE_REVIEW / NEEDS_FIX`

本轮 T2 不能进入 scoped commit，也不能进入 T3 草稿保存。主要原因是 Listing sync 成功写 ASIN 的保护门仍可能在历史 Product/Catalog 镜像不一致或未明确可信的旧导出记录上写错 ASIN。验证命令通过，但现有行为脚本没有覆盖这两个数据不变量。

## Review Scoping

- 身份：镜花（agentKey: `jinghua`）。
- 审查对象：`MSG-20260623-005` T2 `DONE_CLAIMED / FIXED` 与 `MSG-20260623-006` code review 请求。
- 审查节点：`IMPLEMENTATION_REVIEW + DATA_REVIEW + TASK_RUNTIME_REVIEW + SECURITY_REVIEW + TEST_REVIEW + DOCUMENTATION_REVIEW`。
- 审查范围：指定 T2 文件、相关 diff、`docs/superpowers/specs/2026-06-23-lingxing-aplus-publish-technical-plan.md`、T1 review、domain indexes、行为脚本和 project rules。
- 不审：不做页面 QA、不验证真实 Lingxing 登录/真实 Listing 读取、不改业务代码、不提交、不 push。
- 通过标准：Amazon export `sku` 与持久化 seller SKU 同源；ASIN 匹配必须 seller SKU/MSKU exact first，UPC 只能诊断；0/多匹配、错店铺/错站点、不可售、任一本地 ASIN 冲突都不能写错 ASIN；task runtime/API/client 默认安全；T2 不越界到 A+ 草稿/可见性/提交/自动触发/商品主 workflow。

## Blocking Findings

### P1 - Product-only ASIN 冲突会被覆盖，违反“本地已有 ASIN 不得静默覆盖”

`backend/app/services/asin_match_policy.py:293` 只读取 `catalog.amazon_asin` 作为 `existing_asin`，`backend/app/task_runtime/lingxing_listing_sync_workers.py:101` 到 `:104` 在匹配成功后会直接写 `product.amazon_asin = decision.asin`。如果历史数据里 `Product.amazon_asin` 已有真实 ASIN、但 `CatalogProduct.amazon_asin` 为空或镜像漂移，`decide_asin_match()` 会返回 matched，worker 会覆盖 Product 上的本地 ASIN。

这不是理论上的类型问题：`Product.amazon_asin` 和 `CatalogProduct.amazon_asin` 是两个独立列，见 `backend/app/models/models.py:14` 和 `:289`；T2 行为脚本的 conflict case 只在 `_make_product(... existing_asin=...)` 同时设置 Product 与 Catalog ASIN，见 `scripts/test_lingxing_listing_sync_tasks.py:219`、`:270` 到 `:272`，没有覆盖 Product-only / Catalog-only / Product-Catalog 互相冲突。

完整修复边界：

- ASIN 冲突判断必须同时读取 `CatalogProduct.amazon_asin` 和关联 `Product.amazon_asin`；任一已有本地 ASIN 与 Lingxing 返回 ASIN 不一致都必须返回 `asin_conflict`，不得写 Catalog 或 Product。
- 如果 Product 与 Catalog 本身已有两个不同 ASIN，也应先阻断并写 evidence，而不是选择其中一个。
- 行为脚本必须补 Product-only ASIN、Catalog-only ASIN、Product/Catalog 互相冲突三个回归样本，断言 Product/Catalog 都不被覆盖。

必要验证：

- `cd backend && .venv/bin/python ../scripts/test_lingxing_listing_sync_tasks.py`
- `make test-project-rules`
- `cd backend && .venv/bin/python -m compileall -q app`
- `git diff --check`

### P1 - 旧导出兼容 seller SKU 的可信条件过宽，可能用当前 item_code 猜 ASIN 主匹配键

技术计划要求旧记录只有在“export evidence 和当前代码证明这就是实际模板 SKU”时，才能从 `ProductData.item_code` / `CatalogProduct.item_code` bootstrap 或兼容；否则应留空并进入 `waiting_listing`。当前 `seller_sku_candidate()` 在 `catalog.amazon_seller_sku` 为空时，只要 `catalog.exported_at` 存在，就把 `catalog.item_code or product.data.item_code` 当作 `compat_item_code_exact` 的 trusted seller SKU，见 `backend/app/services/asin_match_policy.py:158` 到 `:167`。

这个条件没有检查旧导出 result row 是否有 `Seller SKU` 证据，也没有检查 Product/Catalog 是否已经持久化过 `amazon_seller_sku`。如果历史导出后 `item_code` 被改过，或某类目历史模板 `sku` 并非当前 item_code，这条 fallback 会把“当前 item_code”当作 seller SKU/MSKU exact 主键，并在唯一匹配时写 ASIN，见 `backend/app/services/asin_match_policy.py:305` 到 `:311` 与 worker 写入路径 `backend/app/task_runtime/lingxing_listing_sync_workers.py:85` 到 `:105`。

完整修复边界：

- T2 新链路应优先要求 `CatalogProduct.amazon_seller_sku`，必要时接受 `Product.amazon_seller_sku` 镜像作为同一事实修复来源。
- 对旧导出兼容别名，不能仅凭 `exported_at` 判定 trusted；需要显式迁移/回填证据、导出 result seller_sku 证据或其它可审计标记。没有证据时返回 `missing_seller_sku` / `waiting_listing`，不能查询并写 ASIN。
- 行为脚本要新增“已 exported_at 但无 amazon_seller_sku 的旧记录不自动用 item_code 写 ASIN”用例；如果保留兼容路径，也要有“明确 trusted compat 才允许写”的正例。

必要验证同 P1-1。

## Passed Checks

- Amazon export `sku` 填充与 seller SKU 证据同源：`amazon_seller_sku_for_export()` 当前返回 `ProductData.item_code`，`apply_listing_fill()` 用同一 helper 写 `fields["sku"]`，见 `backend/app/pipeline/amazon_export/listing_fill.py:8` 到 `:27`；导出 preview 和 report rows 也调用同一 helper，见 `backend/app/api/products.py:915`、`:3988` 到 `:3994`、`:4079` 到 `:4085`。
- 新 task export 与旧 offline export 成功路径都持久化 Product/Catalog seller SKU：新 worker 见 `backend/app/task_runtime/catalog_export_workers.py:118` 到 `:135`；旧 offline path 见 `backend/app/services/offline_tasks.py:1137` 到 `:1154`；result rows 暴露 `seller_sku`，见 `backend/app/services/offline_tasks.py:100` 到 `:106`。
- `asin_match_policy` 的主匹配流程已经具备 seller SKU exact、UPC auxiliary evidence、0/多匹配、错店铺/错站点、不可售和 Catalog ASIN 冲突分支：见 `backend/app/services/asin_match_policy.py:211` 到 `:312`。阻断点是本地 ASIN 和 trusted compat 的覆盖范围，不是策略骨架缺失。
- 旧 `asin_sync.py` 新建 item 不再 UPC 优先：`build_sync_item()` 使用 `seller_sku_candidate(catalog)` 并把新 item `lookup_type` 设为 `MSKU`，缺 seller SKU 时 skipped，见 `backend/app/services/asin_sync.py:467` 到 `:478`；旧已保存 UPC/SKU 类型仍由 `_normalize_lookup_type()` 兼容，见 `backend/app/services/asin_sync.py:54` 到 `:60`。
- 新 task runtime 入口、label、worker 注册已建立：API `POST /api/task-runs/lingxing-listing-sync` 见 `backend/app/api/task_runs.py:644` 到 `:660`；task/step label 见 `backend/app/api/task_runs.py:59` 到 `:86` 和 `backend/app/task_runtime/display.py:68`；worker 注册见 `backend/app/main.py:78`。
- planner 具备基本 dedupe/correlation/idempotency：`backend/app/task_planners/lingxing_listing_sync.py:64` 到 `:85`。非阻断风险：dedupe key 未包含 store/site，而 API payload 允许 store/site override；若命可在返工时顺手评估是否把 store/site 纳入 key 或拒绝同 active run 的不同 store/site 复用。
- `lingxing_listing_client.py` 默认 fail closed，真实外部调用必须显式开启，并且开启后强制 store_name/store_id 非空才调用旧 auth：`backend/app/services/lingxing_listing_client.py:41` 到 `:57`；配置默认空/关闭见 `backend/app/config.py:78` 到 `:81` 和 `backend/.env.example:60` 到 `:64`。
- worker event 没有记录 cookie/token/header；事件数据只包含 endpoint family、seller_sku、store_id、site、row counts 和 client evidence 摘要，见 `backend/app/task_runtime/lingxing_listing_sync_workers.py:152` 到 `:164`、`:199` 到 `:212`。
- scoped 越界扫描未发现 T2 新增 A+ 草稿保存 worker/API、draft visibility/submit worker/API、`AUTO_LINGXING_APLUS_AFTER_DONE` 自动触发、商品主 workflow / work_status / 前端按钮改动。现有命中主要是 legacy `aplus_upload.py` 和 T1 预留 evidence 字段，不是本轮新增 T3+ 链路。
- 不需要补 `docs/template-mapping-change-log.md` 的判断成立：本轮没有改 `template_mappings/*.json`、模板文件、类目选择或 Step10 字段映射语义；`sku` 字段仍来自当前实际模板填充值，只是抽出 helper 并在导出成功后持久化/报告 seller SKU 证据。若返工改变模板 `sku` 填充规则或类目映射，再需要追加变更日志。

## Test Coverage Gaps

- `scripts/test_lingxing_listing_sync_tasks.py` 覆盖无 seller SKU、0 匹配、多匹配、成功唯一匹配、UPC auxiliary-only、Catalog/Product 同时已有 ASIN 冲突、错店铺/错站点、不可售和 active dedupe 复用，见 `:214` 到 `:283`。
- 缺口是上述两个 P1：Product-only ASIN、Catalog-only ASIN、Product/Catalog 互相冲突，以及 exported_at-only 旧记录不应被当作 trusted compat seller SKU。
- `scripts/test_project_rules.py` 的 T2 contract 目前是字符串级防线，能防止明显删除 seller SKU first/client fail-closed/越界 API，但不能证明冲突保护的数据行为，见 `scripts/test_project_rules.py:1059` 到 `:1156`。

## Verification

- `cd backend && .venv/bin/python -m compileall -q app`：PASS。
- `cd backend && .venv/bin/python ../scripts/test_lingxing_listing_sync_tasks.py`：PASS。
- `make test-project-rules`：PASS，64 tests。
- `git diff --check`：PASS。

## Gate Meaning

- 不允许：若命 scoped commit T2；进入 T3 Lingxing A+ draft save；把当前行为脚本 PASS 当成 ASIN 写入保护闭环。
- 允许：听云按上述 P1 边界返工；返工后镜花复审可以只聚焦 ASIN conflict / trusted seller SKU compat / 新增回归用例，并复跑同一组验证命令。

## Rereview - 2026-06-23 CST

结论：`CODE_REVIEW_REREVIEW / PASS_WITH_SCOPE`

复审范围只覆盖上一轮两个 P1，不扩展到 T3/T4、页面 QA 或真实领星外部服务验收。

- ASIN conflict 已闭合：`decide_asin_match()` 通过 `local_asin_values()` 同时读取 `CatalogProduct.amazon_asin` 和关联 `Product.amazon_asin`；Product-only、Catalog-only、Product/Catalog mismatch 都会进入 `asin_conflict`，worker 只在 `decision.matched` 时写两侧 ASIN。
- Seller SKU fallback 已闭合：`seller_sku_candidate()` 只信任 `CatalogProduct.amazon_seller_sku` 或 `Product.amazon_seller_sku` 镜像修复来源；函数内已无 `catalog.exported_at + item_code` 隐式 fallback。
- 行为测试已补齐：`scripts/test_lingxing_listing_sync_tasks.py` 覆盖 Product-only conflict、Catalog-only conflict、Product/Catalog mismatch，以及 exported_at-only old record 不使用 item_code 写 ASIN。
- Project rules 已加护栏：`scripts/test_project_rules.py` 防止 `seller_sku_candidate()` 重新引入 `catalog.exported_at` fallback，并要求行为脚本保留四个 P1 回归用例。

复跑验证：

- `cd backend && .venv/bin/python ../scripts/test_lingxing_listing_sync_tasks.py`：PASS。
- `make test-project-rules`：PASS。
- `cd backend && .venv/bin/python -m compileall -q app`：PASS。
- `git diff --check`：PASS。

残余非阻断风险：

- `scripts/test_project_rules.py` 仍是字符串级防线，真正防错主要靠行为脚本。
- `ASIN_MATCH_SOURCE_COMPAT_ITEM_CODE` 仍保留给旧 batch evidence 使用，但不在 T2 `seller_sku_candidate()` / new build path 中作为 exported_at fallback。

Gate meaning：允许若命对 T2 做 scoped commit/push；不代表 T3/T4、页面 QA 或真实领星外部服务验收通过。
