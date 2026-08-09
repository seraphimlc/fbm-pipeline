"""待导出后的 A+ 派生节点 1：使用 LLM 生成 A+ 内容规划。

前置输入包括已落库 Listing、商品事实、关键词、图片分析和用户心智简报。规划要先形成
商品叙事诊断：购买动机、关键场景、买家疑虑、证据强弱、证据缺口、禁止 claim，以及
每个模块在转化路径中的职责；竞品或关键词只能提供市场语境，不能证明自身产品属性。

默认发布 profile 是 `standard_header_image_text_v1`，对应普通 A+ 的 5 个宽横幅
`STANDARD_HEADER_IMAGE_TEXT` 模块，语义角色依次覆盖 hero、lifestyle、feature_proof、
spec_objection、closing。规划应补充 Gallery 未充分表达的场景和异议处理，避免把主图/
Gallery 原样重复成 A+。其它 profile 的模块数量和图片槽位以
`backend/app/aplus_publish/module_registry.py` 为最终事实源，不能在本模块另建一套约束。

输出写入 `ProductAplus` 的规划及 profile/版本相关字段，供 Step 8 生成脚本。此链路独立
于商品主 workflow：A+ 规划失败不得把已完成商品从“待导出”退回；证据不足时应显式记录
缺口或失败，禁止编造卖点继续。
"""

import asyncio
import json
import logging
import re
from datetime import datetime

from app.aplus_publish.module_registry import (
    APLUS_PUBLISH_PROFILE_ENHANCED_BASIC_APLUS_V1,
    APLUS_PUBLISH_PROFILE_STANDARD_HEADER_IMAGE_TEXT_V1,
    INTERNAL_STANDARD_HEADER_IMAGE_TEXT_TYPE,
    LINGXING_STANDARD_HEADER_IMAGE_TEXT,
    producer_contract_for_profile,
    semantic_role_for_position,
)
from app.config import settings
from app.database import async_session
from app.models import Product, ProductData, ProductImage, ProductAplus
from app.pipeline.aplus_narrative_diagnosis import (
    NARRATIVE_DIAGNOSIS_OUTPUT_SCHEMA,
    NARRATIVE_DIAGNOSIS_PROMPT_SECTION,
    normalize_product_narrative_diagnosis,
)
from app.pipeline.customer_mindset import (
    customer_mindset_context,
    customer_mindset_matches_product,
    image_analysis_ready,
)
from app.services.product_pipeline_artifacts import write_aplus_plan_artifacts
from sqlalchemy import select
from sqlalchemy.orm import selectinload

logger = logging.getLogger(__name__)

APLUS_MODULE_CONTRACT_SOURCE = "backend/app/aplus_publish/module_registry.py"
DEFAULT_APLUS_PUBLISH_PROFILE = APLUS_PUBLISH_PROFILE_STANDARD_HEADER_IMAGE_TEXT_V1
_ASIN_RE = re.compile(r"^[A-Z0-9]{10}$")


def _is_transient_llm_error(exc: Exception) -> bool:
    name = type(exc).__name__.lower()
    text = str(exc).lower()
    return (
        "apiconnectionerror" in name
        or "apitimeouterror" in name
        or "timeout" in name
        or "remoteprotocolerror" in name
        or "connection error" in text
        or "server disconnected" in text
        or "temporarily unavailable" in text
        or "transport closed" in text
        or "handler is closed" in text
    )

SYSTEM_PROMPT = """You are an Amazon A+ Content strategist. You design compelling A+ Content layouts that:
1. Tell a brand story
2. Highlight key selling points visually
3. Address buyer objections
4. Cross-sell related products
5. Follow Amazon A+ Content best practices

Critical visual planning rules:
- On-image text must NOT contain the brand name. Do not plan a logo, wordmark, brand-name headline, or brand-name caption inside the image.
- Lifestyle scenes may include people when useful, but any visible person must be shown as a complete, natural full body. Do not plan cropped heads, cropped hands, cropped legs, or partial bodies.
- Preserve the original product identity and proportions as much as possible. Do not plan transformations that change the product type, silhouette, color, material, visible parts, package, surface finish, scale, or construction.
- Preserve the product material shown in the reference images. Do not plan a change from the supplied fabric/plastic/wood/metal/glass/paper/rubber/packaging material into another material.
- Select the concrete primary and secondary reference image_id for every module from the supplied candidate list. Do not make every A+ image use the same two product references.
- Anchor every planned A+ image to selling points that are actually visible or supported by its selected reference images.
- The generated A+ image may change scene, people, light, camera framing, and styling, but the product itself should stay as close as possible to the selected reference images. Do not add, remove, reshape, recolor, retexture, or redesign product parts.

Supported publish profile:
- All 5 business story modules must be publishable through Lingxing STANDARD_HEADER_IMAGE_TEXT.
- Use type "standard_header_image_text" for every module.
- Use semantic_role to express the business purpose: hero, lifestyle, feature_proof, spec_objection, closing.

Output valid JSON only."""

PLAN_PROMPT = """Design an A+ Content plan for this Amazon product.

## Product
- Title: {title}
- Brand: {brand}
- Category: {category}
- Price: ${price}

## Key Features
{features}

## Image Selling Points
{selling_points}

## Reference Image Candidates
{reference_candidates}

## Image Risk and Conversion Gaps from Step 6
{image_diagnostics}

## Primary Keyword
{primary_keyword}

## Customer Mindset Brief
{customer_mindset}

""" + NARRATIVE_DIAGNOSIS_PROMPT_SECTION + """

## Requirements
1. Exactly 5 modules total for standard Amazon A+ content. Do not create 6 or 7 modules.
2. First module: hero/value promise, but on-image text must not include the brand name
3. Use exactly these semantic roles by position: hero, lifestyle, feature_proof, spec_objection, closing.
4. Render specs only as a buyer-objection story in the spec_objection module; do not create an unsupported native comparison chart or native spec table.
5. Last module: confidence, ownership close, or cross-sell context
6. Each module needs: type="standard_header_image_text", semantic_role, headline, subheading, key message, text_content, image concept
7. Image concepts must preserve the original product type, shape, color, proportions, material, texture/finish, package, visible parts, accessories, and construction.
8. If a scene includes people, specify complete full-body people with natural anatomy and no cropped body parts.
9. Any planned on-image text must avoid the brand name "{brand}".
10. For each module, choose `primary_reference_image_id` and, when useful, `secondary_reference_image_id` from the exact image_id values in Reference Image Candidates. Never invent an image_id, filename, slot, or path.
11. Explain the business decision in `reference_selection_reason`, and explain what each selected image proves in `primary_reference_use` and `secondary_reference_use`. Also provide `fallback_reference_roles` for Step 8 to use only if a selected image is missing or unsafe.
12. Add a reference_strategy that explains the two reference roles needed for that module, such as product identity, lifestyle context, dimensions, material close-up, comfort detail, or finished-back view.
13. Vary the selected pair by module; the same two references should not be used for every module. It is acceptable to reuse one strong product-identity image across modules when the supporting image changes.
14. State that the material from the selected product references must be preserved and not replaced.
15. The image concept should stay close to the selected references' visible selling points. Do not plan new features, extra accessories, different modules, different cushions, different legs, different armrests, different stitching, or unsupported claims that are not visible in the references/product facts.
16. Allow changes mainly to scenario, people, light, camera angle, room styling, and clean Amazon A+ composition; keep the product itself reference-faithful.
17. A+ should be experience-led, not spec-led. Prefer lifestyle, usage, ownership feeling, room fit, comfort, setup ease, and emotional context over repeating dry parameters.
18. At least 3 of the 5 modules should be lifestyle/experience-led unless the product category makes that unsafe or misleading.
19. Use the Image Risk and Conversion Gaps to choose module priorities, but translate gaps into user experience where possible. For example, a dimensions gap becomes "small apartment fit"; a material gap becomes "soft touch in daily lounging"; a setup gap becomes "easy move-in setup".
20. Use specs only when they reduce a major buyer objection, and keep specs as supporting evidence rather than the main A+ story.
21. Do not repeat information already covered by MAIN/gallery images unless A+ adds deeper context, emotion, or usage understanding.
22. Do not pretend missing gallery evidence exists. If references are limited, use conservative text/spec explanation or a visual concept anchored to available references, and avoid unsupported visual claims.
23. Every module must explicitly use the product_narrative_diagnosis. Do not create five generic banners that would fit any product.
24. For every module, define the conversion strategy fields: conversion_goal, buyer_objection, evidence_source, risk_guardrails, visual_do_not_claim, experience_angle, and gallery_overlap_avoidance.
25. Keep on-image copy short and useful. Do not write keyword-stuffed or paragraph-like image text.
26. Treat the 5 modules as five wide banner images, not as independent posters. Each image should have one clear focal product/reference anchor, one buyer question, and a simple left/right or foreground/background composition that will still read at 1940 x 1200.
27. The five banners must form this standard story arc: (1) product identity and promise, (2) realistic use/fit context, (3) visible feature or material proof, (4) objection reducer for size/setup/material/compatibility, (5) ownership close or confidence moment.
28. When a Customer Mindset Brief is available, use strategy fields only when strategy_field_evidence marks planning_usable=true. Inferred fields may organize the story but are not researched shopper facts, and fields with copy_claim_usable=false must not become factual on-image claims.
29. Use benefit_ladder items only when copy_usable=true. State a comparative differentiator only when comparison_supported=true. Never convert keyword or competitor evidence into a product attribute.
30. If the mindset quality requires review, design conservatively around critical_unknowns and evidence_boundary_issues instead of inventing a more dramatic story.
31. An A+ or future-visual job with claim_proof_usable=false may define a buyer question, but it cannot authorize factual copy. visual_anchor_usable=true may guide only visible appearance, structure, framing, and reference selection.

Output JSON:
{{
  "plan_summary": "brief description of the A+ strategy",
  """ + NARRATIVE_DIAGNOSIS_OUTPUT_SCHEMA + """,
  "modules": [
    {{
      "position": 1,
      "type": "standard_header_image_text",
      "semantic_role": "hero",
      "publish_profile": "standard_header_image_text_v1",
      "lingxing_content_module_type": "STANDARD_HEADER_IMAGE_TEXT",
      "headline": "...",
      "subheading": "...",
      "key_message": "...",
      "image_concept": "description of what this image should show",
      "image_style": "photography|3d_render|infographic|lifestyle",
      "conversion_goal": "what this module should make the buyer believe or understand",
      "buyer_objection": "the specific doubt or friction this module reduces",
      "evidence_source": "which product facts, listing claim, Step 6 image role, or reference image evidence supports this module",
      "experience_angle": "the real-life usage feeling or ownership scenario this module should create",
      "gallery_overlap_avoidance": "what MAIN/gallery already covers and how this module avoids repeating it",
      "risk_guardrails": ["truthfulness and visual fidelity constraints for this module"],
      "visual_do_not_claim": ["unsupported claims or visual elements this module must avoid"],
      "primary_reference_image_id": "#01",
      "secondary_reference_image_id": "#03",
      "reference_selection_reason": "why these exact two images best support this module and differ from the other modules",
      "primary_reference_use": "what visible product identity or evidence the primary reference must preserve",
      "secondary_reference_use": "what module-specific detail, scale, scene, or function the secondary reference must preserve",
      "fallback_reference_roles": ["product identity", "module-specific supporting evidence"],
      "reference_strategy": "two reference-image roles to use for this module and what each preserves",
      "preferred_reference_roles": ["role 1", "role 2"],
      "text_content": "body text for this module"
    }}
  ],
  "color_palette": ["#hex1", "#hex2"],
  "tone": "professional|warm|minimal|bold",
  "target_audience": "..."
}}"""


def _format_reference_candidates(pi: ProductImage | None) -> str:
    if not pi or not pi.image_analysis:
        return "N/A"

    try:
        payload = json.loads(pi.image_analysis)
    except json.JSONDecodeError:
        return "N/A"

    if isinstance(payload, list):
        reviews = payload
        gallery_selection = []
    elif isinstance(payload, dict):
        reviews = payload.get("images") if isinstance(payload.get("images"), list) else []
        gallery_selection = payload.get("gallery_selection") if isinstance(payload.get("gallery_selection"), list) else []
    else:
        return "N/A"

    by_path = {}
    for item in reviews:
        if isinstance(item, dict) and item.get("path"):
            by_path[item["path"]] = item

    candidates = []
    seen = set()
    for selected in gallery_selection:
        if not isinstance(selected, dict):
            continue
        path = selected.get("path")
        if not path or path in seen:
            continue
        review = by_path.get(path, {})
        mm = review.get("multimodal_result") if isinstance(review.get("multimodal_result"), dict) else {}
        candidates.append({
            "image_id": selected.get("image_id") or review.get("image_id"),
            "slot": selected.get("slot"),
            "filename": selected.get("filename"),
            "path": path,
            "role": selected.get("role") or selected.get("conversion_role") or review.get("conversion_role"),
            "image_type": review.get("image_type"),
            "selling_point": review.get("visible_selling_point") or mm.get("primary_selling_point"),
            "material": review.get("material_texture") or mm.get("material_texture"),
            "scene": review.get("scene_type") or mm.get("scene_type"),
            "risk_flags": review.get("risk_flags") or [],
            "amazon_suitability": (
                (mm.get("quality_assessment") or {}).get("amazon_suitability")
                if isinstance(mm.get("quality_assessment"), dict)
                else None
            ),
        })
        seen.add(path)

    for review in reviews:
        if not isinstance(review, dict):
            continue
        path = review.get("path")
        if not path or path in seen:
            continue
        mm = review.get("multimodal_result") if isinstance(review.get("multimodal_result"), dict) else {}
        candidates.append({
            "image_id": review.get("image_id"),
            "filename": review.get("filename"),
            "path": path,
            "role": review.get("conversion_role"),
            "image_type": review.get("image_type"),
            "selling_point": review.get("visible_selling_point") or mm.get("primary_selling_point"),
            "material": review.get("material_texture") or mm.get("material_texture"),
            "scene": review.get("scene_type") or mm.get("scene_type"),
            "risk_flags": review.get("risk_flags") or [],
            "amazon_suitability": (
                (mm.get("quality_assessment") or {}).get("amazon_suitability")
                if isinstance(mm.get("quality_assessment"), dict)
                else None
            ),
        })
        seen.add(path)
        if len(candidates) >= 16:
            break

    if not candidates:
        return "N/A"
    return json.dumps(candidates[:16], ensure_ascii=False, indent=2)


def _format_image_diagnostics(pi: ProductImage | None) -> str:
    if not pi or not pi.image_analysis:
        return "N/A"
    try:
        payload = json.loads(pi.image_analysis)
    except json.JSONDecodeError:
        return "N/A"
    if not isinstance(payload, dict):
        return "N/A"

    diagnostics = payload.get("selection_diagnostics") if isinstance(payload.get("selection_diagnostics"), dict) else {}
    health = diagnostics.get("image_health") if isinstance(diagnostics.get("image_health"), dict) else {}
    alignment = diagnostics.get("listing_image_alignment") if isinstance(diagnostics.get("listing_image_alignment"), dict) else {}
    missing_roles = diagnostics.get("missing_gallery_roles") if isinstance(diagnostics.get("missing_gallery_roles"), list) else []
    duplicate_backfill = diagnostics.get("duplicate_backfill") if isinstance(diagnostics.get("duplicate_backfill"), list) else []

    summary = {
        "image_health": {
            "level": health.get("level"),
            "label": health.get("label"),
            "requires_attention": health.get("requires_attention"),
            "issues": [
                {
                    "severity": item.get("severity"),
                    "message": item.get("message"),
                    "matched_terms": item.get("matched_terms"),
                }
                for item in (health.get("issues") or [])[:8]
                if isinstance(item, dict)
            ],
        },
        "missing_gallery_roles": [
            {
                "role": item.get("role"),
                "role_label": item.get("role_label"),
                "buyer_question": item.get("buyer_question"),
            }
            for item in missing_roles[:8]
            if isinstance(item, dict)
        ],
        "listing_missing_image_evidence": [
            {
                "claim_label": item.get("claim_label"),
                "role_label": item.get("role_label"),
                "matched_terms": item.get("matched_terms"),
                "message": item.get("message"),
            }
            for item in (alignment.get("missing_evidence") or [])[:8]
            if isinstance(item, dict)
        ],
        "duplicate_backfill_count": len(duplicate_backfill),
        "main_image_status": diagnostics.get("main_image_status"),
        "main_image_warnings": diagnostics.get("main_image_warnings") or [],
    }
    return json.dumps(summary, ensure_ascii=False, indent=2)


def _compact_text(value, fallback: str = "") -> str:
    text = str(value or "").strip()
    if not text:
        text = fallback
    return re.sub(r"\s+", " ", text).strip()


def _trim_text(value, max_length: int, fallback: str = "") -> str:
    text = _compact_text(value, fallback)
    if len(text) <= max_length:
        return text
    return text[: max(0, max_length - 3)].rstrip() + "..."


def _as_list(value) -> list:
    if isinstance(value, list):
        return value
    if value is None:
        return []
    return [value]


def _feature_items_from_product_data(pd: ProductData, selling_points: list) -> list[str]:
    feature_items: list[str] = []
    if getattr(pd, "features", None):
        try:
            parsed_features = json.loads(pd.features)
            if isinstance(parsed_features, list):
                feature_items = [_compact_text(item) for item in parsed_features if _compact_text(item)]
            elif parsed_features:
                feature_items = [_compact_text(parsed_features)]
        except Exception:
            feature_items = [_compact_text(pd.features)]
    if not feature_items and selling_points:
        feature_items = [_compact_text(item) for item in selling_points if _compact_text(item)]
    if not feature_items:
        feature_items = [
            "Clear product identity from the selected reference images.",
            "Visible material and construction details buyers can verify.",
            "Practical ownership context grounded in available product facts.",
        ]
    while len(feature_items) < 3:
        feature_items.append(feature_items[-1])
    return feature_items


def _module_candidates_by_role(raw_modules: list) -> dict[str, dict]:
    by_role: dict[str, dict] = {}
    for module in raw_modules:
        if not isinstance(module, dict):
            continue
        role = _compact_text(module.get("semantic_role"))
        if role and role not in by_role:
            by_role[role] = module
    return by_role


def _raw_module_for_contract(raw_modules: list, modules_by_role: dict[str, dict], contract_module) -> dict:
    role_match = modules_by_role.get(contract_module.semantic_role)
    if role_match is not None:
        return role_match
    for module in raw_modules:
        if not isinstance(module, dict):
            continue
        try:
            if int(module.get("position")) == contract_module.position:
                return module
        except Exception:
            continue
    index = contract_module.position - 1
    if 0 <= index < len(raw_modules) and isinstance(raw_modules[index], dict):
        return raw_modules[index]
    return {}


def _conversion_fields(raw: dict, fallback_headline: str) -> dict:
    return {
        "conversion_goal": _trim_text(
            raw.get("conversion_goal") or raw.get("key_message"),
            300,
            f"Help buyers understand {fallback_headline}.",
        ),
        "buyer_objection": _trim_text(
            raw.get("buyer_objection"),
            300,
            "Clarify a practical buyer concern with supported product evidence.",
        ),
        "evidence_source": _trim_text(
            raw.get("evidence_source") or raw.get("reference_strategy"),
            300,
            "Use available product facts, listing claims, and selected reference images.",
        ),
        "experience_angle": _trim_text(
            raw.get("experience_angle") or raw.get("image_concept"),
            300,
            "Show a realistic ownership or usage moment without unsupported claims.",
        ),
        "gallery_overlap_avoidance": _trim_text(
            raw.get("gallery_overlap_avoidance"),
            300,
            "Avoid repeating MAIN/gallery images unless A+ adds deeper usage context.",
        ),
        "risk_guardrails": _string_list(
            raw.get("risk_guardrails"),
            [
                "Keep claims truthful and supported by product facts or visible reference images.",
                "Preserve product identity, color, material, scale, proportions, and visible construction.",
            ],
            min_items=2,
            max_items=6,
            max_length=220,
        ),
        "visual_do_not_claim": _string_list(
            raw.get("visual_do_not_claim"),
            [
                "Do not show unsupported accessories, functions, certifications, safety claims, or material changes.",
            ],
            min_items=1,
            max_items=6,
            max_length=220,
        ),
    }


def _string_list(value, fallback: list[str], *, min_items: int, max_items: int, max_length: int) -> list[str]:
    items = [_trim_text(item, max_length) for item in _as_list(value) if _compact_text(item)]
    if not items:
        items = list(fallback)
    while len(items) < min_items:
        items.append(fallback[min(len(items), len(fallback) - 1)])
    return items[:max_items]


def _dict_list(value) -> list[dict]:
    return [item for item in _as_list(value) if isinstance(item, dict)]


def _normalize_asin(value) -> str | None:
    asin = _compact_text(value).upper()
    if _ASIN_RE.match(asin):
        return asin
    return None


def _json_dict_from_text(value) -> dict:
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _product_title(pd: ProductData) -> str:
    return _trim_text(getattr(pd, "listing_title", None) or getattr(pd, "title", None), 80, "Current product")


def _normalize_narrative_with_customer_mindset(
    raw_value,
    *,
    product_data: ProductData,
    product_image: ProductImage | None,
    selling_points: list,
    fallback: bool,
) -> dict:
    """Use customer mindset as the upstream truth while retaining A+-specific LLM choices."""
    raw = dict(raw_value) if isinstance(raw_value, dict) else {}
    mindset = customer_mindset_context(
        getattr(product_data, "customer_mindset", None),
        surface="aplus",
        required=False,
    )
    if not mindset:
        return normalize_product_narrative_diagnosis(
            raw,
            product_data=product_data,
            product_image=product_image,
            selling_points=selling_points,
            fallback=fallback,
        )

    strategy = mindset.get("strategy") if isinstance(mindset.get("strategy"), dict) else {}
    quality = mindset.get("quality") if isinstance(mindset.get("quality"), dict) else {}
    strategy_field_evidence = (
        strategy.get("strategy_field_evidence")
        if isinstance(strategy.get("strategy_field_evidence"), dict)
        else {}
    )

    def planning_value(field: str) -> str:
        meta = strategy_field_evidence.get(field)
        if isinstance(meta, dict) and not meta.get("planning_usable"):
            return ""
        return _compact_text(strategy.get(field))

    primary_job = planning_value("primary_job")
    core_value = planning_value("core_value_proposition")
    primary_buyer = planning_value("primary_buyer")
    top_scenarios = strategy.get("top_scenarios") if isinstance(strategy.get("top_scenarios"), list) else []
    primary_scenario = ""
    if (
        top_scenarios
        and isinstance(top_scenarios[0], dict)
        and top_scenarios[0].get("planning_usable", True)
    ):
        primary_scenario = _compact_text(top_scenarios[0].get("scenario"))

    objections = []
    for item in strategy.get("objections") or []:
        if isinstance(item, dict) and _compact_text(item.get("objection")):
            objections.append(_compact_text(item.get("objection")))
    verified_differentiators = []
    for item in strategy.get("differentiators") or []:
        if isinstance(item, dict) and item.get("comparison_supported") and _compact_text(item.get("claim")):
            verified_differentiators.append(_compact_text(item.get("claim")))

    content_direction = strategy.get("content_direction") if isinstance(strategy.get("content_direction"), dict) else {}
    mindset_claims_to_avoid = [
        _compact_text(item)
        for item in content_direction.get("claims_to_avoid") or []
        if _compact_text(item)
    ]
    raw_claims_to_avoid = [
        _compact_text(item)
        for item in _as_list(raw.get("claims_to_avoid") or raw.get("visual_do_not_claim"))
        if _compact_text(item)
    ]
    critical_unknowns = [
        _compact_text(item)
        for item in quality.get("critical_unknowns") or []
        if _compact_text(item)
    ]
    boundary_issues = [
        _compact_text(item)
        for item in quality.get("evidence_boundary_issues") or []
        if _compact_text(item)
    ]
    evidence_gaps = list(dict.fromkeys([*critical_unknowns, *boundary_issues]))[:5]

    module_roles = ("hero", "lifestyle", "feature_proof", "spec_objection", "closing")
    module_strategy = raw.get("narrative_strategy_by_module")
    module_strategy = dict(module_strategy) if isinstance(module_strategy, dict) else {}
    for role, item in zip(module_roles, content_direction.get("aplus_jobs") or []):
        if not isinstance(item, dict):
            continue
        story_job = _compact_text(item.get("story_job"))
        buyer_question = _compact_text(item.get("buyer_question"))
        if story_job and item.get("claim_proof_usable"):
            module_strategy[role] = story_job
        elif buyer_question:
            module_strategy[role] = (
                f"Address the buyer question '{buyer_question}' using only independently supported product facts"
                + (" and the visible reference anchor." if item.get("visual_anchor_usable") else ".")
            )

    diagnosis_summary = _compact_text(raw.get("diagnosis_summary"))
    if primary_job or core_value:
        diagnosis_summary = (
            f"For {primary_buyer or 'the intended buyer'}, use A+ to support the job '{primary_job}' "
            f"through the evidence-grounded value '{core_value}', without filling documented evidence gaps."
        )
    source_truth = {
        "diagnosis_summary": diagnosis_summary,
        "primary_buyer_motivation": primary_job or raw.get("primary_buyer_motivation"),
        "target_use_context": (
            f"{primary_buyer}: {primary_scenario}" if primary_buyer and primary_scenario else primary_scenario
        ) or raw.get("target_use_context"),
        "dominant_purchase_trigger": core_value or raw.get("dominant_purchase_trigger"),
        "key_buyer_objections": objections or raw.get("key_buyer_objections"),
        "evidence_strength": (
            "limited" if critical_unknowns else "mixed" if quality.get("requires_review") else raw.get("evidence_strength") or "strong"
        ),
        "evidence_gaps": evidence_gaps or raw.get("evidence_gaps"),
        "differentiation_angle": (
            "; ".join(verified_differentiators[:3])
            if verified_differentiators
            else "No comparison-ready differentiator is sufficiently proven; lead with supported product value instead."
        ),
        "narrative_strategy_by_module": module_strategy,
        "claims_to_avoid": list(dict.fromkeys([*mindset_claims_to_avoid, *raw_claims_to_avoid]))[:8],
    }
    combined = {**raw, **{key: value for key, value in source_truth.items() if value}}
    normalized = normalize_product_narrative_diagnosis(
        combined,
        product_data=product_data,
        product_image=product_image,
        selling_points=selling_points,
        fallback=fallback,
    )
    normalized["diagnosis_source"] = "customer_mindset+fallback" if fallback else "customer_mindset+llm"
    normalized["customer_mindset_source_fingerprint"] = mindset.get("source_fingerprint")
    return normalized


def _selected_competitor_fact(pd: ProductData, comparison_asin: str | None) -> dict:
    if not comparison_asin:
        return {}
    snapshot = _json_dict_from_text(getattr(pd, "gigab2b_raw_snapshot", None))
    selected = snapshot.get("selected_competitor")
    if not isinstance(selected, dict):
        return {}
    selected_asin = _normalize_asin(selected.get("asin"))
    if selected_asin != comparison_asin:
        return {}
    return selected


def _comparison_product_columns(product: Product, pd: ProductData, pi: ProductImage | None) -> list[dict]:
    current_asin = _normalize_asin(getattr(product, "amazon_asin", None))
    comparison_asin = _normalize_asin(getattr(product, "competitor_asin", None))
    selected_competitor = _selected_competitor_fact(pd, comparison_asin)
    comparison_title = _trim_text(selected_competitor.get("title"), 80) if selected_competitor else ""
    comparison_image = _compact_text(
        selected_competitor.get("image_url")
        or selected_competitor.get("main_image_url")
        or selected_competitor.get("image")
    ) if selected_competitor else ""
    return [
        {
            "column_key": "current_product",
            "asin": current_asin,
            "asin_source": "products.amazon_asin" if current_asin else None,
            "title": _product_title(pd),
            "title_source": "product_data.listing_title_or_title",
            "image_source": getattr(pi, "main_image_path", None) if pi else None,
            "image_source_field": "product_images.main_image_path" if pi and getattr(pi, "main_image_path", None) else None,
        },
        {
            "column_key": "comparison_product",
            "asin": comparison_asin,
            "asin_source": "products.competitor_asin" if comparison_asin else None,
            "title": comparison_title or None,
            "title_source": "product_data.gigab2b_raw_snapshot.selected_competitor.title" if comparison_title else None,
            "image_source": comparison_image or None,
            "image_source_field": "product_data.gigab2b_raw_snapshot.selected_competitor.image_url" if comparison_image else None,
        },
    ]


def _base_enhanced_module(contract_module, profile_version: str) -> dict:
    module = {
        "position": contract_module.position,
        "type": contract_module.internal_type,
        "internal_type": contract_module.internal_type,
        "semantic_role": contract_module.semantic_role,
        "publish_profile": APLUS_PUBLISH_PROFILE_ENHANCED_BASIC_APLUS_V1,
        "profile_version": profile_version,
        "module_spec_key": contract_module.module_spec_key,
        "lingxing_content_module_type": contract_module.lingxing_content_module_type,
        "payload_key": contract_module.payload_key,
        "required_image_slots": list(contract_module.required_image_slots),
    }
    module.update(dict(contract_module.fixed_values))
    return module


def _build_hero_module(raw: dict, contract_module, profile_version: str, pd: ProductData) -> dict:
    headline = _trim_text(raw.get("headline"), 70, _product_title(pd))
    module = _base_enhanced_module(contract_module, profile_version)
    module.update(
        {
            "headline": headline,
            "body": _trim_text(raw.get("body") or raw.get("text_content") or raw.get("key_message"), 300, "Introduce the product with a clear, truthful value promise."),
            "image_concept": _trim_text(raw.get("image_concept"), 500, "Use the confirmed product image as the identity anchor in a clean Amazon A+ hero scene."),
            "alt_text_seed": _trim_text(raw.get("alt_text_seed") or raw.get("headline"), 100, headline),
        }
    )
    module.update(_conversion_fields(raw, headline))
    return module


def _feature_from_raw(raw_feature: dict, fallback_text: str, index: int) -> dict:
    headline = _trim_text(raw_feature.get("headline"), 160, f"Feature {index}")
    return {
        "slot": f"feature_{index}",
        "headline": headline,
        "body": _trim_text(raw_feature.get("body") or raw_feature.get("text_content"), 1000, fallback_text),
        "image_concept": _trim_text(raw_feature.get("image_concept"), 500, f"Show supported product detail for {headline}."),
        "alt_text_seed": _trim_text(raw_feature.get("alt_text_seed") or headline, 100, headline),
    }


def _build_feature_grid_module(raw: dict, contract_module, profile_version: str, pd: ProductData, selling_points: list) -> dict:
    product_features = _feature_items_from_product_data(pd, selling_points)
    raw_features = _dict_list(raw.get("features"))
    features: list[dict] = []
    for index in range(1, 4):
        raw_feature = raw_features[index - 1] if index - 1 < len(raw_features) else {}
        fallback_text = product_features[(index - 1) % len(product_features)]
        features.append(_feature_from_raw(raw_feature, fallback_text, index))
    module = _base_enhanced_module(contract_module, profile_version)
    module.update(
        {
            "headline": _trim_text(raw.get("headline"), 200, "Built Around Everyday Use"),
            "features": features,
            "feature_slots": ["feature_1", "feature_2", "feature_3"],
        }
    )
    return module


def _description_blocks(raw: dict, headline: str) -> list[dict]:
    raw_blocks = _dict_list(raw.get("description_blocks"))
    blocks: list[dict] = []
    for index in range(1, 3):
        raw_block = raw_blocks[index - 1] if index - 1 < len(raw_blocks) else {}
        blocks.append(
            {
                "headline": _trim_text(raw_block.get("headline"), 200, headline if index == 1 else "More Product Context"),
                "body": _trim_text(raw_block.get("body") or raw_block.get("text_content"), 400, "Explain the product benefit using only supported facts."),
            }
        )
    return blocks


def _spec_items(raw_value, fallback_features: list[str], *, min_items: int, max_items: int) -> list[dict]:
    items: list[dict] = []
    for index, raw_item in enumerate(_as_list(raw_value), 1):
        if isinstance(raw_item, dict):
            label = raw_item.get("label") or raw_item.get("name") or raw_item.get("headline")
            value = raw_item.get("value") or raw_item.get("description") or raw_item.get("body")
        else:
            label = f"Detail {index}"
            value = raw_item
        if _compact_text(value):
            items.append(
                {
                    "label": _trim_text(label, 200, f"Detail {index}"),
                    "value": _trim_text(value, 400, fallback_features[(index - 1) % len(fallback_features)]),
                }
            )
    index = len(items) + 1
    while len(items) < min_items:
        fallback = fallback_features[(index - 1) % len(fallback_features)]
        items.append({"label": _trim_text(f"Detail {index}", 200), "value": _trim_text(fallback, 400)})
        index += 1
    return items[:max_items]


def _build_detail_proof_module(raw: dict, contract_module, profile_version: str, pd: ProductData, selling_points: list) -> dict:
    feature_items = _feature_items_from_product_data(pd, selling_points)
    headline = _trim_text(raw.get("headline"), 200, "Details That Support Daily Use")
    module = _base_enhanced_module(contract_module, profile_version)
    module.update(
        {
            "headline": headline,
            "description_headline": _trim_text(raw.get("description_headline"), 160, "Product details"),
            "description_blocks": _description_blocks(raw, headline),
            "spec_items": _spec_items(raw.get("spec_items"), feature_items, min_items=3, max_items=6),
            "spec_note": _trim_text(raw.get("spec_note"), 400, "Specifications should stay grounded in available product facts."),
            "image_concept": _trim_text(raw.get("image_concept"), 500, "Use a detail-focused product reference to support material, construction, or fit claims."),
            "alt_text_seed": _trim_text(raw.get("alt_text_seed") or headline, 100, headline),
        }
    )
    return module


def _metric_labels(raw: dict, feature_items: list[str]) -> list[str]:
    labels = _string_list(
        raw.get("metric_row_labels"),
        [f"Attribute {index}" for index in range(1, 4)],
        min_items=3,
        max_items=6,
        max_length=100,
    )
    if raw.get("metric_row_labels"):
        return labels
    return [_trim_text(item.split(":")[0], 100, f"Attribute {index}") for index, item in enumerate(feature_items[:3], 1)]


def _metric_values(raw_value, labels: list[str], fallback_prefix: str) -> list[str]:
    values = [_trim_text(item, 250) for item in _as_list(raw_value) if _compact_text(item)]
    while len(values) < len(labels):
        values.append(f"{fallback_prefix} {labels[len(values)]}")
    return values[: len(labels)]


def _build_comparison_module(raw: dict, contract_module, profile_version: str, product: Product, pd: ProductData, pi: ProductImage | None, selling_points: list) -> dict:
    feature_items = _feature_items_from_product_data(pd, selling_points)
    labels = _metric_labels(raw, feature_items)
    module = _base_enhanced_module(contract_module, profile_version)
    module.update(
        {
            "headline": _trim_text(raw.get("headline"), 160, "Compare the Details That Matter"),
            "metric_row_labels": labels,
            "current_product_metric_values": _metric_values(raw.get("current_product_metric_values"), labels, "Current product"),
            "comparison_product_metric_values": _metric_values(raw.get("comparison_product_metric_values"), labels, "Comparison product"),
            "comparison_angle": _trim_text(raw.get("comparison_angle"), 300, "Compare practical buying criteria without inventing ASINs or unsupported claims."),
            "product_columns": _comparison_product_columns(product, pd, pi),
        }
    )
    return module


def _spec_rows(raw_value, feature_items: list[str], *, min_items: int, max_items: int) -> list[dict]:
    rows: list[dict] = []
    for index, raw_item in enumerate(_as_list(raw_value), 1):
        if isinstance(raw_item, dict):
            label = raw_item.get("label") or raw_item.get("name") or raw_item.get("headline")
            description = raw_item.get("description") or raw_item.get("value") or raw_item.get("body")
        else:
            label = f"Spec {index}"
            description = raw_item
        if _compact_text(description):
            rows.append(
                {
                    "label": _trim_text(label, 30, f"Spec {index}"),
                    "description": _trim_text(description, 500, feature_items[(index - 1) % len(feature_items)]),
                }
            )
    index = len(rows) + 1
    while len(rows) < min_items:
        rows.append(
            {
                "label": _trim_text(f"Spec {index}", 30),
                "description": _trim_text(feature_items[(index - 1) % len(feature_items)], 500),
            }
        )
        index += 1
    return rows[:max_items]


def _build_technical_or_closing_module(raw: dict, contract_module, profile_version: str, pd: ProductData, selling_points: list) -> dict:
    feature_items = _feature_items_from_product_data(pd, selling_points)
    module = _base_enhanced_module(contract_module, profile_version)
    module.update(
        {
            "headline": _trim_text(raw.get("headline"), 80, "Product Specs"),
            "spec_rows": _spec_rows(raw.get("spec_rows"), feature_items, min_items=4, max_items=10),
            "closing_note": _trim_text(raw.get("closing_note"), 300, ""),
            "tableCount": 1,
        }
    )
    return module


def _build_enhanced_module(raw: dict, contract_module, profile_version: str, product: Product, pd: ProductData, pi: ProductImage | None, selling_points: list) -> dict:
    if contract_module.semantic_role == "hero":
        return _build_hero_module(raw, contract_module, profile_version, pd)
    if contract_module.semantic_role == "feature_grid":
        return _build_feature_grid_module(raw, contract_module, profile_version, pd, selling_points)
    if contract_module.semantic_role == "detail_proof":
        return _build_detail_proof_module(raw, contract_module, profile_version, pd, selling_points)
    if contract_module.semantic_role == "comparison":
        return _build_comparison_module(raw, contract_module, profile_version, product, pd, pi, selling_points)
    if contract_module.semantic_role == "technical_or_closing":
        return _build_technical_or_closing_module(raw, contract_module, profile_version, pd, selling_points)
    raise ValueError(f"Unsupported enhanced A+ semantic role: {contract_module.semantic_role}")


def aplus_publish_profile_for_plan(plan: dict | None) -> str | None:
    if not isinstance(plan, dict):
        return None
    for value in (
        plan.get("publish_profile"),
        plan.get("aplus_plan_version"),
        plan.get("profile"),
    ):
        text = _compact_text(value)
        if text:
            return text
    modules = plan.get("modules")
    if isinstance(modules, list):
        for module in modules:
            if not isinstance(module, dict):
                continue
            text = _compact_text(module.get("publish_profile"))
            if text:
                return text
    return None


def _build_enhanced_basic_aplus_plan(raw_plan: dict, *, product: Product, product_data: ProductData, product_image: ProductImage | None, selling_points: list) -> dict:
    contract = producer_contract_for_profile(APLUS_PUBLISH_PROFILE_ENHANCED_BASIC_APLUS_V1)
    if contract is None:
        raise ValueError("enhanced_basic_aplus_v1 producer contract is not registered")
    raw_modules = raw_plan.get("modules") if isinstance(raw_plan.get("modules"), list) else []
    modules_by_role = _module_candidates_by_role(raw_modules)
    modules = [
        _build_enhanced_module(
            _raw_module_for_contract(raw_modules, modules_by_role, contract_module),
            contract_module,
            contract.profile_version,
            product,
            product_data,
            product_image,
            selling_points,
        )
        for contract_module in contract.modules
    ]
    plan = {
        "aplus_plan_version": contract.profile_key,
        "publish_profile": contract.profile_key,
        "profile_version": contract.profile_version,
        "module_contract_source": APLUS_MODULE_CONTRACT_SOURCE,
        "product_narrative_diagnosis": _normalize_narrative_with_customer_mindset(
            raw_plan.get("product_narrative_diagnosis") or raw_plan.get("narrative_diagnosis"),
            product_data=product_data,
            product_image=product_image,
            selling_points=selling_points,
            fallback=False,
        ),
        "modules": modules,
        "plan_summary": _trim_text(raw_plan.get("plan_summary"), 500, "Enhanced basic A+ plan generated from business content and registry contract."),
        "tone": _trim_text(raw_plan.get("tone"), 80, "professional"),
        "color_palette": _string_list(raw_plan.get("color_palette"), ["#FFFFFF", "#111827", "#2563EB"], min_items=2, max_items=5, max_length=20),
        "target_audience": _trim_text(raw_plan.get("target_audience"), 200, "Amazon shoppers evaluating product fit, quality, and ownership context."),
    }
    for optional_key in ("fallback", "fallback_reason", "llm_model", "reference_candidate_count"):
        if optional_key in raw_plan:
            plan[optional_key] = raw_plan[optional_key]
    return plan


def _build_standard_header_image_text_plan(
    raw_plan: dict,
    *,
    product: Product,
    product_data: ProductData,
    product_image: ProductImage | None,
    selling_points: list,
) -> dict:
    raw_modules = raw_plan.get("modules") if isinstance(raw_plan.get("modules"), list) else []
    modules: list[dict] = []
    for index in range(1, 6):
        raw_module = raw_modules[index - 1] if index - 1 < len(raw_modules) and isinstance(raw_modules[index - 1], dict) else {}
        module = dict(raw_module)
        _normalize_module_strategy(module, index)
        modules.append(module)
    plan = dict(raw_plan)
    plan["product_narrative_diagnosis"] = _normalize_narrative_with_customer_mindset(
        raw_plan.get("product_narrative_diagnosis") or raw_plan.get("narrative_diagnosis"),
        product_data=product_data,
        product_image=product_image,
        selling_points=selling_points,
        fallback=False,
    )
    plan["modules"] = modules
    return plan


def build_aplus_plan_from_business_content(
    raw_plan: dict,
    *,
    product: Product,
    product_data: ProductData,
    product_image: ProductImage | None,
    selling_points: list,
    profile_key: str = DEFAULT_APLUS_PUBLISH_PROFILE,
) -> dict:
    if profile_key == APLUS_PUBLISH_PROFILE_ENHANCED_BASIC_APLUS_V1:
        return _build_enhanced_basic_aplus_plan(
            raw_plan if isinstance(raw_plan, dict) else {},
            product=product,
            product_data=product_data,
            product_image=product_image,
            selling_points=selling_points,
        )
    if profile_key == APLUS_PUBLISH_PROFILE_STANDARD_HEADER_IMAGE_TEXT_V1:
        return _build_standard_header_image_text_plan(
            raw_plan if isinstance(raw_plan, dict) else {},
            product=product,
            product_data=product_data,
            product_image=product_image,
            selling_points=selling_points,
        )
    raise ValueError(f"Unsupported A+ publish profile for Step7 producer: {profile_key}")


def _reference_candidate_count(pi: ProductImage | None) -> int:
    if not pi:
        return 0
    reference_paths = [pi.main_image_path] if pi.main_image_path else []
    if pi.gallery_images:
        try:
            parsed_gallery = json.loads(pi.gallery_images)
            if isinstance(parsed_gallery, list):
                reference_paths.extend(
                    item.get("path") if isinstance(item, dict) else item
                    for item in parsed_gallery
                )
        except Exception:
            pass
    return len({str(path) for path in reference_paths if path})


STANDARD_BANNER_ROLE_GUIDANCE = {
    "hero": {
        "subheading": "A clear first look at the product and its primary value.",
        "experience_angle": "Show the product immediately understandable in a clean hero setting.",
        "buyer_objection": "What is this product, and why should I keep reading?",
        "banner_layout": "Wide hero banner with the product as the dominant focal point and one short benefit phrase.",
        "preferred_reference_roles": ["product identity", "best complete product view"],
        "reference_strategy": "Use a strong product-identity reference plus one context or angle reference; preserve exact product shape, color, material, packaging, and visible construction.",
        "image_style": "photography",
    },
    "lifestyle": {
        "subheading": "Show the product in a realistic usage moment.",
        "experience_angle": "Show a believable ownership or usage moment that explains fit, scale, or daily value.",
        "buyer_objection": "Will this fit my real use case?",
        "banner_layout": "Wide lifestyle banner with real context, enough negative space for short copy, and the product still clearly visible.",
        "preferred_reference_roles": ["usage context", "product identity"],
        "reference_strategy": "Use one usage/context reference when available plus one product-identity reference; preserve scale and visible product details.",
        "image_style": "lifestyle",
    },
    "feature_proof": {
        "subheading": "Focus on supported construction, finish, or functional details.",
        "experience_angle": "Turn a visible product detail into buyer confidence.",
        "buyer_objection": "Can I trust the quality or function shown in the listing?",
        "banner_layout": "Wide proof banner with one main product view and restrained callouts for visible details only.",
        "preferred_reference_roles": ["material close-up", "feature detail"],
        "reference_strategy": "Use a detail/material/feature reference plus one identity reference; avoid showing features not visible in references.",
        "image_style": "infographic",
    },
    "spec_objection": {
        "subheading": "Answer the buyer's practical fit or setup questions.",
        "experience_angle": "Make dimensions, setup, compatibility, material, or included details feel easy to understand.",
        "buyer_objection": "Will the size, setup, material, or compatibility work for me?",
        "banner_layout": "Wide explanatory banner with simple visual hierarchy; use at most two short callouts and no dense spec table.",
        "preferred_reference_roles": ["dimensions or scale", "product identity"],
        "reference_strategy": "Use scale/dimension/detail evidence plus one identity reference; if evidence is limited, keep the visual conservative.",
        "image_style": "infographic",
    },
    "closing": {
        "subheading": "Close with a practical ownership scene.",
        "experience_angle": "Show the final ownership payoff after the buyer understands the product.",
        "buyer_objection": "Is this the right choice to finish my setup or solve my need?",
        "banner_layout": "Wide closing banner with a composed final-use scene and one concise confidence message.",
        "preferred_reference_roles": ["finished use scene", "product identity"],
        "reference_strategy": "Use an ownership/context reference plus one product-identity reference; keep the close truthful and not exaggerated.",
        "image_style": "lifestyle",
    },
}


def _normalize_module_strategy(module: dict, index: int) -> dict:
    module["position"] = index
    module["type"] = INTERNAL_STANDARD_HEADER_IMAGE_TEXT_TYPE
    module["semantic_role"] = semantic_role_for_position(index)
    module["publish_profile"] = APLUS_PUBLISH_PROFILE_STANDARD_HEADER_IMAGE_TEXT_V1
    module["lingxing_content_module_type"] = LINGXING_STANDARD_HEADER_IMAGE_TEXT
    role_guidance = STANDARD_BANNER_ROLE_GUIDANCE.get(module["semantic_role"], {})
    if not str(module.get("headline") or "").strip():
        module["headline"] = f"A+ Module {index}"
    if not str(module.get("subheading") or "").strip() and role_guidance.get("subheading"):
        module["subheading"] = role_guidance["subheading"]
    module.setdefault("conversion_goal", module.get("key_message") or module.get("headline") or f"Explain A+ module {index}")
    module.setdefault("buyer_objection", role_guidance.get("buyer_objection") or "Clarify the buyer doubt addressed by this module.")
    module.setdefault("reference_strategy", role_guidance.get("reference_strategy") or "Use one product-identity reference and one support reference matched to this module.")
    module.setdefault("evidence_source", module.get("reference_strategy") or "Use available product facts and selected reference images.")
    module.setdefault("experience_angle", role_guidance.get("experience_angle") or module.get("image_concept") or module.get("headline") or "Show a realistic ownership or usage experience.")
    module.setdefault("gallery_overlap_avoidance", "Avoid repeating MAIN/gallery specs unless adding deeper usage context.")
    module.setdefault("banner_layout", role_guidance.get("banner_layout") or "Wide Amazon A+ banner with one clear focal product/reference anchor and restrained copy.")
    module.setdefault("image_style", role_guidance.get("image_style") or module.get("image_style") or "photography")
    preferred_roles = module.get("preferred_reference_roles")
    if not isinstance(preferred_roles, list) or not preferred_roles:
        module["preferred_reference_roles"] = list(role_guidance.get("preferred_reference_roles") or ["product identity", "supporting detail"])
    for key in ("primary_reference_image_id", "secondary_reference_image_id"):
        value = str(module.get(key) or "").strip()
        module[key] = value if value else None
    module.setdefault(
        "reference_selection_reason",
        "Use the strongest available product-identity anchor plus evidence matched to this module's buyer question.",
    )
    module.setdefault(
        "primary_reference_use",
        "Preserve product identity, silhouette, color, proportions, visible parts, material, and construction.",
    )
    module.setdefault(
        "secondary_reference_use",
        "Preserve the module-specific visible detail, usage context, scale, or function when available.",
    )
    fallback_roles = module.get("fallback_reference_roles")
    if not isinstance(fallback_roles, list) or not fallback_roles:
        module["fallback_reference_roles"] = list(module.get("preferred_reference_roles") or ["product identity", "supporting detail"])
    if not str(module.get("key_message") or "").strip():
        module["key_message"] = module.get("conversion_goal") or module.get("headline") or f"Explain A+ module {index}"
    if not str(module.get("text_content") or "").strip():
        module["text_content"] = module.get("key_message") or module.get("headline") or f"Explain A+ module {index}"
    guardrails = module.get("risk_guardrails")
    if not isinstance(guardrails, list):
        module["risk_guardrails"] = [
            "Keep claims truthful and supported by product facts or visible reference images.",
            "Preserve product identity, color, material, scale, proportions, and visible construction.",
        ]
    do_not_claim = module.get("visual_do_not_claim")
    if not isinstance(do_not_claim, list):
        module["visual_do_not_claim"] = [
            "Do not show unsupported accessories, functions, certifications, safety claims, or material changes.",
        ]
    checklist = module.get("quality_checklist")
    if not isinstance(checklist, list):
        module["quality_checklist"] = [
            "One clear buyer question and one visible product benefit.",
            "Product identity remains faithful to selected references.",
            "Wide banner composition reads clearly at 1940 x 1200.",
            "On-image copy is short, benefit-led, and brand-name free.",
        ]
    return module


def fallback_aplus_plan(
    product: Product,
    pd: ProductData,
    pi: ProductImage | None,
    selling_points: list,
    *,
    profile_key: str = DEFAULT_APLUS_PUBLISH_PROFILE,
) -> dict:
    title = pd.listing_title or pd.title or "Product"
    category = pd.leaf_category or pd.amazon_category or "General"
    feature_items = _feature_items_from_product_data(pd, selling_points)
    if profile_key == APLUS_PUBLISH_PROFILE_STANDARD_HEADER_IMAGE_TEXT_V1:
        modules = [
            {
                "position": 1,
                "type": INTERNAL_STANDARD_HEADER_IMAGE_TEXT_TYPE,
                "semantic_role": "hero",
                "headline": title[:90],
                "subheading": "A clear first look at the product and its primary value.",
                "key_message": f"Introduce the {category} product with a clean hero composition.",
                "text_content": f"Introduce the {category} product with a clean hero composition and truthful product context.",
                "image_concept": "Use the confirmed product image as the identity anchor, with a simple lifestyle context and conservative copy.",
            },
            {
                "position": 2,
                "type": INTERNAL_STANDARD_HEADER_IMAGE_TEXT_TYPE,
                "semantic_role": "lifestyle",
                "headline": "Designed for Everyday Use",
                "subheading": "Show the product in a realistic usage moment.",
                "key_message": feature_items[0],
                "text_content": feature_items[0],
                "image_concept": "Show a realistic usage scene that keeps the product shape, color, and visible material faithful to the references.",
            },
            {
                "position": 3,
                "type": INTERNAL_STANDARD_HEADER_IMAGE_TEXT_TYPE,
                "semantic_role": "feature_proof",
                "headline": "Visible Details",
                "subheading": "Focus on supported construction, finish, or functional details.",
                "key_message": "; ".join(feature_items[1:4]) or feature_items[0],
                "text_content": "; ".join(feature_items[1:4]) or feature_items[0],
                "image_concept": "Use detail-focused reference images to explain visible construction, finish, or functional parts.",
            },
            {
                "position": 4,
                "type": INTERNAL_STANDARD_HEADER_IMAGE_TEXT_TYPE,
                "semantic_role": "spec_objection",
                "headline": "Product Specifications",
                "subheading": "Answer the buyer's practical fit or setup questions.",
                "key_message": "Present dimensions, material, use case, and included details only when supported by product facts.",
                "text_content": "Present dimensions, material, use case, and included details only when supported by product facts.",
                "image_concept": "Create a clean specification layout without inventing certifications, safety claims, or unsupported performance claims.",
            },
            {
                "position": 5,
                "type": INTERNAL_STANDARD_HEADER_IMAGE_TEXT_TYPE,
                "semantic_role": "closing",
                "headline": "Complete the Setup",
                "subheading": "Close with a practical ownership scene.",
                "key_message": feature_items[-1],
                "text_content": feature_items[-1],
                "image_concept": "Close with a practical ownership scene that reinforces the most visible selling point from the selected images.",
            },
        ]
        for idx, module in enumerate(modules, 1):
            _normalize_module_strategy(module, idx)
        return {
            "modules": modules,
            "product_narrative_diagnosis": _normalize_narrative_with_customer_mindset(
                None,
                product_data=pd,
                product_image=pi,
                selling_points=selling_points,
                fallback=True,
            ),
            "plan_summary": "A+规划由保底逻辑生成：LLM连接超时，已先生成可继续执行的结构化草案；如需更高质量，可重跑A+规划。",
            "tone": "professional",
            "color_palette": ["#FFFFFF", "#111827", "#2563EB"],
            "fallback": True,
            "fallback_reason": "LLM timeout while generating A+ plan",
            "llm_model": settings.LLM_MODEL,
            "reference_candidate_count": _reference_candidate_count(pi),
        }

    raw_plan = {
        "plan_summary": "A+ planning was generated by fallback logic after the LLM did not return usable content.",
        "product_narrative_diagnosis": _normalize_narrative_with_customer_mindset(
            None,
            product_data=pd,
            product_image=pi,
            selling_points=selling_points,
            fallback=True,
        ),
        "tone": "professional",
        "color_palette": ["#FFFFFF", "#111827", "#2563EB"],
        "target_audience": "Amazon shoppers comparing product fit, material, and ownership context.",
        "modules": [
            {
                "semantic_role": "hero",
                "headline": title,
                "body": f"Introduce the {category} product with a clean hero composition and truthful product context.",
                "image_concept": "Use the confirmed product image as the identity anchor, with a simple lifestyle context and conservative copy.",
                "alt_text_seed": title,
            },
            {
                "semantic_role": "feature_grid",
                "headline": "Designed for Everyday Use",
                "features": [
                    {
                        "headline": f"Feature {index}",
                        "body": feature_items[(index - 1) % len(feature_items)],
                        "image_concept": "Show a realistic product detail grounded in selected references.",
                        "alt_text_seed": feature_items[(index - 1) % len(feature_items)],
                    }
                    for index in range(1, 4)
                ],
            },
            {
                "semantic_role": "detail_proof",
                "headline": "Details You Can Verify",
                "description_headline": "Product details",
                "description_blocks": [
                    {
                        "headline": "Visible construction",
                        "body": "Use reference-backed details to explain material, fit, construction, or usage context.",
                    },
                    {
                        "headline": "Buyer context",
                        "body": "Keep specs conservative and do not introduce unsupported certifications or performance claims.",
                    },
                ],
                "spec_items": [{"label": f"Detail {index}", "value": item} for index, item in enumerate(feature_items[:6], 1)],
                "image_concept": "Use detail-focused reference images to explain visible construction, finish, or functional parts.",
                "alt_text_seed": "Product detail view",
            },
            {
                "semantic_role": "comparison",
                "headline": "Compare the Practical Details",
                "metric_row_labels": ["Product type", "Material context", "Use case"],
                "current_product_metric_values": [
                    category,
                    feature_items[0],
                    "Grounded in current product facts and selected reference images.",
                ],
                "comparison_product_metric_values": [
                    "Comparison product fact required",
                    "Comparison product fact required",
                    "Comparison product fact required",
                ],
                "comparison_angle": "Compare only backend-sourced ASIN columns and conservative buyer criteria.",
            },
            {
                "semantic_role": "technical_or_closing",
                "headline": "Product Specs",
                "spec_rows": [{"label": f"Spec {index}", "description": item} for index, item in enumerate((feature_items * 4)[:4], 1)],
                "closing_note": "Use this section to answer final fit and ownership questions.",
            },
        ],
        "fallback": True,
        "fallback_reason": "LLM timeout while generating A+ plan",
        "llm_model": settings.LLM_MODEL,
    }
    raw_plan["reference_candidate_count"] = _reference_candidate_count(pi)
    return build_aplus_plan_from_business_content(
        raw_plan,
        product=product,
        product_data=pd,
        product_image=pi,
        selling_points=selling_points,
        profile_key=profile_key,
    )


def _fallback_aplus_plan(product: Product, pd: ProductData, pi: ProductImage | None, selling_points: list) -> dict:
    return fallback_aplus_plan(product, pd, pi, selling_points)


async def run_aplus_plan(product_id: int) -> dict:
    """
    执行 A+ 规划
    
    读取所有前置数据，调用 LLM 生成 A+ 布局方案
    """
    async with async_session() as db:
        result = await db.execute(
            select(Product)
            .options(
                selectinload(Product.data),
                selectinload(Product.images),
                selectinload(Product.aplus),
            )
            .where(Product.id == product_id)
        )
        product = result.scalar_one_or_none()
        if not product or not product.data:
            raise ValueError(f"Product {product_id} not found or no data")

        pd = product.data
        pi = product.images
        if not pi or not image_analysis_ready(pi.image_analysis):
            raise RuntimeError("图片分析尚未完成，不能规划 A+")
        if not pd.customer_mindset:
            raise RuntimeError("用户心智梳理尚未完成，不能规划 A+")
        if not customer_mindset_matches_product(pd.customer_mindset, product):
            raise RuntimeError("用户心智梳理已过期：商品、关键词、竞品或图片分析输入发生变化，请重新梳理后再规划 A+")

        # 收集卖点
        selling_points = []
        if pi and pi.image_selling_points:
            try:
                selling_points = json.loads(pi.image_selling_points)
            except:
                pass

        # 收集features
        features = "N/A"
        if pd.features:
            try:
                fl = json.loads(pd.features)
                features = "\n".join(f"- {f}" for f in fl) if isinstance(fl, list) else str(fl)
            except:
                features = str(pd.features)

        mindset_context = customer_mindset_context(
            getattr(pd, "customer_mindset", None),
            surface="aplus",
            required=True,
        )

        prompt = PLAN_PROMPT.format(
            title=pd.listing_title or pd.title or "Unknown",
            brand=product.brand or settings.DEFAULT_BRAND,
            category=pd.leaf_category or "General",
            price=pd.suggested_price or "TBD",
            features=features,
            selling_points="\n".join(f"- {s}" for s in selling_points) if selling_points else "N/A",
            reference_candidates=_format_reference_candidates(pi),
            image_diagnostics=_format_image_diagnostics(pi),
            primary_keyword=pd.listing_primary_keyword or "N/A",
            customer_mindset=json.dumps(mindset_context, ensure_ascii=False, indent=2),
        )

        # The read transaction above must not hold a MySQL connection across
        # two long LLM attempts. MySQL may close that idle transport before
        # the fallback plan is persisted; the later write then obtains a fresh
        # connection.
        await db.commit()

        # 调用 LLM
        client = settings.get_llm_client()
        max_attempts = 2
        timeout_seconds = max(
            60,
            int(getattr(settings, "APLUS_PLAN_LLM_TIMEOUT_SECONDS", 120)),
        )
        request_client = (
            client.with_options(timeout=timeout_seconds, max_retries=0)
            if hasattr(client, "with_options")
            else client
        )

        logger.info(f"[Step7] 调用LLM生成A+规划: {pd.title}")
        response = None
        plan = None
        last_transient_error: Exception | None = None
        for attempt in range(1, max_attempts + 1):
            try:
                response = await request_client.chat.completions.create(
                    model=settings.LLM_MODEL,
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.8,
                    max_tokens=3000,
                    response_format={"type": "json_object"},
                )
                break
            except Exception as exc:
                if not _is_transient_llm_error(exc):
                    raise
                last_transient_error = exc
                if attempt >= max_attempts:
                    logger.warning(
                        "[Step7] A+规划LLM连接连续失败，使用 fallback plan: error=%s: %s",
                        type(exc).__name__,
                        exc,
                    )
                    plan = fallback_aplus_plan(product, pd, pi, selling_points)
                    break
                wait_seconds = attempt * 5
                logger.warning(
                    "[Step7] A+规划LLM连接异常，准备重试: attempt=%s/%s, wait=%ss, error=%s: %s",
                    attempt,
                    max_attempts,
                    wait_seconds,
                    type(exc).__name__,
                    exc,
                )
                await asyncio.sleep(wait_seconds)
        if response is None and plan is None:
            if last_transient_error:
                raise RuntimeError(
                    f"A+规划未生成真实结果，请重跑: {type(last_transient_error).__name__}: {last_transient_error}"
                ) from last_transient_error
            raise RuntimeError("A+规划未生成真实结果，请重跑")
        elif plan is None:
            content = response.choices[0].message.content
            if not content:
                raise RuntimeError("LLM 返回空结果")

            try:
                raw_plan = json.loads(content)
            except json.JSONDecodeError as e:
                raise RuntimeError(f"A+规划JSON解析失败: {e}")

            plan = build_aplus_plan_from_business_content(
                raw_plan,
                product=product,
                product_data=pd,
                product_image=pi,
                selling_points=selling_points,
                profile_key=DEFAULT_APLUS_PUBLISH_PROFILE,
            )

        # 确保 ProductAplus 记录存在
        pa = product.aplus
        if not pa:
            pa = ProductAplus(product_id=product.id)
            db.add(pa)

        pa.aplus_plan = json.dumps(plan, ensure_ascii=False)
        pa.aplus_plan_summary = plan.get("plan_summary")
        pa.planned_at = datetime.now()
        pa.llm_model = settings.LLM_MODEL
        await write_aplus_plan_artifacts(db, product=product, plan=plan)
        await db.commit()

        logger.info(f"[Step7] A+规划完成: {len(plan.get('modules') or [])} 个模块, 风格={plan.get('tone')}")
        return plan
