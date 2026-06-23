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
    APLUS_PUBLISH_PROFILE_STANDARD_HEADER_IMAGE_TEXT_V1,
    LINGXING_STANDARD_HEADER_IMAGE_TEXT,
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
    test_module_mapping_failures_are_typed_before_client()
    test_collect_aplus_assets_typed_missing_and_small_image()
    test_prerequisites_are_typed_and_protected()
    await test_draft_client_fails_closed_before_auth_or_request()


if __name__ == "__main__":
    asyncio.run(main())
