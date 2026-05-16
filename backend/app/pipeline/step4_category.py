"""
模块4：类目获取 — 通过 Chrome 访问亚马逊BSR页面获取类目信息

基于竞品ASIN，在亚马逊上查找其所在类目节点
"""

import json
import logging
import asyncio
import re

from app.config import settings
from app.database import async_session
from app.models import Product, ProductData
from app.pipeline.chrome_ctrl import chrome_navigate, chrome_execute_js, chrome_get_page_info, chrome_workflow
from sqlalchemy import select
from sqlalchemy.orm import selectinload

logger = logging.getLogger(__name__)


class Step4NeedsReview(RuntimeError):
    """Step4 缺少类目输入，需要人工补充后继续。"""


def _policy_value(value: str | None, default: str = "manual_review") -> str:
    normalized = (value or "").strip().lower()
    return normalized if normalized in {"fail", "manual_review", "continue"} else default


def _existing_category(pd: ProductData | None) -> tuple[list[str], str | None]:
    if not pd:
        return [], None
    categories: list[str] = []
    if pd.categories:
        try:
            parsed = json.loads(pd.categories)
            if isinstance(parsed, list):
                categories = [str(item).strip() for item in parsed if str(item).strip()]
        except json.JSONDecodeError:
            categories = [part.strip() for part in re.split(r"\s*>\s*|\s*›\s*", pd.categories) if part.strip()]
    leaf = (pd.leaf_category or "").strip() or (categories[-1] if categories else None)
    return categories, leaf


def _handle_category_issue(issue: str, policy: str, pd: ProductData | None) -> dict | None:
    existing_categories, existing_leaf = _existing_category(pd)
    if settings.STEP4_ALLOW_EXISTING_CATEGORY and (existing_categories or existing_leaf):
        logger.warning(f"[Step4] {issue}，使用已有类目继续: {existing_leaf or existing_categories}")
        return {
            "skipped": True,
            "reason": issue,
            "used_existing_category": True,
            "categories": existing_categories,
            "leafCategory": existing_leaf,
        }

    policy = _policy_value(policy)
    if policy == "fail":
        raise RuntimeError(issue)
    if policy == "manual_review":
        raise Step4NeedsReview(f"{issue}。请人工填写 Amazon 类目后点击继续。")

    logger.warning(f"[Step4] 按配置继续执行，忽略问题: {issue}")
    return {"skipped": True, "reason": issue, "categories": [], "leafCategory": None}

# 亚马逊商品页面类目提取 JS
CATEGORY_EXTRACT_JS = '''(function() {
  try {
    function cleanCategory(text) {
        return String(text || "")
            .replace(/\\s+/g, " ")
            .replace(/^›+|›+$/g, "")
            .trim();
    }
    function splitBreadcrumbText(text) {
        return String(text || "")
            .split(/\\s*›\\s*|\\s*>\\s*/)
            .map(cleanCategory)
            .filter(function(item) {
                return item && !/^back to/i.test(item) && item.length <= 80;
            });
    }
    var result = {
        categories: [],
        leafCategory: null,
        url: location.href,
        title: document.title,
        bodyTextSample: (document.body && document.body.innerText ? document.body.innerText.slice(0, 500) : "")
    };
    
    // 方式1：面包屑导航
    var cats = [];
    var breadcrumbRoots = document.querySelectorAll(
        '#wayfinding-breadcrumbs_container, #wayfinding-breadcrumbs_feature_div, [data-feature-name="wayfinding-breadcrumbs"]'
    );
    breadcrumbRoots.forEach(function(root) {
        var links = root.querySelectorAll('a');
        if (links.length > 0) {
            links.forEach(function(a) {
                var text = cleanCategory(a.innerText || a.textContent);
                if (text) cats.push(text);
            });
        } else {
            splitBreadcrumbText(root.innerText || root.textContent).forEach(function(text) {
                cats.push(text);
            });
        }
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
                    var category = cleanCategory(m[1]);
                    if (category) tempCats.push(category);
                }
                if (tempCats.length > 0) {
                    result.categories = tempCats;
                    result.leafCategory = tempCats[0]; // 第一个是叶子类目
                }
            }
        });
    }
    
    return JSON.stringify(result);
  } catch (err) {
    return JSON.stringify({
        categories: [],
        leafCategory: null,
        error: String(err && err.stack ? err.stack : err),
        url: location.href,
        title: document.title,
        bodyTextSample: (document.body && document.body.innerText ? document.body.innerText.slice(0, 500) : "")
    });
  }
})()'''


async def fetch_categories(asin: str) -> dict:
    """
    通过 Chrome 访问亚马逊商品页面获取类目
    
    Args:
        asin: 亚马逊ASIN
    
    Returns:
        dict: {categories: [...], leaf_category: "..."}
    """
    async with chrome_workflow(f"step4_category asin={asin}"):
        return await _fetch_categories_locked(asin)


async def _fetch_categories_locked(asin: str) -> dict:
    url = f"https://www.amazon.com/dp/{asin}"
    
    logger.info(f"[Step4] 打开亚马逊商品页面: {url}")
    success = await chrome_navigate(url, wait=5.0)
    if not success:
        raise RuntimeError("Chrome 导航到亚马逊失败")

    # 提取类目
    logger.info("[Step4] 提取类目信息...")
    js_result = await chrome_execute_js(CATEGORY_EXTRACT_JS, timeout=15)
    if not js_result:
        page_info = await chrome_get_page_info()
        logger.error(f"[Step4] Chrome JS 提取类目失败，页面信息: {page_info}")
        raise RuntimeError(f"Chrome JS 提取类目失败，页面信息={page_info or '未知'}")

    try:
        data = json.loads(js_result)
    except json.JSONDecodeError as e:
        page_info = await chrome_get_page_info()
        logger.error(f"[Step4] 类目JSON解析失败: {e}; raw={js_result[:500]!r}; 页面信息={page_info}")
        raise RuntimeError(f"类目数据解析失败: {e}; 页面信息={page_info or '未知'}")

    if data.get("error"):
        raise RuntimeError(f"类目页面脚本异常: {data.get('error')}; url={data.get('url')}; title={data.get('title')}")

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
        pd = product.data
        if not asin:
            result = _handle_category_issue(
                "未设置竞品 ASIN，无法获取亚马逊类目",
                settings.STEP4_MISSING_ASIN_POLICY,
                pd,
            )
            if result is not None:
                return result

        # 获取类目
        try:
            cat_data = await fetch_categories(asin)
        except Exception as e:
            result = _handle_category_issue(
                f"亚马逊类目获取失败: {type(e).__name__}: {e}",
                settings.STEP4_CATEGORY_MISSING_POLICY,
                pd,
            )
            if result is not None:
                return result

        categories = cat_data.get("categories", [])
        leaf = cat_data.get("leafCategory")

        if not categories:
            result = _handle_category_issue(
                f"无法获取 ASIN {asin} 的类目信息",
                settings.STEP4_CATEGORY_MISSING_POLICY,
                pd,
            )
            if result is not None:
                return result

        # 保存
        if pd:
            pd.categories = json.dumps(categories, ensure_ascii=False)
            pd.leaf_category = leaf
            await db.commit()

        logger.info(f"[Step4] 类目获取完成: ASIN={asin}, 类目={' > '.join(categories)}")
        return cat_data
