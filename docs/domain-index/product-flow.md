# Domain Index: Product Flow

## 范围

- 商品列表、商品详情、图片选择、竞品选择、商品状态流转。
- Amazon/TikTok 商品详情页分流。
- 商品进入导出或平台铺货前的人工确认节点。

## 当前口径

- 商品列表可以按数据源/店铺过滤。
- Amazon 与 TikTok 商品详情页应分流；详情页状态、操作、类目和导出链路不能混用。
- TikTok 有强类目约束；Amazon 当前以模板/导出链路为主。
- 图片、竞品、类目、ASIN、导出等人工确认节点不能自动推进。
- 前端不应重新实现后端业务规则。
- `GET /api/products/{id}` 商品详情必须是只读接口；素材目录只能扫描汇总，不能移动、创建、删除、重命名或改写用户素材文件。
- 商品状态只表达业务节点和业务结果，不表达任务执行细节；Amazon 主流程最终 PRD 以 `docs/superpowers/specs/2026-06-18-amazon-product-workflow-prd.md` 为准。
- Amazon workflow T1 已进入结构层：`products.workflow_node/workflow_status/workflow_error/workflow_updated_at` 和集中枚举常量定义在后端模型/状态常量中；后续投影和写入统一入口仍按 PRD 分阶段推进。
- Amazon workflow T2 的 Product Workflow Service 位于 `backend/app/product_tasks/workflow.py`：集中提供 `set_product_workflow()`、`build_product_workflow()` 和 node/action 映射；商品列表/详情 workflow 投影应同源调用该 service。
- StyleSnap / 搜索竞品插件方案是长期合理方向，但当前 on hold；决策记录见 `docs/superpowers/specs/2026-06-17-stylesnap-client-extension-decision.md`。
- 已修 P0：ProductTaskAction reserve 后的图片分析/Listing 入队态不能再被旧 pipeline `is_running(product.id)` 误判为中断。后续结构治理应把商品主状态从 task queued/running 语义收敛为业务节点四态。

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

- `docs/main-flow-user-path.md`
- `docs/main-flow-qa-checklist.md`
- `docs/item-workbench-redesign-plan.md`
- `docs/documentation-rewrite-brief.md`
- `docs/superpowers/specs/2026-06-18-amazon-product-workflow-prd.md`
- `docs/superpowers/specs/2026-06-17-product-workflow-node-state-prd.md`
- `docs/superpowers/specs/2026-06-17-stylesnap-client-extension-decision.md`
- `docs/superpowers/specs/2026-06-16-product-task-action-refactor-prd.md`

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
- 图片选择问题：先看 `ProductImageReview.tsx` 和 `product_images`。
- 竞品信息问题：先看 `backend/app/api/amazon_stylesnap.py` 和 `backend/app/services/amazon_stylesnap_search.py`。
- 数据源分流问题：先看 `frontend/src/App.tsx`、详情页和 `backend/app/api/products.py`。

## 维护规则

只有页面/API/核心 service/table/状态语义/人工确认节点/验证入口变化时更新本文。普通 bug fix、函数内部重构、样式微调、测试补充不需要更新。
