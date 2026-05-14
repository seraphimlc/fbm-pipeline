---
name: gigab2b-product-collector
description: "大健云仓商品信息采集：提取商品详情（颜色/材质/尺寸）、下载素材包。支持单个和批量处理。"
compatibility: darwin
metadata:
  version: 1.2.0
  requires:
    bins:
      - python3
      - osascript
    python_packages:
      - openpyxl
---

# 大健云仓商品信息采集

**0多模态 · AppleScript+JS · 自动下载素材包**

## 何时使用

- 用户说"获取大建商品信息"、"采集大健云仓数据"、"下载大建素材包"
- 有大健云仓商品URL列表，需要批量提取信息
- 需要下载商品素材包（图片、视频、文档）

## 前置条件

1. **Chrome浏览器已打开**（用于页面操作）
2. **大健云仓已登录**（部分信息需要登录态）
3. **macOS 自动化权限**（AppleScript控制Chrome）

## 工作流程

### Step 1: 提取商品ID

从大健云仓URL中提取商品ID：

```
URL格式: https://www.gigab2b.com/product-detail/{product_id}
        或 https://www.gigab2b.com/index.php?route=product/product&product_id={product_id}

提取: product_id
```

```bash
uv run python3 scripts/extract_info.py id "https://www.gigab2b.com/product-detail/1119060"
# 输出: 1119060
```

### Step 2: 提取商品信息

打开页面并提取商品详情：

```bash
uv run python3 scripts/extract_info.py info 1119060
```

**返回字段**：
- `itemCode` — Item Code (如 W3326S00030)
- `color` — 主颜色 (如 Brown)
- `material` — 主材质 (如 Flannelette)
- `filler` — 填充物 (如 Foam)
- `productType` — 产品类型 (如 Combo Item)
- `dimensions` — 产品尺寸 {length, width, height} (英寸)
- `weight` — 产品重量 (磅)
- `packages` — 包装尺寸列表 [{code, dimensions, weight}]
- `valueTotal` — 货值总计 (美元)
- `estimatedTotal` — 预估总额含运费 (美元)
- `title` — 商品标题
- `features` — 五点描述 (数组)
- `variants` — 变体列表 [{text, productId}]
- `imageCount` — 页面轮播图数量

### Step 3: 下载素材包

下载并解压商品素材包：

```bash
uv run python3 scripts/download_materials.py 1119060 --output-dir "/path/to/output"
```

**素材包内容**：
- `Main Images/` — 主图
- `video/` — 视频
- `file/` — 文档（PDF、DOCX等）

**返回**：
- 实际图片数量
- 素材包解压路径

### Step 4: 批量处理

从Excel表格批量处理：

```bash
uv run python3 scripts/batch_process.py "/path/to/商品表格.xlsx" \
  --url-column 6 \
  --output-dir "/path/to/亚马逊商品/05-03"
```

**自动完成**：
1. 从URL提取商品ID
2. 创建商品文件夹
3. 提取商品信息
4. 下载素材包
5. 写回Excel（Item Code、成本、货值、标题、五点、属性、图片数量）

## 一键流程（Agent操作指南）

当用户要求批量处理大健云仓商品时：

```python
# 1. 读取Excel中的URL列表
# 2. 逐个处理：
for url in urls:
    product_id = extract_id(url)
    info = get_info(product_id)
    image_count = download_materials(product_id)
    write_to_excel(row, info, image_count)
# 3. 汇报进度
```

## 数据格式

### 商品属性格式

```
颜色: Brown
材质: Flannelette
填充物: Foam
产品类型: Combo Item
产品尺寸: 长111.02in × 宽37.01in × 高23.62in
产品重量: 99.33 lbs
包装尺寸:
  W3326P350747: 11.81 * 11.81 * 39.37 in. 36.19 lbs.
  W3326P350745: 13.39 * 13.39 * 39.37 in. 41.25 lbs.
```

**注意**：所有尺寸直接提取英寸值，无需转换

### 五点描述格式

```
1. 第一点描述
2. 第二点描述
3. 第三点描述
4. 第四点描述
5. 第五点描述
```

## 脚本说明

### scripts/extract_info.py

商品信息提取工具：

- `id <url>` — 从URL提取商品ID
- `info <product_id>` — 提取商品详情
- `batch <excel_path>` — 批量提取并写回Excel

### scripts/download_materials.py

素材包下载工具：

- `<product_id>` — 下载单个商品素材包
- `--output-dir` — 指定输出目录
- `--no-extract` — 仅下载不解压

### scripts/batch_process.py

批量处理入口：

- 自动读取Excel中的URL
- 逐个提取信息、下载素材
- 写回Excel并汇报进度

## AppleScript + JS 参考

### 打开页面

```applescript
tell application "Google Chrome"
    tell active tab of front window
        set URL to "https://www.gigab2b.com/product-detail/1119060"
    end tell
end tell
```

### 提取信息（JS）

```javascript
(function() {
    var allText = document.body.innerText;
    var lines = allText.split('\n').map(l => l.trim()).filter(l => l.length > 0);
    var result = {};

    // Item Code
    var codeMatch = allText.match(/W[0-9]{4}S[0-9]{5}/);
    result.itemCode = codeMatch ? codeMatch[0] : null;

    // 货值总计
    var valueMatch = allText.match(/货值总计[^$]*\$?([0-9,.]+)/);
    result.valueTotal = valueMatch ? valueMatch[1] : null;

    // 预估总额
    var estMatch = allText.match(/预估总额[^$]*\$?([0-9,.]+)/);
    result.estimatedTotal = estMatch ? estMatch[1] : null;

    // 标题、五点、属性...

    return JSON.stringify(result);
})()
```

### 点击下载按钮

```javascript
(function() {
    var btns = document.querySelectorAll('button');
    for (var i = 0; i < btns.length; i++) {
        if (btns[i].innerText.includes('下载素材包')) {
            btns[i].click();
            return true;
        }
    }
    return false;
})()
```

## 异常处理

| 情况 | 处理 |
|------|------|
| 页面加载超时 | 等待5秒，刷新重试1次 |
| Item Code不存在 | 部分商品无S编号，返回null |
| 素材包下载失败 | 跳过下载，图片数量记为0 |
| cm转英寸失败 | 保留原始cm值 |
| Chrome未运行 | 启动Chrome，等待5秒 |

## 与其他Skill的关系

- **amazon-fbm-pricing**: 使用本Skill提取的成本、货值计算售价
- **sellersprite-data-collector**: 使用本Skill提取的商品ID组织文件夹
- **browser-pilot**: 本Skill可使用browser-pilot的配置驱动模式

## 版本历史

- **v1.2.0** (2026-05-04): 修复下载超时（先记录existing_zips再点击）、修复Item Code正则（支持P格式）、每次点击选项下载多个zip、简化下载流程
- **v1.1.0** (2026-05-04): 新增颜色/材质/尺寸提取，修复Item Code缺失问题
- **v1.0.0** (2026-05-04): 初始版本，基于实际批量处理经验固化
