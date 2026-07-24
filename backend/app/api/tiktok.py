import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models import GigaInventory, GigaPrice, GigaSku, Product, ProductDataSource
from app.services.tiktok_status import (
    ASCII_EDGE_WHITESPACE_REGEX,
    build_tiktok_classification_cte,
    canonicalize_ascii_edge_text,
    parse_mysql_decimal_20_6,
    parse_mysql_float_decimal_20_6,
    source_nonempty_string,
)


router = APIRouter(prefix="/api/tiktok", tags=["tiktok"])

TIKTOK_FIXED_SHIPPING_FEE = 50.0
TIKTOK_PRICE_BUFFER = 20.0
TIKTOK_PRICE_MULTIPLIER = 2.4


def _reject_nonstandard_json_constant(value: str) -> None:
    raise ValueError(f"invalid JSON numeric constant: {value}")


def _json_loads(value: str | None, fallback: Any, *, exact_numbers: bool = False) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(
            value,
            parse_float=Decimal if exact_numbers else float,
            parse_int=Decimal if exact_numbers else int,
            parse_constant=_reject_nonstandard_json_constant,
        )
    except Exception:
        return fallback


def calculate_tiktok_price(cost: Decimal | None) -> float | None:
    parsed_cost = parse_mysql_decimal_20_6(cost)
    if parsed_cost is None or parsed_cost <= 0:
        return None
    price = (
        (
            parsed_cost
            + Decimal(str(TIKTOK_FIXED_SHIPPING_FEE))
            + Decimal(str(TIKTOK_PRICE_BUFFER))
        )
        * Decimal(str(TIKTOK_PRICE_MULTIPLIER))
    ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(price)


def _number(value: Any) -> Decimal | None:
    return parse_mysql_decimal_20_6(value)


def _parse_warehouse_inventory(value: str | None) -> list[dict[str, Any]]:
    raw = _json_loads(value, [], exact_numbers=True)
    if not isinstance(raw, list):
        return []
    rows: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        warehouse = next((
            canonical
            for key in (
                "warehouseCode",
                "warehouse_code",
                "warehouse",
                "sellerCode",
                "seller_code",
                "code",
            )
            if (canonical := canonicalize_ascii_edge_text(item.get(key))) is not None
        ), None)
        quantity = next((
            parsed
            for key in (
                "quantity",
                "qty",
                "availableQty",
                "available_qty",
                "sellerAvailableInventory",
                "seller_available_inventory",
                "stock",
            )
            if (parsed := _number(item.get(key))) is not None
        ), None)
        if warehouse is None or quantity is None:
            continue
        rows.append({
            "warehouse_code": warehouse,
            "quantity": int(quantity),
        })
    return rows


def _best_purchase_price(price: GigaPrice | None, variant: dict[str, Any]) -> Decimal | None:
    if price:
        for value in (
            price.effective_price,
            price.discounted_price,
            price.exclusive_price,
            price.price,
        ):
            parsed = parse_mysql_float_decimal_20_6(value)
            if parsed is not None and parsed > 0:
                return parsed
    for key in ("cost", "cost_total", "price", "purchase_price"):
        parsed = _number(variant.get(key))
        if parsed is not None and parsed > 0:
            return parsed
    return None


def _image_url(value: str | None) -> str | None:
    if not value:
        return None
    return value


def _sku_key(value: Any) -> str | None:
    return canonicalize_ascii_edge_text(value)


def _sku_key_sql(column: Any):
    return func.regexp_replace(column, ASCII_EDGE_WHITESPACE_REGEX, "")


def _canonical_sku_winners(rows: list[Any]) -> dict[str, Any]:
    winners: dict[str, Any] = {}
    priorities: dict[str, tuple[bool, int]] = {}
    for row in rows:
        raw_sku = str(getattr(row, "sku_code", "") or "")
        canonical_sku = _sku_key(raw_sku)
        if not canonical_sku:
            continue
        priority = (raw_sku == canonical_sku, int(getattr(row, "id", 0) or 0))
        if canonical_sku not in priorities or priority > priorities[canonical_sku]:
            winners[canonical_sku] = row
            priorities[canonical_sku] = priority
    return winners


def _variant_sku(value: dict[str, Any]) -> str | None:
    for key in ("sku", "sku_code", "seller_sku"):
        if sku_code := _sku_key(value.get(key)):
            return sku_code
    return None


@dataclass(frozen=True)
class _TikTokSourceKeys:
    data_source_id: int | None
    site: str | None
    batch_id: str | None
    item_code: str | None
    fact_lookup_enabled: bool
    giga_sku_lookup_enabled: bool


def _resolve_tiktok_source_keys(
    product: Product,
    data_source: ProductDataSource | None,
) -> _TikTokSourceKeys:
    product_data = product.data
    source_site = source_nonempty_string(product.source_site)
    site = source_site if source_site is not None else (data_source.site if data_source else None)
    item_code = (
        source_nonempty_string(product_data.item_code if product_data else None)
        or source_nonempty_string(product.source_item_id)
        or source_nonempty_string(product.gigab2b_product_id)
    )
    batch_id = product.source_batch_id if isinstance(product.source_batch_id, str) else None
    data_source_id = product.source_data_source_id
    fact_lookup_enabled = (
        data_source is not None
        and data_source_id is not None
        and source_nonempty_string(site) is not None
        and source_nonempty_string(batch_id) is not None
    )
    return _TikTokSourceKeys(
        data_source_id=data_source_id,
        site=site,
        batch_id=batch_id,
        item_code=item_code,
        fact_lookup_enabled=fact_lookup_enabled,
        giga_sku_lookup_enabled=(
            fact_lookup_enabled and source_nonempty_string(item_code) is not None
        ),
    )


async def _load_data_source(db: AsyncSession, product: Product) -> ProductDataSource | None:
    if not product.source_data_source_id:
        return None
    return await db.get(ProductDataSource, product.source_data_source_id)


@router.get("/products/{product_id}")
async def get_tiktok_product_detail(product_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Product)
        .options(selectinload(Product.data), selectinload(Product.images))
        .where(Product.id == product_id)
    )
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(404, "Product not found")

    data_source = await _load_data_source(db, product)
    if data_source and (data_source.sales_channel or "amazon").lower() != "tiktok":
        raise HTTPException(400, "该商品所属店铺不是 TikTok 销售渠道")

    classification = build_tiktok_classification_cte(
        product_ids=[product.id],
        data_source_id=product.source_data_source_id,
    )
    projected_status = (
        await db.execute(
            select(classification.c.channel_status)
            .where(classification.c.product_id == product.id)
        )
    ).scalar_one_or_none()
    if projected_status is None:
        raise HTTPException(400, "该商品所属店铺不是 TikTok 销售渠道")

    pd = product.data
    images = product.images
    variants = _json_loads(pd.variants if pd else None, [], exact_numbers=True)
    if not isinstance(variants, list):
        variants = []
    source_keys = _resolve_tiktok_source_keys(product, data_source)
    item_code = source_keys.item_code
    batch_id = source_keys.batch_id
    site = source_keys.site
    data_source_id = source_keys.data_source_id

    giga_skus: list[GigaSku] = []
    if source_keys.giga_sku_lookup_enabled:
        sku_result = await db.execute(
            select(GigaSku)
            .where(
                GigaSku.batch_id == batch_id,
                GigaSku.site == site,
                GigaSku.data_source_id == data_source_id,
                GigaSku.item_code == item_code,
            )
            .order_by(GigaSku.child_sequence.is_(None).asc(), GigaSku.child_sequence.asc(), GigaSku.sku_code.asc())
        )
        raw_giga_skus = sku_result.scalars().all()
        giga_sku_winners = _canonical_sku_winners(raw_giga_skus)
        winner_ids = {row.id for row in giga_sku_winners.values()}
        giga_skus = [row for row in raw_giga_skus if row.id in winner_ids]

    variants_by_sku: dict[str, dict[str, Any]] = {}
    for item in variants:
        if not isinstance(item, dict):
            continue
        if sku_code := _variant_sku(item):
            variants_by_sku[sku_code] = item

    sku_codes = [sku_code for sku in giga_skus if (sku_code := _sku_key(sku.sku_code))]
    if not sku_codes:
        sku_codes = list(variants_by_sku)

    prices_by_sku: dict[str, GigaPrice] = {}
    inventory_by_sku: dict[str, GigaInventory] = {}
    if source_keys.fact_lookup_enabled and sku_codes:
        price_result = await db.execute(
            select(GigaPrice).where(
                GigaPrice.batch_id == batch_id,
                GigaPrice.site == site,
                GigaPrice.data_source_id == data_source_id,
                _sku_key_sql(GigaPrice.sku_code).in_(sku_codes),
            )
        )
        prices_by_sku = _canonical_sku_winners(price_result.scalars().all())
        inventory_result = await db.execute(
            select(GigaInventory).where(
                GigaInventory.batch_id == batch_id,
                GigaInventory.site == site,
                GigaInventory.data_source_id == data_source_id,
                _sku_key_sql(GigaInventory.sku_code).in_(sku_codes),
            )
        )
        inventory_by_sku = _canonical_sku_winners(inventory_result.scalars().all())

    rows: list[dict[str, Any]] = []
    source_skus = giga_skus or [
        GigaSku(
            batch_id=batch_id or "",
            site=site or "",
            data_source_id=data_source_id,
            sku_code=sku_code,
            item_code=item_code,
            product_name=variants_by_sku.get(sku_code, {}).get("title"),
            main_image_url=variants_by_sku.get(sku_code, {}).get("main_image_url"),
            variation_attributes_json=json.dumps(
                variants_by_sku.get(sku_code, {}).get("variation_attributes") or {},
                ensure_ascii=False,
                default=float,
            ),
        )
        for sku_code in sku_codes
    ]

    for sku in source_skus:
        sku_code = _sku_key(sku.sku_code)
        if not sku_code:
            continue
        variant = variants_by_sku.get(sku_code, {})
        price = prices_by_sku.get(sku_code)
        inventory = inventory_by_sku.get(sku_code)
        sku_title = sku.product_name or variant.get("title") or (pd.title if pd else None)
        purchase_price = _best_purchase_price(price, variant)
        warehouses = _parse_warehouse_inventory(inventory.seller_inventory_distribution if inventory else None)
        total_inventory = sum(int(row.get("quantity") or 0) for row in warehouses)
        missing_fields: list[str] = []
        if purchase_price is None:
            missing_fields.append("采购价")
        if not warehouses:
            missing_fields.append("分仓库存")
        rows.append({
            "sku_code": sku_code,
            "item_code": sku.item_code or item_code,
            "title": sku_title,
            "main_image_url": _image_url(sku.main_image_url or variant.get("main_image_url")),
            "variation_attributes": _json_loads(sku.variation_attributes_json, variant.get("variation_attributes") or {}),
            "purchase_price": float(purchase_price) if purchase_price is not None else None,
            "shipping_fee": TIKTOK_FIXED_SHIPPING_FEE,
            "tiktok_price": calculate_tiktok_price(purchase_price),
            "warehouse_inventory": warehouses,
            "warehouse_inventory_total": total_inventory,
            "missing_fields": missing_fields,
        })

    gallery_images = _json_loads(images.gallery_images if images else None, [])
    if not isinstance(gallery_images, list):
        gallery_images = []
    missing_summary = sorted({field for row in rows for field in row["missing_fields"]})

    return {
        "id": product.id,
        "item_code": item_code,
        "title": pd.title if pd else None,
        "status": str(projected_status),
        "source_status": product.status,
        "source_site": site,
        "source_batch_id": batch_id,
        "data_source_id": data_source_id,
        "data_source_name": data_source.name if data_source else None,
        "sales_channel": data_source.sales_channel if data_source else "tiktok",
        "main_image_url": _image_url(images.main_image_path if images else None),
        "gallery_images": gallery_images,
        "pricing_formula": {
            "shipping_fee": TIKTOK_FIXED_SHIPPING_FEE,
            "buffer": TIKTOK_PRICE_BUFFER,
            "multiplier": TIKTOK_PRICE_MULTIPLIER,
            "expression": "round((purchase_price + 50 + 20) * 2.4, 2)",
        },
        "skus": rows,
        "missing_fields": missing_summary,
        "created_at": product.created_at.isoformat() if isinstance(product.created_at, datetime) else product.created_at,
        "updated_at": product.updated_at.isoformat() if isinstance(product.updated_at, datetime) else product.updated_at,
    }
