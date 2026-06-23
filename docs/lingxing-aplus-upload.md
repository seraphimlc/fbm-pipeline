# Lingxing A+ Upload Existing Logic

状态：现有代码事实梳理
更新：2026-06-23

本文记录当前项目中“生成 A+ 后，通过领星 ERP 上传/提交到 Amazon A+”的既有能力。它不是新的打通方案；后续如要重新接入主流程或 Web UI，需要另起技术方案并做真实外部链路 QA。

## 结论

当前代码里仍保留领星 A+ 上传/提交能力：

- 后端服务仍在：`backend/app/services/aplus_upload.py`
- API 入口仍在：`POST /api/products/catalog/aplus-upload`
- 上传批次查询仍在：`GET /api/products/aplus-upload-batches`
- 数据表模型仍在：`aplus_upload_batches`, `aplus_upload_items`
- 前端 API client 仍在：`createAplusUploadBatch()`, `listAplusUploadBatches()`, `getAplusUploadBatch()`
- 旧上传批次页面组件仍在：`frontend/src/pages/AplusUploadList.tsx`

但当前 Web UI 入口不完整：`/aplus-upload` 在 `frontend/src/App.tsx` 中重定向到 `/aplus`，`AplusManagement.tsx` 只展示 `aplus_upload_status`，未看到调用 `createAplusUploadBatch()` 的按钮。因此可以认为“后端能力还在，前端触发入口已弱化或隐藏”。

## 关键入口

后端服务：

- `backend/app/services/aplus_upload.py`
  - `start_aplus_upload_batch(batch_id)`
  - `build_upload_item(catalog)`
  - `_run_batch(batch_id)`
  - `_run_item(item_id, auth, submit)`
  - `_get_lingxing_auth()`
  - `_collect_aplus_images(product)`
  - `_upload_image(client, auth, path, alt_text)`
  - `_save_aplus(client, auth, asin, item_code, product_id, uploaded, submit)`

后端 API：

- `backend/app/api/products.py`
  - `POST /api/products/catalog/aplus-upload`
  - `GET /api/products/aplus-upload-batches`
  - `GET /api/products/aplus-upload-batches/{batch_id}`

Schema：

- `backend/app/api/schemas.py`
  - `AplusUploadCreateRequest`
  - `AplusUploadBatchResponse`
  - `AplusUploadItemResponse`
  - `AplusUploadBatchDetail`
  - `PaginatedAplusUploadBatches`

模型：

- `backend/app/models/models.py`
  - `Product.aplus_upload_status`
  - `Product.aplus_uploaded_at`
  - `Product.aplus_upload_error`
  - `CatalogProduct.aplus_upload_status`
  - `CatalogProduct.aplus_uploaded_at`
  - `CatalogProduct.aplus_upload_error`
  - `AplusUploadBatch`
  - `AplusUploadItem`

前端：

- `frontend/src/api/index.ts`
  - `createAplusUploadBatch(catalogProductIds, store, submitForApproval)`
  - `listAplusUploadBatches(params)`
  - `getAplusUploadBatch(id)`
- `frontend/src/pages/AplusManagement.tsx`
  - 当前展示 `aplus_upload_status`
  - 当前只看到 A+ 生成/重跑按钮，未看到上传按钮
- `frontend/src/pages/AplusUploadList.tsx`
  - 上传批次列表/明细组件仍存在
- `frontend/src/App.tsx`
  - `/aplus-upload` 当前重定向到 `/aplus`

## 外部接口

`backend/app/services/aplus_upload.py` 当前写死了以下领星 URL：

- `https://erp.lingxing.com/erp/aplusList`
- `https://gw.lingxingerp.com/amz/amz-data-transfer/amazon/aplus/uploadDestination`
- `https://gw.lingxingerp.com/amz/amz-data-transfer/amazon/aplus/add`
- `https://gw.lingxingerp.com/amz/amz-data-transfer/amazon/aplus/edit`

认证方式：

- 使用 `chrome_workflow("aplus_upload_auth")`
- 通过 `chrome_navigate()` 打开领星 A+ 页面
- 通过 `chrome_get_cookie_for_domain("erp.lingxing.com")` 读取本机 Chrome Cookie
- 通过 `chrome_execute_js()` 读取页面状态、`localStorage.language`、`sessionStorage.loginEnv`、`location.origin`
- 从 Cookie 中解析 `zid`、`envKey`、`authToken`、`uid`、`company_id`
- 构造领星网关请求头，包括 `Cookie`、`auth-token`、`X-AK-*`、`Origin`、`Referer`

这意味着该能力依赖本机 Chrome 已登录领星 ERP，且依赖当前领星 Web 网关参数仍兼容。

## 执行流程

1. 调用 `POST /api/products/catalog/aplus-upload`，传入 `catalog_product_ids`、`store`、`submit_for_approval`。
2. API 查询 `CatalogProduct`，要求商品资料已经 `confirmed_at`，否则拒绝。
3. API 创建 `AplusUploadBatch`，并为每个商品创建 `AplusUploadItem`。
4. `build_upload_item()` 预检：
   - 读取真实 ASIN：优先 `CatalogProduct.amazon_asin`，其次 `Product.amazon_asin`
   - 读取商品 code：优先 `CatalogProduct.item_code`，其次 `ProductData.item_code`
   - `document_name` 形如 `{asin}_{item_code}_{source_product_id}`
   - 缺真实 ASIN 时标记 `skipped`
   - `amazon_product_status` 不包含售卖/在售/可售/active/buyable/正常时标记 `skipped`
5. API 提交 DB 后调用 `start_aplus_upload_batch(batch.id)`，用进程内 `asyncio.create_task()` 启动批次。
6. `_run_batch()` 将批次置为 `running`，获取领星认证。
7. `_run_item()` 逐个商品执行：
   - 将 Product/Catalog 的 `aplus_upload_status` 置为 `running`
   - 读取商品、`ProductData`、`ProductAplus`
   - `_collect_aplus_images()` 收集前 5 张已完成 A+ 图片
   - `_upload_image()` 请求领星 `uploadDestination`，再把图片上传到返回的 S3/form URL
   - `_save_aplus()` 调领星 `amazon/aplus/add` 保存 A+ 内容
   - 若 `submit_for_approval=true` 且返回草稿 `idHash`，再调 `amazon/aplus/edit?idHash=...` 提交审批
8. 成功后：
   - `AplusUploadItem.status = success`
   - Product/Catalog `aplus_upload_status = submitted` 或 `draft_saved`
   - 写入 `aplus_uploaded_at`
   - 保存 `uploaded_images` 和截断后的 `lingxing_response`
9. 失败后：
   - item 标记 `failed`
   - Product/Catalog `aplus_upload_status = failed`
   - 写入 `aplus_upload_error`
10. 批次根据 item 状态汇总为 `completed` 或 `partial`。

## A+ 内容要求

`_collect_aplus_images()` 当前要求：

- `Product.aplus.aplus_images` 存在
- 至少 5 张图片 `status == "done"` 且有 `path`
- 只取排序后的前 5 张
- 每张图片必须是本地文件
- 图片尺寸至少 `970x600`
- alt text 从 `aplus_plan.modules` 的 `headline` / `subheading` / `key_message` 取，最多 100 字；否则回退 listing title/source title/ASIN

`_save_aplus()` 当前模块结构：

- `contentType = "EBC"`
- `locale = "en-US"`
- 每张图生成一个 `STANDARD_HEADER_IMAGE_TEXT`
- 模块内 headline/body 为空，主要提交图片和 altText

## 状态与保护

上传状态字段同时存在于 Product 和 CatalogProduct：

- `not_uploaded`
- `pending`
- `running`
- `submitted`
- `draft_saved`
- `failed`
- `skipped`

当前保护相关事实：

- `backend/app/services/product_protection.py` 会把已有 A+ 上传/上传中证据作为后续 destructive reset 的保护条件。
- `backend/app/services/aplus_auto_trigger.py` 的 A+ 自动生成 eligibility 也会因 `aplus_upload_status` 或 `aplus_uploaded_at` 阻断，避免覆盖已上传/上传中的 A+。
- `backend/app/product_tasks/actions.py` 和 `backend/app/pipeline/engine.py` 会在同步 CatalogProduct 时携带 Product 的 A+ 上传状态。

## 当前断点和风险

当前能力后续重打通前需要重点复核：

- Web UI 入口不完整：`AplusUploadList.tsx` 组件仍在，但 `/aplus-upload` 被重定向，`AplusManagement.tsx` 未看到上传触发按钮。
- 执行是进程内 `asyncio.create_task()`，不属于新 `task_runs` runtime；服务重启、并发、恢复、审计能力弱于新任务中心。
- 认证依赖本机 Chrome 领星登录态和页面 local/session storage；不适合无头服务或远程部署直接复用。
- 领星网关 URL、headers、返回结构可能随 ERP 版本变化；需要真实账号环境验证。
- 图片上传仍依赖本地 A+ 图片路径；这和当前“尽量 URL 优先”的主流程方向不同，后续需要决定是保留本地文件上传，还是改为可追踪的素材/OSS 输入。
- 当前上传模块只提交 5 个 `STANDARD_HEADER_IMAGE_TEXT` 图片模块，是否满足最新领星/Amazon A+ 模板质量需要业务验收。
- `submit_for_approval=true` 默认自动提交审批；后续重新启用时应明确高风险 gate，不能让自动主流程无确认发布到 Amazon。
- Store 当前默认 `"Andy店-US"` / `DEFAULT_STORE_ID = 17983`，需要配置化和多店铺确认。
- 上传成功写 `submitted` / `draft_saved`，但未形成新任务中心事件；后续 QA 和审计需要补可追踪证据。
- 项目已有 `backend/app/services/asin_sync.py` 可通过领星 Listing 查询回写 ASIN 和 Amazon 商品状态，但当前 `build_sync_item()` 优先 UPC、无 UPC 才用 `item_code/MSKU`。A+ 发布前的 ASIN 对齐应以 Amazon 导入模板中的 seller code/MSKU 为主匹配键；UPC 只能作为辅助查询或诊断，不能优先于 seller code/MSKU，否则可能错配多变体或历史 Listing。

## 后续打通建议

后续如果要把“生成 A+ 后自动发布到 Amazon”重新纳入主流程，建议单独设计：

1. 先把现有 `aplus_upload.py` 能力收敛成明确 service/action 边界。
2. 不直接挂在 Listing/A+ 生成后自动提交审批；先做显式人工触发。
3. 新增或迁移到 `task_runs`，保留批次、step、event、失败重试和恢复能力。
4. 将 Chrome 登录态检查、领星 API 调用、图片上传、A+ 保存/提交拆成可测试步骤。
5. 上传前必须有 preview/gate：真实 ASIN、店铺、A+ 图片、提交审批开关、影响商品清单。
6. 成功/失败必须写 Product/Catalog 状态，并写 task event / evidence。
7. QA 必须使用真实领星登录态和真实 Amazon 可售 ASIN，不得用 fixture 或 mock 当真实发布通过。

## 2026-06-23 只读浏览器学习

用户已在本机 Chrome 登录领星 ERP。只读检查结果：

- 首页：`https://erp.lingxing.com/erp/home`
- A+ 列表：`https://erp.lingxing.com/erp/aplusList`
- 添加 A+：`https://erp.lingxing.com/erp/addAplus`

A+ 列表页当前可见：

- 筛选项：国家、店铺、A+状态、A+类型、修改时间、商品描述名称。
- 操作按钮：`添加A+`、`同步`。
- 表格列：商品描述名称、店铺、国家、A+状态、A+类型、最后修改时间、操作。

添加 A+ 页当前可见：

- 必填字段：店铺、语言、商品描述名称。
- 内容区域：内容模块、预览、添加内容模块。
- ASIN 区：`添加ASIN`。
- 底部动作：`取消`、`保存`、`提交`。
- `添加内容模块` 弹窗当前可见 17 种标准模块：标准公司徽标、标准图片和浅文本覆盖、标准图片和深文本覆盖、带文字的标准图片标题、标准单一左侧图片、标准单一右侧图片、标准单一图片和标注、标准单一图片和规格详细信息、标准单一图片和侧边栏、标准三个图片和文本、标准四个图片和文本、标准四个图片/文本象限、标准多图片模块、标准比较图、标准技术规格、标准文本、标准商品描述文本。
- `带文字的标准图片标题` 对应旧代码使用的 `STANDARD_HEADER_IMAGE_TEXT`；页面显示图片要求为 `970*600像素`，字段包含标题、图片、副标题和正文。

`添加ASIN` 弹窗当前可见：

- 筛选项：Listing状态、ASIN、搜索内容。
- 表格列：图片、ASIN、标题、状态、店铺、国家。
- 底部动作：关闭、确定。

设计影响：

- 页面已经把 `保存` 和 `提交` 分离，自动链路默认应只做保存草稿；提交审批必须显式配置或用户明确触发。
- A+ 发布依赖领星 Listing 侧已有可选 ASIN；缺 ASIN / 缺 Listing 状态应进入同步或等待，不应当作 A+ 上传失败。
- 当前页面支持多种 A+ 模块；旧代码只提交 5 个 `STANDARD_HEADER_IMAGE_TEXT` 图片模块，且标题/body 基本为空。它可能能技术保存，但内容质量是否合格需要业务验收。
- 当前学习未点击保存、提交或确定，未写入领星数据。

当前前端脚本中确认的相关接口：

- 列表：`/amz/amz-data-transfer/amazon/aplus/list`
- 同步列表：`/amz/amz-data-transfer/amazon/aplus/syncList`
- 执行同步：`/amz/amz-data-transfer/amazon/aplus/sync`
- 暂停：`/amz/amz-data-transfer/amazon/aplus/pause?idHash=...`
- 操作日志：`/amz/amz-data-transfer/aplus/operatorLog/query`
- 新增：`/amz/amz-data-transfer/amazon/aplus/add`
- 编辑：`/amz/amz-data-transfer/amazon/aplus/edit?idHash=...`
- 已关联 ASIN：`/amz/amz-data-transfer/amazon/aplus/getRelationAsins?idHash=...`
- 图片上传地址：`/amz/amz-data-transfer/amazon/aplus/uploadDestination`
- 选择可关联 Listing：`/listing-api/api/popLightListing`

同步语义待验证：

- `syncList` / `sync` 是领星页面暴露的 A+ 同步能力，但当前尚未确认它是只从 Amazon 拉回状态、只同步指定店铺列表，还是能确认某个新保存草稿在 Amazon A+ 草稿箱可见。
- 后续实现不能把“调用 sync 成功”等同于 `draft_visible`。
- 正确证据应是同步后能用列表/详情唯一匹配目标 `idHash`、ASIN、店铺、站点和状态，或由真实 Amazon/Seller Central A+ 草稿箱页面确认。
- 若只能看到领星列表 `草稿`，状态只能写 `draft_saved`，并记录 `amazon_draft_visibility=unconfirmed`。

## 2026-06-23 测试账号写入验证

用户明确授权在已登录的 Chrome 测试账号和测试店铺中执行保存/提交。验证环境：

- 领星页面：`https://erp.lingxing.com/erp/addAplus` / `https://erp.lingxing.com/erp/editAplus`
- 店铺：`idea_lc@163.com-US`
- 国家：美国
- 语言：英语（美国）
- ASIN：`B0DJW98XM3`
- A+ 类型：基本 A+
- 测试 A+ 名称：`TEST DO NOT USE - Codex A+ 20260623 1429`
- 测试图片：`/Users/liuchang/Documents/gitproject/fbm-pipeline/tmp/lingxing-aplus-test/test-aplus-970x600.png`

实际 UI 验证结果：

1. 在添加 A+ 页面选择店铺、语言、名称、`B0DJW98XM3` ASIN。
2. 添加模块 `带文字的标准图片标题`，上传 970x600 测试图片。
3. 填写标题、副标题和正文后点击 `保存`，页面返回 A+ 列表，记录状态为 `草稿`。
4. 从列表进入编辑页后发现富文本正文为空；补回正文：
   `This is a controlled test draft generated in a test account. Do not use for production.`
5. 点击编辑页底部 `提交` 后，页面返回 A+ 列表。
6. 列表首行显示该测试记录状态为 `已提交`，最后修改时间为 `2026-06-23 15:45:02`。

结论：

- 真实领星 Web UI 的“保存草稿”和“提交”路径在测试账号中可走通。
- `带文字的标准图片标题` 模块配 970x600 图片、标题、副标题、正文可以通过 UI 提交。
- 编辑页加载后富文本正文可能丢失或未正确回显；自动化实现不能只依赖保存后重新打开页面仍完整，应在保存/提交前校验最终 payload 或页面字段。
- 这次验证只证明 Web UI 交互路径可行，不证明旧后端 `aplus_upload.py` 的网关 API 调用当前仍可直接生产复用。
- 这次验证只确认领星列表中可见 `草稿` / `已提交` 状态，没有确认 Amazon Seller Central A+ 草稿箱是否同步可见。后续应把“领星草稿已保存”和“Amazon 草稿箱已可见/已同步”拆成两个状态或两个证据。
- 自动链路默认仍应保存草稿；提交审批只能在显式配置或人工触发下执行。

## 2026-06-23 STANDARD_HEADER_IMAGE_TEXT 非空 payload 结构

M2.0 证据见 `docs/collaboration/reviews/2026-06-23-lingxing-standard-header-image-text-payload.md`。本轮没有点击保存或提交，没有产生新的领星草稿副作用。

确认来源：

- 已登录 Chrome 中的 Lingxing 测试 `editAplus` 页面只读 DOM。
- 当前页面公开前端 bundle：
  - `https://static.distributetop.com/erp/js/contentModule-0af405eb.js`
  - `https://static.distributetop.com/erp/js/asinModule-4c23da27.js`

确认事实：

- `STANDARD_HEADER_IMAGE_TEXT` / “带文字的标准图片标题”模块结构为 `standardHeaderImageText: { headline, block }`。
- 页面“标题”写入 `standardHeaderImageText.headline.value`。
- 页面“副标题”写入 `standardHeaderImageText.block.headline.value`。
- 页面“正文”写入 `standardHeaderImageText.block.body.textList`。
- `body.textList` 不是 string list，而是 rich-text object list；plain text item 形如：

```json
[
  {
    "value": "正文文本",
    "decoratorSet": []
  }
]
```

- 富文本样式通过 `decoratorSet` 表达；前端 bundle 中可见 `STYLE_BOLD`、`STYLE_ITALIC`、`STYLE_UNDERLINE`、`LIST_ITEM`、`LIST_ORDERED`、`LIST_UNORDERED`。
- 保存按钮调用 `confirm(0)`，最终请求体含 `submitFlag=0`；提交按钮调用 `confirm(1)`，最终请求体含 `submitFlag=1`。

## 2026-06-23 T3.5 module mapper 落地口径

新增发布模块事实源和 mapper：

- `backend/app/aplus_publish/module_registry.py`
  - 首版只支持 `standard_header_image_text_v1` / `STANDARD_HEADER_IMAGE_TEXT`。
  - 图片要求为至少 `970x600`，支持 position `1..5`，必填字段为 `headline` 和可映射 body。
  - failure codes 包括 unsupported profile/module type、module count/position、headline/body missing、asset count/position/size mismatch 等。
- `backend/app/services/lingxing_aplus_module_mapper.py`
  - `preflight_validate()` 在任何 Lingxing auth、`uploadDestination`、对象存储上传和 `amazon/aplus/add` 前校验 plan/profile/type/headline/body/count/position/local assets。
  - `assemble_payload()` 只在 preflight PASS 且图片上传成功后注入 `uploadDestinationId` 和 crop data，生成 `contentModuleList`。

当前自动草稿保存 payload 约束：

- `standardHeaderImageText.headline` 和 `standardHeaderImageText.block.headline` 都使用 `{ "value": "...", "decoratorSet": [] }`。
- `standardHeaderImageText.block.body.textList` 使用 rich-text object list：`[{ "value": "...", "decoratorSet": [] }]`，不得写 string list 或空数组。
- 新生成 Step7 plan / Step8 script 显式携带 `publish_profile=standard_header_image_text_v1` 和 `lingxing_content_module_type=STANDARD_HEADER_IMAGE_TEXT`。
- 旧 plan 缺 profile/type 不做静默迁移，发布任务本地 fail closed，不保存半成品草稿。

验证入口：

```bash
cd backend && .venv/bin/python ../scripts/test_lingxing_aplus_module_mapper.py
cd backend && .venv/bin/python ../scripts/test_lingxing_aplus_publish_policy.py
cd backend && .venv/bin/python ../scripts/test_lingxing_aplus_publish_tasks.py
make test-project-rules
```

未改变范围：仍不确认 `draft_visible`，不提交审批，不把领星发布状态并入商品主 workflow / `work_status`。真实领星草稿字段可见性仍需后续观止 QA。

## 快速定位

```bash
rg -n "aplus_upload|AplusUpload|aplus-upload|lingxing_response|uploadDestination|amazon/aplus|lingxing_aplus_module_mapper|module_registry" backend/app frontend/src
```
