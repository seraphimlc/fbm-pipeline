from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from app.aplus_publish.module_registry import (
    APLUS_PUBLISH_PROFILE_STANDARD_HEADER_IMAGE_TEXT_V1,
    FAILURE_ASSET_COUNT_INVALID,
    FAILURE_ASSET_IMAGE_TOO_SMALL,
    FAILURE_ASSET_POSITION_MISMATCH,
    FAILURE_MODULE_BODY_MISSING,
    FAILURE_MODULE_COUNT_INVALID,
    FAILURE_MODULE_HEADLINE_MISSING,
    FAILURE_MODULE_POSITION_DUPLICATE,
    FAILURE_MODULE_POSITION_INVALID,
    FAILURE_MODULE_POSITION_MISMATCH,
    FAILURE_MODULES_INVALID,
    FAILURE_PLAN_MISSING,
    FAILURE_UNSUPPORTED_MODULE_TYPE,
    FAILURE_UNSUPPORTED_PROFILE,
    FAILURE_UPLOAD_ASSET_MISSING_ID,
    INTERNAL_STANDARD_HEADER_IMAGE_TEXT_TYPE,
    LINGXING_STANDARD_HEADER_IMAGE_TEXT,
    STANDARD_HEADER_IMAGE_TEXT_V1,
    SUPPORTED_APLUS_MODULE_COUNT,
    SUPPORTED_POSITIONS,
    AplusPublishModuleSpec,
)


_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]+")
_WHITESPACE_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class LingxingAplusNormalizedModule:
    position: int
    publish_profile: str
    content_module_type: str
    semantic_role: str | None
    headline: str
    subheading: str
    body: str
    alt_text: str
    field_sources: dict[str, str]
    text_evidence: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LingxingAplusModuleMappingResult:
    ok: bool
    modules: list[LingxingAplusNormalizedModule] = field(default_factory=list)
    content_module_list: list[dict[str, Any]] = field(default_factory=list)
    reason_code: str | None = None
    message: str | None = None
    evidence: dict[str, Any] = field(default_factory=dict)


def _json_loads(value: str | dict[str, Any] | list[Any] | None, fallback: Any) -> Any:
    if value is None:
        return fallback
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except Exception:
        return fallback


def _raw_text(value: Any) -> str:
    return str(value if value is not None else "")


def _normalize_text(value: Any, *, max_length: int, field: str, evidence: dict[str, Any]) -> str:
    original = _raw_text(value)
    text = _CONTROL_CHARS_RE.sub(" ", original).strip()
    text = _WHITESPACE_RE.sub(" ", text)
    if len(text) > max_length:
        evidence.setdefault("truncated_fields", {})[field] = {
            "original_length": len(text),
            "final_length": max_length,
        }
        text = text[:max_length].rstrip()
    return text


def _fail(reason_code: str, message: str, evidence: dict[str, Any] | None = None) -> LingxingAplusModuleMappingResult:
    return LingxingAplusModuleMappingResult(
        ok=False,
        reason_code=reason_code,
        message=message,
        evidence=evidence or {},
    )


def _asset_position(asset: Any) -> int | None:
    raw = getattr(asset, "position", None)
    if raw is None and isinstance(asset, dict):
        raw = asset.get("position")
    try:
        return int(raw)
    except Exception:
        return None


def _asset_value(asset: Any, key: str) -> Any:
    if isinstance(asset, dict):
        return asset.get(key)
    return getattr(asset, key, None)


def _product_title(product: Any) -> str:
    data = getattr(product, "data", None)
    title = (
        getattr(data, "listing_title", None)
        or getattr(data, "title", None)
        or getattr(product, "title", None)
        or getattr(product, "amazon_asin", None)
        or "Amazon A+ product"
    )
    return str(title)


def _pick_text(
    module: dict[str, Any],
    sources: tuple[str, ...],
    *,
    product_title: str,
    max_length: int,
    field: str,
    evidence: dict[str, Any],
) -> tuple[str, str | None]:
    for source in sources:
        value = product_title if source == "product_title" else module.get(source)
        text = _normalize_text(value, max_length=max_length, field=field, evidence=evidence)
        if text:
            return text, f"plan.{source}" if source != "product_title" else "product.title"
    return "", None


def _validate_assets(
    assets: list[Any],
    expected_positions: set[int],
    spec: AplusPublishModuleSpec,
) -> LingxingAplusModuleMappingResult | None:
    if len(assets) != SUPPORTED_APLUS_MODULE_COUNT:
        return _fail(
            FAILURE_ASSET_COUNT_INVALID,
            f"A+ 图片数量必须为 {SUPPORTED_APLUS_MODULE_COUNT} 张",
            {"asset_count": len(assets), "required_count": SUPPORTED_APLUS_MODULE_COUNT},
        )
    positions: list[int] = []
    for asset in assets:
        position = _asset_position(asset)
        if position is None:
            return _fail(FAILURE_ASSET_POSITION_MISMATCH, "A+ 图片缺少 position", {"asset": str(asset)})
        positions.append(position)
        width = int(_asset_value(asset, "width") or 0)
        height = int(_asset_value(asset, "height") or 0)
        if width < spec.image_min_width or height < spec.image_min_height:
            return _fail(
                FAILURE_ASSET_IMAGE_TOO_SMALL,
                f"A+ 图片尺寸小于 {spec.image_min_width}x{spec.image_min_height}",
                {
                    "position": position,
                    "width": width,
                    "height": height,
                    "min_width": spec.image_min_width,
                    "min_height": spec.image_min_height,
                },
            )
    if set(positions) != expected_positions:
        return _fail(
            FAILURE_ASSET_POSITION_MISMATCH,
            "A+ 图片 position 必须与 plan modules 一一对应",
            {"module_positions": sorted(expected_positions), "asset_positions": sorted(positions)},
        )
    return None


def preflight_validate(product: Any, assets: list[Any]) -> LingxingAplusModuleMappingResult:
    """Validate publishable A+ content before any Lingxing auth or upload call."""

    product_aplus = getattr(product, "aplus", None)
    if not product_aplus or not getattr(product_aplus, "aplus_plan", None):
        return _fail(FAILURE_PLAN_MISSING, "缺少 A+ plan，不能保存领星草稿")
    plan = _json_loads(getattr(product_aplus, "aplus_plan", None), {})
    if not isinstance(plan, dict):
        return _fail(FAILURE_PLAN_MISSING, "A+ plan JSON 格式无效")
    modules = plan.get("modules")
    if not isinstance(modules, list):
        return _fail(FAILURE_MODULES_INVALID, "A+ plan.modules 必须是数组")
    if len(modules) != SUPPORTED_APLUS_MODULE_COUNT:
        return _fail(
            FAILURE_MODULE_COUNT_INVALID,
            f"A+ plan.modules 必须为 {SUPPORTED_APLUS_MODULE_COUNT} 个",
            {"module_count": len(modules), "required_count": SUPPORTED_APLUS_MODULE_COUNT},
        )

    product_title = _product_title(product)
    normalized: list[LingxingAplusNormalizedModule] = []
    seen: set[int] = set()
    module_positions: set[int] = set()
    field_evidence: dict[str, Any] = {}
    spec = STANDARD_HEADER_IMAGE_TEXT_V1
    for index, module in enumerate(modules, start=1):
        if not isinstance(module, dict):
            return _fail(FAILURE_MODULES_INVALID, "A+ module 必须是对象", {"index": index})
        try:
            position = int(module.get("position"))
        except Exception:
            return _fail(FAILURE_MODULE_POSITION_INVALID, "A+ module position 无效", {"index": index, "position": module.get("position")})
        if position not in SUPPORTED_POSITIONS:
            return _fail(FAILURE_MODULE_POSITION_INVALID, "A+ module position 超出支持范围", {"position": position})
        if position in seen:
            return _fail(FAILURE_MODULE_POSITION_DUPLICATE, "A+ module position 重复", {"position": position})
        if position != index:
            return _fail(
                FAILURE_MODULE_POSITION_MISMATCH,
                "A+ module position 必须按 1..5 顺序排列",
                {"index": index, "position": position},
            )
        seen.add(position)
        module_positions.add(position)

        profile = str(module.get("publish_profile") or "").strip()
        if profile != APLUS_PUBLISH_PROFILE_STANDARD_HEADER_IMAGE_TEXT_V1:
            return _fail(
                FAILURE_UNSUPPORTED_PROFILE,
                "A+ plan 缺少或使用了不支持的 publish_profile",
                {"position": position, "publish_profile": profile or None},
            )
        module_type = str(module.get("lingxing_content_module_type") or "").strip()
        if module_type != LINGXING_STANDARD_HEADER_IMAGE_TEXT:
            return _fail(
                FAILURE_UNSUPPORTED_MODULE_TYPE,
                "A+ plan 缺少或使用了不支持的 Lingxing content module type",
                {"position": position, "lingxing_content_module_type": module_type or None},
            )

        text_evidence: dict[str, Any] = {}
        headline = _normalize_text(
            module.get("headline"),
            max_length=spec.text_policy.headline_max_length,
            field=f"{position}.headline",
            evidence=text_evidence,
        )
        if not headline:
            return _fail(FAILURE_MODULE_HEADLINE_MISSING, "A+ module headline 不能为空", {"position": position})

        body, body_source = _pick_text(
            module,
            spec.body_source_priority,
            product_title=product_title,
            max_length=spec.text_policy.body_max_length,
            field=f"{position}.body",
            evidence=text_evidence,
        )
        if not body:
            return _fail(FAILURE_MODULE_BODY_MISSING, "A+ module body 不能为空", {"position": position})

        subheading = _normalize_text(
            module.get("subheading"),
            max_length=spec.text_policy.subheading_max_length,
            field=f"{position}.subheading",
            evidence=text_evidence,
        )
        subheading_source = "plan.subheading" if subheading else "plan.headline_fallback"
        if not subheading:
            subheading = headline
            text_evidence["subheading_fallback"] = "headline"

        alt_text, alt_source = _pick_text(
            module,
            spec.alt_text_source_priority,
            product_title=product_title,
            max_length=spec.text_policy.alt_text_max_length,
            field=f"{position}.alt_text",
            evidence=text_evidence,
        )
        if not alt_text:
            alt_text = "Amazon A+ product image"
            alt_source = "literal.default"

        field_sources = {
            "headline": "plan.headline",
            "subheading": subheading_source,
            "body": body_source or "plan.text_content",
            "alt_text": alt_source or "plan.headline",
        }
        field_evidence[str(position)] = {
            "field_sources": field_sources,
            "headline_length": len(headline),
            "subheading_length": len(subheading),
            "body_length": len(body),
            "alt_text_length": len(alt_text),
            **text_evidence,
        }
        normalized.append(
            LingxingAplusNormalizedModule(
                position=position,
                publish_profile=profile,
                content_module_type=module_type,
                semantic_role=str(module.get("semantic_role") or "") or None,
                headline=headline,
                subheading=subheading,
                body=body,
                alt_text=alt_text,
                field_sources=field_sources,
                text_evidence=text_evidence,
            )
        )

    asset_failure = _validate_assets(assets, module_positions, spec)
    if asset_failure:
        return asset_failure

    return LingxingAplusModuleMappingResult(
        ok=True,
        modules=normalized,
        evidence={
            "profile": spec.profile_key,
            "content_module_type": spec.content_module_type,
            "module_count": len(normalized),
            "positions": [item.position for item in normalized],
            "field_sources": field_evidence,
            "payload_structure_evidence": spec.payload_evidence,
            "body_text_list_shape": "rich_text_object_list",
            "internal_module_type": INTERNAL_STANDARD_HEADER_IMAGE_TEXT_TYPE,
        },
    )


def _text_object(value: str) -> dict[str, Any]:
    return {"value": value, "decoratorSet": []}


def _uploaded_by_position(uploaded_assets: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    result: dict[int, dict[str, Any]] = {}
    for item in uploaded_assets:
        try:
            position = int(item.get("position"))
        except Exception:
            continue
        result[position] = item
    return result


def assemble_payload(
    preflight_result: LingxingAplusModuleMappingResult,
    uploaded_assets: list[dict[str, Any]],
) -> LingxingAplusModuleMappingResult:
    if not preflight_result.ok:
        return _fail(
            preflight_result.reason_code or FAILURE_MODULES_INVALID,
            preflight_result.message or "A+ module preflight 未通过，不能组装领星 payload",
            preflight_result.evidence,
        )
    uploaded_by_position = _uploaded_by_position(uploaded_assets)
    expected_positions = {module.position for module in preflight_result.modules}
    if set(uploaded_by_position.keys()) != expected_positions:
        return _fail(
            FAILURE_ASSET_POSITION_MISMATCH,
            "上传图片 position 必须与 preflight module 一一对应",
            {"module_positions": sorted(expected_positions), "uploaded_positions": sorted(uploaded_by_position.keys())},
        )

    spec = STANDARD_HEADER_IMAGE_TEXT_V1
    content_modules: list[dict[str, Any]] = []
    for module in preflight_result.modules:
        uploaded = uploaded_by_position[module.position]
        upload_destination_id = str(uploaded.get("uploadDestinationId") or "").strip()
        if not upload_destination_id:
            return _fail(
                FAILURE_UPLOAD_ASSET_MISSING_ID,
                "上传图片缺少 uploadDestinationId",
                {"position": module.position},
            )
        content_modules.append(
            {
                "contentModuleType": module.content_module_type,
                "standardHeaderImageText": {
                    "headline": _text_object(module.headline),
                    "block": {
                        "image": {
                            "uploadDestinationId": upload_destination_id,
                            "altText": module.alt_text,
                            "imageCropSpecification": {
                                "offset": {
                                    "x": {"units": "pixels", "value": 0},
                                    "y": {"units": "pixels", "value": 0},
                                },
                                "size": {
                                    "height": {"units": "pixels", "value": str(spec.image_crop_height)},
                                    "width": {"units": "pixels", "value": str(spec.image_crop_width)},
                                },
                            },
                        },
                        "headline": _text_object(module.subheading),
                        "body": {"textList": [_text_object(module.body)]},
                    },
                },
                "position": module.position,
            }
        )

    return LingxingAplusModuleMappingResult(
        ok=True,
        modules=preflight_result.modules,
        content_module_list=content_modules,
        evidence={
            **preflight_result.evidence,
            "content_module_count": len(content_modules),
            "uploaded_positions": sorted(uploaded_by_position.keys()),
            "crop_size": {"width": spec.image_crop_width, "height": spec.image_crop_height},
        },
    )


def alt_text_by_position(preflight_result: LingxingAplusModuleMappingResult) -> dict[int, str]:
    return {module.position: module.alt_text for module in preflight_result.modules if preflight_result.ok}
