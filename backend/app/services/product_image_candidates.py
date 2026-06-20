from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import GigaProductImage, Product

PRIMARY_TYPES = {"main", "gallery"}
VARIANT_TYPES = {"variant_main", "variant_gallery"}
LOW_PRIORITY_TYPES = {"file", "brand", "unknown"}


def json_loads(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except Exception:
        return fallback


def normalize_image_path(item: Any) -> str:
    if isinstance(item, str):
        return item.strip()
    if isinstance(item, dict):
        return str(item.get("image_url") or item.get("path") or item.get("local_path") or "").strip()
    return ""


def _text(value: Any) -> str:
    return str(value or "").strip()


def _remote_image_urls(detail: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    for value in [detail.get("mainImageUrl"), *(detail.get("imageUrls") or [])]:
        url = _text(value)
        if url.startswith(("http://", "https://")) and url not in urls:
            urls.append(url)
    return urls


def _candidate_asset_source(image_type: Any) -> str:
    candidate_type = str(image_type or "unknown").strip().lower()
    if candidate_type in PRIMARY_TYPES | VARIANT_TYPES:
        return "giga_detail_gallery"
    if candidate_type == "file":
        return "giga_material_package"
    if candidate_type == "brand":
        return "giga_brand_asset"
    return "unknown"


def _classify_candidate_type(raw_type: Any, sku_code: Any, representative_sku: str | None) -> str:
    candidate_type = str(raw_type or "unknown").strip().lower()
    sku_text = _text(sku_code)
    if representative_sku and sku_text and sku_text != representative_sku and candidate_type in PRIMARY_TYPES:
        return f"variant_{candidate_type}"
    if candidate_type in PRIMARY_TYPES | VARIANT_TYPES | LOW_PRIORITY_TYPES:
        return candidate_type
    return "unknown"


def _candidate_rank(candidate: dict[str, Any]) -> tuple[int, int, int, str]:
    image_type = str(candidate.get("image_type") or "unknown").strip().lower()
    source = str(candidate.get("source") or "")
    sort_order = candidate.get("sort_order")
    try:
        sort_value = int(sort_order)
    except (TypeError, ValueError):
        sort_value = 9999
    is_rep = bool(candidate.get("is_representative_sku"))
    if image_type in PRIMARY_TYPES and is_rep:
        tier = 1
    elif image_type in VARIANT_TYPES:
        tier = 2
    elif source in {"giga_detail", "giga_listing_images", "giga_listing_imageUrls"}:
        tier = 3
    elif image_type in LOW_PRIORITY_TYPES:
        tier = 4
    else:
        tier = 5
    url_bonus = 0 if candidate.get("image_url") else 1
    return tier, url_bonus, sort_value, normalize_image_path(candidate)


def _dedupe_key(candidate: dict[str, Any]) -> str:
    image_url = _text(candidate.get("image_url"))
    if image_url:
        return f"url:{image_url}"
    path = _text(candidate.get("path") or candidate.get("local_path"))
    return f"path:{path}"


def _add_candidate(candidates: list[dict[str, Any]], seen: dict[str, dict[str, Any]], candidate: dict[str, Any]) -> None:
    path = normalize_image_path(candidate)
    image_url = _text(candidate.get("image_url"))
    if not path and not image_url:
        return
    candidate = {
        "path": image_url or path,
        "image_url": image_url or None,
        "local_path": _text(candidate.get("local_path")) or None,
        "image_type": _classify_candidate_type(candidate.get("image_type"), candidate.get("sku_code"), candidate.get("representative_sku")),
        "source": _text(candidate.get("source")) or "unknown",
        "asset_source": _text(candidate.get("asset_source")) or None,
        "sku_code": _text(candidate.get("sku_code")) or None,
        "sort_order": candidate.get("sort_order"),
        "batch_id": _text(candidate.get("batch_id")) or None,
        "site": _text(candidate.get("site")) or None,
        "item_code": _text(candidate.get("item_code")) or None,
        "representative_sku": _text(candidate.get("representative_sku")) or None,
        "is_representative_sku": bool(candidate.get("is_representative_sku")),
        "download_status": _text(candidate.get("download_status")) or None,
    }
    candidate["asset_source"] = candidate["asset_source"] or _candidate_asset_source(candidate["image_type"])
    key = _dedupe_key(candidate)
    if key in seen:
        sources = seen[key].setdefault("merged_sources", [])
        sources.append({
            "source": candidate["source"],
            "asset_source": candidate["asset_source"],
            "image_type": candidate["image_type"],
            "sku_code": candidate["sku_code"],
        })
        return
    seen[key] = candidate
    candidates.append(candidate)


def _snapshot_context(product: Product) -> tuple[dict[str, Any], str | None, str | None, int | None, str | None]:
    snapshot = json_loads(product.data.gigab2b_raw_snapshot, {}) if product.data else {}
    if not isinstance(snapshot, dict):
        snapshot = {}
    batch_id = _text(snapshot.get("batch_id")) or product.source_batch_id
    site = (_text(snapshot.get("site")) or product.source_site or "").upper()
    data_source_id = snapshot.get("data_source_id") or product.source_data_source_id
    try:
        data_source_id = int(data_source_id) if data_source_id else None
    except (TypeError, ValueError):
        data_source_id = None
    representative_sku = _text(snapshot.get("representative_sku")) or (product.data.item_code if product.data else None)
    return snapshot, batch_id, site, data_source_id, representative_sku


async def collect_product_image_candidates(db: AsyncSession, product: Product) -> list[dict[str, Any]]:
    if not product.data:
        return []
    snapshot, batch_id, site, data_source_id, representative_sku = _snapshot_context(product)
    item_code = _text(product.data.item_code or product.gigab2b_product_id)
    candidates: list[dict[str, Any]] = []
    seen: dict[str, dict[str, Any]] = {}

    if item_code:
        query = select(GigaProductImage).where(GigaProductImage.item_code == item_code)
        if batch_id:
            query = query.where(GigaProductImage.batch_id == batch_id)
        if site:
            query = query.where(GigaProductImage.site == site)
        if data_source_id:
            query = query.where(GigaProductImage.data_source_id == data_source_id)
        result = await db.execute(
            query.order_by(
                GigaProductImage.sort_order.is_(None).asc(),
                GigaProductImage.sort_order.asc(),
                GigaProductImage.id.asc(),
            )
        )
        for row in result.scalars().all():
            _add_candidate(candidates, seen, {
                "path": row.image_url or row.local_path,
                "image_url": row.image_url,
                "local_path": row.local_path,
                "image_type": row.image_type or "unknown",
                "source": "giga_product_images",
                "sku_code": row.sku_code,
                "sort_order": row.sort_order,
                "download_status": row.download_status,
                "batch_id": row.batch_id,
                "site": row.site,
                "item_code": row.item_code,
                "representative_sku": representative_sku,
                "is_representative_sku": bool(representative_sku and row.sku_code == representative_sku),
            })

    detail = snapshot.get("detail") if isinstance(snapshot.get("detail"), dict) else snapshot
    for index, url in enumerate(_remote_image_urls(detail), start=1):
        _add_candidate(candidates, seen, {
            "path": url,
            "image_url": url,
            "image_type": "main" if index == 1 else "gallery",
            "source": "giga_detail",
            "asset_source": "giga_detail_gallery",
            "sku_code": representative_sku,
            "sort_order": index,
            "batch_id": batch_id,
            "site": site,
            "item_code": item_code,
            "representative_sku": representative_sku,
            "is_representative_sku": True,
        })

    snapshot_images = snapshot.get("giga_listing_images")
    if isinstance(snapshot_images, list):
        for index, item in enumerate(snapshot_images, start=1):
            if not isinstance(item, dict):
                continue
            sku_code = item.get("sku_code")
            raw_type = item.get("image_type") or item.get("source") or ("main" if index == 1 else "gallery")
            _add_candidate(candidates, seen, {
                "path": item.get("image_url") or item.get("path") or item.get("local_path"),
                "image_url": item.get("image_url"),
                "local_path": item.get("local_path"),
                "image_type": raw_type,
                "source": item.get("source") or "giga_listing_images",
                "asset_source": item.get("asset_source") or "giga_detail_gallery",
                "sku_code": sku_code,
                "sort_order": item.get("sort_order") or index,
                "download_status": item.get("download_status"),
                "batch_id": batch_id,
                "site": site,
                "item_code": item_code,
                "representative_sku": representative_sku,
                "is_representative_sku": bool(representative_sku and sku_code == representative_sku),
            })

    gallery_order = json_loads(product.images.gallery_order, []) if product.images else []
    if isinstance(gallery_order, list):
        for index, item in enumerate(gallery_order, start=1):
            path = normalize_image_path(item)
            if not path:
                continue
            if isinstance(item, dict):
                image_type = item.get("image_type") or item.get("source") or ("main" if index == 1 else "gallery")
                _add_candidate(candidates, seen, {
                    **item,
                    "path": path,
                    "image_type": image_type,
                    "source": item.get("source") or "saved_gallery_order",
                    "sort_order": item.get("sort_order") or index,
                    "representative_sku": item.get("representative_sku") or representative_sku,
                })
            else:
                _add_candidate(candidates, seen, {
                    "path": path,
                    "image_type": "main" if index == 1 else "gallery",
                    "source": "saved_gallery_order",
                    "asset_source": "saved_gallery_order",
                    "sort_order": index,
                    "representative_sku": representative_sku,
                    "is_representative_sku": True,
                })

    return sorted(candidates, key=_candidate_rank)
