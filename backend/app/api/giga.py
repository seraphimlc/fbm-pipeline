from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import (
    GigaInventorySyncRequest,
    GigaInventorySyncResponse,
    GigaPriceSyncRequest,
    GigaPriceSyncResponse,
    GigaSyncMissingRequest,
    GigaSyncQueuedResponse,
    GigaSyncRequest,
    GigaSyncResponse,
    PaginatedGigaInventory,
    PaginatedGigaInventoryAlerts,
    PaginatedGigaPriceAlerts,
    PaginatedGigaProductImages,
    PaginatedGigaItems,
    PaginatedGigaGroups,
    PaginatedGigaSkus,
    PaginatedGigaSyncBatches,
)
from app.database import get_db
from app.models import (
    GigaGroup,
    GigaInventory,
    GigaInventoryAlert,
    GigaItem,
    GigaPrice,
    GigaPriceAlert,
    GigaProductImage,
    GigaSku,
    GigaSyncBatch,
)
from app.services.giga_inventory_sync import (
    GIGA_DYNAMIC_SNAPSHOT_CATEGORIES,
    GigaInventorySyncOptions,
    sync_giga_inventory_snapshot,
)
from app.services.giga_openapi import GigaOpenApiError, GigaSyncOptions, sync_giga_products
from app.services.giga_price_sync import GigaPriceSyncOptions, sync_giga_price_snapshot
from app.services.giga_sync_tasks import enqueue_giga_sync
from app.services.giga_product_drafts import upsert_product_drafts_from_giga_batch


router = APIRouter(prefix="/api/giga", tags=["giga"])


@router.post("/sync", response_model=GigaSyncResponse)
async def sync_giga_products_api(body: GigaSyncRequest, db: AsyncSession = Depends(get_db)):
    """从 GIGA Open API 拉取商品、详情、价格、库存并按 batch/site 落库分组。"""
    try:
        result = await sync_giga_products(
            db,
            GigaSyncOptions(
                task_id=body.task_id,
                batch_id=body.batch_id,
                site=body.site,
                data_source_id=body.data_source_id,
                current_category=body.current_category,
                page_size=body.page_size or 200,
                max_pages=body.max_pages,
                skip_existing=body.skip_existing,
            ),
        )
        await upsert_product_drafts_from_giga_batch(
            db,
            batch_id=result.batch_id,
            site=result.site,
            data_source_id=result.data_source_id,
        )
    except GigaOpenApiError as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:
        raise HTTPException(502, f"GIGA 同步失败: {type(exc).__name__}: {exc}")
    return GigaSyncResponse(**result.__dict__)


@router.post("/sync-missing", response_model=GigaSyncResponse)
async def sync_missing_giga_products_api(body: GigaSyncMissingRequest, db: AsyncSession = Depends(get_db)):
    """工作台增量拉取：已入库 SKU 跳过，只补本地缺失的 GIGA 商品。"""
    source_part = f"ds{body.data_source_id}-" if body.data_source_id else ""
    batch_id = body.batch_id or f"workbench-giga-{source_part}{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    try:
        result = await sync_giga_products(
            db,
            GigaSyncOptions(
                task_id=body.task_id or "workbench-pull-giga",
                batch_id=batch_id,
                site=body.site,
                data_source_id=body.data_source_id,
                current_category=body.current_category,
                page_size=body.page_size or 200,
                max_pages=body.max_pages,
                skip_existing=True,
            ),
        )
        await upsert_product_drafts_from_giga_batch(
            db,
            batch_id=result.batch_id,
            site=result.site,
            data_source_id=result.data_source_id,
        )
    except GigaOpenApiError as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:
        raise HTTPException(502, f"GIGA 增量同步失败: {type(exc).__name__}: {exc}")
    return GigaSyncResponse(**result.__dict__)


@router.post("/sync-missing/background", response_model=GigaSyncQueuedResponse)
async def sync_missing_giga_products_background_api(body: GigaSyncMissingRequest):
    """工作台后台增量拉取：先拉商品/SKU/价格/库存，图片 URL 入库后生成 Product 图片候选。"""
    source_part = f"ds{body.data_source_id}-" if body.data_source_id else ""
    batch_id = body.batch_id or f"workbench-giga-{source_part}{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    try:
        result = await enqueue_giga_sync(
            GigaSyncOptions(
                task_id=body.task_id or "workbench-pull-giga",
                batch_id=batch_id,
                site=body.site,
                data_source_id=body.data_source_id,
                current_category=body.current_category,
                page_size=body.page_size or 200,
                max_pages=body.max_pages,
                skip_existing=True,
                download_images=False,
            )
        )
    except GigaOpenApiError as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:
        raise HTTPException(502, f"GIGA 后台增量同步提交失败: {type(exc).__name__}: {exc}")
    return GigaSyncQueuedResponse(**result.__dict__)


@router.post("/inventory/sync", response_model=GigaInventorySyncResponse)
async def sync_giga_inventory_api(body: GigaInventorySyncRequest, db: AsyncSession = Depends(get_db)):
    """从 GIGA Open API 拉取库存快照，按 batch/site 写入库存事实表并生成有货/无货切换告警。"""
    try:
        result = await sync_giga_inventory_snapshot(
            db,
            GigaInventorySyncOptions(
                task_id=body.task_id,
                batch_id=body.batch_id,
                site=body.site,
                data_source_id=body.data_source_id,
                sku_codes=body.sku_codes or [],
            ),
        )
    except GigaOpenApiError as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:
        raise HTTPException(502, f"GIGA 库存同步失败: {type(exc).__name__}: {exc}")
    return GigaInventorySyncResponse(**result.__dict__)


@router.post("/price/sync", response_model=GigaPriceSyncResponse)
async def sync_giga_price_api(body: GigaPriceSyncRequest, db: AsyncSession = Depends(get_db)):
    """从 GIGA Open API 拉取价格快照，按 batch/site 写入价格事实表。"""
    try:
        result = await sync_giga_price_snapshot(
            db,
            GigaPriceSyncOptions(
                task_id=body.task_id,
                batch_id=body.batch_id,
                site=body.site,
                data_source_id=body.data_source_id,
                sku_codes=body.sku_codes or [],
            ),
        )
    except GigaOpenApiError as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:
        raise HTTPException(502, f"GIGA 价格同步失败: {type(exc).__name__}: {exc}")
    return GigaPriceSyncResponse(**result.__dict__)


@router.get("/batches", response_model=PaginatedGigaSyncBatches)
async def list_giga_batches(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    site: str | None = None,
    data_source_id: int | None = None,
    status: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    query = select(GigaSyncBatch).order_by(GigaSyncBatch.created_at.desc())
    count_query = select(func.count(GigaSyncBatch.id))
    if site:
        query = query.where(GigaSyncBatch.site == site.strip().upper())
        count_query = count_query.where(GigaSyncBatch.site == site.strip().upper())
    if data_source_id:
        query = query.where(GigaSyncBatch.data_source_id == data_source_id)
        count_query = count_query.where(GigaSyncBatch.data_source_id == data_source_id)
    if status:
        query = query.where(GigaSyncBatch.status == status)
        count_query = count_query.where(GigaSyncBatch.status == status)

    total_result = await db.execute(count_query)
    result = await db.execute(query.offset((page - 1) * page_size).limit(page_size))
    return PaginatedGigaSyncBatches(
        items=result.scalars().all(),
        total=total_result.scalar() or 0,
        page=page,
        page_size=page_size,
    )


@router.get("/groups", response_model=PaginatedGigaGroups)
async def list_giga_groups(
    batch_id: str,
    site: str = Query("US", min_length=1),
    data_source_id: int | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    include_single_sku: bool = False,
    db: AsyncSession = Depends(get_db),
):
    normalized_site = site.strip().upper()
    query = (
        select(GigaGroup)
        .where(GigaGroup.batch_id == batch_id, GigaGroup.site == normalized_site)
        .order_by(GigaGroup.deleted_single_sku_group.asc(), GigaGroup.group_size.desc(), GigaGroup.group_code.asc())
    )
    count_query = select(func.count(GigaGroup.id)).where(GigaGroup.batch_id == batch_id, GigaGroup.site == normalized_site)
    if not include_single_sku:
        query = query.where(GigaGroup.deleted_single_sku_group == 0)
        count_query = count_query.where(GigaGroup.deleted_single_sku_group == 0)
    if data_source_id:
        query = query.where(GigaGroup.data_source_id == data_source_id)
        count_query = count_query.where(GigaGroup.data_source_id == data_source_id)

    total_result = await db.execute(count_query)
    result = await db.execute(query.offset((page - 1) * page_size).limit(page_size))
    return PaginatedGigaGroups(
        items=result.scalars().all(),
        total=total_result.scalar() or 0,
        page=page,
        page_size=page_size,
    )


@router.get("/items", response_model=PaginatedGigaItems)
async def list_giga_items(
    batch_id: str | None = None,
    site: str = Query("US", min_length=1),
    data_source_id: int | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    sku_code: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    normalized_site = site.strip().upper()
    query = (
        select(GigaItem)
        .where(GigaItem.site == normalized_site)
        .order_by(GigaItem.updated_at.is_(None).asc(), GigaItem.updated_at.desc(), GigaItem.sku_count.desc(), GigaItem.item_code.asc())
    )
    count_query = select(func.count(GigaItem.id)).where(GigaItem.site == normalized_site)
    if data_source_id:
        query = query.where(GigaItem.data_source_id == data_source_id)
        count_query = count_query.where(GigaItem.data_source_id == data_source_id)
    if batch_id:
        query = query.where(GigaItem.batch_id == batch_id)
        count_query = count_query.where(GigaItem.batch_id == batch_id)
    if sku_code:
        pattern = f"%{sku_code.strip()}%"
        query = query.where(
            or_(
                GigaItem.item_code.ilike(pattern),
                GigaItem.parent_sku_code.ilike(pattern),
                GigaItem.sku_codes_json.ilike(pattern),
            )
        )
        count_query = count_query.where(
            or_(
                GigaItem.item_code.ilike(pattern),
                GigaItem.parent_sku_code.ilike(pattern),
                GigaItem.sku_codes_json.ilike(pattern),
            )
        )
    total_result = await db.execute(count_query)
    result = await db.execute(query.offset((page - 1) * page_size).limit(page_size))
    return PaginatedGigaItems(
        items=result.scalars().all(),
        total=total_result.scalar() or 0,
        page=page,
        page_size=page_size,
    )


@router.get("/skus", response_model=PaginatedGigaSkus)
async def list_giga_skus(
    batch_id: str,
    site: str = Query("US", min_length=1),
    data_source_id: int | None = None,
    item_code: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    normalized_site = site.strip().upper()
    price_batch_result = await db.execute(
        select(GigaSyncBatch.batch_id)
        .where(GigaSyncBatch.site == normalized_site, GigaSyncBatch.status == "done", GigaSyncBatch.price_count > 0)
        .where(GigaSyncBatch.data_source_id == data_source_id if data_source_id else True)
        .order_by(GigaSyncBatch.finished_at.is_(None).asc(), GigaSyncBatch.finished_at.desc(), GigaSyncBatch.created_at.desc())
        .limit(1)
    )
    latest_price_batch_id = price_batch_result.scalar_one_or_none() or batch_id
    inventory_batch_result = await db.execute(
        select(GigaSyncBatch.batch_id)
        .where(GigaSyncBatch.site == normalized_site, GigaSyncBatch.status == "done", GigaSyncBatch.inventory_count > 0)
        .where(GigaSyncBatch.data_source_id == data_source_id if data_source_id else True)
        .order_by(GigaSyncBatch.finished_at.is_(None).asc(), GigaSyncBatch.finished_at.desc(), GigaSyncBatch.created_at.desc())
        .limit(1)
    )
    latest_inventory_batch_id = inventory_batch_result.scalar_one_or_none() or batch_id
    query = (
        select(GigaSku, GigaPrice, GigaInventory)
        .join(
            GigaPrice,
            (GigaPrice.batch_id == latest_price_batch_id)
            & (GigaPrice.site == GigaSku.site)
            & (GigaPrice.data_source_id == GigaSku.data_source_id)
            & (GigaPrice.sku_code == GigaSku.sku_code),
            isouter=True,
        )
        .join(
            GigaInventory,
            (GigaInventory.batch_id == latest_inventory_batch_id)
            & (GigaInventory.site == GigaSku.site)
            & (GigaInventory.data_source_id == GigaSku.data_source_id)
            & (GigaInventory.sku_code == GigaSku.sku_code),
            isouter=True,
        )
        .where(GigaSku.batch_id == batch_id, GigaSku.site == normalized_site)
        .order_by(GigaSku.item_code.asc(), GigaSku.child_sequence.asc(), GigaSku.sku_code.asc())
    )
    count_query = select(func.count(GigaSku.id)).where(GigaSku.batch_id == batch_id, GigaSku.site == normalized_site)
    if data_source_id:
        query = query.where(GigaSku.data_source_id == data_source_id)
        count_query = count_query.where(GigaSku.data_source_id == data_source_id)
    if item_code:
        query = query.where(GigaSku.item_code == item_code)
        count_query = count_query.where(GigaSku.item_code == item_code)
    total_result = await db.execute(count_query)
    result = await db.execute(query.offset((page - 1) * page_size).limit(page_size))
    items = []
    for sku, price, inventory in result.all():
        items.append({
            "id": sku.id,
            "giga_item_id": sku.giga_item_id,
            "batch_id": sku.batch_id,
            "site": sku.site,
            "data_source_id": sku.data_source_id,
            "data_source_name": sku.data_source_name,
            "fulfillment_mode": sku.fulfillment_mode,
            "sku_code": sku.sku_code,
            "item_code": sku.item_code,
            "parent_sku_code": sku.parent_sku_code,
            "parentage": sku.parentage,
            "child_sequence": sku.child_sequence,
            "is_primary_child": sku.is_primary_child,
            "product_name": sku.product_name,
            "main_image_url": sku.main_image_url,
            "description": sku.description,
            "attributes_json": sku.attributes_json,
            "variation_attributes_json": sku.variation_attributes_json,
            "currency": price.currency if price else None,
            "price": price.price if price else None,
            "effective_price": price.effective_price if price else None,
            "exclusive_price": price.exclusive_price if price else None,
            "discounted_price": price.discounted_price if price else None,
            "shipping_fee": price.shipping_fee if price else None,
            "estimated_shipping_fee": price.estimated_shipping_fee if price else None,
            "seller_available_inventory": inventory.seller_available_inventory if inventory else None,
            "total_buyer_available_inventory": inventory.total_buyer_available_inventory if inventory else None,
            "availability_status": inventory.availability_status if inventory else None,
            "created_at": sku.created_at,
            "updated_at": sku.updated_at,
        })
    return PaginatedGigaSkus(
        items=items,
        total=total_result.scalar() or 0,
        page=page,
        page_size=page_size,
    )


@router.get("/images", response_model=PaginatedGigaProductImages)
async def list_giga_product_images(
    batch_id: str,
    site: str = Query("US", min_length=1),
    data_source_id: int | None = None,
    item_code: str | None = None,
    sku_code: str | None = None,
    download_status: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    normalized_site = site.strip().upper()
    query = (
        select(GigaProductImage)
        .where(GigaProductImage.batch_id == batch_id, GigaProductImage.site == normalized_site)
        .order_by(GigaProductImage.item_code.asc(), GigaProductImage.sku_code.asc(), GigaProductImage.sort_order.asc())
    )
    count_query = select(func.count(GigaProductImage.id)).where(
        GigaProductImage.batch_id == batch_id,
        GigaProductImage.site == normalized_site,
    )
    if item_code:
        query = query.where(GigaProductImage.item_code == item_code)
        count_query = count_query.where(GigaProductImage.item_code == item_code)
    if sku_code:
        query = query.where(GigaProductImage.sku_code == sku_code)
        count_query = count_query.where(GigaProductImage.sku_code == sku_code)
    if download_status:
        query = query.where(GigaProductImage.download_status == download_status)
        count_query = count_query.where(GigaProductImage.download_status == download_status)
    if data_source_id:
        query = query.where(GigaProductImage.data_source_id == data_source_id)
        count_query = count_query.where(GigaProductImage.data_source_id == data_source_id)

    total_result = await db.execute(count_query)
    result = await db.execute(query.offset((page - 1) * page_size).limit(page_size))
    return PaginatedGigaProductImages(
        items=result.scalars().all(),
        total=total_result.scalar() or 0,
        page=page,
        page_size=page_size,
    )


@router.get("/inventory", response_model=PaginatedGigaInventory)
async def list_giga_inventory(
    site: str = Query(..., min_length=1),
    data_source_id: int | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    sku_code: str | None = None,
    availability_status: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    normalized_site = site.strip().upper()
    batch_query = (
        select(GigaSyncBatch)
        .where(GigaSyncBatch.site == normalized_site, GigaSyncBatch.status == "done", GigaSyncBatch.inventory_count > 0)
        .order_by(GigaSyncBatch.finished_at.is_(None).asc(), GigaSyncBatch.finished_at.desc(), GigaSyncBatch.created_at.desc())
        .limit(1)
    )
    if data_source_id:
        batch_query = batch_query.where(GigaSyncBatch.data_source_id == data_source_id)
    batch_result = await db.execute(batch_query)
    latest_batch = batch_result.scalar_one_or_none()
    if not latest_batch:
        return PaginatedGigaInventory(items=[], total=0, page=page, page_size=page_size)

    product_batch_query = (
        select(GigaSyncBatch.batch_id)
        .where(
            GigaSyncBatch.site == normalized_site,
            GigaSyncBatch.status == "done",
            GigaSyncBatch.sku_count > 0,
            or_(
                GigaSyncBatch.current_category.is_(None),
                GigaSyncBatch.current_category.notin_(GIGA_DYNAMIC_SNAPSHOT_CATEGORIES),
            ),
        )
        .order_by(GigaSyncBatch.created_at.desc())
        .limit(1)
    )
    if data_source_id:
        product_batch_query = product_batch_query.where(GigaSyncBatch.data_source_id == data_source_id)
    product_batch_result = await db.execute(product_batch_query)
    product_batch_id = product_batch_result.scalar_one_or_none()

    query = (
        select(GigaInventory, GigaSku)
        .join(
            GigaSku,
            (GigaSku.batch_id == product_batch_id)
            & (GigaSku.site == GigaInventory.site)
            & (GigaSku.data_source_id == GigaInventory.data_source_id)
            & (GigaSku.sku_code == GigaInventory.sku_code),
            isouter=True,
        )
        .where(GigaInventory.batch_id == latest_batch.batch_id, GigaInventory.site == normalized_site)
        .order_by(GigaInventory.sku_code.asc())
    )
    count_query = select(func.count(GigaInventory.id)).where(
        GigaInventory.batch_id == latest_batch.batch_id,
        GigaInventory.site == normalized_site,
    )
    if data_source_id:
        query = query.where(GigaInventory.data_source_id == data_source_id)
        count_query = count_query.where(GigaInventory.data_source_id == data_source_id)
    if sku_code:
        like = f"%{sku_code.strip()}%"
        query = query.where(GigaInventory.sku_code.like(like))
        count_query = count_query.where(GigaInventory.sku_code.like(like))
    if availability_status:
        query = query.where(GigaInventory.availability_status == availability_status)
        count_query = count_query.where(GigaInventory.availability_status == availability_status)

    total_result = await db.execute(count_query)
    result = await db.execute(query.offset((page - 1) * page_size).limit(page_size))
    items = []
    for inventory, sku in result.all():
        items.append({
            "id": inventory.id,
            "site": inventory.site,
            "data_source_id": inventory.data_source_id,
            "fulfillment_mode": inventory.fulfillment_mode,
            "inventory_mode": inventory.inventory_mode,
            "sku_code": inventory.sku_code,
            "item_code": sku.item_code if sku else None,
            "product_name": sku.product_name if sku else None,
            "stock_qty": inventory.stock_qty,
            "seller_available_inventory": inventory.seller_available_inventory,
            "total_buyer_available_inventory": inventory.total_buyer_available_inventory,
            "seller_inventory_distribution": inventory.seller_inventory_distribution,
            "buyer_inventory_distribution": inventory.buyer_inventory_distribution,
            "next_arrival_inventory": inventory.next_arrival_inventory,
            "availability_status": inventory.availability_status,
            "pulled_at": inventory.pulled_at,
            "updated_at": inventory.updated_at,
        })
    return PaginatedGigaInventory(
        items=items,
        total=total_result.scalar() or 0,
        page=page,
        page_size=page_size,
        latest_batch_id=latest_batch.batch_id,
        pulled_at=latest_batch.finished_at or latest_batch.started_at,
    )


@router.get("/inventory/alerts", response_model=PaginatedGigaInventoryAlerts)
async def list_giga_inventory_alerts(
    batch_id: str | None = None,
    site: str = Query(..., min_length=1),
    data_source_id: int | None = None,
    change_type: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    normalized_site = site.strip().upper()
    query = (
        select(GigaInventoryAlert)
        .where(GigaInventoryAlert.site == normalized_site)
        .order_by(GigaInventoryAlert.created_at.desc(), GigaInventoryAlert.id.desc())
    )
    count_query = select(func.count(GigaInventoryAlert.id)).where(GigaInventoryAlert.site == normalized_site)
    if batch_id:
        query = query.where(GigaInventoryAlert.batch_id == batch_id)
        count_query = count_query.where(GigaInventoryAlert.batch_id == batch_id)
    if data_source_id:
        query = query.where(GigaInventoryAlert.data_source_id == data_source_id)
        count_query = count_query.where(GigaInventoryAlert.data_source_id == data_source_id)
    if change_type:
        query = query.where(GigaInventoryAlert.change_type == change_type)
        count_query = count_query.where(GigaInventoryAlert.change_type == change_type)

    total_result = await db.execute(count_query)
    result = await db.execute(query.offset((page - 1) * page_size).limit(page_size))
    return PaginatedGigaInventoryAlerts(
        items=result.scalars().all(),
        total=total_result.scalar() or 0,
        page=page,
        page_size=page_size,
    )


@router.get("/price/alerts", response_model=PaginatedGigaPriceAlerts)
async def list_giga_price_alerts(
    batch_id: str | None = None,
    site: str = Query(..., min_length=1),
    data_source_id: int | None = None,
    change_type: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    normalized_site = site.strip().upper()
    query = (
        select(GigaPriceAlert)
        .where(GigaPriceAlert.site == normalized_site)
        .order_by(GigaPriceAlert.created_at.desc(), GigaPriceAlert.id.desc())
    )
    count_query = select(func.count(GigaPriceAlert.id)).where(GigaPriceAlert.site == normalized_site)
    if batch_id:
        query = query.where(GigaPriceAlert.batch_id == batch_id)
        count_query = count_query.where(GigaPriceAlert.batch_id == batch_id)
    if data_source_id:
        query = query.where(GigaPriceAlert.data_source_id == data_source_id)
        count_query = count_query.where(GigaPriceAlert.data_source_id == data_source_id)
    if change_type:
        query = query.where(GigaPriceAlert.change_type == change_type)
        count_query = count_query.where(GigaPriceAlert.change_type == change_type)

    total_result = await db.execute(count_query)
    result = await db.execute(query.offset((page - 1) * page_size).limit(page_size))
    return PaginatedGigaPriceAlerts(
        items=result.scalars().all(),
        total=total_result.scalar() or 0,
        page=page,
        page_size=page_size,
    )
