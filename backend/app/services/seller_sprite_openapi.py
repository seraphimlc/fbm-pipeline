import json
import logging
from datetime import date, timedelta
from typing import Any

import httpx

from app.config import settings


logger = logging.getLogger(__name__)

MCP_URL = "https://mcp.sellersprite.com/mcp"


class SellerSpriteOpenApiError(RuntimeError):
    pass


def is_openapi_configured() -> bool:
    """Return whether an OpenAPI credential is available for workflow use."""
    return bool(settings.SELLERSPRITE_OPENAPI_SECRET_KEY.strip())


async def _call_tool(name: str, request: dict[str, Any]) -> dict[str, Any]:
    """Call one SellerSprite MCP tool and return its decoded data payload."""
    secret = settings.SELLERSPRITE_OPENAPI_SECRET_KEY.strip()
    if not secret:
        raise SellerSpriteOpenApiError("SellerSprite OpenAPI secret key is not configured")

    payload = {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {
            "name": name,
            "arguments": {"request": request},
        },
        "id": 1,
    }
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "secret-key": secret,
        "x-client": "fbm-pipeline",
    }

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(MCP_URL, json=payload, headers=headers)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise SellerSpriteOpenApiError(f"SellerSprite OpenAPI request failed: {exc}") from exc

    text = response.text.strip()
    if text.startswith("data:"):
        text = "\n".join(line[len("data:"):].strip() for line in text.splitlines() if line.startswith("data:"))
    try:
        rpc = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SellerSpriteOpenApiError("SellerSprite OpenAPI returned invalid JSON") from exc
    if rpc.get("error"):
        err = rpc["error"]
        raise SellerSpriteOpenApiError(f"{err.get('code')}: {err.get('message')}")
    content = (rpc.get("result") or {}).get("content") or []
    if not content:
        return {}
    try:
        inner = json.loads(content[0].get("text") or "{}")
    except (AttributeError, json.JSONDecodeError) as exc:
        raise SellerSpriteOpenApiError("SellerSprite OpenAPI returned an invalid tool result") from exc
    if inner.get("code") != "OK":
        raise SellerSpriteOpenApiError(f"{inner.get('code')}: {inner.get('message')}")
    data = inner.get("data")
    return data if isinstance(data, dict) else {}


async def competitor_lookup(
    asins: list[str],
    *,
    marketplace: str = "US",
    month: str | None = None,
    size: int | None = None,
) -> dict[str, dict[str, Any]]:
    """Look up SellerSprite competitor data by ASIN via the MCP HTTP endpoint."""
    cleaned_asins = list(dict.fromkeys(str(asin).strip().upper() for asin in asins if str(asin or "").strip()))
    if not cleaned_asins:
        return {}
    if not is_openapi_configured():
        logger.info("[SellerSprite] OpenAPI secret key is not configured; skip competitor enrichment")
        return {}

    request: dict[str, Any] = {
        "marketplace": (marketplace or "US").strip().upper(),
        "asins": cleaned_asins[:40],
        "page": 1,
        "size": min(max(size or len(cleaned_asins), 1), 100),
    }
    if month:
        request["month"] = month

    data = await _call_tool("competitor_lookup", request)
    items = data.get("items") if isinstance(data, dict) else []
    if not isinstance(items, list):
        return {}
    return {
        str(item.get("asin")).strip().upper(): item
        for item in items
        if isinstance(item, dict) and item.get("asin")
    }


def _keyword_value(item: dict[str, Any], *names: str) -> Any:
    for name in names:
        value = item.get(name)
        if value not in (None, ""):
            return value
    return None


async def keyword_order_lookup(
    asin: str,
    *,
    marketplace: str = "US",
    month: str | None = None,
    size: int = 200,
) -> list[dict[str, Any]]:
    """Reverse-search an ASIN's keywords through SellerSprite OpenAPI."""
    cleaned_asin = str(asin or "").strip().upper()
    if not cleaned_asin:
        return []
    # SellerSprite expects YYYYMM. Use the latest completed month because the
    # current month can be incomplete or unavailable early in the month.
    latest_completed_month = (date.today().replace(day=1) - timedelta(days=1)).strftime("%Y%m")
    request = {
        "asins": [cleaned_asin],
        "marketplace": (marketplace or "US").strip().upper(),
        "reverseType": "M",
        "date": month or latest_completed_month,
        "page": 1,
        "size": min(max(size, 1), 500),
        "order": {"field": "searchRank", "desc": False},
    }
    data = await _call_tool("keyword_order", request)
    raw_items = data.get("items")
    if not isinstance(raw_items, list):
        return []

    keywords: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        keyword = str(_keyword_value(item, "keyword", "searchTerm", "search_term", "term", "word") or "").strip()
        normalized = " ".join(keyword.lower().split())
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        keywords.append(
            {
                "keyword": keyword,
                "search_volume": _keyword_value(item, "searchVolume", "search_volume", "monthlySearches", "monthlyVolume", "monthly_volume", "volume"),
                "monthly_volume": _keyword_value(item, "monthlyVolume", "monthly_volume", "monthlySearches", "searchVolume", "search_volume", "volume"),
                "position": _keyword_value(item, "position", "organicRank", "organic_rank", "rank", "searchRank", "search_rank"),
                "source": "sellersprite_openapi",
            }
        )
    logger.info("[SellerSprite] OpenAPI reverse lookup completed: ASIN=%s, keywords=%s", cleaned_asin, len(keywords))
    return keywords
