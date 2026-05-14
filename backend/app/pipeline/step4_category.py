"""
模块4：类目获取 — 通过 Chrome 访问亚马逊BSR页面获取类目信息

基于竞品ASIN，在亚马逊上查找其所在类目节点
"""

import json
import logging
import asyncio
import re

from app.database import async_session
from app.models import Product, ProductData
from app.pipeline.chrome_ctrl import chrome_navigate, chrome_execute_js
from sqlalchemy import select
from sqlalchemy.orm import selectinload

logger = logging.getLogger(__name__)

# 亚马逊商品页面类目提取 JS
CATEGORY_EXTRACT_JS = '''(function() {
    var result = {categories: [], leafCategory: null};
    
    // 方式1：面包屑导航
    var breadcrumbs = document.querySelectorAll('#wayfinding-breadcrumbs_container li a');
    if (breadcrumbs.length === 0) {
        breadcrumbs = document.querySelectorAll('[data-csa-c-type="element"] a');
    }
    
    var cats = [];
    breadcrumbs.forEach(function(a) {
        var text = a.innerText.trim();
        if (text) cats.push(text);
    });
    
    if (cats.length > 0) {
        result.categories = cats;
        result.leafCategory = cats[cats.length - 1];
        return JSON.stringify(result);
    }
    
    // 方式2：Product Information 区域
    var infoSection = document.querySelector('#productDetails_detailBullets_sections1');
    if (!infoSection) {
        infoSection = document.querySelector('#detailBullets_feature_div');
    }
    if (!infoSection) {
        infoSection = document.querySelector('#prodDetails');
    }
    
    if (infoSection) {
        var rows = infoSection.querySelectorAll('tr, li');
        rows.forEach(function(row) {
            var text = row.innerText;
            var match = text.match(/Best Sellers Rank[:\\s]*([\\s\\S]+)/i);
            if (match) {
                var rankText = match[1].trim();
                // 提取类目路径，格式: #1 in Home & Kitchen (See Top 100) > #5 in Bedding (See Top 100) > ...
                var categoryMatches = rankText.matchAll(/#\\d+\\s+in\\s+([^()\\n]+)/g);
                var tempCats = [];
                for (var m of categoryMatches) {
                    tempCats.push(m[1].trim());
                }
                if (tempCats.length > 0) {
                    result.categories = tempCats;
                    result.leafCategory = tempCats[0]; // 第一个是叶子类目
                }
            }
        });
    }
    
    return JSON.stringify(result);
})()'''


async def fetch_categories(asin: str) -> dict:
    """
    通过 Chrome 访问亚马逊商品页面获取类目
    
    Args:
        asin: 亚马逊ASIN
    
    Returns:
        dict: {categories: [...], leaf_category: "..."}
    """
    url = f"https://www.amazon.com/dp/{asin}"
    
    logger.info(f"[Step4] 打开亚马逊商品页面: {url}")
    success = await chrome_navigate(url, wait=4.0)
    if not success:
        raise RuntimeError("Chrome 导航到亚马逊失败")

    # 提取类目
    logger.info("[Step4] 提取类目信息...")
    js_result = await chrome_execute_js(CATEGORY_EXTRACT_JS, timeout=15)
    if not js_result:
        raise RuntimeError("Chrome JS 提取类目失败")

    try:
        data = json.loads(js_result)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"类目数据解析失败: {e}")

    if not data.get("categories"):
        logger.warning("[Step4] 未提取到类目信息，可能页面未完全加载")
        # 重试一次
        await asyncio.sleep(2)
        js_result = await chrome_execute_js(CATEGORY_EXTRACT_JS, timeout=15)
        if js_result:
            try:
                data = json.loads(js_result)
            except:
                pass

    return data


async def run_category(product_id: int) -> dict:
    """
    执行类目获取
    
    读取商品的 competitor_asin，通过 Chrome 访问亚马逊获取类目
    """
    async with async_session() as db:
        result = await db.execute(
            select(Product)
            .options(selectinload(Product.data))
            .where(Product.id == product_id)
        )
        product = result.scalar_one_or_none()
        if not product:
            raise ValueError(f"Product {product_id} not found")

        asin = product.competitor_asin
        if not asin:
            logger.warning("[Step4] 跳过类目获取：未设置竞品ASIN")
            return {"skipped": True, "reason": "no_competitor_asin"}

        # 获取类目
        cat_data = await fetch_categories(asin)

        categories = cat_data.get("categories", [])
        leaf = cat_data.get("leafCategory")

        if not categories:
            raise RuntimeError(f"无法获取ASIN {asin} 的类目信息")

        # 保存
        pd = product.data
        if pd:
            pd.categories = json.dumps(categories, ensure_ascii=False)
            pd.leaf_category = leaf
            await db.commit()

        logger.info(f"[Step4] 类目获取完成: ASIN={asin}, 类目={' > '.join(categories)}")
        return cat_data
