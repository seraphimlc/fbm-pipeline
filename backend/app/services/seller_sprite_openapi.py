import json
import logging
from typing import Any

import httpx

from app.config import settings


logger = logging.getLogger(__name__)

MCP_URL = "https://mcp.sellersprite.com/mcp"


class SellerSpriteOpenApiError(RuntimeError):
    pass


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
    secret = settings.SELLERSPRITE_OPENAPI_SECRET_KEY.strip()
    if not secret:
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

    payload = {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {
            "name": "competitor_lookup",
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

    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(MCP_URL, json=payload, headers=headers)
    response.raise_for_status()
    text = response.text.strip()
    if text.startswith("data:"):
        text = "\n".join(line[len("data:"):].strip() for line in text.splitlines() if line.startswith("data:"))

    rpc = json.loads(text)
    if rpc.get("error"):
        err = rpc["error"]
        raise SellerSpriteOpenApiError(f"{err.get('code')}: {err.get('message')}")
    content = (rpc.get("result") or {}).get("content") or []
    if not content:
        return {}
    inner_text = content[0].get("text") or ""
    inner = json.loads(inner_text)
    if inner.get("code") != "OK":
        raise SellerSpriteOpenApiError(f"{inner.get('code')}: {inner.get('message')}")

    data = inner.get("data") or {}
    items = data.get("items") if isinstance(data, dict) else []
    if not isinstance(items, list):
        return {}
    return {
        str(item.get("asin")).strip().upper(): item
        for item in items
        if isinstance(item, dict) and item.get("asin")
    }
