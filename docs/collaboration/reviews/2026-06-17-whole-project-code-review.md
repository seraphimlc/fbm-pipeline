# CODE_REVIEW / NEEDS_FIX - 镜花（agentKey: `jinghua`）- 2026-06-17 CST

结论：NEEDS_FIX。项目规则检查、后端编译和前端构建通过，但全仓静态审查发现启动期自动 DDL/回填、安全边界、任务中心状态口径和仓库产物管理仍有 P0/P1 风险，不能作为代码 gate 通过。

## 范围

- 审查请求：用户要求“审查这个项目里的所有代码、文件，并生成审查报告”。
- 覆盖方式：全仓文件清单、当前 git 变更面、后端/前端/脚本/技能目录的静态风险扫描，重点抽读后端 API、数据库初始化、任务运行中心、任务调度、外部调用、文件访问和仓库产物。
- 重点文件/模块：
  - `backend/app/database.py`
  - `backend/app/main.py`
  - `backend/app/config.py`
  - `backend/app/api/task_runs.py`
  - `backend/app/api/products.py`
  - `backend/app/services/aplus_upload.py`
  - `backend/app/task_runtime/scheduler.py`
  - `backend/app/product_tasks/actions.py`
  - `frontend/src/pages/TaskRunCenter.tsx`
  - `frontend/src/api/index.ts`
  - `scripts/test_project_rules.py`
  - `docs/collaboration/*`
  - `skills/`、`codex-skills/` 仅做安全/脚本模式扫描，未做每个 skill 的业务正确性验收。
- 未审范围：
  - 未连接真实 MySQL/外部 API 做写路径验证。
  - 未执行浏览器端人工路径 QA。
  - 未审查 `data/`、`backend/.env`、`frontend/.env` 的敏感内容，按项目保护规则只确认它们处于 ignored 状态。

## 验证

- `git status --short`：当前工作区包含大量改动和未跟踪文件，本次 review 未修改业务代码。
- `rg --files -g '!tmp/**' -g '!frontend/node_modules/**' -g '!backend/.venv/**' -g '!**/__pycache__/**'`：建立审查文件清单。
- `git diff --stat`：已跟踪改动 43 个文件，约 4336 insertions / 6007 deletions；另有大量新后端任务运行模块、协作文档和前端页面未跟踪。
- `make check`：通过。
  - `scripts/validate_template_mappings.py`：OK，5 个 mapping 文件，0 warning。
  - `scripts/test_project_rules.py`：OK，31 项项目规则测试通过。
  - `python3 -m compileall -q app`：通过。
- `cd frontend && npm run build`：通过；Vite 报 chunk size warning，主 JS chunk 约 1.69 MB。
- `git ls-files backend/.env frontend/.env .env '**/.env'`：无输出，未发现 `.env` 被跟踪。

## Findings

1. [P0] 应用启动会自动执行 DDL、索引重建和真实数据回填
   - 位置：`backend/app/database.py:24`
   - 事实：`init_db()` 在 FastAPI lifespan 启动路径执行 `Base.metadata.create_all`，随后调用多组 `_ensure_mysql_*`；其中包括 `ALTER TABLE` 加列/改 LONGTEXT、`UPDATE products ... JOIN product_data` 回填来源字段、`UPDATE giga_skus ... JOIN giga_items` 回填关系、以及在索引列不匹配时 `DROP INDEX` 后重新 `ADD UNIQUE INDEX`。
   - 影响：服务启动变成隐式迁移工具。真实库启动时可能长时间锁表、因重复数据导致唯一索引创建失败、半途失败导致服务不可用，且没有 dry-run、批量上限、备份点、回滚脚本或人工确认。它还把生产数据修改隐藏在普通启动行为里，违反项目“真实数据默认只读和小范围修改”的边界。
   - 期望：启动只做连接和 schema 版本校验；DDL/backfill/唯一索引重建必须迁到显式 migration/backfill 命令，带版本号、幂等检查、数据规模说明、失败恢复和回滚策略。
   - 修复要求：移除 `init_db()` 中的自动变更真实数据路径；补独立迁移脚本/文档和最小只读预检；上线前提供 MySQL 样本库验证结果。

2. [P0] 多个带密钥的外部 HTTP 客户端关闭 TLS 证书校验
   - 位置：`backend/app/config.py:132`、`backend/app/services/aplus_upload.py:208`、`backend/app/pipeline/step9_aplus_image.py:374`、`backend/app/pipeline/step9_aplus_image.py:434`
   - 事实：`get_llm_client()` 使用 `httpx.AsyncClient(verify=False)`；A+ 上传使用 `httpx.AsyncClient(timeout=120, verify=False)`；Step9 在 `GPT_IMAGE_USE_LLM_API=True` 时使用 `verify=False`，请求头包含 `Authorization: Bearer ...`。
   - 影响：LLM、图片生成、A+ 上传等请求携带 API key 或业务授权信息，关闭 TLS 校验会让中间人攻击、代理污染和凭据泄漏成为现实风险。这个问题属于安全基线，不应依赖“当前只在内网/本地跑”的假设。
   - 期望：默认启用证书校验；如确有私有代理证书问题，使用可配置 CA bundle 或显式 dev-only 开关，并在日志/配置页标识不安全模式。
   - 修复要求：删除默认 `verify=False`；新增 `*_TLS_VERIFY` 或 `*_CA_BUNDLE` 配置时必须默认安全，并禁止在生产配置中关闭。

3. [P0] 本地图片代理的路径白名单用字符串前缀判断，且白名单范围过宽
   - 位置：`backend/app/main.py:96`
   - 事实：`_IMAGE_ROOTS` 包含整个用户 `~/Documents` 和 `/tmp`；`serve_image()` 用 `abs_path.startswith(str(Path(r).resolve()))` 判断是否在白名单内。
   - 影响：字符串前缀不是路径包含判断，类似 `/tmpfoo/...` 或同名前缀目录可能误通过。即使修复前缀 bug，整个 `Documents` 和 `/tmp` 作为图片代理根目录也过宽；接口一旦暴露到非本机，就可能变成本机文件探测/图片泄露入口。
   - 期望：只允许 `PRODUCT_BASE_DIR` 和明确业务素材目录；路径判断使用 `Path.resolve()` 后的 `relative_to()` 或 `path.is_relative_to(root)`。
   - 修复要求：收窄 `_IMAGE_ROOTS`；用结构化路径归属判断；错误响应不要回显完整本机路径。

4. [P1] 任务中心列表和详情的状态口径继续分裂，部分过滤永远返回空
   - 位置：`backend/app/api/task_runs.py:196`、`backend/app/api/task_runs.py:301`、`backend/app/api/task_runs.py:431`
   - 事实：详情 `_run_display()` 仍从 `TaskStep` 推导 `stale_running`、`waiting_dependency`、`planned`、进度、最新事件和当前步骤；列表 `_run_list_display()` 只看 `TaskRun.status/cancel/superseded`，不会展示 `stale_running`、真实进度、当前步骤或最新事件；`_display_status_sql_condition()` 对 `stale_running`、`waiting_dependency`、`planned` 直接返回 `and_(False)`。
   - 影响：同一个任务在列表和详情可能显示不同状态；用户筛选 `stale_running`/`waiting_dependency`/`planned` 会得到空结果，即使详情能推导出这些状态。任务中心刚修掉复杂查询，但没有把状态投影落到 `task_runs`，只是把列表语义降级了。
   - 期望：写入侧维护可索引的 `display_status`、`current_step_label`、`progress_*`、`last_heartbeat_at`、`latest_event_message/error_summary` 等投影字段，列表和详情共同消费同一口径。
   - 修复要求：补最小 schema/model 投影字段和写入更新点；列表筛选不能返回硬编码空条件；补行为测试证明列表/详情/过滤一致。

5. [P1] 任务运行器仍绑定单个 API 进程内存态，长任务恢复和调度边界不够稳
   - 位置：`backend/app/task_runtime/scheduler.py:39`、`backend/app/task_runtime/scheduler.py:338`
   - 事实：运行器以模块级 `_runner_task/_runner_handle/_runner_lock` 管理，`kick_task_runtime()` 用当前事件循环 `call_later` 和 `asyncio.create_task` 启动；没有独立 worker 进程、分布式锁持有者登记或多实例调度策略。
   - 影响：状态表已持久化，但实际执行调度仍依赖单个 API 进程存活和事件循环。多进程部署、reload、worker 崩溃、服务滚动重启时，调度行为和恢复责任不清；这类长耗时任务不能只靠进程内任务句柄兜住。
   - 期望：明确 runtime 是 dev/local-only，或拆成持久 worker/队列；至少要有周期性 claim/recover、worker identity、并发上限和多实例行为说明。
   - 修复要求：补运行架构决策和约束；生产路径需要独立 worker 或可靠调度循环；增加重启/多实例/锁过期行为测试。

6. [P1] 工作区 `tmp/` 未被整体忽略，包含浏览器 profile、Cookie/Local Storage 等敏感运行产物
   - 位置：`.gitignore:1`、工作区 `tmp/`
   - 事实：`.gitignore` 忽略了 `data/`、`.env`、`dist/`、`*.log`，但没有忽略仓库根 `tmp/`。`git status --ignored --short tmp ...` 显示 `?? tmp/`，其中有 `tmp/chrome-cdp-profile-*/Default/Cookies`、Local Storage、Session Storage、Cache 等大量文件；`du -sh tmp` 约 224 MB。
   - 影响：这些文件目前未跟踪，但很容易被误 `git add tmp/`，导致浏览器会话、站点缓存或私有调试数据进入提交。对于协作仓库，这是隐私和供应链 hygiene 风险。
   - 期望：根目录 `tmp/`、CDP profile、运行 pid/cache 目录默认 ignore；需要保存的调试证据应放脱敏小文件并显式命名。
   - 修复要求：补 `.gitignore`；清理或移动当前 `tmp/` 运行产物；后续报告只引用路径和摘要，不保留浏览器 profile。

7. [P2] `backend/app/api/products.py` 已膨胀为 5807 行 router，大量业务规则、文件副作用和状态迁移混在 API 层
   - 位置：`backend/app/api/products.py:1`
   - 事实：该文件同时承载商品列表/详情、导入导出、文件打开/解压、主图选择、竞品搜索触发、UPC、ASIN、A+、库存、catalog 等多类流程；例如 `open_product_file()` 直接触发本机 `subprocess.Popen(["open", ...])`。
   - 影响：API handler 变成 god module，业务状态、文件系统副作用和展示字段难以局部验证；后续任何需求都倾向继续往 router 里塞，增加回归风险。
   - 期望：按 domain/service/action/repository 拆分；API 只做协议、参数校验和 service 调用。
   - 修复要求：不要求本轮大重构，但新增功能不得继续塞进该文件；为高风险路径先抽 service，并补行为测试。

8. [P2] 构建/运行产物仍被跟踪或留在工作区，仓库边界不干净
   - 位置：`frontend/tsconfig.tsbuildinfo`、`logs/backend-8190.pid`、`logs/frontend-3190.pid`、`backend/tmp/image-size-tests/*.png`
   - 事实：`git ls-files` 显示上述文件被跟踪；其中 `backend/tmp/image-size-tests` 下有 1.6 MB 到 4.5 MB 的 PNG 测试产物。
   - 影响：构建缓存、pid 和临时图片会制造无关 diff、污染 review、增加仓库体积，并使“真实产物不能无声覆盖”的边界更难维护。
   - 期望：运行缓存和临时产物不进入版本控制；确需保留的测试 fixture 应移到明确的 `tests/fixtures/` 并控制体积。
   - 修复要求：清理已跟踪产物或补充说明其必要性；更新 `.gitignore` 防止复发。

## 已确认通过

- 模板映射校验通过：5 个 mapping 文件，0 warning。
- 项目规则脚本通过：31 项。
- 后端 `compileall` 通过。
- 前端 `npm run build` 通过，只有 Vite 大 chunk warning。
- 未发现 `.env` 被 git 跟踪。
- `backend/app/api/task_runs.py` 当前列表接口没有 `selectinload(TaskRun.steps/groups/events)`，历史页重载大字段的问题已有收敛迹象。

## 未覆盖 / 风险

- 没有真实 MySQL EXPLAIN、慢接口压测或大数据量分页验证；任务中心 SQL 形态仍需要观止按页面路径复验。
- 没有外部平台 sandbox 验证，不确认 A+ 上传、OSS 下载、GIGA API、StyleSnap 搜索的真实失败恢复。
- 没有人工 UI/业务口径验收；清秋/霜弦仍需分别看体验和运营/导出口径。
- 当前工作区混入多会话大量未提交改动，本报告不能可靠判断每个改动归属。
