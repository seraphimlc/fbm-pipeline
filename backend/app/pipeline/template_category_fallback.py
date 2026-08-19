"""Conservative Step 4 category fallback backed by checked-in templates.

This is deliberately narrower than a free-form category guess: a fallback is
only returned when a product's own text has an explicit marker in one of the
registered Amazon template category options.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.models import ProductData


MAPPING_DIR = Path(__file__).resolve().parent / "template_mappings"
_FALLBACK_MAPPINGS = (
    MAPPING_DIR / "vindhvisk_bed_frame.json",
    MAPPING_DIR / "vindhvisk_bicycle.json",
    MAPPING_DIR / "andy_shelf_table_cabinet_gate.json",
    MAPPING_DIR / "andy_storage_furniture.json",
    MAPPING_DIR / "vindhvisk_sofa.json",
)


def _product_text(pd: ProductData) -> str:
    return " ".join(
        str(value or "")
        for value in (
            pd.leaf_category,
            pd.categories,
            pd.product_type,
            pd.title,
            pd.listing_title,
            pd.description,
            pd.features,
            pd.variants,
        )
    ).lower()


def _score_option(option: dict[str, Any], text: str) -> int:
    score = 0
    for marker in option.get("markers") or []:
        normalized = str(marker or "").strip().lower()
        # Very short markers are too ambiguous for an automatic fallback.
        if len(normalized) >= 5 and normalized in text:
            score += 100 + min(len(normalized), 50)
    node = str(option.get("node") or "").strip().lower()
    if len(node) >= 5 and node in text:
        score += 60 + min(len(node), 40)
    return score


def _is_excluded_bed_frame_text(text: str) -> bool:
    return any(marker in text for marker in (
        "adjustable-bed-base",
        "adjustable bed base",
        "adjustable bed bases",
        "childrens-bed-frame",
        "children's bed frame",
        "children bed frame",
        "kids bed frame",
        "sofa bed",
        "futon",
    ))


def select_template_category_fallback(pd: ProductData | None) -> dict[str, Any] | None:
    """Return a registered category only when a specific marker is present."""
    if pd is None:
        return None
    text = _product_text(pd)
    best: tuple[int, dict[str, Any], str] | None = None
    for mapping_path in _FALLBACK_MAPPINGS:
        try:
            mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if mapping.get("category_type") == "bed_frame" and _is_excluded_bed_frame_text(text):
            continue
        for option in mapping.get("browse_category_options") or []:
            if not isinstance(option, dict):
                continue
            score = _score_option(option, text)
            if score and (best is None or score > best[0]):
                best = (score, option, str(mapping.get("category_type") or "template"))
    if best is None:
        return None
    _, option, mapping_type = best
    path = [part.strip() for part in str(option.get("path") or "").split(">") if part.strip()]
    node = str(option.get("node") or "").strip()
    if not path or not node:
        return None
    leaf = f"{path[-1]} ({node})"
    return {
        "skipped": True,
        "reason": f"使用已登记 {mapping_type} 模板类目兜底",
        "used_template_category": True,
        "categories": [*path[:-1], leaf],
        "leafCategory": leaf,
        "itemTypeKeyword": f"{' > '.join(path)} ({node})",
    }
