# Competitor Visual Match URL vs Contact Sheet Experiment

日期：2026-06-20 CST

执行者：听云（agentKey: `tingyun`）

关联消息：`MSG-20260620-017`

## 结论

建议把 `visual_match_competitors` 默认输入方式改为 **direct image URL only**，并删除 Contact Sheet 和下载拼接 fallback 主路径。

本次同样本 A/B 中，direct URL 与 Contact Sheet 的图片加载、JSON 解析、slot+ASIN 绑定都达到 100%。差异主要在质量和耗时：

- direct URL 平均耗时更低：26.48s vs 32.87s。
- direct URL 把源商品图作为独立 reference 输入，明显更贴近人工视觉直觉。
- 当前 Contact Sheet 实现只把 4 个候选拼成 sheet，prompt 主要依赖商品标题，缺少源商品图视觉 reference，容易把“同类但外观差异较大”的候选打得过高。
- 如果 URL 或模型读取失败，建议任务失败并暴露错误，不再降级到拼接图；否则会引入第二套质量更弱、语义不同的路径。

## 样本

来源：本地 MySQL 旧物理表 `amazon_stylesnap_candidates`，只读查询，不写商品状态、不写 task run。

筛选口径：

- 每组包含 1 个 `source_image_url`。
- 每组至少 4 个 `amazon_image_url`。
- 共选 5 组，每组 4 个候选。候选按 rank 取头部、部分中后段，覆盖高度相似、同类但外观不同、明显结构差异。

样本：

| 样本 | item_code | 商品 | 候选 ASIN |
|---|---|---|---|
| S01 | W808P390791 | Bathroom Floor Cabinet with 4 Drawers | B0GR9JNWRY, B09XJ34QKV, B0CGRQQ676, B07H87L8ZQ |
| S02 | W808P365096 | Cream White Vanity Desk with 3 Drawers | B0GY73FC5F, B0CHWKKK6D, B0GXK6GXF1, B0DTPRSBXS |
| S03 | W808P389332 | Over-The-Toilet Storage Cabinet | B0GVRXRN9K, B0DHS4FYCL, B0DQV1PPBL, B0DHV8RGZK |
| S04 | W808P389333 | Tall Bathroom Storage Cabinet | B0DP91NV42, B0DT9PQXBQ, B0DGWYWQK9, B08BC44ZBW |
| S05 | W808P389334 | Cat Litter Box Enclosure Furniture | B07M8Q2BLF, B0D9LTR2CJ, B0GYYVFW9D, B0G3XQS38Z |

## 执行方式

临时脚本：

- `tmp/competitor_visual_ab_experiment.py`

执行命令：

```bash
cd backend
PYTHONPATH=. EXTERNAL_HTTP_VERIFY_TLS=false .venv/bin/python ../tmp/competitor_visual_ab_experiment.py
```

说明：

- `EXTERNAL_HTTP_VERIFY_TLS=false` 只用于本次真实 VLM 探测，原因是本机 Python/OpenAI 客户端连接 LLM_API 时遇到 CA 链校验失败；`curl` 可连通同一 API 域名。
- 该命令不修改配置文件。
- 脚本只读 DB，只写 `tmp/competitor_visual_ab/`。

证据：

- 原始结果：`tmp/competitor_visual_ab/results.json`
- overview 图：
  - `tmp/competitor_visual_ab/S01/overview/S01_overview.jpg`
  - `tmp/competitor_visual_ab/S02/overview/S02_overview.jpg`
  - `tmp/competitor_visual_ab/S03/overview/S03_overview.jpg`
  - `tmp/competitor_visual_ab/S04/overview/S04_overview.jpg`
  - `tmp/competitor_visual_ab/S05/overview/S05_overview.jpg`

## 指标

| 指标 | Direct URL | Contact Sheet |
|---|---:|---:|
| 样本组数 | 5 | 5 |
| 候选槽位 | 20 | 20 |
| 图片加载成功率 | 100% | 100% |
| JSON 可解析率 | 100% | 100% |
| slot + ASIN 绑定正确率 | 100% | 100% |
| 平均耗时 | 26.48s | 32.87s |
| 错误数 | 0 | 0 |

## 逐样本观察

### S01 Bathroom 4-Drawer Cabinet

人工直观看法：C01 最像源商品；C02/C04 同类但面板和把手风格有差异；C03 是 5 抽结构，差异更大。

- Direct URL：C01 0.96 通过；C02/C04/C03 全部 reject。较严格，符合“只选高度近似”的初筛目标。
- Contact Sheet：C01/C02/C04 均通过，C03 reject。对同类候选放宽。

### S02 Vanity Desk

人工直观看法：4 个候选都是梳妆台类，但与源商品的桌体、镜子、腿型、储物结构差异较大，不应进入高置信 Top。

- Direct URL：4 个候选全部 reject。
- Contact Sheet：4 个候选全部 reject。

### S03 Over-The-Toilet Cabinet

人工直观看法：C01 几乎同图同款；C02/C03/C04 都是同类厕所上方柜，但柜门、开放区、整体结构明显不同。

- Direct URL：C01 0.99 通过；C02/C03/C04 全部 reject。
- Contact Sheet：C01/C02/C03/C04 全部通过，明显过宽。

### S04 Tall Bathroom Storage Cabinet

人工直观看法：C03 最像源商品；C01/C02 同类但结构和开口布局不同；C04 更窄、更简化，差异明显。

- Direct URL：C03 0.90 通过；C01/C02/C04 reject。
- Contact Sheet：C03/C01/C02 通过，C04 reject。对 C01/C02 过宽。

### S05 Cat Litter Box Enclosure

人工直观看法：C03 最像源商品；C01 同类且接近但正面结构不完全一致；C02/C04 差异较大。

- Direct URL：C03 0.96 通过；C01/C02/C04 reject。
- Contact Sheet：C03/C01 通过；C02/C04 reject。Contact Sheet 可接受 C01，但仍比 direct 更宽。

## 风险

- 本次只有 5 组样本，足够判断路径可行性和明显质量倾向，但不足以定最终阈值。
- direct URL 依赖模型服务可访问远程图片 URL；如果 Amazon/GIGA URL 过期、防盗链或 provider 侧无法访问，应让任务失败并记录错误，而不是切换到拼接图。
- 本机 Python 客户端连接 LLM_API 有 CA 链问题；生产运行前需要明确 `EXTERNAL_HTTP_VERIFY_TLS` / CA bundle 配置。
- 当前 Contact Sheet 实现没有把源商品图作为视觉 reference，只用商品标题和候选 sheet；如果继续保留该路径，需要重新设计，不应作为本次已实现路径继续演进。

## 推荐改法

1. 更新 PRD 和 domain index：`visual_match_competitors` 默认输入为 direct image URL only。
2. 竞品视觉初筛服务输入结构：
   - reference：源商品主图 URL。
   - candidates：每个候选独立 `slot + asin + title + rank + price/rating + image_url` 文本块，紧跟对应图片 URL。
3. 输出 schema 固定为候选级 JSON：`slot`、`asin`、`image_loaded`、`same_product_type`、`visual_similarity`、`reject`、`reject_reason`、`reason`。
4. 解析必须做 `slot + asin` 双重校验；不匹配即任务失败或候选失败，不按顺序猜。
5. 删除当前竞品视觉初筛里的 Contact Sheet 生成、候选图下载、拼接证据字段和下载失败分类主路径。
6. URL/VLM/JSON/binding 失败时让任务进入 `visual_match_competitors/failed`，通过 workflow 和任务中心暴露错误。
