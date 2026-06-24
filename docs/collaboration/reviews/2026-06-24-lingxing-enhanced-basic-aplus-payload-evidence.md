# Lingxing Enhanced Basic A+ Payload Evidence

日期：2026-06-24 CST
角色：听云（agentKey: `tingyun`）
对应消息：`MSG-20260624-001`
范围：M3.0 payload evidence gate，只做证据，不编码，不提交，不 push。

## 结论

本轮从 Lingxing 当前公开前端 bundle 确认了 `enhanced_basic_aplus_v1` 候选普通 A+ 标准模块的 `contentModuleType`、payload subtree、图片尺寸、字段位置、保存/提交标志和前端 fail-closed 行为。未点击 Lingxing 页面保存或提交，未产生新的草稿副作用，未保存 cookie/token/header 或完整敏感请求。

建议 M3.1 首版使用以下 5 模块组合：

| position | semantic_role | 推荐 UI 模块 | contentModuleType | 原因 |
|---|---|---|---|---|
| 1 | `hero` | 标准图片和深文本覆盖 | `STANDARD_IMAGE_TEXT_OVERLAY` + `overlayColorType="DARK"` | 1 张 970x300 图，适合首屏价值主张。 |
| 2 | `feature_grid` | 标准三个图片和文本 | `STANDARD_THREE_IMAGE_TEXT` | 3 张 300x300 图，结构稳定，适合核心卖点。 |
| 3 | `detail_proof` | 标准单一图片和规格详细信息 | `STANDARD_SINGLE_IMAGE_SPECS_DETAIL` | 1 张 300x300 图 + 规格/说明字段，适合材质和结构细节。 |
| 4 | `comparison` | 标准比较图 | `STANDARD_COMPARISON_TABLE` | 支持列、ASIN、指标行和图，适合对比。 |
| 5 | `technical_or_closing` | 标准技术规格 | `STANDARD_TECH_SPECS` | 无图表格型规格，字段和校验明确。 |

可作为替代的已确认模块：

- `STANDARD_IMAGE_TEXT_OVERLAY` + `overlayColorType="LIGHT"`：标准图片和浅文本覆盖。
- `STANDARD_FOUR_IMAGE_TEXT`：标准四个图片和文本。
- `STANDARD_SINGLE_IMAGE_HIGHLIGHTS`：标准单一图片和标注。
- `STANDARD_TEXT`：标准文本。
- `STANDARD_PRODUCT_DESCRIPTION`：标准商品描述文本。
- `STANDARD_HEADER_IMAGE_TEXT`：带文字的标准图片标题，M2 已确认，可作为普通文本收口备选，不作为增强版首选。

Premium / 高级 A+ 结论：不可进入本轮创建/编辑实现。Lingxing 官方帮助中心 `A+商品描述` 当前说明列表可同步基本 A+、高级 A+、品牌故事，但创建章节写明目前只支持创建基本 A+；高级 A+ 和品牌故事暂不支持查看详情；FAQ 说明目前只支持编辑基本 A+。因此本轮不得声明 Premium / 高级 A+ 可创建、可编辑、可提交或可见。

## 证据来源

1. Lingxing 公开前端 bundle：
   - `https://static.distributetop.com/erp/js/contentModule-0af405eb.js`
   - `https://static.distributetop.com/erp/js/asinModule-4c23da27.js`
2. 已有 M2 evidence：`docs/collaboration/reviews/2026-06-23-lingxing-standard-header-image-text-payload.md`
3. Lingxing 官方帮助中心：`https://www.lingxing.com/help/article/APlusContent`

本轮使用命令只抓取公开 JS 到系统临时目录 `/tmp` 分析，不读取或保存浏览器登录态。未调用 `amazon/aplus/add`、`amazon/aplus/edit`、`uploadDestination` 或对象存储上传。

## 通用 Payload 结构

`asinModule-4c23da27.js` 暴露的默认对象显示，Lingxing basic A+ 内容模块统一进入：

```json
{
  "contentDocument": {
    "contentType": "EBC",
    "locale": "en-US",
    "name": "<document name>",
    "contentModuleList": [
      {
        "contentModuleType": "<STANDARD_...>",
        "<moduleDataKey>": {}
      }
    ]
  },
  "storeId": "<redacted>",
  "submitFlag": 0
}
```

保存草稿与提交的前端行为：

- `contentModule-0af405eb.js` 的底部保存按钮调用 `confirm(0)`，请求体包含 `submitFlag: 0`。
- 提交按钮调用 `confirm(1)`，请求体包含 `submitFlag: 1`。
- 本轮 M3.0 只允许 `submitFlag=0`。

通用字段对象：

```json
{
  "TextComponent": { "value": "<text>", "decoratorSet": [] },
  "ParagraphComponent": {
    "textList": [
      { "value": "<rich text paragraph>", "decoratorSet": [] }
    ]
  },
  "ImageComponent": {
    "uploadDestinationId": "<redacted>",
    "altText": "<image keywords, max 100>",
    "imageCropSpecification": {
      "offset": {
        "x": { "units": "pixels", "value": 0 },
        "y": { "units": "pixels", "value": 0 }
      },
      "size": {
        "height": { "units": "pixels", "value": "<module crop height>" },
        "width": { "units": "pixels", "value": "<module crop width>" }
      }
    }
  }
}
```

图片上传字段位置：

- 上传弹窗调用 `/amz/amz-data-transfer/amazon/aplus/uploadDestination` 获取 `uploadDestinationId`。
- 成功后把 `uploadDestinationId` 写入对应模块的 `*.image.uploadDestinationId`。
- 图片关键词写入同一 image 对象的 `altText`，前端必填且最长 100 字符。
- crop 坐标写入 `imageCropSpecification.offset`，crop 尺寸写入 `imageCropSpecification.size`；尺寸来自模块的 AddImage/AddPicDialog `width` / `height`。

富文本字段位置：

- `body.textList` 是 rich-text object list，不是 string list。
- plain text item 形如 `{ "value": "...", "decoratorSet": [] }`。
- 前端富文本支持加粗、斜体、下划线、列表等 `decoratorSet`，M3.1 可以先只生成 plain text。

清洗与 fail-closed 行为：

- `contentModule-0af405eb.js` 的 `validate()` 会在保存/提交前调用各模块组件的 `validateModel`；必填图片、正文、规格行、比较列等缺失时显示错误并不进入 `$gwPost`。
- `handleParams()` 在提交前调用清洗函数 `L()`，空 `value`、空 `uploadDestinationId`、空 `textList` 会被清理为 `null` 或空数组；因此 M3.1 不能依赖空字段被服务端接受，必须在 mapper preflight 中 fail closed。
- 对目标增强模块，建议 mapper 在任何 Lingxing auth / uploadDestination / add 之前本地校验所有必填文本、图片槽位、规格行、比较列和 alt text。

## 已确认目标模块

### 1. 标准图片和浅文本覆盖 / 标准图片和深文本覆盖

- UI 中文名：标准图片和浅文本覆盖；标准图片和深文本覆盖。
- `contentModuleType`：`STANDARD_IMAGE_TEXT_OVERLAY`。
- 区分字段：`standardImageTextOverlay.overlayColorType = "LIGHT"` 或 `"DARK"`。
- 图片：1 张，970x300 像素。
- 图片字段：`standardImageTextOverlay.block.image`。
- alt/crop/uploadDestination：`block.image.altText`、`block.image.uploadDestinationId`、`block.image.imageCropSpecification`。
- 文本字段：
  - 标题：`standardImageTextOverlay.block.headline.value`，maxlength 70。
  - 正文：`standardImageTextOverlay.block.body.textList`，富文本，maxLength 300，maxLineLength 5。
- 前端必填：图片 `block.image.uploadDestinationId`。标题/正文未在前端 validateModel 中强制，但 M3.1 应为内容质量本地强制。

Payload subtree:

```json
{
  "contentModuleType": "STANDARD_IMAGE_TEXT_OVERLAY",
  "standardImageTextOverlay": {
    "overlayColorType": "DARK",
    "block": {
      "image": { "uploadDestinationId": "<id>", "altText": "<alt>", "imageCropSpecification": "<970x300 crop>" },
      "headline": { "value": "<headline>", "decoratorSet": [] },
      "body": { "textList": [{ "value": "<body>", "decoratorSet": [] }] }
    }
  }
}
```

### 2. 标准三个图片和文本

- UI 中文名：标准三个图片和文本。
- `contentModuleType`：`STANDARD_THREE_IMAGE_TEXT`。
- 图片：3 张，每张 300x300 像素。
- 图片字段：`standardThreeImageText.block1.image`、`block2.image`、`block3.image`。
- alt/crop/uploadDestination：每个 block 的 `image.altText`、`image.uploadDestinationId`、`image.imageCropSpecification`。
- 文本字段：
  - 主标题：`standardThreeImageText.headline.value`，maxlength 200。
  - 每图标题：`blockN.headline.value`，maxlength 160。
  - 每图正文：`blockN.body.textList`，富文本，maxLength 1000，maxLineLength 10。
- 前端必填：3 张图片。文本建议 M3.1 本地强制。

Payload subtree:

```json
{
  "contentModuleType": "STANDARD_THREE_IMAGE_TEXT",
  "standardThreeImageText": {
    "headline": { "value": "<main headline>", "decoratorSet": [] },
    "block1": { "image": "<ImageComponent>", "headline": "<TextComponent>", "body": "<ParagraphComponent>" },
    "block2": { "image": "<ImageComponent>", "headline": "<TextComponent>", "body": "<ParagraphComponent>" },
    "block3": { "image": "<ImageComponent>", "headline": "<TextComponent>", "body": "<ParagraphComponent>" }
  }
}
```

### 3. 标准四个图片和文本

- UI 中文名：标准四个图片和文本。
- `contentModuleType`：`STANDARD_FOUR_IMAGE_TEXT`。
- 图片：4 张，每张 220x220 像素。
- 图片字段：`standardFourImageText.block1.image` 至 `block4.image`。
- alt/crop/uploadDestination：每个 block 的 `image.altText`、`image.uploadDestinationId`、`image.imageCropSpecification`。
- 文本字段：
  - 主标题：`standardFourImageText.headline.value`，maxlength 200。
  - 每图标题：`blockN.headline.value`，maxlength 160。
  - 每图正文：`blockN.body.textList`，富文本，maxLength 1000，maxLineLength 10。
- 前端必填：4 张图片。文本建议 M3.1 本地强制。

Payload subtree:

```json
{
  "contentModuleType": "STANDARD_FOUR_IMAGE_TEXT",
  "standardFourImageText": {
    "headline": { "value": "<main headline>", "decoratorSet": [] },
    "block1": { "image": "<ImageComponent>", "headline": "<TextComponent>", "body": "<ParagraphComponent>" },
    "block2": { "image": "<ImageComponent>", "headline": "<TextComponent>", "body": "<ParagraphComponent>" },
    "block3": { "image": "<ImageComponent>", "headline": "<TextComponent>", "body": "<ParagraphComponent>" },
    "block4": { "image": "<ImageComponent>", "headline": "<TextComponent>", "body": "<ParagraphComponent>" }
  }
}
```

### 4. 标准单一图片和规格详细信息

- UI 中文名：标准单一图片和规格详细信息。
- `contentModuleType`：`STANDARD_SINGLE_IMAGE_SPECS_DETAIL`。
- 图片：1 张，300x300 像素。
- 图片字段：`standardSingleImageSpecsDetail.image`。
- alt/crop/uploadDestination：`image.altText`、`image.uploadDestinationId`、`image.imageCropSpecification`。
- 文本/规格字段：
  - 主标题：`headline.value`，maxlength 200。
  - 描述标题：`descriptionHeadline.value`，maxlength 160。
  - 描述块 1/2 标题：`descriptionBlock1.headline.value`、`descriptionBlock2.headline.value`，maxlength 200。
  - 描述块 1/2 正文：`descriptionBlock1.body.textList`、`descriptionBlock2.body.textList`，富文本，maxLength 400，maxLineLength 10。
  - 规格标题：`specificationHeadline.value`，maxlength 160。
  - 规格列表标题：`specificationListBlock.headline.value`。
  - 规格列表行：`specificationListBlock.block.textList[*].position` + `.text.value`。
  - 规格说明块：`specificationTextBlock.headline.value` + `specificationTextBlock.body.textList`。
- 前端必填：图片、`descriptionBlock1.body.textList`。M3.1 应至少强制图片、主描述、规格标题/规格行完整。

Payload subtree:

```json
{
  "contentModuleType": "STANDARD_SINGLE_IMAGE_SPECS_DETAIL",
  "standardSingleImageSpecsDetail": {
    "headline": "<TextComponent>",
    "image": "<ImageComponent>",
    "descriptionHeadline": "<TextComponent>",
    "descriptionBlock1": { "headline": "<TextComponent>", "body": "<ParagraphComponent>" },
    "descriptionBlock2": { "headline": "<TextComponent>", "body": "<ParagraphComponent>" },
    "specificationHeadline": "<TextComponent>",
    "specificationListBlock": {
      "headline": "<TextComponent>",
      "block": { "textList": [{ "position": 1, "text": { "value": "<spec>", "decoratorSet": [] } }] }
    },
    "specificationTextBlock": { "headline": "<TextComponent>", "body": "<ParagraphComponent>" }
  }
}
```

### 5. 标准单一图片和标注

- UI 中文名：标准单一图片和标注。
- `contentModuleType`：`STANDARD_SINGLE_IMAGE_HIGHLIGHTS`。
- 图片：1 张，300x300 像素。
- 图片字段：`standardSingleImageHighlights.image`。
- alt/crop/uploadDestination：`image.altText`、`image.uploadDestinationId`、`image.imageCropSpecification`。
- 文本/标注字段：
  - 主标题：`headline.value`，maxlength 160。
  - `textBlock1.headline.value` / `body.textList`，标题 maxlength 200，正文 maxLength 1000，maxLineLength 10。
  - `textBlock2.headline.value` / `body.textList`，标题 maxlength 200，正文 maxLength 400，maxLineLength 10。
  - `textBlock3.headline.value` / `body.textList`，标题 maxlength 200，正文 maxLength 400，maxLineLength 10。
  - 标注标题：`bulletedListBlock.headline.value`。
  - 标注列表：`bulletedListBlock.block.textList[*].position` + `.text.value`，单条 maxlength 100，最多 8 条。
- 前端必填：图片。M3.1 应本地强制至少一个文本块或 bullet list 非空。

Payload subtree:

```json
{
  "contentModuleType": "STANDARD_SINGLE_IMAGE_HIGHLIGHTS",
  "standardSingleImageHighlights": {
    "image": "<ImageComponent>",
    "headline": "<TextComponent>",
    "textBlock1": { "headline": "<TextComponent>", "body": "<ParagraphComponent>" },
    "textBlock2": { "headline": "<TextComponent>", "body": "<ParagraphComponent>" },
    "textBlock3": { "headline": "<TextComponent>", "body": "<ParagraphComponent>" },
    "bulletedListBlock": {
      "headline": "<TextComponent>",
      "block": { "textList": [{ "position": 1, "text": { "value": "<bullet>", "decoratorSet": [] } }] }
    }
  }
}
```

### 6. 标准比较图

- UI 中文名：标准比较图。
- `contentModuleType`：`STANDARD_COMPARISON_TABLE`。
- 图片：每个 product column 1 张，150x300 像素；最多 6 列，前 2 列必填，其余列需启用后填完整。
- 图片字段：`standardComparisonTable.productColumns[*].image`。
- alt/crop/uploadDestination：每列 `image.altText`、`image.uploadDestinationId`、`image.imageCropSpecification`。
- 列字段：
  - `productColumns[*].position`
  - `productColumns[*].title`，maxlength 80。
  - `productColumns[*].asin`，maxlength 10，前端校验 `^[A-Z0-9]{10}$`。
  - `productColumns[*].highlight`。
  - `productColumns[*].metrics[*].position` + `.value`。
- 指标行字段：
  - `metricRowLabels[*].position`
  - `metricRowLabels[*].value`，maxlength 100，最多 10 行。
- 指标值：
  - 可选 `"✔"`、`"×"` 或文本。
  - 文本指标 maxlength 250。
- 前端必填：前 2 列的 image/title/asin/first metric，以及第一条 `metricRowLabels[0].value`。可选列若 `isEnable` 但缺字段会阻断保存。
- `beforeSave()` 会过滤未启用/空列、过滤空指标行、删除 UI-only `type` 字段，并重写 position。

Payload subtree:

```json
{
  "contentModuleType": "STANDARD_COMPARISON_TABLE",
  "standardComparisonTable": {
    "productColumns": [
      {
        "position": 1,
        "image": "<ImageComponent>",
        "title": "<column title>",
        "asin": "B0XXXXXXXX",
        "highlight": true,
        "metrics": [
          { "position": 1, "value": "✔" },
          { "position": 2, "value": "<metric text>" }
        ]
      }
    ],
    "metricRowLabels": [
      { "position": 1, "value": "<comparison metric name>" }
    ]
  }
}
```

### 7. 标准技术规格

- UI 中文名：标准技术规格。
- `contentModuleType`：`STANDARD_TECH_SPECS`。
- 图片：无。
- 文本/规格字段：
  - 主标题：`standardTechSpecs.headline.value`，maxlength 80。
  - 布局：`standardTechSpecs.tableCount`，可选 1 或 2。
  - 规格行：`standardTechSpecs.specificationList[*].label.value` + `.description.value`。
  - label maxlength 30，description maxlength 500。
- 前端必填：前 4 条规格名和规格定义。默认 mounted 创建 5 条空规格，可新增到最多 16 条；`beforeSave()` 只保留 label 和 description 都非空的行。

Payload subtree:

```json
{
  "contentModuleType": "STANDARD_TECH_SPECS",
  "standardTechSpecs": {
    "headline": { "value": "<headline>", "decoratorSet": [] },
    "specificationList": [
      {
        "label": { "value": "<spec name>", "decoratorSet": [] },
        "description": { "value": "<spec value>", "decoratorSet": [] }
      }
    ],
    "tableCount": 1
  }
}
```

### 8. 标准文本

- UI 中文名：标准文本。
- `contentModuleType`：`STANDARD_TEXT`。
- 图片：无。
- 文本字段：
  - 标题：`standardText.headline.value`，maxlength 160。
  - 正文：`standardText.body.textList`，富文本，maxLength 5000，maxLineLength 10。
- 前端必填：正文 `body.textList`。

Payload subtree:

```json
{
  "contentModuleType": "STANDARD_TEXT",
  "standardText": {
    "headline": { "value": "<headline>", "decoratorSet": [] },
    "body": { "textList": [{ "value": "<body>", "decoratorSet": [] }] }
  }
}
```

### 9. 标准商品描述文本

- UI 中文名：标准商品描述文本。
- `contentModuleType`：`STANDARD_PRODUCT_DESCRIPTION`。
- 图片：无。
- 文本字段：
  - 正文：`standardProductDescription.body.textList`，富文本，maxLength 6000，maxLineLength 30。
- 前端必填：正文 `body.textList`。

Payload subtree:

```json
{
  "contentModuleType": "STANDARD_PRODUCT_DESCRIPTION",
  "standardProductDescription": {
    "body": { "textList": [{ "value": "<body>", "decoratorSet": [] }] }
  }
}
```

### 10. 带文字的标准图片标题（已确认备选）

- UI 中文名：带文字的标准图片标题。
- `contentModuleType`：`STANDARD_HEADER_IMAGE_TEXT`。
- 图片：1 张，970x600 像素。
- 证据：`docs/collaboration/reviews/2026-06-23-lingxing-standard-header-image-text-payload.md`
- 字段：
  - `standardHeaderImageText.headline.value`
  - `standardHeaderImageText.block.image`
  - `standardHeaderImageText.block.headline.value`
  - `standardHeaderImageText.block.body.textList`

## 不可确认 / 不进入 M3.1 的项

- Premium / 高级 A+ 创建、编辑、提交和可见性：官方帮助中心当前只支持创建/编辑基本 A+，高级 A+ 和品牌故事只作为列表同步能力出现，不作为创建/编辑能力。
- Amazon Seller Central 草稿箱可见性：本轮未做 `draft_visible`，未调用同步后唯一匹配，也未打开 Seller Central。
- Lingxing 服务端对每个字段最大长度之外的业务规则：本轮证据来自前端 bundle serializer 和前端校验，不等同于服务端边界全覆盖。M3.1 应按前端限制收紧，并在 M3.3 用真实草稿保存 QA 验证。
- 复杂富文本样式组合：确认 `decoratorSet` 存在，但首版建议只生成 plain rich-text item。

## 草稿保存副作用

本轮没有产生新的 Lingxing 草稿保存副作用：

- 未点击保存。
- 未点击提交。
- 未调用 `amazon/aplus/add` / `amazon/aplus/edit`。
- 未上传图片。
- 未修改测试店铺数据。

## M3.1 技术方案建议

1. Registry 增加 `enhanced_basic_aplus_v1`，但只收录本 evidence 中 confirmed 的普通 A+ 标准模块。
2. Mapper 保持 two-phase：preflight 在任何 Lingxing auth / uploadDestination / object upload / add 前完成；post-upload 只注入 `uploadDestinationId`、`altText` 和 crop。
3. 对所有图片模块强制 alt text、图片数量、slot 名称、尺寸和 position 一一对应。
4. 对比较图强制至少 2 列、每列 image/title/asin/first metric、至少 1 条 metric row；ASIN 格式 `^[A-Z0-9]{10}$`。
5. 对技术规格强制至少 4 条完整规格行；对文本模块强制 body rich-text object list 非空。
6. 对 overlay / 多图文本模块，前端只强制图片，但自动链路应本地强制 headline/body，避免保存视觉空壳。
7. 所有缺失、空值、未知 module type、payload subtree 未确认、图片 slot 错位、表格行不完整都 fail closed，不 fallback 到 `STANDARD_HEADER_IMAGE_TEXT`。
