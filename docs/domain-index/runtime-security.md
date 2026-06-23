# Domain Index: Runtime Security And Startup

## 范围

- 本地服务绑定、API 访问边界、mutating endpoint 保护。
- API startup 副作用、migration/backfill/runtime kick 边界。
- 外部 HTTP TLS 校验和本地文件/图片代理边界。

## 当前口径

- 默认服务应只监听 `127.0.0.1`。
- mutating endpoints 不能在默认配置下被局域网匿名调用；本机访问放行，远程访问必须显式配置 `API_DEV_TOKEN`。
- 普通 API startup 不应自动执行 DDL/backfill/index rebuild/task kick；相关行为由 `STARTUP_RUN_DB_MAINTENANCE`、`STARTUP_RUN_BACKFILLS`、`STARTUP_RECOVER_TASKS`、`STARTUP_KICK_TASK_RUNTIME` 显式开启。
- 本地一键启动 `scripts/start.sh` 在启动 uvicorn 前会显式执行 `python -m app.database`，跑可重复 schema maintenance，确保 ORM 新字段和 MySQL 现有测试库对齐；这不改变普通 API lifespan 的默认 no-DDL 边界。
- 外部 token-bearing 请求默认开启 TLS verify；私有代理应配置 `EXTERNAL_HTTP_CA_BUNDLE`，不要默认关闭校验。
- 文件/图片代理默认只开放 `PRODUCT_BASE_DIR`，额外目录必须通过 `IMAGE_PROXY_EXTRA_ROOTS` 显式配置；不默认开放 `~/Documents` 或 `/tmp`。

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
- 领星 ERP A+ 上传/发布：`docs/lingxing-aplus-upload.md`、`docs/superpowers/specs/2026-06-23-lingxing-aplus-publish-after-aplus-done-prd.md` 和 `docs/superpowers/specs/2026-06-23-lingxing-aplus-publish-technical-plan.md`；该链路依赖本机 Chrome 登录态、token-bearing HTTP 请求和真实外部网关。T1 仅新增字段、状态 registry、single writer 和 schema/index bootstrap，不触发真实外部调用。T2 新增 `backend/app/services/lingxing_listing_client.py` 和 `lingxing_listing_sync` task，真实 Listing 读取默认由 `LINGXING_LISTING_SYNC_ALLOW_REAL_EXTERNAL_CALLS=false` fail closed；即使显式开启，也必须同时配置 `LINGXING_APLUS_STORE_NAME` 和 `LINGXING_APLUS_STORE_ID`，缺失时返回 `store_config_required`，不得回落到旧默认店铺。T3 新增 `backend/app/services/lingxing_aplus_publish_client.py` 和 `lingxing_aplus_publish` task，真实草稿保存默认由 `LINGXING_APLUS_ALLOW_REAL_EXTERNAL_CALLS=false` fail closed，`LINGXING_APLUS_SUBMIT_FOR_APPROVAL=false` 且 T3 client 不支持 submit；task event 只能记录 seller SKU/ASIN/store/site/idHash/结果摘要，不得记录 cookie、token 或完整 header。

## 关键流程

- 启动：`scripts/start.sh` -> `python -m app.database` 可重复 schema maintenance -> `backend/app/main.py` lifespan -> DB/runtime 初始化。
- mutating API：`backend/app/main.py` middleware -> 本机访问/dev token guard -> router -> service/action。
- TLS 请求：`settings.external_http_verify` -> HTTP client -> 外部服务。
- 领星 A+ 上传旧链路：本机 Chrome 读取领星 Cookie/localStorage/sessionStorage -> 领星网关 `uploadDestination/add/edit` -> 外部对象存储表单上传 -> Product/Catalog A+ 上传状态回写。新 Lingxing A+ 发布工程线 T1 只有 `backend/app/aplus_publish/status.py`、`backend/app/services/aplus_publish_state.py` 和 `backend/app/database.py` schema/index 维护，不新增外部 HTTP/Chrome 调用入口。T2 的 `lingxing_listing_sync` 只读取 Listing / ASIN 前置，默认禁止真实外部请求。T3 的 `lingxing_aplus_publish` 可在显式开启真实外部调用后执行 `uploadDestination` + `amazon/aplus/add` 保存草稿；默认禁止真实外部请求，不调用 edit/submit/sync visibility，不写 `draft_visible`。
- 图片代理：`/api/images/{file_path}` -> `settings.image_proxy_roots` -> `Path.relative_to()` 结构化路径校验。

## 相关文档

- `docs/superpowers/specs/2026-06-17-p0-security-startup-triage-prd.md`
- `docs/collaboration/reviews/2026-06-17-whole-project-code-audit-rerun.md`
- `docs/collaboration/reviews/2026-06-17-whole-project-code-review.md`
- `docs/configuration.md`
- `docs/lingxing-aplus-upload.md`
- `docs/superpowers/specs/2026-06-23-lingxing-aplus-publish-after-aplus-done-prd.md`
- `docs/superpowers/specs/2026-06-23-lingxing-aplus-publish-technical-plan.md`
- `docs/runbook.md`

## 验证入口

- 后端健康检查：`GET /api/health`
- 项目规则：`make test-project-rules`
- 后端编译：`make backend-compile`
- 全量检查：`make check`
- 启动命令：先看 `scripts/start.sh` 当前默认 host。

## 常见定位

- 远程访问风险：先看 `scripts/start.sh`、`backend/app/main.py` 和 router guard。
- 启动改库/唤醒任务：先区分本地一键启动脚本和普通 API lifespan；`scripts/start.sh` 会先跑 `python -m app.database` 补齐 schema，`backend/app/main.py` lifespan 仍由 `STARTUP_RUN_*` 开关控制维护、backfill、恢复和 runtime kick，再看 `backend/app/database.py`。
- TLS verify：先看 `backend/app/config.py`、`aplus_upload.py`、`step9_aplus_image.py`。
- 领星 A+ 发布风险：先看 `docs/superpowers/specs/2026-06-23-lingxing-aplus-publish-after-aplus-done-prd.md`、`docs/superpowers/specs/2026-06-23-lingxing-aplus-publish-technical-plan.md`、`docs/lingxing-aplus-upload.md`、`backend/app/services/lingxing_listing_client.py`、`backend/app/services/lingxing_aplus_publish_client.py` 和 `backend/app/services/aplus_upload.py`；确认 Chrome 登录态、真实外部请求配置、自动提交审批和 task/runtime 审计边界。T2 真实 Listing 读取必须显式设置 `LINGXING_LISTING_SYNC_ALLOW_REAL_EXTERNAL_CALLS=true`、`LINGXING_APLUS_STORE_NAME` 和 `LINGXING_APLUS_STORE_ID`。T3 真实草稿保存必须显式设置 `LINGXING_APLUS_ALLOW_REAL_EXTERNAL_CALLS=true` 和 `LINGXING_APLUS_STORE_ID`，并保持 `LINGXING_APLUS_SUBMIT_FOR_APPROVAL=false`。
- 图片代理：先看 `backend/app/main.py` 中 image proxy 路由和允许根目录。

## 维护规则

只有启动入口、访问边界、TLS 默认值、文件代理目录、startup 副作用或验证入口变化时更新本文。普通 bug fix、函数内部重构、文案微调、测试补充不需要更新。
