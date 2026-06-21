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
- Amazon workflow T3：旧人工图片确认入口仍由 `PUT /api/products/{id}/listing-images` 保存主图/副图并执行 destructive reset，成功后进入 `search_competitor/pending`；该入口现在是自动选图失败/用户主动纠偏入口，保存前必须保护真实 ASIN、导出历史、Amazon 模板输出和 A+ 上传证据。
- Amazon 自动选图阶段 B：新建 Amazon 商品默认进入 `auto_select_images/pending`，完整落库后创建/复用 `product_auto_image_selection` task run 并投影 `processing`；`auto_select_images/pending` 是商品工作台正式状态桶，overview/list/frontend filter 均需显式支持，`processing` 归入 `running`。task run 创建失败落 `auto_select_images/failed`。`POST /api/products/{id}/auto-image-selection/retry` 基于 workflow 状态重试；商品列表消费后端 `retry_auto_image_selection` / `manual_adjust_images` action。自动选图候选和成功写库均 URL 优先；已有 URL 时不下载候选图、不生成 Contact Sheet、不把本地路径写成主图/副图。阶段 B 不自动启动竞品搜索。
- Amazon 自动竞品搜索 Phase A：`search_competitor/pending|failed` 可通过 `POST /api/products/{id}/competitor-search/retry` 创建/复用 `product_competitor_search` task run；reserve 投影 `search_competitor/processing`，成功把 Amazon 页面搜索候选写入 `amazon_competitor_search_candidates` 并进入 `visual_match_competitors/pending`，失败回到 `search_competitor/failed`。`amazon_competitor_search_candidates` 是自动竞品搜索主事实源。本阶段不做视觉初筛、抓详情或自动选择竞品。
- Amazon 竞品视觉初筛 Phase B：`visual_match_competitors/pending|failed` 可通过 `POST /api/products/{id}/competitor-visual-match/retry` 创建/复用 `product_competitor_visual_match` task run；`processing` 状态由 API 直接返回当前 workflow/task-center correlation，不调用 planner。reserve 会清空同商品旧视觉当前事实和 `visual_selected_for_capture`，execute 只读取最近成功 `product_competitor_search` run/step 的候选，默认用源商品主图 URL + 候选 `image_url` direct VLM 做视觉初筛，不下载候选图、不生成 Contact Sheet、不做拼接兜底；只在显式测试 fixture 路径使用 fake review。成功只给当前 run/step Top 4-6 写 `visual_selected_for_capture=1` 并进入 `capture_competitor_candidates/pending`，失败/取消/中断回到 `visual_match_competitors/failed` 且不保留 current selected candidates。本阶段不抓 Amazon 详情、不自动选最终竞品。
- Amazon 候选详情抓取 / 自动选竞品 Phase 1：只建立结构契约、task skeleton 和 fixture adapter。`capture_competitor_candidates` 增加候选详情 current fact 字段，`auto_select_competitor` 成为正式 workflow node 并增加 `final_selected/final_*` current fact 字段；`product_competitor_candidate_capture` 与 `product_auto_competitor_selection` 仅注册 task type/planner/skeleton，真实 API/前端入口尚未启用。商品 workflow 在 pending/failed 只暴露 `open_detail` 主操作和已有 `restart_competitor_search` 辅助操作；processing 可用 `open_task_center`。本阶段不暴露未实现的抓详情/自动选竞品 retry action，不访问真实 Amazon、不写候选详情、不写最终 `competitor_asin`。候选详情 adapter 默认未配置并抛 `adapter_not_configured`，fixture adapter 只用于测试 HTML。
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
- 候选详情抓取/自动选竞品 Phase 1：`capture_competitor_candidates/pending|failed` 与 `auto_select_competitor/pending|failed` 仅用 `open_detail` / `restart_competitor_search` 表示安全用户动作；`processing` 用 `open_task_center` 定位已注册 task correlation。真实 API 入口、真实抓详情、最终 ASIN 写入和前端 retry 按钮尚未启用。
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
- `docs/superpowers/specs/2026-06-17-product-workflow-node-state-prd.md`
- `docs/superpowers/specs/2026-06-16-product-task-action-refactor-prd.md`

## 验证入口

- 商品列表：`http://localhost:3190/products`
- 图片确认：`http://localhost:3190/products/image-review?data_source_id=<id>`
- Amazon 详情：`http://localhost:3190/products/<id>`
- TikTok 详情：`http://localhost:3190/tiktok/products/<id>`
- 商品总览：`GET /api/products/overview?data_source_id=<id>`

## 常见定位

- 状态/按钮/统计问题：先看 `backend/app/api/products.py` 返回字段，再看页面消费逻辑。
- 商品详情打开后素材文件位置变化：先看 `backend/app/api/products.py` 的 GET 详情链路和 `backend/app/services/material_assets.py`，GET 路径不得调用 mutating 素材整理函数。
- 图片选择问题：手动纠偏看 `ProductImageReview.tsx`、`PUT /api/products/{id}/listing-images`、`product_images` 和 `backend/app/services/product_protection.py`；自动选图入口/重试看 `backend/app/services/giga_product_drafts.py`、`POST /api/products/{id}/auto-image-selection/retry`、`backend/app/task_planners/product_auto_image_selection.py`、`backend/app/product_tasks/actions.py`、`backend/app/product_tasks/auto_image_selection.py`。
- 自动竞品搜索问题：先看 `POST /api/products/{id}/competitor-search/retry`、`backend/app/task_planners/product_competitor_search.py`、`backend/app/product_tasks/actions.py` 的 `ProductCompetitorSearchAction`、`backend/app/services/amazon_competitor_query.py` 和 `backend/app/services/amazon_search_page.py`。
- 竞品视觉初筛问题：先看 `POST /api/products/{id}/competitor-visual-match/retry`、`backend/app/task_planners/product_competitor_visual_match.py`、`backend/app/product_tasks/actions.py` 的 `ProductCompetitorVisualMatchAction` 和 `backend/app/services/amazon_competitor_visual_match.py`；重点核对当前成功 Phase A run/step 限定、processing API bypass、旧 selected 清理和失败态不保留 current selected。
- 候选详情抓取/自动选竞品问题：先看 `backend/app/task_planners/product_competitor_candidate_capture.py`、`backend/app/task_planners/product_auto_competitor_selection.py`、`backend/app/product_tasks/actions.py` 的两个 skeleton action 和 `backend/app/services/amazon_listing_detail.py`；Phase 1 默认不应出现真实 Amazon 访问、候选详情落库或 `competitor_asin` 写入。
- 旧 StyleSnap 残留问题：先确认是否还有 `/api/amazon-stylesnap`、旧 service、旧前端页面、旧 ORM 模型、旧 snapshot key 读取或 Step 10/export 兼容读取；不要恢复旧运行入口。
- 数据源分流问题：先看 `frontend/src/App.tsx`、详情页和 `backend/app/api/products.py`。

## 维护规则

只有页面/API/核心 service/table/状态语义/人工确认节点/验证入口变化时更新本文。普通 bug fix、函数内部重构、样式微调、测试补充不需要更新。
