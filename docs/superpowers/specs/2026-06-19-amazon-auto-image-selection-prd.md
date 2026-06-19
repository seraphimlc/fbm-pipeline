# Amazon Auto Image Selection PRD

状态：从总 PRD 拆出的执行设计；待派工
更新：2026-06-19
负责人：若命
适用范围：Amazon 商品主流程的自动选商品图节点。自动竞品选择、Listing 生成、导出、Amazon 上传、TikTok 链路不在本文范围。

## 1. 一句话结论

商品图片选择从默认人工确认改为自动异步节点。系统拿到大健商品图片后，由模型自动选出 1 张主图和最多 8 张 gallery 图片，写入当前商品图片事实；人工图片确认页降级为失败、低置信度和用户主动纠偏入口。

## 2. 目标

- 新建 Amazon 商品草稿后，不再进入“待人工选择图片”主流程。
- 自动选图任务可追踪、可重试、可恢复。
- 自动选图成功后直接进入自动竞品搜索节点。
- 自动选图失败后，用户可以重试或手动调整图片。
- 自动选图结果必须有结构化证据：选择理由、风险标记、模型、时间戳、未选原因。

## 3. 非目标

- 不实现 Amazon 搜索竞品。
- 不实现候选视觉初筛。
- 不实现自动选竞品。
- 不实现后续图片分析卖点提取。
- 不实现 Listing 生成。
- 不改 Amazon 导入模板、Step 10、`template_mappings`。
- 不删除真实素材文件、已生成文件、导出历史、真实 ASIN 或人工确认事实。

## 4. 当前代码事实

历史版本 `backend/app/pipeline/step6_image.py` 曾经把图片拼成 Contact Sheet，让 VLM 选择主图和副图，并直接写入 `product_images.main_image_path/gallery_images`。

当前代码中这段能力已经演化为图片分析节点：

- 入口要求 `product_images.main_image_path` 已存在。
- 主要用于分析已确认图片，生成卖点、证据缺口和 `gallery_selection`。
- 当前不会覆盖人工确认图片顺序。

本 PRD 要把“模型选图”重新前移为独立自动选图节点，但不能原样复活旧实现。

## 5. Workflow 设计

新增或启用节点：

```text
auto_select_images
```

状态只使用：

```text
pending
processing
succeeded
failed
```

状态转移：

| 场景 | workflow_node | workflow_status | workflow_error |
| --- | --- | --- | --- |
| 商品草稿创建后 | `auto_select_images` | `pending` | null |
| 自动选图任务创建/复用成功 | `auto_select_images` | `processing` | null |
| 自动选图成功 | `search_competitor` | `pending` | null |
| 自动选图失败 | `auto_select_images` | `failed` | 失败原因 |

失败可用 action：

```text
retry_auto_image_selection
manual_adjust_images
```

## 6. Task Type

新增 task type：

```text
product_auto_image_selection
```

任务要求：

- 必须落入新任务中心。
- 必须有幂等 key，建议 `product_auto_image_selection:product:{product_id}`。
- 必须有 correlation key，建议 `product:{product_id}:auto_image_selection`。
- 同一商品同一时刻只允许一个 active 自动选图任务。
- 失败、取消、中断、锁超时最终都投影为 `auto_select_images/failed`。
- 不允许用裸 `BackgroundTasks`、`create_task`、临时线程或内存队列承载主流程。

## 7. 输入数据

自动选图从大健商品图片候选中选择。

候选来源：

- 大健 detail 中的 `mainImageUrl`、`imageUrls`。
- `giga_product_images` 表里的代表 SKU 图片。
- 商品草稿 `gigab2b_raw_snapshot.giga_listing_images`。
- 现有 `product_images.gallery_order` 中结构化图片候选。

候选最少字段：

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

候选分层：

1. 代表 SKU 的 `main` 和 `gallery`：主候选。
2. 其它 SKU 的 `variant_main`、`variant_gallery`：备用候选。
3. `file`、`brand`、`unknown`：默认不参与主选择，仅在主候选不足时低优先级使用。

## 8. 模型分析

建议新增服务：

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
- Contact Sheet 批大小由模型网关限制决定，不强制恢复历史 9 张。
- 可以复用当前 `step6_image.py` 的图片读取、Contact Sheet、VLM 调用、结果规范化能力，但要拆出不依赖 `main_image_path` 的候选分析入口。
- 最终选出最多 9 张 Listing 图片，而不是要求每张 Contact Sheet 必须 9 张。

模型必须判断：

- 主图是否符合 Amazon 主图底线。
- gallery 是否覆盖关键买家疑问。
- 图片是否重复、低质量、包装图、品牌图、错误变体、非商品图。
- 候选来源是否可信。

## 9. 输出结构

自动选图任务输出必须结构化：

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

不得只返回选中图片路径。

## 10. 数据写入

建议新增字段：

```text
product_images.image_selection_analysis text/json nullable
product_images.image_selected_at datetime nullable
```

成功后写入：

```text
product_images.main_image_path
product_images.main_image_source = model_selected
product_images.gallery_images
product_images.gallery_order
product_images.image_selection_analysis
product_images.image_selected_at
product_images.vlm_model
```

不要把自动选图分析混进后续 `image_analysis` 的语义里。`image_analysis` 继续用于图片卖点、证据缺口和后续 Listing/A+ 参考。

## 11. 成功推进

自动选图成功后：

```text
workflow_node = search_competitor
workflow_status = pending
workflow_error = null
```

如果自动串联开启，则创建或复用自动竞品搜索任务。串联动作必须通过任务中心持久化，不允许用临时后台线程。

## 12. 失败口径

失败场景：

- 没有候选图片。
- 候选图片无法访问。
- 所有候选都不可用。
- VLM 无响应。
- VLM 返回无效 JSON。
- 主图低置信度。
- 选出的主图不满足 Amazon 主图底线。

失败后：

```text
workflow_node = auto_select_images
workflow_status = failed
workflow_error = 失败原因
```

失败后允许：

- 重试自动选图。
- 人工调整图片。

人工调整图片保存后，必须清理后续竞品、图片分析、Listing、A+ 当前派生状态，并进入 `search_competitor/pending`。

## 13. 前端影响

图片确认页不再作为默认主流程队列。

前端需要展示：

- 自动选图状态。
- 自动选图主图和 gallery。
- 选择理由和风险标记。
- 失败原因。
- `retry_auto_image_selection`。
- `manual_adjust_images`。

商品列表主按钮：

| 状态 | 主按钮 |
| --- | --- |
| `auto_select_images/pending` | 等待自动选图 |
| `auto_select_images/processing` | 自动选图中 |
| `auto_select_images/failed` | 重试自动选图 / 手动调整图片 |
| `search_competitor/pending` | 等待自动选竞品 |

前端不得用 `error_message` 正则拼状态。

## 14. 执行任务拆分

建议给听云拆成以下任务：

- I1：新增自动选图结果字段和 schema。
- I2：抽取候选图片收集服务。
- I3：实现 VLM 自动选图服务。
- I4：实现 `product_auto_image_selection` ProductTaskAction。
- I5：把新建 Amazon 商品初始节点从 `select_images/pending` 切到 `auto_select_images/pending`。
- I6：自动选图成功后推进到 `search_competitor/pending`，并预留自动串联竞品任务入口。
- I7：图片确认页降级为纠偏入口。
- I8：补项目规则/单测和索引。

I1-I4 可以先完成后端闭环；I5-I7 再切主流程和前端。

## 14.1 阶段边界和后续保留

阶段 A 只做后端闭环，不切新建商品默认入口，不改前端默认主流程。这是实施节奏，不是产品目标收缩。

阶段 A 实现时必须保留阶段 B 的设计空间：

- `auto_select_images/pending` 必须作为新建 Amazon 商品后续初始节点保留在 workflow 设计中。
- `product_auto_image_selection` 必须能被阶段 B 的商品创建链路、重试入口或批量触发入口复用，不能只做成测试专用 action。
- 自动选图成功后的业务落点固定为 `search_competitor/pending`，不能因为阶段 A 不切入口而改成临时状态。
- 自动选图失败后的业务落点固定为 `auto_select_images/failed`，后续页面要能基于该状态提供“重试自动选图”和“手动调整图片”。
- 图片确认页降级为纠偏入口是阶段 B 必做项，不因阶段 A 暂不改前端而取消。
- 前端后续必须消费后端 workflow/action，不允许重新用 `current_step/error_message` 或字符串规则推导自动选图状态。

阶段 B 必须另起 REQUEST 或明确任务包执行，不能在阶段 A 中偷偷夹带；但阶段 A 的实现也不能阻断、删除或语义上排斥阶段 B。

## 15. 验收标准

- 新建 Amazon 商品可以进入 `auto_select_images/pending`。
- 创建/复用自动选图任务后进入 `auto_select_images/processing`。
- 自动选图成功后写入 `main_image_path/gallery_images` 和结构化分析结果。
- 自动选图成功后进入 `search_competitor/pending`。
- 自动选图失败后进入 `auto_select_images/failed`，可重试或人工调整。
- 人工调整图片不会保留旧竞品、旧图片分析、旧 Listing、旧 A+ 当前派生状态。
- 页面不再把图片确认页作为默认主流程必经入口。

## 16. 验证命令

至少需要：

```bash
python -m compileall backend/app
make test-project-rules
cd frontend && npm run build
git diff --check
```

如实现触及迁移，需要补迁移验证。

## 17. 禁止范围

- 不执行真实批量商品状态推进。
- 不删除真实素材文件。
- 不删除历史导出记录。
- 不改 Amazon 模板输出。
- 不改 Step 10 模板映射。
- 不把低置信度选图伪装成成功。
- 不用前端字符串规则替代后端 workflow。
- 不把自动选图和后续图片分析混成一个字段语义。

## 18. 阶段 A 技术设计 / 实现对账

状态：2026-06-19 听云阶段 A 后端闭环实现范围。阶段 A 只建立自动选图任务闭环，不切新建商品默认入口，不改默认前端用户路径。

### 18.1 模块职责

- `backend/app/models/status.py`
  - 新增 `WORKFLOW_NODE_AUTO_SELECT_IMAGES = "auto_select_images"`，纳入 Amazon workflow 节点枚举。
- `backend/app/product_tasks/workflow.py`
  - 新增 `auto_select_images` 的展示投影、失败动作 `retry_auto_image_selection` / `manual_adjust_images`、相关 correlation key。
- `backend/app/models/models.py`
  - `ProductImage` 新增 `image_selection_analysis` 和 `image_selected_at`。
- `backend/app/database.py`
  - 按现有 MySQL 启动兼容策略补齐 `product_images.image_selection_analysis`、`product_images.image_selected_at`。
- `backend/app/api/schemas.py`
  - `ProductImageResponse` 暴露自动选图结果字段。
- `backend/app/services/product_image_candidates.py`
  - 商品图片候选收集服务，合并 GIGA 表、detail/snapshot 和已有 `gallery_order`，负责优先级和去重。
- `backend/app/services/product_image_vlm.py`
  - 商品图片 VLM 底层能力：URL 直传、远程图片下载、Contact Sheet 生成、VLM 调用、JSON 清洗和可重试错误判断。该层不承载“自动选图”或“图片分析”的业务语义。
- `backend/app/product_tasks/auto_image_selection.py`
  - VLM 自动选图服务。只返回结构化选择结果，不写商品事实。
- `backend/app/product_tasks/actions.py`
  - 新增 `ProductAutoImageSelectionAction`，负责任务计划、reserve、execute 和最终投影。
- `backend/app/task_planners/product_auto_image_selection.py`
  - 薄 planner：调用 `create_product_action_runs(..., "product_auto_image_selection", ...)`。
- `backend/app/api/task_runs.py`
  - 仅补任务中心 task/step label，不改变默认前端路径。

### 18.2 ProductTaskAction 生命周期

Task type：

```text
product_auto_image_selection
```

Task plan：

- run title：`自动选图：商品 #{product_id}`
- group key：`auto_image_selection`
- step key：`product:{product_id}:auto_image_selection`
- step type：`product_auto_image_selection`
- max attempts：`2`

幂等和关联：

```text
dedupe_key = product_auto_image_selection:product:{product_id}
correlation_key = product:{product_id}:auto_image_selection
```

投影规则：

- `validate`：只验证商品存在，不要求已有 `main_image_path`。
- `reserve`：创建或复用 active run 后写 `auto_select_images/processing`，不写临时后台任务。
- `execute_step`：调用 `run_auto_image_selection(product_id, db=db)`，只返回结构化结果，不写 `product_images`。
- `on_step_success`：唯一成功写入点。写当前图片事实，清当前下游派生状态，进入 `search_competitor/pending`。
- `on_step_failure`：写 `auto_select_images/failed` 和可读失败原因。
- `on_cancel_requested`：写 `auto_select_images/failed`，错误文案说明取消。
- `on_step_interrupted` / 锁超时恢复：写 `auto_select_images/failed`，错误文案说明中断或锁超时。

### 18.3 ProductImage 字段和写入

新增字段：

```text
product_images.image_selection_analysis LONGTEXT NULL
product_images.image_selected_at DATETIME NULL
```

成功后写入：

- `main_image_path`
- `main_image_source = "model_selected"`
- `gallery_images`
- `gallery_order`
- `image_selection_analysis`
- `image_selected_at`
- `vlm_model`

`image_selection_analysis` 保存完整结构化结果：

```json
{
  "selected_main": {},
  "selected_gallery": [],
  "rejected": [],
  "confidence": "high|medium",
  "warnings": [],
  "contact_sheets": [],
  "model": "",
  "candidate_count": 0,
  "analyzed_count": 0
}
```

兼容策略：

- 不迁移历史商品状态。
- 老数据没有新字段时由启动补列兼容。
- 未经过自动选图的商品字段保持 null。

### 18.4 候选图片来源和优先级

候选来源：

1. `giga_product_images` 表。
2. `product_data.gigab2b_raw_snapshot` 中的 `mainImageUrl` / `imageUrls` 或 `detail.mainImageUrl` / `detail.imageUrls`。
3. `product_data.gigab2b_raw_snapshot.giga_listing_images`。
4. `product_images.gallery_order`。

每个候选保留：

```text
path, image_url, local_path, image_type, source, asset_source, sku_code, sort_order,
batch_id, site, item_code, representative_sku, is_representative_sku, download_status
```

排序优先级：

1. 代表 SKU 的 `main` / `gallery`。
2. 其它 SKU 的 `variant_main` / `variant_gallery`。
3. detail / snapshot 补充图。
4. `file` / `brand` / `unknown`。

去重策略：

- 优先以 `local_path/path` 去重。
- 没有本地路径时以 `image_url` 去重。
- 被合并来源保留到 `merged_sources`，不丢事实。

不可用候选处理：

- 本地文件不存在会被跳过并记录 warning。
- URL 候选先直传 VLM；直传失败后尝试下载并生成 Contact Sheet。
- 全部候选不可用则失败到 `auto_select_images/failed`。

### 18.5 VLM 和 Contact Sheet 边界

- 自动选图服务和旧 `step6_image.py` 共同复用 `backend/app/services/product_image_vlm.py` 的 URL 直传、远程下载、Contact Sheet 生成和 VLM 调用能力。
- 自动选图使用独立 prompt 和输出结构。
- 旧图片分析继续使用自己的 `VLM_SYSTEM_PROMPT` 和图片分析输出结构；自动选图使用 `AUTO_IMAGE_SELECTION_SYSTEM_PROMPT` 和选图输出结构。
- 服务不要求 `product_images.main_image_path` 已存在。
- 服务不写 `image_analysis`、`image_selling_points`、Listing、A+、导出或 Step 10 字段。
- `image_analysis` 继续保留给后续图片卖点和证据分析节点。

### 18.6 Workflow 落点

| 场景 | workflow_node | workflow_status |
| --- | --- | --- |
| 创建或复用自动选图 task run | `auto_select_images` | `processing` |
| 自动选图成功 | `search_competitor` | `pending` |
| 没有候选 / 候选不可访问 | `auto_select_images` | `failed` |
| VLM 无效 JSON / 未返回主图 | `auto_select_images` | `failed` |
| 主图不合规 / 主图高风险 | `auto_select_images` | `failed` |
| `confidence = low` | `auto_select_images` | `failed` |
| 用户取消 | `auto_select_images` | `failed` |
| worker 中断 / 锁超时恢复 | `auto_select_images` | `failed` |

成功投影前保护门：

- 商品已有真实 Amazon ASIN。
- Catalog 已有真实 Amazon ASIN。
- Catalog 已人工确认。
- Catalog 已有真实导出历史。
- 商品已有 Amazon 模板输出证据。
- 商品或 Catalog 已有 A+ 上传记录或上传中状态。

命中保护门时不静默清理，自动选图任务失败到 `auto_select_images/failed`。

### 18.7 阶段 A 未做事项

- 不切新建 Amazon 商品默认入口；新商品仍保持当前 `select_images/pending` 主流程。
- 不改默认前端用户路径。
- 不实现自动竞品搜索。
- 不实现自动选竞品。
- 不实现后续图片分析卖点提取。
- 不实现 Listing、A+、导出、Amazon 上传。
- 不改 Step 10、模板文件或 `template_mappings`。
- 不批量迁移历史商品 workflow。

### 18.8 测试和验证证据

项目规则新增行为测试覆盖：

- 自动选图节点、字段、schema、补列、action、planner 和服务契约。
- 候选来源合并、代表 SKU 优先、其它 SKU fallback、低优先级 brand/file/unknown 和去重。
- 低置信度不推进。
- reserve 写 `auto_select_images/processing`。
- success 写图片事实、清下游当前派生状态并进入 `search_competitor/pending`。
- failure 写 `auto_select_images/failed`。
- 不写后续 `image_analysis` 语义。

验证命令：

```bash
python -m compileall backend/app
make test-project-rules
git diff --check
```
