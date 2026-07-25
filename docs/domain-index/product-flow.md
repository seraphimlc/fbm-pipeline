# Domain Index: Product Flow

## 范围

- 商品列表、商品详情、图片选择、竞品选择、商品状态流转。
- Amazon/TikTok 商品详情页分流。
- 商品进入导出或平台铺货前的人工确认节点。

## 当前口径

- Amazon 与 TikTok 商品详情页应分流；详情页状态、操作、类目和导出链路不能混用。
- `GET /api/products/{id}` 商品详情必须是只读接口；素材目录只能扫描汇总，不能移动、创建、删除、重命名或改写用户素材文件。
- 商品状态只表达业务节点和业务结果，任务执行细节由 task runtime 表达；后端统一入口在 `backend/app/product_tasks/workflow.py`，产品合同以当前 Amazon workflow PRD 为准。
- 新建 Amazon 商品默认仍走人工选图；自动选图阶段 A 不改默认入口。人工图片确认后进入 `search_competitor/pending`，不得自动启动竞品搜索。
- 竞品搜索/抓取保留本机浏览器依赖；搜索成功进入 `select_competitor/pending`，权限或 token 问题进入 `get_stylesnap_token/pending`，该链路不写 task run。
- 选择竞品后进入 `capture_competitor_detail/processing`，详情成功进入 `image_analysis/processing`；真实 ASIN、人工确认、导出历史或模板输出不得被重选自动覆盖，抓取链路不写 task run。
- 前端只消费后端稳定字段，不重新实现业务状态、保护边界或推进规则。

## 关键入口

- 商品列表：`frontend/src/pages/ProductList.tsx`
- Amazon 详情：`frontend/src/pages/ProductDetail.tsx`
- TikTok 详情：`frontend/src/pages/TikTokProductDetail.tsx`
- 图片确认：`frontend/src/pages/ProductImageReview.tsx`
- 竞品确认：`frontend/src/pages/ProductCompetitorReview.tsx`
- 新建商品：`frontend/src/pages/CreateProduct.tsx`
- 前端 API client：`frontend/src/api/index.ts`
- 商品 API：`backend/app/api/products.py`
- StyleSnap API：`backend/app/api/amazon_stylesnap.py`
- 自动选图：`backend/app/services/product_image_candidates.py`, `backend/app/services/product_image_vlm.py`, `backend/app/product_tasks/auto_image_selection.py`, `backend/app/task_planners/product_auto_image_selection.py`
- TikTok API：`backend/app/api/tiktok.py`
- pipeline：`backend/app/pipeline/engine.py`, `backend/app/pipeline/step*.py`
- 模型：`backend/app/models/models.py`
- 表：`products`, `product_data`, `product_images`, `product_aplus`, `catalog_products`

## 关键流程

- 商品列表/详情：页面 -> `frontend/src/api/index.ts` -> `backend/app/api/products.py`；详情素材摘要通过 `backend/app/services/material_assets.py` 只读扫描。
- 图片确认：`ProductImageReview.tsx` -> 商品 API -> `product_images`。
- 竞品确认：`ProductCompetitorReview.tsx` -> StyleSnap API/service。
- Amazon/TikTok 详情分流：前端路由和数据源类型共同决定详情入口。

## 相关文档

- `docs/superpowers/specs/2026-06-18-amazon-product-workflow-prd.md`
- `docs/superpowers/specs/2026-06-19-amazon-auto-image-selection-prd.md`
- `docs/superpowers/specs/2026-06-19-amazon-auto-competitor-selection-prd.md`
- `docs/superpowers/specs/2026-06-17-product-workflow-node-state-prd.md`

## 验证入口

- 商品列表：`http://localhost:3190/products`
- 图片确认：`http://localhost:3190/products/image-review?data_source_id=<id>`
- 竞品确认：`http://localhost:3190/products/competitor-review?data_source_id=<id>`
- Amazon 详情：`http://localhost:3190/products/<id>`
- TikTok 详情：`http://localhost:3190/tiktok/products/<id>`
- 商品总览：`GET /api/products/overview?data_source_id=<id>`

## 常见定位

- 状态/按钮/统计问题：先看 `backend/app/api/products.py` 返回字段，再看页面消费逻辑。
- 商品详情打开后素材文件位置变化：先看 `backend/app/api/products.py` 的 GET 详情链路和 `backend/app/services/material_assets.py`，GET 路径不得调用 mutating 素材整理函数。
- 图片选择问题：默认人工图片确认仍看 `ProductImageReview.tsx` 和 `product_images`；自动选图后端闭环先看 `backend/app/services/product_image_candidates.py`、`backend/app/services/product_image_vlm.py`、`backend/app/product_tasks/auto_image_selection.py` 和 `backend/app/product_tasks/actions.py`。
- 竞品信息问题：先看 `backend/app/api/amazon_stylesnap.py` 和 `backend/app/services/amazon_stylesnap_search.py`。
- 数据源分流问题：先看 `frontend/src/App.tsx`、详情页和 `backend/app/api/products.py`。

## 维护规则

只有页面/API/核心 service/table/状态语义/人工确认节点/验证入口变化时更新本文。普通 bug fix、函数内部重构、样式微调、测试补充不需要更新。
