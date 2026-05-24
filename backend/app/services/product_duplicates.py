import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CatalogProduct, Product, ProductData


@dataclass
class ProductDuplicate:
    product: Product
    field: str
    value: str

    @property
    def message(self) -> str:
        return f"{field_label(self.field)} {self.value} 已存在于任务 {self.product.id}"


def field_label(field: str) -> str:
    return {
        "gigab2b_product_id": "大建云仓商品ID",
        "item_code": "商品Code",
    }.get(field, field)


def extract_gigab2b_product_id(url: str | None) -> str | None:
    if not url:
        return None
    parsed = urlparse(url)
    product_id = (parse_qs(parsed.query).get("product_id") or [None])[0]
    if product_id:
        return product_id.strip() or None

    patterns = (
        r"[?&]product_id=([A-Za-z0-9_-]+)",
        r"/product/detail/([A-Za-z0-9_-]+)",
        r"/product-detail/([A-Za-z0-9_-]+)",
    )
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1).strip()
    return None


def extract_gigab2b_item_code_from_url(url: str | None) -> str | None:
    if not url:
        return None
    match = re.search(r"/product(?:-|/)detail/([A-Za-z0-9_-]+)", url)
    if not match:
        return None
    value = match.group(1).strip()
    return value if value and not value.isdigit() else None


def normalize_item_code(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


async def find_duplicate_by_gigab2b_product_id(
    db: AsyncSession,
    gigab2b_product_id: str | None,
    *,
    exclude_product_id: int | None = None,
) -> ProductDuplicate | None:
    if not gigab2b_product_id:
        return None

    query = select(Product).where(Product.gigab2b_product_id == gigab2b_product_id)
    if exclude_product_id is not None:
        query = query.where(Product.id != exclude_product_id)
    result = await db.execute(query.order_by(Product.id.asc()).limit(1))
    product = result.scalar_one_or_none()
    if product:
        return ProductDuplicate(product=product, field="gigab2b_product_id", value=gigab2b_product_id)

    fallback_query = select(Product).where(Product.gigab2b_product_id.is_(None))
    if exclude_product_id is not None:
        fallback_query = fallback_query.where(Product.id != exclude_product_id)
    fallback_result = await db.execute(fallback_query.order_by(Product.id.asc()))
    for candidate in fallback_result.scalars().all():
        if extract_gigab2b_product_id(candidate.gigab2b_url) == gigab2b_product_id:
            return ProductDuplicate(product=candidate, field="gigab2b_product_id", value=gigab2b_product_id)
    return None


async def find_duplicate_by_item_code(
    db: AsyncSession,
    item_code: str | None,
    *,
    exclude_product_id: int | None = None,
) -> ProductDuplicate | None:
    normalized = normalize_item_code(item_code)
    if not normalized:
        return None

    query = (
        select(Product)
        .join(ProductData, ProductData.product_id == Product.id)
        .where(ProductData.item_code == normalized)
    )
    if exclude_product_id is not None:
        query = query.where(Product.id != exclude_product_id)
    result = await db.execute(query.order_by(Product.id.asc()).limit(1))
    product = result.scalar_one_or_none()
    if product:
        return ProductDuplicate(product=product, field="item_code", value=normalized)

    catalog_query = (
        select(Product)
        .join(CatalogProduct, CatalogProduct.source_product_id == Product.id)
        .where(CatalogProduct.item_code == normalized)
    )
    if exclude_product_id is not None:
        catalog_query = catalog_query.where(Product.id != exclude_product_id)
    catalog_result = await db.execute(catalog_query.order_by(Product.id.asc()).limit(1))
    product = catalog_result.scalar_one_or_none()
    if product:
        return ProductDuplicate(product=product, field="item_code", value=normalized)
    return None
