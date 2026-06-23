# Lingxing A+ Publish After A+ Done PRD

状态：reviewed，镜花方案评审 `PASS_WITH_CONSTRAINTS`，已派发听云写整体技术方案；技术方案通过若命和镜花 gate 前不直接编码。
日期：2026-06-23

## 1. 背景

商品主链路已经按“自动推进到待导出”设计；A+ 生成已经按独立派生链路设计为：商品进入 `flow_done/succeeded` / 待导出后，可按配置自动创建 `aplus_generate` 任务。

用户进一步提出：旧系统里还有一段通过领星 ERP 把 A+ 发布到 Amazon 的能力。目标是在 A+ 生成完成后，把领星 A+ 上传/保存/提交审批链路也串起来。

当前事实见 `docs/lingxing-aplus-upload.md`：

- 旧后端服务仍在：`backend/app/services/aplus_upload.py`。
- 旧 API 仍在：`POST /api/products/catalog/aplus-upload`。
- 旧批次表仍在：`aplus_upload_batches`, `aplus_upload_items`。
- 旧前端批次页组件仍在，但 `/aplus-upload` 目前重定向到 `/aplus`，实际页面触发入口弱化。
- 旧执行方式是进程内 `asyncio.create_task()`，不是新 `task_runs`。
- 旧领星认证依赖本机 Chrome 登录态和领星页面 cookie/localStorage/sessionStorage。
- 旧上传要求 A+ 图片是本地文件。
- 旧接口默认 `submit_for_approval=true`，这对重新接自动链路来说风险过高。
- 旧服务当前还存在实现问题：`_run_item()` 使用 `settings.external_http_verify`，但文件未导入 `settings`，说明旧能力不能未经整理直接复用。

2026-06-23 只读浏览器学习补充：

- 用户已在本机 Chrome 登录领星 ERP，首页为 `https://erp.lingxing.com/erp/home`。
- 旧代码中的 A+ 页面路径 `https://erp.lingxing.com/erp/aplusList` 仍可访问，页面标题为“领星ERP - 跨境电商管理系统”。
- A+ 列表页可见筛选项：国家、店铺、A+状态、A+类型、修改时间、商品描述名称。
- A+ 列表页可见操作：`添加A+`、`同步`。
- `添加A+` 打开 `https://erp.lingxing.com/erp/addAplus`，表单包含必填字段：店铺、语言、商品描述名称。
- 添加页底部明确分离 `保存` 和 `提交` 两个按钮。这支持自动链路默认只保存草稿、提交审批单独受控的设计。
- 添加页有 `添加ASIN` 弹窗；弹窗从领星 Listing 列表选择 ASIN，筛选项包含 Listing状态、ASIN/搜索内容，表格列包含图片、ASIN、标题、状态、店铺、国家。
- 这说明 A+ 发布前置确实依赖领星 Listing 侧已存在可选 ASIN；缺 ASIN 或 Listing 状态未同步时，应进入同步/等待状态，而不是直接判定 A+ 上传失败。
- A+ 发布前不能临时人工猜选 ASIN。当前项目链路是先准备商品和 Amazon 导入 Excel，Amazon 侧导入后才为每个商品生成 ASIN；因此必须先从领星 ERP 拉回 Listing/商品数据，并用导入时的 seller code/MSKU 与本地 `CatalogProduct` / `Product` 对齐，得到可信 ASIN 后才能创建 A+。
- 当前前端路由配置显示 `/aplusList` 的页面权限/API meta 是 `amazon/aplus/list`，实际请求路径是 `/amz/amz-data-transfer/amazon/aplus/list`。
- `/addAplus` 的页面权限/API meta 是 `amazon/aplus/add`，实际保存/提交请求路径是 `/amz/amz-data-transfer/amazon/aplus/add`；编辑路径是 `/amz/amz-data-transfer/amazon/aplus/edit?idHash=...`。
- A+ 列表页当前脚本还包含 `/amz/amz-data-transfer/amazon/aplus/syncList`、`/amz/amz-data-transfer/amazon/aplus/sync`、`/amz/amz-data-transfer/amazon/aplus/pause?idHash=...` 和 `/amz/amz-data-transfer/aplus/operatorLog/query`。
- `添加ASIN` 弹窗使用 `/listing-api/api/popLightListing` 查询可关联 Listing；编辑页还会用 `/amz/amz-data-transfer/amazon/aplus/getRelationAsins?idHash=...` 读取已关联 ASIN。
- 图片上传仍是 `/amz/amz-data-transfer/amazon/aplus/uploadDestination` 获取 `uploadDestinationId/url`，再把文件上传到返回的对象存储 URL。
- “添加内容模块”弹窗当前可见 17 种标准模块；旧代码使用的 `STANDARD_HEADER_IMAGE_TEXT` 对应页面里的“带文字的标准图片标题”，该模块图片要求显示为 `970*600像素`，字段包含标题、图片、副标题和正文。

2026-06-23 测试账号写入验证补充：

- 用户授权后，已在测试店铺 `idea_lc@163.com-US` 用真实领星 Web UI 创建测试 A+：`TEST DO NOT USE - Codex A+ 20260623 1429`。
- 使用 ASIN `B0DJW98XM3`、模块 `带文字的标准图片标题`、970x600 测试图片、标题、副标题和正文，点击 `保存` 后记录进入列表并显示 `草稿`。
- 从编辑页补回正文后点击 `提交`，列表首行显示状态 `已提交`，最后修改时间 `2026-06-23 15:45:02`。
- 编辑页加载后曾出现富文本正文为空的情况；实现时必须在保存/提交前校验最终内容事实，不能假设保存后的页面回显一定完整。
- 该验证证明真实 Web UI 保存/提交路径可行，但不等于旧后端 `aplus_upload.py` 的网关 API 直接可生产复用。

## 2. 核心结论

领星 A+ 发布不能并入商品主 workflow，也不能直接挂旧 `start_aplus_upload_batch()`。

正确链路不是一条单线，而是两条前置链路汇合后再发布：

```text
商品主流程完成 -> export_ready

本地 A+ 内容链：
export_ready -> A+ 自动生成任务 -> ProductAplus.aplus_status=done

ASIN 回流链：
Amazon Excel 导出 -> 人工/外部导入 Amazon -> 领星 Listing 拉取
-> seller code/MSKU 对齐 -> 得到可信 ASIN / Amazon 在售状态

领星发布链：
ProductAplus.done + ASIN 已对齐
-> 建领星 A+ 草稿并关联 ASIN
-> 保存草稿
-> 确认 Amazon A+ 草稿可见/已同步
-> 可选提交审批
```

商品主流程、A+ 生成、ASIN 回流、领星发布是四个层次不同的边界：

- 商品主流程只负责商品从大健数据走到待导出。
- A+ 生成只负责生成本地 A+ 内容和图片，不需要等 ASIN。
- ASIN 同步只负责把 Amazon 导入后的外部 ASIN 事实按 seller code/MSKU 回流到本地。
- 领星发布只负责把已生成的 A+ 内容绑定已对齐 ASIN 并写入外部平台。

任何领星失败都不能把商品主流程从待导出回退，也不能改写 `Product.workflow_node/workflow_status`。

### 2.1 节点边界

| 节点 | 输入 | 输出 | 是否依赖 ASIN | 失败影响 |
| --- | --- | --- | --- | --- |
| `aplus_generate_product` | 商品资料、图片、Listing 文案 | `ProductAplus.aplus_status=done`、A+ 图片 | 否 | 不影响商品待导出 |
| `lingxing_listing_sync_product` | seller code/MSKU、店铺、站点 | 可信 ASIN、Amazon 状态、匹配证据 | 是，本节点产出 ASIN | 不影响 A+ 本地内容 |
| `lingxing_aplus_publish_product` | A+ 内容、已对齐 ASIN、店铺 | 领星草稿、`idHash`、状态证据 | 是 | 不影响商品主流程和本地 A+ done |
| `lingxing_aplus_draft_visibility_product` | `idHash`、ASIN、店铺、站点 | `draft_visible` 或 `unconfirmed` | 是 | 不影响已保存草稿 |
| `lingxing_aplus_submit_product` | 已保存/可见草稿、用户确认或显式配置 | `submitted` | 是 | 不回退草稿，只写提交失败 |

`aplus_generate_product` 和 `lingxing_listing_sync_product` 可以并行或先后执行；`lingxing_aplus_publish_product` 必须等二者都满足。

## 3. 目标

1. A+ 生成完成后，可按配置自动进入领星发布前置检查。
2. A+ 发布前必须完成领星 Listing 拉取与 seller code/MSKU 对齐，不能在提交前临时搜索或猜选 ASIN。
3. 缺 ASIN、缺 Amazon 商品状态、状态未同步、seller code 无法唯一匹配时，不直接失败；进入可解释的前置等待或自动触发同步/对齐。
4. 领星 A+ 上传/保存/提交迁移到新 `task_runs`，获得恢复、重试、审计和任务中心可见性。
5. 默认动作是保存草稿，不默认提交审批。
6. 所有状态和任务类型必须集中定义，避免散落在 API、页面、任务、统计里各写一份。
7. QA 必须覆盖真实领星登录态、真实 ASIN、真实可售状态和真实外部返回；fixture 只能证明内部逻辑。
8. 保存/提交前必须有内容完整性校验，特别是富文本正文、图片上传结果、ASIN 关联和最终提交动作。
9. 区分“领星草稿已保存”和“Amazon A+ 草稿箱已可见/已同步”，不能把前者直接当成后者。

## 4. 非目标

- 不把领星发布放进 Amazon 商品主 workflow。
- 不让商品列表 `work_status` 增加领星发布中、领星失败等状态。
- 不默认自动提交审批。
- 不在商品详情 GET、商品列表 GET 或页面加载时触发发布。
- 不绕过领星登录、验证码、权限或风控。
- 不解决多服务实例下的分布式浏览器登录态共享；初版按单服务实例设计。
- 不实现 Amazon Seller Central 导入 Excel 的动作；本 PRD 假设 Amazon 导入已由现有导出/人工导入链路完成。
- 不把未对齐 ASIN 的商品自动创建 A+；ASIN 对齐失败必须等待同步、等待人工处理或标记可解释状态。

## 5. 触发策略

### 5.1 默认配置

新增配置建议：

```text
AUTO_LINGXING_APLUS_AFTER_DONE=false
LINGXING_APLUS_SUBMIT_FOR_APPROVAL=false
LINGXING_APLUS_STORE_NAME=Andy店-US
LINGXING_APLUS_STORE_ID=17983
```

含义：

- `AUTO_LINGXING_APLUS_AFTER_DONE=false`：默认不自动发布，只保留手动触发。
- `LINGXING_APLUS_SUBMIT_FOR_APPROVAL=false`：自动链路默认只保存草稿。
- 提交审批必须由显式配置、手动按钮或后续用户确认开启。

### 5.2 允许触发入口

允许：

- `aplus_generate_product` success hook，在 `ProductAplus.aplus_status=done` 已提交后 best-effort 触发。
- A+ 管理页手动选择商品后触发。
- 任务中心对失败或等待项重试。
- 后续可增加受控维护扫描，用于服务重启后补齐 `done` 但未进入领星检查的商品。

不允许：

- 商品列表 GET。
- 商品详情 GET。
- A+ 管理页加载。
- 旧 `asyncio.create_task()` 裸后台任务作为自动链路默认执行器。

## 6. 状态模型

### 6.1 状态归属

领星发布状态使用现有 `aplus_upload_status` 字段承载，但必须新增集中 registry，例如：

```text
backend/app/aplus_publish/status.py
```

建议以 `CatalogProduct.aplus_upload_status` 为主事实，`Product.aplus_upload_status` 作为兼容镜像。所有写入必须经过同一个 service，不允许 API、worker、旧 pipeline 分散写状态。

### 6.2 状态清单

所有状态长度必须兼容当前 `String(20)` 字段，除非本阶段明确改表。

```text
not_uploaded      未进入领星发布
checking          正在检查前置条件
waiting_listing   等待 Listing / ASIN 对齐
syncing_listing   正在同步 Listing / ASIN
ready_to_upload   前置满足，等待上传
uploading         正在上传/保存 A+
draft_saved       已保存草稿
draft_confirming  正在确认 Amazon 草稿可见性
draft_visible     Amazon 草稿已可见/已同步
submitted         已提交审批
failed            执行失败，可重试
skipped           明确跳过，不自动重试
auth_required     领星登录态缺失，需要人工登录
```

### 6.3 状态语义

- `not_uploaded`：初始态或 reset 后状态。
- `checking`：只用于短时任务运行态，不应长期停留。
- `waiting_listing`：缺真实 ASIN、缺 Amazon 商品状态、seller code/MSKU 未唯一对齐、状态不是已知可售，但可以通过领星 Listing 同步恢复。
- `syncing_listing`：已经创建或正在执行领星 Listing 拉取、seller code/MSKU 对齐、ASIN/Amazon 状态同步任务。
- `ready_to_upload`：前置满足，但尚未开始上传。
- `uploading`：正在读取本地 A+ 图片、上传到领星返回的对象存储、保存领星 A+ 文档。
- `draft_saved`：领星已保存草稿，但尚未确认 Amazon A+ 草稿箱可见性。
- `draft_confirming`：正在通过领星同步/查询或人工 QA 确认 Amazon A+ 草稿是否可见。
- `draft_visible`：已确认 Amazon A+ 草稿箱或领星同步回流状态可见；自动链路默认成功终点应优先落到这个状态。
- `submitted`：已提交审批；只有显式开启提交审批时才允许产生。
- `failed`：内部代码、图片、接口、外部返回等失败，可由任务中心重试。
- `skipped`：保护门或业务规则明确不应自动处理，例如已有上传证据、商品不属于 Amazon 链路。
- `auth_required`：领星未登录、Cookie 缺失、浏览器权限不足。它不是代码失败，应提示人工处理后重试。

### 6.4 草稿可见性证据

`draft_saved`、`draft_visible`、`submitted` 必须用不同证据支撑：

- `draft_saved`：领星 `amazon/aplus/add` 或 Web UI 保存成功，且领星列表能看到该 A+ 记录。
- `draft_visible`：在 `draft_saved` 之后，通过领星同步/查询结果或 Amazon Seller Central A+ 草稿箱页面确认该草稿对 Amazon 侧可见。
- `submitted`：通过领星 `amazon/aplus/edit` / Web UI 提交动作后，领星列表或 Amazon 侧状态进入已提交/审核中/同等含义。

禁止：

- 只因为 `amazon/aplus/add` 返回成功就写 `draft_visible`。
- 只因为领星列表显示 `草稿` 就声称 Amazon 草稿箱已可见。
- 只因为调用了 `/amazon/aplus/sync` 就写 `draft_visible`；必须读取同步后的列表/详情/外部状态并匹配目标 `idHash`、ASIN、seller code/MSKU。

## 7. 前置条件

创建领星发布任务前必须检查：

- `ProductAplus.aplus_status == "done"`。
- `ProductAplus.aplus_images` 存在，且满足领星上传要求。
- A+ 图片本地文件存在，当前旧领星上传能力不能 URL 直传。
- `CatalogProduct.confirmed_at` 存在，说明商品已进入待导出。
- 本地商品必须有稳定 seller code/MSKU 对齐键。优先使用 Amazon 导入 Excel 实际写入的 seller code/MSKU；当前可映射到 `CatalogProduct.item_code` / `ProductData.item_code`，如果导出模板使用了不同字段，必须新增并持久化该字段，例如 `amazon_seller_sku`。
- `CatalogProduct.amazon_asin` 或 `Product.amazon_asin` 存在真实 ASIN，且该 ASIN 必须来自 seller code/MSKU 对齐结果或经过同等强度校验。
- `CatalogProduct.amazon_product_status` 或 `Product.amazon_product_status` 是可售状态。
- 没有 active 领星发布 task。
- 没有 `draft_saved/submitted/uploading` 等保护状态。
- 店铺配置明确，不能继续写死在业务逻辑里。

### 7.1 ASIN 对齐节点

`lingxing_listing_sync_product` 的职责不是“随便查一下 ASIN”，而是把 Amazon 导入后的外部事实拉回本地：

1. 输入本地商品的 seller code/MSKU、店铺、站点、可选 UPC、商品标题和本地商品 id。
2. 调领星 Listing 能力拉取或查询 Listing 数据。
3. 用 seller code/MSKU 做主匹配键，与领星返回的 `msku` / 商品编码 / seller SKU 字段精确匹配。
4. 找到唯一有效 Listing 后，读取 ASIN、Listing 状态、店铺、国家、标题等证据。
5. 校验店铺、国家、seller code/MSKU、ASIN 格式和 Listing 状态。
6. 写回 `CatalogProduct.amazon_asin` / `Product.amazon_asin`、`amazon_product_status`、`asin_sync_status`、同步时间和匹配证据。
7. 只有对齐成功且状态可售，A+ 发布节点才允许使用该 ASIN。

对齐规则：

- 主匹配键是导入模板中的 seller code/MSKU，不是页面上临时输入的 ASIN。
- UPC 只能作为辅助查询或诊断字段，不能在 A+ 发布链路里优先覆盖 seller code/MSKU；否则可能把同 UPC、多变体或历史 Listing 错配到当前商品。
- 匹配 0 条：进入 `waiting_listing`，提示可能尚未从 Amazon/领星同步完成。
- 匹配多条：进入 `waiting_listing` 或 `multiple_found` 类错误，不自动选择第一条。
- 匹配到删除、暂停、非目标店铺、非目标站点、不可售状态：不允许创建 A+，写清楚阻塞原因。
- 已有本地 ASIN 但领星按 seller code/MSKU 拉回的 ASIN 不一致：阻断发布，等待人工确认或专门修复任务；不能静默覆盖。

如果 ASIN、seller code/MSKU 对齐结果或 Amazon 状态缺失：

- 不写 `failed`。
- 写 `waiting_listing` 或 `syncing_listing`。
- 创建或复用领星 Listing 拉取与 ASIN 对齐任务。
- 同步成功后再进入发布检查。

### 7.2 草稿可见性确认节点

`confirm_draft_visibility` 在 `save_draft` 后执行。职责是确认“领星草稿”是否已经成为 Amazon 侧可见草稿。

输入：

- 领星 A+ `idHash`。
- A+ document name。
- seller code/MSKU。
- ASIN。
- 店铺、站点。
- `save_draft` 的原始响应摘要。

允许的确认方式：

1. 调领星 A+ 列表/详情查询，确认目标 `idHash`、ASIN、店铺、站点和状态。
2. 必要时调用领星 A+ 同步接口，再重新查询列表/详情。
3. 若领星无法证明 Amazon 侧可见，则由观止通过真实 Amazon/Seller Central A+ 草稿箱页面确认。

通过条件：

- 能唯一定位到目标 A+。
- 目标 A+ 关联的是已通过 seller code/MSKU 对齐的 ASIN。
- 状态明确表示 Amazon 侧草稿可见、已同步、已提交或已批准之一。
- 证据中要保存查询时间、接口/页面来源、原始状态文本和目标匹配字段。

未通过但不算失败的情况：

- 领星保存成功，但同步延迟导致暂时无法确认 Amazon 草稿箱可见。
- 领星只显示本地草稿，未提供 Amazon 侧可见证据。
- 领星同步接口返回处理中。

这些情况保持 `draft_saved`，记录 `amazon_draft_visibility=unconfirmed`，允许后续重试确认。

如果 Amazon 状态明确不是可售：

- 写 `waiting_listing` 或 `skipped` 的选择取决于状态来源：
  - 状态过期或未同步：进入同步。
  - 状态新鲜且明确不可售：写 `skipped`，错误信息说明不可售。

### 7.3 数据字段和证据归属

现有可复用字段：

- `Product.amazon_asin` / `CatalogProduct.amazon_asin`
- `Product.asin_sync_status` / `CatalogProduct.asin_sync_status`
- `Product.asin_synced_at` / `CatalogProduct.asin_synced_at`
- `Product.asin_sync_error` / `CatalogProduct.asin_sync_error`
- `Product.amazon_product_status` / `CatalogProduct.amazon_product_status`
- `Product.amazon_product_status_synced_at` / `CatalogProduct.amazon_product_status_synced_at`
- `Product.aplus_upload_status` / `CatalogProduct.aplus_upload_status`
- `Product.aplus_uploaded_at` / `CatalogProduct.aplus_uploaded_at`
- `Product.aplus_upload_error` / `CatalogProduct.aplus_upload_error`
- `CatalogProduct.item_code` / `ProductData.item_code`
- `AsinSyncItem.lookup_code`、`matched_code`、`amazon_asin`、`amazon_product_status`
- `AplusUploadItem.amazon_asin`、`item_code`、`document_name`、`uploaded_images`、`lingxing_response`

必须新增或迁移的字段：

```text
CatalogProduct.amazon_seller_sku: String(100), nullable
Product.amazon_seller_sku: String(100), nullable
  Amazon 导入 Excel 实际写入的 seller code/MSKU。
  若确认始终等于 item_code，也要由导出时显式写入同值；不能靠运行时猜。

CatalogProduct.asin_match_source: String(50), nullable
Product.asin_match_source: String(50), nullable
  例如 lingxing_listing、manual_verified、legacy_import。

CatalogProduct.asin_match_evidence_json: Text, nullable
Product.asin_match_evidence_json: Text, nullable
  保存匹配店铺、站点、seller sku、ASIN、Listing 状态、领星 row id / raw 摘要、同步任务 id。

AplusUploadItem.lingxing_aplus_id_hash: String(100), nullable
  领星 A+ add/edit 返回或页面 URL 中的 idHash。

AplusUploadItem.lingxing_status_text: String(100), nullable
  领星列表/详情原始状态文本，例如 草稿、已提交、已批准。

AplusUploadItem.amazon_draft_visibility: String(30), default unconfirmed
  unconfirmed / visible / not_visible / sync_pending / failed。

AplusUploadItem.draft_visible_at: DateTime, nullable
AplusUploadItem.submitted_at: DateTime, nullable

AplusUploadItem.publish_evidence_json: Text, nullable
  保存草稿、同步查询、草稿可见性确认、提交审批的证据摘要。
```

字段归属规则：

- `CatalogProduct` 是 Amazon 导出后可运营商品事实主表；ASIN、seller sku、Amazon 状态和 A+ 发布状态以它为主。
- `Product` 字段只做兼容镜像，写入必须通过同一 service 同步，不允许一个入口只写 Product、另一个入口只写 CatalogProduct。
- 详细外部响应不要全部塞进 Product/Catalog；放在 `AplusUploadItem.publish_evidence_json`、`TaskStep.result_json`、`TaskStepEvent.data_json`。
- 真实外部原文要截断或脱敏；不能把 cookie、auth token、完整请求头写入 DB 或日志。
- 如果实现决定不新增 `AplusUploadItem` 字段，而改用新表，例如 `lingxing_aplus_publish_items`，必须保留以上语义和索引能力。

建议索引/约束：

- `catalog_products.amazon_seller_sku`
- `catalog_products.amazon_asin`
- `catalog_products.aplus_upload_status`
- `aplus_upload_items.lingxing_aplus_id_hash`
- `aplus_upload_items.amazon_draft_visibility`

迁移要求：

- 现有测试数据可丢弃，不需要为历史脏数据做复杂兼容。
- 迁移后必须有 schema/bootstrap 脚本和项目规则测试防止字段缺失导致本地启动失败。

## 8. 任务中心设计

### 8.1 新任务类型

建议新增四类 task，其中后两类可以先作为 `lingxing_aplus_publish_product` 的内部 step 实现，但 registry 和事件语义必须先定义清楚：

```text
lingxing_listing_sync
lingxing_listing_sync_product

lingxing_aplus_publish
lingxing_aplus_publish_product

lingxing_aplus_draft_visibility
lingxing_aplus_draft_visibility_product

lingxing_aplus_submit
lingxing_aplus_submit_product
```

说明：

- `lingxing_listing_sync` 负责从领星拉取 Listing 数据，并按 seller code/MSKU 对齐本地商品、真实 ASIN 和 Amazon 商品状态。
- `lingxing_aplus_publish` 负责上传 A+ 图片、创建/保存领星草稿，不默认提交审批。
- `lingxing_aplus_draft_visibility` 负责确认领星草稿是否在 Amazon A+ 草稿箱或领星同步回流状态中可见。
- `lingxing_aplus_submit` 负责显式提交审批，只能由用户动作或显式配置触发。
- 这些任务都应进入新 `task_runs` 或同一 `task_run` 的明确 step/group，不能继续用裸 `asyncio.create_task()`。

### 8.2 幂等规则

同一商品：

- 已有 active `lingxing_aplus_publish_product` 时，不重复创建。
- 已有 active `lingxing_listing_sync_product` 时，不重复创建。
- 已有 active `lingxing_aplus_draft_visibility_product` 时，不重复创建确认任务。
- 已有 active `lingxing_aplus_submit_product` 时，不重复提交。
- 已 `draft_saved/draft_visible/submitted` 时，不自动重复上传。
- 已 `submitted` 时，不自动提交审批。
- 失败重试必须复用当前商品和当前 A+ 版本事实，不得拿旧 A+ 图片或旧 ASIN 状态误判成功。
- A+ 发布任务必须记录使用的 seller code/MSKU、ASIN、店铺、站点和对齐任务 id；重试时若这些事实发生变化，必须重新跑前置检查。

建议 task metadata：

```text
dedupe_key=lingxing_aplus_publish:product:{product_id}:aplus:{product_aplus_id}
correlation_key=product:{product_id}:lingxing_aplus_publish

dedupe_key=lingxing_aplus_draft_visibility:product:{product_id}:idHash:{id_hash}
correlation_key=product:{product_id}:lingxing_aplus_publish

dedupe_key=lingxing_aplus_submit:product:{product_id}:idHash:{id_hash}
correlation_key=product:{product_id}:lingxing_aplus_publish
```

如果 `ProductAplus` 没有稳定版本号，则至少使用 `product_id` + `ProductAplus.updated_at` 或任务创建时记录的图片摘要。

### 8.3 Worker 步骤

`lingxing_aplus_publish_product` 内部建议拆成可审计步骤，但可以由一个 worker 顺序执行并写 events：

1. `check_prerequisites`
   - 读取 Product/Catalog/ProductAplus。
   - 判断 seller code/MSKU、ASIN 对齐状态、Amazon 状态、A+ 图片、本地文件、店铺、保护状态。
   - 如果未完成 seller code/MSKU -> ASIN 唯一对齐，创建或复用 `lingxing_listing_sync_product`，本发布任务等待或结束为可解释前置状态。
2. `ensure_lingxing_auth`
   - 通过本机 Chrome 读取领星登录态。
   - 登录缺失写 `auth_required`，不要当普通 `failed`。
3. `collect_aplus_images`
   - 读取 A+ 图片，校验本地文件和尺寸。
   - 记录将上传的文件路径、尺寸、alt text 来源。
4. `upload_images`
   - 调领星 `uploadDestination`。
   - 上传到领星返回的对象存储 URL。
5. `save_draft`
   - 调领星 `amazon/aplus/add`。
   - 成功写 `draft_saved`。
6. `confirm_draft_visibility`
   - 调领星 A+ 同步/查询能力，确认草稿是否已在 Amazon A+ 草稿箱或领星同步结果中可见。
   - 若只能在领星列表看到 `草稿`，但无法证明 Amazon 草稿箱可见，则保持 `draft_saved` 并记录 `amazon_draft_visibility=unconfirmed`。
   - 若已确认可见，写 `draft_visible`。
7. `submit_for_approval`
   - 仅当显式开启时执行。
   - 成功写 `submitted`。

## 9. 代码边界

### 9.1 必须拆分的能力层

旧 `aplus_upload.py` 需要拆出能力层，不能继续把批次、状态、浏览器认证、HTTP 调用、图片读取混在一个文件里。

建议边界：

```text
app/services/lingxing_auth.py
  - 获取领星登录态和 headers

app/services/lingxing_aplus_client.py
  - uploadDestination
  - upload binary to returned storage URL
  - add A+ document
  - edit/submit A+ document

app/services/aplus_publish_assets.py
  - 收集 ProductAplus 图片
  - 校验本地文件和尺寸
  - 生成 alt text

app/services/aplus_publish_policy.py
  - 前置条件、保护门、状态决策
  - seller code/MSKU 与 ASIN 对齐结果校验

app/services/lingxing_listing_client.py
  - 查询/拉取领星 Listing
  - 返回标准化 Listing 行，至少包含 store/country/msku/asin/status/title/raw

app/task_planners/lingxing_aplus_publish.py
  - 创建/复用 task_runs

app/task_planners/lingxing_listing_sync.py
  - 创建/复用 Listing 拉取与 ASIN 对齐任务

app/task_runtime/lingxing_aplus_publish_workers.py
  - 执行 worker，写 task event 和业务状态

app/task_runtime/lingxing_listing_sync_workers.py
  - 执行 Listing 拉取、seller code/MSKU 对齐、ASIN/Amazon 状态回写
```

### 9.2 不允许的实现方式

- 不允许从 `aplus_generate` worker 里直接调用旧 `_run_batch()`。
- 不允许在 API 里创建 DB 批次后继续 `start_aplus_upload_batch()` 当作自动链路。
- 不允许把 `submit_for_approval=true` 作为自动链路默认值。
- 不允许在 A+ 发布 worker 里临时搜索页面并选第一个 ASIN。
- 不允许绕过 seller code/MSKU 对齐，直接使用页面搜索结果或历史残留 ASIN。
- 不允许把缺 ASIN / 缺 Amazon 状态 / seller code 无法唯一匹配统一写成上传失败。
- 不允许让 Product 和 CatalogProduct 的 A+ 上传状态各自散写。
- 不允许用 fixture 或 mock 响应声明真实领星发布通过。

## 10. 外部依赖和瓶颈

### 10.1 真实浏览器依赖

当前领星认证依赖本机 Chrome：

- 需要用户已经登录领星 ERP。
- 需要本机 Chrome 可被控制。
- 需要 Cookie、localStorage、sessionStorage 中的字段仍与当前领星页面一致。
- 远程服务器、无 GUI 环境、容器环境不能直接复用。

因此初版部署口径：

- 单服务实例。
- 单个或低并发领星任务执行。
- 领星登录失效时写 `auth_required`，等待人工登录后重试。

### 10.2 并发和限速

领星发布不是高并发任务。

建议：

- 同一时间只运行 1 个 `lingxing_aplus_publish` worker，或使用全局 semaphore。
- 商品间可以排队，不要并发打开多个浏览器认证流程。
- HTTP 请求要有限速、超时和结构化错误。

### 10.3 多实例风险

如果未来服务集群化：

- 必须有 DB lease 或分布式锁，保证同一商品只被一个 worker 发布。
- 领星登录态需要变成受控凭据/会话管理，不再依赖某台机器的本机 Chrome。
- `task_runs` worker 要按 worker group 或 queue 分配到具备领星浏览器能力的节点。

本 PRD 初版不实现集群模式，但代码不能写死到无法演进。

## 11. UI 和 API

### 11.1 A+ 管理页

A+ 管理页应展示：

- A+ 生成状态。
- 领星发布状态。
- 最近任务入口。
- 错误原因。
- 是否需要领星登录。
- 保存草稿/提交审批的明确差异。

允许操作：

- 手动触发领星发布。
- 对失败项重试。
- 对 `auth_required` 项在人工登录后重试。
- 对已 `draft_saved/draft_visible` 项手动提交审批，前提是用户明确点击；若仅 `draft_saved` 且草稿可见性未确认，页面必须提示风险。

### 11.2 旧上传批次页

旧 `AplusUploadList.tsx` 可以保留为历史批次查看，但新入口应优先接任务中心。

后续要么：

- 把旧批次页改成任务中心入口和历史上传证据页。
- 要么明确标为 legacy，只读展示，不再作为新发布入口。

## 12. 阶段拆分

### L1 - 方案和状态收敛

交付：

- 新增本 PRD。
- 新增领星发布状态 registry 设计。
- 明确 Product/Catalog 状态主从关系。
- 明确配置项和默认值。
- 听云提交整体技术方案，不写代码；方案必须覆盖数据迁移、task 设计、旧代码拆分、真实外部验证入口。

Gate：

- 若命评审 PRD。
- 镜花方案审查，重点看边界、状态、外部风险和任务中心承载方式。

### L2 - 前置同步任务中心化

交付：

- 将领星 Listing 拉取、seller code/MSKU 对齐、ASIN/Amazon 状态同步迁移或包装到 `task_runs`。
- 新增 `lingxing_listing_sync` / `lingxing_listing_sync_product`。
- 缺 ASIN / 缺 Amazon 状态 / 未完成 seller code 唯一对齐时创建或复用同步任务。
- 同步结果写 Product/Catalog 的 ASIN、Amazon 状态、对齐状态、同步时间和匹配证据。
- 当前旧 `asin_sync.py` 如被复用，必须调整为 A+ 发布前置语义：seller code/MSKU 优先，UPC 只做辅助，不允许 UPC 优先导致错配。

Gate：

- 代码 review 必须证明不会把缺前置误写为发布失败，也不会绕过 seller code/MSKU 对齐。
- 行为脚本覆盖同步缺失、同步成功、同步失败、重复触发、0 匹配、多匹配、ASIN 冲突、非目标店铺/站点。

### L3 - 领星 A+ 发布任务中心化

交付：

- 拆分旧 `aplus_upload.py` 能力层。
- 新增 `lingxing_aplus_publish` / `lingxing_aplus_publish_product`。
- 默认只保存草稿。
- 增加草稿可见性确认：保存领星草稿后，不直接宣称 Amazon 草稿箱同步成功；必须通过领星同步/查询结果或真实 Seller Central/Amazon A+ 草稿箱 QA 确认。
- 状态通过 registry/service 统一写入 Product/Catalog。
- 任务中心可查看进度、错误、外部响应摘要。

Gate：

- 镜花 code review。
- 行为脚本覆盖本地图片缺失、尺寸不足、未登录、保存草稿成功、草稿可见性未确认、草稿可见性确认成功、接口失败、重复触发。

### L4 - A+ done 后自动触发

交付：

- `aplus_generate_product` success 后按配置触发领星发布前置检查。
- 默认关闭。
- 开启后：前置满足且 ASIN 已通过 seller code/MSKU 对齐才创建发布任务；前置缺失创建同步/对齐任务；外部失败不影响 A+ done 和商品待导出。

Gate：

- 行为脚本覆盖 config off、config on、缺 ASIN、已有 active task、已草稿、已提交、未登录。
- 行为脚本必须覆盖 seller code/MSKU 未对齐、对齐成功、对齐冲突后不创建发布任务。
- 商品主 workflow 不被领星状态污染。

### L5 - 页面和人工闸

交付：

- A+ 管理页展示领星发布状态和任务入口。
- 支持手动保存草稿、重试、提交审批。
- 提交审批必须有清晰按钮和确认，不由默认自动链路触发。

Gate：

- 观止 QA 使用当前测试数据当真实场景跑页面路径。
- 提交审批路径必须经过用户确认或显式配置。

### L6 - 真实外部链路验收

交付：

- 使用真实领星登录态。
- 使用真实 ASIN 和可售商品。
- 验证保存草稿。
- 验证保存草稿后是否能同步/确认到 Amazon A+ 草稿箱状态。
- 如用户确认，再验证提交审批。

Gate：

- 观止 QA 只在真实外部返回下给 PASS。
- fixture/mock 只能标为内部行为通过，不能标为真实发布通过。

### 推荐派工方式

第一轮只派听云写整体技术方案，不直接编码。技术方案过若命和镜花 gate 后，再拆开发任务：

1. `T1 数据与状态基础`
   - 新增/迁移字段。
   - 新增状态 registry 和统一写入 service。
   - 加项目规则测试，保证状态全集、字段、任务类型消费端闭合。
2. `T2 ASIN 对齐任务中心化`
   - 改造或替换旧 `asin_sync.py`。
   - seller code/MSKU 优先，UPC 只辅助。
   - 结果写 Product/Catalog 和 task evidence。
3. `T3 领星 A+ 草稿创建`
   - 拆旧 `aplus_upload.py` 能力层。
   - 新增上传图片、保存草稿、记录 `idHash` 和 `draft_saved`。
   - 不做提交审批。
4. `T4 草稿可见性确认`
   - 接入领星 A+ 查询/同步结果。
   - 不能确认时保持 `draft_saved + amazon_draft_visibility=unconfirmed`。
   - 能确认时写 `draft_visible`。
5. `T5 页面与任务中心展示`
   - A+ 管理页展示 ASIN 对齐、领星草稿、草稿可见性、提交审批状态。
   - 提供手动重试/确认入口。
6. `T6 显式提交审批`
   - 只在用户点击或显式配置下执行。
   - 需要二次确认和独立任务/step。

每个 T 都必须有：

- 技术方案中的对应章节。
- 行为脚本或规则测试。
- 镜花 code review 范围。
- 观止是否入场的判定。T1-T4 默认先由镜花把代码和证据 gate 住，T5-T6 再让观止做真实路径 QA。

## 13. 验证要求

代码级：

- `cd backend && python -m compileall -q app`
- `make test-project-rules`
- 新增专项行为脚本，例如：
  - `scripts/test_lingxing_aplus_publish_policy.py`
  - `scripts/test_lingxing_aplus_publish_tasks.py`

行为覆盖：

- `ProductAplus.aplus_status=done` 但配置关闭，不创建发布任务。
- 配置开启且前置完整，创建一个发布任务。
- 重复触发不重复创建。
- 缺 ASIN 或 seller code/MSKU 未对齐，进入 `waiting_listing` 或 `syncing_listing`。
- 领星返回 0 条匹配，不创建 A+ 发布任务。
- 领星返回多条匹配，不自动选择，不创建 A+ 发布任务。
- 领星返回 ASIN 与本地已有 ASIN 冲突，阻断发布并记录证据。
- 未登录领星进入 `auth_required`。
- A+ 图片缺本地文件进入 `failed`，错误明确。
- 保存草稿成功写 `draft_saved`。
- 保存草稿后未确认 Amazon 草稿箱可见时，不写 `draft_visible`。
- 通过领星同步/查询或真实页面确认 Amazon 草稿箱可见后，才写 `draft_visible`。
- 提交审批只有显式开启时才写 `submitted`。
- 领星失败不影响商品 `flow_done/succeeded` 和 A+ `done`。

真实 QA：

- 本机 Chrome 已登录领星。
- 目标商品已经完成 Amazon 导入，领星 Listing 中能按 seller code/MSKU 唯一匹配到真实 ASIN。
- Amazon 商品状态是可售。
- A+ 图片本地存在且尺寸满足要求。
- 真实保存草稿后能在领星页面看到结果。
- 真实保存草稿后能在 Amazon A+ 草稿箱或领星同步回流结果中确认可见。
- 若执行提交审批，需用户确认该商品允许提交。

## 14. 待确认问题

1. 自动链路首版是否只做到 `draft_saved`，还是必须做到 `draft_visible`。若命建议：技术任务先保存草稿，再增加确认节点；验收口径不能把 `draft_saved` 冒充 `draft_visible`。
2. 是否允许后续通过配置打开自动 `submitted`。若命建议真实 QA 通过后再开。
3. 是否需要把旧 `AplusUploadBatch/AplusUploadItem` 继续作为发布证据表，还是只保留历史记录，新链路以 `task_runs` 为主。若命建议初版可复用表存外部响应摘要，但执行事实以 `task_runs` 为主。
4. 领星店铺是否只有 `Andy店-US / 17983`。若多店铺，配置和 UI 必须显式选择。
5. Amazon 导入 Excel 中实际作为 seller code/MSKU 的字段是否始终等于 `CatalogProduct.item_code` / `ProductData.item_code`。若不是，必须新增 `amazon_seller_sku` 等字段保存导出时的真实 seller code。
6. A+ 模块是否继续用 5 个 `STANDARD_HEADER_IMAGE_TEXT`。这需要业务验收，不应由代码默认认为最新可用。
7. 旧代码当前只提交 5 个 `STANDARD_HEADER_IMAGE_TEXT` 图片模块，且标题/body 基本为空；真实页面支持更多模块和文本字段。若继续使用该结构，只能算“技术可保存”，不能默认算“内容质量合格”。

## 15. 给执行者的要求

方案评审记录：

- `docs/collaboration/reviews/2026-06-23-lingxing-aplus-publish-prd-review.md`

听云实现前必须先提交整体技术方案，至少覆盖：

- 状态 registry 和写入服务。
- task 类型、planner、worker、event、幂等设计。
- 领星 Listing 拉取与 seller code/MSKU -> ASIN 对齐方案。
- 旧 `aplus_upload.py` 拆分方案。
- ASIN/Listing 同步如何接入新任务中心。
- 配置项默认值和风险闸。
- 数据迁移或兼容策略。
- 测试脚本和真实 QA 入口。

镜花审查时必须重点看：

- 是否仍有裸 `asyncio.create_task()` 承载新链路。
- 是否有状态散写或状态全集不闭合。
- 是否把外部前置缺失误判为发布失败。
- 是否绕过 seller code/MSKU 对齐直接选 ASIN。
- 是否保留了 UPC 优先导致错配的旧逻辑。
- 是否默认提交审批。
- 是否用 fixture 冒充真实领星发布。
- 是否让领星发布污染商品主 workflow。

观止 QA 时必须区分：

- 内部行为脚本 PASS。
- 页面路径 PASS。
- 真实领星保存草稿 PASS。
- 真实提交审批 PASS。

这些结论不能互相替代。
