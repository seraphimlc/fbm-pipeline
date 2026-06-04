# Codex Handoff: GIGA 商品池、库存价格同步、Amazon StyleSnap 同款验证

日期：2026-06-02  
仓库：`/Users/liuchang/Documents/gitproject/fbm-pipeline`  
当前重点：从 GIGA 商品池出发，用本地主图通过 Amazon StyleSnap + 卖家精灵找到同款候选，后续让用户从 5 个候选中选择，再进入 listing 页抓内容。

## 1. 接手先读

新会话进入后先执行：

```bash
cd /Users/liuchang/Documents/gitproject/fbm-pipeline
git status --short
sed -n '1,220p' docs/codex-cold-start.md
sed -n '1,260p' docs/codex-handoff-2026-06-02-amazon-stylesnap.md
```

注意：

- 当前工作区有较多未提交改动，接手时不要随手回滚、清空或覆盖。
- 不要打印 `backend/.env` 的 secret 值。
- 不要自动 commit / push，除非用户明确要求。
- 用户的工作方式是：思考 -> 规划 -> 任务拆分 -> 纠偏 -> 任务执行 -> 测试 -> 复盘。

## 2. 最近业务背景

平台目标是 FBM 铺货自动化：

1. 从 GIGA 大健云仓拉取商品，站点当前为 `US`。
2. 商品应按 `item` 维度承载后续流程，SKU 作为 item 下的子体保存。
3. 页面展示也倾向 item 维度：每行 item，左侧 `+` 展开后显示 SKU。
4. Listing、图片、A+ 等后续生成可以 item 维度做一次；但导出 Amazon Excel 时必须把所有子 SKU 及父子变体关系填写完整。
5. GIGA 原始 `associateProductList` 为空时，不允许强行聚合；父子关系必须来自可信数据。
6. 库存、价格都要做每日同步，并记录日志。库存/价格变化需要可提示和告警。
7. 库存真源和价格真源都应落数据库，下游导出使用最新库存/价格，不依赖临时文件。

## 3. GIGA 商品、库存、价格当前状态

已做过或讨论过的模块：

- GIGA Buyer OpenAPI 客户端和若干 buyer 接口封装。
- GIGA 商品拉取、item/SKU 存储、商品池页面。
- GIGA 库存同步：应有“同步日志表 + 最新库存表/库存事实表”的思路。
- GIGA 价格同步：接口为 `/b2b-overseas-api/v1/buyer/product/price/v1`，最多 200 个 SKU 一批，限流 10 秒 10 次。
- 图片落盘与映射：用户要求图片既落表也落盘，但随后明确说“不要全量下载，目前这些已经够用了，下载图片先停”。后续只做映射回填和按需使用现有图片。

相关文件可能包括：

```text
backend/app/services/giga_openapi.py
backend/app/services/giga_inventory_sync.py
backend/app/services/giga_price_sync.py
backend/app/services/giga_image_assets.py
backend/app/api/giga.py
scripts/giga_sync.py
scripts/giga_inventory_sync.py
scripts/giga_price_sync.py
scripts/giga_image_backfill.py
docs/giga-buyer-openapi-reference.md
docs/giga-inventory-sync.md
```

接手后要先看当前代码实现和数据库模型，不要根据这里的文字直接重写。

## 4. Amazon 同款匹配目标

用户给过一个旧技能包：

```text
/Users/liuchang/Documents/Codex/2026-05-17/new-chat/deliverables/amazon-item-match-review-ubuntu-ready.zip
```

已经学习到的目标调整：

- 不只是找 1 个同款，要找 5 个候选。
- 5 个候选要排序。
- 用户选择其中一个后，再进入该 Amazon listing 页面抓内容。
- 抓内容应包含 listing 标题、价格、评分、卖家、图片、五点、描述/A+、详情字段等可见内容。
- 这次不是用普通 Amazon 搜索，也不是 App；用户本机 Chrome 装了卖家精灵插件，入口是：

```text
https://www.amazon.com/stylesnap?q=local
```

## 5. 已验证的 StyleSnap 链路

本机 Chrome 已开启“Allow JavaScript from Apple Events”，AppleScript 能执行 Chrome 页面 JS。

卖家精灵插件位置：

```text
/Users/liuchang/Library/Application Support/Google/Chrome/Default/Extensions/lnbmbgocenenhhhdojdielgnmeflbnfb/5.0.3_0
```

关键发现：

- StyleSnap 页面有 `<input type="file" id="file" accept="image/avif,image/*">`。
- 卖家精灵支持本地图片上传路径：把图片 data URL 存入 `localStorage.uploadedImage`，然后跳转 `/stylesnap`。
- 插件会读取 `localStorage.uploadedImage`，构造 `File/DataTransfer`，注入 `#file` 并触发上传。
- 上传成功后页面变成：

```text
https://www.amazon.com/stylesnap?q=local
```

页面结果区标题为 `SIMILAR PRODUCTS`，卖家精灵会逐步注入 ASIN、品牌、卖家、配送、类目排名、价格、评分、颜色/尺寸等字段。

## 6. 烟测文件

本轮选了 10 个 SKU 的本地主图，manifest 在：

```text
/Users/liuchang/Documents/gitproject/fbm-pipeline/data/tmp/stylesnap_smoke/manifest.json
```

验证脚本在：

```text
/Users/liuchang/Documents/gitproject/fbm-pipeline/data/tmp/stylesnap_smoke/run_stylesnap_smoke.py
```

最终结果在：

```text
/Users/liuchang/Documents/gitproject/fbm-pipeline/data/tmp/stylesnap_smoke/results_dedicated.json
```

第一次链路结果保留在：

```text
/Users/liuchang/Documents/gitproject/fbm-pipeline/data/tmp/stylesnap_smoke/results.json
```

`data/tmp` 可能不纳入 git，接手时如果文件不在，需要从数据库重新选 10 个 SKU 或让用户提供。

## 7. 本轮 10 SKU 烟测结果

最终一轮结果：10 个 SKU 全部成功，每个都有 5 个候选 ASIN。

Top 1 摘要：

| SKU | item | Top 1 ASIN | 品牌 | 卖家 | 价格 |
|---|---|---|---|---|---|
| `N726P248345B` | `N726P248345Y` | `B0FJY14SQY` | Merax | Amazon | `$129.99` |
| `N726P248345C` | `N726P248345Y` | `B0F124RNML` | Merax | Amazon | `$109.99` |
| `N726P248345O` | `N726P248345Y` | `B0F127RNRQ` | Merax | VGT-USVN | `$109.99` |
| `N726P248345Y` | `N726P248345Y` | `B0FL6DQ6JG` | anwickjeff | ZEKOshop | `$59.98` |
| `W1019138604` | `W1019138605` | `B0F6BWK5LW` | YHUBHSIS | Amodeoday | `$88.29` |
| `W1019138605` | `W1019138605` | `B0F6CMDPF7` | YHUBHSIS | Amodeoday | `$88.29` |
| `W1019P171907` | `W1019138605` | `B0BVF9VZGB` | 部分字段未注入 | 部分字段未注入 | `$199.99` |
| `W101984862` | `W101984862` | `B0DKFBJFHT` | 部分字段未注入 | 部分字段未注入 | `$129.00` |
| `W1019P165865` | `W1019P165868` | `B0D2B6YRT7` | AVGVLIJ | Lifelong Research | `$119.99` |
| `W1019P165868` | `W1019P165868` | `B0FB3QN5Y7` | 部分字段未注入 | 部分字段未注入 | `$98.29` |

完整 Top 5 看 `results_dedicated.json`。

## 8. 重要坑点

1. Chrome 活动标签可能被 OpenClaw、本地页面或别的窗口抢走。脚本现在会新建专用 Chrome 窗口，并记录 `/tmp/stylesnap-window-id.txt`。
2. StyleSnap 页面上传后，旧结果可能还没清空。脚本通过先改 `document.body.innerText` 再跳转，降低旧结果抢跑风险。
3. 卖家精灵字段不是瞬间注入。脚本需要等到页面出现 `品牌:` 和 `卖家:`，否则只能拿到 ASIN/价格，品牌/评分/类目可能为空。
4. StyleSnap 结果页通常不暴露完整 listing 标题。候选阶段可用 ASIN、价格、品牌、卖家、类目、评分做初筛；完整标题和详情要等用户选定 ASIN 后进入详情页抓。
5. 视觉搜索质量会受图片裁切影响。比如同一个 item 的不同颜色/角度可能返回不同 ASIN，需要后续做 item 级聚合和人工确认。

## 9. 下一步建议

建议按这个顺序继续：

1. 把临时 `run_stylesnap_smoke.py` 正式化为项目内 Amazon 同款候选采集模块。
2. 输入从 SKU 改成 item 维度：每个 item 选择代表主图，同时保留所有子 SKU。
3. 每个 item 产出 Top 5 候选，字段至少包含：
   - rank
   - asin
   - url
   - brand
   - seller
   - delivery
   - price
   - rating
   - category_rank
   - color / size / style
   - raw snippet
4. 做一个 Review 页面：左侧 GIGA item 图片和 SKU 列表，右侧 5 个 Amazon 候选，让用户选择。
5. 用户选中后，进入 `https://www.amazon.com/dp/{ASIN}` 抓完整 listing 内容。
6. 把选择结果和 listing 抓取结果落数据库，后续用于生成 listing、图片/A+ 和 Amazon Excel。

## 10. 可复跑命令

复跑当前 10 SKU 烟测：

```bash
cd /Users/liuchang/Documents/gitproject/fbm-pipeline
rm -f data/tmp/stylesnap_smoke/results_dedicated.json /tmp/stylesnap-window-id.txt
/usr/bin/python3 -m py_compile data/tmp/stylesnap_smoke/run_stylesnap_smoke.py
/usr/bin/python3 data/tmp/stylesnap_smoke/run_stylesnap_smoke.py
```

读取结果摘要：

```bash
/usr/bin/python3 - <<'PY'
import json
from pathlib import Path
p=Path('/Users/liuchang/Documents/gitproject/fbm-pipeline/data/tmp/stylesnap_smoke/results_dedicated.json')
data=json.loads(p.read_text())
print('rows', len(data), 'with_5', sum(len(r.get('candidates',[]))>=5 for r in data))
for r in data:
    c=(r.get('candidates') or [{}])[0]
    print(r['sku_code'], r['item_code'], c.get('asin'), c.get('brand'), c.get('seller'), c.get('price'))
PY
```

## 11. 当前接手判断

链路已经证明可行：本地 GIGA 主图 -> Chrome StyleSnap -> 卖家精灵增强结果 -> 抽取 Top 5 候选。

还没完成的是产品化：

- 候选结果还没落正式数据库。
- 还没有 item 级 Review 页面。
- 用户选择候选后的 Amazon listing 详情抓取还没接入。
- 候选排序目前主要依赖 StyleSnap 返回顺序和卖家精灵字段，后续应加规则评分。
- 临时 smoke 文件在 `data/tmp`，可能不受 git 管理。

