from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

from app.models import CatalogProduct, Product


ASIN_RE = re.compile(r"\bB[A-Z0-9]{9}\b")

ASIN_MATCH_SOURCE_SELLER_SKU = "seller_sku_exact"
ASIN_MATCH_SOURCE_PRODUCT_SELLER_SKU_MIRROR = "product_seller_sku_mirror"
ASIN_MATCH_SOURCE_COMPAT_ITEM_CODE = "compat_item_code_exact"
ASIN_MATCH_SOURCE_MISSING_SELLER_SKU = "missing_seller_sku"
ASIN_MATCH_SOURCE_NOT_FOUND = "seller_sku_not_found"
ASIN_MATCH_SOURCE_MULTIPLE = "seller_sku_multiple"
ASIN_MATCH_SOURCE_WRONG_MARKET = "seller_sku_wrong_store_or_site"
ASIN_MATCH_SOURCE_NOT_SELLABLE = "seller_sku_not_sellable"
ASIN_MATCH_SOURCE_ASIN_CONFLICT = "seller_sku_asin_conflict"

SYNC_STATUS_SYNCED = "synced"
SYNC_STATUS_WAITING_LISTING = "waiting_listing"
SYNC_STATUS_NOT_FOUND = "not_found"
SYNC_STATUS_MULTIPLE_FOUND = "multiple_found"
SYNC_STATUS_ASIN_CONFLICT = "asin_conflict"
SYNC_STATUS_NOT_SELLABLE = "not_sellable"


def normalize_match_code(value: str | None) -> str:
    return re.sub(r"\s+", "", value or "").upper()


def normalize_site(value: str | None) -> str:
    return str(value or "").strip().upper()


def normalize_store_id(value: str | int | None) -> str:
    return str(value or "").strip()


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


@dataclass(frozen=True)
class SellerSkuCandidate:
    value: str | None
    source: str
    trusted: bool
    reason: str | None = None


@dataclass(frozen=True)
class LingxingListingRow:
    msku: str | None = None
    asin: str | None = None
    store_id: str | None = None
    store_name: str | None = None
    site: str | None = None
    status_text: str | None = None
    amazon_product_status: str | None = None
    is_deleted: bool = False
    is_sellable: bool | None = None
    raw_summary: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> "LingxingListingRow":
        return cls(
            msku=_first_str(value, "msku", "seller_sku", "sellerSku", "sku"),
            asin=_first_str(value, "asin", "ASIN"),
            store_id=_first_str(value, "store_id", "sid", "sids", "storeId"),
            store_name=_first_str(value, "store_name", "storeName", "store"),
            site=_first_str(value, "site", "marketplace", "market", "country"),
            status_text=_first_str(value, "status_text", "statusText", "status_name", "statusName", "listing_status", "sale_status"),
            amazon_product_status=_first_str(value, "amazon_product_status", "amazonProductStatus", "listing_status", "status_text"),
            is_deleted=_truthy(value.get("is_deleted", value.get("is_delete"))),
            is_sellable=_sellable(value),
            raw_summary=_sanitize_row_summary(value),
        )

    def summary(self) -> dict[str, Any]:
        return {
            "msku": self.msku,
            "asin": self.asin,
            "store_id": self.store_id,
            "store_name": self.store_name,
            "site": self.site,
            "status_text": self.status_text,
            "amazon_product_status": self.amazon_product_status,
            "is_deleted": self.is_deleted,
            "is_sellable": self.is_sellable,
            "raw_summary": self.raw_summary,
        }


@dataclass(frozen=True)
class AsinMatchDecision:
    matched: bool
    sync_status: str
    match_source: str
    asin: str | None = None
    amazon_product_status: str | None = None
    error: str | None = None
    evidence: dict[str, Any] = field(default_factory=dict)


def _first_str(value: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        item = value.get(key)
        if item not in (None, ""):
            return str(item).strip()
    return None


def _truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "deleted", "已删除"}


def _sellable(value: dict[str, Any]) -> bool | None:
    for key in ("is_sellable", "sellable", "isSellable"):
        if key in value:
            return str(value.get(key)).strip().lower() in {"1", "true", "yes", "y"}
    status_text = _first_str(value, "status_text", "statusText", "status_name", "listing_status", "sale_status")
    if status_text and status_text.strip().lower() in {"停售", "已停售", "inactive", "not sellable", "unsellable", "deleted", "已删除"}:
        return False
    numeric_status = value.get("status")
    if str(numeric_status).strip() == "0":
        return False
    return None


def _sanitize_row_summary(value: dict[str, Any]) -> dict[str, Any]:
    allowed = (
        "id",
        "id_hash",
        "idHash",
        "msku",
        "asin",
        "sid",
        "store_id",
        "store_name",
        "site",
        "status",
        "status_text",
        "sale_status",
    )
    return {key: value.get(key) for key in allowed if key in value}


def seller_sku_candidate(catalog: CatalogProduct) -> SellerSkuCandidate:
    product: Product | None = catalog.source_product
    primary = str(catalog.amazon_seller_sku or "").strip()
    product_mirror = str((product.amazon_seller_sku if product else None) or "").strip()
    if primary and product_mirror and normalize_match_code(primary) != normalize_match_code(product_mirror):
        return SellerSkuCandidate(
            None,
            ASIN_MATCH_SOURCE_MISSING_SELLER_SKU,
            False,
            "Product/Catalog amazon_seller_sku 不一致，不能选择任一镜像作为 A+ 发布前置主匹配键",
        )
    if primary:
        return SellerSkuCandidate(primary, ASIN_MATCH_SOURCE_SELLER_SKU, True)
    if product_mirror:
        return SellerSkuCandidate(
            product_mirror,
            ASIN_MATCH_SOURCE_PRODUCT_SELLER_SKU_MIRROR,
            True,
            "CatalogProduct.amazon_seller_sku 为空，使用 Product.amazon_seller_sku 镜像修复同一 seller SKU 事实",
        )
    return SellerSkuCandidate(None, ASIN_MATCH_SOURCE_MISSING_SELLER_SKU, False, "缺少已持久化的 Amazon seller SKU/MSKU")


def _normalize_asin(value: str | None) -> str | None:
    normalized = str(value or "").strip().upper()
    return normalized or None


def local_asin_values(catalog: CatalogProduct) -> dict[str, str]:
    product: Product | None = catalog.source_product
    values: dict[str, str] = {}
    catalog_asin = _normalize_asin(catalog.amazon_asin)
    product_asin = _normalize_asin(product.amazon_asin if product else None)
    if catalog_asin:
        values["catalog"] = catalog_asin
    if product_asin:
        values["product"] = product_asin
    return values


def _local_asin_conflict_decision(
    *,
    evidence: dict[str, Any],
    local_asins: dict[str, str],
    lingxing_asin: str | None = None,
    amazon_product_status: str | None = None,
) -> AsinMatchDecision | None:
    distinct_local_asins = sorted(set(local_asins.values()))
    if len(distinct_local_asins) > 1:
        return AsinMatchDecision(
            False,
            SYNC_STATUS_ASIN_CONFLICT,
            ASIN_MATCH_SOURCE_ASIN_CONFLICT,
            asin=lingxing_asin,
            amazon_product_status=amazon_product_status,
            error="Product 与 Catalog 已有不同本地 ASIN，必须人工处理后才能同步领星 Listing",
            evidence={
                **evidence,
                "reason": "local_product_catalog_asin_conflict",
                "local_asins": local_asins,
                "lingxing_asin": lingxing_asin,
            },
        )
    if lingxing_asin:
        for owner, local_asin in local_asins.items():
            if local_asin != lingxing_asin:
                return AsinMatchDecision(
                    False,
                    SYNC_STATUS_ASIN_CONFLICT,
                    ASIN_MATCH_SOURCE_ASIN_CONFLICT,
                    asin=lingxing_asin,
                    amazon_product_status=amazon_product_status,
                    error=f"{owner} 本地 ASIN {local_asin} 与领星 seller SKU/MSKU 返回 ASIN {lingxing_asin} 冲突",
                    evidence={
                        **evidence,
                        "reason": "asin_conflict",
                        "local_asins": local_asins,
                        "conflict_owner": owner,
                        "existing_asin": local_asin,
                        "lingxing_asin": lingxing_asin,
                    },
                )
    return None


def _market_matches(row: LingxingListingRow, *, expected_store_id: str | None, expected_site: str | None) -> bool:
    if expected_store_id and normalize_store_id(row.store_id) and normalize_store_id(row.store_id) != expected_store_id:
        return False
    if expected_site and normalize_site(row.site) and normalize_site(row.site) != expected_site:
        return False
    return True


def _is_sellable(row: LingxingListingRow) -> bool:
    if row.is_deleted:
        return False
    if row.is_sellable is False:
        return False
    return True


def _base_evidence(
    *,
    seller_sku: SellerSkuCandidate,
    expected_store_id: str | None,
    expected_site: str | None,
    rows: list[LingxingListingRow],
    auxiliary_upc: str | None,
    auxiliary_rows: list[LingxingListingRow],
) -> dict[str, Any]:
    return {
        "matched_at": datetime.now().isoformat(),
        "seller_sku": seller_sku.value,
        "seller_sku_source": seller_sku.source,
        "seller_sku_reason": seller_sku.reason,
        "expected_store_id": expected_store_id,
        "expected_site": expected_site,
        "row_count": len(rows),
        "rows": [row.summary() for row in rows],
        "auxiliary_upc": auxiliary_upc,
        "auxiliary_upc_row_count": len(auxiliary_rows),
        "auxiliary_upc_rows": [row.summary() for row in auxiliary_rows[:5]],
    }


def decide_asin_match(
    *,
    catalog: CatalogProduct,
    rows: list[LingxingListingRow],
    expected_store_id: str | int | None = None,
    expected_site: str | None = None,
    auxiliary_upc: str | None = None,
    auxiliary_rows: list[LingxingListingRow] | None = None,
) -> AsinMatchDecision:
    seller_sku = seller_sku_candidate(catalog)
    expected_store = normalize_store_id(expected_store_id)
    expected_site_value = normalize_site(expected_site)
    auxiliary = auxiliary_rows or []
    evidence = _base_evidence(
        seller_sku=seller_sku,
        expected_store_id=expected_store or None,
        expected_site=expected_site_value or None,
        rows=rows,
        auxiliary_upc=auxiliary_upc,
        auxiliary_rows=auxiliary,
    )
    local_asins = local_asin_values(catalog)
    evidence = {**evidence, "local_asins": local_asins}

    if not seller_sku.value:
        return AsinMatchDecision(
            False,
            SYNC_STATUS_WAITING_LISTING,
            ASIN_MATCH_SOURCE_MISSING_SELLER_SKU,
            error="缺少 Amazon seller SKU/MSKU，不能用 UPC 作为 A+ 发布前置主匹配键",
            evidence={**evidence, "reason": "missing_seller_sku"},
        )

    local_conflict = _local_asin_conflict_decision(evidence=evidence, local_asins=local_asins)
    if local_conflict:
        return local_conflict

    exact_rows = [row for row in rows if normalize_match_code(row.msku) == normalize_match_code(seller_sku.value)]
    if not exact_rows:
        reason = "upc_auxiliary_only" if auxiliary else "seller_sku_not_found"
        return AsinMatchDecision(
            False,
            SYNC_STATUS_NOT_FOUND,
            ASIN_MATCH_SOURCE_NOT_FOUND,
            error="未找到 seller SKU/MSKU 精确匹配的领星 Listing",
            evidence={**evidence, "reason": reason, "exact_row_count": 0},
        )

    market_rows = [row for row in exact_rows if _market_matches(row, expected_store_id=expected_store or None, expected_site=expected_site_value or None)]
    if not market_rows:
        return AsinMatchDecision(
            False,
            SYNC_STATUS_WAITING_LISTING,
            ASIN_MATCH_SOURCE_WRONG_MARKET,
            error="seller SKU/MSKU 命中领星 Listing，但店铺或站点不匹配",
            evidence={**evidence, "reason": "wrong_store_or_site", "exact_row_count": len(exact_rows)},
        )

    sellable_rows = [row for row in market_rows if _is_sellable(row)]
    if not sellable_rows:
        return AsinMatchDecision(
            False,
            SYNC_STATUS_NOT_SELLABLE,
            ASIN_MATCH_SOURCE_NOT_SELLABLE,
            error="seller SKU/MSKU 命中的领星 Listing 不可售或已删除",
            evidence={**evidence, "reason": "not_sellable", "exact_row_count": len(exact_rows), "market_row_count": len(market_rows)},
        )

    if len(sellable_rows) > 1:
        return AsinMatchDecision(
            False,
            SYNC_STATUS_MULTIPLE_FOUND,
            ASIN_MATCH_SOURCE_MULTIPLE,
            error="seller SKU/MSKU 精确匹配到多个可售 Listing，不能自动选择",
            evidence={**evidence, "reason": "multiple_seller_sku_rows", "sellable_row_count": len(sellable_rows)},
        )

    row = sellable_rows[0]
    asin = str(row.asin or "").strip().upper()
    if not asin or not ASIN_RE.fullmatch(asin):
        return AsinMatchDecision(
            False,
            SYNC_STATUS_NOT_FOUND,
            ASIN_MATCH_SOURCE_NOT_FOUND,
            error="seller SKU/MSKU 命中 Listing，但未返回有效 ASIN",
            evidence={**evidence, "reason": "missing_valid_asin"},
        )

    local_conflict = _local_asin_conflict_decision(
        evidence=evidence,
        local_asins=local_asins,
        lingxing_asin=asin,
        amazon_product_status=row.amazon_product_status or row.status_text,
    )
    if local_conflict:
        return local_conflict

    return AsinMatchDecision(
        True,
        SYNC_STATUS_SYNCED,
        seller_sku.source,
        asin=asin,
        amazon_product_status=row.amazon_product_status or row.status_text,
        evidence={**evidence, "reason": "seller_sku_unique_match", "matched_row": row.summary()},
    )


def decision_to_json(decision: AsinMatchDecision) -> str:
    return json_dumps(asdict(decision))
