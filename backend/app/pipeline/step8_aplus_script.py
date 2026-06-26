"""
模块8：A+ 脚本 — 使用 LLM 为每个 A+ 模块生成出图 Prompt

将模块7的规划转化为具体的 GPT Image 出图指令（prompt + 尺寸 + 风格）
"""

import asyncio
import json
import logging
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote, urlparse

from app.aplus_publish.module_registry import (
    APLUS_PUBLISH_PROFILE_ENHANCED_BASIC_APLUS_V1,
    APLUS_PUBLISH_PROFILE_STANDARD_HEADER_IMAGE_TEXT_V1,
    LINGXING_STANDARD_HEADER_IMAGE_TEXT,
    producer_contract_for_profile,
    required_image_slots,
)
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


def _is_remote_url(value: str | None) -> bool:
    return bool(value and str(value).strip().lower().startswith(("http://", "https://")))


def _reference_filename(path: str) -> str:
    if _is_remote_url(path):
        return Path(unquote(urlparse(path).path)).name or "remote-reference.jpg"
    return Path(path).name

SYSTEM_PROMPT = """You are an expert at writing image generation prompts for Amazon A+ Content.
You create detailed, specific prompts for GPT Image API that produce:
- Professional product photography
- Clean, brand-consistent visuals
- Amazon-compliant layouts
- High conversion design

Key rules:
- Prompts must be in English
- Describe exact composition, lighting, color scheme
- Include product appearance based on attributes
- Specify text elements to render (headlines, bullet points)
- On-image text must NOT contain the brand name. The brand can guide style internally, but do not render it as a logo, wordmark, headline, caption, or text overlay.
- Lifestyle scenes may include people when useful, but any visible person must be shown as a complete, natural full body. Do not crop people at the head, hands, torso, legs, or feet.
- Preserve the original product identity and proportions as much as possible: same product type, shape, color, scale, key parts, visible accessories, material, surface finish, and distinctive construction details shown in the references.
- Preserve the exact material shown in the selected product reference images. Do not change fabric, plastic, wood, metal, finish, texture, packaging, or visible surface treatment into another material.
- Each A+ module must use its own two reference images chosen for that module's purpose. Do not reuse the same pair for every image.
- Each generated image should stay close to the selected references' visible selling points. Do not invent new product functions, parts, accessories, finishes, construction details, or claims that are not visible in the references or supported by product facts.
- You may change scene, people, light, room styling, camera framing, and A+ layout, but keep the product itself as close as possible to the selected reference images.
- Output dimensions should match Amazon A+ specs

Output valid JSON only."""

SCRIPT_PROMPT = """Generate image generation prompts for each A+ Content module.

## Product
- Title: {title}
- Brand: {brand}
- Color: {color}
- Material: {material}
- Category: {category}

## A+ Plan
{plan_json}

## Reference Image Candidates
{reference_candidates}

## Brand Colors
{colors}

## Image Style
Style: {style}
Tone: {tone}

## Requirements
For each module in the plan, generate a detailed image generation prompt:
- Adapt the visual strategy to the actual product category and product facts. Do not reuse furniture, sofa, home decor, toy, apparel, electronics, or other category-specific assumptions unless they match this product.
- Prompt should describe exact visual composition
- Include product appearance (color, material, shape)
- Specify text overlays (headlines, key points)
- Text overlays must not include the brand name "{brand}" or any logo/wordmark.
- If a lifestyle image includes people, require complete full-body people with natural anatomy and no cropped body parts.
- Protect product fidelity: explicitly preserve the original product type, shape, color, dimensions, proportions, key parts, visible accessories, material, texture/finish, and distinctive construction details. Preserve the material shown in the selected references; do not change fabric/plastic/wood/metal/finish/texture/packaging. Avoid any prompt language that changes the product design.
- Choose 1-2 reference_images for each module from the Reference Image Candidates. Use two when the module needs separate identity/detail anchors; use one when the available material is limited or one strong reference is enough. Select them based on the module purpose: lifestyle modules need usage/context plus product-identity references, detail modules need material/feature close-ups plus product-identity references, spec modules need dimensions/scale plus product-identity references.
- Do not use the same two reference images for every module.
- In the prompt, include a short "Selected reference images" section that explains how each selected reference should be used.
- Generate exactly 5 scripts total for standard Amazon A+ content. Do not create 6 or 7 scripts.
- Every script must request an output size of exactly {output_width} x {output_height} pixels.
- Inherit each module's conversion_goal, buyer_objection, evidence_source, risk_guardrails, and visual_do_not_claim into the corresponding script.
- Inherit each module's experience_angle and gallery_overlap_avoidance into the corresponding script.
- The prompt must explicitly state the module conversion goal, buyer objection, evidence source, experience angle, gallery overlap avoidance, and risk guardrails.
- Make A+ images experience-led: show real usage, ownership feeling, room/context fit, comfort, setup ease, or emotional payoff before dry specs.
- Avoid repeating MAIN/gallery image information unless the A+ module adds deeper context, lifestyle understanding, or conversion emotion.
- Do not use A+ images to claim something missing from product facts or references. If Step 7 says evidence is limited, keep the visual conservative and explanatory.
- The prompt must make the generated A+ image express the selling point visible in the selected references, not a generic marketing scene.
- Except for scene, people, light, room styling, camera framing, and clean A+ graphic layout, keep the product appearance as close as possible to the selected product references.
- Do not add, remove, or alter product parts, proportions, accessories, mechanisms, labels, packaging, material texture, surface finish, safety features, age cues, or visible construction details unless they are present in the selected references/product facts.
- For child, baby, pet, medical, electrical, or safety-sensitive products, avoid unsupported certification, age, safety, health, durability, battery, waterproof, or performance claims; show only realistic compliant use supported by product facts and references.
- Preserve each plan module's publish_profile, lingxing_content_module_type, and semantic_role in the script JSON for traceability.
- Each prompt should be 100-300 words

Standard output size for this pipeline:
- Every A+ image: {output_width} x {output_height} px

Output JSON:
{{
  "scripts": [
    {{
      "module_position": 1,
      "publish_profile": "standard_header_image_text_v1",
      "lingxing_content_module_type": "STANDARD_HEADER_IMAGE_TEXT",
      "semantic_role": "hero",
      "prompt": "detailed image generation prompt...",
      "negative_prompt": "what to avoid...",
      "width": {output_width},
      "height": {output_height},
      "style": "photography|3d_render|infographic|lifestyle",
      "conversion_goal": "copied or sharpened from the A+ plan",
      "buyer_objection": "copied or sharpened from the A+ plan",
      "evidence_source": "facts/references this image is allowed to use",
      "experience_angle": "real-life scenario or ownership feeling this A+ image should create",
      "gallery_overlap_avoidance": "how this image avoids repeating MAIN/gallery content",
      "risk_guardrails": ["truthfulness and fidelity rules for this image"],
      "visual_do_not_claim": ["unsupported claims or elements to avoid"],
      "reference_images": [
        {{
          "label": "A",
          "slot": "01",
          "filename": "...",
          "path": "/absolute/path/to/reference.jpg",
          "use_for": "what this reference controls",
          "preserve": "what must be preserved from this image",
          "avoid_copying": "what should not be copied literally",
          "path_exists": true
        }}
      ],
      "text_overlays": [
        {{"text": "...", "position": "top-center", "font_size": "large"}}
      ]
    }}
  ],
  "summary": "brief description of the visual strategy"
}}"""

REGENERATE_SCRIPT_PROMPT = """Regenerate one A+ Content image generation script based on the user's feedback.

## Product
- Title: {title}
- Brand: {brand}
- Color: {color}
- Material: {material}
- Category: {category}

## Original A+ Module Plan
{module_plan_json}

## Current Script
{current_script_json}

## Feedback Diagnosis and Revision Plan
{diagnosis_json}

## Available Reference Image Candidates from Step6 Analysis
{reference_candidates_json}

## User Feedback / Reason To Regenerate
{reason}

## Requirements
- Regenerate ONLY module_position {module_position}.
- Before writing the script, use the user_feedback_analysis and diagnosis as a decision brief. Interpret what the user really wants, then generate a fresh, coherent script that fits the product, module plan, current result, and available references.
- Do not paste the analysis mechanically into the image prompt. Convert the useful parts into natural prompt changes, reference choices, negative constraints, and layout/color/product-fidelity instructions.
- Rewrite the script appropriately every time. If the feedback asks to change references, analyze the candidate references and update reference_images with a clear rationale. If the feedback asks to adjust script/color/shape/scene/text, rewrite the prompt and negative_prompt to make that change concrete.
- Treat concrete user feedback as acceptance criteria, but apply it in context: preserve the original module purpose unless the feedback intentionally changes it.
- Keep the image useful for the same A+ module purpose unless the feedback says otherwise.
- Follow the Feedback Diagnosis and Revision Plan as guidance. If it says to keep references, preserve them. If it says to add or reselect references, choose from the available candidates and update the prompt accordingly.
- Adapt the regenerated visual strategy to the actual product category and product facts. Do not reuse category-specific assumptions from another product type.
- On-image text must not include the brand name "{brand}" or any logo/wordmark.
- If a lifestyle image includes people, require complete full-body people with natural anatomy and no cropped body parts.
- Protect product fidelity: preserve the original product type, shape, color, dimensions, proportions, key parts, visible accessories, material, texture/finish, and distinctive construction details. Preserve the exact material shown in selected references and do not change fabric/plastic/wood/metal/finish/texture/packaging. Avoid any prompt language that changes the product design.
- Choose 1-2 reference_images for this module from the module purpose/current references and include them in the JSON. Do not duplicate weak references just to reach two.
- Output size must be exactly {output_width} x {output_height} pixels.
- Preserve or improve the module conversion strategy fields: conversion_goal, buyer_objection, evidence_source, risk_guardrails, and visual_do_not_claim.
- Preserve or improve the module experience fields: experience_angle and gallery_overlap_avoidance.
- Keep the image focused on the same buyer objection and supported evidence unless the user feedback explicitly changes the module strategy.
- Keep the regenerated image experience-led unless the user specifically asks for a spec/parameter image.
- Keep the regenerated script close to the selected references' visible selling points. Only change scene, people, light, room styling, camera framing, and A+ layout when useful.
- Do not add, remove, or alter product parts, proportions, accessories, mechanisms, labels, packaging, material texture, surface finish, safety features, age cues, or visible construction details unless they are present in the selected references/product facts.
- For child, baby, pet, medical, electrical, or safety-sensitive products, avoid unsupported certification, age, safety, health, durability, battery, waterproof, or performance claims; show only realistic compliant use supported by product facts and references.
- Include a concise negative_prompt that blocks brand text/logos, cropped people, deformed product, wrong color, wrong product type, wrong scale, altered proportions, changed reference material, invented accessories, invented product features, unsupported safety/age claims, and changed product construction.
- Add a "feedback_acceptance_checklist" array that rewrites the user's feedback into concrete visual requirements this new prompt satisfies.
- Add a "feedback_application_notes" string explaining exactly how the prompt changed to satisfy the feedback.
- Return valid JSON only.

Output JSON:
{{
  "module_position": {module_position},
  "prompt": "detailed image generation prompt...",
  "negative_prompt": "what to avoid...",
  "width": {output_width},
  "height": {output_height},
  "style": "photography|3d_render|infographic|lifestyle",
  "conversion_goal": "...",
  "buyer_objection": "...",
  "evidence_source": "...",
  "experience_angle": "...",
  "gallery_overlap_avoidance": "...",
  "risk_guardrails": [],
  "visual_do_not_claim": [],
  "feedback_acceptance_checklist": [],
  "feedback_application_notes": "...",
  "reference_images": [],
  "text_overlays": [
    {{"text": "...", "position": "top-center", "font_size": "large"}}
  ]
}}"""

REGENERATION_DIAGNOSIS_PROMPT = """Analyze why the current generated A+ image did not satisfy the user's feedback, then decide how to revise it.

Use the already-analyzed Step6 image data. Do not blindly keep or change references: decide from the feedback.

## Product
- Title: {title}
- Brand: {brand}
- Color: {color}
- Material: {material}
- Category: {category}

## Original A+ Module Plan
{module_plan_json}

## Current Script
{current_script_json}

## Current Generated Image Record
{current_generated_image_json}

## Current Reference Images
{current_references_json}

## Available Reference Image Candidates from Step6 Analysis
{reference_candidates_json}

## User Feedback
{reason}

First, analyze the user's words carefully, including Chinese feedback. Do not treat the feedback as a vague style hint. Convert it into edit intent, likely cause, reference-image implication, and practical script changes. Then classify the feedback and return a regeneration plan:
- If the user says to rewrite/change the script/prompt, script_rewrite_required must be true and the prompt_revision_plan must describe concrete script changes.
- If the user says the previous instruction was ignored, identify which instruction was ignored and make it an important acceptance criterion.
- If the user asks to change a generated image but may need a different reference image, decide whether current references can support the requested change.
- If this is only copy/layout/composition, keep current references unless a better support image is obvious.
- If product shape, color, material, scale, feature, or authenticity is wrong, choose stronger identity/detail references from the candidate list.
- If scene or selling point is wrong, keep an identity reference and add/select a candidate that supports the requested scenario or selling point.
- If the current references are weak, misleading, too generic, or do not support the module purpose, reselect references.
- Prefer 1-2 references total. Always include at least one product-identity reference when possible.

Output valid JSON only:
{{
  "user_feedback_analysis": {{
    "plain_language_intent": "what the user wants changed, in plain Chinese or English",
    "requested_actions": ["explicit actions requested by the user"],
    "target_objects": ["which image areas/modules/product parts/text/scenes the feedback refers to"],
    "rejected_elements": ["what must not appear again"],
    "preserve_elements": ["what must stay the same"],
    "change_elements": ["what must visibly change"],
    "acceptance_criteria": ["requirements derived from the user's words, applied in context"],
    "reference_selection_implication": "keep current references|add support reference|reselect references|unclear, with reason",
    "script_rewrite_required": true,
    "image_regeneration_required": true
  }},
  "issue_type": "composition|product_fidelity|scene_mismatch|selling_point_mismatch|text_overlay|reference_mismatch|style_tone|other",
  "root_cause": "short explanation",
  "reference_action": "keep|add|reselect",
  "selected_reference_paths": ["/absolute/path/from_candidates"],
  "avoid_reference_paths": ["/absolute/path/to_avoid"],
  "reference_rationale": "why these references fit the feedback and module",
  "prompt_revision_plan": ["specific prompt changes to make"],
  "composition_changes": ["specific visual/layout changes"],
  "fidelity_rules": ["what product details must be preserved"],
  "text_overlay_changes": ["text changes or placement changes"],
  "acceptance_checklist": ["concrete visual requirements that must be satisfied in the regenerated image"],
  "risk_notes": ["unsupported claims or visual risks to avoid"]
}}"""


def _sanitize_on_image_text(text: str | None, brand: str) -> str:
    if not text:
        return ""
    cleaned = str(text).replace(brand, "").strip()
    cleaned = " ".join(cleaned.split())
    return cleaned


def _load_reference_candidates(product: Product) -> list[dict]:
    pi = product.images
    if not pi or not pi.image_analysis:
        return []

    try:
        payload = json.loads(pi.image_analysis)
    except json.JSONDecodeError:
        return []

    if isinstance(payload, list):
        reviews = payload
        gallery_selection = []
    elif isinstance(payload, dict):
        reviews = payload.get("images") if isinstance(payload.get("images"), list) else []
        gallery_selection = payload.get("gallery_selection") if isinstance(payload.get("gallery_selection"), list) else []
    else:
        return []

    by_path = {}
    for review in reviews:
        if isinstance(review, dict) and review.get("path"):
            by_path[review["path"]] = review

    candidates: list[dict] = []
    seen: set[str] = set()
    by_candidate_path: dict[str, dict] = {}

    def add_candidate(path: str | None, source: dict | None = None, selected: dict | None = None) -> None:
        if not path:
            return
        if path in seen:
            existing = by_candidate_path.get(path)
            if existing and selected:
                for key, value in {
                    "slot": selected.get("slot"),
                    "conversion_role": selected.get("role") or selected.get("conversion_role"),
                    "filename": selected.get("filename"),
                }.items():
                    if value and not existing.get(key):
                        existing[key] = value
            return
        review = source or by_path.get(path) or {}
        selected = selected or {}
        mm = review.get("multimodal_result") if isinstance(review.get("multimodal_result"), dict) else {}
        candidate = {
            "image_id": review.get("image_id"),
            "slot": selected.get("slot") or review.get("slot"),
            "filename": selected.get("filename") or review.get("filename") or _reference_filename(path),
            "path": path,
            "image_type": review.get("image_type"),
            "conversion_role": selected.get("role") or selected.get("conversion_role") or review.get("conversion_role"),
            "visible_selling_point": review.get("visible_selling_point") or mm.get("primary_selling_point"),
            "material_texture": review.get("material_texture") or mm.get("material_texture"),
            "product_angle": review.get("product_angle") or mm.get("product_angle"),
            "scene_type": review.get("scene_type") or mm.get("scene_type"),
            "aplus_reference_value": review.get("aplus_reference_value") or mm.get("aplus_reference_value"),
        }
        candidates.append(candidate)
        seen.add(path)
        by_candidate_path[path] = candidate

    if pi.main_image_path:
        add_candidate(pi.main_image_path)

    for selected in gallery_selection:
        if isinstance(selected, dict):
            add_candidate(selected.get("path"), selected=selected)

    gallery_paths = []
    if pi.gallery_images:
        try:
            gallery_paths = json.loads(pi.gallery_images)
        except json.JSONDecodeError:
            gallery_paths = []
    if isinstance(gallery_paths, list):
        for item in gallery_paths:
            path = item if isinstance(item, str) else item.get("path") if isinstance(item, dict) else None
            add_candidate(path)

    for review in reviews:
        if isinstance(review, dict):
            add_candidate(review.get("path"), source=review)

    return candidates


def _reference_candidates_for_prompt(candidates: list[dict]) -> str:
    compact = [
        {
            "slot": item.get("slot"),
            "image_id": item.get("image_id"),
            "filename": item.get("filename"),
            "path": item.get("path"),
            "role": item.get("conversion_role"),
            "image_type": item.get("image_type"),
            "selling_point": item.get("visible_selling_point"),
            "material": item.get("material_texture"),
            "scene": item.get("scene_type"),
        }
        for item in candidates[:16]
    ]
    return json.dumps(compact, ensure_ascii=False, indent=2) if compact else "N/A"


def _combined_text(module: dict, script: dict) -> str:
    parts = []
    for obj in (module, script):
        for key in (
            "type",
            "headline",
            "subheading",
            "key_message",
            "image_concept",
            "image_style",
            "conversion_goal",
            "buyer_objection",
            "evidence_source",
            "experience_angle",
            "gallery_overlap_avoidance",
            "reference_strategy",
            "style",
            "prompt",
        ):
            value = obj.get(key) if isinstance(obj, dict) else None
            if isinstance(value, str):
                parts.append(value)
        roles = obj.get("preferred_reference_roles") if isinstance(obj, dict) else None
        if isinstance(roles, list):
            parts.extend(str(role) for role in roles)
        for key in ("risk_guardrails", "visual_do_not_claim"):
            values = obj.get(key) if isinstance(obj, dict) else None
            if isinstance(values, list):
                parts.extend(str(value) for value in values)
    return " ".join(parts).lower()


def _reference_intent_text(module: dict) -> str:
    parts = []
    if isinstance(module, dict):
        for key in (
            "type",
            "headline",
            "subheading",
            "key_message",
            "image_concept",
            "image_style",
            "conversion_goal",
            "buyer_objection",
            "evidence_source",
            "experience_angle",
            "gallery_overlap_avoidance",
            "reference_strategy",
        ):
            value = module.get(key)
            if isinstance(value, str):
                parts.append(value)
        roles = module.get("preferred_reference_roles")
        if isinstance(roles, list):
            parts.extend(str(role) for role in roles)
        for key in ("risk_guardrails", "visual_do_not_claim"):
            values = module.get(key)
            if isinstance(values, list):
                parts.extend(str(value) for value in values)
    return " ".join(parts).lower()


def _candidate_text(candidate: dict) -> str:
    return " ".join(str(candidate.get(key) or "") for key in (
        "slot",
        "filename",
        "image_type",
        "conversion_role",
        "visible_selling_point",
        "material_texture",
        "product_angle",
        "scene_type",
        "aplus_reference_value",
    )).lower()


def _explicit_reference_score(candidate: dict, module: dict) -> float:
    text = _reference_intent_text(module)
    if not text:
        return 0.0

    score = 0.0
    slot = str(candidate.get("slot") or "").strip().lower()
    image_id = str(candidate.get("image_id") or "").strip().lower()
    filename = str(candidate.get("filename") or "").strip().lower()
    stem = Path(filename).stem.lower() if filename else ""

    if slot:
        slot_plain = slot.lstrip("#")
        slot_num = slot_plain.zfill(2) if slot_plain.isdigit() else slot_plain
        slot_patterns = {
            f"slot {slot_plain}",
            f"slot {slot_num}",
            f"image slot {slot_plain}",
            f"image slot {slot_num}",
            f"reference from image slot {slot_plain}",
            f"reference from image slot {slot_num}",
        }
        if any(pattern in text for pattern in slot_patterns):
            score += 80

    if image_id:
        image_plain = image_id.lstrip("#")
        image_num = image_plain.zfill(2) if image_plain.isdigit() else image_plain
        image_patterns = {
            image_id,
            f"image {image_plain}",
            f"image {image_num}",
            f"#{image_num}",
        }
        if any(pattern in text for pattern in image_patterns):
            score += 70

    if filename and filename in text:
        score += 90
    elif stem and len(stem) >= 4 and stem in text:
        score += 90

    return score


def _score_reference_candidate(candidate: dict, module: dict, script: dict, position: int, index: int, main_path: str | None) -> float:
    explicit_score = _explicit_reference_score(candidate, module)
    module_text = _reference_intent_text(module) or _combined_text(module, script)
    candidate_text = _candidate_text(candidate)
    path = candidate.get("path")
    score = 1.0 + explicit_score + ((position + index) % 7) * 0.01

    is_main = bool(main_path and path == main_path)
    if is_main or "main" in candidate_text or "identity" in candidate_text or "hero" in candidate_text:
        score += 5.5 if explicit_score else 3.0

    material_intent = any(word in module_text for word in (
        "material close-up", "material close up", "fabric close-up", "fabric close up",
        "texture close-up", "texture close up", "detail close-up", "detail close up",
        "surface detail", "finish detail", "packaging detail", "detail module",
        "quadrant feature", "feature layout",
    ))
    if material_intent:
        if any(word in candidate_text for word in ("material", "fabric", "texture", "surface", "finish", "plastic", "wood", "metal", "packaging", "close-up", "close up", "detail", "swatch")):
            score += 10

    if any(word in module_text for word in ("dimension", "size", "spec", "measurement", "width", "depth", "height", "scale")):
        if any(word in candidate_text for word in ("dimension", "size", "spec", "measurement", "scale")):
            score += 10

    if any(word in module_text for word in ("lifestyle", "usage", "use case", "in use", "scene", "context", "home", "room", "outdoor", "play", "child", "kid", "family", "installation", "assembly")):
        if any(word in candidate_text for word in ("lifestyle", "usage", "use", "scene", "context", "home", "room", "outdoor", "play", "child", "kid", "family", "installation", "assembly")):
            score += 10

    if any(word in module_text for word in ("feature", "function", "benefit", "comfort", "support", "foam", "cushion", "rebound", "relax", "seating", "storage", "fold", "adjust", "light", "sound", "wheel", "ride", "remote", "control", "battery")):
        if any(word in candidate_text for word in ("feature", "function", "benefit", "comfort", "support", "foam", "cushion", "fill", "detail", "hands", "storage", "fold", "adjust", "light", "sound", "wheel", "ride", "remote", "control", "battery")):
            score += 8

    if any(word in module_text for word in ("safety", "age", "kid", "child", "children", "toddler", "certification", "stable", "non-toxic")):
        if any(word in candidate_text for word in ("safety", "age", "kid", "child", "children", "toddler", "certification", "stable", "non-toxic")):
            score += 8

    if any(word in module_text for word in ("comparison", "chart", "compare")):
        if any(word in candidate_text for word in ("dimension", "spec", "comparison", "front", "identity")):
            score += 7

    if any(word in module_text for word in ("back", "rear", "finished", "side", "front", "angle", "top", "bottom")):
        if any(word in candidate_text for word in ("back", "rear", "finished", "side", "front", "angle", "top", "bottom")):
            score += 9

    return score


def _reference_use_for(candidate: dict, module: dict, script: dict) -> str:
    text = _combined_text(module, script)
    candidate_text = _candidate_text(candidate)
    if any(word in text for word in ("dimension", "size", "spec", "measurement")) and any(word in candidate_text for word in ("dimension", "size", "spec", "measurement")):
        return "Use for accurate scale, measurements, and layout proportions."
    if any(word in candidate_text for word in ("material", "fabric", "texture", "surface", "finish", "plastic", "wood", "metal", "packaging", "close-up", "detail")):
        return "Use for exact material, surface texture, finish, detail quality, packaging, and visible construction."
    if any(word in candidate_text for word in ("lifestyle", "usage", "scene", "context", "home", "room", "outdoor", "play", "child", "kid", "family", "installation", "assembly")):
        return "Use for usage context, realistic scale, styling direction, and atmosphere."
    return "Use for product identity, silhouette, shape, color, proportions, key parts, accessories, and distinctive construction."


def _reference_visible_selling_point(candidate: dict) -> str:
    selling_point = candidate.get("visible_selling_point") or candidate.get("aplus_reference_value")
    if selling_point:
        return str(selling_point)
    return "the visible product selling point shown in this reference"


def _format_reference(candidate: dict, label: str, module: dict, script: dict) -> dict:
    path = candidate.get("path") or ""
    return {
        "label": label,
        "slot": candidate.get("slot"),
        "image_id": candidate.get("image_id"),
        "filename": candidate.get("filename") or _reference_filename(path),
        "path": path,
        "use_for": _reference_use_for(candidate, module, script),
        "visible_selling_point": _reference_visible_selling_point(candidate),
        "preserve": "Preserve the visible selling point, product type, material, texture, color, silhouette, proportions, key parts, accessories, packaging, surface finish, and distinctive construction shown in this reference.",
        "avoid_copying": "Do not copy supplier text overlays, logos, watermarks, exact infographic layout, or unsupported props/claims. Do not invent new accessories, mechanisms, construction details, or product features that are not visible here.",
        "path_exists": _is_remote_url(path) or (Path(path).is_file() if path else False),
    }


def _strip_previous_regeneration_sections(prompt: str | None) -> str:
    """Remove old regeneration audit blocks before asking the LLM for a fresh rewrite."""
    if not prompt:
        return ""
    cleaned = str(prompt)
    leading_markers = (
        "USER FEEDBACK DECISION BRIEF:",
        "MANDATORY USER FEEDBACK REQUIREMENTS:",
    )
    if cleaned.lstrip().startswith(leading_markers):
        lines = cleaned.splitlines()
        end_index = None
        for index, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("Use this brief to rewrite") or stripped.startswith("The final generated image must visibly satisfy"):
                end_index = index + 1
                break
        if end_index is not None:
            while end_index < len(lines) and not lines[end_index].strip():
                end_index += 1
            cleaned = "\n".join(lines[end_index:]).strip()

    trailing_markers = (
        "Regeneration diagnosis and revision plan:",
        "Selected reference images:",
    )
    while True:
        positions = [cleaned.find(marker) for marker in trailing_markers if cleaned.find(marker) >= 0]
        if not positions:
            break
        cleaned = cleaned[:min(positions)].rstrip()
    return cleaned.strip()


def _clean_script_for_regeneration(script: dict) -> dict:
    """Keep useful module fields, but remove previous regen-specific baggage."""
    cleaned = {
        key: value
        for key, value in script.items()
        if key not in {
            "regenerate_reason",
            "regeneration_diagnosis",
            "regenerated_at",
            "feedback_acceptance_checklist",
            "feedback_application_notes",
            "user_feedback_analysis",
        }
    }
    cleaned["prompt"] = _strip_previous_regeneration_sections(script.get("prompt"))
    return cleaned


def _list_value(value) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if item]
    if value:
        return [str(value)]
    return []


def _module_strategy(module: dict, script: dict | None = None) -> dict:
    script = script or {}
    conversion_goal = script.get("conversion_goal") or module.get("conversion_goal") or module.get("key_message") or module.get("headline") or ""
    buyer_objection = script.get("buyer_objection") or module.get("buyer_objection") or ""
    evidence_source = script.get("evidence_source") or module.get("evidence_source") or module.get("reference_strategy") or ""
    experience_angle = script.get("experience_angle") or module.get("experience_angle") or module.get("image_concept") or ""
    gallery_overlap_avoidance = script.get("gallery_overlap_avoidance") or module.get("gallery_overlap_avoidance") or ""
    risk_guardrails = _list_value(script.get("risk_guardrails")) or _list_value(module.get("risk_guardrails"))
    visual_do_not_claim = _list_value(script.get("visual_do_not_claim")) or _list_value(module.get("visual_do_not_claim"))
    return {
        "conversion_goal": conversion_goal,
        "buyer_objection": buyer_objection,
        "evidence_source": evidence_source,
        "experience_angle": experience_angle,
        "gallery_overlap_avoidance": gallery_overlap_avoidance,
        "risk_guardrails": risk_guardrails,
        "visual_do_not_claim": visual_do_not_claim,
    }


def _attach_module_strategy_section(script: dict, module: dict) -> None:
    strategy = _module_strategy(module, script)
    script.update(strategy)
    _inherit_publish_contract(script, module)

    lines = [
        "Module conversion strategy:",
        f"- Conversion goal: {strategy.get('conversion_goal') or 'Keep the product value clear and truthful.'}",
        f"- Buyer objection: {strategy.get('buyer_objection') or 'Reduce the main buyer doubt for this module.'}",
        f"- Evidence source: {strategy.get('evidence_source') or 'Use only product facts and selected reference images.'}",
        f"- Experience angle: {strategy.get('experience_angle') or 'Show a realistic ownership or usage experience.'}",
        f"- Avoid gallery overlap: {strategy.get('gallery_overlap_avoidance') or 'Do not repeat MAIN/gallery specs unless adding deeper usage context.'}",
    ]
    if strategy.get("risk_guardrails"):
        lines.append("- Risk guardrails: " + "; ".join(strategy["risk_guardrails"]))
    if strategy.get("visual_do_not_claim"):
        lines.append("- Do not claim or show: " + "; ".join(strategy["visual_do_not_claim"]))
    lines.append("The image should feel like an experience page, not a parameter sheet. Keep on-image copy short, benefit-led, and non-misleading.")

    section = "\n".join(lines)
    prompt = script.get("prompt") or ""
    if "Module conversion strategy:" not in prompt:
        script["prompt"] = f"{prompt.rstrip()}\n\n{section}".strip()


def _inherit_publish_contract(script: dict, module: dict) -> None:
    script["publish_profile"] = module.get("publish_profile") or APLUS_PUBLISH_PROFILE_STANDARD_HEADER_IMAGE_TEXT_V1
    script["lingxing_content_module_type"] = module.get("lingxing_content_module_type") or LINGXING_STANDARD_HEADER_IMAGE_TEXT
    if module.get("semantic_role"):
        script["semantic_role"] = module.get("semantic_role")


def _select_references_for_script(
    candidates: list[dict],
    module: dict,
    script: dict,
    position: int,
    main_path: str | None,
    used_pairs: set[tuple[str, ...]] | None = None,
) -> list[dict]:
    if not candidates:
        return []

    scored = sorted(
        enumerate(candidates),
        key=lambda pair: _score_reference_candidate(pair[1], module, script, position, pair[0], main_path),
        reverse=True,
    )

    selected: list[dict] = []
    seen: set[str] = set()
    for _, candidate in scored:
        path = candidate.get("path")
        if not path or path in seen:
            continue
        selected.append(candidate)
        seen.add(path)
        if len(selected) == 2:
            break

    if len(selected) < 2:
        start = max(position - 1, 0) * 2
        for offset in range(len(candidates)):
            candidate = candidates[(start + offset) % len(candidates)]
            path = candidate.get("path")
            if path and path not in seen:
                selected.append(candidate)
                seen.add(path)
            if len(selected) == 2:
                break

    if used_pairs and len(selected) == 2:
        pair_key = tuple(sorted(str(item.get("path")) for item in selected if item.get("path")))
        if pair_key in used_pairs and len(candidates) > 2:
            selected_paths = {item.get("path") for item in selected}
            for _, alternate in scored:
                alternate_path = alternate.get("path")
                if not alternate_path or alternate_path in selected_paths:
                    continue
                candidate_pair = [selected[0], alternate]
                alternate_key = tuple(sorted(str(item.get("path")) for item in candidate_pair if item.get("path")))
                if alternate_key not in used_pairs:
                    selected = candidate_pair
                    break

    return [_format_reference(candidate, chr(65 + index), module, script) for index, candidate in enumerate(selected[:2])]


def _select_references_for_regeneration(
    candidates: list[dict],
    module: dict,
    script: dict,
    position: int,
    main_path: str | None,
    diagnosis: dict | None,
) -> list[dict]:
    diagnosis = diagnosis or {}
    by_path = {str(candidate.get("path")): candidate for candidate in candidates if candidate.get("path")}
    selected: list[dict] = []
    seen: set[str] = set()

    def add_path(path: str | None) -> None:
        if not path or path in seen:
            return
        candidate = by_path.get(path)
        if candidate:
            selected.append(candidate)
            seen.add(path)

    action = str(diagnosis.get("reference_action") or "").lower()
    selected_paths = diagnosis.get("selected_reference_paths") if isinstance(diagnosis.get("selected_reference_paths"), list) else []
    avoid_paths = {
        str(path)
        for path in (diagnosis.get("avoid_reference_paths") if isinstance(diagnosis.get("avoid_reference_paths"), list) else [])
        if path
    }

    if action == "keep":
        for ref in script.get("reference_images") or []:
            add_path(ref if isinstance(ref, str) else ref.get("path") if isinstance(ref, dict) else None)

    for path in selected_paths:
        add_path(str(path) if path else None)
        if len(selected) >= 2:
            break

    diagnosis_text_all = json.dumps(diagnosis, ensure_ascii=False).lower()
    honor_single_reference = (
        action == "reselect"
        and len(selected) == 1
        and (
            len(selected_paths) == 1
            or "single" in diagnosis_text_all
            or "only" in diagnosis_text_all
            or "唯一" in diagnosis_text_all
            or "单一" in diagnosis_text_all
            or "不再使用" in diagnosis_text_all
            or "避免" in diagnosis_text_all
        )
    )
    if honor_single_reference:
        return [_format_reference(selected[0], "A", module, script)]

    if action in {"add", "reselect"} and not any(main_path and item.get("path") == main_path for item in selected):
        add_path(main_path)

    if len(selected) < 2:
        diagnosis_text = {
            "issue_type": diagnosis.get("issue_type"),
            "root_cause": diagnosis.get("root_cause"),
            "reference_rationale": diagnosis.get("reference_rationale"),
            "prompt_revision_plan": diagnosis.get("prompt_revision_plan"),
            "composition_changes": diagnosis.get("composition_changes"),
            "fidelity_rules": diagnosis.get("fidelity_rules"),
        }
        scored = sorted(
            enumerate(candidates),
            key=lambda pair: _score_reference_candidate(
                pair[1],
                {**module, "reference_strategy": json.dumps(diagnosis_text, ensure_ascii=False)},
                script,
                position,
                pair[0],
                main_path,
            ),
            reverse=True,
        )
        for _, candidate in scored:
            path = candidate.get("path")
            if not path or path in seen or (action == "reselect" and path in avoid_paths):
                continue
            selected.append(candidate)
            seen.add(path)
            if len(selected) >= 2:
                break

    if not selected:
        return _select_references_for_script(candidates, module, script, position, main_path)
    return [_format_reference(candidate, chr(65 + index), module, script) for index, candidate in enumerate(selected[:2])]


def _append_reference_section(script: dict, refs: list[dict], brand: str) -> None:
    script["reference_images"] = refs
    if not refs:
        return

    script["reference_guidance"] = {
        "selected_reference_files": [ref.get("filename") for ref in refs if ref.get("filename")],
        "material_fidelity_rule": "Preserve the exact material, texture, surface finish, color, and visible construction shown in the selected references.",
        "product_change_rule": "Only scene, layout, lighting, framing, styling, and text placement may change; do not redesign the product itself.",
        "brand_text_rule": f"Do not render the brand name '{brand}' or any logo/wordmark as on-image text.",
    }


def _append_regeneration_diagnosis_section(script: dict, diagnosis: dict | None) -> None:
    if not diagnosis:
        return
    feedback_analysis = diagnosis.get("user_feedback_analysis") if isinstance(diagnosis.get("user_feedback_analysis"), dict) else {}
    script["regeneration_decision_summary"] = {
        "feedback_intent": feedback_analysis.get("plain_language_intent") or diagnosis.get("user_feedback"),
        "issue_type": diagnosis.get("issue_type") or "other",
        "root_cause": diagnosis.get("root_cause"),
        "reference_action": diagnosis.get("reference_action"),
        "reference_rationale": diagnosis.get("reference_rationale"),
        "requested_actions": feedback_analysis.get("requested_actions"),
        "acceptance_criteria": feedback_analysis.get("acceptance_criteria") or diagnosis.get("acceptance_checklist"),
    }


def _prepend_feedback_requirements(script: dict, reason: str, diagnosis: dict | None) -> None:
    diagnosis = diagnosis or {}
    feedback_analysis = diagnosis.get("user_feedback_analysis") if isinstance(diagnosis.get("user_feedback_analysis"), dict) else {}
    checklist = diagnosis.get("acceptance_checklist")
    if not isinstance(checklist, list) or not checklist:
        checklist = [reason.strip()]
    for key in ("acceptance_criteria", "requested_actions", "change_elements"):
        values = feedback_analysis.get(key)
        if isinstance(values, list):
            checklist.extend(str(item).strip() for item in values if str(item).strip())
    checklist = [str(item).strip() for item in checklist if str(item).strip()]
    checklist = list(dict.fromkeys(checklist))
    script["feedback_acceptance_checklist"] = checklist
    script["user_feedback_analysis"] = feedback_analysis
    script["feedback_application_notes"] = (
        f"Feedback intent analyzed first: {feedback_analysis.get('plain_language_intent')}. "
        "The prompt was then rewritten in context, with reference choices and visual instructions adjusted where useful."
        if feedback_analysis.get("plain_language_intent")
        else script.get("feedback_application_notes") or "The regenerated prompt was revised to directly satisfy the user's feedback and the diagnosis checklist."
    )


def _attach_reference_images(scripts_data: dict, product: Product, plan: dict, brand: str) -> dict:
    scripts = scripts_data.get("scripts", [])
    if not isinstance(scripts, list):
        return scripts_data

    candidates = _load_reference_candidates(product)
    modules = plan.get("modules", []) if isinstance(plan, dict) else []
    used_pairs: set[tuple[str, ...]] = set()

    for index, script in enumerate(scripts):
        if not isinstance(script, dict):
            continue
        position = int(script.get("module_position") or index + 1)
        module = next(
            (
                item for item in modules
                if isinstance(item, dict) and (item.get("position") == position or item.get("module_position") == position)
            ),
            {},
        )
        refs = _select_references_for_script(
            candidates,
            module,
            script,
            position,
            product.images.main_image_path if product.images else None,
            used_pairs,
        )
        _attach_module_strategy_section(script, module)
        _append_reference_section(script, refs, brand)
        pair_key = tuple(sorted(str(ref.get("path")) for ref in refs if ref.get("path")))
        if pair_key:
            used_pairs.add(pair_key)

    return scripts_data


def _sanitize_scripts(scripts_data: dict, brand: str) -> dict:
    scripts = scripts_data.get("scripts", [])
    if not isinstance(scripts, list):
        scripts_data["scripts"] = []
        return scripts_data

    for script in scripts:
        overlays = script.get("text_overlays")
        if isinstance(overlays, list):
            for overlay in overlays:
                if isinstance(overlay, dict):
                    text = _sanitize_on_image_text(overlay.get("text"), brand)
                    words = text.split()
                    if len(words) > 8:
                        text = " ".join(words[:8])
                    overlay["text"] = text

        negative = script.get("negative_prompt") or ""
        required_negative = (
            "brand name text, brand logo, wordmark, cropped people, partial body, "
            "cut off head, cut off hands, cut off feet, distorted anatomy, "
            "deformed product, wrong product type, wrong color, wrong scale, "
            "distorted product proportions, altered key parts, changed texture, "
            "changed reference material, changed surface finish, changed packaging, "
            "invented accessories, invented product features, unsupported safety claims, "
            "unsupported age claims, changed product construction, added parts not in references, "
            "removed parts from references"
        )
        if required_negative.lower() not in negative.lower():
            script["negative_prompt"] = f"{negative.rstrip()}, {required_negative}".strip(", ")

        prompt = script.get("prompt") or ""
        if prompt and "On-image text must not include the brand name" not in prompt:
            script["prompt"] = (
                f"{prompt}\n\nOn-image text must not include the brand name '{brand}' or any logo/wordmark. "
                "If people appear in the scene, show complete full-body people with natural anatomy and no cropped body parts. "
                "Preserve the original product type, shape, color, dimensions, proportions, key parts, visible accessories, material, texture/finish, packaging, and distinctive construction details as much as possible. "
                "Preserve the exact material/surface finish shown in the selected reference images; do not change the product material or visible design. "
                "Make the image express the selected references' visible selling points. Apart from scene, people, lighting, camera framing, styling, and A+ layout, keep the product itself as close as possible to the selected references and do not invent accessories, features, safety claims, age claims, or construction details."
            )

        strategy = _module_strategy({}, script)
        if strategy.get("visual_do_not_claim") and "Do not claim or show:" not in script.get("prompt", ""):
            script["prompt"] = (
                f"{script.get('prompt', '').rstrip()}\n\nDo not claim or show: "
                f"{'; '.join(strategy['visual_do_not_claim'])}"
            ).strip()

    return scripts_data


def _normalize_script_count_and_size(scripts_data: dict) -> dict:
    scripts = scripts_data.get("scripts", [])
    if not isinstance(scripts, list):
        scripts_data["scripts"] = []
        return scripts_data

    if len(scripts) < 5:
        raise RuntimeError(f"A+脚本数量不足: {len(scripts)}/5")
    if len(scripts) > 5:
        logger.info(f"[Step8] A+脚本返回 {len(scripts)} 张，普通A+仅保留前5张")
        scripts = scripts[:5]

    for idx, script in enumerate(scripts, 1):
        if not isinstance(script, dict):
            continue
        script["module_position"] = idx
        script["width"] = settings.APLUS_IMAGE_WIDTH
        script["height"] = settings.APLUS_IMAGE_HEIGHT
        prompt = script.get("prompt") or ""
        size_rule = f"Output size requirement: exactly {settings.APLUS_IMAGE_WIDTH} x {settings.APLUS_IMAGE_HEIGHT} pixels."
        if prompt and size_rule not in prompt:
            script["prompt"] = f"{prompt.rstrip()}\n\n{size_rule}"

    scripts_data["scripts"] = scripts
    return scripts_data


def _plan_publish_profile(plan: dict | None) -> str:
    if not isinstance(plan, dict):
        return APLUS_PUBLISH_PROFILE_STANDARD_HEADER_IMAGE_TEXT_V1
    for value in (
        plan.get("publish_profile"),
        plan.get("aplus_plan_version"),
        plan.get("profile"),
    ):
        if str(value or "").strip() == APLUS_PUBLISH_PROFILE_ENHANCED_BASIC_APLUS_V1:
            return APLUS_PUBLISH_PROFILE_ENHANCED_BASIC_APLUS_V1
    modules = plan.get("modules")
    if isinstance(modules, list):
        for module in modules:
            if (
                isinstance(module, dict)
                and str(module.get("publish_profile") or "").strip() == APLUS_PUBLISH_PROFILE_ENHANCED_BASIC_APLUS_V1
            ):
                return APLUS_PUBLISH_PROFILE_ENHANCED_BASIC_APLUS_V1
    return APLUS_PUBLISH_PROFILE_STANDARD_HEADER_IMAGE_TEXT_V1


def _modules_by_position(plan: dict | None) -> dict[int, dict]:
    modules = plan.get("modules") if isinstance(plan, dict) else []
    if not isinstance(modules, list):
        return {}
    result: dict[int, dict] = {}
    for index, module in enumerate(modules, 1):
        if not isinstance(module, dict):
            continue
        try:
            position = int(module.get("position") or module.get("module_position") or index)
        except (TypeError, ValueError):
            position = index
        result[position] = module
    return result


def _scripts_by_position(scripts_data: dict) -> dict[int, dict]:
    scripts = scripts_data.get("scripts") if isinstance(scripts_data, dict) else []
    if not isinstance(scripts, list):
        return {}
    result: dict[int, dict] = {}
    for index, script in enumerate(scripts, 1):
        if not isinstance(script, dict):
            continue
        try:
            position = int(script.get("module_position") or script.get("position") or index)
        except (TypeError, ValueError):
            position = index
        result[position] = script
    return result


def _strip_global_size_assumptions(prompt: str | None) -> str:
    cleaned = str(prompt or "").strip()
    if not cleaned:
        return ""
    width = re.escape(str(settings.APLUS_IMAGE_WIDTH))
    height = re.escape(str(settings.APLUS_IMAGE_HEIGHT))
    cleaned = re.sub(
        rf"Output size requirement:\s*exactly\s*{width}\s*x\s*{height}\s*pixels\.?",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(rf"\b{width}\s*x\s*{height}\b", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _payload_slot(payload_path: tuple[str, ...] | list[str] | tuple[object, ...]) -> str:
    return ".".join(str(part) for part in payload_path)


def _asset_slot_id(position: int, slot_id: str) -> str:
    return f"m{position}_{slot_id.replace('.', '_')}"


def _slot_business_context(module: dict, slot_id: str) -> str:
    context: list[str] = []
    if module.get("headline"):
        context.append(f"Module headline: {module.get('headline')}")
    for key in ("image_concept", "conversion_goal", "buyer_objection", "evidence_source", "experience_angle"):
        if module.get(key):
            context.append(f"{key}: {module.get(key)}")

    if slot_id.startswith("feature_") and isinstance(module.get("features"), list):
        feature_key = slot_id.split(".", 1)[0]
        feature = next(
            (item for item in module["features"] if isinstance(item, dict) and item.get("slot") == feature_key),
            None,
        )
        if feature:
            context.append(f"Feature slot content: {json.dumps(feature, ensure_ascii=False)}")
    elif slot_id.startswith("comparison.") and isinstance(module.get("product_columns"), list):
        column_index = "1" if "column_1" in slot_id else "2" if "column_2" in slot_id else ""
        try:
            column = module["product_columns"][int(column_index) - 1] if column_index else None
        except (TypeError, ValueError, IndexError):
            column = None
        if isinstance(column, dict):
            safe_column = {
                key: value
                for key, value in column.items()
                if key in {"column_key", "asin", "title", "image_source", "alt_text_seed"}
            }
            context.append(f"Comparison column content: {json.dumps(safe_column, ensure_ascii=False)}")

    return "\n".join(str(item) for item in context if item)


def _enhanced_slot_prompt(base_prompt: str, module: dict, slot_id: str, payload_slot: str, width: int, height: int) -> str:
    cleaned = _strip_global_size_assumptions(base_prompt)
    if not cleaned:
        cleaned = (
            module.get("image_concept")
            or module.get("conversion_goal")
            or module.get("headline")
            or "Create a focused Amazon A+ module asset using only supported product facts and selected references."
        )
    context = _slot_business_context(module, slot_id)
    parts = [
        cleaned,
        context,
        (
            f"Generate the image asset for A+ slot '{slot_id}' at payload path '{payload_slot}'. "
            f"Output size requirement: exactly {width} x {height} pixels. "
            "Use this slot's module role and factual content only; do not create assets for other slots in the module."
        ),
    ]
    return "\n\n".join(part.strip() for part in parts if str(part).strip())


def _normalize_enhanced_scripts_for_plan(scripts_data: dict, plan: dict) -> dict:
    contract = producer_contract_for_profile(APLUS_PUBLISH_PROFILE_ENHANCED_BASIC_APLUS_V1)
    if contract is None:
        raise RuntimeError("Enhanced basic A+ producer contract is not registered")

    raw_by_position = _scripts_by_position(scripts_data)
    module_by_position = _modules_by_position(plan)
    slots_by_position: dict[int, list] = {}
    for slot_spec in required_image_slots(contract.profile_key):
        slots_by_position.setdefault(slot_spec.position, []).append(slot_spec)

    fixed_keys = {
        "position",
        "module_position",
        "publish_profile",
        "profile_version",
        "type",
        "internal_type",
        "semantic_role",
        "module_spec_key",
        "lingxing_content_module_type",
        "payload_key",
        "image_slots",
        "width",
        "height",
    }

    normalized_scripts: list[dict] = []
    for module_contract in contract.modules:
        raw = raw_by_position.get(module_contract.position, {})
        module = module_by_position.get(module_contract.position, {})
        script = {key: value for key, value in raw.items() if key not in fixed_keys}
        script.update(
            {
                "module_position": module_contract.position,
                "publish_profile": contract.profile_key,
                "profile_version": contract.profile_version,
                "type": module_contract.internal_type,
                "internal_type": module_contract.internal_type,
                "semantic_role": module_contract.semantic_role,
                "module_spec_key": module_contract.module_spec_key,
                "lingxing_content_module_type": module_contract.lingxing_content_module_type,
                "payload_key": module_contract.payload_key,
            }
        )
        if module.get("headline") and not script.get("headline"):
            script["headline"] = module.get("headline")
        if module.get("alt_text_seed") and not script.get("alt_text"):
            script["alt_text"] = module.get("alt_text_seed")

        module_slots: list[dict] = []
        contract_slot_ids = set(module_contract.required_image_slots)
        for slot_spec in slots_by_position.get(module_contract.position, []):
            if slot_spec.slot.slot_id not in contract_slot_ids:
                continue
            payload_slot = _payload_slot(slot_spec.slot.payload_path)
            target_width = slot_spec.slot.crop_width
            target_height = slot_spec.slot.crop_height
            module_slots.append(
                {
                    "asset_slot_id": _asset_slot_id(module_contract.position, slot_spec.slot.slot_id),
                    "slot_id": slot_spec.slot.slot_id,
                    "payload_slot": payload_slot,
                    "payload_path": list(slot_spec.slot.payload_path),
                    "publish_profile": contract.profile_key,
                    "profile_version": contract.profile_version,
                    "module_position": module_contract.position,
                    "semantic_role": module_contract.semantic_role,
                    "module_spec_key": module_contract.module_spec_key,
                    "lingxing_content_module_type": module_contract.lingxing_content_module_type,
                    "target_width": target_width,
                    "target_height": target_height,
                    "min_width": slot_spec.slot.min_width,
                    "min_height": slot_spec.slot.min_height,
                    "prompt": _enhanced_slot_prompt(
                        raw.get("prompt") or script.get("prompt") or "",
                        module,
                        slot_spec.slot.slot_id,
                        payload_slot,
                        target_width,
                        target_height,
                    ),
                    "negative_prompt": raw.get("negative_prompt") or script.get("negative_prompt"),
                    "style": raw.get("style") or script.get("style") or "photography",
                    "alt_text": module.get("alt_text_seed") or script.get("alt_text"),
                }
            )
        script["image_slots"] = module_slots
        if script.get("prompt"):
            script["prompt"] = _strip_global_size_assumptions(script.get("prompt"))
        normalized_scripts.append(script)

    return {
        **{key: value for key, value in scripts_data.items() if key != "scripts"},
        "aplus_plan_version": plan.get("aplus_plan_version") or contract.profile_key,
        "publish_profile": contract.profile_key,
        "profile_version": contract.profile_version,
        "module_contract_source": "module_registry.producer_contract_for_profile",
        "scripts": normalized_scripts,
    }


def normalize_aplus_scripts_for_plan(scripts_data: dict, plan: dict) -> dict:
    if not isinstance(scripts_data, dict):
        scripts_data = {"scripts": []}
    if _plan_publish_profile(plan) == APLUS_PUBLISH_PROFILE_ENHANCED_BASIC_APLUS_V1:
        return _normalize_enhanced_scripts_for_plan(scripts_data, plan)

    normalized = _normalize_script_count_and_size(scripts_data)
    for script in normalized.get("scripts", []):
        if not isinstance(script, dict):
            continue
        script["publish_profile"] = APLUS_PUBLISH_PROFILE_STANDARD_HEADER_IMAGE_TEXT_V1
        script["lingxing_content_module_type"] = LINGXING_STANDARD_HEADER_IMAGE_TEXT
    return normalized


def _fallback_aplus_scripts(plan: dict, product: Product, pd: ProductData) -> dict:
    modules = plan.get("modules") if isinstance(plan.get("modules"), list) else []
    title = pd.listing_title or pd.title or "Product"
    category = pd.leaf_category or "General"
    color = pd.color or "the original product color"
    material = pd.material or "the visible original material"
    scripts: list[dict] = []
    for idx in range(1, 6):
        module = modules[idx - 1] if idx - 1 < len(modules) and isinstance(modules[idx - 1], dict) else {}
        headline = module.get("headline") or module.get("type") or f"A+ Module {idx}"
        key_message = module.get("key_message") or module.get("conversion_goal") or "Explain a visible product benefit using selected reference images."
        image_concept = module.get("image_concept") or module.get("experience_angle") or "Create a clean Amazon A+ product image using selected references."
        scripts.append(
            {
                "module_position": idx,
                "publish_profile": module.get("publish_profile") or APLUS_PUBLISH_PROFILE_STANDARD_HEADER_IMAGE_TEXT_V1,
                "lingxing_content_module_type": module.get("lingxing_content_module_type") or LINGXING_STANDARD_HEADER_IMAGE_TEXT,
                "semantic_role": module.get("semantic_role"),
                "fallback_script": True,
                "prompt": (
                    f"Create Amazon A+ module {idx} for {title}. Module headline: {headline}. "
                    f"Product category: {category}. Preserve the product as shown in the selected reference images: "
                    f"same product type, shape, proportions, key parts, {color}, {material}, surface finish, and visible construction. "
                    f"Visual concept: {image_concept}. Conversion message: {key_message}. "
                    "Use a professional ecommerce composition with clean lighting, clear product visibility, and restrained on-image text. "
                    "Do not invent unsupported features, accessories, certifications, safety claims, age claims, or performance claims. "
                    f"Output size requirement: exactly {settings.APLUS_IMAGE_WIDTH} x {settings.APLUS_IMAGE_HEIGHT} pixels."
                ),
                "negative_prompt": (
                    "brand name text, brand logo, wordmark, cropped people, deformed product, wrong product type, wrong color, "
                    "wrong scale, altered proportions, changed material, invented accessories, invented product features, "
                    "unsupported safety claims, unsupported age claims, changed construction"
                ),
                "width": settings.APLUS_IMAGE_WIDTH,
                "height": settings.APLUS_IMAGE_HEIGHT,
                "style": "photography" if idx in (1, 2, 5) else "infographic",
                "conversion_goal": module.get("conversion_goal") or key_message,
                "buyer_objection": module.get("buyer_objection") or "Help shoppers understand the product clearly before purchase.",
                "evidence_source": module.get("evidence_source") or "Use only product facts and selected reference images.",
                "experience_angle": module.get("experience_angle") or image_concept,
                "gallery_overlap_avoidance": module.get("gallery_overlap_avoidance") or "Add context and clarity beyond the gallery images.",
                "risk_guardrails": module.get("risk_guardrails") or [
                    "Keep claims truthful and supported by product facts or visible reference images.",
                    "Preserve product identity, color, material, scale, proportions, and visible construction.",
                ],
                "visual_do_not_claim": module.get("visual_do_not_claim") or [
                    "Do not show unsupported accessories, functions, certifications, safety claims, or material changes.",
                ],
                "text_overlays": [
                    {"text": str(headline)[:48], "position": "top-center", "font_size": "large"},
                ],
            }
        )
    scripts_data = {
        "scripts": scripts,
        "summary": "A+脚本由保底逻辑生成：LLM连接超时，已按A+规划生成可继续出图的结构化脚本；如需更高质量，可重跑A+脚本。",
        "fallback": True,
        "fallback_reason": "LLM timeout while generating A+ scripts",
        "llm_model": settings.LLM_MODEL,
    }
    return normalize_aplus_scripts_for_plan(scripts_data, plan)


async def run_aplus_script(product_id: int) -> dict:
    """
    执行 A+ 脚本生成
    
    读取 A+ 规划，为每个模块生成出图 prompt
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
        pa = product.aplus
        if not pa or not pa.aplus_plan:
            raise ValueError("未找到A+规划，请先执行Step7")

        try:
            plan = json.loads(pa.aplus_plan)
        except:
            raise ValueError("A+规划数据损坏")

        prompt = SCRIPT_PROMPT.format(
            title=pd.listing_title or pd.title or "Unknown",
            brand=product.brand or settings.DEFAULT_BRAND,
            color=pd.color or "N/A",
            material=pd.material or "N/A",
            category=pd.leaf_category or "General",
            plan_json=json.dumps(plan.get("modules", []), ensure_ascii=False, indent=2),
            reference_candidates=_reference_candidates_for_prompt(_load_reference_candidates(product)),
            colors=", ".join(plan.get("color_palette", ["#FFFFFF", "#000000"])),
            style=plan.get("tone", "professional"),
            tone=plan.get("tone", "professional"),
            output_width=settings.APLUS_IMAGE_WIDTH,
            output_height=settings.APLUS_IMAGE_HEIGHT,
        )

        # 调用 LLM
        client = settings.get_llm_client()
        max_attempts = 2
        request_client = client.with_options(timeout=45, max_retries=0) if hasattr(client, "with_options") else client

        logger.info(f"[Step8] 调用LLM生成A+脚本: {len(plan.get('modules', []))} 个模块")
        response = None
        last_transient_error: Exception | None = None
        for attempt in range(1, max_attempts + 1):
            try:
                response = await request_client.chat.completions.create(
                    model=settings.LLM_MODEL,
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.7,
                    max_tokens=4000,
                    response_format={"type": "json_object"},
                )
                break
            except Exception as exc:
                if not _is_transient_llm_error(exc):
                    raise
                last_transient_error = exc
                if attempt >= max_attempts:
                    logger.warning(
                        "[Step8] A+脚本LLM连接连续失败，使用保底脚本继续: attempts=%s, error=%s: %s",
                        max_attempts,
                        type(exc).__name__,
                        exc,
                    )
                    break
                wait_seconds = attempt * 5
                logger.warning(
                    "[Step8] A+脚本LLM连接异常，准备重试: attempt=%s/%s, wait=%ss, error=%s: %s",
                    attempt,
                    max_attempts,
                    wait_seconds,
                    type(exc).__name__,
                    exc,
                )
                await asyncio.sleep(wait_seconds)
        if response is None:
            if last_transient_error:
                scripts_data = _fallback_aplus_scripts(plan, product, pd)
            else:
                raise RuntimeError("A+脚本未生成真实结果，请重跑")
        else:
            content = response.choices[0].message.content
            if not content:
                raise RuntimeError("LLM 返回空结果")

            try:
                scripts_data = json.loads(content)
            except json.JSONDecodeError as e:
                raise RuntimeError(f"A+脚本JSON解析失败: {e}")

        brand = product.brand or settings.DEFAULT_BRAND
        scripts_data = normalize_aplus_scripts_for_plan(scripts_data, plan)
        scripts_data = _attach_reference_images(scripts_data, product, plan, brand)
        scripts_data = _sanitize_scripts(scripts_data, brand)

        # 保存
        pa.aplus_scripts = json.dumps(scripts_data, ensure_ascii=False)
        pa.aplus_scripts_summary = scripts_data.get("summary")
        pa.scripted_at = datetime.now()
        await db.commit()

        scripts = scripts_data.get("scripts", [])
        logger.info(f"[Step8] A+脚本生成完成: {len(scripts)} 个出图prompt")
        return scripts_data


async def diagnose_aplus_regeneration_feedback(product_id: int, module_position: int, reason: str) -> dict:
    """先分析用户反馈，判断是否需要重选参考图，并给出脚本修改方案。"""
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
        pa = product.aplus
        if not pa or not pa.aplus_plan or not pa.aplus_scripts:
            raise ValueError("未找到A+规划/脚本，请先执行Step7/Step8")

        try:
            plan = json.loads(pa.aplus_plan)
            scripts_data = json.loads(pa.aplus_scripts)
        except json.JSONDecodeError:
            raise ValueError("A+规划或脚本数据损坏")

        modules = plan.get("modules", []) if isinstance(plan, dict) else []
        scripts = scripts_data.get("scripts", []) if isinstance(scripts_data, dict) else []
        current_script = next((item for item in scripts if item.get("module_position") == module_position), None)
        if not current_script:
            raise ValueError(f"未找到模块 {module_position} 的A+脚本")
        clean_current_script = _clean_script_for_regeneration(current_script)
        module_plan = next((item for item in modules if item.get("position") == module_position or item.get("module_position") == module_position), {})
        current_generated = {}
        if pa.aplus_images:
            try:
                image_items = json.loads(pa.aplus_images)
                if isinstance(image_items, list):
                    current_generated = next((item for item in image_items if item.get("position") == module_position), {}) or {}
            except json.JSONDecodeError:
                current_generated = {}
        brand = product.brand or settings.DEFAULT_BRAND
        candidates = _load_reference_candidates(product)

        prompt = REGENERATION_DIAGNOSIS_PROMPT.format(
            title=pd.listing_title or pd.title or "Unknown",
            brand=brand,
            color=pd.color or "N/A",
            material=pd.material or "N/A",
            category=pd.leaf_category or "General",
            module_plan_json=json.dumps(module_plan, ensure_ascii=False, indent=2),
            current_script_json=json.dumps(clean_current_script, ensure_ascii=False, indent=2),
            current_generated_image_json=json.dumps(current_generated, ensure_ascii=False, indent=2),
            current_references_json=json.dumps(current_script.get("reference_images") or [], ensure_ascii=False, indent=2),
            reference_candidates_json=_reference_candidates_for_prompt(candidates),
            reason=reason.strip(),
        )

    client = settings.get_llm_client()
    logger.info(f"[Step8] 分析A+重新生成反馈: product={product_id}, module={module_position}")
    response = await client.chat.completions.create(
        model=settings.LLM_MODEL,
        messages=[
            {"role": "system", "content": "You diagnose Amazon A+ image regeneration feedback and choose reference images from analyzed candidates. Return valid JSON only."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
        max_tokens=1600,
        response_format={"type": "json_object"},
    )
    content = response.choices[0].message.content
    if not content:
        raise RuntimeError("反馈诊断返回空结果")
    try:
        diagnosis = json.loads(content)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"A+反馈诊断JSON解析失败: {e}")
    if not isinstance(diagnosis, dict):
        raise RuntimeError("A+反馈诊断返回格式错误")
    feedback_analysis = diagnosis.get("user_feedback_analysis")
    if not isinstance(feedback_analysis, dict):
        feedback_analysis = {
            "plain_language_intent": reason.strip(),
            "requested_actions": [reason.strip()],
            "acceptance_criteria": [reason.strip()],
            "script_rewrite_required": True,
            "image_regeneration_required": True,
        }
        diagnosis["user_feedback_analysis"] = feedback_analysis
    feedback_analysis.setdefault("script_rewrite_required", True)
    feedback_analysis.setdefault("image_regeneration_required", True)
    if not isinstance(feedback_analysis.get("acceptance_criteria"), list) or not feedback_analysis.get("acceptance_criteria"):
        legacy_requirements = feedback_analysis.get("non_negotiable_requirements")
        feedback_analysis["acceptance_criteria"] = legacy_requirements if isinstance(legacy_requirements, list) and legacy_requirements else [reason.strip()]
    diagnosis["user_feedback"] = reason.strip()
    diagnosis["diagnosed_at"] = datetime.now().isoformat(timespec="seconds")
    logger.info(
        f"[Step8] A+反馈诊断完成: product={product_id}, module={module_position}, "
        f"issue={diagnosis.get('issue_type')}, references={diagnosis.get('reference_action')}"
    )
    return diagnosis


async def regenerate_aplus_module_script(product_id: int, module_position: int, reason: str, diagnosis: dict | None = None) -> dict:
    """按用户反馈重新生成单个 A+ 模块脚本，并写回原脚本列表。"""
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
        pa = product.aplus
        if not pa or not pa.aplus_plan:
            raise ValueError("未找到A+规划，请先执行Step7")
        if not pa.aplus_scripts:
            raise ValueError("未找到A+脚本，请先执行Step8")

        try:
            plan = json.loads(pa.aplus_plan)
            scripts_data = json.loads(pa.aplus_scripts)
        except json.JSONDecodeError:
            raise ValueError("A+规划或脚本数据损坏")

        if _plan_publish_profile(plan) == APLUS_PUBLISH_PROFILE_ENHANCED_BASIC_APLUS_V1:
            raise ValueError("Enhanced basic A+ uses slot-level scripts; module-level script regeneration is not supported in Phase 3")

        modules = plan.get("modules", []) if isinstance(plan, dict) else []
        scripts = scripts_data.get("scripts", []) if isinstance(scripts_data, dict) else []
        if not isinstance(scripts, list) or not scripts:
            raise ValueError("A+脚本中没有出图模块")

        current_script = next((item for item in scripts if item.get("module_position") == module_position), None)
        if not current_script:
            raise ValueError(f"未找到模块 {module_position} 的A+脚本")
        clean_current_script = _clean_script_for_regeneration(current_script)

        module_plan = next((item for item in modules if item.get("position") == module_position or item.get("module_position") == module_position), {})
        brand = product.brand or settings.DEFAULT_BRAND
        diagnosis = diagnosis or {
            "issue_type": "other",
            "root_cause": "Regenerate based on user feedback.",
            "reference_action": "keep",
            "prompt_revision_plan": [reason.strip()],
        }
        candidates = _load_reference_candidates(product)
        prompt = REGENERATE_SCRIPT_PROMPT.format(
            title=pd.listing_title or pd.title or "Unknown",
            brand=brand,
            color=pd.color or "N/A",
            material=pd.material or "N/A",
            category=pd.leaf_category or "General",
            module_plan_json=json.dumps(module_plan, ensure_ascii=False, indent=2),
            current_script_json=json.dumps(clean_current_script, ensure_ascii=False, indent=2),
            diagnosis_json=json.dumps(diagnosis, ensure_ascii=False, indent=2),
            reference_candidates_json=_reference_candidates_for_prompt(candidates),
            reason=reason.strip(),
            module_position=module_position,
            output_width=settings.APLUS_IMAGE_WIDTH,
            output_height=settings.APLUS_IMAGE_HEIGHT,
        )

        client = settings.get_llm_client()
        logger.info(f"[Step8] 按反馈重新生成A+模块脚本: product={product_id}, module={module_position}")
        response = await client.chat.completions.create(
            model=settings.LLM_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=0.7,
            max_tokens=2200,
            response_format={"type": "json_object"},
        )

        content = response.choices[0].message.content
        if not content:
            raise RuntimeError("LLM 返回空结果")

        try:
            regenerated = json.loads(content)
        except json.JSONDecodeError as e:
            raise RuntimeError(f"A+模块脚本JSON解析失败: {e}")

        if isinstance(regenerated, dict) and isinstance(regenerated.get("script"), dict):
            regenerated = regenerated["script"]
        if not isinstance(regenerated, dict):
            raise RuntimeError("A+模块脚本返回格式错误")

        regenerated["module_position"] = module_position
        regenerated["width"] = settings.APLUS_IMAGE_WIDTH
        regenerated["height"] = settings.APLUS_IMAGE_HEIGHT
        regenerated.setdefault("style", current_script.get("style", "photography"))
        regenerated["regenerate_reason"] = reason.strip()
        regenerated["regeneration_diagnosis"] = diagnosis
        regenerated["regenerated_at"] = datetime.now().isoformat(timespec="seconds")

        sanitized = _sanitize_scripts({"scripts": [regenerated]}, brand)
        regenerated = sanitized["scripts"][0]
        refs = _select_references_for_regeneration(
            candidates,
            module_plan,
            regenerated,
            module_position,
            product.images.main_image_path if product.images else None,
            diagnosis,
        )
        _attach_module_strategy_section(regenerated, module_plan)
        _append_regeneration_diagnosis_section(regenerated, diagnosis)
        _append_reference_section(regenerated, refs, brand)
        _prepend_feedback_requirements(regenerated, reason, diagnosis)
        regenerated = _sanitize_scripts({"scripts": [regenerated]}, brand)["scripts"][0]

        updated_scripts = [
            regenerated if item.get("module_position") == module_position else item
            for item in scripts
        ]
        updated_scripts.sort(key=lambda item: item.get("module_position") or 0)
        scripts_data["scripts"] = updated_scripts
        scripts_data["summary"] = scripts_data.get("summary") or "A+ image scripts"
        scripts_data["last_regenerated_module"] = module_position
        scripts_data["last_regenerate_reason"] = reason.strip()
        scripts_data["last_regeneration_diagnosis"] = diagnosis

        pa.aplus_scripts = json.dumps(scripts_data, ensure_ascii=False)
        pa.aplus_scripts_summary = scripts_data.get("summary")
        pa.scripted_at = datetime.now()
        await db.commit()

        logger.info(f"[Step8] A+模块脚本重新生成完成: product={product_id}, module={module_position}")
        return regenerated
