# Lingxing A+ Publish T3 Real Save Module QA

结论：`QA / PASS_WITH_SCOPE`

## Scope

- 本轮补充验证上一轮真实保存的 Lingxing A+ 草稿在领星编辑页面中的模块结构。
- 样本：TaskRun `1244`，TaskStep `1250`，Product `1435`，CatalogProduct `1300`，AplusUploadItem `26`。
- Lingxing `idHash=c0ae094b6a9609107a5842d694dcc31c`，ASIN `B0GX2GFR73`，MSKU `N726P248345C`，店铺 `idea_lc@163.com-US` / `store_id=10372`。
- 本轮未点击 `保存`，未点击 `提交`，未触发审批提交。

## Page Evidence

- Chrome URL:
  `https://erp.lingxing.com/erp/editAplus?tag_name=%E7%BC%96%E8%BE%91A%2B&idHash=c0ae094b6a9609107a5842d694dcc31c&isEdit=1`
- 页面可打开，标题为 `领星ERP - 跨境电商管理系统`，没有登录阻塞。
- 页面顶部字段匹配：
  - 店铺：`idea_lc@163.com-US`
  - 语言：`英语（美国）`
  - 商品描述名称：`B0GX2GFR73_N726P248345C_1435`
- 页面 ASIN 表格可见 `B0GX2GFR73`，标题为 `7-in-1 Baby Tricycle for 12-72 Months... (Blue)`。
- 本地截图证据：`/Users/liuchang/Documents/gitproject/fbm-pipeline/tmp/lingxing-aplus-module-qa-20260623.png`

## Module Structure

页面内容区按自上而下顺序读取到 5 个模块：

| Position | 页面模块类型 | 对应代码模块 | 图片绑定 | 文本字段 |
| --- | --- | --- | --- | --- |
| 1 | 带文字的标准图片标题 | `STANDARD_HEADER_IMAGE_TEXT` | 1 张可见 970x600 图片 | 标题/副标题/正文为空 |
| 2 | 带文字的标准图片标题 | `STANDARD_HEADER_IMAGE_TEXT` | 1 张可见 970x600 图片 | 标题/副标题/正文为空 |
| 3 | 带文字的标准图片标题 | `STANDARD_HEADER_IMAGE_TEXT` | 1 张可见 970x600 图片 | 标题/副标题/正文为空 |
| 4 | 带文字的标准图片标题 | `STANDARD_HEADER_IMAGE_TEXT` | 1 张可见 970x600 图片 | 标题/副标题/正文为空 |
| 5 | 带文字的标准图片标题 | `STANDARD_HEADER_IMAGE_TEXT` | 1 张可见 970x600 图片 | 标题/副标题/正文为空 |

DOM audit details:

- Module count: `5`
- Module top positions: `169`, `1379`, `2589`, `3799`, `5009`; order is stable as page order `1..5`.
- Each module has exactly one visible image from `https://m.media-amazon.com/images/S/aplus-media/...`.
- Each module image reports `naturalWidth=970`, `naturalHeight=600`, rendered `width=970`, `height=600`.
- The images are not the static `pic-Aplus-04.png` placeholder and are not broken-image blanks.

Observed image URLs:

1. `https://m.media-amazon.com/images/S/aplus-media/sc/ede06edc-ce3e-480a-9936-ed4b5134a419.__CR0,0,970,600_PT0_SX970_V1__.png`
2. `https://m.media-amazon.com/images/S/aplus-media/sc/fefaf8b3-774f-42ca-b74a-8ccf2c9c7da2.__CR0,0,970,600_PT0_SX970_V1__.png`
3. `https://m.media-amazon.com/images/S/aplus-media/sc/cc5eb396-e01d-4042-86e2-52737ff8f789.__CR0,0,970,600_PT0_SX970_V1__.png`
4. `https://m.media-amazon.com/images/S/aplus-media/sc/715ee84c-6234-43f5-9212-5b87d45c8bf0.__CR0,0,970,600_PT0_SX970_V1__.png`
5. `https://m.media-amazon.com/images/S/aplus-media/sc/34b3d3df-9f7e-48fa-bf83-23e45b24c95c.__CR0,0,970,600_PT0_SX970_V1__.png`

## Text Field Finding

`QA_FINDING / CURRENT_IMPLEMENTATION_LIMITATION`:

- 5 个模块的页面字段均存在，但标题、副标题、正文实际为空。
- 每个模块读取到 3 个文本控件：
  - 标题 input：空字符串
  - 副标题 input：空字符串
  - 正文富文本区域：空字符串，页面计数为 `0/6000`
- 这与当前代码提交的 payload 一致：`contentModuleType="STANDARD_HEADER_IMAGE_TEXT"`，`headline.value=""`，`block.headline.value=""`，`block.body.textList=[]`。
- 因此本轮只通过“模块结构、顺序、图片绑定”验收；不把 A+ 文案内容质量包装成通过。

## Result

`QA / PASS_WITH_SCOPE`

通过项：

- 目标 `idHash` 页面可打开，未被登录或定位问题阻塞。
- 页面草稿中存在 5 个内容模块。
- 5 个模块类型均为页面上的 `带文字的标准图片标题`，对应当前代码的 `STANDARD_HEADER_IMAGE_TEXT`。
- 模块页面顺序为 `1..5`。
- 每个模块均绑定并可见一张 970x600 图片，不是空白或失败占位。

范围限制：

- 文本字段为空是本轮明确记录的当前实现限制，不代表 A+ 内容质量合格。
- 本 QA 不代表 `amazon_draft_visibility=draft_visible`。
- 本 QA 不代表 Amazon Seller Central 草稿箱可见。
- 本 QA 不代表 submit approval，且本轮没有点击 `提交`。
