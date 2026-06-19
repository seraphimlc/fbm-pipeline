from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.database import async_session
from app.models import Product
from app.services.product_image_candidates import collect_product_image_candidates, normalize_image_path
from app.services.product_image_vlm import (
    analyze_contact_sheet,
    analyze_image_url_batch,
    build_contact_sheets,
    build_image_url_batches,
    download_image_records,
    is_remote_url,
)

logger = logging.getLogger(__name__)


AUTO_IMAGE_SELECTION_PROMPT = """Analyze these candidate images and select Amazon listing images.

Product: {title}
Brand: {brand}
Category: {category}
Known product facts:
{facts}

Candidate metadata:
{candidates}

Select exactly one best MAIN image and up to 8 gallery images from this batch.

MAIN image hard baseline:
- product identity must be clear;
- avoid lifestyle, packaging-only, labels, box/shipping packaging, overlays, watermarks, collage, wrong variant, blurry or low-quality images;
- prefer clean product-only images on white/neutral background.

Gallery images should answer buyer doubts: alternate angle, size/scale, material/detail, function/use, lifestyle/context, package contents, or proof. Reject duplicate, wrong-variant, brand-only, packaging-only, non-product, low-quality, or risky images.

Output valid JSON only:
{{
  "selected_main": {{
    "image_id": "#01",
    "score": 0.95,
    "reason": "",
    "risk_flags": [],
    "main_image_valid": true
  }},
  "selected_gallery": [
    {{
      "image_id": "#02",
      "role": "alternate_angle|size_scale|material_detail|function_use|lifestyle|package_contents|proof",
      "score": 0.88,
      "reason": "",
      "risk_flags": []
    }}
  ],
  "rejected": [
    {{
      "image_id": "#10",
      "reason": "duplicate|packaging|wrong_variant|low_quality|brand_asset|not_product"
    }}
  ],
  "confidence": "high|medium|low",
  "warnings": []
}}"""

AUTO_IMAGE_SELECTION_SYSTEM_PROMPT = """You are an expert Amazon listing image selector.
Choose product images for an Amazon listing from candidate images.
Keep automatic selection conservative: reject low-confidence or risky main images.
Output valid JSON only, no markdown fences."""


class AutoImageSelectionError(RuntimeError):
    """Raised when automatic image selection cannot safely advance workflow."""


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _json_loads(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except Exception:
        return fallback


def _product_facts(product: Product) -> str:
    data = product.data
    if not data:
        return "{}"
    facts = {
        "item_code": data.item_code,
        "title": data.title,
        "color": data.color,
        "material": data.material,
        "product_type": data.product_type,
        "dimensions": data.dimensions,
        "weight": data.weight,
        "features": _json_loads(data.features, data.features),
    }
    return _json_dumps({key: value for key, value in facts.items() if value})


def _source_filename(source: str, index: int) -> str:
    if is_remote_url(source):
        name = Path(unquote(urlparse(source).path)).name
    else:
        name = Path(source).expanduser().name
    return name or f"candidate_image_{index:02d}.jpg"


def _candidate_prompt_lines(records: list[dict[str, Any]]) -> str:
    lines = []
    for record in records:
        candidate = record["candidate"]
        lines.append(
            f"{record['image_id']} path={candidate.get('path') or ''} "
            f"type={candidate.get('image_type') or ''} source={candidate.get('source') or ''} "
            f"asset_source={candidate.get('asset_source') or ''} sku={candidate.get('sku_code') or ''} "
            f"sort_order={candidate.get('sort_order') or ''}"
        )
    return "\n".join(lines)


def _records_from_candidates(candidates: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    records: list[dict[str, Any]] = []
    warnings: list[str] = []
    for index, candidate in enumerate(candidates, start=1):
        source = normalize_image_path(candidate)
        if not source:
            warnings.append(f"候选 #{index} 缺少 path/image_url")
            continue
        if not is_remote_url(source) and not Path(source).expanduser().is_file():
            warnings.append(f"本地候选不可访问: {source}")
            continue
        records.append({
            "image_id": f"#{len(records) + 1:02d}",
            "filename": _source_filename(source, len(records) + 1),
            "path": source,
            "candidate": candidate,
        })
    return records, warnings


def _score(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _entry_for_selection(item: dict[str, Any], records_by_id: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    image_id = str(item.get("image_id") or item.get("sheet_label") or "").strip()
    record = records_by_id.get(image_id)
    if not record:
        path = str(item.get("path") or item.get("image_url") or "").strip()
        record = next((candidate for candidate in records_by_id.values() if candidate.get("path") == path), None)
    if not record:
        return None
    candidate = record["candidate"]
    return {
        "path": candidate.get("path") or record["path"],
        "image_url": candidate.get("image_url"),
        "image_id": record["image_id"],
        "score": _score(item.get("score")),
        "reason": str(item.get("reason") or item.get("decision_reason") or "").strip(),
        "risk_flags": item.get("risk_flags") if isinstance(item.get("risk_flags"), list) else [],
        "candidate": candidate,
        "main_image_valid": item.get("main_image_valid", True),
    }


def _normalize_batch_result(raw: dict[str, Any], batch_records: list[dict[str, Any]]) -> dict[str, Any]:
    records_by_id = {record["image_id"]: record for record in batch_records}
    main = raw.get("selected_main") if isinstance(raw.get("selected_main"), dict) else None
    selected_main = _entry_for_selection(main, records_by_id) if main else None
    gallery: list[dict[str, Any]] = []
    for item in raw.get("selected_gallery") or []:
        if not isinstance(item, dict):
            continue
        entry = _entry_for_selection(item, records_by_id)
        if not entry:
            continue
        entry["role"] = str(item.get("role") or "proof")
        gallery.append(entry)
    rejected: list[dict[str, Any]] = []
    for item in raw.get("rejected") or []:
        if not isinstance(item, dict):
            continue
        entry = _entry_for_selection(item, records_by_id)
        if not entry:
            continue
        rejected.append({
            "path": entry["path"],
            "image_url": entry.get("image_url"),
            "image_id": entry["image_id"],
            "reason": str(item.get("reason") or "").strip() or "not_selected",
        })
    return {
        "selected_main": selected_main,
        "selected_gallery": gallery,
        "rejected": rejected,
        "confidence": str(raw.get("confidence") or "medium").strip().lower(),
        "warnings": raw.get("warnings") if isinstance(raw.get("warnings"), list) else [],
    }


def _merge_batch_results(batch_results: list[dict[str, Any]], contact_sheets: list[dict[str, Any]], warnings: list[str], model: str) -> dict[str, Any]:
    main_candidates = [item["selected_main"] for item in batch_results if item.get("selected_main")]
    if not main_candidates:
        raise AutoImageSelectionError("VLM 未返回可用主图")
    selected_main = max(main_candidates, key=lambda item: _score(item.get("score")))
    if selected_main.get("main_image_valid") is False:
        raise AutoImageSelectionError("VLM 判定主图不满足 Amazon 主图底线")
    hard_flags = {"main_hard_reject", "wrong_variant", "not_product", "packaging_only", "low_quality"}
    if hard_flags.intersection({str(flag).strip().lower() for flag in selected_main.get("risk_flags") or []}):
        raise AutoImageSelectionError("VLM 主图风险标记不允许自动推进")

    gallery_candidates: list[dict[str, Any]] = []
    for result in batch_results:
        gallery_candidates.extend(result.get("selected_gallery") or [])
    gallery_candidates = sorted(gallery_candidates, key=lambda item: _score(item.get("score")), reverse=True)
    gallery: list[dict[str, Any]] = []
    seen = {selected_main["path"]}
    for item in gallery_candidates:
        path = item.get("path")
        if not path or path in seen:
            continue
        seen.add(path)
        gallery.append(item)
        if len(gallery) >= 8:
            break

    rejected: list[dict[str, Any]] = []
    for result in batch_results:
        rejected.extend(result.get("rejected") or [])

    confidences = [str(result.get("confidence") or "medium").lower() for result in batch_results]
    confidence = "low" if "low" in confidences else ("medium" if "medium" in confidences else "high")
    if confidence == "low":
        raise AutoImageSelectionError("VLM 自动选图低置信度，需人工纠偏")

    return {
        "selected_main": {key: value for key, value in selected_main.items() if key not in {"candidate", "main_image_valid"}},
        "selected_gallery": [{key: value for key, value in item.items() if key != "candidate"} for item in gallery],
        "rejected": rejected,
        "confidence": confidence,
        "warnings": [*warnings, *[warning for result in batch_results for warning in result.get("warnings") or []]],
        "contact_sheets": contact_sheets,
        "model": model,
    }


async def _load_product(db: AsyncSession, product_id: int) -> Product:
    result = await db.execute(
        select(Product)
        .where(Product.id == product_id)
        .options(selectinload(Product.data), selectinload(Product.images), selectinload(Product.aplus), selectinload(Product.catalog_item))
    )
    product = result.scalar_one_or_none()
    if not product:
        raise AutoImageSelectionError(f"商品不存在: {product_id}")
    return product


async def _run_with_db(db: AsyncSession, product_id: int) -> dict[str, Any]:
    product = await _load_product(db, product_id)
    candidates = await collect_product_image_candidates(db, product)
    if not candidates:
        raise AutoImageSelectionError("没有可用于自动选图的候选图片")

    records, warnings = _records_from_candidates(candidates)
    if not records:
        raise AutoImageSelectionError("候选图片均不可访问")

    data = product.data
    material_dir = Path(data.material_dir or settings.PRODUCT_BASE_DIR / "PRODUCT" / str(product.id)).expanduser() if data else settings.PRODUCT_BASE_DIR / "PRODUCT" / str(product.id)
    material_dir.mkdir(parents=True, exist_ok=True)
    selection_dir = material_dir / "auto image selection"
    selection_dir.mkdir(parents=True, exist_ok=True)

    model = settings.VLM_MODEL
    client = settings.get_image_analysis_client()
    prompt = AUTO_IMAGE_SELECTION_PROMPT.format(
        title=data.title if data else product.gigab2b_product_id,
        brand=product.brand,
        category=data.leaf_category or data.product_type if data else "",
        facts=_product_facts(product),
        candidates=_candidate_prompt_lines(records),
    )

    contact_sheets: list[dict[str, Any]] = []
    batch_results: list[dict[str, Any]] = []
    try:
        batches = build_image_url_batches(records)
        contact_sheets = list(batches)
        for batch in batches:
            batch_records = [record for record in records if record["image_id"] in set(batch["image_ids"])]
            raw, _reviews = await analyze_image_url_batch(
                client,
                model,
                batch,
                batch_records,
                prompt,
                system_prompt=AUTO_IMAGE_SELECTION_SYSTEM_PROMPT,
                log_prefix="AutoImageSelection",
            )
            batch_results.append(_normalize_batch_result(raw, batch_records))
    except Exception as direct_error:
        logger.warning("自动选图 URL 直传失败，切换 Contact Sheet: product_id=%s error=%s", product_id, direct_error)
        downloaded_records = await download_image_records(records, selection_dir)
        if not downloaded_records:
            raise AutoImageSelectionError(f"候选图片无法访问: {direct_error}") from direct_error
        contact_sheets = build_contact_sheets(downloaded_records, selection_dir / "contact_sheets", f"product_{product_id}_auto_selection")
        batch_results = []
        for sheet in contact_sheets:
            batch_records = [record for record in downloaded_records if record["image_id"] in set(sheet["image_ids"])]
            raw, _reviews = await analyze_contact_sheet(
                client,
                model,
                sheet,
                batch_records,
                prompt,
                system_prompt=AUTO_IMAGE_SELECTION_SYSTEM_PROMPT,
                log_prefix="AutoImageSelection",
            )
            batch_results.append(_normalize_batch_result(raw, batch_records))

    result = _merge_batch_results(batch_results, contact_sheets, warnings, model)
    result["candidate_count"] = len(candidates)
    result["analyzed_count"] = len(records)
    return result


async def run_auto_image_selection(product_id: int, db: AsyncSession | None = None) -> dict[str, Any]:
    if db is not None:
        return await _run_with_db(db, product_id)
    async with async_session() as session:
        return await _run_with_db(session, product_id)
