# Task Center Projection Code Review

日期：2026-06-17
Reviewer：若命（agentKey: `ruoming`）
范围：`MSG-20260617-008` / `MSG-20260617-009` 任务中心 projection route 实现
结论：NEEDS_FIX

## 总结

听云当前实现没有按最新产品口径执行。用户和若命已确认本轮先走收缩路线：从列表/API/前端下线无法可信支持的 `stale_running / waiting_dependency / planned` 筛选和列表操作，run-level projection 另开后续 PRD。

当前代码却继续落了 projection 字段、schema ensure、startup backfill、列表筛选、前端筛选和项目规则，等于把待讨论的 projection 方案当作已验收事实。这会让任务中心继续承载未定稿的状态投影，并把错误方向用测试锁住。

## Findings

### P0：实现路线与已确认产品决策相反

- 代码位置：
  - `backend/app/models/models.py`：`TaskRun.display_status/display_reason/current_step_id/available_actions_json/.../projection_updated_at`
  - `backend/app/database.py:125-151`、`backend/app/database.py:181-197`
  - `backend/app/main.py:86-93`
  - `backend/app/task_runtime/display.py:169-339`
  - `backend/app/api/task_runs.py:231-238`、`backend/app/api/task_runs.py:370-417`
- 事实：
  - 代码已把 projection 字段落入 `task_runs` 模型和 MySQL ensure。
  - startup backfill 中加入 `backfill_task_run_display_projections()`。
  - 列表 API 优先读取 `TaskRun.display_status` / `available_actions_json`。
  - `_display_status_sql_condition()` 让 `stale_running / waiting_dependency / planned` 继续按 `TaskRun.display_status` 筛选。
- 问题：
  - 这不是“收缩路线”，而是完整 projection route。
  - projection route 影响表结构、维护窗口、状态刷新点、旧数据、前端按钮和测试规则，已经超出本轮整改边界。
- 要求：
  - 本轮按收缩路线返工。
  - projection 相关 schema/backfill/list-filter/action 存储改动先不要继续扩大；若必须保留某些字段，必须在新 PRD/code review 中单独说明必要性、兼容性和迁移计划。

### P0：前端仍暴露不可信的列表筛选

- 代码位置：
  - `frontend/src/pages/TaskRunCenter.tsx:453-468`
- 事实：
  - 状态筛选下拉仍包含 `{ value: 'stale_running', label: '疑似卡住' }`。
  - `planned` / `waiting_dependency` 虽未出现在下拉，但仍被前端作为 active run 状态参与轮询：`frontend/src/pages/TaskRunCenter.tsx:225`。
- 问题：
  - 最新 PRD 要求本轮从前端移除/禁用 `stale_running / waiting_dependency / planned` 的列表筛选和列表操作。
  - 继续显示“疑似卡住”会让用户以为列表可以可信发现卡住任务。
- 要求：
  - 状态筛选下拉删除 `stale_running`。
  - URL 初始化时如果带 `display_status=stale_running|waiting_dependency|planned`，前端应清理该筛选或展示明确不可用提示，并不要发送误导性列表请求。
  - `hasActiveRun` 轮询可保留诊断态识别，但不能把这些状态变成列表筛选能力。

### P0：API 仍接受并执行不可信筛选

- 代码位置：
  - `backend/app/api/task_runs.py:370-417`
- 事实：
  - `_display_status_sql_condition("stale_running")` 返回 `TaskRun.display_status == "stale_running"`。
  - `_display_status_sql_condition("waiting_dependency")` 返回 `TaskRun.display_status == "waiting_dependency"`。
  - `_display_status_sql_condition("planned")` 返回 `TaskRun.display_status == "planned"`。
- 问题：
  - 本轮产品口径要求 API 不再返回误导性空结果或依赖未验收 projection 的 total。
  - 当前实现继续把这些列表筛选作为可用能力暴露。
- 要求：
  - 对 `display_status=stale_running|waiting_dependency|planned` 返回 400，错误文案说明“该状态仅在详情诊断中展示，当前列表不支持筛选”。
  - 或者完全从允许值中删除，不能再返回基于未验收 projection 的列表。

### P1：列表和详情并未真正同源

- 代码位置：
  - `backend/app/api/task_runs.py:226-238`
  - `backend/app/task_runtime/display.py:169-187`
  - `backend/app/task_runtime/display.py:190-285`
- 事实：
  - 详情 `_run_display()` 每次调用 `compute_task_run_projection()`，基于 loaded steps 即时计算。
  - 列表 `_run_list_display()` 优先读 `task_run_projection_from_fields()`，也就是 DB 中旧的 projection 字段。
- 问题：
  - 如果 projection 字段没有及时刷新，列表和详情仍会不同源。
  - 听云 `DONE_CLAIMED` 中“列表/详情/filter/action 同源”的说法不成立。
- 要求：
  - 本轮收缩路线下，列表不要展示这些依赖 step 的诊断状态。
  - 后续如果要做 projection PRD，必须证明所有状态变更路径都刷新 projection，并定义 projection 失效/恢复策略。

### P1：startup backfill 设计过重，不能作为本轮修复的一部分

- 代码位置：
  - `backend/app/main.py:86-93`
  - `backend/app/task_runtime/display.py:328-339`
- 事实：
  - `backfill_task_run_display_projections()` 会先查出全部 `TaskRun.id`，然后逐个 `refresh_task_run_projection()`。
  - `refresh_task_run_projection()` 每个 run 都 `selectinload` groups、steps、step events、run events。
- 问题：
  - 即使该开关默认关闭，这也是一次全量 N+1 维护任务设计，和本轮“先收缩、保可信”不匹配。
  - 一旦维护窗口开启，会把历史任务全量读出并逐个装饰，风险和耗时都未评估。
- 要求：
  - 本轮移除 task display projection backfill 或标记为后续 PRD，不与 `STARTUP_RUN_BACKFILLS` 绑定。
  - 后续若保留，必须有独立维护命令、批量分页、进度、失败恢复、数据规模说明和验收样本。

### P1：项目规则测试把错误方向锁死

- 代码位置：
  - `scripts/test_project_rules.py:1260-1385`
- 事实：
  - `test_task_run_list_default_views_are_db_pageable()` 要求 `stale_running` 必须 DB pageable。
  - `test_task_run_display_projection_fields_and_filters_are_run_level()` 强制模型和 schema ensure 必须有 projection 字段。
  - `test_task_run_list_response_prefers_display_projection()` 构造 `display_status=stale_running`，要求列表按 projection 返回并允许筛选。
- 问题：
  - 这些测试与最新 PRD 完全相反，会阻止听云按收缩路线整改。
- 要求：
  - 改成护栏测试：
    - 前端不展示 `stale_running` 筛选项。
    - API 对 `display_status=stale_running|waiting_dependency|planned` 返回明确不支持。
    - 列表路径不依赖 step JOIN/EXISTS/内存分页，也不依赖未验收 projection。
    - 详情仍可显示 step 诊断状态。

## 修复边界

本轮只做收缩路线：

- 前端删除/禁用不可信列表筛选。
- API 删除/拒绝不可信 `display_status` 列表筛选。
- 列表状态和按钮回到可信的 run-level 基础状态，不展示依赖 step 的诊断态。
- 详情页保留诊断态可以接受，但不能把它变成列表筛选能力。
- 项目规则测试改为保护上述收缩口径。

本轮不做：

- 不新增或扩大 `task_runs` projection schema。
- 不做 projection backfill。
- 不声明列表/详情/filter/action 已同源。
- 不迁移旧任务。
- 不触发真实任务、GIGA 拉品、导出、A+、商品状态推进或外部平台。

## 验证要求

听云返工后至少提供：

- `make backend-compile`
- `make test-project-rules`
- `git diff --check`
- 如改前端：`cd frontend && npm run build`
- 代码级样本：
  - `_display_status_sql_condition("stale_running")` 或 API 参数校验返回明确不支持。
  - `TaskRunCenter.tsx` 不再包含 `value: 'stale_running'` 状态筛选。
  - 详情路径仍可显示 `stale_running` 诊断状态。
