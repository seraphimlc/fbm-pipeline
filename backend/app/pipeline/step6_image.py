"""
模块6：主图分析 — 使用 VLM 分析商品图片，选择主图和副图

流程：
1. 从素材目录读取所有商品图片
2. 生成 Contact Sheet（缩略图拼接）
3. VLM 分析每张图片的卖点
4. 根据主图规则选择合规主图和副图序列
"""

import json
import logging
import asyncio
from datetime import datetime
from pathlib import Path

from openai import AsyncOpenAI
from PIL import Image

from app.config import settings
from app.database import async_session
from app.models import Product, ProductData, ProductImage
from sqlalchemy import select
from sqlalchemy.orm import selectinload

logger = logging.getLogger(__name__)

# 支持的图片格式
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tiff"}

# Contact Sheet 参数
THUMB_SIZE = 400
SHEET_COLS = 3
SHEET_MAX = 9  # 每页最多9张

# VLM 系统提示
VLM_SYSTEM_PROMPT = """You are an expert Amazon product image analyst. You analyze product images and provide:
1. Compliance assessment (Amazon main image rules)
2. Selling point extraction
3. Quality scoring
4. Recommended slot assignment

Amazon main image rules:
- Pure white background (#FFFFFF)
- Product occupies 85%+ of frame
- No text overlays, logos, or watermarks on main image
- No accessories not included
- Single product view preferred
- Professional photography quality

Output valid JSON only."""

VLM_ANALYSIS_PROMPT = """Analyze this product image contact sheet for Amazon listing.

Product: {title}
Brand: {brand}
Category: {category}

For each image (numbered top-left to bottom-right), provide:
- compliance: compliant | non-compliant (for slot 01)
- selling_points: list of visual selling points
- quality_score: 1-10
- recommended_slot: 01-09 or "exclude"
- reason: brief explanation

Output JSON:
{{
  "images": [
    {{
      "index": 1,
      "compliance": "compliant|non-compliant",
      "selling_points": ["...", "..."],
      "quality_score": 8,
      "recommended_slot": "01",
      "reason": "..."
    }}
  ],
  "main_image_candidate": 1,
  "gallery_order": [1, 3, 5, 2, 4],
  "excluded": [6, 7],
  "overall_assessment": "...",
  "category_style": "standard|lifestyle|infographic"
}}"""


def _scan_images(material_dir: str) -> list[Path]:
    """扫描素材目录中的所有图片"""
    dir_path = Path(material_dir)
    if not dir_path.exists():
        return []
    
    images = []
    for ext in IMAGE_EXTENSIONS:
        images.extend(dir_path.glob(f"*{ext}"))
        images.extend(dir_path.glob(f"*{ext.upper()}"))
    
    # 排序：优先原图，排除 new main image / new aplus image 子目录
    result = []
    for img in sorted(images):
        if "new " not in str(img).lower():
            result.append(img)
    return result


def _build_contact_sheet(images: list[Path], output_path: Path) -> Path | None:
    """生成 Contact Sheet"""
    if not images:
        return None

    batch = images[:SHEET_MAX]
    n = len(batch)
    rows = (n + SHEET_COLS - 1) // SHEET_COLS

    sheet_w = SHEET_COLS * THUMB_SIZE + (SHEET_COLS + 1) * 10
    sheet_h = rows * THUMB_SIZE + (rows + 1) * 10

    sheet = Image.new("RGB", (sheet_w, sheet_h), (40, 40, 40))

    for i, img_path in enumerate(batch):
        row = i // SHEET_COLS
        col = i % SHEET_COLS
        x = 10 + col * (THUMB_SIZE + 10)
        y = 10 + row * (THUMB_SIZE + 10)

        try:
            img = Image.open(img_path).convert("RGB")
            img.thumbnail((THUMB_SIZE, THUMB_SIZE), Image.Resampling.LANCZOS)
            # 居中
            offset_x = x + (THUMB_SIZE - img.width) // 2
            offset_y = y + (THUMB_SIZE - img.height) // 2
            sheet.paste(img, (offset_x, offset_y))
        except Exception as e:
            logger.warning(f"无法处理图片 {img_path}: {e}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output_path, quality=90)
    return output_path


async def run_image_analysis(product_id: int) -> dict:
    """
    执行主图分析
    
    1. 扫描素材目录图片
    2. 生成 Contact Sheet
    3. VLM 分析
    4. 选择主图和副图
    """
    async with async_session() as db:
        result = await db.execute(
            select(Product)
            .options(selectinload(Product.data), selectinload(Product.images))
            .where(Product.id == product_id)
        )
        product = result.scalar_one_or_none()
        if not product or not product.data:
            raise ValueError(f"Product {product_id} not found or no data")

        pd = product.data
        if not pd.material_dir:
            raise ValueError("未设置素材目录，请先执行商品采集")

        # 扫描图片
        images = _scan_images(pd.material_dir)
        if not images:
            raise ValueError(f"素材目录中未找到图片: {pd.material_dir}")

        logger.info(f"[Step6] 找到 {len(images)} 张图片")

        # 确保 ProductImage 记录存在
        pi = product.images
        if not pi:
            pi = ProductImage(product_id=product.id)
            db.add(pi)

        # 生成 Contact Sheet
        material_dir = Path(pd.material_dir)
        cs_path = material_dir / "contact_sheet.jpg"
        _build_contact_sheet(images, cs_path)
        pi.contact_sheet_path = str(cs_path)

        # 调用 VLM 分析
        client = AsyncOpenAI(
            base_url=settings.VLM_API_BASE,
            api_key=settings.VLM_API_KEY,
        )

        # 构建带图片的请求
        import base64
        with open(cs_path, "rb") as f:
            img_b64 = base64.b64encode(f.read()).decode()

        category = pd.leaf_category or "General"
        prompt = VLM_ANALYSIS_PROMPT.format(
            title=pd.title or "Unknown",
            brand=product.brand or settings.DEFAULT_BRAND,
            category=category,
        )

        logger.info("[Step6] 调用VLM分析图片...")
        response = await client.chat.completions.create(
            model=settings.VLM_MODEL,
            messages=[
                {"role": "system", "content": VLM_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{img_b64}",
                            },
                        },
                    ],
                },
            ],
            max_tokens=2000,
            temperature=0.3,
            # thinking 开启，让 VLM 深度分析卖点（正式流水线无 timeout 限制）
            # extra_body={"enable_thinking": False},
        )

        content = response.choices[0].message.content
        if not content:
            raise RuntimeError("VLM 返回空结果")

        # 清理可能的 markdown fence
        content_clean = content.strip()
        if content_clean.startswith("```"):
            content_clean = content_clean.split("\n", 1)[1] if "\n" in content_clean else content_clean[3:]
        if content_clean.endswith("```"):
            content_clean = content_clean[:-3]
        content_clean = content_clean.strip()

        try:
            analysis = json.loads(content_clean)
        except json.JSONDecodeError as e:
            logger.warning(f"VLM JSON解析失败，保存原始内容: {e}")
            analysis = {"raw": content, "images": [], "gallery_order": []}

        # 提取主图
        main_idx = analysis.get("main_image_candidate")
        gallery_order = analysis.get("gallery_order", [])
        image_analyses = analysis.get("images", [])

        # 确定主图路径
        main_image_path = None
        if main_idx and 1 <= main_idx <= len(images):
            main_image_path = str(images[main_idx - 1])

        # 确定副图路径列表
        gallery_paths = []
        for idx in gallery_order:
            if 1 <= idx <= len(images):
                gallery_paths.append(str(images[idx - 1]))

        # 卖点提取
        selling_points = []
        for img_a in image_analyses:
            selling_points.extend(img_a.get("selling_points", []))
        selling_points = list(dict.fromkeys(selling_points))[:15]  # 去重取前15

        # 保存到数据库
        pi.image_analysis = json.dumps(image_analyses, ensure_ascii=False)
        pi.image_selling_points = json.dumps(selling_points, ensure_ascii=False)
        pi.category_style = analysis.get("category_style", "standard")
        pi.main_image_path = main_image_path
        pi.main_image_source = "vlm_selected"
        pi.gallery_images = json.dumps(gallery_paths, ensure_ascii=False)
        pi.gallery_order = json.dumps(gallery_order, ensure_ascii=False)
        pi.main_image_summary = analysis.get("overall_assessment")
        pi.analyzed_at = datetime.now()
        pi.vlm_model = settings.VLM_MODEL
        await db.commit()

        logger.info(
            f"[Step6] 图片分析完成: {len(image_analyses)} 张图, "
            f"主图={main_image_path}, 副图={len(gallery_paths)} 张"
        )
        return analysis
