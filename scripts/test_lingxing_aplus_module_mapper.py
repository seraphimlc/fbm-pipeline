from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.aplus_publish.module_registry import (  # noqa: E402
    APLUS_PUBLISH_PROFILE_STANDARD_HEADER_IMAGE_TEXT_V1,
    LINGXING_STANDARD_HEADER_IMAGE_TEXT,
)
from app.models import Product, ProductAplus, ProductData  # noqa: E402
from app.services.lingxing_aplus_module_mapper import assemble_payload, preflight_validate  # noqa: E402
from app.services.lingxing_aplus_publish_policy import AplusPublishAsset  # noqa: E402


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _image(path: Path, size: tuple[int, int] = (1940, 1200)) -> AplusPublishAsset:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, "white").save(path, format="JPEG")
    return AplusPublishAsset(
        position=int(path.stem.split("_")[-1]),
        path=path,
        alt_text="legacy alt",
        width=size[0],
        height=size[1],
        content_type="image/jpeg",
        size=path.stat().st_size,
    )


def _modules(overrides=None):
    overrides = overrides or {}
    modules = []
    for position in range(1, 6):
        module = {
            "position": position,
            "type": "standard_header_image_text",
            "semantic_role": ["hero", "lifestyle", "feature_proof", "spec_objection", "closing"][position - 1],
            "publish_profile": APLUS_PUBLISH_PROFILE_STANDARD_HEADER_IMAGE_TEXT_V1,
            "lingxing_content_module_type": LINGXING_STANDARD_HEADER_IMAGE_TEXT,
            "headline": f"Headline {position}",
            "subheading": f"Subheading {position}",
            "key_message": f"Key message {position}",
            "text_content": f"Body text {position}",
        }
        module.update(overrides.get(position, {}))
        modules.append(module)
    return modules


def _product(modules) -> Product:
    product = Product(id=301, gigab2b_url="https://example.test/mapper", gigab2b_product_id="MAPPER")
    product.data = ProductData(item_code="MAPPER-SKU", title="Mapper product", listing_title="Mapper listing")
    product.aplus = ProductAplus(
        id=701,
        product_id=301,
        aplus_status="done",
        aplus_plan=json.dumps({"modules": modules}, ensure_ascii=False),
    )
    return product


def _assets(tmp: Path, *, size: tuple[int, int] = (1940, 1200)) -> list[AplusPublishAsset]:
    return [_image(tmp / f"aplus_{position}.jpg", size=size) for position in range(1, 6)]


def test_valid_plan_assembles_rich_text_payload() -> None:
    with tempfile.TemporaryDirectory() as raw_tmp:
        product = _product(_modules())
        preflight = preflight_validate(product, _assets(Path(raw_tmp)))
        assert_true(preflight.ok, f"preflight should pass: {preflight.reason_code} {preflight.message}")
        uploaded = [
            {"position": position, "uploadDestinationId": f"UPLOAD-{position}", "width": 1940, "height": 1200}
            for position in range(1, 6)
        ]
        assembled = assemble_payload(preflight, uploaded)
        assert_true(assembled.ok, f"assemble should pass: {assembled.reason_code}")
        assert_true(len(assembled.content_module_list) == 5, "payload should contain exactly 5 modules")
        first = assembled.content_module_list[0]["standardHeaderImageText"]
        assert_true(first["headline"] == {"value": "Headline 1", "decoratorSet": []}, "title must be a rich-text object")
        assert_true(first["block"]["headline"] == {"value": "Subheading 1", "decoratorSet": []}, "subtitle must be a rich-text object")
        assert_true(
            first["block"]["body"]["textList"] == [{"value": "Body text 1", "decoratorSet": []}],
            "body.textList must be rich-text object list, not strings",
        )
        assert_true(first["block"]["image"]["uploadDestinationId"] == "UPLOAD-1", "uploaded id should be injected after upload")


def test_body_fallback_and_subheading_fallback_are_recorded() -> None:
    with tempfile.TemporaryDirectory() as raw_tmp:
        product = _product(_modules({2: {"text_content": " ", "subheading": ""}}))
        result = preflight_validate(product, _assets(Path(raw_tmp)))
        assert_true(result.ok, f"fallback preflight should pass: {result.reason_code}")
        module = result.modules[1]
        assert_true(module.body == "Key message 2", "body should fall back to key_message")
        assert_true(module.subheading == "Headline 2", "empty subtitle should fall back to headline")
        assert_true(result.evidence["field_sources"]["2"]["field_sources"]["body"] == "plan.key_message", "body source should be recorded")


def test_fail_closed_for_missing_text_and_unsupported_contract() -> None:
    with tempfile.TemporaryDirectory() as raw_tmp:
        assets = _assets(Path(raw_tmp))
        missing_headline = preflight_validate(_product(_modules({1: {"headline": ""}})), assets)
        assert_true(not missing_headline.ok and missing_headline.reason_code == "aplus_module_headline_missing", "missing headline should fail closed")

        missing_body = preflight_validate(_product(_modules({1: {"text_content": "", "key_message": ""}})), assets)
        assert_true(not missing_body.ok and missing_body.reason_code == "aplus_module_body_missing", "missing body should fail closed")

        missing_profile = preflight_validate(_product(_modules({1: {"publish_profile": ""}})), assets)
        assert_true(not missing_profile.ok and missing_profile.reason_code == "unsupported_aplus_publish_profile", "missing profile should fail closed")

        bad_type = preflight_validate(_product(_modules({1: {"lingxing_content_module_type": "STANDARD_COMPARISON_TABLE"}})), assets)
        assert_true(not bad_type.ok and bad_type.reason_code == "unsupported_aplus_module_type", "unsupported module type should fail closed")


def test_fail_closed_for_count_position_and_asset_mismatch() -> None:
    with tempfile.TemporaryDirectory() as raw_tmp:
        assets = _assets(Path(raw_tmp))
        count = preflight_validate(_product(_modules()[:4]), assets)
        assert_true(not count.ok and count.reason_code == "aplus_module_count_invalid", "module count must be exactly 5")

        duplicate = _modules()
        duplicate[1]["position"] = 1
        duplicate_result = preflight_validate(_product(duplicate), assets)
        assert_true(not duplicate_result.ok and duplicate_result.reason_code == "aplus_module_position_duplicate", "duplicate position should fail closed")

        mismatched_assets = list(assets)
        mismatched_assets[4] = AplusPublishAsset(
            position=9,
            path=mismatched_assets[4].path,
            alt_text="bad",
            width=mismatched_assets[4].width,
            height=mismatched_assets[4].height,
            content_type=mismatched_assets[4].content_type,
            size=mismatched_assets[4].size,
        )
        asset_result = preflight_validate(_product(_modules()), mismatched_assets)
        assert_true(not asset_result.ok and asset_result.reason_code == "aplus_asset_position_mismatch", "asset position mismatch should fail closed")

    with tempfile.TemporaryDirectory() as raw_tmp:
        small = preflight_validate(_product(_modules()), _assets(Path(raw_tmp), size=(969, 600)))
        assert_true(not small.ok and small.reason_code == "aplus_asset_image_too_small", "small image should fail closed in mapper")


def test_text_normalization_records_truncation() -> None:
    with tempfile.TemporaryDirectory() as raw_tmp:
        long_body = "x" * 650
        product = _product(_modules({1: {"text_content": f"  {long_body}\n\t"}}))
        result = preflight_validate(product, _assets(Path(raw_tmp)))
        assert_true(result.ok, "long text should be truncated, not rejected")
        assert_true(len(result.modules[0].body) == 500, "body should use conservative mapper limit")
        assert_true("truncated_fields" in result.evidence["field_sources"]["1"], "truncation should be recorded in evidence")


def main() -> None:
    test_valid_plan_assembles_rich_text_payload()
    test_body_fallback_and_subheading_fallback_are_recorded()
    test_fail_closed_for_missing_text_and_unsupported_contract()
    test_fail_closed_for_count_position_and_asset_mismatch()
    test_text_normalization_records_truncation()


if __name__ == "__main__":
    main()
