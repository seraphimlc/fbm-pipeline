# 类目导出文件映射修改记录

本文件专门记录 Amazon 类目导出文件映射相关变更，方便后续回看和回滚判断。

## 记录规则

- 只记录会影响 Step 10 Amazon 导入表格生成、类目模板匹配、模板字段映射或模板文件本身的变更。
- 涉及 `backend/app/pipeline/template_mappings/*.json`、`backend/app/pipeline/step10_amazon_template.py` 类目选择/字段填充逻辑、`backend/app/pipeline/templates/*.xlsm` 时，必须追加记录。
- 每条记录至少包含：日期、改动文件、涉及类目/模板、变更原因、验证命令和结果、后续注意事项。
- 不要覆盖历史记录；只追加新条目。

## 2026-05-24

### Handling Time 默认值填充

- 改动文件：
  - `backend/app/pipeline/step10_amazon_template.py`
  - `backend/app/api/products.py`
  - `backend/app/pipeline/template_mappings/vindhvisk_sofa.json`
  - `backend/app/pipeline/template_mappings/vindhvisk_bicycle.json`
  - `backend/app/pipeline/template_mappings/ride_on_toy.json`
  - `backend/app/pipeline/template_mappings/andy_storage_furniture.json`
  - `backend/app/pipeline/template_mappings/andy_shelf_table_cabinet_gate.json`
- 涉及类目/模板：
  - 所有当前 Step 10 类目导入模板：`CHAIR_SOFA.xlsm`、`BICYCLE_CYCLING.xlsm`、`RIDE_ON_TOY.xlsm`、`DRESSER_STORAGE_DRAWER_STORAGE_BOX_CABINET_STEP_STOOL.xlsm`、`SHELF_TABLE_CABINET_ANIMAL_CAGE_TEMPORARY_GATE.xlsm`
  - 库存/价格更新模板：`PriceAndQuantity.xlsm`
- 变更原因：
  - Amazon 模板中存在 `Handling Time (US)` 字段，需要在所有含该字段的导出表格里默认填写 1 天。
- 主要行为：
  - 映射 JSON 增加 `handling_time`，统一指向 `fulfillment_availability#1.lead_time_to_ship_max_days`。
  - Step 10 导出时只要映射声明 `handling_time` 就写入 `1`。
  - 库存/价格更新导出检测到同一字段时也写入 `1`。
- 验证：
  - `make validate-template-mappings` 通过：5 个映射文件、96 个类目选项、0 个 warning。
  - `python3 -m compileall -q backend/app/pipeline/step10_amazon_template.py backend/app/api/products.py` 通过。
  - `make test-project-rules` 未通过：`test_asin_sync_uses_lingxing_product_code_for_upc` 断言失败，属于 ASIN 同步 UPC 查询规则，与本次 Handling Time 填充逻辑无关；本次相关的 `test_template_mapping_changes_must_be_logged` 已通过。
- 后续注意：
  - 新增类目模板时，如果模板含 `Handling Time (US)`，需同步在映射 JSON 声明 `handling_time`。

### Step 10 图片 OSS URL 复用修复

- 改动文件：
  - `backend/app/pipeline/step10_amazon_template.py`
- 涉及类目/模板：
  - 所有带 `image_fields` 的 Amazon 导入模板
  - 当前包括 `CHAIR_SOFA.xlsm`、`RIDE_ON_TOY.xlsm`、`ANDY_STORAGE_FURNITURE.xlsm`、`VINDHVISK_BICYCLE.xlsm`
- 变更原因：
  - 商品详情页允许人工替换主图/副图后，Step 10 重新生成导入表格时不能继续复用旧表格里的图片 URL，否则会把替换前的主图 URL 写回模板。
- 主要行为：
  - 当当前商品存在主图且 OSS 配置可用时，Step 10 总是按当前 `main_image_path` 和 `gallery_images` 重新上传图片并写入导入模板。
  - 仅在缺少当前主图或 OSS 未配置时，才继续复用旧导入表格中已有的图片 URL，避免无图/无 OSS 情况下丢失已有可用 URL。
- 验证：
  - `npm run build` 通过。
  - `make validate-template-mappings` 通过：5 个映射文件、96 个类目选项、0 个 warning。
  - `make test-project-rules` 未通过：`test_asin_sync_uses_lingxing_product_code_for_upc` 断言失败，属于 ASIN 同步 UPC 查询规则，与本次 Step 10 图片上传逻辑无关；本次相关的 `test_template_mapping_changes_must_be_logged` 已通过。
- 后续注意：
  - 替换主图只更新数据库中的本地图片路径；新的 OSS URL 会在下一次执行 Step 10 生成 Amazon 导入表格时产生。

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
