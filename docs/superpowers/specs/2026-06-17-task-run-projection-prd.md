# Task Run Projection PRD

日期：2026-06-17
Owner：若命（agentKey: `ruoming`）
执行角色：听云（agentKey: `tingyun`）
验证角色：镜花 / 观止

## 背景

任务中心重构主体已落地，但观止和镜花都确认仍有 P1：

- 详情 `_run_display()` 能根据 step lock/heartbeat 派生 `stale_running`。
- 列表 `_run_list_display()` 只看 `TaskRun.status`，会把同一任务显示成普通 `running`。
- `_display_status_sql_condition("stale_running")` 当前返回 `and_(False)`。
- 前端仍暴露“疑似卡住”筛选，用户永远筛不出真实 stale running。

这说明列表、详情、筛选、按钮不再同源。

## 目标

让任务中心列表、详情、筛选、按钮消费同一组 run-level projection，或者明确收缩当前无法可信支持的筛选/操作。

## 2026-06-17 用户确认后的执行决策

本轮先走**收缩路线**，不继续扩大实现 run-level projection。

原因：

- 任务中心当前首要问题是用户看到不可信筛选和不一致按钮；先下线不可信入口，恢复页面可信度。
- run-level projection 会影响表结构、状态刷新点、backfill、任务生命周期和旧数据语义，需要单独 PRD 和 code review，不应在当前返工里边写边扩。
- 任务中心和商品流程需要先明确边界：任务中心是异步执行事实中心，商品流程是业务状态和操作中心。不能为了商品流程按钮，把商品语义继续塞进任务中心状态。

因此本任务的执行路线固定为：

1. 从 API 和前端移除/禁用 `stale_running / waiting_dependency / planned` 的列表筛选和列表操作。
2. 详情页可以保留这些派生诊断状态，但它们不能出现在列表筛选和 total 统计口径中。
3. 高频列表接口继续保持 `task_runs` 单表 DB 级真实分页、真实 total。
4. 如果当前已有投影路线实现，不视为自动接受；必须由若命/镜花单独 review 后决定保留、回退，或拆成后续 projection PRD。

后续 projection 路线另开任务时，才允许设计：

1. **投影路线**：在 `task_runs` 上增加可索引 projection 字段，并在 step 状态变化、事件写入、取消/重试/恢复时更新。

不得继续用复杂查询、`EXISTS/IN`、JOIN、重复 count、运行时二次过滤或内存分页来弥补投影缺失。

## 产品边界：任务中心 vs 商品流程

任务中心负责异步任务执行事实：

- 任务类型、标题、来源、关联对象。
- 运行状态、进度、失败原因、最后事件、最后心跳、当前 step。
- 任务级操作：取消、重试、唤醒、标记中断、查看详情。
- 任务影响物：关联商品、批次、导出文件、报告入口。

商品流程负责业务状态和用户决策：

- 商品业务阶段：待选图、待选竞品、待生成 Listing、待导出、已导出、失败等。
- 商品下一步动作：选图、确认竞品、生成文案、导出、重新分析。
- 业务数据完整性：主图、竞品、标题、类目、价格、库存、导出结果。
- 商品页可以展示最近任务摘要并跳转任务中心，但不能把任务状态当成商品状态。

连接关系：

```text
商品页面 action
-> 创建 task_run
-> task runtime 执行 steps
-> task 成功/失败写任务事实
-> 商品域 action handler 更新商品业务投影
-> 商品页面读取商品业务状态
-> 任务中心读取任务执行状态
```

禁止：

- 用任务中心状态反推商品状态。
- 让商品列表为了显示任务状态去 join task_steps 或内存聚合。
- 让前端根据 task title、step label、summary 字符串判断业务状态。
- 把商品动作直接写成裸后台任务，绕过 task runtime。
- 让任务成功自动推进所有商品状态；必须由商品域 action 明确声明成功后的业务投影。

## 非目标

- 不迁移全部旧 offline tasks。
- 不实现完整分布式 worker。
- 不修复所有 dedupe/idempotency DB 约束。
- 不重构全部 `TaskRunCenter.tsx` 或 `api/task_runs.py`。
- 不触发真实任务、真实 GIGA 拉品、导出、A+、商品状态推进或外部平台。

## 当前事实

- API：`backend/app/api/task_runs.py`
- runtime：`backend/app/task_runtime/`
- models：`backend/app/models/models.py`
- frontend：`frontend/src/pages/TaskRunCenter.tsx`
- tests/rules：`scripts/test_project_rules.py`
- PRD：`docs/superpowers/specs/2026-06-16-task-center-state-action-prd.md`
- QA：`MSG-20260617-003`
- audit：`MSG-20260617-JH-004`

## 方案要求

听云开工前必须写 `TASK_DEFINITION` 和短设计说明，确认执行收缩路线。

### 本轮不做投影路线

以下内容本轮不实现，只作为后续 projection PRD 的候选问题：

- `task_runs` 新增哪些字段，例如：
  - `display_status`
  - `display_reason`
  - `available_actions_json`
  - `current_step_id`
  - `current_step_type`
  - `current_step_label`
  - `progress_current`
  - `progress_total`
  - `last_heartbeat_at`
  - `last_event_at`
  - `error_summary`
- 字段哪些需要 DB index。
- 字段在何处更新：
  - run 创建
  - step claim/running
  - step success/failure/interrupted
  - cancel requested
  - retry
  - recover/kick
  - stale 判断刷新
- 旧数据如何 backfill，backfill 是否默认执行，是否触碰真实业务状态。
- 列表、详情、filter、actions 如何共用 projection。
- API 响应如何保持兼容。

### 收缩路线要求

必须说明：

- API 不再接受哪些 `display_status` 过滤值。
- 前端筛选项删除哪些值。
- 列表中是否还显示 `stale_running / waiting_dependency / planned`，如果显示，来自何处。
- 详情页如何保留诊断能力。
- 用户如何发现卡住任务：本轮如果没有可信列表能力，必须明确这是后续投影任务。

## 强约束

- 列表页必须继续 DB 级真实分页、真实 total。
- 高频列表接口优先 `task_runs` 单表 `where + order + limit`。
- 不允许 `and_(False)` 搭配前端可见筛选项。
- 不允许列表显示普通 `running`，详情显示 `stale_running`，并给出不同操作矩阵。
- 不允许前端重新推导业务状态。

## 验收标准

- 列表、详情、筛选、按钮同源，或不可同源的筛选被明确下线。
- 前端不能展示“疑似卡住”等不可信列表筛选。
- API 对 `display_status=stale_running / waiting_dependency / planned` 不应返回误导性空结果；应删除支持或返回明确不可筛选错误。
- 构造样本 `RUN_STATUS_RUNNING + running step locked_until 过期`：
  - 详情可以显示 `stale_running` 诊断。
  - 列表/API 不提供误导性筛选和列表操作。
- `make backend-compile`
- `make test-project-rules`
- `git diff --check`
- 如改前端，跑 `cd frontend && npm run build`

## DONE_CLAIMED 必填

- 选择路线：收缩。
- 改动文件。
- 列表/详情/filter/action 同源说明。
- SQL 形态说明：关键列表接口不是复杂查询、不是运行时过滤、不是内存分页。
- 行为测试或项目规则证据。
- 页面/API 样本或代码级样本。
- 未覆盖项和后续风险。
- 索引更新情况。
