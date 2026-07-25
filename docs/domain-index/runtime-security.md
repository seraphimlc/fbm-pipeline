# Domain Index: Runtime Security And Startup

## 范围

- 本地服务绑定、API 访问边界、mutating endpoint 保护。
- API startup 副作用、migration/backfill/runtime kick 边界。
- 外部 HTTP TLS 校验和本地文件/图片代理边界。
- Integration hardening database source manifest、detached digest 与 backup provenance 的纯数据合同边界。
- 可执行 Legacy inventory 的临时 schema、backup/restore、分类与清理边界。

## 当前口径

- 默认服务应只监听 `127.0.0.1`。
- mutating endpoints 不能在默认配置下被局域网匿名调用；本机访问放行，远程访问必须显式配置 `API_DEV_TOKEN`。
- 普通 API startup 不应自动执行 DDL/backfill/index rebuild/task kick；相关行为由 `STARTUP_RUN_DB_MAINTENANCE`、`STARTUP_RUN_BACKFILLS`、`STARTUP_RECOVER_TASKS`、`STARTUP_KICK_TASK_RUNTIME` 显式开启。
- 外部 token-bearing 请求默认开启 TLS verify；私有代理应配置 `EXTERNAL_HTTP_CA_BUNDLE`，不要默认关闭校验。
- 文件/图片代理默认只开放 `PRODUCT_BASE_DIR`，额外目录必须通过 `IMAGE_PROXY_EXTRA_ROOTS` 显式配置；不默认开放 `~/Documents` 或 `/tmp`。
- Integration hardening database source manifest 是只接收 dict/bytes 的纯 stdlib 数据合同：校验 canonical manifest body、detached digest、backup hash binding 与 source-side legacy empty proof；它不连接 MySQL、不读取 env、不执行 capture/dump/restore，也不证明 backup 与 manifest 已真实来自同一快照、restore 成功或 Phase 0 PASS。通过 source-side empty proof 后仍需后续 restore 逐项一致性验证。
- `IH-R1-LEGACY-INVENTORY` 已提供首个真正可执行的只读路径：纯 core 让 candidate group 只拥有 candidate/capture 行、legacy Product workflow 独立成记录，并以 `Counter` 对全部物理 source row 做 exactly-once fail-closed；`succeeded` 且无候选固定进入 manual review。精确 `batch/site/item_code` Product 匹配同时读取真实 ASIN、Amazon template path/generated/fill-summary/warnings、Catalog confirmed/export/A+ 与可稳定归属的成功 A+ item，存在不可逆 downstream facts 时只允许 `audit_only`，current competitor conflict 仍为 `review_required`。成功 A+ item 缺 Product/Catalog 或 Catalog/Product 不一致时固定进入 `review_required`，不能降为 interrupted/audit-only。
- Legacy fixture manifest/restore 绑定 `products`、`product_data`、`catalog_products`、`aplus_upload_items`、candidate、capture 共 6 表及 6 个 decision projections。`legacy_migration.py` 输出 deterministic `records` + `records_sha256`、实际 HEAD、clean/dirty status paths、runtime source-file hashes；运行时实测范围仅为 `git/mysql/mysqldump` subprocess、本机 `127.0.0.1:3306`、fixture `task_runs/task_steps` delta、隔离 `DATA_DIR`/Step 10 output delta 和 cleanup。external network/browser 没有 Python runtime monitor，只能标为 `observed=false / static_review_only`，不得伪装成运行时零值。
- Legacy inventory 当前只执行 inventory/restore verification，不执行 migration apply，不写真实业务 schema，不读取应用 `DATABASE_URL`，不创建 TaskRun，不启动浏览器，不访问外部平台，不生成 Step 10 输出，也不代表 legacy migration、AC-1、Phase 0 或 merge-ready 已完成。

## 关键入口

- 启动脚本：`scripts/start.sh`
- 后端入口：`backend/app/main.py`
- 配置：`backend/app/config.py`, `backend/.env.example`
- 数据库初始化：`backend/app/database.py`
- 配置 API：`backend/app/api/config_api.py`
- 任务 API：`backend/app/api/task_runs.py`
- 商品/文件/导出 API：`backend/app/api/products.py`
- 数据源 API：`backend/app/api/data_sources.py`
- 外部 HTTP client：`backend/app/services/aplus_upload.py`, `backend/app/pipeline/step9_aplus_image.py`
- Integration hardening canonical JSON 公共核：`scripts/integration_hardening/common.py`
- Integration hardening database source manifest 纯数据合同：`scripts/integration_hardening/database_source_manifest.py`
- Legacy inventory pure core：`scripts/integration_hardening/legacy_inventory.py`
- Legacy inventory protected MySQL execution：`scripts/integration_hardening/legacy_inventory_mysql.py`, `scripts/integration_hardening/legacy_migration.py`
- Legacy inventory source/side-effect evidence：`scripts/integration_hardening/legacy_run_evidence.py`
- Legacy inventory deterministic fixture：`scripts/integration_hardening/legacy_inventory_fixture.py`
- Integration hardening database source manifest focused gate：`scripts/testing/test_integration_hardening_database_source_manifest.py`
- Legacy inventory focused core gate：`scripts/testing/test_integration_hardening_legacy_inventory.py`
- Legacy inventory non-empty MySQL E2E gate：`scripts/testing/test_integration_hardening_legacy_inventory_mysql.py`

## 关键流程

- 启动：`scripts/start.sh` -> `backend/app/main.py` lifespan -> DB/runtime 初始化。
- mutating API：`backend/app/main.py` middleware -> 本机访问/dev token guard -> router -> service/action。
- TLS 请求：`settings.external_http_verify` -> HTTP client -> 外部服务。
- 图片代理：`/api/images/{file_path}` -> `settings.image_proxy_roots` -> `Path.relative_to()` 结构化路径校验。

## 相关文档

- `docs/superpowers/specs/2026-07-25-integration-hardening-plan-status-review.md`
- `docs/superpowers/specs/2026-07-25-legacy-real-backup-inventory-technical-design.md`
- `docs/configuration.md`
- `docs/runbook.md`

## 验证入口

- 后端健康检查：`GET /api/health`
- 项目规则：`make test-project-rules`
- Integration hardening database source manifest contract：`python3 scripts/testing/test_integration_hardening_database_source_manifest.py`（纯数据校验；不执行 capture/dump/restore，不代表同快照、restore 或 Phase 0 PASS）
- Legacy inventory focused core：`/usr/bin/python3 -B scripts/testing/test_integration_hardening_legacy_inventory.py`
- Legacy inventory non-empty MySQL fixture：`/usr/bin/python3 -B scripts/testing/test_integration_hardening_legacy_inventory_mysql.py`（覆盖独立 schema allocation/load/import、owned-only cleanup、TaskRun/TaskStep state digest 与 Step 10 directory/symlink guard）
- Legacy inventory executable summary：`/usr/bin/python3 -B scripts/integration_hardening/legacy_migration.py --fixture-e2e`
- 后端编译：`make backend-compile`
- 全量检查：`make check`
- 启动命令：先看 `scripts/start.sh` 当前默认 host。

## 常见定位

- 远程访问风险：先看 `scripts/start.sh`、`backend/app/main.py` 和 router guard。
- 启动改库/唤醒任务：先看 `backend/app/main.py` lifespan 和 `backend/app/config.py` 的 `STARTUP_RUN_*` 开关，再看 `backend/app/database.py`。
- TLS verify：先看 `backend/app/config.py`、`aplus_upload.py`、`step9_aplus_image.py`。
- 图片代理：先看 `backend/app/main.py` 中 image proxy 路由和允许根目录。

## 维护规则

只有启动入口、访问边界、TLS 默认值、文件代理目录、startup 副作用或验证入口变化时更新本文。普通 bug fix、函数内部重构、文案微调、测试补充不需要更新。
