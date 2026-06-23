from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.aplus_publish.status import STATUS_AUTH_REQUIRED, STATUS_READY_TO_UPLOAD, STATUS_SYNCING_LISTING, STATUS_WAITING_LISTING, is_protected_status
from app.models import CatalogProduct, Product
from app.services.aplus_publish_state import set_aplus_publish_status
from app.services.asin_match_policy import (
    ASIN_MATCH_SOURCE_MISSING_SELLER_SKU,
    ASIN_MATCH_SOURCE_PRODUCT_SELLER_SKU_MIRROR,
    ASIN_MATCH_SOURCE_SELLER_SKU,
    AsinMatchDecision,
    LingxingListingRow,
    decide_asin_match,
    decision_to_json,
    json_dumps,
    seller_sku_candidate,
)
from app.services.lingxing_listing_client import (
    LingxingListingClient,
    LingxingListingClientError,
    LingxingListingQuery,
    LingxingListingQueryResult,
)
from app.task_runtime.events import emit_event, update_step_progress
from app.task_runtime.json_utils import json_loads
from app.task_runtime.registry import TaskContext, register_worker


ListingClientFactory = Callable[[], LingxingListingClient]
listing_client_factory: ListingClientFactory = LingxingListingClient


def _payload(ctx: TaskContext) -> dict[str, Any]:
    value = json_loads(ctx.step.payload_json, {})
    return value if isinstance(value, dict) else {}


async def _load_catalog(ctx: TaskContext, catalog_product_id: int) -> CatalogProduct:
    result = await ctx.db.execute(
        select(CatalogProduct)
        .where(CatalogProduct.id == catalog_product_id)
        .options(selectinload(CatalogProduct.source_product).selectinload(Product.data))
    )
    catalog = result.scalar_one_or_none()
    if not catalog:
        raise ValueError(f"CatalogProduct not found: {catalog_product_id}")
    return catalog


async def _set_aplus_status_if_unprotected(ctx: TaskContext, catalog: CatalogProduct, status: str, error: str | None = None) -> None:
    if is_protected_status(catalog.aplus_upload_status):
        return
    await set_aplus_publish_status(
        ctx.db,
        catalog_product_id=catalog.id,
        status=status,
        error=error,
    )


def _decision_payload(decision: AsinMatchDecision) -> dict[str, Any]:
    return {
        "matched": decision.matched,
        "sync_status": decision.sync_status,
        "match_source": decision.match_source,
        "asin": decision.asin,
        "amazon_product_status": decision.amazon_product_status,
        "error": decision.error,
        "evidence": decision.evidence,
    }


async def _apply_decision(ctx: TaskContext, catalog: CatalogProduct, decision: AsinMatchDecision) -> None:
    now = datetime.now()
    product = catalog.source_product
    catalog.asin_sync_status = decision.sync_status
    catalog.asin_sync_error = decision.error
    catalog.asin_match_source = decision.match_source
    catalog.asin_match_evidence_json = decision_to_json(decision)
    catalog.asin_synced_at = now
    catalog.updated_at = now
    if decision.matched and decision.asin:
        catalog.amazon_asin = decision.asin
        catalog.amazon_product_status = decision.amazon_product_status
        catalog.amazon_product_status_synced_at = now
        catalog.amazon_product_status_error = None if decision.amazon_product_status else "领星 Listing 接口未返回亚马逊商品状态"
    elif decision.error:
        catalog.amazon_product_status_synced_at = now
        catalog.amazon_product_status_error = decision.error

    if product:
        product.asin_sync_status = catalog.asin_sync_status
        product.asin_sync_error = catalog.asin_sync_error
        product.asin_match_source = catalog.asin_match_source
        product.asin_match_evidence_json = catalog.asin_match_evidence_json
        product.asin_synced_at = catalog.asin_synced_at
        product.updated_at = now
        if decision.matched and decision.asin:
            product.amazon_asin = decision.asin
            product.amazon_product_status = decision.amazon_product_status
            product.amazon_product_status_synced_at = now
            product.amazon_product_status_error = catalog.amazon_product_status_error
        elif decision.error:
            product.amazon_product_status_synced_at = now
            product.amazon_product_status_error = decision.error

    next_status = STATUS_READY_TO_UPLOAD if decision.matched else STATUS_WAITING_LISTING
    await _set_aplus_status_if_unprotected(ctx, catalog, next_status, decision.error)
    await ctx.db.flush()


async def _missing_seller_sku_decision(catalog: CatalogProduct, *, store_id: str | None, site: str | None) -> AsinMatchDecision:
    return decide_asin_match(
        catalog=catalog,
        rows=[],
        expected_store_id=store_id,
        expected_site=site,
        auxiliary_rows=[],
    )


async def lingxing_listing_sync_product(ctx: TaskContext) -> dict[str, Any]:
    payload = _payload(ctx)
    catalog_product_id = int(payload.get("catalog_product_id") or 0)
    if not catalog_product_id:
        raise ValueError("catalog_product_id is required")
    store_name = str(payload.get("store_name") or "").strip() or None
    store_id = str(payload.get("store_id") or "").strip() or None
    site = str(payload.get("site") or "").strip() or None
    catalog = await _load_catalog(ctx, catalog_product_id)
    product = catalog.source_product
    candidate = seller_sku_candidate(catalog)
    if candidate.value and candidate.source == ASIN_MATCH_SOURCE_PRODUCT_SELLER_SKU_MIRROR and not catalog.amazon_seller_sku:
        catalog.amazon_seller_sku = candidate.value
        catalog.updated_at = datetime.now()
        await ctx.db.flush()
    elif candidate.value and candidate.source == ASIN_MATCH_SOURCE_SELLER_SKU and product and not product.amazon_seller_sku:
        product.amazon_seller_sku = candidate.value
        product.updated_at = datetime.now()
        await ctx.db.flush()
    await _set_aplus_status_if_unprotected(ctx, catalog, STATUS_SYNCING_LISTING)

    if not candidate.value:
        decision = await _missing_seller_sku_decision(catalog, store_id=store_id, site=site)
        await _apply_decision(ctx, catalog, decision)
        await update_step_progress(
            ctx.db,
            ctx.step,
            current=1,
            total=1,
            message="缺少 seller SKU/MSKU，已进入等待 Listing 对齐",
            data={"match_source": ASIN_MATCH_SOURCE_MISSING_SELLER_SKU},
        )
        return _decision_payload(decision)

    auxiliary_upc = catalog.upc or (product.upc if product else None)
    await emit_event(
        ctx.db,
        step=ctx.step,
        event_type="external_call",
        message="查询领星 Listing（seller SKU/MSKU exact）",
        data={
            "endpoint_family": "lingxing_listing",
            "search_field": "msku",
            "seller_sku": candidate.value,
            "store_id": store_id,
            "site": site,
            "has_auxiliary_upc": bool(auxiliary_upc),
        },
    )
    await ctx.db.commit()

    try:
        query_result = await listing_client_factory().fetch_listing_rows(
            LingxingListingQuery(
                seller_sku=candidate.value,
                store_name=store_name,
                store_id=store_id,
                site=site,
                auxiliary_upc=auxiliary_upc,
            )
        )
    except LingxingListingClientError as exc:
        catalog.asin_sync_status = "failed"
        catalog.asin_sync_error = str(exc)
        catalog.asin_match_source = "auth_required" if exc.auth_required else "lingxing_listing_client_error"
        catalog.asin_match_evidence_json = json_dumps({"reason": exc.code, "message": str(exc)})
        catalog.asin_synced_at = datetime.now()
        if product:
            product.asin_sync_status = catalog.asin_sync_status
            product.asin_sync_error = catalog.asin_sync_error
            product.asin_match_source = catalog.asin_match_source
            product.asin_match_evidence_json = catalog.asin_match_evidence_json
            product.asin_synced_at = catalog.asin_synced_at
        if exc.auth_required:
            await _set_aplus_status_if_unprotected(ctx, catalog, STATUS_AUTH_REQUIRED, str(exc))
        else:
            await _set_aplus_status_if_unprotected(ctx, catalog, STATUS_WAITING_LISTING, str(exc))
        await ctx.db.commit()
        raise

    rows = query_result.rows
    auxiliary_rows = query_result.auxiliary_rows
    await emit_event(
        ctx.db,
        step=ctx.step,
        event_type="external_result",
        message="领星 Listing 查询返回",
        data={
            "endpoint_family": "lingxing_listing",
            "seller_sku": candidate.value,
            "store_id": store_id,
            "site": site,
            "row_count": len(rows),
            "auxiliary_upc_row_count": len(auxiliary_rows),
            "client_evidence": query_result.evidence,
        },
    )
    decision = decide_asin_match(
        catalog=catalog,
        rows=rows,
        expected_store_id=store_id,
        expected_site=site,
        auxiliary_upc=auxiliary_upc,
        auxiliary_rows=auxiliary_rows,
    )
    await _apply_decision(ctx, catalog, decision)
    await update_step_progress(
        ctx.db,
        ctx.step,
        current=1,
        total=1,
        message="领星 Listing / ASIN 对齐完成" if decision.matched else f"领星 Listing / ASIN 未对齐：{decision.error}",
        data={
            "matched": decision.matched,
            "sync_status": decision.sync_status,
            "match_source": decision.match_source,
        },
    )
    return _decision_payload(decision)


def register_lingxing_listing_sync_workers() -> None:
    register_worker("lingxing_listing_sync_product", lingxing_listing_sync_product)
