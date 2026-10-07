# Amazon 模板映射规范

本文档说明 `backend/app/pipeline/template_mappings/*.json` 的结构、合并规则和维护要求。所有 Amazon 导入表格相关改动先看这里。

## 目标

模板映射 JSON 负责把系统里的商品资料、Listing、图片、包装和类目固定值写入 Amazon 类目模板。运行时主要由 `backend/app/pipeline/step10_amazon_template.py` 读取。

## 文件位置

- 映射目录：`backend/app/pipeline/template_mappings/`
- 模板目录：`backend/app/pipeline/templates/`
- 生成目录：`{material_dir}/amazon import/`

## 顶层字段

| 字段 | 必填 | 说明 |
|------|------|------|
| `brand` | 建议 | 适用品牌，通用模板可用 `*` |
| `category` | 建议 | 默认类目名称 |
| `category_type` | 可选 | 代码里的特殊类目逻辑标识，例如 `ride_on_toy` |
| `template_path` | 必填 | 相对 `backend/app/pipeline/` 的 `.xlsm` 模板路径，或绝对路径 |
| `output_filename` | 必填 | 输出文件名模板，常用 `{item_code}` |
| `data_row` | 必填 | Amazon Template 工作表的数据行，当前通常是 `8` |
| `fixed_values` | 必填 | 固定写入模板的字段和值 |
| `dynamic_fields` | 必填 | 系统动态字段到 Amazon 模板字段的映射 |
| `bullet_fields` | 建议 | 五点字段列表 |
| `image_fields` | 建议 | 主图和副图字段 |
| `package_fields` | 建议 | 包装尺寸和重量字段 |
| `browse_category_options` | 可选 | 人工类目选择和细分类目匹配选项 |
| `required_fields` | 可选 | 除默认关键字段外，额外要求不能空的字段 |

## 类目选项

`browse_category_options` 用于前端人工选择和 Step 10 细分类目判断。

```json
{
  "product_type": "SOFA",
  "node": "sofas",
  "path": "家居、厨具、家装 > 家具 > 客厅家具 > 多人沙发",
  "markers": ["sofas & couches", "sofa", "couch", "多人沙发"]
}
```

类目 key 由 `path` 拆分后生成。若有 `node`，叶子类目显示为 `叶子类目 (node)`。

## 合并规则

当导入、合并或维护模板类目映射时，如果多个来源映射到同一个类目 key，按导入顺序以后导入的映射为准。

只覆盖发生冲突的类目映射；没有冲突的其他类目必须保留原有映射，不得因为一次导入而整体替换或清空。

当前静态类目选项在 `backend/app/api/products.py` 中按文件名排序读取 `template_mappings/*.json`。如果两个文件暴露同一个类目 key，排序靠后的文件会覆盖靠前文件的同 key 选项。

## 修改要求

修改或新增映射后执行：

```bash
make validate-template-mappings
```

如果改动了合并逻辑或导出规则，再执行：

```bash
make test-project-rules
```

## 导出运营边界

Amazon 首次导入表用于新建 listing。已有真实 Amazon ASIN 的商品不应再次生成首次导入表；库存变化应走 PriceAndQuantity 库存更新模板，价格变化暂只作为运营复核和告警输入，未确认定价策略前不自动写入 Amazon。

导出中心是任务工作台，不是商品资格审查页。真实 ASIN、库存缺失、负库存、模板异常、字段异常等应尽量进入导出任务 `result_json.rows` 和导出报告，形成 `exported / skipped / failed` 的逐商品原因，而不是在商品列表上组合成前置资格总 gate。库存为 0 时仍导出首次导入表，Quantity 写入 `0`。

类目来源优先归属商品处理链路：用户选择竞品后，系统从已选竞品详情、类目排名或候选信息同步 `ProductData.categories/leaf_category` 和 `CatalogProduct.leaf_category`。导出中心不做常规临时猜类目；若类目与 mapping marker 或人工记录冲突，应先回到商品详情/竞品类目链路复核，再决定是否需要改 mapping 或人工确认。

如果后续改动首次导入表的价格、类目选择、字段填充或模板匹配逻辑，必须同步追加 `docs/template-mapping-change-log.md` 并跑 `make validate-template-mappings`。

## 常见风险

- `template_path` 指向不存在的 `.xlsm` 文件。
- Amazon 模板字段名复制错误，导致 Step 10 报缺列。
- 类目 key 重复但不是预期覆盖。
- 新类目只加了模板文件，没有加匹配逻辑。
- 修改 `fixed_values` 时误删了合规、配送或 `product_type` 必填字段。

## 当前特殊类目

- `vindhvisk_bed_frame.json` 使用 `BED_FRAME.xlsm`，只覆盖 `Vindhvisk / Bed Frames` 和带有明确 `bed frame` 或 `platform bed` 事实的普通床架。儿童床架、沙发床架和 `adjustable-bed-bases` 不使用此映射。床架 Size、Form Factor、承重、商品/包装规格和 Origin 必须有商品或供应商证据；证据不足时 Step 10 以逐字段原因失败，不使用家具默认值或尺寸反推。`Country of Origin` 不接受公共 Offer 层的 `China` 兜底。
- `vindhvisk_bicycle.json` 使用 `BICYCLE_CYCLING.xlsm`，覆盖 Kids/Folding/Road/Cruiser/Mountain/Electric/Cycling 等自行车任务。Step10 会先按来源叶子类目匹配细分 browse node，再用标题中的 electric/folding/mountain/cruiser/BMX 等关键词兜底。
- 电动自行车会自动补电压、瓦数、锂电池包装等可从标题识别的字段；电池重量、UL/认证编号、FCC/SDoC 仍需要发布前人工复核。

## 2026-10-07 供应商属性规则

床架、自行车、收纳家具和童车使用 `amazon_export/attribute_rules.py`，单商品 writer 和 catalog 合并行共享规则，不为这些字段调用模型。支持规范化材料、Clincher/Tubeless/Tubular、Full → Dual、年龄描述、实际配件、功能、形状、抽屉数和闭合方式。闭合枚举必须匹配模板允许值；映射 `supplier_text_fields` 明确允许材料、配件、外观等来源描述型字符串，不用推荐下拉值代替真实材料。此类自定义文字是否被 Amazon 接受仍需平台校验。尺寸几何和非易碎分类属于规则推导，不代表供应商逐字声明。无证据的涂层工艺、轮胎类型、进口标识或认证不得猜测。

`vindhvisk_bicycle.json` 增加 Tire Type；`andy_storage_furniture.json` 增加 Special Features 和 Closure Type。合并行只覆盖映射配置的语义键，避免清空策略字段。明确 Outdoor Bikes + bicycle/bike 商品身份优先自行车模板；明确电动童车名称走既有 RIDE_ON_TOY，不写回人工/来源类目。

验证：`backend/.venv/bin/python scripts/test_template_attribute_rules.py`；真实文件只读审计：`backend/.venv/bin/python scripts/audit_template_attribute_rules.py --output <report.json> <export.zip>...`。报告检查属性决策及类目路由，不等同于 Amazon 上传成功。

### v2 条件必填与可复用证据

- `required_by_product_type` 记录本批 Amazon 预览暴露的条件必填项。多槽字段只需至少一个非空值；单商品生成保留草稿并提示风险，catalog 导出在最终合并行检查，缺字段的商品写失败原因，不进入可提交工作簿/manifest。
- 读取 canonical `product_source_snapshot.material_facts` 中已提取的供应商 HTML/text；去除售后政策，不使用生成 Listing、竞品、A+ 文案作为属性证据。
- 非美国明确产地 → Imported；MDF → Engineered Wood Panel Construction；外观 Finish Type 可描述 Linen Upholstered / Multicolor Finish，不据颜色断言 Painted；“safer than glass”不作为含玻璃证据。踏凳 Maximum Height 使用供应商 assembled overall height（英寸），不声称是站台高度。
- `amazon_export/reviewed_supplier_attributes.json` 持久保存一次核对的供应商实物/标签证据。每项绑定 SKU、title/material/color 身份指纹、来源相对路径与 SHA-256；身份或原文件变化、文件缺失时该项失效。只给具体 SKU 使用标签 CARB 声明，不推广到其他 MDF 商品，不替代独立证书文件核验。柜门面板样式使用封闭枚举，Sliding 不代替门板样式；无门四抽屉实物按 DRESSER 导出，不改人工类目。

2026-10-07 用户明确要求这类缺失产地按中国处理：自行车映射 `supplier_origin_default=China`。缺失源产地的进口标识记为 `source=user_policy`，不得声称供应商已确认；有实际产地仍优先实际值。Tire Type 与 Material 是不同字段：当前 BICYCLE 的 Tire Type 只有 Clincher/Tubeless/Tubular，没有 Plastic；不能把用户材料偏好填进不接受该值的轮胎结构枚举。

2026-10-07 用户后续明确指定两款受阻商品 W2563P385794 / N726P248345Y 的 Tire Type 为 Clincher：按 SKU 和商品身份绑定的人工记录持久化，属性来源为 `user_confirmation`；不扩展为全库默认，也不冒充供应商事实。人工记录沿用文件 SHA-256 校验，身份或记录变化时失效。

### A+确认前明确数据补充

`listing_check.data_supplement`保存规则/AI/人工结果及来源、原文和输入指纹。规则和已核对SKU证据优先；AI只处理原文出现了模板允许值的剩余字段，必须提供可逐字核对的原文，禁止推测。输入不变时缓存复用。既有候选关键词为空时复用安全同义词，并排除Listing已明确删除的候选；没有可靠候选时保持空值。默认产地China作为用户政策存储，不冒充源事实。认证、尺寸、承重、轮胎结构、涂层工艺等不得由AI推断。导出不再临时调用模型补属性。
