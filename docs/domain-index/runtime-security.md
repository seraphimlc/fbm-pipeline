# Domain Index: Runtime Security And Startup

## 范围

- 本地服务绑定、API 访问边界、mutating endpoint 保护。
- API startup 副作用、migration/backfill/runtime kick 边界。
- 外部 HTTP TLS 校验和本地文件/图片代理边界。

## 当前口径

- 默认服务应只监听 `127.0.0.1`。
- mutating endpoints 不能在默认配置下被局域网匿名调用；本机访问放行，远程访问必须显式配置 `API_DEV_TOKEN`。
- 普通 API startup 不应自动执行 DDL/backfill/index rebuild/task kick；相关行为由 `STARTUP_RUN_DB_MAINTENANCE`、`STARTUP_RUN_BACKFILLS`、`STARTUP_RECOVER_TASKS`、`STARTUP_KICK_TASK_RUNTIME` 显式开启。
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

## 关键流程

- 启动：`scripts/start.sh` -> `backend/app/main.py` lifespan -> DB/runtime 初始化。
- mutating API：`backend/app/main.py` middleware -> 本机访问/dev token guard -> router -> service/action。
- TLS 请求：`settings.external_http_verify` -> HTTP client -> 外部服务。
- 图片代理：`/api/images/{file_path}` -> `settings.image_proxy_roots` -> `Path.relative_to()` 结构化路径校验。

## 相关文档

- `docs/superpowers/specs/2026-06-17-p0-security-startup-triage-prd.md`
- `docs/collaboration/reviews/2026-06-17-whole-project-code-audit-rerun.md`
- `docs/collaboration/reviews/2026-06-17-whole-project-code-review.md`
- `docs/configuration.md`
- `docs/runbook.md`

## 验证入口

- 后端健康检查：`GET /api/health`
- 项目规则：`make test-project-rules`
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
