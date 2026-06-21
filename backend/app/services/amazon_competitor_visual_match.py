from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.models import AmazonCompetitorSearchCandidate, Product, TaskRun, TaskStep
from app.services.product_image_vlm import clean_json_content, image_data_url, is_remote_url
from app.task_runtime.constants import RUN_STATUS_SUCCEEDED, STEP_STATUS_SUCCEEDED

logger = logging.getLogger(__name__)

TASK_TYPE_COMPETITOR_SEARCH = "product_competitor_search"
FAKE_VISUAL_MATCH_MODEL = "fake_competitor_visual_match_v1"
VISUAL_MATCH_RULE_VERSION = "amazon_competitor_visual_match_direct_url_v1"
MAX_CANDIDATES = 20
MAX_SELECTED = 6
MIN_SELECTED = 4
MIN_VISUAL_SIMILARITY = 0.65


class CompetitorVisualMatchError(RuntimeError):
    """Raised when current visual matching cannot safely produce current selected candidates."""


async def clear_current_visual_match(db: AsyncSession, product_id: int, *, now: datetime | None = None) -> int:
    """Clear current visual facts for a product before retrying visual match."""
    now = now or datetime.now()
    result = await db.execute(
        select(AmazonCompetitorSearchCandidate)
        .where(AmazonCompetitorSearchCandidate.product_id == product_id)
    )
    rows = result.scalars().all()
    for row in rows:
        _clear_visual_fields(row, now=now)
    return len(rows)


async def run_competitor_visual_match(
    product_id: int,
    *,
    db: AsyncSession,
    use_fake_vlm: bool = False,
) -> dict[str, Any]:
    product = await _load_product(db, product_id)
    source_image_url = _source_image_url(product)
    search_run, search_step = await _current_successful_search_run_step(db, product_id)
    candidates = await _current_search_candidates(db, product_id, search_run.id, search_step.id)
    if not candidates:
        raise CompetitorVisualMatchError("缺少当前成功搜索批次候选")

    records = [_record_for_candidate(candidate, index) for index, candidate in enumerate(candidates[:MAX_CANDIDATES], start=1)]
    if len(records) < MIN_SELECTED:
        raise CompetitorVisualMatchError(f"可视觉初筛候选不足: {len(records)}")

    reviews = (
        _fake_visual_reviews(product, records)
        if use_fake_vlm
        else await _analyze_direct_url_reviews(product, source_image_url, records)
    )
    reviews_by_id = {int(item["candidate_id"]): item for item in reviews}

    accepted = [
        item for item in reviews
        if not item["reject"]
        and item["same_product_type"]
        and float(item["visual_similarity"]) >= MIN_VISUAL_SIMILARITY
    ]
    accepted.sort(key=lambda item: (-float(item["visual_similarity"]), int(item["search_rank"]), int(item["candidate_id"])))
    selected_ids = {int(item["candidate_id"]) for item in accepted[:MAX_SELECTED]}
    if len(selected_ids) < MIN_SELECTED:
        raise CompetitorVisualMatchError(f"视觉初筛 Top 候选不足: {len(selected_ids)}")

    candidate_results: list[dict[str, Any]] = []
    for record in records:
        review = reviews_by_id.get(int(record["candidate_id"]))
        if not review:
            raise CompetitorVisualMatchError(f"VLM 未返回候选结果: slot={record['slot']} asin={record['asin']}")
        selected = int(record["candidate_id"]) in selected_ids
        candidate_results.append({
            **review,
            "selected_for_capture": selected,
            "visual_rank": _rank_for_candidate(int(record["candidate_id"]), accepted) if selected else None,
            "visual_exclusion_reason": None if selected else _visual_exclusion_reason(review),
        })

    return {
        "product_id": product_id,
        "search_run_id": search_run.id,
        "search_step_id": search_step.id,
        "model": FAKE_VISUAL_MATCH_MODEL if use_fake_vlm else settings.VLM_MODEL,
        "rule_version": VISUAL_MATCH_RULE_VERSION,
        "input_mode": "fake_fixture" if use_fake_vlm else "direct_image_url",
        "source_image_url": source_image_url,
        "candidate_count": len(records),
        "valid_image_count": len(records),
        "selected_count": len(selected_ids),
        "candidate_results": candidate_results,
    }


async def _analyze_direct_url_reviews(product: Product, source_image_url: str, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    client = settings.get_image_analysis_client()
    prompt = _direct_visual_match_prompt(product, source_image_url, records)
    content: list[dict[str, Any]] = [
        {"type": "text", "text": prompt["reference_text"]},
        {"type": "image_url", "image_url": {"url": _vlm_image_url(source_image_url)}},
    ]
    for record in records:
        content.append({"type": "text", "text": _candidate_descriptor(record)})
        content.append({"type": "image_url", "image_url": {"url": record["image_url"]}})
    content.append({"type": "text", "text": prompt["output_schema"]})

    request_client = client.with_options(timeout=90, max_retries=0) if hasattr(client, "with_options") else client
    try:
        response = await asyncio.wait_for(
            request_client.chat.completions.create(
                model=settings.VLM_MODEL,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a strict Amazon product visual matching reviewer. Output valid JSON only.",
                    },
                    {"role": "user", "content": content},
                ],
                max_tokens=4000,
                temperature=0.1,
            ),
            timeout=110,
        )
    except Exception as exc:
        raise CompetitorVisualMatchError(f"VLM direct URL 调用失败: {type(exc).__name__}: {exc}") from exc

    response_content = response.choices[0].message.content
    if not response_content:
        raise CompetitorVisualMatchError("VLM direct URL 返回空结果")
    try:
        analysis = json.loads(clean_json_content(response_content))
    except json.JSONDecodeError as exc:
        raise CompetitorVisualMatchError(f"VLM direct URL JSON 解析失败: {exc}") from exc

    items = analysis.get("candidates") if isinstance(analysis, dict) else None
    if not isinstance(items, list):
        raise CompetitorVisualMatchError("VLM direct URL 结果缺少 candidates 数组")

    by_slot = {record["slot"]: record for record in records}
    seen_slots: set[str] = set()
    reviews: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            raise CompetitorVisualMatchError("VLM direct URL candidates 包含非对象项")
        slot = str(item.get("slot") or "").strip()
        asin = str(item.get("asin") or "").strip()
        record = by_slot.get(slot)
        if not record:
            raise CompetitorVisualMatchError(f"VLM direct URL 返回未知 slot: {slot or '<empty>'}")
        if asin != record["asin"]:
            raise CompetitorVisualMatchError(f"VLM direct URL slot/asin 绑定失败: slot={slot} expected={record['asin']} actual={asin or '<empty>'}")
        if slot in seen_slots:
            raise CompetitorVisualMatchError(f"VLM direct URL 返回重复 slot: {slot}")
        seen_slots.add(slot)
        reviews.append(_normalize_direct_visual_review(item, record, analysis))

    missing_slots = sorted(set(by_slot) - seen_slots)
    if missing_slots:
        raise CompetitorVisualMatchError(f"VLM direct URL 未返回候选 slot: {', '.join(missing_slots)}")
    return reviews


def _direct_visual_match_prompt(product: Product, source_image_url: str, records: list[dict[str, Any]]) -> dict[str, str]:
    title = getattr(getattr(product, "data", None), "title", None) or getattr(product, "gigab2b_product_id", "") or ""
    facts = [
        "Compare every candidate image against the reference product image.",
        "The first attached image is the source/reference product image.",
        f"Our product title: {title}",
        f"Source image URL: {source_image_url}",
        "Each candidate is attached as its own image immediately after its slot metadata.",
        "Do not use contact sheets. Do not infer slot or asin from order if the metadata conflicts.",
    ]
    output_schema = [
        "Return valid JSON only with this exact top-level shape:",
        '{"candidates":[{"slot":"C01","asin":"...","image_loaded":true,"same_product_type":true,"visual_similarity":0.0,"attribute_match":0.0,"title_match":0.0,"reject":false,"reject_reason":"","reason":"..."}]}',
        "Required rules:",
        "- Return exactly one object for every provided candidate slot.",
        "- Use the exact slot and asin values from the metadata.",
        "- Scores must be numbers from 0 to 1.",
        "- image_loaded=false requires reject=true and a reject_reason.",
        "- reject=true for accessories, replacement parts, covers only, wrong product types, bad variants, low similarity, or unreadable images.",
        "Candidate slots:",
    ]
    output_schema.extend(_candidate_descriptor(record) for record in records)
    return {"reference_text": "\n".join(facts), "output_schema": "\n".join(output_schema)}


def _candidate_descriptor(record: dict[str, Any]) -> str:
    return (
        f"slot={record['slot']} asin={record['asin']} search_rank={record['search_rank']} "
        f"price={record.get('price') or ''} rating={record.get('rating') or ''} review_count={record.get('review_count') or ''} "
        f"title={record.get('title') or ''} image_url={record['image_url']}"
    )


def _normalize_direct_visual_review(item: dict[str, Any], record: dict[str, Any], analysis: dict[str, Any]) -> dict[str, Any]:
    image_loaded = bool(item.get("image_loaded"))
    reject = bool(item.get("reject")) or not image_loaded
    reject_reason = str(item.get("reject_reason") or ("image_not_loaded" if not image_loaded else ""))
    raw = {
        "review": item,
        "analysis": analysis,
        "rule_version": VISUAL_MATCH_RULE_VERSION,
        "input_mode": "direct_image_url",
        "source_image_url": analysis.get("source_image_url") if isinstance(analysis, dict) else None,
    }
    return {
        "candidate_id": int(record["candidate_id"]),
        "slot": record["slot"],
        "asin": record["asin"],
        "search_rank": int(record["search_rank"]),
        "image_loaded": image_loaded,
        "visual_similarity": _coerce_score(item.get("visual_similarity")),
        "same_product_type": bool(item.get("same_product_type")),
        "attribute_match": _coerce_score(item.get("attribute_match")),
        "title_match": _coerce_score(item.get("title_match")),
        "reject": reject,
        "reject_reason": reject_reason,
        "reason": str(item.get("reason") or ""),
        "raw": raw,
    }


def _vlm_image_url(value: str) -> str:
    if is_remote_url(value):
        return value
    path = Path(value).expanduser()
    if not path.is_file():
        raise CompetitorVisualMatchError(f"源商品主图不可访问: {value}")
    return image_data_url(path)


async def _load_product(db: AsyncSession, product_id: int) -> Product:
    result = await db.execute(
        select(Product)
        .where(Product.id == product_id)
        .options(selectinload(Product.data), selectinload(Product.images))
    )
    product = result.scalar_one_or_none()
    if not product:
        raise CompetitorVisualMatchError(f"商品不存在: {product_id}")
    return product


def _source_image_url(product: Product) -> str:
    value = str(getattr(getattr(product, "images", None), "main_image_path", None) or "").strip()
    if not value:
        raise CompetitorVisualMatchError("缺少商品当前主图 URL")
    return value


async def _current_successful_search_run_step(db: AsyncSession, product_id: int) -> tuple[TaskRun, TaskStep]:
    correlation_key = f"product:{product_id}:competitor_search"
    run_result = await db.execute(
        select(TaskRun)
        .where(TaskRun.task_type == TASK_TYPE_COMPETITOR_SEARCH)
        .where(TaskRun.correlation_key == correlation_key)
        .where(TaskRun.status == RUN_STATUS_SUCCEEDED)
        .order_by(TaskRun.updated_at.desc(), TaskRun.id.desc())
    )
    run = run_result.scalars().first()
    if not run:
        raise CompetitorVisualMatchError("缺少当前成功的自动竞品搜索任务")
    step_result = await db.execute(
        select(TaskStep)
        .where(TaskStep.task_run_id == run.id)
        .where(TaskStep.step_type == TASK_TYPE_COMPETITOR_SEARCH)
        .where(TaskStep.status == STEP_STATUS_SUCCEEDED)
        .order_by(TaskStep.updated_at.desc(), TaskStep.id.desc())
    )
    step = step_result.scalars().first()
    if not step:
        raise CompetitorVisualMatchError("缺少当前成功的自动竞品搜索步骤")
    return run, step


async def _current_search_candidates(
    db: AsyncSession,
    product_id: int,
    search_run_id: int,
    search_step_id: int,
) -> list[AmazonCompetitorSearchCandidate]:
    result = await db.execute(
        select(AmazonCompetitorSearchCandidate)
        .where(AmazonCompetitorSearchCandidate.product_id == product_id)
        .where(AmazonCompetitorSearchCandidate.task_run_id == search_run_id)
        .where(AmazonCompetitorSearchCandidate.task_step_id == search_step_id)
        .where(AmazonCompetitorSearchCandidate.is_excluded == 0)
        .where(AmazonCompetitorSearchCandidate.image_url.is_not(None))
        .where(AmazonCompetitorSearchCandidate.image_url != "")
        .order_by(AmazonCompetitorSearchCandidate.search_rank.asc(), AmazonCompetitorSearchCandidate.id.asc())
        .limit(MAX_CANDIDATES)
    )
    return result.scalars().all()


def _record_for_candidate(candidate: AmazonCompetitorSearchCandidate, index: int) -> dict[str, Any]:
    image_url = str(candidate.image_url or "").strip()
    if not image_url:
        raise CompetitorVisualMatchError(f"候选缺少 image_url: candidate_id={candidate.id}")
    return {
        "candidate_id": candidate.id,
        "slot": f"C{index:02d}",
        "asin": candidate.asin,
        "image_url": image_url,
        "search_rank": candidate.search_rank,
        "title": candidate.title or "",
        "price": candidate.price or "",
        "rating": candidate.rating or "",
        "review_count": candidate.review_count or "",
    }


def _fake_visual_reviews(product: Product, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    product_tokens = _tokens(getattr(getattr(product, "data", None), "title", None) or getattr(product, "gigab2b_product_id", "") or "")
    reviews: list[dict[str, Any]] = []
    for record in records:
        rank = int(record.get("search_rank") or 99)
        title = str(record.get("title") or "")
        title_tokens = _tokens(title)
        overlap = len(product_tokens & title_tokens)
        title_match = min(1.0, overlap / max(len(product_tokens), 1)) if product_tokens else 0.5
        accessory = any(term in title.lower() for term in ("accessory", "replacement", "spare part", "cover only", "slipcover"))
        visual_similarity = max(0.0, min(0.96, 0.92 - max(rank - 1, 0) * 0.035 + min(title_match, 0.35) * 0.08))
        same_product_type = not accessory
        reject = accessory or visual_similarity < MIN_VISUAL_SIMILARITY
        reject_reason = "accessory_or_replacement" if accessory else ("low_visual_similarity" if reject else "")
        reviews.append({
            "candidate_id": int(record["candidate_id"]),
            "slot": record["slot"],
            "asin": record["asin"],
            "search_rank": rank,
            "image_loaded": True,
            "visual_similarity": round(visual_similarity, 4),
            "same_product_type": same_product_type,
            "attribute_match": round(max(0.45, min(0.95, visual_similarity - 0.05)), 4),
            "title_match": round(title_match, 4),
            "reject": reject,
            "reject_reason": reject_reason,
            "reason": "fake fixture visual score from search rank, title overlap, and accessory filters",
            "raw": {
                "rule_version": VISUAL_MATCH_RULE_VERSION,
                "input_mode": "fake_fixture",
                "slot": record["slot"],
            },
        })
    return reviews


def _coerce_score(value: object) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def _visual_exclusion_reason(review: dict[str, Any]) -> str | None:
    if review.get("reject_reason"):
        return str(review["reject_reason"])
    if not review.get("same_product_type"):
        return "different_product_type"
    if float(review.get("visual_similarity") or 0) < MIN_VISUAL_SIMILARITY:
        return "low_visual_similarity"
    return "not_top_candidate"


def _rank_for_candidate(candidate_id: int, accepted: list[dict[str, Any]]) -> int | None:
    for index, item in enumerate(accepted[:MAX_SELECTED], start=1):
        if int(item["candidate_id"]) == candidate_id:
            return index
    return None


def _clear_visual_fields(row: AmazonCompetitorSearchCandidate, *, now: datetime) -> None:
    row.visual_similarity_score = None
    row.visual_same_product_type = None
    row.visual_attribute_match_score = None
    row.visual_title_match_score = None
    row.visual_reject = None
    row.visual_reject_reason = None
    row.visual_reason = None
    row.visual_sheet_path = None
    row.visual_sheet_page = None
    row.visual_sheet_label = None
    row.visual_rank = None
    row.visual_selected_for_capture = 0
    row.visual_task_run_id = None
    row.visual_task_step_id = None
    row.visual_exclusion_reason = None
    row.visual_model = None
    row.visual_raw_json = None
    row.visual_matched_at = None
    row.updated_at = now


def _tokens(text: str) -> set[str]:
    return {part for part in "".join(ch.lower() if ch.isalnum() else " " for ch in text).split() if len(part) >= 4}
