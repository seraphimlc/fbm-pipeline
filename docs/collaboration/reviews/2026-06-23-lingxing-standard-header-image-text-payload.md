# Lingxing STANDARD_HEADER_IMAGE_TEXT Payload Evidence

日期：2026-06-23 CST  
角色：听云（agentKey: `tingyun`）  
对应消息：`MSG-20260623-009`

## 结论

Lingxing 页面模块“带文字的标准图片标题”对应 `contentModuleType="STANDARD_HEADER_IMAGE_TEXT"`。非空标题、副标题、正文保存时，前端 serializer 生成的 payload subtree 使用 rich-text object list，不是 string list：

- `standardHeaderImageText.headline.value`：页面“标题”输入值。
- `standardHeaderImageText.block.headline.value`：页面“副标题”输入值。
- `standardHeaderImageText.block.body.textList`：`[{ "value": "...", "decoratorSet": [...] }]` 形式的 rich-text object list。
- plain text 正文的 `decoratorSet` 为空数组；加粗/斜体/下划线/列表等样式进入 `decoratorSet`。

## 确认方法

1. 使用已登录 Chrome 中的 Lingxing `editAplus` 测试页做只读检查，未点击保存或提交。
2. 读取当前页面已加载静态资源清单，定位到：
   - `https://static.distributetop.com/erp/js/contentModule-0af405eb.js`
   - `https://static.distributetop.com/erp/js/asinModule-4c23da27.js`
3. 在公开前端 bundle 中定位 serializer：
   - `contentModule-0af405eb.js` 的 `StandardHeaderImageText` 组件把页面字段绑定到 `moduleData.headline.value`、`moduleData.block.headline.value`、`moduleData.block.body.textList`。
   - `Content.handleParams()` 将清洗后的 `moduleData` push 到 `amazonAPlusCreate.contentDocument.contentModuleList`。
   - `Content.confirm(e)` 调用 `$gwPost(l, { ...amazonAPlusCreate, submitFlag: e, ... })`；保存按钮为 `confirm(0)`，提交按钮为 `confirm(1)`。
   - `asinModule-4c23da27.js` 的 `WangEditor.changeText()` 将编辑器内容转换为 `[{ value, decoratorSet }]` 并通过 `input/change` 写回 `body.textList`。
4. 当前测试页 DOM 只读确认了已有测试数据：
   - 店铺显示为测试店铺。
   - A+ 名称为 `TEST DO NOT USE - Codex A+ 20260623 1429`。
   - 第一个模块为“带文字的标准图片标题”，标题/副标题非空，正文编辑器当前文本为 `一`。

## 是否产生草稿保存副作用

本轮没有点击页面“保存”或“提交”，没有调用 `amazon/aplus/add` / `amazon/aplus/edit`，没有产生新的草稿保存或提交副作用。

历史页面本身是已存在测试 A+ 编辑页；本轮仅做只读页面状态和公开静态 bundle 检查。

## 目标测试店铺 / ASIN 脱敏摘要

- 店铺：`idea_lc@***-US`
- A+ 名称：`TEST DO NOT USE - Codex A+ 20260623 1429`
- 页面 URL：`/erp/editAplus?...&idHash=<redacted>&isEdit=1`
- 当前关联 ASIN：`B0****QRZ`
- 模块：第一个内容模块为 `STANDARD_HEADER_IMAGE_TEXT` / “带文字的标准图片标题”

## Redacted Payload Subtree

以下 subtree 来自前端 serializer 结构和当前测试页非空字段，只保留 M2.0 需要的字段；图片 ID、ASIN、idHash 等外部标识已脱敏。

```json
{
  "submitFlag": 0,
  "contentDocument": {
    "contentType": "EBC",
    "locale": "en-US",
    "name": "TEST DO NOT USE - Codex A+ 20260623 1429",
    "contentModuleList": [
      {
        "contentModuleType": "STANDARD_HEADER_IMAGE_TEXT",
        "standardHeaderImageText": {
          "headline": {
            "value": "TEST A+ CONTENT - DO NOT USE",
            "decoratorSet": []
          },
          "block": {
            "image": {
              "uploadDestinationId": "<redacted>",
              "altText": "<redacted>",
              "imageCropSpecification": {
                "offset": {
                  "x": { "units": "pixels", "value": 0 },
                  "y": { "units": "pixels", "value": 0 }
                },
                "size": {
                  "height": { "units": "pixels", "value": "600" },
                  "width": { "units": "pixels", "value": "970" }
                }
              }
            },
            "headline": {
              "value": "Lingxing ERP integration test",
              "decoratorSet": []
            },
            "body": {
              "textList": [
                {
                  "value": "一",
                  "decoratorSet": []
                }
              ]
            }
          }
        }
      }
    ]
  },
  "storeId": "<redacted>"
}
```

## 字段结构判断

- `body.textList` 是 rich-text object list。
- plain paragraph item 结构是 `{ "value": string, "decoratorSet": [] }`。
- `decoratorSet` 支持的样式类型来自前端 bundle：`STYLE_BOLD`、`STYLE_ITALIC`、`STYLE_UNDERLINE`、`LIST_ITEM`、`LIST_ORDERED`、`LIST_UNORDERED`。
- `standardHeaderImageText.headline` 和 `standardHeaderImageText.block.headline` 使用同一文本对象结构：`{ "value": string, "decoratorSet": [] }`。
- 保存草稿按钮对应 `submitFlag=0`；提交按钮对应 `submitFlag=1`。

## No-submit 声明

本轮没有点击提交审批，没有调用 submit 路径，没有确认 `draft_visible`，没有推进 Amazon/Seller Central 草稿可见性。

## 无法确认项

- 本轮未抓取真实 Network request body；结论来自当前生产前端 bundle serializer 和当前测试页面 DOM 状态。
- 未确认 `$gwPost` wrapper 是否会在发送前追加通用 envelope 或网关公共字段；但 `contentDocument.contentModuleList[*].standardHeaderImageText` subtree 由上述 serializer 原样构造。
- 未确认 Lingxing 服务端对最大长度、换行、复杂富文本样式组合的最终接受边界。
