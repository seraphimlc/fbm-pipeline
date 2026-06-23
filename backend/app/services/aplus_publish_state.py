"""Single writer for Lingxing A+ publish state and evidence.

This module is deliberately DB-only. It must not import Chrome helpers, HTTP
clients, task planners, task workers, or product workflow writers. Task runs own
execution lifecycle; this service only projects external publish business facts
to CatalogProduct/Product mirrors and AplusUploadItem evidence fields.

Task runs own execution lifecycle; AplusUploadItem owns external evidence.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.aplus_publish.status import normalize_aplus_publish_status
from app.models import AplusUploadItem, CatalogProduct, Product


def _json_dumps(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, default=str)


async def _load_catalog_for_publish_state(
    db: AsyncSession,
    *,
    catalog_product_id: int | None = None,
    product_id: int | None = None,
) -> CatalogProduct:
    query = select(CatalogProduct).options(selectinload(CatalogProduct.source_product))
    if catalog_product_id:
        query = query.where(CatalogProduct.id == int(catalog_product_id))
    elif product_id:
        query = query.where(CatalogProduct.source_product_id == int(product_id))
    else:
        raise ValueError("catalog_product_id or product_id is required")

    catalog = (await db.execute(query)).scalar_one_or_none()
    if not catalog:
        raise ValueError("CatalogProduct is required as the primary Lingxing A+ publish fact")
    return catalog


async def set_aplus_publish_status(
    db: AsyncSession,
    *,
    status: str,
    catalog_product_id: int | None = None,
    product_id: int | None = None,
    error: str | None = None,
    uploaded_at: datetime | None = None,
    now: datetime | None = None,
) -> CatalogProduct:
    """Write Product/Catalog A+ publish status with CatalogProduct as primary fact.

    The writer rejects unknown Product/Catalog status keys. Legacy values may be
    read and normalized by the registry, but this writer should only produce
    registered states.
    """

    normalized_status = normalize_aplus_publish_status(status, allow_legacy=False)
    timestamp = now or datetime.now()
    catalog = await _load_catalog_for_publish_state(
        db,
        catalog_product_id=catalog_product_id,
        product_id=product_id,
    )
    product: Product | None = catalog.source_product

    catalog.aplus_upload_status = normalized_status
    catalog.aplus_upload_error = error
    catalog.updated_at = timestamp
    if uploaded_at is not None:
        catalog.aplus_uploaded_at = uploaded_at

    if product:
        product.aplus_upload_status = normalized_status
        product.aplus_upload_error = error
        product.updated_at = timestamp
        if uploaded_at is not None:
            product.aplus_uploaded_at = uploaded_at

    await db.flush()
    return catalog


async def update_aplus_publish_item_evidence(
    db: AsyncSession,
    *,
    item_id: int,
    lingxing_aplus_id_hash: str | None = None,
    lingxing_status_text: str | None = None,
    amazon_draft_visibility: str | None = None,
    draft_visible_at: datetime | None = None,
    submitted_at: datetime | None = None,
    publish_evidence: dict[str, Any] | str | None = None,
    source_task_run_id: int | None = None,
    source_task_step_id: int | None = None,
    product_aplus_id: int | None = None,
    aplus_content_fingerprint: str | None = None,
    seller_sku_used: str | None = None,
    store_id: str | None = None,
    site: str | None = None,
) -> AplusUploadItem:
    """Update external evidence fields on AplusUploadItem.

    AplusUploadItem is the external publish evidence table, not the execution
    source of truth. Do not infer task success from these fields; use task_runs
    for execution lifecycle.
    """

    item = await db.get(AplusUploadItem, int(item_id))
    if not item:
        raise ValueError(f"AplusUploadItem not found: {item_id}")

    if lingxing_aplus_id_hash is not None:
        item.lingxing_aplus_id_hash = lingxing_aplus_id_hash
    if lingxing_status_text is not None:
        item.lingxing_status_text = lingxing_status_text
    if amazon_draft_visibility is not None:
        item.amazon_draft_visibility = amazon_draft_visibility
    if draft_visible_at is not None:
        item.draft_visible_at = draft_visible_at
    if submitted_at is not None:
        item.submitted_at = submitted_at
    if publish_evidence is not None:
        item.publish_evidence_json = _json_dumps(publish_evidence)
    if source_task_run_id is not None:
        item.source_task_run_id = source_task_run_id
    if source_task_step_id is not None:
        item.source_task_step_id = source_task_step_id
    if product_aplus_id is not None:
        item.product_aplus_id = product_aplus_id
    if aplus_content_fingerprint is not None:
        item.aplus_content_fingerprint = aplus_content_fingerprint
    if seller_sku_used is not None:
        item.seller_sku_used = seller_sku_used
    if store_id is not None:
        item.store_id = store_id
    if site is not None:
        item.site = site

    await db.flush()
    return item
