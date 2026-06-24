from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


APLUS_PUBLISH_PROFILE_STANDARD_HEADER_IMAGE_TEXT_V1 = "standard_header_image_text_v1"
APLUS_PUBLISH_PROFILE_ENHANCED_BASIC_APLUS_V1 = "enhanced_basic_aplus_v1"
LINGXING_STANDARD_HEADER_IMAGE_TEXT = "STANDARD_HEADER_IMAGE_TEXT"
LINGXING_STANDARD_IMAGE_TEXT_OVERLAY = "STANDARD_IMAGE_TEXT_OVERLAY"
LINGXING_STANDARD_THREE_IMAGE_TEXT = "STANDARD_THREE_IMAGE_TEXT"
LINGXING_STANDARD_SINGLE_IMAGE_SPECS_DETAIL = "STANDARD_SINGLE_IMAGE_SPECS_DETAIL"
LINGXING_STANDARD_COMPARISON_TABLE = "STANDARD_COMPARISON_TABLE"
LINGXING_STANDARD_TECH_SPECS = "STANDARD_TECH_SPECS"
INTERNAL_STANDARD_HEADER_IMAGE_TEXT_TYPE = "standard_header_image_text"
INTERNAL_STANDARD_IMAGE_TEXT_OVERLAY_TYPE = "standard_image_text_overlay"
INTERNAL_STANDARD_THREE_IMAGE_TEXT_TYPE = "standard_three_image_text"
INTERNAL_STANDARD_SINGLE_IMAGE_SPECS_DETAIL_TYPE = "standard_single_image_specs_detail"
INTERNAL_STANDARD_COMPARISON_TABLE_TYPE = "standard_comparison_table"
INTERNAL_STANDARD_TECH_SPECS_TYPE = "standard_tech_specs"
SUPPORTED_APLUS_MODULE_COUNT = 5
SUPPORTED_POSITIONS = (1, 2, 3, 4, 5)
SEMANTIC_ROLES = ("hero", "lifestyle", "feature_proof", "spec_objection", "closing")
ENHANCED_BASIC_APLUS_SEMANTIC_ROLES = (
    "hero",
    "feature_grid",
    "detail_proof",
    "comparison",
    "technical_or_closing",
)

STANDARD_HEADER_IMAGE_TEXT_PAYLOAD_EVIDENCE = (
    "docs/collaboration/reviews/2026-06-23-lingxing-standard-header-image-text-payload.md"
)
ENHANCED_BASIC_APLUS_PAYLOAD_EVIDENCE = (
    "docs/collaboration/reviews/2026-06-24-lingxing-enhanced-basic-aplus-payload-evidence.md"
)


FAILURE_UNSUPPORTED_PROFILE = "unsupported_aplus_publish_profile"
FAILURE_UNSUPPORTED_MODULE_TYPE = "unsupported_aplus_module_type"
FAILURE_PLAN_MISSING = "aplus_plan_missing"
FAILURE_MODULES_INVALID = "aplus_modules_invalid"
FAILURE_MODULE_COUNT_INVALID = "aplus_module_count_invalid"
FAILURE_MODULE_POSITION_INVALID = "aplus_module_position_invalid"
FAILURE_MODULE_POSITION_DUPLICATE = "aplus_module_position_duplicate"
FAILURE_MODULE_POSITION_MISMATCH = "aplus_module_position_mismatch"
FAILURE_MODULE_HEADLINE_MISSING = "aplus_module_headline_missing"
FAILURE_MODULE_BODY_MISSING = "aplus_module_body_missing"
FAILURE_ASSET_COUNT_INVALID = "aplus_asset_count_invalid"
FAILURE_ASSET_POSITION_MISMATCH = "aplus_asset_position_mismatch"
FAILURE_ASSET_IMAGE_TOO_SMALL = "aplus_asset_image_too_small"
FAILURE_UPLOAD_ASSET_MISSING_ID = "aplus_uploaded_asset_missing_id"
FAILURE_PAYLOAD_STRUCTURE_UNVERIFIED = "lingxing_payload_structure_unverified"
FAILURE_PROFILE_MODULE_SEQUENCE_MISMATCH = "aplus_profile_module_sequence_mismatch"
FAILURE_MODULE_SEMANTIC_ROLE_MISMATCH = "aplus_module_semantic_role_mismatch"
FAILURE_MODULE_SPEC_UNREGISTERED = "aplus_module_spec_unregistered"
FAILURE_IMAGE_SLOT_MISSING = "aplus_image_slot_missing"
FAILURE_IMAGE_SLOT_DUPLICATE = "aplus_image_slot_duplicate"
FAILURE_IMAGE_SLOT_UNEXPECTED = "aplus_image_slot_unexpected"
FAILURE_IMAGE_SLOT_DIMENSION_INVALID = "aplus_image_slot_dimension_invalid"
FAILURE_ALT_TEXT_MISSING = "aplus_alt_text_missing"
FAILURE_ALT_TEXT_TOO_LONG = "aplus_alt_text_too_long"
FAILURE_TEXT_FIELD_MISSING = "aplus_text_field_missing"
FAILURE_TEXT_FIELD_TOO_LONG = "aplus_text_field_too_long"
FAILURE_RICH_TEXT_INVALID = "aplus_rich_text_invalid"
FAILURE_COMPARISON_COLUMN_COUNT_INVALID = "aplus_comparison_column_count_invalid"
FAILURE_COMPARISON_COLUMN_ASIN_MISSING = "aplus_comparison_column_asin_missing"
FAILURE_COMPARISON_COLUMN_ASIN_INVALID = "aplus_comparison_column_asin_invalid"
FAILURE_COMPARISON_METRIC_ROWS_INVALID = "aplus_comparison_metric_rows_invalid"
FAILURE_COMPARISON_METRIC_VALUE_MISSING = "aplus_comparison_metric_value_missing"
FAILURE_SPEC_ROWS_INVALID = "aplus_spec_rows_invalid"
FAILURE_PAYLOAD_BUILDER_MISSING = "aplus_payload_builder_missing"

MAPPER_FAILURE_CODES = (
    FAILURE_UNSUPPORTED_PROFILE,
    FAILURE_UNSUPPORTED_MODULE_TYPE,
    FAILURE_PLAN_MISSING,
    FAILURE_MODULES_INVALID,
    FAILURE_MODULE_COUNT_INVALID,
    FAILURE_MODULE_POSITION_INVALID,
    FAILURE_MODULE_POSITION_DUPLICATE,
    FAILURE_MODULE_POSITION_MISMATCH,
    FAILURE_MODULE_HEADLINE_MISSING,
    FAILURE_MODULE_BODY_MISSING,
    FAILURE_ASSET_COUNT_INVALID,
    FAILURE_ASSET_POSITION_MISMATCH,
    FAILURE_ASSET_IMAGE_TOO_SMALL,
    FAILURE_UPLOAD_ASSET_MISSING_ID,
    FAILURE_PAYLOAD_STRUCTURE_UNVERIFIED,
    FAILURE_PROFILE_MODULE_SEQUENCE_MISMATCH,
    FAILURE_MODULE_SEMANTIC_ROLE_MISMATCH,
    FAILURE_MODULE_SPEC_UNREGISTERED,
    FAILURE_IMAGE_SLOT_MISSING,
    FAILURE_IMAGE_SLOT_DUPLICATE,
    FAILURE_IMAGE_SLOT_UNEXPECTED,
    FAILURE_IMAGE_SLOT_DIMENSION_INVALID,
    FAILURE_ALT_TEXT_MISSING,
    FAILURE_ALT_TEXT_TOO_LONG,
    FAILURE_TEXT_FIELD_MISSING,
    FAILURE_TEXT_FIELD_TOO_LONG,
    FAILURE_RICH_TEXT_INVALID,
    FAILURE_COMPARISON_COLUMN_COUNT_INVALID,
    FAILURE_COMPARISON_COLUMN_ASIN_MISSING,
    FAILURE_COMPARISON_COLUMN_ASIN_INVALID,
    FAILURE_COMPARISON_METRIC_ROWS_INVALID,
    FAILURE_COMPARISON_METRIC_VALUE_MISSING,
    FAILURE_SPEC_ROWS_INVALID,
    FAILURE_PAYLOAD_BUILDER_MISSING,
)


class AplusRegistryContractError(ValueError):
    def __init__(self, reason_code: str, message: str, evidence: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.reason_code = reason_code
        self.evidence = evidence or {}


@dataclass(frozen=True)
class AplusTextPolicy:
    headline_max_length: int
    subheading_max_length: int
    body_max_length: int
    alt_text_max_length: int
    collapse_whitespace: bool = True


@dataclass(frozen=True)
class AplusImageSlotSpec:
    slot_id: str
    payload_path: tuple[str, ...]
    required: bool
    min_width: int
    min_height: int
    crop_width: int
    crop_height: int
    alt_text_required: bool = True
    alt_text_max_length: int = 100


@dataclass(frozen=True)
class AplusTextFieldSpec:
    field_id: str
    payload_path: tuple[str, ...]
    required: bool
    max_length: int
    rich_text: bool = False
    max_line_length: int | None = None


@dataclass(frozen=True)
class AplusComparisonSpec:
    min_columns: int
    max_columns: int
    min_metric_rows: int
    max_metric_rows: int
    asin_required: bool
    title_max_length: int
    metric_label_max_length: int
    metric_value_max_length: int


@dataclass(frozen=True)
class AplusSpecTableSpec:
    min_rows: int
    max_rows: int
    label_max_length: int
    description_max_length: int
    table_count_values: tuple[int, ...]


@dataclass(frozen=True)
class AplusModuleSpec:
    spec_key: str
    content_module_type: str
    ui_name: str
    payload_key: str
    image_slots: tuple[AplusImageSlotSpec, ...]
    text_fields: tuple[AplusTextFieldSpec, ...]
    comparison: AplusComparisonSpec | None = None
    spec_table: AplusSpecTableSpec | None = None
    fixed_values: dict[str, Any] = field(default_factory=dict)
    payload_evidence: str = ""


@dataclass(frozen=True)
class AplusProfileModuleBinding:
    position: int
    semantic_role: str
    internal_type: str
    module_spec_key: str


@dataclass(frozen=True)
class AplusProfileSpec:
    profile_key: str
    profile_version: str
    tier: str
    module_count: int
    module_sequence: tuple[AplusProfileModuleBinding, ...]
    payload_evidence: str


@dataclass(frozen=True)
class AplusProfileImageSlotSpec:
    position: int
    semantic_role: str
    module_spec_key: str
    slot: AplusImageSlotSpec


@dataclass(frozen=True)
class AplusProducerModuleContract:
    position: int
    semantic_role: str
    internal_type: str
    module_spec_key: str
    lingxing_content_module_type: str
    payload_key: str
    required_image_slots: tuple[str, ...]
    text_fields: tuple[str, ...]
    fixed_values: dict[str, Any]
    comparison: AplusComparisonSpec | None = None
    spec_table: AplusSpecTableSpec | None = None


@dataclass(frozen=True)
class AplusProfileProducerContract:
    profile_key: str
    profile_version: str
    tier: str
    module_count: int
    modules: tuple[AplusProducerModuleContract, ...]
    payload_evidence: str


@dataclass(frozen=True)
class AplusPublishModuleSpec:
    profile_key: str
    content_module_type: str
    ui_name: str
    image_min_width: int
    image_min_height: int
    image_crop_width: int
    image_crop_height: int
    required_fields: tuple[str, ...]
    optional_fields: tuple[str, ...]
    supported_positions: tuple[int, ...]
    body_source_priority: tuple[str, ...]
    alt_text_source_priority: tuple[str, ...]
    text_policy: AplusTextPolicy
    payload_evidence: str


STANDARD_HEADER_IMAGE_TEXT_V1 = AplusPublishModuleSpec(
    profile_key=APLUS_PUBLISH_PROFILE_STANDARD_HEADER_IMAGE_TEXT_V1,
    content_module_type=LINGXING_STANDARD_HEADER_IMAGE_TEXT,
    ui_name="带文字的标准图片标题",
    image_min_width=970,
    image_min_height=600,
    image_crop_width=970,
    image_crop_height=600,
    required_fields=("headline", "body"),
    optional_fields=("subheading",),
    supported_positions=SUPPORTED_POSITIONS,
    body_source_priority=("text_content", "key_message"),
    alt_text_source_priority=("headline", "key_message", "product_title"),
    text_policy=AplusTextPolicy(
        headline_max_length=100,
        subheading_max_length=160,
        body_max_length=500,
        alt_text_max_length=100,
    ),
    payload_evidence=STANDARD_HEADER_IMAGE_TEXT_PAYLOAD_EVIDENCE,
)

LEGACY_STANDARD_HEADER_IMAGE_TEXT_MODULE_SPEC = AplusModuleSpec(
    spec_key=INTERNAL_STANDARD_HEADER_IMAGE_TEXT_TYPE,
    content_module_type=LINGXING_STANDARD_HEADER_IMAGE_TEXT,
    ui_name="带文字的标准图片标题",
    payload_key="standardHeaderImageText",
    image_slots=(
        AplusImageSlotSpec(
            slot_id="module.image",
            payload_path=("standardHeaderImageText", "block", "image"),
            required=True,
            min_width=970,
            min_height=600,
            crop_width=970,
            crop_height=600,
        ),
    ),
    text_fields=(
        AplusTextFieldSpec("headline", ("standardHeaderImageText", "headline"), True, 100),
        AplusTextFieldSpec("subheading", ("standardHeaderImageText", "block", "headline"), False, 160),
        AplusTextFieldSpec("body", ("standardHeaderImageText", "block", "body"), True, 500, rich_text=True),
    ),
    payload_evidence=STANDARD_HEADER_IMAGE_TEXT_PAYLOAD_EVIDENCE,
)

ENHANCED_IMAGE_TEXT_OVERLAY_DARK_SPEC = AplusModuleSpec(
    spec_key="image_text_overlay_dark",
    content_module_type=LINGXING_STANDARD_IMAGE_TEXT_OVERLAY,
    ui_name="标准图片和深文本覆盖",
    payload_key="standardImageTextOverlay",
    image_slots=(
        AplusImageSlotSpec(
            slot_id="hero.image",
            payload_path=("standardImageTextOverlay", "block", "image"),
            required=True,
            min_width=970,
            min_height=300,
            crop_width=970,
            crop_height=300,
        ),
    ),
    text_fields=(
        AplusTextFieldSpec("headline", ("standardImageTextOverlay", "block", "headline"), True, 70),
        AplusTextFieldSpec("body", ("standardImageTextOverlay", "block", "body"), True, 300, rich_text=True, max_line_length=5),
    ),
    fixed_values={"overlayColorType": "DARK"},
    payload_evidence=ENHANCED_BASIC_APLUS_PAYLOAD_EVIDENCE,
)

ENHANCED_THREE_IMAGE_TEXT_SPEC = AplusModuleSpec(
    spec_key="three_image_text",
    content_module_type=LINGXING_STANDARD_THREE_IMAGE_TEXT,
    ui_name="标准三个图片和文本",
    payload_key="standardThreeImageText",
    image_slots=(
        AplusImageSlotSpec("feature_1.image", ("standardThreeImageText", "block1", "image"), True, 300, 300, 300, 300),
        AplusImageSlotSpec("feature_2.image", ("standardThreeImageText", "block2", "image"), True, 300, 300, 300, 300),
        AplusImageSlotSpec("feature_3.image", ("standardThreeImageText", "block3", "image"), True, 300, 300, 300, 300),
    ),
    text_fields=(
        AplusTextFieldSpec("headline", ("standardThreeImageText", "headline"), True, 200),
        AplusTextFieldSpec("block1.headline", ("standardThreeImageText", "block1", "headline"), True, 160),
        AplusTextFieldSpec("block1.body", ("standardThreeImageText", "block1", "body"), True, 1000, rich_text=True, max_line_length=10),
        AplusTextFieldSpec("block2.headline", ("standardThreeImageText", "block2", "headline"), True, 160),
        AplusTextFieldSpec("block2.body", ("standardThreeImageText", "block2", "body"), True, 1000, rich_text=True, max_line_length=10),
        AplusTextFieldSpec("block3.headline", ("standardThreeImageText", "block3", "headline"), True, 160),
        AplusTextFieldSpec("block3.body", ("standardThreeImageText", "block3", "body"), True, 1000, rich_text=True, max_line_length=10),
    ),
    payload_evidence=ENHANCED_BASIC_APLUS_PAYLOAD_EVIDENCE,
)

ENHANCED_SINGLE_IMAGE_SPECS_DETAIL_SPEC = AplusModuleSpec(
    spec_key="single_image_specs_detail",
    content_module_type=LINGXING_STANDARD_SINGLE_IMAGE_SPECS_DETAIL,
    ui_name="标准单一图片和规格详细信息",
    payload_key="standardSingleImageSpecsDetail",
    image_slots=(
        AplusImageSlotSpec(
            "detail.image",
            ("standardSingleImageSpecsDetail", "image"),
            True,
            300,
            300,
            300,
            300,
        ),
    ),
    text_fields=(
        AplusTextFieldSpec("headline", ("standardSingleImageSpecsDetail", "headline"), True, 200),
        AplusTextFieldSpec("description_headline", ("standardSingleImageSpecsDetail", "descriptionHeadline"), True, 160),
        AplusTextFieldSpec("description_block1.headline", ("standardSingleImageSpecsDetail", "descriptionBlock1", "headline"), True, 200),
        AplusTextFieldSpec("description_block1.body", ("standardSingleImageSpecsDetail", "descriptionBlock1", "body"), True, 400, rich_text=True, max_line_length=10),
        AplusTextFieldSpec("description_block2.headline", ("standardSingleImageSpecsDetail", "descriptionBlock2", "headline"), False, 200),
        AplusTextFieldSpec("description_block2.body", ("standardSingleImageSpecsDetail", "descriptionBlock2", "body"), False, 400, rich_text=True, max_line_length=10),
        AplusTextFieldSpec("specification_headline", ("standardSingleImageSpecsDetail", "specificationHeadline"), True, 160),
        AplusTextFieldSpec("specification_list_headline", ("standardSingleImageSpecsDetail", "specificationListBlock", "headline"), True, 160),
        AplusTextFieldSpec("specification_text_headline", ("standardSingleImageSpecsDetail", "specificationTextBlock", "headline"), False, 160),
        AplusTextFieldSpec("specification_text_body", ("standardSingleImageSpecsDetail", "specificationTextBlock", "body"), False, 400, rich_text=True, max_line_length=10),
    ),
    spec_table=AplusSpecTableSpec(
        min_rows=3,
        max_rows=6,
        label_max_length=200,
        description_max_length=400,
        table_count_values=(1,),
    ),
    payload_evidence=ENHANCED_BASIC_APLUS_PAYLOAD_EVIDENCE,
)

ENHANCED_COMPARISON_TABLE_SPEC = AplusModuleSpec(
    spec_key="comparison_table",
    content_module_type=LINGXING_STANDARD_COMPARISON_TABLE,
    ui_name="标准比较图",
    payload_key="standardComparisonTable",
    image_slots=(
        AplusImageSlotSpec("comparison.column_1.image", ("standardComparisonTable", "productColumns", "1", "image"), True, 150, 300, 150, 300),
        AplusImageSlotSpec("comparison.column_2.image", ("standardComparisonTable", "productColumns", "2", "image"), True, 150, 300, 150, 300),
    ),
    text_fields=(),
    comparison=AplusComparisonSpec(
        min_columns=2,
        max_columns=2,
        min_metric_rows=3,
        max_metric_rows=6,
        asin_required=True,
        title_max_length=80,
        metric_label_max_length=100,
        metric_value_max_length=250,
    ),
    payload_evidence=ENHANCED_BASIC_APLUS_PAYLOAD_EVIDENCE,
)

ENHANCED_TECH_SPECS_SPEC = AplusModuleSpec(
    spec_key="tech_specs",
    content_module_type=LINGXING_STANDARD_TECH_SPECS,
    ui_name="标准技术规格",
    payload_key="standardTechSpecs",
    image_slots=(),
    text_fields=(
        AplusTextFieldSpec("headline", ("standardTechSpecs", "headline"), True, 80),
    ),
    spec_table=AplusSpecTableSpec(
        min_rows=4,
        max_rows=16,
        label_max_length=30,
        description_max_length=500,
        table_count_values=(1, 2),
    ),
    payload_evidence=ENHANCED_BASIC_APLUS_PAYLOAD_EVIDENCE,
)

STANDARD_HEADER_IMAGE_TEXT_PROFILE = AplusProfileSpec(
    profile_key=APLUS_PUBLISH_PROFILE_STANDARD_HEADER_IMAGE_TEXT_V1,
    profile_version="1",
    tier="basic",
    module_count=SUPPORTED_APLUS_MODULE_COUNT,
    module_sequence=tuple(
        AplusProfileModuleBinding(
            position=position,
            semantic_role=SEMANTIC_ROLES[position - 1],
            internal_type=INTERNAL_STANDARD_HEADER_IMAGE_TEXT_TYPE,
            module_spec_key=INTERNAL_STANDARD_HEADER_IMAGE_TEXT_TYPE,
        )
        for position in SUPPORTED_POSITIONS
    ),
    payload_evidence=STANDARD_HEADER_IMAGE_TEXT_PAYLOAD_EVIDENCE,
)

ENHANCED_BASIC_APLUS_V1_PROFILE = AplusProfileSpec(
    profile_key=APLUS_PUBLISH_PROFILE_ENHANCED_BASIC_APLUS_V1,
    profile_version="1",
    tier="basic",
    module_count=SUPPORTED_APLUS_MODULE_COUNT,
    module_sequence=(
        AplusProfileModuleBinding(1, "hero", INTERNAL_STANDARD_IMAGE_TEXT_OVERLAY_TYPE, "image_text_overlay_dark"),
        AplusProfileModuleBinding(2, "feature_grid", INTERNAL_STANDARD_THREE_IMAGE_TEXT_TYPE, "three_image_text"),
        AplusProfileModuleBinding(3, "detail_proof", INTERNAL_STANDARD_SINGLE_IMAGE_SPECS_DETAIL_TYPE, "single_image_specs_detail"),
        AplusProfileModuleBinding(4, "comparison", INTERNAL_STANDARD_COMPARISON_TABLE_TYPE, "comparison_table"),
        AplusProfileModuleBinding(5, "technical_or_closing", INTERNAL_STANDARD_TECH_SPECS_TYPE, "tech_specs"),
    ),
    payload_evidence=ENHANCED_BASIC_APLUS_PAYLOAD_EVIDENCE,
)

SUPPORTED_MODULE_SPECS_BY_PROFILE = {
    STANDARD_HEADER_IMAGE_TEXT_V1.profile_key: STANDARD_HEADER_IMAGE_TEXT_V1,
}

SUPPORTED_MODULE_SPECS_BY_TYPE = {
    STANDARD_HEADER_IMAGE_TEXT_V1.content_module_type: STANDARD_HEADER_IMAGE_TEXT_V1,
}

MODULE_SPECS_BY_KEY = {
    LEGACY_STANDARD_HEADER_IMAGE_TEXT_MODULE_SPEC.spec_key: LEGACY_STANDARD_HEADER_IMAGE_TEXT_MODULE_SPEC,
    ENHANCED_IMAGE_TEXT_OVERLAY_DARK_SPEC.spec_key: ENHANCED_IMAGE_TEXT_OVERLAY_DARK_SPEC,
    ENHANCED_THREE_IMAGE_TEXT_SPEC.spec_key: ENHANCED_THREE_IMAGE_TEXT_SPEC,
    ENHANCED_SINGLE_IMAGE_SPECS_DETAIL_SPEC.spec_key: ENHANCED_SINGLE_IMAGE_SPECS_DETAIL_SPEC,
    ENHANCED_COMPARISON_TABLE_SPEC.spec_key: ENHANCED_COMPARISON_TABLE_SPEC,
    ENHANCED_TECH_SPECS_SPEC.spec_key: ENHANCED_TECH_SPECS_SPEC,
}

PROFILE_SPECS_BY_KEY = {
    STANDARD_HEADER_IMAGE_TEXT_PROFILE.profile_key: STANDARD_HEADER_IMAGE_TEXT_PROFILE,
    ENHANCED_BASIC_APLUS_V1_PROFILE.profile_key: ENHANCED_BASIC_APLUS_V1_PROFILE,
}


def get_publish_profile_spec(profile_key: str | None) -> AplusPublishModuleSpec | None:
    return SUPPORTED_MODULE_SPECS_BY_PROFILE.get(str(profile_key or "").strip())


def get_profile_spec(profile_key: str | None) -> AplusProfileSpec | None:
    return PROFILE_SPECS_BY_KEY.get(str(profile_key or "").strip())


def get_module_spec(spec_key: str | None) -> AplusModuleSpec | None:
    return MODULE_SPECS_BY_KEY.get(str(spec_key or "").strip())


def _resolved_profile_bindings(profile: AplusProfileSpec) -> tuple[tuple[AplusProfileModuleBinding, AplusModuleSpec], ...]:
    if profile.module_count != len(profile.module_sequence):
        raise AplusRegistryContractError(
            FAILURE_PROFILE_MODULE_SEQUENCE_MISMATCH,
            "A+ profile module_count must match module_sequence length",
            {
                "profile_key": profile.profile_key,
                "module_count": profile.module_count,
                "sequence_length": len(profile.module_sequence),
            },
        )
    positions = tuple(binding.position for binding in profile.module_sequence)
    expected_positions = tuple(range(1, profile.module_count + 1))
    if positions != expected_positions or len(set(positions)) != len(positions):
        raise AplusRegistryContractError(
            FAILURE_PROFILE_MODULE_SEQUENCE_MISMATCH,
            "A+ profile module_sequence positions must be contiguous and unique",
            {
                "profile_key": profile.profile_key,
                "positions": positions,
                "expected_positions": expected_positions,
            },
        )
    resolved: list[tuple[AplusProfileModuleBinding, AplusModuleSpec]] = []
    for binding in profile.module_sequence:
        spec = get_module_spec(binding.module_spec_key)
        if spec is None:
            raise AplusRegistryContractError(
                FAILURE_MODULE_SPEC_UNREGISTERED,
                "A+ profile binding references an unregistered module spec",
                {
                    "profile_key": profile.profile_key,
                    "position": binding.position,
                    "semantic_role": binding.semantic_role,
                    "module_spec_key": binding.module_spec_key,
                },
            )
        resolved.append((binding, spec))
    return tuple(resolved)


def validate_profile_contract(profile_key: str | None) -> tuple[str, ...]:
    profile = get_profile_spec(profile_key)
    if not profile:
        return ()
    return tuple(binding.module_spec_key for binding, _spec in _resolved_profile_bindings(profile))


def iter_profile_module_specs(profile_key: str | None) -> tuple[AplusModuleSpec, ...]:
    profile = get_profile_spec(profile_key)
    if not profile:
        return ()
    return tuple(spec for _binding, spec in _resolved_profile_bindings(profile))


def get_module_spec_for_binding(
    profile_key: str | None,
    position: int,
    module_type: str | None,
) -> AplusModuleSpec | None:
    profile = get_profile_spec(profile_key)
    if not profile:
        return None
    try:
        expected_position = int(position)
    except Exception:
        return None
    expected_type = str(module_type or "").strip()
    for binding, spec in _resolved_profile_bindings(profile):
        if binding.position != expected_position:
            continue
        if spec and spec.content_module_type == expected_type:
            return spec
        return None
    return None


def required_image_slots(profile_key: str | None) -> tuple[AplusProfileImageSlotSpec, ...]:
    profile = get_profile_spec(profile_key)
    if not profile:
        return ()
    slots: list[AplusProfileImageSlotSpec] = []
    for binding, spec in _resolved_profile_bindings(profile):
        slots.extend(
            AplusProfileImageSlotSpec(
                position=binding.position,
                semantic_role=binding.semantic_role,
                module_spec_key=binding.module_spec_key,
                slot=slot,
            )
            for slot in spec.image_slots
            if slot.required
        )
    return tuple(slots)


def producer_contract_for_profile(profile_key: str | None) -> AplusProfileProducerContract | None:
    profile = get_profile_spec(profile_key)
    if not profile:
        return None
    modules: list[AplusProducerModuleContract] = []
    for binding, spec in _resolved_profile_bindings(profile):
        modules.append(
            AplusProducerModuleContract(
                position=binding.position,
                semantic_role=binding.semantic_role,
                internal_type=binding.internal_type,
                module_spec_key=binding.module_spec_key,
                lingxing_content_module_type=spec.content_module_type,
                payload_key=spec.payload_key,
                required_image_slots=tuple(slot.slot_id for slot in spec.image_slots if slot.required),
                text_fields=tuple(field.field_id for field in spec.text_fields),
                fixed_values=dict(spec.fixed_values),
                comparison=spec.comparison,
                spec_table=spec.spec_table,
            )
        )
    return AplusProfileProducerContract(
        profile_key=profile.profile_key,
        profile_version=profile.profile_version,
        tier=profile.tier,
        module_count=profile.module_count,
        modules=tuple(modules),
        payload_evidence=profile.payload_evidence,
    )


def semantic_role_for_position(position: int) -> str:
    index = max(1, min(int(position), SUPPORTED_APLUS_MODULE_COUNT)) - 1
    return SEMANTIC_ROLES[index]
