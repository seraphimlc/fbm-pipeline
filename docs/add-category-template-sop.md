# 新增类目模板 SOP

新增 Amazon 类目模板时按这个清单执行，避免模板能生成但上架前检查缺字段。

## 1. 放置模板文件

把 Amazon 下载的 `.xlsm` 放到：

```text
backend/app/pipeline/templates/
```

文件名使用稳定的大写类目名，例如 `PATIO_FURNITURE.xlsm`。

## 2. 新建映射 JSON

在下面目录新增一个映射文件：

```text
backend/app/pipeline/template_mappings/
```

命名建议：`brand_or_category.json`，例如 `vindhvisk_sofa.json`。

至少填写：

- `brand`
- `category` 或 `category_type`
- `template_path`
- `output_filename`
- `data_row`
- `fixed_values`
- `dynamic_fields`
- `image_fields`
- `package_fields`

字段含义见 `docs/template-mapping-spec.md`。

## 3. 增加类目选择项

如果这个模板会支持多个叶子类目，在映射 JSON 中补 `browse_category_options`。

同一个类目 key 冲突时，后导入的映射覆盖前者；只覆盖冲突类目，其他类目保持原样。

## 4. 接入匹配逻辑

根据适用范围选择一种方式：

- 固定品牌 + 叶子类目：更新 `BRAND_TEMPLATE_MAPPINGS`。
- 通用类目：在 `_load_template_mapping` 中增加清晰的 marker 判断。
- 细分类目选择：补 `browse_category_options`，并在 Step 10 写入对应字段。

## 5. 跑校验

```bash
make validate-template-mappings
make test-project-rules
```

校验输出里如果出现重复类目 key，确认是否符合“后导入覆盖”的预期。

## 6. 用样例商品生成一次导入表格

选一个已完成 Step 5、Step 6、Step 9 的样例商品，运行 Step 10 或前端“生成导入表格”。

检查：

- 输出文件在 `{material_dir}/amazon import/`
- `Template` 工作表第 8 行有 SKU、标题、品牌、价格、图片、包装
- `amazon_template_fill_summary.risk_level` 合理
- 高风险提醒没有被静默吞掉
- 导出任务或导出报告能区分成功、跳过和失败原因；至少确认库存缺失/负库存、模板缺失/停用、字段异常、已有真实 ASIN 等原因不会只停留在 toast 或顶层错误。
- 库存数量应来自最新 GIGA 库存快照；库存 0 也应导出并写入 Quantity `0`，不阻断商品进入待导出或首次导入表生成。
- 如果模板涉及价格字段，先确认价格来源和运营策略；未确认前不得把 GIGA `effective_price` 自动写入 Amazon 价格字段。

## 7. 更新文档

如果新增了特殊规则、字段兜底、类目 marker 或运营注意事项，同步更新：

- `docs/template-mapping-spec.md`
- 当前 pipeline/runbook 文档；重写前按 `docs/documentation-rewrite-brief.md` 确认目标文件
- 必要时更新 `docs/runbook.md`
