# Domain Index: Runtime Security And Startup

## 范围

- 本地服务绑定、API 访问边界、mutating endpoint 保护。
- API startup 副作用、migration/backfill/runtime kick 边界。
- 外部 HTTP TLS 校验和本地文件/图片代理边界。

## 当前口径

- 默认服务应只监听 `127.0.0.1`。
- mutating endpoints 不能在默认配置下被局域网匿名调用；本机访问放行，直接远程 FastAPI 写请求必须显式携带 `API_DEV_TOKEN`。
- 非 loopback Vite 开发前端使用双层写保护：`scripts/read_startup_env.py` 单次按 python-dotenv 语义快照 `backend/.env` 的 effective `FRONTEND_HOST`（缺省 `127.0.0.1`）与双 token，并在 helper 内统一识别 `localhost`、`127/8`、`::1`、IPv4-mapped IPv6 和 bracket IPv6。若该快照为 remote，解码并 trim 后的双 token 必须分别为 1..4096 UTF-8 字节、每字节均为可见 ASCII `0x21..0x7E`，且字节完全一致。helper 将同一快照 host/token 注入 child env并签发一次性 FD proof；`scripts/start.sh` 首阶段不读取/分类 `FRONTEND_HOST`，continuation 通过 proof 后只使用注入 host，因此 `.env` 竞态或父环境不能产生“remote host + 未验证 token”。失败发生在 database/uvicorn/Vite 前，loopback snapshot 不强制 transport 合同。`frontend/dev-api-write-guard.ts` 在 proxy 前按原始 socket 校验调用方 token，成功后只增加 remote marker，`backend/app/main.py` 再独立校验同一调用方 token。XFF/Forwarded 不参与本机判断，非空 `X-FBM-Dev-Token` 优先于 Bearer，token 不进入客户端 bundle 或由 proxy 代注。
- `frontend/vite.config.ts` 仅用 `loadEnv(..., 'VITE_')` 恢复非敏感 `VITE_BACKEND_URL` / `VITE_FRONTEND_PORT` 的 mode-specific 配置，显式 process env 优先；写 token 始终只读 `process.env.DEV_API_WRITE_TOKEN`，frontend env 中的 `DEV_API_WRITE_TOKEN` / `VITE_DEV_API_WRITE_TOKEN` 均不授权。
- 前端 axios interceptor 只识别 status 403 且 code 为 `REMOTE_DEV_READ_ONLY` 的标准拒绝，统一错误文案后 reject 同一错误对象；`fbmMutationCallsiteId` 只保留在 axios request config 供测试观测，不进入 URL、header、query 或 body。D2b 的 inventory/owner contract、生产 wrapper 与 Playwright runtime gate 均已启用：workflow registry 间接 closure 必须由 lookup、execute alias/fallback 到实际 call callee 的 AST 链路证明，dead reference 不算覆盖；wrapper boundary 必须是 `.catch(() => undefined)`，callback 内未调用的嵌套 function-like 不算 toast/clear/operation 证据，loading setter 必须一次写入 owner `useState` 的显式 `false|null` 初值。test-only observer 仅通过页面动态 import 安装 axios request interceptor，mutation 不被 mock，继续到真实非 loopback Vite pre-guard 403；runtime harness 对 page error / unhandled rejection fail-fast，并最终证明 upstream/backend 写入均为 0。
- 普通 API startup 不应自动执行 DDL/backfill/index rebuild/task kick；相关行为由 `STARTUP_RUN_DB_MAINTENANCE`、`STARTUP_RUN_BACKFILLS`、`STARTUP_RECOVER_TASKS`、`STARTUP_KICK_TASK_RUNTIME` 显式开启。
- 本地一键启动 `scripts/start.sh` 在启动 uvicorn 前会显式执行 `python -m app.database`，跑可重复 schema maintenance，确保 ORM 新字段和 MySQL 现有测试库对齐；这不改变普通 API lifespan 的默认 no-DDL 边界。
- 外部 token-bearing 请求默认开启 TLS verify；私有代理应配置 `EXTERNAL_HTTP_CA_BUNDLE`，不要默认关闭校验。
- 文件/图片代理默认只开放 `PRODUCT_BASE_DIR`，额外目录必须通过 `IMAGE_PROXY_EXTRA_ROOTS` 显式配置；不默认开放 `~/Documents` 或 `/tmp`。

## 关键入口

- 启动脚本：`scripts/start.sh`
- 启动 dotenv 读取：`scripts/read_startup_env.py`
- 后端入口：`backend/app/main.py`
- Vite proxy 前写保护：`frontend/dev-api-write-guard.ts`, `frontend/vite.config.ts`
- 前端标准 403 与 mutation D2a foundation：`frontend/src/api/index.ts`, `frontend/src/api/mutationRunner.ts`, `frontend/src/api/mutationInventory.generated.ts`, `frontend/src/api/mutationOwnerContract.ts`
- 配置：`backend/app/config.py`, `backend/.env.example`
- 数据库初始化：`backend/app/database.py`
- 配置 API：`backend/app/api/config_api.py`；本地环境变量页面通过 `/api/config/local-env` 读取脱敏列表、逐项更新或导入 `backend/.env`，敏感值不得由读取接口返回。
- 任务 API：`backend/app/api/task_runs.py`
- 商品/文件/导出 API：`backend/app/api/products.py`
- 数据源 API：`backend/app/api/data_sources.py`
- 外部 HTTP client：`backend/app/services/aplus_upload.py`, `backend/app/pipeline/step9_aplus_image.py`
- 领星 ERP A+ 上传/发布：`docs/lingxing-aplus-upload.md`、`docs/superpowers/specs/2026-06-23-lingxing-aplus-publish-after-aplus-done-prd.md`、`docs/superpowers/specs/2026-06-23-lingxing-aplus-publish-technical-plan.md` 和 `docs/superpowers/specs/2026-06-24-lingxing-aplus-enhanced-basic-prd.md`；该链路依赖本机 Chrome 登录态、token-bearing HTTP 请求和真实外部网关。T1 仅新增字段、状态 registry、single writer 和 schema/index bootstrap，不触发真实外部调用。T2 新增 `backend/app/services/lingxing_listing_client.py` 和 `lingxing_listing_sync` task，真实 Listing 读取默认由 `LINGXING_LISTING_SYNC_ALLOW_REAL_EXTERNAL_CALLS=false` fail closed；即使显式开启，也必须同时配置 `LINGXING_APLUS_STORE_NAME` 和 `LINGXING_APLUS_STORE_ID`，缺失时返回 `store_config_required`，不得回落到旧默认店铺。T3 新增 `backend/app/services/lingxing_aplus_publish_client.py` 和 `lingxing_aplus_publish` task，真实草稿保存默认由 `LINGXING_APLUS_ALLOW_REAL_EXTERNAL_CALLS=false` fail closed，`LINGXING_APLUS_SUBMIT_FOR_APPROVAL=false` 且 T3 client 不支持 submit；enhanced `enhanced_basic_aplus_v1` 只增加多 slot 本地 preflight、上传和 mapper assembly，不改变默认外部调用关闭、draft-save-only、submit/edit/draft visibility 禁止边界；task event 只能记录 seller SKU/ASIN/store/site/idHash/slot id/结果摘要，不得记录 cookie、token 或完整 header。

## 关键流程

- 启动：`scripts/start.sh` -> `python -m app.database` 可重复 schema maintenance -> `backend/app/main.py` lifespan -> DB/runtime 初始化。
- 远程 Vite 写请求：原始 browser socket -> Vite pre middleware token guard -> `X-FBM-Proxy-Client: remote` -> FastAPI token guard -> router；任一层拒绝均返回 `REMOTE_DEV_READ_ONLY` 标准 403。
- 直接 mutating API：`backend/app/main.py` middleware -> 本机访问/dev token guard -> router -> service/action。
- TLS 请求：`settings.external_http_verify` -> HTTP client -> 外部服务。
- 领星 A+ 上传旧链路：本机 Chrome 读取领星 Cookie/localStorage/sessionStorage -> 领星网关 `uploadDestination/add/edit` -> 外部对象存储表单上传 -> Product/Catalog A+ 上传状态回写。新 Lingxing A+ 发布工程线 T1 只有 `backend/app/aplus_publish/status.py`、`backend/app/services/aplus_publish_state.py` 和 `backend/app/database.py` schema/index 维护，不新增外部 HTTP/Chrome 调用入口。T2 的 `lingxing_listing_sync` 只读取 Listing / ASIN 前置，默认禁止真实外部请求。T3/M3 的 `lingxing_aplus_publish` 可在显式开启真实外部调用后执行 `uploadDestination` + `amazon/aplus/add` 保存草稿；enhanced profile 会上传 7 个 registry slot assets 并按 `asset_slot_id` 组装 payload，但默认仍禁止真实外部请求，不调用 edit/submit/sync visibility，不写 `draft_visible`。M3.3 readiness 脚本 `scripts/check_lingxing_enhanced_aplus_qa_readiness.py` 只能只读检查配置、候选样本、policy 和 mapper，不调用 Lingxing auth、`uploadDestination`、对象上传或 `amazon/aplus/add`。M3.3 sample 脚本 `scripts/prepare_lingxing_enhanced_aplus_qa_sample.py` 默认 dry-run；只有显式 `--write` 才允许写本地 ProductAplus 和 slot 图片，且仍不得触发真实外部调用或创建发布 task。
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
- 远程 Vite/FastAPI 判别性验证：`python3 scripts/test_stability_repair_r1_remote_guard.py`
- 前端 mutation foundation：`cd frontend && npm run mutations:check`
- 后端编译：`make backend-compile`
- 全量检查：`make check`
- 启动命令：先看 `scripts/start.sh` 当前默认 host。

## 常见定位

- 远程访问风险：先看 `scripts/read_startup_env.py` 的 host+token 单快照分类/校验、`scripts/start.sh` 的 FD proof continuation 与最终 Vite host来源、`frontend/dev-api-write-guard.ts` proxy 前 guard、`frontend/vite.config.ts` middleware 顺序、`backend/app/main.py` remote marker 二次校验，再跑包含 `.env` before/after snapshot race 的真实多进程 remote guard harness。
- 启动改库/唤醒任务：先区分本地一键启动脚本和普通 API lifespan；`scripts/start.sh` 会先跑 `python -m app.database` 补齐 schema，`backend/app/main.py` lifespan 仍由 `STARTUP_RUN_*` 开关控制维护、backfill、恢复和 runtime kick，再看 `backend/app/database.py`。
- TLS verify：先看 `backend/app/config.py`、`aplus_upload.py`、`step9_aplus_image.py`。
- Amazon 图片 XMP 合规：`backend/app/services/amazon_image_compliance.py` 使用配置的 `IMAGE_COMPLIANCE_EXIFTOOL_PATH` 写入/读取元数据；含人物投放图在 OSS 上传后由 `download_private_file()` 回读并核验标签及 SHA-256。真实 OSS 门槛脚本为 `scripts/test_amazon_image_compliance_oss.py`，未配置 OSS 或 ExifTool 时只能 SKIPPED。
- 领星 A+ 发布风险：先看 `docs/superpowers/specs/2026-06-23-lingxing-aplus-publish-after-aplus-done-prd.md`、`docs/superpowers/specs/2026-06-23-lingxing-aplus-publish-technical-plan.md`、`docs/superpowers/specs/2026-06-24-lingxing-aplus-enhanced-basic-prd.md`、`docs/lingxing-aplus-upload.md`、`backend/app/services/lingxing_listing_client.py`、`backend/app/services/lingxing_aplus_publish_client.py`、`backend/app/services/lingxing_aplus_publish_policy.py`、`backend/app/services/lingxing_aplus_module_mapper.py` 和 `backend/app/services/aplus_upload.py`；确认 Chrome 登录态、真实外部请求配置、自动提交审批、multi-slot upload map 和 task/runtime 审计边界。T2 真实 Listing 读取必须显式设置 `LINGXING_LISTING_SYNC_ALLOW_REAL_EXTERNAL_CALLS=true`、`LINGXING_APLUS_STORE_NAME` 和 `LINGXING_APLUS_STORE_ID`。T3/M3 真实草稿保存必须显式设置 `LINGXING_APLUS_ALLOW_REAL_EXTERNAL_CALLS=true` 和 `LINGXING_APLUS_STORE_ID`，并保持 `LINGXING_APLUS_SUBMIT_FOR_APPROVAL=false`。
- 图片代理：先看 `backend/app/main.py` 中 image proxy 路由和允许根目录。

## 维护规则

只有启动入口、访问边界、TLS 默认值、文件代理目录、startup 副作用或验证入口变化时更新本文。普通 bug fix、函数内部重构、文案微调、测试补充不需要更新。
