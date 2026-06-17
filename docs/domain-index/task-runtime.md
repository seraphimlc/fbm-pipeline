# Domain Index: Task Runtime

## 范围

- 新任务中心、新任务框架、任务状态/操作、恢复/重试/取消。
- GIGA 拉品和已迁移到新任务框架的任务。
- 旧 `offline_tasks` 只作为边界和兼容入口定位。

## 当前口径

- 新任务中心使用 `task_runs/task_groups/task_steps/task_step_events`。
- 旧 `offline_tasks` 和新 `task_runs` 不应混成同一个展示或状态语义。
- 任务状态和可操作性以后端字段为准，前端不自行推导。
- 2026-06-17 产品口径：任务中心是异步执行事实中心，商品流程是业务状态和操作中心；任务中心不能替代商品流程页面，也不能用任务状态反推商品状态。
- 当前 `MSG-20260617-010/012` 收敛方向：本轮走收缩路线，列表/API/total 不支持 `stale_running/waiting_dependency/planned` 筛选；这些状态仅保留为详情诊断展示。
- 长耗时任务必须可追踪、可恢复、可重试，不塞进临时后台任务。
- 高频列表接口不允许内存分页、假 total、重复 count 或复杂查询临时拼状态。
- 本轮不启用 run-level projection route；列表接口不得用 projection 存储、step JOIN、`EXISTS`、子查询或内存分页补回 `stale_running/waiting_dependency/planned` 筛选。

## 关键入口

- 页面：`frontend/src/pages/TaskRunCenter.tsx`
- 旧页面：`frontend/src/pages/OfflineTaskCenter.tsx`
- API：`backend/app/api/task_runs.py`, `backend/app/api/offline_tasks.py`
- runtime：`backend/app/task_runtime/`
- planners：`backend/app/task_planners/`
- 商品动作适配：`backend/app/product_tasks/actions.py`
- 模型：`backend/app/models/models.py`
- 后端注册：`backend/app/main.py`
- 表：`task_runs`, `task_groups`, `task_steps`, `task_step_events`, `offline_tasks`, `offline_task_steps`

## 关键流程

- 展示任务：`GET /api/task-runs` -> `TaskRunCenter.tsx`
- 创建任务：API/planner -> `task_runs/task_groups/task_steps` 落库。
- 执行任务：runtime 串行执行 step -> 写 `task_step_events` -> 更新 run/step 状态。
- 取消/重试/恢复：先看 `backend/app/api/task_runs.py` 和 `backend/app/task_runtime/` 当前实现。
- 旧任务边界：旧 `offline_tasks` 仍由旧页面/API 定位，不进入新任务中心语义。

## 相关文档

- `docs/superpowers/specs/2026-06-13-task-runtime-giga-pull-design.md`
- `docs/superpowers/specs/2026-06-16-task-center-state-action-prd.md`
- `docs/superpowers/specs/2026-06-16-product-task-action-refactor-prd.md`
- `docs/superpowers/specs/2026-06-03-offline-task-center.md`
- `docs/collaboration/playbooks/code-review.md`
- `docs/collaboration/playbooks/full-audit.md`
- `docs/collaboration/playbooks/qa.md`

## 验证入口

- 页面：`http://localhost:3190/task-runs`
- 旧页面：`http://localhost:3190/offline-tasks`
- API：`GET /api/task-runs`
- 任务详情/操作 API：先在 `backend/app/api/task_runs.py` 确认当前路由。
- 项目规则：`make test-project-rules`

## 常见定位

- 状态/按钮不对：先看 `backend/app/api/task_runs.py` 的列表筛选/响应字段，再看 `backend/app/task_runtime/display.py`；注意区分列表支持状态和详情诊断状态。
- 统计/分页不对：先看 `backend/app/api/task_runs.py` 的 DB 级过滤、排序和 count。
- 任务不执行：先看 `task_steps` 状态、`task_step_events`、`task_runs` 状态字段和 runtime scheduler。
- GIGA 拉品任务：先看 `backend/app/task_planners/giga_pull.py` 和 `backend/app/task_runtime/giga_pull_workers.py`。

## 维护规则

只有页面/API/核心 service/action/table/任务类型/状态语义/验证入口变化时更新本文。普通 bug fix、函数内部重构、样式微调、测试补充不需要更新。
