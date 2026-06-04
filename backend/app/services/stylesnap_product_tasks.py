import html
import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.models import (
    AmazonListingCapture,
    AmazonStyleSnapCandidate,
    CatalogProduct,
    GigaInventory,
    GigaItem,
    GigaProductImage,
    GigaPrice,
    GigaRawSkuDetail,
    GigaSku,
    Product,
    ProductAplus,
    ProductData,
    ProductImage,
)
from app.pipeline.step2_pricing import calculate_price
from app.services.product_duplicates import find_duplicate_by_item_code
from app.services.upc_pool import ensure_product_upc


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tiff"}


@dataclass
class GigaProductDraftSyncResult:
    requested_items: int = 0
    created: int = 0
    updated: int = 0
    skipped: int = 0
    product_ids: list[int] = field(default_factory=list)
    skipped_details: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(float(str(value).replace(",", "").strip()))
    except (TypeError, ValueError):
        return None


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _json_loads(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except Exception:
        return fallback


def _strip_html(value: str | None) -> str | None:
    text = _text(value)
    if not text:
        return None
    text = re.sub(r"(?is)<br\s*/?>", "\n", text)
    text = re.sub(r"(?is)</(p|div|tr|li|table)>", "\n", text)
    text = re.sub(r"(?is)<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*", "\n", text)
    return text.strip() or None


def _attr_text(detail: dict[str, Any], key: str) -> str | None:
    attrs = detail.get("attributes") if isinstance(detail.get("attributes"), dict) else {}
    return _text(detail.get(key)) or _text(attrs.get(key)) or _text(attrs.get(key.replace("main", "Main ")))


def _category_path_from_candidate(candidate: AmazonStyleSnapCandidate) -> tuple[list[str], str | None]:
    categories: list[str] = []
    for text in (candidate.category_rank, candidate.raw_snippet):
        if not text:
            continue
        cleaned_text = re.sub(r"\s+", " ", text)
        pattern = (
            r"#?[\d,]+\s+in\s+(.+?)"
            r"(?=(?:\s+#?[\d,]+\s+in\s+| ASIN:| 品牌:| 卖家:| 配送:| 加入产品库|"
            r"近30天|销售额|FBA费用|毛利率|变体数|价格:|评分|配送时长|Color:|"
            r"Style:|Size:|商品重量|商品尺寸|包装重量|包装尺寸|上架时间|全部流量词|"
            r"自然搜索词|广告流量词|搜索推荐词|$))"
        )
        for match in re.finditer(pattern, cleaned_text, flags=re.I):
            category = re.sub(r"\([^)]*\)", "", match.group(1))
            category = re.sub(r"\s+", " ", category).strip(" >›-")
            if category and category not in categories:
                categories.append(category)
    return categories, categories[0] if categories else None


def _category_path_from_listing_capture(capture: AmazonListingCapture | None) -> tuple[list[str], str | None]:
    if not capture:
        return [], None
    categories = [str(item).strip() for item in _json_loads(capture.categories, []) if str(item).strip()]
    if categories or capture.leaf_category:
        return categories, capture.leaf_category or (categories[-1] if categories else None)
    if capture.category_rank:
        matches = re.findall(r"#?[\d,]+\s+in\s+([^#()]+)", capture.category_rank)
        cleaned = [re.sub(r"\s+", " ", item).strip(" >›-") for item in matches if item.strip()]
        if cleaned:
            return cleaned, cleaned[-1]
    return [], None


def _listing_capture_snapshot(capture: AmazonListingCapture | None) -> dict[str, Any] | None:
    if not capture:
        return None
    return {
        "capture_id": capture.id,
        "status": capture.capture_status,
        "capture_error": capture.capture_error,
        "asin": capture.asin,
        "url": capture.url,
        "title": capture.title,
        "brand": capture.brand,
        "seller": capture.seller,
        "price": capture.price,
        "rating": capture.rating,
        "review_count": capture.review_count,
        "availability": capture.availability,
        "categories": _json_loads(capture.categories, []),
        "leaf_category": capture.leaf_category,
        "category_rank": capture.category_rank,
        "bullets": _json_loads(capture.bullets_json, []),
        "description": capture.description,
        "product_details": _json_loads(capture.product_details_json, {}),
        "aplus_text": capture.aplus_text,
        "main_image_url": capture.main_image_url,
        "image_urls": _json_loads(capture.image_urls_json, []),
    }


async def _load_price_inventory(
    db: AsyncSession,
    site: str,
    fallback_batch_id: str,
    sku_codes: list[str],
    data_source_id: int | None = None,
) -> tuple[dict[str, GigaPrice], dict[str, GigaInventory]]:
    if not sku_codes:
        return {}, {}

    from app.models import GigaSyncBatch

    price_batch_result = await db.execute(
        select(GigaSyncBatch.batch_id)
        .where(GigaSyncBatch.site == site, GigaSyncBatch.status == "done", GigaSyncBatch.price_count > 0)
        .where(GigaSyncBatch.data_source_id == data_source_id if data_source_id else True)
        .order_by(GigaSyncBatch.finished_at.is_(None).asc(), GigaSyncBatch.finished_at.desc(), GigaSyncBatch.created_at.desc())
        .limit(1)
    )
    price_batch_id = price_batch_result.scalar_one_or_none() or fallback_batch_id
    inventory_batch_result = await db.execute(
        select(GigaSyncBatch.batch_id)
        .where(GigaSyncBatch.site == site, GigaSyncBatch.status == "done", GigaSyncBatch.inventory_count > 0)
        .where(GigaSyncBatch.data_source_id == data_source_id if data_source_id else True)
        .order_by(GigaSyncBatch.finished_at.is_(None).asc(), GigaSyncBatch.finished_at.desc(), GigaSyncBatch.created_at.desc())
        .limit(1)
    )
    inventory_batch_id = inventory_batch_result.scalar_one_or_none() or fallback_batch_id

    price_query = select(GigaPrice).where(GigaPrice.batch_id == price_batch_id, GigaPrice.site == site, GigaPrice.sku_code.in_(sku_codes))
    if data_source_id:
        price_query = price_query.where(GigaPrice.data_source_id == data_source_id)
    price_result = await db.execute(price_query)
    inventory_query = select(GigaInventory).where(
        GigaInventory.batch_id == inventory_batch_id,
        GigaInventory.site == site,
        GigaInventory.sku_code.in_(sku_codes),
    )
    if data_source_id:
        inventory_query = inventory_query.where(GigaInventory.data_source_id == data_source_id)
    inventory_result = await db.execute(inventory_query)
    return (
        {item.sku_code: item for item in price_result.scalars().all()},
        {item.sku_code: item for item in inventory_result.scalars().all()},
    )


def _representative_sku(item_code: str, skus: list[GigaSku], selected: list[AmazonStyleSnapCandidate]) -> GigaSku | None:
    if not skus:
        return None
    by_code = {sku.sku_code: sku for sku in skus}
    if item_code in by_code:
        return by_code[item_code]
    for sku in skus:
        if sku.is_primary_child:
            return sku
    for candidate in selected:
        if candidate.sku_code in by_code:
            return by_code[candidate.sku_code]
    return skus[0]


def _variant_rows(
    skus: list[GigaSku],
    raw_by_sku: dict[str, dict[str, Any]],
    prices_by_sku: dict[str, GigaPrice],
    inventory_by_sku: dict[str, GigaInventory],
) -> list[dict[str, Any]]:
    variants: list[dict[str, Any]] = []
    for sku in skus:
        detail = raw_by_sku.get(sku.sku_code, {})
        price = prices_by_sku.get(sku.sku_code)
        inventory = inventory_by_sku.get(sku.sku_code)
        variants.append({
            "sku": sku.sku_code,
            "item_code": sku.item_code,
            "title": sku.product_name,
            "color": _text(detail.get("mainColor")) or _json_loads(sku.variation_attributes_json, {}).get("Main Color"),
            "material": _text(detail.get("mainMaterial")),
            "attributes": _json_loads(sku.attributes_json, {}),
            "variation_attributes": _json_loads(sku.variation_attributes_json, {}),
            "main_image_url": sku.main_image_url,
            "price": price.effective_price if price else None,
            "shipping_fee": price.shipping_fee if price else None,
            "stock": inventory.stock_qty if inventory else None,
        })
    return variants


def _pricing_values(skus: list[GigaSku], prices_by_sku: dict[str, GigaPrice]) -> tuple[float | None, float | None, float | None, float | None, float | None]:
    values: list[tuple[float, float | None, float | None, float | None]] = []
    for sku in skus:
        price = prices_by_sku.get(sku.sku_code)
        if not price:
            continue
        value_total = price.effective_price or price.price
        shipping = price.shipping_fee or price.estimated_shipping_fee or price.shipping_fee_max or price.shipping_fee_min
        if value_total is None:
            continue
        estimated_total = value_total + shipping if shipping is not None else None
        values.append((value_total, estimated_total, shipping, price.shipping_fee_min, price.shipping_fee_max))
    if not values:
        return None, None, None, None, None
    value_total = max(item[0] for item in values)
    estimated_candidates = [item[1] for item in values if item[1] is not None]
    shipping_candidates = [item[2] for item in values if item[2] is not None]
    shipping_min_candidates = [item[3] for item in values if item[3] is not None]
    shipping_max_candidates = [item[4] for item in values if item[4] is not None]
    return (
        value_total,
        max(estimated_candidates) if estimated_candidates else None,
        max(shipping_candidates) if shipping_candidates else None,
        min(shipping_min_candidates) if shipping_min_candidates else None,
        max(shipping_max_candidates) if shipping_max_candidates else None,
    )


def _package_entries_from_detail(detail: dict[str, Any], sku_code: str | None = None) -> list[dict[str, Any]]:
    length = _float(detail.get("length"))
    width = _float(detail.get("width"))
    height = _float(detail.get("height"))
    weight = _float(detail.get("weight"))
    if not (length and width and height and weight):
        return []

    raw_length_unit = str(detail.get("lengthUnit") or detail.get("unit_length") or "in").strip()
    raw_weight_unit = str(detail.get("weightUnit") or detail.get("unit_weight") or "lb").strip()
    length_unit = "in." if raw_length_unit.lower().startswith("in") or "英寸" in raw_length_unit else raw_length_unit
    weight_unit = "lbs." if raw_weight_unit.lower().startswith("lb") or "磅" in raw_weight_unit else raw_weight_unit
    return [{
        "code": sku_code or detail.get("sku") or "",
        "qty": "1",
        "length": length,
        "width": width,
        "height": height,
        "weight_value": weight,
        "length_unit": length_unit,
        "weight_unit": weight_unit,
        "dimensions": f"{length:g} * {width:g} * {height:g} {length_unit} {weight:g} {weight_unit}",
        "weight": f"{weight:g} {weight_unit}",
    }]


def _giga_image_urls(detail: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    for value in [detail.get("mainImageUrl"), *(detail.get("imageUrls") or [])]:
        url = _text(value)
        if url and url.startswith(("http://", "https://")) and url not in urls:
            urls.append(url)
    return urls


def _giga_image_extension(url: str) -> str:
    suffix = Path(unquote(urlparse(url).path)).suffix.lower()
    return suffix if suffix in IMAGE_EXTENSIONS else ".jpg"


def _giga_local_image_path(site: str, item_code: str, image_url: str) -> str | None:
    item_dir = settings.PRODUCT_BASE_DIR / "GIGA" / site.upper() / item_code
    name_prefix = f"source_image_{hashlib.sha256(image_url.encode('utf-8')).hexdigest()[:16]}"
    expected = item_dir / f"{name_prefix}{_giga_image_extension(image_url)}"
    if expected.is_file():
        return str(expected)
    matches = sorted(item_dir.glob(f"{name_prefix}.*"))
    for match in matches:
        if match.is_file():
            return str(match)
    return None


def _is_remote_url(value: str | None) -> bool:
    return bool(value and re.match(r"^https?://", str(value).strip(), flags=re.I))


def _giga_listing_image_entries(detail: dict[str, Any], item_code: str, site: str) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    for index, url in enumerate(_giga_image_urls(detail), start=1):
        path = _giga_local_image_path(site, item_code, url)
        if not path or path in seen_paths:
            continue
        seen_paths.add(path)
        entries.append({
            "sort_order": index,
            "image_url": url,
            "local_path": path,
            "source": "giga_listing_imageUrls",
        })
    return entries


def _giga_listing_image_paths(detail: dict[str, Any], item_code: str, site: str) -> list[str]:
    return [entry["local_path"] for entry in _giga_listing_image_entries(detail, item_code, site)]


async def _giga_image_entries_from_table(
    db: AsyncSession,
    batch_id: str,
    site: str,
    item_code: str,
    *,
    data_source_id: int | None = None,
    include_pending: bool = False,
) -> list[dict[str, Any]]:
    query = select(GigaProductImage).where(
        GigaProductImage.batch_id == batch_id,
        GigaProductImage.site == site,
        GigaProductImage.item_code == item_code,
    )
    if data_source_id:
        query = query.where(GigaProductImage.data_source_id == data_source_id)
    if not include_pending:
        query = query.where(
            GigaProductImage.local_path.is_not(None),
            GigaProductImage.download_status == "done",
        )
    result = await db.execute(query.order_by(GigaProductImage.sort_order.is_(None).asc(), GigaProductImage.sort_order.asc(), GigaProductImage.id.asc()))
    entries: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    for row in result.scalars().all():
        local_path = _text(row.local_path)
        image_url = _text(row.image_url)
        path = local_path or image_url
        if not path or path in seen_paths:
            continue
        seen_paths.add(path)
        entries.append({
            "sort_order": row.sort_order or len(entries) + 1,
            "image_url": image_url,
            "local_path": local_path,
            "path": path,
            "download_status": row.download_status,
            "source": row.image_type or "giga_product_images",
            "sku_code": row.sku_code,
        })
    return entries


def _material_dir(item_code: str, image_paths: list[str]) -> str:
    local_paths = [path for path in image_paths if path and not _is_remote_url(path)]
    if local_paths:
        return str(Path(local_paths[0]).expanduser().resolve().parent)
    return str(settings.PRODUCT_BASE_DIR / "GIGA" / "US" / item_code)


def _prefill_pricing(pd: ProductData) -> None:
    if pd.value_total and pd.estimated_total:
        calc = calculate_price(pd.estimated_total, pd.value_total)
        if calc:
            pd.suggested_price = calc["suggested_price"]
            pd.cost_total = calc["cost_total"]
            pd.profit = calc["profit"]
            pd.profit_rate = calc["profit_rate"]
            pd.pricing_detail = _json_dumps(calc["breakdown"])


async def create_product_draft_from_giga_item(
    db: AsyncSession,
    *,
    batch_id: str,
    site: str = "US",
    data_source_id: int | None = None,
    item_code: str,
    brand: str | None = None,
) -> tuple[Product, bool]:
    """Create a product draft so the detail page can confirm the search/listing images."""
    normalized_site = site.strip().upper()
    normalized_item_code = item_code.strip()

    giga_item_query = select(GigaItem).where(
        GigaItem.batch_id == batch_id,
        GigaItem.site == normalized_site,
        GigaItem.item_code == normalized_item_code,
    )
    if data_source_id:
        giga_item_query = giga_item_query.where(GigaItem.data_source_id == data_source_id)
    giga_item_result = await db.execute(giga_item_query)
    giga_item = giga_item_result.scalar_one_or_none()
    if not giga_item:
        raise ValueError("GIGA Item 不存在，请先拉取商品")

    duplicate = await find_duplicate_by_item_code(db, normalized_item_code, data_source_id=giga_item.data_source_id)

    sku_result = await db.execute(
        select(GigaSku)
        .where(
            GigaSku.batch_id == batch_id,
            GigaSku.site == normalized_site,
            GigaSku.data_source_id == giga_item.data_source_id,
            GigaSku.giga_item_id == giga_item.id,
        )
        .order_by(GigaSku.child_sequence.is_(None).asc(), GigaSku.child_sequence.asc(), GigaSku.sku_code.asc())
    )
    skus = list(sku_result.scalars().all())
    if not skus:
        raise ValueError("缺少 GIGA SKU 明细，不能创建商品草稿")

    representative = _representative_sku(normalized_item_code, skus, [])
    if not representative:
        raise ValueError("缺少代表 SKU，不能创建商品草稿")

    raw_by_sku: dict[str, dict[str, Any]] = {}
    raw_result = await db.execute(
        select(GigaRawSkuDetail).where(
            GigaRawSkuDetail.batch_id == batch_id,
            GigaRawSkuDetail.site == normalized_site,
            GigaRawSkuDetail.data_source_id == giga_item.data_source_id,
            GigaRawSkuDetail.sku_code.in_([sku.sku_code for sku in skus]),
        )
    )
    for raw in raw_result.scalars().all():
        raw_by_sku[raw.sku_code] = _json_loads(raw.data_json, {})

    detail = raw_by_sku.get(representative.sku_code, {})
    prices_by_sku, inventory_by_sku = await _load_price_inventory(
        db,
        normalized_site,
        batch_id,
        [sku.sku_code for sku in skus],
        data_source_id=giga_item.data_source_id,
    )
    giga_listing_image_entries = _giga_listing_image_entries(detail, normalized_item_code, normalized_site)
    if not giga_listing_image_entries:
        giga_listing_image_entries = await _giga_image_entries_from_table(
            db,
            batch_id,
            normalized_site,
            normalized_item_code,
            data_source_id=giga_item.data_source_id,
            include_pending=True,
        )
    image_paths = [entry.get("path") or entry.get("local_path") or entry.get("image_url") for entry in giga_listing_image_entries]
    image_paths = [path for path in image_paths if path]
    value_total, estimated_total, shipping_cost, shipping_min, shipping_max = _pricing_values(skus, prices_by_sku)
    stock_values = [
        inventory_by_sku[sku.sku_code].stock_qty
        for sku in skus
        if sku.sku_code in inventory_by_sku and inventory_by_sku[sku.sku_code].stock_qty is not None
    ]

    now = datetime.now()
    created = duplicate is None
    if duplicate:
        product_result = await db.execute(
            select(Product)
            .options(selectinload(Product.data), selectinload(Product.images), selectinload(Product.aplus))
            .where(Product.id == duplicate.product.id)
        )
        product = product_result.scalar_one()
        had_data = product.data is not None
        had_images = product.images is not None
        had_aplus = product.aplus is not None
    else:
        product = Product(
            gigab2b_url=f"https://www.gigab2b.com/product-detail/{normalized_item_code}",
            gigab2b_product_id=normalized_item_code,
            competitor_asin=None,
            brand=brand or settings.DEFAULT_BRAND,
            status="created",
            current_step=0,
            error_message="待确认商品图片",
            created_at=now,
            updated_at=now,
        )
        db.add(product)
        await db.flush()
        had_data = False
        had_images = False
        had_aplus = False

    product.gigab2b_url = product.gigab2b_url or f"https://www.gigab2b.com/product-detail/{normalized_item_code}"
    product.gigab2b_product_id = product.gigab2b_product_id or normalized_item_code
    if product.status == "created" and product.current_step <= 0:
        product.error_message = product.error_message or "待确认商品图片"
    product.updated_at = now

    pd = product.data if had_data else ProductData(product_id=product.id)
    pd.item_code = normalized_item_code
    pd.title = pd.title or representative.product_name or giga_item.item_name
    pd.color = pd.color or _text(detail.get("mainColor"))
    pd.material = pd.material or _text(detail.get("mainMaterial"))
    pd.product_type = pd.product_type or _text(detail.get("category")) or giga_item.category
    pd.dimension_length = pd.dimension_length if pd.dimension_length is not None else _float(detail.get("assembledLength") or detail.get("length"))
    pd.dimension_width = pd.dimension_width if pd.dimension_width is not None else _float(detail.get("assembledWidth") or detail.get("width"))
    pd.dimension_height = pd.dimension_height if pd.dimension_height is not None else _float(detail.get("assembledHeight") or detail.get("height"))
    pd.weight = pd.weight if pd.weight is not None else _float(detail.get("assembledWeight") or detail.get("weight"))
    package_entries = _package_entries_from_detail(detail, representative.sku_code)
    if package_entries:
        pd.packages = _json_dumps(package_entries)
    pd.value_total = value_total
    pd.estimated_total = estimated_total
    pd.shipping_cost = shipping_cost
    pd.shipping_cost_min = shipping_min
    pd.shipping_cost_max = shipping_max
    if not pd.features:
        pd.features = _json_dumps(detail.get("characteristics") or [])
    if not pd.description:
        pd.description = _strip_html(detail.get("description"))
    pd.variants = _json_dumps(_variant_rows(skus, raw_by_sku, prices_by_sku, inventory_by_sku))
    existing_snapshot = _json_loads(pd.gigab2b_raw_snapshot, {})
    if not isinstance(existing_snapshot, dict):
        existing_snapshot = {}
    existing_snapshot.update({
        "source": "giga_openapi_prefill_draft",
        "batch_id": batch_id,
        "site": normalized_site,
        "data_source_id": giga_item.data_source_id,
        "data_source_name": giga_item.data_source_name,
        "fulfillment_mode": giga_item.fulfillment_mode,
        "item": {
            "item_code": normalized_item_code,
            "sku_codes": [sku.sku_code for sku in skus],
            "raw_group": _json_loads(giga_item.raw_group_json, {}),
        },
        "representative_sku": representative.sku_code,
        "giga_listing_images": giga_listing_image_entries,
    })
    pd.gigab2b_raw_snapshot = _json_dumps(existing_snapshot)
    pd.stock = sum(stock_values) if stock_values else None
    pd.seller = pd.seller or "GIGA"
    pd.origin = pd.origin or _text(detail.get("placeOfOrigin"))
    pd.image_count = len(image_paths) or len(detail.get("imageUrls") or [])
    pd.material_dir = _material_dir(normalized_item_code, image_paths)
    pd.collected_at = now
    _prefill_pricing(pd)
    product.data = pd

    pi = product.images if had_images else ProductImage(product_id=product.id)
    pi.gallery_order = _json_dumps(image_paths)
    pi.vlm_model = settings.VLM_MODEL
    product.images = pi

    if not had_data:
        db.add(pd)
    if not had_images:
        db.add(pi)
    if not had_aplus:
        db.add(ProductAplus(product_id=product.id))
    await db.commit()
    await db.refresh(product)
    return product, created


async def upsert_product_drafts_from_giga_batch(
    db: AsyncSession,
    *,
    batch_id: str,
    site: str = "US",
    data_source_id: int | None = None,
    brand: str | None = None,
) -> GigaProductDraftSyncResult:
    normalized_site = site.strip().upper()
    query = select(GigaItem).where(GigaItem.batch_id == batch_id, GigaItem.site == normalized_site)
    if data_source_id:
        query = query.where(GigaItem.data_source_id == data_source_id)
    query = query.order_by(GigaItem.item_code.asc())
    result = await db.execute(query)
    items = [
        {
            "item_code": item.item_code,
        }
        for item in result.scalars().all()
    ]

    sync_result = GigaProductDraftSyncResult(requested_items=len(items))
    for item in items:
        item_code = item["item_code"]
        if not item_code:
            sync_result.skipped += 1
            sync_result.skipped_details.append("缺少 item_code，跳过")
            continue
        try:
            product, created = await create_product_draft_from_giga_item(
                db,
                batch_id=batch_id,
                site=normalized_site,
                data_source_id=data_source_id,
                item_code=item_code,
                brand=brand,
            )
            sync_result.product_ids.append(product.id)
            if created:
                sync_result.created += 1
            else:
                sync_result.updated += 1
        except Exception as exc:
            await db.rollback()
            sync_result.skipped += 1
            sync_result.errors.append(f"{item_code}: {type(exc).__name__}: {exc}")
    return sync_result
