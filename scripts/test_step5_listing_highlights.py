#!/usr/bin/env python3
"""Focused Step 5 title and Product Highlights generation contracts."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.config import settings  # noqa: E402
from app.pipeline.step5_listing import (  # noqa: E402
    LISTING_REWRITE_MAX_ATTEMPTS,
    _build_rewrite_prompt,
    _listing_contract_violations,
    _normalize_listing,
    _prepare_listing_output,
    _repair_listing_contract,
    _rewrite_fields_for_violations,
)


def _valid_listing() -> dict:
    return {
        "keyword_plan": {"primary_keyword": "modular sofa", "excluded_keywords": []},
        "positioning": {"target_buyer": "apartment households", "conversion_risks": []},
        "title": "Vindhvisk Modular Sofa, Flexible Three-Piece Living Room Seating",
        "product_highlights": [
            "Flexible Layout: Reconfigure three modules for movie night or reading as the room changes.",
            "Woven Upholstery: The supported fabric detail adds a clear tactile finish to everyday seating.",
            "Three-Piece Format: Separate modules make placement easier when arranging an apartment living room.",
        ],
        "bullets": [
            "Flexible seating supports the documented modular layout.",
            "The three-piece format helps buyers plan their room arrangement.",
            "Use the modules for reading or movie-night seating in the living room.",
            "Check the documented dimensions before ordering for the intended space.",
            "Review the supported configuration boundaries to reduce mismatched purchases.",
        ],
        "bullet_audit": [
            {"position": 1, "role": "core_purchase_reason", "specific_detail": "documented modular layout", "evidence_refs": ["product.title"]},
            {"position": 2, "role": "supported_experience", "specific_detail": "three-piece format", "evidence_refs": ["product.title"]},
            {"position": 3, "role": "use_scene", "specific_detail": "living-room reading or movie night", "evidence_refs": ["product.title"]},
            {"position": 4, "role": "fit_and_practicality", "specific_detail": "documented dimensions", "evidence_refs": ["product.title"]},
            {"position": 5, "role": "purchase_boundary", "specific_detail": "configuration boundaries", "evidence_refs": ["product.title"]},
        ],
        "description": "A three-piece modular sofa designed for flexible living-room seating.",
        "search_terms": "apartment couch, flexible seating",
        "title_zh": "Vindhvisk 模块化沙发，灵活三件套客厅座椅",
        "product_highlights_zh": [
            "灵活布局：在客厅观影或阅读时重新组合三个模块，适应空间变化。",
            "织物表面：有依据的面料细节为日常坐卧提供清晰可见的触感表现。",
            "三件式结构：在公寓客厅布置时，独立模块更方便安排摆放位置。",
        ],
        "bullets_zh": [
            "灵活座椅布局与已有模块化结构证据保持一致。",
            "三件式结构便于买家提前规划房间布局。",
            "适合在客厅阅读或观影时作为日常座椅使用。",
            "下单前请核对已有尺寸信息与目标空间。",
            "确认有依据的组合边界，减少因理解偏差造成的错购。",
        ],
        "description_zh": "一款适合灵活客厅布局的三件式模块化沙发。",
        "search_terms_zh": "公寓沙发 灵活座椅",
        "primary_keyword": "modular sofa",
        "compliance_check": {"status": "pass", "issues": []},
        "removed_keywords": [],
    }


class _FakeCompletions:
    def __init__(self, payloads: list[dict]) -> None:
        self.payloads = payloads
        self.call_count = 0

    async def create(self, **_kwargs):
        self.call_count += 1
        payload = self.payloads[min(self.call_count - 1, len(self.payloads) - 1)]
        message = SimpleNamespace(content=json.dumps(payload, ensure_ascii=False))
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def _fake_client(*payloads: dict):
    completions = _FakeCompletions(list(payloads))
    return SimpleNamespace(chat=SimpleNamespace(completions=completions)), completions


def test_valid_contract_and_no_program_truncation() -> None:
    listing = _valid_listing()
    prepared = _prepare_listing_output(listing, "Green")
    assert _listing_contract_violations(prepared) == []

    normalized = _normalize_listing(prepared, "Green")
    assert normalized["title"] == listing["title"]
    assert normalized["product_highlights"] == listing["product_highlights"]
    assert normalized["bullets"] == listing["bullets"]
    assert normalized["compliance_check"]["title_max_chars"] == settings.STEP5_TITLE_MAX_CHARS
    assert normalized["compliance_check"]["product_highlights_count"] == 3
    assert normalized["compliance_check"]["bullet_contract"]["target_max_chars"] == 320
    assert len(normalized["compliance_check"]["bullet_contract"]["audit"]) == 5

    overlong_title = "T" * (settings.STEP5_TITLE_MAX_CHARS + 1)
    invalid = _valid_listing()
    invalid["title"] = overlong_title
    prepared_invalid = _prepare_listing_output(invalid, "Green")
    assert prepared_invalid["title"] == overlong_title
    assert any(item.startswith("title:length=") for item in _listing_contract_violations(prepared_invalid))
    try:
        _normalize_listing(prepared_invalid, "Green")
    except RuntimeError as exc:
        assert "不得程序截断" in str(exc)
    else:
        raise AssertionError("Overlong title must be rejected instead of truncated")


def test_highlight_count_length_scene_and_rewrite_fields() -> None:
    invalid = _valid_listing()
    invalid["product_highlights"] = ["Supported feature and practical result."] * 2
    invalid["product_highlights_zh"] = ["有依据的功能与实际结果。"] * 2
    violations = _listing_contract_violations(invalid)
    assert any(item.startswith("product_highlights:count=") for item in violations)
    assert any("explicit use scene missing" in item for item in violations)
    assert _rewrite_fields_for_violations(violations) == [
        "product_highlights",
        "product_highlights_zh",
    ]

    invalid = _valid_listing()
    overlong = "H" * (settings.STEP5_PRODUCT_HIGHLIGHT_MAX_CHARS + 1)
    invalid["product_highlights"][0] = overlong
    violations = _listing_contract_violations(invalid)
    assert invalid["product_highlights"][0] == overlong
    assert any(item.startswith("product_highlights[1]:length=") for item in violations)

    prompt = _build_rewrite_prompt(invalid, violations, _rewrite_fields_for_violations(violations))
    assert "Never mechanically truncate" in prompt
    assert "Keywords and competitor content are not product proof" in prompt
    assert "concise factual benefit label and a colon" in prompt
    assert "selling point + specific use scene or supported parameter + result" in prompt


def test_bullet_contract_rejects_padding_repetition_and_missing_audit() -> None:
    invalid = _valid_listing()
    invalid["bullets"][0] = "This high quality modular sofa is perfect for making life easier in every room."
    invalid["bullets"][1] = "This high quality modular sofa is perfect for making life easier in every room."
    invalid["bullet_audit"] = invalid["bullet_audit"][:4]
    violations = _listing_contract_violations(invalid)
    assert any("generic filler" in item for item in violations)
    assert any("overlapping claims" in item for item in violations)
    assert any(item.startswith("bullet_audit:count=") for item in violations)
    assert _rewrite_fields_for_violations(violations) == ["bullets", "bullets_zh", "bullet_audit"]


def test_bullet_audit_must_match_mindset_evidence() -> None:
    listing = _valid_listing()
    context = {
        "supporting_evidence": [{"id": "product.title"}],
        "strategy": {
            "content_direction": {
                "bullet_jobs": [
                    {"required_proof_refs": ["product.title"], "claim_proof_usable": True}
                    for _ in range(5)
                ]
            }
        },
    }
    listing["bullet_audit"][2]["evidence_refs"] = ["competitor.title"]
    violations = _listing_contract_violations(listing, context)
    assert "bullet_audit[3]:unknown evidence ref" in violations
    assert "bullet_audit[3]:missing required own-product proof" in violations


async def test_targeted_rewrite_and_bounded_failure() -> None:
    invalid = _valid_listing()
    invalid["title"] = "T" * (settings.STEP5_TITLE_MAX_CHARS + 20)
    valid_patch = {
        "title": "Vindhvisk Modular Sofa, Flexible Three-Piece Seating",
        "title_zh": "Vindhvisk 模块化沙发，灵活三件式座椅",
    }
    client, completions = _fake_client(valid_patch)
    repaired = await _repair_listing_contract(client, "source evidence", invalid, "Green")
    assert repaired["title"] == valid_patch["title"]
    assert repaired["product_highlights"] == invalid["product_highlights"]
    assert completions.call_count == 1

    invalid_patch = {
        "title": "T" * (settings.STEP5_TITLE_MAX_CHARS + 1),
        "title_zh": "仍然超长",
    }
    client, completions = _fake_client(invalid_patch, valid_patch)
    repaired = await _repair_listing_contract(client, "source evidence", invalid, "Green")
    assert repaired["title"] == valid_patch["title"]
    assert completions.call_count == LISTING_REWRITE_MAX_ATTEMPTS

    client, completions = _fake_client(invalid_patch)
    try:
        await _repair_listing_contract(client, "source evidence", invalid, "Green")
    except RuntimeError as exc:
        assert f"{LISTING_REWRITE_MAX_ATTEMPTS} 次定向重写" in str(exc)
    else:
        raise AssertionError("Invalid rewrite must fail after the bounded retry count")
    assert completions.call_count == LISTING_REWRITE_MAX_ATTEMPTS


def main() -> None:
    test_valid_contract_and_no_program_truncation()
    test_highlight_count_length_scene_and_rewrite_fields()
    test_bullet_contract_rejects_padding_repetition_and_missing_audit()
    test_bullet_audit_must_match_mindset_evidence()
    asyncio.run(test_targeted_rewrite_and_bounded_failure())
    print("Step 5 title/Product Highlights contracts passed")


if __name__ == "__main__":
    main()
