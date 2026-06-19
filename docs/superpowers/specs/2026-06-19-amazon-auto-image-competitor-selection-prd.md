# Amazon Auto Image & Competitor Selection PRD

状态：讨论通过方向；待拆分执行
更新：2026-06-19
负责人：若命
适用范围：Amazon 商品主流程中“选商品图片”和“选参考竞品”的自动化改造；导出、Amazon 上传、TikTok 链路不在本文范围。

## 0. 执行 PRD 拆分

本文是总纲和方案索引。执行时以两个拆分 PRD 为准：

- 自动选商品图：`docs/superpowers/specs/2026-06-19-amazon-auto-image-selection-prd.md`
- 自动选竞品：`docs/superpowers/specs/2026-06-19-amazon-auto-competitor-selection-prd.md`

听云后续任务应基于拆分 PRD 建顶层 `REQUEST`，不要直接按本文一次性实现整条链路。

## 1. 一句话结论

选商品图片和选参考竞品不再作为默认人工节点，而改为系统自动异步节点。模型负责选图；系统根据大健商品信息生成 Amazon 页面搜索关键词，召回候选商品后按 4 个候选一组拼图，与大健主图做视觉对比，再抓取高相似候选详情并自动选择最合适的参考竞品。人工页面只保留为失败、低置信度或用户主动纠偏入口。

## 2. 背景问题

当前流程里，用户需要先确认商品主图和 gallery，再从 StyleSnap 候选里选择参考竞品。这个设计有几个问题：

- 用户逐个商品手动选图效率低，且判断标准不稳定。
- 旧代码历史上曾有模型选图能力，但当前主流程已退化为规则预选和人工确认。
- StyleSnap 依赖 token、浏览器上下文和页面状态，作为自动主流程入口不够稳定；关键词搜索 Amazon 页面更可控、更可解释。
- Amazon 页面关键词搜索本身也不等于最终答案，搜索结果需要再做图片相似、属性、类目和详情质量重排。
- 当前竞品 ASIN 被后续多个步骤依赖，人工随手选错会污染关键词、类目、Listing、模板字段判断。
- 商品流程应该走自动化主线，只在系统无法自信判断时交给用户纠偏。

## 3. 当前代码事实

### 3.1 历史模型选图

历史版本 `backend/app/pipeline/step6_image.py` 曾使用 `SHEET_COLS = 3`、`SHEET_MAX = 9`，把图片拼成 9 张一页的 Contact Sheet，调用 VLM 分析后直接写入：

```text
product_images.main_image_path
product_images.main_image_source = vlm_selected
product_images.gallery_images
```

### 3.2 当前模型选图能力

当前 `step6_image.py` 已演化为图片分析节点：

- 优先 URL 直传 VLM。
- URL 直传失败后按需下载图片并生成 Contact Sheet 兜底。
- 当前 `SHEET_MAX = 6`，用于控制请求体大小。
- 输出 `gallery_selection`、`selection_diagnostics`、`image_selling_points`。
- 当前要求 `product_images.main_image_path` 已存在，所以它发生在人工确认图片之后。
- 当前不会覆盖人工确认的图片顺序。

### 3.3 当前竞品数据用途

竞品数据当前不是单纯展示用途，而是主流程事实源：

- `product.competitor_asin` 是进入后续图片分析/Listing 生成的前置条件。
- Step3 使用 `competitor_asin` 调卖家精灵获取关键词。
- Step4 使用 `competitor_asin` 获取或补充 Amazon 类目。
- Step5 Listing prompt 使用选中竞品的标题、bullets、description、价格、评分、评论数、类目排名、A+ 摘要和 product details 作为市场参考。
- Step10 Amazon 模板字段判断使用选中竞品 ASIN、类目 rank、raw snippet、抓取到的 title/bullets 作为语义参考。

因此自动竞品选择必须严肃做候选召回、视觉初筛和详情重排，不能简单选择 StyleSnap 第一名，也不能简单选择 Amazon 搜索结果第一名。

## 4. 设计原则

### 4.1 自动是主线，人工是纠偏

默认流程不要求用户逐个商品确认图片或竞品。人工入口只用于：

- 自动节点失败。
- 自动节点低置信度。
- 用户对结果不满意，主动重选或换竞品。

### 4.2 异步节点必须可追踪、可重试、可恢复

自动选图、Amazon 页面搜索、候选视觉初筛、抓候选详情、自动竞品选择都属于可能耗时、失败、依赖外部服务的动作，必须作为可追踪的异步节点进入任务中心或商品任务框架。

禁止使用不可恢复的裸线程、临时后台任务或只存在内存里的队列承载主流程。

### 4.3 商品 workflow 只表达业务结果

任务中心记录执行事实；商品 workflow 只记录业务节点四态：

```text
pending
processing
succeeded
failed
```

商品状态不新增 canceled、interrupted、timeout 等任务执行态。任务失败、取消、中断、超时最终都投影为对应业务节点 `failed`。

### 4.4 置信度低不硬推进

模型/系统没有足够信心时，不要假装成功。节点应进入 `failed` 或 `pending_manual_review` 的等价业务表达，由人工纠偏入口处理。

V1 推荐仍只使用 `failed`，通过 `workflow_error` 和分析结果说明低置信度原因，避免扩状态。

### 4.5 不复活旧实现

不能把历史 9 图 Contact Sheet 逻辑原样搬回。应复用其可用能力，按当前任务框架、状态机和数据结构重建自动选图节点。

### 4.6 不扩大到导出和平台上传

本 PRD 只到 Listing 生成完成。导出中心、Amazon 模板、Amazon 上传、TikTok 链路不在本次改造范围。

### 4.7 Amazon 页面关键词搜索是主召回方案

V1 主方案不再依赖 StyleSnap 图片搜索。竞品候选召回优先使用 Amazon 页面关键词搜索：

- 从大健商品标题、类目线索、属性、材质、尺寸、颜色、用途中提取搜索关键词。
- 生成多组 Amazon 搜索 query。
- 通过 Amazon 搜索结果页抓取候选 ASIN 和基础展示信息。
- 后续通过视觉对比和详情分析选竞品。

StyleSnap 只作为备用候选来源或历史兼容，不作为新主流程必经入口。

### 4.8 浏览器慢节奏、小样本召回

Amazon 页面搜索使用浏览器自动化，不使用裸 HTTP 请求作为主方案。异步任务的目标是稳定和可恢复，不是高并发跑量。

执行原则：

- 默认串行执行，不开多标签并发搜索。
- 单商品内搜索 query 数量和候选数量都要控制。
- 每次页面跳转、滚动、抓取之间保留合理等待。
- 遇到验证码、地区页、登录页、机器人校验、页面结构异常时立即停止当前节点并写失败原因，不做无限重试。
- 允许任务整体慢一点；宁可少抓可信候选，也不要批量访问触发风控。

## 5. 新主流程

目标流程：

```text
商品草稿创建
  -> 自动选图
  -> Amazon 页面关键词搜索候选竞品
  -> 候选图片视觉初筛
  -> 抓取高相似候选竞品详情
  -> 自动分析并选择竞品
  -> 图片分析
  -> Listing 生成
  -> 主流程完成
```

人工纠偏入口：

```text
自动选图失败/用户不满意 -> 手动调整图片 -> 重新进入搜索候选竞品
自动竞品失败/用户不满意 -> 手动选择竞品 -> 抓取竞品详情 -> 后续自动推进
```

## 6. Workflow 节点定义

### 6.1 节点枚举

建议替换或扩展 Amazon workflow node：

```text
auto_select_images
get_stylesnap_token
search_competitor
visual_match_competitors
capture_competitor_candidates
auto_select_competitor
image_analysis
listing_generation
flow_done
```

保留人工纠偏入口对应 action，但不作为主流程默认节点：

```text
manual_adjust_images
manual_select_competitor
```

### 6.2 节点表

| 顺序 | 节点 key | 节点名称 | 类型 | 成功后进入 | 失败后动作 |
| --- | --- | --- | --- | --- | --- |
| 1 | `auto_select_images` | 自动选图 | 异步 | `search_competitor/pending` | 重试自动选图；或人工调整图片 |
| 2 | `search_competitor` | Amazon 页面关键词搜索候选 | 异步/外部依赖 | `visual_match_competitors/pending` | 重试搜索；页面访问问题进入失败 |
| 3 | `visual_match_competitors` | 候选图片视觉初筛 | 异步 | `capture_competitor_candidates/pending` | 重试视觉初筛；或调整搜索词重搜 |
| 4 | `capture_competitor_candidates` | 抓取高相似候选详情 | 异步 | `auto_select_competitor/pending` | 重试抓取；候选不足则回到搜索 |
| 5 | `auto_select_competitor` | 自动选择竞品 | 异步 | `image_analysis/pending` 或直接创建图片分析任务 | 重试分析；或人工选择竞品 |
| 6 | `image_analysis` | 图片分析 | 异步 | `listing_generation/pending` 或直接创建 Listing 任务 | 重试图片分析 |
| 7 | `listing_generation` | Listing 生成 | 异步 | `flow_done/succeeded` | 重试 Listing |
| 8 | `flow_done` | 主流程完成 | 结束 | 无 | 无 |

`get_stylesnap_token` 保留为历史/备用 StyleSnap 路径节点，不进入新主流程默认节点表。

## 7. 自动选图节点

### 7.1 目标

从大健商品图片候选中自动选出 Amazon Listing 可用图片：

- 主图 1 张。
- Gallery 最多 8 张。
- 保留模型判断、选择理由、风险标记和未选原因。
- 成功后直接写入商品图片选择结果。

### 7.2 输入

输入来源：

- 大健 detail 中的 `mainImageUrl`、`imageUrls`。
- `giga_product_images` 表里的代表 SKU 图片。
- 商品草稿 `gigab2b_raw_snapshot.giga_listing_images`。

候选图最少字段：

```json
{
  "path": "",
  "image_url": "",
  "image_type": "main|gallery|variant_main|variant_gallery|file|brand|unknown",
  "source": "",
  "asset_source": "",
  "sku_code": "",
  "sort_order": 1
}
```

### 7.3 候选优先级

V1 候选池分层：

1. 代表 SKU 的 `main` 和 `gallery`：主候选。
2. 其它 SKU 的 `variant_main`、`variant_gallery`：备用候选。
3. `file`、`brand`、`unknown`：默认不参与主选择，只在主候选不足时作为低优先级备用。

模型可以看到候选来源，但必须被提示不要把品牌图、外箱图、说明图、非商品主体图优先选为主图。

### 7.4 模型分析方式

复用当前图片分析能力，但拆出新的自动选图服务，不能依赖 `pi.main_image_path` 已存在。

建议服务：

```text
backend/app/product_tasks/auto_image_selection.py
```

建议核心函数：

```python
async def run_auto_image_selection(product_id: int) -> dict:
    ...
```

分析方式：

- 优先 URL 直传 VLM。
- URL 直传失败后按需下载并生成 Contact Sheet。
- Contact Sheet 批大小由模型网关限制决定，不强制恢复 9 张；可以继续使用当前 `SHEET_MAX = 6`。
- 最终选择最多 9 张 Listing 图，而不是要求每张 Contact Sheet 必须 9 张。

### 7.5 输出

输出必须结构化，建议字段：

```json
{
  "selected_main": {
    "path": "",
    "image_url": "",
    "image_id": "#01",
    "score": 0.95,
    "reason": "",
    "risk_flags": []
  },
  "selected_gallery": [
    {
      "path": "",
      "image_url": "",
      "image_id": "#02",
      "role": "alternate_angle|size_scale|material_detail|function_use|lifestyle|package_contents|proof",
      "score": 0.88,
      "reason": "",
      "risk_flags": []
    }
  ],
  "rejected": [
    {
      "path": "",
      "image_id": "#10",
      "reason": "duplicate|packaging|wrong_variant|low_quality|brand_asset|not_product"
    }
  ],
  "confidence": "high|medium|low",
  "warnings": [],
  "contact_sheets": [],
  "model": ""
}
```

### 7.6 成功写入

自动选图成功后写入：

```text
product_images.main_image_path
product_images.main_image_source = model_selected
product_images.gallery_images
product_images.gallery_order
product_images.image_selection_analysis 或 product_images.image_analysis 的明确子结构
product_images.vlm_model
```

建议新增独立字段：

```text
product_images.image_selection_analysis text/json nullable
product_images.image_selected_at datetime nullable
```

理由：`image_analysis` 当前承担后续图片卖点和证据分析，自动选图与后续图片分析语义不同，不应混在一个字段里。

### 7.7 成功后推进

成功：

```text
workflow_node = search_competitor
workflow_status = pending
workflow_error = null
```

如果产品策略允许自动串联，自动创建搜索竞品任务。

### 7.8 失败口径

失败场景：

- 没有候选图片。
- 所有候选都不可用。
- VLM 无响应或返回无效 JSON。
- 主图低置信度。
- 选出的主图不满足 Amazon 主图底线。

失败：

```text
workflow_node = auto_select_images
workflow_status = failed
workflow_error = 失败原因
```

允许动作：

```text
retry_auto_image_selection
manual_adjust_images
```

## 8. 搜索候选竞品节点

### 8.1 目标

使用大健商品信息生成关键词，在 Amazon 页面搜索候选竞品，写入候选表，不让用户从搜索结果里手动挑。

### 8.2 输入

必须已有：

```text
product_images.main_image_path
product_images.main_image_source = model_selected|manual_selected
product_data.title
product_data.description / features / material / dimensions 等可用商品事实
```

### 8.3 行为

V1 主流程使用浏览器自动化执行 Amazon 页面关键词搜索，不使用裸 HTTP 请求，不使用 StyleSnap 作为默认入口。

搜索动作：

1. 从大健商品事实提取搜索词。
2. 生成少量高质量 query。
3. 通过浏览器打开 Amazon 搜索结果页。
4. 慢速读取首屏和少量滚动后的自然搜索结果候选。
5. 去广告、去重复 ASIN、去明显无效结果。
6. 保存候选和 query 证据。

建议搜索规模：

- 每个商品生成 2-3 组 query。
- 每个 query 抓前 8-12 个自然结果。
- 合并去重后保留最多 20 个候选进入视觉初筛。
- 单商品搜索阶段不翻深页；V1 只做首屏和少量滚动补充。

建议节奏：

- 同一商品内 query 串行执行。
- 每次搜索页打开后等待页面稳定再解析。
- 每个 query 之间保留间隔。
- 不在一个任务里连续处理大量商品；批量商品由任务队列逐个调度。

搜索结果候选最少字段：

```json
{
  "asin": "",
  "url": "",
  "title": "",
  "image_url": "",
  "price": "",
  "rating": "",
  "review_count": "",
  "sponsored": false,
  "search_query": "",
  "search_rank": 1,
  "source": "amazon_search_page"
}
```

搜索成功后：

```text
workflow_node = visual_match_competitors
workflow_status = pending
```

搜索失败：

```text
workflow_node = search_competitor
workflow_status = failed
workflow_error = 普通失败原因
```

页面访问、验证码、登录、地区、反爬或解析问题：

```text
workflow_node = search_competitor
workflow_status = failed
workflow_error = 明确页面访问或解析失败原因
```

### 8.4 搜索词生成规则

搜索词不是直接拿大健标题整句搜索。必须先抽取结构化词：

| 类型 | 示例 | 用途 |
| --- | --- | --- |
| 核心品类词 | sofa, storage cabinet, dog bed | query 主体 |
| 关键属性 | modular, rechargeable, foldable | 区分功能 |
| 材质 | fabric, metal, wood | 区分商品形态 |
| 尺寸/容量 | 72 inch, 4 tier, 2 pack | 区分规格 |
| 场景 | living room, garage, camping | 召回买家语义 |
| 排除词 | replacement part, cover only, accessory | 降低误召回 |

每个 query 只能保留 3-7 个关键词，避免过窄导致无结果。

### 8.5 Query 输出结构

建议保存：

```json
{
  "queries": [
    {
      "query": "modular sofa fabric living room",
      "intent": "core_product",
      "included_terms": ["modular sofa", "fabric", "living room"],
      "excluded_terms": ["cover only"],
      "reason": "商品标题和图片指向模块沙发"
    }
  ],
  "source_facts": {
    "title": "",
    "material": "",
    "dimensions": "",
    "features": []
  },
  "model": ""
}
```

## 9. 候选图片视觉初筛节点

### 9.1 目标

把 Amazon 搜索候选按 4 个一组拼成候选 Contact Sheet，让模型对照大健商品主图和商品事实，筛出视觉上和商品类型上最接近的候选，减少后续详情抓取量。

### 9.2 输入

必须已有：

- 自动选出的商品主图。
- 大健商品标题、属性、规格。
- Amazon 搜索候选的主图、title、ASIN、price、rating/review_count、query 和 rank。

### 9.3 拼图规则

V1 固定 4 个候选一组，使用 2x2 布局。

每个候选 tile 必须显示：

```text
#编号
ASIN
title 截断文本
query/rank
price/rating/reviews 简要信息
```

大健商品主图不混在候选 2x2 里，作为单独参考图传给模型，避免模型把源商品误认为候选。

### 9.4 模型判断

模型必须逐个候选输出：

```json
{
  "asin": "",
  "visual_similarity": 0.0,
  "same_product_type": true,
  "attribute_match": 0.0,
  "title_match": 0.0,
  "reject": false,
  "reject_reason": "",
  "reason": ""
}
```

不得只输出一个 winner。每个候选都要有分数和原因，方便审查和调试。

### 9.5 初筛结果

视觉初筛后：

- 保留 Top 4-6 个候选进入详情抓取。
- 明显非同类、配件、替换件、包装、错误变体、品牌强绑定商品直接排除。
- 如果 Top 候选分数都低于阈值，节点失败，不硬推进。

建议阈值：

```text
visual_similarity >= 0.65
same_product_type = true
```

阈值不是最终业务规则，执行者必须保留可配置能力或常量集中定义。

### 9.6 状态转移

成功：

```text
workflow_node = capture_competitor_candidates
workflow_status = pending
workflow_error = null
```

失败：

```text
workflow_node = visual_match_competitors
workflow_status = failed
workflow_error = 失败原因
```

允许动作：

```text
retry_visual_match_competitors
retry_competitor_search
manual_select_competitor
```

## 10. 抓取候选竞品详情节点

### 10.1 目标

不只抓用户选中的一个竞品，而是抓取视觉初筛后的高相似候选详情，为自动竞品选择提供事实。

### 10.2 候选范围

V1 建议：

- 视觉初筛 Top N 候选，默认 N = 4-6。
- 去重 ASIN。
- 明显无 ASIN、无 URL、不可抓取的候选直接标记排除。

### 10.3 抓取内容

每个候选至少抓：

```text
asin
url
title
brand
seller
price
rating
review_count
category_rank
leaf_category
main_image_url
bullets
description
product_details
aplus_text
capture_status
capture_error
```

### 10.4 成功条件

至少有 1 个候选详情抓取成功，且包含 title 或 bullets。

建议更严格的自动选择条件：

- 至少 2 个候选详情抓取成功，或
- Top 1/Top 2 候选详情抓取成功且数据完整度高。

如果候选数据太少，应进入失败或低置信度，不要硬选。

## 11. 自动竞品选择节点

### 11.1 目标

从候选竞品中选出最适合作为后续关键词、类目、Listing 和模板字段参考的竞品。

### 11.2 输入

输入事实：

- 我方商品标题、描述、规格、尺寸、材质、颜色、价格、类目线索。
- 自动选图结果和主图。
- Amazon 搜索 query、搜索 rank、搜索结果基础信息。
- 视觉初筛结果：相似度、同类判断、排除原因。
- 抓取到的候选 Amazon Listing 详情。
- 如可用，SellerSprite 补充数据。

### 11.3 评分维度

必须输出各维度分数和理由：

| 维度 | 说明 |
| --- | --- |
| image_similarity | 图片/外观是否相似 |
| search_relevance | 搜索 query 和结果标题是否相关 |
| product_type_match | 商品类型是否一致 |
| attribute_match | 尺寸、材质、颜色、套装数量、用途是否一致 |
| category_match | Amazon 类目/leaf category 是否合理 |
| listing_quality | 标题、bullets、description、A+、product details 是否完整 |
| market_signal | rating、review_count、category_rank 是否有参考价值 |
| risk | 品牌强绑定、明显不同款、错误变体、专利/独特设计、违禁或不适合作参考 |
| data_completeness | 关键字段是否完整 |

### 11.4 选择规则

不能只按 Amazon 搜索排名选，不能只按视觉相似分选。

建议排序：

```text
final_score =
  image_similarity * 0.25
  + search_relevance * 0.10
  + product_type_match * 0.25
  + attribute_match * 0.15
  + category_match * 0.15
  + listing_quality * 0.10
  + market_signal * 0.05
  + data_completeness * 0.05
  - risk_penalty
```

具体权重可在实现中调整，但输出必须能解释为什么选它、为什么不选其它候选。

### 11.5 输出

建议结构：

```json
{
  "selected": {
    "candidate_id": 123,
    "asin": "B0...",
    "final_score": 0.86,
    "confidence": "high|medium|low",
    "reason": "",
    "strengths": [],
    "risks": []
  },
  "ranked_candidates": [
    {
      "candidate_id": 123,
      "asin": "B0...",
      "final_score": 0.86,
      "dimension_scores": {
        "image_similarity": 0.8,
        "search_relevance": 0.8,
        "product_type_match": 0.9,
        "attribute_match": 0.8,
        "category_match": 0.9,
        "listing_quality": 0.8,
        "market_signal": 0.7,
        "data_completeness": 0.9,
        "risk": 0.1
      },
      "reason": "",
      "reject_reason": null
    }
  ],
  "warnings": [],
  "model": ""
}
```

### 11.6 成功写入

成功后写入：

```text
products.competitor_asin
amazon 搜索候选记录 selected 标记
product_data.gigab2b_raw_snapshot.selected_competitor
product_data.gigab2b_raw_snapshot.amazon_listing_capture
product_data.gigab2b_raw_snapshot.auto_competitor_selection
product_data.categories / leaf_category
catalog_products.competitor_asin
```

建议新增独立字段或表保存自动选择分析：

```text
amazon_competitor_selection_analysis
```

如果不新增表，V1 可暂存到 `gigab2b_raw_snapshot.auto_competitor_selection`，但必须结构化、可读、可追踪。

兼容期如继续复用 `amazon_stylesnap_candidates` 表或 `selected_stylesnap` snapshot key 保存候选，必须明确 `source = amazon_search_page`，并在代码和返回字段中用中性命名展示为 selected competitor，不能让后续代码误以为候选来自 StyleSnap。

### 11.7 成功后推进

成功：

```text
workflow_node = image_analysis
workflow_status = pending
workflow_error = null
```

如果自动串联，创建/复用 `product_image_analysis` 任务。

### 11.8 失败口径

失败场景：

- 无候选。
- 视觉初筛没有可信候选。
- 候选详情全部抓取失败。
- 候选都明显不是同类商品。
- 最佳候选置信度低。
- 模型返回无效分析。

失败：

```text
workflow_node = auto_select_competitor
workflow_status = failed
workflow_error = 失败原因
```

允许动作：

```text
retry_auto_competitor_selection
manual_select_competitor
retry_competitor_search
```

## 12. 人工纠偏入口

### 12.1 图片纠偏

图片确认页不再作为主流程队列页。改为：

- 自动选图失败列表。
- 用户主动进入商品详情调整图片。
- 调整保存后清空后续竞品、图片分析、Listing、A+ 派生态。
- 保存后进入 `search_competitor/pending`。

### 12.2 竞品纠偏

竞品确认页不再作为主流程队列页。改为：

- 自动竞品失败列表。
- 低置信度候选说明。
- 用户可以查看系统排名、维度分数、风险理由。
- 用户手动选择竞品后，沿用现有抓详情逻辑，并进入后续自动流程。

### 12.3 不做复杂回滚

用户重新调整图片或换竞品，代表后续派生数据无效。直接清理旧竞品、旧图片分析、旧 Listing、旧 A+ 派生态；遇到真实 ASIN、导出历史、Amazon 模板输出等保护证据时阻断。

## 13. 前端变化

### 13.1 商品列表

商品列表主按钮应按 workflow 返回：

| workflow | 主按钮 |
| --- | --- |
| `auto_select_images/failed` | 重试自动选图 / 手动调整图片 |
| `search_competitor/failed` | 重试 Amazon 搜索 |
| `visual_match_competitors/failed` | 重试视觉初筛 / 重新搜索 |
| `get_stylesnap_token/pending` | 处理 token 后重试 |
| `capture_competitor_candidates/failed` | 重试抓取候选 |
| `auto_select_competitor/failed` | 重试自动选竞品 / 手动选竞品 |
| `image_analysis/failed` | 重试图片分析 |
| `listing_generation/failed` | 重试 Listing |
| `flow_done/succeeded` | 查看详情 / 进入导出 |

前端不得用 `error_message` 正则拼主按钮。

### 13.2 商品详情

详情页新增或调整展示：

- 自动选图结果：主图、gallery、选择理由、风险标记。
- Amazon 搜索召回证据：query、结果数量、排除数量。
- 候选视觉初筛结果：4 图拼图、视觉分、排除原因。
- 自动竞品选择结果：选中 ASIN、候选排名、最终分数、理由、风险。
- 失败节点的错误和可执行动作。
- 人工纠偏入口。

### 13.3 图片确认页

降级为纠偏工具，不再承载默认待处理队列。

### 13.4 竞品确认页

降级为纠偏工具，不再承载默认待处理队列。

## 14. 后端任务类型

建议新增或调整 task type：

```text
product_auto_image_selection
product_competitor_search
product_competitor_visual_match
product_competitor_candidate_capture
product_auto_competitor_selection
```

保留现有：

```text
product_image_analysis
product_listing_generation
```

每个 task type 都必须：

- 有幂等 key。
- 有 correlation key。
- 可以 retry。
- 可以从 DB 恢复。
- 成功/失败通过 Product Workflow Service 投影到商品 workflow。

## 15. 与现有 T1-T9 的关系

本文是对 `2026-06-18-amazon-product-workflow-prd.md` 中手动 `select_images`、`select_competitor` 主流程的产品升级。

执行时不要在同一轮里硬改全部 T1-T9。建议新建一组阶段任务：

- A1：设计并落表自动选图结果结构。
- A2：实现 `product_auto_image_selection` task action。
- A3：把新建 Amazon 商品初始节点从 `select_images` 切到 `auto_select_images`。
- A4：调整图片确认页为纠偏入口。
- A5：实现大健商品事实到 Amazon 搜索 query 的生成和记录。
- A6：实现 Amazon 页面搜索候选抓取任务。
- A7：实现 4 候选一组的视觉初筛任务。
- A8：实现高相似候选详情批量抓取任务。
- A9：实现自动竞品选择分析和写入。
- A10：把竞品确认页改为纠偏入口。
- A11：串联自动流程：选图成功 -> Amazon 搜索 -> 视觉初筛 -> 抓候选详情 -> 自动选竞品 -> 图片分析 -> Listing。
- A12：清理旧手动主流程路径、StyleSnap 主流程依赖和过时文案/按钮。
- A13：镜花代码 review、观止白盒 QA。

## 16. 禁止范围

本次改造禁止：

- 修改 Amazon 导入模板文件。
- 修改 `template_mappings`。
- 修改 Step 10 模板字段含义。
- 覆盖真实 ASIN。
- 清理用户已生成素材。
- 删除真实导出历史。
- 把低置信度结果伪装成成功。
- 用内存队列承载主流程异步节点。
- 用裸 HTTP 请求批量打 Amazon 搜索页或详情页。
- 为了速度并发打开多个 Amazon 搜索页/详情页。
- 用前端字符串判断替代后端 workflow。
- 只选 StyleSnap 第一名冒充自动竞品分析。
- 只选 Amazon 搜索第一名冒充自动竞品分析。
- 只看候选图片相似度，不抓详情、不做属性和类目重排。
- 把广告结果、配件、替换件、cover-only 商品混入最终候选而不标记。
- 为了“快速上线”保留两套主流程并让页面继续混用。

## 17. 验收标准

### 17.1 自动选图

- 新商品无需用户进入图片确认页，即可自动完成主图/gallery 选择。
- 选图结果有结构化理由、风险、模型和时间戳。
- 失败可重试；失败原因在商品详情和任务中心可见。
- 手动调整图片后，旧竞品、旧图片分析、旧 Listing、旧 A+ 派生态被清理或阻断。

### 17.2 自动竞品

- 系统能生成多组 Amazon 搜索 query，抓取自然搜索候选，并保存 query/排名/候选证据。
- Amazon 搜索通过浏览器慢速执行，单商品 query 和候选数量受控；页面异常能停止并写清失败原因。
- 系统能按 4 个候选一组生成视觉对比输入，并对每个候选输出视觉分、同类判断和排除原因。
- 系统能抓取视觉 Top 候选详情、分析并选出参考竞品。
- 选中竞品不是简单 Amazon 搜索第一名，也不是简单视觉最高分，而有维度评分和选择理由。
- 写入 `competitor_asin`、selected candidate、listing capture 和类目线索。
- 低置信度不硬推进。
- 手动换竞品后清理后续派生数据，并受真实 ASIN/导出保护约束。

### 17.3 流程串联

- 用户触发或 GIGA 拉品生成商品草稿后，主流程能自动走到 Listing 生成。
- 任务中心能看到每个自动节点的执行、失败、重试。
- 商品列表/详情只展示业务 workflow，不展示任务内部状态。
- 旧图片确认/竞品确认队列不再作为主流程必经入口。

### 17.4 验证命令

至少需要：

```bash
python -m compileall backend/app
make test-project-rules
cd frontend && npm run build
```

还需要补充针对自动选图、Amazon 搜索 query 生成、搜索候选解析、视觉初筛、自动竞品选择、失败重试、人工纠偏 reset 的后端单测或项目规则测试。

## 18. 给执行者的拆分原则

听云执行时必须先提交阶段设计，不得直接开写整条链路。

每个阶段任务必须写清：

- 本阶段改哪些文件。
- 本阶段新增或修改哪些字段、接口、task type、workflow action。
- 本阶段不做什么。
- 本阶段如何验证。
- 本阶段完成后是否能独立 review。

镜花 review 时重点看：

- 自动节点是否真的持久化、可追踪、可重试。
- 模型输出是否结构化、可解释。
- Amazon 页面搜索是否有清晰边界、失败口径和候选证据。
- 视觉初筛是否逐候选输出分数和原因，而不是只输出 winner。
- 是否出现前端猜状态、后端字符串猜状态、内存队列、复杂查询补洞。
- 是否旧手动主流程和新自动主流程混用。
- 是否有低置信度硬推进。

观止 QA 时重点看：

- 新商品能否无人手动选图/选竞品走到 Listing。
- Amazon 页面搜索召回、4 候选一组视觉初筛、详情重排是否在页面/证据中可见。
- 自动失败后用户能否清楚知道下一步。
- 手动纠偏后后续派生数据是否正确重置。
- 页面展示的结果、任务状态、商品状态是否同源一致。
