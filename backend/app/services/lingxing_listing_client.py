from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx

from app.config import settings
from app.services.asin_match_policy import LingxingListingRow
from app.services.asin_sync import LINGXING_LISTING_API_URL, _get_lingxing_listing_auth


class LingxingListingClientError(RuntimeError):
    def __init__(self, code: str, message: str, *, auth_required: bool = False):
        super().__init__(message)
        self.code = code
        self.auth_required = auth_required


def _clean_optional(value: str | int | None) -> str | None:
    cleaned = str(value or "").strip()
    return cleaned or None


@dataclass(frozen=True)
class LingxingListingQuery:
    seller_sku: str
    store_name: str | None = None
    store_id: str | int | None = None
    site: str | None = None
    auxiliary_upc: str | None = None


@dataclass(frozen=True)
class LingxingListingQueryResult:
    rows: list[LingxingListingRow] = field(default_factory=list)
    auxiliary_rows: list[LingxingListingRow] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)


class LingxingListingClient:
    async def fetch_listing_rows(self, query: LingxingListingQuery) -> LingxingListingQueryResult:
        if not settings.LINGXING_LISTING_SYNC_ALLOW_REAL_EXTERNAL_CALLS:
            raise LingxingListingClientError(
                "real_external_calls_disabled",
                "Lingxing Listing sync real external calls are disabled by config",
            )

        store_name = _clean_optional(query.store_name) or _clean_optional(settings.LINGXING_APLUS_STORE_NAME)
        store_id = _clean_optional(query.store_id) or _clean_optional(settings.LINGXING_APLUS_STORE_ID)
        if not store_name or not store_id:
            raise LingxingListingClientError(
                "store_config_required",
                "Lingxing Listing sync requires explicit store_name and store_id when real external calls are enabled",
            )

        auth = await _get_lingxing_listing_auth(store_name)
        if not auth.get("ok"):
            raise LingxingListingClientError(
                "auth_required",
                auth.get("error") or "领星登录态失效，无法读取 Listing",
                auth_required=True,
            )

        rows = await self._query_field(auth["headers"], store_id=store_id, field="msku", value=query.seller_sku)
        auxiliary_rows: list[LingxingListingRow] = []
        if query.auxiliary_upc:
            auxiliary_rows = await self._query_field(auth["headers"], store_id=store_id, field="amz_product_id", value=query.auxiliary_upc)
        return LingxingListingQueryResult(
            rows=rows,
            auxiliary_rows=auxiliary_rows,
            evidence={
                "endpoint_family": "lingxing_listing",
                "search_field": "msku",
                "seller_sku": query.seller_sku,
                "store_id": store_id,
                "site": query.site,
                "row_count": len(rows),
                "auxiliary_upc_row_count": len(auxiliary_rows),
            },
        )

    async def _query_field(self, headers: dict[str, str], *, store_id: str, field: str, value: str) -> list[LingxingListingRow]:
        payload = {
            "sids": store_id,
            "search_field": field,
            "search_value": [value],
            "offset": 0,
            "length": 20,
        }
        try:
            async with httpx.AsyncClient(timeout=20, verify=settings.external_http_verify) as client:
                response = await client.post(LINGXING_LISTING_API_URL, headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()
        except Exception as exc:
            raise LingxingListingClientError(
                "request_failed",
                f"领星 Listing API 查询失败: {type(exc).__name__}: {exc}",
            ) from exc

        if data.get("code") != 1:
            raise LingxingListingClientError("api_failed", data.get("msg") or "领星 Listing API 返回失败")
        raw_rows = ((data.get("data") or {}).get("list") or [])
        return [LingxingListingRow.from_mapping(row) for row in raw_rows if isinstance(row, dict)]
