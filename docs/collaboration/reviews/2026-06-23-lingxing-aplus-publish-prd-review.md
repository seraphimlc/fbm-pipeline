# Lingxing A+ Publish PRD Review

结论：`PRODUCT_DESIGN_REVIEW / PASS_WITH_CONSTRAINTS`

本结论只表示 PRD 的产品边界、任务分层、状态语义和后续技术方案入口可以继续推进；不代表代码 review、QA PASS、真实领星链路验收，也不授权直接编码。

## 审查范围

- `docs/superpowers/specs/2026-06-23-lingxing-aplus-publish-after-aplus-done-prd.md`
- `docs/lingxing-aplus-upload.md`
- 已知代码事实：
  - `backend/app/services/aplus_upload.py`
  - `backend/app/services/asin_sync.py`
  - `backend/app/models/models.py`

## 通过判断

1. A+ 生成、ASIN 同步、领星 A+ 发布被拆成独立链路，边界成立。

   PRD 没有把领星发布状态塞回商品主 workflow，也没有让领星失败回滚商品 `export_ready` 或 A+ 本地生成结果。这符合当前项目“商品主链路”和“派生链路”分离的方向。

2. ASIN 对齐作为领星发布硬前置是正确的。

   PRD 明确禁止在 A+ UI 里临时猜选 ASIN，要求通过 Amazon 导入时的 seller code/MSKU 与领星 Listing 数据对齐。旧 `asin_sync.py` 目前 UPC 优先，这一点已被列为必须调整的风险，不能沿用到 A+ 发布前置。

3. `draft_saved`、`draft_visible`、`submitted` 的状态分层成立。

   PRD 区分了“领星草稿保存成功”和“Amazon A+ 草稿箱可见/已同步”，并把提交审批作为显式受控动作。这能避免把外部平台的不同事实压成一个 `uploaded` 状态。

4. 默认关闭与显式提交审批的安全边界成立。

   PRD 要求 `AUTO_LINGXING_APLUS_AFTER_DONE=false`、`LINGXING_APLUS_SUBMIT_FOR_APPROVAL=false`，这能防止 A+ 生成完成后未经 gate 直接触发真实外部发布或审批。

5. 技术方案 gate 是必要且充分的下一步。

   本链路涉及真实外部平台、登录态、异步任务、状态 registry、旧代码迁移、数据表事实源和 QA 入口。直接编码风险过高，应先由听云写整体 `TECHNICAL_PLAN`，再由若命和镜花评审。

## 必须在技术方案中钉住的约束

1. 首版终点必须讲清楚。

   技术实现可以先完成 `draft_saved`，但验收口径不能把 `draft_saved` 称为 `draft_visible`。如果要宣称 Amazon A+ 草稿箱可见，必须有领星同步/查询或真实 Amazon/Seller Central 页面证据。

2. 事实源必须唯一。

   技术方案需要明确 `task_runs`、`AplusUploadBatch/AplusUploadItem`、`CatalogProduct`、`Product`、`ProductAplus` 分别承载什么。不能让旧上传批次表和新任务中心各自写一套不可 reconcile 的发布状态。

3. seller sku 必须可追溯。

   如果 Amazon 导出模板里的 seller code/MSKU 不总是等于 `CatalogProduct.item_code` / `ProductData.item_code`，必须新增并持久化 `amazon_seller_sku` 或等价字段。A+ 发布前置匹配必须以该真实导出键为主，UPC 只能辅助诊断。

4. 旧 `aplus_upload.py` 不能原样挂回自动链路。

   旧模块使用进程内 `asyncio.create_task()`，默认提交审批，且存在 `settings` 未导入问题。技术方案必须拆出能力层，并把新链路放进 `task_runs` 的可恢复、可审计、可重试机制。

5. 真实 QA 入口必须提前设计。

   fixture 和内部行为脚本只能证明内部逻辑。领星登录态、真实保存草稿、草稿可见性、提交审批必须分别给出可执行 QA 入口和证据标准。

## 未覆盖

- 未做代码 review。
- 未做页面 QA。
- 未启动服务、未跑真实 `task_runs`。
- 未确认 Amazon Seller Central A+ 草稿箱可见性。
- 未确认最终店铺、ASIN 样本、A+ 模块内容质量是否可用于真实发布。

## 下一步

若命派发听云写整体技术方案，不直接编码。技术方案完成后：

1. 若命审产品语义、范围、阶段顺序和用户目标。
2. 镜花审架构、数据模型、状态闭环、任务生命周期、测试和维护性。
3. 两个 gate 通过后，再按阶段派发实现。
