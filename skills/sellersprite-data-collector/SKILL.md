---
name: sellersprite-data-collector
description: "卖家精灵关键词反查：直接API导出，0浏览器0多模态。支持单ASIN和批量导出。"
compatibility: darwin
metadata:
  version: 2.0.0
  requires:
    bins:
      - python3
    python_packages:
      - openpyxl
---

# 卖家精灵数据收集 v2 — 直接API路线

**0浏览器 · 0多模态 · 0截屏** — 直接调用卖家精灵后端API导出关键词反查Excel。

## 何时使用

- 用户说"关键词反查"、"卖家精灵查词"、"查竞品关键词"、"批量查词"
- 需要从卖家精灵获取ASIN的关键词数据
- 有 Amazon 商品 Excel 表格，需要填充"竞品关键词前20"列

## 前置条件

1. **卖家精灵账号已登录**（Cookie中有 `Sprite-X-Token`）
2. **macOS 自动化权限**（仅自动获取Cookie时需要，手动传Cookie则不需要）
3. **Python 依赖**：`openpyxl`（`uv pip install openpyxl`）

## API 逆向信息

从卖家精灵JS源码 `chunk-01ccfd8e` 逆向出的导出API：

```
同步导出: POST /v3/api/relation/ta/export-keyword-new?market={market}&exportVariations={bool}&exportGkImages={bool}
请求体:   {"asin": "B0GMWKDNBC"}
响应:     二进制Excel文件 (blob)
认证:     Cookie中的 Sprite-X-Token (JWT, 约24h有效)
```

**注意**：前端拦截器会将 `export-keyword` 改写为 `export-keyword-new`，所以API调用时直接用 `-new` 后缀。

### 市场ID

| ID | 市场 |
|----|------|
| 1 | 美国 (COM) |
| 2 | 英国 |
| 3 | 德国 |
| 4 | 法国 |
| 5 | 意大利 |
| 6 | 西班牙 |
| 7 | 日本 |

## 工作流程

### Step 1: 获取Cookie（自动或手动）

**自动获取**（推荐）：
```bash
uv run python3 scripts/api_export.py token
```
自动从Chrome读取Cookie，确认 `Sprite-X-Token` 存在即可。

**手动获取**：
如果自动获取失败，在Chrome中打开卖家精灵 → F12 → Application → Cookies → 复制 `Sprite-X-Token` 的值。

### Step 2: 导出关键词

**单ASIN导出**：
```bash
uv run python3 scripts/api_export.py export B0GMWKDNBC
```

**批量导出**：
```bash
uv run python3 scripts/api_export.py export-batch B0GMWKDNBC B0ABCDEF12 B098765432
```

**指定输出目录**：
```bash
uv run python3 scripts/api_export.py export B0GMWKDNBC --output-dir ~/Downloads
```

**导出变体数据**：
```bash
uv run python3 scripts/api_export.py export B0GMWKDNBC --variations
```

### Step 3: 提取关键词

从导出的Excel中提取关键词列表：
```bash
uv run python3 scripts/api_export.py extract "/path/to/ReverseASIN-US-B0GMWKDNBC-Keywords.xlsx" --limit 20
```

### Step 4: 写回商品表格

使用 excel_handler.py 将关键词写回商品Excel：
```bash
# 先检查待处理的ASIN
uv run python3 scripts/excel_handler.py pending "/path/to/商品表格.xlsx"

# 批量写回
uv run python3 scripts/excel_handler.py write-downloads "/path/to/商品表格.xlsx"
```

## 一键流程（Agent操作指南）

当用户要求查关键词时，按以下步骤执行：

```
1. 获取Cookie: 从Chrome读取 document.cookie
2. 调API导出: curl POST /v3/api/relation/ta/export-keyword-new
3. 解析Excel: 提取前20个关键词
4. 写回表格: 用 excel_handler.py write-downloads
```

### curl 命令模板

```bash
curl -X POST \
  "https://www.sellersprite.com/v3/api/relation/ta/export-keyword-new?market=1&exportVariations=false&exportGkImages=false" \
  -H "Cookie: Sprite-X-Token=<TOKEN>; ecookie=<ECOOKIE>; current_guest=<GUEST>" \
  -H "Content-Type: application/json;charset=UTF-8" \
  -H "Referer: https://www.sellersprite.com/v3/keyword-reverse" \
  -d '{"asin":"<ASIN>"}' \
  -o "<OUTPUT_PATH>.xlsx"
```

## 批量处理建议

- 每个ASIN间隔 **3-5秒**，避免触发频率限制
- Token有效期约 **24小时**，过期需重新获取
- 导出文件默认保存到 `~/Documents/F/亚马逊工作目录/亚马逊商品/`
- 每5个ASIN执行一次 `write-downloads`，避免积累

## 异常处理

| 情况 | 处理 |
|------|------|
| Token过期 (401) | 重新从Chrome获取Cookie |
| 权限不足 (403) | 提醒用户需要VIP账号 |
| 频率限制 (429) | 等待30秒后重试 |
| 无数据 | 该ASIN可能无关键词数据，跳过 |
| 网络错误 | 重试1次，仍失败则跳过 |

## 脚本说明

### scripts/api_export.py ⭐ 核心脚本
直接API导出工具：
- `export` — 导出单个ASIN的关键词Excel
- `export-batch` — 批量导出多个ASIN
- `extract` — 从导出Excel提取关键词列表
- `token` — 从Chrome获取当前Cookie/Token

### scripts/excel_handler.py
Excel 读写工具（保留，用于写回商品表格）：
- `inspect` — 检查表格结构
- `pending` — 列出待处理的ASIN行
- `keywords` — 从导出文件提取关键词
- `write` — 写回关键词到指定行
- `write-downloads` — 批量扫描Downloads写回Excel

## 与 sellersprite-api Skill 的关系

- `sellersprite-api`：卖家精灵官方Open API（需要API Key，功能有限）
- `sellersprite-data-collector`（本Skill）：逆向Web API，直接导出完整Excel，数据更全
- **优先用本Skill**，API Key不可用时用 sellersprite-api

## 版本历史

- **v2.0.0** (2026-05-01): 逆向出导出API，实现0浏览器0多模态方案
- **v1.0.0** (2026-04-30): 初始版本，AppleScript+JS控制Chrome方案
