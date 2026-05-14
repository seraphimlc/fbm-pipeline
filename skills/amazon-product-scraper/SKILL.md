# Amazon Category Scraper

从亚马逊商品页抓取类目信息。AppleScript + JS 控制航哥的 Chrome，0多模态。

## 触发条件

- 查亚马逊商品类目/分类
- 需要给 ASIN 补充类目信息
- 用户提到"商品类目"、"ASIN类目"

## 前置条件

- Chrome 已打开，已开启"允许 Apple 事件中的 JavaScript"

## 使用

### 单个 ASIN
```bash
uv run python3 scripts/scrape_category.py B0GMWKDNBC
```

### 批量
```bash
uv run python3 scripts/scrape_category.py B0GMWKDNBC B0ABCDEF12 B098765432
```

### 输出格式
```json
{"asin": "B0GMWKDNBC", "categories": ["Home & Kitchen", "Furniture", "Living Room Furniture", "Sofas & Couches"], "leaf_category": "Sofas & Couches"}
```

## 批量注意

- 每个 ASIN 间隔 3-5 秒
- 每批不超过 10 个，批次间等 30 秒

## 选择器

| 字段 | 选择器 |
|------|--------|
| 面包屑 | `#wayfinding-breadcrumbs_feature_div` |
| 备选 | `.a-breadcrumb` |
