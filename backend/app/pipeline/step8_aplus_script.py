"""
模块8：A+ 脚本 — 使用 LLM 为每个 A+ 模块生成出图 Prompt

将模块7的规划转化为具体的 GPT Image 出图指令（prompt + 尺寸 + 风格）
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

SYSTEM_PROMPT = """You are an expert at writing image generation prompts for Amazon A+ Content.
You create detailed, specific prompts for GPT Image API that produce:
- Professional product photography
- Clean, brand-consistent visuals
- Amazon-compliant layouts
- High conversion design

Key rules:
- Prompts must be in English
- Describe exact composition, lighting, color scheme
- Include product appearance based on attributes
- Specify text elements to render (headlines, bullet points)
- No faces/humans unless lifestyle scene
- Output dimensions should match Amazon A+ specs

Output valid JSON only."""

SCRIPT_PROMPT = """Generate image generation prompts for each A+ Content module.

## Product
- Title: {title}
- Brand: {brand}
- Color: {color}
- Material: {material}
- Category: {category}

## A+ Plan
{plan_json}

## Brand Colors
{colors}

## Image Style
Style: {style}
Tone: {tone}

## Requirements
For each module in the plan, generate a detailed image generation prompt:
- Prompt should describe exact visual composition
- Include product appearance (color, material, shape)
- Specify text overlays (headlines, key points)
- Match the module type to Amazon image dimensions
- Each prompt should be 100-300 words

Standard Amazon A+ image sizes:
- Image Header: 970 x 600 px
- Single Image + Text: 300 x 300 or 300 x 400 px
- 4 Image Quadrant: 300 x 300 px each
- Comparison: varies

Output JSON:
{{
  "scripts": [
    {{
      "module_position": 1,
      "prompt": "detailed image generation prompt...",
      "negative_prompt": "what to avoid...",
      "width": 970,
      "height": 600,
      "style": "photography|3d_render|infographic|lifestyle",
      "text_overlays": [
        {{"text": "...", "position": "top-center", "font_size": "large"}}
      ]
    }}
  ],
  "summary": "brief description of the visual strategy"
}}"""


async def run_aplus_script(product_id: int) -> dict:
    """
    执行 A+ 脚本生成
    
    读取 A+ 规划，为每个模块生成出图 prompt
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
        pa = product.aplus
        if not pa or not pa.aplus_plan:
            raise ValueError("未找到A+规划，请先执行Step7")

        try:
            plan = json.loads(pa.aplus_plan)
        except:
            raise ValueError("A+规划数据损坏")

        prompt = SCRIPT_PROMPT.format(
            title=pd.listing_title or pd.title or "Unknown",
            brand=product.brand or settings.DEFAULT_BRAND,
            color=pd.color or "N/A",
            material=pd.material or "N/A",
            category=pd.leaf_category or "General",
            plan_json=json.dumps(plan.get("modules", []), ensure_ascii=False, indent=2),
            colors=", ".join(plan.get("color_palette", ["#FFFFFF", "#000000"])),
            style=plan.get("tone", "professional"),
            tone=plan.get("tone", "professional"),
        )

        # 调用 LLM
        client = settings.get_llm_client()

        logger.info(f"[Step8] 调用LLM生成A+脚本: {len(plan.get('modules', []))} 个模块")
        response = await client.chat.completions.create(
            model=settings.LLM_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=0.7,
            max_tokens=4000,
            response_format={"type": "json_object"},
        )

        content = response.choices[0].message.content
        if not content:
            raise RuntimeError("LLM 返回空结果")

        try:
            scripts_data = json.loads(content)
        except json.JSONDecodeError as e:
            raise RuntimeError(f"A+脚本JSON解析失败: {e}")

        # 保存
        pa.aplus_scripts = json.dumps(scripts_data, ensure_ascii=False)
        pa.aplus_scripts_summary = scripts_data.get("summary")
        pa.scripted_at = datetime.now()
        await db.commit()

        scripts = scripts_data.get("scripts", [])
        logger.info(f"[Step8] A+脚本生成完成: {len(scripts)} 个出图prompt")
        return scripts_data
