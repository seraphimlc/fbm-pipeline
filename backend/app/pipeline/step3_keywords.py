"""
模块3：关键词获取 — 通过卖家精灵逆向API获取关键词反查数据

使用卖家精灵的导出API（逆向自JS源码 chunk-01ccfd8e）
POST /v3/api/relation/ta/export-keyword-new?market=1
"""

import io
import json
import logging
import httpx
from pathlib import Path

import openpyxl

from app.config import settings
from app.database import async_session
from app.models import Product
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
    "Referer": "https://www.sellersprite.com/v3/keyword-reverse",
}

PLACEHOLDER_TOKENS = {"", "xxx", "token", "your_token"}
SELLERSPRITE_LOGIN_URL = "https://www.sellersprite.com/v3/keyword-reverse"


class Step3NeedsLogin(RuntimeError):
    """卖家精灵需要人工登录后才能继续。"""


async def _request_manual_sellersprite_login(reason: str) -> None:
    if settings.STEP3_MANUAL_LOGIN_ON_AUTH_FAILURE:
        try:
            from app.pipeline.chrome_ctrl import chrome_open_url_for_user

            opened = await chrome_open_url_for_user(SELLERSPRITE_LOGIN_URL)
            if opened:
                logger.warning(f"[Step3] 已打开卖家精灵登录页面，等待人工登录: {reason}")
        except Exception as e:
            logger.warning(f"[Step3] 打开卖家精灵登录页面失败: {e}")
    raise Step3NeedsLogin(f"{reason}。请在 Chrome 登录卖家精灵后点击继续。")


async def _get_sellersprite_cookie() -> str:
    """从Chrome获取卖家精灵的完整Cookie"""
    try:
        from app.pipeline.chrome_ctrl import chrome_get_cookie_for_domain, chrome_navigate, chrome_workflow

        async with chrome_workflow("step3_sellersprite_cookie"):
            cookie = await chrome_get_cookie_for_domain("sellersprite.com")
            if cookie and "Sprite-X-Token" in cookie:
                return cookie

            # 如果用户已登录但没有打开卖家精灵标签页，先在专用标签页打开一次页面再读 cookie。
            await chrome_navigate(SELLERSPRITE_LOGIN_URL, wait=5.0)
            cookie = await chrome_get_cookie_for_domain("sellersprite.com")
            if cookie and "Sprite-X-Token" in cookie:
                return cookie
    except Exception as e:
        if isinstance(e, Step3NeedsLogin):
            raise
        logger.debug(f"从Chrome获取cookie失败: {e}")
    await _request_manual_sellersprite_login("未找到卖家精灵登录态")


async def _ensure_sellersprite_logged_in_for_empty_keywords(asin: str) -> None:
    """空导出时复核登录态：未登录停人工，已登录则认为竞品暂无关键词数据。"""
    try:
        from app.pipeline.chrome_ctrl import chrome_execute_js, chrome_navigate, chrome_workflow

        async with chrome_workflow("step3_sellersprite_empty_keywords_login_check"):
            await chrome_navigate(SELLERSPRITE_LOGIN_URL, wait=5.0)
            raw = await chrome_execute_js(
                r"""(function() {
    var text = (document.body && document.body.innerText || '').replace(/\s+/g, ' ').slice(0, 3000);
    var href = location.href || '';
    var title = document.title || '';
    var hasPasswordInput = !!document.querySelector('input[type="password"]');
    var hasLoginUrl = /login|signin|passport/i.test(href);
    var hasLoginForm = hasPasswordInput || !!document.querySelector('form[action*="login" i], input[name*="password" i]');
    var hasLoggedInHint = /退出登录|个人中心|会员中心|我的账户|账号中心|用户中心|工作台/.test(text)
        || !!document.querySelector('[class*="avatar" i], [class*="account" i], [class*="user" i]');
    var loginTextOnly = /登录卖家精灵|账号登录|手机号登录|验证码登录|忘记密码|Login|Sign in/i.test(text) && !hasLoggedInHint;
    return JSON.stringify({
        href: href,
        title: title,
        hasLoginUrl: hasLoginUrl,
        hasLoginForm: hasLoginForm,
        hasLoggedInHint: hasLoggedInHint,
        loginTextOnly: loginTextOnly
    });
})()""",
                timeout=30,
            )
    except Exception as e:
        if isinstance(e, Step3NeedsLogin):
            raise
        logger.warning(f"[Step3] 空关键词后检查卖家精灵登录态失败: ASIN={asin}, error={e}")
        return

    try:
        state = json.loads(raw or "{}")
    except Exception:
        logger.warning(f"[Step3] 空关键词后登录态检查返回异常: ASIN={asin}, raw={raw}")
        return

    if state.get("hasLoginUrl") or state.get("hasLoginForm") or state.get("loginTextOnly"):
        logger.warning(f"[Step3] 空关键词疑似卖家精灵未登录: ASIN={asin}, state={state}")
        await _request_manual_sellersprite_login("卖家精灵未登录或登录态已失效，无法确认关键词为空")

    logger.info(f"[Step3] 卖家精灵已登录但关键词为空，按竞品无数据继续: ASIN={asin}, state={state}")


def _configured_cookie() -> str | None:
    token = (settings.SELLERSPRITE_TOKEN or "").strip()
    if token.lower() in PLACEHOLDER_TOKENS:
        return None
    return f"Sprite-X-Token={token}"


def _is_excel_response(content: bytes) -> bool:
    return content.startswith(b"PK\x03\x04")


def _describe_non_excel_response(content: bytes) -> str:
    text = content[:500].decode("utf-8", errors="replace").strip()
    try:
        data = json.loads(text)
    except Exception:
        return text[:300] or "空响应"
    code = data.get("code")
    if code == "ERR_GLOBAL_SESSION_EXPIRED":
        return "卖家精灵登录已失效，请重新登录卖家精灵后继续"
    return f"卖家精灵返回非Excel数据: {data}"


async def fetch_keywords(asin: str) -> tuple[list[dict], bytes]:
    """
    通过卖家精灵API获取ASIN的关键词反查数据
    
    Args:
        asin: 亚马逊ASIN
    
    Returns:
        (关键词列表, 原始Excel bytes)
    """
    # 优先用配置的token，否则从Chrome登录态获取完整Cookie。
    cookie = _configured_cookie() or await _get_sellersprite_cookie()

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
            await _request_manual_sellersprite_login("卖家精灵登录已失效")
        if resp.status_code == 403:
            raise RuntimeError("卖家精灵没有导出权限，请确认账号已登录且有对应会员权限")
        if resp.status_code == 429:
            raise RuntimeError("卖家精灵 API 限流，请稍后重试")
        if resp.status_code != 200:
            raise RuntimeError(f"卖家精灵 API 错误: {resp.status_code} {resp.text[:200]}")

        # 成功时返回 Excel；异常时可能仍是 200 + JSON/HTML。
        content_type = resp.headers.get("content-type", "")
        if "json" in content_type:
            data = resp.json()
            if data.get("code") == "ERR_GLOBAL_SESSION_EXPIRED":
                await _request_manual_sellersprite_login("卖家精灵登录已失效")
            if data.get("code") != 0:
                raise RuntimeError(f"卖家精灵 API 返回错误: {data}")
        if not _is_excel_response(resp.content):
            reason = _describe_non_excel_response(resp.content)
            if "登录已失效" in reason:
                await _request_manual_sellersprite_login("卖家精灵登录已失效")
            raise RuntimeError(reason)

        # 解析 Excel
        keywords = _parse_excel(resp.content)
        logger.info(f"[Step3] 获取到 {len(keywords)} 个关键词")
        return keywords, resp.content


def _parse_excel(content: bytes) -> list[dict]:
    """解析卖家精灵导出的 Excel"""
    try:
        wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except Exception as e:
        raise RuntimeError(f"卖家精灵Excel解析失败: {e}; {_describe_non_excel_response(content)}") from e
    ws = wb.active

    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return []

    header_idx = None
    col_map = {}
    for r_idx, row in enumerate(rows[:10]):
        candidate_headers = [str(h or "").strip() for h in row]
        candidate_map = _build_col_map(candidate_headers)
        if "keyword" in candidate_map:
            header_idx = r_idx
            col_map = candidate_map
            logger.info(f"[Step3] Excel表头行={header_idx + 1}, headers={candidate_headers}")
            break

    if header_idx is None:
        preview = [[str(c or "").strip() for c in row[:8]] for row in rows[:5]]
        logger.warning(f"[Step3] 未识别到关键词表头，前5行预览: {preview}")
        wb.close()
        return []

    keywords = []
    for row in rows[header_idx + 1:]:
        entry = {}
        for field, idx in col_map.items():
            entry[field] = row[idx] if idx < len(row) else None
        if entry.get("keyword"):
            keywords.append(entry)

    wb.close()
    return keywords


def _build_col_map(headers: list[str]) -> dict:
    """标准化列名映射（卖家精灵可能的列名）"""
    col_map = {}
    for i, h in enumerate(headers):
        h = h.strip()
        h_lower = h.lower()
        if "keyword" not in col_map and (h_lower == "keyword" or h in {"关键词", "搜索词"}):
            col_map["keyword"] = i
        elif "search_volume" not in col_map and ("search volume" in h_lower or h in {"搜索量", "搜索热度"}):
            col_map["search_volume"] = i
        elif "position" not in col_map and (
            h_lower == "position" or h in {"自然排名", "排名"}
        ):
            col_map["position"] = i
        elif "page" not in col_map and (
            h_lower == "page" or h in {"自然排名页码", "页码"}
        ):
            col_map["page"] = i
        elif "product_count" not in col_map and ("product count" in h_lower or h in {"商品数", "竞品数"}):
            col_map["product_count"] = i
        elif "asin" not in col_map and h_lower == "asin":
            col_map["asin"] = i
        elif "monthly_volume" not in col_map and h == "月搜索量":
            col_map["monthly_volume"] = i
    return col_map


def _top_keywords(keywords: list[dict], limit: int = 20) -> list[dict]:
    """取搜索量最高的 top N 关键词"""
    def volume_value(item: dict) -> int:
        raw = item.get("search_volume") or item.get("monthly_volume") or 0
        try:
            return int(float(str(raw).replace(",", "").strip()))
        except (TypeError, ValueError):
            return 0

    sorted_kw = sorted(
        keywords,
        key=volume_value,
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
            raise ValueError("未设置竞品ASIN，无法获取关键词")

        # 调用API
        keywords, excel_bytes = await fetch_keywords(asin)
        if not keywords:
            await _ensure_sellersprite_logged_in_for_empty_keywords(asin)

        # 取 Top 20
        top = _top_keywords(keywords, 20)

        # 保存 Excel 到素材目录
        pd = product.data
        keyword_dir = Path(pd.material_dir) if pd and pd.material_dir else None
        excel_path = None
        if keyword_dir:
            keyword_dir.mkdir(parents=True, exist_ok=True)
            excel_path = keyword_dir / f"keywords_{asin}.xlsx"
            excel_path.write_bytes(excel_bytes)

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
