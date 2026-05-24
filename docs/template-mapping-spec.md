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

## 常见风险

- `template_path` 指向不存在的 `.xlsm` 文件。
- Amazon 模板字段名复制错误，导致 Step 10 报缺列。
- 类目 key 重复但不是预期覆盖。
- 新类目只加了模板文件，没有加匹配逻辑。
- 修改 `fixed_values` 时误删了合规、配送或 `product_type` 必填字段。

## 当前特殊类目

- `vindhvisk_bicycle.json` 使用 `BICYCLE_CYCLING.xlsm`，覆盖 Kids/Folding/Road/Cruiser/Mountain/Electric/Cycling 等自行车任务。Step10 会先按来源叶子类目匹配细分 browse node，再用标题中的 electric/folding/mountain/cruiser/BMX 等关键词兜底。
- 电动自行车会自动补电压、瓦数、锂电池包装等可从标题识别的字段；电池重量、UL/认证编号、FCC/SDoC 仍需要发布前人工复核。
