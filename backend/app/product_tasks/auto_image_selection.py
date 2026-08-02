from __future__ import annotations

import json
import logging
from datetime import datetime
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
    build_contact_sheets,
    download_image_records,
    is_remote_url,
    require_complete_batch_reviews,
)
from app.services.product_pipeline_artifacts import product_dimensions

logger = logging.getLogger(__name__)


# Slots 02-09.  The first automatic pass must already preserve the shopper
# story used by Step 6, rather than forwarding a score-sorted pile of angles.
GALLERY_STORY_ROLES = (
    "lifestyle", "lifestyle", "lifestyle", "material_detail", "function_use",
    "material_detail", "alternate_angle", "size_scale",
)


AUTO_IMAGE_SELECTION_PROMPT = """Analyze these candidate images and select Amazon listing images.

Product: {title}
Brand: {brand}
Category: {category}
Known product facts:
{facts}

Candidate metadata:
{candidates}

Analyze every labeled tile, then select exactly one best MAIN image and up to 8 gallery images from this batch.

MAIN image hard baseline:
- product identity must be clear;
- avoid lifestyle, packaging-only, labels, box/shipping packaging, overlays, watermarks, collage, wrong variant, blurry or low-quality images;
- prefer clean product-only images on white/neutral background.

Gallery order after MAIN must be: up to three visually distinct, attractive lifestyle/context images; material/detail; function/use; a second distinct detail; one alternate full-product angle; and size/scale last. Do not use more than one non-main alternate full-product angle. Reject duplicate, wrong-variant, brand-only, packaging-only, non-product, low-quality, or risky images.

Output valid JSON only:
{{
  "images": [
    {{
      "image_id": "#01",
      "filename": "source.jpg",
      "visual_summary": "",
      "visible_selling_point": "",
      "material_texture": "",
      "scene_type": "",
      "size_scale_cues": "",
      "visible_parts": [],
      "contains_person": false,
      "confidence": "high|medium|low",
      "uncertainty": [],
      "conversion_role": "exact_set|alternate_angle|size_scale|material_detail|function_use|lifestyle|package_contents|proof|exclude",
      "risk_flags": [],
      "slot01_score": 0,
      "gallery_score": 0,
      "decision_reason": ""
    }}
  ],
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
}}

The images array MUST contain exactly one entry for every supplied image_id. Every image_id must also appear exactly once across selected_main, selected_gallery, or rejected."""

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
        "dimensions": product_dimensions(data),
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
            f"{record['image_id']} image_url={candidate.get('image_url') or ''} path={candidate.get('path') or ''} "
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


def _story_role(value: Any) -> str:
    role = str(value or "proof").strip().lower().replace("-", "_").replace(" ", "_")
    if role in {"exact_set", "identity", "variant"}:
        return "alternate_angle"
    if role in {"lifestyle", "material_detail", "function_use", "alternate_angle", "size_scale", "setup_storage", "package_contents", "proof"}:
        return role
    if any(token in role for token in ("scene", "room", "context", "home")):
        return "lifestyle"
    if any(token in role for token in ("material", "fabric", "texture", "detail", "close")):
        return "material_detail"
    if any(token in role for token in ("dimension", "measurement", "size", "scale", "fit")):
        return "size_scale"
    if any(token in role for token in ("function", "use", "feature", "setup", "storage")):
        return "function_use"
    if any(token in role for token in ("angle", "front", "side", "back", "product")):
        return "alternate_angle"
    return "proof"


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
        "path": record["path"],
        "image_url": candidate.get("image_url"),
        "image_id": record["image_id"],
        "score": _score(item.get("score")),
        "reason": str(item.get("reason") or item.get("decision_reason") or "").strip(),
        "risk_flags": item.get("risk_flags") if isinstance(item.get("risk_flags"), list) else [],
        "candidate": candidate,
        "main_image_valid": item.get("main_image_valid", True),
        "material_asset_id": candidate.get("material_asset_id"),
        "content_hash": candidate.get("content_hash"),
    }


def _normalize_batch_result(raw: dict[str, Any], batch_records: list[dict[str, Any]], reviews: list[dict[str, Any]]) -> dict[str, Any]:
    records_by_id = {record["image_id"]: record for record in batch_records}
    enriched_reviews = []
    for review in reviews:
        record = records_by_id.get(str(review.get("image_id") or ""))
        candidate = record.get("candidate") if record else {}
        enriched_reviews.append({
            **review,
            "candidate": candidate,
            "material_asset_id": candidate.get("material_asset_id") if isinstance(candidate, dict) else None,
            "content_hash": candidate.get("content_hash") if isinstance(candidate, dict) else None,
        })
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
            "material_asset_id": entry.get("material_asset_id"),
            "content_hash": entry.get("content_hash"),
        })
    expected_ids = {record["image_id"] for record in batch_records}
    decision_ids = [entry["image_id"] for entry in ([selected_main] if selected_main else [])]
    decision_ids.extend(entry["image_id"] for entry in gallery)
    decision_ids.extend(entry["image_id"] for entry in rejected)
    missing_ids = sorted(expected_ids - set(decision_ids))
    duplicate_ids = sorted({image_id for image_id in decision_ids if decision_ids.count(image_id) > 1})
    if missing_ids or duplicate_ids:
        raise AutoImageSelectionError(
            "VLM 自动选图决策未覆盖全部图片: "
            f"missing={missing_ids or []}, duplicate={duplicate_ids or []}"
        )
    return {
        "selected_main": selected_main,
        "selected_gallery": gallery,
        "rejected": rejected,
        "confidence": str(raw.get("confidence") or "medium").strip().lower(),
        "warnings": raw.get("warnings") if isinstance(raw.get("warnings"), list) else [],
        "image_reviews": enriched_reviews,
    }


def _merge_batch_results(batch_results: list[dict[str, Any]], image_batches: list[dict[str, Any]], warnings: list[str], model: str) -> dict[str, Any]:
    main_candidates = [item["selected_main"] for item in batch_results if item.get("selected_main")]
    if not main_candidates:
        raise AutoImageSelectionError("VLM 未返回可用主图")
    selected_main = max(main_candidates, key=lambda item: _score(item.get("score")))
    if selected_main.get("main_image_valid") is False:
        raise AutoImageSelectionError("VLM 判定主图不满足 Amazon 主图底线")
    hard_flags = {"main_hard_reject", "wrong_variant", "not_product", "packaging_only", "low_quality"}
    if hard_flags.intersection({str(flag).strip().lower() for flag in selected_main.get("risk_flags") or []}):
        raise AutoImageSelectionError("VLM 主图风险标记不允许自动推进")

    image_reviews: list[dict[str, Any]] = []
    for result in batch_results:
        image_reviews.extend(result.get("image_reviews") or [])
    review_by_id = {
        str(item.get("image_id") or "").strip(): item
        for item in image_reviews
        if isinstance(item, dict) and str(item.get("image_id") or "").strip()
    }

    gallery_candidates: list[dict[str, Any]] = []
    for result in batch_results:
        gallery_candidates.extend(result.get("selected_gallery") or [])
    for item in main_candidates:
        if item.get("image_id") == selected_main.get("image_id"):
            continue
        gallery_candidates.append({**item, "role": "exact_set"})
    def enriched_candidate(item: dict[str, Any]) -> dict[str, Any]:
        review = review_by_id.get(str(item.get("image_id") or "").strip(), {})
        role = _story_role(review.get("conversion_role") or item.get("role"))
        return {
            **item,
            "role": role,
            "visual_summary": review.get("visual_summary"),
            "visible_selling_point": review.get("visible_selling_point") or item.get("reason"),
            "gallery_score": _score(review.get("gallery_score") or item.get("score")),
        }

    gallery_candidates = [enriched_candidate(item) for item in gallery_candidates]
    gallery_candidates = sorted(gallery_candidates, key=lambda item: _score(item.get("gallery_score")), reverse=True)
    gallery: list[dict[str, Any]] = []
    seen = {selected_main["path"]}
    seen_ids = {selected_main["image_id"]}
    def add_story_candidate(item: dict[str, Any]) -> bool:
        path = item.get("path")
        image_id = item.get("image_id")
        if not path or not image_id or path in seen or image_id in seen_ids:
            return False
        seen.add(path)
        seen_ids.add(image_id)
        gallery.append(item)
        return True

    for target_role in GALLERY_STORY_ROLES:
        if len(gallery) >= 8:
            break
        exact = [
            item for item in gallery_candidates
            if item.get("image_id") not in seen_ids and item.get("role") == target_role
        ]
        for item in exact:
            if add_story_candidate(item):
                break
        else:
            # Keep dimensions last and reserve the single alternate-angle seat;
            # a missing role is filled with the best remaining conversion image.
            fallback = [
                item for item in gallery_candidates
                if item.get("image_id") not in seen_ids
                and (target_role == "size_scale" or item.get("role") != "size_scale")
                and (target_role == "alternate_angle" or item.get("role") != "alternate_angle")
            ]
            if fallback:
                item = fallback[0]
                item = {
                    **item,
                    "selection_warnings": [
                        f"未找到{target_role}图片，以 {item.get('role')} 图片补位。",
                    ],
                }
                add_story_candidate(item)

    rejected_by_id: dict[str, dict[str, Any]] = {}
    for result in batch_results:
        for item in result.get("rejected") or []:
            image_id = str(item.get("image_id") or "").strip()
            if image_id:
                rejected_by_id[image_id] = item

    selected_ids = {selected_main["image_id"], *[item["image_id"] for item in gallery]}
    for item in gallery_candidates:
        image_id = str(item.get("image_id") or "").strip()
        if not image_id or image_id in selected_ids or image_id in rejected_by_id:
            continue
        rejected_by_id[image_id] = {
            "path": item.get("path"),
            "image_url": item.get("image_url"),
            "image_id": image_id,
            "reason": "not_selected_after_global_merge",
            "material_asset_id": item.get("material_asset_id"),
            "content_hash": item.get("content_hash"),
        }

    expected_ids = {
        str(image_id)
        for batch in image_batches
        for image_id in (batch.get("image_ids") or [])
        if str(image_id or "").strip()
    }
    decision_ids = [selected_main["image_id"], *[item["image_id"] for item in gallery], *rejected_by_id]
    missing_ids = sorted(expected_ids - set(decision_ids))
    duplicate_ids = sorted({image_id for image_id in decision_ids if decision_ids.count(image_id) > 1})
    review_ids = [str(item.get("image_id") or "").strip() for item in image_reviews]
    missing_review_ids = sorted(expected_ids - set(review_ids))
    duplicate_review_ids = sorted({image_id for image_id in review_ids if image_id and review_ids.count(image_id) > 1})
    if missing_ids or duplicate_ids or missing_review_ids or duplicate_review_ids:
        raise AutoImageSelectionError(
            "自动选图全局合并未覆盖全部图片: "
            f"decision_missing={missing_ids}, decision_duplicate={duplicate_ids}, "
            f"review_missing={missing_review_ids}, review_duplicate={duplicate_review_ids}"
        )
    rejected = [rejected_by_id[image_id] for image_id in sorted(rejected_by_id)]

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
        "image_batches": image_batches,
        "image_reviews": image_reviews,
        "decision_coverage": {
            "expected_count": len(expected_ids),
            "reviewed_count": len(review_ids),
            "selected_main_count": 1,
            "selected_gallery_count": len(gallery),
            "rejected_count": len(rejected),
            "complete": True,
        },
        "model": model,
    }


def selection_to_image_analysis(selection: dict[str, Any]) -> dict[str, Any]:
    """Turn the all-candidate vision pass into the downstream visual evidence.

    Automatic selection already requires a complete VLM review of every
    candidate image.  Reusing the reviews for the selected main/gallery avoids
    paying for a second, identical vision pass later in the product flow.
    Unselected reviews remain in ``image_selection_analysis`` for audit while
    the consumer-facing evidence set contains only Listing images.
    """
    reviews = selection.get("image_reviews") if isinstance(selection.get("image_reviews"), list) else []
    review_by_id = {
        str(review.get("image_id") or "").strip(): review
        for review in reviews
        if isinstance(review, dict) and str(review.get("image_id") or "").strip()
    }
    ordered_selection = [selection.get("selected_main"), *(selection.get("selected_gallery") or [])]
    images: list[dict[str, Any]] = []
    gallery_selection: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for slot, selected in enumerate(ordered_selection, start=1):
        if not isinstance(selected, dict):
            continue
        image_id = str(selected.get("image_id") or "").strip()
        if not image_id or image_id in seen_ids:
            continue
        seen_ids.add(image_id)
        review = review_by_id.get(image_id, {})
        role = "main" if slot == 1 else _story_role(selected.get("role") or review.get("conversion_role"))
        evidence = {
            **review,
            "image_id": image_id,
            "path": selected.get("path") or review.get("path"),
            "image_url": selected.get("image_url") or review.get("image_url"),
            "filename": selected.get("filename") or review.get("filename"),
            "conversion_role": review.get("conversion_role") or role,
            "visible_selling_point": review.get("visible_selling_point") or selected.get("reason"),
            "risk_flags": review.get("risk_flags") if isinstance(review.get("risk_flags"), list) else selected.get("risk_flags") or [],
            "confidence": review.get("confidence") or selection.get("confidence"),
            "uncertainty": review.get("uncertainty") if isinstance(review.get("uncertainty"), list) else [],
            "slot": slot,
            "selection_role": role,
        }
        evidence["multimodal_result"] = {
            "visual_summary": review.get("visual_summary"),
            "visible_selling_point": evidence["visible_selling_point"],
            "material_texture": review.get("material_texture"),
            "scene_type": review.get("scene_type"),
            "size_scale_cues": review.get("size_scale_cues"),
            "visible_parts": review.get("visible_parts"),
            "confidence": evidence["confidence"],
            "uncertainty": evidence["uncertainty"],
        }
        images.append(evidence)
        gallery_selection.append({
            "slot": slot,
            "image_id": image_id,
            "path": evidence["path"],
            "selection_role": role,
            "decision_reason": selected.get("reason") or review.get("decision_reason"),
        })
    if not images:
        raise AutoImageSelectionError("候选图片视觉分析未生成已选图片证据")
    return {
        "images": images,
        "gallery_selection": gallery_selection,
        "selection_diagnostics": {
            "analysis_stage": "candidate_vision_before_selection",
            "candidate_review_count": len(reviews),
            "selected_image_count": len(images),
            "decision_coverage": selection.get("decision_coverage") or {},
            "warnings": selection.get("warnings") or [],
        },
        "selling_points": list(dict.fromkeys(
            str(image.get("visible_selling_point") or "").strip()
            for image in images
            if str(image.get("visible_selling_point") or "").strip()
        )),
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
    model = settings.VLM_MODEL
    client = settings.get_image_analysis_client()
    image_batches: list[dict[str, Any]] = []
    batch_results: list[dict[str, Any]] = []
    try:
        material_dir = Path(data.material_dir).expanduser().resolve() if data and data.material_dir else (
            settings.PRODUCT_BASE_DIR / "GIGA" / (product.source_site or "US") / str(data.item_code if data else product.id)
        )
        analysis_dir = material_dir / "image analysis" / "contact_sheets" / datetime.now().strftime("auto_selection_%Y%m%d_%H%M%S")
        local_records = await download_image_records(records, analysis_dir / "source_cache")
        if len(local_records) != len(records):
            raise AutoImageSelectionError(f"候选图片本地化不完整: {len(local_records)}/{len(records)}")
        batches = build_contact_sheets(local_records, analysis_dir, str(data.item_code if data and data.item_code else product.id))
        image_batches = list(batches)
        for batch in batches:
            batch_records = [record for record in local_records if record["image_id"] in set(batch["image_ids"])]
            batch_prompt = AUTO_IMAGE_SELECTION_PROMPT.format(
                title=data.title if data else product.gigab2b_product_id,
                brand=product.brand,
                category=data.leaf_category or data.product_type if data else "",
                facts=_product_facts(product),
                candidates=_candidate_prompt_lines(batch_records),
            )
            raw, reviews = await analyze_contact_sheet(
                client,
                model,
                batch,
                batch_records,
                batch_prompt,
                system_prompt=AUTO_IMAGE_SELECTION_SYSTEM_PROMPT,
                log_prefix="AutoImageSelection",
            )
            require_complete_batch_reviews(reviews, batch_records, batch_label=f"contact_sheet={batch['sheet_page']}")
            batch_results.append(_normalize_batch_result(raw, batch_records, reviews))
    except Exception as exc:
        logger.warning("自动选图 Contact Sheet VLM 失败: product_id=%s error=%s", product_id, exc)
        raise AutoImageSelectionError(f"自动选图 Contact Sheet VLM 失败: {type(exc).__name__}: {exc}") from exc

    result = _merge_batch_results(batch_results, image_batches, warnings, model)
    result["candidate_count"] = len(candidates)
    result["analyzed_count"] = len(result.get("image_reviews") or [])
    return result


async def run_auto_image_selection(product_id: int, db: AsyncSession | None = None) -> dict[str, Any]:
    if db is not None:
        return await _run_with_db(db, product_id)
    async with async_session() as session:
        return await _run_with_db(session, product_id)
