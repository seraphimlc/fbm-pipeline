# GIGA Buyer Open API 速查

更新时间：2026-06-02

来源：

- 官方入口：`https://www.gigab2b.com/index.php?route=information/open_api/index&doc_id=14&api_lang=zh-cn`
- 文档数据接口：`information/open_api/getOpenApiMenus`、`information/open_api/getOpenApiDetails`

本文是项目内速查，不替代官方文档。实现前仍需以官方页面最新字段为准。

## 通用规则

### 域名

- Sandbox: `https://openapi-sandbox.gigab2b.com`
- Production: `https://openapi.gigab2b.com`

当前项目不再使用全局 `GIGA_API_BASE`。每个大健店铺的 Open API 地址在「数据源维护」中配置，并随 `data_source_id` 一起读取。

### 认证头

所有 Buyer Open API 都使用同一套公共请求头：

| Header | 必填 | 说明 |
|---|---:|---|
| `Content-Type` | 是 | `application/json` |
| `client-id` | 是 | Open API 应用的 Client ID |
| `timestamp` | 是 | 毫秒时间戳，20 分钟内有效 |
| `nonce` | 是 | 10 位随机值 |
| `sign` | 是 | 签名 |

签名规则：

1. 字符串 1：`client_id&api_path&timestamp&nonce`
2. 秘钥：`client_id&client_secret&nonce`
3. 用 HMAC-SHA256 计算字符串 1。
4. 将 hex digest 做 base64，得到 `sign`。

项目实现位置：[backend/app/services/giga_openapi.py](/Users/liuchang/Documents/gitproject/fbm-pipeline/backend/app/services/giga_openapi.py)

### 通用响应

大多数接口返回：

| 字段 | 说明 |
|---|---|
| `success` | 请求是否成功 |
| `code` | 错误码，成功通常为 `200` |
| `data` | 业务数据 |
| `requestId` | 请求唯一标识，排错时保留 |
| `msg` | 错误信息 |
| `subMsg` | 二级错误场景 |
| `recommend` | 错误诊断链接 |

### 常见约束

- 产品、价格、库存接口仅支持 Buyer 加入收藏夹或有囤货库存的产品。
- SKU 批量查询类接口通常单次最多 200 个 SKU。
- 订单号批量查询类接口通常单次最多 100 个订单号。
- 时间字段未特别说明时，官方文档多处使用 GMT-8。
- 后续所有同步结果应落数据库，不以临时 JSON/XLSX/stdout 作为真源。

## Buyer 接口总览

| doc_id | 分组 | 名称 | Method | Path | 限流 |
|---:|---|---|---|---|---|
| 5 | 产品 | 产品列表查询 | POST | `/b2b-overseas-api/v1/buyer/product/skus/v1` | 10 秒 10 次 |
| 6 | 产品 | 产品详情查询 | POST | `/b2b-overseas-api/v1/buyer/product/detailInfo/v1` | 10 秒 20 次 |
| 7 | 产品 | 产品价格查询 | POST | `/b2b-overseas-api/v1/buyer/product/price/v1` | 10 秒 10 次 |
| 8 | 发货订单 | 订单导入-一件代发 | POST | `/b2b-overseas-api/v1/buyer/order/dropShip-sync/v1` | 暂无 |
| 9 | 发货订单 | 订单导入-上门取货上传 label | POST | `/b2b-overseas-api/v1/buyer/order/pickUpSelfLabel-sync/v1` | 暂无 |
| 10 | 发货订单 | 订单导入-上门取货 GIGA 代买 Label | POST | `/b2b-overseas-api/v1/buyer/order/pickUp-sync/v1` | 暂无 |
| 11 | 发货订单 | 订单状态查询 | POST | `/b2b-overseas-api/v1/buyer/order/status/v1` | 10 秒 20 次 |
| 19 | 库存 | 库存查询 | POST | `/b2b-overseas-api/v1/buyer/inventory/quantity/v2` | 10 秒 10 次 |
| 12 | 物流 | 发货物流查询 | POST | `/b2b-overseas-api/v1/buyer/order/track-no/v1` | 10 秒 20 次 |
| 13 | 仓库 | 仓库地址查询 | POST | `/b2b-overseas-api/v1/buyer/warehouse/query-address/v1` | 10 秒 20 次 |

## 产品接口

### 产品列表查询

Path: `/b2b-overseas-api/v1/buyer/product/skus/v1`

用途：

- 获取 Buyer 可访问的商品池 SKU / item code。
- 当前项目拉取 GIGA 商品池的第一步。
- 官方支持按更新时间、收藏时间等过滤，适合后续做增量拉品。

请求体关键字段：

| 字段 | 必填 | 说明 |
|---|---:|---|
| `page` | 否 | 页码，不小于 1 |
| `pageSize` | 否 | 100 到 10000，默认 5000 |
| `sort` | 否 | 更新时间或首次发布时间排序 |
| `firstArrivalDate` | 否 | 首次到库时间，`yyyy-MM-dd` |
| `lastUpdatedAfter` | 否 | 最后更新时间之后的数据 |
| `queryTimeType` | 否 | `1` 最后更新时间，`2` 收藏时间 |
| `startTime` / `endTime` | 否 | 时间范围，需和 `queryTimeType` 配合 |

返回重点：

- `data.pageInfo`
- `data.records`
- records 中包含 SKU、产品名称、更新时间等商品池入口信息。

项目建议：

- 商品池主同步不应重复导入已存在 item/SKU。
- 后续增量同步优先用 `queryTimeType=2` 或更新时间范围，而不是全量重复拉。

### 产品详情查询

Path: `/b2b-overseas-api/v1/buyer/product/detailInfo/v1`

用途：

- 通过 SKU 或产品名称查询商品详情。
- 当前项目用于 item 维度聚合、父子 SKU、标题、图片、属性、变体属性、描述等。

请求体关键字段：

| 字段 | 必填 | 说明 |
|---|---:|---|
| `skus` | 条件必填 | SKU 列表，最多 200；和 `productNames` 必须且只能二选一 |
| `productNames` | 条件必填 | 产品名称列表，最多 200；和 `skus` 必须且只能二选一 |

返回重点：

- `sku`: 平台产品编码 item code；组合产品时也是 item code。
- `mpn`
- 包装尺寸：`weightUnit`、`lengthUnit`、`weight`、`length`、`width`、`height`
- 标题、图片、描述、属性、组合/变体关系、可购买状态等。

项目建议：

- 后续 listing、图片、A+ 应以 item 为单位处理，一组 SKU 只生成一套。
- Amazon 导入表格仍要保留子 SKU 维度，父子关系和变体属性必须完整保存。

### 产品价格查询

Path: `/b2b-overseas-api/v1/buyer/product/price/v1`

用途：

- 每天同步价格快照。
- 检测有效成交价变化，生成价格告警。
- 商品池 SKU 展开展示最新价格。

请求体关键字段：

| 字段 | 必填 | 说明 |
|---|---:|---|
| `skus` | 是 | SKU 列表，最多 200 |

返回重点：

- `currency`
- `price`: 原价
- `exclusivePrice`: 专享价，有值时优先作为成交价
- `discountedPrice`: 活动折扣价，无专享价但有活动价时作为成交价
- `shippingFee`
- `shippingFeeRange.minAmount/maxAmount`
- `mapPrice`、`srpPrice`、`futureMapPrice`
- `sellerInfo`
- `spotPrice`、`rebatesPrice`、`marginPrice`、`futurePrice`
- `skuAvailable`

项目口径：

- `effective_price = exclusivePrice -> discountedPrice -> price`
- 价格事实表：[giga_prices](/Users/liuchang/Documents/gitproject/fbm-pipeline/backend/app/models/models.py:462)
- 价格告警表：[giga_price_alerts](/Users/liuchang/Documents/gitproject/fbm-pipeline/backend/app/models/models.py:500)
- 同步脚本：[scripts/giga_price_sync.py](/Users/liuchang/Documents/gitproject/fbm-pipeline/scripts/giga_price_sync.py)

## 库存接口

### 库存查询

Path: `/b2b-overseas-api/v1/buyer/inventory/quantity/v2`

用途：

- 每天同步 SKU 库存快照。
- 检测有货/无货切换，生成库存告警。
- Amazon 库存更新模板和普通导入表数量覆盖读取最新库存。

请求体关键字段：

| 字段 | 必填 | 说明 |
|---|---:|---|
| `skus` | 是 | item code / SKU，单次最多 200 |

返回重点：

- `buyerInventoryInfo`: Buyer 自有库存信息。
- `sellerInventoryInfo`: 平台/Seller 可售库存信息。
- 美国和欧洲上门取货 Buyer 支持仓库维度库存。
- 接口支持促销活动可购库存、仓租等字段。

项目口径：

- `stock_qty` 优先取大于 0 的 `sellerAvailableInventory`，否则取大于 0 的 `totalBuyerAvailableInventory`，否则为 0 或可解析非正数。
- 库存事实表：[giga_inventory](/Users/liuchang/Documents/gitproject/fbm-pipeline/backend/app/models/models.py:534)
- 库存告警表：[giga_inventory_alerts](/Users/liuchang/Documents/gitproject/fbm-pipeline/backend/app/models/models.py:553)
- 同步脚本：[scripts/giga_inventory_sync.py](/Users/liuchang/Documents/gitproject/fbm-pipeline/scripts/giga_inventory_sync.py)

## 发货订单接口

订单接口目前还没有在项目中落地。后续实现时应先设计订单日志表、请求幂等表和错误重试表，避免重复导入订单。

### 订单导入-一件代发

Path: `/b2b-overseas-api/v1/buyer/order/dropShip-sync/v1`

用途：

- 将一件代发类型的发货订单同步到 B2B 平台。
- 加拿大国别 Buyer 暂不可用。

请求体关键字段：

| 字段 | 必填 | 说明 |
|---|---:|---|
| `orderDate` | 是 | 订单日期 |
| `orderNo` | 是 | 发货单号 |
| `shipName` / `shipPhone` | 是 | 收货人姓名、电话 |
| `shipAddress1` / `shipCity` / `shipCountry` / `shipZipCode` | 是 | 收货地址 |
| `shipState` | 条件必填 | 德国和英国站非必填，其他国别必填 |
| `hasOtherLabel` | 否 | 是否有除品牌标和 Packing Slip 外的纸箱贴标要求 |
| `shippedDate` | 否 | 日本站指定送货日期 |
| `orderFrom` | 否 | 发货方/店铺名，美国站支持 |
| `salesChannel` | 否 | Wayfair、Amazon、Walmart、eBay、HomeDepot、Overstock 等 |
| `orderLines` | 是 | 明细列表 |

`orderLines` 关键字段：

- `sku`
- `qty`
- `itemPrice`
- `productName`
- `amazonOrderItemId`
- `itemTax`
- `itemUnitDiscount`

项目建议：

- `orderNo` 必须作为幂等键。
- Amazon 订单需要保留 `amazonOrderItemId`，可能影响亚马逊渠道特惠运费判断。

### 订单导入-上门取货上传 label

Path: `/b2b-overseas-api/v1/buyer/order/pickUpSelfLabel-sync/v1`

用途：

- Buyer 自付运费且已有 label 文件时导入订单。
- 仅支持美国 Buyer。

请求体关键字段：

| 字段 | 必填 | 说明 |
|---|---:|---|
| `orderNo` / `orderDate` | 是 | 发货单号、订单时间 |
| `shipMethod` | 是 | FedEx、UPS、GOFO、OnTrac、Amazon Shipping、USPS、LTL、ATS 等 |
| `shipServiceLevel` | 条件必填 | LTL 订单必填 |
| `salesChannel` | 是 | Amazon、Wayfair、Walmart、Overstock、Home Depot、Lowe's、Other |
| `bolFile` | 条件必填 | LTL 且非 Amazon 时必填，base64 |
| `packingSlip` | 否 | Home Depot 装箱文件，base64 |
| `orderLines` | 是 | 明细列表 |

`orderLines` 关键字段：

- `sku`
- `qty`
- `warehouseCode`
- `currencyCode`
- `labelFile`: 普通快递订单必填，base64，数量应和 SKU 数一致。
- `brandLabelName`

### 订单导入-上门取货 GIGA 代买 Label

Path: `/b2b-overseas-api/v1/buyer/order/pickUp-sync/v1`

用途：

- Buyer 自付运费，但需要 GIGA 代买发货 label。
- 仅支持美国 Buyer。

请求体关键字段：

| 字段 | 必填 | 说明 |
|---|---:|---|
| `orderDate` / `orderNo` | 是 | 订单日期、发货单号 |
| 收货人和地址字段 | 是 | `shipName`、`shipPhone`、`shipAddress1`、`shipCity`、`shipCountry`、`shipState`、`shipZipCode` |
| `shipMethod` | 是 | 只能是 FedEx 或 UPS |
| `shipServiceLevel` | 是 | 按 `shipMethod` 限定服务枚举 |
| `salesChannel` | 是 | Wayfair、Walmart、Home Depot、Overstock、Target、Macys、Amazon、Chewy、Other |
| `orderLines` | 是 | 明细列表 |
| `packingSlip` | 否 | Home Depot 装箱文件 |
| `payAccountNumber` / `payAccountPostalCode` | 否 | 承运商计费账户信息 |

项目建议：

- 如果后续做 Amazon FBM 发货，应优先明确我们是走一件代发、上传 label，还是 GIGA 代买 label。
- 不同订单导入接口字段相近但约束不同，不要混用同一 DTO 硬塞。

### 订单状态查询

Path: `/b2b-overseas-api/v1/buyer/order/status/v1`

用途：

- 按发货订单号查询 B2B 平台订单状态。

请求体关键字段：

| 字段 | 必填 | 说明 |
|---|---:|---|
| `orderNo` | 是 | 发货订单号集合 |

返回重点：

- `orderNo`
- `orderStatus`
  - `1`: Unpaid
  - `2`: Being Processed
  - `4`: On Hold
  - `16`: Canceled
  - `32`: Completed
- `canCancel`: `0` 不可取消，`1` 可取消

项目建议：

- 后续应做订单状态每日或定时同步。
- `On Hold` 和 `Canceled` 应进入运营告警。

## 物流接口

### 发货物流查询

Path: `/b2b-overseas-api/v1/buyer/order/track-no/v1`

用途：

- 查询订单发货物流，包括包裹级别运单号和物流商。
- 德国站一件代发且购买 Return Label Service 时，可能返回退货运单号。

请求体关键字段：

| 字段 | 必填 | 说明 |
|---|---:|---|
| `orderNo` | 是 | 发货订单号，单次最多 100 个 |

返回重点：

- `orderNo`
- `shipTrackInfo`
- `returnTrackInfo`

项目建议：

- 后续 Amazon/店铺回传 tracking 时，应以该接口为物流真源。
- 包裹级别 tracking 可能一单多包裹，表结构不要只存一个 tracking number。

## 仓库接口

### 仓库地址查询

Path: `/b2b-overseas-api/v1/buyer/warehouse/query-address/v1`

用途：

- 通过仓库 code 查询 GIGA B2B 仓库地址，包含供应商仓库地址。
- 仓库 code 可从库存查询接口获得。

请求体关键字段：

| 字段 | 必填 | 说明 |
|---|---:|---|
| `warehouseCodes` | 是 | B2B 平台仓库 code，单次最多 200 个 |

返回重点：

- `warehouseCode`
- `address`
- `country`
- `state`
- `city`
- `zipCode`

项目建议：

- 如果库存同步里出现仓库分布，应补一张仓库维表，把 `warehouseCode` 映射为可读地址。

## PII 加解密规则

官方 doc_id=21 是发货订单个人身份信息 PII 加解密规则。

关键点：

- PII 包括姓名、邮箱、电话、邮编、收货地址等。
- 发货后 30 天内必须删除订单 PII。
- 超过订单发货时间 30 天后，订单详情查询也不会提供 PII。
- 加解密算法：`AES/CBC/PKCS5Padding`
- key: Open API `Client ID` 前 16 位。
- iv: Open API `Client ID` 前 16 位，不足补 0。

项目要求：

- 后续实现订单接口时，不要长期持久化明文 PII。
- 如果必须落库，应有过期清理任务和脱敏展示。
- 日志、错误信息、导出文件中不得输出完整收件人 PII。

## 当前项目已覆盖

已实现：

- 产品列表、详情、价格、库存同步。
- item 维度商品池。
- 每日库存快照和库存告警。
- 每日价格快照和价格变动告警。
- Buyer Open API SDK wrapper，统一放在 `GigaOpenApiClient`。

SDK wrapper 对照：

| 官方接口 | Client 方法 | 状态 |
|---|---|---|
| 产品列表查询 | `fetch_sku_page` / `fetch_sku_records` | 已接入商品池同步 |
| 产品详情查询 | `fetch_details` / `fetch_details_by_product_names` | 已接入商品池同步 |
| 产品价格查询 | `fetch_prices` | 已接入价格同步和商品池同步 |
| 库存查询 | `fetch_inventory` | 已接入库存同步和商品池同步 |
| 订单导入-一件代发 | `submit_dropship_order` | SDK 已放置，暂未接业务流程 |
| 订单导入-上门取货上传 label | `submit_pickup_self_label_order` | SDK 已放置，暂未接业务流程 |
| 订单导入-上门取货 GIGA 代买 Label | `submit_pickup_giga_label_order` | SDK 已放置，暂未接业务流程 |
| 订单状态查询 | `fetch_order_status` | SDK 已放置，暂未落库 |
| 发货物流查询 | `fetch_track_numbers` | SDK 已放置，暂未落库 |
| 仓库地址查询 | `fetch_warehouse_addresses` | SDK 已放置，暂未落库 |

注意：

- 订单导入类 wrapper 会真实创建/同步订单，未设计幂等表、审核流和 PII 策略前，不要接前端按钮或自动任务。
- 只读类 wrapper 已自动按官方单次上限分批。
- 需要调用订单导入时，应先定义请求 DTO、幂等键、重试策略、失败日志、人工复核入口。

待实现：

- 订单导入。
- 订单状态同步。
- 发货物流/tracking 同步。
- 仓库地址维表。
- 订单 PII 脱敏、加解密和清理策略。

## 后续开发优先级建议

1. 仓库地址维表：补齐库存分仓可读性。
2. 订单状态查询：低风险，先做只读同步和告警。
3. 发货物流查询：为后续 Amazon/店铺 tracking 回传做准备。
4. 订单导入：高风险，先做 DTO、幂等表、sandbox 或小批量手动验证。
5. PII 策略：订单导入或订单详情相关开发前必须先定。
