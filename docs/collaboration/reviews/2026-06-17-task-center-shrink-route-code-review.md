# Task Center Shrink Route Code Review

日期：2026-06-17
Reviewer：镜花（agentKey: `jinghua`）
范围：`MSG-20260617-010` / `MSG-20260617-012` 收缩路线返工实现
结论：CODE_REVIEW / PASS

## 范围

- 审查文件：
  - `backend/app/api/task_runs.py`
  - `backend/app/task_runtime/display.py`
  - `backend/app/task_runtime/scheduler.py`
  - `backend/app/models/models.py`
  - `backend/app/database.py`
  - `backend/app/main.py`
  - `frontend/src/pages/TaskRunCenter.tsx`
  - `scripts/test_project_rules.py`
  - `docs/domain-index/task-runtime.md`
- 审查目标：
  - 回退未验收 run-level projection route。
  - 列表/API/total 不支持 `stale_running / waiting_dependency / planned`。
  - 详情保留诊断态和详情动作。
  - 列表保持 `task_runs` 单表 DB 分页和真实 total。

## 验证

- `make backend-compile`：PASS。
- `make test-project-rules`：PASS，36 tests。
- `git diff --check`：PASS。
- `cd frontend && npm run build`：PASS；仅 Vite chunk-size warning。
- 代码级样本：
  - `_display_status_sql_condition("stale_running"|"waiting_dependency"|"planned")` 均返回 400。
  - `task_run_list_is_db_pageable(view="current", display_status_filter="stale_running")` 返回 `False`。

## Findings

未发现 P0/P1 阻断问题。

## 已确认通过

- `TaskRun` ORM 已移除未验收 projection 字段；MySQL ensure 不再新增 projection columns / `idx_task_runs_display_status_id`。
- `main.py` 不再调用 `backfill_task_run_display_projections()`；scheduler/API 不再调用 `refresh_task_run_projection()`。
- `backend/app/api/task_runs.py` 的列表路径不再引用 `TaskRun.display_status`、`task_run_projection_from_fields` 或 stored projection；`_history_display_sql_condition()` 只基于 `superseded_by_run_id` 和 run-level terminal status。
- `display_status=stale_running|waiting_dependency|planned` 在列表筛选中明确 400，错误文案说明仅用于详情诊断。
- `list_task_runs()` 仍是 `task_runs` 单表 `where/order/offset/limit/count`；未引入 step JOIN、`EXISTS`、scan window 或内存分页。
- `compute_task_run_display()` 作为纯详情诊断 helper 保留，不持久化、不 backfill、不喂给列表筛选/total。
- `TaskRunCenter.tsx` 删除“疑似卡住”列表筛选，URL 初始化会静默清理不支持的诊断态筛选；详情/标签仍保留诊断态展示能力。
- `docs/domain-index/task-runtime.md` 已同步为收缩路线口径。

## 未覆盖 / 风险

- 本轮 code review 未连接真实服务做页面点击或数据库现场验证；实际页面路径仍建议交给观止做 QA。
- 物理数据库中若已存在旧 projection columns，本轮按约束保留为遗留无用列，未做 destructive cleanup。
- `scripts/test_project_rules.py` 仍有较多字符串护栏；本轮关键 400 行为和详情 stale 诊断已有最小运行样本，但后续 task center 仍应逐步补更真实的 API/service 级测试。
