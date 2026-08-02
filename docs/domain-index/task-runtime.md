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
- 商品域 ProductTaskAction 当前包含 `product_auto_image_selection`、`product_competitor_search`、`product_competitor_visual_match`、`product_competitor_candidate_capture`、`product_auto_competitor_selection`、`product_keyword_research`、`product_image_analysis`、`product_customer_mindset`、`product_listing_generation`。自动竞品链路、任务失败重载和保护门沿用既有口径；内容生成尾段固定为 `product_image_analysis -> product_customer_mindset -> product_listing_generation`。心智 action 使用 `backend/app/pipeline/customer_mindset.py`，基于图片分析后的证据目录回答 13 个固定核心问题，并按商品证据从实际使用行为、材质或性能参数、摆放或环境适配、长期使用或维护、买错风险或证据缺口等视角择优生成 2 至 5 个商品特有、高决策影响且互不重复的动态问题，总计 15 至 18 题；成功写 `ProductData.customer_mindset/customer_mindset_generated_at` 后才创建 Listing run。失败、取消或中断停在 `customer_mindset/failed`，不写 Listing 或 completed。Listing 与 A+规划读取同一简报；直接 Step 6、批量推进、重试和继续入口缺少简报时不得绕过。Listing success 仍通过 `_project_listing_completed()` 投影到 `flow_done/succeeded` / `Product.status=completed`，之后才按配置 best-effort 触发独立 A+ task。
- Lingxing A+ 发布工程线 T1 已建立数据/状态基础：`backend/app/aplus_publish/status.py` 定义发布状态 registry，`backend/app/services/aplus_publish_state.py` 统一写 Product/Catalog 发布状态镜像和 AplusUploadItem 外部证据，`backend/app/database.py` 补齐字段和索引。T2 已注册 `lingxing_listing_sync` task type 和 `lingxing_listing_sync_product` step，通过 `backend/app/task_planners/lingxing_listing_sync.py`、`backend/app/task_runtime/lingxing_listing_sync_workers.py` 和 `POST /api/task-runs/lingxing-listing-sync` 执行 seller SKU/MSKU first 的 Lingxing Listing / ASIN 对齐；UPC 只能作为辅助诊断。T3 已注册 `lingxing_aplus_publish` task type 和 `lingxing_aplus_publish_product` step，通过 `backend/app/task_planners/lingxing_aplus_publish.py`、`backend/app/task_runtime/lingxing_aplus_publish_workers.py` 和 `POST /api/task-runs/lingxing-aplus-publish` 保存领星 A+ 草稿；成功只写 `draft_saved`、`lingxing_aplus_id_hash`/record key、`publish_evidence_json` 和 `amazon_draft_visibility=unconfirmed`。T3.5/M2/M3 的发布模块事实源为 `backend/app/aplus_publish/module_registry.py`：legacy `standard_header_image_text_v1` 仍走 5 个 `STANDARD_HEADER_IMAGE_TEXT`；enhanced `enhanced_basic_aplus_v1` 是 basic tier，固定 5 个普通 A+ 标准模块和 7 个必需 image slot。`backend/app/services/lingxing_aplus_module_mapper.py` 在任何 Lingxing auth/uploadDestination/object upload/add 前做 profile-aware preflight，缺 profile/type/headline/body、数量/position/图片不匹配、enhanced slot 缺失/重复/意外/尺寸或 payload_slot 不一致、比较图/规格表不满足 registry 均本地 fail closed；client 上传后只用 mapper `assemble_payload()` 注入 `uploadDestinationId`，enhanced 路径按 `asset_slot_id` slot map 组装 `contentModuleList`。当前仍未注册 `lingxing_aplus_draft_visibility` 或 `lingxing_aplus_submit`，也未启用 A+ done 自动触发；enhanced profile 成功仍只是 draft-save-only。
- 高频列表接口不允许内存分页、假 total、重复 count 或复杂查询临时拼状态。
- Catalog export 的业务终态由 validated outcome 驱动：`done/succeeded`、`partial_failed/partial_failed`、`failed/failed`，只覆盖 TaskRun `succeeded|partial_failed|failed` 与 OfflineTask `done|partial_failed|failed`，不覆盖 canceled/interrupted/paused。只有 parse-valid material summary 才阻断更旧 step；invalid JSON、NaN/Infinity、溢出数值、深度/内存解析失败都记录为 malformed nonmaterial，并继续回退更旧的 parse-valid material step，status-only summary 同样可回退。选中的 raw payload 恰好进入一次 `normalize_catalog_export_response()`；invalid-only 不制造 authoritative failed，parse-valid unsafe row 仍 authoritative fail closed。validated outcome 是 TaskRun/OfflineTask 响应、Export Center、download action、categories 和 existing-result 复用的唯一事实源。
- 列表投影采用“全历史 owner scalar + 一次 step batch”：每个 owner kind 先只读全部 catalog owner 的 `id/status/summary_json|result_json`，再一次批量读取 `owner_id/step.id/result_json` 的 newest parse-valid material step，不加载 groups/events/完整 ORM steps。Python 生成共享 `records_by_id`、authoritative 与 succeeded/done/partial/failed ID 集；TaskRun/OfflineTask 列表及 Export Files/Categories 各自每 owner kind 只加载一次 projection，并让 owner SQL、row builder、下载 gate、类目聚合消费同一 records/ID sets。raw canceled/interrupted/paused 即使带 material done 也不被 outcome 复活，不进入 Export Files/Categories；禁止 legacy partial helper、JSON SQL、step JOIN/`EXISTS`/子查询、N+1 和 row builder 内二次 selector/normalize/project。
- Catalog export worker 通过 `TaskWorkerOutcome` 交给 scheduler 单事务投影 step/group/run、terminal event 与 CatalogProduct 导出事实；partial 是不可自动重试终态，但保留下载结果。
- 本轮不启用 run-level projection route；列表接口不得用 projection 存储、step JOIN、`EXISTS`、子查询或内存分页补回 `stale_running/waiting_dependency/planned` 筛选。

## 关键入口

- 页面：`frontend/src/pages/TaskRunCenter.tsx`
- 旧页面：`frontend/src/pages/OfflineTaskCenter.tsx`
- API：`backend/app/api/task_runs.py`, `backend/app/api/offline_tasks.py`
- Catalog export effective status：`backend/app/task_runtime/catalog_export_status.py`
- runtime：`backend/app/task_runtime/`
- planners：`backend/app/task_planners/`
- 商品动作适配：`backend/app/product_tasks/actions.py`
- 自动选图 planner：`backend/app/task_planners/product_auto_image_selection.py`
- 自动竞品搜索 planner：`backend/app/task_planners/product_competitor_search.py`
- 竞品视觉初筛 planner：`backend/app/task_planners/product_competitor_visual_match.py`
- 候选详情抓取 planner：`backend/app/task_planners/product_competitor_candidate_capture.py`
- 自动选竞品 planner：`backend/app/task_planners/product_auto_competitor_selection.py`
- 关键词采集 planner：`backend/app/task_planners/product_keyword_research.py`
- 用户心智 planner：`backend/app/task_planners/product_customer_mindset.py`
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
- `docs/superpowers/specs/2026-06-23-lingxing-aplus-module-mapping-prd.md`
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
- Catalog export outcome/MySQL：`cd backend && R1_TEST_MYSQL_ADMIN_URL='mysql+asyncmy://root@127.0.0.1:3306/' .venv/bin/python ../scripts/test_stability_repair_r1_catalog_export.py`
- 完整项目规则隔离 MySQL：`R1_TEST_MYSQL_ADMIN_URL='mysql+asyncmy://root@127.0.0.1:3306/' python3 scripts/testing/run_with_r1_mysql.py -- make test-project-rules`；只有字面 argv `make test-project-rules` 是 canonical 输入，wrapper 将其改写为经 `resolve(strict=True)`/可执行校验的 `/usr/bin/make`（fallback `/bin/make`）与固定 `-C <repo> -f <repo>/Makefile test-project-rules`，不信任 caller PATH 或绝对/相对 make 路径。marker path/nonce/command id 只注入该 trusted child，generic child 会清除这些环境变量；markerless/wrong nonce/db/command 返回 3，不存在 executable 返回 127，退出/信号路径清理自有进程组、数据库和临时目录。

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
- 商品图片分析 / 用户心智 / Listing 生成任务：先看 `backend/app/product_tasks/actions.py` 的 `ProductImageAnalysisAction` / `ProductCustomerMindsetAction` / `ProductListingGenerationAction`、`backend/app/pipeline/customer_mindset.py`、三个对应 planner 及 `POST /api/products/{id}/retry`；问题与消费契约用 `cd backend && .venv/bin/python ../scripts/test_customer_mindset.py`，完整行为链用 `cd backend && .venv/bin/python ../scripts/test_image_analysis_listing_e5.py`。
- A+ 自动触发 A1/A2：先看 `backend/app/services/aplus_auto_trigger.py`、`backend/app/product_tasks/actions.py` 的 Listing success hook、`backend/app/task_planners/aplus_generate.py` 和 `scripts/test_aplus_auto_trigger_a1_a2.py --stage a2`；A2 的 task-runtime 口径是默认关闭 no-op，开启后通过新任务中心 `aplus_generate` 创建/复用单品 A+ run，不使用旧 `offline_tasks`。
- Lingxing A+ 草稿保存 T3/T3.5/M3：行为验证用 `cd backend && .venv/bin/python ../scripts/test_lingxing_aplus_module_mapper.py`、`cd backend && .venv/bin/python ../scripts/test_lingxing_aplus_publish_policy.py`、`cd backend && .venv/bin/python ../scripts/test_lingxing_aplus_publish_tasks.py` 和 `make test-project-rules`；M3.3 前置只读 readiness 用 `cd backend && .venv/bin/python ../scripts/check_lingxing_enhanced_aplus_qa_readiness.py`；本地 enhanced QA 样本准备 dry-run 用 `cd backend && .venv/bin/python ../scripts/prepare_lingxing_enhanced_aplus_qa_sample.py`，写库必须显式 `--catalog-product-id <id> --write`，覆盖已有 A+ 内容还必须显式 `--overwrite-aplus`。这些验证覆盖 legacy + enhanced registry/profile、Step8/Step9 slot manifest、policy asset collection、mapper preflight/assembly、client slot upload map、worker external-call 前 fail-closed 和 draft-save-only 成功边界；readiness/sample 脚本只检查或准备本地 ProductAplus/slot images，不触发 Lingxing/Chrome/Amazon。它们只证明 `draft_saved + amazon_draft_visibility=unconfirmed` 或 QA 前置是否齐备，不能作为 `draft_visible`、Amazon Seller Central 可见或 `submitted`。继续 M3.3/T4 前必须先经过 code review，并由观止用真实领星草稿确认 enhanced 5 个模块字段可见。
- Lingxing A+ 发布 task 迁移问题：T1 数据/状态基础先看 `backend/app/aplus_publish/status.py`、`backend/app/services/aplus_publish_state.py`、`backend/app/models/models.py` 和 `backend/app/database.py`；T2 Listing / ASIN 前置看 `backend/app/task_planners/lingxing_listing_sync.py`、`backend/app/task_runtime/lingxing_listing_sync_workers.py`、`backend/app/services/asin_match_policy.py` 和 `backend/app/services/lingxing_listing_client.py`；T3/T3.5/M3 草稿保存、registry-backed module/slot 映射和 enhanced profile 看 `backend/app/aplus_publish/module_registry.py`、`backend/app/pipeline/step7_aplus_plan.py`、`backend/app/pipeline/step8_aplus_script.py`、`backend/app/pipeline/step9_aplus_image.py`、`backend/app/services/lingxing_aplus_module_mapper.py`、`backend/app/services/lingxing_aplus_publish_policy.py`、`backend/app/services/lingxing_aplus_publish_client.py`、`backend/app/task_planners/lingxing_aplus_publish.py`、`backend/app/task_runtime/lingxing_aplus_publish_workers.py` 和 `POST /api/task-runs/lingxing-aplus-publish`。如果要找 draft visibility 或 submit worker/API，当前应确认尚未存在，后续 T4/T6 才允许新增。

## 维护规则

只有页面/API/核心 service/action/table/任务类型/状态语义/验证入口变化时更新本文。普通 bug fix、函数内部重构、样式微调、测试补充不需要更新。
