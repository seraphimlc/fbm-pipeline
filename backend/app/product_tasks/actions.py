from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import async_session
from app.config import settings
from app.models import (
    AmazonCompetitorSearchCandidate,
    CatalogProduct,
    Product,
    ProductImage,
    ProductMaterialAsset,
    TaskGroup,
    TaskRun,
    TaskStep,
)
from app.models.status import (
    COMPLETED,
    FAILED,
    PAUSED,
    STEP3_KEYWORDS,
    STEP5_LISTING,
    STEP6_CURATING,
    STEP6_DONE,
    STEP_CUSTOMER_MINDSET,
    WORKFLOW_NODE_AUTO_SELECT_IMAGES,
    WORKFLOW_NODE_AUTO_SELECT_COMPETITOR,
    WORKFLOW_NODE_CAPTURE_COMPETITOR_CANDIDATES,
    WORKFLOW_NODE_FLOW_DONE,
    WORKFLOW_NODE_IMAGE_ANALYSIS,
    WORKFLOW_NODE_KEYWORD_RESEARCH,
    WORKFLOW_NODE_CUSTOMER_MINDSET,
    WORKFLOW_NODE_LISTING_GENERATION,
    WORKFLOW_NODE_PREPARE_MATERIALS,
    WORKFLOW_NODE_SEARCH_COMPETITOR,
    WORKFLOW_NODE_VISUAL_MATCH_COMPETITORS,
    WORKFLOW_STATUS_FAILED,
    WORKFLOW_STATUS_PENDING,
    WORKFLOW_STATUS_PROCESSING,
    WORKFLOW_STATUS_SUCCEEDED,
)
from app.product_tasks.auto_image_selection import run_auto_image_selection, selection_to_image_analysis
from app.services.product_material_prepare import prepare_product_materials, write_material_manifest
from app.services.product_pipeline_artifacts import write_image_selection_artifacts
from app.pipeline.engine import _assert_step_prerequisites
from app.pipeline.step2_pricing import run_pricing
from app.pipeline.step4_category import run_category
from app.pipeline.step5_listing import run_listing
from app.pipeline.step6_image import run_image_analysis
from app.pipeline.step3_keywords import run_keywords
from app.pipeline.customer_mindset import (
    customer_mindset_matches_product,
    image_analysis_ready,
    run_customer_mindset,
)
from app.product_tasks.workflow import set_product_workflow
from app.services.amazon_competitor_query import CompetitorQueryError, build_amazon_competitor_queries
from app.services.amazon_competitor_visual_match import (
    CompetitorVisualMatchError,
    clear_current_visual_match,
    run_competitor_visual_match,
)
from app.services.amazon_listing_detail import (
    AmazonListingDetailError,
    AmazonListingDetailEvidenceContext,
    get_amazon_listing_detail_adapter,
    listing_detail_to_dict,
)
from app.services.amazon_search_page import AmazonSearchPageError, candidate_to_dict, run_amazon_search_queries
from app.services.product_protection import (
    auto_image_selection_protection_reasons,
    product_external_result_protection_reasons,
    raise_if_auto_image_selection_protected,
)
from app.services.aplus_auto_trigger import try_auto_start_aplus_after_export_ready
from app.task_runtime.actions import TaskAction, TaskGroupPlan, TaskRunPlan, TaskStepPlan, action_for, register_action
from app.task_runtime.constants import (
    RUN_STATUS_FAILED,
    RUN_STATUS_INTERRUPTED,
    RUN_STATUS_PENDING,
    RUN_STATUS_RUNNING,
    RUN_STATUS_SUCCEEDED,
    STEP_STATUS_PENDING,
    STEP_STATUS_READY,
    STEP_STATUS_RUNNING,
    STEP_STATUS_SUCCEEDED,
)
from app.task_runtime.events import update_step_progress
from app.task_runtime.exceptions import TaskStepCanceled, TaskStepInterrupted
from app.task_runtime.json_utils import json_dumps, json_loads
from app.task_runtime.registry import TaskContext, register_worker
from app.task_runtime.scheduler import kick_task_runtime


ACTIVE_RUN_STATUSES = (RUN_STATUS_PENDING, RUN_STATUS_RUNNING)
ACTIVE_STEP_STATUSES = (STEP_STATUS_PENDING, STEP_STATUS_READY, STEP_STATUS_RUNNING)
logger = logging.getLogger(__name__)

AUTO_COMPETITOR_SELECTION_MODEL = "rule_based_auto_competitor_v2"
AUTO_COMPETITOR_SELECTION_RULE_VERSION = "auto_competitor_selection_v2"
AUTO_COMPETITOR_HIGH_THRESHOLD = 0.78
AUTO_COMPETITOR_MEDIUM_THRESHOLD = 0.68
_TOKEN_STOPWORDS = {
    "a",
    "an",
    "and",
    "by",
    "for",
    "in",
    "of",
    "on",
    "the",
    "to",
    "with",
}
_ACCESSORY_TERMS = {
    "accessory",
    "accessories",
    "cover",
    "covers",
    "replacement",
    "part",
    "parts",
    "protector",
    "slipcover",
}

PRODUCT_ACTION_TYPES = {
    "product_material_prepare",
    "product_auto_image_selection",
    "product_competitor_search",
    "product_competitor_visual_match",
    "product_competitor_candidate_capture",
    "product_auto_competitor_selection",
    "product_keyword_research",
    "product_image_analysis",
    "product_customer_mindset",
    "product_listing_generation",
}


def _payload_for_step(step: TaskStep) -> dict[str, Any]:
    value = json_loads(step.payload_json, {})
    return value if isinstance(value, dict) else {}


def _payload_for_run(run: TaskRun) -> dict[str, Any]:
    value = json_loads(run.payload_json, {})
    return value if isinstance(value, dict) else {}


def _selected_listing_image_ref(item: dict[str, Any] | None) -> str:
    if not isinstance(item, dict):
        return ""
    return str(item.get("image_url") or item.get("path") or item.get("local_path") or "").strip()


def _legacy_dedupe_key(task_type: str, product_id: int) -> str | None:
    if task_type == "product_material_prepare":
        return f"product_material_prepare:product:{product_id}"
    if task_type == "product_auto_image_selection":
        return f"product_auto_image_selection:product:{product_id}"
    if task_type == "product_competitor_search":
        return f"product_competitor_search:product:{product_id}"
    if task_type == "product_competitor_visual_match":
        return f"product_competitor_visual_match:product:{product_id}"
    if task_type == "product_competitor_candidate_capture":
        return f"product_competitor_candidate_capture:product:{product_id}"
    if task_type == "product_auto_competitor_selection":
        return f"product_auto_competitor_selection:product:{product_id}"
    if task_type == "product_keyword_research":
        return f"product_keyword_research:product:{product_id}"
    if task_type == "product_image_analysis":
        return f"product_image_analysis:product:{product_id}"
    if task_type == "product_customer_mindset":
        return f"product_customer_mindset:product:{product_id}"
    if task_type == "product_listing_generation":
        return f"product_listing_generation:product:{product_id}"
    return None


def _legacy_correlation_key(task_type: str, product_id: int) -> str | None:
    if task_type == "product_material_prepare":
        return f"product:{product_id}:material_prepare"
    if task_type == "product_auto_image_selection":
        return f"product:{product_id}:auto_image_selection"
    if task_type == "product_competitor_search":
        return f"product:{product_id}:competitor_search"
    if task_type == "product_competitor_visual_match":
        return f"product:{product_id}:competitor_visual_match"
    if task_type == "product_competitor_candidate_capture":
        return f"product:{product_id}:competitor_candidate_capture"
    if task_type == "product_auto_competitor_selection":
        return f"product:{product_id}:auto_competitor_selection"
    if task_type == "product_keyword_research":
        return f"product:{product_id}:keyword_research"
    if task_type == "product_image_analysis":
        return f"product:{product_id}:image_analysis"
    if task_type == "product_customer_mindset":
        return f"product:{product_id}:customer_mindset"
    if task_type == "product_listing_generation":
        return f"product:{product_id}:listing_generation"
    return None


def _legacy_payload_product_id(run: TaskRun) -> int | None:
    value = _payload_for_run(run).get("product_id")
    if value is not None and str(value).isdigit():
        product_id = int(value)
        return product_id if product_id > 0 else None
    return None


async def _load_product(db: AsyncSession, product_id: int) -> Product:
    result = await db.execute(
        select(Product)
        .where(Product.id == product_id)
        .options(
            selectinload(Product.data),
            selectinload(Product.images),
            selectinload(Product.aplus),
            selectinload(Product.catalog_item),
            selectinload(Product.files),
        )
    )
    product = result.scalar_one_or_none()
    if not product:
        raise RuntimeError(f"商品不存在: {product_id}")
    return product


def _product_id(payload: dict[str, Any]) -> int:
    product_id = int(payload.get("product_id") or 0)
    if product_id <= 0:
        raise ValueError("商品任务缺少 product_id")
    return product_id


def _visual_ids_from_payload(payload: dict[str, Any]) -> tuple[int | None, int | None]:
    visual_task_run_id = int(payload.get("visual_task_run_id") or 0)
    visual_task_step_id = int(payload.get("visual_task_step_id") or 0)
    return (
        visual_task_run_id if visual_task_run_id > 0 else None,
        visual_task_step_id if visual_task_step_id > 0 else None,
    )


def _sync_catalog_item(product: Product) -> None:
    if product.catalog_item:
        product.catalog_item.status = product.status
        product.catalog_item.updated_at = product.updated_at


def _e5_export_ready_protection_reasons(product: Product) -> list[str]:
    return product_external_result_protection_reasons(product)


def _raise_if_e5_export_ready_protected(product: Product, *, action_label: str) -> None:
    reasons = _e5_export_ready_protection_reasons(product)
    if reasons:
        raise RuntimeError(f"当前商品已有不可逆外部结果，不能{action_label}：" + "；".join(reasons))


def _workflow_node_for_step(step: int) -> str:
    if step == 3:
        return WORKFLOW_NODE_KEYWORD_RESEARCH
    return WORKFLOW_NODE_IMAGE_ANALYSIS if step == 5 else WORKFLOW_NODE_LISTING_GENERATION


def _json_from_text(value: str | None) -> Any:
    return json_loads(value, {})


def _customer_mindset_ready(product: Product) -> bool:
    data = product.data
    if not data or not data.customer_mindset:
        return False
    try:
        return customer_mindset_matches_product(data.customer_mindset, product)
    except RuntimeError:
        return False


def _raise_if_customer_mindset_missing(product: Product) -> None:
    if not _customer_mindset_ready(product):
        raise RuntimeError("前置节点未完成：用户心智梳理未完成，不能进入 Listing 文案")


def _listing_content_ready(product: Product) -> bool:
    data = product.data
    title = str(data.listing_title or "").strip() if data else ""
    if not title or len(title) > settings.STEP5_TITLE_MAX_CHARS:
        return False
    highlights = _json_from_text(str(getattr(data, "listing_product_highlights", "") or ""))
    if not isinstance(highlights, list) or len(highlights) != 1:
        return False
    if any(
        not str(item or "").strip()
        or len(str(item).strip()) > settings.STEP5_PRODUCT_HIGHLIGHT_MAX_CHARS
        for item in highlights
    ):
        return False
    bullets = _json_from_text(str(data.listing_bullets or "").strip())
    if not isinstance(bullets, list) or len(bullets) != 5:
        return False
    return all(
        str(item or "").strip()
        and len(str(item).strip()) <= settings.STEP5_BULLET_MAX_CHARS
        for item in bullets
    )


def _clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, value))


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = re.search(r"\d+(?:\.\d+)?", str(value).replace(",", ""))
    return float(match.group(0)) if match else None


def _safe_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    match = re.search(r"\d+", str(value).replace(",", ""))
    return int(match.group(0)) if match else None


def _text_tokens(*values: Any) -> set[str]:
    tokens: set[str] = set()
    for value in values:
        if value is None:
            continue
        if isinstance(value, (list, tuple, set)):
            tokens.update(_text_tokens(*value))
            continue
        if isinstance(value, dict):
            tokens.update(_text_tokens(*value.values()))
            continue
        for token in re.findall(r"[a-z0-9]+", str(value).lower()):
            if len(token) <= 2 or token in _TOKEN_STOPWORDS:
                continue
            if token.endswith("s") and len(token) > 4:
                token = token[:-1]
            tokens.add(token)
    return tokens


def _list_from_json_text(value: str | None) -> list[Any]:
    parsed = json_loads(value, [])
    return parsed if isinstance(parsed, list) else []


def _dict_from_json_text(value: str | None) -> dict[str, Any]:
    parsed = json_loads(value, {})
    return parsed if isinstance(parsed, dict) else {}


def _rank_quality(rank: int | None, *, scale: int = 6) -> float:
    if not rank or rank <= 0:
        return 0.4
    return _clamp((scale + 1 - rank) / scale)


def _source_product_tokens(product: Product) -> set[str]:
    data = product.data
    if not data:
        return set()
    return _text_tokens(
        data.title,
        data.material,
        data.product_type,
        data.color,
        data.leaf_category,
    )


def _candidate_bullets(row: AmazonCompetitorSearchCandidate) -> list[str]:
    return [str(item) for item in _list_from_json_text(row.bullets_json) if str(item or "").strip()]


def _candidate_tokens(row: AmazonCompetitorSearchCandidate) -> set[str]:
    details = _dict_from_json_text(row.product_details_json)
    selected_details = {
        key: value
        for key, value in details.items()
        if _is_identity_detail_key(key) and len(str(value or "")) <= 500
    }
    return _text_tokens(
        row.title,
        _candidate_bullets(row),
        row.description,
        row.leaf_category,
        row.category_rank,
        selected_details,
    )


def _candidate_identity_tokens(row: AmazonCompetitorSearchCandidate) -> set[str]:
    return _text_tokens(row.title, row.leaf_category, row.category_rank)


def _is_identity_detail_key(value: Any) -> bool:
    key = str(value or "").strip().lower()
    return any(marker in key for marker in (
        "brand",
        "color",
        "size",
        "material",
        "style",
        "type",
        "dimension",
        "weight",
        "finish",
        "special feature",
        "compatible",
        "included component",
    ))


def _overlap_score(source_tokens: set[str], candidate_tokens: set[str]) -> float:
    if not source_tokens or not candidate_tokens:
        return 0.5
    return _clamp(len(source_tokens & candidate_tokens) / max(1, len(source_tokens)))


def _category_alignment_score(product: Product, row: AmazonCompetitorSearchCandidate) -> float:
    data = product.data
    source_tokens = _category_tokens(
        getattr(data, "product_type", None) if data else None,
        getattr(data, "leaf_category", None) if data else None,
    )
    candidate_tokens = _category_tokens(row.leaf_category, row.category_rank)
    if not candidate_tokens:
        return 0.6
    if not source_tokens:
        return 0.5
    overlap = len(source_tokens & candidate_tokens)
    return _clamp(overlap / max(1, min(len(source_tokens), len(candidate_tokens))))


def _category_tokens(*values: Any) -> set[str]:
    aliases = {
        "beds": "bed",
        "frames": "frame",
        "bases": "base",
        "sofas": "sofa",
        "chairs": "chair",
        "tables": "table",
        "cabinets": "cabinet",
        "shelves": "shelf",
    }
    return {aliases.get(token, token) for token in _text_tokens(*values)}


def _auto_competitor_hard_reject_reasons(row: AmazonCompetitorSearchCandidate) -> list[str]:
    reasons: list[str] = []
    if not str(row.asin or "").strip():
        reasons.append("missing_asin")
    if not str(row.url or "").strip():
        reasons.append("missing_url")
    if row.capture_status != "succeeded":
        reasons.append("detail_capture_not_succeeded")
    if row.visual_reject:
        reasons.append("visual_reject")
    if row.visual_same_product_type == 0:
        reasons.append("different_visual_product_type")
    if row.is_accessory or row.is_replacement_part or row.is_cover_only:
        reasons.append("accessory_or_replacement")
    identity_tokens = _candidate_identity_tokens(row)
    if identity_tokens & _ACCESSORY_TERMS:
        reasons.append("accessory_terms")
    if not str(row.title or "").strip() and not _candidate_bullets(row):
        reasons.append("missing_title_and_bullets")
    return reasons


def _score_auto_competitor_candidate(
    product: Product,
    row: AmazonCompetitorSearchCandidate,
    *,
    comparison_success_count: int,
) -> dict[str, Any]:
    hard_rejects = _auto_competitor_hard_reject_reasons(row)
    source_tokens = _source_product_tokens(product)
    candidate_tokens = _candidate_tokens(row)

    visual_values = [
        _safe_float(row.visual_similarity_score),
        _safe_float(row.visual_attribute_match_score),
        _safe_float(row.visual_title_match_score),
    ]
    visual_numbers = [_clamp(value) for value in visual_values if value is not None]
    visual_base = sum(visual_numbers) / len(visual_numbers) if visual_numbers else 0.0
    visual_fit = _clamp((visual_base * 0.85) + (_rank_quality(row.visual_rank) * 0.15))
    if row.visual_reject_reason:
        visual_fit = _clamp(visual_fit - 0.1)

    token_overlap = _overlap_score(source_tokens, candidate_tokens)
    title_fit = _clamp(0.25 + token_overlap * 0.75)
    if candidate_tokens & _ACCESSORY_TERMS:
        title_fit = _clamp(title_fit - 0.35)

    bullets = _candidate_bullets(row)
    details = _dict_from_json_text(row.product_details_json)
    detail_checks = [
        bool(str(row.title or "").strip()),
        len(bullets) >= 2,
        bool(details),
        bool(str(row.main_image_url or row.image_url or "").strip()),
        bool(str(row.description or row.aplus_text or "").strip()),
    ]
    detail_completeness = sum(1 for item in detail_checks if item) / len(detail_checks)

    category_alignment = _category_alignment_score(product, row)

    rating = _safe_float(row.rating)
    review_count = _safe_int(row.review_count)
    marketplace_evidence = (
        (0.35 if rating and rating >= 4.0 else 0.15 if rating else 0.0)
        + (0.35 if review_count and review_count >= 50 else 0.2 if review_count else 0.0)
        + (0.3 if str(row.price or "").strip() else 0.0)
    )

    stability = (_rank_quality(row.visual_rank) * 0.65) + (_rank_quality(row.search_rank, scale=12) * 0.35)

    dimensions = {
        "visual_fit": round(visual_fit, 4),
        "title_source_fit": round(title_fit, 4),
        "detail_completeness": round(detail_completeness, 4),
        "category_alignment": round(category_alignment, 4),
        "marketplace_evidence": round(_clamp(marketplace_evidence), 4),
        "rank_stability": round(_clamp(stability), 4),
    }
    if (
        source_tokens
        and candidate_tokens
        and dimensions["title_source_fit"] <= 0.35
        and dimensions["category_alignment"] <= 0.25
    ):
        hard_rejects.append("different_product_type_low_title_and_category_alignment")
    score = (
        dimensions["visual_fit"] * 0.35
        + dimensions["title_source_fit"] * 0.20
        + dimensions["detail_completeness"] * 0.15
        + dimensions["category_alignment"] * 0.10
        + dimensions["marketplace_evidence"] * 0.10
        + dimensions["rank_stability"] * 0.10
    )
    score = round(_clamp(score), 4)

    risks: list[str] = []
    if comparison_success_count < 2:
        risks.append("only_one_detail_success_candidate")
    if dimensions["visual_fit"] < 0.78:
        risks.append("visual_score_below_high_confidence")
    if dimensions["title_source_fit"] < 0.65:
        risks.append("limited_source_title_overlap")
    if dimensions["category_alignment"] < 0.65:
        risks.append("limited_category_alignment")
    if row.sponsored:
        risks.append("sponsored_candidate")

    if hard_rejects:
        confidence = "rejected"
    elif score >= AUTO_COMPETITOR_HIGH_THRESHOLD and not any(risk in risks for risk in {"visual_score_below_high_confidence", "limited_source_title_overlap"}):
        confidence = "high"
    elif score >= AUTO_COMPETITOR_MEDIUM_THRESHOLD:
        confidence = "medium"
        if "score_below_high_threshold" not in risks:
            risks.append("score_below_high_threshold")
    else:
        confidence = "low"
        risks.append("score_below_medium_threshold")

    asin = str(row.asin or "").strip().upper()
    reason = (
        f"{confidence} confidence auto competitor {asin}: score={score}, "
        f"visual={dimensions['visual_fit']}, title={dimensions['title_source_fit']}, "
        f"detail={dimensions['detail_completeness']}"
    )
    return {
        "candidate_id": row.id,
        "asin": asin,
        "visual_rank": row.visual_rank,
        "search_rank": row.search_rank,
        "score": score,
        "confidence": confidence,
        "dimensions": dimensions,
        "risks": risks,
        "hard_rejects": hard_rejects,
        "reason": reason,
    }


def _score_auto_competitor_candidates(product: Product, rows: list[AmazonCompetitorSearchCandidate]) -> dict[str, Any]:
    comparison_success_count = sum(1 for row in rows if row.capture_status == "succeeded")
    scored = [
        _score_auto_competitor_candidate(product, row, comparison_success_count=comparison_success_count)
        for row in rows
    ]
    scored.sort(key=lambda item: (item["hard_rejects"] != [], -float(item["score"]), int(item.get("visual_rank") or 999), int(item["candidate_id"])))
    qualified = [
        item
        for item in scored
        if not item["hard_rejects"] and item["confidence"] in {"high", "medium"} and float(item["score"]) >= AUTO_COMPETITOR_MEDIUM_THRESHOLD
    ]
    if not qualified:
        best = scored[0] if scored else None
        raise RuntimeError(
            "自动选竞品没有达到 medium 阈值的候选"
            + (f": best={best['asin']} score={best['score']} confidence={best['confidence']} rejects={best['hard_rejects']}" if best else "")
        )
    selected = qualified[0]
    return {
        "scored_candidates": scored,
        "selected": selected,
        "success_count": comparison_success_count,
    }


def _clear_auto_image_downstream_outputs(product: Product) -> None:
    if product.data:
        for field in (
            "categories",
            "leaf_category",
            "customer_mindset",
            "customer_mindset_generated_at",
            "listing_title",
            "listing_product_highlights",
            "listing_bullets",
            "listing_search_terms",
            "listing_title_zh",
            "listing_product_highlights_zh",
            "listing_bullets_zh",
            "listing_search_terms_zh",
            "listing_description",
            "listing_description_zh",
            "listing_check",
            "listing_primary_keyword",
            "listing_removed_keywords",
        ):
            setattr(product.data, field, None)
    if product.images:
        product.images.contact_sheet_path = None
        product.images.image_analysis = None
        product.images.image_selling_points = None
        product.images.category_style = None
        product.images.main_image_summary = None
        product.images.analyzed_at = None
    if product.aplus:
        for column in product.aplus.__table__.columns:
            if column.name in {"id", "product_id"}:
                continue
            if column.name == "llm_model":
                setattr(product.aplus, column.name, settings.LLM_MODEL)
            else:
                setattr(product.aplus, column.name, None)
    product.competitor_asin = None
    product.aplus_upload_status = "not_uploaded"
    product.aplus_uploaded_at = None
    product.aplus_upload_error = None
    if product.catalog_item:
        product.catalog_item.competitor_asin = None
        product.catalog_item.confirmed_at = None
        product.catalog_item.aplus_upload_status = "not_uploaded"
        product.catalog_item.aplus_uploaded_at = None
        product.catalog_item.aplus_upload_error = None


async def _project_product_failure(
    db: AsyncSession,
    *,
    product_id: int,
    step: int,
    label: str,
    error: Exception | str,
) -> None:
    try:
        product = await _load_product(db, product_id)
    except RuntimeError:
        return
    now = datetime.now()
    product.status = FAILED
    product.current_step = step
    product.error_message = f"{label}失败: {type(error).__name__}: {error}" if isinstance(error, Exception) else str(error)
    set_product_workflow(
        product,
        node=_workflow_node_for_step(step),
        status=WORKFLOW_STATUS_FAILED,
        error=product.error_message,
        now=now,
    )
    product.updated_at = now
    _sync_catalog_item(product)
    await db.commit()


async def _project_product_paused(
    db: AsyncSession,
    *,
    product_id: int,
    step: int,
    message: str,
) -> None:
    try:
        product = await _load_product(db, product_id)
    except RuntimeError:
        return
    now = datetime.now()
    product.status = PAUSED
    product.current_step = step
    product.error_message = message
    set_product_workflow(
        product,
        node=_workflow_node_for_step(step),
        status=WORKFLOW_STATUS_FAILED,
        error=message,
        now=now,
    )
    product.updated_at = now
    _sync_catalog_item(product)


async def _project_auto_image_selection_failed(
    db: AsyncSession,
    *,
    product_id: int,
    message: str,
) -> None:
    try:
        product = await _load_product(db, product_id)
    except RuntimeError:
        return
    now = datetime.now()
    product.status = FAILED
    product.current_step = 1
    product.error_message = message
    set_product_workflow(
        product,
        node=WORKFLOW_NODE_AUTO_SELECT_IMAGES,
        status=WORKFLOW_STATUS_FAILED,
        error=message,
        now=now,
    )
    product.updated_at = now
    _sync_catalog_item(product)
    await db.commit()


async def _project_competitor_search_failed(
    db: AsyncSession,
    *,
    product_id: int,
    message: str,
) -> None:
    try:
        product = await _load_product(db, product_id)
    except RuntimeError:
        return
    now = datetime.now()
    product.status = FAILED
    product.current_step = 2
    product.error_message = message
    set_product_workflow(
        product,
        node=WORKFLOW_NODE_SEARCH_COMPETITOR,
        status=WORKFLOW_STATUS_FAILED,
        error=message,
        now=now,
    )
    product.updated_at = now
    _sync_catalog_item(product)
    await db.commit()


async def _project_competitor_visual_match_failed(
    db: AsyncSession,
    *,
    product_id: int,
    message: str,
) -> None:
    try:
        product = await _load_product(db, product_id)
    except RuntimeError:
        return
    now = datetime.now()
    await clear_current_visual_match(db, product_id, now=now)
    product.status = FAILED
    product.current_step = 2
    product.error_message = message
    set_product_workflow(
        product,
        node=WORKFLOW_NODE_VISUAL_MATCH_COMPETITORS,
        status=WORKFLOW_STATUS_FAILED,
        error=message,
        now=now,
    )
    product.updated_at = now
    _sync_catalog_item(product)
    await db.commit()


async def _project_competitor_candidate_capture_failed(
    db: AsyncSession,
    *,
    product_id: int,
    message: str,
    workflow_error: str | None = None,
) -> None:
    try:
        product = await _load_product(db, product_id)
    except RuntimeError:
        return
    now = datetime.now()
    await clear_current_competitor_capture(db, product_id, now=now)
    await clear_current_auto_competitor_selection(db, product_id, now=now, clear_product_fact=False)
    product.status = FAILED
    product.current_step = 2
    product.error_message = message
    set_product_workflow(
        product,
        node=WORKFLOW_NODE_CAPTURE_COMPETITOR_CANDIDATES,
        status=WORKFLOW_STATUS_FAILED,
        error=workflow_error or message,
        now=now,
    )
    product.updated_at = now
    _sync_catalog_item(product)
    await db.commit()


async def _project_auto_competitor_selection_failed(
    db: AsyncSession,
    *,
    product_id: int,
    message: str,
    workflow_error: str | None = None,
) -> None:
    try:
        product = await _load_product(db, product_id)
    except RuntimeError:
        return
    now = datetime.now()
    await clear_current_auto_competitor_selection(db, product_id, now=now, clear_product_fact=False)
    product.status = FAILED
    product.current_step = 2
    product.error_message = message
    set_product_workflow(
        product,
        node=WORKFLOW_NODE_AUTO_SELECT_COMPETITOR,
        status=WORKFLOW_STATUS_FAILED,
        error=workflow_error or message,
        now=now,
    )
    product.updated_at = now
    _sync_catalog_item(product)
    await db.commit()


async def _project_image_analysis_creation_failed(
    db: AsyncSession,
    *,
    product_id: int,
    message: str,
) -> None:
    try:
        product = await _load_product(db, product_id)
    except RuntimeError:
        return
    now = datetime.now()
    product.status = FAILED
    product.current_step = 5
    product.error_message = message
    set_product_workflow(
        product,
        node=WORKFLOW_NODE_IMAGE_ANALYSIS,
        status=WORKFLOW_STATUS_FAILED,
        error=message,
        now=now,
    )
    product.updated_at = now
    _sync_catalog_item(product)
    await db.commit()


async def _project_customer_mindset_failed(
    db: AsyncSession,
    *,
    product_id: int,
    message: str,
    paused: bool = False,
) -> None:
    try:
        product = await _load_product(db, product_id)
    except RuntimeError:
        return
    now = datetime.now()
    product.status = PAUSED if paused else FAILED
    product.current_step = 6
    product.error_message = message
    set_product_workflow(
        product,
        node=WORKFLOW_NODE_CUSTOMER_MINDSET,
        status=WORKFLOW_STATUS_FAILED,
        error=message,
        now=now,
    )
    product.updated_at = now
    _sync_catalog_item(product)
    await db.commit()


async def _project_keyword_research_failed(
    db: AsyncSession,
    *,
    product_id: int,
    message: str,
) -> None:
    try:
        product = await _load_product(db, product_id)
    except RuntimeError:
        return
    now = datetime.now()
    product.status = FAILED
    product.current_step = 3
    product.error_message = message
    set_product_workflow(
        product,
        node=WORKFLOW_NODE_KEYWORD_RESEARCH,
        status=WORKFLOW_STATUS_FAILED,
        error=message,
        now=now,
    )
    product.updated_at = now
    _sync_catalog_item(product)
    await db.commit()


async def _project_material_prepare_failed(
    db: AsyncSession,
    *,
    product_id: int,
    message: str,
    paused: bool = False,
) -> None:
    try:
        product = await _load_product(db, product_id)
    except RuntimeError:
        return
    now = datetime.now()
    product.status = PAUSED if paused else FAILED
    product.current_step = 1
    product.error_message = message
    set_product_workflow(
        product,
        node=WORKFLOW_NODE_PREPARE_MATERIALS,
        status=WORKFLOW_STATUS_FAILED,
        error=message,
        now=now,
    )
    product.updated_at = now
    _sync_catalog_item(product)
    await db.commit()


class ProductMaterialPrepareAction:
    """Resolve the GIGA page, download every required package, and register all assets."""

    action_type = "product_material_prepare"

    async def validate(self, db: AsyncSession, payload: dict[str, Any]) -> None:
        product = await _load_product(db, _product_id(payload))
        reasons = product_external_result_protection_reasons(product)
        if reasons:
            raise RuntimeError("商品已有不可逆外部结果，不能自动刷新供应商素材: " + "；".join(reasons))

    def dedupe_key(self, payload: dict[str, Any]) -> str | None:
        return f"product_material_prepare:product:{_product_id(payload)}"

    def correlation_key(self, payload: dict[str, Any]) -> str | None:
        return f"product:{_product_id(payload)}:material_prepare"

    async def reserve(self, db: AsyncSession, payload: dict[str, Any], run: TaskRun) -> None:
        product = await _load_product(db, _product_id(payload))
        now = datetime.now()
        product.status = "created"
        product.current_step = 1
        product.error_message = None
        set_product_workflow(
            product,
            node=WORKFLOW_NODE_PREPARE_MATERIALS,
            status=WORKFLOW_STATUS_PROCESSING,
            error=None,
            now=now,
        )
        product.updated_at = now
        _sync_catalog_item(product)

    def build_plan(self, payload: dict[str, Any]) -> TaskRunPlan:
        product_id = _product_id(payload)
        task_payload = {
            "product_id": product_id,
            "pipeline_target": str(payload.get("pipeline_target") or "export_ready"),
            "test_session_key": str(payload.get("test_session_key") or "").strip() or None,
            "origin_task_run_id": payload.get("origin_task_run_id"),
        }
        return TaskRunPlan(
            task_type=self.action_type,
            title=f"准备供应商素材：商品 #{product_id}",
            payload=task_payload,
            groups=[
                TaskGroupPlan(
                    group_key="material_prepare",
                    title="解析商品页并准备素材包",
                    steps=[
                        TaskStepPlan(
                            step_key=f"product:{product_id}:material_prepare",
                            step_type=self.action_type,
                            payload=task_payload,
                            max_attempts=2,
                        )
                    ],
                )
            ],
        )

    async def execute_step(self, db: AsyncSession, step: TaskStep, payload: dict[str, Any]) -> dict[str, Any]:
        product_id = _product_id(payload)
        await update_step_progress(
            db,
            step,
            current=0,
            total=1,
            message="开始解析 GIGA 商品页并下载素材包",
            data={"product_id": product_id, "test_session_key": payload.get("test_session_key")},
        )
        material_result = await prepare_product_materials(
            db,
            product_id=product_id,
            source_task_run_id=int(payload.get("origin_task_run_id") or step.task_run_id or 0) or None,
            test_session_key=str(payload.get("test_session_key") or "").strip() or None,
        )
        return {"product_id": product_id, "material_prepare": material_result}

    async def on_step_success(self, db: AsyncSession, step: TaskStep, result: dict[str, Any]) -> None:
        product_id = int(result.get("product_id") or _payload_for_step(step).get("product_id") or 0)
        product = await _load_product(db, product_id)
        now = datetime.now()
        product.status = "created"
        product.current_step = 1
        product.error_message = None
        set_product_workflow(
            product,
            node=WORKFLOW_NODE_AUTO_SELECT_IMAGES,
            status=WORKFLOW_STATUS_PENDING,
            error=None,
            now=now,
        )
        product.updated_at = now
        _sync_catalog_item(product)
        await db.commit()

        payload = _payload_for_step(step)
        async with async_session() as planner_db:
            runs = await create_product_action_runs(
                planner_db,
                "product_auto_image_selection",
                [{
                    "product_id": product_id,
                    "created_by": "product_material_prepare",
                    "pipeline_target": payload.get("pipeline_target"),
                    "test_session_key": payload.get("test_session_key"),
                    "origin_task_run_id": payload.get("origin_task_run_id"),
                }],
                created_by="product_material_prepare",
                auto_start=True,
            )
        result["next_task_run_ids"] = [run.id for run in runs]
        await _best_effort_update_step_progress(
            db,
            step,
            current=1,
            total=1,
            message="供应商素材准备完成，已进入自动选图",
            data={"product_id": product_id, "next_task_run_ids": result["next_task_run_ids"]},
        )

    async def on_step_failure(self, db: AsyncSession, step: TaskStep, error: Exception) -> None:
        product_id = int(_payload_for_step(step).get("product_id") or 0)
        if product_id > 0:
            await _project_material_prepare_failed(
                db,
                product_id=product_id,
                message=f"供应商素材准备失败: {type(error).__name__}: {error}",
            )

    async def on_step_interrupted(self, db: AsyncSession, step: TaskStep, reason: str | None = None) -> None:
        product_id = int(_payload_for_step(step).get("product_id") or 0)
        if product_id > 0:
            await _project_material_prepare_failed(
                db,
                product_id=product_id,
                message=f"供应商素材准备任务已中断: {reason or '服务重启或执行锁超时'}",
                paused=True,
            )

    async def on_cancel_requested(self, db: AsyncSession, run: TaskRun, reason: str | None = None) -> None:
        product_id = int(_payload_for_run(run).get("product_id") or 0)
        if product_id > 0:
            await _project_material_prepare_failed(
                db,
                product_id=product_id,
                message=f"供应商素材准备任务已取消: {reason or '用户取消'}",
                paused=True,
            )


async def _create_or_reuse_keyword_research_after_auto_competitor(product_id: int) -> list[int]:
    async with async_session() as planner_db:
        runs = await create_product_action_runs(
            planner_db,
            "product_keyword_research",
            [{"product_id": product_id, "created_by": "product_auto_competitor_selection"}],
            created_by="product_auto_competitor_selection",
            auto_start=True,
        )
        return [run.id for run in runs]


async def _reload_step_for_product_action(db: AsyncSession, step_id: int) -> TaskStep | None:
    result = await db.execute(
        select(TaskStep)
        .where(TaskStep.id == step_id)
        .options(selectinload(TaskStep.task_run), selectinload(TaskStep.task_group))
    )
    return result.scalar_one_or_none()


async def _best_effort_update_step_progress(
    db: AsyncSession,
    step: TaskStep,
    *,
    current: int,
    total: int,
    message: str,
    data: dict[str, Any],
) -> None:
    try:
        await update_step_progress(
            db,
            step,
            current=current,
            total=total,
            message=message,
            data=data,
        )
    except Exception:
        await db.rollback()
        logger.exception(
            "Product action success projection completed, but final progress event failed: step_id=%s",
            step.id,
        )


def _project_listing_completed(product: Product) -> None:
    _raise_if_customer_mindset_missing(product)
    if not _listing_content_ready(product):
        raise RuntimeError("Listing 生成未落库标题、商品亮点和五点，不能进入待导出")
    _raise_if_e5_export_ready_protected(product, action_label="完成 Listing 并进入待导出")
    now = datetime.now()
    product.status = COMPLETED
    product.current_step = 6
    product.error_message = None
    set_product_workflow(
        product,
        node=WORKFLOW_NODE_FLOW_DONE,
        status=WORKFLOW_STATUS_SUCCEEDED,
        error=None,
        now=now,
    )
    product.updated_at = now

    pd = product.data
    item = product.catalog_item
    if not item:
        item = CatalogProduct(source_product_id=product.id, gigab2b_url=product.gigab2b_url)
        product.catalog_item = item

    item.gigab2b_url = product.gigab2b_url
    item.gigab2b_product_id = product.gigab2b_product_id
    item.competitor_asin = product.competitor_asin
    item.amazon_asin = product.amazon_asin
    item.asin_sync_status = product.asin_sync_status
    item.asin_synced_at = product.asin_synced_at
    item.asin_sync_error = product.asin_sync_error
    item.amazon_product_status = product.amazon_product_status
    item.amazon_product_status_synced_at = product.amazon_product_status_synced_at
    item.amazon_product_status_error = product.amazon_product_status_error
    item.aplus_upload_status = product.aplus_upload_status
    item.aplus_uploaded_at = product.aplus_uploaded_at
    item.aplus_upload_error = product.aplus_upload_error
    item.upc = product.upc
    item.brand = product.brand
    item.item_code = pd.item_code if pd else None
    item.title = pd.title if pd else None
    item.leaf_category = pd.leaf_category if pd else None
    item.status = product.status
    item.confirmed_at = item.confirmed_at or now
    item.updated_at = now


class ProductAutoImageSelectionAction:
    """节点 1：自动选图，为后续所有视觉节点建立可信的商品图片集合。

    前置与输入：商品必须仍可安全重跑，输入来自 GIGA/供应商图片及已有商品素材；
    `raise_if_auto_image_selection_protected` 会阻止覆盖真实 ASIN、导出记录、A+ 上传等
    不可逆外部结果。执行入口是 `run_auto_image_selection`，任务最多尝试 2 次。

    处理规则：先逐张完成候选图片视觉分析，再选出 1 张主图；Gallery 去重后最多保存
    8 张，且不得重复主图。
    图片引用优先保留可供 VLM 直接访问的 URL，本地路径仅作为已有素材的兼容形式。
    选择依据、顺序、置信度和所用模型一并保留，不能只留下最终路径。

    落库与下游：候选视觉分析结果会沉淀为 `ProductImage.image_analysis`，再写入
    `main_image_path`、`gallery_images`、`gallery_order`、`image_selection_analysis`、
    `image_selected_at` 和 `vlm_model`。后续不再对同一组 Listing 图片二次调用 VLM。
    重跑会清理尚可重建的竞品、图片分析、用户心智、Listing 和 A+ 下游产物；成功后
    唯一进入 `search_competitor/pending`。缺少主图、结果格式错误、取消或中断均按
    fail-closed 投影失败状态，不允许用空结果继续流程。
    """

    action_type = "product_auto_image_selection"

    async def validate(self, db: AsyncSession, payload: dict[str, Any]) -> None:
        product_id = _product_id(payload)
        product = await _load_product(db, product_id)
        raise_if_auto_image_selection_protected(product)

    def dedupe_key(self, payload: dict[str, Any]) -> str | None:
        return f"product_auto_image_selection:product:{_product_id(payload)}"

    def correlation_key(self, payload: dict[str, Any]) -> str | None:
        return f"product:{_product_id(payload)}:auto_image_selection"

    async def reserve(self, db: AsyncSession, payload: dict[str, Any], run: TaskRun) -> None:
        product = await _load_product(db, _product_id(payload))
        raise_if_auto_image_selection_protected(product)
        now = datetime.now()
        product.status = "created"
        product.current_step = 1
        product.error_message = None
        set_product_workflow(
            product,
            node=WORKFLOW_NODE_AUTO_SELECT_IMAGES,
            status=WORKFLOW_STATUS_PROCESSING,
            error=None,
            now=now,
        )
        product.updated_at = now
        _sync_catalog_item(product)

    def build_plan(self, payload: dict[str, Any]) -> TaskRunPlan:
        product_id = _product_id(payload)
        task_payload = {
            "product_id": product_id,
            "pipeline_target": payload.get("pipeline_target"),
            "test_session_key": payload.get("test_session_key"),
            "origin_task_run_id": payload.get("origin_task_run_id"),
        }
        return TaskRunPlan(
            task_type=self.action_type,
            title=f"自动选图：商品 #{product_id}",
            payload=task_payload,
            groups=[
                TaskGroupPlan(
                    group_key="auto_image_selection",
                    title="自动选图",
                    steps=[
                        TaskStepPlan(
                            step_key=f"product:{product_id}:auto_image_selection",
                            step_type=self.action_type,
                            payload=task_payload,
                            max_attempts=2,
                        )
                    ],
                )
            ],
        )

    async def execute_step(self, db: AsyncSession, step: TaskStep, payload: dict[str, Any]) -> dict[str, Any]:
        product_id = _product_id(payload)
        product = await _load_product(db, product_id)
        item_code = product.data.item_code if product.data else product.gigab2b_product_id
        await update_step_progress(
            db,
            step,
            current=0,
            total=1,
            message="开始候选图片视觉分析与自动选图",
            data={"product_id": product_id, "item_code": item_code},
        )
        return {
            "product_id": product_id,
            "item_code": item_code,
            "auto_image_selection": await run_auto_image_selection(product_id, db=db),
        }

    async def on_step_success(self, db: AsyncSession, step: TaskStep, result: dict[str, Any]) -> None:
        product_id = int(result.get("product_id") or _payload_for_step(step).get("product_id") or 0)
        product = await _load_product(db, product_id)
        reasons = auto_image_selection_protection_reasons(product)
        if reasons:
            message = "自动选图成功但商品已有不可逆外部结果，不能静默清理: " + "；".join(reasons)
            await _project_auto_image_selection_failed(db, product_id=product_id, message=message)
            raise RuntimeError(message)

        selection = result.get("auto_image_selection")
        if not isinstance(selection, dict):
            message = "自动选图结果格式不正确"
            await _project_auto_image_selection_failed(db, product_id=product_id, message=message)
            raise RuntimeError(message)
        selected_main = selection.get("selected_main") if isinstance(selection.get("selected_main"), dict) else None
        selected_gallery = selection.get("selected_gallery") if isinstance(selection.get("selected_gallery"), list) else []
        main_path = _selected_listing_image_ref(selected_main)
        if not main_path:
            message = "自动选图结果缺少主图"
            await _project_auto_image_selection_failed(db, product_id=product_id, message=message)
            raise RuntimeError(message)

        now = datetime.now()
        if not product.images:
            product.images = ProductImage(product_id=product.id)
            db.add(product.images)

        _clear_auto_image_downstream_outputs(product)

        gallery_paths: list[str] = []
        for item in selected_gallery[:8]:
            if not isinstance(item, dict):
                continue
            path = _selected_listing_image_ref(item)
            if path and path != main_path and path not in gallery_paths:
                gallery_paths.append(path)
        gallery_order = [
            {"selected_role": "main", **selected_main},
            *[{"selected_role": "gallery", **item} for item in selected_gallery[:8] if isinstance(item, dict)],
        ]

        product.images.main_image_path = main_path
        product.images.main_image_source = "model_selected"
        product.images.gallery_images = json_dumps(gallery_paths)
        product.images.gallery_order = json_dumps(gallery_order)
        product.images.image_selection_analysis = json_dumps(selection)
        product.images.image_analysis = json_dumps(selection_to_image_analysis(selection), ensure_ascii=False)
        product.images.analyzed_at = now
        image_batches = selection.get("image_batches") if isinstance(selection.get("image_batches"), list) else []
        product.images.contact_sheet_path = str(image_batches[0].get("sheet_path")) if image_batches else None
        product.images.image_selected_at = now
        product.images.vlm_model = str(selection.get("model") or settings.VLM_MODEL)

        reviews = selection.get("image_reviews") if isinstance(selection.get("image_reviews"), list) else []
        rejected = selection.get("rejected") if isinstance(selection.get("rejected"), list) else []
        selected_main_asset_id = int(selected_main.get("material_asset_id") or 0) if selected_main else 0
        selected_gallery_asset_ids = {
            int(item.get("material_asset_id") or 0)
            for item in selected_gallery
            if isinstance(item, dict) and int(item.get("material_asset_id") or 0) > 0
        }
        review_by_asset_id = {
            int(review.get("material_asset_id") or 0): review
            for review in reviews
            if isinstance(review, dict) and int(review.get("material_asset_id") or 0) > 0
        }
        rejection_by_asset_id = {
            int(item.get("material_asset_id") or 0): str(item.get("reason") or "not_selected")
            for item in rejected
            if isinstance(item, dict) and int(item.get("material_asset_id") or 0) > 0
        }
        material_asset_ids = set(review_by_asset_id)
        if selected_main_asset_id > 0:
            material_asset_ids.add(selected_main_asset_id)
        material_asset_ids.update(selected_gallery_asset_ids)
        if material_asset_ids:
            asset_result = await db.execute(
                select(ProductMaterialAsset).where(
                    ProductMaterialAsset.product_id == product_id,
                    ProductMaterialAsset.id.in_(material_asset_ids),
                )
            )
            for asset in asset_result.scalars().all():
                review = review_by_asset_id.get(asset.id, {})
                usage = json_loads(asset.downstream_usage_json, [])
                if not isinstance(usage, list):
                    usage = []
                for value in (
                    "contact_sheet_review" if review else None,
                    "listing_main" if asset.id == selected_main_asset_id else None,
                    "listing_gallery" if asset.id in selected_gallery_asset_ids else None,
                ):
                    if value and value not in usage:
                        usage.append(value)
                evidence = review.get("contact_sheet_evidence") if isinstance(review, dict) else {}
                asset.downstream_usage_json = json_dumps(usage)
                if asset.id == selected_main_asset_id or asset.id in selected_gallery_asset_ids:
                    asset.processing_status = "selected"
                    asset.rejection_reason = None
                elif asset.id in rejection_by_asset_id:
                    asset.processing_status = "rejected"
                    asset.rejection_reason = rejection_by_asset_id[asset.id]
                else:
                    asset.processing_status = "analyzed"
                    asset.rejection_reason = None
                asset.contact_sheet_path = str(evidence.get("sheet_path") or "") or None
                asset.contact_sheet_page = int(evidence.get("sheet_page") or 0) or None
                asset.contact_sheet_label = str(evidence.get("sheet_label") or review.get("image_id") or "") or None
                asset.updated_at = now

        artifact_paths: dict[str, str] = {}
        if product.data and product.data.material_dir:
            await write_material_manifest(db, product.id, Path(product.data.material_dir).expanduser().resolve())
            artifact_paths = await write_image_selection_artifacts(
                db,
                product=product,
                selection=selection,
                main_path=main_path,
                gallery_paths=gallery_paths,
            )

        product.status = "created"
        product.current_step = 1
        product.error_message = None
        set_product_workflow(
            product,
            node=WORKFLOW_NODE_SEARCH_COMPETITOR,
            status=WORKFLOW_STATUS_PENDING,
            error=None,
            now=now,
        )
        product.updated_at = now
        _sync_catalog_item(product)
        if product.catalog_item:
            product.catalog_item.updated_at = now

        step.task_run.summary_json = json_dumps({
            "product_id": product_id,
            "item_code": result.get("item_code"),
            "status": "auto_image_selection_done",
            "next_node": WORKFLOW_NODE_SEARCH_COMPETITOR,
            "main_image_path": main_path,
            "gallery_count": len(gallery_paths),
            "confidence": selection.get("confidence"),
            "artifact_paths": artifact_paths,
        })
        await db.commit()
        try:
            competitor_runs = await create_product_action_runs(
                db,
                "product_competitor_search",
                [{
                    "product_id": product_id,
                    "created_by": "product_auto_image_selection",
                    "pipeline_target": product.pipeline_target,
                    "test_session_key": product.pipeline_test_session_key,
                    "origin_task_run_id": product.pipeline_origin_task_run_id,
                }],
                created_by="product_auto_image_selection",
                auto_start=True,
            )
        except Exception as exc:
            await db.rollback()
            message = f"自动选图已完成，但竞品搜索任务创建失败: {type(exc).__name__}: {exc}"
            await _project_competitor_search_failed(db, product_id=product_id, message=message)
            result["status"] = "downstream_failed"
            result["downstream_error"] = message
            return
        competitor_run_ids = [run.id for run in competitor_runs]
        step.task_run.summary_json = json_dumps({
            "product_id": product_id,
            "item_code": result.get("item_code"),
            "status": "auto_image_selection_done",
            "next_node": WORKFLOW_NODE_SEARCH_COMPETITOR,
            "main_image_path": main_path,
            "gallery_count": len(gallery_paths),
            "confidence": selection.get("confidence"),
            "competitor_search_task_run_ids": competitor_run_ids,
            "artifact_paths": artifact_paths,
        })
        await db.commit()
        await _best_effort_update_step_progress(
            db,
            step,
            current=1,
            total=1,
            message="自动选图完成，已提交竞品搜索任务",
            data={
                "product_id": product_id,
                "item_code": result.get("item_code"),
                "gallery_count": len(gallery_paths),
                "competitor_search_task_run_ids": competitor_run_ids,
            },
        )
        result["status"] = "done"
        result["next_node"] = WORKFLOW_NODE_SEARCH_COMPETITOR
        result["competitor_search_task_run_ids"] = competitor_run_ids

    async def on_step_failure(self, db: AsyncSession, step: TaskStep, error: Exception) -> None:
        product_id = int(_payload_for_step(step).get("product_id") or 0)
        if product_id <= 0:
            return
        await _project_auto_image_selection_failed(
            db,
            product_id=product_id,
            message=f"自动选图失败: {type(error).__name__}: {error}",
        )

    async def on_step_interrupted(self, db: AsyncSession, step: TaskStep, reason: str | None = None) -> None:
        product_id = int(_payload_for_step(step).get("product_id") or 0)
        if product_id <= 0:
            return
        await _project_auto_image_selection_failed(
            db,
            product_id=product_id,
            message=f"自动选图任务已中断: {reason or '服务重启或执行锁超时'}",
        )

    async def on_cancel_requested(self, db: AsyncSession, run: TaskRun, reason: str | None = None) -> None:
        product_id = int(_payload_for_run(run).get("product_id") or 0)
        if product_id <= 0:
            return
        await _project_auto_image_selection_failed(
            db,
            product_id=product_id,
            message=f"自动选图任务已取消: {reason or '用户取消'}",
        )


class ProductCompetitorSearchAction:
    """节点 2：自动搜索 Amazon 竞品，生成可审计的候选池。

    前置与输入：商品须有已确认主图且处于搜索/允许重搜状态；查询词由
    `build_amazon_competitor_queries` 根据商品名称、类目、属性等事实生成。已有真实
    ASIN、导出或其它受保护外部结果时禁止重跑。任务本身最多尝试 1 次。

    数量与过滤：每个查询当前默认最多取 12 条，事实源为
    `settings.AMAZON_SEARCH_PER_QUERY_LIMIT`；跨查询按 ASIN 去重后的候选总数当前默认
    最多 20 条，事实源为 `settings.AMAZON_SEARCH_MAX_CANDIDATES`。Sponsored、配件、
    replacement part、cover only 等风险项必须标记或排除，不能伪装为完整同类商品。

    落库与下游：保存搜索 run/step、查询来源、排名、ASIN、标题、价格、评分、评论数、
    主图 URL 和风险证据；成功后进入 `visual_match_competitors/pending` 并创建视觉初筛
    任务。真实 Amazon 搜索 adapter 默认关闭，未显式配置时必须失败，不得用假数据或
    静默打开浏览器冒充 API 成功。
    """

    action_type = "product_competitor_search"

    async def validate(self, db: AsyncSession, payload: dict[str, Any]) -> None:
        product_id = _product_id(payload)
        product = await _load_product(db, product_id)
        reasons = auto_image_selection_protection_reasons(product)
        if reasons:
            raise RuntimeError("当前商品已有不可逆外部结果，不能自动搜索竞品：" + "；".join(reasons))
        if product.workflow_node not in {WORKFLOW_NODE_SEARCH_COMPETITOR, WORKFLOW_NODE_VISUAL_MATCH_COMPETITORS}:
            raise RuntimeError("当前商品不在搜索竞品节点，不能启动自动竞品搜索")
        if (
            product.workflow_node == WORKFLOW_NODE_VISUAL_MATCH_COMPETITORS
            and product.workflow_status not in {WORKFLOW_STATUS_PENDING, WORKFLOW_STATUS_FAILED}
        ):
            raise RuntimeError("当前视觉初筛状态不可重新搜索竞品")
        if (
            product.workflow_node == WORKFLOW_NODE_SEARCH_COMPETITOR
            and product.workflow_status in {WORKFLOW_STATUS_FAILED, WORKFLOW_STATUS_PROCESSING}
            and not _is_auto_competitor_search_product(product)
        ):
            raise RuntimeError("当前商品属于旧竞品搜索状态；旧人工搜索入口已停用，请先重新进入当前自动竞品搜索节点")
        if product.workflow_status not in {WORKFLOW_STATUS_PENDING, WORKFLOW_STATUS_FAILED, WORKFLOW_STATUS_PROCESSING}:
            raise RuntimeError("当前搜索竞品状态不可启动自动竞品搜索")
        if not (product.images and product.images.main_image_path):
            raise RuntimeError("自动竞品搜索缺少已确认商品主图")
        build_amazon_competitor_queries(product)

    def dedupe_key(self, payload: dict[str, Any]) -> str | None:
        return f"product_competitor_search:product:{_product_id(payload)}"

    def correlation_key(self, payload: dict[str, Any]) -> str | None:
        return f"product:{_product_id(payload)}:competitor_search"

    async def reserve(self, db: AsyncSession, payload: dict[str, Any], run: TaskRun) -> None:
        product_id = _product_id(payload)
        product = await _load_product(db, product_id)
        now = datetime.now()
        await clear_current_visual_match(db, product_id, now=now)
        product.status = "competitor_searching"
        product.current_step = 2
        product.error_message = "自动竞品搜索已加入任务中心队列"
        set_product_workflow(
            product,
            node=WORKFLOW_NODE_SEARCH_COMPETITOR,
            status=WORKFLOW_STATUS_PROCESSING,
            error=None,
            now=now,
        )
        product.updated_at = now
        _sync_catalog_item(product)

    def build_plan(self, payload: dict[str, Any]) -> TaskRunPlan:
        product_id = _product_id(payload)
        return TaskRunPlan(
            task_type=self.action_type,
            title=f"自动竞品搜索：商品 #{product_id}",
            payload={"product_id": product_id},
            groups=[
                TaskGroupPlan(
                    group_key="competitor_search",
                    title="自动竞品搜索",
                    steps=[
                        TaskStepPlan(
                            step_key=f"product:{product_id}:competitor_search",
                            step_type=self.action_type,
                            payload={"product_id": product_id},
                            max_attempts=1,
                        )
                    ],
                )
            ],
        )

    async def execute_step(self, db: AsyncSession, step: TaskStep, payload: dict[str, Any]) -> dict[str, Any]:
        product_id = _product_id(payload)
        product = await _load_product(db, product_id)
        item_code = product.data.item_code if product.data else product.gigab2b_product_id
        query_plan = build_amazon_competitor_queries(product)
        queries = query_plan.get("queries") if isinstance(query_plan.get("queries"), list) else []
        await update_step_progress(
            db,
            step,
            current=0,
            total=max(len(queries), 1),
            message="开始自动竞品搜索",
            data={"product_id": product_id, "item_code": item_code, "query_count": len(queries)},
        )
        marketplace = (product.source_site or "US").strip().upper()
        results = await run_amazon_search_queries(
            queries,
            marketplace=marketplace,
            per_query_limit=settings.AMAZON_SEARCH_PER_QUERY_LIMIT,
            product_id=product_id,
            item_code=str(item_code or ""),
            task_run_id=step.task_run_id,
            task_step_id=step.id,
        )
        result_payload = {
            "product_id": product_id,
            "item_code": item_code,
            "query_plan": query_plan,
            "search_results": [
                {
                    "query": item.query,
                    "query_intent": item.query_intent,
                    "query_index": item.query_index,
                    "captured_at": item.captured_at.isoformat(),
                    "raw_search_page": item.raw_search_page,
                    "candidates": [candidate_to_dict(candidate) for candidate in item.candidates],
                }
                for item in results
            ],
        }
        await update_step_progress(
            db,
            step,
            current=len(results),
            total=max(len(queries), 1),
            message="自动竞品搜索页面解析完成",
            data={"product_id": product_id, "result_query_count": len(results)},
        )
        return result_payload

    async def on_step_success(self, db: AsyncSession, step: TaskStep, result: dict[str, Any]) -> None:
        product_id = int(result.get("product_id") or _payload_for_step(step).get("product_id") or 0)
        product = await _load_product(db, product_id)
        raw_results = result.get("search_results") if isinstance(result.get("search_results"), list) else []
        now = datetime.now()
        written_count = await _upsert_competitor_search_candidates(
            db,
            product=product,
            step=step,
            search_results=raw_results,
            now=now,
        )
        if written_count <= 0:
            message = "自动竞品搜索未得到可落库的 ASIN 候选"
            await _project_competitor_search_failed(db, product_id=product_id, message=message)
            raise RuntimeError(message)

        product.status = "created"
        product.current_step = 2
        product.error_message = None
        set_product_workflow(
            product,
            node=WORKFLOW_NODE_VISUAL_MATCH_COMPETITORS,
            status=WORKFLOW_STATUS_PENDING,
            error=None,
            now=now,
        )
        product.updated_at = now
        _sync_catalog_item(product)
        step.task_run.summary_json = json_dumps({
            "product_id": product_id,
            "item_code": result.get("item_code"),
            "status": "competitor_search_done",
            "next_node": WORKFLOW_NODE_VISUAL_MATCH_COMPETITORS,
            "query_count": len(raw_results),
            "candidate_count": written_count,
        })
        await db.commit()
        try:
            visual_runs = await create_product_action_runs(
                db,
                "product_competitor_visual_match",
                [{"product_id": product_id, "created_by": "product_competitor_search"}],
                created_by="product_competitor_search",
                auto_start=True,
            )
        except Exception as exc:
            await db.rollback()
            message = f"竞品搜索已完成，但视觉初筛任务创建失败: {type(exc).__name__}: {exc}"
            await _project_competitor_visual_match_failed(db, product_id=product_id, message=message)
            result["status"] = "downstream_failed"
            result["downstream_error"] = message
            return
        visual_run_ids = [run.id for run in visual_runs]
        step.task_run.summary_json = json_dumps({
            "product_id": product_id,
            "item_code": result.get("item_code"),
            "status": "competitor_search_done",
            "next_node": WORKFLOW_NODE_VISUAL_MATCH_COMPETITORS,
            "query_count": len(raw_results),
            "candidate_count": written_count,
            "competitor_visual_match_task_run_ids": visual_run_ids,
        })
        await db.commit()
        await _best_effort_update_step_progress(
            db,
            step,
            current=len(raw_results),
            total=max(len(raw_results), 1),
            message="自动竞品搜索完成，已提交视觉初筛任务",
            data={
                "product_id": product_id,
                "candidate_count": written_count,
                "competitor_visual_match_task_run_ids": visual_run_ids,
            },
        )
        result["status"] = "done"
        result["next_node"] = WORKFLOW_NODE_VISUAL_MATCH_COMPETITORS
        result["candidate_count"] = written_count
        result["competitor_visual_match_task_run_ids"] = visual_run_ids

    async def on_step_failure(self, db: AsyncSession, step: TaskStep, error: Exception) -> None:
        product_id = int(_payload_for_step(step).get("product_id") or 0)
        if product_id <= 0:
            return
        if isinstance(error, AmazonSearchPageError):
            message = f"自动竞品搜索失败: {error.error_type}: {error}"
        elif isinstance(error, CompetitorQueryError):
            message = f"自动竞品搜索失败: {error}"
        else:
            message = f"自动竞品搜索失败: {type(error).__name__}: {error}"
        await _project_competitor_search_failed(db, product_id=product_id, message=message)

    async def on_step_interrupted(self, db: AsyncSession, step: TaskStep, reason: str | None = None) -> None:
        product_id = int(_payload_for_step(step).get("product_id") or 0)
        if product_id <= 0:
            return
        await _project_competitor_search_failed(
            db,
            product_id=product_id,
            message=f"自动竞品搜索任务已中断: {reason or '服务重启或执行锁超时'}",
        )

    async def on_cancel_requested(self, db: AsyncSession, run: TaskRun, reason: str | None = None) -> None:
        product_id = int(_payload_for_run(run).get("product_id") or 0)
        if product_id <= 0:
            return
        await _project_competitor_search_failed(
            db,
            product_id=product_id,
            message=f"自动竞品搜索任务已取消: {reason or '用户取消'}",
        )


async def _upsert_competitor_search_candidates(
    db: AsyncSession,
    *,
    product: Product,
    step: TaskStep,
    search_results: list[dict[str, Any]],
    now: datetime,
) -> int:
    max_candidates = max(1, int(settings.AMAZON_SEARCH_MAX_CANDIDATES or 20))
    flattened = _round_robin_competitor_candidates(search_results, max_candidates=max_candidates)

    if not flattened:
        return 0

    existing_result = await db.execute(
        select(AmazonCompetitorSearchCandidate).where(
            AmazonCompetitorSearchCandidate.product_id == product.id,
            AmazonCompetitorSearchCandidate.asin.in_([item["asin"] for item in flattened]),
        )
    )
    existing_by_asin = {item.asin: item for item in existing_result.scalars().all()}
    written = 0
    for index, item in enumerate(flattened, start=1):
        candidate = item["candidate"]
        result = item["result"]
        asin = item["asin"]
        flags = _competitor_candidate_flags(candidate)
        row = existing_by_asin.get(asin)
        if not row:
            row = AmazonCompetitorSearchCandidate(product_id=product.id, asin=asin)
            db.add(row)
        row.task_run_id = step.task_run_id
        row.task_step_id = step.id
        row.source_data_source_id = product.source_data_source_id
        row.source_site = product.source_site
        row.source_batch_id = product.source_batch_id
        row.item_code = product.data.item_code if product.data else product.gigab2b_product_id
        row.sku_code = _candidate_sku_code(product)
        row.search_query = str(result.get("query") or candidate.get("search_query") or "").strip()
        row.query_intent = str(result.get("query_intent") or "").strip() or None
        row.query_index = int(result.get("query_index") or 0) or None
        row.search_rank = int(candidate.get("search_rank") or index)
        row.source = "amazon_search_page"
        row.captured_at = _parse_iso_datetime(result.get("captured_at")) or now
        row.url = candidate.get("url")
        row.title = candidate.get("title")
        row.image_url = candidate.get("image_url")
        row.price = candidate.get("price")
        row.rating = candidate.get("rating")
        row.review_count = candidate.get("review_count")
        row.sponsored = 1 if candidate.get("sponsored") else 0
        row.is_accessory = 1 if flags["is_accessory"] else 0
        row.is_replacement_part = 1 if flags["is_replacement_part"] else 0
        row.is_cover_only = 1 if flags["is_cover_only"] else 0
        row.is_excluded = 1 if flags["is_excluded"] else 0
        row.exclusion_reason = flags["exclusion_reason"]
        row.raw_candidate_json = json_dumps(candidate)
        row.raw_search_page_json = json_dumps(result.get("raw_search_page") if isinstance(result.get("raw_search_page"), dict) else {})
        row.updated_at = now
        written += 1
    return written


def _round_robin_competitor_candidates(
    search_results: list[dict[str, Any]],
    *,
    max_candidates: int,
) -> list[dict[str, Any]]:
    """Deduplicate while preserving evidence from every search intent.

    Sequential flattening allowed the first two 12-result queries to exhaust a
    20-candidate pool, so the third query never participated. Round-robin by
    search rank gives each real query a chance before deeper results are used.
    """
    buckets: list[tuple[dict[str, Any], list[dict[str, Any]]]] = []
    for result in search_results:
        if not isinstance(result, dict):
            continue
        candidates = result.get("candidates") if isinstance(result.get("candidates"), list) else []
        buckets.append((result, [item for item in candidates if isinstance(item, dict)]))

    flattened: list[dict[str, Any]] = []
    seen: set[str] = set()
    depth = max((len(candidates) for _, candidates in buckets), default=0)
    for rank_offset in range(depth):
        for result, candidates in buckets:
            if rank_offset >= len(candidates):
                continue
            candidate = candidates[rank_offset]
            asin = str(candidate.get("asin") or "").strip().upper()
            if not asin or asin in seen:
                continue
            seen.add(asin)
            flattened.append({"result": result, "candidate": candidate, "asin": asin})
            if len(flattened) >= max_candidates:
                return flattened
    return flattened


def _competitor_candidate_flags(candidate: dict[str, Any]) -> dict[str, Any]:
    title = str(candidate.get("title") or "").lower()
    is_accessory = any(term in title for term in ("accessory", "accessories", "parts kit"))
    is_replacement_part = any(term in title for term in ("replacement", "spare part", "repair part"))
    is_cover_only = any(term in title for term in ("cover only", "slipcover", "cover replacement"))
    exclusion_reasons: list[str] = []
    if candidate.get("sponsored"):
        exclusion_reasons.append("sponsored")
    if is_accessory:
        exclusion_reasons.append("accessory")
    if is_replacement_part:
        exclusion_reasons.append("replacement_part")
    if is_cover_only:
        exclusion_reasons.append("cover_only")
    return {
        "is_accessory": is_accessory,
        "is_replacement_part": is_replacement_part,
        "is_cover_only": is_cover_only,
        "is_excluded": bool(exclusion_reasons),
        "exclusion_reason": ",".join(exclusion_reasons) or None,
    }


def _candidate_sku_code(product: Product) -> str | None:
    snapshot = _json_from_text(product.data.gigab2b_raw_snapshot) if product.data else {}
    if isinstance(snapshot, dict):
        value = snapshot.get("representative_sku") or snapshot.get("sku_code")
        if value:
            return str(value)
    return product.data.item_code if product.data else None


def _parse_iso_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except Exception:
        return None


def _is_auto_competitor_search_product(product: Product) -> bool:
    marker = "自动竞品搜索"
    return marker in str(product.error_message or "") or marker in str(product.workflow_error or "")


class ProductCompetitorVisualMatchAction:
    """节点 3：用图片证据对竞品候选做视觉初筛，缩小后续详情抓取范围。

    前置与输入：只读取最近一次成功搜索 run/step 的当前候选；源商品使用已确认主图
    URL，候选使用各自 `image_url`，两者直接交给 VLM。此节点不会下载候选图，也不会
    拼 Contact Sheet，因此模型判断必须可追溯到原始 URL 和当前搜索批次。

    处理与限制：目标是选出 Top 4-6 个外观和产品类型相符的候选，记录视觉排名、
    相似度、选择理由、风险及 `visual_selected_for_capture`。任务最多尝试 1 次；选择
    数量必须大于 0，后续详情抓取还会执行最多 6 个候选的硬校验。

    落库与下游：视觉结果绑定当前 search run/step 和本任务 run/step；写入成功后进入
    `capture_competitor_candidates` 并自动创建候选详情抓取任务。无合格候选、VLM/API/
    TLS 错误或证据批次不一致均 fail closed，失败态不得保留一组“当前已选”候选。
    """

    action_type = "product_competitor_visual_match"

    async def validate(self, db: AsyncSession, payload: dict[str, Any]) -> None:
        product_id = _product_id(payload)
        product = await _load_product(db, product_id)
        reasons = product_external_result_protection_reasons(product)
        if reasons:
            raise RuntimeError("当前商品已有不可逆外部结果，不能自动视觉初筛竞品：" + "；".join(reasons))
        if product.workflow_node != WORKFLOW_NODE_VISUAL_MATCH_COMPETITORS:
            raise RuntimeError("当前商品不在视觉初筛竞品节点，不能启动视觉初筛")
        if product.workflow_status not in {WORKFLOW_STATUS_PENDING, WORKFLOW_STATUS_FAILED}:
            raise RuntimeError("当前视觉初筛状态不可启动或重试")
        await _latest_successful_competitor_search_ids(db, product_id)

    def dedupe_key(self, payload: dict[str, Any]) -> str | None:
        return f"product_competitor_visual_match:product:{_product_id(payload)}"

    def correlation_key(self, payload: dict[str, Any]) -> str | None:
        return f"product:{_product_id(payload)}:competitor_visual_match"

    async def reserve(self, db: AsyncSession, payload: dict[str, Any], run: TaskRun) -> None:
        product_id = _product_id(payload)
        product = await _load_product(db, product_id)
        now = datetime.now()
        await clear_current_visual_match(db, product_id, now=now)
        product.status = "competitor_visual_matching"
        product.current_step = 2
        product.error_message = "竞品视觉初筛已加入任务中心队列"
        set_product_workflow(
            product,
            node=WORKFLOW_NODE_VISUAL_MATCH_COMPETITORS,
            status=WORKFLOW_STATUS_PROCESSING,
            error=None,
            now=now,
        )
        product.updated_at = now
        _sync_catalog_item(product)

    def build_plan(self, payload: dict[str, Any]) -> TaskRunPlan:
        product_id = _product_id(payload)
        return TaskRunPlan(
            task_type=self.action_type,
            title=f"竞品视觉初筛：商品 #{product_id}",
            payload={"product_id": product_id},
            groups=[
                TaskGroupPlan(
                    group_key="competitor_visual_match",
                    title="竞品视觉初筛",
                    steps=[
                        TaskStepPlan(
                            step_key=f"product:{product_id}:competitor_visual_match",
                            step_type=self.action_type,
                            payload={"product_id": product_id},
                            max_attempts=1,
                        )
                    ],
                )
            ],
        )

    async def execute_step(self, db: AsyncSession, step: TaskStep, payload: dict[str, Any]) -> dict[str, Any]:
        product_id = _product_id(payload)
        product = await _load_product(db, product_id)
        item_code = product.data.item_code if product.data else product.gigab2b_product_id
        await update_step_progress(
            db,
            step,
            current=0,
            total=1,
            message="开始竞品视觉初筛",
            data={"product_id": product_id, "item_code": item_code},
        )
        result = await run_competitor_visual_match(product_id, db=db)
        await update_step_progress(
            db,
            step,
            current=1,
            total=1,
            message="竞品视觉初筛完成",
            data={
                "product_id": product_id,
                "selected_count": result.get("selected_count"),
                "search_run_id": result.get("search_run_id"),
                "search_step_id": result.get("search_step_id"),
            },
        )
        result["item_code"] = item_code
        return result

    async def on_step_success(self, db: AsyncSession, step: TaskStep, result: dict[str, Any]) -> None:
        product_id = int(result.get("product_id") or _payload_for_step(step).get("product_id") or 0)
        product = await _load_product(db, product_id)
        now = datetime.now()
        candidate_results = result.get("candidate_results") if isinstance(result.get("candidate_results"), list) else []
        search_run_id = int(result.get("search_run_id") or 0)
        search_step_id = int(result.get("search_step_id") or 0)
        if not search_run_id or not search_step_id:
            message = "视觉初筛结果缺少当前搜索 run/step 证据"
            await _project_competitor_visual_match_failed(db, product_id=product_id, message=message)
            raise RuntimeError(message)
        written_count = await _write_visual_match_results(
            db,
            product_id=product_id,
            search_run_id=search_run_id,
            search_step_id=search_step_id,
            visual_task_run_id=step.task_run_id,
            visual_task_step_id=step.id,
            candidate_results=candidate_results,
            model=str(result.get("model") or ""),
            now=now,
        )
        selected_count = sum(1 for item in candidate_results if isinstance(item, dict) and item.get("selected_for_capture"))
        if selected_count <= 0 or written_count <= 0:
            message = "竞品视觉初筛未得到可抓详情的 Top 候选"
            await _project_competitor_visual_match_failed(db, product_id=product_id, message=message)
            raise RuntimeError(message)

        product.status = "created"
        product.current_step = 2
        product.error_message = None
        set_product_workflow(
            product,
            node=WORKFLOW_NODE_CAPTURE_COMPETITOR_CANDIDATES,
            status=WORKFLOW_STATUS_PENDING,
            error=None,
            now=now,
        )
        product.updated_at = now
        _sync_catalog_item(product)
        step.task_run.summary_json = json_dumps({
            "product_id": product_id,
            "item_code": result.get("item_code"),
            "status": "competitor_visual_match_done",
            "next_node": WORKFLOW_NODE_CAPTURE_COMPETITOR_CANDIDATES,
            "search_run_id": search_run_id,
            "search_step_id": search_step_id,
            "selected_count": selected_count,
            "valid_image_count": result.get("valid_image_count"),
        })
        await db.commit()
        try:
            capture_runs = await create_product_action_runs(
                db,
                "product_competitor_candidate_capture",
                [
                    {
                        "product_id": product_id,
                        "visual_task_run_id": step.task_run_id,
                        "visual_task_step_id": step.id,
                        "created_by": "product_competitor_visual_match",
                    }
                ],
                created_by="product_competitor_visual_match",
                auto_start=True,
            )
        except Exception as exc:
            await db.rollback()
            message = f"视觉初筛已完成，但候选详情抓取任务创建失败: {type(exc).__name__}: {exc}"
            await _project_competitor_candidate_capture_failed(
                db,
                product_id=product_id,
                message=message,
                workflow_error=json_dumps({"code": "task_run_creation_failed", "message": message}),
            )
            result["status"] = "downstream_failed"
            result["downstream_error"] = message
            return

        capture_run_ids = [run.id for run in capture_runs]
        step.task_run.summary_json = json_dumps({
            "product_id": product_id,
            "item_code": result.get("item_code"),
            "status": "competitor_visual_match_done",
            "next_node": WORKFLOW_NODE_CAPTURE_COMPETITOR_CANDIDATES,
            "candidate_capture_task_run_ids": capture_run_ids,
            "search_run_id": search_run_id,
            "search_step_id": search_step_id,
            "selected_count": selected_count,
            "valid_image_count": result.get("valid_image_count"),
        })
        await db.commit()
        await _best_effort_update_step_progress(
            db,
            step,
            current=1,
            total=1,
            message="竞品视觉初筛完成，已提交候选详情抓取任务",
            data={"product_id": product_id, "selected_count": selected_count, "candidate_capture_task_run_ids": capture_run_ids},
        )
        result["status"] = "done"
        result["next_node"] = WORKFLOW_NODE_CAPTURE_COMPETITOR_CANDIDATES
        result["candidate_capture_task_run_ids"] = capture_run_ids

    async def on_step_failure(self, db: AsyncSession, step: TaskStep, error: Exception) -> None:
        product_id = int(_payload_for_step(step).get("product_id") or 0)
        if product_id <= 0:
            return
        prefix = "竞品视觉初筛失败"
        message = f"{prefix}: {error}" if isinstance(error, CompetitorVisualMatchError) else f"{prefix}: {type(error).__name__}: {error}"
        await _project_competitor_visual_match_failed(db, product_id=product_id, message=message)

    async def on_step_interrupted(self, db: AsyncSession, step: TaskStep, reason: str | None = None) -> None:
        product_id = int(_payload_for_step(step).get("product_id") or 0)
        if product_id <= 0:
            return
        await _project_competitor_visual_match_failed(
            db,
            product_id=product_id,
            message=f"竞品视觉初筛任务已中断: {reason or '服务重启或执行锁超时'}",
        )

    async def on_cancel_requested(self, db: AsyncSession, run: TaskRun, reason: str | None = None) -> None:
        product_id = int(_payload_for_run(run).get("product_id") or 0)
        if product_id <= 0:
            return
        await _project_competitor_visual_match_failed(
            db,
            product_id=product_id,
            message=f"竞品视觉初筛任务已取消: {reason or '用户取消'}",
        )


async def _latest_successful_competitor_search_ids(db: AsyncSession, product_id: int) -> tuple[int, int]:
    run_result = await db.execute(
        select(TaskRun)
        .where(TaskRun.task_type == "product_competitor_search")
        .where(TaskRun.correlation_key == f"product:{product_id}:competitor_search")
        .where(TaskRun.status == RUN_STATUS_SUCCEEDED)
        .order_by(TaskRun.updated_at.desc(), TaskRun.id.desc())
    )
    run = run_result.scalars().first()
    if not run:
        raise RuntimeError("缺少当前成功的自动竞品搜索任务")
    step_result = await db.execute(
        select(TaskStep)
        .where(TaskStep.task_run_id == run.id)
        .where(TaskStep.step_type == "product_competitor_search")
        .where(TaskStep.status == "succeeded")
        .order_by(TaskStep.updated_at.desc(), TaskStep.id.desc())
    )
    step = step_result.scalars().first()
    if not step:
        raise RuntimeError("缺少当前成功的自动竞品搜索步骤")
    return run.id, step.id


async def _write_visual_match_results(
    db: AsyncSession,
    *,
    product_id: int,
    search_run_id: int,
    search_step_id: int,
    visual_task_run_id: int,
    visual_task_step_id: int,
    candidate_results: list[dict[str, Any]],
    model: str,
    now: datetime,
) -> int:
    result = await db.execute(
        select(AmazonCompetitorSearchCandidate)
        .where(AmazonCompetitorSearchCandidate.product_id == product_id)
        .where(AmazonCompetitorSearchCandidate.task_run_id == search_run_id)
        .where(AmazonCompetitorSearchCandidate.task_step_id == search_step_id)
    )
    rows_by_id = {row.id: row for row in result.scalars().all()}
    written = 0
    for item in candidate_results:
        if not isinstance(item, dict):
            continue
        candidate_id = int(item.get("candidate_id") or 0)
        row = rows_by_id.get(candidate_id)
        if not row:
            continue
        row.visual_similarity_score = _float_or_none(item.get("visual_similarity"))
        row.visual_same_product_type = 1 if item.get("same_product_type") else 0 if item.get("same_product_type") is not None else None
        row.visual_attribute_match_score = _float_or_none(item.get("attribute_match"))
        row.visual_title_match_score = _float_or_none(item.get("title_match"))
        row.visual_reject = 1 if item.get("reject") else 0
        row.visual_reject_reason = str(item.get("reject_reason") or "") or None
        row.visual_reason = str(item.get("reason") or "") or None
        row.visual_sheet_path = None
        row.visual_sheet_page = None
        row.visual_sheet_label = None
        row.visual_rank = int(item.get("visual_rank") or 0) or None
        row.visual_selected_for_capture = 1 if item.get("selected_for_capture") else 0
        row.visual_task_run_id = visual_task_run_id
        row.visual_task_step_id = visual_task_step_id
        row.visual_exclusion_reason = str(item.get("visual_exclusion_reason") or "") or None
        row.visual_model = model or None
        row.visual_raw_json = json_dumps(item.get("raw") if isinstance(item.get("raw"), dict) else item)
        row.visual_matched_at = now
        row.updated_at = now
        written += 1
    return written


def _float_or_none(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


async def clear_current_competitor_capture(db: AsyncSession, product_id: int, *, now: datetime | None = None) -> int:
    """Clear current candidate detail facts for a product.

    Search and visual-match facts remain intact; task events are the historical
    diagnostic source for failed/interrupted runs.
    """
    now = now or datetime.now()
    result = await db.execute(
        select(AmazonCompetitorSearchCandidate)
        .where(AmazonCompetitorSearchCandidate.product_id == product_id)
    )
    rows = result.scalars().all()
    for row in rows:
        row.detail_task_run_id = None
        row.detail_task_step_id = None
        row.detail_captured_at = None
        row.brand = None
        row.seller = None
        row.category_rank = None
        row.leaf_category = None
        row.main_image_url = None
        row.bullets_json = None
        row.description = None
        row.product_details_json = None
        row.aplus_text = None
        row.capture_status = None
        row.capture_error = None
        row.capture_raw_json = None
        row.updated_at = now
    return len(rows)


async def clear_current_auto_competitor_selection(
    db: AsyncSession,
    product_id: int,
    *,
    now: datetime | None = None,
    clear_product_fact: bool,
) -> int:
    """Clear current auto-selected competitor facts for a product."""
    now = now or datetime.now()
    product: Product | None = None
    if clear_product_fact:
        product = await _load_product(db, product_id)
        reasons = product_external_result_protection_reasons(product)
        if reasons:
            raise RuntimeError("当前商品已有不可逆外部结果，不能清理当前派生竞品事实：" + "；".join(reasons))

    result = await db.execute(
        select(AmazonCompetitorSearchCandidate)
        .where(AmazonCompetitorSearchCandidate.product_id == product_id)
    )
    rows = result.scalars().all()
    for row in rows:
        row.final_selected = 0
        row.final_rank = None
        row.final_score = None
        row.final_confidence = None
        row.final_dimension_scores_json = None
        row.final_reason = None
        row.final_risks_json = None
        row.final_model = None
        row.final_rule_version = None
        row.final_raw_json = None
        row.final_selected_at = None
        row.updated_at = now

    if product:
        product.competitor_asin = None
        product.updated_at = now
        if product.catalog_item:
            product.catalog_item.competitor_asin = None
            product.catalog_item.updated_at = now
        if product.data:
            snapshot = _json_from_text(product.data.gigab2b_raw_snapshot)
            if isinstance(snapshot, dict):
                snapshot.pop("selected_competitor", None)
                snapshot.pop("auto_competitor_selection", None)
                product.data.gigab2b_raw_snapshot = json_dumps(snapshot)
    return len(rows)


async def _latest_successful_competitor_visual_match_ids(db: AsyncSession, product_id: int) -> tuple[int, int]:
    run_result = await db.execute(
        select(TaskRun)
        .where(TaskRun.task_type == "product_competitor_visual_match")
        .where(TaskRun.correlation_key == f"product:{product_id}:competitor_visual_match")
        .where(TaskRun.status == RUN_STATUS_SUCCEEDED)
        .order_by(TaskRun.updated_at.desc(), TaskRun.id.desc())
    )
    run = run_result.scalars().first()
    if not run:
        raise RuntimeError("缺少当前成功的竞品视觉初筛任务")
    step_result = await db.execute(
        select(TaskStep)
        .where(TaskStep.task_run_id == run.id)
        .where(TaskStep.step_type == "product_competitor_visual_match")
        .where(TaskStep.status == STEP_STATUS_SUCCEEDED)
        .order_by(TaskStep.updated_at.desc(), TaskStep.id.desc())
    )
    step = step_result.scalars().first()
    if not step:
        raise RuntimeError("缺少当前成功的竞品视觉初筛步骤")
    return run.id, step.id


async def _latest_visual_selected_for_capture_ids(db: AsyncSession, product_id: int) -> tuple[int, int]:
    result = await db.execute(
        select(AmazonCompetitorSearchCandidate)
        .where(AmazonCompetitorSearchCandidate.product_id == product_id)
        .where(AmazonCompetitorSearchCandidate.visual_selected_for_capture == 1)
        .where(AmazonCompetitorSearchCandidate.visual_task_run_id.is_not(None))
        .where(AmazonCompetitorSearchCandidate.visual_task_step_id.is_not(None))
        .order_by(
            AmazonCompetitorSearchCandidate.visual_matched_at.desc(),
            AmazonCompetitorSearchCandidate.visual_task_run_id.desc(),
            AmazonCompetitorSearchCandidate.visual_task_step_id.desc(),
            AmazonCompetitorSearchCandidate.id.desc(),
        )
        .limit(1)
    )
    row = result.scalar_one_or_none()
    if not row or not row.visual_task_run_id or not row.visual_task_step_id:
        raise RuntimeError("缺少当前视觉初筛 Top 候选，不能抓取候选竞品详情")
    return int(row.visual_task_run_id), int(row.visual_task_step_id)


async def _current_visual_selected_for_capture(
    db: AsyncSession,
    product_id: int,
    *,
    visual_task_run_id: int | None = None,
    visual_task_step_id: int | None = None,
) -> list[AmazonCompetitorSearchCandidate]:
    if visual_task_run_id is None or visual_task_step_id is None:
        try:
            visual_task_run_id, visual_task_step_id = await _latest_successful_competitor_visual_match_ids(db, product_id)
        except RuntimeError:
            visual_task_run_id, visual_task_step_id = await _latest_visual_selected_for_capture_ids(db, product_id)
    result = await db.execute(
        select(AmazonCompetitorSearchCandidate)
        .where(AmazonCompetitorSearchCandidate.product_id == product_id)
        .where(AmazonCompetitorSearchCandidate.visual_task_run_id == visual_task_run_id)
        .where(AmazonCompetitorSearchCandidate.visual_task_step_id == visual_task_step_id)
        .where(AmazonCompetitorSearchCandidate.visual_selected_for_capture == 1)
        .where(AmazonCompetitorSearchCandidate.visual_rank.is_not(None))
        .order_by(AmazonCompetitorSearchCandidate.visual_rank.asc(), AmazonCompetitorSearchCandidate.id.asc())
    )
    return result.scalars().all()


async def _current_captured_candidates_for_auto_selection(
    db: AsyncSession,
    product_id: int,
    *,
    visual_task_run_id: int | None = None,
    visual_task_step_id: int | None = None,
) -> list[AmazonCompetitorSearchCandidate]:
    rows = await _current_visual_selected_for_capture(
        db,
        product_id,
        visual_task_run_id=visual_task_run_id,
        visual_task_step_id=visual_task_step_id,
    )
    return [row for row in rows if row.capture_status == "succeeded"]


async def _captured_candidate_success_count(db: AsyncSession, product_id: int) -> int:
    result = await db.execute(
        select(AmazonCompetitorSearchCandidate)
        .where(AmazonCompetitorSearchCandidate.product_id == product_id)
        .where(AmazonCompetitorSearchCandidate.capture_status == "succeeded")
    )
    return len(result.scalars().all())


class ProductCompetitorCandidateCaptureAction:
    """节点 4：抓取视觉初筛候选的 Amazon 详情事实，供确定性选品使用。

    前置与输入：只处理当前视觉任务 run/step 中 `visual_selected_for_capture=true` 的
    候选，候选数必须为 1-6；不允许回读旧批次或扩大到整个搜索候选池。执行前会清理
    可重建的旧 capture/selection 结果，已有不可逆外部结果时禁止重跑。

    抓取内容：逐候选获取标题、五点、描述、价格、评分、评论数、图片和详情属性等
    结构化事实。`execute_step` 只返回抓取结果，`on_step_success` 再在单一数据库事务中
    写入当前 capture 证据，避免部分落库被误当成完整成功。任务失败时不可拼接旧详情。

    落库与下游：保存每个候选的抓取状态、事实、错误和来源 run/step；当前集合具备
    可用详情后进入 `auto_select_competitor` 并创建自动选竞品任务。真实详情 adapter
    默认 fail closed，除非显式配置；抓取失败、Top 高位候选全部失败或事务失败都必须
    留下可见错误，不能以空字段继续。
    """

    action_type = "product_competitor_candidate_capture"

    async def validate(self, db: AsyncSession, payload: dict[str, Any]) -> None:
        product_id = _product_id(payload)
        visual_task_run_id, visual_task_step_id = _visual_ids_from_payload(payload)
        product = await _load_product(db, product_id)
        reasons = product_external_result_protection_reasons(product)
        if reasons:
            raise RuntimeError("当前商品已有不可逆外部结果，不能抓取候选竞品详情：" + "；".join(reasons))
        if product.workflow_node != WORKFLOW_NODE_CAPTURE_COMPETITOR_CANDIDATES:
            raise RuntimeError("当前商品不在抓取候选竞品节点，不能启动候选详情抓取")
        if product.workflow_status not in {WORKFLOW_STATUS_PENDING, WORKFLOW_STATUS_FAILED}:
            raise RuntimeError("当前候选详情抓取状态不可启动或重试")
        selected_rows = await _current_visual_selected_for_capture(
            db,
            product_id,
            visual_task_run_id=visual_task_run_id,
            visual_task_step_id=visual_task_step_id,
        )
        selected_count = len(selected_rows)
        if selected_count <= 0:
            raise RuntimeError("缺少当前视觉初筛 Top 候选，不能抓取候选竞品详情")
        if selected_count > 6:
            raise RuntimeError(f"当前视觉初筛 Top 候选超过上限: {selected_count}")

    def dedupe_key(self, payload: dict[str, Any]) -> str | None:
        return f"product_competitor_candidate_capture:product:{_product_id(payload)}"

    def correlation_key(self, payload: dict[str, Any]) -> str | None:
        return f"product:{_product_id(payload)}:competitor_candidate_capture"

    async def reserve(self, db: AsyncSession, payload: dict[str, Any], run: TaskRun) -> None:
        product_id = _product_id(payload)
        product = await _load_product(db, product_id)
        now = datetime.now()
        await clear_current_competitor_capture(db, product_id, now=now)
        await clear_current_auto_competitor_selection(db, product_id, now=now, clear_product_fact=False)
        product.status = "competitor_detail_capturing"
        product.current_step = 2
        product.error_message = "候选竞品详情抓取已加入任务中心队列"
        set_product_workflow(
            product,
            node=WORKFLOW_NODE_CAPTURE_COMPETITOR_CANDIDATES,
            status=WORKFLOW_STATUS_PROCESSING,
            error=None,
            now=now,
        )
        product.updated_at = now
        _sync_catalog_item(product)

    def build_plan(self, payload: dict[str, Any]) -> TaskRunPlan:
        product_id = _product_id(payload)
        visual_task_run_id, visual_task_step_id = _visual_ids_from_payload(payload)
        plan_payload = {"product_id": product_id}
        if visual_task_run_id and visual_task_step_id:
            plan_payload["visual_task_run_id"] = visual_task_run_id
            plan_payload["visual_task_step_id"] = visual_task_step_id
        return TaskRunPlan(
            task_type=self.action_type,
            title=f"抓取候选竞品详情：商品 #{product_id}",
            payload=plan_payload,
            groups=[
                TaskGroupPlan(
                    group_key="competitor_candidate_capture",
                    title="抓取候选竞品详情",
                    steps=[
                        TaskStepPlan(
                            step_key=f"product:{product_id}:competitor_candidate_capture",
                            step_type=self.action_type,
                            payload=plan_payload,
                            max_attempts=1,
                        )
                    ],
                )
            ],
        )

    async def execute_step(self, db: AsyncSession, step: TaskStep, payload: dict[str, Any]) -> dict[str, Any]:
        product_id = _product_id(payload)
        product = await _load_product(db, product_id)
        visual_task_run_id, visual_task_step_id = _visual_ids_from_payload(payload)
        selected_rows = await _current_visual_selected_for_capture(
            db,
            product_id,
            visual_task_run_id=visual_task_run_id,
            visual_task_step_id=visual_task_step_id,
        )
        if not selected_rows:
            raise RuntimeError("缺少当前视觉初筛 Top 候选，不能抓取候选竞品详情")
        if len(selected_rows) > 6:
            raise RuntimeError(f"当前视觉初筛 Top 候选超过上限: {len(selected_rows)}")
        visual_task_run_id = int(selected_rows[0].visual_task_run_id or 0)
        visual_task_step_id = int(selected_rows[0].visual_task_step_id or 0)
        adapter = get_amazon_listing_detail_adapter()
        await update_step_progress(
            db,
            step,
            current=0,
            total=len(selected_rows),
            message="开始抓取候选竞品详情",
            data={
                "product_id": product_id,
                "visual_task_run_id": visual_task_run_id,
                "visual_task_step_id": visual_task_step_id,
                "selected_count": len(selected_rows),
            },
        )
        candidate_results: list[dict[str, Any]] = []
        for index, row in enumerate(selected_rows, start=1):
            asin = str(row.asin or "").strip().upper()
            try:
                detail = await adapter.fetch(
                    asin,
                    url=row.url,
                    marketplace=(product.source_site or "US").strip().upper(),
                    evidence_context=AmazonListingDetailEvidenceContext(
                        task_run_id=step.task_run_id,
                        task_step_id=step.id,
                        product_id=product_id,
                        candidate_id=row.id,
                        visual_rank=row.visual_rank,
                    ),
                )
                detail_dict = listing_detail_to_dict(detail)
                qualified = bool(detail.title or detail.bullets)
                candidate_results.append({
                    "candidate_id": row.id,
                    "asin": asin,
                    "visual_rank": row.visual_rank,
                    "status": "succeeded" if qualified else "failed",
                    "detail": detail_dict if qualified else None,
                    "error_type": None if qualified else "missing_title_and_bullets",
                    "error_message": None if qualified else "候选详情缺少 title 和 bullets",
                    "raw": detail_dict,
                })
            except AmazonListingDetailError as exc:
                candidate_results.append({
                    "candidate_id": row.id,
                    "asin": asin,
                    "visual_rank": row.visual_rank,
                    "status": "failed",
                    "detail": None,
                    "error_type": exc.error_type,
                    "error_message": str(exc),
                    "raw": {"error_type": exc.error_type, "message": str(exc)},
                })
            except Exception as exc:
                candidate_results.append({
                    "candidate_id": row.id,
                    "asin": asin,
                    "visual_rank": row.visual_rank,
                    "status": "failed",
                    "detail": None,
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                    "raw": {"error_type": type(exc).__name__, "message": str(exc)},
                })
            await update_step_progress(
                db,
                step,
                current=index,
                total=len(selected_rows),
                message=f"候选竞品详情抓取进度 {index}/{len(selected_rows)}",
                data={"product_id": product_id, "candidate_id": row.id, "asin": asin},
            )

        success_count = sum(1 for item in candidate_results if item.get("status") == "succeeded")
        warnings: list[str] = []
        if 0 < success_count < len(candidate_results):
            warnings.append("partial_capture")
        if success_count < 3:
            warnings.append("low_success_count")
        top_two = [item for item in candidate_results if int(item.get("visual_rank") or 99) <= 2]
        if top_two and not any(item.get("status") == "succeeded" for item in top_two):
            warnings.append("top_rank_failed")
        result = {
            "product_id": product_id,
            "visual_task_run_id": visual_task_run_id,
            "visual_task_step_id": visual_task_step_id,
            "candidate_results": candidate_results,
            "selected_count": len(selected_rows),
            "success_count": success_count,
            "warnings": warnings,
        }
        if success_count <= 0:
            error_types = sorted({
                str(item.get("error_type") or "capture_failed")
                for item in candidate_results
                if isinstance(item, dict)
            })
            failure_reason = ", ".join(error_types) or "capture_failed"
            step.task_run.summary_json = json_dumps({
                **result,
                "status": "candidate_capture_failed",
                "failure_reason": failure_reason,
            })
            await update_step_progress(
                db,
                step,
                current=len(selected_rows),
                total=len(selected_rows),
                message="候选竞品详情抓取全失败",
                data={"product_id": product_id, "success_count": success_count, "warnings": warnings, "failure_reason": failure_reason},
            )
            raise RuntimeError(f"候选竞品详情抓取全失败: {failure_reason}")
        return result

    async def on_step_success(self, db: AsyncSession, step: TaskStep, result: dict[str, Any]) -> None:
        product_id = int(result.get("product_id") or _payload_for_step(step).get("product_id") or 0)
        if product_id <= 0:
            return
        visual_task_run_id = int(result.get("visual_task_run_id") or 0)
        visual_task_step_id = int(result.get("visual_task_step_id") or 0)
        if not visual_task_run_id or not visual_task_step_id:
            message = "候选详情抓取结果缺少当前视觉 run/step 证据"
            await _project_competitor_candidate_capture_failed(db, product_id=product_id, message=message)
            raise RuntimeError(message)
        selected_rows = await _current_visual_selected_for_capture(
            db,
            product_id,
            visual_task_run_id=visual_task_run_id,
            visual_task_step_id=visual_task_step_id,
        )
        rows_by_id = {row.id: row for row in selected_rows}
        candidate_results = result.get("candidate_results") if isinstance(result.get("candidate_results"), list) else []
        result_ids = {int(item.get("candidate_id") or 0) for item in candidate_results if isinstance(item, dict)}
        if result_ids != set(rows_by_id):
            message = "候选详情抓取结果未完整匹配当前视觉 Top 集合"
            await _project_competitor_candidate_capture_failed(db, product_id=product_id, message=message)
            raise RuntimeError(message)

        now = datetime.now()
        success_count = 0
        for item in candidate_results:
            if not isinstance(item, dict):
                continue
            row = rows_by_id.get(int(item.get("candidate_id") or 0))
            if not row:
                continue
            status = "succeeded" if item.get("status") == "succeeded" else "failed"
            detail = item.get("detail") if isinstance(item.get("detail"), dict) else {}
            row.detail_task_run_id = step.task_run_id
            row.detail_task_step_id = step.id
            row.detail_captured_at = now
            row.capture_status = status
            row.capture_error = None if status == "succeeded" else str(item.get("error_message") or item.get("error_type") or "capture_failed")
            row.capture_raw_json = json_dumps(item.get("raw") if item.get("raw") is not None else item)
            if status == "succeeded":
                row.brand = str(detail.get("brand") or "") or None
                row.seller = str(detail.get("seller") or "") or None
                row.category_rank = str(detail.get("category_rank") or "") or None
                row.leaf_category = str(detail.get("leaf_category") or "") or None
                row.main_image_url = str(detail.get("main_image_url") or "") or None
                bullets = detail.get("bullets") if isinstance(detail.get("bullets"), list) else []
                row.bullets_json = json_dumps([str(value) for value in bullets if str(value or "").strip()])
                row.description = str(detail.get("description") or "") or None
                product_details = detail.get("product_details") if isinstance(detail.get("product_details"), dict) else {}
                row.product_details_json = json_dumps(product_details)
                row.aplus_text = str(detail.get("aplus_text") or "") or None
                success_count += 1
            row.updated_at = now

        if success_count <= 0:
            message = "候选详情抓取没有任何合格成功结果"
            await _project_competitor_candidate_capture_failed(db, product_id=product_id, message=message)
            raise RuntimeError(message)

        product = await _load_product(db, product_id)
        product.status = "created"
        product.current_step = 2
        product.error_message = None
        set_product_workflow(
            product,
            node=WORKFLOW_NODE_AUTO_SELECT_COMPETITOR,
            status=WORKFLOW_STATUS_PENDING,
            error=None,
            now=now,
        )
        product.updated_at = now
        _sync_catalog_item(product)
        warnings = result.get("warnings") if isinstance(result.get("warnings"), list) else []
        step.task_run.summary_json = json_dumps({
            "product_id": product_id,
            "status": "candidate_capture_done",
            "next_node": WORKFLOW_NODE_AUTO_SELECT_COMPETITOR,
            "visual_task_run_id": visual_task_run_id,
            "visual_task_step_id": visual_task_step_id,
            "selected_count": len(selected_rows),
            "success_count": success_count,
            "warnings": warnings,
        })
        await db.commit()
        try:
            auto_selection_runs = await create_product_action_runs(
                db,
                "product_auto_competitor_selection",
                [{"product_id": product_id, "created_by": "product_competitor_candidate_capture"}],
                created_by="product_competitor_candidate_capture",
                auto_start=True,
            )
        except Exception as exc:
            await db.rollback()
            message = f"候选详情抓取已完成，但自动选竞品任务创建失败: {type(exc).__name__}: {exc}"
            await _project_auto_competitor_selection_failed(
                db,
                product_id=product_id,
                message=message,
                workflow_error=json_dumps({"code": "task_run_creation_failed", "message": message}),
            )
            result["status"] = "downstream_failed"
            result["downstream_error"] = message
            return

        auto_selection_run_ids = [run.id for run in auto_selection_runs]
        step.task_run.summary_json = json_dumps({
            "product_id": product_id,
            "status": "candidate_capture_done",
            "next_node": WORKFLOW_NODE_AUTO_SELECT_COMPETITOR,
            "auto_competitor_selection_task_run_ids": auto_selection_run_ids,
            "visual_task_run_id": visual_task_run_id,
            "visual_task_step_id": visual_task_step_id,
            "selected_count": len(selected_rows),
            "success_count": success_count,
            "warnings": warnings,
        })
        await db.commit()
        await _best_effort_update_step_progress(
            db,
            step,
            current=len(selected_rows),
            total=len(selected_rows),
            message="候选竞品详情抓取完成，已提交自动选竞品任务",
            data={
                "product_id": product_id,
                "success_count": success_count,
                "warnings": warnings,
                "auto_competitor_selection_task_run_ids": auto_selection_run_ids,
            },
        )
        result["status"] = "done"
        result["next_node"] = WORKFLOW_NODE_AUTO_SELECT_COMPETITOR
        result["auto_competitor_selection_task_run_ids"] = auto_selection_run_ids

    async def on_step_failure(self, db: AsyncSession, step: TaskStep, error: Exception) -> None:
        product_id = int(_payload_for_step(step).get("product_id") or 0)
        if product_id <= 0:
            return
        await _project_competitor_candidate_capture_failed(
            db,
            product_id=product_id,
            message=f"候选竞品详情抓取失败: {type(error).__name__}: {error}",
        )

    async def on_step_interrupted(self, db: AsyncSession, step: TaskStep, reason: str | None = None) -> None:
        product_id = int(_payload_for_step(step).get("product_id") or 0)
        if product_id <= 0:
            return
        await _project_competitor_candidate_capture_failed(
            db,
            product_id=product_id,
            message=f"候选竞品详情抓取任务已中断: {reason or '服务重启或执行锁超时'}",
        )

    async def on_cancel_requested(self, db: AsyncSession, run: TaskRun, reason: str | None = None) -> None:
        product_id = int(_payload_for_run(run).get("product_id") or 0)
        if product_id <= 0:
            return
        await _project_competitor_candidate_capture_failed(
            db,
            product_id=product_id,
            message=f"候选竞品详情抓取任务已取消: {reason or '用户取消'}",
        )


class ProductAutoCompetitorSelectionAction:
    """节点 5：从成功抓取详情的当前候选中确定最终参考竞品。

    前置与输入：只消费当前视觉集合内、详情抓取成功且证据完整的候选；缺少候选或
    当前流程状态不符时拒绝执行。选定逻辑是可复现的规则评分，不由 LLM 自由决定，
    当前模型标识为 `rule_based_auto_competitor_v1`，规则版本为
    `auto_competitor_selection_v1`。

    处理规则：综合产品类型/标题匹配、视觉排名、详情完整度、价格、评分、评论量和
    风险信号排序；硬拒绝、证据不足或低置信度时 fail closed。最终结果必须保留每个
    候选的分数构成和拒绝原因，便于以后解释为什么选中该 ASIN。

    落库与下游：写入最终 selected row、`Product.competitor_asin`、CatalogProduct 和
    GIGA snapshot 的竞品事实；成功后创建 `product_keyword_research`，进入“商品准备”，
    不能跳过关键词/定价/类目直接做图片分析。取消、中断或落库失败会清除不完整的
    当前选择投影，不得保留半成功竞品。
    """

    action_type = "product_auto_competitor_selection"

    async def validate(self, db: AsyncSession, payload: dict[str, Any]) -> None:
        product_id = _product_id(payload)
        product = await _load_product(db, product_id)
        reasons = product_external_result_protection_reasons(product)
        if reasons:
            raise RuntimeError("当前商品已有不可逆外部结果，不能自动选择竞品：" + "；".join(reasons))
        if product.workflow_node != WORKFLOW_NODE_AUTO_SELECT_COMPETITOR:
            raise RuntimeError("当前商品不在自动选竞品节点，不能启动自动选择")
        if product.workflow_status not in {WORKFLOW_STATUS_PENDING, WORKFLOW_STATUS_FAILED, WORKFLOW_STATUS_PROCESSING}:
            raise RuntimeError("当前自动选竞品状态不可启动或重试")
        rows = await _current_captured_candidates_for_auto_selection(db, product_id)
        if not rows:
            raise RuntimeError("缺少当前视觉集合内已成功抓取详情的候选，不能自动选择竞品")
        _score_auto_competitor_candidates(product, rows)

    def dedupe_key(self, payload: dict[str, Any]) -> str | None:
        return f"product_auto_competitor_selection:product:{_product_id(payload)}"

    def correlation_key(self, payload: dict[str, Any]) -> str | None:
        return f"product:{_product_id(payload)}:auto_competitor_selection"

    async def reserve(self, db: AsyncSession, payload: dict[str, Any], run: TaskRun) -> None:
        product_id = _product_id(payload)
        product = await _load_product(db, product_id)
        now = datetime.now()
        await clear_current_auto_competitor_selection(db, product_id, now=now, clear_product_fact=True)
        product.status = "auto_competitor_selecting"
        product.current_step = 2
        product.error_message = "自动选竞品已加入任务中心队列"
        set_product_workflow(
            product,
            node=WORKFLOW_NODE_AUTO_SELECT_COMPETITOR,
            status=WORKFLOW_STATUS_PROCESSING,
            error=None,
            now=now,
        )
        product.updated_at = now
        _sync_catalog_item(product)

    def build_plan(self, payload: dict[str, Any]) -> TaskRunPlan:
        product_id = _product_id(payload)
        return TaskRunPlan(
            task_type=self.action_type,
            title=f"自动选竞品：商品 #{product_id}",
            payload={"product_id": product_id},
            groups=[
                TaskGroupPlan(
                    group_key="auto_competitor_selection",
                    title="自动选竞品",
                    steps=[
                        TaskStepPlan(
                            step_key=f"product:{product_id}:auto_competitor_selection",
                            step_type=self.action_type,
                            payload={"product_id": product_id},
                            max_attempts=1,
                        )
                    ],
                )
            ],
        )

    async def execute_step(self, db: AsyncSession, step: TaskStep, payload: dict[str, Any]) -> dict[str, Any]:
        product_id = _product_id(payload)
        product = await _load_product(db, product_id)
        rows = await _current_captured_candidates_for_auto_selection(db, product_id)
        if not rows:
            raise RuntimeError("缺少当前视觉集合内已成功抓取详情的候选，不能自动选择竞品")
        visual_task_run_id = int(rows[0].visual_task_run_id or 0)
        visual_task_step_id = int(rows[0].visual_task_step_id or 0)
        await update_step_progress(
            db,
            step,
            current=0,
            total=len(rows),
            message="开始自动选竞品规则评分",
            data={
                "product_id": product_id,
                "visual_task_run_id": visual_task_run_id,
                "visual_task_step_id": visual_task_step_id,
                "candidate_count": len(rows),
            },
        )
        scored = _score_auto_competitor_candidates(product, rows)
        selected = scored["selected"]
        result = {
            "product_id": product_id,
            "visual_task_run_id": visual_task_run_id,
            "visual_task_step_id": visual_task_step_id,
            "candidate_count": len(rows),
            "success_count": scored["success_count"],
            "selected_candidate_id": selected["candidate_id"],
            "selected_asin": selected["asin"],
            "selected_score": selected["score"],
            "selected_confidence": selected["confidence"],
            "selected_dimensions": selected["dimensions"],
            "selected_reason": selected["reason"],
            "selected_risks": selected["risks"],
            "scored_candidates": scored["scored_candidates"],
            "rule_version": AUTO_COMPETITOR_SELECTION_RULE_VERSION,
            "model": AUTO_COMPETITOR_SELECTION_MODEL,
        }
        step.task_run.summary_json = json_dumps({
            **result,
            "status": "auto_competitor_scored",
        })
        await update_step_progress(
            db,
            step,
            current=len(rows),
            total=len(rows),
            message="自动选竞品规则评分完成",
            data={
                "product_id": product_id,
                "selected_candidate_id": selected["candidate_id"],
                "selected_asin": selected["asin"],
                "confidence": selected["confidence"],
                "score": selected["score"],
            },
        )
        return result

    async def on_step_success(self, db: AsyncSession, step: TaskStep, result: dict[str, Any]) -> None:
        product_id = int(result.get("product_id") or _payload_for_step(step).get("product_id") or 0)
        if product_id <= 0:
            return
        visual_task_run_id = int(result.get("visual_task_run_id") or 0)
        visual_task_step_id = int(result.get("visual_task_step_id") or 0)
        selected_candidate_id = int(result.get("selected_candidate_id") or 0)
        if not visual_task_run_id or not visual_task_step_id or not selected_candidate_id:
            message = "自动选竞品结果缺少 current set 或 selected candidate 证据"
            await _project_auto_competitor_selection_failed(db, product_id=product_id, message=message)
            raise RuntimeError(message)
        product = await _load_product(db, product_id)
        reasons = product_external_result_protection_reasons(product)
        if reasons:
            message = "当前商品已有不可逆外部结果，不能写入自动竞品：" + "；".join(reasons)
            await _project_auto_competitor_selection_failed(db, product_id=product_id, message=message)
            raise RuntimeError(message)
        rows = await _current_captured_candidates_for_auto_selection(
            db,
            product_id,
            visual_task_run_id=visual_task_run_id,
            visual_task_step_id=visual_task_step_id,
        )
        rows_by_id = {row.id: row for row in rows}
        selected_row = rows_by_id.get(selected_candidate_id)
        if not selected_row:
            message = "自动选竞品结果不属于当前视觉/详情集合"
            await _project_auto_competitor_selection_failed(db, product_id=product_id, message=message)
            raise RuntimeError(message)
        rescored = _score_auto_competitor_candidates(product, rows)
        selected = rescored["selected"]
        if int(selected["candidate_id"]) != selected_candidate_id:
            message = "自动选竞品 success hook 重算结果与 execute_step 不一致"
            await _project_auto_competitor_selection_failed(db, product_id=product_id, message=message)
            raise RuntimeError(message)

        now = datetime.now()
        await clear_current_auto_competitor_selection(db, product_id, now=now, clear_product_fact=True)
        product = await _load_product(db, product_id)
        selected_row = rows_by_id[selected_candidate_id]
        selected_row.final_selected = 1
        selected_row.final_rank = 1
        selected_row.final_score = float(selected["score"])
        selected_row.final_confidence = str(selected["confidence"])
        selected_row.final_dimension_scores_json = json_dumps(selected["dimensions"])
        selected_row.final_reason = str(selected["reason"])
        selected_row.final_risks_json = json_dumps(selected["risks"])
        selected_row.final_model = AUTO_COMPETITOR_SELECTION_MODEL
        selected_row.final_rule_version = AUTO_COMPETITOR_SELECTION_RULE_VERSION
        selected_row.final_raw_json = json_dumps({
            "visual_task_run_id": visual_task_run_id,
            "visual_task_step_id": visual_task_step_id,
            "scored_candidates": rescored["scored_candidates"],
            "execute_result": result,
        })
        selected_row.final_selected_at = now
        selected_row.updated_at = now
        asin = str(selected_row.asin or selected["asin"] or "").strip().upper()
        product.competitor_asin = asin
        product.status = "created"
        product.current_step = 3
        product.error_message = None
        product.updated_at = now
        set_product_workflow(
            product,
            node=WORKFLOW_NODE_KEYWORD_RESEARCH,
            status=WORKFLOW_STATUS_PENDING,
            error=None,
            now=now,
        )
        if product.catalog_item:
            product.catalog_item.competitor_asin = asin
            product.catalog_item.updated_at = now
        if product.data:
            snapshot = _json_from_text(product.data.gigab2b_raw_snapshot)
            if not isinstance(snapshot, dict):
                snapshot = {}
            selected_competitor = {
                "asin": asin,
                "candidate_id": selected_row.id,
                "url": selected_row.url,
                "title": selected_row.title,
                "image_url": selected_row.main_image_url or selected_row.image_url,
                "score": selected["score"],
                "confidence": selected["confidence"],
                "selected_at": now.isoformat(),
            }
            snapshot["selected_competitor"] = selected_competitor
            snapshot["auto_competitor_selection"] = {
                "model": AUTO_COMPETITOR_SELECTION_MODEL,
                "rule_version": AUTO_COMPETITOR_SELECTION_RULE_VERSION,
                "visual_task_run_id": visual_task_run_id,
                "visual_task_step_id": visual_task_step_id,
                "selected_candidate_id": selected_row.id,
                "selected_asin": asin,
                "score": selected["score"],
                "confidence": selected["confidence"],
                "risks": selected["risks"],
            }
            product.data.gigab2b_raw_snapshot = json_dumps(snapshot)
        _sync_catalog_item(product)
        step.task_run.summary_json = json_dumps({
            "product_id": product_id,
            "status": "auto_competitor_selected",
            "next_node": WORKFLOW_NODE_IMAGE_ANALYSIS,
            "visual_task_run_id": visual_task_run_id,
            "visual_task_step_id": visual_task_step_id,
            "selected_candidate_id": selected_row.id,
            "selected_asin": asin,
            "score": selected["score"],
            "confidence": selected["confidence"],
            "risks": selected["risks"],
        })
        await db.commit()

        try:
            keyword_run_ids = await _create_or_reuse_keyword_research_after_auto_competitor(product_id)
        except Exception as exc:
            message = f"自动竞品已选定，但创建关键词采集任务失败: {type(exc).__name__}: {exc}"
            await _project_keyword_research_failed(db, product_id=product_id, message=message)
            result["status"] = "downstream_failed"
            result["downstream_error"] = message
            return

        await db.refresh(product)
        step.task_run.summary_json = json_dumps({
            "product_id": product_id,
            "status": "auto_competitor_selected",
            "next_node": WORKFLOW_NODE_KEYWORD_RESEARCH,
            "keyword_research_task_run_ids": keyword_run_ids,
            "selected_candidate_id": selected_row.id,
            "selected_asin": asin,
            "score": selected["score"],
            "confidence": selected["confidence"],
            "risks": selected["risks"],
        })
        await db.commit()
        await _best_effort_update_step_progress(
            db,
            step,
            current=1,
            total=1,
            message="自动选竞品完成，已提交关键词采集任务",
            data={"product_id": product_id, "selected_asin": asin, "keyword_research_task_run_ids": keyword_run_ids},
        )
        result["status"] = "done"
        result["next_node"] = WORKFLOW_NODE_KEYWORD_RESEARCH
        result["keyword_research_task_run_ids"] = keyword_run_ids

    async def on_step_failure(self, db: AsyncSession, step: TaskStep, error: Exception) -> None:
        product_id = int(_payload_for_step(step).get("product_id") or 0)
        if product_id <= 0:
            return
        await _project_auto_competitor_selection_failed(
            db,
            product_id=product_id,
            message=f"自动选竞品失败: {type(error).__name__}: {error}",
        )

    async def on_step_interrupted(self, db: AsyncSession, step: TaskStep, reason: str | None = None) -> None:
        product_id = int(_payload_for_step(step).get("product_id") or 0)
        if product_id <= 0:
            return
        await _project_auto_competitor_selection_failed(
            db,
            product_id=product_id,
            message=f"自动选竞品任务已中断: {reason or '服务重启或执行锁超时'}",
        )

    async def on_cancel_requested(self, db: AsyncSession, run: TaskRun, reason: str | None = None) -> None:
        product_id = int(_payload_for_run(run).get("product_id") or 0)
        if product_id <= 0:
            return
        await _project_auto_competitor_selection_failed(
            db,
            product_id=product_id,
            message=f"自动选竞品任务已取消: {reason or '用户取消'}",
        )


class ProductKeywordResearchAction:
    """节点 6：商品准备，在一个任务内依次完成关键词、定价和 Amazon 类目。

    前置与输入：必须有最终参考竞品 ASIN 和商品基础资料，且没有真实 ASIN、导出、
    A+ 上传等受保护结果。任务最多尝试 2 次，内部顺序固定为 `run_keywords` ->
    `run_pricing` -> `run_category`，任一环节失败都不能进入图片分析。

    关键词：优先通过卖家精灵 OpenAPI 采集并写入 `ProductData.keywords_top`；API 返回
    空结果时才允许 LLM 兜底。只有 OpenAPI 未配置且旧兼容链路需要人工登录时，才可能
    调用浏览器，不能在 API 可用时无故打开浏览器。

    定价：设含运费采购总成本为 T、货值为 G。每单保费 I=2.5%×G、广告预留 A=$2、
    4% 退货下的平均保障赔付 B=4%×60%×G（只赔货值、不赔物流），固定期望成本
    C=T+I+A-B。售价留存收入按 10% 佣金、4% 退货收入损失计算；退货管理费为每笔
    佣金的 20%、最高 $5，再乘实际 4% 退货率。分别求解管理费未封顶与封顶区间，
    同时满足 5% 目标净利率和 $10 最低利润并向上取美分；最终事实源是 `PRICING_*`
    配置和 `step2_pricing.py` 的逐项注释。

    类目与下游：根据已选竞品 ASIN 获取 Amazon 叶子类目。候选图片视觉分析已在选图前
    完成；只有 `keywords_top`、`suggested_price`、`leaf_category` 和该视觉证据均已落库，
    才创建用户心智任务。缺任何一项均 fail closed，并保留具体失败阶段。
    """

    action_type = "product_keyword_research"

    async def validate(self, db: AsyncSession, payload: dict[str, Any]) -> None:
        product = await _load_product(db, _product_id(payload))
        reasons = product_external_result_protection_reasons(product)
        if reasons:
            raise RuntimeError("当前商品已有不可逆外部结果，不能重新采集关键词：" + "；".join(reasons))
        if product.workflow_node != WORKFLOW_NODE_KEYWORD_RESEARCH:
            raise RuntimeError("当前商品不在关键词采集节点，不能启动关键词任务")
        if product.workflow_status not in {WORKFLOW_STATUS_PENDING, WORKFLOW_STATUS_FAILED, WORKFLOW_STATUS_PROCESSING}:
            raise RuntimeError("当前关键词采集状态不可启动或重试")
        if not product.competitor_asin:
            raise RuntimeError("前置节点未完成：缺少已选定的参考竞品 ASIN")
        if not product.data:
            raise RuntimeError("前置节点未完成：缺少商品基础资料，无法生成关键词")

    def dedupe_key(self, payload: dict[str, Any]) -> str | None:
        return f"product_keyword_research:product:{_product_id(payload)}"

    def correlation_key(self, payload: dict[str, Any]) -> str | None:
        return f"product:{_product_id(payload)}:keyword_research"

    async def reserve(self, db: AsyncSession, payload: dict[str, Any], run: TaskRun) -> None:
        product = await _load_product(db, _product_id(payload))
        now = datetime.now()
        product.status = STEP3_KEYWORDS
        product.current_step = 3
        product.error_message = "关键词采集已加入任务中心队列"
        set_product_workflow(
            product,
            node=WORKFLOW_NODE_KEYWORD_RESEARCH,
            status=WORKFLOW_STATUS_PROCESSING,
            error=None,
            now=now,
        )
        product.updated_at = now
        _sync_catalog_item(product)

    def build_plan(self, payload: dict[str, Any]) -> TaskRunPlan:
        product_id = _product_id(payload)
        return TaskRunPlan(
            task_type=self.action_type,
            title=f"商品准备：关键词、定价与类目 #{product_id}",
            payload={"product_id": product_id},
            groups=[
                TaskGroupPlan(
                    group_key="keyword_research",
                    title="关键词、定价与类目",
                    steps=[
                        TaskStepPlan(
                            step_key=f"product:{product_id}:keyword_research",
                            step_type=self.action_type,
                            payload={"product_id": product_id},
                            max_attempts=2,
                        )
                    ],
                )
            ],
        )

    async def execute_step(self, db: AsyncSession, step: TaskStep, payload: dict[str, Any]) -> dict[str, Any]:
        product_id = _product_id(payload)
        product = await _load_product(db, product_id)
        await update_step_progress(
            db,
            step,
            current=0,
            total=3,
            message="开始采集竞品关键词",
            data={"product_id": product_id, "competitor_asin": product.competitor_asin},
        )
        keyword_result = await run_keywords(product_id)
        if not keyword_result.get("top_keywords"):
            raise RuntimeError("关键词采集未返回可用关键词")
        await update_step_progress(
            db,
            step,
            current=1,
            total=3,
            message="关键词采集完成，开始计算建议售价",
            data={"product_id": product_id},
        )
        pricing_result = await run_pricing(product_id)
        await update_step_progress(
            db,
            step,
            current=2,
            total=3,
            message="定价完成，开始匹配 Amazon 类目",
            data={"product_id": product_id},
        )
        category_result = await run_category(product_id)
        return {
            "product_id": product_id,
            "keyword_result": keyword_result,
            "pricing_result": pricing_result,
            "category_result": category_result,
        }

    async def on_step_success(self, db: AsyncSession, step: TaskStep, result: dict[str, Any]) -> None:
        product_id = int(result.get("product_id") or _payload_for_step(step).get("product_id") or 0)
        product = await _load_product(db, product_id)
        await db.refresh(product, attribute_names=["data"])
        if not product.data or not product.data.keywords_top:
            message = "商品准备完成但未落库关键词结果，不能进入用户心智梳理"
            await _project_keyword_research_failed(db, product_id=product_id, message=message)
            raise RuntimeError(message)
        if product.data.suggested_price is None:
            message = "商品准备完成但缺少建议售价，不能进入用户心智梳理"
            await _project_keyword_research_failed(db, product_id=product_id, message=message)
            raise RuntimeError(message)
        if not product.data.leaf_category:
            message = "商品准备完成但缺少 Amazon 类目，不能进入用户心智梳理"
            await _project_keyword_research_failed(db, product_id=product_id, message=message)
            raise RuntimeError(message)
        now = datetime.now()
        if not product.images or not image_analysis_ready(product.images.image_analysis):
            message = "候选图片视觉分析未完成，不能进入用户心智梳理"
            await _project_image_analysis_creation_failed(db, product_id=product_id, message=message)
            raise RuntimeError(message)
        product.status = STEP6_DONE
        product.current_step = 5
        product.error_message = None
        set_product_workflow(
            product,
            node=WORKFLOW_NODE_IMAGE_ANALYSIS,
            status=WORKFLOW_STATUS_SUCCEEDED,
            error=None,
            now=now,
        )
        product.updated_at = now
        _sync_catalog_item(product)
        await db.commit()
        try:
            customer_mindset_runs = await create_product_action_runs(
                db,
                "product_customer_mindset",
                [{"product_id": product_id, "created_by": "product_keyword_research"}],
                created_by="product_keyword_research",
            )
        except Exception as exc:
            await db.rollback()
            message = f"商品准备已完成，但用户心智任务创建失败: {type(exc).__name__}: {exc}"
            await _project_customer_mindset_failed(db, product_id=product_id, message=message)
            result["status"] = "downstream_failed"
            result["downstream_error"] = message
            return
        customer_mindset_run_ids = [run.id for run in customer_mindset_runs]
        step.task_run.summary_json = json_dumps({
            "product_id": product_id,
            "status": "product_preparation_done",
            "next_node": WORKFLOW_NODE_CUSTOMER_MINDSET,
            "keyword_source": "llm_fallback" if result["keyword_result"].get("llm_fallback") else "sellersprite",
            "top_keyword_count": len(result["keyword_result"].get("top_keywords") or []),
            "suggested_price": product.data.suggested_price,
            "leaf_category": product.data.leaf_category,
            "image_analysis_stage": "candidate_vision_before_selection",
            "customer_mindset_task_run_ids": customer_mindset_run_ids,
        })
        await db.commit()
        await _best_effort_update_step_progress(
            db,
            step,
            current=3,
            total=3,
            message="商品准备完成，候选图片视觉分析已复用，已提交用户心智梳理",
            data={"product_id": product_id, "customer_mindset_task_run_ids": customer_mindset_run_ids},
        )
        result["status"] = "done"
        result["next_node"] = WORKFLOW_NODE_CUSTOMER_MINDSET
        result["customer_mindset_task_run_ids"] = customer_mindset_run_ids

    async def on_step_failure(self, db: AsyncSession, step: TaskStep, error: Exception) -> None:
        product_id = int(_payload_for_step(step).get("product_id") or 0)
        if product_id > 0:
            await _project_keyword_research_failed(db, product_id=product_id, message=f"关键词采集失败: {type(error).__name__}: {error}")

    async def on_step_interrupted(self, db: AsyncSession, step: TaskStep, reason: str | None = None) -> None:
        product_id = int(_payload_for_step(step).get("product_id") or 0)
        if product_id > 0:
            await _project_keyword_research_failed(db, product_id=product_id, message=f"关键词采集任务已中断: {reason or '服务重启或执行锁超时'}")

    async def on_cancel_requested(self, db: AsyncSession, run: TaskRun, reason: str | None = None) -> None:
        product_id = int(_payload_for_run(run).get("product_id") or 0)
        if product_id > 0:
            await _project_keyword_research_failed(db, product_id=product_id, message=f"关键词采集任务已取消: {reason or '用户取消'}")


class ProductImageAnalysisAction:
    """节点 7：分析商品自己的已确认图片，建立后续文案可引用的视觉证据。

    前置与输入：商品准备必须完成，并具备主图和 Gallery；输入只来自本商品图片，不能
    把竞品图片当作自身属性证据。远程 URL 直接交给 VLM，本地路径仅兼容历史或人工
    素材。执行入口是 `run_image_analysis`，任务最多尝试 2 次。

    输出内容：逐图识别角色、可见卖点、材质/纹理、结构细节、使用场景、尺寸或包装
    线索、合规风险和证据缺口，并形成跨图汇总。分析支持基于图片集合 fingerprint 的
    缓存，但只有 fingerprint 与输入一致时才能复用。

    真实性与下游：URL VLM 调用失败时不得悄悄下载图片、改走 Contact Sheet 或生成
    占位分析来伪成功；没有真实分析结果必须 fail closed。结果写入 ProductImage 的图片
    分析字段；成功后只创建 `product_customer_mindset`，不能绕过用户心智直接生成
    Listing。取消/中断会投影为暂停或失败，保留可重试性。
    """

    action_type = "product_image_analysis"

    async def validate(self, db: AsyncSession, payload: dict[str, Any]) -> None:
        product_id = _product_id(payload)
        product = await _load_product(db, product_id)
        _raise_if_e5_export_ready_protected(product, action_label="启动图片分析")
        await _assert_step_prerequisites(product_id, 5)

    def dedupe_key(self, payload: dict[str, Any]) -> str | None:
        return f"product_image_analysis:product:{_product_id(payload)}"

    def correlation_key(self, payload: dict[str, Any]) -> str | None:
        return f"product:{_product_id(payload)}:image_analysis"

    async def reserve(self, db: AsyncSession, payload: dict[str, Any], run: TaskRun) -> None:
        product = await _load_product(db, _product_id(payload))
        _raise_if_e5_export_ready_protected(product, action_label="启动图片分析")
        now = datetime.now()
        product.status = STEP6_CURATING
        product.current_step = 5
        product.error_message = "图片分析已加入任务中心队列"
        set_product_workflow(
            product,
            node=WORKFLOW_NODE_IMAGE_ANALYSIS,
            status=WORKFLOW_STATUS_PROCESSING,
            error=product.error_message,
            now=now,
        )
        product.updated_at = now
        _sync_catalog_item(product)

    def build_plan(self, payload: dict[str, Any]) -> TaskRunPlan:
        product_id = _product_id(payload)
        return TaskRunPlan(
            task_type=self.action_type,
            title=f"图片分析：商品 #{product_id}",
            payload={"product_id": product_id},
            groups=[
                TaskGroupPlan(
                    group_key="image_analysis",
                    title="图片分析",
                    steps=[
                        TaskStepPlan(
                            step_key=f"product:{product_id}:image_analysis",
                            step_type=self.action_type,
                            payload={"product_id": product_id},
                            max_attempts=2,
                        )
                    ],
                )
            ],
        )

    async def execute_step(self, db: AsyncSession, step: TaskStep, payload: dict[str, Any]) -> dict[str, Any]:
        product_id = _product_id(payload)
        product = await _load_product(db, product_id)
        item_code = product.data.item_code if product.data else product.gigab2b_product_id
        await update_step_progress(
            db,
            step,
            current=0,
            total=1,
            message="开始图片分析",
            data={"product_id": product_id, "item_code": item_code},
        )
        return {
            "product_id": product_id,
            "item_code": item_code,
            "image_analysis": await run_image_analysis(product_id),
        }

    async def on_step_success(self, db: AsyncSession, step: TaskStep, result: dict[str, Any]) -> None:
        product_id = int(result.get("product_id") or _payload_for_step(step).get("product_id") or 0)
        try:
            product = await _load_product(db, product_id)
        except RuntimeError:
            return
        if (
            product.status == COMPLETED
            and product.workflow_node == WORKFLOW_NODE_FLOW_DONE
            and product.workflow_status == WORKFLOW_STATUS_SUCCEEDED
        ):
            step.task_run.summary_json = json_dumps({
                "product_id": product_id,
                "item_code": result.get("item_code"),
                "status": "already_completed",
                "next_step": None,
                "customer_mindset_task_run_ids": [],
            })
            await db.commit()
            result["status"] = "already_completed"
            result["next_step"] = None
            result["customer_mindset_task_run_ids"] = []
            return
        reasons = _e5_export_ready_protection_reasons(product)
        if reasons:
            message = "图片分析完成，但当前商品已有不可逆外部结果，不能创建用户心智任务：" + "；".join(reasons)
            await _project_customer_mindset_failed(db, product_id=product_id, message=message)
            result["status"] = "downstream_failed"
            result["downstream_error"] = message
            return
        now = datetime.now()
        product.status = STEP6_DONE
        product.current_step = 5
        product.error_message = None
        set_product_workflow(
            product,
            node=WORKFLOW_NODE_IMAGE_ANALYSIS,
            status=WORKFLOW_STATUS_SUCCEEDED,
            error=None,
            now=now,
        )
        product.updated_at = now
        _sync_catalog_item(product)
        try:
            customer_mindset_runs = await create_product_action_runs(
                db,
                self._customer_mindset_action_type(),
                [{"product_id": product_id, "created_by": "product_image_analysis"}],
                created_by="product_image_analysis",
            )
        except Exception as exc:
            await db.rollback()
            message = f"图片分析已完成，但用户心智任务创建失败: {type(exc).__name__}: {exc}"
            await _project_customer_mindset_failed(db, product_id=product_id, message=message)
            result["status"] = "downstream_failed"
            result["downstream_error"] = message
            return
        customer_mindset_run_ids = [run.id for run in customer_mindset_runs]
        step.task_run.summary_json = json_dumps({
            "product_id": product_id,
            "item_code": result.get("item_code"),
            "status": "image_analysis_done",
            "next_step": 6,
            "next_node": WORKFLOW_NODE_CUSTOMER_MINDSET,
            "customer_mindset_task_run_ids": customer_mindset_run_ids,
        })
        await db.commit()
        await _best_effort_update_step_progress(
            db,
            step,
            current=1,
            total=1,
            message="图片分析完成，已提交用户心智梳理",
            data={"product_id": product_id, "item_code": result.get("item_code"), "customer_mindset_task_run_ids": customer_mindset_run_ids},
        )
        result["status"] = "done"
        result["next_step"] = 6
        result["next_node"] = WORKFLOW_NODE_CUSTOMER_MINDSET
        result["customer_mindset_task_run_ids"] = customer_mindset_run_ids

    async def on_step_failure(self, db: AsyncSession, step: TaskStep, error: Exception) -> None:
        product_id = int(_payload_for_step(step).get("product_id") or 0)
        if product_id <= 0:
            return
        await _project_product_failure(db, product_id=product_id, step=5, label="图片分析", error=error)

    async def on_step_interrupted(self, db: AsyncSession, step: TaskStep, reason: str | None = None) -> None:
        product_id = int(_payload_for_step(step).get("product_id") or 0)
        if product_id <= 0:
            return
        await _project_product_paused(
            db,
            product_id=product_id,
            step=5,
            message=f"图片分析任务已中断: {reason or '服务重启或执行锁超时'}",
        )

    async def on_cancel_requested(self, db: AsyncSession, run: TaskRun, reason: str | None = None) -> None:
        product_id = int(_payload_for_run(run).get("product_id") or 0)
        if product_id <= 0:
            return
        await _project_product_paused(
            db,
            product_id=product_id,
            step=5,
            message=f"图片分析任务已取消: {reason or '用户取消'}",
        )

    @staticmethod
    def _customer_mindset_action_type() -> str:
        return "product_customer_mindset"


class ProductCustomerMindsetAction:
    """节点 8：在图片分析后形成统一的买家心智与内容决策简报。

    前置与输入：必须有商品事实、关键词、竞品参考和真实图片分析；关键词只是市场搜索
    信号，竞品只是市场参考，两者都不能证明本商品拥有某项材质、尺寸或功能。任务最多
    尝试 2 次，缺图片分析或商品已进入受保护的待导出状态时拒绝执行。

    问题结构：固定 13 个核心问题，保持稳定顺序；再由第一次 LLM 调用生成 2 至 5 个
    商品专属、高决策影响且不重复的动态问题，共 15 至 18 题。动态问题从实际使用行为、
    材质或性能参数、摆放或环境适配、长期使用或维护、买错风险或证据缺口等视角中，
    按商品证据择优选择。第二次 LLM 调用回答全部问题并生成统一内容策略。

    证据要求：每题保存结论、证据引用、回答状态、置信度、假设、未知项和下游用途；
    无法由自身证据确认的内容必须标为未知或风险，禁止补写成确定 claim。结果写入
    `ProductData.customer_mindset` 和 `customer_mindset_generated_at`。

    下游与失败：只有结构完整且已落库的简报才能创建 `product_listing_generation`。
    问题数/覆盖面不符、证据引用无效、LLM 失败、取消或中断均 fail closed，不允许用
    半份简报生成 Listing。
    """

    action_type = "product_customer_mindset"

    async def validate(self, db: AsyncSession, payload: dict[str, Any]) -> None:
        product_id = _product_id(payload)
        product = await _load_product(db, product_id)
        _raise_if_e5_export_ready_protected(product, action_label="启动用户心智梳理")
        await _assert_step_prerequisites(product_id, 6, require_customer_mindset=False)

    def dedupe_key(self, payload: dict[str, Any]) -> str | None:
        return f"product_customer_mindset:product:{_product_id(payload)}"

    def correlation_key(self, payload: dict[str, Any]) -> str | None:
        return f"product:{_product_id(payload)}:customer_mindset"

    async def reserve(self, db: AsyncSession, payload: dict[str, Any], run: TaskRun) -> None:
        product = await _load_product(db, _product_id(payload))
        _raise_if_e5_export_ready_protected(product, action_label="启动用户心智梳理")
        if not product.images or not image_analysis_ready(product.images.image_analysis):
            raise RuntimeError("前置节点未完成：图片分析节点未完成，不能梳理用户心智")
        now = datetime.now()
        product.status = STEP_CUSTOMER_MINDSET
        product.current_step = 6
        product.error_message = "用户心智梳理已加入任务中心队列"
        set_product_workflow(
            product,
            node=WORKFLOW_NODE_CUSTOMER_MINDSET,
            status=WORKFLOW_STATUS_PROCESSING,
            error=product.error_message,
            now=now,
        )
        product.updated_at = now
        _sync_catalog_item(product)

    def build_plan(self, payload: dict[str, Any]) -> TaskRunPlan:
        product_id = _product_id(payload)
        return TaskRunPlan(
            task_type=self.action_type,
            title=f"用户心智梳理：商品 #{product_id}",
            payload={"product_id": product_id},
            groups=[
                TaskGroupPlan(
                    group_key="customer_mindset",
                    title="用户心智梳理",
                    steps=[
                        TaskStepPlan(
                            step_key=f"product:{product_id}:customer_mindset",
                            step_type=self.action_type,
                            payload={"product_id": product_id},
                            max_attempts=2,
                        )
                    ],
                )
            ],
        )

    async def execute_step(self, db: AsyncSession, step: TaskStep, payload: dict[str, Any]) -> dict[str, Any]:
        product_id = _product_id(payload)
        product = await _load_product(db, product_id)
        item_code = product.data.item_code if product.data else product.gigab2b_product_id
        await update_step_progress(
            db,
            step,
            current=0,
            total=1,
            message="开始梳理用户心智",
            data={"product_id": product_id, "item_code": item_code},
        )
        return {
            "product_id": product_id,
            "item_code": item_code,
            "customer_mindset": await run_customer_mindset(product_id),
        }

    async def on_step_success(self, db: AsyncSession, step: TaskStep, result: dict[str, Any]) -> None:
        product_id = int(result.get("product_id") or _payload_for_step(step).get("product_id") or 0)
        product = await _load_product(db, product_id)
        if (
            product.status == COMPLETED
            and product.workflow_node == WORKFLOW_NODE_FLOW_DONE
            and product.workflow_status == WORKFLOW_STATUS_SUCCEEDED
        ):
            step.task_run.summary_json = json_dumps({
                "product_id": product_id,
                "item_code": result.get("item_code"),
                "status": "already_completed",
                "next_step": None,
                "listing_task_run_ids": [],
            })
            await db.commit()
            result["status"] = "already_completed"
            result["next_step"] = None
            result["listing_task_run_ids"] = []
            return

        reasons = _e5_export_ready_protection_reasons(product)
        if reasons:
            message = "用户心智梳理完成，但当前商品已有不可逆外部结果，不能创建 Listing 任务：" + "；".join(reasons)
            await _project_product_failure(db, product_id=product_id, step=6, label="Listing 任务创建", error=message)
            result["status"] = "downstream_failed"
            result["downstream_error"] = message
            return

        await db.refresh(product, attribute_names=["data"])
        if not isinstance(result.get("customer_mindset"), dict) or not _customer_mindset_ready(product):
            message = "用户心智梳理任务完成但未落库有效结果，不能创建 Listing 任务"
            await _project_customer_mindset_failed(db, product_id=product_id, message=message)
            result["status"] = "downstream_failed"
            result["downstream_error"] = message
            return

        now = datetime.now()
        product.status = STEP_CUSTOMER_MINDSET
        product.current_step = 6
        product.error_message = None
        set_product_workflow(
            product,
            node=WORKFLOW_NODE_CUSTOMER_MINDSET,
            status=WORKFLOW_STATUS_SUCCEEDED,
            error=None,
            now=now,
        )
        product.updated_at = now
        _sync_catalog_item(product)
        try:
            listing_runs = await create_product_action_runs(
                db,
                "product_listing_generation",
                [{"product_id": product_id, "created_by": "product_customer_mindset"}],
                created_by="product_customer_mindset",
            )
        except Exception as exc:
            await db.rollback()
            message = f"用户心智梳理已完成，但 Listing 任务创建失败: {type(exc).__name__}: {exc}"
            await _project_product_failure(db, product_id=product_id, step=6, label="Listing 任务创建", error=message)
            result["status"] = "downstream_failed"
            result["downstream_error"] = message
            return

        listing_run_ids = [run.id for run in listing_runs]
        step.task_run.summary_json = json_dumps({
            "product_id": product_id,
            "item_code": result.get("item_code"),
            "status": "customer_mindset_done",
            "next_node": WORKFLOW_NODE_LISTING_GENERATION,
            "listing_task_run_ids": listing_run_ids,
        })
        await db.commit()
        await _best_effort_update_step_progress(
            db,
            step,
            current=1,
            total=1,
            message="用户心智梳理完成，已提交 Listing 生成",
            data={"product_id": product_id, "item_code": result.get("item_code"), "listing_task_run_ids": listing_run_ids},
        )
        result["status"] = "done"
        result["next_node"] = WORKFLOW_NODE_LISTING_GENERATION
        result["listing_task_run_ids"] = listing_run_ids

    async def on_step_failure(self, db: AsyncSession, step: TaskStep, error: Exception) -> None:
        product_id = int(_payload_for_step(step).get("product_id") or 0)
        if product_id > 0:
            await _project_customer_mindset_failed(
                db,
                product_id=product_id,
                message=f"用户心智梳理失败: {type(error).__name__}: {error}",
            )

    async def on_step_interrupted(self, db: AsyncSession, step: TaskStep, reason: str | None = None) -> None:
        product_id = int(_payload_for_step(step).get("product_id") or 0)
        if product_id > 0:
            await _project_customer_mindset_failed(
                db,
                product_id=product_id,
                message=f"用户心智梳理任务已中断: {reason or '服务重启或执行锁超时'}",
                paused=True,
            )

    async def on_cancel_requested(self, db: AsyncSession, run: TaskRun, reason: str | None = None) -> None:
        product_id = int(_payload_for_run(run).get("product_id") or 0)
        if product_id > 0:
            await _project_customer_mindset_failed(
                db,
                product_id=product_id,
                message=f"用户心智梳理任务已取消: {reason or '用户取消'}",
                paused=True,
            )


class ProductListingGenerationAction:
    """节点 9：把完整商品证据转成 Amazon Listing，并将主流程推进到待导出。

    前置与输入：必须消费商品事实、卖家精灵/兜底关键词、已选竞品的市场参考、图片
    分析以及结构完整的用户心智简报；竞品事实不能改写成本商品事实。已有真实 ASIN、
    导出历史、模板输出或 A+ 上传证据时禁止覆盖。任务最多尝试 2 次。

    文案硬限制（最终事实源为配置和 `search_terms.py`）：英文标题最大 75 字符
    (`STEP5_TITLE_MAX_CHARS`，含空格和标点)，标题只承担品牌、核心品类、必要规格和
    一个最强且有证据的差异点；Product Highlight 是独立于旧五点的单条标题补充，最大
    120 字符 (`STEP5_PRODUCT_HIGHLIGHT_MAX_CHARS`)，承接标题放不下且最重要的已证实
    属性、适配、配置或使用信息。旧五点仍必须恰好 5 条，每条当前最大 500
    字符 (`STEP5_BULLET_MAX_CHARS`)；Search Terms 使用逗号分隔，最多 20 个关键词短语
    (`SEARCH_TERMS_MAX_KEYWORDS`)，整体最大 250 个 UTF-8 bytes
    (`STEP5_SEARCH_TERMS_MAX_BYTES`)。LLM 默认 temperature=0.7、最大输出 2000 tokens，
    分别由 `STEP5_LLM_TEMPERATURE`、`STEP5_LLM_MAX_TOKENS` 控制。

    输出与校验：生成英文标题、1 条标题补充 Product Highlight、恰好五条英文五点、
    产品描述、Search Terms、对应中文翻译及 `listing_check`。标题或任一 Product
    Highlight 超限、数量错误或完全没有具体场景时，生成器必须把具体问题反馈给 LLM
    重新写完整语义；不得在单词中间机械截断。达到重写次数仍不合规则任务失败，不能
    以不完整文案进入待导出。用户心智中的证据缺口和买错风险应进入合适亮点、五点或
    描述，而非被隐藏。

    落库与下游：仅当标题、Product Highlights 和五点等必要结果已成功落库，才投影为
    `flow_done/succeeded`、`Product.status=completed`，并在商品列表显示“待导出”。这是
    主 workflow 的唯一完成入口。A+ 是待导出后的独立派生链路，默认自动触发关闭
    (`AUTO_APLUS_AFTER_EXPORT_READY=False`)；A+ 失败不得让商品退出待导出。
    """

    action_type = "product_listing_generation"

    async def validate(self, db: AsyncSession, payload: dict[str, Any]) -> None:
        product_id = _product_id(payload)
        product = await _load_product(db, product_id)
        _raise_if_e5_export_ready_protected(product, action_label="启动 Listing 生成")
        await _assert_step_prerequisites(product_id, 6)

    def dedupe_key(self, payload: dict[str, Any]) -> str | None:
        return f"product_listing_generation:product:{_product_id(payload)}"

    def correlation_key(self, payload: dict[str, Any]) -> str | None:
        return f"product:{_product_id(payload)}:listing_generation"

    async def reserve(self, db: AsyncSession, payload: dict[str, Any], run: TaskRun) -> None:
        product = await _load_product(db, _product_id(payload))
        _raise_if_e5_export_ready_protected(product, action_label="启动 Listing 生成")
        _raise_if_customer_mindset_missing(product)
        now = datetime.now()
        product.status = STEP5_LISTING
        product.current_step = 6
        product.error_message = "Listing 生成已加入任务中心队列"
        set_product_workflow(
            product,
            node=WORKFLOW_NODE_LISTING_GENERATION,
            status=WORKFLOW_STATUS_PROCESSING,
            error=product.error_message,
            now=now,
        )
        product.updated_at = now
        _sync_catalog_item(product)

    def build_plan(self, payload: dict[str, Any]) -> TaskRunPlan:
        product_id = _product_id(payload)
        item_code = payload.get("item_code")
        return TaskRunPlan(
            task_type=self.action_type,
            title=f"Listing 生成：{item_code or f'商品 #{product_id}'}",
            payload={"product_id": product_id, "item_code": item_code},
            groups=[
                TaskGroupPlan(
                    group_key="listing",
                    title="Listing 生成",
                    steps=[
                        TaskStepPlan(
                            step_key=f"product:{product_id}:listing",
                            step_type=self.action_type,
                            payload={"product_id": product_id, "item_code": item_code},
                            max_attempts=2,
                        )
                    ],
                )
            ],
        )

    async def execute_step(self, db: AsyncSession, step: TaskStep, payload: dict[str, Any]) -> dict[str, Any]:
        product_id = _product_id(payload)
        product = await _load_product(db, product_id)
        _raise_if_customer_mindset_missing(product)
        item_code = product.data.item_code if product.data else product.gigab2b_product_id
        await update_step_progress(
            db,
            step,
            current=0,
            total=1,
            message="开始生成 Listing",
            data={"product_id": product_id, "item_code": item_code},
        )
        return {
            "product_id": product_id,
            "item_code": item_code,
            "listing": await run_listing(product_id),
        }

    async def on_step_success(self, db: AsyncSession, step: TaskStep, result: dict[str, Any]) -> None:
        product_id = int(result.get("product_id") or _payload_for_step(step).get("product_id") or 0)
        source_task_run_id = step.task_run_id
        source_task_step_id = step.id
        product = await _load_product(db, product_id)
        # run_listing() 使用独立数据库会话落库。当前 task-runtime 会话可能刚连续执行完
        # customer_mindset -> listing，identity map 里的 ProductData 仍是心智落库前旧值；
        # success hook 必须显式刷新 data，不能把已存在的 durable 心智误判为缺失。
        await db.refresh(product, attribute_names=["data"])
        _raise_if_e5_export_ready_protected(product, action_label="完成 Listing 并进入待导出")
        _project_listing_completed(product)
        summary = {
            "product_id": product_id,
            "item_code": result.get("item_code"),
            "status": "listing_done",
            "next_step": "export",
        }
        step.task_run.summary_json = json_dumps(summary)
        await db.commit()
        try:
            aplus_auto_trigger = await try_auto_start_aplus_after_export_ready(
                db,
                product_id,
                source_task_run_id=source_task_run_id,
                source_task_step_id=source_task_step_id,
            )
        except Exception as exc:
            await db.rollback()
            logger.exception(
                "A+ auto trigger failed after listing export-ready commit: product_id=%s task_run_id=%s",
                product_id,
                source_task_run_id,
            )
            aplus_auto_trigger = {
                "status": "failed",
                "code": "trigger_failed",
                "message": f"{type(exc).__name__}: {exc}",
                "details": {"product_id": product_id},
                "source_task_run_id": source_task_run_id,
                "source_task_step_id": source_task_step_id,
            }
        summary["aplus_auto_trigger"] = aplus_auto_trigger
        try:
            refreshed_step = (
                await db.execute(
                    select(TaskStep)
                    .where(TaskStep.id == source_task_step_id)
                    .options(selectinload(TaskStep.task_run))
                )
            ).scalar_one()
            step = refreshed_step
            step.task_run.summary_json = json_dumps(summary)
            await db.commit()
        except Exception:
            await db.rollback()
            logger.exception(
                "Listing success A+ auto trigger summary write failed: product_id=%s task_run_id=%s",
                product_id,
                source_task_run_id,
            )
            reloaded_step = await db.get(TaskStep, source_task_step_id)
            if reloaded_step is not None:
                step = reloaded_step
        await _best_effort_update_step_progress(
            db,
            step,
            current=1,
            total=1,
            message="Listing 生成完成，已进入待导出",
            data={"product_id": product_id, "item_code": result.get("item_code"), "aplus_auto_trigger": aplus_auto_trigger},
        )
        result["status"] = "done"
        result["next_step"] = "export"
        result["aplus_auto_trigger"] = aplus_auto_trigger

    async def on_step_failure(self, db: AsyncSession, step: TaskStep, error: Exception) -> None:
        product_id = int(_payload_for_step(step).get("product_id") or 0)
        if product_id <= 0:
            return
        await _project_product_failure(db, product_id=product_id, step=6, label="Listing 生成", error=error)

    async def on_step_interrupted(self, db: AsyncSession, step: TaskStep, reason: str | None = None) -> None:
        product_id = int(_payload_for_step(step).get("product_id") or 0)
        if product_id <= 0:
            return
        await _project_product_paused(
            db,
            product_id=product_id,
            step=6,
            message=f"Listing 生成任务已中断: {reason or '服务重启或执行锁超时'}",
        )

    async def on_cancel_requested(self, db: AsyncSession, run: TaskRun, reason: str | None = None) -> None:
        product_id = int(_payload_for_run(run).get("product_id") or 0)
        if product_id <= 0:
            return
        await _project_product_paused(
            db,
            product_id=product_id,
            step=6,
            message=f"Listing 生成任务已取消: {reason or '用户取消'}",
        )


async def _existing_active_run(db: AsyncSession, action: TaskAction, payload: dict[str, Any]) -> TaskRun | None:
    dedupe_key = action.dedupe_key(payload)
    if dedupe_key:
        result = await db.execute(
            select(TaskRun)
            .where(TaskRun.dedupe_key == dedupe_key)
            .where(TaskRun.status.in_(ACTIVE_RUN_STATUSES))
            .options(selectinload(TaskRun.steps))
            .order_by(TaskRun.id.asc())
        )
        run = result.scalars().first()
        if run:
            return run
    plan = action.build_plan(payload)
    step_keys = [step.step_key for group in plan.groups for step in group.steps]
    if not step_keys:
        return None
    result = await db.execute(
        select(TaskRun)
        .join(TaskStep, TaskStep.task_run_id == TaskRun.id)
        .where(TaskRun.task_type == action.action_type)
        .where(TaskRun.status.in_(ACTIVE_RUN_STATUSES))
        .where(TaskStep.step_key.in_(step_keys))
        .where(TaskStep.status.in_(ACTIVE_STEP_STATUSES))
        .options(selectinload(TaskRun.steps))
        .order_by(TaskRun.id.asc())
    )
    return result.scalars().first()


async def _lock_product_for_action_payload(db: AsyncSession, payload: dict[str, Any]) -> None:
    product_id = int(payload.get("product_id") or 0)
    if product_id <= 0:
        return
    await db.execute(select(Product.id).where(Product.id == product_id).with_for_update())


async def _mark_previous_runs_superseded(db: AsyncSession, run: TaskRun) -> None:
    if not run.correlation_key:
        return
    result = await db.execute(
        select(TaskRun)
        .where(TaskRun.correlation_key == run.correlation_key)
        .where(TaskRun.id != run.id)
        .where(TaskRun.id < run.id)
        .where(TaskRun.status.in_((RUN_STATUS_FAILED, RUN_STATUS_INTERRUPTED)))
        .where(TaskRun.superseded_by_run_id.is_(None))
    )
    now = datetime.now()
    for previous in result.scalars().all():
        previous.superseded_by_run_id = run.id
        previous.superseded_at = now


async def _reload_action_runs_for_response(db: AsyncSession, runs: list[TaskRun]) -> list[TaskRun]:
    loaded_runs: list[TaskRun] = []
    for run in runs:
        result = await db.execute(
            select(TaskRun)
            .where(TaskRun.id == run.id)
            .options(
                selectinload(TaskRun.groups).selectinload(TaskGroup.steps),
                selectinload(TaskRun.steps),
            )
        )
        loaded = result.scalar_one_or_none()
        if loaded:
            loaded_runs.append(loaded)
    return loaded_runs


async def backfill_product_action_task_run_keys(db: AsyncSession) -> int:
    """Backfill ProductTaskAction metadata for pre-action task_runs.

    This is product-domain compatibility, not task-center framework parsing.
    It only updates task_run metadata keys and superseded pointers; product state,
    ASINs, material assets, and generated outputs are untouched.
    """
    result = await db.execute(
        select(TaskRun)
        .where(TaskRun.task_type.in_(PRODUCT_ACTION_TYPES))
        .order_by(TaskRun.id.asc())
    )
    runs = result.scalars().all()
    changed = 0
    now = datetime.now()
    by_correlation: dict[str, list[TaskRun]] = {}
    for run in runs:
        product_id = _legacy_payload_product_id(run)
        if not product_id:
            if run.correlation_key:
                by_correlation.setdefault(run.correlation_key, []).append(run)
            continue
        dedupe_key = _legacy_dedupe_key(run.task_type, product_id)
        correlation_key = _legacy_correlation_key(run.task_type, product_id)
        if dedupe_key and not run.dedupe_key:
            run.dedupe_key = dedupe_key
            changed += 1
        if correlation_key and not run.correlation_key:
            run.correlation_key = correlation_key
            changed += 1
        if run.correlation_key:
            by_correlation.setdefault(run.correlation_key, []).append(run)

    for correlation_runs in by_correlation.values():
        ordered = sorted(correlation_runs, key=lambda item: (item.created_at or datetime.min, item.id))
        for index, run in enumerate(ordered[:-1]):
            if run.status not in {RUN_STATUS_FAILED, RUN_STATUS_INTERRUPTED}:
                continue
            if run.superseded_by_run_id:
                continue
            run.superseded_by_run_id = ordered[index + 1].id
            run.superseded_at = now
            changed += 1

    if changed:
        await db.commit()
    else:
        await db.rollback()
    return changed


async def create_product_action_runs(
    db: AsyncSession,
    action_type: str,
    payloads: list[dict[str, Any]],
    *,
    created_by: str | None = "web",
    auto_start: bool = True,
) -> list[TaskRun]:
    action = action_for(action_type)
    if not payloads:
        raise ValueError("请选择要执行的商品")

    now = datetime.now()
    runs: list[TaskRun] = []
    for raw_payload in payloads:
        payload = dict(raw_payload)
        if created_by and not payload.get("created_by"):
            payload["created_by"] = created_by
        await action.validate(db, payload)
        await _lock_product_for_action_payload(db, payload)
        existing = await _existing_active_run(db, action, payload)
        if existing:
            plan = action.build_plan(payload)
            existing.dedupe_key = existing.dedupe_key or action.dedupe_key(payload)
            existing.correlation_key = existing.correlation_key or action.correlation_key(payload)
            existing.updated_at = now
            if action_type == "product_competitor_candidate_capture" and payload.get("visual_task_run_id") and payload.get("visual_task_step_id"):
                existing.payload_json = json_dumps(plan.payload)
                step_payloads_by_key = {
                    step_plan.step_key: step_plan.payload
                    for group_plan in plan.groups
                    for step_plan in group_plan.steps
                }
            else:
                step_payloads_by_key = {}
            for step in existing.steps:
                if step.step_key in step_payloads_by_key and step.status in (STEP_STATUS_PENDING, STEP_STATUS_READY):
                    step.payload_json = json_dumps(step_payloads_by_key[step.step_key])
                if auto_start and step.status == STEP_STATUS_PENDING:
                    step.status = STEP_STATUS_READY
                    step.updated_at = now
            existing.payload_json = existing.payload_json or json_dumps(plan.payload)
            await action.reserve(db, payload, existing)
            runs.append(existing)
            continue

        plan = action.build_plan(payload)
        run = TaskRun(
            task_type=plan.task_type,
            title=plan.title,
            status=RUN_STATUS_PENDING,
            created_by=created_by,
            payload_json=json_dumps(plan.payload),
            dedupe_key=action.dedupe_key(payload),
            correlation_key=action.correlation_key(payload),
            idempotency_key=payload.get("idempotency_key"),
            source_ref=payload.get("source_ref"),
            created_at=now,
            updated_at=now,
        )
        db.add(run)
        await db.flush()

        for group_plan in plan.groups:
            group = TaskGroup(
                task_run_id=run.id,
                group_key=group_plan.group_key,
                title=group_plan.title,
                status=RUN_STATUS_PENDING,
                sort_order=group_plan.sort_order,
                depends_on_group_keys_json=json_dumps(group_plan.depends_on_group_keys),
                failure_policy=group_plan.failure_policy,
                retry_policy=group_plan.retry_policy,
                progress_current=0,
                progress_total=len(group_plan.steps),
                created_at=now,
                updated_at=now,
            )
            db.add(group)
            await db.flush()
            for index, step_plan in enumerate(group_plan.steps):
                db.add(
                    TaskStep(
                        task_run_id=run.id,
                        task_group_id=group.id,
                        step_key=step_plan.step_key,
                        step_type=step_plan.step_type,
                        status=STEP_STATUS_READY if auto_start and group_plan.sort_order == 1 and index == 0 else STEP_STATUS_PENDING,
                        sort_order=step_plan.sort_order,
                        payload_json=json_dumps(step_plan.payload),
                        progress_current=0,
                        progress_total=1,
                        max_attempts=step_plan.max_attempts,
                        created_at=now,
                        updated_at=now,
                    )
                )
        await action.reserve(db, payload, run)
        await _mark_previous_runs_superseded(db, run)
        runs.append(run)

    await db.commit()
    runs = await _reload_action_runs_for_response(db, runs)
    if auto_start:
        kick_task_runtime()
    return runs


async def product_action_worker(ctx: TaskContext) -> dict[str, Any]:
    action = action_for(ctx.step.step_type)
    step_id = int(getattr(ctx.step, "id", 0) or 0)
    step_type = str(ctx.step.step_type)
    payload = _payload_for_step(ctx.step)
    try:
        result = await action.execute_step(ctx.db, ctx.step, payload)
        await ctx.db.refresh(ctx.run)
        if ctx.run.cancel_requested_at:
            await action.on_cancel_requested(ctx.db, ctx.run, ctx.run.cancel_reason)
            await ctx.db.commit()
            raise TaskStepCanceled(ctx.run.cancel_reason or "用户取消")
    except Exception as exc:
        if isinstance(exc, (TaskStepCanceled, TaskStepInterrupted)):
            raise
        await ctx.db.rollback()
        try:
            failure_step = await _reload_step_for_product_action(ctx.db, step_id) if step_id > 0 else ctx.step
            if failure_step is not None:
                await action.on_step_failure(ctx.db, failure_step, exc)
            else:
                logger.error("Product task failure projection skipped; step missing: step_id=%s type=%s", step_id, step_type)
        except Exception:
            await ctx.db.rollback()
            logger.exception(
                "Product task failure projection failed; preserving original worker error: step_id=%s type=%s",
                step_id,
                step_type,
            )
        raise
    return result


def register_product_task_actions() -> None:
    for action in (
        ProductMaterialPrepareAction(),
        ProductAutoImageSelectionAction(),
        ProductCompetitorSearchAction(),
        ProductCompetitorVisualMatchAction(),
        ProductCompetitorCandidateCaptureAction(),
        ProductAutoCompetitorSelectionAction(),
        ProductKeywordResearchAction(),
        ProductImageAnalysisAction(),
        ProductCustomerMindsetAction(),
        ProductListingGenerationAction(),
    ):
        register_action(action)
        register_worker(action.action_type, product_action_worker)
