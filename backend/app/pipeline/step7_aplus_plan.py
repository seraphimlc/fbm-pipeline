"""
模块7：A+ 规划 — 使用 LLM 设计 A+ Content 布局

基于商品属性、卖点、关键词和图片分析结果，
生成 A+ Content 的模块布局规划（通常 5-7 个模块）
"""

import json
import logging
from datetime import datetime

from app.config import settings
from app.database import async_session
from app.models import Product, ProductData, ProductImage, ProductAplus
from sqlalchemy import select
from sqlalchemy.orm import selectinload

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an Amazon A+ Content strategist. You design compelling A+ Content layouts that:
1. Tell a brand story
2. Highlight key selling points visually
3. Address buyer objections
4. Cross-sell related products
5. Follow Amazon A+ Content best practices

Common A+ module types:
- Standard Image Header (banner with text overlay)
- Standard Single Image + Text (side by side)
- Standard 4 Image / Text (quadrant layout)
- Standard Comparison Chart
- Standard Multiple Image + Text

Output valid JSON only."""

PLAN_PROMPT = """Design an A+ Content plan for this Amazon product.

## Product
- Title: {title}
- Brand: {brand}
- Category: {category}
- Price: ${price}

## Key Features
{features}

## Image Selling Points
{selling_points}

## Primary Keyword
{primary_keyword}

## Requirements
1. 5-7 modules total
2. First module: brand banner/header
3. Mix of image+text modules
4. At least one comparison or spec module
5. Last module: cross-sell or brand closing
6. Each module needs: type, headline, key message, image concept

Output JSON:
{{
  "plan_summary": "brief description of the A+ strategy",
  "modules": [
    {{
      "position": 1,
      "type": "standard_image_header",
      "headline": "...",
      "subheading": "...",
      "key_message": "...",
      "image_concept": "description of what this image should show",
      "image_style": "photography|3d_render|infographic|lifestyle",
      "text_content": "body text for this module"
    }}
  ],
  "color_palette": ["#hex1", "#hex2"],
  "tone": "professional|warm|minimal|bold",
  "target_audience": "..."
}}"""


async def run_aplus_plan(product_id: int) -> dict:
    """
    执行 A+ 规划
    
    读取所有前置数据，调用 LLM 生成 A+ 布局方案
    """
    async with async_session() as db:
        result = await db.execute(
            select(Product)
            .options(
                selectinload(Product.data),
                selectinload(Product.images),
                selectinload(Product.aplus),
            )
            .where(Product.id == product_id)
        )
        product = result.scalar_one_or_none()
        if not product or not product.data:
            raise ValueError(f"Product {product_id} not found or no data")

        pd = product.data
        pi = product.images

        # 收集卖点
        selling_points = []
        if pi and pi.image_selling_points:
            try:
                selling_points = json.loads(pi.image_selling_points)
            except:
                pass

        # 收集features
        features = "N/A"
        if pd.features:
            try:
                fl = json.loads(pd.features)
                features = "\n".join(f"- {f}" for f in fl) if isinstance(fl, list) else str(fl)
            except:
                features = str(pd.features)

        prompt = PLAN_PROMPT.format(
            title=pd.listing_title or pd.title or "Unknown",
            brand=product.brand or settings.DEFAULT_BRAND,
            category=pd.leaf_category or "General",
            price=pd.suggested_price or "TBD",
            features=features,
            selling_points="\n".join(f"- {s}" for s in selling_points) if selling_points else "N/A",
            primary_keyword=pd.listing_primary_keyword or "N/A",
        )

        # 调用 LLM
        client = settings.get_llm_client()

        logger.info(f"[Step7] 调用LLM生成A+规划: {pd.title}")
        response = await client.chat.completions.create(
            model=settings.LLM_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=0.8,
            max_tokens=3000,
            response_format={"type": "json_object"},
        )

        content = response.choices[0].message.content
        if not content:
            raise RuntimeError("LLM 返回空结果")

        try:
            plan = json.loads(content)
        except json.JSONDecodeError as e:
            raise RuntimeError(f"A+规划JSON解析失败: {e}")

        # 确保 ProductAplus 记录存在
        pa = product.aplus
        if not pa:
            pa = ProductAplus(product_id=product.id)
            db.add(pa)

        pa.aplus_plan = json.dumps(plan, ensure_ascii=False)
        pa.aplus_plan_summary = plan.get("plan_summary")
        pa.planned_at = datetime.now()
        pa.llm_model = settings.LLM_MODEL
        await db.commit()

        modules = plan.get("modules", [])
        logger.info(f"[Step7] A+规划完成: {len(modules)} 个模块, 风格={plan.get('tone')}")
        return plan
