#!/usr/bin/env python3
"""Focused black-box contracts for short titles and Product Highlights."""

from __future__ import annotations

import asyncio
import json
import sys
import zipfile
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.pipeline import step5_listing  # noqa: E402
from app.api import products as product_api  # noqa: E402
from app.product_tasks import actions as product_actions  # noqa: E402


TITLE_LIMIT = 75
HIGHLIGHT_LIMIT = 120
EXPECTED_BULLET_FIELDS = [
    f"bullet_point[marketplace_id=ATVPDKIKX0DER][language_tag=en_US]#{index}.value"
    for index in range(1, 6)
]
LISTING_TEMPLATE_CASES = {
    "vindhvisk_bicycle.json": "BICYCLE_CYCLING.xlsm",
    "vindhvisk_sofa.json": "CHAIR_SOFA.xlsm",
    "andy_storage_furniture.json": "DRESSER_STORAGE_DRAWER_STORAGE_BOX_CABINET_STEP_STOOL.xlsm",
    "ride_on_toy.json": "RIDE_ON_TOY.xlsm",
    "andy_shelf_table_cabinet_gate.json": "SHELF_TABLE_CABINET_ANIMAL_CAGE_TEMPORARY_GATE.xlsm",
}


class FakeCompletionClient:
    def __init__(self, responses: list[dict]) -> None:
        self.responses = list(responses)
        self.calls: list[dict] = []
        self.chat = SimpleNamespace(completions=self)

    def with_options(self, **_kwargs):
        return self

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if not self.responses:
            raise AssertionError("Listing generator requested more LLM responses than expected")
        payload = self.responses.pop(0)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))]
        )


class FakeResult:
    def __init__(self, product: SimpleNamespace) -> None:
        self.product = product

    def scalar_one_or_none(self):
        return self.product


class FakeSession:
    def __init__(self, product: SimpleNamespace) -> None:
        self.product = product
        self.committed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def execute(self, _statement):
        return FakeResult(self.product)

    async def commit(self):
        self.committed = True


def _product_fixture() -> SimpleNamespace:
    data = SimpleNamespace(
        title="Three-piece modular sofa",
        product_type="modular sofa",
        color="Green",
        material="Woven fabric",
        filler="Foam",
        dimension_length=85.0,
        dimension_width=34.0,
        dimension_height=30.0,
        weight=120.0,
        packages=json.dumps([{"count": 3}]),
        variants=json.dumps([{"color": "Green"}]),
        features=json.dumps(["three-piece layout", "deep seats"]),
        description="Three-piece modular sofa for flexible seating.",
        origin="China",
        keywords_top=json.dumps([{"keyword": "modular sofa", "search_volume": 12000}]),
        categories=json.dumps(["Furniture", "Living Room", "Sofas"]),
        leaf_category="Sofas",
        customer_mindset="{}",
        listing_title="previous title",
        listing_product_highlights=json.dumps(["previous highlight"]),
        listing_bullets=json.dumps(["previous bullet"]),
        listing_description="previous description",
        listing_search_terms="previous terms",
        listing_title_zh="old title zh",
        listing_product_highlights_zh=json.dumps(["old highlight zh"]),
        listing_bullets_zh=json.dumps(["old bullet zh"]),
        listing_description_zh="old description zh",
        listing_search_terms_zh="old terms zh",
        listing_check="{}",
        listing_primary_keyword=None,
        listing_removed_keywords="[]",
    )
    return SimpleNamespace(id=42, brand="Vindhvisk", data=data, images=None)


def _mindset_context() -> dict:
    return {
        "schema_version": "test-v1",
        "source_fingerprint": "listing-contract-fixture",
        "strategy": {
            "primary_buyer": "apartment households",
            "core_value_proposition": "flexible supported seating",
            "objections": [],
        },
        "quality": {
            "requires_review": False,
            "critical_unknowns": [],
            "conflicts": [],
            "evidence_boundary_issues": [],
        },
    }


def _valid_listing(*, highlights: list[str] | None = None, title: str | None = None) -> dict:
    product_highlights = highlights or [
        "Three modular pieces support flexible seating arrangements beyond the title's core product identity.",
    ]
    bullets = [
        "Modular layout gives the living room a flexible three-piece seating foundation.",
        "Deep seats create a supported place to settle in during everyday lounging.",
        "Use the sofa for movie night or reading when the household needs shared seating.",
        "Compare the supplied dimensions with the intended room before arranging the modules.",
        "Confirm the included three-piece configuration before ordering to avoid layout assumptions.",
    ]
    return {
        "keyword_plan": {
            "primary_keyword": "modular sofa",
            "title_keywords": ["modular sofa"],
            "bullet_keywords": ["deep seat"],
            "search_term_keywords": ["flexible couch"],
            "excluded_keywords": [],
        },
        "positioning": {
            "target_buyer": "apartment households",
            "main_click_reason": "flexible seating",
            "conversion_risks": [],
        },
        "title": title or "Vindhvisk Modular Sofa with Deep Seats for Living Room",
        "product_highlights": product_highlights,
        "bullets": bullets,
        "bullet_audit": [
            {"position": 1, "role": "core_purchase_reason", "specific_detail": "three-piece modular layout", "evidence_refs": ["product.title"]},
            {"position": 2, "role": "supported_experience", "specific_detail": "deep seats", "evidence_refs": ["product.title"]},
            {"position": 3, "role": "use_scene", "specific_detail": "movie night or reading", "evidence_refs": ["product.title"]},
            {"position": 4, "role": "fit_and_practicality", "specific_detail": "supplied dimensions", "evidence_refs": ["product.title"]},
            {"position": 5, "role": "purchase_boundary", "specific_detail": "included three-piece configuration", "evidence_refs": ["product.title"]},
        ],
        "description": "A three-piece modular sofa designed for flexible seating arrangements.",
        "search_terms": "flexible couch, three piece seating",
        "title_zh": "Vindhvisk modular sofa",
        "product_highlights_zh": [f"Highlight zh {index}" for index in range(1, len(product_highlights) + 1)],
        "bullets_zh": [f"Bullet zh {index}" for index in range(1, 6)],
        "description_zh": "Product description zh",
        "search_terms_zh": "Search terms zh",
        "primary_keyword": "modular sofa",
        "compliance_check": {"status": "pass", "issues": []},
        "removed_keywords": [],
    }


async def _run_listing_case(responses: list[dict]):
    product = _product_fixture()
    session = FakeSession(product)
    client = FakeCompletionClient(responses)
    fake_settings = SimpleNamespace(
        DEFAULT_BRAND="Vindhvisk",
        LLM_MODEL="test-model",
        STEP5_LLM_TEMPERATURE=0.0,
        STEP5_LLM_MAX_TOKENS=4000,
        STEP5_LLM_TIMEOUT_SECONDS=120,
        STEP5_LLM_RETRY_ATTEMPTS=2,
        STEP5_DESCRIPTION_INPUT_MAX_CHARS=8000,
        STEP5_FEATURES_INPUT_MAX_CHARS=4000,
        STEP5_STRUCTURED_INPUT_MAX_CHARS=6000,
        STEP5_IMAGE_CONTEXT_MAX_ITEMS=6,
        STEP5_IMAGE_EVIDENCE_MAX_CHARS=500,
        STEP5_IMAGE_DIAGNOSTICS_MAX_CHARS=1000,
        STEP5_TITLE_MAX_CHARS=TITLE_LIMIT,
        STEP5_PRODUCT_HIGHLIGHT_MAX_CHARS=HIGHLIGHT_LIMIT,
        STEP5_BULLET_MAX_CHARS=500,
        STEP5_SEARCH_TERMS_MAX_BYTES=250,
        get_llm_client=lambda: client,
    )
    originals = (
        step5_listing.async_session,
        step5_listing.settings,
        step5_listing.customer_mindset_context,
        step5_listing.customer_mindset_matches_product,
    )
    step5_listing.async_session = lambda: session
    step5_listing.settings = fake_settings
    step5_listing.customer_mindset_context = lambda *_args, **_kwargs: _mindset_context()
    step5_listing.customer_mindset_matches_product = lambda *_args, **_kwargs: True
    try:
        result = await step5_listing.run_listing(product.id)
    finally:
        (
            step5_listing.async_session,
            step5_listing.settings,
            step5_listing.customer_mindset_context,
            step5_listing.customer_mindset_matches_product,
        ) = originals
    return result, product.data, client, session


def _assert_valid_contract(result: dict) -> None:
    assert 0 < len(result["title"]) <= TITLE_LIMIT, result["title"]
    highlights = result["product_highlights"]
    assert len(highlights) == 1, highlights
    assert all(0 < len(item) <= HIGHLIGHT_LIMIT for item in highlights), highlights
    assert len(result["bullets"]) == 5, result["bullets"]


def test_completion_gates_require_the_full_contract() -> None:
    valid_data = SimpleNamespace(
        listing_title="Vindhvisk Modular Sofa for Flexible Living Room Seating",
        listing_product_highlights=json.dumps(
            ["Three modular pieces support flexible seating arrangements beyond the title's core product identity."]
        ),
        listing_bullets=json.dumps([f"Distinct legacy bullet {index}" for index in range(1, 6)]),
    )
    readiness_checks = (
        product_api._listing_content_ready,
        product_actions._listing_content_ready,
    )
    for check in readiness_checks:
        assert check(SimpleNamespace(data=valid_data))

        missing_highlights = SimpleNamespace(**vars(valid_data))
        missing_highlights.listing_product_highlights = None
        assert not check(SimpleNamespace(data=missing_highlights))

        short_bullets = SimpleNamespace(**vars(valid_data))
        short_bullets.listing_bullets = json.dumps(["Only one legacy bullet"])
        assert not check(SimpleNamespace(data=short_bullets))

        overlong_title = SimpleNamespace(**vars(valid_data))
        overlong_title.listing_title = "T" * (TITLE_LIMIT + 1)
        assert not check(SimpleNamespace(data=overlong_title))

        overlong_highlight = SimpleNamespace(**vars(valid_data))
        highlights = json.loads(valid_data.listing_product_highlights)
        highlights[0] = "H" * 1000
        overlong_highlight.listing_product_highlights = json.dumps(highlights)
        assert not check(SimpleNamespace(data=overlong_highlight))

    assert product_api._normalize_listing_title("Vindhvisk Modular Sofa", brand="Vindhvisk") == "Vindhvisk Modular Sofa"
    try:
        product_api._normalize_listing_title("Modular Sofa by Vindhvisk", brand="Vindhvisk")
    except Exception as exc:
        assert "必须以品牌“Vindhvisk”开头" in str(exc)
    else:
        raise AssertionError("Manual Listing title must begin with the product brand")


async def test_valid_boundaries_and_separate_persistence() -> None:
    one_highlight = ["Three modular pieces support flexible seating arrangements beyond the title's core product identity."]
    expected = _valid_listing(highlights=one_highlight)
    result, data, client, session = await _run_listing_case([expected])

    _assert_valid_contract(result)
    assert len(client.calls) == 1, "A valid response should not trigger a rewrite"
    assert session.committed
    assert json.loads(data.listing_product_highlights) == one_highlight
    assert json.loads(data.listing_bullets) == expected["bullets"]
    assert data.listing_product_highlights != data.listing_bullets
    assert json.loads(data.listing_product_highlights_zh) == expected["product_highlights_zh"]
    assert json.loads(data.listing_bullets_zh) == expected["bullets_zh"]


async def test_overlong_copy_is_rewritten_not_truncated() -> None:
    invalid = _valid_listing(
        title="Vindhvisk Modular Sofa " + "unsupported overflow wording " * 5,
        highlights=["Three modular pieces " + "supported seating detail " * 8],
    )
    rewritten = _valid_listing()
    result, data, client, _session = await _run_listing_case([invalid, rewritten])

    _assert_valid_contract(result)
    assert len(client.calls) == 2, "Overlong copy must trigger an LLM rewrite"
    assert result["title"] == rewritten["title"], "Title must use rewritten copy, not a character slice"
    assert result["product_highlights"] == rewritten["product_highlights"]
    assert data.listing_title == rewritten["title"]


async def test_invalid_highlight_count_triggers_rewrite() -> None:
    invalid = _valid_listing(
        highlights=[
            "During movie night, deep seats support the intended lounging use.",
            "Three modular pieces support a flexible arrangement.",
        ]
    )
    rewritten = _valid_listing()
    result, _data, client, _session = await _run_listing_case([invalid, rewritten])

    _assert_valid_contract(result)
    assert len(client.calls) == 2, "More than one Product Highlight must trigger a rewrite"


def _shared_strings(template_path: Path) -> str:
    with zipfile.ZipFile(template_path) as archive:
        try:
            return archive.read("xl/sharedStrings.xml").decode("utf-8", errors="replace")
        except KeyError:
            return ""


def test_real_template_and_mapping_contract() -> None:
    mappings_dir = BACKEND / "app" / "pipeline" / "template_mappings"
    templates_dir = BACKEND / "app" / "pipeline" / "templates"

    for mapping_name, template_name in LISTING_TEMPLATE_CASES.items():
        mapping = json.loads((mappings_dir / mapping_name).read_text(encoding="utf-8"))
        assert mapping["template_path"] == f"templates/{template_name}"
        assert mapping["bullet_fields"] == EXPECTED_BULLET_FIELDS
        mapping_text = json.dumps(mapping).lower()
        assert "product_highlight" not in mapping_text
        assert "item_highlight" not in mapping_text

        shared_strings = _shared_strings(templates_dir / template_name)
        assert "<t>Bullet Point</t>" in shared_strings, template_name
        assert "Item Highlights" not in shared_strings, template_name
        assert "Product Highlights" not in shared_strings, template_name
        for field in EXPECTED_BULLET_FIELDS:
            assert f"<t>{field}</t>" in shared_strings, f"{template_name}: {field}"

    price_quantity_strings = _shared_strings(templates_dir / "PriceAndQuantity.xlsm")
    assert "Item Highlights" not in price_quantity_strings
    assert "Product Highlights" not in price_quantity_strings
    assert all(field not in price_quantity_strings for field in EXPECTED_BULLET_FIELDS)


async def main() -> None:
    test_real_template_and_mapping_contract()
    test_completion_gates_require_the_full_contract()
    await test_valid_boundaries_and_separate_persistence()
    await test_overlong_copy_is_rewritten_not_truncated()
    await test_invalid_highlight_count_triggers_rewrite()
    print("listing title/highlights focused contracts: PASS")


if __name__ == "__main__":
    asyncio.run(main())
