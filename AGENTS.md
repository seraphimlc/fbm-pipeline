# 项目级规则

## 工作方式

- 先查看现有流程、映射 JSON、文档和配置，再修改代码。
- 不要把用户已有商品数据、人工类目、真实 ASIN、已生成素材或模板输出整体覆盖掉；除非需求明确要求重建。
- 涉及 Amazon 导入模板、类目、字段名、上架检查时，优先查看 `backend/app/pipeline/template_mappings/*.json`、`backend/app/pipeline/step10_amazon_template.py` 和 `docs/template-mapping-spec.md`。

## 模板类目映射合并

当导入、合并或维护模板类目映射时，如果多个来源映射到同一个类目 key，按导入顺序以后导入的映射为准。

只覆盖发生冲突的类目映射；没有冲突的其他类目必须保留原有映射，不得因为一次导入而整体替换或清空。

## 类目导出文件映射修改记录

- 每次新增、删除或修改 Amazon 类目导出文件映射时，必须同步追加记录到 `docs/template-mapping-change-log.md`。
- 记录范围包括 `backend/app/pipeline/template_mappings/*.json`、`backend/app/pipeline/step10_amazon_template.py` 中的类目选择/字段填充逻辑、`backend/app/pipeline/templates/*.xlsm` 模板文件，以及会影响 Step 10 导出字段或类目匹配的文档/配置。
- 每条记录至少写明日期、改动文件、涉及类目/模板、变更原因、验证命令和结果、后续注意事项。
- 该记录是类目导出文件映射修改专用，不用于泛化记录无关功能改动。

## Amazon 导入表格

- 新增或修改类目模板时，必须同步维护 `template_mappings/*.json`，并跑模板映射校验。
- 已有真实 Amazon ASIN 的商品，不允许再次导出 Amazon 导入表格。
- Step 10 只负责生成导入表格和风险提示；任务完成后仍需人工确认，不能自动进入可运营商品列表。

## 新增类目模板

新增类目模板按 `docs/add-category-template-sop.md` 执行，至少包含模板文件、映射 JSON、类目匹配逻辑、校验结果和一个样例商品生成检查。
