# Amazon Auto Competitor Selection PRD

状态：从总 PRD 拆出的执行设计；待派工
更新：2026-06-21
负责人：若命
适用范围：Amazon 商品主流程中自动搜索、视觉初筛、抓详情并选择参考竞品。自动选商品图详见 `2026-06-19-amazon-auto-image-selection-prd.md`。

## 1. 一句话结论

竞品选择从默认人工选择改为系统自动异步链路：系统根据大健商品信息生成 Amazon 搜索关键词，用浏览器慢速搜索 Amazon 页面，抓取少量候选；再用源商品主图 URL + 候选 image URL 做视觉初筛，抓取 Top 候选详情，最后通过结构化评分自动选出最适合作为关键词、类目、Listing 和模板参考的竞品。

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

把源商品主图作为 reference，把 Amazon 搜索候选的图片 URL 作为独立图片输入给 VLM，让模型对照大健商品主图和商品事实，筛出视觉和商品类型最接近的候选。

### 8.2 Direct URL 输入规则

V1 默认 direct image URL only，不生成候选 Contact Sheet，不下载候选图做 fallback。

输入必须包含：

```text
reference:
- source image URL
- 商品 title / item_code / sku_code 等商品事实

candidates:
- slot，如 C01/C02
- ASIN
- title
- query/rank
- price/rating/reviews 简要信息
- image_url
```

候选图片必须作为独立 `image_url` 输入；文本元数据必须紧跟对应图片，便于模型回填 `slot + asin`。

### 8.3 模型输出

模型必须逐个候选输出：

```json
{
  "slot": "C01",
  "asin": "",
  "image_loaded": true,
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
解析必须做 `slot + asin` 双重校验；未知 slot、重复 slot、ASIN 不匹配或缺失候选都不得按顺序猜，必须形成可解释失败。

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

## Phase B 视觉初筛实现对账

范围：实现原方案阶段 1-4，不实现 Phase A -> Phase B 自动串联，不抓 Amazon 详情，不最终选择竞品，不触发图片分析、Listing、A+、导出或上传。

数据契约：

- `amazon_competitor_search_candidates` 增加当前视觉事实字段：`visual_similarity_score`、`visual_same_product_type`、`visual_attribute_match_score`、`visual_title_match_score`、`visual_reject`、`visual_reject_reason`、`visual_reason`、`visual_rank`、`visual_selected_for_capture`、`visual_exclusion_reason`、`visual_model`、`visual_raw_json`、`visual_matched_at`。
- 已存在的 `visual_sheet_path`、`visual_sheet_page`、`visual_sheet_label` 属于旧 Contact Sheet 方案残留字段；当前 direct URL 主路径不写入、不作为证据字段，后续可单独评估物理 drop。
- MySQL startup ensure columns/indexes 增加 `ix_amz_comp_visual_current` 和 `ix_amz_comp_visual_run_step`。
- 当前 selected 只表示最新一次视觉初筛当前事实；retry reserve 会清空同商品旧视觉事实和 `visual_selected_for_capture`。

候选输入：

- Phase B 只读取最近成功 `product_competitor_search` task run 和成功 step 写入的候选。
- 查询必须同时绑定 `product_id + task_run_id + task_step_id`，并过滤 `is_excluded=0`、`image_url` 非空；不得读取同 product 历史所有候选再排序。
- success 只对当前 run/step 输入集合写 Top 4-6；旧 run 候选不得保留 `visual_selected_for_capture=1`。

服务：

- 服务文件：`backend/app/services/amazon_competitor_visual_match.py`。
- 每个商品最多处理 20 个当前 run/step 候选。
- 默认运行路径为 direct image URL：源商品当前主图作为 reference，每个候选以独立 `image_url` 输入，并带 `slot`、`asin`、`title`、`search_rank`、`price/rating/review_count` 元数据。
- VLM 输出固定为候选级 JSON：`slot`、`asin`、`image_loaded`、`same_product_type`、`visual_similarity`、`attribute_match`、`title_match`、`reject`、`reject_reason`、`reason`。
- 解析必须做 `slot + asin` 双重校验；未知 slot、重复 slot、ASIN 不匹配、缺失候选、JSON 解析失败或 VLM 调用失败均使本轮视觉初筛失败，不按顺序猜测。
- 不保留 Contact Sheet fallback；不下载候选图、不生成拼接图、不调用 `analyze_contact_sheet()`。
- `fake_competitor_visual_match_v1` 仅作为显式测试 fixture，不得静默推进真实商品流程。

任务中心：

- task type：`product_competitor_visual_match`。
- planner：`backend/app/task_planners/product_competitor_visual_match.py`。
- action：`ProductCompetitorVisualMatchAction`，注册到 `register_product_task_actions()`。
- correlation key：`product:{product_id}:competitor_visual_match`。
- reserve：`visual_match_competitors/processing`，并清空旧 selected。
- success：写当前 run/step visual 字段，Top 4-6 标记 `visual_selected_for_capture=1`，进入 `capture_competitor_candidates/pending`。
- failure/cancel/interrupted：进入 `visual_match_competitors/failed`，且不保留 current selected candidates。

API / 前端：

- 后端入口：`POST /api/products/{product_id}/competitor-visual-match/retry`。
- `visual_match_competitors/processing` 在 API 层直接返回当前 workflow/task-center correlation，不调用 planner，不创建重复 run。
- 商品列表消费 `retry_competitor_visual_match`、`restart_competitor_search` 和 `open_task_center` action；不新增复杂页面。

保护：

- 中性 helper：`product_external_result_protection_reasons(product)`。
- 自动选图保护 helper 委托中性 helper；视觉初筛 action 直接调用中性 helper，避免已有真实 ASIN、Catalog 确认/导出、Amazon 模板输出、A+ 上传证据被静默覆盖。

## Phase 1 候选详情抓取与自动选竞品结构契约对账

状态：2026-06-21 按 `MSG-20260621-009` 只实现结构契约、任务 skeleton 和 fixture adapter。

本阶段只为后续候选详情抓取和自动最终选竞品建立可测试边界；不访问真实 Amazon，不抓真实详情落库，不做最终评分，不写 `products.competitor_asin`，不改前端，不触发真实商品 task run。

数据契约：

- `amazon_competitor_search_candidates` 增加候选详情 current fact 字段：`detail_task_run_id`、`detail_task_step_id`、`detail_captured_at`、`brand`、`seller`、`category_rank`、`leaf_category`、`main_image_url`、`bullets_json`、`description`、`product_details_json`、`aplus_text`、`capture_status`、`capture_error`、`capture_raw_json`。
- 同表增加最终选择 current fact 字段：`final_selected`、`final_rank`、`final_score`、`final_confidence`、`final_dimension_scores_json`、`final_reason`、`final_risks_json`、`final_model`、`final_rule_version`、`final_raw_json`、`final_selected_at`。
- MySQL startup ensure 同步补字段，并新增 `ix_amz_comp_capture_current(product_id, visual_selected_for_capture, capture_status, visual_rank, id)` 和 `ix_amz_comp_final_current(product_id, final_selected, final_rank, id)`。
- `capture_status/final_selected/final_*` 均为当前事实；后续查询不得把旧 run 的 current fact 当作当前结果。

任务中心：

- 新 workflow node：`auto_select_competitor`。
- 新 task type：`product_competitor_candidate_capture`、`product_auto_competitor_selection`。
- planner：`backend/app/task_planners/product_competitor_candidate_capture.py`、`backend/app/task_planners/product_auto_competitor_selection.py`，均只通过 `create_product_action_runs()` 创建/复用 task run。
- action skeleton：`ProductCompetitorCandidateCaptureAction`、`ProductAutoCompetitorSelectionAction`，均注册到 `register_product_task_actions()`。
- correlation key：`product:{product_id}:competitor_candidate_capture`、`product:{product_id}:auto_competitor_selection`。
- skeleton 执行采用严格模式：`execute_step()` 只写进度后明确失败；候选详情抓取不得在 execute 阶段写候选表，后续真实落库只能在 success hook 单事务完成；自动选竞品 skeleton 禁止写 `competitor_asin`。
- Phase 1 不启用商品侧真实 API/前端 retry 入口；`capture_competitor_candidates` 与 `auto_select_competitor` 的 pending/failed 商品 workflow 主操作只能是当前前端已支持的 `open_detail`，可保留已有 `restart_competitor_search` 作为辅助操作；processing 才能用 `open_task_center` 定位已注册 correlation。不得暴露未实现的 `retry_competitor_candidate_capture` 或 `retry_auto_competitor_selection`。

清理契约：

- `clear_current_competitor_capture(db, product_id, *, now)` 清同商品候选详情 current fact，包括 detail/capture/listing detail 字段；不清搜索事实、视觉事实或历史 task event。
- `clear_current_auto_competitor_selection(db, product_id, *, now, clear_product_fact)` 清同商品 `final_selected/final_*`；当 `clear_product_fact=True` 时，必须先通过 `product_external_result_protection_reasons(product)` 保护门，之后才允许清 `Product.competitor_asin`、`CatalogProduct.competitor_asin` 和 `ProductData.gigab2b_raw_snapshot` 中的 `selected_competitor/auto_competitor_selection`。

候选详情 adapter：

- 服务边界：`backend/app/services/amazon_listing_detail.py`。
- `FixtureAmazonListingDetailAdapter` 只读取测试传入的 fixture HTML，支持解析 title、brand、seller、main image、bullets、description、product details、Best Sellers Rank、leaf category 和 A+ 文本。
- 默认 `UnconfiguredAmazonListingDetailAdapter` 只抛 `adapter_not_configured`，不访问真实 Amazon、不启动浏览器、不伪造空成功。

未实现：

- 真实 Amazon 详情抓取。
- 候选详情真实落库 success hook。
- 最终评分、置信度决策和最终 ASIN 写入。
- 前端 retry 入口、真实商品 task run、真实 VLM、外部平台或 Step 10。

## Phase 2A 候选详情抓取 fixture 执行与 current-set 对账

状态：2026-06-21 按 `MSG-20260621-021` 实现 Backend Fixture Execution and Current-Set Contract。

本阶段只打开后端候选详情抓取的 fixture/configured adapter 执行路径；不开放商品侧 API/前端按钮，不访问真实 Amazon，不触发自动最终选竞品，不写最终 `competitor_asin`。

current-set evidence：

- `amazon_competitor_search_candidates` 增加 `visual_task_run_id`、`visual_task_step_id`。
- 视觉初筛 success 给本次视觉任务触达的候选写入 `visual_task_run_id=step.task_run_id`、`visual_task_step_id=step.id`。
- 候选详情抓取只读取最近成功 `product_competitor_visual_match` run/step 对应的 Top 候选：
  - `product_id = 当前商品`
  - `visual_task_run_id = latest successful visual run`
  - `visual_task_step_id = latest successful visual step`
  - `visual_selected_for_capture = 1`
  - `visual_rank IS NOT NULL`
  - order by `visual_rank ASC, id ASC`
- 对应 MySQL index：`ix_amz_comp_visual_capture_set(product_id, visual_task_run_id, visual_task_step_id, visual_selected_for_capture, visual_rank, id)`。

任务执行：

- `ProductCompetitorCandidateCaptureAction.validate()` 必须用 current visual run/step 解析精确 Top 集合；0 个候选或超过 6 个候选直接失败。
- `execute_step()` 只调用 `get_amazon_listing_detail_adapter()` 返回的 fixture/configured adapter，返回 per-candidate 结构化结果；不写 `amazon_competitor_search_candidates`。
- 默认 adapter 仍是 `UnconfiguredAmazonListingDetailAdapter`，只抛 `adapter_not_configured`，不能伪造成功。
- 全失败必须让任务失败；partial success 允许进入 success hook，但要把失败候选写成 `capture_status=failed`。

成功投影：

- `on_step_success()` 重新用 result 中的 `visual_task_run_id/visual_task_step_id` 加载当前 Top 集合，要求 result candidate ids 与当前集合完全一致。
- success hook 单事务写候选详情 current facts：`detail_task_run_id/detail_task_step_id/detail_captured_at/brand/seller/category_rank/leaf_category/main_image_url/bullets_json/description/product_details_json/aplus_text/capture_status/capture_error/capture_raw_json`。
- 至少 1 个候选成功且包含 title 或 bullets 后，商品 workflow 推进到 `auto_select_competitor/pending`。
- failure/cancel/interrupted 清理当前候选详情和 final current facts，回到 `capture_competitor_candidates/failed`。

仍未实现：

- 真实 Amazon adapter 和真实小样本授权。
- `POST /api/products/{id}/competitor-candidate-capture/retry`。
- 前端 `retry_competitor_candidate_capture` 按钮。
- 自动最终选竞品评分和最终 ASIN 写入。
