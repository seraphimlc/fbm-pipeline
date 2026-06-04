"""
模块7：A+ 规划 — 使用 LLM 设计 A+ Content 布局

基于商品属性、卖点、关键词和图片分析结果，
生成 A+ Content 的模块布局规划（普通 A+ 固定 5 个模块）
"""

import asyncio
import json
import logging
from datetime import datetime

from app.config import settings
from app.database import async_session
from app.models import Product, ProductData, ProductImage, ProductAplus
from sqlalchemy import select
from sqlalchemy.orm import selectinload

logger = logging.getLogger(__name__)


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

Common A+ module types:
- Standard Image Header (banner with text overlay)
- Standard Single Image + Text (side by side)
- Standard 4 Image / Text (quadrant layout)
- Standard Comparison Chart
- Standard Multiple Image + Text

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
2. First module: hero banner/header, but on-image text must not include the brand name
3. Mix of image+text modules
4. At least one comparison or spec module
5. Last module: cross-sell or brand closing
6. Each module needs: type, headline, key message, image concept
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
      "type": "standard_image_header",
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


def _normalize_module_strategy(module: dict, index: int) -> dict:
    module.setdefault("conversion_goal", module.get("key_message") or module.get("headline") or f"Explain A+ module {index}")
    module.setdefault("buyer_objection", "Clarify the buyer doubt addressed by this module.")
    module.setdefault("evidence_source", module.get("reference_strategy") or "Use available product facts and selected reference images.")
    module.setdefault("experience_angle", module.get("image_concept") or module.get("headline") or "Show a realistic ownership or usage experience.")
    module.setdefault("gallery_overlap_avoidance", "Avoid repeating MAIN/gallery specs unless adding deeper usage context.")
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
        request_client = client.with_options(timeout=60, max_retries=0) if hasattr(client, "with_options") else client

        logger.info(f"[Step7] 调用LLM生成A+规划: {pd.title}")
        response = None
        for attempt in range(1, 4):
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
                if not _is_transient_llm_error(exc) or attempt >= 3:
                    raise
                wait_seconds = attempt * 5
                logger.warning(
                    "[Step7] A+规划LLM连接异常，准备重试: attempt=%s/3, wait=%ss, error=%s: %s",
                    attempt,
                    wait_seconds,
                    type(exc).__name__,
                    exc,
                )
                await asyncio.sleep(wait_seconds)
        if response is None:
            raise RuntimeError("LLM 未返回 A+规划响应")

        content = response.choices[0].message.content
        if not content:
            raise RuntimeError("LLM 返回空结果")

        try:
            plan = json.loads(content)
        except json.JSONDecodeError as e:
            raise RuntimeError(f"A+规划JSON解析失败: {e}")

        modules = plan.get("modules", [])
        if not isinstance(modules, list) or len(modules) < 5:
            raise RuntimeError(f"A+规划模块数量不足: {len(modules) if isinstance(modules, list) else 0}/5")
        if len(modules) > 5:
            logger.info(f"[Step7] A+规划返回 {len(modules)} 个模块，普通A+仅保留前5个")
            modules = modules[:5]
        for idx, module in enumerate(modules, 1):
            if isinstance(module, dict):
                module["position"] = idx
                _normalize_module_strategy(module, idx)
        plan["modules"] = modules

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

        logger.info(f"[Step7] A+规划完成: {len(modules)} 个模块, 风格={plan.get('tone')}")
        return plan
