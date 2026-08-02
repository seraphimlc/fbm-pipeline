#!/usr/bin/env python3
"""Focused contracts for detailed, evidence-bounded image analysis output."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.pipeline.step6_image import (  # noqa: E402
    VLM_ANALYSIS_PROMPT,
    _gallery_evidence_coverage,
    _image_evidence_cards,
    _listing_image_alignment,
    _pending_listing_image_alignment,
)
from app.services.product_image_vlm import require_complete_batch_reviews  # noqa: E402
from types import SimpleNamespace


def main() -> None:
    review = {
        "image_id": "#01",
        "filename": "sofa-detail.jpg",
        "visible_selling_point": "Visible woven upholstery and three seat modules",
        "decision_reason": "Useful material-detail proof",
        "conversion_role": "material_detail",
        "risk_flags": ["exact fiber composition is not visible"],
        "multimodal_result": {
            "visual_summary": "Close detail of woven upholstery on a modular sofa.",
            "product_angle": "close-up",
            "product_state": "assembled",
            "color_reading": "green",
            "size_scale_cues": "no human scale reference",
            "visible_parts": "woven seat cushion and module seam",
            "completeness": "detail only, not full product",
            "material_texture": "woven texture",
            "scene_type": "studio product detail",
            "background_props": "none",
            "text_graphics": "none",
            "claimable_visual_facts": ["Visible woven upholstery texture", "Separate module seam is visible"],
            "non_claimable_or_uncertain": ["Exact fiber composition is not proven"],
            "recommended_copy_uses": ["Material appearance anchor for a Product Highlight"],
            "quality_assessment": {
                "sharpness": "clear",
                "crop_and_completeness": "detailed crop; not suitable as the only full-product view",
                "lighting_and_color": "even studio lighting",
                "amazon_suitability": "gallery",
            },
            "aplus_reference_value": "Can anchor a fabric-detail A+ module",
            "confidence": "high",
            "uncertainty": ["Cannot verify fabric composition from image alone"],
        },
    }
    gallery = [
        {**review, "slot": "02", "selection_role": "material_detail"},
        {"image_id": "#02", "slot": "03", "selection_role": "size_scale"},
    ]

    cards = _image_evidence_cards([review], gallery)
    assert len(cards) == 1
    assert cards[0]["selected_for_gallery"] is True
    assert cards[0]["claimable_visual_facts"] == review["multimodal_result"]["claimable_visual_facts"]
    assert "Exact fiber composition is not proven" in cards[0]["not_proven_or_uncertain"]
    assert "exact fiber composition is not visible" in cards[0]["not_proven_or_uncertain"]
    assert cards[0]["quality_assessment"]["amazon_suitability"] == "gallery"

    coverage = {item["key"]: item for item in _gallery_evidence_coverage(gallery)}
    assert coverage["material_detail"]["status"] == "covered"
    assert coverage["size_scale"]["image_ids"] == ["#02"]
    assert coverage["package_contents"]["status"] == "missing"

    for key in (
        "claimable_visual_facts",
        "non_claimable_or_uncertain",
        "recommended_copy_uses",
        "quality_assessment",
    ):
        assert key in VLM_ANALYSIS_PROMPT

    require_complete_batch_reviews(
        [{"image_id": "#01"}, {"image_id": "#02"}],
        [{"image_id": "#01"}, {"image_id": "#02"}],
        batch_label="fixture",
    )
    try:
        require_complete_batch_reviews(
            [{"image_id": "#01"}],
            [{"image_id": "#01"}, {"image_id": "#02"}],
            batch_label="fixture",
        )
        raise AssertionError("partial VLM result must be rejected")
    except RuntimeError as exc:
        assert "missing=#02" in str(exc)

    pd = SimpleNamespace(
        title="Example Sofa",
        listing_title="Example Sofa",
        listing_product_highlights='["Room Fit: Compact size for apartment living"]',
        listing_bullets='["Dimensions help buyers plan their space before ordering."]',
        listing_description="",
        material=None,
        filler=None,
        product_type="sofa",
        leaf_category="Sofas",
        description="",
    )
    alignment = _listing_image_alignment(pd, gallery)
    assert alignment["status"] == "checked"
    assert _pending_listing_image_alignment()["status"] == "pending_listing"
    print("image evidence card contracts: PASS")


if __name__ == "__main__":
    main()
