# Product Workflow Node State PRD

状态：讨论定稿版；后续商品流程、任务框架、页面状态和 QA 均以本文为产品口径。
更新：2026-06-17
负责人：若命
适用范围：Amazon 商品铺货链路；TikTok 链路后续单独定义，不复用 Amazon 类目/竞品/导出口径。

## 1. 一句话结论

商品状态只表达业务节点和业务结果，不表达任务执行细节。

商品流程节点分为同步节点、半同步节点和异步节点。同步/半同步节点不进任务中心；异步节点可以进任务中心，但商品侧只关心节点结果，不关心 task_run 的 queued、running、canceled、interrupted、retrying 等执行细节。

## 2. 核心原则

### 2.1 商品状态是业务事实

商品状态回答的是：

- 商品现在处在哪个业务节点。
- 这个业务节点是否待处理、处理中、成功或失败。
- 用户下一步应该做什么。

商品状态不回答：

- 后台任务是否 queued。
- 后台任务是否 running。
- 后台任务是否 canceled、interrupted、timeout。
- 后台任务第几次 retry。
- 后台任务哪个 step 失败。

这些执行事实归任务中心或具体执行工具展示。

### 2.2 任务状态不能污染商品主状态

异步任务创建后，商品进入该业务节点的“执行中”。任务排队、运行、取消、中断、超时、worker 异常，都不需要新增商品主状态。

对商品来说：

- 任务成功：业务节点成功。
- 任务失败、取消、中断、超时：业务节点失败。
- 失败原因可以写入 `error_message` 或关联任务/候选记录，但商品主状态不为每种技术失败扩枚举。

### 2.3 前端不重新实现业务规则

前端只消费后端返回的商品 workflow / node state / allowed action。

前端禁止自己用 `Product.status/current_step/error_message/task_run.display_status` 拼业务规则。页面可以展示任务中心入口，但不把任务状态当商品主状态。

### 2.4 StyleSnap 竞品搜索不进任务中心

StyleSnap 竞品搜索依赖用户浏览器、Amazon 登录态、StyleSnap token 和页面上下文。它不是稳定后台任务，不承诺服务重启恢复，不进入 task runtime。

后续长期方案记录为 Chrome 客户端插件模式，见 `MSG-20260617-020`。在插件正式推进前，商品流程仍按本文节点语义设计。

## 3. 节点类型定义

### 3.1 同步节点

同步节点由用户动作当场完成，不进入任务中心。

特征：

- 用户在页面上确认或选择。
- 成功后立即进入下一业务节点。
- 失败通常是表单校验或操作错误，不形成长期商品节点状态。
- 不展示 task status。

当前同步节点：

- 选择图片。
- 选择竞品。

### 3.2 半同步节点

半同步节点由用户手动触发，执行依赖当前浏览器/外部页面状态，不进入任务中心。

特征：

- 可以短时后台执行，但不是持久化任务。
- 不承诺服务重启恢复。
- 用户不需要等待请求完成；失败后可以手动重试。
- 商品只展示业务结果，不展示队列或任务细节。

当前半同步节点：

- 搜索竞品（StyleSnap 图片搜索）。

### 3.3 异步节点

异步节点可以后台执行，可以进入任务中心。

特征：

- 业务执行耗时较长。
- 可失败、可重试、可记录执行事件。
- 商品侧统一四态：待进入、执行中、成功、失败。
- task_run 的 queued/running/canceled/interrupted/retrying 只在任务中心展示。

当前异步节点：

- 抓取选中竞品详情。
- 图片分析。
- Listing 生成。
- 导出生成。

## 4. Amazon 商品流程节点

### 4.1 节点总览

| 顺序 | 节点 | 类型 | 待进入 | 执行中 | 成功 | 失败 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 选择图片 | 同步 | 待选择图片 | 不适用 | 已选择图片，进入下一节点 | 操作错误，不形成长期状态 |
| 2 | 获取 StyleSnap token | 前置/同步 | 待获取 StyleSnap token | 不适用 | 可搜索竞品 | 仍待获取 token |
| 3 | 搜索竞品 | 半同步 | 待搜索竞品 | 竞品搜索中 | 待选择竞品 | 竞品搜索失败 |
| 4 | 选择竞品 | 同步 | 待选择竞品 | 不适用 | 已选择竞品，进入下一节点 | 操作错误，不形成长期状态 |
| 5 | 抓取选中竞品详情 | 异步 | 待抓取竞品详情 | 竞品详情抓取中 | 竞品详情抓取完成 | 竞品详情抓取失败 |
| 6 | 图片分析 | 异步 | 待图片分析 | 图片分析中 | 图片分析完成 | 图片分析失败 |
| 7 | Listing 生成 | 异步 | 待生成 Listing | Listing 生成中 | Listing 生成完成 | Listing 生成失败 |
| 8 | 导出生成 | 异步 | 待导出 | 导出生成中 | 导出完成 | 导出失败 |

### 4.2 选择图片

类型：同步节点。

完成条件：

- 用户确认主图。
- 用户确认 Listing 图片。

完成后流向：

- 进入 StyleSnap token / 搜索竞品相关节点。
- 前端可以立即请求后端尝试启动竞品搜索，但页面不等待搜索完成。

禁止：

- 不自动越过用户确认图片。
- 不把图片选择状态写成任务状态。

### 4.3 获取 StyleSnap token

类型：搜索竞品的前置同步节点。

含义：

- 当前商品已具备搜索竞品的业务条件，但当前用户浏览器没有可用 Amazon StyleSnap token。
- 这是业务上的“待获取 token”，不是 task status。

页面动作：

- 引导用户打开 Amazon StyleSnap / 登录 Amazon / 授权浏览器插件。
- token 可用后，用户可以触发搜索竞品。

禁止：

- 后端不保存 Amazon token。
- 后端不保存 Amazon cookie。
- 不因为缺 token 创建任务中心任务。

### 4.4 搜索竞品

类型：半同步节点。

口径：

- 搜索竞品依赖用户浏览器和 Amazon 页面上下文。
- 不进入任务中心。
- 不承诺服务重启恢复。
- 失败后用户手动重试。

状态：

- 待搜索竞品：主图已确认，尚未成功生成候选。
- 竞品搜索中：用户已触发搜索，系统正在尝试获取候选。
- 待选择竞品：候选已写入，可人工选择。
- 竞品搜索失败：本次搜索失败，可手动重试。

错误归类：

- token 缺失或失效：商品进入待获取 StyleSnap token。
- Chrome / 插件 / Amazon 页面不可用：商品进入待获取 StyleSnap token 或竞品搜索失败，错误原因必须清楚。
- Amazon 未返回候选、图片不可用、解析失败：商品进入竞品搜索失败。

禁止：

- 不写 `task_runs`。
- 不展示 queued/running。
- 不做服务重启恢复。
- 不自动批量静默搜索。

长期方案：

- 最合理方案是 Chrome 客户端插件：插件在 Amazon 页面上下文读取 token、上传图片、解析结果并回传本地后端。
- 插件方案暂不执行，已在 `MSG-20260617-020` 记录为 on hold。

### 4.5 选择竞品

类型：同步节点。

完成条件：

- 用户从候选中选择一个参考竞品。

完成后流向：

- 进入抓取选中竞品详情节点。

禁止：

- 不自动替用户选择竞品。
- 候选信息不完整时，页面应允许用户判断或重抓详情，但不能绕过用户选择。

### 4.6 抓取选中竞品详情

类型：异步节点。

四态：

- 待进入：已选择竞品，但尚未开始抓取详情。
- 执行中：竞品详情抓取中。
- 成功：竞品详情抓取完成，满足后续图片分析前置条件。
- 失败：竞品详情抓取失败。

说明：

- 该节点可以进入任务中心，因为它是选中竞品后的后台补全动作。
- 失败后商品状态显示抓取失败，任务细节在任务中心或候选详情中查看。

### 4.7 图片分析

类型：异步节点。

四态：

- 待进入：图片、竞品、竞品详情等前置条件满足，但尚未提交分析。
- 执行中：图片分析任务已创建、入队或执行。
- 成功：图片分析完成。
- 失败：图片分析失败。

重要口径：

- 商品不区分图片分析 queued 和 running。
- 任务 canceled、interrupted、timeout 均投影为图片分析失败。
- 商品页可以提供查看任务入口，但商品主状态仍是图片分析中或图片分析失败。

### 4.8 Listing 生成

类型：异步节点。

四态：

- 待进入：图片分析完成，尚未提交 Listing 生成。
- 执行中：Listing 生成任务已创建、入队或执行。
- 成功：Listing 生成完成，进入待导出。
- 失败：Listing 生成失败。

重要口径：

- 商品不区分 Listing queued 和 running。
- 任务 canceled、interrupted、timeout 均投影为 Listing 生成失败。

### 4.9 导出生成

类型：异步节点。

四态：

- 待进入：Listing 完成，商品待导出。
- 执行中：导出文件生成中。
- 成功：导出完成。
- 失败：导出失败。

注意：

- 已有真实 Amazon ASIN 的商品不得再次导出 Amazon 导入表格，沿用项目级规则。
- Step 10 只负责生成导入表格和风险提示，最终仍需人工上传/确认。

## 5. 商品 workflow 返回口径

后端应向商品列表和商品详情返回统一 workflow 字段。字段名后续实现可调整，但语义必须稳定。

建议结构：

```ts
workflow: {
  node_key: string
  node_label: string
  node_type: 'sync' | 'semi_sync' | 'async'
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

字段说明：

- `node_key`：业务节点，例如 `select_images`、`search_competitor`、`image_analysis`。
- `node_type`：节点类型。
- `node_status`：商品业务节点状态，不是 task status。
- `work_status`：商品列表筛选用业务状态。
- `primary_action`：页面主操作。
- `related_task_run_id/related_correlation_key`：仅异步节点需要；用于跳转任务中心，不用于覆盖商品状态。

禁止：

- `node_status` 不得直接等于 task_run.display_status。
- `work_status` 不得通过 task_run queued/running/canceled/interrupted 直接生成。
- `error_message` 只能作为补充说明，不能作为核心状态机唯一判断依据。

## 6. 商品状态与任务状态映射

异步节点的 ProductTaskAction 生命周期必须投影商品状态。

### 6.1 reserve / create

任务创建或复用成功后：

- 商品进入该节点的执行中。
- 商品可保存关联 `task_run_id` 或 `correlation_key`。
- 商品不需要知道任务是 queued 还是 running。

### 6.2 success

任务成功后：

- 商品进入该节点成功。
- 如有下一节点，商品 workflow 指向下一节点。
- 必要时同步 `catalog_products`。

### 6.3 failed / canceled / interrupted / timeout

任务失败、取消、中断、超时后：

- 商品进入该节点失败。
- 失败原因写入 `error_message` 或任务事件。
- 商品主状态不拆 canceled/interrupted/timeout。

## 7. 前端展示与操作

商品列表和详情页：

- 展示业务节点和业务状态。
- 主按钮来自 `workflow.primary_action`。
- 可以提供“查看任务中心”入口，但只作为辅助。
- 不展示 task queued/running/canceled/interrupted 作为商品主状态。

任务中心：

- 展示任务执行细节。
- 提供 retry、cancel、wake、mark interrupted 等任务操作。
- 不反向定义商品业务阶段。

## 8. 非目标

本 PRD 不做以下事项：

- 不设计 TikTok 链路。
- 不实现 Chrome 插件。
- 不把 StyleSnap 搜索迁入任务中心。
- 不一次性重构全部 `products.py`。
- 不改 Step 10、Amazon 模板、`template_mappings`。
- 不触碰真实 ASIN、人工类目、已生成素材或导出产物。

## 9. 后续实施建议

下一轮若进入实现，应先拆成小任务：

1. 商品 workflow 业务节点模型整理。
2. 商品列表/详情统一消费后端 workflow。
3. ProductTaskAction 生命周期按本文四态投影。
4. StyleSnap 搜索节点按半同步口径收敛展示，不进入任务中心。
5. 镜花做代码 review，观止按页面路径 QA。

听云不得在没有新任务定义时直接实现本文。若本文与代码现实冲突，先写 `REQUEST` 给若命或直接向用户确认。
