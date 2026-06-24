"""
模块7：A+ 规划 — 使用 LLM 设计 A+ Content 布局

基于商品属性、卖点、关键词和图片分析结果，
生成 A+ Content 的模块布局规划（普通 A+ 固定 5 个模块）
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
- Preserve the original product identity and proportions as much as possible. Do not plan transformations that change the sofa shape, color, module count, cushion proportions, armrest structure, fabric texture, or low-profile silhouette.
- Preserve the product material shown in the reference images. Do not plan a change from the supplied upholstery/fabric/wood/metal material into another material.
- Plan different reference-image roles per module. Do not make every A+ image use the same two product references.
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

## Requirements
1. Exactly 5 modules total for standard Amazon A+ content. Do not create 6 or 7 modules.
2. First module: hero/value promise, but on-image text must not include the brand name
3. Use exactly these semantic roles by position: hero, lifestyle, feature_proof, spec_objection, closing.
4. Render specs only as a buyer-objection story in the spec_objection module; do not create an unsupported native comparison chart or native spec table.
5. Last module: confidence, ownership close, or cross-sell context
6. Each module needs: type="standard_header_image_text", semantic_role, headline, subheading, key message, text_content, image concept
7. Image concepts must preserve the original product shape, color, module count, cushion proportions, armrests, fabric texture, and low-profile silhouette.
8. If a scene includes people, specify complete full-body people with natural anatomy and no cropped body parts.
9. Any planned on-image text must avoid the brand name "{brand}".
10. For each module, add a reference_strategy that names the two different kinds of product references needed for that module, such as product identity, lifestyle context, dimensions, material close-up, comfort detail, or finished-back view.
11. Choose reference strategies from the provided image candidates and vary the pair by module; the same two references should not be used for every module.
12. State that the material from the selected product references must be preserved and not replaced.
13. The image concept should stay close to the selected references' visible selling points. Do not plan new features, extra accessories, different modules, different cushions, different legs, different armrests, different stitching, or unsupported claims that are not visible in the references/product facts.
14. Allow changes mainly to scenario, people, light, camera angle, room styling, and clean Amazon A+ composition; keep the product itself reference-faithful.
15. A+ should be experience-led, not spec-led. Prefer lifestyle, usage, ownership feeling, room fit, comfort, setup ease, and emotional context over repeating dry parameters.
16. At least 3 of the 5 modules should be lifestyle/experience-led unless the product category makes that unsafe or misleading.
17. Use the Image Risk and Conversion Gaps to choose module priorities, but translate gaps into user experience where possible. For example, a dimensions gap becomes "small apartment fit"; a material gap becomes "soft touch in daily lounging"; a setup gap becomes "easy move-in setup".
18. Use specs only when they reduce a major buyer objection, and keep specs as supporting evidence rather than the main A+ story.
19. Do not repeat information already covered by MAIN/gallery images unless A+ adds deeper context, emotion, or usage understanding.
20. Do not pretend missing gallery evidence exists. If references are limited, use conservative text/spec explanation or a visual concept anchored to available references, and avoid unsupported visual claims.
21. For every module, define the conversion strategy fields: conversion_goal, buyer_objection, evidence_source, risk_guardrails, visual_do_not_claim, experience_angle, and gallery_overlap_avoidance.
22. Keep on-image copy short and useful. Do not write keyword-stuffed or paragraph-like image text.

Output JSON:
{{
  "plan_summary": "brief description of the A+ strategy",
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
            "slot": selected.get("slot"),
            "filename": selected.get("filename"),
            "path": path,
            "role": selected.get("role") or selected.get("conversion_role") or review.get("conversion_role"),
            "image_type": review.get("image_type"),
            "selling_point": review.get("visible_selling_point") or mm.get("primary_selling_point"),
            "material": review.get("material_texture") or mm.get("material_texture"),
            "scene": review.get("scene_type") or mm.get("scene_type"),
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


def _build_standard_header_image_text_plan(raw_plan: dict) -> dict:
    raw_modules = raw_plan.get("modules") if isinstance(raw_plan.get("modules"), list) else []
    modules: list[dict] = []
    for index in range(1, 6):
        raw_module = raw_modules[index - 1] if index - 1 < len(raw_modules) and isinstance(raw_modules[index - 1], dict) else {}
        module = dict(raw_module)
        _normalize_module_strategy(module, index)
        modules.append(module)
    plan = dict(raw_plan)
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
        return _build_standard_header_image_text_plan(raw_plan if isinstance(raw_plan, dict) else {})
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


def _normalize_module_strategy(module: dict, index: int) -> dict:
    module["position"] = index
    module["type"] = INTERNAL_STANDARD_HEADER_IMAGE_TEXT_TYPE
    module["semantic_role"] = semantic_role_for_position(index)
    module["publish_profile"] = APLUS_PUBLISH_PROFILE_STANDARD_HEADER_IMAGE_TEXT_V1
    module["lingxing_content_module_type"] = LINGXING_STANDARD_HEADER_IMAGE_TEXT
    if not str(module.get("headline") or "").strip():
        module["headline"] = f"A+ Module {index}"
    module.setdefault("conversion_goal", module.get("key_message") or module.get("headline") or f"Explain A+ module {index}")
    module.setdefault("buyer_objection", "Clarify the buyer doubt addressed by this module.")
    module.setdefault("evidence_source", module.get("reference_strategy") or "Use available product facts and selected reference images.")
    module.setdefault("experience_angle", module.get("image_concept") or module.get("headline") or "Show a realistic ownership or usage experience.")
    module.setdefault("gallery_overlap_avoidance", "Avoid repeating MAIN/gallery specs unless adding deeper usage context.")
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
        )

        # 调用 LLM
        client = settings.get_llm_client()
        max_attempts = 2
        request_client = client.with_options(timeout=35, max_retries=0) if hasattr(client, "with_options") else client

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
        await db.commit()

        logger.info(f"[Step7] A+规划完成: {len(plan.get('modules') or [])} 个模块, 风格={plan.get('tone')}")
        return plan
