# Main Flow QA Checklist

更新：2026-06-05

本文档是观止（`agentKey: guanzhi`）用于验收当前 P0 主链路的 QA gate 清单。范围聚焦“商品拉取 -> Product 草稿 -> CatalogProduct 待导出 -> 人工创建导出任务 -> 任务结果/文件”。A+ 生成/上传、多店铺 ASIN 模型、自动写 Amazon 价格策略不在当前 P0 验收范围。

## QA 结论规则

最终结论只能是：

- `PASS`：验收对象有明确实现范围，且磁盘 diff、命令输出、测试数据库事实、接口响应、页面行为或导出样例能证明主路径可走通，关键风险有解释。
- `NEEDS_FIX`：主路径存在可复现阻断、数据覆盖风险、状态表达误导、导出结果不可解释、幂等失效或回归测试缺口。
- `BLOCKED`：缺少必要运行环境、账号登录、测试数据、用户确认或外部服务，导致无法用事实完成验收。

不接受“应该可以”“执行者说已修”作为 PASS 依据。每次 `REVIEW` 必须列出证据来源和未覆盖风险。

## 安全边界

默认只读或小范围测试：

- 不覆盖 `data/`、`backend/data/`、真实商品数据、人工类目、真实 ASIN、已生成素材、A+ 图片或 Amazon 导入表格输出。
- 不自动 commit、push、merge、deploy。
- 不把真实密钥、账号、完整商品敏感数据或真实 ASIN 批量写入 inbox。
- 涉及 Step 10、`template_mappings/*.json`、模板文件或会影响 Amazon 导入字段/类目匹配的改动，必须检查 `docs/template-mapping-change-log.md`，并跑 `make validate-template-mappings` 或 `make check`。

## 端到端路径

验收路径按用户能否继续操作来判断：

1. 商品拉取任务可创建，并在任务中心看到任务记录。
2. 任务失败、中断、暂停、恢复或完成时有明确状态和下一步动作。
3. raw/source 数据进入 Product 草稿时，不覆盖用户已确认的图片顺序、竞品、类目、Listing 或导出状态。
4. Product 草稿保留稳定来源信息；如果没有独立来源字段，`gigab2b_raw_snapshot` 等结构必须可追溯且有测试保护。
5. 商品工作台展示 Product/SKU 维度的可处理对象，不把 GIGA raw/source 半成品当成主操作对象。
6. 商品详情首屏可渲染商品事实、图片、步骤和可继续操作入口，不被竞品候选等非首屏请求卡死。
7. 用户可完成或复核选图、搜索候选竞品、选择竞品、抓取竞品详情。
8. 类目从选中竞品/抓取详情链路落到 `ProductData` 和 `CatalogProduct`，导出中心不临时猜类目。
9. Listing/图片分析完成后，商品进入待导出或导出中心路径，A+ 缺失不阻断当前 P0 主链路。
10. 导出中心可人工创建导出任务；已导出但没有真实 ASIN 的商品可再次新建导出任务。
11. 同一 `offline_task` / step 重跑必须幂等，不重复生成同一任务 zip。
12. 任务中心和导出中心对同一导出任务的状态、下载入口、失败/跳过原因表达一致。

## 分层验收

raw/source 层：

- 证据优先来自 GIGA source 表、拉取任务 `result_json`、draft upsert 结果和代码 diff。
- 拉取或 upsert 结果应尽量结构化为 created、updated、skipped、error，而不是只写日志。
- 字段覆盖策略必须是白名单或在代码/文档中可追溯。

Product 草稿层：

- Product 是工作台对象，承载图片确认、竞品选择、类目、Listing 和图片分析过程。
- 重新拉取 raw/source 不应清空用户已确认的主图顺序、已选竞品、人工类目、Listing 文案或处理状态。
- 商品详情失败态要允许继续处理或明确返回任务中心查看。

CatalogProduct 待导出层：

- CatalogProduct 是导出候选对象，不等同于 raw/source 或所有 Product。
- “待导出”表示进入导出入口，不等于 Amazon 可运营完成。
- “已导出”表示历史任务/文件可追溯，不表示永久禁止再次创建新导出任务。
- 已有真实 Amazon ASIN 的商品仍禁止再次生成首次导入表格；多店铺 ASIN 模型另行讨论。

## 任务状态验收

任务中心状态必须以数据库事实和接口响应为准：

- `pending`：任务已创建但未执行；页面不应显示已产出结果。
- `running`：任务正在执行；刷新后仍能看到当前状态或明确恢复策略。
- `paused`：用户或系统暂停；页面提供继续/恢复路径，不当作失败。
- `interrupted`：任务被服务重启或执行中断遗留；页面解释为未完成，需要重跑或查看详情。
- `done`：任务完成；对导出任务只表示结果产物已生成，不等于可运营完成。
- `failed`：没有成功产物或系统异常；仍应尽量保留结构化失败/跳过原因。
- `partial_failed`：有成功产物，也有跳过或失败行；有 zip 时必须允许下载，并展示逐商品原因。

## 导出任务结果验收

导出任务 `result_json` 至少应包含：

- `status`
- `requested_count`
- `success_count`
- `skipped_count`
- `failed_count`
- `filename`
- `file_path`
- `oss_object_key`
- `oss_url`
- `report_filename`
- `created_at`
- `rows`

`rows[]` 至少应包含：

- `catalog_id`
- `product_id`
- `item_code`
- `category`
- `status`
- `reason`
- `template_file`
- `output_file`

行状态使用稳定枚举：

- `exported`
- `skipped`
- `failed`

状态规则：

- 全部成功：任务 `done`，zip 可下载，报告可追溯。
- 有成功也有跳过或失败：任务 `partial_failed`，zip 可下载，逐商品原因可见。
- 全部没有成功产物：任务 `failed`，不要求有 zip，但必须尽量保留 `rows` 说明原因。
- 库存 0、真实 ASIN、模板异常、字段异常都应进入 `rows.reason` 或导出报告，不应只靠前端资格总 gate。

## 验收证据优先级

优先使用能复查的事实：

- `git diff -- <相关文件>`：确认实际改动范围。
- `make test-project-rules`、`make check`、`cd frontend && npm run build`：确认规则、后端编译和前端构建。
- 数据库只读查询：确认任务、步骤、Product、CatalogProduct 和导出结果状态。
- 接口响应：确认创建任务、任务详情、下载入口、导出中心列表结果一致。
- 页面行为：确认用户路径真的可走通，首屏不被非关键请求卡死。
- 导出样例或报告：确认 `exported/skipped/failed` 与 zip、报告、任务结果一致。

## 常见 NEEDS_FIX 条件

出现以下任一情况，不应给 PASS：

- 执行者写了 `DONE_CLAIMED`，但没有可复查命令或数据证据。
- 商品拉取或 draft upsert 覆盖用户已确认信息。
- 商品详情首屏因候选竞品、外部接口或非关键请求卡住。
- 导出中心仍把“已导出”表达成无真实 ASIN商品也不能再次新建导出任务。
- 同一任务/步骤重复执行后生成多个 zip 或覆盖历史结果。
- `partial_failed` 有 zip 但页面或接口不能下载。
- 全失败或全跳过只剩顶层错误，没有逐商品原因。
- 任务中心和导出中心对同一任务状态、计数、下载入口或原因表达不一致。
- Step 10/template mapping 相关改动没有同步 change log 或没有跑映射校验。

## REVIEW 输出模板

```markdown
### MSG-YYYYMMDD-NNN - REVIEW

- From: 观止（agentKey: `guanzhi`）
- To: ...
- Status: PASS / NEEDS_FIX / BLOCKED
- Created: YYYY-MM-DD HH:mm CST
- Related to:
  - ...
- Scope:
  - 本次验收对象和不覆盖范围。
- Evidence:
  - 磁盘 diff / 命令输出 / 数据库事实 / 接口响应 / 页面行为 / 导出样例。
- Findings:
  - 关键问题或风险；没有问题时写明未覆盖风险。
- Step 10 / mapping:
  - 是否涉及模板、mapping、字段填充或 change log；相关校验结果。
- Conclusion:
  - `PASS` / `NEEDS_FIX` / `BLOCKED`，并说明原因。
```
