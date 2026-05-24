import re
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Product, UpcPoolItem
from app.services.product_duplicates import extract_gigab2b_product_id


UPC_SOURCE_GIGAB2B = "大建云仓"


class UpcPoolEmptyError(ValueError):
    pass


def normalize_upc(value: object) -> str:
    return str(value or "").strip().replace(" ", "")


def parse_upc_bulk_text(text: str) -> tuple[list[str], list[str]]:
    values = re.split(r"[\s,，;；]+", text or "")
    upcs: list[str] = []
    invalid: list[str] = []
    seen: set[str] = set()
    for raw in values:
        upc = normalize_upc(raw)
        if not upc:
            continue
        if not re.fullmatch(r"[A-Za-z0-9]{6,32}", upc):
            invalid.append(upc)
            continue
        if upc in seen:
            continue
        seen.add(upc)
        upcs.append(upc)
    return upcs, invalid


async def add_upcs_to_pool(db: AsyncSession, text: str) -> dict:
    upcs, invalid = parse_upc_bulk_text(text)
    if not upcs:
        return {"added": 0, "duplicated": 0, "invalid": invalid, "items": []}

    existing_result = await db.execute(select(UpcPoolItem.upc).where(UpcPoolItem.upc.in_(upcs)))
    existing = set(existing_result.scalars().all())
    now = datetime.now()
    added_items: list[UpcPoolItem] = []
    for upc in upcs:
        if upc in existing:
            continue
        item = UpcPoolItem(upc=upc, status="available", created_at=now, updated_at=now)
        db.add(item)
        added_items.append(item)
    await db.flush()
    return {
        "added": len(added_items),
        "duplicated": len(existing),
        "invalid": invalid,
        "items": added_items,
    }


async def available_upc_count(db: AsyncSession) -> int:
    result = await db.execute(
        select(func.count(UpcPoolItem.id)).where(UpcPoolItem.status == "available")
    )
    return result.scalar() or 0


def _binding_identity(product: Product) -> tuple[str | None, str | None, str | None]:
    data = product.__dict__.get("data")
    item_code = data.item_code if data and data.item_code else None
    source_product_id = product.gigab2b_product_id or extract_gigab2b_product_id(product.gigab2b_url)
    return item_code, source_product_id, product.gigab2b_url


def bind_upc_item(item: UpcPoolItem, product: Product) -> None:
    item_code, source_product_id, source_url = _binding_identity(product)

    if item.status == "bound":
        if item.bound_item_code and item_code and item.bound_item_code != item_code:
            raise ValueError(f"UPC {item.upc} 已绑定商品Code {item.bound_item_code}，不能改绑到 {item_code}")
        if item.bound_source_product_id and source_product_id and item.bound_source_product_id != source_product_id:
            raise ValueError(
                f"UPC {item.upc} 已绑定来源商品ID {item.bound_source_product_id}，不能改绑到 {source_product_id}"
            )

    now = datetime.now()
    item.status = "bound"
    item.source = item.source or UPC_SOURCE_GIGAB2B
    item.product_id = item.product_id or product.id
    item.bound_item_code = item.bound_item_code or item_code
    item.bound_source_product_id = item.bound_source_product_id or source_product_id
    item.bound_source_url = item.bound_source_url or source_url
    item.bound_at = item.bound_at or now
    item.updated_at = now
    product.upc = item.upc


async def ensure_product_upc(db: AsyncSession, product: Product) -> UpcPoolItem:
    if product.upc:
        result = await db.execute(select(UpcPoolItem).where(UpcPoolItem.upc == product.upc))
        item = result.scalar_one_or_none()
        if not item:
            now = datetime.now()
            item = UpcPoolItem(upc=product.upc, status="available", created_at=now, updated_at=now)
            db.add(item)
            await db.flush()
        bind_upc_item(item, product)
        return item

    result = await db.execute(
        select(UpcPoolItem)
        .where(UpcPoolItem.status == "available")
        .order_by(UpcPoolItem.id.asc())
        .limit(1)
    )
    item = result.scalar_one_or_none()
    if not item:
        raise UpcPoolEmptyError("UPC池子可用UPC不足，请先到 UPC池子 添加UPC")
    bind_upc_item(item, product)
    return item


async def refresh_upc_binding(db: AsyncSession, product: Product) -> None:
    if not product.upc:
        return
    result = await db.execute(select(UpcPoolItem).where(UpcPoolItem.upc == product.upc))
    item = result.scalar_one_or_none()
    if item:
        bind_upc_item(item, product)
