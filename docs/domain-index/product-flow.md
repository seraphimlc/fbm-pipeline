# Domain Index: Product Flow

## 范围

- 商品列表、商品详情、图片选择、竞品选择、商品状态流转。
- Amazon/TikTok 商品详情页分流。
- 商品进入导出或平台铺货前的人工确认节点。

## 当前口径

- 商品列表可以按数据源/店铺过滤。
- Amazon 与 TikTok 商品详情页应分流；详情页状态、操作、类目和导出链路不能混用。
- TikTok 有强类目约束；Amazon 当前以模板/导出链路为主。
- 旧主流程中图片、竞品、类目、ASIN、导出等人工确认节点不能自动推进；自动选图/自动竞品选择的新目标流程见 `docs/superpowers/specs/2026-06-19-amazon-auto-image-competitor-selection-prd.md`。执行设计已拆为 `docs/superpowers/specs/2026-06-19-amazon-auto-image-selection-prd.md` 和 `docs/superpowers/specs/2026-06-19-amazon-auto-competitor-selection-prd.md`，将图片选择和竞品选择改为系统自动异步节点，人工页面降级为失败/低置信度/主动纠偏入口。
- 前端不应重新实现后端业务规则。
- `GET /api/products/{id}` 商品详情必须是只读接口；素材目录只能扫描汇总，不能移动、创建、删除、重命名或改写用户素材文件。
- 商品状态只表达业务节点和业务结果，不表达任务执行细节；Amazon 主流程最终 PRD 以 `docs/superpowers/specs/2026-06-18-amazon-product-workflow-prd.md` 为准。
- Amazon workflow T1 已进入结构层：`products.workflow_node/workflow_status/workflow_error/workflow_updated_at` 和集中枚举常量定义在后端模型/状态常量中；后续投影和写入统一入口仍按 PRD 分阶段推进。
- Amazon workflow T2 的 Product Workflow Service 位于 `backend/app/product_tasks/workflow.py`：集中提供 `set_product_workflow()`、`build_product_workflow()` 和 node/action 映射；商品列表/详情 workflow 投影应同源调用该 service。
- 空 workflow 字段投影为 `needs_initialization` 正式工作状态；后端 overview/list/filter/schema 和前端工作台类型、元信息、筛选入口都必须接住该状态，不得回退到旧 `status/current_step` 猜成图片确认等其它桶。
- Amazon workflow T3：旧人工图片确认入口仍由 `PUT /api/products/{id}/listing-images` 保存主图/副图并执行 destructive reset，成功后进入 `search_competitor/pending`；该入口现在是自动选图失败/用户主动纠偏入口，保存前必须保护真实 ASIN、导出历史、Amazon 模板输出和 A+ 上传证据。
- Amazon 自动选图阶段 B：新建 Amazon 商品默认进入 `auto_select_images/pending`，完整落库后创建/复用 `product_auto_image_selection` task run 并投影 `processing`；`auto_select_images/pending` 是商品工作台正式状态桶，overview/list/frontend filter 均需显式支持，`processing` 归入 `running`。`auto_select_images/succeeded` 的节点 label 可显示自动选图完成，但工作台 `work_status` 必须落入已有 `select_competitor` 桶，不能产生未注册的中间状态。task run 创建失败落 `auto_select_images/failed`。`POST /api/products/{id}/auto-image-selection/retry` 基于 workflow 状态重试；商品列表消费后端 `retry_auto_image_selection` / `manual_adjust_images` action。自动选图候选和成功写库均 URL 优先；已有 URL 时不下载候选图、不生成 Contact Sheet、不把本地路径写成主图/副图。阶段 B 不自动启动竞品搜索。
- Amazon 自动竞品搜索 Phase A：`search_competitor/pending|failed` 可通过 `POST /api/products/{id}/competitor-search/retry` 创建/复用 `product_competitor_search` task run；reserve 投影 `search_competitor/processing`，成功把 Amazon 页面搜索候选写入 `amazon_competitor_search_candidates` 并进入 `visual_match_competitors/pending`，失败回到 `search_competitor/failed`。`amazon_competitor_search_candidates` 是自动竞品搜索主事实源。本阶段不做视觉初筛、抓详情或自动选择竞品。
- Amazon 竞品视觉初筛 Phase B：`visual_match_competitors/pending|failed` 可通过 `POST /api/products/{id}/competitor-visual-match/retry` 创建/复用 `product_competitor_visual_match` task run；`processing` 状态由 API 直接返回当前 workflow/task-center correlation，不调用 planner。reserve 会清空同商品旧视觉当前事实和 `visual_selected_for_capture`，execute 只读取最近成功 `product_competitor_search` run/step 的候选，默认用源商品主图 URL + 候选 `image_url` direct VLM 做视觉初筛，不下载候选图、不生成 Contact Sheet、不做拼接兜底；只在显式测试 fixture 路径使用 fake review。成功只给当前 run/step Top 4-6 写 `visual_selected_for_capture=1` 并进入 `capture_competitor_candidates/pending`，失败/取消/中断回到 `visual_match_competitors/failed` 且不保留 current selected candidates。本阶段不抓 Amazon 详情、不自动选最终竞品。
- Amazon 候选详情抓取 / 自动选竞品 E4A：`capture_competitor_candidates` 已增加 `visual_task_run_id/visual_task_step_id` current-set evidence；视觉初筛 success 会给当前 Top 候选写入 visual task run/step。`product_competitor_candidate_capture` 可在 fixture/configured adapter 下执行，`execute_step()` 只返回结构化候选详情结果、不写候选表；`on_step_success()` 单事务写 `detail_* / capture_*` current facts，并推进到 `auto_select_competitor/pending`。`product_auto_competitor_selection` 后端已基于最新成功视觉 run/step 的当前 successful detail rows 做 deterministic rule scoring，`execute_step()` 只返回评分结果，`on_step_success()` 重查 current set 和保护门后写 selected row `final_*`、`products.competitor_asin`、`catalog_products.competitor_asin` 和 snapshot selected competitor，并创建/复用 `product_image_analysis` task run（E4A 不自动启动真实图片分析）。低置信度、事实不足、硬拒绝、保护门、取消或中断回到失败态且不清 search/visual/detail facts。真实 API/前端 retry 入口仍未启用，商品 workflow 在 pending/failed 仍只暴露 `open_detail` / `restart_competitor_search`；processing 用 `open_task_center`。
- Amazon 图片分析 / Listing 生成 E5：`product_image_analysis` success 通过 `create_product_action_runs()` 创建或复用 `product_listing_generation` run，重复 success 复用 active listing run，已 `flow_done/succeeded` / `Product.status=completed` 的商品 no-op。Listing 创建失败会投影到 `listing_generation/failed` 并暴露 `retry_listing_generation`。`product_listing_generation` success 是唯一进入 `flow_done/succeeded`、`Product.status=completed`、商品列表 `export_ready/待导出` 的主流程入口；failure/cancel/interrupted 不得写 completed。E5 保护门阻断真实 ASIN、导出历史、Amazon 模板输出、A+ 上传证据和预先存在的 `CatalogProduct.confirmed_at`，Listing success 只允许受控创建待导出用 `confirmed_at`。历史商品如果 `workflow_node/workflow_status` 为空但已有稳定 E5 事实，`build_product_workflow()` 会只读投影：`Product.status=completed` + `CatalogProduct.confirmed_at` 视为 `flow_done/succeeded`；failed 商品按 `ProductImage.image_analysis` / `ProductData.listing_title` 是否已产出区分图片分析或 Listing retry action，不用 `error_message` 字符串或 `current_step` 猜节点。商品列表所有接受的 `work_status` 均使用 DB 级 predicate/count/page；不可由内存过滤、内存分页或伪造 total 兜底。
- 今日自动主链路目标见 `docs/superpowers/specs/2026-06-21-amazon-auto-flow-to-export-ready-prd.md`：从 GIGA 商品入库/分组自动推进到 `Product.status=completed`，前端展示 `export_ready / 待导出`；不包含自动导出、Amazon 上传或外部平台发布。
- A+ 自动触发见 `docs/superpowers/specs/2026-06-21-amazon-aplus-auto-after-export-ready-prd.md`：A+ 是待导出后的独立派生链路，不并入商品主 workflow；A+ 失败不能让商品退出待导出。
- TikTok 链路重设计见 `docs/superpowers/specs/2026-06-21-tiktok-listing-flow-redesign-prd.md`：TikTok 需要独立状态、类目、库存、价格和导出/发布口径，不能复用 Amazon 类目/竞品/导出语义。
- 旧 StyleSnap 模式已退役：后端不再注册或保留 `/api/amazon-stylesnap` router，旧前端竞品确认页已删除，`/products/competitor-review` 仅重定向到商品列表；代码层不再保留旧 `AmazonStyleSnapCandidate` / `AmazonListingCapture` 模型、旧 snapshot key 读取或导出兼容逻辑。已存在的旧物理表不由应用启动逻辑维护或自动 drop。
- 已修 P0：ProductTaskAction reserve 后的图片分析/Listing 入队态不能再被旧 pipeline `is_running(product.id)` 误判为中断。后续结构治理应把商品主状态从 task queued/running 语义收敛为业务节点四态。

## 关键入口

- 商品列表：`frontend/src/pages/ProductList.tsx`
- Amazon 详情：`frontend/src/pages/ProductDetail.tsx`
- TikTok 详情：`frontend/src/pages/TikTokProductDetail.tsx`
- 图片确认：`frontend/src/pages/ProductImageReview.tsx`
- 新建商品：`frontend/src/pages/CreateProduct.tsx`
- 前端 API client：`frontend/src/api/index.ts`
- 商品 API：`backend/app/api/products.py`
- 自动选图：`backend/app/services/giga_product_drafts.py`, `backend/app/services/product_image_candidates.py`, `backend/app/services/product_image_vlm.py`, `backend/app/services/product_protection.py`, `backend/app/product_tasks/auto_image_selection.py`, `backend/app/task_planners/product_auto_image_selection.py`
- 自动竞品搜索/视觉初筛/候选详情/自动选竞品：`backend/app/services/amazon_competitor_query.py`, `backend/app/services/amazon_search_page.py`, `backend/app/services/amazon_competitor_visual_match.py`, `backend/app/services/amazon_listing_detail.py`, `backend/app/task_planners/product_competitor_search.py`, `backend/app/task_planners/product_competitor_visual_match.py`, `backend/app/task_planners/product_competitor_candidate_capture.py`, `backend/app/task_planners/product_auto_competitor_selection.py`, `backend/app/product_tasks/actions.py`
- TikTok API：`backend/app/api/tiktok.py`
- pipeline：`backend/app/pipeline/engine.py`, `backend/app/pipeline/step*.py`
- 模型：`backend/app/models/models.py`
- 表：`products`, `product_data`, `product_images`, `product_aplus`, `catalog_products`, `amazon_competitor_search_candidates`

## 关键流程

- 商品列表/详情：页面 -> `frontend/src/api/index.ts` -> `backend/app/api/products.py`；详情素材摘要通过 `backend/app/services/material_assets.py` 只读扫描。
- 图片确认：`ProductImageReview.tsx` -> 商品 API -> `product_images`。
- 自动竞品搜索：商品列表/详情 workflow action -> `POST /api/products/{id}/competitor-search/retry` -> `product_competitor_search` task run -> `amazon_competitor_search_candidates`。
- 竞品视觉初筛：商品列表 workflow action -> `POST /api/products/{id}/competitor-visual-match/retry` -> `product_competitor_visual_match` task run -> 当前搜索 run/step 的 `amazon_competitor_search_candidates.visual_*` 字段 -> `capture_competitor_candidates/pending`。
- 候选详情抓取/自动选竞品 E4A：`capture_competitor_candidates/pending|failed` 与 `auto_select_competitor/pending|failed` 仍仅用 `open_detail` / `restart_competitor_search` 表示安全用户动作；`processing` 用 `open_task_center` 定位已注册 task correlation。后端 candidate capture action 已支持 fixture/configured adapter 执行和 success hook 落库；auto competitor selection action 已支持 deterministic final competitor scoring/write 和 image_analysis task 创建/复用。真实 API retry、前端按钮、真实 Amazon adapter 和真实图片分析执行仍未启用。
- 图片分析/Listing 生成 E5：图片分析 success hook -> `product_listing_generation` task run -> Listing success hook -> `_project_listing_completed()` -> `flow_done/succeeded` / `Product.status=completed` / 商品列表 `export_ready`。`retry_image_analysis`、`retry_listing_generation` 由 workflow 暴露并由商品列表映射到后端安全 `retryStep`；前端不自行推业务状态。
- Amazon/TikTok 详情分流：前端路由和数据源类型共同决定详情入口。

## 相关文档

- `docs/main-flow-user-path.md`
- `docs/main-flow-qa-checklist.md`
- `docs/item-workbench-redesign-plan.md`
- `docs/documentation-rewrite-brief.md`
- `docs/superpowers/specs/2026-06-18-amazon-product-workflow-prd.md`
- `docs/superpowers/specs/2026-06-19-amazon-auto-image-competitor-selection-prd.md`
- `docs/superpowers/specs/2026-06-19-amazon-auto-image-selection-prd.md`
- `docs/superpowers/specs/2026-06-19-amazon-auto-competitor-selection-prd.md`
- `docs/superpowers/specs/2026-06-21-amazon-auto-flow-to-export-ready-prd.md`
- `docs/superpowers/specs/2026-06-21-amazon-aplus-auto-after-export-ready-prd.md`
- `docs/superpowers/specs/2026-06-21-tiktok-listing-flow-redesign-prd.md`
- `docs/superpowers/specs/2026-06-17-product-workflow-node-state-prd.md`
- `docs/superpowers/specs/2026-06-16-product-task-action-refactor-prd.md`

## 验证入口

- 商品列表：`http://localhost:3190/products`
- 图片确认：`http://localhost:3190/products/image-review?data_source_id=<id>`
- Amazon 详情：`http://localhost:3190/products/<id>`
- TikTok 详情：`http://localhost:3190/tiktok/products/<id>`
- 商品总览：`GET /api/products/overview?data_source_id=<id>`
- E5 行为脚本：`cd backend && .venv/bin/python ../scripts/test_image_analysis_listing_e5.py`

## 常见定位

- 状态/按钮/统计问题：先看 `backend/app/api/products.py` 返回字段，再看页面消费逻辑。
- 商品详情打开后素材文件位置变化：先看 `backend/app/api/products.py` 的 GET 详情链路和 `backend/app/services/material_assets.py`，GET 路径不得调用 mutating 素材整理函数。
- 图片选择问题：手动纠偏看 `ProductImageReview.tsx`、`PUT /api/products/{id}/listing-images`、`product_images` 和 `backend/app/services/product_protection.py`；自动选图入口/重试看 `backend/app/services/giga_product_drafts.py`、`POST /api/products/{id}/auto-image-selection/retry`、`backend/app/task_planners/product_auto_image_selection.py`、`backend/app/product_tasks/actions.py`、`backend/app/product_tasks/auto_image_selection.py`。
- 自动竞品搜索问题：先看 `POST /api/products/{id}/competitor-search/retry`、`backend/app/task_planners/product_competitor_search.py`、`backend/app/product_tasks/actions.py` 的 `ProductCompetitorSearchAction`、`backend/app/services/amazon_competitor_query.py` 和 `backend/app/services/amazon_search_page.py`。
- 竞品视觉初筛问题：先看 `POST /api/products/{id}/competitor-visual-match/retry`、`backend/app/task_planners/product_competitor_visual_match.py`、`backend/app/product_tasks/actions.py` 的 `ProductCompetitorVisualMatchAction` 和 `backend/app/services/amazon_competitor_visual_match.py`；重点核对当前成功 Phase A run/step 限定、processing API bypass、旧 selected 清理和失败态不保留 current selected。
- 候选详情抓取/自动选竞品问题：先看 `backend/app/task_planners/product_competitor_candidate_capture.py`、`backend/app/task_planners/product_auto_competitor_selection.py`、`backend/app/product_tasks/actions.py` 的 `ProductCompetitorCandidateCaptureAction` / `ProductAutoCompetitorSelectionAction` 和 `backend/app/services/amazon_listing_detail.py`；E4A 只允许 fixture/configured adapter 的候选详情抓取落库和 deterministic final competitor scoring/write，不应出现真实 Amazon 访问、前端 retry 入口或真实图片分析执行。
- 旧 StyleSnap 残留问题：先确认是否还有 `/api/amazon-stylesnap`、旧 service、旧前端页面、旧 ORM 模型、旧 snapshot key 读取或 Step 10/export 兼容读取；不要恢复旧运行入口。
- 数据源分流问题：先看 `frontend/src/App.tsx`、详情页和 `backend/app/api/products.py`。

## 维护规则

只有页面/API/核心 service/table/状态语义/人工确认节点/验证入口变化时更新本文。普通 bug fix、函数内部重构、样式微调、测试补充不需要更新。
