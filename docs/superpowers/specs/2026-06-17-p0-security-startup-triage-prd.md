# P0 Security / Startup Boundary Triage PRD

日期：2026-06-17
Owner：若命（agentKey: `ruoming`）
执行角色：听云（agentKey: `tingyun`）
验证角色：镜花（code review）/ 观止（QA）

## 背景

镜花两轮全量只读审计均为 `NEEDS_FIX`，观止 Round 5 任务中心 QA 也为 `NEEDS_FIX`。

当前不能继续把任务中心当成唯一主线推进。必须先收敛全仓 P0 安全/启动边界，再进入 task runtime/task center 的状态投影修复。

相关输入：

- `docs/collaboration/reviews/2026-06-17-whole-project-code-audit-rerun.md`
- `docs/collaboration/reviews/2026-06-17-whole-project-code-review.md`
- `docs/collaboration/reviews/2026-06-17-task-center-code-review-round5.md`
- `MSG-20260617-JH-002`
- `MSG-20260617-JH-001`
- `MSG-20260617-003`

## 本轮目标

### 目标 A：先封 P0 安全/启动边界

本轮优先处理镜花全量审计中的 P0：

1. 服务默认绑定 `0.0.0.0` 且无鉴权/本机访问边界。
2. API 启动自动执行 DDL、backfill、恢复、kick runtime。
3. 外部 token 请求默认关闭 TLS 校验。
4. 本地图片代理根目录过宽，并使用字符串前缀做路径判断。

目标不是一次性建立完整权限系统，而是把“默认不安全”和“启动即改库/触发任务”的风险先关掉。

### 目标 B：给 task center 状态投影做设计，不混在 P0 修复里偷改

观止 Round 5 发现：

- 列表路径把 `stale_running` 降级成 `running`。
- 详情路径能判定 `stale_running`，但列表筛选无法可信发现。
- 列表/详情状态不同源。

该问题需要最小投影字段或明确删除不可支持筛选/操作。它属于 task runtime/task center 第二阶段，不要混进 P0 安全启动修复里边写边猜。

## 非目标

- 不做完整登录/用户权限系统。
- 不重构全部 `api/products.py`。
- 不迁移全部旧 offline task。
- 不修复全部 P1/P2。
- 不触发真实 GIGA 拉品、导出、A+、上传、外部平台调用或商品状态推进。
- 不触碰 `data/`、`backend/data/`、真实 ASIN、人工类目、Amazon 模板、`template_mappings`、已生成素材、真实导出文件。

## 产品/工程口径

### 本地服务访问边界

V1 口径：

- 默认只监听 `127.0.0.1`。
- 如果用户明确配置远程监听，必须有显式 opt-in 配置，并在启动日志中提示风险。
- mutating API 必须有本机访问边界或 dev token 边界；不能在默认配置下被局域网匿名调用。
- `.env` 写入、任务创建/重试/取消/唤醒、文件打开/解压/导出、数据源密钥写入等 mutating endpoints 都属于保护范围。

### 启动副作用边界

V1 口径：

- 普通 API startup 不应自动执行 DDL/backfill/索引重建/真实数据修复。
- 普通 API startup 不应自动 kick 长任务运行器，除非显式开启 runtime worker 模式。
- schema 初始化、backfill、恢复、runtime kick 应拆成显式 admin/migration/worker 命令或显式配置开关。
- 如果为了开发环境兼容暂时保留某项 startup 行为，必须默认关闭，并在配置、日志、文档、测试里明确。

### TLS 边界

V1 口径：

- 外部 token-bearing 请求默认开启 TLS 校验。
- 私有代理场景使用 CA bundle 配置，不使用默认 `verify=False`。
- 若必须保留 dev-only insecure 开关，必须显式命名、默认关闭，并禁止被普通生产配置误用。

### 文件代理边界

V1 口径：

- 默认只允许业务管理的图片/素材目录。
- 不允许默认开放 `~/Documents` 或 `/tmp`。
- 路径归属必须使用结构化路径判断，例如 `Path.relative_to()` / `Path.is_relative_to()`，不能用字符串前缀。
- 错误响应不要泄漏完整本机路径。

## 执行拆分

### Phase 1：听云先写设计说明，不直接开改

听云先写 `TASK_DEFINITION` 和一个短设计说明，至少回答：

- 哪些 endpoint 算 mutating，准备用什么本机访问/令牌边界保护。
- startup 中哪些行为保留、哪些移到显式命令、哪些用配置开关关闭。
- TLS 配置如何命名，默认值是什么。
- image proxy 允许哪些目录，路径校验怎么做。
- 哪些测试会证明这些边界。

如果发现实现会影响本地启动方式或用户需要确认远程访问口径，先 `REQUEST` 若命/用户，不要硬改。

### Phase 2：实现 P0 安全/启动边界

实现范围限制在：

- `scripts/start.sh`
- `README.md` / 部署或配置文档中对应启动说明
- `backend/app/main.py`
- `backend/app/config.py`
- `backend/app/database.py`
- 涉及 TLS verify 的外部 client 文件
- 必要的本机访问 guard / dev token helper
- `scripts/test_project_rules.py` 或行为测试文件

如必须新增管理命令或迁移入口，先在设计说明中列出路径和命令名。

### Phase 3：只做 task center 投影方案，不实现

听云在 P0 修复 `DONE_CLAIMED` 后，另写 task center 投影方案，供若命/用户确认后再开第二个实现任务。

方案必须明确：

- `task_runs` 需要哪些 run-level projection 字段。
- 这些字段在 step 状态变化、事件写入、cancel/retry/recover 时如何更新。
- 列表、详情、筛选、操作如何同源消费。
- 是否继续支持 `stale_running/waiting_dependency/planned` 筛选；如支持，如何可索引；如不支持，前端/API 如何删除或标记不可筛选。

## 验收标准

### P0 修复验收

- 默认启动命令不监听 `0.0.0.0`。
- mutating endpoints 在默认远程访问场景下不可匿名调用；测试覆盖至少一个 config 写入、一个 task mutation、一个 data source mutation 或等价路径。
- 普通 API startup 不自动执行 DDL/backfill/index rebuild/task kick；相关行为迁到显式命令或显式配置开关。
- 外部 token-bearing 请求默认 TLS verify on。
- image proxy 不默认开放 `~/Documents` 和 `/tmp`，路径归属用结构化判断。
- `make backend-compile`、`make test-project-rules`、`git diff --check` 通过；如改前端再跑 `cd frontend && npm run build`。

### 任务中心方案验收

- 不要求本轮实现。
- 方案清楚说明列表/详情/filter/action 同源字段。
- 不允许再用复杂查询、`EXISTS/IN`、JOIN、重复 count、运行时二次过滤或内存分页来弥补投影缺失。

## DONE_CLAIMED 必填

听云完成 P0 修复后，`DONE_CLAIMED` 必须列：

- 每个 P0 的修复文件和行为对账。
- 默认启动命令和监听地址。
- mutating endpoint guard 覆盖范围。
- startup 副作用从哪里移除，显式命令/开关在哪里。
- TLS verify 默认值。
- image proxy 允许目录和路径校验方式。
- 验证命令和结果。
- 未覆盖项和残余风险。
- 索引更新情况；若未更新 project/domain index，说明理由。

## 交给观止/镜花的复验方式

- 镜花先做代码 review：重点看是否用补丁掩盖边界、是否新增更大的 router 复杂度、是否真的移除了默认不安全行为。
- 观止再做只读/最小副作用 QA：检查启动命令、健康检查、安全 guard、图片代理拒绝样本、TLS 配置默认值；不要触发真实业务任务或外部平台。
