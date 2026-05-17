"""
模块10：Amazon 导入模板 — 将商品数据写入类目专用 Excel 模板

当前支持 Vindhvisk / Sofas & Couches，以及儿童骑乘玩具 RIDE_ON_TOY。
模板字段映射保存在 template_mappings/*.json，运行时不依赖大模型。
"""

import json
import logging
import re
import shutil
import asyncio
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from openpyxl import load_workbook

from app.config import settings
from app.database import async_session
from app.models import Product, ProductData, ProductFile
from app.pipeline.ride_on_category import RIDE_ON_CATEGORY_MARKERS, select_ride_on_category
from app.services.oss_uploader import oss_configured, upload_private_image
from sqlalchemy import select
from sqlalchemy.orm import selectinload

logger = logging.getLogger(__name__)

DATA_ROW = 8
AMAZON_TEMPLATE_LOGIC_VERSION = "2026-05-17-project-templates-v5"
SOFA_ITEM_DIMENSION_MAX_WIDTH_INCHES = 82
PIPELINE_DIR = Path(__file__).parent
MAPPING_DIR = PIPELINE_DIR / "template_mappings"
TEMPLATE_DIR = PIPELINE_DIR / "templates"
BRAND_TEMPLATE_MAPPINGS = {
    ("Vindhvisk", "Sofas & Couches"): MAPPING_DIR / "vindhvisk_sofa.json",
}
RIDE_ON_TOY_MAPPING = MAPPING_DIR / "ride_on_toy.json"
RIDE_ON_TOY_CATEGORY_MARKERS = RIDE_ON_CATEGORY_MARKERS


def _snapshot_model(obj):
    if obj is None:
        return None
    return SimpleNamespace(**{column.name: getattr(obj, column.name) for column in obj.__table__.columns})


def _resolve_template_path(template_path: str | Path) -> Path:
    path = Path(template_path).expanduser()
    if path.is_absolute():
        return path
    return (PIPELINE_DIR / path).resolve()


def _load_template_mapping(product: Product, pd: ProductData) -> dict:
    key = (product.brand or "", pd.leaf_category or "")
    mapping_path = BRAND_TEMPLATE_MAPPINGS.get(key)
    category_text = " ".join(
        str(item or "")
        for item in (
            pd.leaf_category,
            pd.categories,
            pd.product_type,
            pd.title,
        )
    ).lower()
    if not mapping_path and any(marker in category_text for marker in RIDE_ON_TOY_CATEGORY_MARKERS):
        mapping_path = RIDE_ON_TOY_MAPPING
    if not mapping_path and (product.brand or "") == "Vindhvisk":
        sofa_mapping_path = MAPPING_DIR / "vindhvisk_sofa.json"
        if sofa_mapping_path.exists():
            try:
                sofa_mapping = json.loads(sofa_mapping_path.read_text(encoding="utf-8"))
            except Exception:
                sofa_mapping = {}
            for option in sofa_mapping.get("browse_category_options") or []:
                if not isinstance(option, dict):
                    continue
                candidates = [
                    option.get("node"),
                    option.get("path"),
                    *(option.get("markers") or []),
                ]
                if any(str(candidate or "").lower() in category_text for candidate in candidates if candidate):
                    mapping_path = sofa_mapping_path
                    break
    if not mapping_path:
        raise ValueError(f"未配置品牌/类目导入模板映射: brand={product.brand or '未知'}, leaf_category={pd.leaf_category or '未知'}")
    with mapping_path.open("r", encoding="utf-8") as f:
        mapping = json.load(f)
    if mapping.get("template_path"):
        mapping["template_path"] = str(_resolve_template_path(mapping["template_path"]))
    return mapping


def _json_loads(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except Exception:
        return fallback


def _information_workbook_values(pd: ProductData) -> dict[str, Any]:
    if not pd.material_dir:
        return {}
    material_dir = Path(pd.material_dir).expanduser()
    if not material_dir.is_dir():
        return {}

    candidates = sorted(material_dir.rglob("*productinfo*.xlsx"))
    if not candidates:
        return {}

    for path in candidates:
        try:
            wb = load_workbook(path, data_only=True, read_only=False)
            ws = wb["产品信息"] if "产品信息" in wb.sheetnames else wb.active
            values: dict[str, Any] = {}
            group = None
            for col in range(1, ws.max_column + 1):
                if ws.cell(1, col).value:
                    group = str(ws.cell(1, col).value)
                field = ws.cell(2, col).value or ws.cell(1, col).value
                value = ws.cell(3, col).value
                if field not in (None, "") and value not in (None, ""):
                    field_name = str(field).strip()
                    values[field_name] = value
                    if group:
                        values[f"{group}.{field_name}"] = value
            return values
        except Exception as exc:
            logger.warning(f"[Step10] 读取大健 Information 表格失败: {path}: {exc}")
    return {}


def _parse_package_dimensions(text: str | None) -> dict[str, float] | None:
    if not text:
        return None
    nums = [float(item) for item in re.findall(r"\d+(?:\.\d+)?", text)]
    if len(nums) < 4:
        return None
    return {
        "length": nums[0],
        "width": nums[1],
        "height": nums[2],
        "weight": nums[3],
    }


def _package_from_information_workbook(pd: ProductData) -> dict[str, float] | None:
    values = _information_workbook_values(pd)
    if not values:
        return None
    keys = {
        "length": "包装尺寸-长度(英寸)",
        "width": "包装尺寸-宽度(英寸)",
        "height": "包装尺寸-高度(英寸)",
        "weight": "包装尺寸-重量(磅)",
    }
    try:
        package = {key: float(str(values[field]).replace(",", "")) for key, field in keys.items() if values.get(field) not in (None, "")}
    except ValueError:
        return None
    return package if set(package) == set(keys) else None


def _representative_package(pd: ProductData) -> tuple[dict[str, float] | None, list[str]]:
    warnings: list[str] = []
    packages = _json_loads(pd.packages, [])
    parsed_packages: list[dict[str, float]] = []
    if isinstance(packages, list):
        for item in packages:
            parsed = _parse_package_dimensions((item or {}).get("dimensions") if isinstance(item, dict) else str(item))
            if parsed:
                parsed_packages.append(parsed)

    if not parsed_packages:
        info_package = _package_from_information_workbook(pd)
        if info_package:
            warnings.append("页面未解析到包裹明细，已使用大健 Information 表格中的包装尺寸/重量。")
            return info_package, warnings
        warnings.append("缺少可解析的外包装尺寸/重量，模板包裹尺寸列未填写。")
        return None, warnings

    if len(parsed_packages) > 1:
        warnings.append("该商品有多个外包装，Amazon模板只有一组包裹尺寸列；当前使用重量最大的外包装作为代表包裹。")

    return max(parsed_packages, key=lambda item: item.get("weight", 0)), warnings


def _index_template_columns(ws) -> dict[str, str]:
    columns: dict[str, str] = {}
    for cell in ws[5]:
        if cell.value:
            columns[str(cell.value)] = cell.column_letter
    return columns


def _set(ws, columns: dict[str, str], attr: str, value: Any) -> None:
    if value in (None, ""):
        return
    col = columns.get(attr)
    if col:
        ws[f"{col}{DATA_ROW}"] = value


def _nonempty(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return value != ""


def _flatten_mapping_values(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        result: list[str] = []
        for item in value:
            result.extend(_flatten_mapping_values(item))
        return result
    if isinstance(value, dict):
        result: list[str] = []
        for item in value.values():
            result.extend(_flatten_mapping_values(item))
        return result
    return []


def _critical_template_fields(mapping: dict) -> list[str]:
    fields = mapping.get("dynamic_fields", {})
    keys = (
        "sku",
        "title",
        "brand",
        "description",
        "search_terms",
        "list_price",
        "quantity",
        "price",
        "country_of_origin",
        "shipping_template",
    )
    result: list[str] = []
    for key in keys:
        result.extend(_flatten_mapping_values(fields.get(key)))
    result.extend(_flatten_mapping_values(mapping.get("bullet_fields", [])[:5]))
    image_fields = mapping.get("image_fields", {})
    result.extend(_flatten_mapping_values(image_fields.get("main")))
    package_fields = mapping.get("package_fields", {})
    for key in ("length_value", "width_value", "height_value", "weight_value"):
        result.extend(_flatten_mapping_values(package_fields.get(key)))
    result.extend(_flatten_mapping_values(mapping.get("required_fields", [])))
    return list(dict.fromkeys(field for field in result if field))


def _filled_field_names(fill: dict[str, Any], columns: dict[str, str]) -> set[str]:
    return {attr for attr, value in fill.items() if attr in columns and _nonempty(value)}


def _missing_required_fields(mapping: dict, fill: dict[str, Any], columns: dict[str, str]) -> list[str]:
    return [
        attr
        for attr in _critical_template_fields(mapping)
        if attr in columns and not _nonempty(fill.get(attr))
    ]


def _listing_template_warnings(pd: ProductData) -> list[str]:
    warnings: list[str] = []
    listing_check = _json_loads(pd.listing_check, {})
    issues = listing_check.get("issues") if isinstance(listing_check, dict) else []
    if isinstance(issues, list):
        for issue in issues[:5]:
            if isinstance(issue, dict):
                message = issue.get("message") or issue.get("issue") or issue.get("text")
            else:
                message = str(issue)
            if message:
                warnings.append(f"Listing提醒: {message}")

    primary = (pd.listing_primary_keyword or "").strip().lower()
    title_start = (pd.listing_title or "")[:100].lower()
    if primary and primary not in title_start:
        warnings.append("主关键词未出现在标题前100字符内，可能影响搜索相关性。")
    if not pd.listing_search_terms:
        warnings.append("Search Terms 为空，导入模板缺少后台关键词。")
    elif len(pd.listing_search_terms.strip()) < 40:
        warnings.append("Search Terms 偏短，后台关键词覆盖可能不足。")
    return warnings


def _pricing_template_warnings(pd: ProductData) -> list[str]:
    warnings: list[str] = []
    if pd.suggested_price is None:
        warnings.append("建议售价为空，导入模板价格无法确认。")
    if pd.profit is None or pd.profit_rate is None:
        warnings.append("利润数据为空，上传前需要人工确认价格。")
        return warnings
    target_margin_percent = settings.PRICING_TARGET_MARGIN_RATE * 100
    if pd.profit_rate < target_margin_percent:
        warnings.append(f"净利率 {pd.profit_rate:.1f}% 低于系统目标 {target_margin_percent:.1f}%。")
    if pd.profit < settings.PRICING_MIN_PROFIT:
        warnings.append(f"单件利润 ${pd.profit:.2f} 低于系统最低利润 ${settings.PRICING_MIN_PROFIT:.2f}。")
    return warnings


def _inventory_template_warnings(pd: ProductData) -> list[str]:
    return ["导入表格按系统策略不提交库存数量，后续需通过库存同步功能更新可售库存。"]


def _aplus_template_warnings(product: Product) -> list[str]:
    if not product.aplus:
        return ["未生成 A+ 内容，导入表格只包含 Listing 和图片信息。"]
    images = _json_loads(product.aplus.aplus_images, [])
    if not isinstance(images, list) or not images:
        return ["未生成 A+ 图片，后续上架前需要人工补 A+。"]
    done_count = sum(1 for item in images if isinstance(item, dict) and item.get("status", "done") == "done")
    warnings: list[str] = []
    if done_count < 5:
        warnings.append(f"A+ 图片仅完成 {done_count}/5 张，发布前需要人工补齐或确认。")
    if product.aplus.aplus_status and product.aplus.aplus_status not in {"done", "regen_done"}:
        warnings.append(f"A+ 状态为 {product.aplus.aplus_status}，发布前建议复核。")
    return warnings


def _step6_main_image_warnings(product: Product) -> list[str]:
    if not product.images:
        return ["未找到 Step6 图片选择结果。"]
    if product.images.main_image_source == "fallback_substitute":
        return ["主图使用了替代图，不是完全合规白底主图；上传前请人工确认。"]
    return []


def _template_risk_level(warnings: list[str], missing_required: list[str], main_image_url_filled: bool) -> str:
    if missing_required or not main_image_url_filled:
        return "high_risk"
    high_keywords = ("主图上传失败", "缺少Step6选定主图", "OSS 未配置", "利润数据为空", "低于系统最低利润")
    if any(any(keyword in warning for keyword in high_keywords) for warning in warnings):
        return "high_risk"
    return "warning" if warnings else "pass"


def _build_fill_summary(
    mapping: dict,
    fill: dict[str, Any],
    columns: dict[str, str],
    warnings: list[str],
    missing_columns: list[str],
    uploaded_images: list[dict],
) -> dict[str, Any]:
    filled_fields = _filled_field_names(fill, columns)
    missing_required = _missing_required_fields(mapping, fill, columns)
    main_image_field = mapping.get("image_fields", {}).get("main")
    main_image_url_filled = bool(main_image_field and _nonempty(fill.get(main_image_field)))
    image_field_names = set(_flatten_mapping_values(mapping.get("image_fields", {})))
    image_url_count = len([field for field in image_field_names if _nonempty(fill.get(field))])
    return {
        "logic_version": AMAZON_TEMPLATE_LOGIC_VERSION,
        "risk_level": _template_risk_level(warnings, missing_required, main_image_url_filled),
        "filled_count": len(filled_fields),
        "attempted_count": len([value for value in fill.values() if _nonempty(value)]),
        "template_column_count": len(columns),
        "missing_required_count": len(missing_required),
        "missing_required_fields": missing_required[:50],
        "unmapped_count": len(missing_columns),
        "unmapped_fields": missing_columns[:50],
        "image_url_count": image_url_count,
        "main_image_url_filled": main_image_url_filled,
        "uploaded_image_count": len(uploaded_images),
        "warnings_count": len(warnings),
    }


def _gallery_paths(product: Product) -> list[Path]:
    if not product.images:
        return []
    paths = _json_loads(product.images.gallery_images, [])
    if not isinstance(paths, list):
        return []
    return [Path(str(path)).expanduser() for path in paths if path]


def _image_health_warnings(product: Product) -> list[str]:
    if not product.images or not product.images.image_analysis:
        return []
    payload = _json_loads(product.images.image_analysis, {})
    if not isinstance(payload, dict):
        return []
    diagnostics = payload.get("selection_diagnostics")
    if not isinstance(diagnostics, dict):
        return []
    health = diagnostics.get("image_health")
    if not isinstance(health, dict):
        return []
    level = health.get("level")
    if level not in {"high_risk", "review_recommended"}:
        return []
    label = health.get("label") or level
    issues = [
        item.get("message")
        for item in (health.get("issues") or [])
        if isinstance(item, dict) and item.get("severity") in {"high", "review"} and item.get("message")
    ]
    if not issues:
        return [f"Step6图片健康等级为 {label}，最终确认前请复核图片。"]
    return [f"Step6图片健康等级为 {label}: {issue}" for issue in issues[:5]]


def _upload_listing_images(product: Product, pd: ProductData, mapping: dict) -> tuple[dict[str, str], list[str], list[dict]]:
    warnings: list[str] = []
    uploaded: list[dict] = []
    fill: dict[str, str] = {}

    if not oss_configured():
        warnings.append("OSS 未配置，主图/副图URL未写入导入模板。")
        return fill, warnings, uploaded
    if not product.images or not product.images.main_image_path:
        warnings.append("缺少Step6选定主图，主图/副图URL未写入导入模板。")
        return fill, warnings, uploaded

    product_key = pd.item_code or f"product-{product.id}"
    image_paths = [Path(product.images.main_image_path).expanduser()]
    other_fields = mapping.get("image_fields", {}).get("others", [])
    image_paths.extend(_gallery_paths(product)[:len(other_fields)])

    for idx, path in enumerate(image_paths[:1 + len(other_fields)]):
        slot = "main" if idx == 0 else f"other_{idx}"
        field = mapping.get("image_fields", {}).get("main") if idx == 0 else other_fields[idx - 1]
        if not field:
            continue
        try:
            result = upload_private_image(path, product_key, slot)
        except Exception as exc:
            warnings.append(f"图片上传失败 {slot}: {type(exc).__name__}: {exc}")
            continue
        uploaded.append(result)
        fill[field] = result["url"]

    main_field = mapping.get("image_fields", {}).get("main")
    if main_field and main_field not in fill:
        warnings.append("主图上传失败或缺失，导入模板未填写主图URL。")
    if len(fill) < len(image_paths[:9]):
        warnings.append(f"Listing图片URL仅填写 {len(fill)}/{len(image_paths[:9])} 个。")
    warnings.extend(_image_health_warnings(product))
    return fill, warnings, uploaded


def _remove_column_validations(ws, column_letter: str) -> None:
    if not ws.data_validations:
        return
    kept = []
    target_prefix = f"{column_letter}{DATA_ROW}:"
    target_cell = f"{column_letter}{DATA_ROW}"
    for validation in ws.data_validations.dataValidation:
        sqref = str(validation.sqref)
        if target_prefix in sqref or target_cell in sqref:
            continue
        kept.append(validation)
    ws.data_validations.dataValidation = kept


def _template_values(wb, attr: str) -> list[str]:
    ws = wb["Dropdown Lists"]
    for col in range(1, ws.max_column + 1):
        if ws.cell(3, col).value == attr:
            return [
                str(ws.cell(row, col).value)
                for row in range(4, ws.max_row + 1)
                if ws.cell(row, col).value not in (None, "")
            ]
    return []


def _first_template_value(wb, attr: str, fallback: str | None = None) -> str | None:
    values = _template_values(wb, attr)
    return values[0] if values else fallback


def _stock_value(pd: ProductData) -> int | None:
    if pd.stock is not None:
        return pd.stock
    values = _information_workbook_values(pd)
    raw = values.get("可售库存")
    if raw in (None, ""):
        return None
    try:
        return int(float(str(raw).replace(",", "")))
    except ValueError:
        return None


def _material_value(pd: ProductData) -> str:
    raw = " ".join([pd.material or "", pd.filler or "", pd.description or ""]).lower()
    if "foam" in raw or "all-foam" in raw or "boneless" in raw or "frameless" in raw:
        return "Polyurethane (PU)"
    if re.search(r"\b(?:metal|steel|iron)\s+frame\b|\bframe\s+(?:made\s+of\s+)?(?:metal|steel|iron)\b", raw):
        return "Metal"
    if re.search(r"\b(?:wood|wooden|engineered wood)\s+frame\b|\bframe\s+(?:made\s+of\s+)?(?:wood|wooden|engineered wood)\b", raw):
        return "Engineered Wood"
    return "Polyurethane (PU)"


def _frame_material_value(pd: ProductData) -> str:
    raw = " ".join([pd.material or "", pd.filler or "", pd.description or "", pd.title or ""]).lower()
    def has_positive_frame(pattern: str) -> bool:
        for match in re.finditer(pattern, raw):
            prefix = raw[max(0, match.start() - 45):match.start()]
            if re.search(r"\b(?:no|without|not|free of|unlike)\b", prefix):
                continue
            return True
        return False

    if "all-foam" in raw or "boneless" in raw or "frameless" in raw:
        return "Engineered Wood"
    if has_positive_frame(r"\b(?:metal|steel|iron)\s+frame\b|\bframe\s+(?:made\s+of\s+)?(?:metal|steel|iron)\b"):
        return "Metal"
    if has_positive_frame(r"\bbamboo\s+frame\b|\bframe\s+(?:made\s+of\s+)?bamboo\b"):
        return "Bamboo"
    if has_positive_frame(r"\bplastic\s+frame\b|\bframe\s+(?:made\s+of\s+)?plastic\b"):
        return "Plastic"
    return "Engineered Wood"


def _fabric_value(pd: ProductData) -> str:
    raw = " ".join([pd.material or "", pd.description or "", pd.title or ""]).lower()
    if "corduroy" in raw:
        return "Corduroy"
    if "chenille" in raw:
        return "Chenille"
    if "velvet" in raw:
        return "Velvet"
    if "leather" in raw:
        return "Faux Leather"
    if "flannelette" in raw or "fabric" in raw:
        return "Polyester"
    return "Polyester"


def _description(pd: ProductData) -> str:
    parts = []
    if pd.listing_title:
        parts.append(pd.listing_title)
    bullets = _json_loads(pd.listing_bullets, [])
    if isinstance(bullets, list):
        parts.extend(str(item) for item in bullets if item)
    if pd.description:
        parts.append(pd.description)
    return "\n".join(parts)[:1900]


def _facts_text(pd: ProductData) -> str:
    values = [
        pd.title,
        pd.listing_title,
        pd.color,
        pd.material,
        pd.filler,
        pd.product_type,
        pd.description,
        pd.features,
        pd.variants,
    ]
    info_values = _information_workbook_values(pd)
    values.extend(info_values.get(key) for key in (
        "产品描述",
        "产品特点1",
        "产品特点2",
        "产品特点3",
        "产品特点4",
        "产品特点5",
        "产品特点6",
        "产品特点7",
        "规格描述1",
        "规格描述2",
        "规格描述3",
    ))
    return " ".join(str(value or "") for value in values)


def _included_components(pd: ProductData, seating: int | None) -> str:
    text = " ".join([pd.description or "", pd.title or "", pd.listing_title or ""]).lower()
    parts = []
    if seating:
        parts.append(f"{seating} sofa modules")
    else:
        parts.append("Sofa")

    pillow_match = re.search(r"(\d+)\s+(?:complimentary\s+)?pillows?", text)
    back_pillow_match = re.search(r"(\d+)\s+(?:oversized\s+)?back pillows?", text)
    accent_pillow_match = re.search(r"(\d+)\s+accent cushions?", text)
    if back_pillow_match:
        parts.append(f"{back_pillow_match.group(1)} back pillows")
    if accent_pillow_match:
        parts.append(f"{accent_pillow_match.group(1)} accent cushions")
    if not back_pillow_match and not accent_pillow_match and pillow_match:
        parts.append(f"{pillow_match.group(1)} pillows")
    elif "pillow" in text and not any("pillow" in part for part in parts):
        parts.append("Pillows")

    return ", ".join(parts)


def _seating_capacity(pd: ProductData) -> int | None:
    text = " ".join([pd.title or "", pd.listing_title or "", pd.product_type or "", pd.description or ""])
    match = re.search(r"(\d+)\s*(?:Seat|Seater|seat|seater)", text)
    if match:
        return int(match.group(1))
    variants = _json_loads(pd.variants, [])
    if isinstance(variants, list):
        color = (pd.color or "").lower()
        for item in variants:
            item_text = str(item.get("text") if isinstance(item, dict) else item)
            if color and color not in item_text.lower():
                continue
            match = re.search(r"(\d+)\s*(?:Seat|Seater|seat|seater)", item_text)
            if match:
                return int(match.group(1))
    return None


def _seat_depth(pd: ProductData) -> float | None:
    if not pd.dimension_width:
        return None
    return round(min(max(pd.dimension_width - 12, 20), 30), 1)


def _weight_capacity_maximum(seating: int | None) -> int:
    return max(seating or 3, 1) * 250


def _omit_fields(fill: dict[str, Any], fields: dict[str, str], keys: tuple[str, ...]) -> None:
    for key in keys:
        attr = fields.get(key)
        if attr:
            fill.pop(attr, None)


def _sofa_dimension_warnings(pd: ProductData, fill: dict[str, Any], fields: dict[str, str]) -> list[str]:
    width = pd.dimension_length
    if width is None or width <= SOFA_ITEM_DIMENSION_MAX_WIDTH_INCHES:
        return []

    _omit_fields(fill, fields, (
        "depth_value",
        "depth_unit",
        "height_value",
        "height_unit",
        "width_value",
        "width_unit",
    ))
    return [
        f"SOFA Item Dimensions D x W x H 的 width={width:g} inches 超过 Amazon 允许的 "
        f"{SOFA_ITEM_DIMENSION_MAX_WIDTH_INCHES:g} inches，已跳过该字段组；普通 Item Width/Length 仍保留。"
    ]


def _amazon_item_type_keyword(option: dict[str, Any]) -> str:
    return f"{option['path']} ({option['node']})"


def _furniture_match_text(pd: ProductData) -> str:
    text_values = [
        pd.leaf_category,
        pd.categories,
        pd.product_type,
        pd.title,
        pd.listing_title,
        pd.description,
        pd.features,
        pd.variants,
    ]
    return " ".join(str(value or "") for value in text_values).lower()


def _find_browse_option(options: list[Any], node: str) -> dict[str, Any] | None:
    for option in options:
        if isinstance(option, dict) and option.get("node") == node:
            return option
    return None


def _looks_like_sofa(pd: ProductData) -> bool:
    text = _furniture_match_text(pd)
    sofa_markers = (
        "sofa",
        "couch",
        "loveseat",
        "love seat",
        "futon",
        "sleeper",
        "settee",
        "sectional",
        "chaise sofa",
        "1-2 seater",
        "2 seater",
        "two seater",
        "多人沙发",
        "双人沙发",
        "沙发",
    )
    if any(marker in text for marker in sofa_markers):
        return True
    # Amazon returned CHAIR dimension warnings for 62.6 x 48.23 in. Sofa-like
    # furniture should not be squeezed into living-room-chairs just because the
    # supplier leaf category says so.
    longest_side = max((pd.dimension_length or 0), (pd.dimension_width or 0))
    depth_side = min((pd.dimension_length or 0), (pd.dimension_width or 0))
    return longest_side > 40 or depth_side > 35.04


def _preferred_sofa_node(pd: ProductData) -> str:
    text = _furniture_match_text(pd)
    if "futon" in text:
        return "futon-sets"
    if any(marker in text for marker in ("patio loveseat", "outdoor loveseat", "庭院双人沙发")):
        return "patio-loveseats"
    if any(marker in text for marker in ("patio sofa", "outdoor sofa", "户外沙发")):
        return "patio-sofas"
    if any(marker in text for marker in ("children sofa", "kids sofa", "儿童沙发")):
        return "childrens-sofas"
    return "sofas"


def _sofa_type_value(pd: ProductData) -> str:
    text = _furniture_match_text(pd)
    if "sofa bed" in text:
        return "Sofa Bed"
    if "chaise" in text or "lounge chair" in text:
        return "Sofa Chaise"
    if "sleeper" in text:
        return "Sleeper"
    if "futon" in text:
        return "Futon"
    if "loveseat" in text or "love seat" in text:
        return "Loveseat"
    if "sectional" in text:
        return "Sectional"
    if "settee" in text:
        return "Settee"
    if "convertible" in text:
        return "Convertible"
    return "Standard"


def _select_furniture_category_option(mapping: dict, pd: ProductData) -> dict[str, Any] | None:
    options = mapping.get("browse_category_options") or []
    if not isinstance(options, list):
        return None

    if _looks_like_sofa(pd):
        preferred = _find_browse_option(options, _preferred_sofa_node(pd))
        if preferred:
            return preferred

    haystack = _furniture_match_text(pd)
    best: tuple[int, int, dict[str, Any]] | None = None
    for index, option in enumerate(options):
        if not isinstance(option, dict):
            continue
        score = 0
        node = str(option.get("node") or "").lower()
        path = str(option.get("path") or "").lower()
        if node and node in haystack:
            score += 40
        if path and path in haystack:
            score += 40
        for marker in option.get("markers") or []:
            marker_text = str(marker or "").lower().strip()
            if marker_text and marker_text in haystack:
                score += 20 + min(len(marker_text), 30)
        if score and (best is None or score > best[0]):
            best = (score, index, option)

    if best:
        return best[2]

    for option in options:
        if isinstance(option, dict) and option.get("node") == "sofas":
            return option
    return None


def _apply_furniture_category_fill(fill: dict[str, Any], mapping: dict, pd: ProductData) -> tuple[dict[str, Any] | None, list[str]]:
    warnings: list[str] = []
    option = _select_furniture_category_option(mapping, pd)
    if not option:
        warnings.append("SOFA/CHAIR 模板未匹配到细分类目，沿用映射默认类目。")
        return None, warnings

    fill["product_type#1.value"] = option.get("product_type") or "SOFA"
    fill["item_type_keyword[marketplace_id=ATVPDKIKX0DER]#1.value"] = _amazon_item_type_keyword(option)

    if option.get("product_type") == "CHAIR":
        fill.pop("sofa_type[marketplace_id=ATVPDKIKX0DER]#1.value", None)
    else:
        fill["sofa_type[marketplace_id=ATVPDKIKX0DER]#1.value"] = _sofa_type_value(pd)
    return option, warnings


def _ride_on_material(pd: ProductData) -> str:
    raw = _facts_text(pd).lower()
    if "metal" in raw or "steel" in raw:
        return "Plastic, Metal"
    if "wood" in raw:
        return "Plastic, Wood"
    return pd.material or "Plastic"


def _ride_on_target_gender(pd: ProductData) -> str:
    raw = _facts_text(pd).lower()
    if any(word in raw for word in ("girl", "girls", "princess", "pink")):
        return "Female"
    if any(word in raw for word in ("boy", "boys")):
        return "Male"
    return "Unisex"


def _ride_on_voltage(pd: ProductData) -> tuple[int, list[str]]:
    warnings: list[str] = []
    raw = _facts_text(pd).lower()
    match = re.search(r"\b(6|12|18|24)\s*v(?:olt)?s?\b", raw)
    if match:
        return int(match.group(1)), warnings
    warnings.append("未识别骑乘玩具电压，按常见 12V 电瓶车默认填写；上传前建议核对电池铭牌/说明书。")
    return 12, warnings


def _ride_on_age_months(pd: ProductData) -> tuple[int, int | None, list[str]]:
    warnings: list[str] = []
    raw = _facts_text(pd).lower()
    range_match = re.search(r"(\d+)\s*[-~–]\s*(\d+)\s*(?:years?|yrs?|岁)", raw)
    if range_match:
        return int(range_match.group(1)) * 12, int(range_match.group(2)) * 12, warnings
    year_match = re.search(r"(?:ages?\s*)?(\d+)\s*\+?\s*(?:years?|yrs?|岁)", raw)
    if year_match:
        return int(year_match.group(1)) * 12, None, warnings
    month_match = re.search(r"(\d+)\s*(?:months?|月)", raw)
    if month_match:
        return int(month_match.group(1)), None, warnings
    warnings.append("未识别建议年龄，按 3 岁以上默认填写玩具合规年龄；上传前建议核对页面/说明书。")
    return 36, None, warnings


def _ride_on_seating_capacity(pd: ProductData) -> int:
    raw = _facts_text(pd).lower()
    if re.search(r"\b(2|two)\s*(?:seat|seater|kids|children)\b", raw):
        return 2
    return 1


def _ride_on_battery_profile(pd: ProductData) -> tuple[dict[str, Any], list[str]]:
    warnings: list[str] = []
    raw = _facts_text(pd).lower()
    voltage, voltage_warnings = _ride_on_voltage(pd)
    warnings.extend(voltage_warnings)

    if "lithium polymer" in raw or "li-polymer" in raw or "lipo" in raw:
        composition = "Lithium Polymer"
    elif "lithium" in raw or "li-ion" in raw or "lion" in raw:
        composition = "Lithium Ion"
    elif "nimh" in raw or "ni-mh" in raw:
        composition = "NiMH"
    elif "nicad" in raw or "ni-cd" in raw:
        composition = "NiCAD"
    elif "alkaline" in raw:
        composition = "Alkaline"
    else:
        composition = "Lead Acid"
        if not any(word in raw for word in ("lead acid", "lead-acid", "sealed lead", "sla")):
            warnings.append("未识别电池化学类型，按骑乘电瓶车常见 Lead Acid 默认填写；如实际为锂电池需改模板。")

    quantity = 1
    quantity_match = re.search(r"\b(\d+)\s*(?:x|pcs?|pieces?)?\s*(?:battery|batteries)\b", raw)
    if quantity_match:
        quantity = max(int(quantity_match.group(1)), 1)

    battery_type = f"{voltage}V" if voltage in (9, 12) else "Nonstandard Battery"
    profile: dict[str, Any] = {
        "voltage": voltage,
        "composition": composition,
        "quantity": quantity,
        "type": battery_type,
    }

    ah_match = re.search(r"(\d+(?:\.\d+)?)\s*ah\b", raw)
    if ah_match:
        profile["energy_content"] = round(voltage * float(ah_match.group(1)), 2)
    return profile, warnings


def _ride_on_size(pd: ProductData) -> str | None:
    if pd.dimension_length and pd.dimension_width and pd.dimension_height:
        return f'{pd.dimension_length:g}" L x {pd.dimension_width:g}" W x {pd.dimension_height:g}" H'
    return None


def _ride_on_included_components(pd: ProductData) -> list[str]:
    raw = _facts_text(pd).lower()
    parts = ["Ride-on toy", "Charger"]
    if "remote" in raw or "2.4g" in raw or "parent control" in raw:
        parts.append("Remote control")
    if "manual" in raw or "instruction" in raw:
        parts.append("User manual")
    return parts[:5]


def _ride_on_assembly(pd: ProductData) -> tuple[str, int | None, str | None]:
    raw = _facts_text(pd).lower()
    if any(phrase in raw for phrase in ("no assembly required", "fully assembled", "ready to use out of box", "ready to use out of the box")):
        return "No", None, None
    return "Yes", 30, "Minutes"


def _apply_ride_on_toy_fill(fill: dict[str, Any], fields: dict[str, str], product: Product, pd: ProductData) -> list[str]:
    warnings: list[str] = []
    age_min, age_max, age_warnings = _ride_on_age_months(pd)
    battery, battery_warnings = _ride_on_battery_profile(pd)
    warnings.extend(age_warnings)
    warnings.extend(battery_warnings)
    voltage = battery["voltage"]

    age_years = max(age_min // 12, 1)
    age_description = f"{age_years} years and up"
    if age_max:
        age_description = f"{age_min // 12}-{age_max // 12} years"
    assembly_required, assembly_time, assembly_time_unit = _ride_on_assembly(pd)

    ships_globally = str(fill.get(fields.get("ships_globally", ""), "No") or "No").strip().lower() == "yes"

    fill.update({
        fields["target_audience_1"]: "Children",
        fields["target_audience_2"]: "Kids",
        fields["target_gender"]: _ride_on_target_gender(pd),
        fields["age_range_description"]: age_description,
        fields["material"]: _ride_on_material(pd),
        fields["color"]: pd.color,
        fields["size"]: _ride_on_size(pd),
        fields["part_number"]: pd.item_code,
        fields["theme_1"]: "Cars",
        fields["is_assembly_required"]: assembly_required,
        fields["assembly_time"]: assembly_time,
        fields["assembly_time_unit"]: assembly_time_unit,
        fields["seating_capacity"]: _ride_on_seating_capacity(pd),
        fields["voltage_value"]: voltage,
        fields["voltage_unit"]: "Volts",
        fields["unit_count"]: 1,
        fields["unit_count_type"]: "Count",
        fields["manufacturer_min_age"]: age_min,
        fields["manufacturer_max_age"]: age_max,
        fields["height_value"]: pd.dimension_height,
        fields["height_unit"]: "Inches",
        fields["length_value"]: pd.dimension_length,
        fields["length_unit"]: "Inches",
        fields["width_value"]: pd.dimension_width,
        fields["width_unit"]: "Inches",
        fields["item_weight_value"]: pd.weight,
        fields["item_weight_unit"]: "Pounds",
        fields["buyer_age_restrictions"]: "No",
        fields["cpsia_cautionary_statement_1"]: "No Warning Applicable",
        fields["pesticide_marking_type_1"]: "EPA Establishment Number",
        fields["pesticide_registration_status_1"]: "This product is not a pesticide or pesticide device, as defined under the U.S. Federal Insecticide, Fungicide, and Rodenticide Act.",
        fields["has_multiple_battery_powered_components"]: "No",
        fields["contains_battery_or_cell"]: "Battery",
        fields["battery_contains_free_unabsorbed_liquid"]: "No",
        fields["is_battery_non_spillable"]: "Yes" if battery["composition"] in ("Lead Acid", "Wet Alkali") else None,
        fields["non_lithium_battery_packaging"]: "Batteries contained in equipment" if not battery["composition"].startswith("Lithium") else None,
        fields["has_replaceable_battery"]: "Yes",
        fields["battery_installation_device_type"]: "Installed in Vehicle",
        fields["batteries_required"]: "Yes",
        fields["batteries_included"]: "Yes",
        fields["battery_cell_composition"]: battery["composition"],
        fields["num_batteries_quantity"]: battery["quantity"],
        fields["num_batteries_type"]: battery["type"],
    })

    if ships_globally:
        fill.update({
            fields["compliance_toy_voltage"]: "Up to 12 Volts" if voltage <= 12 else "More than 12 Volts",
            fields["compliance_toy_type"]: "Cars",
            fields["compliance_recommended_age"]: "Over 3 Years of Age" if age_min >= 36 else "Under 3 Years of Age",
            fields["compliance_operation_mode"]: "Electronic - Battery",
        })
    else:
        warnings.append("RIDE_ON_TOY 默认按美国 FBM 非全球配送生成，已跳过 Ships Globally 条件下才允许的 Toy Compliance 字段。")

    if battery.get("energy_content") and not battery["composition"].startswith("Lithium"):
        fill[fields["non_lithium_battery_energy_content"]] = battery["energy_content"]
        fill[fields["non_lithium_battery_energy_content_unit"]] = "Watt Hours"

    if battery["composition"].startswith("Lithium"):
        fill[fields["lithium_battery_packaging"]] = "Batteries contained in equipment"
        if battery.get("energy_content"):
            fill[fields["lithium_battery_energy_content"]] = battery["energy_content"]
            fill[fields["lithium_battery_energy_content_unit"]] = "Watt Hours"
        warnings.append("识别为锂电池类骑乘玩具，锂电池重量/电芯数量/UN运输信息可能还需人工补充。")

    raw = _facts_text(pd).lower()
    if any(word in raw for word in ("remote", "2.4g", "bluetooth", "wireless")):
        warnings.append("商品疑似含遥控/无线功能，模板未自动填写 FCC ID 或 SDoC 联系资料；如上架报错需补 FCC 合规资料。")
    warnings.append("未自动填写 UL/TUV/Intertek 等监管证书编号或合规媒体 URL；这些字段需要真实证书资料后再补。")

    for field, component in zip(fields.get("included_components", []), _ride_on_included_components(pd)):
        fill[field] = component

    return warnings


def _build_amazon_template_file(product: Product, pd: ProductData, mapping: dict) -> dict:
    """同步生成 Excel 文件。调用方应放到线程中执行，避免阻塞 API 事件循环。"""
    template_path = Path(mapping["template_path"])
    material_dir = Path(pd.material_dir) if pd.material_dir else Path.cwd() / "outputs"
    output_dir = material_dir / "amazon import"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_name = str(mapping.get("output_filename") or "{item_code}_amazon_import.xlsm").format(item_code=pd.item_code)
    output_path = output_dir / output_name
    shutil.copy2(template_path, output_path)

    wb = load_workbook(output_path, keep_vba=True, data_only=False)
    ws = wb["Template"]
    columns = _index_template_columns(ws)
    warnings: list[str] = []

    # 清空模板第8行的示例/偏好默认值，保留表头和验证规则。
    for cell in ws[DATA_ROW]:
        cell.value = None

    brand_col = columns.get("brand[marketplace_id=ATVPDKIKX0DER][language_tag=en_US]#1.value")
    if brand_col:
        _remove_column_validations(ws, brand_col)

    package, package_warnings = _representative_package(pd)
    warnings.extend(package_warnings)
    bullets = _json_loads(pd.listing_bullets, [])
    bullets = bullets if isinstance(bullets, list) else []

    fields = mapping["dynamic_fields"]
    fill = dict(mapping.get("fixed_values", {}))
    shipping_template = _first_template_value(wb, fields["shipping_template"])
    if not shipping_template:
        warnings.append("模板未找到 Shipping Template 下拉值，配送模板未填写。")
    stock_quantity = None
    inventory_available = "Disabled"

    fill.update({
        fields["sku"]: pd.item_code,
        fields["title"]: pd.listing_title,
        fields["brand"]: product.brand,
        fields["product_id_type"]: "UPC" if product.upc else "GTIN Exempt",
        fields["product_id_value"]: product.upc,
        fields["model_number"]: pd.item_code,
        fields["model_name"]: pd.item_code,
        fields["manufacturer"]: product.brand,
        fields["description"]: _description(pd),
        fields["search_terms"]: pd.listing_search_terms,
        fields["list_price"]: pd.suggested_price,
        fields["fulfillment_channel"]: "Fulfillment by Merchant (Default)",
        fields["quantity"]: stock_quantity,
        fields["inventory_available"]: inventory_available,
        fields["price"]: pd.suggested_price,
        fields["country_of_origin"]: pd.origin or "China",
        fields["shipping_template"]: shipping_template,
    })

    if mapping.get("category_type") == "ride_on_toy":
        item_type_option = select_ride_on_category(_facts_text(pd))
        if item_type_option:
            fill["item_type_keyword[marketplace_id=ATVPDKIKX0DER]#1.value"] = item_type_option.item_type_keyword
        else:
            warnings.append("未能匹配 RIDE_ON_TOY 细分类目，沿用模板默认儿童电瓶车类目。")
        warnings.extend(_apply_ride_on_toy_fill(fill, fields, product, pd))
    else:
        category_option, category_warnings = _apply_furniture_category_fill(fill, mapping, pd)
        warnings.extend(category_warnings)
        seating = _seating_capacity(pd)
        if category_option and category_option.get("product_type") == "CHAIR" and not seating:
            seating = 1
        if seating is None:
            warnings.append("未能从标题/描述识别座位数，Seating Capacity 暂未填写。")
        product_type = (category_option or {}).get("product_type")
        material = _material_value(pd)
        frame_material = _frame_material_value(pd)
        fill.update({
            fields["material"]: material,
            fields["fabric_type"]: _fabric_value(pd),
            fields["color"]: pd.color,
            fields["size"]: f'{pd.dimension_length:g}" x {pd.dimension_width:g}" x {pd.dimension_height:g}"' if pd.dimension_length and pd.dimension_width and pd.dimension_height else None,
            fields["number_of_pieces"]: 1,
            fields["item_shape"]: "Rectangular",
            fields["part_number"]: pd.item_code,
            fields["included_components"]: _included_components(pd, seating),
            fields["is_fragile"]: "No",
            fields["frame_material"]: frame_material,
            fields["frame_material_structured"]: frame_material,
            fields["unit_count"]: 1,
            fields["unit_count_type"]: "Count",
            fields["seat_depth"]: _seat_depth(pd),
            fields["seat_depth_unit"]: "Inches",
            fields["seat_height"]: 16,
            fields["seat_height_unit"]: "Inches",
            fields["weight_capacity_maximum"]: _weight_capacity_maximum(seating),
            fields["weight_capacity_maximum_unit"]: "Pounds",
            fields["maximum_weight_recommendation"]: _weight_capacity_maximum(seating),
            fields["maximum_weight_recommendation_unit"]: "Pounds",
            fields["depth_value"]: pd.dimension_width,
            fields["depth_unit"]: "Inches",
            fields["height_value"]: pd.dimension_height,
            fields["height_unit"]: "Inches",
            fields["width_value"]: pd.dimension_length,
            fields["width_unit"]: "Inches",
            fields["item_width_value"]: pd.dimension_length,
            fields["item_width_unit"]: "Inches",
            fields["item_length_value"]: pd.dimension_width,
            fields["item_length_unit"]: "Inches",
        })
        if seating:
            fill[fields["seating_capacity"]] = seating
        if product_type == "SOFA":
            _omit_fields(fill, fields, (
                "maximum_weight_recommendation",
                "maximum_weight_recommendation_unit",
            ))
            warnings.extend(_sofa_dimension_warnings(pd, fill, fields))
        if product_type == "CHAIR":
            fill[fields["included_components"]] = "Chair"
            _omit_fields(fill, fields, (
                "number_of_pieces",
                "seating_capacity",
                "weight_capacity_maximum",
                "weight_capacity_maximum_unit",
                "maximum_weight_recommendation",
                "maximum_weight_recommendation_unit",
                "item_length_value",
                "item_length_unit",
            ))
        if pd.weight:
            fill[fields["item_weight_value"]] = pd.weight
            fill[fields["item_weight_unit"]] = "Pounds"

    image_fill, image_warnings, uploaded_images = _upload_listing_images(product, pd, mapping)
    fill.update(image_fill)
    warnings.extend(image_warnings)
    if package:
        package_fields = mapping["package_fields"]
        fill.update({
            package_fields["length_value"]: package["length"],
            package_fields["length_unit"]: "Inches",
            package_fields["width_value"]: package["width"],
            package_fields["width_unit"]: "Inches",
            package_fields["height_value"]: package["height"],
            package_fields["height_unit"]: "Inches",
            package_fields["weight_value"]: package["weight"],
            package_fields["weight_unit"]: "Pounds",
        })

    for field, bullet in zip(mapping.get("bullet_fields", []), bullets[:5]):
        fill[field] = bullet

    missing_columns = []
    for attr, value in fill.items():
        if attr not in columns:
            missing_columns.append(attr)
            continue
        _set(ws, columns, attr, value)
    if missing_columns:
        warnings.append(f"模板中未找到 {len(missing_columns)} 个预期字段: {', '.join(missing_columns[:5])}")
    warnings.extend(_listing_template_warnings(pd))
    warnings.extend(_pricing_template_warnings(pd))
    warnings.extend(_inventory_template_warnings(pd))
    warnings.extend(_aplus_template_warnings(product))
    warnings.extend(_step6_main_image_warnings(product))
    warnings = list(dict.fromkeys(warnings))
    fill_summary = _build_fill_summary(mapping, fill, columns, warnings, missing_columns, uploaded_images)

    wb.save(output_path)

    return {
        "path": str(output_path),
        "warnings": warnings,
        "uploaded_images": uploaded_images,
        "fill_summary": fill_summary,
        "filled_fields": fill_summary["filled_count"],
    }


async def run_amazon_template(product_id: int) -> dict:
    """生成 Amazon 类目导入模板。"""
    async with async_session() as db:
        result = await db.execute(
            select(Product)
            .options(selectinload(Product.data), selectinload(Product.images), selectinload(Product.aplus))
            .where(Product.id == product_id)
        )
        product = result.scalar_one_or_none()
        if not product or not product.data:
            raise ValueError(f"Product {product_id} not found or no data")

        pd = product.data
        mapping = _load_template_mapping(product, pd)
        template_path = Path(mapping["template_path"])
        if not template_path.is_file():
            raise FileNotFoundError(f"模板文件不存在: {template_path}")
        if not pd.item_code:
            raise ValueError("缺少商品Code，无法生成SKU")
        if not pd.listing_title or not pd.listing_bullets:
            raise ValueError("缺少Listing文案，请先执行Step5")

        product_snapshot = _snapshot_model(product)
        product_snapshot.data = _snapshot_model(product.data)
        product_snapshot.images = _snapshot_model(product.images)
        product_snapshot.aplus = _snapshot_model(product.aplus)
        pd_snapshot = product_snapshot.data

    template_result = await asyncio.to_thread(_build_amazon_template_file, product_snapshot, pd_snapshot, mapping)
    output_path = Path(template_result["path"])

    async with async_session() as db:
        result = await db.execute(select(Product).options(selectinload(Product.data)).where(Product.id == product_id))
        product = result.scalar_one_or_none()
        if not product or not product.data:
            raise ValueError(f"Product {product_id} not found or no data")
        pd = product.data
        pd.amazon_template_path = template_result["path"]
        pd.amazon_template_warnings = json.dumps(template_result["warnings"], ensure_ascii=False)
        pd.amazon_template_fill_summary = json.dumps(template_result["fill_summary"], ensure_ascii=False)
        pd.amazon_template_generated_at = datetime.now()
        file_result = await db.execute(
            select(ProductFile).where(
                ProductFile.product_id == product.id,
                ProductFile.file_type == "amazon_import_template",
                ProductFile.path == template_result["path"],
            )
        )
        product_file = file_result.scalar_one_or_none()
        metadata_json = json.dumps({
            "warnings": template_result["warnings"],
            "uploaded_images": template_result["uploaded_images"],
            "fill_summary": template_result["fill_summary"],
            "filled_fields": template_result["filled_fields"],
        }, ensure_ascii=False)
        if product_file:
            product_file.label = "Amazon导入表格"
            product_file.directory = str(output_path.parent)
            product_file.metadata_json = metadata_json
            product_file.updated_at = datetime.now()
        else:
            db.add(ProductFile(
                product_id=product.id,
                file_type="amazon_import_template",
                label="Amazon导入表格",
                path=template_result["path"],
                directory=str(output_path.parent),
                metadata_json=metadata_json,
                created_at=datetime.now(),
                updated_at=datetime.now(),
            ))
        await db.commit()

        logger.info(f"[Step10] Amazon导入模板已生成: {output_path}")
        return template_result
