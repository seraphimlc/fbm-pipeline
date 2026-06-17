# CODE_AUDIT_REPORT / NEEDS_FIX - Whole Project Rerun

- Reviewer: 镜花（agentKey: `jinghua`）
- Created: 2026-06-17 CST
- Trigger: 用户要求“再做一遍全量审计”
- Mode: 全量审计，只读
- Conclusion: `NEEDS_FIX`

结论：`make check`、前端构建和 `git diff --check` 都通过，但代码 gate 不能 PASS。当前项目的主要风险不是单个编译错误，而是运行安全边界、启动副作用、任务状态合同、幂等并发、运行器可靠性和测试可信度不足。存在 P0/P1，按镜花职责不能给 `PASS`。

## AUDIT_PLAN - 镜花（agentKey: `jinghua`）

- 审计目标: 对当前工作区做全量只读代码审计，输出可执行的 P0/P1/P2 findings、证据、修复顺序和未覆盖风险。
- 审计范围: 当前仓库代码、文档、配置样例、脚本、前后端 API 合同、任务运行链路、导出链路、仓库卫生；重点覆盖 dirty/untracked 模块和近期 task runtime/task center 主线。
- 不审范围: 不读取 `.env` 内容，不读取真实 `data/` 商品数据，不启动后端服务，不执行迁移、导出、上传、真实任务、外部平台调用或会修改业务状态的操作。
- 背景 / 触发原因: 用户要求重做全量审计；此前已有 task center 多轮 `NEEDS_FIX` 和第一版全仓审查。
- 事实来源:
  - `AGENTS.md`
  - `docs/collaboration.md`
  - `docs/collaboration/roles/jinghua.md`
  - `docs/collaboration/inbox.md`
  - `docs/collaboration/reviews/*`
  - `docs/superpowers/specs/*task*`
  - `git status --short`
  - `git diff --stat`
  - 静态源码检索和关键文件行号
  - 只读构建/检查命令
- 系统地图:
  - 入口 / 页面 / API: FastAPI `backend/app/main.py` 挂载 products/config/data_sources/giga/tiktok/task_runs/amazon_stylesnap/offline_tasks；前端页面集中在 `frontend/src/pages/*`。
  - 核心模块 / 服务 / action: `backend/app/api/products.py`、`backend/app/api/task_runs.py`、`backend/app/task_runtime/*`、`backend/app/task_planners/*`、`backend/app/product_tasks/actions.py`、`backend/app/services/offline_tasks.py`、GIGA/StyleSnap/A+/Amazon export pipeline。
  - 数据表 / 文件 / 外部依赖: SQLAlchemy/MySQL models、Amazon 模板映射 JSON/XLSM、GIGA OpenAPI、SellerSprite、Chrome 登录态、Lingxing、LLM/VLM/Image API、OSS。
  - 测试 / 文档: `scripts/test_project_rules.py`、`Makefile`、协作文档、API/部署/配置文档。
- 审计项:
  1. 代码结构与模块边界 - done
  2. 数据模型与查询 - done
  3. 状态机与操作矩阵 - done
  4. 事务、幂等、并发与恢复 - done
  5. 错误处理与可观测性 - done
  6. API 合同与界面消费 - done
  7. 文档与知识沉淀 - done
  8. 测试质量与防回归 - done
- 只读边界: 未改业务代码、未读 `.env`、未读真实 `data/`、未启动服务、未触发任务、未调用外部平台。
- 子 agent 分工: 未使用子 agent。
- 输出物: 本报告；inbox 顶部短消息。
- 阶段检查点: 系统地图完成；关键证据行号完成；只读检查完成；报告完成。

## System Map

- Backend: FastAPI + SQLAlchemy async + MySQL。`main.py` 在 lifespan 中注册 worker/action、初始化 DB、恢复任务、唤醒 runtime。
- Frontend: Vite/React/Ant Design。核心 API client 在 `frontend/src/api/index.ts`，TaskRunCenter 在 `frontend/src/pages/TaskRunCenter.tsx`。
- Task systems:
  - 新 runtime: `task_runs/task_groups/task_steps/task_step_events`，入口 `/api/task-runs/*`，planner 在 `backend/app/task_planners/*`，runner 在 `backend/app/task_runtime/scheduler.py`。
  - 旧 offline task: `backend/app/services/offline_tasks.py` 和 `/api/offline-tasks/*` 仍在。
  - 商品 pipeline: `backend/app/pipeline/engine.py` 仍有独立 in-process task。
- Export/template flow: `backend/app/api/products.py`、`step10_amazon_template.py`、`backend/app/pipeline/template_mappings/*.json`、XLSM 模板。
- High-size hotspots:
  - `backend/app/api/products.py`: 5807 lines
  - `backend/app/services/offline_tasks.py`: 1887 lines
  - `backend/app/services/giga_openapi.py`: 1212 lines
  - `backend/app/pipeline/step10_amazon_template.py`: 2325 lines
  - `frontend/src/api/index.ts`: 1658 lines
  - `scripts/test_project_rules.py`: 1578 lines

## Verification

Passed:

- `make check`
  - template mapping validation: OK
  - `scripts/test_project_rules.py`: 31 tests passed
  - backend compileall: passed
- `cd frontend && npm run build`
  - passed
  - Vite warning: main JS chunk is 1,692.09 kB, gzip 520.27 kB
- `git diff --check`
  - passed, no whitespace error output

Not run by design:

- Backend server startup, because `lifespan` would run DB DDL/backfills/recovery and kick task runtime.
- API write probes, task creation, export, upload, external platform calls.
- DB samples against real data.

## Findings

### P0-1 Unauthenticated 0.0.0.0 Service Exposes Mutating Local Control APIs

Evidence:

- `scripts/start.sh:45` starts backend with `uvicorn app.main:app --host 0.0.0.0`.
- `scripts/start.sh:51` starts Vite with `--host 0.0.0.0`.
- `README.md:15-16` documents the same public bind pattern.
- `backend/app/main.py:75-91` adds CORS and mounts all routers, but there is no authentication dependency, auth middleware, API token check, or local-only request guard.
- Mutating examples:
  - `backend/app/api/config_api.py:280-289` patches config and writes backend `.env`.
  - `backend/app/api/task_runs.py:647-848` exposes task creation, retry, wake, cancel and mark-interrupted endpoints.
  - `backend/app/api/products.py:3214-5794` exposes import, export, file open/extract, delete, start/restart/retry/resume/pause and A+ regenerate endpoints.
  - `backend/app/api/data_sources.py:150-261` exposes create/update/delete for product data sources and credentials.

Impact:

If the service is reachable from LAN, VPN, shared Wi-Fi, browser-exposed network, or an unintended host binding, an unauthenticated caller can alter config, trigger local file operations, mutate products/tasks, create exports, and manage external data source credentials. This is a remote-control surface over local workflow state.

Required fix:

- Default bind should be loopback only.
- Add an explicit auth boundary for every API, including dev mode, or enforce local-only request checks with a clear opt-in for remote access.
- Remove unauthenticated `.env` mutation and task/file/export mutators from any remotely reachable surface.
- Add a regression test that fails if mutating routers are mounted without the required auth/local dependency.

### P0-2 Startup Performs DDL, Backfills, Recovery and Runtime Kicks

Evidence:

- `backend/app/main.py:41-59` lifespan registers workers, calls `init_db()`, runs `backfill_product_action_task_run_keys`, `recover_task_runtime`, `kick_task_runtime`, `recover_offline_tasks`, `recover_interrupted_pipelines`, and `recover_regenerate_tasks`.
- `backend/app/database.py:24-40` calls `Base.metadata.create_all` and multiple `_ensure_mysql_*` functions on normal app startup.
- `backend/app/database.py:105-114` updates `product_data_sources`.
- `backend/app/database.py:147-165` updates `products` from JSON snapshot.
- `backend/app/database.py:196-217` updates `giga_skus` and adds FK/index.
- `backend/app/database.py:234-245` can drop and recreate unique indexes.

Impact:

Starting the API for a read-only health check, QA smoke test, OpenAPI inspection, or local frontend verification can mutate schema, mutate business rows, rewrite indexes and wake task execution. This violates build/run/admin separation and makes safe review/QA hard.

Required fix:

- Move schema migration/backfill/index changes into explicit migration/admin commands.
- Make app startup side effects minimal and idempotent: register in-memory worker definitions only, no business backfills, no automatic task wake unless explicitly configured.
- Add a safe startup mode for API/read-only verification.
- Document and test startup side effects.

### P0-3 TLS Verification Is Disabled on Token-Bearing External Requests

Evidence:

- `backend/app/config.py:132-138` creates the LLM OpenAI client with `httpx.AsyncClient(verify=False)`.
- `backend/app/services/aplus_upload.py:208` uses `httpx.AsyncClient(timeout=120, verify=False)`.
- `backend/app/pipeline/step9_aplus_image.py:374` and `:434` use `verify=not settings.GPT_IMAGE_USE_LLM_API`; when LLM API mode is enabled, TLS verification is disabled for image calls.
- Docs normalize this behavior: `docs/03-配置说明.md:131`, `docs/03-配置说明.md:368`, `docs/04-Pipeline步骤详解.md:360`, `docs/05-部署指南.md:363`.

Impact:

Bearer tokens, cookies, auth headers and image/upload payloads can be exposed to a man-in-the-middle endpoint. Because docs describe this as built-in behavior, it is likely to persist and spread.

Required fix:

- Default TLS verification must be on.
- If a private proxy needs custom trust, support CA bundle configuration instead of `verify=False`.
- Any insecure override must be explicit, environment-scoped, logged with warning, and blocked in non-dev settings.

### P0-4 Local Image Proxy Allows Broad Roots and Uses String Prefix Path Check

Evidence:

- `backend/app/main.py:96-101` permits image roots: product base dir, `~/Documents`, and `/tmp`.
- `backend/app/main.py:122-126` resolves the path and checks `abs_path.startswith(root)`.
- `/tmp` currently contains 225M and 2141 files, including Chrome profiles, QA artifacts, zip downloads, logs and JSON snapshots.

Impact:

The proxy exposes broad local filesystem areas to any API caller. A string-prefix check is structurally weaker than `Path.relative_to()` or `is_relative_to()`, and broad roots make mistakes high-impact. Even with extension filtering, screenshots, exported images, generated artifacts and image-like sensitive files can leak.

Required fix:

- Remove `~/Documents` and `/tmp` from default image roots.
- Use structural path validation, not string prefix.
- Serve only known managed asset directories or opaque file IDs.
- Add tests for path traversal, prefix sibling paths and disallowed roots.

### P1-1 Data Source Secrets Are Stored Plaintext and Mutated Without an Access Boundary

Evidence:

- `backend/app/models/models.py:81` stores `ProductDataSource.client_secret` as `Text`.
- `backend/app/api/data_sources.py:105` masks the secret in responses, but `:165-184` and `:233-249` write the raw secret to DB.
- There is no auth boundary on the router.

Impact:

Response masking helps UI display but does not protect storage or unauthorized mutation. Combined with P0-1, an unauthenticated caller can create/replace store credentials.

Required fix:

- Add auth first.
- Encrypt secrets at rest or move them to a secret store.
- Limit API reads/writes by role and audit every change.
- Never expose storage paths or credential metadata more than necessary.

### P1-2 Task Center List and Detail Derive Different Display State Contracts

Evidence:

- Detail display uses loaded steps: `backend/app/api/task_runs.py:196-298`.
- List display uses only run-level status/cancel/superseded fields and drops current step, live progress, latest event and heartbeat: `backend/app/api/task_runs.py:301-375`.
- Display filters for `stale_running`, `waiting_dependency`, and `planned` return `and_(False)`: `backend/app/api/task_runs.py:431-448`.

Impact:

The list, detail, filters, buttons and progress can disagree. Some visible display states can never be filtered. This is exactly the task center class of issues that has repeatedly caused review failures.

Required fix:

- Persist a single run-level projection for display status, action matrix, current step, progress and heartbeat.
- Make list/detail/filter consume the same projection.
- Remove impossible `and_(False)` filters or mark those states not filterable in the API contract.
- Add behavior tests that create actual task rows and verify list/detail/filter parity.

### P1-3 TaskRun Dedupe and Idempotency Are Indexed but Not Enforced

Evidence:

- `TaskRun` fields exist at `backend/app/models/models.py:142-180`, including `dedupe_key` and `idempotency_key`, but there is no `UniqueConstraint` for them.
- DB startup adds indexes only: `backend/app/database.py:177-180`.
- Product actions do a product lock and active scan in `backend/app/product_tasks/actions.py`, but non-product planners do not have equivalent DB enforcement:
  - `backend/app/task_planners/giga_pull.py:29-113` always creates new runs per source.
  - `backend/app/task_planners/giga_dynamic_sync.py:29-118` always creates new runs per source.
  - `backend/app/task_planners/catalog_export.py:15-44` scans active steps to prevent duplicates.
  - `backend/app/task_planners/aplus_generate.py:30-42` scans active steps to prevent duplicates.

Impact:

Concurrent clicks or retrying API calls can create duplicate runs before scan results see each other. Indexes improve lookup but do not enforce idempotency. For export/A+/GIGA sync, duplicate external work can create duplicate files, API calls, task events and inconsistent UI state.

Required fix:

- Define per-task dedupe/idempotency semantics.
- Add DB-level unique constraints or claim tables for active dedupe windows.
- Use transactional insert or upsert behavior.
- Add concurrent creation tests.

### P1-4 Runtime Still Depends on In-Process Async Tasks Across Multiple Frameworks

Evidence:

- New scheduler has module globals `_runner_task`, `_runner_handle`, `_runner_lock`: `backend/app/task_runtime/scheduler.py:39-43`.
- `kick_task_runtime()` uses `loop.call_later` and `asyncio.create_task`: `backend/app/task_runtime/scheduler.py:348-367`.
- Legacy/background systems also create process-local tasks:
  - `backend/app/services/inventory_sync.py:34`
  - `backend/app/services/aplus_upload.py:42`
  - `backend/app/services/asin_sync.py:39`
  - `backend/app/services/giga_image_download_tasks.py:155`
  - `backend/app/services/giga_sync_tasks.py:148`
  - `backend/app/services/offline_tasks.py:1262`
  - `backend/app/pipeline/engine.py:337`

Impact:

State can split across process memory, DB rows and legacy task registries. Restarts, multi-process serving, failed startup, worker crashes and concurrent API processes can leave work orphaned or duplicated.

Required fix:

- Pick one durable task execution model.
- Reduce process-local state to short-lived worker claim state.
- Make recovery/retry/cancel semantics DB-backed and shared across task types.
- Retire or strictly isolate old offline task creation paths.

### P1-5 Domain Code Imports Router Helpers, Collapsing API and Business Boundaries

Evidence:

- `backend/app/task_planners/catalog_export.py:69` imports `_catalog_category` and `_template_status_for_catalog` from `app.api.products`.
- `backend/app/services/offline_tasks.py:1088` and `:1545` import build/template helpers from `app.api.products`.
- `backend/app/task_runtime/catalog_export_workers.py:51` imports `CatalogExportBuildError` and `build_catalog_export_zip` from `app.api.products`.
- `backend/app/api/products.py` is a 5807-line router with route handlers, export builders, template logic, file operations, status transitions and helpers.

Impact:

The API router has become a business domain module. Workers/planners now depend on route-layer internals, which makes testing harder and encourages future changes to add more hidden behavior to the router.

Required fix:

- Move catalog/export/template domain logic into service/domain modules.
- Keep routers responsible for protocol, validation and response shaping.
- Make workers/planners import services, not API modules.

### P1-6 Tests Are Mostly String Guards and Do Not Prove Behavior

Evidence:

- `scripts/test_project_rules.py` is the primary test file discovered.
- It heavily reads source text and asserts string presence, for example `scripts/test_project_rules.py:88-113`, `:331-344`, `:950-966`.
- Some executable subprocess tests exist near `:1278`, `:1341`, `:1428`, `:1485`, `:1527`, but coverage remains narrow.
- No regular pytest suite or frontend behavior test suite was found in this audit.

Impact:

String checks can pass while behavior, transaction semantics, SQL shape, auth boundary and UI/API contracts are broken. This explains why `make check` can pass while P0/P1 risks remain.

Required fix:

- Keep project-rule string guards only for policy smoke checks.
- Add backend behavior tests around auth, startup side effects disabled mode, task projection parity, dedupe concurrency, and export/A+ invariants.
- Add frontend/API contract tests for task center list/detail/filter/action matrix.

### P2-1 Repository Hygiene Is Unsafe for Runtime Artifacts

Evidence:

- `.gitignore:1-35` ignores Python/Node/env/log/data, but not root `tmp/`, `backend/tmp/`, `frontend/dist/`, `logs/*.pid`, Chrome profiles or QA artifacts explicitly.
- `git status --short` shows tracked runtime/build artifacts such as `frontend/tsconfig.tsbuildinfo`, `logs/*.pid`, and `backend/tmp/image-size-tests/*.png`.
- Root `tmp/` is untracked and large: 225M, 2141 files.

Impact:

Runtime state, local browser profiles, cookies/local storage, downloaded zips and generated artifacts can accidentally enter review scope or be committed. This is also a context-budget and privacy risk.

Required fix:

- Ignore `tmp/`, `backend/tmp/`, PID files, local build info and generated QA/browser profiles.
- Decide which generated artifacts are intentionally tracked and document why.
- Clean or quarantine existing untracked runtime artifacts after user approval.

### P2-2 Frontend Bundle and API Client Are Monolithic

Evidence:

- `frontend/src/api/index.ts` is 1658 lines.
- `frontend/src/pages/TaskRunCenter.tsx` is 704 lines.
- Build output warns that the main JS chunk is 1,692.09 kB after minification.

Impact:

This is not the first blocker, but it increases page load cost and makes API contract changes harder to review.

Required fix:

- Split API client by domain.
- Lazy-load heavy pages/routes.
- Keep TaskRunCenter state derivation in backend projection and small frontend render helpers.

## Repair Order

1. P0 security/run boundary: loopback by default, auth/local guard, remove unauthenticated config/task/file/export mutation, restore TLS verification, narrow file proxy roots.
2. P0 startup safety: move DDL/backfills/recovery/kick into explicit migration/admin/worker commands; create safe API startup mode.
3. P1 task model: persist task display projection, enforce list/detail/filter parity, add DB-backed dedupe/idempotency.
4. P1 runtime convergence: choose a durable worker model and retire or isolate legacy process-local task systems.
5. P1 structure: extract catalog/export/template services out of `api/products.py`.
6. P1/P2 tests and repo hygiene: add behavior tests and clean generated/runtime artifact policy.

## Uncovered Areas

- I did not inspect real product data in `data/`.
- I did not inspect `.env` values.
- I did not start the backend or call live API endpoints because startup has known mutating side effects.
- I did not verify external platform behavior or real browser-login flows.
- I did not do a full line-by-line audit of every skill script under `skills/` and `codex-skills/`; those should be a separate tool/security audit if they are treated as executable product surface.

## Next Actions

- 若命: triage whether the service is intended to ever bind beyond localhost; decide the auth/local-only policy before implementation.
- 听云: fix P0 items first, then task projection/idempotency/runtime convergence in separate changes.
- 观止: after P0/P1 fixes, rerun QA using safe startup mode plus behavior tests; do not rely only on `make check`.
- 镜花: re-review after P0/P1 `DONE_CLAIMED`, with special attention to whether fixes add more router-level complexity.
