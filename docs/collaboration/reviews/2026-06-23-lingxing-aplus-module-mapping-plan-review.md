# Lingxing A+ Module Mapping Technical Plan Review

日期：2026-06-23
Reviewer：镜花（agentKey: `jinghua`）
对象：

- `docs/superpowers/specs/2026-06-23-lingxing-aplus-module-mapping-prd.md`
- `docs/superpowers/specs/2026-06-23-lingxing-aplus-module-mapping-technical-plan.md`

## 结论

`TECHNICAL_PLAN_REVIEW / NEEDS_FIX`

P0：无。

P1：mapper validation 与外部副作用边界存在内部矛盾。

方案一方面要求 mapper validation 在 external call 和 `STATUS_UPLOADING` 前完成，另一方面又写了 preferred boundary 为 client 先上传图片、再用 uploaded ids 调 mapper。当前 `lingxing_aplus_publish_client.py` 的图片上传已经是外部副作用，所以如果等上传后才发现 profile/text/position 不合法，就已经违背“不保存半成品、不产生不必要外部副作用”的 gate。

要求修复：

- 所有 plan/profile/text/count/position/local-asset 语义校验必须在任何 Lingxing client 调用前完成。
- 上传后只允许做 post-upload assembly：注入 `uploadDestinationId`、crop data 等上传结果。
- post-upload assembly 不应再发现 unsupported profile、缺 headline/body、模块数量错误或 position 错位；这些必须由 preflight 阶段阻断。

## 通过项

- Step7/Step8 作为生产端纳入契约是正确的；当前代码仍会产出发布端不支持的 comparison/spec 等语义，方案要求用 registry-derived profile/type 对齐。
- Registry 被定义为 mapper、policy/client、project rules 的事实源，不是只写在文档里的口号。
- Payload 结构未知被正确阻断：M2.0 evidence gate 之前不能猜 `body.textList`。
- 旧数据策略为 fail closed，没有继续静默迁移旧 `aplus_plan`。
- 测试和 project rules 明确覆盖空文本 payload、静默强转和生产消费端漂移。

## 非阻断风险

- Project rules 后续应尽量 import/check registry constants，而不是只做脆弱字符串扫描。
- 文本长度限制仍未知；方案已把它放入 evidence gate，可接受。

## Gate Meaning

本 review 不允许进入完整实现。允许继续 M2.0 payload evidence gathering。

若命已在技术方案中补充两阶段 mapper 边界：preflight validation 必须在外部调用前完成，post-upload assembly 只能在 preflight PASS 后注入上传结果。
