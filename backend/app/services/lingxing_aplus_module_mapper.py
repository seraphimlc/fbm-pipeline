from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.aplus_publish.module_registry import (
    APLUS_PUBLISH_PROFILE_ENHANCED_BASIC_APLUS_V1,
    APLUS_PUBLISH_PROFILE_STANDARD_HEADER_IMAGE_TEXT_V1,
    FAILURE_ASSET_COUNT_INVALID,
    FAILURE_ASSET_IMAGE_TOO_SMALL,
    FAILURE_ASSET_POSITION_MISMATCH,
    FAILURE_ALT_TEXT_MISSING,
    FAILURE_ALT_TEXT_TOO_LONG,
    FAILURE_COMPARISON_COLUMN_ASIN_INVALID,
    FAILURE_COMPARISON_COLUMN_ASIN_MISSING,
    FAILURE_COMPARISON_COLUMN_COUNT_INVALID,
    FAILURE_COMPARISON_METRIC_ROWS_INVALID,
    FAILURE_COMPARISON_METRIC_VALUE_MISSING,
    FAILURE_IMAGE_SLOT_DIMENSION_INVALID,
    FAILURE_IMAGE_SLOT_DUPLICATE,
    FAILURE_IMAGE_SLOT_MISSING,
    FAILURE_IMAGE_SLOT_UNEXPECTED,
    FAILURE_MODULE_BODY_MISSING,
    FAILURE_MODULE_COUNT_INVALID,
    FAILURE_MODULE_HEADLINE_MISSING,
    FAILURE_MODULE_POSITION_DUPLICATE,
    FAILURE_MODULE_POSITION_INVALID,
    FAILURE_MODULE_POSITION_MISMATCH,
    FAILURE_MODULE_SEMANTIC_ROLE_MISMATCH,
    FAILURE_MODULE_SPEC_UNREGISTERED,
    FAILURE_MODULES_INVALID,
    FAILURE_PAYLOAD_BUILDER_MISSING,
    FAILURE_PAYLOAD_STRUCTURE_UNVERIFIED,
    FAILURE_PLAN_MISSING,
    FAILURE_PROFILE_MODULE_SEQUENCE_MISMATCH,
    FAILURE_RICH_TEXT_INVALID,
    FAILURE_SPEC_ROWS_INVALID,
    FAILURE_TEXT_FIELD_MISSING,
    FAILURE_TEXT_FIELD_TOO_LONG,
    FAILURE_UNSUPPORTED_MODULE_TYPE,
    FAILURE_UNSUPPORTED_PROFILE,
    FAILURE_UPLOAD_ASSET_MISSING_ID,
    INTERNAL_STANDARD_COMPARISON_TABLE_TYPE,
    INTERNAL_STANDARD_HEADER_IMAGE_TEXT_TYPE,
    INTERNAL_STANDARD_IMAGE_TEXT_OVERLAY_TYPE,
    INTERNAL_STANDARD_SINGLE_IMAGE_SPECS_DETAIL_TYPE,
    INTERNAL_STANDARD_TECH_SPECS_TYPE,
    INTERNAL_STANDARD_THREE_IMAGE_TEXT_TYPE,
    LINGXING_STANDARD_COMPARISON_TABLE,
    LINGXING_STANDARD_HEADER_IMAGE_TEXT,
    LINGXING_STANDARD_IMAGE_TEXT_OVERLAY,
    LINGXING_STANDARD_SINGLE_IMAGE_SPECS_DETAIL,
    LINGXING_STANDARD_TECH_SPECS,
    LINGXING_STANDARD_THREE_IMAGE_TEXT,
    STANDARD_HEADER_IMAGE_TEXT_V1,
    SUPPORTED_APLUS_MODULE_COUNT,
    SUPPORTED_POSITIONS,
    AplusImageSlotSpec,
    AplusModuleSpec,
    AplusPublishModuleSpec,
    AplusSpecTableSpec,
    AplusTextFieldSpec,
    get_module_spec_for_binding,
    get_profile_spec,
    required_image_slots,
)


_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]+")
_WHITESPACE_RE = re.compile(r"\s+")
_ASIN_RE = re.compile(r"^[A-Z0-9]{10}$")


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
    module_spec_key: str | None = None
    internal_type: str | None = None
    payload_key: str | None = None
    fixed_values: dict[str, Any] = field(default_factory=dict)
    text_fields: dict[str, str] = field(default_factory=dict)
    image_slots: list[dict[str, Any]] = field(default_factory=list)
    comparison_columns: list[dict[str, Any]] = field(default_factory=list)
    metric_row_labels: list[str] = field(default_factory=list)
    spec_rows: list[dict[str, str]] = field(default_factory=list)
    table_count: int | None = None


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


def _plan_profile(plan: dict[str, Any], modules: list[Any]) -> str | None:
    for value in (plan.get("publish_profile"), plan.get("aplus_plan_version")):
        text = str(value or "").strip()
        if text:
            return text
    for module in modules:
        if isinstance(module, dict):
            text = str(module.get("publish_profile") or "").strip()
            if text:
                return text
    return None


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


def _asset_slot_key(asset: Any) -> tuple[int | None, str | None]:
    raw_position = _asset_value(asset, "module_position") or _asset_value(asset, "position")
    try:
        position = int(raw_position)
    except Exception:
        position = None
    slot_id = str(_asset_value(asset, "slot_id") or "").strip() or None
    return position, slot_id


def _payload_slot_from_path(payload_path: tuple[str, ...]) -> str:
    return ".".join(str(item) for item in payload_path)


def _asset_path_exists(asset: Any) -> bool:
    path = _asset_value(asset, "path")
    if isinstance(path, Path):
        return path.is_file()
    if path:
        return Path(str(path)).expanduser().is_file()
    return False


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


def _list_item(items: Any, index: int) -> dict[str, Any]:
    if isinstance(items, list) and index < len(items) and isinstance(items[index], dict):
        return items[index]
    return {}


def _enhanced_raw_field(module: dict[str, Any], field_id: str) -> Any:
    if field_id == "body":
        return module.get("body") or module.get("text_content")
    if field_id.startswith("block"):
        block_index = int(field_id[5]) - 1
        key = field_id.split(".", 1)[1]
        feature = _list_item(module.get("features"), block_index)
        return feature.get(key) or module.get(field_id.replace(".", "_"))
    if field_id.startswith("description_block"):
        block_index = int(field_id[len("description_block")]) - 1
        key = field_id.split(".", 1)[1]
        block = _list_item(module.get("description_blocks"), block_index)
        return block.get(key) or module.get(field_id.replace(".", "_"))
    if field_id == "specification_text_body":
        return module.get("specification_text_body") or module.get("spec_note")
    return module.get(field_id)


def _normalize_enhanced_text_value(raw: Any, field: AplusTextFieldSpec, evidence: dict[str, Any]) -> tuple[str, bool]:
    if raw is None:
        return "", False
    if isinstance(raw, str):
        text = raw
    elif isinstance(raw, (int, float)):
        text = str(raw)
    elif field.rich_text and isinstance(raw, list):
        parts: list[str] = []
        for item in raw:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                parts.append(str(item.get("value") or item.get("text") or item.get("body") or ""))
            else:
                return "", True
        text = " ".join(parts)
    elif field.rich_text and isinstance(raw, dict):
        text = str(raw.get("value") or raw.get("text") or raw.get("body") or "")
    else:
        return "", True
    text = _CONTROL_CHARS_RE.sub(" ", text).strip()
    text = _WHITESPACE_RE.sub(" ", text)
    evidence[f"{field.field_id}_length"] = len(text)
    return text, False


def _validate_enhanced_text_fields(module: dict[str, Any], spec: AplusModuleSpec) -> tuple[dict[str, str], LingxingAplusModuleMappingResult | None]:
    fields: dict[str, str] = {}
    evidence: dict[str, Any] = {}
    for field in spec.text_fields:
        value, invalid = _normalize_enhanced_text_value(_enhanced_raw_field(module, field.field_id), field, evidence)
        if invalid:
            return fields, _fail(
                FAILURE_RICH_TEXT_INVALID if field.rich_text else FAILURE_TEXT_FIELD_MISSING,
                "增强版 A+ 文本字段格式无效",
                {"field_id": field.field_id},
            )
        if field.required and not value:
            return fields, _fail(
                FAILURE_TEXT_FIELD_MISSING,
                "增强版 A+ 必填文本字段为空",
                {"field_id": field.field_id},
            )
        if value and len(value) > field.max_length:
            return fields, _fail(
                FAILURE_TEXT_FIELD_TOO_LONG,
                "增强版 A+ 文本字段超过长度限制",
                {"field_id": field.field_id, "length": len(value), "max_length": field.max_length},
            )
        fields[field.field_id] = value
    return fields, None


def _validate_enhanced_assets(profile_key: str, assets: list[Any]) -> tuple[dict[tuple[int, str], dict[str, Any]], LingxingAplusModuleMappingResult | None]:
    required = required_image_slots(profile_key)
    required_by_key = {(slot.position, slot.slot.slot_id): slot for slot in required}
    seen: dict[tuple[int, str], Any] = {}
    for asset in assets:
        position, slot_id = _asset_slot_key(asset)
        if position is None or slot_id is None:
            return {}, _fail(
                FAILURE_IMAGE_SLOT_UNEXPECTED,
                "增强版 A+ 图片缺少 module_position 或 slot_id",
                {"asset": str(asset)},
            )
        key = (position, slot_id)
        if key not in required_by_key:
            return {}, _fail(FAILURE_IMAGE_SLOT_UNEXPECTED, "增强版 A+ 图片 slot 不在 registry 契约中", {"module_position": position, "slot_id": slot_id})
        if key in seen:
            return {}, _fail(FAILURE_IMAGE_SLOT_DUPLICATE, "增强版 A+ 图片 slot 重复", {"module_position": position, "slot_id": slot_id})
        seen[key] = asset
    missing = sorted(set(required_by_key) - set(seen))
    if missing:
        return {}, _fail(
            FAILURE_IMAGE_SLOT_MISSING,
            "增强版 A+ 图片 slot 不完整",
            {"missing_slots": [{"module_position": position, "slot_id": slot_id} for position, slot_id in missing]},
        )
    result: dict[tuple[int, str], dict[str, Any]] = {}
    for key, profile_slot in required_by_key.items():
        asset = seen[key]
        slot = profile_slot.slot
        width = int(_asset_value(asset, "width") or 0)
        height = int(_asset_value(asset, "height") or 0)
        if width < slot.min_width or height < slot.min_height:
            return {}, _fail(
                FAILURE_IMAGE_SLOT_DIMENSION_INVALID,
                "增强版 A+ 图片尺寸小于 registry 要求",
                {"module_position": key[0], "slot_id": key[1], "width": width, "height": height, "min_width": slot.min_width, "min_height": slot.min_height},
            )
        if not _asset_path_exists(asset):
            return {}, _fail(FAILURE_IMAGE_SLOT_MISSING, "增强版 A+ 图片本地文件不存在", {"module_position": key[0], "slot_id": key[1], "path": str(_asset_value(asset, "path") or "")})
        payload_slot = str(_asset_value(asset, "payload_slot") or "").strip()
        expected_payload_slot = _payload_slot_from_path(slot.payload_path)
        if payload_slot != expected_payload_slot:
            return {}, _fail(
                FAILURE_IMAGE_SLOT_UNEXPECTED,
                "增强版 A+ 图片 payload_slot 与 registry 不一致",
                {"module_position": key[0], "slot_id": key[1], "payload_slot": payload_slot, "expected_payload_slot": expected_payload_slot},
            )
        alt_text = str(_asset_value(asset, "alt_text") or "").strip()
        if slot.alt_text_required and not alt_text:
            return {}, _fail(FAILURE_ALT_TEXT_MISSING, "增强版 A+ 图片 alt text 不能为空", {"module_position": key[0], "slot_id": key[1]})
        if len(alt_text) > slot.alt_text_max_length:
            return {}, _fail(
                FAILURE_ALT_TEXT_TOO_LONG,
                "增强版 A+ 图片 alt text 超过长度限制",
                {"module_position": key[0], "slot_id": key[1], "length": len(alt_text), "max_length": slot.alt_text_max_length},
            )
        asset_slot_id = str(_asset_value(asset, "asset_slot_id") or "").strip()
        if not asset_slot_id:
            return {}, _fail(FAILURE_IMAGE_SLOT_UNEXPECTED, "增强版 A+ 图片缺少 asset_slot_id", {"module_position": key[0], "slot_id": key[1]})
        result[key] = {
            "asset_slot_id": asset_slot_id,
            "slot_id": slot.slot_id,
            "payload_slot": payload_slot,
            "alt_text": alt_text,
            "crop_width": slot.crop_width,
            "crop_height": slot.crop_height,
            "width": width,
            "height": height,
        }
    return result, None


def _clean_enhanced_rows(raw_rows: Any, *, label_key: str = "label", value_key: str = "description") -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    if not isinstance(raw_rows, list):
        return rows
    for raw in raw_rows:
        if not isinstance(raw, dict):
            continue
        label = _CONTROL_CHARS_RE.sub(" ", str(raw.get(label_key) or raw.get("name") or raw.get("headline") or "")).strip()
        value = _CONTROL_CHARS_RE.sub(" ", str(raw.get(value_key) or raw.get("value") or raw.get("body") or "")).strip()
        label = _WHITESPACE_RE.sub(" ", label)
        value = _WHITESPACE_RE.sub(" ", value)
        if label or value:
            rows.append({"label": label, "description": value})
    return rows


def _validate_spec_rows(rows: list[dict[str, str]], spec_table: AplusSpecTableSpec, *, position: int) -> LingxingAplusModuleMappingResult | None:
    if len(rows) < spec_table.min_rows or len(rows) > spec_table.max_rows:
        return _fail(
            FAILURE_SPEC_ROWS_INVALID,
            "增强版 A+ 规格行数不符合 registry 要求",
            {"position": position, "row_count": len(rows), "min_rows": spec_table.min_rows, "max_rows": spec_table.max_rows},
        )
    for index, row in enumerate(rows, 1):
        label = row.get("label") or ""
        description = row.get("description") or ""
        if not label or not description:
            return _fail(FAILURE_SPEC_ROWS_INVALID, "增强版 A+ 规格行不能只有 label 或 description", {"position": position, "row_index": index})
        if len(label) > spec_table.label_max_length or len(description) > spec_table.description_max_length:
            return _fail(
                FAILURE_SPEC_ROWS_INVALID,
                "增强版 A+ 规格行超过长度限制",
                {
                    "position": position,
                    "row_index": index,
                    "label_length": len(label),
                    "description_length": len(description),
                    "label_max_length": spec_table.label_max_length,
                    "description_max_length": spec_table.description_max_length,
                },
            )
    return None


def _comparison_values(module: dict[str, Any], column_index: int, label_count: int) -> list[str]:
    columns = module.get("product_columns")
    column = _list_item(columns, column_index)
    raw_metrics = column.get("metrics")
    if isinstance(raw_metrics, list):
        values = []
        for item in raw_metrics:
            if isinstance(item, dict):
                values.append(str(item.get("value") or "").strip())
            else:
                values.append(str(item or "").strip())
        return values
    key = "current_product_metric_values" if column_index == 0 else "comparison_product_metric_values"
    raw = module.get(key)
    if isinstance(raw, list):
        return [str(item or "").strip() for item in raw]
    return [""] * label_count


def _validate_comparison(module: dict[str, Any], spec: AplusModuleSpec, *, position: int) -> tuple[list[dict[str, Any]], list[str], LingxingAplusModuleMappingResult | None]:
    comparison = spec.comparison
    if comparison is None:
        return [], [], None
    columns = module.get("product_columns")
    if not isinstance(columns, list) or len(columns) != comparison.min_columns or len(columns) != comparison.max_columns:
        return [], [], _fail(
            FAILURE_COMPARISON_COLUMN_COUNT_INVALID,
            "增强版 A+ 比较图必须包含 2 个产品列",
            {"position": position, "column_count": len(columns) if isinstance(columns, list) else None},
        )
    raw_labels = module.get("metric_row_labels")
    if not isinstance(raw_labels, list):
        return [], [], _fail(FAILURE_COMPARISON_METRIC_ROWS_INVALID, "增强版 A+ 比较图缺少 metric row labels", {"position": position})
    labels = [
        _WHITESPACE_RE.sub(" ", _CONTROL_CHARS_RE.sub(" ", str(item or "")).strip())
        for item in raw_labels
        if _WHITESPACE_RE.sub(" ", _CONTROL_CHARS_RE.sub(" ", str(item or "")).strip())
    ]
    if len(labels) < comparison.min_metric_rows or len(labels) > comparison.max_metric_rows:
        return [], [], _fail(
            FAILURE_COMPARISON_METRIC_ROWS_INVALID,
            "增强版 A+ 比较图 metric row 数量不符合 registry 要求",
            {"position": position, "metric_row_count": len(labels), "min_rows": comparison.min_metric_rows, "max_rows": comparison.max_metric_rows},
        )
    normalized_columns: list[dict[str, Any]] = []
    for column_index, raw_column in enumerate(columns):
        if not isinstance(raw_column, dict):
            return [], [], _fail(FAILURE_COMPARISON_COLUMN_COUNT_INVALID, "增强版 A+ 比较图列必须是对象", {"position": position, "column_index": column_index + 1})
        asin = str(raw_column.get("asin") or "").strip().upper()
        if comparison.asin_required and not asin:
            return [], [], _fail(FAILURE_COMPARISON_COLUMN_ASIN_MISSING, "增强版 A+ 比较图产品列缺少 ASIN", {"position": position, "column_index": column_index + 1})
        if asin and not _ASIN_RE.match(asin):
            return [], [], _fail(FAILURE_COMPARISON_COLUMN_ASIN_INVALID, "增强版 A+ 比较图产品列 ASIN 格式无效", {"position": position, "column_index": column_index + 1, "asin": asin})
        title = _WHITESPACE_RE.sub(" ", _CONTROL_CHARS_RE.sub(" ", str(raw_column.get("title") or "")).strip())
        if not title:
            return [], [], _fail(FAILURE_TEXT_FIELD_MISSING, "增强版 A+ 比较图产品列标题不能为空", {"position": position, "column_index": column_index + 1, "field_id": "product_columns.title"})
        if len(title) > comparison.title_max_length:
            return [], [], _fail(FAILURE_TEXT_FIELD_TOO_LONG, "增强版 A+ 比较图产品列标题过长", {"position": position, "column_index": column_index + 1, "length": len(title), "max_length": comparison.title_max_length})
        values = _comparison_values(module, column_index, len(labels))
        if len(values) != len(labels):
            return [], [], _fail(
                FAILURE_COMPARISON_METRIC_ROWS_INVALID,
                "增强版 A+ 比较图 metric values 与 labels 数量不一致",
                {"position": position, "column_index": column_index + 1, "label_count": len(labels), "value_count": len(values)},
            )
        cleaned_values: list[str] = []
        for metric_index, value in enumerate(values, 1):
            clean_value = _WHITESPACE_RE.sub(" ", _CONTROL_CHARS_RE.sub(" ", str(value or "")).strip())
            if not clean_value:
                return [], [], _fail(FAILURE_COMPARISON_METRIC_VALUE_MISSING, "增强版 A+ 比较图 metric value 不能为空", {"position": position, "column_index": column_index + 1, "metric_index": metric_index})
            if len(clean_value) > comparison.metric_value_max_length:
                return [], [], _fail(FAILURE_TEXT_FIELD_TOO_LONG, "增强版 A+ 比较图 metric value 过长", {"position": position, "column_index": column_index + 1, "metric_index": metric_index})
            cleaned_values.append(clean_value)
        normalized_columns.append(
            {
                "position": column_index + 1,
                "title": title,
                "asin": asin,
                "highlight": bool(raw_column.get("highlight")) if "highlight" in raw_column else column_index == 0,
                "metric_values": cleaned_values,
            }
        )
    return normalized_columns, labels, None


def _preflight_validate_enhanced(product: Any, plan: dict[str, Any], modules: list[Any], assets: list[Any]) -> LingxingAplusModuleMappingResult:
    profile_key = APLUS_PUBLISH_PROFILE_ENHANCED_BASIC_APLUS_V1
    profile = get_profile_spec(profile_key)
    if profile is None:
        return _fail(FAILURE_UNSUPPORTED_PROFILE, "增强版 A+ profile 未注册", {"publish_profile": profile_key})
    if not profile.payload_evidence:
        return _fail(FAILURE_PAYLOAD_STRUCTURE_UNVERIFIED, "增强版 A+ profile 缺少 payload evidence", {"publish_profile": profile_key})
    asset_map, asset_failure = _validate_enhanced_assets(profile_key, assets)
    if asset_failure:
        return asset_failure
    normalized: list[LingxingAplusNormalizedModule] = []
    field_evidence: dict[str, Any] = {}
    content_module_types: list[str] = []
    for index, binding in enumerate(profile.module_sequence, 1):
        module = modules[index - 1]
        if not isinstance(module, dict):
            return _fail(FAILURE_MODULES_INVALID, "增强版 A+ module 必须是对象", {"index": index})
        try:
            position = int(module.get("position"))
        except Exception:
            return _fail(FAILURE_MODULE_POSITION_INVALID, "增强版 A+ module position 无效", {"index": index, "position": module.get("position")})
        if position != binding.position:
            return _fail(FAILURE_PROFILE_MODULE_SEQUENCE_MISMATCH, "增强版 A+ module sequence 与 registry 不一致", {"index": index, "position": position, "expected_position": binding.position})
        role = str(module.get("semantic_role") or "").strip()
        if role != binding.semantic_role:
            return _fail(FAILURE_MODULE_SEMANTIC_ROLE_MISMATCH, "增强版 A+ semantic_role 与 registry 不一致", {"position": position, "semantic_role": role, "expected_semantic_role": binding.semantic_role})
        module_spec_key = str(module.get("module_spec_key") or "").strip()
        if module_spec_key != binding.module_spec_key:
            return _fail(FAILURE_MODULE_SPEC_UNREGISTERED, "增强版 A+ module_spec_key 与 registry 不一致", {"position": position, "module_spec_key": module_spec_key, "expected_module_spec_key": binding.module_spec_key})
        module_type = str(module.get("lingxing_content_module_type") or "").strip()
        spec = get_module_spec_for_binding(profile_key, position, module_type)
        if spec is None:
            return _fail(FAILURE_UNSUPPORTED_MODULE_TYPE, "增强版 A+ Lingxing content module type 与 registry 不一致", {"position": position, "lingxing_content_module_type": module_type or None})
        if not spec.payload_evidence:
            return _fail(FAILURE_PAYLOAD_STRUCTURE_UNVERIFIED, "增强版 A+ module spec 缺少 payload evidence", {"position": position, "module_spec_key": module_spec_key})
        text_fields, text_failure = _validate_enhanced_text_fields(module, spec)
        if text_failure:
            return text_failure
        spec_rows: list[dict[str, str]] = []
        table_count: int | None = None
        if spec.spec_table:
            raw_rows = module.get("spec_rows") if binding.internal_type == INTERNAL_STANDARD_TECH_SPECS_TYPE else module.get("spec_items")
            spec_rows = _clean_enhanced_rows(raw_rows, value_key="description" if binding.internal_type == INTERNAL_STANDARD_TECH_SPECS_TYPE else "value")
            spec_failure = _validate_spec_rows(spec_rows, spec.spec_table, position=position)
            if spec_failure:
                return spec_failure
            table_count = int(module.get("tableCount") or 1)
            if table_count not in spec.spec_table.table_count_values:
                return _fail(FAILURE_SPEC_ROWS_INVALID, "增强版 A+ tableCount 不符合 registry 要求", {"position": position, "tableCount": table_count, "allowed": spec.spec_table.table_count_values})
        comparison_columns, metric_row_labels, comparison_failure = _validate_comparison(module, spec, position=position)
        if comparison_failure:
            return comparison_failure
        image_slots = []
        for slot in spec.image_slots:
            item = asset_map[(position, slot.slot_id)]
            image_slots.append(item)
        content_module_types.append(spec.content_module_type)
        headline = text_fields.get("headline") or text_fields.get("block1.headline") or spec.ui_name
        body = text_fields.get("body") or text_fields.get("block1.body") or text_fields.get("description_block1.body") or ""
        alt_text = image_slots[0]["alt_text"] if image_slots else ""
        field_evidence[str(position)] = {
            "semantic_role": binding.semantic_role,
            "module_spec_key": binding.module_spec_key,
            "content_module_type": spec.content_module_type,
            "text_fields": {key: len(value) for key, value in text_fields.items() if value},
            "image_slots": [slot["slot_id"] for slot in image_slots],
            "comparison_column_count": len(comparison_columns),
            "metric_row_count": len(metric_row_labels),
            "spec_row_count": len(spec_rows),
        }
        normalized.append(
            LingxingAplusNormalizedModule(
                position=position,
                publish_profile=profile_key,
                content_module_type=spec.content_module_type,
                semantic_role=binding.semantic_role,
                headline=headline,
                subheading="",
                body=body,
                alt_text=alt_text,
                field_sources={field_id: f"plan.modules[{position}].{field_id}" for field_id in text_fields},
                text_evidence=field_evidence[str(position)],
                module_spec_key=binding.module_spec_key,
                internal_type=binding.internal_type,
                payload_key=spec.payload_key,
                fixed_values=dict(spec.fixed_values),
                text_fields=text_fields,
                image_slots=image_slots,
                comparison_columns=comparison_columns,
                metric_row_labels=metric_row_labels,
                spec_rows=spec_rows,
                table_count=table_count,
            )
        )
    return LingxingAplusModuleMappingResult(
        ok=True,
        modules=normalized,
        evidence={
            "profile": profile_key,
            "profile_version": profile.profile_version,
            "module_count": len(normalized),
            "positions": [item.position for item in normalized],
            "semantic_roles": [item.semantic_role for item in normalized],
            "content_module_types": content_module_types,
            "required_image_slot_count": len(required_image_slots(profile_key)),
            "asset_slot_ids": [slot["asset_slot_id"] for module in normalized for slot in module.image_slots],
            "field_sources": field_evidence,
            "payload_structure_evidence": profile.payload_evidence,
        },
    )


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
    profile = _plan_profile(plan, modules)
    if profile == APLUS_PUBLISH_PROFILE_ENHANCED_BASIC_APLUS_V1:
        return _preflight_validate_enhanced(product, plan, modules, assets)
    if profile and not get_profile_spec(profile):
        return _fail(
            FAILURE_UNSUPPORTED_PROFILE,
            "A+ plan 使用了不支持的 publish_profile",
            {"publish_profile": profile},
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


def _paragraph_object(value: str) -> dict[str, Any]:
    return {"textList": [_text_object(value)]}


def _image_object(slot: dict[str, Any], uploaded: dict[str, Any]) -> dict[str, Any]:
    upload_destination_id = str(uploaded.get("uploadDestinationId") or "").strip()
    if not upload_destination_id:
        raise KeyError(FAILURE_UPLOAD_ASSET_MISSING_ID)
    return {
        "uploadDestinationId": upload_destination_id,
        "altText": slot["alt_text"],
        "imageCropSpecification": {
            "offset": {
                "x": {"units": "pixels", "value": 0},
                "y": {"units": "pixels", "value": 0},
            },
            "size": {
                "height": {"units": "pixels", "value": str(slot["crop_height"])},
                "width": {"units": "pixels", "value": str(slot["crop_width"])},
            },
        },
    }


def _uploaded_by_position(uploaded_assets: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    result: dict[int, dict[str, Any]] = {}
    for item in uploaded_assets:
        try:
            position = int(item.get("position"))
        except Exception:
            continue
        result[position] = item
    return result


def _uploaded_by_slot(uploaded_assets: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for item in uploaded_assets:
        asset_slot_id = str(item.get("asset_slot_id") or "").strip()
        if asset_slot_id:
            result[asset_slot_id] = item
    return result


def _slot_uploads_for_module(module: LingxingAplusNormalizedModule, uploaded_by_slot: dict[str, dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], LingxingAplusModuleMappingResult | None]:
    result: dict[str, dict[str, Any]] = {}
    for slot in module.image_slots:
        asset_slot_id = slot["asset_slot_id"]
        uploaded = uploaded_by_slot.get(asset_slot_id)
        if not uploaded:
            return {}, _fail(
                FAILURE_UPLOAD_ASSET_MISSING_ID,
                "上传图片缺少 enhanced asset_slot_id",
                {"position": module.position, "asset_slot_id": asset_slot_id, "slot_id": slot["slot_id"]},
            )
        if not str(uploaded.get("uploadDestinationId") or "").strip():
            return {}, _fail(
                FAILURE_UPLOAD_ASSET_MISSING_ID,
                "上传图片缺少 uploadDestinationId",
                {"position": module.position, "asset_slot_id": asset_slot_id, "slot_id": slot["slot_id"]},
            )
        result[slot["slot_id"]] = uploaded
    return result, None


def _enhanced_slot(module: LingxingAplusNormalizedModule, slot_id: str) -> dict[str, Any]:
    for slot in module.image_slots:
        if slot["slot_id"] == slot_id:
            return slot
    raise KeyError(slot_id)


def _build_enhanced_hero(module: LingxingAplusNormalizedModule, uploads: dict[str, dict[str, Any]]) -> dict[str, Any]:
    slot = _enhanced_slot(module, "hero.image")
    return {
        "contentModuleType": LINGXING_STANDARD_IMAGE_TEXT_OVERLAY,
        "standardImageTextOverlay": {
            "overlayColorType": module.fixed_values.get("overlayColorType") or "DARK",
            "block": {
                "image": _image_object(slot, uploads[slot["slot_id"]]),
                "headline": _text_object(module.text_fields["headline"]),
                "body": _paragraph_object(module.text_fields["body"]),
            },
        },
    }


def _build_enhanced_feature_grid(module: LingxingAplusNormalizedModule, uploads: dict[str, dict[str, Any]]) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "headline": _text_object(module.text_fields["headline"]),
    }
    for index, slot_id in enumerate(("feature_1.image", "feature_2.image", "feature_3.image"), 1):
        slot = _enhanced_slot(module, slot_id)
        payload[f"block{index}"] = {
            "image": _image_object(slot, uploads[slot_id]),
            "headline": _text_object(module.text_fields[f"block{index}.headline"]),
            "body": _paragraph_object(module.text_fields[f"block{index}.body"]),
        }
    return {
        "contentModuleType": LINGXING_STANDARD_THREE_IMAGE_TEXT,
        "standardThreeImageText": payload,
    }


def _build_enhanced_detail(module: LingxingAplusNormalizedModule, uploads: dict[str, dict[str, Any]]) -> dict[str, Any]:
    slot = _enhanced_slot(module, "detail.image")
    spec_items = [
        {"position": index, "text": _text_object(f"{row['label']}: {row['description']}")}
        for index, row in enumerate(module.spec_rows, 1)
    ]
    return {
        "contentModuleType": LINGXING_STANDARD_SINGLE_IMAGE_SPECS_DETAIL,
        "standardSingleImageSpecsDetail": {
            "headline": _text_object(module.text_fields["headline"]),
            "image": _image_object(slot, uploads[slot["slot_id"]]),
            "descriptionHeadline": _text_object(module.text_fields["description_headline"]),
            "descriptionBlock1": {
                "headline": _text_object(module.text_fields["description_block1.headline"]),
                "body": _paragraph_object(module.text_fields["description_block1.body"]),
            },
            "descriptionBlock2": {
                "headline": _text_object(module.text_fields.get("description_block2.headline") or ""),
                "body": _paragraph_object(module.text_fields.get("description_block2.body") or ""),
            },
            "specificationHeadline": _text_object(module.text_fields["specification_headline"]),
            "specificationListBlock": {
                "headline": _text_object(module.text_fields["specification_list_headline"]),
                "block": {"textList": spec_items},
            },
            "specificationTextBlock": {
                "headline": _text_object(module.text_fields.get("specification_text_headline") or ""),
                "body": _paragraph_object(module.text_fields.get("specification_text_body") or ""),
            },
        },
    }


def _build_enhanced_comparison(module: LingxingAplusNormalizedModule, uploads: dict[str, dict[str, Any]]) -> dict[str, Any]:
    slot_ids = ("comparison.column_1.image", "comparison.column_2.image")
    product_columns = []
    for column, slot_id in zip(module.comparison_columns, slot_ids, strict=True):
        slot = _enhanced_slot(module, slot_id)
        product_columns.append(
            {
                "position": column["position"],
                "image": _image_object(slot, uploads[slot_id]),
                "title": column["title"],
                "asin": column["asin"],
                "highlight": column["highlight"],
                "metrics": [
                    {"position": index, "value": value}
                    for index, value in enumerate(column["metric_values"], 1)
                ],
            }
        )
    return {
        "contentModuleType": LINGXING_STANDARD_COMPARISON_TABLE,
        "standardComparisonTable": {
            "productColumns": product_columns,
            "metricRowLabels": [
                {"position": index, "value": label}
                for index, label in enumerate(module.metric_row_labels, 1)
            ],
        },
    }


def _build_enhanced_tech_specs(module: LingxingAplusNormalizedModule, uploads: dict[str, dict[str, Any]]) -> dict[str, Any]:
    if uploads:
        raise KeyError(FAILURE_IMAGE_SLOT_UNEXPECTED)
    return {
        "contentModuleType": LINGXING_STANDARD_TECH_SPECS,
        "standardTechSpecs": {
            "headline": _text_object(module.text_fields["headline"]),
            "specificationList": [
                {
                    "label": _text_object(row["label"]),
                    "description": _text_object(row["description"]),
                }
                for row in module.spec_rows
            ],
            "tableCount": module.table_count or 1,
        },
    }


_ENHANCED_PAYLOAD_BUILDERS = {
    INTERNAL_STANDARD_IMAGE_TEXT_OVERLAY_TYPE: _build_enhanced_hero,
    INTERNAL_STANDARD_THREE_IMAGE_TEXT_TYPE: _build_enhanced_feature_grid,
    INTERNAL_STANDARD_SINGLE_IMAGE_SPECS_DETAIL_TYPE: _build_enhanced_detail,
    INTERNAL_STANDARD_COMPARISON_TABLE_TYPE: _build_enhanced_comparison,
    INTERNAL_STANDARD_TECH_SPECS_TYPE: _build_enhanced_tech_specs,
}


def _assemble_enhanced_payload(
    preflight_result: LingxingAplusModuleMappingResult,
    uploaded_assets: list[dict[str, Any]],
) -> LingxingAplusModuleMappingResult:
    uploaded_by_slot = _uploaded_by_slot(uploaded_assets)
    expected_slot_ids = [slot["asset_slot_id"] for module in preflight_result.modules for slot in module.image_slots]
    if set(uploaded_by_slot) != set(expected_slot_ids):
        return _fail(
            FAILURE_UPLOAD_ASSET_MISSING_ID,
            "上传图片 asset_slot_id 必须与 enhanced preflight slots 一一对应",
            {"expected_asset_slot_ids": sorted(expected_slot_ids), "uploaded_asset_slot_ids": sorted(uploaded_by_slot)},
        )
    content_modules: list[dict[str, Any]] = []
    for module in preflight_result.modules:
        builder = _ENHANCED_PAYLOAD_BUILDERS.get(module.internal_type or "")
        if builder is None:
            return _fail(FAILURE_PAYLOAD_BUILDER_MISSING, "增强版 A+ module 缺少 payload builder", {"position": module.position, "internal_type": module.internal_type})
        uploads, upload_failure = _slot_uploads_for_module(module, uploaded_by_slot)
        if upload_failure:
            return upload_failure
        try:
            content_modules.append(builder(module, uploads))
        except KeyError as exc:
            reason = str(exc).strip("'") or FAILURE_PAYLOAD_BUILDER_MISSING
            if reason == FAILURE_UPLOAD_ASSET_MISSING_ID:
                return _fail(reason, "上传图片缺少 uploadDestinationId", {"position": module.position})
            return _fail(FAILURE_PAYLOAD_BUILDER_MISSING, "增强版 A+ payload builder 无法组装模块", {"position": module.position, "missing": reason})

    return LingxingAplusModuleMappingResult(
        ok=True,
        modules=preflight_result.modules,
        content_module_list=content_modules,
        evidence={
            **preflight_result.evidence,
            "content_module_count": len(content_modules),
            "uploaded_asset_slot_ids": sorted(uploaded_by_slot),
            "payload_builder_profile": APLUS_PUBLISH_PROFILE_ENHANCED_BASIC_APLUS_V1,
        },
    )


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
    if preflight_result.evidence.get("profile") == APLUS_PUBLISH_PROFILE_ENHANCED_BASIC_APLUS_V1:
        return _assemble_enhanced_payload(preflight_result, uploaded_assets)
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
