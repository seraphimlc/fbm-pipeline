from __future__ import annotations

import html
import json
import re
from typing import Any

from app.pipeline.amazon_export.context import AmazonExportContext


_BED_SIZES = (
    ("california king", "California King"),
    ("twin xl", "Twin XL"),
    ("full xl", "Full XL"),
    ("twin", "Twin"),
    ("full", "Full"),
    ("queen", "Queen"),
    ("king", "King"),
)


def _json_value(value: Any, fallback: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if not value:
        return fallback
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return fallback


def _clean_text(value: Any) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", str(value or ""))).split())


def _snapshot(pd: Any) -> dict[str, Any]:
    value = _json_value(getattr(pd, "gigab2b_raw_snapshot", None), {})
    return value if isinstance(value, dict) else {}


def _part_number_from_evidence(pd: Any) -> str | None:
    """Prefer supplier MPN/part number, then fall back to our stable SKU."""
    snapshot = _snapshot(pd)
    candidates: list[Any] = [snapshot.get("mpn"), snapshot.get("part_number")]
    response = snapshot.get("_response")
    if isinstance(response, dict):
        rows = response.get("data")
        if isinstance(rows, list) and rows and isinstance(rows[0], dict):
            candidates.extend([rows[0].get("mpn"), rows[0].get("partNumber")])
    for value in candidates:
        text = _clean_text(value)
        if text:
            return text
    return _clean_text(getattr(pd, "item_code", None)) or None


def _property_values(pd: Any) -> dict[str, str]:
    snapshot = _snapshot(pd)
    specification = snapshot.get("specification") if isinstance(snapshot.get("specification"), dict) else {}
    values: dict[str, str] = {}
    for item in specification.get("property_infos") or []:
        if not isinstance(item, dict):
            continue
        name = _clean_text(item.get("property_name") or item.get("name")).lower()
        value = _clean_text(item.get("property_value_name") or item.get("property_value") or item.get("value"))
        if name and value:
            values[name] = value
    origin = _clean_text(specification.get("origin_place"))
    if origin:
        values.setdefault("origin", origin)
    return values


def _product_information_values(pd: Any) -> dict[str, str]:
    values: dict[str, str] = {}
    source = str(getattr(pd, "description", "") or "")
    pairs = re.findall(r"<td[^>]*>(.*?)</td>\s*<td[^>]*>(.*?)</td>", source, flags=re.IGNORECASE | re.DOTALL)
    for raw_name, raw_value in pairs:
        name, value = _clean_text(raw_name).lower(), _clean_text(raw_value)
        if name and value:
            values[name] = value
    # Step 1 persists the supplier's Product Information table as readable text.
    # Preserve the label/value evidence instead of relying on a particular HTML shape.
    labels = {
        "color", "material", "bed type", "size", "numbers of package", "spring box",
        "product dimension/weight", "package dimensions/weight", "number of bed slats",
        "bed weight capability", "bed mattress thickness", "assembly required",
        "adjustable headboard", "origin",
    }
    lines = [line.strip() for line in str(getattr(pd, "description", "") or "").splitlines() if line.strip()]
    for index, line in enumerate(lines[:-1]):
        name = _clean_text(line).lower()
        value = _clean_text(lines[index + 1])
        if name in labels and value:
            values.setdefault(name, value)
    return values


def _evidence_text(pd: Any, values: dict[str, str]) -> str:
    parts = [
        getattr(pd, "title", None),
        getattr(pd, "product_type", None),
        getattr(pd, "material", None),
        getattr(pd, "filler", None),
        getattr(pd, "description", None),
        getattr(pd, "features", None),
    ]
    variants = _json_value(getattr(pd, "variants", None), [])
    if isinstance(variants, list):
        parts.extend(variants)
    parts.extend(values.values())
    return " ".join(_clean_text(part) for part in parts if part not in (None, ""))


def _value_for(values: dict[str, str], *names: str) -> str | None:
    for name in names:
        value = values.get(name.lower())
        if value:
            return value
    return None


def _size_from_evidence(values: dict[str, str], text: str) -> str | None:
    candidate = " ".join(filter(None, (_value_for(values, "size", "bed size", "mattress size"), text))).lower()
    for marker, size in _BED_SIZES:
        if re.search(rf"\b{re.escape(marker)}\b", candidate):
            return size
    return None


def _origin_from_evidence(pd: Any, values: dict[str, str], text: str) -> str | None:
    candidates = [getattr(pd, "origin", None), _value_for(values, "origin", "place of origin")]
    for candidate in candidates:
        country = _clean_text(candidate)
        if country:
            return country
    match = re.search(r"\borigin\s*(?:of)?\s*[:\-]?\s*(china|united states|usa|canada|vietnam|malaysia)\b", text, re.IGNORECASE)
    return match.group(1).title() if match else None


def _require(value: Any, name: str, missing: list[str]) -> None:
    if value in (None, ""):
        missing.append(name)


def _write_many(fill: dict[str, Any], fields: dict[str, Any], key: str, values: list[Any]) -> None:
    targets = fields.get(key) or []
    if isinstance(targets, str):
        targets = [targets]
    for target, value in zip(targets, values):
        if value not in (None, ""):
            fill[target] = value


def apply_bed_frame_strategy(ctx: AmazonExportContext) -> None:
    """Fill BED_FRAME only from own-product facts, never furniture defaults."""
    from app.pipeline import step10_amazon_template as legacy

    pd, product, fields = ctx.product_data, ctx.product, ctx.fields
    properties = _property_values(pd)
    information = _product_information_values(pd)
    facts = {**properties, **information}
    text = _evidence_text(pd, facts)

    size = _size_from_evidence(facts, text)
    bed_type = _value_for(facts, "bed type") or ""
    form_factor = "Platform Bed" if re.search(r"\bplatform bed\b", bed_type or text, re.IGNORECASE) else None
    origin = _origin_from_evidence(pd, facts, text)
    capacity_match = re.search(r"\b(\d+(?:\.\d+)?)\s*(?:lb|lbs|pounds?)\b", _value_for(facts, "bed weight capability", "weight capacity") or "", re.IGNORECASE)
    capacity = float(capacity_match.group(1)) if capacity_match else None
    if capacity is not None and capacity.is_integer():
        capacity = int(capacity)

    missing: list[str] = []
    _require(getattr(product, "upc", None), "UPC", missing)
    _require(getattr(pd, "item_code", None), "SKU", missing)
    _require(size, "床型 Size", missing)
    _require(form_factor, "床架类型 Form Factor", missing)
    _require(origin, "原产地 Origin", missing)
    _require(capacity, "最大承重", missing)
    for value, name in (
        (getattr(pd, "dimension_length", None), "商品长度"),
        (getattr(pd, "dimension_width", None), "商品宽度"),
        (getattr(pd, "dimension_height", None), "商品高度"),
        (getattr(pd, "weight", None), "商品重量"),
    ):
        _require(value, name, missing)
    package = ctx.package or {}
    for key, name in (("length", "包装长度"), ("width", "包装宽度"), ("height", "包装高度"), ("weight", "包装重量")):
        _require(package.get(key), name, missing)
    if getattr(pd, "stock", None) is None:
        missing.append("可售库存")
    elif pd.stock < 0:
        missing.append("可售库存不能为负数")
    if getattr(pd, "suggested_price", None) in (None, "") or float(pd.suggested_price) <= 0:
        missing.append("建议售价")
    if missing:
        ctx.fill.pop(fields["country_of_origin"], None)
        raise ValueError(f"床架导出缺少可验证字段: {', '.join(missing)}")

    # These fields are template-specific semantic decisions.  The dedicated
    # pre-export analysis stores only values allowed by the real workbook;
    # never invent a value here when analysis returned no supported choice.
    _field = lambda key: (legacy._semantic_values_from_listing_check(pd, key) or [None])[0]
    if fields.get("part_number"):
        ctx.fill[fields["part_number"]] = _part_number_from_evidence(pd)
    if fields.get("item_shape"):
        ctx.fill[fields["item_shape"]] = _field("item_shape")
    if fields.get("finish_type"):
        ctx.fill[fields["finish_type"]] = _field("finish_type")
    if fields.get("is_fragile"):
        ctx.fill[fields["is_fragile"]] = _field("is_fragile")

    material_evidence = _value_for(facts, "material") or ""
    normalized_materials: list[str] = []
    if "linen" in material_evidence.lower():
        normalized_materials.append("Linen")
    if re.search(r"\bplywood\b|engineered wood", material_evidence, re.IGNORECASE):
        normalized_materials.append("Engineered Wood")
    if re.search(r"\bwood\b", material_evidence, re.IGNORECASE):
        normalized_materials.append("Wood")
    has_wood = "Wood" in normalized_materials
    components: list[str] = []
    if re.search(r"\bheadboard\b", text, re.IGNORECASE):
        components.append("Headboard")
    if re.search(r"\b(?:assembly|installation)\s+(?:manual|instructions)\b|detailed instructions", text, re.IGNORECASE):
        components.append("Installation Manual")
    if re.search(r"\bslats?\b", text, re.IGNORECASE):
        components.append("Slat")
    features: list[str] = []
    if re.search(r"\badjustable\s+headboard\b", text, re.IGNORECASE):
        features.append("Adjustable")
    if re.search(r"no\s+(?:need\s+for\s+a\s+)?(?:box|spring)\s*(?:box)?|no box spring", text, re.IGNORECASE):
        features.append("No Box Spring Needed")
    if re.search(r"\bslats?\b", text, re.IGNORECASE):
        features.append("Slatted")
    if re.search(r"\bupholstered\b", text, re.IGNORECASE):
        features.append("Upholstered")

    ctx.fill.update({
        fields["style"]: "Modern" if re.search(r"\bmodern\b", text, re.IGNORECASE) else None,
        fields["color"]: getattr(pd, "color", None),
        fields["size"]: f"{size} (U.S. Standard)",
        fields["form_factor"]: form_factor,
        fields["frame_material"]: "Wood" if has_wood else None,
        fields["base_material"]: "Wood" if has_wood else None,
        fields["headboard_material"]: "Engineered Wood" if "Engineered Wood" in normalized_materials else None,
        fields["maximum_weight"]: capacity,
        fields["maximum_weight_unit"]: "Pounds",
        fields["item_length"]: pd.dimension_length,
        fields["item_length_unit"]: "Inches",
        fields["item_width"]: pd.dimension_width,
        fields["item_width_unit"]: "Inches",
        fields["item_height"]: pd.dimension_height,
        fields["item_height_unit"]: "Inches",
        fields["item_weight"]: pd.weight,
        fields["item_weight_unit"]: "Pounds",
        fields["country_of_origin"]: origin,
    })
    if re.search(r"\bassembly required\b", text, re.IGNORECASE):
        ctx.fill[fields["assembly_required"]] = "Yes"
    _write_many(ctx.fill, fields, "materials", normalized_materials)
    _write_many(ctx.fill, fields, "mattress_sizes", [size])
    _write_many(ctx.fill, fields, "included_components", components)
    _write_many(ctx.fill, fields, "special_features", features)
