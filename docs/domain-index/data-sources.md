# Domain Index: Data Sources And GIGA

## 范围

- 数据源配置、店铺/平台/站点口径。
- GIGA 拉品、商品池、库存同步、价格同步。
- TikTok/Amazon 数据源差异。

## 当前口径

- 数据源代表店铺/账号/平台/站点；商品列表按数据源过滤。
- Amazon 和 TikTok 链路强隔离；详情页、状态和操作不能混用。
- GIGA 拉品使用新任务框架。
- 拉品阶段只保存图片 URL 候选，不全量下载图片。
- 拉品流程先全量同步 SKU/detail/inventory/price，再统一做 item/group 聚合。
- Amazon 库存看总库存；TikTok 看每个仓库库存。

## 关键入口

- 数据源页面：`frontend/src/pages/ProductDataSourceList.tsx`
- 库存同步页面：`frontend/src/pages/InventorySyncList.tsx`
- 数据源 API：`backend/app/api/data_sources.py`
- GIGA API：`backend/app/api/giga.py`
- TikTok API：`backend/app/api/tiktok.py`
- GIGA OpenAPI client：`backend/app/services/giga_openapi.py`
- GIGA 拉品：`backend/app/task_planners/giga_pull.py`, `backend/app/task_runtime/giga_pull_workers.py`
- GIGA 库存/价格：`backend/app/task_planners/giga_dynamic_sync.py`, `backend/app/task_runtime/giga_dynamic_sync_workers.py`
- 库存/价格服务：`backend/app/services/giga_inventory_sync.py`, `backend/app/services/giga_price_sync.py`
- 表：`product_data_sources`, `giga_sync_batches`, `giga_raw_sku_details`, `giga_items`, `giga_skus`, `giga_groups`, `giga_product_images`, `giga_prices`, `giga_price_alerts`, `giga_inventory`, `giga_inventory_alerts`

## 关键流程

- 数据源配置：页面 -> `backend/app/api/data_sources.py` -> `product_data_sources`。
- GIGA 拉品：planner -> worker -> SKU/detail/inventory/price -> item/group 聚合。
- 库存/价格同步：planner/worker -> GIGA service -> 库存/价格表。
- 平台差异：商品链路根据数据源平台进入 Amazon 或 TikTok 路径。

## 相关文档

- `docs/giga-buyer-openapi-reference.md`
- `docs/giga-inventory-sync.md`
- `docs/configuration.md`
- `docs/item-workbench-redesign-plan.md`
- `docs/superpowers/specs/2026-06-13-task-runtime-giga-pull-design.md`

## 验证入口

- 数据源页面：`http://localhost:3190/data-sources`
- 库存同步页面：`http://localhost:3190/inventory-sync`
- 任务中心：`http://localhost:3190/task-runs`
- GIGA 商品池：`GET /api/giga/items?data_source_id=<id>`
- GIGA SKU：`GET /api/giga/skus?data_source_id=<id>`
- GIGA 库存：`GET /api/giga/inventory?site=US&page=1&page_size=50`

## 常见定位

- 数据源过滤问题：先看 `data_source_id` 在页面/API/DB 的传递。
- 拉品任务问题：先看 `giga_pull.py`、`giga_pull_workers.py` 和任务中心事件。
- 库存/价格同步问题：先看 `giga_dynamic_sync` planner/worker 和对应 service。
- GIGA API 问题：先看 `backend/app/services/giga_openapi.py`。

## 维护规则

只有页面/API/核心 service/action/table/平台口径/验证入口变化时更新本文。普通 bug fix、函数内部重构、样式微调、测试补充不需要更新。
