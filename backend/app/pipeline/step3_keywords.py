"""
模块3：关键词获取 — 通过卖家精灵逆向API获取关键词反查数据

使用卖家精灵的导出API（逆向自JS源码 chunk-01ccfd8e）
POST /v3/api/relation/ta/export-keyword-new?market=1
"""

import io
import json
import logging
import httpx
from datetime import datetime
from pathlib import Path

import openpyxl

from app.config import settings
from app.database import async_session
from app.models import Product, ProductData
from sqlalchemy import select
from sqlalchemy.orm import selectinload

logger = logging.getLogger(__name__)

# 卖家精灵 API 地址
API_BASE = "https://www.sellersprite.com"
EXPORT_ENDPOINT = "/v3/api/relation/ta/export-keyword-new"

# 请求头
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/json;charset=UTF-8",
    "Origin": "https://www.sellersprite.com",
    "Referer": "https://www.sellersprite.com/keyword-reverse-search",
}


async def _get_sellersprite_cookie() -> str:
    """从Chrome获取卖家精灵的完整Cookie"""
    try:
        from app.pipeline.chrome_ctrl import chrome_execute_js
        js_result = await chrome_execute_js('document.cookie')
        if js_result and 'Sprite-X-Token' in js_result:
            return js_result
    except Exception as e:
        logger.debug(f"从Chrome获取cookie失败: {e}")
    raise RuntimeError("未找到Sprite-X-Token，请先在Chrome登录卖家精灵")


async def fetch_keywords(asin: str) -> list[dict]:
    """
    通过卖家精灵API获取ASIN的关键词反查数据
    
    Args:
        asin: 亚马逊ASIN
    
    Returns:
        list[dict]: 关键词列表，每个包含 keyword, search_volume, position 等
    """
    # 优先用配置的token，否则从Chrome获取
    if settings.SELLERSPRITE_TOKEN:
        cookie = f"Sprite-X-Token={settings.SELLERSPRITE_TOKEN}"
    else:
        cookie = await _get_sellersprite_cookie()

    headers = {**HEADERS, "Cookie": cookie}

    params = {
        "market": "1",              # 美国站
        "exportVariations": "false",
        "exportGkImages": "false",
    }

    body = {"asin": asin}

    async with httpx.AsyncClient(timeout=120) as client:
        logger.info(f"[Step3] 请求卖家精灵关键词: ASIN={asin}")
        resp = await client.post(
            f"{API_BASE}{EXPORT_ENDPOINT}",
            params=params,
            json=body,
            headers=headers,
        )

        if resp.status_code == 401:
            raise RuntimeError("卖家精灵 Token 已过期，请重新获取")
        if resp.status_code == 429:
            raise RuntimeError("卖家精灵 API 限流，请稍后重试")
        if resp.status_code != 200:
            raise RuntimeError(f"卖家精灵 API 错误: {resp.status_code} {resp.text[:200]}")

        # 返回的是 Excel 文件
        content_type = resp.headers.get("content-type", "")
        if "json" in content_type:
            # 可能返回了错误JSON
            data = resp.json()
            if data.get("code") != 0:
                raise RuntimeError(f"卖家精灵 API 返回错误: {data}")

        # 解析 Excel
        keywords = _parse_excel(resp.content)
        logger.info(f"[Step3] 获取到 {len(keywords)} 个关键词")
        return keywords


def _parse_excel(content: bytes) -> list[dict]:
    """解析卖家精灵导出的 Excel"""
    wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True)
    ws = wb.active

    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return []

    # 第一行是表头
    headers = [str(h or "").strip() for h in rows[0]]
    
    # 标准化列名映射（卖家精灵可能的列名）
    col_map = {}
    for i, h in enumerate(headers):
        h_lower = h.lower()
        if "keyword" in h_lower or "搜索词" in h or "关键词" in h:
            col_map["keyword"] = i
        elif "search volume" in h_lower or "搜索量" in h or "搜索热度" in h:
            col_map["search_volume"] = i
        elif "position" in h_lower or "排名" in h:
            col_map["position"] = i
        elif "page" in h_lower or "页码" in h:
            col_map["page"] = i
        elif "product count" in h_lower or "商品数" in h or "竞品数" in h:
            col_map["product_count"] = i
        elif "asin" in h_lower:
            col_map["asin"] = i
        elif "月搜索量" in h:
            col_map["monthly_volume"] = i

    keywords = []
    for row in rows[1:]:
        entry = {}
        for field, idx in col_map.items():
            entry[field] = row[idx] if idx < len(row) else None
        if entry.get("keyword"):
            keywords.append(entry)

    wb.close()
    return keywords


def _top_keywords(keywords: list[dict], limit: int = 20) -> list[dict]:
    """取搜索量最高的 top N 关键词"""
    sorted_kw = sorted(
        keywords,
        key=lambda x: int(x.get("search_volume") or x.get("monthly_volume") or 0),
        reverse=True,
    )
    return sorted_kw[:limit]


async def run_keywords(product_id: int) -> dict:
    """
    执行关键词获取
    
    读取商品的 competitor_asin，调用卖家精灵API获取关键词
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
            logger.warning("[Step3] 跳过关键词获取：未设置竞品ASIN")
            return {"skipped": True, "reason": "no_competitor_asin"}

        # 检查是否有卖家精灵 Token
        if not settings.SELLERSPRITE_TOKEN:
            logger.warning(
                "[Step3] 跳过关键词获取：未配置卖家精灵Token。"
                "请在 .env 设置 SELLERSPRITE_TOKEN 或在Chrome登录卖家精灵。"
            )
            return {"skipped": True, "reason": "no_sellersprite_token"}

        # 调用API
        keywords = await fetch_keywords(asin)

        # 取 Top 20
        top = _top_keywords(keywords, 20)

        # 保存 Excel 到素材目录
        pd = product.data
        keyword_dir = Path(pd.material_dir) if pd and pd.material_dir else None
        excel_path = None
        if keyword_dir:
            keyword_dir.mkdir(parents=True, exist_ok=True)
            excel_path = keyword_dir / f"keywords_{asin}.xlsx"
            # 将原始Excel保存（如果有）
            # TODO: 如果需要保存原始Excel，需要在fetch_keywords中返回原始bytes

        # 保存到数据库
        if pd:
            pd.keywords_top = json.dumps(
                [{"keyword": k.get("keyword"), "volume": k.get("search_volume") or k.get("monthly_volume"), "position": k.get("position")} for k in top],
                ensure_ascii=False,
            )
            pd.keyword_excel_path = str(excel_path) if excel_path else None
            await db.commit()

        logger.info(f"[Step3] 关键词获取完成: ASIN={asin}, top={len(top)}, total={len(keywords)}")
        return {
            "asin": asin,
            "total_keywords": len(keywords),
            "top_keywords": top,
            "excel_path": str(excel_path) if excel_path else None,
        }
