import json
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models import GigaInventory, GigaPrice, GigaSku, Product, ProductDataSource


router = APIRouter(prefix="/api/tiktok", tags=["tiktok"])

TIKTOK_FIXED_SHIPPING_FEE = 50.0
TIKTOK_PRICE_BUFFER = 20.0
TIKTOK_PRICE_MULTIPLIER = 2.4


def _json_loads(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except Exception:
        return fallback


def calculate_tiktok_price(cost: float | None) -> float | None:
    if cost is None or cost <= 0:
        return None
    return round((float(cost) + TIKTOK_FIXED_SHIPPING_FEE + TIKTOK_PRICE_BUFFER) * TIKTOK_PRICE_MULTIPLIER, 2)


def _number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_quantity(value: Any) -> int:
    parsed = _number(value)
    return int(parsed) if parsed is not None else 0


def _parse_warehouse_inventory(value: str | None) -> list[dict[str, Any]]:
    raw = _json_loads(value, [])
    if not isinstance(raw, list):
        return []
    rows: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        warehouse = (
            item.get("warehouseCode")
            or item.get("warehouse_code")
            or item.get("warehouse")
            or item.get("sellerCode")
            or item.get("seller_code")
            or item.get("code")
        )
        quantity = (
            item.get("quantity")
            or item.get("qty")
            or item.get("availableQty")
            or item.get("available_qty")
            or item.get("sellerAvailableInventory")
            or item.get("seller_available_inventory")
            or item.get("stock")
        )
        rows.append({
            "warehouse_code": str(warehouse or "UNKNOWN"),
            "quantity": _int_quantity(quantity),
        })
    return rows


def _best_purchase_price(price: GigaPrice | None, variant: dict[str, Any]) -> float | None:
    if price:
        for value in (
            price.effective_price,
            price.discounted_price,
            price.exclusive_price,
            price.price,
        ):
            parsed = _number(value)
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


def _variant_sku(value: dict[str, Any]) -> str | None:
    for key in ("sku", "sku_code", "seller_sku"):
        text = str(value.get(key) or "").strip()
        if text:
            return text
    return None


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

    pd = product.data
    images = product.images
    variants = _json_loads(pd.variants if pd else None, [])
    if not isinstance(variants, list):
        variants = []
    item_code = (pd.item_code if pd else None) or product.source_item_id or product.gigab2b_product_id
    batch_id = product.source_batch_id
    site = product.source_site or data_source.site if data_source else product.source_site
    data_source_id = product.source_data_source_id

    giga_skus: list[GigaSku] = []
    if batch_id and site and data_source_id and item_code:
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
        giga_skus = sku_result.scalars().all()

    sku_codes = [sku.sku_code for sku in giga_skus]
    if not sku_codes:
        sku_codes = [code for code in (_variant_sku(item) for item in variants if isinstance(item, dict)) if code]

    prices_by_sku: dict[str, GigaPrice] = {}
    inventory_by_sku: dict[str, GigaInventory] = {}
    if batch_id and site and data_source_id and sku_codes:
        price_result = await db.execute(
            select(GigaPrice).where(
                GigaPrice.batch_id == batch_id,
                GigaPrice.site == site,
                GigaPrice.data_source_id == data_source_id,
                GigaPrice.sku_code.in_(sku_codes),
            )
        )
        prices_by_sku = {row.sku_code: row for row in price_result.scalars().all()}
        inventory_result = await db.execute(
            select(GigaInventory).where(
                GigaInventory.batch_id == batch_id,
                GigaInventory.site == site,
                GigaInventory.data_source_id == data_source_id,
                GigaInventory.sku_code.in_(sku_codes),
            )
        )
        inventory_by_sku = {row.sku_code: row for row in inventory_result.scalars().all()}

    variants_by_sku = {
        _variant_sku(item): item
        for item in variants
        if isinstance(item, dict) and _variant_sku(item)
    }
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
            variation_attributes_json=json.dumps(variants_by_sku.get(sku_code, {}).get("variation_attributes") or {}, ensure_ascii=False),
        )
        for sku_code in sku_codes
    ]

    for sku in source_skus:
        variant = variants_by_sku.get(sku.sku_code, {})
        price = prices_by_sku.get(sku.sku_code)
        inventory = inventory_by_sku.get(sku.sku_code)
        sku_title = sku.product_name or variant.get("title") or (pd.title if pd else product.title)
        purchase_price = _best_purchase_price(price, variant)
        warehouses = _parse_warehouse_inventory(inventory.seller_inventory_distribution if inventory else None)
        total_inventory = sum(int(row.get("quantity") or 0) for row in warehouses)
        missing_fields: list[str] = []
        if purchase_price is None:
            missing_fields.append("采购价")
        if not warehouses:
            missing_fields.append("分仓库存")
        rows.append({
            "sku_code": sku.sku_code,
            "item_code": sku.item_code or item_code,
            "title": sku_title,
            "main_image_url": _image_url(sku.main_image_url or variant.get("main_image_url")),
            "variation_attributes": _json_loads(sku.variation_attributes_json, variant.get("variation_attributes") or {}),
            "purchase_price": purchase_price,
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
    if product.status == "failed":
        tiktok_status = "failed"
    elif not rows:
        tiktok_status = "draft"
    elif missing_summary:
        tiktok_status = "missing_required_info"
    else:
        tiktok_status = "export_ready"

    return {
        "id": product.id,
        "item_code": item_code,
        "title": product.title or (pd.title if pd else None),
        "status": tiktok_status,
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
