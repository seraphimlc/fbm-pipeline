"""
模块9：A+ 出图 — 使用 GPT Image API 批量生成 A+ Content 图片

基于模块8的出图脚本，并发调用 GPT Image API 生成图片
5个并发，每张图 15-30秒
"""

import asyncio
import base64
import json
import logging
from datetime import datetime
from pathlib import Path

from openai import AsyncOpenAI

from app.config import settings
from app.database import async_session
from app.models import Product, ProductAplus
from sqlalchemy import select
from sqlalchemy.orm import selectinload

logger = logging.getLogger(__name__)


async def _generate_single_image(
    client: AsyncOpenAI,
    script: dict,
    output_path: Path,
    semaphore: asyncio.Semaphore,
) -> dict:
    """
    生成单张 A+ 图片
    
    Returns:
        dict: {path, status, error?}
    """
    async with semaphore:
        prompt = script.get("prompt", "")
        width = script.get("width", 970)
        height = script.get("height", 600)
        position = script.get("module_position", 0)

        try:
            logger.info(f"[Step9] 生成模块 {position} 图片 ({width}x{height})...")
            
            response = await client.images.generate(
                model=settings.GPT_IMAGE_MODEL,
                prompt=prompt,
                n=1,
                size=f"{width}x{height}",
                quality="high",
            )

            image_data = response.data[0]
            
            # GPT Image API 可能返回 url 或 b64_json
            if hasattr(image_data, 'b64_json') and image_data.b64_json:
                img_bytes = base64.b64decode(image_data.b64_json)
            elif hasattr(image_data, 'url') and image_data.url:
                # 下载 URL
                import httpx
                async with httpx.AsyncClient(timeout=60) as http:
                    img_resp = await http.get(image_data.url)
                    img_bytes = img_resp.content
            else:
                return {"position": position, "status": "failed", "error": "No image data returned"}

            # 保存
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "wb") as f:
                f.write(img_bytes)

            logger.info(f"[Step9] 模块 {position} 图片已保存: {output_path.name}")
            return {
                "position": position,
                "status": "done",
                "path": str(output_path),
                "size": len(img_bytes),
            }

        except Exception as e:
            error_msg = f"{type(e).__name__}: {str(e)}"
            logger.error(f"[Step9] 模块 {position} 生成失败: {error_msg}")
            return {"position": position, "status": "failed", "error": error_msg}


async def run_aplus_image(product_id: int) -> dict:
    """
    执行 A+ 出图
    
    读取 A+ 脚本，并发生成所有 A+ 图片
    """
    async with async_session() as db:
        result = await db.execute(
            select(Product)
            .options(
                selectinload(Product.data),
                selectinload(Product.aplus),
            )
            .where(Product.id == product_id)
        )
        product = result.scalar_one_or_none()
        if not product or not product.data:
            raise ValueError(f"Product {product_id} not found or no data")

        pd = product.data
        pa = product.aplus
        if not pa or not pa.aplus_scripts:
            raise ValueError("未找到A+脚本，请先执行Step8")

        try:
            scripts_data = json.loads(pa.aplus_scripts)
        except:
            raise ValueError("A+脚本数据损坏")

        scripts = scripts_data.get("scripts", [])
        if not scripts:
            raise ValueError("A+脚本中没有出图模块")

        # 准备输出目录
        material_dir = Path(pd.material_dir) if pd.material_dir else Path("/tmp/fbm_unknown")
        output_dir = material_dir / "new aplus image"
        output_dir.mkdir(parents=True, exist_ok=True)

        # 创建 OpenAI client
        client = AsyncOpenAI(
            base_url=settings.GPT_IMAGE_API_BASE,
            api_key=settings.GPT_IMAGE_API_KEY,
        )

        # 并发控制
        semaphore = asyncio.Semaphore(settings.APLUS_CONCURRENCY)
        
        # 并发生成所有图片
        tasks = []
        for script in scripts:
            position = script.get("module_position", 0)
            output_path = output_dir / f"aplus_{position:02d}.png"
            tasks.append(_generate_single_image(client, script, output_path, semaphore))

        logger.info(f"[Step9] 开始生成 {len(tasks)} 张A+图片，并发数={settings.APLUS_CONCURRENCY}")
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 汇总结果
        image_results = []
        success_count = 0
        for r in results:
            if isinstance(r, Exception):
                image_results.append({"status": "failed", "error": str(r)})
            else:
                image_results.append(r)
                if r.get("status") == "done":
                    success_count += 1

        # 保存到数据库
        pa.aplus_images = json.dumps(image_results, ensure_ascii=False)
        pa.aplus_image_count = success_count
        pa.aplus_status = "done" if success_count == len(scripts) else "partial"
        pa.generated_at = datetime.now()
        await db.commit()

        logger.info(
            f"[Step9] A+出图完成: {success_count}/{len(scripts)} 成功, "
            f"目录={output_dir}"
        )
        return {
            "total": len(scripts),
            "success": success_count,
            "results": image_results,
            "output_dir": str(output_dir),
        }
