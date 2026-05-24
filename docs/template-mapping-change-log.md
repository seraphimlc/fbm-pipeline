# 类目导出文件映射修改记录

本文件专门记录 Amazon 类目导出文件映射相关变更，方便后续回看和回滚判断。

## 记录规则

- 只记录会影响 Step 10 Amazon 导入表格生成、类目模板匹配、模板字段映射或模板文件本身的变更。
- 涉及 `backend/app/pipeline/template_mappings/*.json`、`backend/app/pipeline/step10_amazon_template.py` 类目选择/字段填充逻辑、`backend/app/pipeline/templates/*.xlsm` 时，必须追加记录。
- 每条记录至少包含：日期、改动文件、涉及类目/模板、变更原因、验证命令和结果、后续注意事项。
- 不要覆盖历史记录；只追加新条目。

## 2026-05-24

### SOFA/CHAIR 与 RIDE_ON_TOY 导出修复

- 改动文件：
  - `backend/app/pipeline/step10_amazon_template.py`
  - `backend/app/pipeline/template_mappings/ride_on_toy.json`
- 涉及类目/模板：
  - `CHAIR_SOFA.xlsm`
  - `RIDE_ON_TOY.xlsm`
  - `Sofas & Couches`
  - `休闲椅 (living-room-chaise-lounges)`
  - `Electric Vehicles`
- 变更原因：
  - Amazon processing summary 显示 sofa 批次因 `Seating Capacity` 缺失被阻塞。
  - 超大 chaise 使用 `CHAIR` 会触发 Amazon CHAIR 尺寸上限告警，后续改为走 `SOFA / sofas`。
  - RIDE_ON_TOY 批次缺 `sub_brand` 为非阻塞质量告警，补充映射和填充值。
- 主要行为：
  - 支持识别 `3-Seat`、`2-Seater` 等带连字符座位数。
  - 对 sofa/sectional/modular/sofa bed 等按标题和尺寸估算 `Seating Capacity`。
  - 超出 CHAIR 尺寸阈值的 chaise 不再优先使用 `CHAIR / living-room-chaise-lounges`，改走 `SOFA / sofas`。
  - RIDE_ON_TOY 写入 `sub_brand`。
- 验证：
  - `make validate-template-mappings` 通过。
  - `make test-project-rules` 通过。
  - 重新生成涉及的 27 个模板，`amazon_template_fill_summary.missing_required_count = 0`。
- 后续注意：
  - RIDE_ON_TOY 的 `ps_toys_dv_us` 属 Amazon 玩具合规文档要求，不是普通模板字段缺失，仍需真实资质资料。
