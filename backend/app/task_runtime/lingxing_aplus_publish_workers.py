from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.aplus_publish.status import (
    STATUS_AUTH_REQUIRED,
    STATUS_DRAFT_SAVED,
    STATUS_FAILED,
    STATUS_READY_TO_UPLOAD,
    STATUS_UPLOADING,
)
from app.models import AplusUploadBatch, AplusUploadItem, CatalogProduct, Product
from app.services.aplus_publish_state import set_aplus_publish_status, update_aplus_publish_item_evidence
from app.services.asin_match_policy import seller_sku_candidate
from app.services.lingxing_aplus_publish_client import (
    LingxingAplusDraftSaveClient,
    LingxingAplusDraftSaveClientError,
    LingxingAplusDraftSaveRequest,
    LingxingAplusDraftSaveResult,
)
from app.services.lingxing_aplus_publish_policy import (
    build_aplus_content_fingerprint,
    collect_aplus_publish_assets,
    evaluate_aplus_publish_prerequisites,
)
from app.task_runtime.events import emit_event, update_step_progress
from app.task_runtime.json_utils import json_dumps, json_loads
from app.task_runtime.registry import TaskContext, register_worker


DraftSaveClientFactory = Callable[[], LingxingAplusDraftSaveClient]
draft_save_client_factory: DraftSaveClientFactory = LingxingAplusDraftSaveClient


def _payload(ctx: TaskContext) -> dict[str, Any]:
    value = json_loads(ctx.step.payload_json, {})
    return value if isinstance(value, dict) else {}


def _clean(value: str | int | None) -> str | None:
    text = str(value or "").strip()
    return text or None


async def _load_catalog(ctx: TaskContext, catalog_product_id: int) -> CatalogProduct:
    result = await ctx.db.execute(
        select(CatalogProduct)
        .where(CatalogProduct.id == catalog_product_id)
        .options(
            selectinload(CatalogProduct.source_product).selectinload(Product.data),
            selectinload(CatalogProduct.source_product).selectinload(Product.aplus),
        )
    )
    catalog = result.scalar_one_or_none()
    if not catalog:
        raise ValueError(f"CatalogProduct not found: {catalog_product_id}")
    return catalog


async def _latest_draft_item(ctx: TaskContext, catalog: CatalogProduct) -> AplusUploadItem | None:
    product_aplus_id = getattr(getattr(catalog.source_product, "aplus", None), "id", None)
    query = (
        select(AplusUploadItem)
        .where(AplusUploadItem.catalog_product_id == catalog.id)
        .where(AplusUploadItem.lingxing_aplus_id_hash.is_not(None))
        .order_by(AplusUploadItem.id.desc())
        .limit(1)
    )
    if product_aplus_id:
        query = query.where(AplusUploadItem.product_aplus_id == product_aplus_id)
    return (await ctx.db.execute(query)).scalar_one_or_none()


async def _finish_prereq_not_met(ctx: TaskContext, catalog: CatalogProduct, decision) -> dict[str, Any]:
    if not decision.protected:
        await set_aplus_publish_status(
            ctx.db,
            catalog_product_id=catalog.id,
            status=decision.status,
            error=decision.message,
        )
    await emit_event(
        ctx.db,
        step=ctx.step,
        event_type="policy",
        message=decision.message or decision.reason_code or "A+ 发布前置不满足",
        data={
            "status": decision.status,
            "reason_code": decision.reason_code,
            "protected": decision.protected,
            "evidence": decision.evidence,
        },
    )
    await update_step_progress(
        ctx.db,
        ctx.step,
        current=1,
        total=1,
        message=decision.message,
        data={"status": decision.status, "reason_code": decision.reason_code},
    )
    return {
        "status": decision.status,
        "reason_code": decision.reason_code,
        "message": decision.message,
        "protected": decision.protected,
    }


async def _record_success(
    ctx: TaskContext,
    *,
    catalog: CatalogProduct,
    request: LingxingAplusDraftSaveRequest,
    result: LingxingAplusDraftSaveResult,
) -> dict[str, Any]:
    record_key = result.id_hash or result.record_key
    if not record_key:
        raise LingxingAplusDraftSaveClientError("missing_record_key", "领星保存草稿成功但未返回 idHash 或等价 record key")

    now = datetime.now()
    batch = AplusUploadBatch(
        store=request.store_id,
        submit_for_approval=0,
        status="completed",
        total_count=1,
        success_count=1,
        failed_count=0,
        skipped_count=0,
        created_at=now,
        started_at=now,
        finished_at=now,
    )
    ctx.db.add(batch)
    await ctx.db.flush()
    item = AplusUploadItem(
        batch_id=batch.id,
        catalog_product_id=catalog.id,
        product_id=request.product_id,
        product_aplus_id=request.product_aplus_id,
        amazon_asin=request.asin,
        item_code=request.seller_sku,
        document_name=request.document_name,
        status="success",
        uploaded_images=json.dumps(result.uploaded_images, ensure_ascii=False, default=str),
        lingxing_response=json.dumps(result.evidence, ensure_ascii=False, default=str),
        started_at=now,
        finished_at=now,
    )
    ctx.db.add(item)
    await ctx.db.flush()
    publish_evidence = {
        **(result.evidence or {}),
        "idHash": record_key,
        "lingxing_status_text": result.status_text,
        "amazon_draft_visibility": "unconfirmed",
        "asin": request.asin,
        "seller_sku": request.seller_sku,
        "store_id": request.store_id,
        "site": request.site,
        "submitFlag": 0,
        "source_task_run_id": ctx.run.id,
        "source_task_step_id": ctx.step.id,
    }
    await update_aplus_publish_item_evidence(
        ctx.db,
        item_id=item.id,
        lingxing_aplus_id_hash=record_key,
        lingxing_status_text=result.status_text or "草稿",
        amazon_draft_visibility="unconfirmed",
        publish_evidence=publish_evidence,
        source_task_run_id=ctx.run.id,
        source_task_step_id=ctx.step.id,
        product_aplus_id=request.product_aplus_id,
        aplus_content_fingerprint=request.content_fingerprint,
        seller_sku_used=request.seller_sku,
        store_id=request.store_id,
        site=request.site,
    )
    await set_aplus_publish_status(
        ctx.db,
        catalog_product_id=catalog.id,
        status=STATUS_DRAFT_SAVED,
        uploaded_at=now,
    )
    await emit_event(
        ctx.db,
        step=ctx.step,
        event_type="external_result",
        message="领星 A+ 草稿保存成功",
        data={
            "endpoint_family": "lingxing_aplus_add",
            "idHash": record_key,
            "status": STATUS_DRAFT_SAVED,
            "amazon_draft_visibility": "unconfirmed",
            "submitFlag": 0,
            "store_id": request.store_id,
            "site": request.site,
            "seller_sku": request.seller_sku,
        },
    )
    await update_step_progress(
        ctx.db,
        ctx.step,
        current=1,
        total=1,
        message="领星 A+ 草稿已保存；Amazon 草稿可见性未确认",
        data={"status": STATUS_DRAFT_SAVED, "amazon_draft_visibility": "unconfirmed", "idHash": record_key},
    )
    return {
        "status": STATUS_DRAFT_SAVED,
        "lingxing_aplus_id_hash": record_key,
        "amazon_draft_visibility": "unconfirmed",
        "source_task_run_id": ctx.run.id,
        "source_task_step_id": ctx.step.id,
    }


async def lingxing_aplus_publish_product(ctx: TaskContext) -> dict[str, Any]:
    payload = _payload(ctx)
    catalog_product_id = int(payload.get("catalog_product_id") or 0)
    if not catalog_product_id:
        raise ValueError("catalog_product_id is required")
    store_id = _clean(payload.get("store_id"))
    site = _clean(payload.get("site"))
    catalog = await _load_catalog(ctx, catalog_product_id)
    product = catalog.source_product
    existing = await _latest_draft_item(ctx, catalog)
    if existing and existing.lingxing_aplus_id_hash and (catalog.aplus_upload_status or "") == STATUS_DRAFT_SAVED:
        await emit_event(
            ctx.db,
            step=ctx.step,
            event_type="policy",
            message="已有 draft_saved/idHash，停止重复保存领星草稿",
            data={"status": STATUS_DRAFT_SAVED, "idHash": existing.lingxing_aplus_id_hash},
        )
        await update_step_progress(
            ctx.db,
            ctx.step,
            current=1,
            total=1,
            message="已有领星 A+ 草稿，未创建第二个草稿",
            data={"status": STATUS_DRAFT_SAVED, "idHash": existing.lingxing_aplus_id_hash},
        )
        return {
            "status": STATUS_DRAFT_SAVED,
            "reason_code": "existing_draft_saved",
            "lingxing_aplus_id_hash": existing.lingxing_aplus_id_hash,
            "amazon_draft_visibility": existing.amazon_draft_visibility,
        }

    decision = evaluate_aplus_publish_prerequisites(catalog, store_id=store_id, site=site)
    if not decision.ok:
        return await _finish_prereq_not_met(ctx, catalog, decision)
    assets_result = collect_aplus_publish_assets(product)
    if not assets_result.ok:
        await set_aplus_publish_status(
            ctx.db,
            catalog_product_id=catalog.id,
            status=STATUS_FAILED,
            error=assets_result.message,
        )
        await emit_event(
            ctx.db,
            step=ctx.step,
            event_type="policy",
            message=assets_result.message,
            data={"status": STATUS_FAILED, "reason_code": assets_result.reason_code, "evidence": assets_result.evidence},
        )
        await update_step_progress(
            ctx.db,
            ctx.step,
            current=1,
            total=1,
            message=assets_result.message,
            data={"status": STATUS_FAILED, "reason_code": assets_result.reason_code},
        )
        return {"status": STATUS_FAILED, "reason_code": assets_result.reason_code, "message": assets_result.message}

    seller_sku = seller_sku_candidate(catalog).value
    asin = _clean(catalog.amazon_asin) or _clean(product.amazon_asin)
    product_aplus_id = int(getattr(product.aplus, "id", None) or payload.get("product_aplus_id") or 0)
    fingerprint = build_aplus_content_fingerprint(product.aplus, assets_result.assets)
    document_name = f"{asin}_{seller_sku}_{product.id}"
    request = LingxingAplusDraftSaveRequest(
        asin=asin,
        seller_sku=seller_sku,
        document_name=document_name[:200],
        store_id=store_id,
        site=site,
        assets=assets_result.assets,
        product_id=product.id,
        product_aplus_id=product_aplus_id,
        content_fingerprint=fingerprint,
    )
    await set_aplus_publish_status(ctx.db, catalog_product_id=catalog.id, status=STATUS_READY_TO_UPLOAD)
    await emit_event(
        ctx.db,
        step=ctx.step,
        event_type="external_call",
        message="准备调用领星 A+ 保存草稿",
        data={
            "endpoint_family": "lingxing_aplus_add",
            "asin": asin,
            "seller_sku": seller_sku,
            "store_id": store_id,
            "site": site,
            "image_count": len(assets_result.assets),
            "submitFlag": 0,
        },
    )
    await set_aplus_publish_status(ctx.db, catalog_product_id=catalog.id, status=STATUS_UPLOADING)
    await ctx.db.commit()

    try:
        result = await draft_save_client_factory().save_draft(request)
    except LingxingAplusDraftSaveClientError as exc:
        status = STATUS_AUTH_REQUIRED if exc.auth_required else STATUS_FAILED
        failure_payload = {"status": status, "reason_code": exc.code, "message": str(exc)}
        await set_aplus_publish_status(
            ctx.db,
            catalog_product_id=catalog.id,
            status=status,
            error=str(exc),
        )
        await emit_event(
            ctx.db,
            step=ctx.step,
            event_type="external_result",
            message=str(exc),
            data={
                "endpoint_family": "lingxing_aplus_add",
                "status": status,
                "reason_code": exc.code,
                "auth_required": exc.auth_required,
            },
        )
        await update_step_progress(
            ctx.db,
            ctx.step,
            current=1,
            total=1,
            message=str(exc),
            data={"status": status, "reason_code": exc.code},
        )
        ctx.step.result_json = json_dumps(failure_payload)
        await ctx.db.commit()
        raise

    return await _record_success(ctx, catalog=catalog, request=request, result=result)


def register_lingxing_aplus_publish_workers() -> None:
    register_worker("lingxing_aplus_publish_product", lingxing_aplus_publish_product)
