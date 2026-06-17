from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import (
    PaginatedProductDataSources,
    ProductDataSourceCreate,
    ProductDataSourceResponse,
    ProductDataSourceUpdate,
)
from app.database import get_db
from app.models import GigaSyncBatch, ProductDataSource


router = APIRouter(prefix="/api/product-data-sources", tags=["product-data-sources"])

VALID_PLATFORMS = {"giga"}
VALID_SALES_CHANNELS = {"amazon", "tiktok"}
VALID_FULFILLMENT_MODES = {"self_ship", "dropship"}


def _normalize_site(value: str | None) -> str:
    site = (value or "").strip().upper()
    if not site:
        raise HTTPException(400, "站点不能为空")
    return site


def _normalize_platform(value: str | None) -> str:
    platform = (value or "giga").strip().lower()
    if platform not in VALID_PLATFORMS:
        raise HTTPException(400, f"暂不支持的店铺平台: {platform}")
    return platform


def _normalize_sales_channel(value: str | None) -> str:
    sales_channel = (value or "amazon").strip().lower()
    if sales_channel not in VALID_SALES_CHANNELS:
        raise HTTPException(400, f"暂不支持的销售渠道: {sales_channel}")
    return sales_channel


def _validate_choice(value: str, allowed: set[str], label: str) -> str:
    normalized = (value or "").strip()
    if normalized not in allowed:
        raise HTTPException(400, f"{label} 不合法: {value}")
    return normalized


def _shipping_mode_for_fulfillment(fulfillment_mode: str) -> str:
    return "packing_fee" if fulfillment_mode == "self_ship" else "giga_shipping_fee"


def _inventory_mode_for_fulfillment(fulfillment_mode: str) -> str:
    return "warehouse_distribution" if fulfillment_mode == "self_ship" else "available_qty"


def _validate_source_ready(
    *,
    enabled: bool,
    api_base: str | None,
    client_id: str | None,
    client_secret: str | None,
    fulfillment_mode: str,
    shipping_cost_mode: str,
) -> None:
    if fulfillment_mode == "self_ship" and shipping_cost_mode != "packing_fee":
        raise HTTPException(400, "自发货店铺的运费口径应为 packing_fee")
    if fulfillment_mode == "dropship" and shipping_cost_mode != "giga_shipping_fee":
        raise HTTPException(400, "代发货店铺的运费口径应为 giga_shipping_fee")
    if enabled and not (api_base or "").strip():
        raise HTTPException(400, "启用的店铺需要配置 Open API 地址")
    if enabled and (not (client_id or "").strip() or not (client_secret or "").strip()):
        raise HTTPException(400, "启用的店铺需要配置 AK/SK")


def _mask_secret(secret: str | None) -> str | None:
    if not secret:
        return None
    text = secret.strip()
    if len(text) <= 6:
        return "***"
    return f"{text[:3]}***{text[-3:]}"


def _to_response(source: ProductDataSource) -> ProductDataSourceResponse:
    fulfillment_mode = source.fulfillment_mode or "dropship"
    return ProductDataSourceResponse(
        id=source.id,
        name=source.name,
        platform=source.platform or "giga",
        sales_channel=source.sales_channel or "amazon",
        site=source.site,
        country=source.country or source.site,
        fulfillment_mode=fulfillment_mode,
        api_base=source.api_base,
        client_id=source.client_id,
        shipping_cost_mode=source.shipping_cost_mode or _shipping_mode_for_fulfillment(fulfillment_mode),
        packing_fee=source.packing_fee,
        inventory_mode=source.inventory_mode or _inventory_mode_for_fulfillment(fulfillment_mode),
        enabled=bool(source.enabled),
        remark=source.remark,
        client_secret_masked=_mask_secret(source.client_secret),
        created_at=source.created_at,
        updated_at=source.updated_at,
    )


@router.get("", response_model=PaginatedProductDataSources)
async def list_product_data_sources(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    platform: str | None = None,
    sales_channel: str | None = None,
    site: str | None = None,
    enabled: bool | None = None,
    db: AsyncSession = Depends(get_db),
):
    query = select(ProductDataSource).order_by(ProductDataSource.enabled.desc(), ProductDataSource.id.desc())
    count_query = select(func.count(ProductDataSource.id))
    if platform:
        normalized_platform = _normalize_platform(platform)
        query = query.where(ProductDataSource.platform == normalized_platform)
        count_query = count_query.where(ProductDataSource.platform == normalized_platform)
    if sales_channel:
        normalized_sales_channel = _normalize_sales_channel(sales_channel)
        query = query.where(ProductDataSource.sales_channel == normalized_sales_channel)
        count_query = count_query.where(ProductDataSource.sales_channel == normalized_sales_channel)
    if site:
        normalized_site = _normalize_site(site)
        query = query.where(ProductDataSource.site == normalized_site)
        count_query = count_query.where(ProductDataSource.site == normalized_site)
    if enabled is not None:
        enabled_int = 1 if enabled else 0
        query = query.where(ProductDataSource.enabled == enabled_int)
        count_query = count_query.where(ProductDataSource.enabled == enabled_int)

    total_result = await db.execute(count_query)
    result = await db.execute(query.offset((page - 1) * page_size).limit(page_size))
    return PaginatedProductDataSources(
        items=[_to_response(source) for source in result.scalars().all()],
        total=total_result.scalar() or 0,
        page=page,
        page_size=page_size,
    )


@router.post("", response_model=ProductDataSourceResponse)
async def create_product_data_source(body: ProductDataSourceCreate, db: AsyncSession = Depends(get_db)):
    name = body.name.strip()
    existing_result = await db.execute(select(ProductDataSource).where(ProductDataSource.name == name))
    if existing_result.scalar_one_or_none():
        raise HTTPException(400, f"店铺名称已存在: {name}")

    platform = _normalize_platform(body.platform)
    sales_channel = _normalize_sales_channel(body.sales_channel)
    site = _normalize_site(body.site)
    fulfillment_mode = _validate_choice(body.fulfillment_mode, VALID_FULFILLMENT_MODES, "履约方式")
    shipping_cost_mode = _shipping_mode_for_fulfillment(fulfillment_mode)
    inventory_mode = _inventory_mode_for_fulfillment(fulfillment_mode)
    api_base = (body.api_base or "").strip() or None
    client_id = (body.client_id or "").strip() or None
    client_secret = (body.client_secret or "").strip() or None
    _validate_source_ready(
        enabled=body.enabled,
        api_base=api_base,
        client_id=client_id,
        client_secret=client_secret,
        fulfillment_mode=fulfillment_mode,
        shipping_cost_mode=shipping_cost_mode,
    )

    source = ProductDataSource(
        name=name,
        platform=platform,
        sales_channel=sales_channel,
        site=site,
        country=site,
        fulfillment_mode=fulfillment_mode,
        api_base=api_base,
        client_id=client_id,
        client_secret=client_secret,
        shipping_cost_mode=shipping_cost_mode,
        packing_fee=None,
        inventory_mode=inventory_mode,
        enabled=1 if body.enabled else 0,
        remark=(body.remark or "").strip() or None,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    db.add(source)
    await db.commit()
    await db.refresh(source)
    return _to_response(source)


@router.patch("/{source_id}", response_model=ProductDataSourceResponse)
async def update_product_data_source(
    source_id: int,
    body: ProductDataSourceUpdate,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(ProductDataSource).where(ProductDataSource.id == source_id))
    source = result.scalar_one_or_none()
    if not source:
        raise HTTPException(404, "店铺不存在")

    if body.name is not None:
        name = body.name.strip()
        existing_result = await db.execute(
            select(ProductDataSource).where(ProductDataSource.name == name, ProductDataSource.id != source_id)
        )
        if existing_result.scalar_one_or_none():
            raise HTTPException(400, f"店铺名称已存在: {name}")
        source.name = name
    if body.platform is not None:
        source.platform = _normalize_platform(body.platform)
    if body.sales_channel is not None:
        source.sales_channel = _normalize_sales_channel(body.sales_channel)
    if body.site is not None:
        source.site = _normalize_site(body.site)
    if body.fulfillment_mode is not None:
        source.fulfillment_mode = _validate_choice(body.fulfillment_mode, VALID_FULFILLMENT_MODES, "履约方式")
        source.shipping_cost_mode = _shipping_mode_for_fulfillment(source.fulfillment_mode)
        source.inventory_mode = _inventory_mode_for_fulfillment(source.fulfillment_mode)
        source.packing_fee = None
    if body.api_base is not None:
        source.api_base = body.api_base.strip() or None
    if body.client_id is not None:
        source.client_id = body.client_id.strip() or None
    if body.client_secret is not None and body.client_secret.strip():
        source.client_secret = body.client_secret.strip()
    source.country = source.site
    if body.enabled is not None:
        source.enabled = 1 if body.enabled else 0
    if body.remark is not None:
        source.remark = body.remark.strip() or None

    source.fulfillment_mode = _validate_choice(source.fulfillment_mode or "dropship", VALID_FULFILLMENT_MODES, "履约方式")
    source.shipping_cost_mode = _shipping_mode_for_fulfillment(source.fulfillment_mode)
    source.inventory_mode = _inventory_mode_for_fulfillment(source.fulfillment_mode)
    source.packing_fee = None
    _validate_source_ready(
        enabled=bool(source.enabled),
        api_base=source.api_base,
        client_id=source.client_id,
        client_secret=source.client_secret,
        fulfillment_mode=source.fulfillment_mode,
        shipping_cost_mode=source.shipping_cost_mode,
    )

    source.updated_at = datetime.now()
    await db.commit()
    await db.refresh(source)
    return _to_response(source)


@router.delete("/{source_id}", response_model=ProductDataSourceResponse)
async def delete_product_data_source(source_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ProductDataSource).where(ProductDataSource.id == source_id))
    source = result.scalar_one_or_none()
    if not source:
        raise HTTPException(404, "店铺不存在")
    usage_result = await db.execute(
        select(func.count(GigaSyncBatch.id)).where(GigaSyncBatch.data_source_id == source_id)
    )
    if (usage_result.scalar() or 0) > 0:
        source.enabled = 0
        source.updated_at = datetime.now()
        await db.commit()
        await db.refresh(source)
        return _to_response(source)
    await db.delete(source)
    await db.commit()
    return _to_response(source)
