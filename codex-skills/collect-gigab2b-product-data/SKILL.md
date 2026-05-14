---
name: collect-gigab2b-product-data
description: Collect product specifications from logged-in GIGAB2B/大建云仓 product pages listed in spreadsheet URLs, then append source fields and Amazon-ready import columns. Use when Codex needs to enrich `.xlsx` product sheets from 大建云仓 URLs, especially sofa/SOFA Amazon import preparation, packaging dimensions, weights, origin, material, stock, logistics cost, and page-derived listing attributes while ignoring images.
---

# Collect GIGAB2B Product Data

## Overview

Use this skill to enrich a product spreadsheet from 大建云仓/GIGAB2B product URLs using the user's logged-in local Chrome session. The bundled script reads an `.xlsx`, opens each URL in Chrome, extracts page text, parses product specs, appends columns, and saves the workbook with a timestamped backup.

Default behavior matches the sofa workflow:

- Keep the original spreadsheet columns unchanged.
- Append source fields prefixed with `大建`.
- Append Amazon-ready fields prefixed with `亚马逊`.
- Fill Amazon fields only for rows whose title/page title matches sofa keywords.
- Ignore image URL collection.
- Use `Brand Name = Vindhvisk`, `Product Type = SOFA`, `Product Id Type = GTIN Exempt`, `Dangerous Goods Regulations = Not Applicable` unless the user overrides.

## Workflow

1. Confirm Chrome is already logged in to GIGAB2B. Use the local browser, not unauthenticated HTTP requests, because GIGAB2B pages may require login/captcha. Public/English pages can still expose specs, but stock, logistics, and pricing often require login.
2. Inspect the spreadsheet headers and identify:
   - product URL column, usually `大建云仓URL`
   - product id column, usually `大建商品id`
   - SKU column, usually `大建云仓Item Code`
   - title column, usually `新商品标题`
   - bullet column, usually `新五点描述`
3. Run `scripts/collect_gigab2b_to_xlsx.py` with the workbook path and relevant options.
4. Validate the output:
   - Count rows with `采集状态 = 已采集`.
   - Check the first enriched row manually.
   - Confirm `大建页面标题` and `大建Seller` match the intended product, not a later or previous browser page.
   - Check that non-target products have blank Amazon fields and a clear `待确认事项`.
   - Check target products for missing key Amazon fields.
5. Report the workbook path, backup path, target-product count, and remaining issues.

## Script

Use the bundled script:

```bash
python3 /path/to/collect-gigab2b-product-data/scripts/collect_gigab2b_to_xlsx.py \
  --workbook "/path/to/商品表格.xlsx" \
  --brand "Vindhvisk" \
  --product-type "SOFA" \
  --item-type-keyword "sofas"
```

Useful options:

- `--sheet Sheet1`: choose a sheet; defaults to the active sheet.
- `--url-column 大建云仓URL`: URL header.
- `--id-column 大建商品id`: product id header for cache filenames.
- `--sku-column 大建云仓Item Code`: SKU source header.
- `--title-column 新商品标题`: local title source.
- `--bullet-column 新五点描述`: five-point source to split into Amazon bullets.
- `--target-keywords sofa,couch,sectional,loveseat,chaise`: classify target rows by title/page title.
- `--fill-all-targets`: fill Amazon fields for every successfully collected row.
- `--cache-dir /path/to/cache`: save/read page text cache.
- `--use-cache`: reuse cached page text if present. Default refetches pages to avoid stale Chrome/page mismatches.
- `--offline-cache-only`: use cache only, useful for testing without moving Chrome. Only use with known-good cache.
- `--max-rows N`: test a small batch first.

Use the bundled Python runtime when available, because it includes `openpyxl`:

```bash
/Users/jiyuhang/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 \
  /Users/jiyuhang/.codex/skills/collect-gigab2b-product-data/scripts/collect_gigab2b_to_xlsx.py \
  --workbook "/path/to/商品表格.xlsx"
```

## Field Rules

The script parses these common GIGAB2B Chinese and English labels:

- `产品名称` / `Product Name`, `产品类型` / `Product Type`, `Item Code`
- `产地` / `Place of Origin`, `颜色` / `Main Color`, `材质` / `Main Material`, `填充物` / `Filler`, `适用场景` / `Use Case`, `座位个数` / `Seats`, `坐感` / `Seat Plushness`, `造型` / `Sectional Shape`
- `组装长度 (英寸)` / `Assembled Length (in.)`, `组装宽度 (英寸)` / `Assembled Width (in.)`, `组装高度 (英寸)` / `Assembled Height (in.)`, `产品重量 (磅)` / `Product Weight (lbs.)`
- combo package rows like `子产品 1`, `包裹数量`, `11.81 * 11.81 * 39.37 英寸 36.19 磅`
- English combo package rows like `Sub-item 1`, `Package Quantity`, `11.81 * 11.81 * 39.37 in. 36.19 lbs.`
- single-box package rows like `长度 (英寸)`, `宽度 (英寸)`, `高度 (英寸)`, `重量 (磅)`
- `可售库存`, `一件代发`, `云送仓`, shipping lead times, seller name

For Amazon-ready fields:

- Use spreadsheet SKU first; fall back to page `Item Code`.
- Use spreadsheet title first; fall back to page product title.
- Split `新五点描述` into five bullet columns when present.
- Use page feature bullets for product description when available.
- Use the heaviest package for Amazon package dimensions/weight, and keep full package detail in `大建包裹明细`.
- If a target product page says it is delisted and no stock is shown, set quantity to `0` and note it in `待确认事项`.
- Do not infer UPC/EAN/GTIN from competitor ASINs; use `GTIN Exempt` unless the user supplies barcodes.

## Validation Snippets

After running, check the workbook with a short script:

```bash
python3 - <<'PY'
from openpyxl import load_workbook
p = "/path/to/商品表格.xlsx"
wb = load_workbook(p, data_only=True, read_only=True)
ws = wb.active
h = [ws.cell(1,c).value for c in range(1, ws.max_column+1)]
def val(r, name): return ws.cell(r, h.index(name)+1).value
target = [r for r in range(2, ws.max_row+1) if val(r, "亚马逊Product Type")]
print("target rows:", len(target), target[:20])
key = ["亚马逊SKU","亚马逊Brand Name","亚马逊Product Type","亚马逊Item Name",
       "亚马逊Product Id Type","亚马逊Item Type Keyword","亚马逊Country of Origin",
       "亚马逊Dangerous Goods Regulations","亚马逊Quantity",
       "亚马逊Package Length","亚马逊Package Width","亚马逊Package Height","亚马逊Package Weight"]
missing = [(r,k) for r in target for k in key if val(r,k) in (None, "")]
print("missing:", missing[:50], "count=", len(missing))
PY
```
