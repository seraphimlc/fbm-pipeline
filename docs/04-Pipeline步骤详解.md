# 04 - Pipeline 步骤详解

> FBM铺货系统 10 步流水线的完整技术文档。每个步骤包含：职责、输入/输出、核心逻辑、数据库变更、错误处理。

---

## 总览

```
Step1 商品采集 ──→ Step2 定价分析 ──┬──→ Step3 关键词调研 ──┐
     (Chrome+JS)    (公式计算)       │    (SellerSprite API) │
                                     │                        │
                                     └──→ Step4 类目获取 ──┐ │
                                          (亚马逊爬取)      │ │
                                                           ↓ ↓
                                              Step5 Listing生成 ← LLM
                                                   │
                                              Step6 主图分析 ← VLM
                                                   │
                                              Step7 A+规划 ← LLM
                                                   │
                                              Step8 A+脚本 ← LLM
                                                   │
                                              Step9 A+出图 ← GPT Image
                                                   │
                                              Step10 导入表格
                                                   │
                                              待人工确认
```

**执行规则**：
- Step 1 必须成功，否则整个 Pipeline 终止
- Step 2/3/4 可 graceful skip（缺数据不阻塞后续）
- Step 3 和 Step 4 可并行（`STEP3_4_PARALLEL=True`）
- Step 5~10 严格顺序执行，任一失败则 Pipeline 标记 FAILED

---

## Step 1 — 商品采集

### 文件
`backend/app/pipeline/step1_collect.py`

### 职责
从大健云仓（GigaB2B）采集商品信息、创建商品素材目录，并下载/解压素材 ZIP。

### 输入
| 字段 | 来源 | 说明 |
|------|------|------|
| `product.gigab2b_url` | 用户创建时填入 | GigaB2B 商品页面 URL |
| `product.brand` | 用户创建时填入 | 品牌名 |
| `product.competitor_asin` | 用户创建时填入（可选） | 竞品 ASIN |

### 输出 → ProductData
| 字段 | 类型 | 说明 |
|------|------|------|
| `item_code` | str | GigaB2B 商品编号（如 W3327A001065） |
| `title` | str | 供应商标题 |
| `color` | str | 颜色 |
| `material` | str | 材质 |
| `filler` | str | 填充物 |
| `product_type` | str | 产品类型 |
| `origin` | str | 产地 |
| `features` | JSON list | 特性列表 |
| `weight` | float | 重量（磅） |
| `dimension_length` | float | 长（英寸） |
| `dimension_width` | float | 宽（英寸） |
| `dimension_height` | float | 高（英寸） |
| `value_total` | float | 货值总计（美元） |
| `estimated_total` | float | 预估总额含运费（美元） |
| `image_count` | int | 图片数量 |
| `material_dir` | str | 本地素材目录路径 |
| `packages` | JSON | 包装信息 |
| `variants` | JSON | 变体信息 |
| `stock` | int | 库存 |
| `seller` | str | 供应商名称 |

### 核心流程

```
1. chrome_navigate(gigab2b_url)          # 打开 GigaB2B 商品页
2. chrome_execute_js(EXTRACT_JS)         # JS 注入提取商品信息
3. 核心字段为空时按配置重试
4. 解析 JSON 结果 → 构造 ProductData
5. 创建素材目录（~/Documents/F/.../大健云仓/{Brand}/{W-ID}/）
6. 写入数据库
7. 点击“下载素材包”，按配置优先级选择 ZIP 类型
8. 等待 Chrome 下载完成，移动到 原始素材/
9. 解压到 原始素材/解压文件/
10. 整理视频素材
```

### Chrome JS 注入（核心）

通过 AppleScript 在 Chrome 中执行 JS，提取页面商品数据：
- 商品标题、价格、规格属性
- 图片 URL 列表、素材链接线索

### 异常分级

| 场景 | 默认处理 |
|------|----------|
| 页面无法打开、未登录、核心商品字段采不到 | 标记失败，阻断 Pipeline |
| 页面显示下架/不可售，或库存为 0 | 标记 `unavailable`，停止 Pipeline |
| 价格/成本缺失 | 停在 `pending_review`，写入待人工处理原因 |
| 素材包下载失败但本地已有素材 | 继续执行 |
| 素材包缺失且本地无素材 | 停在 `pending_review`，等待补素材 |

相关策略可通过系统配置调整：`STEP1_PRICE_MISSING_POLICY`、`STEP1_MATERIAL_MISSING_POLICY`、`STEP1_ALLOW_EXISTING_MATERIALS`。

### 素材下载策略
- 通过页面“下载素材包”按钮触发 Chrome 下载
- 按 `STEP1_MATERIAL_PACKAGE_PRIORITY` 选择素材包类型
- 只接收点击下载之后产生的新 ZIP
- 如果多个新 ZIP 都不包含当前货号，默认视为无法安全判断
- ZIP 会移动到 `原始素材/` 并解压到 `原始素材/解压文件/`

### 错误处理
- Chrome 导航失败、核心字段采集失败 → `failed`
- 价格/成本缺失 → 默认 `pending_review`
- 素材下载失败且无本地素材 → 默认 `pending_review`
- 素材下载失败但已有本地素材 → 默认继续

### 特殊说明
- **浏览器流程锁**：Step 1 外层通过 `chrome_workflow()` 串行化完整浏览器业务流程
- **单次 Chrome 操作锁**：底层 AppleScript/JS 操作仍通过 Chrome 操作锁保护

---

## Step 2 — 定价分析

### 文件
`backend/app/pipeline/step2_pricing.py`

### 职责
基于成本数据，计算 FBM（卖家自发货）建议售价。

### 输入
| 字段 | 来源 | 说明 |
|------|------|------|
| `product_data.estimated_total` | Step 1 采集 | 预估总额含运费 T（美元） |
| `product_data.value_total` | Step 1 采集 | 货值总计 G（美元） |

### 输出 → ProductData
| 字段 | 类型 | 说明 |
|------|------|------|
| `suggested_price` | float | 建议售价 |
| `cost_total` | float | 综合成本 |
| `profit` | float | 预估利润 |
| `profit_rate` | float | 净利率百分数，按利润/建议售价计算；5.0 表示 5% |
| `pricing_detail` | JSON | 定价明细，包含两条价格线、净收入、变动费用和采用依据 |

### 定价公式

```
设:
  T = estimated_total      # 预估总额含运费
  G = value_total           # 货值总计
  P = suggested_price       # 建议售价
  R = PRICING_NET_REVENUE_RATE
  M = PRICING_TARGET_MARGIN_RATE

综合成本:
  cost = T + PRICING_FIXED_COST - PRICING_RETURN_CREDIT_RATE × G

公式（取两者最大值）:
  P1: 确保目标净利率
      P1 = cost / (R - M)

  P2: 确保最低利润
      P2 = (cost + PRICING_MIN_PROFIT) / R

  suggested_price = MAX(P1, P2)
  profit = suggested_price × R - cost
  profit_rate = profit / suggested_price × 100
```

`pricing_detail.selected_rule` 用来解释采用哪条价格线：

- `target_margin`：目标净利率线更高
- `min_profit`：最低利润线更高

**费率假设**：
- 亚马逊佣金率：约 15%（含在 0.635/0.685 系数中）
- 优惠券扣费：含在系数中
- 广告费：预留比例

### Skip 条件
当缺少 `estimated_total` 或 `value_total` 时返回：
```json
{"skipped": true, "reason": "missing_cost_data"}
```
Pipeline 不终止，继续执行后续步骤。

### 特殊说明
- 定价公式参数来自系统配置中的 `PRICING_*`
- T = estimated_total（预估总额含运费），G = value_total（货值总计）
- `profit_rate` 是净利率，不是成本回报率；前端不再额外乘以 100

---

## Step 3 — 关键词调研

### 文件
`backend/app/pipeline/step3_keywords.py`

### 职责
通过卖家精灵（SellerSprite）逆向 API，获取竞品 ASIN 的关键词数据。

### 输入
| 字段 | 来源 | 说明 |
|------|------|------|
| `product.competitor_asin` | 用户创建时填入 | 竞品 ASIN |
| `SELLERSPRITE_TOKEN` | 配置环境变量（可选） | SellerSprite 认证 Token |

### 输出 → ProductData
| 字段 | 类型 | 说明 |
|------|------|------|
| `keywords_top` | JSON list | Top 关键词列表（含搜索量、排名等） |
| `keywords_raw_count` | int | 原始关键词总数 |

### 核心流程

```
1. 检查 competitor_asin → 无则按配置进入待人工处理/继续/失败
2. 获取 SellerSprite Cookie
   - 方式 A：使用配置中的 SELLERSPRITE_TOKEN
   - 方式 B：通过 chrome_ctrl 从浏览器读取 Cookie
3. 如果未登录/登录过期，打开卖家精灵页面，让任务停在 `pending_review`
4. 用户登录后点击继续，从 Step 3 重试
5. 调用逆向 API:
   POST /v3/api/relation/ta/export-keyword-new
     ?market=1&exportVariations=false&exportGkImages=false
   Body: {"asin": "B0XXXXX"}
6. 返回 Excel 二进制 → openpyxl 解析
7. 提取 Top 20 关键词（按搜索量排序）
8. 写入数据库
```

### 逆向 API 细节

| 项目 | 值 |
|------|-----|
| 基础 URL | `https://www.sellersprite.com` |
| 路径 | `/v3/api/relation/ta/export-keyword-new` |
| 方法 | POST |
| Content-Type | `application/json` |
| 认证 | Cookie 中的 `Sprite-X-Token`（JWT，约 24h 有效） |
| Query 参数 | `market=1`（美国站）, `exportVariations=false`, `exportGkImages=false` |
| Body | `{"asin": "B0XXXXX"}` |
| 返回 | Excel 文件（二进制），含 ~2000 条关键词，31 列 |

### Excel 解析
使用 openpyxl 读取返回的 Excel，提取关键列：
- 关键词文本
- 搜索量
- 月均购买数
- 竞争度
- 排名

### 人工登录

当没有 SellerSprite Cookie 或登录失效时，默认会在 Chrome 前台打开 `https://www.sellersprite.com/v3/keyword-reverse`，任务状态变为 `pending_review`，`current_step=3`。登录完成后，在任务详情或列表点击“继续”，Pipeline 会从 Step 3 接着执行。

---

## Step 4 — 类目获取

### 文件
`backend/app/pipeline/step4_category.py`

### 职责
通过 Chrome 访问亚马逊商品页面，从面包屑导航或 BSR 信息中提取类目路径。

### 输入
| 字段 | 来源 | 说明 |
|------|------|------|
| `product.competitor_asin` | 用户创建时填入 | 竞品 ASIN |

### 输出 → ProductData
| 字段 | 类型 | 说明 |
|------|------|------|
| `categories` | JSON list | 类目路径 `["Home & Kitchen", "Bedding", ...]` |
| `leaf_category` | str | 叶子类目（最末级） |

### 核心流程

```
1. 检查 competitor_asin → 无则 skip
2. chrome_navigate("https://www.amazon.com/dp/{asin}")  # 等待 4s
3. chrome_execute_js(CATEGORY_EXTRACT_JS)
4. JS 提取策略（两步降级）:
   a. 面包屑导航: #wayfinding-breadcrumbs_container li a
   b. Product Information: #productDetails_detailBullets_sections1 中的 BSR
5. 解析 JSON → categories + leaf_category
6. 写入数据库
```

### JS 提取逻辑（双策略）

**策略 1 — 面包屑导航**：
```javascript
document.querySelectorAll('#wayfinding-breadcrumbs_container li a')
// 提取所有面包屑链接文本 → 类目路径
// 最后一项为叶子类目
```

**策略 2 — BSR 排名**：
```javascript
// 在 #productDetails 或 #prodDetails 中
// 匹配 "Best Sellers Rank: #N in Category > #N in Sub-category"
// 正则: /#\d+\s+in\s+([^()\n]+)/g
```

### 人工补类目

默认配置下，缺竞品 ASIN 或类目抓取失败时，任务会停在 `pending_review`，`current_step=4`。用户可在商品详情页手动填写 Amazon 类目路径和叶子类目，再点击“继续”。如果商品已有人工类目且 `STEP4_ALLOW_EXISTING_CATEGORY=True`，系统会使用已有类目继续后续步骤。

### 并行说明
当前 Pipeline 按 Step 3 → Step 4 执行。Step 4 使用浏览器流程锁，避免和其他浏览器任务串页。

---

## Step 5 — Listing 文案生成

### 文件
`backend/app/pipeline/step5_listing.py`

### 职责
使用 LLM（GPT-5.5）生成亚马逊 Listing：标题、五点描述、Search Terms。

### 输入
| 字段 | 来源 | 说明 |
|------|------|------|
| `product_data.title` | Step 1 | 供应商标题 |
| `product.brand` | 用户填入 | 品牌 |
| `product_data.color` | Step 1 | 颜色 |
| `product_data.material` | Step 1 | 材质 |
| `product_data.filler` | Step 1 | 填充物 |
| `product_data.features` | Step 1 | 特性列表 |
| `product_data.weight/dimensions` | Step 1 | 物理属性 |
| `product_data.keywords_top` | Step 3 | 竞品关键词（可选） |
| `product_data.categories` | Step 4 | 类目路径（可选） |

### 输出 → ProductData
| 字段 | 类型 | 说明 |
|------|------|------|
| `listing_title` | str | 亚马逊标题（≤200 字符） |
| `listing_bullets` | JSON list | 五点描述（每点 ≤500 字符） |
| `listing_search_terms` | str | 后台搜索词（≤250 bytes） |
| `listing_primary_keyword` | str | 主关键词 |
| `listing_check` | JSON | 合规检查结果、关键词计划、定位计划和系统修剪记录 |
| `listing_removed_keywords` | JSON list | 被排除的关键词及原因 |

### LLM 配置

| 参数 | 值 |
|------|-----|
| 模型 | `settings.LLM_MODEL`（gpt-5.5） |
| 客户端 | `settings.get_llm_client()`（含 SSL verify=False） |
| temperature | `STEP5_LLM_TEMPERATURE`，默认 0.7 |
| max_tokens | `STEP5_LLM_MAX_TOKENS`，默认 2000 |
| response_format | `{"type": "json_object"}` |

### Prompt 架构

**System Prompt**：亚马逊 Listing 专家角色，核心原则：
- 自然语言而非关键词堆砌
- 场景驱动的卖点描述
- 解决买家疑虑（尺寸、适用性、耐用性等）
- 不做虚假宣传

**User Prompt 模板**：注入商品属性 + 关键词 + 类目，要求输出：
```json
{
  "keyword_plan": {
    "primary_keyword": "...",
    "title_keywords": ["..."],
    "bullet_keywords": ["..."],
    "search_terms_only": ["..."],
    "excluded_keywords": ["..."]
  },
  "positioning": {
    "target_buyer": "...",
    "main_click_reason": "...",
    "conversion_risks": ["..."]
  },
  "title": "品牌 + 主关键词 + 核心属性",
  "bullets": ["5条卖点描述"],
  "search_terms": "后台搜索词（空格分隔）",
  "primary_keyword": "主关键词",
  "compliance_check": {
    "status": "pass|warning",
    "issues": ["风险项"]
  },
  "removed_keywords": ["被排除的关键词及原因"]
}
```

### 错误处理
- 无 `title` 且无 `product_type` → `ValueError("缺少商品基本信息")`
- LLM 返回空 → `RuntimeError`
- LLM 输出超过标题、五点或 Search Terms 限制 → 系统自动裁剪，并写入 `listing_check.system_adjustments`
- Search Terms 中和标题/五点重复的词会自动剔除，避免浪费后台关键词空间
- 主关键词未进入标题前 80 字符、标题逗号过多等问题会写入 `listing_check.issues`

### 人工编辑

商品详情页支持人工编辑标题、五点描述、Search Terms、主关键词和中文翻译。保存后会直接写回 `product_data`，后续 Step 7/8/10 会使用人工修正后的 Listing。
- JSON 解析失败 → `RuntimeError`

---

## Step 6 — 主图分析

### 文件
`backend/app/pipeline/step6_image.py`

### 职责
使用 VLM（Qwen3.6-plus）分析商品图片，选择合规主图和副图序列。

### 输入
| 字段 | 来源 | 说明 |
|------|------|------|
| `product_data.material_dir` | Step 1 | 本地素材目录 |
| `product_data.leaf_category` | Step 4 | 叶子类目（用于风格判断） |
| `product.brand` | 用户填入 | 品牌名 |

### 输出 → ProductImage
| 字段 | 类型 | 说明 |
|------|------|------|
| `contact_sheet_path` | str | Contact Sheet 图片路径 |
| `image_analysis` | JSON list | 每张图的详细分析 |
| `image_selling_points` | JSON list | 提取的视觉卖点（≤15条） |
| `category_style` | str | 推荐图片风格 |
| `main_image_path` | str | VLM 选定的主图路径 |
| `main_image_source` | str | `"vlm_selected"` 或 `"fallback_substitute"` |
| `gallery_images` | JSON list | 副图路径列表 |
| `gallery_order` | JSON list | 副图排序 |
| `main_image_summary` | str | 总体评估文本 |
| `analyzed_at` | datetime | 分析时间 |
| `vlm_model` | str | 使用的 VLM 模型名 |

### 核心流程

```
1. 扫描素材目录中的图片
   - 支持: .jpg/.jpeg/.png/.webp/.gif/.bmp/.tiff
   - 排除: 含 "new " 的路径（避免重复处理生成的图片）
2. 生成 Contact Sheet（缩略图拼接）
   - 每张缩略图 400×400
   - 3 列网格，每页最多 9 张
   - 深灰背景，居中对齐
3. 编码 Contact Sheet 为 Base64
4. 调用 VLM 分析（带图片的 multimodal 请求）
5. 解析分析结果 → 选主图 + 排副图 + 提取卖点
   - 优先选择合规主图
   - 如果没有完全合规主图，不中断流程，从现有素材中选择风险最低的替代图
   - 替代原因写入 `selection_diagnostics.main_image_warnings`
   - 副图按买家决策路径排序，优先覆盖全貌/角度、尺寸/比例、材质/细节、功能、场景、安装/包装
   - 重复角度或重复场景会先被压制；如果素材不足，会作为兜底副图使用并标记原因
   - 读取 Step 5 的 Listing 策略，检查文案卖点是否有图片证据
6. 写入数据库
```

### Contact Sheet 生成
```
┌──────────────────────────────┐
│  [1]    [2]    [3]           │
│                              │
│  [4]    [5]    [6]           │
│                              │
│  [7]    [8]    [9]           │
└──────────────────────────────┘
  400×400  灰色背景  编号从左到右、从上到下
```

### VLM 分析 Prompt

要求 VLM 对每张图分析：
- **compliance**: 是否符合亚马逊主图规则（纯白背景、85%+ 占比、无文字水印等）
- **selling_points**: 视觉卖点列表
- **quality_score**: 1-10 质量评分
- **recommended_slot**: 推荐位置（01-09 或 exclude）
- **reason**: 选择理由

最终输出：
```json
{
  "images": [...],
  "main_image_candidate": 1,
  "gallery_order": [1, 3, 5, 2, 4],
  "excluded": [6, 7],
  "overall_assessment": "...",
  "category_style": "standard|lifestyle|infographic"
}
```

### 亚马逊主图合规规则
VLM System Prompt 内置规则：
- 纯白背景（#FFFFFF）
- 商品占比 ≥ 85%
- 无文字叠加、Logo、水印
- 不含未附带配件
- 单品展示优先
- 专业摄影品质

### 主图替代策略

当前阶段不自动生图。若素材中没有完全适合作为 01 主图的图片，Step 6 会继续使用现有素材替代，而不是让流程停住：

- 优先排除错款、错色、模糊、严重裁切、水印等身份风险
- 在剩余图片里选择最接近商品全貌/角度图的一张
- `main_image_source` 写为 `fallback_substitute`
- `image_analysis.selection_diagnostics` 写入替代图编号、文件名和风险提醒
- 前端商品详情的“图片素材”页会显示“当前主图为替代素材”

### 图库转化诊断

`image_analysis.selection_diagnostics` 会额外记录：

- `gallery_roles`: 01-09 每张图承担的转化任务和买家疑问
- `missing_gallery_roles`: 当前素材缺失的关键图片角色
- `duplicate_suppressed`: 因同角色、同角度或同场景被压制的图片
- `duplicate_backfill`: 素材不足时兜底使用的重复图片
- `listing_image_alignment`: Listing 卖点与图片证据的对齐结果
- `image_health`: 图片健康等级，取值为 `pass`、`warning`、`high_risk`、`review_recommended`

其中 `listing_image_alignment.missing_evidence` 用于提醒：Listing 提到了尺寸、材质、功能、安装/清洁、包装配件或场景，但选定图库里没有对应证据。该提醒不阻断流程，只辅助人工审核和后续补素材。

`image_health` 会把主图替代、图库数量不足、关键角色缺失、Listing 缺图片证据、重复图兜底等问题汇总成最终风险等级。`high_risk` 和 `review_recommended` 会继续带到 Step 10 导入表格 warnings，避免最终确认时遗漏。

### 错误处理
- 素材目录不存在或无图片 → `ValueError`
- VLM 返回空 → `RuntimeError`
- JSON 解析失败 → 保存原始内容为 `{"raw": content}`，不中断

---

## Step 7 — A+ 规划

### 文件
`backend/app/pipeline/step7_aplus_plan.py`

### 职责
使用 LLM 设计 A+ Content 布局方案（5-7 个模块）。

### 输入
| 字段 | 来源 | 说明 |
|------|------|------|
| `product_data.listing_title` | Step 5 | 生成的标题 |
| `product.brand` | 用户填入 | 品牌 |
| `product_data.leaf_category` | Step 4 | 叶子类目 |
| `product_data.suggested_price` | Step 2 | 建议售价 |
| `product_data.features` | Step 1 | 特性列表 |
| `product_image.image_selling_points` | Step 6 | 视觉卖点 |
| `product_image.image_analysis.selection_diagnostics` | Step 6 | 图片健康等级、缺失角色、Listing 图片证据缺口 |
| `product_data.listing_primary_keyword` | Step 5 | 主关键词 |

### 输出 → ProductAplus
| 字段 | 类型 | 说明 |
|------|------|------|
| `aplus_plan` | JSON | 完整 A+ 规划方案 |
| `aplus_plan_summary` | str | 规划摘要 |
| `planned_at` | datetime | 规划时间 |
| `llm_model` | str | 使用的 LLM 模型 |

### A+ 模块类型

| 类型 | 说明 | 典型用途 |
|------|------|----------|
| `standard_image_header` | 带文字的横幅图 | 品牌开篇 |
| `standard_single_image_text` | 单图+文字并排 | 卖点展示 |
| `standard_4_image_text` | 四象限图文 | 多卖点/规格 |
| `standard_comparison_chart` | 对比表格 | 规格对比 |
| `standard_multiple_image_text` | 多图文组合 | 功能展示 |

### 图片缺口补偿

Step 7 会读取 Step 6 的 `image_health`、`missing_gallery_roles`、`listing_image_alignment.missing_evidence`。如果图库缺尺寸、材质、安装/包装、功能证据，A+ 规划会优先安排模块去降低这些买家疑虑。

注意：A+ 规划不会假装缺失证据已经存在。如果参考图不足，会要求采用保守的规格/文字解释或基于现有参考图的安全视觉方案，避免创造图片中没有的结构、材质、配件或功能。

每个 A+ 模块会输出转化策略字段：

- `conversion_goal`: 模块要达成的转化目标
- `buyer_objection`: 模块要降低的买家顾虑
- `evidence_source`: 使用哪些商品事实、Listing 卖点或图片证据
- `experience_angle`: 模块要创造的真实使用场景或拥有体验
- `gallery_overlap_avoidance`: 避免重复主图/副图已讲内容的方式
- `risk_guardrails`: 生成和文案必须遵守的真实性限制
- `visual_do_not_claim`: 不能画、不能说的无证据内容

A+ 的默认定位是体验页，不是参数页。Step 7 会优先规划生活方式、使用感、空间适配、舒适度、轻松布置、情绪价值等模块；规格/参数只作为降低重大顾虑的辅助证据。

### 典型 6 模块布局

```
[1] 品牌横幅 Header      → 品牌故事 + 品牌调性
[2] 核心卖点图文          → 最强卖点（图+文）
[3] 第二卖点图文          → 次要卖点
[4] 功能/规格展示         → 四象限或多图文
[5] 对比/使用场景         → 尺寸对比或使用指南
[6] 品牌收尾 + 交叉销售   → 品牌承诺 + 推荐其他产品
```

### LLM 输出格式
```json
{
  "plan_summary": "A+策略简述",
  "modules": [
    {
      "position": 1,
      "type": "standard_image_header",
      "headline": "模块标题",
      "subheading": "副标题",
	      "key_message": "核心信息",
	      "image_concept": "图片应展示什么",
	      "image_style": "photography|3d_render|infographic|lifestyle",
	      "conversion_goal": "这个模块要让买家理解/相信什么",
	      "buyer_objection": "这个模块解决的具体购买顾虑",
	      "evidence_source": "支撑该模块的商品事实、Listing卖点或图片证据",
	      "experience_angle": "这个模块要创造的真实使用体验",
	      "gallery_overlap_avoidance": "如何避免重复主图/副图已经讲过的内容",
	      "risk_guardrails": ["真实性和视觉保真限制"],
	      "visual_do_not_claim": ["不能表达的无证据卖点或视觉元素"],
	      "text_content": "正文内容"
	    }
	  ],
  "color_palette": ["#hex1", "#hex2"],
  "tone": "professional|warm|minimal|bold",
  "target_audience": "目标受众描述"
}
```

### LLM 配置

| 参数 | 值 |
|------|-----|
| temperature | 0.8（创意性较高） |
| max_tokens | 3000 |
| response_format | `json_object` |

---

## Step 8 — A+ 脚本生成

### 文件
`backend/app/pipeline/step8_aplus_script.py`

### 职责
将 A+ 规划转化为具体的 GPT Image 出图 Prompt（含尺寸、风格、文字叠加）。

### 输入
| 字段 | 来源 | 说明 |
|------|------|------|
| `product_aplus.aplus_plan` | Step 7 | A+ 规划方案 |
| `product_data.listing_title` | Step 5 | 标题 |
| `product_data.color/material` | Step 1 | 商品外观属性 |
| `product_data.leaf_category` | Step 4 | 类目 |

### 输出 → ProductAplus
| 字段 | 类型 | 说明 |
|------|------|------|
| `aplus_scripts` | JSON | 完整出图脚本 |
| `aplus_scripts_summary` | str | 视觉策略摘要 |
| `scripted_at` | datetime | 脚本生成时间 |

### 输出格式
```json
{
  "scripts": [
    {
      "module_position": 1,
      "prompt": "详细的图片生成 Prompt（100-300 词）",
      "negative_prompt": "要避免的元素",
	      "width": 970,
	      "height": 600,
	      "style": "photography|3d_render|infographic|lifestyle",
	      "conversion_goal": "继承自 Step 7 的转化目标",
	      "buyer_objection": "继承自 Step 7 的买家顾虑",
	      "evidence_source": "该图允许使用的证据来源",
	      "experience_angle": "继承自 Step 7 的体验角度",
	      "gallery_overlap_avoidance": "避免重复主图/副图的方式",
	      "risk_guardrails": ["真实性和保真限制"],
	      "visual_do_not_claim": ["不能画、不能说的内容"],
	      "text_overlays": [
	        {"text": "标题文字", "position": "top-center", "font_size": "large"}
	      ]
    }
  ],
  "summary": "视觉策略简述"
}
```

### Amazon A+ 标准尺寸

| 模块类型 | 尺寸（px） |
|----------|------------|
| Image Header | 970 × 600 |
| Single Image + Text | 300 × 300 或 300 × 400 |
| 4 Image Quadrant | 300 × 300（每象限） |
| Comparison Chart | 可变 |

### Prompt 质量
- 描述精确的视觉构图（构图、灯光、配色方案）
- 包含商品外观描述（颜色、材质、形状）
- 指定文字叠加元素（标题、要点）
- 继承每个模块的转化目标、买家顾虑、证据来源和风险限制
- 继承体验角度，画面优先表现真实使用体验，而不是参数页
- 避免重复主图/副图已经覆盖的规格信息，除非 A+ 能增加场景理解或情绪价值
- 图上文字短而清楚，不堆关键词，不写段落
- 不含人脸/人体（除非是生活方式场景）

---

## Step 9 — A+ 出图

### 文件
`backend/app/pipeline/step9_aplus_image.py`

### 职责
基于 Step 8 的出图脚本，并发调用 GPT Image API 生成 A+ Content 图片。

### 输入
| 字段 | 来源 | 说明 |
|------|------|------|
| `product_aplus.aplus_scripts` | Step 8 | 出图脚本 |
| `product_data.material_dir` | Step 1 | 素材目录（输出位置） |

### 输出
- **文件系统**：图片保存到 `{material_dir}/new aplus image/aplus_{position:02d}.jpg`
- **ProductAplus 表**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `aplus_images` | JSON list | 每张图的生成结果 |
| `aplus_image_count` | int | 成功数量 |
| `aplus_status` | str | `"done"` 或 `"partial"` |
| `generated_at` | datetime | 生成时间 |

### 核心流程

```
1. 解析 A+ 脚本 → 获取所有模块的 prompt + 尺寸
2. 创建输出目录: {material_dir}/new aplus image/
3. 创建 OpenAI client → 连接 GPT Image API
4. 并发生成（asyncio.Semaphore 控制）:
   - 默认并发数: APLUS_CONCURRENCY（通常为 5）
   - 每张图调用: client.images.generate(model, prompt, size, quality="high")
5. 处理返回:
   - b64_json → base64 解码保存
   - url → httpx 下载保存
6. 汇总结果 → 写入数据库
```

### 并发控制
```python
semaphore = asyncio.Semaphore(settings.APLUS_CONCURRENCY)  # 默认 5
tasks = [_generate_single_image(client, script, path, semaphore) for script in scripts]
results = await asyncio.gather(*tasks, return_exceptions=True)
```

### 单张图片生成
```python
response = await client.images.generate(
    model=settings.GPT_IMAGE_MODEL,      # gpt-image-2
    prompt=script["prompt"],
    n=1,
    size=f"{width}x{height}",
    quality="high",
)
```

### 结果状态
| 状态 | 说明 |
|------|------|
| `done` | 全部成功（`success_count == total`） |
| `partial` | 部分成功（有些模块失败） |

每张图的结果：
```json
{
  "position": 1,
  "status": "done|failed",
	  "path": "/path/to/aplus_01.jpg",
  "size": 123456,
	  "error": "错误信息（仅 failed 时）"
	}
	```

### 成本控制与失败恢复

Step 9 默认不覆盖已经成功的 A+ 图片：

- `APLUS_IMAGE_OVERWRITE_POLICY=skip_success`：跳过已有成功图片，只生成缺失或失败的模块
- `APLUS_IMAGE_OVERWRITE_POLICY=overwrite_all`：整批重新生成全部模块
- 如果数据库中已有 `status=done` 且文件存在，会直接复用
- 如果数据库没有成功记录但目标文件 `aplus_XX.jpg` 已存在，也会直接复用
- 单张“重新生成”是用户主动操作，仍会备份并覆盖该模块

部分失败时会保存成功/失败明细。后续重试 Step 9 会优先复用已成功图片，只补失败或缺失模块，避免整批重复消耗生图费用。

### 文件命名
```
new aplus image/
├── aplus_01.jpg    # 模块 1（品牌横幅）
├── aplus_02.jpg    # 模块 2（核心卖点）
├── aplus_03.jpg    # 模块 3（第二卖点）
├── aplus_04.jpg    # 模块 4（功能展示）
└── aplus_05.jpg    # 模块 5（品牌收尾）
```

---

## Step 10 — Amazon 导入表格

### 职责
将 Listing、价格、库存、图片 URL、包装尺寸和类目模板固定值写入 Amazon 类目导入模板，并生成“上架前检查”。

### 模板映射合并规则

导入或合并模板类目映射时，如果映射的类目 key 发生冲突，按导入顺序以后导入的映射为准；只覆盖冲突的类目，其他没有冲突的类目保持原样。

### 输出
- **文件系统**：导入表格保存到 `{material_dir}/amazon import/`
- **ProductData 表**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `amazon_template_path` | str | 导入表格路径 |
| `amazon_template_warnings` | JSON list | 上架前风险提醒 |
| `amazon_template_fill_summary` | JSON dict | 字段填充、缺失关键字段、图片 URL 和风险等级汇总 |
| `amazon_template_generated_at` | datetime | 生成时间 |

### 上架前检查

Step 10 会把前面几个步骤的风险合并到最终结果：

- 模板字段：已填字段数、模板缺失字段、关键字段是否为空
- 图片：主图 URL 是否写入、Listing 图数量、Step 6 图片健康提醒
- Listing：主关键词位置、Search Terms 是否过短、Step 5 文案提醒
- 价格：净利率、单件利润是否低于系统配置
- 库存：库存为空、为 0 或过低
- A+：A+ 图片是否完成 5 张、状态是否为 done

`amazon_template_fill_summary.risk_level` 取值为 `pass`、`warning`、`high_risk`，前端会在商品详情“各种文件”中展示，方便人工最后确认。

---

## 人工确认与运营状态

Step 10 完成后，任务进入 `pending_review`，不会自动进入可运营商品列表。人工在商品详情确认后，系统才会写入/更新 `catalog_products.confirmed_at`，商品才会出现在“商品列表”。

商品列表用于后续运营动作：

- **ASIN 同步**：仅对已确认商品执行。领星 Listing 查不到时标记 `not_found`，多匹配时标记 `multiple_found`，两种情况都不会写入真实 ASIN，只提示人工处理。
- **A+ 上传**：仅对已确认商品执行。上传状态会回写到商品和商品资料，常见状态为 `not_uploaded`、`pending`、`running`、`submitted`、`draft_saved`、`failed`、`skipped`。
- **上架检查**：商品列表显示 Step 10 的风险等级和提醒数量，便于优先处理高风险商品。

---

## 步骤依赖矩阵

| 步骤 | 依赖 | 可 Skip | 使用 AI | 使用 Chrome | 平均耗时 |
|------|------|---------|---------|-------------|----------|
| Step 1 | 用户输入（URL） | ❌ | ❌ | ✅ | 30-60s |
| Step 2 | Step 1（cost_price） | ✅ | ❌ | ❌ | <1s |
| Step 3 | Step 1（ASIN）+ Token | ✅ | ❌ | ✅（Cookie） | 10-20s |
| Step 4 | Step 1（ASIN） | ✅ | ❌ | ✅ | 10-15s |
| Step 5 | Step 1+3+4 | ❌ | ✅ LLM | ❌ | 15-30s |
| Step 6 | Step 1（图片） | ❌ | ✅ VLM | ❌ | 10-20s |
| Step 7 | Step 1+5+6 | ❌ | ✅ LLM | ❌ | 15-30s |
| Step 8 | Step 7 | ❌ | ✅ LLM | ❌ | 15-30s |
| Step 9 | Step 8 | ❌ | ✅ GPT Image | ❌ | 60-180s |
| Step 10 | Step 5+6+9 | ❌ | ❌ | ❌ | 5-20s |

## 全流程估算时间

- **最快**（无 Skip，并发 Step3+4）：~3-5 分钟
- **典型**（有 Skip，顺序执行）：~2-4 分钟
- **最慢**（网络慢 + 多张 A+ 图）：~8-10 分钟

---

## 数据库字段完整映射

### ProductData 表 — Pipeline 写入的所有字段

| Step | 写入字段 | 说明 |
|------|----------|------|
| 1 | `title, color, material, filler, product_type, origin, features, description, weight, dimension_length/width/height, cost_price, images, material_dir, source_url` | 采集数据 |
| 2 | `suggested_price, cost_total, profit, profit_rate, pricing_detail` | 定价 |
| 3 | `keywords_top, keywords_raw_count` | 关键词 |
| 4 | `categories, leaf_category` | 类目 |
| 5 | `listing_title, listing_bullets, listing_search_terms, listing_primary_keyword, listing_check, listing_removed_keywords` | Listing |
| 10 | `amazon_template_path, amazon_template_warnings, amazon_template_fill_summary, amazon_template_generated_at` | Amazon 导入表格与上架前检查 |

### ProductImage 表 — Pipeline 写入的所有字段

| Step | 写入字段 | 说明 |
|------|----------|------|
| 6 | `contact_sheet_path, image_analysis, image_selling_points, category_style, main_image_path, main_image_source, gallery_images, gallery_order, main_image_summary, analyzed_at, vlm_model` | 图片分析 |

### ProductAplus 表 — Pipeline 写入的所有字段

| Step | 写入字段 | 说明 |
|------|----------|------|
| 7 | `aplus_plan, aplus_plan_summary, planned_at, llm_model` | A+ 规划 |
| 8 | `aplus_scripts, aplus_scripts_summary, scripted_at` | A+ 脚本 |
| 9 | `aplus_images, aplus_image_count, aplus_status, generated_at` | A+ 出图 |
