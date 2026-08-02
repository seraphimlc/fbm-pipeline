#!/usr/bin/env python3
"""Regression checks for the agreed 01-09 conversion-story image order."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.pipeline.step6_image import DEFAULT_IMAGE_STRATEGY, _select_gallery  # noqa: E402
from app.product_tasks.auto_image_selection import _merge_batch_results  # noqa: E402


STORY_ROLES = [
    "lifestyle", "lifestyle", "lifestyle", "material_detail", "function_use",
    "material_detail", "alternate_angle", "size_scale",
]


def _review(image_id: str, role: str, score: float) -> dict:
    return {
        "image_id": image_id,
        "filename": f"{image_id[1:]}.jpg",
        "path": f"/tmp/{image_id[1:]}.jpg",
        "conversion_role": role,
        "gallery_score": score,
        "slot01_score": 9 if image_id == "#01" else 3,
        "visible_selling_point": role,
        "decision_reason": role,
        "risk_flags": [],
        "multimodal_result": {
            "visual_summary": f"{role} palette{image_id[1:]} architecture{image_id[1:]} ambience{image_id[1:]}",
        },
    }


def test_step6_story_order() -> None:
    reviews = [_review("#01", "alternate_angle", 9.5)]
    reviews.extend(_review(f"#{index:02d}", role, 9.0 - index / 20) for index, role in enumerate(STORY_ROLES, start=2))
    _main, gallery, diagnostics = _select_gallery(reviews, DEFAULT_IMAGE_STRATEGY)
    assert [item["selection_role"] for item in gallery] == ["identity", *STORY_ROLES]
    assert gallery[-1]["selection_role"] == "size_scale"
    assert sum(item["selection_role"] == "alternate_angle" for item in gallery) == 1
    assert diagnostics["target_gallery_count"] == 9


def test_auto_selection_story_order() -> None:
    reviews = [_review("#01", "alternate_angle", 9.5)]
    reviews.extend(_review(f"#{index:02d}", role, 9.0 - index / 20) for index, role in enumerate(STORY_ROLES, start=2))
    selected_main = {
        "image_id": "#01", "path": "/tmp/01.jpg", "score": 0.99,
        "risk_flags": [], "main_image_valid": True,
    }
    selected_gallery = [
        {"image_id": review["image_id"], "path": review["path"], "score": review["gallery_score"], "role": review["conversion_role"]}
        for review in reviews[1:]
    ]
    result = _merge_batch_results(
        [{
            "selected_main": selected_main,
            "selected_gallery": selected_gallery,
            "rejected": [], "confidence": "high", "warnings": [], "image_reviews": reviews,
        }],
        [{"sheet_page": 1, "sheet_path": "/tmp/story.jpg", "image_ids": [item["image_id"] for item in reviews]}],
        [], "fixture",
    )
    assert [item["role"] for item in result["selected_gallery"]] == STORY_ROLES
    assert result["selected_gallery"][-1]["role"] == "size_scale"
    assert sum(item["role"] == "alternate_angle" for item in result["selected_gallery"]) == 1


if __name__ == "__main__":
    test_step6_story_order()
    test_auto_selection_story_order()
    print("image gallery story: PASS")
