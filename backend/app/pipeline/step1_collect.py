"""
模块1：商品采集 — 从大健云仓(GigaB2B)采集商品数据
通过 Chrome + AppleScript 控制浏览器，执行 JS 提取商品信息
"""

import json
import re
import logging
import asyncio
import httpx
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse, urlencode, parse_qs

from app.config import settings
from app.database import async_session
from app.models import Product, ProductData
from app.pipeline.chrome_ctrl import chrome_navigate, chrome_execute_js

logger = logging.getLogger(__name__)


def _strip_oss_process(url: str) -> str:
    """去掉 OSS 缩略图参数，获取原图"""
    parsed = urlparse(url)
    # 如果 URL 里有 x-oss-process，去掉它（问号后面全部）
    base = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    # 但保留 CDN 认证参数 (x-cc, x-cu, x-ct, x-cs)
    qs = parse_qs(parsed.query)
    auth_params = {k: v[0] for k, v in qs.items() if k.startswith("x-c")}
    if auth_params:
        base += "?" + urlencode(auth_params)
    return base


async def _download_images(image_urls: list[str], save_dir: Path) -> int:
    """
    下载商品图片到素材目录
    去掉 OSS 缩略图参数获取原图
    """
    downloaded = 0
    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
        for i, url in enumerate(image_urls, 1):
            try:
                # 获取原图URL
                original_url = _strip_oss_process(url)
                ext = Path(urlparse(url).path).suffix or ".jpg"
                if ext not in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
                    ext = ".jpg"
                save_path = save_dir / f"source_image_{i:02d}{ext}"

                resp = await client.get(original_url)
                if resp.status_code == 200:
                    save_path.write_bytes(resp.content)
                    logger.info(f"[Step1] 图片 {i} 已下载: {save_path.name} ({len(resp.content)//1024}KB)")
                    downloaded += 1
                else:
                    logger.warning(f"[Step1] 图片 {i} 下载失败: HTTP {resp.status_code}")
            except Exception as e:
                logger.warning(f"[Step1] 图片 {i} 下载异常: {e}")
    return downloaded

# GigaB2B 商品信息提取 JS — 从外部文件加载，避免 Python 转义问题
_EXTRACT_JS_PATH = Path(__file__).parent / "extract_product.js"


def _load_extract_js() -> str:
    """加载 JS 提取脚本，避免 Python 三引号转义问题"""
    return _EXTRACT_JS_PATH.read_text(encoding="utf-8")


EXTRACT_JS = _load_extract_js()


def extract_product_id(url: str) -> str | None:
    """从 GigaB2B URL 提取商品ID"""
    match = re.search(r'product_id=(\d+)', url)
    if match:
        return match.group(1)
    match = re.search(r'product-detail/(\d+)', url)
    if match:
        return match.group(1)
    return None


def _parse_float(val) -> float | None:
    """安全解析浮点数"""
    if val is None:
        return None
    try:
        # 去掉逗号和空格
        cleaned = str(val).replace(",", "").replace(" ", "").strip()
        return float(cleaned)
    except (ValueError, TypeError):
        return None


def _parse_int(val) -> int | None:
    """安全解析整数"""
    if val is None:
        return None
    try:
        return int(float(str(val).replace(",", "").strip()))
    except (ValueError, TypeError):
        return None


async def collect_product(product_id: int) -> dict:
    """
    执行商品采集：
    1. 从 URL 提取 GigaB2B 商品ID
    2. 通过 Chrome 打开页面
    3. 执行 JS 提取商品数据
    4. 解析并保存到数据库
    
    Returns:
        dict: 采集到的商品数据
    """
    async with async_session() as db:
        # 读取商品记录
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload
        result = await db.execute(
            select(Product)
            .options(selectinload(Product.data))
            .where(Product.id == product_id)
        )
        product = result.scalar_one_or_none()
        if not product:
            raise ValueError(f"Product {product_id} not found")

        gigab2b_pid = extract_product_id(product.gigab2b_url)
        if not gigab2b_pid:
            raise ValueError(f"无法从URL提取商品ID: {product.gigab2b_url}")

        # 更新 product_id 字段
        product.gigab2b_product_id = gigab2b_pid

        # 打开 GigaB2B 页面
        url = f"https://www.gigab2b.com/index.php?route=product/product&product_id={gigab2b_pid}"
        logger.info(f"[Step1] 打开 GigaB2B 页面: {url}")
        
        success = await chrome_navigate(url, wait=4.0)
        if not success:
            raise RuntimeError("Chrome 导航失败，请确认 Chrome 已开启 JS 权限")

        # 执行 JS 提取
        logger.info("[Step1] 执行 JS 提取商品数据...")
        js_result = await chrome_execute_js(EXTRACT_JS, timeout=30)
        if not js_result:
            raise RuntimeError("Chrome JS 提取失败，请确认页面已加载完成")

        try:
            data = json.loads(js_result)
        except json.JSONDecodeError as e:
            raise RuntimeError(f"JS 返回数据解析失败: {e}")

        logger.info(f"[Step1] 提取到商品: {data.get('title', 'N/A')}")

        # 创建素材目录
        brand = product.brand or settings.DEFAULT_BRAND
        item_code = data.get("itemCode") or gigab2b_pid
        material_dir = settings.PRODUCT_BASE_DIR / brand / item_code
        material_dir.mkdir(parents=True, exist_ok=True)

        # 解析并保存数据
        pd = product.data
        if not pd:
            pd = ProductData(product_id=product.id)
            db.add(pd)

        pd.item_code = data.get("itemCode")
        pd.title = data.get("title")
        pd.color = data.get("color")
        pd.material = data.get("material")
        pd.filler = data.get("filler")
        pd.product_type = data.get("productType")
        pd.dimension_length = _parse_float(data.get("dimensionLength"))
        pd.dimension_width = _parse_float(data.get("dimensionWidth"))
        pd.dimension_height = _parse_float(data.get("dimensionHeight"))
        pd.weight = _parse_float(data.get("weight"))
        pd.packages = json.dumps(data.get("packages", []), ensure_ascii=False) if data.get("packages") else None
        pd.value_total = _parse_float(data.get("valueTotal"))
        pd.estimated_total = _parse_float(data.get("estimatedTotal"))
        pd.shipping_cost = _parse_float(data.get("shippingCost"))  # 一件代发物流费
        pd.shipping_cost_min = _parse_float(data.get("shippingCostMin"))  # 云送仓最低物流费
        pd.shipping_cost_max = _parse_float(data.get("shippingCostMax"))  # 云送仓最高物流费
        pd.features = json.dumps(data.get("features", []), ensure_ascii=False) if data.get("features") else None
        pd.description = data.get("characteristic")  # 大建五点描述
        pd.variants = json.dumps(data.get("variants", []), ensure_ascii=False) if data.get("variants") else None
        pd.stock = None  # 需要额外接口
        pd.seller = data.get("seller")
        pd.origin = data.get("origin")
        pd.image_count = _parse_int(data.get("imageCount"))
        pd.material_dir = str(material_dir)
        pd.collected_at = datetime.now()

        await db.commit()

        # === 下载商品图片 ===
        image_urls = data.get("imageUrls", [])
        if image_urls:
            logger.info(f"[Step1] 开始下载 {len(image_urls)} 张商品图片...")
            downloaded = await _download_images(image_urls, material_dir)
            logger.info(f"[Step1] 图片下载完成: {downloaded}/{len(image_urls)}")
        else:
            logger.warning("[Step1] 未提取到图片URL，跳过下载")

        logger.info(f"[Step1] 商品采集完成: {pd.item_code} / {pd.title}")
        return data
