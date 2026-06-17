# Amazon Product Workflow PRD

状态：用户评审通过；执行版。后续按阶段拆成 inbox 顶层任务给听云执行。
更新：2026-06-18
负责人：若命
适用范围：Amazon 商品铺货主流程，截止到 Listing 生成完成；导出、上传 Amazon、TikTok 链路不在本文范围。

## 1. 一句话结论

商品链路先跑顺，状态一致，用户能完成铺货，才是目标。

本 PRD 要把 Amazon 商品主流程从 `status/current_step/error_message` 和任务状态混用中拆出来，改为结构化商品 workflow。商品状态只表达业务节点和业务结果；任务中心只表达异步任务执行事实。

## 2. 背景问题

当前商品流程存在几个根问题：

- 商品状态、任务状态、页面按钮状态混在一起。
- 商品列表/详情会从 `Product.status/current_step/error_message`、旧 `pipeline.engine.is_running()`、task_run 状态和前端正则中拼状态。
- 任务 queued/running/interrupted 等执行细节会污染商品主状态。
- 用户重新选择主图后，旧候选、旧竞品、旧分析、旧 Listing 容易继续污染当前流程。
- StyleSnap 搜索竞品依赖浏览器/Amazon 页面上下文，不适合包装成任务中心任务。

这导致状态不可信，按钮不可信，后续每修一个点都在继续补洞。

## 3. 设计原则

### 3.1 商品状态是业务事实

商品状态回答：

- 商品处在哪个业务节点。
- 该节点是待处理、处理中、成功还是失败。
- 用户下一步该做什么。

商品状态不回答：

- task_run 是否 queued/running。
- task_run 是否 canceled/interrupted/timeout。
- task_run 第几次 retry。
- task step 细节。

### 3.2 异步任务只投影业务结果

异步节点进入任务中心后，商品只关心业务节点结果：

- 任务创建/复用成功：商品节点进入 `processing`。
- 任务成功：商品节点进入下一节点或 `succeeded`。
- 任务失败、取消、中断、超时：商品节点进入 `failed`。

商品主状态不为 canceled/interrupted/timeout 单独扩枚举。

### 3.3 前端不猜业务规则

前端只消费后端返回的 workflow 和 allowed actions。前端不得用 `status/current_step/error_message`、task display status 或字符串正则自己拼主状态和主按钮。

### 3.4 能简化就简化

V1 不做 workflow version，不保留历史流程分支，不做旧数据和新数据并存判断。用户重新选主图，代表旧竞品/旧分析/旧 Listing 对当前流程已经无效，直接清空旧派生数据。

### 3.5 不迁移存量测试数据

当前存量商品数据是测试数据，可以丢弃或重拉。V1 不做复杂 backfill，不从旧 `status/current_step/error_message` 猜新 workflow 字段。

## 4. 范围

### 4.1 In Scope

- Amazon 商品主流程节点定义。
- 新增结构化 workflow 字段。
- 商品列表/详情 workflow projection。
- 图片选择和重新选图 destructive reset。
- StyleSnap 搜索竞品作为半同步节点的业务口径。
- 选择竞品后自动推进：抓取详情 -> 图片分析 -> Listing 生成。
- ProductTaskAction 对异步节点的业务状态投影。
- 后续给听云、镜花、观止的阶段任务拆分。

### 4.2 Out Of Scope

- TikTok 链路。
- 导出中心和 Amazon 导入表格生成。
- Amazon 上传和平台刊登。
- Chrome 客户端插件实现。
- 存量测试数据迁移。
- 全量重构 `products.py`。
- 修改 Step 10、模板文件、`template_mappings`。
- 真实 ASIN、人工类目、已生成素材、导出产物的清理。

## 5. 新增数据字段

在 `products` 表新增：

```text
workflow_node        varchar / enum-like string, nullable during rollout
workflow_status      varchar / enum-like string, nullable during rollout
workflow_error       text nullable
workflow_updated_at  datetime nullable
```

V1 不新增 `workflow_version`。

### 5.1 workflow_node 枚举

```text
select_images
get_stylesnap_token
search_competitor
select_competitor
capture_competitor_detail
image_analysis
listing_generation
flow_done
```

导出不在主流程内，不新增 `export` 节点。

### 5.2 workflow_status 枚举

```text
pending
processing
succeeded
failed
```

同步节点通常只使用 `pending/succeeded`。半同步节点和异步节点可以使用四态。

### 5.3 字段职责

- `workflow_node`：当前业务节点。
- `workflow_status`：当前业务节点状态。
- `workflow_error`：当前业务节点错误或阻塞原因。
- `workflow_updated_at`：当前 workflow 最后更新时间。

### 5.4 旧字段处理

`Product.status/current_step/error_message` V1 保留兼容旧接口和历史逻辑，但新商品列表、商品详情、主按钮、筛选和 QA 均以新 workflow 字段为主。

禁止继续新增依赖 `error_message` 文案或 `current_step` 数字猜商品主状态的代码。

## 6. 状态更新统一入口

必须新增商品 workflow service/helper，所有写入统一从这里走。

建议位置：

```text
backend/app/product_tasks/workflow.py
```

建议接口：

```python
def set_product_workflow(
    product,
    *,
    node: str,
    status: str,
    error: str | None = None,
    now: datetime | None = None,
) -> None:
    ...
```

禁止在业务代码中到处散写：

```python
product.workflow_node = ...
product.workflow_status = ...
product.workflow_error = ...
```

所有同步节点、半同步节点、ProductTaskAction 生命周期钩子必须调用统一入口。

## 7. Amazon 主流程节点

| 顺序 | 节点 key | 节点名称 | 类型 | 待进入 | 执行中 | 成功 | 失败 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `select_images` | 选择图片 | 同步 | 待选择图片 | 不适用 | 进入搜索竞品 | 操作错误，不形成长期状态 |
| 2 | `get_stylesnap_token` | 获取 StyleSnap token | 前置/同步 | 待获取 token | 不适用 | 可搜索竞品 | 仍待获取 token |
| 3 | `search_competitor` | 搜索竞品 | 半同步 | 待搜索竞品 | 竞品搜索中 | 待选择竞品 | 竞品搜索失败 |
| 4 | `select_competitor` | 选择竞品 | 同步 | 待选择竞品 | 不适用 | 进入抓取详情 | 操作错误，不形成长期状态 |
| 5 | `capture_competitor_detail` | 抓取竞品详情 | 异步 | 待抓取详情 | 抓取中 | 抓取完成 | 抓取失败 |
| 6 | `image_analysis` | 图片分析 | 异步 | 待图片分析 | 图片分析中 | 图片分析完成 | 图片分析失败 |
| 7 | `listing_generation` | Listing 生成 | 异步 | 待生成 Listing | Listing 生成中 | Listing 完成 | Listing 失败 |
| 8 | `flow_done` | 主流程完成 | 结束 | 不适用 | 不适用 | 铺货内容已生成 | 不适用 |

## 8. 节点转移规则

### 8.1 选择图片

初始新商品：

```text
workflow_node = select_images
workflow_status = pending
```

用户确认图片成功：

```text
workflow_node = search_competitor
workflow_status = pending
workflow_error = null
```

前端可以在确认图片成功后立即调用搜索竞品接口，但图片确认接口本身只负责图片保存、旧流程派生数据清理和推进到 `search_competitor/pending`。

重新选择主图与选择图片成功走同一套逻辑。

### 8.2 获取 StyleSnap token

`get_stylesnap_token` 保留为 V1 节点，但不是正常主线必经节点。

当搜索竞品失败原因明确是 token/login/browser 上下文问题：

```text
workflow_node = get_stylesnap_token
workflow_status = pending
workflow_error = 明确错误原因
```

用户处理好 token 后，由搜索入口或后续插件入口推进回：

```text
workflow_node = search_competitor
workflow_status = pending
```

### 8.3 搜索竞品

用户触发搜索：

```text
workflow_node = search_competitor
workflow_status = processing
```

搜索成功，有候选：

```text
workflow_node = select_competitor
workflow_status = pending
workflow_error = null
```

搜索失败，属于商品/图片/解析/API 返回问题：

```text
workflow_node = search_competitor
workflow_status = failed
workflow_error = 失败原因
```

token/browser 类问题：

```text
workflow_node = get_stylesnap_token
workflow_status = pending
workflow_error = token/browser 问题
```

用户点重试：

```text
workflow_node = search_competitor
workflow_status = processing
```

搜索竞品不写 `task_runs`，不进入任务中心。

### 8.4 选择竞品

用户选择竞品成功：

```text
workflow_node = capture_competitor_detail
workflow_status = processing
```

选择竞品成功后允许自动触发抓取竞品详情。

用户换竞品：

- 清空旧竞品详情、图片分析、Listing 派生数据。
- 保留商品基础数据和新选中竞品。
- 进入：

```text
workflow_node = capture_competitor_detail
workflow_status = processing
```

### 8.5 抓取竞品详情

抓取成功：

```text
workflow_node = image_analysis
workflow_status = processing
```

抓取成功后允许自动触发图片分析。

抓取失败：

```text
workflow_node = capture_competitor_detail
workflow_status = failed
workflow_error = 失败原因
```

用户可操作：

- 重新抓取：回到 `capture_competitor_detail/processing`。
- 换竞品：按选择竞品规则清理后续派生数据并重新抓取。

### 8.6 图片分析

图片分析成功：

```text
workflow_node = listing_generation
workflow_status = processing
```

图片分析成功后允许自动触发 Listing 生成。

图片分析失败：

```text
workflow_node = image_analysis
workflow_status = failed
workflow_error = 失败原因
```

用户重试：

```text
workflow_node = image_analysis
workflow_status = processing
```

用户重新选图：

- 执行 destructive reset。
- 回到 `search_competitor/pending`。

### 8.7 Listing 生成

Listing 生成成功：

```text
workflow_node = flow_done
workflow_status = succeeded
workflow_error = null
```

Listing 生成失败：

```text
workflow_node = listing_generation
workflow_status = failed
workflow_error = 失败原因
```

用户重试：

```text
workflow_node = listing_generation
workflow_status = processing
```

Listing 成功后主铺货内容生成流程结束。用户导出或不导出，是后一阶段的事，不属于本主流程。

## 9. Destructive Reset 规则

重新选择主图或重新确认图片时，V1 采用 destructive reset，不做历史版本。

保留：

- 原始 GIGA 数据。
- 商品基础信息。
- 当前新主图和 Listing 图片。
- UPC、品牌等非流程派生字段。
- 已下载/生成的真实文件和导出记录本身，除非后续有明确清理任务。

清空或失效：

- StyleSnap 当前候选竞品。
- 当前选中竞品。
- 当前竞品详情抓取结果。
- 当前图片分析结果。
- 当前 Listing 生成结果。
- 当前待导出业务状态。
- 与旧竞品/旧 Listing 相关的 workflow error。

重置后：

```text
workflow_node = search_competitor
workflow_status = pending
workflow_error = null
```

禁止：

- 不做 `workflow_version`。
- 不保留旧候选与新候选并存判断。
- 不让旧竞品详情、旧图片分析、旧 Listing 继续满足当前流程前置条件。

## 10. 自动推进边界

允许自动推进：

- 选择竞品成功后，自动触发抓取竞品详情。
- 抓取竞品详情成功后，自动触发图片分析。
- 图片分析成功后，自动触发 Listing 生成。

不允许自动越过：

- 选择图片。
- 搜索竞品的用户触发。
- 选择竞品。
- Listing 完成后的导出/上传阶段。

前端可以在用户确认图片成功后立即调用搜索竞品接口，但图片确认接口和搜索接口职责必须分开。

## 11. Workflow Projection API

后端商品列表和详情应返回统一 workflow 对象。

建议结构：

```ts
workflow: {
  node_key: string
  node_label: string
  node_type: 'sync' | 'semi_sync' | 'async' | 'done'
  node_status: 'pending' | 'processing' | 'succeeded' | 'failed'
  work_status: string
  primary_action: string | null
  primary_action_label: string | null
  allowed_actions: string[]
  action_reason: string
  related_task_run_id?: number | null
  related_correlation_key?: string | null
}
```

### 11.1 Action 建议

```text
open_detail
open_image_review
search_competitor
open_competitor_review
retry_competitor_search
select_competitor
retry_competitor_capture
open_task_center
retry_image_analysis
retry_listing_generation
restart_from_images
open_export_center
```

### 11.2 work_status 建议

```text
select_images
get_stylesnap_token
search_competitor
select_competitor
capture_competitor_detail
image_analysis
listing_generation
flow_done
failed
```

筛选项可以按产品页面需要再细化，但不得使用 task status 作为商品主筛选。

## 12. 与任务中心的边界

任务中心负责：

- 异步任务的 queued/running/succeeded/failed/canceled/interrupted。
- step 进度和事件。
- retry/cancel/wake/mark interrupted。
- 错误细节和执行证据。

商品流程负责：

- 当前业务节点。
- 当前节点状态。
- 主操作。
- 自动推进。
- 商品业务失败原因。

异步节点进入任务中心时：

- 商品页面可以提供 `open_task_center`。
- 商品主状态仍是业务节点的 `processing/failed/succeeded`。
- task_run 状态不能直接覆盖商品 workflow。

## 13. StyleSnap 插件决策引用

StyleSnap / 搜索竞品长期合理方案是 Chrome 客户端插件模式，当前只记录，不推进。

决策记录：

- `docs/superpowers/specs/2026-06-17-stylesnap-client-extension-decision.md`

本 PRD 不实现插件，也不继续强化后端 AppleScript 控 Chrome 为长期方向。

## 14. 发布与迁移策略

### 14.1 数据

- V1 新增字段。
- V1 不做复杂存量迁移。
- 当前测试数据可以清空或重拉。
- 新拉回商品默认 `select_images/pending`。

### 14.2 兼容

- 旧字段先保留。
- 新商品流程 UI 和 API projection 优先读新 workflow 字段。
- 如果 workflow 字段为空，页面可以显示“待初始化/需重新拉品”，不要继续复杂猜测旧状态。

### 14.3 验证

- 新字段存在并可写。
- 新商品从 `select_images/pending` 开始。
- 每个节点转移都有项目规则或单元行为测试。
- 商品列表和详情使用同一 workflow projection。
- 前端不再用 `error_message` 正则决定主按钮。

## 15. 给听云的任务拆分建议

以下是后续派工模板。确认 PRD 后，若命应按阶段新建顶层 inbox message，不要一次性把所有阶段丢给听云。

### T1 - Workflow 字段和枚举常量

目标：

- 给 `products` 增加 `workflow_node/workflow_status/workflow_error/workflow_updated_at`。
- 增加后端枚举常量和校验 helper。

范围：

- `backend/app/models/models.py`
- `backend/app/database.py` 或迁移入口
- `backend/app/models/status.py` 或新 workflow constants 文件
- 项目规则测试

禁止：

- 不改前端页面。
- 不改任务中心。
- 不做存量复杂 backfill。
- 不碰导出和模板。

完成证据：

- backend compile。
- project rules。
- 字段/枚举静态检查。

### T2 - Product Workflow Service

目标：

- 新增 `backend/app/product_tasks/workflow.py`。
- 提供 `set_product_workflow()`、`build_product_workflow()`、node/action 映射。
- 商品列表/详情可通过该 service 得到统一 workflow object。

禁止：

- 不在多个文件散写 workflow 字段。
- 不靠 `error_message` 作为核心状态判断。
- 不从 task status 反推商品主状态。

完成证据：

- 行为测试覆盖每个 node/status 到 label/action 的映射。
- 商品列表和详情使用同一 projection helper。

### T3 - 新商品初始化和图片选择 reset

目标：

- 新商品默认 `select_images/pending`。
- 图片确认成功后 destructive reset 旧流程派生数据。
- 图片确认成功后进入 `search_competitor/pending`。

禁止：

- 图片确认接口不直接执行搜索竞品。
- 不做 workflow version。
- 不保留旧派生数据继续作为当前流程前置条件。

完成证据：

- 选择图片后 workflow 转移正确。
- 重新选图清理旧候选/选中竞品/分析/Listing 相关当前数据。
- 不清理源数据和受保护导出记录。

### T4 - 搜索竞品半同步节点收敛

目标：

- 搜索竞品接口按本文投影 workflow。
- 成功进入 `select_competitor/pending`。
- 普通失败进入 `search_competitor/failed`。
- token/browser 类问题进入 `get_stylesnap_token/pending`。

禁止：

- 不写 `task_runs`。
- 不新增任务中心入口。
- 不实现 Chrome 插件。
- 不做持久化后台队列。

完成证据：

- API 行为测试覆盖成功、普通失败、token/browser 失败。
- 页面显示来自 workflow，不靠前端正则。

### T5 - 选择竞品与抓取详情自动推进

目标：

- 选择竞品成功后进入 `capture_competitor_detail/processing`。
- 自动触发抓取详情。
- 抓取成功后进入 `image_analysis/processing` 并自动触发图片分析。
- 抓取失败进入 `capture_competitor_detail/failed`。

禁止：

- 不自动选择竞品。
- 不在抓取失败时强制清空候选。
- 不把抓取详情当同步操作。

完成证据：

- 选择竞品、换竞品、抓取成功、抓取失败均有行为测试。

### T6 - 图片分析 ProductTaskAction 投影

目标：

- 图片分析任务创建/复用成功：`image_analysis/processing`。
- 成功：`listing_generation/processing` 并触发 Listing 生成。
- 失败/取消/中断/超时：`image_analysis/failed`。

禁止：

- 商品主状态不显示 queued/running/canceled/interrupted。
- 不用旧 `pipeline.engine.is_running()` 判断新 workflow。

完成证据：

- ProductTaskAction 生命周期测试。
- 任务中心状态变化不直接覆盖商品 workflow。

### T7 - Listing ProductTaskAction 投影

目标：

- Listing 任务创建/复用成功：`listing_generation/processing`。
- 成功：`flow_done/succeeded`。
- 失败/取消/中断/超时：`listing_generation/failed`。

禁止：

- Listing 成功后不自动导出。
- 导出不进入主流程节点。

完成证据：

- Listing 生命周期测试。
- `flow_done/succeeded` 商品在列表/详情状态一致。

### T8 - 前端商品列表和详情消费 workflow

目标：

- 商品列表主状态、主按钮、筛选来源于后端 workflow。
- 商品详情流程节点展示来源于后端 workflow。
- 前端移除主流程 `error_message` 正则判断。

禁止：

- 不在前端重建业务状态机。
- 不把 task_run display status 当商品主状态。

完成证据：

- frontend build。
- 页面截图或观止 QA 前置样本。

### T9 - 删除旧路径和不用的逻辑

目标：

- 删除与新 workflow 冲突的旧 `status/current_step/error_message` 主状态推导。
- 删除已经不再使用的旧流程代码、旧按钮判断、旧状态映射和旧页面分支。
- 只保留仍被未迁移模块真实依赖的兼容字段读写；保留项必须逐项列出理由、调用方和后续移除条件。

禁止：

- 不删除数据库旧字段本身，除非另有迁移任务明确批准。
- 不破坏尚未迁移的导出/A+/老任务路径。
- 不把旧逻辑改名后继续保留。
- 不用“兼容”当理由留下无人调用或已经被新 workflow 覆盖的判断。

完成证据：

- scoped rg 证明主流程页面不再依赖旧猜测。
- project rules 增加防回归检查。
- 删除清单：列出删除了哪些旧路径/旧逻辑。
- 保留清单：列出仍保留的旧字段或兼容逻辑、保留原因和移除条件。

## 16. 镜花 Review 清单

镜花只做代码 review，不做 QA。

每阶段重点：

- 是否符合本文节点和状态定义。
- 是否有散写 workflow 字段。
- 是否继续用 `error_message/current_step` 猜主状态。
- 是否把 task status 泄漏成商品主状态。
- 是否引入 workflow version 或复杂历史分支。
- 是否把搜索竞品写入 task_runs。
- 是否自动越过人工节点。
- 是否清理旧派生数据时误删源数据、真实导出、真实 ASIN、模板产物。
- T9 是否真的删除旧路径和不用逻辑，而不是改名、旁路保留或用“兼容”包装继续使用旧状态判断。
- T9 保留清单是否逐项说明调用方、保留原因和移除条件；没有真实调用方的旧逻辑必须打回。
- SQL 是否简单可索引，禁止用复杂查询弥补模型缺陷。
- 测试是否证明关键状态转移，而不是只证明函数存在。

大阶段 review 必须写报告；小阶段可直接回 inbox。

## 17. 观止 QA 清单

观止只做 QA，不改代码。

QA 必须白盒说明：

- 测了哪个节点。
- 用了哪个 product_id。
- 前置数据是什么。
- 操作路径是什么。
- 期望 workflow 是什么。
- 实际 API workflow 是什么。
- 实际页面文案和按钮是什么。
- 是否触发副作用。

建议 QA 用例：

- 新商品默认待选图。
- 选择图片后进入待搜索竞品。
- 重新选图清空旧派生数据。
- 搜索竞品成功进入待选择竞品。
- 搜索竞品失败进入搜索失败。
- token/browser 类问题进入待获取 token。
- 选择竞品后自动抓取详情。
- 抓取详情成功后自动图片分析。
- 图片分析成功后自动 Listing。
- Listing 成功后 flow_done。
- 图片分析失败可重试，不回到选图。
- Listing 失败可重试，不回到图片分析。
- 导出不属于主流程。

PASS 必须有 API 和页面证据。缺样本写 BLOCKED，不用口头判断冒充 PASS。

## 18. 开放问题

当前无阻塞开放问题。

待用户确认后，若命再把本文拆成具体执行消息。确认前听云不得开工。
