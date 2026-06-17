# Domain Index: Export Flow

## 范围

- Amazon 导出、导出中心、导入模板、类目映射。
- Step 10、UPC、导出任务和模板校验。
- 不覆盖平台实际上传后的运营状态。

## 当前口径

- 导出只生成导入表格和风险提示，不代表平台上架成功。
- 已有真实 Amazon ASIN 的商品，不允许再次导出 Amazon 导入表格。
- 改模板、类目映射、Step 10 或导出字段时，必须更新 `docs/template-mapping-change-log.md`。
- 不覆盖真实导出文件、模板文件或已生成素材，除非用户明确要求。

## 关键入口

- 导出中心页面：`frontend/src/pages/CatalogList.tsx`
- 导出 planner：`backend/app/task_planners/catalog_export.py`
- 导出 worker：`backend/app/task_runtime/catalog_export_workers.py`
- 商品 API：`backend/app/api/products.py`
- Amazon 模板旧入口：`backend/app/pipeline/step10_amazon_template.py`
- Amazon 导出规则层：`backend/app/pipeline/amazon_export/`
- 模板映射：`backend/app/pipeline/template_mappings/*.json`
- 模板文件：`backend/app/pipeline/templates/*.xlsm`
- UPC：`frontend/src/pages/UpcPoolPage.tsx`, `backend/app/services/upc_pool.py`
- 表：`catalog_products`, `task_runs`, `task_steps`, `task_step_events`, `products`, `product_data`

## 关键流程

- 导出中心：`CatalogList.tsx` -> 商品 API/导出任务 -> 任务中心。
- Amazon 导出：planner -> worker -> `backend/app/pipeline/amazon_export/`。
- 模板/类目：template mappings -> templates -> Step 10/导出规则层。
- UPC：导出前按当前 UPC service/model 逻辑定位。

## 相关文档

- `docs/template-mapping-spec.md`
- `docs/template-mapping-change-log.md`
- `docs/add-category-template-sop.md`
- `docs/main-flow-user-path.md`
- `docs/main-flow-qa-checklist.md`
- `docs/superpowers/specs/2026-06-16-task-center-state-action-prd.md`

## 验证入口

- 导出中心：`http://localhost:3190/export-center`
- 任务中心：`http://localhost:3190/task-runs`
- 模板映射校验：`make validate-template-mappings`
- 项目规则校验：`make test-project-rules`

## 常见定位

- 导出任务状态：先看 `catalog_export.py`、`catalog_export_workers.py` 和 `task_runs` 事件。
- 模板字段问题：先看 `backend/app/pipeline/amazon_export/` 和 `template_mappings/*.json`。
- 类目映射问题：先看 `docs/template-mapping-spec.md` 和 `docs/template-mapping-change-log.md`。
- UPC 问题：先看 `backend/app/services/upc_pool.py`。

## 维护规则

只有页面/API/核心 service/action/table/导出字段/模板映射/验证入口变化时更新本文。普通 bug fix、函数内部重构、样式微调、测试补充不需要更新。
