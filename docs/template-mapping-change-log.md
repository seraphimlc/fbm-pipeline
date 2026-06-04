# 类目导出文件映射修改记录

本文件专门记录 Amazon 类目导出文件映射相关变更，方便后续回看和回滚判断。

## 记录规则

- 只记录会影响 Step 10 Amazon 导入表格生成、类目模板匹配、模板字段映射或模板文件本身的变更。
- 涉及 `backend/app/pipeline/template_mappings/*.json`、`backend/app/pipeline/step10_amazon_template.py` 类目选择/字段填充逻辑、`backend/app/pipeline/templates/*.xlsm` 时，必须追加记录。
- 每条记录至少包含：日期、改动文件、涉及类目/模板、变更原因、验证命令和结果、后续注意事项。
- 不要覆盖历史记录；只追加新条目。

## 2026-06-02

### Amazon 商品描述改用 Step5 生成文案

- 改动文件：
  - `backend/app/models/models.py`
  - `backend/app/database.py`
  - `backend/app/pipeline/step5_listing.py`
  - `backend/app/pipeline/step10_amazon_template.py`
  - `backend/app/api/schemas.py`
  - `backend/app/api/products.py`
  - `frontend/src/api/index.ts`
  - `frontend/src/pages/ProductDetail.tsx`
  - `docs/template-mapping-change-log.md`
- 涉及类目/模板：
  - 所有映射到 `product_description[marketplace_id=ATVPDKIKX0DER][language_tag=en_US]#1.value` 的 Amazon 导入模板。
  - 当前包括 `vindhvisk_sofa.json`、`vindhvisk_bicycle.json`、`ride_on_toy.json`、`andy_storage_furniture.json`、`andy_shelf_table_cabinet_gate.json` 对应模板。
- 变更原因：
  - Amazon listing 在没有 A+ 前需要可用的商品文字描述，不能依赖大健原始商品描述。
  - 大健描述作为供应商原始数据继续保留，但不再作为前台主要展示内容，也不再拼入 Amazon 导入模板的商品描述字段。
- 主要行为：
  - ProductData 新增 `listing_description`、`listing_description_zh`。
  - Step 5 生成标题、五点、商品描述、Search Terms 及中文翻译。
  - Step 10 的 `description` 字段优先写入 `listing_description`；若缺失，仅用 listing 标题和五点兜底，不再追加 `pd.description`。
  - 商品详情页 Listing 文案 tab 展示并允许编辑商品描述；基本信息区不再展示“大健描述”。
- 验证：
  - `backend/.venv/bin/python -m py_compile backend/app/models/models.py backend/app/database.py backend/app/pipeline/step5_listing.py backend/app/pipeline/step10_amazon_template.py backend/app/api/schemas.py backend/app/api/products.py` 通过。
  - `make validate-template-mappings` 通过：5 个 mapping file，96 个 category options，0 warning。
  - `cd frontend && npm run build` 通过，只有 Vite 大 chunk 提示。
- 后续注意：
  - 旧任务需重跑 Step 5 才会生成新的 `listing_description`。
  - 已经生成过 Amazon 导入表格的商品，如需使用新描述，需要重新运行 Step 10。

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

## 2026-06-02

### Amazon 导出库存来源改为最新 GIGA 库存快照

- 改动文件：
  - `backend/app/api/products.py`
  - `backend/app/api/giga.py`
  - `backend/app/services/giga_inventory_sync.py`
  - `backend/app/models/models.py`
  - `backend/app/database.py`
  - `frontend/src/pages/InventorySyncList.tsx`
  - `docs/giga-inventory-sync.md`
  - `docs/configuration.md`
  - `docs/02-API接口文档.md`
  - `docs/05-部署指南.md`
- 涉及类目/模板：
  - 所有通过 `/api/products/catalog/export` 导出的 Amazon 类目导入模板中的 Quantity 字段。
  - 库存/价格更新模板：`PriceAndQuantity.xlsm`。
- 变更原因：
  - GIGA 库存已改为 Open API 每日快照，导出库存不能继续依赖旧的 `catalog_products.stock`。
  - 库存同步页面需要直接展示最新 SKU 库存，而不是旧的网页登录态库存同步批次。
- 主要行为：
  - 新增 GIGA 库存快照同步，库存事实写入 `giga_inventory`，复合唯一键为 `batch_id + site + sku_code`。
  - 当前复用 `giga_sync_batches` 作为库存同步日志，库存 batch 使用 `current_category=inventory_snapshot` 标识。
  - 新增 `giga_inventory_alerts`，记录 `out_of_stock` 和 `restocked`。
  - `/inventory-sync` 页面展示最新库存快照，按 SKU 分页，不再展示旧同步批次。
  - `/api/products/catalog/inventory-template/export` 使用最新 `giga_inventory.stock_qty` 写入库存更新模板。
  - `/api/products/catalog/export` 中如需覆盖 Amazon 导入表 Quantity，也使用最新 `giga_inventory.stock_qty`。
  - 若最新库存快照缺少目标 SKU，则导出跳过/停止该商品并写入报告。
- 验证：
  - `cd backend && .venv/bin/python -m compileall -q app` 通过。
  - `make test-project-rules` 通过。
  - `cd frontend && npm run build` 通过，只有 Vite 大 chunk 提示。
  - `backend/.venv/bin/python scripts/giga_inventory_sync.py --site US --task-id manual-giga-inventory-check` 成功：219 SKU、成功 219、失败 0、告警 1。
  - `curl -s 'http://localhost:8190/api/giga/inventory?site=US&page=1&page_size=3'` 返回最新库存分页数据，总数 219。
- 后续注意：
  - 部署时应配置每日 cron 或 systemd timer 调用 `scripts/giga_inventory_sync.py --site US`。
  - 当前库存同步日志复用 `giga_sync_batches`；如后续要彻底分离商品同步与库存同步，可新增 `giga_inventory_sync_logs`。
  - Seller 分仓和 Buyer 分仓按 GIGA Open API 原样保存；当前 US 数据可能返回空数组。

### Amazon 导入类目优先参考已选同款候选

- 改动文件：
  - `backend/app/pipeline/step10_amazon_template.py`
  - `docs/template-mapping-change-log.md`
- 涉及类目/模板：
  - 所有由 Step 10 自动选择 Amazon 导入模板或细分类目的类目。
  - 当前重点覆盖 `RIDE_ON_TOY.xlsm`、`BICYCLE_CYCLING.xlsm`、`CHAIR_SOFA.xlsm`、`DRESSER_STORAGE_DRAWER_STORAGE_BOX_CABINET_STEP_STOOL.xlsm`、`SHELF_TABLE_CABINET_ANIMAL_CAGE_TEMPORARY_GATE.xlsm`。
- 变更原因：
  - 同款抽卡页面由人工从 Amazon StyleSnap Top 5 候选中选出最匹配竞品；后续导出 Amazon Excel 时，类目应优先参考这个已选竞品上的类目/类目排名文本。
- 主要行为：
  - Step 10 生成模板前，会按当前商品 `item_code` 匹配 `amazon_stylesnap_candidates` 中已选候选。
  - 已选候选的 `category_rank` 和 `raw_snippet` 会并入模板选择和细分类目匹配上下文，但不会覆盖 `product_data.leaf_category` 或真实 ASIN 字段。
  - 导出 warning/fill summary 会记录“Amazon 导入类目参考已选同款候选: ASIN ... / 类目...”。
  - 若没有已选候选，Step 10 保持原有类目选择逻辑。
- 验证：
  - `backend/.venv/bin/python -m py_compile backend/app/pipeline/step10_amazon_template.py` 通过。
  - `make validate-template-mappings` 通过。
- 后续注意：
  - 当前 StyleSnap 候选阶段保存的是卖家精灵增强后的类目排名/摘要文本，不是完整 Amazon browse node；后续 listing 详情抓取若能拿到更完整 breadcrumbs，可继续补强匹配上下文。
