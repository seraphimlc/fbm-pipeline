# GIGA 库存与价格同步说明

本文记录 GIGA Open API 库存与价格同步模块的当前约定，供后续 Codex/开发者冷启动、排查和扩展使用。

## 目标

- 每天从 GIGA Open API 拉取 SKU 库存和价格。
- 库存和价格事实只落数据库，不依赖 JSON、XLSX、cache 或 stdout。
- 所有动态事实必须带 `batch_id + site + sku_code`，不同站点、不同批次互不覆盖。
- 页面按 SKU 分页展示最新库存。
- Amazon 库存更新模板和普通 Amazon 导入表格数量覆盖，都读取最新 GIGA 库存快照。
- 对 SKU 有货/无货切换生成告警。
- 对 SKU 有效成交价变化生成告警。

## Open API

库存接口：

```http
POST https://openapi.gigab2b.com/b2b-overseas-api/v1/buyer/inventory/quantity/v2
```

请求体：

```json
{
  "skus": ["W3662P363291"]
}
```

价格接口：

```http
POST https://openapi.gigab2b.com/b2b-overseas-api/v1/buyer/product/price/v1
```

请求体同样使用 SKU 列表：

```json
{
  "skus": ["W3662P363291"]
}
```

价格接口约束：

- 单次 `skus` 最多 200 个。
- 限流为 10 秒内 10 次。
- 仅支持 Buyer 加入收藏夹内或者有囤货库存的产品。

认证头沿用 GIGA Open API 签名：

- `Content-Type: application/json`
- `client-id`
- `timestamp`
- `nonce`
- `sign`

店铺 API 地址、AK/SK、站点和履约方式只允许从「数据源维护」/`product_data_sources` 表读取。全局 `backend/.env` 只保留非店铺维度的运行参数：

```text
GIGA_SYNC_PAGE_SIZE=200
```

## 库存字段

GIGA 返回两类库存：

- `sellerInventoryInfo`
  - `sellerAvailableInventory`: 平台/Seller 可采购库存。
  - `sellerInventoryDistribution`: Seller 分仓库存。当前 US 返回可能为空数组 `[]`。
- `buyerInventoryInfo`
  - `totalBuyerAvailableInventory`: Buyer 自有可用库存总数。
  - `buyerInventoryDistribution`: Buyer 分仓库存。当前 US 返回可能为空数组 `[]`。

当前系统统一计算 `stock_qty`：

1. 优先使用大于 0 的 `sellerAvailableInventory`。
2. 若 seller 没有可用值，再使用大于 0 的 `totalBuyerAvailableInventory`。
3. 若两者都没有正数，保留 0 或可解析到的非正数。

`availability_status`：

- `in_stock`: `stock_qty > 0`
- `out_of_stock`: `stock_qty <= 0`

## 数据库表

### 动态同步日志

当前复用 `giga_sync_batches` 记录同步日志：

- `batch_id`
- `site`
- `task_id`
- `current_category = inventory_snapshot` 表示库存日快照。
- `current_category = price_snapshot` 表示价格日快照。
- `status`
- `sku_count`
- `inventory_count`
- `price_count`
- `error_message`
- `started_at`
- `finished_at`

说明：

- 商品同步 batch、库存同步 batch 和价格同步 batch 都在 `giga_sync_batches` 中。
- 库存同步 batch 通过 `current_category = inventory_snapshot` 标识。
- 价格同步 batch 通过 `current_category = price_snapshot` 标识。
- 后续如需进一步解耦，建议新增专用日志表 `giga_inventory_sync_logs` / `giga_price_sync_logs`，但当前实现不需要临时文件即可追踪日志。

### 库存事实表

`giga_inventory` 是库存真源：

- 复合唯一键：`batch_id + site + sku_code`
- 关键字段：
  - `batch_id`
  - `site`
  - `sku_code`
  - `task_id`
  - `stock_qty`
  - `seller_available_inventory`
  - `total_buyer_available_inventory`
  - `seller_inventory_distribution`
  - `buyer_inventory_distribution`
  - `next_arrival_inventory`
  - `availability_status`
  - `source_platform = GIGA`
  - `pulled_at`

### 价格事实表

`giga_prices` 是价格真源：

- 复合唯一键：`batch_id + site + sku_code`
- 关键字段：
  - `batch_id`
  - `site`
  - `sku_code`
  - `task_id`
  - `currency`
  - `price`
  - `exclusive_price`
  - `discounted_price`
  - `effective_price`
  - `shipping_fee`
  - `shipping_fee_min`
  - `shipping_fee_max`
  - `estimated_shipping_fee`
  - `map_price`
  - `srp_price`
  - `future_map_price`
  - `exclusive_price_expire_time`
  - `promotion_from`
  - `promotion_to`
  - `purchase_limit`
  - `sku_available`
  - `seller_info_json`
  - `spot_price_json`
  - `rebates_price_json`
  - `margin_price_json`
  - `future_price_json`
  - `raw_price_json`
  - `source_platform = GIGA`
  - `pulled_at`

`effective_price` 是告警和下游默认使用的有效成交价：

1. `exclusivePrice` 有值时优先使用专享价。
2. 否则 `discountedPrice` 有值时使用活动折扣价。
3. 否则使用 `price` 原价。

商品池 SKU 展开时，价格读取最新有价格数据的 done batch；不会因为商品详情 batch 较老而展示旧价格。

### 库存告警表

`giga_inventory_alerts` 记录相邻库存快照的有货/无货切换：

- `change_type = out_of_stock`: 有货变无货。
- `change_type = restocked`: 无货变有货。
- 记录上一批次、上一库存、当前库存、SKU、item 和提示文案。

告警只比较最新库存 batch 和上一个有库存数据的 done batch。

### 价格告警表

`giga_price_alerts` 记录相邻价格快照的有效成交价变化：

- `change_type = price_changed`
- 记录上一批次、上一有效价、当前有效价、原价、专享价、活动价、运费、SKU、item 和提示文案。

告警只比较最新价格 batch 和上一个有价格数据的 done batch。同一天重跑同一个价格 batch 会先清理该 batch 原有价格告警，再按当前结果重新生成。

## 同步入口

手动同步库存：

```bash
cd /Users/liuchang/Documents/gitproject/fbm-pipeline
backend/.venv/bin/python scripts/giga_inventory_sync.py --site US --task-id manual-giga-inventory
```

手动同步价格：

```bash
cd /Users/liuchang/Documents/gitproject/fbm-pipeline
backend/.venv/bin/python scripts/giga_price_sync.py --site US --task-id manual-giga-price
```

默认 batch：

```text
YYYYMMDD-{site}-inventory
YYYYMMDD-{site}-price
```

例如：

```text
20260602-us-inventory
20260602-us-price
```

同一天重跑同一个默认 batch，会重写这一天该站点的库存或价格快照，不会覆盖其它日期或其它站点。

必须显式传 `--site US` 或 `--site JP`，未明确 site 禁止执行。

## 每日同步

部署时建议配置 cron 或 systemd timer，每天执行一次库存和价格：

```cron
15 6 * * * cd /Users/liuchang/Documents/gitproject/fbm-pipeline && backend/.venv/bin/python scripts/giga_inventory_sync.py --site US --task-id daily-giga-inventory >> logs/giga_inventory_sync.log 2>&1
25 6 * * * cd /Users/liuchang/Documents/gitproject/fbm-pipeline && backend/.venv/bin/python scripts/giga_price_sync.py --site US --task-id daily-giga-price >> logs/giga_price_sync.log 2>&1
```

cron 只负责触发；库存事实、价格事实、同步结果和告警都落数据库。

## 页面

前端页面：

```text
http://localhost:3190/inventory-sync
```

页面行为：

- 展示最新 GIGA 库存快照。
- 按 SKU 分页，不展示 batch ID。
- 支持 SKU 搜索和有货/无货筛选。
- 展示 seller/buyer 库存、分仓数量和同步时间。
- “同步库存”按钮会触发 `POST /api/giga/inventory/sync`。
- “同步价格”按钮会触发 `POST /api/giga/price/sync`，并在成功提示中显示变价告警数量。

## API

同步库存：

```http
POST /api/giga/inventory/sync
```

同步价格：

```http
POST /api/giga/price/sync
```

价格请求示例：

```json
{
  "batch_id": "20260602-us-price",
  "site": "US",
  "task_id": "manual-giga-price"
}
```

库存请求示例：

```json
{
  "batch_id": "20260602-us-inventory",
  "site": "US",
  "task_id": "manual-giga-inventory"
}
```

查看最新库存：

```http
GET /api/giga/inventory?site=US&page=1&page_size=50
```

查看库存切换告警：

```http
GET /api/giga/inventory/alerts?site=US&batch_id=20260602-us-inventory
```

查看价格告警：

```http
GET /api/giga/price/alerts?site=US&batch_id=20260602-us-price
```

## 导出口径

库存导出必须读取最新 `giga_inventory.stock_qty`：

- `POST /api/products/catalog/inventory-template/export`
- `POST /api/products/catalog/export` 中的数量覆盖

不再依赖 `catalog_products.stock` 作为导出库存来源。

库存口径只在导出执行时影响 Quantity，不阻断商品拉取、商品处理、选竞品、生成 Listing 或进入待导出。若最新库存为 0，Amazon 首次导入表继续导出并写入 Quantity `0`；若最新库存快照缺少目标 SKU 或出现负库存，任务 `result_json.rows` 和导出报告应记录跳过/失败原因。这不是永久运营结论，后续补货后可由用户人工新建导出任务。

如果选中商品的 SKU 不在最新 GIGA 库存快照中：

- 库存更新模板导出：跳过该 SKU，并写入导出报告。
- 普通 Amazon 导入表格导出：停止该商品导出，并写入导出报告。

价格事实当前用于运营复核、价格变化告警和后续定价策略输入，不自动写入 Amazon 首次导入表或 PriceAndQuantity 模板。是否把 `effective_price`、人工售价、利润公式价或其它价格写入 Amazon，需要单独确认价格策略；未确认前，系统只把价格变化作为告警和复核信息。

PriceAndQuantity 当前按“库存更新模板”使用：只对已有真实 ASIN 的商品按 SKU 写入 Quantity，价格列留空，不更新 Amazon 价格。已有真实 ASIN 的商品补货或库存变化应优先走该库存更新模板；没有真实 ASIN 的商品仍走首次导入表导出。

## 当前已验证数据

2026-06-02 手动同步 US：

- 库存 batch_id: `20260602-us-inventory`
- SKU: `219`
- 成功: `219`
- 失败: `0`
- 有货: `202`
- 无货: `17`
- 告警: `1`
- 价格 batch_id: `20260602-us-price`
- 价格成功: `219`
- 价格失败: `0`
- 价格告警: `1`

告警样例：

- `W808P212699` / item `W808P354928`
- `out_of_stock`
- 库存 `1 -> 0`
- `price_changed`
- 有效价 `26.1 -> 29.0`

## 验证命令

```bash
cd backend && .venv/bin/python -m compileall -q app
make test-project-rules
cd frontend && npm run build
curl -s 'http://localhost:8190/api/giga/inventory?site=US&page=1&page_size=3'
backend/.venv/bin/python scripts/giga_price_sync.py --site US --task-id manual-giga-price
curl -s 'http://localhost:8190/api/giga/price/alerts?site=US&page=1&page_size=3'
```
