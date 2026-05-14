# 04 - Pipeline 步骤详解

> FBM铺货系统 9 步流水线的完整技术文档。每个步骤包含：职责、输入/输出、核心逻辑、数据库变更、错误处理。

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
```

**执行规则**：
- Step 1 必须成功，否则整个 Pipeline 终止
- Step 2/3/4 可 graceful skip（缺数据不阻塞后续）
- Step 3 和 Step 4 可并行（`STEP3_4_PARALLEL=True`）
- Step 5~9 严格顺序执行，任一失败则 Pipeline 标记 FAILED

---

## Step 1 — 商品采集

### 文件
`backend/app/pipeline/step1_collect.py`

### 职责
从大健云仓（GigaB2B）采集商品信息：标题、属性、图片、描述。

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
2. chrome_execute_js(COLLECT_JS)         # JS 注入提取商品信息
3. 解析 JSON 结果 → 构造 ProductData
4. 创建素材目录（~/Documents/F/.../大健云仓/{Brand}/{W-ID}/）
5. _download_images() → httpx 逐张下载图片
   - _strip_oss_process() 去除 OSS 缩略图参数，获取原图
   - 保存到 material_dir
6. 写入数据库
```

### Chrome JS 注入（核心）

通过 AppleScript 在 Chrome 中执行 JS，提取页面商品数据：
- 商品标题、价格、规格属性
- 图片 URL 列表
- 商品描述 HTML
- 尺寸/重量等物理属性

### 图片下载策略
- 从 JS 提取的图片 URL 中去除 `x-oss-process=image/resize,...` 参数
- 这样获取的是 OSS 原图（非缩略图）
- 使用 httpx 异步下载，保存到本地素材目录

### 错误处理
- Chrome 导航失败 → `RuntimeError("Chrome 导航失败")`
- JS 提取返回空 → 重试一次，仍失败则 `RuntimeError`
- 图片下载失败（单张）→ 跳过，不阻塞（其余图片继续下载）

### 特殊说明
- **全局串行锁**：所有 Chrome 操作通过 `chrome_ctrl._chrome_lock = asyncio.Lock()` 串行化
- **JS 文件写入**：`_write_js_file()` 将 JS 脚本写入 `/tmp/fbm_{name}.js`，再通过 AppleScript 执行

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
| `profit_rate` | float | 利润率（%） |

### 定价公式

```
设:
  T = estimated_total      # 预估总额含运费
  G = value_total           # 货值总计
  P = suggested_price       # 建议售价

综合成本:
  cost = T + 9 - 0.06 × G

公式（取两者最大值）:
  P1: 确保 5% 利润率
      P1 = (T + 9 - 0.06×G) / 0.635

  P2: 确保最低 $10 利润
      P2 = (T + 19 - 0.06×G) / 0.685

  suggested_price = MAX(P1, P2)
```

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
- 定价公式中的常数（9、19、0.06、0.635、0.685）为经验参数
- T = estimated_total（预估总额含运费），G = value_total（货值总计）
- 如需调整利润率或保底利润，修改 `step2_pricing.py` 中的公式即可

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
| `SELLERSPRITE_TOKEN` | 配置环境变量 | SellerSprite 认证 Token |

### 输出 → ProductData
| 字段 | 类型 | 说明 |
|------|------|------|
| `keywords_top` | JSON list | Top 关键词列表（含搜索量、排名等） |
| `keywords_raw_count` | int | 原始关键词总数 |

### 核心流程

```
1. 检查 competitor_asin → 无则 skip
2. 获取 SellerSprite Cookie
   - 方式 A：使用配置中的 SELLERSPRITE_TOKEN
   - 方式 B：通过 chrome_ctrl 从浏览器读取 Cookie
3. 调用逆向 API:
   POST /v3/api/relation/ta/export-keyword-new
     ?market=1&exportVariations=false&exportGkImages=false
   Body: {"asin": "B0XXXXX"}
4. 返回 Excel 二进制 → openpyxl 解析
5. 提取 Top 20 关键词（按搜索量排序）
6. 写入数据库
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

### Skip 条件
- 无 `competitor_asin` → `{"skipped": true, "reason": "no_competitor_asin"}`
- 无 SellerSprite Token/Cookie → `{"skipped": true, "reason": "no_sellersprite_token"}`

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

### Skip 条件
- 无 `competitor_asin` → `{"skipped": true, "reason": "no_competitor_asin"}`

### 并行说明
当 `STEP3_4_PARALLEL=True` 时，Step 3 和 Step 4 通过 `asyncio.gather()` 并行执行。但两者都需要 Chrome，实际会因 `_chrome_lock` 串行等待。

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
| `listing_check` | JSON | 合规检查结果 |
| `listing_removed_keywords` | JSON list | 被排除的关键词及原因 |

### LLM 配置

| 参数 | 值 |
|------|-----|
| 模型 | `settings.LLM_MODEL`（gpt-5.5） |
| 客户端 | `settings.get_llm_client()`（含 SSL verify=False） |
| temperature | 0.7 |
| max_tokens | 2000 |
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
| `main_image_source` | str | 固定 `"vlm_selected"` |
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
- **文件系统**：图片保存到 `{material_dir}/new aplus image/aplus_{position:02d}.png`
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
  "path": "/path/to/aplus_01.png",
  "size": 123456,
  "error": "错误信息（仅 failed 时）"
}
```

### 文件命名
```
new aplus image/
├── aplus_01.png    # 模块 1（品牌横幅）
├── aplus_02.png    # 模块 2（核心卖点）
├── aplus_03.png    # 模块 3（第二卖点）
├── aplus_04.png    # 模块 4（功能展示）
├── aplus_05.png    # 模块 5（对比场景）
└── aplus_06.png    # 模块 6（品牌收尾）
```

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
| 2 | `suggested_price, pricing_detail` | 定价 |
| 3 | `keywords_top, keywords_raw_count` | 关键词 |
| 4 | `categories, leaf_category` | 类目 |
| 5 | `listing_title, listing_bullets, listing_search_terms, listing_primary_keyword, listing_check, listing_removed_keywords` | Listing |

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
