#!/usr/bin/env python3
"""Focused contract for Step 7-owned, Step 8-validated A+ references."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.pipeline.step7_aplus_plan import _normalize_module_strategy  # noqa: E402
from app.pipeline.step8_aplus_script import _select_references_for_script  # noqa: E402


def candidate(image_id: str, path: str, role: str, **extra) -> dict:
    return {
        "image_id": image_id,
        "path": path,
        "filename": Path(path).name,
        "conversion_role": role,
        "visible_selling_point": role,
        **extra,
    }


def main() -> None:
    module = _normalize_module_strategy(
        {
            "primary_reference_image_id": "#03",
            "secondary_reference_image_id": "#01",
            "reference_selection_reason": "Use material proof plus identity.",
            "primary_reference_use": "Preserve the visible material texture.",
            "secondary_reference_use": "Preserve the complete product identity.",
        },
        3,
    )
    script = {"module_position": 3, "prompt": "Show material detail."}
    candidates = [
        candidate("#01", "https://example.test/main.jpg", "identity"),
        candidate("#02", "https://example.test/scene.jpg", "lifestyle"),
        candidate("#03", "https://example.test/detail.jpg", "material_detail"),
    ]
    refs = _select_references_for_script(candidates, module, script, 3, candidates[0]["path"], set())
    assert [ref["image_id"] for ref in refs] == ["#03", "#01"]
    assert script["reference_selection_audit"]["fallback_used"] is False
    assert script["reference_selection_audit"]["selection_owner"] == "step7_business_plan"

    unsafe_module = _normalize_module_strategy(
        {
            "primary_reference_image_id": "#99",
            "secondary_reference_image_id": "#04",
            "preferred_reference_roles": ["material detail", "product identity"],
        },
        3,
    )
    unsafe_script = {"module_position": 3, "prompt": "Show material detail."}
    unsafe_candidates = [
        *candidates,
        candidate("#04", "https://example.test/bad.jpg", "exclude", risk_flags=["wrong variant"]),
    ]
    fallback_refs = _select_references_for_script(
        unsafe_candidates,
        unsafe_module,
        unsafe_script,
        3,
        candidates[0]["path"],
        set(),
    )
    assert len(fallback_refs) == 2
    assert "#04" not in [ref["image_id"] for ref in fallback_refs]
    assert unsafe_script["reference_selection_audit"]["fallback_used"] is True
    assert len(unsafe_script["reference_selection_audit"]["validation_issues"]) == 2
    print("A+ Step7 reference planning / Step8 validation contract: PASS")


if __name__ == "__main__":
    main()
