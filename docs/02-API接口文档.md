# FBM铺货系统 — API 接口文档

> 版本：0.1.0 | 更新日期：2026-05-13
> 基础地址：`http://localhost:8190`
> Swagger UI：`http://localhost:8190/docs`

---

## 接口总览

| 模块 | 方法 | 路径 | 说明 |
|------|------|------|------|
| 商品 | POST | `/api/products` | 创建商品任务 |
| 商品 | GET | `/api/products` | 商品列表（分页） |
| 商品 | GET | `/api/products/{id}` | 商品详情（含子表） |
| 商品 | PATCH | `/api/products/{id}` | 更新商品信息 |
| 商品 | DELETE | `/api/products/{id}` | 删除商品 |
| Pipeline | POST | `/api/products/{id}/start` | 启动 Pipeline |
| Pipeline | POST | `/api/products/{id}/pause` | 暂停 Pipeline |
| Pipeline | POST | `/api/products/{id}/retry` | 重试失败步骤 |
| Pipeline | POST | `/api/products/{id}/step/{step}` | 单独执行某步 |
| 配置 | GET | `/api/config` | 获取系统配置（脱敏） |
| 配置 | GET | `/api/config/status` | 系统健康检查 |
| 图片 | GET | `/api/images/{path}` | 本地图片代理 |
| 健康 | GET | `/api/health` | 健康检查 |

---

## 1. 商品 CRUD

### 1.1 创建商品任务

```
POST /api/products
```

**请求体**（`application/json`）：

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| gigab2b_url | string | ✅ | — | 大健云仓商品链接 |
| competitor_asin | string \| null | ❌ | null | 竞品 ASIN（用于关键词反查） |
| brand | string | ❌ | "Vindhvisk" | 品牌 |

**请求示例**：
```json
{
  "gigab2b_url": "https://www.gigab2b.com/product/detail/W3327A001065",
  "competitor_asin": "B0GMWKDNBC",
  "brand": "Vindhvisk"
}
```

**响应** `201 Created` → [ProductResponse](#productresponse)

**逻辑**：
1. 创建 `Product` 记录，状态为 `created`
2. 自动创建3张空子表（`ProductData`、`ProductImage`、`ProductAplus`）

---

### 1.2 商品列表

```
GET /api/products?page=1&page_size=20&status=step1_done
```

**查询参数**：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| page | int | ❌ | 1 | 页码（≥1） |
| page_size | int | ❌ | 20 | 每页数量（1~100） |
| status | string | ❌ | null | 按状态筛选 |

**响应** → [PaginatedResponse](#paginatedresponse)

---

### 1.3 商品详情

```
GET /api/products/{product_id}
```

**路径参数**：`product_id` (int)

**响应** `200 OK` → [ProductDetail](#productdetail)

返回完整数据，包括 `data`（商品数据）、`images`（图片分析）、`aplus`（A+内容）三个嵌套对象。

---

### 1.4 更新商品

```
PATCH /api/products/{product_id}
```

**请求体**（`application/json`，全可选）：

| 字段 | 类型 | 说明 |
|------|------|------|
| gigab2b_url | string \| null | 更新商品链接 |
| competitor_asin | string \| null | 更新竞品 ASIN |
| brand | string \| null | 更新品牌 |
| status | string \| null | 强制修改状态 |
| current_step | int \| null | 强制修改步骤 |
| error_message | string \| null | 清除/设置错误信息 |

**响应** `200 OK` → [ProductResponse](#productresponse)

---

### 1.5 删除商品

```
DELETE /api/products/{product_id}
```

**响应** `204 No Content`（无返回体）

**注意**：级联删除3张子表数据。

---

## 2. Pipeline 控制

### 2.1 启动 Pipeline

```
POST /api/products/{product_id}/start
```

**前置条件**：商品状态必须为 `created`

**逻辑**：
1. 将状态设为 `step1_collecting`，current_step 设为 1
2. 后台异步启动 Pipeline（非阻塞）
3. 立即返回更新后的商品信息

**响应** `200 OK` → [ProductResponse](#productresponse)

**错误**：
- `404` — 商品不存在
- `400` — 状态不是 `created`，无法启动

---

### 2.2 暂停 Pipeline

```
POST /api/products/{product_id}/pause
```

**逻辑**：
1. 将状态设为 `paused`
2. 向后台任务发送 `CancelledError`，Pipeline 在 `except` 中安全退出
3. 下次可从暂停点继续

**响应** `200 OK` → [ProductResponse](#productresponse)

---

### 2.3 重试失败步骤

```
POST /api/products/{product_id}/retry
```

**前置条件**：商品状态必须为 `failed`

**逻辑**：
1. 根据 `current_step` 找到失败的步骤
2. 清除 `error_message`
3. 将状态恢复为该步骤的 `_running` 状态
4. 重新启动 Pipeline（从失败步骤继续）

**响应** `200 OK` → [ProductResponse](#productresponse)

**错误**：
- `400` — 状态不是 `failed`

---

### 2.4 单独执行某步

```
POST /api/products/{product_id}/step/{step}
```

**路径参数**：
- `product_id` (int) — 商品 ID
- `step` (int) — 步骤编号（1~9）

**用途**：调试或重跑某个特定步骤（不改变商品主状态）

**响应** `200 OK`：
```json
{
  "status": "ok",
  "step": 1,
  "data": { ... }
}
```

**错误**：
- `400` — step 不在 1~9 范围内
- `500` — 步骤执行失败

---

## 3. 配置接口

### 3.1 获取系统配置

```
GET /api/config
```

**响应** `200 OK`：
```json
{
  "project_name": "FBM Pipeline",
  "version": "0.1.0",
  "backend_port": 8190,
  "frontend_port": 3190,
  "default_brand": "Vindhvisk",
  "llm_model": "gpt-5.5",
  "vlm_model": "qwen3.6-plus",
  "gpt_image_model": "gpt-image-2",
  "product_base_dir": "/Users/.../大健云仓",
  "aplus_concurrency": 5,
  "poll_interval": 3,
  "step3_4_parallel": true,
  "llm_api_configured": true,
  "vlm_api_configured": true,
  "gpt_image_api_configured": true,
  "sellersprite_configured": false
}
```

> `*_configured` 字段只返回 `bool`，不暴露实际 Key 值。

---

### 3.2 系统健康检查

```
GET /api/config/status
```

**响应** `200 OK`：
```json
{
  "status": "ok",
  "database": "fbm.db",
  "product_dir_exists": true
}
```

---

### 3.3 全局健康检查

```
GET /api/health
```

**响应** `200 OK`：
```json
{
  "status": "ok",
  "version": "0.1.0"
}
```

---

## 4. 图片代理

### 4.1 本地图片访问

```
GET /api/images/{file_path:path}
```

前端无法直接访问本地文件系统，通过此接口代理图片。

**路径参数**：`file_path` — 本地文件路径（支持 `~/` 开头）

**示例**：
```
GET /api/images/~/Documents/F/亚马逊工作目录/亚马逊商品/大健云仓/Vindhvisk/W3327A001065/source_image_01.jpg
```

**安全限制**：只允许访问以下白名单目录：
- `~/Documents/`
- `PRODUCT_BASE_DIR`
- `/tmp/`

**支持的图片格式**：`.jpg` `.jpeg` `.png` `.webp` `.gif` `.bmp` `.tiff`

**错误**：
- `403` — 路径不在白名单内
- `404` — 文件不存在
- `400` — 非图片文件

---

## 5. 数据模型（Schemas）

### ProductResponse

```json
{
  "id": 1,
  "gigab2b_url": "https://www.gigab2b.com/product/detail/W3327A001065",
  "gigab2b_product_id": "W3327A001065",
  "competitor_asin": "B0GMWKDNBC",
  "brand": "Vindhvisk",
  "status": "step1_done",
  "current_step": 1,
  "error_message": null,
  "created_at": "2026-05-13T10:00:00",
  "updated_at": "2026-05-13T10:05:00"
}
```

### ProductDetail

继承 `ProductResponse`，额外包含3个嵌套对象：

```json
{
  "...": "（ProductResponse 全部字段）",
  "data": { "见 ProductDataResponse" },
  "images": { "见 ProductImageResponse" },
  "aplus": { "见 ProductAplusResponse" }
}
```

### ProductDataResponse

商品全量数据，按 Pipeline 步骤分区：

| 字段分组 | 字段 | 类型 | 来源步骤 |
|---------|------|------|---------|
| **基础** | id, product_id | int | 系统 |
| **Step1采集** | item_code, title, color, material, filler, product_type, dimension_*, weight, packages, features (JSON), variants (JSON), stock, seller, origin, image_count, material_dir | Step 1 |
| **Step1价格** | value_total, estimated_total | Step 1 |
| **Step2定价** | suggested_price, cost_total, profit, profit_rate | Step 2 |
| **Step3关键词** | keywords_top (JSON), keyword_excel_path | Step 3 |
| **Step4类目** | categories (JSON), leaf_category | Step 4 |
| **Step5 Listing** | listing_title, listing_bullets (JSON), listing_search_terms, listing_check (JSON), listing_primary_keyword, listing_removed_keywords (JSON) | Step 5 |
| **时间** | collected_at | datetime | Step 1 |

> JSON 字段说明：
> - `features` → `string[]`（商品特性列表）
> - `variants` → `object[]`（变体列表）
> - `keywords_top` → `object[]`（Top 关键词列表）
> - `categories` → `object[]`（类目路径列表）
> - `listing_bullets` → `object[]`（五点描述）
> - `listing_check` → `object`（Listing 质量检查结果）

### ProductImageResponse

| 字段 | 类型 | 说明 |
|------|------|------|
| contact_sheet_path | string \| null | 缩略图拼合路径 |
| image_analysis | string (JSON) \| null | VLM 图片分析结果 |
| image_selling_points | string (JSON) \| null | 图片卖点 |
| category_style | string \| null | 类目视觉风格 |
| main_image_path | string \| null | 选定的主图路径 |
| main_image_source | string \| null | 主图来源（original/generated） |
| gallery_images | string (JSON) \| null | 副图列表 |
| gallery_order | string (JSON) \| null | 副图排列顺序 |
| main_image_summary | string \| null | 主图摘要 |
| analyzed_at | datetime \| null | 分析时间 |
| vlm_model | string | 使用的 VLM 模型 |

### ProductAplusResponse

| 字段 | 类型 | 说明 |
|------|------|------|
| aplus_plan | string (JSON) \| null | A+ 模块规划（6个模块） |
| aplus_plan_summary | string \| null | 规划摘要 |
| aplus_scripts | string (JSON) \| null | A+ 图像提示词脚本 |
| aplus_scripts_summary | string \| null | 脚本摘要 |
| aplus_images | string (JSON) \| null | 生成的 A+ 图片信息 |
| aplus_image_count | int \| null | 生成图片数量 |
| aplus_status | string \| null | A+ 生成状态 |
| planned_at | datetime \| null | 规划时间 |
| scripted_at | datetime \| null | 脚本时间 |
| generated_at | datetime \| null | 出图时间 |
| llm_model | string | 使用的 LLM 模型 |

### PaginatedResponse

```json
{
  "items": [ ProductResponse, ... ],
  "total": 42,
  "page": 1,
  "page_size": 20
}
```

---

## 6. 错误响应格式

所有错误返回统一 JSON 格式：

```json
{
  "detail": "错误描述"
}
```

### 常见 HTTP 状态码

| 状态码 | 含义 | 典型场景 |
|--------|------|---------|
| 400 | Bad Request | 状态不允许操作（如非 created 状态启动）、无效 step 编号 |
| 403 | Forbidden | 图片代理路径越权 |
| 404 | Not Found | 商品不存在 |
| 500 | Internal Error | 步骤执行异常 |

---

*上一步：[01-架构设计](./01-架构设计.md) | 下一步：[03-配置说明](./03-配置说明.md)*
