from __future__ import annotations

from dataclasses import dataclass


APLUS_PUBLISH_PROFILE_STANDARD_HEADER_IMAGE_TEXT_V1 = "standard_header_image_text_v1"
LINGXING_STANDARD_HEADER_IMAGE_TEXT = "STANDARD_HEADER_IMAGE_TEXT"
INTERNAL_STANDARD_HEADER_IMAGE_TEXT_TYPE = "standard_header_image_text"
SUPPORTED_APLUS_MODULE_COUNT = 5
SUPPORTED_POSITIONS = (1, 2, 3, 4, 5)
SEMANTIC_ROLES = ("hero", "lifestyle", "feature_proof", "spec_objection", "closing")


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
)


@dataclass(frozen=True)
class AplusTextPolicy:
    headline_max_length: int
    subheading_max_length: int
    body_max_length: int
    alt_text_max_length: int
    collapse_whitespace: bool = True


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
    payload_evidence="docs/collaboration/reviews/2026-06-23-lingxing-standard-header-image-text-payload.md",
)

SUPPORTED_MODULE_SPECS_BY_PROFILE = {
    STANDARD_HEADER_IMAGE_TEXT_V1.profile_key: STANDARD_HEADER_IMAGE_TEXT_V1,
}

SUPPORTED_MODULE_SPECS_BY_TYPE = {
    STANDARD_HEADER_IMAGE_TEXT_V1.content_module_type: STANDARD_HEADER_IMAGE_TEXT_V1,
}


def get_publish_profile_spec(profile_key: str | None) -> AplusPublishModuleSpec | None:
    return SUPPORTED_MODULE_SPECS_BY_PROFILE.get(str(profile_key or "").strip())


def semantic_role_for_position(position: int) -> str:
    index = max(1, min(int(position), SUPPORTED_APLUS_MODULE_COUNT)) - 1
    return SEMANTIC_ROLES[index]
