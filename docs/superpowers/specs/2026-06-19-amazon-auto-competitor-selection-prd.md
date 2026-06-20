# Amazon Auto Competitor Selection PRD

状态：从总 PRD 拆出的执行设计；待派工
更新：2026-06-19
负责人：若命
适用范围：Amazon 商品主流程中自动搜索、视觉初筛、抓详情并选择参考竞品。自动选商品图详见 `2026-06-19-amazon-auto-image-selection-prd.md`。

## 1. 一句话结论

竞品选择从默认人工选择改为系统自动异步链路：系统根据大健商品信息生成 Amazon 搜索关键词，用浏览器慢速搜索 Amazon 页面，抓取少量候选；再把候选按 4 个一组做视觉初筛，抓取 Top 候选详情，最后通过结构化评分自动选出最适合作为关键词、类目、Listing 和模板参考的竞品。

## 2. 目标

- 不再依赖 StyleSnap 作为主流程默认搜索入口。
- 不再要求用户从候选竞品中手动选择。
- Amazon 页面搜索使用浏览器自动化，慢节奏、小样本、可失败、可重试。
- 自动竞品结果必须可解释：query、候选、视觉分、详情抓取、最终评分和选择理由都要可追踪。
- 低置信度不硬推进，转人工纠偏。

## 3. 非目标

- 不实现自动选商品图。
- 不实现 Listing 生成。
- 不实现导出或 Amazon 上传。
- 不实现 Chrome 插件。
- 不改 Step 10 模板字段含义。
- 不批量推进真实商品。

## 4. 前置条件

必须已有：

```text
product_images.main_image_path
product_images.main_image_source = model_selected|manual_selected
product_data.title
product_data.description / features / material / dimensions 等可用商品事实
```

正常情况下，自动选图成功后进入自动竞品链路。

## 5. Workflow 设计

节点：

```text
search_competitor
visual_match_competitors
capture_competitor_candidates
auto_select_competitor
```

状态只使用：

```text
pending
processing
succeeded
failed
```

节点流转：

| 节点 | 成功后进入 | 失败后动作 |
| --- | --- | --- |
| `search_competitor` | `visual_match_competitors/pending` | 重试搜索；或人工选择竞品 |
| `visual_match_competitors` | `capture_competitor_candidates/pending` | 重试视觉初筛；重新搜索；或人工选择竞品 |
| `capture_competitor_candidates` | `auto_select_competitor/pending` | 重试抓详情；重新搜索 |
| `auto_select_competitor` | `image_analysis/pending` | 重试自动选竞品；或人工选择竞品 |

## 6. Task Types

新增 task type：

```text
product_competitor_search
product_competitor_visual_match
product_competitor_candidate_capture
product_auto_competitor_selection
```

任务要求：

- 全部进入任务中心。
- 全部可重试、可恢复、可记录 event。
- 全部由 Product Workflow Service 投影商品 workflow。
- 不允许用裸 `BackgroundTasks`、临时线程或内存队列承载主流程。
- 同一商品同一节点同一时刻只允许一个 active task。

## 7. Amazon 页面搜索

### 7.1 搜索方式

V1 使用浏览器自动化执行 Amazon 页面搜索，不使用裸 HTTP 请求作为主方案。

执行原则：

- 默认串行执行。
- 不开多标签并发搜索。
- 不做高频翻页。
- 每次页面跳转、滚动、抓取之间保留合理等待。
- 遇到验证码、地区页、登录页、机器人校验、页面结构异常时立即停止当前节点并写失败原因。

### 7.2 Query 生成

不能直接拿大健标题整句搜索。必须先抽取结构化词：

| 类型 | 示例 | 用途 |
| --- | --- | --- |
| 核心品类词 | sofa, storage cabinet, dog bed | query 主体 |
| 关键属性 | modular, rechargeable, foldable | 区分功能 |
| 材质 | fabric, metal, wood | 区分形态 |
| 尺寸/容量 | 72 inch, 4 tier, 2 pack | 区分规格 |
| 场景 | living room, garage, camping | 召回买家语义 |
| 排除词 | replacement part, cover only, accessory | 降低误召回 |

规模：

- 每个商品生成 2-3 组 query。
- 每个 query 保留 3-7 个关键词。
- 每个 query 抓前 8-12 个自然结果。
- 合并去重后最多 20 个候选进入视觉初筛。

Query 输出：

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

### 7.3 搜索候选字段

候选最少字段：

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

广告结果、配件、替换件、cover-only 商品必须标记或排除。

### 7.4 搜索状态

搜索任务创建/复用：

```text
workflow_node = search_competitor
workflow_status = processing
```

搜索成功：

```text
workflow_node = visual_match_competitors
workflow_status = pending
```

搜索失败：

```text
workflow_node = search_competitor
workflow_status = failed
workflow_error = 失败原因
```

## 8. 候选视觉初筛

### 8.1 目标

把 Amazon 搜索候选按 4 个一组拼成候选 Contact Sheet，让模型对照大健商品主图和商品事实，筛出视觉和商品类型最接近的候选。

### 8.2 拼图规则

V1 固定 4 个候选一组，使用 2x2 布局。

每个候选 tile 必须显示：

```text
#编号
ASIN
title 截断文本
query/rank
price/rating/reviews 简要信息
```

大健商品主图作为单独参考图传给模型，不混进候选 2x2 图里。

### 8.3 模型输出

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

不得只输出 winner。

### 8.4 初筛结果

视觉初筛后：

- 保留 Top 4-6 个候选进入详情抓取。
- 明显非同类、配件、替换件、包装、错误变体、品牌强绑定商品直接排除。
- 如果 Top 候选分数都低于阈值，节点失败，不硬推进。

建议阈值：

```text
visual_similarity >= 0.65
same_product_type = true
```

阈值应集中定义，方便后续调整。

### 8.5 视觉初筛状态

任务创建/复用：

```text
workflow_node = visual_match_competitors
workflow_status = processing
```

成功：

```text
workflow_node = capture_competitor_candidates
workflow_status = pending
```

失败：

```text
workflow_node = visual_match_competitors
workflow_status = failed
workflow_error = 失败原因
```

## 9. 抓取候选详情

### 9.1 候选范围

只抓视觉初筛 Top 4-6 个候选。

### 9.2 抓取内容

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

### 9.3 成功条件

至少 1 个候选详情抓取成功，且包含 title 或 bullets。

更理想条件：

- 至少 2 个候选详情抓取成功，或
- Top 1/Top 2 候选详情抓取成功且数据完整度高。

### 9.4 状态

任务创建/复用：

```text
workflow_node = capture_competitor_candidates
workflow_status = processing
```

成功：

```text
workflow_node = auto_select_competitor
workflow_status = pending
```

失败：

```text
workflow_node = capture_competitor_candidates
workflow_status = failed
workflow_error = 失败原因
```

## 10. 自动选竞品

### 10.1 输入

输入事实：

- 我方商品标题、描述、规格、尺寸、材质、颜色、价格、类目线索。
- 自动选图结果和主图。
- Amazon 搜索 query、搜索 rank、搜索结果基础信息。
- 视觉初筛结果：相似度、同类判断、排除原因。
- 抓取到的候选 Amazon Listing 详情。
- 如可用，SellerSprite 补充数据。

### 10.2 评分维度

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

建议权重：

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

不能只按 Amazon 搜索排名选，不能只按视觉相似分选。

### 10.3 输出

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

### 10.4 成功写入

成功后写入：

```text
products.competitor_asin
amazon 搜索候选记录 selected 标记
product_data.gigab2b_raw_snapshot.selected_competitor
product_data.gigab2b_raw_snapshot.auto_competitor_selection
product_data.categories / leaf_category
catalog_products.competitor_asin
```

自动搜索候选不得复用旧 `amazon_stylesnap_candidates` 表或旧 StyleSnap snapshot key；新候选只写 `amazon_competitor_search_candidates`。旧 StyleSnap 运行入口和代码层历史兼容已退役。

### 10.5 成功推进

自动选竞品成功后：

```text
workflow_node = image_analysis
workflow_status = pending
workflow_error = null
```

如果自动串联开启，则创建或复用 `product_image_analysis` 任务。

### 10.6 失败

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

## 11. 前端影响

竞品确认页不再作为默认主流程队列。

商品详情需要展示：

- Amazon 搜索 query。
- 每个 query 的候选数量。
- 候选视觉初筛 4 图拼图。
- 每个候选视觉分、同类判断、排除原因。
- 抓详情成功/失败情况。
- 最终选中竞品、维度评分、选择理由、风险。
- 手动纠偏入口。

商品列表主按钮：

| 状态 | 主按钮 |
| --- | --- |
| `search_competitor/failed` | 重试 Amazon 搜索 / 手动选竞品 |
| `visual_match_competitors/failed` | 重试视觉初筛 / 重新搜索 |
| `capture_competitor_candidates/failed` | 重试抓候选详情 |
| `auto_select_competitor/failed` | 重试自动选竞品 / 手动选竞品 |

前端不得用 `error_message` 正则拼状态。

## 12. 执行任务拆分

建议给听云拆成以下任务：

- C1：设计 Amazon 搜索候选持久化结构和来源字段。
- C2：实现大健商品事实到搜索 query 的生成服务。
- C3：实现浏览器慢速 Amazon 页面搜索任务。
- C4：实现搜索候选去重、广告/配件/无效候选标记。
- C5：实现 4 候选一组视觉初筛。
- C6：实现高相似候选详情抓取任务。
- C7：实现自动竞品结构化评分和写入。
- C8：串联自动选竞品成功后进入 `image_analysis/pending` 并创建/复用图片分析任务。
- C9：竞品确认页降级为纠偏入口。
- C10：补项目规则/单测和索引。

C1-C4 先完成搜索召回；C5-C7 完成自动选择；C8-C10 完成流程串联和 UI 收口。

## 13. 验收标准

- 系统能从商品事实生成 2-3 组 Amazon 搜索 query。
- 浏览器慢速搜索能抓取自然搜索候选，并保存 query/rank/候选证据。
- 单商品候选合并后最多 20 个进入视觉初筛。
- 视觉初筛按 4 个候选一组输出逐候选评分。
- 视觉 Top 4-6 候选进入详情抓取。
- 自动竞品选择有维度评分、最终理由和风险。
- 不能只选 Amazon 搜索第一名。
- 不能只选视觉最高分。
- 低置信度不硬推进。
- 成功写入 `competitor_asin`、selected competitor、listing capture 和类目线索。
- 成功后进入 `image_analysis/pending`。

## 14. 验证命令

至少需要：

```bash
python -m compileall backend/app
make test-project-rules
cd frontend && npm run build
git diff --check
```

如使用浏览器自动化，需要提供可控的 dry-run 或 mock 页面测试，不能依赖真实 Amazon 页面作为唯一测试证据。

## 15. 禁止范围

- 不用裸 HTTP 请求批量打 Amazon 搜索页或详情页。
- 不并发打开多个 Amazon 搜索页/详情页追求速度。
- 不无限重试验证码、地区页、登录页、机器人校验。
- 不把广告结果、配件、替换件、cover-only 商品混入最终候选而不标记。
- 不只选 Amazon 搜索第一名。
- 不只看候选图片相似度。
- 不把低置信度结果伪装成成功。
- 不改 Step 10 模板映射或 Amazon 导入模板。
- 不覆盖真实 ASIN、导出历史或人工确认事实。

## 16. Phase A 搜索召回实现对账

状态：2026-06-20 已按 `MSG-20260620-006` 执行 Phase A 搜索召回。

本阶段只启用“搜索召回”，不启用视觉初筛、候选详情抓取、自动评分/选择、图片分析、Listing、A+、导出、Amazon 上传或 Step 10。

数据契约：

- 新自动竞品主事实表：`amazon_competitor_search_candidates`。
- 主归属字段：`product_id`、`source_data_source_id`、`source_site`、`source_batch_id`、`item_code`、`sku_code`。
- 运行证据字段：`task_run_id`、`task_step_id`。
- 搜索证据字段：`search_query`、`query_intent`、`query_index`、`search_rank`、`source="amazon_search_page"`、`captured_at`。
- 候选字段：`asin`、`url`、`title`、`image_url`、`price`、`rating`、`review_count`、`sponsored`。
- 标记字段：`is_accessory`、`is_replacement_part`、`is_cover_only`、`is_excluded`、`exclusion_reason`。
- 原始证据：`raw_candidate_json`、`raw_search_page_json`。
- 幂等口径：`product_id + asin` 唯一；没有 ASIN 的结果不进入主候选表。

Query 生成：

- 服务：`backend/app/services/amazon_competitor_query.py`。
- V1 使用确定性规则，`rule_version=amazon_competitor_query_v1`。
- 输入来自 `ProductData.title/description/features/material/dimensions/packages/variants` 和 `ProductImage.main_image_path/main_image_source/image_selection_analysis`。
- 每个商品生成 1-3 组 query，每组 3-7 个 included terms；事实不足时失败为 `insufficient_product_facts_for_competitor_search`。
- 不直接使用大健标题整句。

搜索 adapter：

- 服务：`backend/app/services/amazon_search_page.py`。
- adapter 负责页面访问、结果解析和异常分类；ProductTaskAction 负责 workflow、候选落库和任务生命周期。
- 已有 fixture HTML 解析和异常分类：`captcha`、`region_page`、`login_required`、`bot_check`、`unsupported_page_structure`、`navigation_timeout`、`empty_results`。
- 默认未配置真实浏览器 adapter 时明确失败，不伪造空成功；真实 Amazon 小样本搜索需单独授权。

任务中心：

- task type：`product_competitor_search`。
- planner：`backend/app/task_planners/product_competitor_search.py`。
- action：`ProductCompetitorSearchAction`，注册到 `register_product_task_actions()`。
- correlation key：`product:{product_id}:competitor_search`。
- reserve：`search_competitor/processing`。
- success：候选 upsert 与 workflow 投影在 `on_step_success()` 同事务完成，成功后进入 `visual_match_competitors/pending`。
- failure/cancel/interrupted：进入 `search_competitor/failed`，写可读 `workflow_error`。

API / 前端：

- 后端入口：`POST /api/products/{product_id}/competitor-search/retry`。
- 商品列表消费后端 workflow action：`start_competitor_search`、`retry_competitor_search`、`open_task_center`、`open_detail`。
- 旧 StyleSnap API / service / 前端竞品确认页已退役；代码层不再保留旧 `amazon_stylesnap_candidates` / `amazon_listing_captures` ORM 模型、旧 snapshot key 读取或导出兼容，新自动搜索入口不复用 `BackgroundTasks`。
