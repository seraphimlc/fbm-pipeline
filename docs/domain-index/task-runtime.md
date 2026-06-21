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
- 商品域 ProductTaskAction 当前包含 `product_auto_image_selection`、`product_competitor_search`、`product_competitor_visual_match`、`product_competitor_candidate_capture`、`product_auto_competitor_selection`、`product_image_analysis`、`product_listing_generation`；自动选图阶段 B 在新建 Amazon 商品完整落库后通过 `backend/app/task_planners/product_auto_image_selection.py` 创建/复用 task run，失败重试 API 也走同一 planner，不用裸后台任务承载主流程；自动竞品搜索 Phase A 通过 `backend/app/task_planners/product_competitor_search.py` 创建/复用 task run，成功后投影到 `visual_match_competitors/pending`；竞品视觉初筛 Phase B 通过 `backend/app/task_planners/product_competitor_visual_match.py` 创建/复用 task run，执行路径为源商品主图 URL + 候选 image URL direct VLM，不走候选下载/Contact Sheet fallback，processing 复用在 API 层 bypass，不改 `create_product_action_runs()` 顺序，成功后给当前 Top 候选写 `visual_task_run_id/visual_task_step_id` 并投影到 `capture_competitor_candidates/pending`；候选详情抓取 Phase 2A 可通过 fixture/configured adapter 执行，execute 只返回结构化结果，success hook 单事务写候选详情 current facts 并进入 `auto_select_competitor/pending`；自动选竞品仍是 skeleton，不写最终 ASIN，商品 workflow 不暴露未实现的抓详情/自动选竞品 retry action。
- 高频列表接口不允许内存分页、假 total、重复 count 或复杂查询临时拼状态。
- 本轮不启用 run-level projection route；列表接口不得用 projection 存储、step JOIN、`EXISTS`、子查询或内存分页补回 `stale_running/waiting_dependency/planned` 筛选。

## 关键入口

- 页面：`frontend/src/pages/TaskRunCenter.tsx`
- 旧页面：`frontend/src/pages/OfflineTaskCenter.tsx`
- API：`backend/app/api/task_runs.py`, `backend/app/api/offline_tasks.py`
- runtime：`backend/app/task_runtime/`
- planners：`backend/app/task_planners/`
- 商品动作适配：`backend/app/product_tasks/actions.py`
- 自动选图 planner：`backend/app/task_planners/product_auto_image_selection.py`
- 自动竞品搜索 planner：`backend/app/task_planners/product_competitor_search.py`
- 竞品视觉初筛 planner：`backend/app/task_planners/product_competitor_visual_match.py`
- 候选详情抓取 planner：`backend/app/task_planners/product_competitor_candidate_capture.py`
- 自动选竞品 planner：`backend/app/task_planners/product_auto_competitor_selection.py`
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
- 商品自动选图任务：先看 `backend/app/task_planners/product_auto_image_selection.py`、`backend/app/product_tasks/actions.py` 的 `ProductAutoImageSelectionAction`，再看 `backend/app/product_tasks/auto_image_selection.py`；商品侧重试入口看 `POST /api/products/{id}/auto-image-selection/retry`。
- 商品自动竞品搜索任务：先看 `backend/app/task_planners/product_competitor_search.py`、`backend/app/product_tasks/actions.py` 的 `ProductCompetitorSearchAction`，再看 `backend/app/services/amazon_competitor_query.py` 和 `backend/app/services/amazon_search_page.py`；商品侧启动/重试入口看 `POST /api/products/{id}/competitor-search/retry`。
- 商品竞品视觉初筛任务：先看 `backend/app/task_planners/product_competitor_visual_match.py`、`backend/app/product_tasks/actions.py` 的 `ProductCompetitorVisualMatchAction`，再看 `backend/app/services/amazon_competitor_visual_match.py`；商品侧启动/重试入口看 `POST /api/products/{id}/competitor-visual-match/retry`。
- 商品候选详情抓取 / 自动选竞品任务：先看 `backend/app/task_planners/product_competitor_candidate_capture.py`、`backend/app/task_planners/product_auto_competitor_selection.py` 和 `backend/app/product_tasks/actions.py` 的 `ProductCompetitorCandidateCaptureAction` / `ProductAutoCompetitorSelectionAction`；Phase 2A 后端 candidate capture 已支持 fixture/configured adapter 执行和 detail current fact success hook，真实 API/前端入口仍未启用，`backend/app/services/amazon_listing_detail.py` 默认 adapter 仍只抛 `adapter_not_configured`；商品 workflow pending/failed 只能给 `open_detail` / `restart_competitor_search`，processing 才给 `open_task_center`。

## 维护规则

只有页面/API/核心 service/action/table/任务类型/状态语义/验证入口变化时更新本文。普通 bug fix、函数内部重构、样式微调、测试补充不需要更新。
