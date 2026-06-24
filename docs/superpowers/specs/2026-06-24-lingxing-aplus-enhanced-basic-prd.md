# Lingxing A+ Enhanced Basic PRD

日期：2026-06-24
Owner：若命（agentKey: `ruoming`）
状态：PRD_READY_FOR_TECHNICAL_PLAN

## 1. 背景

当前 T3.5/M2 已经把 A+ 发布从“5 张空文本 `STANDARD_HEADER_IMAGE_TEXT` 图片模块”推进到可信的基础 A+ 草稿：

- Step7/Step8 生成 5 个业务语义段落。
- 发布 profile 统一为 `standard_header_image_text_v1`。
- Lingxing 草稿使用 5 个 `STANDARD_HEADER_IMAGE_TEXT` 模块。
- 标题、副标题、正文、图片和 alt text 已通过真实领星草稿字段 QA。

这解决了“能稳定保存基础 A+ 草稿”的问题，但视觉和信息结构仍偏基础：所有模块形态一致，不能利用比较图、技术规格、多图文、图片覆盖等普通 A+ 标准模块表达卖点。

用户决策：先做增强版普通 A+；同时调研领星是否支持真正高级 A+ / Premium A+。Premium A+ 不进入本轮实现。

## 2. 领星高级 A+ / Premium A+ 调研结论

事实来源：

- 领星帮助中心 `A+商品描述`：`https://www.lingxing.com/help/article/APlusContent`
- 本地记录：`docs/lingxing-aplus-upload.md`

确认事实：

- 领星 A+ 列表字段包含 `A+类型`，类型包括 `基本A+`、`高级A+`、`品牌故事`。
- 领星支持同步列表里的全部 A+ 数据，包括基本 A+、高级 A+、品牌故事。
- 领星帮助中心“创建基本A+”章节明确说明：由于亚马逊接口限制，目前只支持创建基本 A+。
- 帮助中心还说明：高级 A+ 和品牌故事暂不支持查看详情；常见问题也说明目前只支持编辑基本 A+。
- 领星创建基本 A+ 支持 17 种基本 A+ 内容模块。

产品判断：

- 当前自动化不应实现真正 Premium A+ / 高级 A+ 创建、编辑、提交或可见性验证。
- 高级 A+ 只作为后续 feasibility 课题：若未来要做，需要确认账号/品牌权限、Amazon API/卖家后台能力、领星 UI/API 是否已开放创建或编辑、以及真实 payload。
- 本轮只做 `enhanced_basic_aplus_v1`：使用普通 A+ 的标准模块组合，提升内容结构和表现力。

## 3. 目标

构建增强版普通 A+ 发布 profile，让自动 A+ 从单一模块升级为一套稳定、可验证、可保存草稿的普通 A+ 模块组合。

目标结果：

1. 新增 `enhanced_basic_aplus_v1` profile。
2. Step7 规划从“5 个同形态段落”升级为“5 个业务角色 + 指定普通 A+ 模块类型”。
3. Step8 出图脚本根据模块类型生成对应素材数量、画面比例和文案。
4. module registry / mapper / client 支持多个已确认 payload 的普通 A+ 模块。
5. 未确认 payload 的模块不得进入发布 profile。
6. 发布任务仍只保存领星草稿：`draft_saved + amazon_draft_visibility=unconfirmed`。
7. 真实 QA 必须验证领星草稿编辑页模块类型、顺序、字段和图片均正确可见。

## 4. 非目标

本轮不做：

- Premium A+ / 高级 A+ 创建、编辑、提交或可见性验证。
- 品牌故事创建、编辑、提交或可见性验证。
- `draft_visible`。
- submit approval。
- Amazon Seller Central 草稿箱可见性验证。
- A+ 内容审美最终验收。
- 把领星发布状态并入商品主 workflow / 商品列表 `work_status`。
- 支持全部 17 种普通 A+ 模块。
- 对旧 A+ plan 做静默迁移。

## 5. 增强版普通 A+ V1 模板

`enhanced_basic_aplus_v1` 是一套受控模板，不是让 LLM 任意选择领星模块。

首选模块组合：

| position | semantic_role | 目标普通 A+ 模块 | 用途 |
|---|---|---|---|
| 1 | `hero` | 标准图片和深文本覆盖 / 标准图片和浅文本覆盖 | 首屏价值主张，大视觉 + 短标题 |
| 2 | `feature_grid` | 标准三个图片和文本 / 标准四个图片和文本 | 3-4 个核心卖点 |
| 3 | `detail_proof` | 标准单一图片和规格详细信息 / 标准单一图片和标注 | 材质、结构、功能细节 |
| 4 | `comparison` | 标准比较图 | 和普通替代品或同类方案对比 |
| 5 | `technical_or_closing` | 标准技术规格 / 标准文本 / 带文字的标准图片标题 | 参数、适配场景、收口购买理由 |

实施约束：

- 每个目标模块必须先确认真实 Lingxing `contentModuleType` 和 payload subtree。
- 如果某个首选模块无法确认 payload，听云必须写 `REQUEST / DESIGN_CHANGE`，提出替代模块和影响；不得静默退回 `STANDARD_HEADER_IMAGE_TEXT`。
- 支持模块数量以完整闭环为准：registry、Step7、Step8、mapper、client、tests、docs 和真实 QA 必须同源。

## 6. Payload Evidence Gate

在实现 `enhanced_basic_aplus_v1` 前，必须先完成 M3.0 evidence gate。

M3.0 必须确认：

- 目标模块在领星 UI 中的中文名、图片尺寸要求、字段类型和限制。
- 目标模块对应的真实 `contentModuleType`。
- `amazon/aplus/add` payload subtree。
- 图片上传引用字段：`uploadDestinationId`、crop 坐标、alt text 字段位置。
- 纯文本、富文本、表格/对比行、规格行、多图列表的 payload 结构。
- 保存草稿必须 `submitFlag=0`。

允许的确认方法：

1. 优先读已登录领星页面公开前端 bundle serializer。
2. 可使用测试账号/测试店铺做受控草稿保存来抓 payload，但必须只保存草稿，不提交审批。
3. 证据必须脱敏，不保存 cookie/token/header 或完整敏感请求。

输出文件建议：

- `docs/collaboration/reviews/2026-06-24-lingxing-enhanced-basic-aplus-payload-evidence.md`

## 7. 数据与状态口径

本轮不新增商品主流程状态。

A+ 发布 profile 是 A+ 生成/发布链路内部语义：

- `publish_profile=enhanced_basic_aplus_v1`
- `lingxing_content_module_type` 由每个模块的 registry spec 决定。
- `semantic_role` 表达业务用途，不等于 Lingxing API module type。

旧数据策略：

- 旧 `standard_header_image_text_v1` plan 仍可按旧 profile 发布。
- `enhanced_basic_aplus_v1` 不对旧 plan 自动升级。
- 缺 profile/type 的旧 plan 仍 fail closed。
- 若用户要把已有基础 A+ 重生成增强版，必须重新跑 A+ plan/script/image，不做发布时临时改写。

## 8. 生成端要求

Step7：

- 输出 `aplus_plan.version` 或等价字段，标识增强版 profile。
- 每个 module 必须包含：
  - `position`
  - `semantic_role`
  - `publish_profile`
  - `lingxing_content_module_type`
  - 模块所需字段，例如 headline、subheading、body、feature items、comparison rows、spec rows 等。
- LLM 只能生成业务内容，不决定实际可发布 module type；module type 由后端模板/registry 赋值。

Step8：

- 根据 module type 生成对应数量和尺寸的图片脚本。
- 多图模块必须明确每张图的用途、alt text、文案和对应 payload slot。
- 比较图 / 技术规格模块如主要由文本/表格承载，应避免生成无用图片。
- regenerated module 必须保留 profile/type/semantic_role 和模块字段结构。

## 9. 发布端要求

Registry：

- 新增或扩展 module specs，支持每种 confirmed basic module。
- 每个 spec 包含：
  - profile key
  - Lingxing `contentModuleType`
  - UI 中文名
  - 图片数量、尺寸和 crop 规则
  - 必填字段 / 可选字段
  - 文本长度/行数策略
  - failure code
  - evidence file path

Mapper：

- `preflight_validate()` 仍必须在任何 Lingxing auth、uploadDestination、对象存储上传和 `amazon/aplus/add` 前完成所有 plan/profile/type/text/table/image slot 语义校验。
- `assemble_payload()` 只在 preflight PASS 和图片上传成功后注入 upload destination / crop / image references。
- 对未知 profile/type、缺字段、数量错位、图片 slot 错位、表格行不完整、payload 结构未确认等情况 fail closed。

Client：

- 继续只消费 mapper 生成的 `contentModuleList`。
- 不得在 client 私下硬编码 fallback 模块。
- 不得把增强版模块失败降级保存为基础 `STANDARD_HEADER_IMAGE_TEXT`。

## 10. 验收标准

工程验收：

- registry / mapper / Step7 / Step8 / policy / client / worker / tests / docs 闭合。
- project rules 增加反向闭包：Step7 可能产出的 profile/type 必须被 registry/mapper/client/tests 支持。
- 未确认 payload 的模块不能出现在 `enhanced_basic_aplus_v1`。
- 旧 `standard_header_image_text_v1` 路径不回归。

真实 QA：

- 使用测试账号/测试店铺保存真实领星草稿，`submitFlag=0`。
- 编辑页可见 5 个模块，模块类型、顺序、图片、标题、正文、表格/规格/对比字段与本地 plan/mapper 对账一致。
- 不提交审批，不声明 `draft_visible`，不声明 Amazon Seller Central 可见。

## 11. 分阶段建议

M3.0：Payload evidence gate

- 确认目标模块 payload。
- 输出 evidence doc。
- 若目标模块不可确认，写 design change。

M3.1：Technical plan

- 听云基于 PRD 和 evidence 写技术方案。
- 必须覆盖 registry 扩展、Step7/Step8 schema、mapper 多模块结构、client 边界、测试、旧路径兼容、文档索引。
- 需要镜花 review。

M3.2：Implementation

- 分阶段实现 enhanced profile。
- 先不打开真实外部调用；本地测试和 project rules 通过后进入 code review。

M3.3：Real Lingxing QA

- 观止保存真实增强版普通 A+ 草稿，验证字段和模块结构。

M3.4：Commit / push

- 若命在镜花 code review 和观止 QA 通过后 scoped commit/push。

## 12. 当前结论

增强版普通 A+ 可以做，而且是当前最合理路线。

真正 Premium A+ / 高级 A+ 暂不做自动创建或编辑：领星官方文档显示列表可同步高级 A+，但创建/编辑当前只支持基本 A+。后续如要继续，应另开 Premium A+ feasibility，不和本轮增强版普通 A+ 混在一起。
