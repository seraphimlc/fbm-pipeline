"""A+ product narrative diagnosis helpers.

This module owns the product-story diagnosis contract used before A+ module
planning. Step7 remains the compatibility entry point for A+ planning, but the
diagnosis stage is intentionally named and isolated here.
"""

from __future__ import annotations

import json
import re
from typing import Any


NARRATIVE_DIAGNOSIS_PROMPT_SECTION = """## Product Narrative Diagnosis
Before designing modules, diagnose the product story with AI judgment. Do not merely restate the title or feature list.
Use the product facts, Step 6 image diagnostics, available reference images, category, price point, and primary keyword to decide:
- why the target buyer would care
- what the buyer is uncertain about
- whether the current image/fact evidence is strong, mixed, or limited
- what A+ must add beyond MAIN/gallery images
- which emotional, practical, proof, or objection-reduction story should lead"""


NARRATIVE_DIAGNOSIS_OUTPUT_SCHEMA = """"product_narrative_diagnosis": {{
    "diagnosis_summary": "one concise paragraph explaining the A+ story strategy for this exact product",
    "product_story_type": "experience_led|proof_led|spec_objection_led|trust_led|comparison_led|gift_or_occasion_led|problem_solution_led",
    "primary_buyer_motivation": "the main reason the buyer would care",
    "target_use_context": "the most plausible real-life use or ownership context",
    "dominant_purchase_trigger": "what makes the buyer move from interest to purchase",
    "key_buyer_objections": ["specific doubts this product must answer"],
    "evidence_strength": "strong|mixed|limited",
    "evidence_gaps": ["missing visual/fact proof that A+ should handle conservatively"],
    "differentiation_angle": "how this product should feel different without inventing claims",
    "gallery_repetition_risk": "what MAIN/gallery already covers and A+ should not simply repeat",
    "visual_story_tone": "warm|technical|minimal|premium|playful|practical|durable|soft|clean",
    "narrative_strategy_by_module": {{
      "hero": "story job for module 1",
      "lifestyle": "story job for module 2",
      "feature_proof": "story job for module 3",
      "spec_objection": "story job for module 4",
      "closing": "story job for module 5"
    }},
    "claims_to_avoid": ["unsupported claims, scenes, certifications, materials, or outcomes to avoid"]
  }}"""


def _compact_text(value: Any, fallback: str = "") -> str:
    text = str(value or "").strip()
    if not text:
        text = fallback
    return re.sub(r"\s+", " ", text).strip()


def _trim_text(value: Any, max_length: int, fallback: str = "") -> str:
    text = _compact_text(value, fallback)
    if len(text) <= max_length:
        return text
    return text[: max(0, max_length - 3)].rstrip() + "..."


def _as_list(value: Any) -> list:
    if isinstance(value, list):
        return value
    if value is None:
        return []
    return [value]


def _string_list(value: Any, fallback: list[str], *, min_items: int, max_items: int, max_length: int) -> list[str]:
    items = [_trim_text(item, max_length) for item in _as_list(value) if _compact_text(item)]
    if not items:
        items = list(fallback)
    while len(items) < min_items:
        items.append(fallback[min(len(items), len(fallback) - 1)])
    return items[:max_items]


def _product_title(product_data: Any) -> str:
    return _trim_text(getattr(product_data, "listing_title", None) or getattr(product_data, "title", None), 80, "Current product")


def _feature_items_from_product_data(product_data: Any, selling_points: list) -> list[str]:
    feature_items: list[str] = []
    features = getattr(product_data, "features", None)
    if features:
        try:
            parsed_features = json.loads(features)
            if isinstance(parsed_features, list):
                feature_items = [_compact_text(item) for item in parsed_features if _compact_text(item)]
            elif parsed_features:
                feature_items = [_compact_text(parsed_features)]
        except Exception:
            feature_items = [_compact_text(features)]
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


def _reference_candidate_count(product_image: Any | None) -> int:
    if not product_image:
        return 0
    reference_paths = [product_image.main_image_path] if getattr(product_image, "main_image_path", None) else []
    gallery_images = getattr(product_image, "gallery_images", None)
    if gallery_images:
        try:
            parsed_gallery = json.loads(gallery_images)
            if isinstance(parsed_gallery, list):
                reference_paths.extend(
                    item.get("path") if isinstance(item, dict) else item
                    for item in parsed_gallery
                )
        except Exception:
            pass
    return len({str(path) for path in reference_paths if path})


def _diagnosis_text(value: Any, max_length: int, fallback: str) -> str:
    return _trim_text(value, max_length, fallback)


def _diagnosis_choice(value: Any, allowed: set[str], fallback: str) -> str:
    text = _compact_text(value).lower().replace("-", "_").replace(" ", "_")
    return text if text in allowed else fallback


def _story_type_from_product(product_data: Any, selling_points: list) -> str:
    category = _compact_text(getattr(product_data, "leaf_category", None) or getattr(product_data, "amazon_category", None)).lower()
    text = " ".join([
        category,
        _compact_text(getattr(product_data, "listing_title", None) or getattr(product_data, "title", None)),
        " ".join(map(str, selling_points)),
    ]).lower()
    if any(term in text for term in ("gift", "holiday", "party", "decor", "toy")):
        return "gift_or_occasion_led"
    if any(term in text for term in ("replacement", "repair", "organizer", "storage", "cleaning", "solution")):
        return "problem_solution_led"
    if any(term in text for term in ("size", "compatible", "fit", "set up", "setup", "installation", "dimension")):
        return "spec_objection_led"
    if any(term in text for term in ("steel", "wood", "fabric", "material", "waterproof", "durable", "heavy duty")):
        return "proof_led"
    return "experience_led"


def _evidence_strength(product_image: Any | None, selling_points: list) -> str:
    reference_count = _reference_candidate_count(product_image)
    if reference_count >= 5 and len(selling_points) >= 3:
        return "strong"
    if reference_count >= 2 or selling_points:
        return "mixed"
    return "limited"


def _diagnosis_module_strategy(raw_strategy: Any, story_type: str) -> dict:
    raw_strategy = raw_strategy if isinstance(raw_strategy, dict) else {}
    defaults_by_story = {
        "experience_led": {
            "hero": "Make the product immediately understandable and desirable.",
            "lifestyle": "Show the most believable daily-use context.",
            "feature_proof": "Use visible details to support the experience promise.",
            "spec_objection": "Answer the practical fit or setup doubt without turning A+ into a spec sheet.",
            "closing": "Close with a confident ownership moment.",
        },
        "proof_led": {
            "hero": "Lead with a clear product promise grounded in visible construction.",
            "lifestyle": "Show where the proof matters in real use.",
            "feature_proof": "Make the strongest material, build, or functional evidence visible.",
            "spec_objection": "Translate technical details into practical buyer confidence.",
            "closing": "Close on reliability and fit-for-purpose confidence.",
        },
        "spec_objection_led": {
            "hero": "Frame the product around the core fit or compatibility promise.",
            "lifestyle": "Show the product in the use case where fit matters.",
            "feature_proof": "Support the fit claim with visible product detail.",
            "spec_objection": "Answer size, setup, compatibility, material, or included-part doubts clearly.",
            "closing": "Close by reducing final purchase friction.",
        },
        "trust_led": {
            "hero": "Make the product feel clear, stable, and credible.",
            "lifestyle": "Show realistic use without overclaiming.",
            "feature_proof": "Use evidence-backed details to build trust.",
            "spec_objection": "Address the strongest reason a cautious buyer may hesitate.",
            "closing": "Close with confidence, care, and ownership reassurance.",
        },
    }
    defaults = defaults_by_story.get(story_type, defaults_by_story["experience_led"])
    return {
        role: _diagnosis_text(raw_strategy.get(role), 220, default)
        for role, default in defaults.items()
    }


def normalize_product_narrative_diagnosis(
    raw_value: Any,
    *,
    product_data: Any,
    product_image: Any | None,
    selling_points: list,
    fallback: bool,
) -> dict:
    raw = raw_value if isinstance(raw_value, dict) else {}
    category = _compact_text(getattr(product_data, "leaf_category", None) or getattr(product_data, "amazon_category", None), "General")
    title = _product_title(product_data)
    feature_items = _feature_items_from_product_data(product_data, selling_points)
    story_type = _diagnosis_choice(
        raw.get("product_story_type"),
        {
            "experience_led",
            "proof_led",
            "spec_objection_led",
            "trust_led",
            "comparison_led",
            "gift_or_occasion_led",
            "problem_solution_led",
        },
        _story_type_from_product(product_data, selling_points),
    )
    evidence_strength = _diagnosis_choice(raw.get("evidence_strength"), {"strong", "mixed", "limited"}, _evidence_strength(product_image, selling_points))
    key_objections = _string_list(
        raw.get("key_buyer_objections"),
        [
            "Will this product fit my intended use?",
            "Can I trust the visible quality and product details?",
            "What does A+ add beyond the main gallery?",
        ],
        min_items=2,
        max_items=5,
        max_length=180,
    )
    evidence_gaps = _string_list(
        raw.get("evidence_gaps"),
        [
            "Do not imply missing visual proof; use conservative explanation when reference evidence is limited.",
        ],
        min_items=1,
        max_items=5,
        max_length=180,
    )
    return {
        "diagnosis_summary": _diagnosis_text(
            raw.get("diagnosis_summary"),
            500,
            f"Use A+ to turn {title} into a {story_type.replace('_', ' ')} five-banner story for {category} shoppers.",
        ),
        "product_story_type": story_type,
        "primary_buyer_motivation": _diagnosis_text(
            raw.get("primary_buyer_motivation"),
            240,
            f"Understand whether {title} fits the buyer's real use case and quality expectations.",
        ),
        "target_use_context": _diagnosis_text(
            raw.get("target_use_context"),
            240,
            f"Realistic {category} ownership or usage context supported by product facts.",
        ),
        "dominant_purchase_trigger": _diagnosis_text(
            raw.get("dominant_purchase_trigger"),
            240,
            feature_items[0],
        ),
        "key_buyer_objections": key_objections,
        "evidence_strength": evidence_strength,
        "evidence_gaps": evidence_gaps,
        "differentiation_angle": _diagnosis_text(
            raw.get("differentiation_angle"),
            260,
            "Differentiate through supported use context and visible details rather than unsupported claims.",
        ),
        "gallery_repetition_risk": _diagnosis_text(
            raw.get("gallery_repetition_risk"),
            260,
            "Do not repeat MAIN/gallery facts unless A+ adds usage context, emotion, or buyer decision clarity.",
        ),
        "visual_story_tone": _diagnosis_choice(
            raw.get("visual_story_tone"),
            {"warm", "technical", "minimal", "premium", "playful", "practical", "durable", "soft", "clean"},
            "practical",
        ),
        "narrative_strategy_by_module": _diagnosis_module_strategy(raw.get("narrative_strategy_by_module"), story_type),
        "claims_to_avoid": _string_list(
            raw.get("claims_to_avoid") or raw.get("visual_do_not_claim"),
            [
                "Do not invent certifications, safety outcomes, materials, accessories, dimensions, compatibility, or performance claims.",
            ],
            min_items=1,
            max_items=6,
            max_length=220,
        ),
        "diagnosis_source": "fallback" if fallback or not raw else "llm",
    }
