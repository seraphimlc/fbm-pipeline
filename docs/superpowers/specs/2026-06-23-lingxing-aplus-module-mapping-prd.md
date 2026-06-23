# Lingxing A+ Module Mapping PRD

状态：draft，T4 `draft_visible` 前置 gate
日期：2026-06-23

## 1. 背景

T3 已证明新 `lingxing_aplus_publish` 任务可以通过真实领星链路保存 A+ 草稿，但观止补验发现当前草稿的 5 个模块全部是 `STANDARD_HEADER_IMAGE_TEXT`，且标题、副标题、正文均为空。

这说明当前链路只完成了“图片保存进领星草稿”，没有完成“A+ 内容结构按生成结果可信落到领星模块”。如果继续做 T4 `draft_visible`，只会把一个内容结构不完整的草稿继续往外部状态推进。

当前代码事实：

- A+ 规划在 `backend/app/pipeline/step7_aplus_plan.py` 生成 5 个语义模块，字段包含 `type`、`headline`、`subheading`、`key_message`、`text_content`、`conversion_goal`、`buyer_objection` 等。
- A+ 脚本在 `backend/app/pipeline/step8_aplus_script.py` 把模块转为 5 张 1940x1200 出图脚本。
- A+ 出图在 `backend/app/pipeline/step9_aplus_image.py` 生成一张图对应一个模块。
- T3 发布在 `backend/app/services/lingxing_aplus_publish_policy.py` 只收集 5 张本地图片和 alt text。
- T3 发布 client 在 `backend/app/services/lingxing_aplus_publish_client.py` 的 `_module_payload()` 里把每张图硬编码为 `STANDARD_HEADER_IMAGE_TEXT`，并把 `headline.value`、`block.headline.value`、`block.body.textList` 写空。
- `docs/lingxing-aplus-upload.md` 记录真实页面可见 17 种标准模块，但当前已确认的 API payload 只有旧代码使用的 `STANDARD_HEADER_IMAGE_TEXT`。

## 2. 核心判断

首版不要猜 17 种领星模块的 API payload。当前可信事实只支持一个发布组件：

```text
Lingxing contentModuleType = STANDARD_HEADER_IMAGE_TEXT
页面模块 = 带文字的标准图片标题
图片要求 = 970x600 或等比例更大图裁切
字段 = 标题、图片、副标题、正文
```

因此首版正确方案不是“继续让 Step7 产出各种原生模块类型，然后发布端静默塞进 `STANDARD_HEADER_IMAGE_TEXT`”，而是定义一个明确的发布 profile：

```text
standard_header_image_text_v1
```

这个 profile 的含义是：

- A+ 仍然由 5 个业务语义段落组成，例如 hero、lifestyle、feature proof、spec/objection、closing。
- 每个语义段落都用一张 1940x1200 A+ 图片承载主视觉。
- 领星发布层统一用 5 个 `STANDARD_HEADER_IMAGE_TEXT` 模块承载这些段落。
- 生成端必须显式声明该模块可按 `STANDARD_HEADER_IMAGE_TEXT` 发布；发布端不能再隐式强转未知模块。
- 领星模块里的标题、副标题、正文必须从 `ProductAplus.aplus_plan` 落下去，不能空着。

以后要支持 comparison chart、多图、规格表等原生领星模块，必须先捕获或验证对应 API payload，再新增模块 registry 和 mapper。不得靠名称猜。

## 3. 目标

1. 在 T4 `draft_visible` 前，补齐 A+ 生成结果到领星模块 payload 的可信映射。
2. 让 A+ 生成端、发布策略层、领星 client 使用同一套模块支持定义，避免生产端和消费端语义脱节。
3. 当前首版只支持 `standard_header_image_text_v1`，但必须明确这是受支持 profile，不是静默降级。
4. `STANDARD_HEADER_IMAGE_TEXT` 的标题、副标题、正文必须从 A+ 规划字段填充。
5. 不支持的模块类型、缺字段、模块数量不一致、图片和模块位置不一致时 fail closed，不保存不完整草稿。
6. 新增测试防止再次出现“所有模块硬编码同类且文本为空”的问题。

## 4. 非目标

- 不在本阶段推进 `draft_visible`、`submit approval` 或 Amazon 草稿箱确认。
- 不支持 17 种领星模块全集。
- 不猜测未验证的 Lingxing API payload。
- 不把领星发布状态并入商品主 workflow。
- 不新增商品列表 `work_status`。
- 不为了兼容旧测试数据自动发布旧 `aplus_plan`。测试数据可以丢弃；新链路以新 profile 为准。

## 5. 支持模块定义

### 5.1 Registry

新增或整理一个模块 registry，例如：

```text
backend/app/aplus_publish/module_registry.py
```

首版至少定义：

```text
profile_key: standard_header_image_text_v1
content_module_type: STANDARD_HEADER_IMAGE_TEXT
ui_name: 带文字的标准图片标题
image_min_width: 970
image_min_height: 600
required_fields:
  - headline
  - body
optional_fields:
  - subheading
supported_positions: 1..5
```

Registry 必须被 mapper 和规则测试读取。不能让支持类型只存在于 client `_module_payload()` 字符串里。

### 5.2 Source Fields

每个 `ProductAplus.aplus_plan.modules[*]` 至少需要：

```json
{
  "position": 1,
  "type": "standard_header_image_text",
  "semantic_role": "hero|lifestyle|feature_proof|spec_objection|closing",
  "publish_profile": "standard_header_image_text_v1",
  "lingxing_content_module_type": "STANDARD_HEADER_IMAGE_TEXT",
  "headline": "...",
  "subheading": "...",
  "key_message": "...",
  "text_content": "..."
}
```

字段策略：

- `headline`：映射到领星模块主标题；不能为空。
- `subheading`：映射到领星模块副标题或 block headline；允许为空，但如果源里有值必须写入。
- `body`：优先取 `text_content`，其次取 `key_message`，不能为空。
- `altText`：优先取 `headline`，其次取 `key_message`，最后取商品标题；最多 100 字。
- `semantic_role` 只表达业务段落用途，不等于 Lingxing API module type。
- `type` 如果继续保留，必须是项目内语义类型；发布判断不能只靠它。

### 5.3 Step7/Step8 Alignment

`step7_aplus_plan.py` 必须调整为生成当前可发布 profile，而不是继续要求“至少一个 comparison/spec 原生模块”这种发布端不支持的模块形态。

新的 Step7 目标是 5 个 A+ 语义段落：

1. hero / value promise
2. lifestyle / usage context
3. feature proof / material or function
4. spec objection / size, compatibility, setup, safety, or other buyer doubt
5. closing / confidence or cross-sell

这 5 个段落都应显式标记：

```text
publish_profile = standard_header_image_text_v1
lingxing_content_module_type = STANDARD_HEADER_IMAGE_TEXT
```

`step8_aplus_script.py` 仍负责生成每个段落对应的一张 A+ 图片，但不得把 unsupported native module type 写进脚本结果，导致发布端误判。

## 6. Mapper 设计

新增 mapper，例如：

```text
backend/app/services/lingxing_aplus_module_mapper.py
```

输入：

- `ProductAplus.aplus_plan`
- `ProductAplus.aplus_scripts`
- `ProductAplus.aplus_images`
- `AplusPublishAsset` 上传结果

输出：

- 5 个按 position 排序的 `LingxingAplusModulePayload`
- `contentModuleList`
- typed evidence：profile、模块数、字段来源、unsupported/invalid reason

必须校验：

1. `aplus_plan.modules` 是 list，且恰好 5 个模块。
2. 每个模块 position 唯一，范围 `1..5`。
3. 每个模块的 `publish_profile` 是 `standard_header_image_text_v1`。
4. 每个模块的 `lingxing_content_module_type` 是 `STANDARD_HEADER_IMAGE_TEXT`。
5. 每个模块有非空 `headline` 和可映射的非空 body。
6. 图片 assets 也是 5 个，position 与模块一一对应。
7. 图片尺寸满足 registry 要求。
8. 文本要做 trim、长度限制和基础控制字符清洗；超长时按字段策略截断，并在 evidence 记录。
9. 遇到未知 profile、未知 module type、缺字段、数量错位、position 错位时返回 typed failure，例如：
   - `unsupported_aplus_publish_profile`
   - `unsupported_aplus_module_type`
   - `aplus_module_count_invalid`
   - `aplus_module_position_mismatch`
   - `aplus_module_headline_missing`
   - `aplus_module_body_missing`

## 7. Client Payload

`LingxingAplusDraftSaveClient._save_draft()` 不应再调用硬编码 `_module_payload(image, index)`。

它应接收 mapper 产出的 `contentModuleList`，或接收结构化 module 后由 mapper/client 边界生成 payload。

`STANDARD_HEADER_IMAGE_TEXT` payload 必须满足：

- `contentModuleType = "STANDARD_HEADER_IMAGE_TEXT"`
- image 使用上传后的 `uploadDestinationId`、`altText`、裁切尺寸。
- `headline.value` 写入模块 headline。
- `block.headline.value` 写入 subheading 或 headline 的合理降级。
- `block.body.textList` 写入 body。

如果当前代码还没有确认 `body.textList` 的真实非空结构，听云必须先通过已登录领星页面、已有测试草稿、网络请求或现有可验证资料确认结构；不能猜一个 payload 当完成。确认结果应写入技术方案或实现说明。

## 8. 旧数据和兼容

本阶段不要求兼容旧测试数据：

- 旧 `aplus_plan` 没有 `publish_profile` 时，新发布任务可以 fail closed。
- 如果听云认为需要兼容已有生成结果，必须在技术方案里说明转换规则、风险和测试；若无法证明语义不丢失，则不做兼容。
- 已经保存过的空文本草稿不自动修复、不自动提交、不自动写 `draft_visible`。

## 9. 测试要求

至少新增或更新：

1. Mapper 单元/脚本测试：
   - 支持 `standard_header_image_text_v1`，生成 5 个 `STANDARD_HEADER_IMAGE_TEXT` payload。
   - headline/subheading/body 从 plan 正确写入。
   - 源有文本时 payload 不得为空。
   - 图片和模块 position 错位时 fail closed。
   - 缺 headline/body 时 fail closed。
   - 未知 profile/module type 时 fail closed。
2. Policy/task 测试：
   - `collect_aplus_publish_assets()` 或上层 policy 能把模块映射失败转为 typed reason。
   - `lingxing_aplus_publish` worker 不会在模块映射失败时保存草稿。
3. Project rules：
   - 禁止 `lingxing_aplus_publish_client.py` 继续存在硬编码空 `headline.value=""` / `body.textList=[]` 作为生产路径。
   - 确认 supported module registry 与 mapper/client 使用闭合。
4. 真实 QA 准备：
   - 观止后续必须用真实领星草稿验证：5 个模块仍按顺序存在，且标题/副标题/正文至少按源字段可见或可由编辑页读取。

## 10. 执行拆分

### M1 Technical Plan

听云先写技术方案，不直接编码。必须覆盖：

- 支持 profile 和 registry 设计。
- Step7/Step8 如何停止生产不受支持的模块类型。
- Mapper 输入/输出、失败码、text 截断/清洗策略。
- `STANDARD_HEADER_IMAGE_TEXT` 非空 body payload 结构如何验证。
- T3 policy/client/worker 如何接入 mapper。
- 测试和 project rules。
- 是否兼容旧 `aplus_plan`；若兼容，规则是什么；若不兼容，fail closed 行为是什么。

### M2 Implementation

方案通过后实现：

- registry + mapper
- Step7/Step8 profile 对齐
- T3 policy/client 接入
- tests/project rules/index 更新

### M3 Review / QA

- 镜花 review：重点看生成端和发布端契约是否闭合，是否仍有静默强转或空文本 payload，是否有可靠测试守住。
- 观止 QA：只在代码 gate 后进入，验证真实领星草稿模块字段，不做 `draft_visible` 或 submit。

## 11. 完成定义

本 PRD 完成时必须同时满足：

- 新生成的 A+ 规划明确使用 `standard_header_image_text_v1` profile。
- 发布端只接受受支持 profile/module type。
- 保存草稿 payload 不再丢弃 headline/subheading/body。
- 不支持模块 fail closed，不会保存半成品草稿。
- T3 真实 QA 能看到模块字段不再全空。
- T4 `draft_visible` 可以在内容结构可信的前提下继续推进。
