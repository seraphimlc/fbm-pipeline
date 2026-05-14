// GigaB2B 商品信息提取脚本 (v2)
// 匹配 Vue + Element UI 页面结构
(function() {
    var result = {};
    var fullText = document.body.innerText;
    var lines = fullText.split('\n').map(function(l) { return l.trim(); }).filter(function(l) { return l.length > 0; });

    // ===== Item Code =====
    var codeMatch = fullText.match(/Item Code:\s*\n?\s*(W[0-9A-Z]+)/i);
    result.itemCode = codeMatch ? codeMatch[1] : null;
    if (!result.itemCode) {
        var codeMatch2 = fullText.match(/(W[0-9]{4}[A-Z][0-9]{5,6})/);
        result.itemCode = codeMatch2 ? codeMatch2[1] : null;
    }

    // ===== 标题 =====
    // 方式1：面包屑区域标题
    var breadcrumb = document.querySelector('.el-breadcrumb');
    if (breadcrumb) {
        var titleEl = breadcrumb.parentElement.querySelector('div[class*="title"], h1, h2');
        if (titleEl) result.title = titleEl.innerText.trim();
    }
    // 方式2：document title（去掉后缀）
    if (!result.title) {
        result.title = document.title.replace(/\s*-\s*GigaB2B.*$/, '').trim() || document.title;
    }

    // ===== 解析产品规格区 =====
    var productInfo = {};
    var productDimensions = {};
    var currentSection = 'info';

    for (var i = 0; i < lines.length; i++) {
        var line = lines[i];
        if (/^(产品信息|基础信息)$/.test(line)) { currentSection = 'info'; continue; }
        if (/^(产品尺寸|Product Dimensions)$/.test(line)) { currentSection = 'dimensions'; continue; }
        if (/^(包装尺寸|Package Size)$/.test(line)) { currentSection = 'package'; continue; }
        if (/^(产品特点|Features?)$/.test(line)) { currentSection = 'features'; continue; }

        // 匹配 "Key:" 独占一行，value在下一行
        if (/[：:]$/.test(line)) {
            var key = line.replace(/[：:]$/, '').trim();
            var value = lines[i + 1] ? lines[i + 1].trim() : '';
            if (value && !/[：:]$/.test(value) && !/^(产品|Product|Package|基础|规格|特点|Related)/.test(value)) {
                if (currentSection === 'info') productInfo[key] = value;
                else if (currentSection === 'dimensions') productDimensions[key] = value;
            }
            continue;
        }
        // 匹配 "Key: Value" 同一行
        var kvMatch = line.match(/^(.+?)[：:]\s*(.+)$/);
        if (kvMatch && !/[：:]$/.test(line)) {
            var key = kvMatch[1].trim();
            var value = kvMatch[2].trim();
            if (value && !/^(产品|Product|Package|基础|规格|特点|Related)/.test(value) && value.length < 200) {
                if (currentSection === 'info') productInfo[key] = value;
                else if (currentSection === 'dimensions') productDimensions[key] = value;
            }
        }
    }

    result.productInfo = productInfo;
    result.productDimensions = productDimensions;

    // ===== 关键字段 =====
    result.color = productInfo['Main Color'] || productInfo['颜色'] || null;
    result.material = productInfo['Main Material'] || productInfo['材质'] || null;
    result.filler = productInfo['Filler'] || productInfo['填充物'] || null;
    result.productType = productInfo['Product Type'] || productInfo['产品类型'] || null;
    result.origin = productInfo['Place of Origin'] || productInfo['产地'] || null;

    result.dimensionLength = productDimensions['Assembled Length (in.)'] || productDimensions['组装长度 (英寸)'] || productInfo['组装长度 (英寸)'] || null;
    result.dimensionWidth = productDimensions['Assembled Width (in.)'] || productDimensions['组装宽度 (英寸)'] || productInfo['组装宽度 (英寸)'] || null;
    result.dimensionHeight = productDimensions['Assembled Height (in.)'] || productDimensions['组装高度 (英寸)'] || productInfo['组装高度 (英寸)'] || null;
    result.weight = productDimensions['Product Weight (lbs.)'] || productDimensions['产品重量 (磅)'] || productInfo['产品重量 (磅)'] || null;

    // ===== 价格 =====
    var valueMatch = fullText.match(/货值总计[^$]*\$?([0-9,.]+)/);
    result.valueTotal = valueMatch ? valueMatch[1] : null;
    var priceMatch = fullText.match(/\$([0-9,.]+)\s*-\s*\$([0-9,.]+)/);
    if (priceMatch) {
        result.priceMin = priceMatch[1];
        result.priceMax = priceMatch[2];
    }
    // 也尝试提取单价
    var unitMatch = fullText.match(/\$\s*([0-9,.]+)\s*\/\s*(?:件|Piece|pcs)/i);
    result.unitPrice = unitMatch ? unitMatch[1] : null;

    // ===== 预估总额（含物流费）=====
    // 匹配 "预估总额" 后面跟着 "$xxx.xx /件"
    var estimatedMatch = fullText.match(/预估总额[^$]*\$([0-9,.]+)\s*\/\s*件/);
    result.estimatedTotal = estimatedMatch ? estimatedMatch[1] : null;

    // ===== 物流费 =====
    // 一件代发: "预估物流费: $xx.xx /件"
    var shippingMatch = fullText.match(/预估物流费:\s*\$([0-9,.]+)\s*\/件/);
    result.shippingCost = shippingMatch ? shippingMatch[1] : null;
    // 云送仓范围: "$xx.xx~$xx.xx /件"
    var shippingRangeMatch = fullText.match(/预估物流费:\s*\$([0-9,.]+)~\$([0-9,.]+)\s*\/件/);
    result.shippingCostMin = shippingRangeMatch ? shippingRangeMatch[1] : null;
    result.shippingCostMax = shippingRangeMatch ? shippingRangeMatch[2] : null;

    // ===== 变体 =====
    var variants = [];
    var variantSection = false;
    for (var i = 0; i < lines.length; i++) {
        if (/^关联产品$/.test(lines[i])) { variantSection = true; continue; }
        if (variantSection) {
            if (lines[i].includes('+')) {
                variants.push({text: lines[i]});
            } else if (!/^\d+\s*件$/.test(lines[i])) {
                variantSection = false;
            }
        }
    }
    result.variants = variants;

    // ===== 包装信息 =====
    var packages = [];
    var currentSubItem = null;
    for (var i = 0; i < lines.length; i++) {
        var subMatch = lines[i].match(/(?:子产品|Sub-item)\s*\d+[：:]\s*(W[0-9A-Z]+)/i);
        if (subMatch) {
            currentSubItem = {code: subMatch[1], qty: '', dimensions: '', weight: ''};
            continue;
        }
        if (currentSubItem) {
            var qtyMatch = lines[i].match(/(?:包裹数量|Package Quantity)[：:]\s*(\d+)/);
            if (qtyMatch) { currentSubItem.qty = qtyMatch[1]; continue; }
            var dimMatch = lines[i].match(/([\d.]+)\s*\*\s*([\d.]+)\s*\*\s*([\d.]+)\s*(英寸|in\.|cm)/);
            if (dimMatch) {
                currentSubItem.dimensions = lines[i].trim();
                var weightMatch = lines[i].match(/([\d.]+)\s*(?:磅|lbs\.?)/);
                if (weightMatch) currentSubItem.weight = weightMatch[1] + ' lbs';
                packages.push(currentSubItem);
                currentSubItem = null;
            }
        }
    }
    result.packages = packages;

    // ===== 图片 =====
    var imageUrls = [];
    // 方式1：el-image__inner（产品大图）
    document.querySelectorAll('img.el-image__inner').forEach(function(img) {
        var src = img.getAttribute('src') || '';
        if (src.includes('b2bfiles') && !src.includes('video_trans') && src.length > 30) {
            if (imageUrls.indexOf(src) === -1) imageUrls.push(src);
        }
    });
    // 方式2：所有 b2bfiles 图片
    if (imageUrls.length === 0) {
        document.querySelectorAll('img[src*="b2bfiles"]').forEach(function(img) {
            var src = img.getAttribute('src') || '';
            if (src.length > 30 && !src.includes('icon') && !src.includes('logo') && !src.includes('bannerDesign') && !src.includes('video_trans')) {
                if (imageUrls.indexOf(src) === -1) imageUrls.push(src);
            }
        });
    }
    result.imageUrls = imageUrls;
    result.imageCount = imageUrls.length;

    // ===== 卖家 =====
    var sellerEl = document.querySelector('.store-info .seller-name, .store-info a');
    result.seller = sellerEl ? sellerEl.innerText.trim() : null;
    if (!result.seller) {
        var gigaMatch = fullText.match(/([a-zA-Z][a-zA-Z0-9_-]{2,})\s*\n?\s*GIGA Index/);
        result.seller = gigaMatch ? gigaMatch[1] : null;
    }

    // ===== 产品特点 =====
    var features = [];
    var inFeatures = false;
    for (var i = 0; i < lines.length; i++) {
        if (/^(产品特点|Features?)$/.test(lines[i])) { inFeatures = true; continue; }
        if (inFeatures) {
            if (/^(产品|Product|Package|基础|规格|相关|Related)/.test(lines[i])) break;
            if (lines[i].length > 10) features.push(lines[i]);
            if (features.length >= 10) break;
        }
    }
    result.features = features;

    // ===== 额外字段 =====
    result.scene = productInfo['适用场景'] || productInfo['Applicable Scene'] || null;
    result.seats = productInfo['座位个数'] || productInfo['Number of Seats'] || null;
    result.seatFeel = productInfo['坐感'] || productInfo['Seat Feel'] || null;
    result.shape = productInfo['造型'] || productInfo['Shape'] || null;

    // ===== 大建五点描述（从DOM中提取 characteristic 列表）=====
    var characteristic = '';
    try {
        // 产品特点区域：一组连续的长英文LI，通常3-5条
        // 通过找包含英文冒号的长LI来定位
        var allLi = document.querySelectorAll('li');
        var charItems = [];
        for (var ci = 0; ci < allLi.length; ci++) {
            var liText = allLi[ci].innerText.trim();
            // 长英文描述（带冒号的Title:Description格式，或纯长文本描述）
            if (liText.length > 40 && /[a-zA-Z]/.test(liText) && !/^(Step|非|Return|Step\d)/.test(liText)) {
                charItems.push(liText);
            }
        }
        if (charItems.length >= 3) {
            characteristic = charItems.join('\n');
        }
    } catch(e) {}
    result.characteristic = characteristic || null;

    // ===== 商品描述（图文描述区域）=====
    // 描述内容在 .pre-text 区域，通常是图片
    var descImages = [];
    var preText = document.querySelector('.pre-text');
    if (preText) {
        preText.querySelectorAll('img').forEach(function(img) {
            var src = img.getAttribute('data-src') || img.getAttribute('src') || '';
            if (src.includes('b2bfiles') && !src.includes('product_base')) {
                descImages.push(src);
            }
        });
    }
    result.descriptionImages = descImages;
    
    // 描述文字（如果有）
    var descText = '';
    if (preText) {
        descText = preText.innerText.trim();
    }
    result.descriptionText = descText || null;

    return JSON.stringify(result);
})()
