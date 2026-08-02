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
- 指定 SKU 测试入口先由 GIGA list API 确定要处理的 SKU，再由素材准备任务使用登录态浏览器在 GIGA 搜索页按 Item Code 精确映射数字 `product_id`，详情页二次校验后下载素材；搜索卡片和详情 Item Code 均轮询到真实 DOM 就绪后再判定，不能用固定等待时间把慢加载误报成无匹配；OpenAPI 的 SKU 标识不能直接冒充网页 `product_id`。
- `pipeline_target=aplus_done` 和 `test_session_key` 从 GIGA pull planner/worker 传播到 Product 和所有后续素材/商品任务，支持按单次会话审计与精确清理。To B、Information 为必需素材包，Retail Ready 可选；Downloads 原 ZIP 只复制不移动。
- Amazon 库存看总库存；TikTok 看每个仓库库存。

## 关键入口

- 数据源页面：`frontend/src/pages/ProductDataSourceList.tsx`
- 库存同步页面：`frontend/src/pages/InventorySyncList.tsx`
- 数据源 API：`backend/app/api/data_sources.py`
- GIGA API：`backend/app/api/giga.py`
- TikTok API：`backend/app/api/tiktok.py`
- GIGA OpenAPI client：`backend/app/services/giga_openapi.py`
- GIGA 拉品：`backend/app/task_planners/giga_pull.py`, `backend/app/task_runtime/giga_pull_workers.py`；商品工作台可提交指定数量或全部新增 SKU，同步上限在 worker 过滤历史 SKU 后生效。
- GIGA 素材准备：`backend/app/services/product_material_prepare.py`, `backend/app/task_planners/product_material_prepare.py`, `backend/app/pipeline/step1_collect.py`, `product_material_assets`
- GIGA 库存/价格：`backend/app/task_planners/giga_dynamic_sync.py`, `backend/app/task_runtime/giga_dynamic_sync_workers.py`
- 库存/价格服务：`backend/app/services/giga_inventory_sync.py`, `backend/app/services/giga_price_sync.py`
- 表：`product_data_sources`, `giga_sync_batches`, `giga_raw_sku_details`, `giga_items`, `giga_skus`, `giga_groups`, `giga_product_images`, `giga_prices`, `giga_price_alerts`, `giga_inventory`, `giga_inventory_alerts`

## 关键流程

- 数据源配置：页面 -> `backend/app/api/data_sources.py` -> `product_data_sources`。
- GIGA 拉品：planner -> worker -> SKU/detail/inventory/price -> item/group 聚合 -> Product 草稿；新建或 `aplus_done` 商品再进入 `product_material_prepare`，完成网页 ID 映射、ZIP 下载/解压、素材事实登记和 Contact Sheet 前置准备。
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
- 单 SKU A+目标拉品：`POST /api/task-runs/giga-pull`，请求携带 `data_source_ids`、`sku_codes`、`pipeline_target=aplus_done`、`refresh_existing=true`、`test_session_key`
- GIGA 库存：`GET /api/giga/inventory?site=US&page=1&page_size=50`

## 常见定位

- 数据源过滤问题：先看 `data_source_id` 在页面/API/DB 的传递。
- 拉品任务问题：先看 `giga_pull.py`、`giga_pull_workers.py` 和任务中心事件。
- 库存/价格同步问题：先看 `giga_dynamic_sync` planner/worker 和对应 service。
- GIGA API 问题：先看 `backend/app/services/giga_openapi.py`。
- SKU 到网页 product_id 或素材包问题：先看 `backend/app/services/product_material_prepare.py` 的搜索页精确匹配、详情页二次校验和 `step1_collect.py` 的显式下载选项类型。

## 维护规则

只有页面/API/核心 service/action/table/平台口径/验证入口变化时更新本文。普通 bug fix、函数内部重构、样式微调、测试补充不需要更新。
