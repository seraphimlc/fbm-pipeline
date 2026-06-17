# FBM Pipeline 操作与故障手册

状态：候选背景，待按 `docs/documentation-rewrite-brief.md` 重写；启动/安全边界以 `docs/domain-index/runtime-security.md` 和 P0 PRD 为准。

这份手册用于日常运营、排错和后续代码分析。先定位步骤，再看对应处理方式。

## 快速检查

```bash
make check
```

检查内容包括模板映射校验、项目规则回归检查和后端代码编译。

主链路 QA gate 见 `docs/main-flow-qa-checklist.md`。观止验收时必须基于磁盘 diff、命令输出、数据库事实、接口响应、页面行为或导出样例给出 `PASS / NEEDS_FIX / BLOCKED`，不能只依赖执行者报告。

## Step 1 商品采集

常见问题：

- 页面加载慢或大健云仓信息缺失。
- 价格为空。
- 素材包缺失或下载超时。

处理：

- 先确认商品链接可在浏览器打开。
- 价格或素材缺失时，按配置策略进入人工复核，不要直接跳过关键数据。
- 已有素材目录时，优先复用现有素材，不要清空用户整理过的文件。

## Step 4 类目获取

常见问题：

- 缺竞品 ASIN。
- Amazon 页面没有抓到面包屑或 BSR 类目。
- 类目不适合当前商品。

处理：

- 默认让任务停在人工复核。
- 在商品详情页手动补 Amazon 类目路径和叶子类目。
- 如果已有人工类目且配置允许，后续流程应沿用已有类目。

## Step 5 Listing

常见问题：

- 标题关键词位置不理想。
- 五点过长或信息和素材不一致。
- Search Terms 为空或过短。

处理：

- 优先根据 Step 1 商品信息、Step 3 关键词、Step 4 类目修正文案。
- 不要编造材质、尺寸、认证、保修或功能。
- 修改后重新生成 Step 10 导入表格，让上架前检查重新汇总风险。

## Step 6 图片分析

常见问题：

- 主图不合规。
- 图库数量不足。
- 商品变体、配件或尺寸信息不清楚。

处理：

- 主图槽位优先保证白底、无文字、无多余道具。
- 辅图可承载场景和卖点，但不能替代主图合规。
- 图片健康提醒会带到 Step 10，不要在最终确认时忽略。

## Step 9 A+ 出图

常见问题：

- 图片生成失败。
- 图片体积超过 Amazon 限制。
- 生成图和产品细节不一致。

处理：

- 检查 GPT Image API 配置和重试次数。
- 保留产品结构、颜色、材质、配件等身份锚点。
- 重新生成单张失败模块时，不要覆盖已确认成功的其他模块，除非明确要求。

## Amazon 导入表格导出

常见问题：

- 找不到模板映射。
- 模板字段缺列。
- 图片 URL 未写入。
- 风险等级为 `high_risk`。
- 导出任务 `partial_failed`，只有部分商品生成产物。
- 全部商品被跳过或失败，没有生成 zip。

处理：

- 先看 `backend/app/pipeline/template_mappings/*.json` 是否有对应品牌/类目。
- 修改映射后运行 `make validate-template-mappings`。
- OSS 未配置或主图缺失时，导入表格不会写入图片 URL，需要先补配置或补图片。
- 导出任务完成后仍需人工确认；导出文件和报告不是“可运营完成”证明。
- `partial_failed` 表示有成功产物，也有跳过或失败行；允许下载成功产物，但必须查看逐商品原因。
- 全部无成功产物时，任务应尽量保留逐商品失败/跳过原因，页面不要只显示 toast 或顶层错误。

## 商品工作台、导出中心与后续运营

主路径：

- `/products` 商品工作台负责商品处理入口和下一步动作。
- `/products/{id}` 商品详情负责选图、选择竞品、抓竞品详情、Listing/图片分析；首屏不应被竞品候选等非首屏请求阻塞。
- `/export-center` 导出中心是任务工作台，负责人工创建导出任务、查看历史任务和下载产物。
- `/offline-tasks` 任务中心是任务事实源，导出任务结果以 `result_json.rows` 和导出报告为准。

状态口径：

- “待导出”表示商品已进入导出入口。
- “已导出”表示已有历史导出任务或文件可追溯，不表示永久禁止再次创建新导出任务。
- 历史导出文件只用于下载和追溯，不作为商品是否可导出的状态主轴。
- 不新增“导出过期”状态。
- A+ 不在当前 P0 主链路；A+ 缺失不能阻断商品进入待导出或创建导出任务。

ASIN 同步：

- 只对已确认商品执行。
- 领星找不到时标记 `not_found`。
- 多匹配时标记 `multiple_found`。
- 不要把不确定的 ASIN 写入真实 ASIN 字段。

A+ 上传：

- 只对已确认商品执行。
- 失败时先看上传错误，再确认领星登录状态和模块图片是否存在。

GIGA 库存与价格同步：

- 页面 `/inventory-sync` 展示最新 GIGA 库存快照，按 SKU 分页，不展示旧批次列表。
- 手动同步命令：
  `backend/.venv/bin/python scripts/giga_inventory_sync.py --site US --task-id manual-giga-inventory`
- 手动同步价格：
  `backend/.venv/bin/python scripts/giga_price_sync.py --site US --task-id manual-giga-price`
- 每日同步应由 cron 或 systemd timer 触发；结果以数据库为准。
- 库存事实表是 `giga_inventory`，价格事实表是 `giga_prices`，同步日志当前复用 `giga_sync_batches`，告警表是 `giga_inventory_alerts` / `giga_price_alerts`。
- 有货/无货切换看 `/api/giga/inventory/alerts?site=US`。
- 价格变化看 `/api/giga/price/alerts?site=US`。
- 商品池 SKU 展开会读取最新价格快照。

导出 Amazon 导入表格：

- 已有真实 Amazon ASIN 的商品不能再次导出导入表格。
- 当前调试阶段，已导出但没有真实 ASIN 的商品可以由用户人工创建新的导出任务；新任务生成新文件，旧任务和旧文件保留。
- 批量导出会按模板路径和类目拆分。
- 数量字段读取最新 `giga_inventory.stock_qty`，不再依赖 `catalog_products.stock`。
- 如果最新库存快照缺少目标 SKU，导出报告和任务结果会提示跳过该商品。
- 库存 0 不阻断商品拉取到待导出主流程；导出执行时继续生成首次导入表，Quantity 写入 `0`，由运营后续决定是否补货或暂缓上架。
- 模板异常、字段异常、真实 ASIN 拦截、库存缺失或负库存等原因应进入任务 `result_json.rows` 或导出报告，页面不能只靠前置文案解释。
- 类目来源归属商品处理链路：选择竞品和抓取竞品详情后，同步到商品资料和待导出记录；导出中心不临时猜类目，也不把缺类目做成常规前置资格总 gate。
- GIGA 价格事实当前用于告警和运营复核，不自动写 Amazon 价格。首次导入表价格字段和 PriceAndQuantity 价格列如需启用，必须先确认定价策略。

Amazon PriceAndQuantity 库存更新模板：

- 当前按库存更新模板使用，只对已有真实 ASIN 的商品导出。
- 按 SKU 写入 Quantity、Fulfillment Channel 和 Handling Time；价格列留空，不更新价格。
- 缺少真实 ASIN、缺少 SKU、最新库存快照缺失或负库存时，写入库存模板导出报告并跳过。
- 已有真实 ASIN 的商品补货或库存变化优先走该模板，不重走首次导入表。

## 模板映射维护

规则：

- 同一类目 key 冲突时，后导入映射覆盖前者。
- 只覆盖冲突类目，非冲突类目保留。
- 新增类目模板按 `docs/add-category-template-sop.md` 执行。

常用命令：

```bash
make validate-template-mappings
make test-project-rules
```
