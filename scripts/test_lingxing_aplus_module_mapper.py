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
    APLUS_PUBLISH_PROFILE_ENHANCED_BASIC_APLUS_V1,
    APLUS_PUBLISH_PROFILE_STANDARD_HEADER_IMAGE_TEXT_V1,
    AplusProfileModuleBinding,
    AplusProfileSpec,
    AplusRegistryContractError,
    ENHANCED_BASIC_APLUS_PAYLOAD_EVIDENCE,
    INTERNAL_STANDARD_HEADER_IMAGE_TEXT_TYPE,
    LINGXING_STANDARD_COMPARISON_TABLE,
    LINGXING_STANDARD_HEADER_IMAGE_TEXT,
    LINGXING_STANDARD_IMAGE_TEXT_OVERLAY,
    LINGXING_STANDARD_SINGLE_IMAGE_SPECS_DETAIL,
    LINGXING_STANDARD_TECH_SPECS,
    LINGXING_STANDARD_THREE_IMAGE_TEXT,
    PROFILE_SPECS_BY_KEY,
    FAILURE_MODULE_SPEC_UNREGISTERED,
    FAILURE_PROFILE_MODULE_SEQUENCE_MISMATCH,
    FAILURE_ALT_TEXT_MISSING,
    FAILURE_COMPARISON_COLUMN_ASIN_INVALID,
    FAILURE_COMPARISON_COLUMN_ASIN_MISSING,
    FAILURE_COMPARISON_METRIC_ROWS_INVALID,
    FAILURE_IMAGE_SLOT_DUPLICATE,
    FAILURE_IMAGE_SLOT_MISSING,
    FAILURE_IMAGE_SLOT_UNEXPECTED,
    FAILURE_SPEC_ROWS_INVALID,
    FAILURE_TEXT_FIELD_MISSING,
    get_module_spec_for_binding,
    get_profile_spec,
    get_publish_profile_spec,
    producer_contract_for_profile,
    required_image_slots,
    validate_profile_contract,
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


def _enhanced_modules(overrides=None) -> list[dict]:
    overrides = overrides or {}
    modules = [
        {
            "position": 1,
            "type": "standard_image_text_overlay",
            "semantic_role": "hero",
            "publish_profile": APLUS_PUBLISH_PROFILE_ENHANCED_BASIC_APLUS_V1,
            "profile_version": "1",
            "module_spec_key": "image_text_overlay_dark",
            "lingxing_content_module_type": LINGXING_STANDARD_IMAGE_TEXT_OVERLAY,
            "headline": "Quiet power for daily use",
            "body": "A focused hero message with a strong product promise.",
        },
        {
            "position": 2,
            "type": "standard_three_image_text",
            "semantic_role": "feature_grid",
            "publish_profile": APLUS_PUBLISH_PROFILE_ENHANCED_BASIC_APLUS_V1,
            "profile_version": "1",
            "module_spec_key": "three_image_text",
            "lingxing_content_module_type": LINGXING_STANDARD_THREE_IMAGE_TEXT,
            "headline": "Three reasons it fits the routine",
            "features": [
                {"headline": "Fast setup", "body": "Ready quickly without extra tools."},
                {"headline": "Stable build", "body": "Designed for repeatable daily handling."},
                {"headline": "Easy care", "body": "Simple surfaces make cleanup straightforward."},
            ],
        },
        {
            "position": 3,
            "type": "standard_single_image_specs_detail",
            "semantic_role": "detail_proof",
            "publish_profile": APLUS_PUBLISH_PROFILE_ENHANCED_BASIC_APLUS_V1,
            "profile_version": "1",
            "module_spec_key": "single_image_specs_detail",
            "lingxing_content_module_type": LINGXING_STANDARD_SINGLE_IMAGE_SPECS_DETAIL,
            "headline": "Details you can check",
            "description_headline": "Built for practical use",
            "description_blocks": [
                {"headline": "Material focus", "body": "The detail view highlights the finish and contact points."},
                {"headline": "Use case", "body": "Helpful where compact storage and reliable use matter."},
            ],
            "specification_headline": "Detail summary",
            "specification_list_headline": "What to notice",
            "spec_items": [
                {"label": "Finish", "value": "Smooth, easy-care surface"},
                {"label": "Handling", "value": "Balanced shape for repeat use"},
                {"label": "Storage", "value": "Compact profile for shelves"},
            ],
            "specification_text_headline": "Design note",
            "spec_note": "Confirm final claims against source product facts before publishing.",
        },
        {
            "position": 4,
            "type": "standard_comparison_table",
            "semantic_role": "comparison",
            "publish_profile": APLUS_PUBLISH_PROFILE_ENHANCED_BASIC_APLUS_V1,
            "profile_version": "1",
            "module_spec_key": "comparison_table",
            "lingxing_content_module_type": LINGXING_STANDARD_COMPARISON_TABLE,
            "headline": "Compare the details",
            "metric_row_labels": ["Setup", "Material", "Care"],
            "current_product_metric_values": ["Tool-free", "Reinforced", "Wipe clean"],
            "comparison_product_metric_values": ["Requires extras", "Basic", "Hand wash"],
            "product_columns": [
                {"column_key": "current_product", "asin": "B0ABCDEF12", "title": "Current product", "highlight": True},
                {"column_key": "comparison_product", "asin": "B0ZZZZZZ99", "title": "Common alternative", "highlight": False},
            ],
        },
        {
            "position": 5,
            "type": "standard_tech_specs",
            "semantic_role": "technical_or_closing",
            "publish_profile": APLUS_PUBLISH_PROFILE_ENHANCED_BASIC_APLUS_V1,
            "profile_version": "1",
            "module_spec_key": "tech_specs",
            "lingxing_content_module_type": LINGXING_STANDARD_TECH_SPECS,
            "headline": "Technical specs",
            "tableCount": 1,
            "spec_rows": [
                {"label": "Use", "description": "Everyday indoor routines"},
                {"label": "Care", "description": "Wipe clean as needed"},
                {"label": "Fit", "description": "Compact storage profile"},
                {"label": "Pack", "description": "Ships as one ready-to-use item"},
            ],
        },
    ]
    for position, values in overrides.items():
        modules[position - 1].update(values)
    return modules


def _enhanced_product(modules: list[dict] | None = None) -> Product:
    product = Product(id=302, gigab2b_url="https://example.test/enhanced", gigab2b_product_id="ENHANCED", amazon_asin="B0ABCDEF12")
    product.data = ProductData(item_code="ENHANCED-SKU", title="Enhanced product", listing_title="Enhanced listing")
    product.aplus = ProductAplus(
        id=702,
        product_id=302,
        aplus_status="done",
        aplus_plan=json.dumps(
            {
                "aplus_plan_version": APLUS_PUBLISH_PROFILE_ENHANCED_BASIC_APLUS_V1,
                "publish_profile": APLUS_PUBLISH_PROFILE_ENHANCED_BASIC_APLUS_V1,
                "profile_version": "1",
                "modules": modules or _enhanced_modules(),
            },
            ensure_ascii=False,
        ),
    )
    return product


def _enhanced_assets(tmp: Path, *, alt_text: str = "enhanced slot alt") -> list[AplusPublishAsset]:
    assets: list[AplusPublishAsset] = []
    for profile_slot in required_image_slots(APLUS_PUBLISH_PROFILE_ENHANCED_BASIC_APLUS_V1):
        slot = profile_slot.slot
        asset_slot_id = f"m{profile_slot.position}_{slot.slot_id.replace('.', '_')}"
        path = tmp / f"{asset_slot_id}.jpg"
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (slot.crop_width, slot.crop_height), "white").save(path, format="JPEG")
        assets.append(
            AplusPublishAsset(
                position=profile_slot.position,
                module_position=profile_slot.position,
                path=path,
                alt_text=alt_text,
                width=slot.crop_width,
                height=slot.crop_height,
                content_type="image/jpeg",
                size=path.stat().st_size,
                asset_slot_id=asset_slot_id,
                slot_id=slot.slot_id,
                semantic_role=profile_slot.semantic_role,
                payload_slot=".".join(slot.payload_path),
                target_width=slot.crop_width,
                target_height=slot.crop_height,
                min_width=slot.min_width,
                min_height=slot.min_height,
            )
        )
    return assets


def _uploaded_enhanced(assets: list[AplusPublishAsset]) -> list[dict]:
    return [
        {
            "asset_slot_id": asset.asset_slot_id,
            "uploadDestinationId": f"UPLOAD-{asset.asset_slot_id}",
            "width": asset.width,
            "height": asset.height,
        }
        for asset in assets
    ]


def test_registry_enhanced_profile_sequence_contract() -> None:
    profile = get_profile_spec(APLUS_PUBLISH_PROFILE_ENHANCED_BASIC_APLUS_V1)
    assert_true(profile is not None, "enhanced profile must be registry-backed")
    sequence = [
        (
            binding.position,
            binding.semantic_role,
            get_module_spec_for_binding(
                APLUS_PUBLISH_PROFILE_ENHANCED_BASIC_APLUS_V1,
                binding.position,
                {
                    "image_text_overlay_dark": LINGXING_STANDARD_IMAGE_TEXT_OVERLAY,
                    "three_image_text": LINGXING_STANDARD_THREE_IMAGE_TEXT,
                    "single_image_specs_detail": LINGXING_STANDARD_SINGLE_IMAGE_SPECS_DETAIL,
                    "comparison_table": LINGXING_STANDARD_COMPARISON_TABLE,
                    "tech_specs": LINGXING_STANDARD_TECH_SPECS,
                }[binding.module_spec_key],
            ),
        )
        for binding in profile.module_sequence
    ]
    assert_true([item[0] for item in sequence] == [1, 2, 3, 4, 5], "enhanced profile positions must be fixed")
    assert_true(
        [item[1] for item in sequence] == ["hero", "feature_grid", "detail_proof", "comparison", "technical_or_closing"],
        "enhanced profile semantic roles must be fixed",
    )
    assert_true(
        [item[2].content_module_type for item in sequence if item[2]]
        == [
            LINGXING_STANDARD_IMAGE_TEXT_OVERLAY,
            LINGXING_STANDARD_THREE_IMAGE_TEXT,
            LINGXING_STANDARD_SINGLE_IMAGE_SPECS_DETAIL,
            LINGXING_STANDARD_COMPARISON_TABLE,
            LINGXING_STANDARD_TECH_SPECS,
        ],
        "enhanced profile must bind to the five confirmed Lingxing basic modules",
    )
    hero_spec = sequence[0][2]
    assert_true(hero_spec.fixed_values == {"overlayColorType": "DARK"}, "hero overlay must be fixed to DARK")


def test_registry_enhanced_image_slots_and_module_constraints() -> None:
    slots = required_image_slots(APLUS_PUBLISH_PROFILE_ENHANCED_BASIC_APLUS_V1)
    assert_true(len(slots) == 7, "enhanced V1 must require exactly 7 image slots")
    slot_shapes = {
        item.slot.slot_id: (item.position, item.semantic_role, item.slot.crop_width, item.slot.crop_height)
        for item in slots
    }
    assert_true(slot_shapes["hero.image"] == (1, "hero", 970, 300), "hero slot must be 970x300")
    assert_true(slot_shapes["feature_1.image"] == (2, "feature_grid", 300, 300), "feature slot 1 must be 300x300")
    assert_true(slot_shapes["feature_2.image"] == (2, "feature_grid", 300, 300), "feature slot 2 must be 300x300")
    assert_true(slot_shapes["feature_3.image"] == (2, "feature_grid", 300, 300), "feature slot 3 must be 300x300")
    assert_true(slot_shapes["detail.image"] == (3, "detail_proof", 300, 300), "detail slot must be 300x300")
    assert_true(slot_shapes["comparison.column_1.image"] == (4, "comparison", 150, 300), "comparison column 1 must be 150x300")
    assert_true(slot_shapes["comparison.column_2.image"] == (4, "comparison", 150, 300), "comparison column 2 must be 150x300")

    contract = producer_contract_for_profile(APLUS_PUBLISH_PROFILE_ENHANCED_BASIC_APLUS_V1)
    assert_true(contract is not None and contract.module_count == 5, "producer contract must expose five modules")
    modules = {module.semantic_role: module for module in contract.modules}
    assert_true(modules["technical_or_closing"].required_image_slots == (), "tech specs must not require an image")
    assert_true(modules["comparison"].comparison.min_columns == 2, "comparison must require two columns")
    assert_true(modules["comparison"].comparison.max_columns == 2, "enhanced V1 comparison must be fixed to two columns")
    assert_true(modules["comparison"].comparison.min_metric_rows == 3, "comparison must require at least three metric rows")
    assert_true(modules["technical_or_closing"].spec_table.min_rows == 4, "tech specs must require at least four rows")
    assert_true(modules["technical_or_closing"].spec_table.max_rows == 16, "tech specs must cap rows at sixteen")
    for module in contract.modules:
        spec = get_module_spec_for_binding(contract.profile_key, module.position, module.lingxing_content_module_type)
        assert_true(spec.payload_evidence == ENHANCED_BASIC_APLUS_PAYLOAD_EVIDENCE, f"{module.semantic_role} must carry M3.0 evidence")
        for slot in spec.image_slots:
            assert_true(slot.alt_text_required and slot.alt_text_max_length == 100, f"{slot.slot_id} must require <=100 alt text")


def test_registry_old_profile_compatibility_contract() -> None:
    legacy_publish_spec = get_publish_profile_spec(APLUS_PUBLISH_PROFILE_STANDARD_HEADER_IMAGE_TEXT_V1)
    assert_true(legacy_publish_spec is not None, "legacy M2 publish profile lookup must remain supported")
    assert_true(legacy_publish_spec.content_module_type == LINGXING_STANDARD_HEADER_IMAGE_TEXT, "legacy content type must be unchanged")
    assert_true(legacy_publish_spec.image_min_width == 970 and legacy_publish_spec.image_min_height == 600, "legacy image dimensions must be unchanged")

    legacy_profile = get_profile_spec(APLUS_PUBLISH_PROFILE_STANDARD_HEADER_IMAGE_TEXT_V1)
    assert_true(legacy_profile is not None and legacy_profile.module_count == 5, "legacy profile contract must expose five modules")
    assert_true(
        [binding.semantic_role for binding in legacy_profile.module_sequence]
        == ["hero", "lifestyle", "feature_proof", "spec_objection", "closing"],
        "legacy semantic roles must be unchanged",
    )
    legacy_contract = producer_contract_for_profile(APLUS_PUBLISH_PROFILE_STANDARD_HEADER_IMAGE_TEXT_V1)
    assert_true(
        all(module.module_spec_key == INTERNAL_STANDARD_HEADER_IMAGE_TEXT_TYPE for module in legacy_contract.modules),
        "legacy producer contract must still use standard header image text",
    )


def test_registry_contract_fails_for_broken_registered_profiles() -> None:
    missing_spec_key = "test_missing_module_spec_profile"
    PROFILE_SPECS_BY_KEY[missing_spec_key] = AplusProfileSpec(
        profile_key=missing_spec_key,
        profile_version="test",
        tier="basic",
        module_count=1,
        module_sequence=(
            AplusProfileModuleBinding(1, "hero", "missing_module_type", "missing_module_spec"),
        ),
        payload_evidence="test",
    )
    try:
        try:
            producer_contract_for_profile(missing_spec_key)
        except AplusRegistryContractError as exc:
            assert_true(exc.reason_code == FAILURE_MODULE_SPEC_UNREGISTERED, "orphan binding must fail with module spec reason")
        else:
            raise AssertionError("orphan profile binding must not produce a truncated contract")
    finally:
        PROFILE_SPECS_BY_KEY.pop(missing_spec_key, None)

    mismatch_key = "test_module_count_mismatch_profile"
    PROFILE_SPECS_BY_KEY[mismatch_key] = AplusProfileSpec(
        profile_key=mismatch_key,
        profile_version="test",
        tier="basic",
        module_count=2,
        module_sequence=(
            AplusProfileModuleBinding(1, "hero", INTERNAL_STANDARD_HEADER_IMAGE_TEXT_TYPE, INTERNAL_STANDARD_HEADER_IMAGE_TEXT_TYPE),
        ),
        payload_evidence="test",
    )
    try:
        try:
            validate_profile_contract(mismatch_key)
        except AplusRegistryContractError as exc:
            assert_true(exc.reason_code == FAILURE_PROFILE_MODULE_SEQUENCE_MISMATCH, "module count mismatch must fail as sequence mismatch")
        else:
            raise AssertionError("module_count mismatch must not validate as a usable profile")
    finally:
        PROFILE_SPECS_BY_KEY.pop(mismatch_key, None)


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


def test_valid_enhanced_plan_assembles_five_confirmed_payload_subtrees() -> None:
    with tempfile.TemporaryDirectory() as raw_tmp:
        assets = _enhanced_assets(Path(raw_tmp))
        preflight = preflight_validate(_enhanced_product(), assets)
        assert_true(preflight.ok, f"enhanced preflight should pass: {preflight.reason_code} {preflight.message}")
        assembled = assemble_payload(preflight, _uploaded_enhanced(assets))
        assert_true(assembled.ok, f"enhanced assemble should pass: {assembled.reason_code} {assembled.message}")
        assert_true(
            [item["contentModuleType"] for item in assembled.content_module_list]
            == [
                LINGXING_STANDARD_IMAGE_TEXT_OVERLAY,
                LINGXING_STANDARD_THREE_IMAGE_TEXT,
                LINGXING_STANDARD_SINGLE_IMAGE_SPECS_DETAIL,
                LINGXING_STANDARD_COMPARISON_TABLE,
                LINGXING_STANDARD_TECH_SPECS,
            ],
            "enhanced payload must contain the five confirmed modules in order",
        )
        hero = assembled.content_module_list[0]["standardImageTextOverlay"]
        assert_true(hero["overlayColorType"] == "DARK", "hero overlay must be dark")
        assert_true(hero["block"]["image"]["imageCropSpecification"]["size"]["height"]["value"] == "300", "hero crop must be 970x300")
        feature = assembled.content_module_list[1]["standardThreeImageText"]
        assert_true(feature["block3"]["body"]["textList"][0]["value"] == "Simple surfaces make cleanup straightforward.", "feature block text must be mapped")
        detail = assembled.content_module_list[2]["standardSingleImageSpecsDetail"]
        assert_true(detail["specificationListBlock"]["block"]["textList"][2]["position"] == 3, "detail spec rows must preserve positions")
        comparison = assembled.content_module_list[3]["standardComparisonTable"]
        assert_true(len(comparison["productColumns"]) == 2, "comparison must contain two product columns")
        assert_true(comparison["productColumns"][1]["asin"] == "B0ZZZZZZ99", "comparison ASIN must be mapped")
        assert_true(comparison["productColumns"][0]["metrics"][0]["value"] == "Tool-free", "comparison metric values must be mapped")
        tech = assembled.content_module_list[4]["standardTechSpecs"]
        assert_true("image" not in tech, "technical specs must not receive a placeholder image")
        assert_true(len(tech["specificationList"]) == 4, "tech specs must contain 4+ rows")


def test_enhanced_slot_failures_are_typed() -> None:
    with tempfile.TemporaryDirectory() as raw_tmp:
        assets = _enhanced_assets(Path(raw_tmp))
        missing = preflight_validate(_enhanced_product(), assets[:-1])
        assert_true(not missing.ok and missing.reason_code == FAILURE_IMAGE_SLOT_MISSING, "missing enhanced slot must fail closed")

        duplicate_assets = assets + [assets[0]]
        duplicate = preflight_validate(_enhanced_product(), duplicate_assets)
        assert_true(not duplicate.ok and duplicate.reason_code == FAILURE_IMAGE_SLOT_DUPLICATE, "duplicate enhanced slot must fail closed")

        unexpected_asset = AplusPublishAsset(
            position=1,
            module_position=1,
            path=assets[0].path,
            alt_text="unexpected",
            width=970,
            height=300,
            content_type="image/jpeg",
            size=assets[0].size,
            asset_slot_id="m1_unexpected",
            slot_id="unexpected.image",
            payload_slot="standardImageTextOverlay.block.image",
        )
        unexpected = preflight_validate(_enhanced_product(), assets + [unexpected_asset])
        assert_true(not unexpected.ok and unexpected.reason_code == FAILURE_IMAGE_SLOT_UNEXPECTED, "unexpected enhanced slot must fail closed")

        no_alt = _enhanced_assets(Path(raw_tmp) / "no-alt", alt_text="")
        alt_result = preflight_validate(_enhanced_product(), no_alt)
        assert_true(not alt_result.ok and alt_result.reason_code == FAILURE_ALT_TEXT_MISSING, "missing enhanced alt text must fail closed")


def test_enhanced_text_comparison_and_spec_failures_are_typed() -> None:
    with tempfile.TemporaryDirectory() as raw_tmp:
        assets = _enhanced_assets(Path(raw_tmp))
        missing_text = preflight_validate(_enhanced_product(_enhanced_modules({1: {"body": ""}})), assets)
        assert_true(not missing_text.ok and missing_text.reason_code == FAILURE_TEXT_FIELD_MISSING, "missing hero body must fail closed")

        missing_second_asin_modules = _enhanced_modules()
        missing_second_asin_modules[3]["product_columns"][1]["asin"] = ""
        missing_asin = preflight_validate(_enhanced_product(missing_second_asin_modules), assets)
        assert_true(not missing_asin.ok and missing_asin.reason_code == FAILURE_COMPARISON_COLUMN_ASIN_MISSING, "missing comparison ASIN must fail closed")

        bad_asin_modules = _enhanced_modules()
        bad_asin_modules[3]["product_columns"][1]["asin"] = "TOO-SHORT"
        bad_asin = preflight_validate(_enhanced_product(bad_asin_modules), assets)
        assert_true(not bad_asin.ok and bad_asin.reason_code == FAILURE_COMPARISON_COLUMN_ASIN_INVALID, "invalid comparison ASIN must fail closed")

        metric_mismatch_modules = _enhanced_modules({4: {"comparison_product_metric_values": ["Only one"]}})
        metric_mismatch = preflight_validate(_enhanced_product(metric_mismatch_modules), assets)
        assert_true(not metric_mismatch.ok and metric_mismatch.reason_code == FAILURE_COMPARISON_METRIC_ROWS_INVALID, "metric row mismatch must fail closed")

        short_specs_modules = _enhanced_modules({5: {"spec_rows": [{"label": "Use", "description": "Daily"}]}})
        short_specs = preflight_validate(_enhanced_product(short_specs_modules), assets)
        assert_true(not short_specs.ok and short_specs.reason_code == FAILURE_SPEC_ROWS_INVALID, "tech specs with fewer than four rows must fail closed")


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
    test_registry_enhanced_profile_sequence_contract()
    test_registry_enhanced_image_slots_and_module_constraints()
    test_registry_old_profile_compatibility_contract()
    test_registry_contract_fails_for_broken_registered_profiles()
    test_valid_plan_assembles_rich_text_payload()
    test_valid_enhanced_plan_assembles_five_confirmed_payload_subtrees()
    test_enhanced_slot_failures_are_typed()
    test_enhanced_text_comparison_and_spec_failures_are_typed()
    test_body_fallback_and_subheading_fallback_are_recorded()
    test_fail_closed_for_missing_text_and_unsupported_contract()
    test_fail_closed_for_count_position_and_asset_mismatch()
    test_text_normalization_records_truncation()


if __name__ == "__main__":
    main()
