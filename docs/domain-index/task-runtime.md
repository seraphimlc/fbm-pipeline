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
- `auto_start=True` 的当前保证是“正常服务进程内创建 ready step 后由 `kick_task_runtime()` 调度进程内 runner 自动 drain，并通过 `_claim_next_step` / `_execute_step` 触达 worker 路径”，不是跨进程、跨重启的 durable worker。`backend/app/task_runtime/scheduler.py` 会记录 runner schedule/start/claim/finish，并清理完成、异常或取消后的 runner state；不通过自动调用 task-center wake 伪装修复。历史 queued/stale run 的启动仍由显式 `STARTUP_KICK_TASK_RUNTIME` / `STARTUP_RECOVER_TASKS` 或人工 wake 控制，默认安全关闭。
- 商品域 ProductTaskAction 当前包含 `product_auto_image_selection`、`product_competitor_search`、`product_competitor_visual_match`、`product_competitor_candidate_capture`、`product_auto_competitor_selection`、`product_image_analysis`、`product_listing_generation`；自动选图阶段 B 在新建 Amazon 商品完整落库后通过 `backend/app/task_planners/product_auto_image_selection.py` 创建/复用 task run，失败重试 API 也走同一 planner，不用裸后台任务承载主流程；自动竞品搜索 Phase A 通过 `backend/app/task_planners/product_competitor_search.py` 创建/复用 task run，成功后投影到 `visual_match_competitors/pending`；竞品视觉初筛 Phase B 通过 `backend/app/task_planners/product_competitor_visual_match.py` 创建/复用 task run，执行路径为源商品主图 URL + 候选 image URL direct VLM，不走候选下载/Contact Sheet fallback，processing 复用在 API 层 bypass，不改 `create_product_action_runs()` 顺序，成功后给当前 Top 候选写 `visual_task_run_id/visual_task_step_id` 并创建/复用 `product_competitor_candidate_capture`；ProductTaskAction failure hook 由 worker 在 rollback 后重载 step 再投影，scheduler 异常路径也重载 step/run/group，避免 VLM/API/TLS/model failure 因 async lazy-load/MissingGreenlet 崩 runner；候选详情抓取 Phase 2A 可通过 fixture/configured adapter 执行，默认 detail adapter 未配置时 typed failed 为 `adapter_not_configured`，execute 只返回结构化结果，success hook 单事务写候选详情 current facts 并创建/复用 `product_auto_competitor_selection`；自动选竞品 E4A 已实现 deterministic scoring、protected final competitor write 和 `product_image_analysis` task run 创建/复用（不自动执行真实图片分析），商品 workflow 仍不暴露抓详情/自动选竞品 retry action。E5 已实现 `product_image_analysis` success 创建/复用 `product_listing_generation`，Listing success 通过 `_project_listing_completed()` 投影到 `flow_done/succeeded` / `Product.status=completed`；下游创建失败投影到 `listing_generation/failed`，failure/cancel/interrupted 不写 completed，E5 action 保护门阻断真实 ASIN、导出历史、模板输出、A+ 上传和预先人工确认。A+ 自动触发 A1/A2 位于 `backend/app/services/aplus_auto_trigger.py`：A1 eligibility 检查 active 主流程/A+ task，A2 Listing hook 在 E5 commit 后、配置开启时调用 `create_aplus_generate_runs()` 创建/复用 `aplus_generate` run；默认关闭不创建 task，失败只写 listing summary/log。
- Lingxing A+ 发布工程线 T1 已建立数据/状态基础：`backend/app/aplus_publish/status.py` 定义发布状态 registry，`backend/app/services/aplus_publish_state.py` 统一写 Product/Catalog 发布状态镜像和 AplusUploadItem 外部证据，`backend/app/database.py` 补齐字段和索引。T2 已注册 `lingxing_listing_sync` task type 和 `lingxing_listing_sync_product` step，通过 `backend/app/task_planners/lingxing_listing_sync.py`、`backend/app/task_runtime/lingxing_listing_sync_workers.py` 和 `POST /api/task-runs/lingxing-listing-sync` 执行 seller SKU/MSKU first 的 Lingxing Listing / ASIN 对齐；UPC 只能作为辅助诊断。当前仍未注册 `lingxing_aplus_publish`、`lingxing_aplus_draft_visibility` 或 `lingxing_aplus_submit`，也未启用 A+ done 自动触发。
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
- 自动启动：planner/action 创建 task run 时若 `auto_start=True`，首个可执行 step 持久化为 `ready`，提交后调用 `kick_task_runtime()`；runner 在当前服务进程内领取 ready step，不需要用户点击 wake。wake 仅用于诊断态/手动恢复，不是新 run 正常执行路径。
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
- 新 run 需要 wake 才执行：先确认创建路径是否真的传入 `auto_start=True` 且首 step 为 `ready`，再看后端日志中的 `[TaskRuntime] scheduling/starting/claimed/finished` runner 生命周期日志；若服务重启前已存在 queued/stale run，默认不会 startup pickup，需显式配置或人工 wake。若正常服务进程内新 run 无日志且一直 queued，优先查 `kick_task_runtime()` runner state 和异常日志。
- GIGA 拉品任务：先看 `backend/app/task_planners/giga_pull.py` 和 `backend/app/task_runtime/giga_pull_workers.py`。
- 商品自动选图任务：先看 `backend/app/task_planners/product_auto_image_selection.py`、`backend/app/product_tasks/actions.py` 的 `ProductAutoImageSelectionAction`，再看 `backend/app/product_tasks/auto_image_selection.py`；商品侧重试入口看 `POST /api/products/{id}/auto-image-selection/retry`。
- 商品自动竞品搜索任务：先看 `backend/app/task_planners/product_competitor_search.py`、`backend/app/product_tasks/actions.py` 的 `ProductCompetitorSearchAction`，再看 `backend/app/services/amazon_competitor_query.py` 和 `backend/app/services/amazon_search_page.py`；商品侧启动/重试入口看 `POST /api/products/{id}/competitor-search/retry`。
- 商品竞品视觉初筛任务：先看 `backend/app/task_planners/product_competitor_visual_match.py`、`backend/app/product_tasks/actions.py` 的 `ProductCompetitorVisualMatchAction`，再看 `backend/app/services/amazon_competitor_visual_match.py`；商品侧启动/重试入口看 `POST /api/products/{id}/competitor-visual-match/retry`。
- 商品候选详情抓取 / 自动选竞品任务：先看 `backend/app/task_planners/product_competitor_candidate_capture.py`、`backend/app/task_planners/product_auto_competitor_selection.py` 和 `backend/app/product_tasks/actions.py` 的 `ProductCompetitorCandidateCaptureAction` / `ProductAutoCompetitorSelectionAction`；Phase 2A 后端 candidate capture 已支持 fixture/configured adapter 执行、detail current fact success hook 和自动创建/复用 auto competitor selection；E4A 后端 auto competitor selection 已支持 current-set deterministic scoring、final facts 写入和 image_analysis task 创建/复用；真实 API/前端入口仍未启用，`backend/app/services/amazon_listing_detail.py` 默认 adapter 仍只抛 `adapter_not_configured` 并通过 task failed/workflow failed 暴露；商品 workflow pending/failed 只能给 `open_detail` / `restart_competitor_search`，processing 才给 `open_task_center`。
- 商品图片分析 / Listing 生成任务：先看 `backend/app/product_tasks/actions.py` 的 `ProductImageAnalysisAction` / `ProductListingGenerationAction`、`backend/app/task_planners/product_image_analysis.py`、`backend/app/task_planners/product_listing.py`、`POST /api/products/{id}/retry` 和 `frontend/src/pages/ProductList.tsx` 的 `retry_image_analysis` / `retry_listing_generation` 映射；行为验证用 `cd backend && .venv/bin/python ../scripts/test_image_analysis_listing_e5.py`。
- A+ 自动触发 A1/A2：先看 `backend/app/services/aplus_auto_trigger.py`、`backend/app/product_tasks/actions.py` 的 Listing success hook、`backend/app/task_planners/aplus_generate.py` 和 `scripts/test_aplus_auto_trigger_a1_a2.py --stage a2`；A2 的 task-runtime 口径是默认关闭 no-op，开启后通过新任务中心 `aplus_generate` 创建/复用单品 A+ run，不使用旧 `offline_tasks`。
- Lingxing A+ 发布 task 迁移问题：T1 数据/状态基础先看 `backend/app/aplus_publish/status.py`、`backend/app/services/aplus_publish_state.py`、`backend/app/models/models.py` 和 `backend/app/database.py`；T2 Listing / ASIN 前置看 `backend/app/task_planners/lingxing_listing_sync.py`、`backend/app/task_runtime/lingxing_listing_sync_workers.py`、`backend/app/services/asin_match_policy.py` 和 `backend/app/services/lingxing_listing_client.py`。如果要找 A+ 草稿保存、draft visibility 或 submit worker/API，当前应确认尚未存在，后续 T3+ 才允许新增。

## 维护规则

只有页面/API/核心 service/action/table/任务类型/状态语义/验证入口变化时更新本文。普通 bug fix、函数内部重构、样式微调、测试补充不需要更新。
