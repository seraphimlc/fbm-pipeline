#!/usr/bin/env python3
"""大健云仓商品信息提取"""

import subprocess
import json
import re
import time
import sys
import os

# JS提取脚本路径
JS_FILE = '/tmp/gigab2b_extract.js'

# 创建JS提取脚本（v2 - 支持颜色/材质/尺寸）
JS_SCRIPT = '''(function() {
    // 从tabpanel中提取，数据更干净
    var tabpanel = document.querySelector('[role="tabpanel"]') || document.querySelector('.el-tab-pane');
    var sourceText = tabpanel ? tabpanel.innerText : document.body.innerText;
    var lines = sourceText.split('\\n').map(l => l.trim()).filter(l => l.length > 0);
    var result = {};

    // ===== Item Code =====
    for (var i = 0; i < lines.length; i++) {
        if (lines[i] === 'Item Code:' || lines[i].match(/^Item Code\\s*:/)) {
            result.itemCode = lines[i + 1] || null;
            break;
        }
    }
    // Fallback: 全文匹配
    if (!result.itemCode) {
        var codeMatch = sourceText.match(/W[0-9]{4}[A-Z][0-9]{5,6}/);
        result.itemCode = codeMatch ? codeMatch[0] : null;
    }

    // ===== 标题 =====
    for (var i = 0; i < lines.length; i++) {
        if (lines[i] === 'Product Name:' || lines[i].match(/^Product Name\\s*:/)) {
            result.title = lines[i + 1] || null;
            break;
        }
    }

    // ===== 解析键值对（Key一行，Value下一行）=====
    var productInfo = {};
    var productDimensions = {};
    var currentSection = 'info';

    for (var i = 0; i < lines.length; i++) {
        var line = lines[i];

        // 区域切换
        if (line === 'Product Information') { currentSection = 'info'; continue; }
        if (line === 'Product Dimensions') { currentSection = 'dimensions'; continue; }
        if (line === 'Package Size') { currentSection = 'package'; continue; }
        if (line === 'Specification') continue;

        // Package Size区域单独处理
        if (currentSection === 'package') continue;

        // 键值对格式：Key: 在一行，Value在下一行
        if (line.match(/:$/)) {
            var key = line.replace(/:$/, '').trim();
            var value = lines[i + 1] ? lines[i + 1].trim() : '';
            // 确保value不是下一个key
            if (value && !value.match(/:$/) && !value.match(/^(Product|Package|Specification)/)) {
                if (currentSection === 'info') {
                    productInfo[key] = value;
                } else if (currentSection === 'dimensions') {
                    productDimensions[key] = value;
                }
            }
        }
        // 也处理 "Key : Value" 同行格式
        var kvMatch = line.match(/^(.+?)\\s*:\\s*(.+)$/);
        if (kvMatch && !line.match(/:$/)) {
            var key = kvMatch[1].trim();
            var value = kvMatch[2].trim();
            if (value && !value.match(/^(Product|Package|Specification)/)) {
                if (currentSection === 'info') {
                    productInfo[key] = value;
                } else if (currentSection === 'dimensions') {
                    productDimensions[key] = value;
                }
            }
        }
    }

    result.productInfo = productInfo;
    result.productDimensions = productDimensions;

    // ===== 提取关键字段（同时支持中英文标签）=====
    result.color = productInfo['Main Color'] || productInfo['颜色'] || null;
    result.material = productInfo['Main Material'] || productInfo['材质'] || null;
    result.filler = productInfo['Filler'] || productInfo['填充物'] || null;
    result.productType = productInfo['Product Type'] || productInfo['产品类型'] || null;
    result.origin = productInfo['Place of Origin'] || productInfo['产地'] || null;
    result.useCase = productInfo['Use Case'] || productInfo['场合'] || null;

    // 产品尺寸（同时支持中英文标签）
    result.dimensions = {
        length: productDimensions['Assembled Length (in.)'] || productDimensions['组装长度 (英寸)'] || productInfo['组装长度 (英寸)'] || null,
        width: productDimensions['Assembled Width (in.)'] || productDimensions['组装宽度 (英寸)'] || productInfo['组装宽度 (英寸)'] || null,
        height: productDimensions['Assembled Height (in.)'] || productDimensions['组装高度 (英寸)'] || productInfo['组装高度 (英寸)'] || null
    };
    result.weight = productDimensions['Product Weight (lbs.)'] || productDimensions['产品重量 (磅)'] || productInfo['产品重量 (磅)'] || productInfo['重量 (磅)'] || null;

    // ===== 货值/价格（需要登录态，从全页面提取）=====
    var fullText = document.body.innerText;
    var valueMatch = fullText.match(/货值总计[^$]*\\$?([0-9,.]+)/);
    result.valueTotal = valueMatch ? valueMatch[1] : null;
    var estMatch = fullText.match(/预估总额[^$]*\\$?([0-9,.]+)/);
    result.estimatedTotal = estMatch ? estMatch[1] : null;

    // ===== Variants（变体信息）=====
    var variants = [];
    var variantLinks = document.querySelectorAll('a[href*="product_id"]');
    variantLinks.forEach(function(link) {
        var text = link.innerText.trim();
        var href = link.getAttribute('href');
        var idMatch = href.match(/product_id=(\\d+)/);
        if (text && idMatch && !text.includes('Login')) {
            variants.push({ text: text, productId: idMatch[1] });
        }
    });
    result.variants = variants;

    // ===== Package Size =====
    var packages = [];
    var currentSubItem = null;
    for (var i = 0; i < lines.length; i++) {
        var subMatch = lines[i].match(/Sub-item \\d+:\\s*(W[0-9A-Z]+)/i);
        if (subMatch) {
            currentSubItem = { code: subMatch[1], qty: '', dimensions: '', weight: '' };
            continue;
        }
        if (currentSubItem) {
            var qtyMatch = lines[i].match(/Package Quantity:\\s*(\\d+)/);
            if (qtyMatch) { currentSubItem.qty = qtyMatch[1]; continue; }
            var dimMatch = lines[i].match(/[\\d.]+\\s*\\*\\s*[\\d.]+\\s*\\*\\s*[\\d.]+\\s*(in\\.|cm)/);
            if (dimMatch) {
                currentSubItem.dimensions = lines[i].trim();
                var weightMatch = lines[i].match(/([\\d.]+)\\s*lbs\\.?/);
                if (weightMatch) currentSubItem.weight = weightMatch[1] + ' lbs';
                packages.push(currentSubItem);
                currentSubItem = null;
            }
        }
    }
    result.packages = packages;

    // ===== 图片数量 =====
    var carousel = document.querySelector('.el-carousel');
    if (carousel) {
        result.imageCount = carousel.querySelectorAll('.el-carousel__item').length;
    }

    return JSON.stringify(result);
})()
'''

def ensure_js_file():
    """确保JS文件存在"""
    if not os.path.exists(JS_FILE):
        with open(JS_FILE, 'w') as f:
            f.write(JS_SCRIPT)

def extract_id(url):
    """从URL提取商品ID"""
    match = re.search(r'product_id=(\d+)', url)
    if match:
        return match.group(1)

    match = re.search(r'product-detail/(\d+)', url)
    if match:
        return match.group(1)

    return None

def open_page(product_id):
    """打开大健云仓商品页面"""
    url = f"https://www.gigab2b.com/index.php?route=product/product&product_id={product_id}"
    osascript = f'''tell application "Google Chrome"
    tell active tab of front window
        set URL to "{url}"
    end tell
end tell'''
    subprocess.run(['osascript', '-e', osascript], capture_output=True)
    time.sleep(3)

def get_info(product_id):
    """获取商品信息"""
    ensure_js_file()

    # 打开页面
    open_page(product_id)

    # 执行JS提取
    osascript = '''tell application "Google Chrome"
    tell active tab of front window
        set jsFile to do shell script "cat /tmp/gigab2b_extract.js"
        set result to execute javascript jsFile
        return result
    end tell
end tell'''

    result = subprocess.run(['osascript', '-e', osascript], capture_output=True, text=True)

    try:
        return json.loads(result.stdout.strip())
    except Exception as e:
        print(f"❌ JS解析失败: {e}")
        return None

def cm_to_inch(text):
    """cm转英寸"""
    if not text:
        return text

    def replace_cm(match):
        cm_value = float(match.group(1))
        inch_value = cm_value / 2.54
        return f"{inch_value:.2f}英寸"

    return re.sub(r'([0-9.]+)\s*cm', replace_cm, text)

def format_attributes(info):
    """格式化商品属性（包含颜色、材质、尺寸等）"""
    if not info:
        return ""

    parts = []

    # 颜色
    color = info.get('color')
    if color:
        parts.append(f"颜色: {color}")

    # 材质
    material = info.get('material')
    if material:
        parts.append(f"材质: {material}")

    # 填充物
    filler = info.get('filler')
    if filler:
        parts.append(f"填充物: {filler}")

    # 产品类型
    product_type = info.get('productType')
    if product_type:
        parts.append(f"产品类型: {product_type}")

    # 产品尺寸
    dims = info.get('dimensions', {})
    if dims and any(dims.values()):
        dim_parts = []
        if dims.get('length'):
            dim_parts.append(f"长{dims['length']}in")
        if dims.get('width'):
            dim_parts.append(f"宽{dims['width']}in")
        if dims.get('height'):
            dim_parts.append(f"高{dims['height']}in")
        if dim_parts:
            parts.append(f"产品尺寸: {' × '.join(dim_parts)}")

    # 产品重量
    weight = info.get('weight')
    if weight:
        parts.append(f"产品重量: {weight} lbs")

    # 包装尺寸
    packages = info.get('packages', [])
    if packages:
        pkg_texts = []
        for pkg in packages:
            pkg_texts.append(f"  {pkg['code']}: {pkg['dimensions']}")
        parts.append(f"包装尺寸:\n" + "\n".join(pkg_texts))

    return '\n'.join(parts)

def format_features(features):
    """格式化五点描述"""
    if not features:
        return ""

    return '\n'.join([f"{i+1}. {f}" for i, f in enumerate(features)])

def main():
    if len(sys.argv) < 2:
        print("用法:")
        print("  extract_info.py id <url>         — 从URL提取商品ID")
        print("  extract_info.py info <product_id> — 提取商品详情")
        sys.exit(1)

    command = sys.argv[1]

    if command == 'id':
        if len(sys.argv) < 3:
            print("❌ 缺少URL参数")
            sys.exit(1)
        url = sys.argv[2]
        product_id = extract_id(url)
        print(product_id if product_id else "❌ 无法提取商品ID")

    elif command == 'info':
        if len(sys.argv) < 3:
            print("❌ 缺少product_id参数")
            sys.exit(1)
        product_id = sys.argv[2]
        info = get_info(product_id)

        if info:
            print(json.dumps(info, indent=2, ensure_ascii=False))
        else:
            print("❌ 无法获取商品信息")

    else:
        print(f"❌ 未知命令: {command}")
        sys.exit(1)

if __name__ == '__main__':
    main()