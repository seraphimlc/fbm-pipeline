from __future__ import annotations

import asyncio
import json
from pathlib import Path
import sys
import tempfile

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.config import settings  # noqa: E402
from app.aplus_publish.module_registry import (  # noqa: E402
    APLUS_PUBLISH_PROFILE_ENHANCED_BASIC_APLUS_V1,
    APLUS_PUBLISH_PROFILE_STANDARD_HEADER_IMAGE_TEXT_V1,
    FAILURE_IMAGE_SLOT_DUPLICATE,
    FAILURE_IMAGE_SLOT_MISSING,
    FAILURE_IMAGE_SLOT_UNEXPECTED,
    LINGXING_STANDARD_HEADER_IMAGE_TEXT,
    LINGXING_STANDARD_COMPARISON_TABLE,
    LINGXING_STANDARD_IMAGE_TEXT_OVERLAY,
    LINGXING_STANDARD_SINGLE_IMAGE_SPECS_DETAIL,
    LINGXING_STANDARD_TECH_SPECS,
    LINGXING_STANDARD_THREE_IMAGE_TEXT,
    required_image_slots,
)
from app.models import CatalogProduct, Product, ProductAplus, ProductData  # noqa: E402
from app.services.lingxing_aplus_module_mapper import preflight_validate  # noqa: E402
from app.services.lingxing_aplus_publish_client import (  # noqa: E402
    LingxingAplusDraftSaveClient,
    LingxingAplusDraftSaveClientError,
    LingxingAplusDraftSaveRequest,
)
from app.services.lingxing_aplus_publish_policy import (  # noqa: E402
    build_aplus_content_fingerprint,
    collect_aplus_publish_assets,
    evaluate_aplus_publish_prerequisites,
)


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _image(path: Path, size: tuple[int, int]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, "white").save(path, format="JPEG")
    return str(path)


def _product_with_aplus(tmp: Path, *, image_size: tuple[int, int] = (970, 600), missing_index: int | None = None) -> Product:
    product = Product(
        id=101,
        gigab2b_url="https://example.test/product",
        gigab2b_product_id="T3-POLICY",
        amazon_seller_sku="T3-SKU",
        amazon_asin="B0T3POLICY",
        status="completed",
    )
    product.data = ProductData(item_code="T3-SKU", title="T3 policy fixture", listing_title="T3 listing title")
    modules = [
        {
            "position": index,
            "type": "standard_header_image_text",
            "semantic_role": ["hero", "lifestyle", "feature_proof", "spec_objection", "closing"][index - 1],
            "publish_profile": APLUS_PUBLISH_PROFILE_STANDARD_HEADER_IMAGE_TEXT_V1,
            "lingxing_content_module_type": LINGXING_STANDARD_HEADER_IMAGE_TEXT,
            "headline": f"Module {index}",
            "subheading": f"Subtitle {index}",
            "key_message": f"Key message {index}",
            "text_content": f"Body text {index}",
        }
        for index in range(1, 6)
    ]
    images = []
    for index in range(1, 6):
        path = tmp / f"aplus_{index:02d}.jpg"
        if missing_index != index:
            _image(path, image_size)
        images.append({"status": "done", "path": str(path), "position": index})
    product.aplus = ProductAplus(
        id=501,
        product_id=product.id,
        aplus_status="done",
        aplus_plan=json.dumps({"modules": modules}, ensure_ascii=False),
        aplus_images=json.dumps(images, ensure_ascii=False),
    )
    return product


def _enhanced_modules() -> list[dict]:
    return [
        {
            "position": 1,
            "type": "standard_image_text_overlay",
            "semantic_role": "hero",
            "publish_profile": APLUS_PUBLISH_PROFILE_ENHANCED_BASIC_APLUS_V1,
            "module_spec_key": "image_text_overlay_dark",
            "lingxing_content_module_type": LINGXING_STANDARD_IMAGE_TEXT_OVERLAY,
            "headline": "Hero headline",
            "body": "Hero body copy.",
        },
        {
            "position": 2,
            "type": "standard_three_image_text",
            "semantic_role": "feature_grid",
            "publish_profile": APLUS_PUBLISH_PROFILE_ENHANCED_BASIC_APLUS_V1,
            "module_spec_key": "three_image_text",
            "lingxing_content_module_type": LINGXING_STANDARD_THREE_IMAGE_TEXT,
            "headline": "Feature headline",
            "features": [
                {"headline": "One", "body": "First feature."},
                {"headline": "Two", "body": "Second feature."},
                {"headline": "Three", "body": "Third feature."},
            ],
        },
        {
            "position": 3,
            "type": "standard_single_image_specs_detail",
            "semantic_role": "detail_proof",
            "publish_profile": APLUS_PUBLISH_PROFILE_ENHANCED_BASIC_APLUS_V1,
            "module_spec_key": "single_image_specs_detail",
            "lingxing_content_module_type": LINGXING_STANDARD_SINGLE_IMAGE_SPECS_DETAIL,
            "headline": "Detail headline",
            "description_headline": "Detail description",
            "description_blocks": [
                {"headline": "Block one", "body": "Detail body one."},
                {"headline": "Block two", "body": "Detail body two."},
            ],
            "specification_headline": "Detail specs",
            "specification_list_headline": "Details",
            "spec_items": [
                {"label": "Finish", "value": "Smooth"},
                {"label": "Use", "value": "Daily"},
                {"label": "Care", "value": "Wipe clean"},
            ],
        },
        {
            "position": 4,
            "type": "standard_comparison_table",
            "semantic_role": "comparison",
            "publish_profile": APLUS_PUBLISH_PROFILE_ENHANCED_BASIC_APLUS_V1,
            "module_spec_key": "comparison_table",
            "lingxing_content_module_type": LINGXING_STANDARD_COMPARISON_TABLE,
            "metric_row_labels": ["Setup", "Material", "Care"],
            "current_product_metric_values": ["Fast", "Reinforced", "Easy"],
            "comparison_product_metric_values": ["Slow", "Basic", "Manual"],
            "product_columns": [
                {"asin": "B0POLICY12", "title": "Current product", "highlight": True},
                {"asin": "B0POLICY99", "title": "Comparison product", "highlight": False},
            ],
        },
        {
            "position": 5,
            "type": "standard_tech_specs",
            "semantic_role": "technical_or_closing",
            "publish_profile": APLUS_PUBLISH_PROFILE_ENHANCED_BASIC_APLUS_V1,
            "module_spec_key": "tech_specs",
            "lingxing_content_module_type": LINGXING_STANDARD_TECH_SPECS,
            "headline": "Specs",
            "tableCount": 1,
            "spec_rows": [
                {"label": "Use", "description": "Daily"},
                {"label": "Care", "description": "Wipe clean"},
                {"label": "Fit", "description": "Compact"},
                {"label": "Pack", "description": "One item"},
            ],
        },
    ]


def _enhanced_product_with_aplus(tmp: Path, *, mutate_images=None) -> Product:
    product = Product(
        id=102,
        gigab2b_url="https://example.test/enhanced-policy",
        gigab2b_product_id="T3-ENHANCED",
        amazon_seller_sku="T3-ENHANCED-SKU",
        amazon_asin="B0POLICY12",
        status="completed",
    )
    product.data = ProductData(item_code="T3-ENHANCED-SKU", title="Enhanced policy fixture", listing_title="Enhanced policy title")
    images = []
    for profile_slot in required_image_slots(APLUS_PUBLISH_PROFILE_ENHANCED_BASIC_APLUS_V1):
        slot = profile_slot.slot
        asset_slot_id = f"m{profile_slot.position}_{slot.slot_id.replace('.', '_')}"
        path = tmp / f"{asset_slot_id}.jpg"
        _image(path, (slot.crop_width, slot.crop_height))
        images.append(
            {
                "status": "done",
                "path": str(path),
                "position": profile_slot.position,
                "module_position": profile_slot.position,
                "semantic_role": profile_slot.semantic_role,
                "asset_slot_id": asset_slot_id,
                "slot_id": slot.slot_id,
                "payload_slot": ".".join(slot.payload_path),
                "target_width": slot.crop_width,
                "target_height": slot.crop_height,
                "alt_text": f"{profile_slot.semantic_role} alt",
            }
        )
    if mutate_images:
        images = mutate_images(images, tmp)
    product.aplus = ProductAplus(
        id=502,
        product_id=product.id,
        aplus_status="done",
        aplus_plan=json.dumps(
            {
                "aplus_plan_version": APLUS_PUBLISH_PROFILE_ENHANCED_BASIC_APLUS_V1,
                "publish_profile": APLUS_PUBLISH_PROFILE_ENHANCED_BASIC_APLUS_V1,
                "profile_version": "1",
                "modules": _enhanced_modules(),
            },
            ensure_ascii=False,
        ),
        aplus_images=json.dumps(images, ensure_ascii=False),
    )
    return product


def test_collect_aplus_assets_success_and_fingerprint() -> None:
    with tempfile.TemporaryDirectory() as raw_tmp:
        product = _product_with_aplus(Path(raw_tmp))
        result = collect_aplus_publish_assets(product)
        assert_true(result.ok, f"expected assets ok, got {result.reason_code}: {result.message}")
        assert_true(len(result.assets) == 5, "draft save must collect exactly 5 A+ images")
        assert_true(result.assets[0].alt_text == "Module 1", "alt text should come from A+ plan module headline")
        mapping = preflight_validate(product, result.assets)
        assert_true(mapping.ok, f"module mapping should pass: {mapping.reason_code}")
        fingerprint = build_aplus_content_fingerprint(product.aplus, result.assets, module_mapping_evidence=mapping.evidence)
        assert_true(len(fingerprint) == 64, "content fingerprint should be a sha256 hex digest")
        assert_true(mapping.evidence.get("profile") == APLUS_PUBLISH_PROFILE_STANDARD_HEADER_IMAGE_TEXT_V1, "mapping evidence should record supported publish profile")


def test_collect_enhanced_aplus_assets_success_and_mapper_preflight() -> None:
    with tempfile.TemporaryDirectory() as raw_tmp:
        product = _enhanced_product_with_aplus(Path(raw_tmp))
        result = collect_aplus_publish_assets(product)
        assert_true(result.ok, f"expected enhanced assets ok, got {result.reason_code}: {result.message}")
        assert_true(len(result.assets) == 7, "enhanced profile must collect exactly seven image slots")
        assert_true(
            sorted(asset.slot_id for asset in result.assets)
            == sorted(slot.slot.slot_id for slot in required_image_slots(APLUS_PUBLISH_PROFILE_ENHANCED_BASIC_APLUS_V1)),
            "enhanced policy assets must preserve registry slot ids",
        )
        assert_true(all(asset.semantic_role != "technical_or_closing" for asset in result.assets), "technical specs must not get a placeholder image")
        mapping = preflight_validate(product, result.assets)
        assert_true(mapping.ok, f"enhanced module mapping should pass after policy collection: {mapping.reason_code} {mapping.message}")
        fingerprint = build_aplus_content_fingerprint(product.aplus, result.assets, module_mapping_evidence=mapping.evidence)
        assert_true(len(fingerprint) == 64, "enhanced content fingerprint should be a sha256 hex digest")
        assert_true(mapping.evidence.get("profile") == APLUS_PUBLISH_PROFILE_ENHANCED_BASIC_APLUS_V1, "enhanced mapping evidence should record profile")


def test_module_mapping_failures_are_typed_before_client() -> None:
    with tempfile.TemporaryDirectory() as raw_tmp:
        product = _product_with_aplus(Path(raw_tmp))
        plan = json.loads(product.aplus.aplus_plan)
        plan["modules"][0].pop("publish_profile")
        product.aplus.aplus_plan = json.dumps(plan, ensure_ascii=False)
        assets = collect_aplus_publish_assets(product)
        assert_true(assets.ok, "asset collection should still pass before semantic mapping")
        mapping = preflight_validate(product, assets.assets)
        assert_true(
            not mapping.ok and mapping.reason_code == "unsupported_aplus_publish_profile",
            "old plan without publish_profile must fail closed before client/auth/upload",
        )


def test_collect_aplus_assets_typed_missing_and_small_image() -> None:
    with tempfile.TemporaryDirectory() as raw_tmp:
        missing = collect_aplus_publish_assets(_product_with_aplus(Path(raw_tmp), missing_index=3))
        assert_true(not missing.ok and missing.reason_code == "image_missing", "missing image must be a typed policy reason")

    with tempfile.TemporaryDirectory() as raw_tmp:
        small = collect_aplus_publish_assets(_product_with_aplus(Path(raw_tmp), image_size=(969, 600)))
        assert_true(not small.ok and small.reason_code == "image_too_small", "undersized image must be a typed policy reason")


def test_collect_enhanced_assets_typed_slot_failures() -> None:
    with tempfile.TemporaryDirectory() as raw_tmp:
        missing = collect_aplus_publish_assets(_enhanced_product_with_aplus(Path(raw_tmp), mutate_images=lambda images, _tmp: images[:-1]))
        assert_true(not missing.ok and missing.reason_code == FAILURE_IMAGE_SLOT_MISSING, "missing enhanced slot must be a typed policy reason")

    with tempfile.TemporaryDirectory() as raw_tmp:
        duplicate = collect_aplus_publish_assets(_enhanced_product_with_aplus(Path(raw_tmp), mutate_images=lambda images, _tmp: images + [dict(images[0])]))
        assert_true(not duplicate.ok and duplicate.reason_code == FAILURE_IMAGE_SLOT_DUPLICATE, "duplicate enhanced slot must be a typed policy reason")

    def add_unexpected(images, tmp):
        unexpected_path = tmp / "unexpected.jpg"
        _image(unexpected_path, (970, 300))
        return images + [
            {
                "status": "done",
                "path": str(unexpected_path),
                "position": 1,
                "module_position": 1,
                "semantic_role": "hero",
                "asset_slot_id": "m1_unexpected",
                "slot_id": "unexpected.image",
                "payload_slot": "standardImageTextOverlay.block.image",
                "target_width": 970,
                "target_height": 300,
                "alt_text": "unexpected",
            }
        ]

    with tempfile.TemporaryDirectory() as raw_tmp:
        unexpected = collect_aplus_publish_assets(_enhanced_product_with_aplus(Path(raw_tmp), mutate_images=add_unexpected))
        assert_true(not unexpected.ok and unexpected.reason_code == FAILURE_IMAGE_SLOT_UNEXPECTED, "unexpected enhanced slot must be a typed policy reason")


def test_prerequisites_are_typed_and_protected() -> None:
    catalog = CatalogProduct(
        id=201,
        source_product_id=101,
        gigab2b_url="https://example.test/product",
        gigab2b_product_id="T3-POLICY",
        amazon_seller_sku="T3-SKU",
        amazon_asin=None,
        asin_sync_status="waiting_listing",
        aplus_upload_status="not_uploaded",
    )
    product = Product(id=101, gigab2b_url=catalog.gigab2b_url, gigab2b_product_id="T3-POLICY", amazon_seller_sku="T3-SKU")
    product.aplus = ProductAplus(product_id=101, aplus_status="done")
    catalog.source_product = product
    decision = evaluate_aplus_publish_prerequisites(catalog, store_id="17983", site="US")
    assert_true(not decision.ok and decision.status == "waiting_listing" and decision.reason_code == "asin_not_aligned", "missing ASIN should wait for listing")

    catalog.amazon_asin = "B0T3POLICY"
    product.aplus.aplus_status = "failed"
    decision = evaluate_aplus_publish_prerequisites(catalog, store_id="17983", site="US")
    assert_true(not decision.ok and decision.status == "skipped" and decision.reason_code == "product_aplus_not_done", "A+ not done should be skipped with typed reason")

    product.aplus.aplus_status = "done"
    catalog.aplus_upload_status = "draft_saved"
    decision = evaluate_aplus_publish_prerequisites(catalog, store_id="17983", site="US")
    assert_true(not decision.ok and decision.status == "draft_saved" and decision.protected, "draft_saved should be protected from duplicate drafts")


async def test_draft_client_fails_closed_before_auth_or_request() -> None:
    old_allow = settings.LINGXING_APLUS_ALLOW_REAL_EXTERNAL_CALLS
    old_submit = settings.LINGXING_APLUS_SUBMIT_FOR_APPROVAL
    settings.LINGXING_APLUS_ALLOW_REAL_EXTERNAL_CALLS = False
    settings.LINGXING_APLUS_SUBMIT_FOR_APPROVAL = True
    try:
        product = _product_with_aplus(Path(tempfile.mkdtemp()))
        assets_result = collect_aplus_publish_assets(product)
        mapping = preflight_validate(product, assets_result.assets)
        assert_true(mapping.ok, f"test fixture mapping should pass: {mapping.reason_code}")
        request = LingxingAplusDraftSaveRequest(
            asin="B0T3POLICY",
            seller_sku="T3-SKU",
            document_name="T3 policy",
            store_id="17983",
            site="US",
            assets=assets_result.assets,
            product_id=101,
            product_aplus_id=501,
            content_fingerprint="abc",
            module_mapping=mapping,
        )
        try:
            await LingxingAplusDraftSaveClient().save_draft(request)
        except LingxingAplusDraftSaveClientError as exc:
            assert_true(exc.code == "real_external_calls_disabled", "real client must default fail closed")
        else:
            raise AssertionError("real client should not run when external calls are disabled")
    finally:
        settings.LINGXING_APLUS_ALLOW_REAL_EXTERNAL_CALLS = old_allow
        settings.LINGXING_APLUS_SUBMIT_FOR_APPROVAL = old_submit


async def main() -> None:
    test_collect_aplus_assets_success_and_fingerprint()
    test_collect_enhanced_aplus_assets_success_and_mapper_preflight()
    test_module_mapping_failures_are_typed_before_client()
    test_collect_aplus_assets_typed_missing_and_small_image()
    test_collect_enhanced_assets_typed_slot_failures()
    test_prerequisites_are_typed_and_protected()
    await test_draft_client_fails_closed_before_auth_or_request()


if __name__ == "__main__":
    asyncio.run(main())
