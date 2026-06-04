# FBM Pipeline 操作与故障手册

这份手册用于日常运营、排错和后续代码分析。先定位步骤，再看对应处理方式。

## 快速检查

```bash
make check
```

检查内容包括模板映射校验、项目规则回归检查和后端代码编译。

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

## Step 10 Amazon 导入表格

常见问题：

- 找不到模板映射。
- 模板字段缺列。
- 图片 URL 未写入。
- 风险等级为 `high_risk`。

处理：

- 先看 `backend/app/pipeline/template_mappings/*.json` 是否有对应品牌/类目。
- 修改映射后运行 `make validate-template-mappings`。
- OSS 未配置或主图缺失时，导入表格不会写入图片 URL，需要先补配置或补图片。
- Step 10 完成后仍需人工确认，确认后才进入商品列表。

## 商品列表与后续运营

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
- 批量导出会按模板路径和类目拆分。
- 数量字段读取最新 `giga_inventory.stock_qty`，不再依赖 `catalog_products.stock`。
- 如果最新库存快照缺少目标 SKU，导出报告会提示跳过或停止该商品。

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
