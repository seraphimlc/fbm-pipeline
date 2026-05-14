"""
模块5：Listing文案 — 使用 LLM 生成标题、五点描述、Search Terms

输入：模块1采集的商品属性 + 模块3的关键词 + 模块4的类目
输出：listing_title, listing_bullets, listing_search_terms, listing_check
"""

import json
import logging
from datetime import datetime

from app.config import settings
from app.database import async_session
from app.models import Product, ProductData
from sqlalchemy import select
from sqlalchemy.orm import selectinload

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an expert Amazon listing copywriter specializing in the US marketplace.
Your goal is to write buyer-centered listing copy that attracts the right customers and reduces mismatched clicks.

Core principles:
- Searchable but natural language
- Product truth over keyword stuffing
- Scenario-driven benefits that help shoppers decide
- Clear answers to buyer doubts about fit, use, durability, etc.
- No exaggeration or unsupported claims

You must output valid JSON only, no markdown fences."""

LISTING_PROMPT_TEMPLATE = """Generate an Amazon product listing based on the following information.

## Product Attributes
- Title (supplier): {title}
- Brand: {brand}
- Color: {color}
- Material: {material}
- Filler: {filler}
- Product Type: {product_type}
- Dimensions: {length}" L x {width}" W x {height}" H
- Weight: {weight} lbs
- Features: {features}
- Origin: {origin}

## Top Keywords (from competitor analysis)
{keywords_json}

## Category
{category_path}

## Requirements
1. **Title** (max 200 chars): Include brand, primary keyword, key attributes. Natural and searchable.
2. **Five Bullets** (each max 500 chars): Benefit-driven, scenario-based. Address buyer objections.
3. **Search Terms** (max 250 bytes total, space-separated): High-value keywords NOT already in title/bullets.
4. **Primary Keyword**: The single most important search term for this product.
5. **Compliance Check**: Flag any risky claims, prohibited words, or issues.

Output JSON:
{{
  "title": "...",
  "bullets": ["...", "...", "...", "...", "..."],
  "search_terms": "...",
  "primary_keyword": "...",
  "compliance_check": {{
    "status": "pass|warning",
    "issues": ["..."]
  }},
  "removed_keywords": ["keywords intentionally excluded and why"]
}}"""


def _build_prompt(product: Product, pd: ProductData) -> str:
    """构建LLM Prompt"""
    # 解析关键词
    keywords = []
    if pd.keywords_top:
        try:
            keywords = json.loads(pd.keywords_top)
        except:
            pass

    # 解析features
    features = "N/A"
    if pd.features:
        try:
            fl = json.loads(pd.features)
            features = "; ".join(fl) if isinstance(fl, list) else str(fl)
        except:
            features = str(pd.features)

    # 类目路径
    category_path = "N/A"
    if pd.categories:
        try:
            cats = json.loads(pd.categories)
            category_path = " > ".join(cats) if isinstance(cats, list) else str(cats)
        except:
            category_path = str(pd.categories)

    keywords_json = json.dumps(keywords, ensure_ascii=False, indent=2) if keywords else "[]"

    return LISTING_PROMPT_TEMPLATE.format(
        title=pd.title or "N/A",
        brand=product.brand or settings.DEFAULT_BRAND,
        color=pd.color or "N/A",
        material=pd.material or "N/A",
        filler=pd.filler or "N/A",
        product_type=pd.product_type or "N/A",
        length=pd.dimension_length or "?",
        width=pd.dimension_width or "?",
        height=pd.dimension_height or "?",
        weight=pd.weight or "?",
        features=features,
        origin=pd.origin or "N/A",
        keywords_json=keywords_json,
        category_path=category_path,
    )


async def run_listing(product_id: int) -> dict:
    """
    执行 Listing 文案生成
    
    读取 Step1-4 的数据，调用 LLM 生成 Listing
    """
    async with async_session() as db:
        result = await db.execute(
            select(Product)
            .options(selectinload(Product.data))
            .where(Product.id == product_id)
        )
        product = result.scalar_one_or_none()
        if not product or not product.data:
            raise ValueError(f"Product {product_id} not found or no data")

        pd = product.data
        if not pd.title and not pd.product_type:
            raise ValueError("缺少商品基本信息，无法生成Listing")

        # 构建Prompt
        prompt = _build_prompt(product, pd)

        # 调用 LLM
        client = settings.get_llm_client()

        logger.info(f"[Step5] 调用LLM生成Listing: {pd.title}")
        response = await client.chat.completions.create(
            model=settings.LLM_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=0.7,
            max_tokens=2000,
            response_format={"type": "json_object"},
        )

        content = response.choices[0].message.content
        if not content:
            raise RuntimeError("LLM 返回空结果")

        try:
            listing = json.loads(content)
        except json.JSONDecodeError as e:
            raise RuntimeError(f"LLM 返回JSON解析失败: {e}")

        # 保存到数据库
        pd.listing_title = listing.get("title")
        pd.listing_bullets = json.dumps(listing.get("bullets", []), ensure_ascii=False)
        pd.listing_search_terms = listing.get("search_terms")
        pd.listing_check = json.dumps(listing.get("compliance_check", {}), ensure_ascii=False)
        pd.listing_primary_keyword = listing.get("primary_keyword")
        pd.listing_removed_keywords = json.dumps(listing.get("removed_keywords", []), ensure_ascii=False)
        await db.commit()

        logger.info(
            f"[Step5] Listing生成完成: 标题='{listing.get('title', '')[:50]}...', "
            f"主关键词='{listing.get('primary_keyword')}'"
        )
        return listing
