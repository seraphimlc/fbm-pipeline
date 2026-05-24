import subprocess
import shutil
import zipfile
import json
import re
from copy import copy
from io import BytesIO
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from openpyxl import Workbook, load_workbook
from sqlalchemy import delete, select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from datetime import datetime

from app.database import get_db
from app.config import settings
from app.models import (
    AplusRegenerateTask,
    AplusUploadBatch,
    AplusUploadItem,
    AsinSyncBatch,
    AsinSyncItem,
    CatalogProduct,
    InventorySyncBatch,
    InventorySyncItem,
    Product,
    ProductData,
    ProductImage,
    ProductAplus,
    ProductFile,
    UpcPoolItem,
)
from app.models.status import COMPLETED, DUPLICATE_SKIPPED, PENDING_REVIEW, SOURCE_UNAVAILABLE, STEP_LABELS, STEP_STATUS_MAP
from app.api.schemas import (
    ProductCreate, ProductUpdate, ProductResponse, ProductDetail,
    PaginatedResponse, ProductFileEntry, AplusRegenerateRequest,
    AsinSyncBatchDetail, AsinSyncBatchResponse, AsinSyncCreateRequest,
    AplusUploadBatchDetail, AplusUploadBatchResponse, AplusUploadCreateRequest,
    BulkImportResponse, BulkStartRequest, BulkStartResponse,
    PaginatedAsinSyncBatches, PaginatedCatalogProducts, CatalogProductResponse,
    PaginatedAplusUploadBatches, WorkbenchOverview, CatalogAsinUpdateRequest,
    InventorySyncBatchDetail, InventorySyncBatchResponse, InventorySyncCreateRequest,
    PaginatedInventorySyncBatches, PaginatedUpcPoolItems, UpcPoolImportRequest,
    UpcPoolImportResponse, UpcPoolSummary,
)
from app.pipeline.engine import start_pipeline as enqueue_pipeline, cancel_pipeline, is_running
from app.pipeline.step1_collect import collect_product
from app.pipeline.step2_pricing import run_pricing
from app.pipeline.step3_keywords import run_keywords
from app.pipeline.step4_category import run_category
from app.pipeline.step5_listing import run_listing
from app.pipeline.step6_image import run_image_analysis
from app.pipeline.step7_aplus_plan import run_aplus_plan
from app.pipeline.step8_aplus_script import run_aplus_script
from app.pipeline.step9_aplus_image import run_aplus_image
from app.pipeline.ride_on_category import RIDE_ON_CATEGORY_OPTIONS
from app.pipeline.step10_amazon_template import (
    AMAZON_TEMPLATE_LOGIC_VERSION,
    DATA_ROW,
    MAPPING_DIR,
    _load_template_mapping,
    _offer_quantity,
    _representative_package,
    run_amazon_template,
)
from app.services.material_assets import (
    IMAGE_EXTENSIONS,
    VIDEO_EXTENSIONS,
    aplus_folder_summary,
    aplus_image_folder,
    folder_summary,
    organize_video_files,
)
from app.services.asin_sync import build_sync_item, start_asin_sync_batch
from app.services.inventory_sync import (
    InventorySyncLoginRequired,
    assert_gigab2b_logged_in_for_inventory,
    build_inventory_sync_item,
    start_inventory_sync_batch,
)
from app.services.aplus_upload import build_upload_item, start_aplus_upload_batch
from app.services.aplus_regenerate import create_regenerate_task, retry_latest_regenerate_tasks
from app.services.product_duplicates import (
    extract_gigab2b_item_code_from_url,
    extract_gigab2b_product_id,
    find_duplicate_by_gigab2b_product_id,
    find_duplicate_by_item_code,
)
from app.services.upc_pool import (
    UpcPoolEmptyError,
    add_upcs_to_pool,
    available_upc_count,
    ensure_product_upc,
)

# Step runners indexed by step number
STEP_RUNNERS = {
    1: collect_product,
    2: run_pricing,
    3: run_keywords,
    4: run_category,
    5: run_listing,
    6: run_image_analysis,
    7: run_aplus_plan,
    8: run_aplus_script,
    9: run_aplus_image,
    10: run_amazon_template,
}

router = APIRouter(prefix="/api/products", tags=["products"])


ZIP_EXTENSIONS = {".zip"}
MATERIAL_IMAGE_EXTENSIONS = IMAGE_EXTENSIONS
RUNNING_STATUSES = {
    "step1_collecting",
    "step2_pricing",
    "step3_keywords",
    "step4_category",
    "step5_listing",
    "step6_curating",
    "step7_aplus_plan",
    "step8_aplus_script",
    "step9_aplus_image",
    "step10_amazon_template",
}


def _compact_error_message(message: str | None) -> str | None:
    if not message:
        return None
    return " ".join(message.strip().splitlines())[:120]


def _current_task_status(product: Product) -> str:
    aplus_status = product.aplus.aplus_status if product.aplus else None
    aplus_status_labels = {
        "regen_queued": "A+重新生图排队中",
        "regen_script_running": "A+正在重写脚本",
        "regen_image_running": "A+正在重新生图",
        "regen_done": "A+重新生图完成",
        "regen_failed": "A+重新生图失败",
        "regen_interrupted": "A+重新生图被中断，可重试",
    }
    if aplus_status in aplus_status_labels:
        return aplus_status_labels[aplus_status]

    step_label = STEP_LABELS.get(product.current_step, f"Step {product.current_step}")
    if product.status in RUNNING_STATUSES:
        return f"运行中：{step_label}"
    if product.status == "created":
        return "待启动"
    if product.status == "paused":
        return f"已暂停：{step_label}"
    if product.status == "pending_review":
        detail = _compact_error_message(product.error_message)
        return f"待人工处理：{detail or step_label}"
    if product.status == "failed":
        detail = _compact_error_message(product.error_message)
        return f"失败：{detail or step_label}"
    if product.status == SOURCE_UNAVAILABLE:
        detail = _compact_error_message(product.error_message)
        return f"原商品下架停止采集：{detail}" if detail else "原商品下架停止采集"
    if product.status == DUPLICATE_SKIPPED:
        detail = _compact_error_message(product.error_message)
        return f"重复商品已跳过：{detail}" if detail else "重复商品已跳过"
    if product.status == "unavailable":
        detail = _compact_error_message(product.error_message)
        return f"商品已下架：{detail}" if detail else "商品已下架"
    if product.status == COMPLETED:
        return "已完成"
    return product.status or "-"


def _split_category_path(value: str | None) -> list[str]:
    if not value:
        return []
    return [part.strip() for part in re.split(r"\s*>\s*|\s*›\s*", str(value)) if part.strip()]


def _category_option_key(categories: list[str], leaf_category: str | None) -> str:
    return " > ".join(categories) or (leaf_category or "")


def _static_category_options() -> list[dict]:
    options: dict[str, dict] = {}

    for option in RIDE_ON_CATEGORY_OPTIONS:
        categories = option.categories
        key = _category_option_key(categories, option.leaf_category)
        options[key] = {
            "key": key,
            "label": " > ".join(categories),
            "categories": categories,
            "leaf_category": option.leaf_category,
            "source": "ride_on_toy",
        }

    # 项目规则：同一类目 key 冲突时，后导入的映射覆盖前者；
    # 只替换冲突类目，其他类目继续保留。
    for mapping_path in sorted(MAPPING_DIR.glob("*.json")):
        try:
            mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        for item in mapping.get("browse_category_options") or []:
            if not isinstance(item, dict):
                continue
            path = str(item.get("path") or "").strip()
            node = str(item.get("node") or "").strip()
            categories = _split_category_path(path)
            if not categories:
                continue
            leaf = f"{categories[-1]} ({node})" if node else categories[-1]
            option_categories = [*categories[:-1], leaf]
            key = _category_option_key(option_categories, leaf)
            options[key] = {
                "key": key,
                "label": " > ".join(option_categories),
                "categories": option_categories,
                "leaf_category": leaf,
                "source": mapping_path.stem,
            }

    return sorted(options.values(), key=lambda item: item["label"])


IMPORT_TEMPLATE_HEADERS = ["原始数据链接", "竞品ASIN"]
HEADER_ALIASES = {
    "原始数据链接": "gigab2b_url",
    "来源链接": "gigab2b_url",
    "源链接": "gigab2b_url",
    "source_url": "gigab2b_url",
    "大健云仓商品链接": "gigab2b_url",
    "大建云仓商品链接": "gigab2b_url",
    "商品链接": "gigab2b_url",
    "gigab2b_url": "gigab2b_url",
    "url": "gigab2b_url",
    "竞品ASIN": "competitor_asin",
    "竞品 ASIN": "competitor_asin",
    "competitor_asin": "competitor_asin",
    "asin": "competitor_asin",
    "UPC": "upc",
    "upc": "upc",
    "品牌": "brand",
    "brand": "brand",
}


def _is_in_dir(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _safe_material_dir(product: Product) -> Path:
    material_dir = product.data.material_dir if product.data else None
    if not material_dir:
        raise HTTPException(400, "素材目录不存在")
    path = Path(material_dir).expanduser().resolve()
    if not path.is_dir():
        raise HTTPException(404, f"素材目录不存在: {material_dir}")
    return path


def _summarize_extracted_files(extracted_dir: Path, limit: int = 30) -> list[str]:
    if not extracted_dir.is_dir():
        return []

    priority_words = ("认证", "证书", "certificate", "certification", "cert", "cpsia", "astm", "prop", "test", "report")
    files: list[Path] = []
    for path in extracted_dir.rglob("*"):
        if path.is_file():
            files.append(path)

    files.sort(key=lambda p: (not any(word in p.name.lower() for word in priority_words), str(p).lower()))
    return [str(path.relative_to(extracted_dir)) for path in files[:limit]]


def _find_extracted_dir(material_dir: Path, zip_path: Path) -> Path:
    default_dir = zip_path.with_suffix("")
    if default_dir.is_dir():
        return default_dir

    for path in material_dir.rglob(zip_path.stem):
        if path.is_dir():
            return path

    return default_dir


def _scan_zip_files(material_dir: Path) -> list[ProductFileEntry]:
    entries: list[ProductFileEntry] = []
    for path in sorted(material_dir.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in ZIP_EXTENSIONS:
            continue
        stat = path.stat()
        extracted_dir = _find_extracted_dir(material_dir, path)
        entries.append(ProductFileEntry(
            name=path.name,
            path=str(path),
            size=stat.st_size,
            modified_at=datetime.fromtimestamp(stat.st_mtime),
            extracted_dir=str(extracted_dir),
            extracted_exists=extracted_dir.is_dir(),
            extracted_files=_summarize_extracted_files(extracted_dir),
        ))
    return entries


def _count_material_images(material_dir: Path) -> int:
    count = 0
    for path in material_dir.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in MATERIAL_IMAGE_EXTENSIONS:
            continue
        name = path.name.lower()
        path_text = str(path).lower()
        if "new " in path_text or "image analysis" in path_text or name == "contact_sheet.jpg":
            continue
        count += 1
    return count


def _build_list_item(product: Product) -> dict:
    return {
        "id": product.id,
        "source_url": product.gigab2b_url,
        "source_item_id": product.gigab2b_product_id,
        "gigab2b_url": product.gigab2b_url,
        "gigab2b_product_id": product.gigab2b_product_id,
        "competitor_asin": product.competitor_asin,
        "amazon_asin": product.amazon_asin,
        "asin_sync_status": product.asin_sync_status,
        "asin_synced_at": product.asin_synced_at,
        "asin_sync_error": product.asin_sync_error,
        "aplus_upload_status": product.aplus_upload_status,
        "aplus_uploaded_at": product.aplus_uploaded_at,
        "aplus_upload_error": product.aplus_upload_error,
        "upc": product.upc,
        "brand": product.brand,
        "status": product.status,
        "current_step": product.current_step,
        "current_task_status": _current_task_status(product),
        "error_message": product.error_message,
        "created_at": product.created_at,
        "updated_at": product.updated_at,
        "item_code": product.data.item_code if product.data else None,
        "title": product.data.title if product.data else None,
        "leaf_category": product.data.leaf_category if product.data else None,
    }


def _template_risk_from_data(pd: ProductData | None) -> tuple[str | None, int | None]:
    if not pd:
        return None, None
    summary = {}
    warnings = []
    try:
        summary = json.loads(pd.amazon_template_fill_summary or "{}")
    except Exception:
        summary = {}
    try:
        warnings = json.loads(pd.amazon_template_warnings or "[]")
    except Exception:
        warnings = []
    risk = summary.get("risk_level") if isinstance(summary, dict) else None
    warning_count = len(warnings) if isinstance(warnings, list) else None
    return risk, warning_count


def _amazon_template_cache_path(pd: ProductData | None) -> Path | None:
    if not pd or not pd.amazon_template_path:
        return None
    source_path = Path(pd.amazon_template_path).expanduser()
    if not source_path.is_file():
        return None
    try:
        summary = json.loads(pd.amazon_template_fill_summary or "{}")
    except Exception:
        summary = {}
    if not isinstance(summary, dict) or summary.get("logic_version") != AMAZON_TEMPLATE_LOGIC_VERSION:
        return None
    return source_path


def _safe_json(value: str | None, fallback):
    if not value:
        return fallback
    try:
        parsed = json.loads(value)
        return parsed if parsed is not None else fallback
    except Exception:
        return fallback


def _shipping_template_preview(product: Product, pd: ProductData, mapping: dict) -> str | None:
    preferences = mapping.get("shipping_template_by_brand") or {}
    for candidate in (product.brand, settings.DEFAULT_BRAND, "Andy店-US", "*"):
        preferred = preferences.get(str(candidate or ""))
        if preferred:
            return preferred
    return None


def _build_amazon_export_preview(product: Product) -> dict | None:
    pd = product.data
    if not pd:
        return None
    try:
        mapping = _load_template_mapping(product, pd)
    except Exception as exc:
        return {"available": False, "error": f"{type(exc).__name__}: {exc}"}

    package, package_warnings = _representative_package(pd)
    try:
        quantity = _offer_quantity(pd)
    except Exception as exc:
        quantity = None
        package_warnings.append(str(exc))

    fields = mapping.get("dynamic_fields") or {}
    return {
        "available": True,
        "logic_version": AMAZON_TEMPLATE_LOGIC_VERSION,
        "template_path": mapping.get("template_path"),
        "output_filename": str(mapping.get("output_filename") or "{item_code}_amazon_import.xlsm").format(item_code=pd.item_code),
        "category": pd.leaf_category or mapping.get("category") or mapping.get("category_type"),
        "field_attributes": {
            "shipping_template": fields.get("shipping_template"),
            "price": fields.get("price"),
            "quantity": fields.get("quantity"),
            "product_weight": fields.get("item_weight_value"),
        },
        "offer": {
            "sku": pd.item_code,
            "brand": product.brand,
            "fulfillment_channel": "Fulfillment by Merchant (Default)",
            "shipping_template": _shipping_template_preview(product, pd, mapping),
            "quantity": quantity,
            "price": pd.suggested_price,
            "list_price": pd.suggested_price,
            "country_of_origin": pd.origin or "China",
        },
        "product_dimensions": {
            "length": pd.dimension_length,
            "width": pd.dimension_width,
            "height": pd.dimension_height,
            "unit": "Inches",
            "size_text": (
                f'{pd.dimension_length:g}" x {pd.dimension_width:g}" x {pd.dimension_height:g}"'
                if pd.dimension_length and pd.dimension_width and pd.dimension_height
                else None
            ),
        },
        "product_weight": {
            "value": pd.weight,
            "unit": "Pounds" if pd.weight else None,
        },
        "package_aggregate": {
            **(package or {}),
            "length_unit": "Inches" if package else None,
            "weight_unit": "Pounds" if package else None,
            "warnings": package_warnings,
        },
        "package_items": _safe_json(pd.packages, []),
        "source_costs": {
            "value_total": pd.value_total,
            "estimated_total": pd.estimated_total,
            "shipping_cost": pd.shipping_cost,
            "shipping_cost_min": pd.shipping_cost_min,
            "shipping_cost_max": pd.shipping_cost_max,
            "suggested_price": pd.suggested_price,
            "cost_total": pd.cost_total,
            "profit": pd.profit,
            "profit_rate": pd.profit_rate,
        },
    }


def _sync_catalog_item(product: Product, db: AsyncSession, confirm: bool = False) -> CatalogProduct:
    pd = product.data
    item = product.catalog_item
    if not item:
        item = CatalogProduct(source_product_id=product.id, gigab2b_url=product.gigab2b_url)
        db.add(item)

    item.gigab2b_url = product.gigab2b_url
    item.gigab2b_product_id = product.gigab2b_product_id
    item.competitor_asin = product.competitor_asin
    item.amazon_asin = product.amazon_asin
    item.asin_sync_status = product.asin_sync_status
    item.asin_synced_at = product.asin_synced_at
    item.asin_sync_error = product.asin_sync_error
    item.aplus_upload_status = product.aplus_upload_status
    item.aplus_uploaded_at = product.aplus_uploaded_at
    item.aplus_upload_error = product.aplus_upload_error
    item.upc = product.upc
    item.brand = product.brand
    item.item_code = pd.item_code if pd else None
    item.title = pd.title if pd else None
    item.leaf_category = pd.leaf_category if pd else None
    item.status = product.status
    if confirm and item.confirmed_at is None:
        item.confirmed_at = datetime.now()
    item.updated_at = datetime.now()
    return item


def _mark_pipeline_starting(product: Product) -> None:
    product.status = "step1_collecting"
    product.current_step = 1
    product.error_message = None
    product.updated_at = datetime.now()


def _workbook_response(wb: Workbook, filename: str) -> StreamingResponse:
    stream = BytesIO()
    wb.save(stream)
    stream.seek(0)
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return StreamingResponse(
        stream,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=headers,
    )


async def _upc_pool_summary(db: AsyncSession) -> UpcPoolSummary:
    total_result = await db.execute(select(func.count(UpcPoolItem.id)))
    available_result = await db.execute(
        select(func.count(UpcPoolItem.id)).where(UpcPoolItem.status == "available")
    )
    bound_result = await db.execute(
        select(func.count(UpcPoolItem.id)).where(UpcPoolItem.status == "bound")
    )
    return UpcPoolSummary(
        total=total_result.scalar() or 0,
        available=available_result.scalar() or 0,
        bound=bound_result.scalar() or 0,
    )


def _catalog_export_row(product: Product) -> dict:
    pd = product.data
    return {
        "任务ID": product.id,
        "原始数据链接": product.gigab2b_url,
        "来源商品ID": product.gigab2b_product_id,
        "商品Code": pd.item_code if pd else None,
        "竞品ASIN": product.competitor_asin,
        "真实ASIN": product.amazon_asin,
        "ASIN同步状态": product.asin_sync_status,
        "ASIN同步信息": product.asin_sync_error,
        "UPC": product.upc,
        "A+上传状态": product.aplus_upload_status,
        "A+上传信息": product.aplus_upload_error,
        "品牌": product.brand,
        "类目": pd.leaf_category if pd else None,
        "标题": pd.title if pd else None,
        "颜色": pd.color if pd else None,
        "材质": pd.material if pd else None,
        "产品类型": pd.product_type if pd else None,
        "建议售价": pd.suggested_price if pd else None,
        "总成本": pd.cost_total if pd else None,
        "利润": pd.profit if pd else None,
        "利润率": pd.profit_rate if pd else None,
        "Listing标题": pd.listing_title if pd else None,
        "Search Terms": pd.listing_search_terms if pd else None,
    }


def _safe_export_name(value: str | None, fallback: str = "未分类") -> str:
    raw = (value or fallback).strip() or fallback
    return "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in raw)[:90] or fallback


def _copy_row_format(ws, source_row: int, target_row: int) -> None:
    if target_row == source_row:
        return
    ws.row_dimensions[target_row].height = ws.row_dimensions[source_row].height
    for col in range(1, ws.max_column + 1):
        source = ws.cell(source_row, col)
        target = ws.cell(target_row, col)
        if source.has_style:
            target._style = copy(source._style)
        if source.number_format:
            target.number_format = source.number_format
        if source.alignment:
            target.alignment = copy(source.alignment)
        if source.protection:
            target.protection = copy(source.protection)


def _clear_template_data_rows(ws, row_count: int) -> None:
    max_row = max(ws.max_row, DATA_ROW + row_count + 2)
    for row in range(DATA_ROW, max_row + 1):
        if row > DATA_ROW:
            _copy_row_format(ws, DATA_ROW, row)
        for col in range(1, ws.max_column + 1):
            ws.cell(row, col).value = None


def _template_attribute_columns(ws) -> dict[str, int]:
    return {
        str(cell.value): cell.column
        for cell in ws[5]
        if cell.value not in (None, "")
    }


def _copy_import_data_row(source_path: Path, target_ws, target_row: int) -> None:
    source_wb = load_workbook(source_path, keep_vba=True, data_only=False)
    if "Template" not in source_wb.sheetnames:
        raise ValueError(f"导入表格缺少 Template 工作表: {source_path}")
    source_ws = source_wb["Template"]
    _copy_row_format(target_ws, DATA_ROW, target_row)
    source_columns = _template_attribute_columns(source_ws)
    target_columns = _template_attribute_columns(target_ws)
    for attr, source_col in source_columns.items():
        target_col = target_columns.get(attr)
        if target_col:
            target_ws.cell(target_row, target_col).value = source_ws.cell(DATA_ROW, source_col).value


def _catalog_stock_export_override(ws, mapping: dict, catalog: CatalogProduct | None) -> tuple[int, int] | None:
    if not catalog or catalog.stock is None:
        return None
    if catalog.stock <= 0:
        raise ValueError(f"运营库存为 {catalog.stock}，无可售库存，已停止导出 Amazon 导入表格。")
    quantity_attr = (mapping.get("dynamic_fields") or {}).get("quantity")
    if not quantity_attr:
        return None
    quantity_col = _template_attribute_columns(ws).get(str(quantity_attr))
    if not quantity_col:
        raise ValueError("模板未找到 Amazon 数量字段，无法写入运营库存。")
    return quantity_col, catalog.stock


def _summary_workbook(rows: list[dict]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "导出报告"
    headers = ["状态", "商品ID", "商品Code", "类目", "模板文件", "导出文件", "原因"]
    ws.append(headers)
    for row in rows:
        ws.append([row.get(header) for header in headers])
    for column_cells in ws.columns:
        column_letter = column_cells[0].column_letter
        max_length = max(len(str(cell.value or "")) for cell in column_cells[:80])
        ws.column_dimensions[column_letter].width = min(max(max_length + 2, 12), 60)
    stream = BytesIO()
    wb.save(stream)
    return stream.getvalue()


PRICE_QUANTITY_DATA_ROW = 7
PRICE_QUANTITY_FORMAT_ROW = 6
PRICE_QUANTITY_SKU_ATTR = "contribution_sku#1.value"
PRICE_QUANTITY_FULFILLMENT_ATTR = "fulfillment_availability#1.fulfillment_channel_code"
PRICE_QUANTITY_QUANTITY_ATTR = "fulfillment_availability#1.quantity"
PRICE_QUANTITY_INVENTORY_ALWAYS_AVAILABLE_ATTR = "fulfillment_availability#1.is_inventory_available"
PRICE_QUANTITY_FBM_VALUE = "Fulfillment by Merchant (Default)"


def _inventory_update_report_workbook(rows: list[dict]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "库存模板导出报告"
    headers = ["状态", "商品资料ID", "任务ID", "商品Code", "真实ASIN", "SKU", "库存", "导出文件", "原因"]
    ws.append(headers)
    for row in rows:
        ws.append([row.get(header) for header in headers])
    for column_cells in ws.columns:
        column_letter = column_cells[0].column_letter
        max_length = max(len(str(cell.value or "")) for cell in column_cells[:80])
        ws.column_dimensions[column_letter].width = min(max(max_length + 2, 12), 60)
    stream = BytesIO()
    wb.save(stream)
    return stream.getvalue()


def _clear_price_quantity_data_rows(ws, row_count: int) -> None:
    max_row = max(ws.max_row, PRICE_QUANTITY_DATA_ROW + row_count + 2)
    for row in range(PRICE_QUANTITY_DATA_ROW, max_row + 1):
        _copy_row_format(ws, PRICE_QUANTITY_FORMAT_ROW, row)
        for col in range(1, ws.max_column + 1):
            ws.cell(row, col).value = None


def _catalog_price_quantity_sku(catalog: CatalogProduct) -> str:
    product = catalog.source_product
    product_data = product.data if product and product.data else None
    return str(catalog.item_code or (product_data.item_code if product_data else "") or "").strip()


def _naive_datetime(value: datetime | None) -> datetime | None:
    if value and value.tzinfo:
        return value.replace(tzinfo=None)
    return value


def _delete_material_dir(material_dir: str | None) -> None:
    if not material_dir:
        return

    path = Path(material_dir).expanduser().resolve()
    allowed_root = Path(settings.PRODUCT_BASE_DIR).expanduser().resolve()
    if not _is_in_dir(path, allowed_root):
        raise HTTPException(403, "素材目录不在允许删除的商品目录内")
    if path.is_dir():
        shutil.rmtree(path)


def _reset_product_data(pd: ProductData) -> None:
    for column in ProductData.__table__.columns:
        if column.name in {"id", "product_id"}:
            continue
        setattr(pd, column.name, None)


def _reset_product_images(pi: ProductImage) -> None:
    for column in ProductImage.__table__.columns:
        if column.name in {"id", "product_id"}:
            continue
        if column.name == "vlm_model":
            setattr(pi, column.name, settings.VLM_MODEL)
        else:
            setattr(pi, column.name, None)


def _reset_product_aplus(pa: ProductAplus) -> None:
    for column in ProductAplus.__table__.columns:
        if column.name in {"id", "product_id"}:
            continue
        if column.name == "llm_model":
            setattr(pa, column.name, settings.LLM_MODEL)
        else:
            setattr(pa, column.name, None)


async def _raise_if_duplicate_gigab2b_url(db: AsyncSession, gigab2b_url: str) -> None:
    gigab2b_product_id = extract_gigab2b_product_id(gigab2b_url)
    duplicate = await find_duplicate_by_gigab2b_product_id(db, gigab2b_product_id)
    if duplicate:
        raise HTTPException(409, f"{duplicate.message}，已跳过创建")
    url_item_code = extract_gigab2b_item_code_from_url(gigab2b_url)
    duplicate = await find_duplicate_by_item_code(db, url_item_code)
    if duplicate:
        raise HTTPException(409, f"{duplicate.message}，已跳过创建")


@router.post("", response_model=ProductResponse, status_code=201)
async def create_product(body: ProductCreate, db: AsyncSession = Depends(get_db)):
    """创建新商品任务"""
    await _raise_if_duplicate_gigab2b_url(db, body.gigab2b_url)
    gigab2b_product_id = extract_gigab2b_product_id(body.gigab2b_url)
    product = Product(
        gigab2b_url=body.gigab2b_url,
        gigab2b_product_id=gigab2b_product_id,
        competitor_asin=body.competitor_asin,
        brand=body.brand,
    )
    db.add(product)
    await db.flush()
    try:
        await ensure_product_upc(db, product)
    except UpcPoolEmptyError as exc:
        raise HTTPException(400, str(exc))
    # 创建关联空子表
    db.add(ProductData(product_id=product.id))
    db.add(ProductImage(product_id=product.id))
    db.add(ProductAplus(product_id=product.id))
    db.add(CatalogProduct(
        source_product_id=product.id,
        gigab2b_url=product.gigab2b_url,
        gigab2b_product_id=product.gigab2b_product_id,
        competitor_asin=product.competitor_asin,
        asin_sync_status=product.asin_sync_status or "not_synced",
        aplus_upload_status=product.aplus_upload_status or "not_uploaded",
        upc=product.upc,
        brand=product.brand,
        status=product.status,
    ))
    await db.commit()
    await db.refresh(product)
    return product


@router.get("/overview", response_model=WorkbenchOverview)
async def get_workbench_overview(db: AsyncSession = Depends(get_db)):
    """工作台概览：用于顶部快速发现需要处理的任务和商品。"""
    running_result = await db.execute(select(func.count(Product.id)).where(Product.status.in_(RUNNING_STATUSES)))
    manual_result = await db.execute(select(func.count(Product.id)).where(Product.status == PENDING_REVIEW, Product.current_step < 10))
    failed_result = await db.execute(select(func.count(Product.id)).where(Product.status == "failed"))
    confirmable_result = await db.execute(select(func.count(Product.id)).where(Product.status == PENDING_REVIEW, Product.current_step >= 10))
    asin_not_synced_result = await db.execute(
        select(func.count(CatalogProduct.id)).where(
            CatalogProduct.confirmed_at.is_not(None),
            ((CatalogProduct.amazon_asin.is_(None)) | (CatalogProduct.amazon_asin == "")),
            ((CatalogProduct.asin_sync_status.is_(None)) | (CatalogProduct.asin_sync_status.in_(("not_synced", "skipped")))),
        )
    )
    asin_attention_result = await db.execute(
        select(func.count(CatalogProduct.id)).where(
            CatalogProduct.confirmed_at.is_not(None),
            CatalogProduct.asin_sync_status.in_(("not_found", "multiple_found", "failed")),
        )
    )
    aplus_failed_result = await db.execute(
        select(func.count(CatalogProduct.id)).where(
            CatalogProduct.confirmed_at.is_not(None),
            CatalogProduct.aplus_upload_status == "failed",
        )
    )
    listing_high_risk_result = await db.execute(
        select(func.count(ProductData.id))
        .join(CatalogProduct, CatalogProduct.source_product_id == ProductData.product_id)
        .where(
            CatalogProduct.confirmed_at.is_not(None),
            ProductData.amazon_template_fill_summary.like('%"risk_level"%high_risk%'),
        )
    )
    return WorkbenchOverview(
        running_tasks=running_result.scalar() or 0,
        manual_review_tasks=manual_result.scalar() or 0,
        failed_tasks=failed_result.scalar() or 0,
        confirmable_tasks=confirmable_result.scalar() or 0,
        asin_not_synced=asin_not_synced_result.scalar() or 0,
        asin_attention=asin_attention_result.scalar() or 0,
        aplus_failed=aplus_failed_result.scalar() or 0,
        listing_high_risk=listing_high_risk_result.scalar() or 0,
    )


@router.get("/category-options")
async def list_category_options(db: AsyncSession = Depends(get_db)):
    """返回人工编辑 Amazon 类目时允许选择的已有类目。"""
    options: dict[str, dict] = {item["key"]: item for item in _static_category_options()}
    result = await db.execute(
        select(ProductData.categories, ProductData.leaf_category)
        .where((ProductData.categories.is_not(None)) | (ProductData.leaf_category.is_not(None)))
    )
    for categories_raw, leaf in result.all():
        categories: list[str] = []
        if categories_raw:
            try:
                parsed = json.loads(categories_raw)
                if isinstance(parsed, list):
                    categories = [str(item).strip() for item in parsed if str(item).strip()]
                else:
                    categories = _split_category_path(str(parsed))
            except Exception:
                categories = _split_category_path(str(categories_raw))
        leaf = str(leaf or "").strip() or (categories[-1] if categories else "")
        if not categories and leaf:
            categories = [leaf]
        if not categories:
            continue
        key = _category_option_key(categories, leaf)
        options[key] = {
            "key": key,
            "label": " > ".join(categories),
            "categories": categories,
            "leaf_category": leaf,
            "source": "history",
        }
    return {"items": sorted(options.values(), key=lambda item: item["label"])}


async def _allowed_category_keys(db: AsyncSession) -> set[str]:
    result = await list_category_options(db)
    return {str(item.get("key") or "") for item in result.get("items", [])}


@router.get("", response_model=PaginatedResponse)
async def list_products(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str | None = None,
    item_id: str | None = None,
    competitor_asin: str | None = None,
    upc: str | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    db: AsyncSession = Depends(get_db),
):
    """商品任务列表（分页）"""
    query = select(Product).options(selectinload(Product.data), selectinload(Product.aplus)).order_by(Product.created_at.desc())
    count_query = select(func.count(Product.id))

    if status:
        query = query.where(Product.status == status)
        count_query = count_query.where(Product.status == status)
    if item_id:
        pattern = f"%{item_id.strip()}%"
        query = query.join(ProductData, ProductData.product_id == Product.id, isouter=True).where(
            (Product.gigab2b_product_id.ilike(pattern)) | (ProductData.item_code.ilike(pattern))
        )
        count_query = count_query.join(ProductData, ProductData.product_id == Product.id, isouter=True).where(
            (Product.gigab2b_product_id.ilike(pattern)) | (ProductData.item_code.ilike(pattern))
        )
    if competitor_asin:
        pattern = f"%{competitor_asin.strip()}%"
        query = query.where(Product.competitor_asin.ilike(pattern))
        count_query = count_query.where(Product.competitor_asin.ilike(pattern))
    if upc:
        pattern = f"%{upc.strip()}%"
        query = query.where(Product.upc.ilike(pattern))
        count_query = count_query.where(Product.upc.ilike(pattern))
    created_from = _naive_datetime(created_from)
    created_to = _naive_datetime(created_to)
    if created_from:
        query = query.where(Product.created_at >= created_from)
        count_query = count_query.where(Product.created_at >= created_from)
    if created_to:
        query = query.where(Product.created_at <= created_to)
        count_query = count_query.where(Product.created_at <= created_to)

    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    result = await db.execute(
        query.offset((page - 1) * page_size).limit(page_size)
    )
    items = result.scalars().all()

    return PaginatedResponse(items=[_build_list_item(item) for item in items], total=total, page=page, page_size=page_size)


@router.get("/import/template")
async def download_import_template():
    """下载批量创建任务模板。"""
    wb = Workbook()
    ws = wb.active
    ws.title = "批量导入任务"
    ws.append(IMPORT_TEMPLATE_HEADERS)
    ws.append(["https://www.gigab2b.com/product-detail/example", "B0XXXXXXXX"])
    for width, column in zip((42, 18), ("A", "B")):
        ws.column_dimensions[column].width = width
    return _workbook_response(wb, "fbm_task_import_template.xlsx")


@router.post("/import", response_model=BulkImportResponse)
async def import_products(file: UploadFile = File(...), db: AsyncSession = Depends(get_db)):
    """批量导入任务，并同步创建商品资料记录。"""
    if not file.filename or not file.filename.lower().endswith((".xlsx", ".xlsm")):
        raise HTTPException(400, "请上传 xlsx/xlsm Excel 文件")

    try:
        content = await file.read()
        wb = load_workbook(BytesIO(content), data_only=True)
    except Exception:
        raise HTTPException(400, "Excel 文件无法读取")

    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        raise HTTPException(400, "Excel 文件为空")

    header_row = [str(cell).strip() if cell is not None else "" for cell in rows[0]]
    index_map: dict[str, int] = {}
    for idx, header in enumerate(header_row):
        normalized = header.replace(" ", "")
        field = HEADER_ALIASES.get(header) or HEADER_ALIASES.get(normalized) or HEADER_ALIASES.get(header.lower())
        if field:
            index_map[field] = idx

    if "gigab2b_url" not in index_map or "competitor_asin" not in index_map:
        raise HTTPException(400, "模板必须包含：原始数据链接、竞品ASIN")

    created_ids: list[int] = []
    errors: list[str] = []
    skipped_details: list[str] = []
    skipped = 0
    seen_product_ids: dict[str, int] = {}
    seen_item_codes: dict[str, int] = {}
    remaining_upcs = await available_upc_count(db)

    for row_number, row in enumerate(rows[1:], start=2):
        values = list(row)
        gigab2b_url = str(values[index_map["gigab2b_url"]]).strip() if index_map["gigab2b_url"] < len(values) and values[index_map["gigab2b_url"]] is not None else ""
        competitor_asin = str(values[index_map["competitor_asin"]]).strip() if index_map["competitor_asin"] < len(values) and values[index_map["competitor_asin"]] is not None else ""
        brand = "Vindhvisk"
        if "brand" in index_map and index_map["brand"] < len(values) and values[index_map["brand"]] is not None:
            brand = str(values[index_map["brand"]]).strip() or brand

        if not any([gigab2b_url, competitor_asin]):
            skipped += 1
            continue
        if not gigab2b_url or not competitor_asin:
            errors.append(f"第 {row_number} 行缺少必填字段")
            continue

        gigab2b_product_id = extract_gigab2b_product_id(gigab2b_url)
        url_item_code = extract_gigab2b_item_code_from_url(gigab2b_url)
        if gigab2b_product_id and gigab2b_product_id in seen_product_ids:
            skipped += 1
            skipped_details.append(f"第 {row_number} 行跳过：大建云仓商品ID {gigab2b_product_id} 已在第 {seen_product_ids[gigab2b_product_id]} 行导入")
            continue
        if url_item_code and url_item_code in seen_item_codes:
            skipped += 1
            skipped_details.append(f"第 {row_number} 行跳过：商品Code {url_item_code} 已在第 {seen_item_codes[url_item_code]} 行导入")
            continue

        duplicate = await find_duplicate_by_gigab2b_product_id(db, gigab2b_product_id)
        if not duplicate:
            duplicate = await find_duplicate_by_item_code(db, url_item_code)
        if duplicate:
            skipped += 1
            skipped_details.append(f"第 {row_number} 行跳过：{duplicate.message}")
            continue

        if remaining_upcs <= 0:
            raise HTTPException(400, f"UPC池子可用UPC不足：已可导入 {len(created_ids)} 行，后续第 {row_number} 行没有可用UPC")

        product = Product(
            gigab2b_url=gigab2b_url,
            gigab2b_product_id=gigab2b_product_id,
            competitor_asin=competitor_asin,
            brand=brand,
        )
        db.add(product)
        await db.flush()
        try:
            await ensure_product_upc(db, product)
        except UpcPoolEmptyError as exc:
            raise HTTPException(400, str(exc))
        remaining_upcs -= 1
        db.add(ProductData(product_id=product.id))
        db.add(ProductImage(product_id=product.id))
        db.add(ProductAplus(product_id=product.id))
        db.add(CatalogProduct(
            source_product_id=product.id,
            gigab2b_url=product.gigab2b_url,
            gigab2b_product_id=gigab2b_product_id,
            competitor_asin=product.competitor_asin,
            asin_sync_status=product.asin_sync_status or "not_synced",
            aplus_upload_status=product.aplus_upload_status or "not_uploaded",
            upc=product.upc,
            brand=product.brand,
            status=product.status,
        ))
        if gigab2b_product_id:
            seen_product_ids[gigab2b_product_id] = row_number
        if url_item_code:
            seen_item_codes[url_item_code] = row_number
        created_ids.append(product.id)

    await db.commit()
    return BulkImportResponse(
        created=len(created_ids),
        skipped=skipped,
        skipped_details=skipped_details,
        errors=errors,
        product_ids=created_ids,
    )


@router.get("/upc-pool", response_model=PaginatedUpcPoolItems)
async def list_upc_pool(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    status: str | None = None,
    q: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """UPC池子列表。已绑定记录只允许同一商品Code/来源商品ID重复确认。"""
    query = select(UpcPoolItem).order_by(UpcPoolItem.id.asc())
    count_query = select(func.count(UpcPoolItem.id))
    if status:
        query = query.where(UpcPoolItem.status == status)
        count_query = count_query.where(UpcPoolItem.status == status)
    if q:
        pattern = f"%{q.strip()}%"
        criteria = (
            (UpcPoolItem.upc.ilike(pattern))
            | (UpcPoolItem.bound_item_code.ilike(pattern))
            | (UpcPoolItem.bound_source_product_id.ilike(pattern))
        )
        query = query.where(criteria)
        count_query = count_query.where(criteria)

    total_result = await db.execute(count_query)
    result = await db.execute(query.offset((page - 1) * page_size).limit(page_size))
    return PaginatedUpcPoolItems(
        items=result.scalars().all(),
        total=total_result.scalar() or 0,
        page=page,
        page_size=page_size,
        summary=await _upc_pool_summary(db),
    )


@router.post("/upc-pool/import", response_model=UpcPoolImportResponse)
async def import_upc_pool(body: UpcPoolImportRequest, db: AsyncSession = Depends(get_db)):
    """批量追加 UPC 到池子，重复 UPC 会保留原记录。"""
    result = await add_upcs_to_pool(db, body.text)
    await db.commit()
    return UpcPoolImportResponse(
        added=result["added"],
        duplicated=result["duplicated"],
        invalid=result["invalid"],
        summary=await _upc_pool_summary(db),
    )


@router.post("/bulk-start", response_model=BulkStartResponse)
async def bulk_start_pipeline(body: BulkStartRequest, db: AsyncSession = Depends(get_db)):
    """批量启动待处理任务。只会启动 created 状态的任务，其余返回跳过原因。"""
    requested_ids = list(dict.fromkeys(body.product_ids))
    if len(requested_ids) > settings.BULK_START_MAX_TASKS:
        raise HTTPException(400, f"单次最多批量启动 {settings.BULK_START_MAX_TASKS} 个任务")
    result = await db.execute(select(Product).where(Product.id.in_(requested_ids)))
    products = {product.id: product for product in result.scalars().all()}

    errors: list[str] = []
    started_ids: list[int] = []
    for product_id in requested_ids:
        product = products.get(product_id)
        if not product:
            errors.append(f"任务 {product_id} 不存在")
            continue
        if product.status != "created":
            errors.append(f"任务 {product_id} 当前状态为 {product.status}，已跳过")
            continue
        if is_running(product.id):
            errors.append(f"任务 {product_id} 已在运行中，已跳过")
            continue
        _mark_pipeline_starting(product)
        started_ids.append(product.id)

    await db.commit()

    actually_started: list[int] = []
    for product_id in started_ids:
        if enqueue_pipeline(product_id):
            actually_started.append(product_id)
        else:
            errors.append(f"任务 {product_id} 后台队列已存在，已跳过")
            product = products.get(product_id)
            if product:
                product.status = "created"
                product.current_step = 0
                product.updated_at = datetime.now()

    if len(actually_started) != len(started_ids):
        await db.commit()

    return BulkStartResponse(
        requested=len(requested_ids),
        started=len(actually_started),
        skipped=len(requested_ids) - len(actually_started),
        errors=errors,
        started_ids=actually_started,
    )


@router.get("/catalog", response_model=PaginatedCatalogProducts)
async def list_catalog_products(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=1000),
    item_id: str | None = None,
    competitor_asin: str | None = None,
    amazon_asin: str | None = None,
    asin_sync_status: str | None = None,
    aplus_upload_status: str | None = None,
    stock_sync_status: str | None = None,
    template_risk_level: str | None = None,
    upc: str | None = None,
    category: str | None = None,
    imported_from: datetime | None = None,
    imported_to: datetime | None = None,
    stock_synced_from: datetime | None = None,
    stock_synced_to: datetime | None = None,
    db: AsyncSession = Depends(get_db),
):
    """独立商品资料列表，最多单页返回 1000 条。"""
    query = select(CatalogProduct).join(
        Product, CatalogProduct.source_product_id == Product.id
    ).outerjoin(
        ProductData, ProductData.product_id == Product.id
    ).options(
        selectinload(CatalogProduct.source_product).selectinload(Product.data)
    ).order_by(CatalogProduct.imported_at.desc())
    count_query = select(func.count(CatalogProduct.id)).join(
        Product, CatalogProduct.source_product_id == Product.id
    ).outerjoin(ProductData, ProductData.product_id == Product.id)

    query = query.where(CatalogProduct.confirmed_at.is_not(None))
    count_query = count_query.where(CatalogProduct.confirmed_at.is_not(None))

    if item_id:
        pattern = f"%{item_id.strip()}%"
        query = query.where((Product.gigab2b_product_id.ilike(pattern)) | (ProductData.item_code.ilike(pattern)))
        count_query = count_query.where((Product.gigab2b_product_id.ilike(pattern)) | (ProductData.item_code.ilike(pattern)))
    if competitor_asin:
        pattern = f"%{competitor_asin.strip()}%"
        query = query.where(Product.competitor_asin.ilike(pattern))
        count_query = count_query.where(Product.competitor_asin.ilike(pattern))
    if amazon_asin:
        pattern = f"%{amazon_asin.strip()}%"
        query = query.where((Product.amazon_asin.ilike(pattern)) | (CatalogProduct.amazon_asin.ilike(pattern)))
        count_query = count_query.where((Product.amazon_asin.ilike(pattern)) | (CatalogProduct.amazon_asin.ilike(pattern)))
    if asin_sync_status:
        if asin_sync_status == "synced":
            query = query.where(((Product.amazon_asin.is_not(None)) & (Product.amazon_asin != "")) | ((CatalogProduct.amazon_asin.is_not(None)) & (CatalogProduct.amazon_asin != "")))
            count_query = count_query.where(((Product.amazon_asin.is_not(None)) & (Product.amazon_asin != "")) | ((CatalogProduct.amazon_asin.is_not(None)) & (CatalogProduct.amazon_asin != "")))
        elif asin_sync_status == "not_synced":
            query = query.where(((Product.amazon_asin.is_(None)) | (Product.amazon_asin == "")) & ((CatalogProduct.amazon_asin.is_(None)) | (CatalogProduct.amazon_asin == "")))
            count_query = count_query.where(((Product.amazon_asin.is_(None)) | (Product.amazon_asin == "")) & ((CatalogProduct.amazon_asin.is_(None)) | (CatalogProduct.amazon_asin == "")))
        elif asin_sync_status == "manual_linked":
            query = query.where((Product.asin_sync_status == "manual_linked") | (CatalogProduct.asin_sync_status == "manual_linked"))
            count_query = count_query.where((Product.asin_sync_status == "manual_linked") | (CatalogProduct.asin_sync_status == "manual_linked"))
        else:
            query = query.where((Product.asin_sync_status == asin_sync_status) | (CatalogProduct.asin_sync_status == asin_sync_status))
            count_query = count_query.where((Product.asin_sync_status == asin_sync_status) | (CatalogProduct.asin_sync_status == asin_sync_status))
    if aplus_upload_status:
        query = query.where((Product.aplus_upload_status == aplus_upload_status) | (CatalogProduct.aplus_upload_status == aplus_upload_status))
        count_query = count_query.where((Product.aplus_upload_status == aplus_upload_status) | (CatalogProduct.aplus_upload_status == aplus_upload_status))
    if stock_sync_status:
        if stock_sync_status == "not_synced":
            query = query.where((CatalogProduct.stock_sync_status.is_(None)) | (CatalogProduct.stock_sync_status == "not_synced"))
            count_query = count_query.where((CatalogProduct.stock_sync_status.is_(None)) | (CatalogProduct.stock_sync_status == "not_synced"))
        else:
            query = query.where(CatalogProduct.stock_sync_status == stock_sync_status)
            count_query = count_query.where(CatalogProduct.stock_sync_status == stock_sync_status)
    if template_risk_level:
        pattern = f'%"risk_level"%{template_risk_level}%'
        query = query.where(ProductData.amazon_template_fill_summary.like(pattern))
        count_query = count_query.where(ProductData.amazon_template_fill_summary.like(pattern))
    if upc:
        pattern = f"%{upc.strip()}%"
        query = query.where((Product.upc.ilike(pattern)) | (CatalogProduct.upc.ilike(pattern)))
        count_query = count_query.where((Product.upc.ilike(pattern)) | (CatalogProduct.upc.ilike(pattern)))
    if category:
        pattern = f"%{category.strip()}%"
        query = query.where((ProductData.leaf_category.ilike(pattern)) | (CatalogProduct.leaf_category.ilike(pattern)))
        count_query = count_query.where((ProductData.leaf_category.ilike(pattern)) | (CatalogProduct.leaf_category.ilike(pattern)))
    imported_from = _naive_datetime(imported_from)
    imported_to = _naive_datetime(imported_to)
    if imported_from:
        query = query.where(CatalogProduct.imported_at >= imported_from)
        count_query = count_query.where(CatalogProduct.imported_at >= imported_from)
    if imported_to:
        query = query.where(CatalogProduct.imported_at <= imported_to)
        count_query = count_query.where(CatalogProduct.imported_at <= imported_to)
    stock_synced_from = _naive_datetime(stock_synced_from)
    stock_synced_to = _naive_datetime(stock_synced_to)
    if stock_synced_from:
        query = query.where(CatalogProduct.stock_synced_at >= stock_synced_from)
        count_query = count_query.where(CatalogProduct.stock_synced_at >= stock_synced_from)
    if stock_synced_to:
        query = query.where(CatalogProduct.stock_synced_at <= stock_synced_to)
        count_query = count_query.where(CatalogProduct.stock_synced_at <= stock_synced_to)

    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0
    result = await db.execute(query.offset((page - 1) * page_size).limit(page_size))
    items = result.scalars().all()
    for item in items:
        product = item.source_product
        if product:
            pd = product.data
            item.gigab2b_url = product.gigab2b_url
            item.gigab2b_product_id = product.gigab2b_product_id
            item.competitor_asin = product.competitor_asin
            item.amazon_asin = product.amazon_asin
            item.asin_sync_status = product.asin_sync_status
            item.asin_synced_at = product.asin_synced_at
            item.asin_sync_error = product.asin_sync_error
            item.aplus_upload_status = product.aplus_upload_status
            item.aplus_uploaded_at = product.aplus_uploaded_at
            item.aplus_upload_error = product.aplus_upload_error
            item.upc = product.upc
            item.brand = product.brand
            item.item_code = pd.item_code if pd else None
            item.title = pd.title if pd else None
            item.leaf_category = pd.leaf_category if pd else None
            item.status = product.status
            item.updated_at = datetime.now()
            risk, warning_count = _template_risk_from_data(pd)
            item.template_risk_level = risk
            item.template_warnings_count = warning_count
    await db.commit()
    return PaginatedCatalogProducts(items=items, total=total, page=page, page_size=page_size)


@router.post("/catalog/export")
async def export_catalog_products(ids: list[int], db: AsyncSession = Depends(get_db)):
    """按 Amazon 类目模板拆分导出可导入 Amazon 的 xlsm，同一类目多个商品写多行。"""
    if not ids:
        raise HTTPException(400, "请选择要导出的商品")
    if len(ids) > 300:
        raise HTTPException(400, "单次最多导出 300 个商品")

    catalog_result = await db.execute(select(CatalogProduct).where(CatalogProduct.id.in_(ids)))
    catalog_items = catalog_result.scalars().all()
    source_ids = [item.source_product_id for item in catalog_items]
    product_result = await db.execute(
        select(Product)
        .options(selectinload(Product.data), selectinload(Product.images), selectinload(Product.aplus))
        .where(Product.id.in_(source_ids))
    )
    products_by_id = {product.id: product for product in product_result.scalars().all()}
    catalog_by_source_id = {item.source_product_id: item for item in catalog_items}

    grouped: dict[tuple[str, str], dict] = {}
    report_rows: list[dict] = []
    for item in catalog_items:
        product = products_by_id.get(item.source_product_id)
        pd = product.data if product else None
        base_report = {
            "商品ID": product.id if product else item.source_product_id,
            "商品Code": pd.item_code if pd else item.item_code,
            "类目": (pd.leaf_category if pd else None) or item.leaf_category or "未分类",
        }
        if not product or not pd:
            report_rows.append({**base_report, "状态": "跳过", "原因": "商品资料不存在"})
            continue
        existing_asin = (product.amazon_asin or item.amazon_asin or "").strip()
        if existing_asin:
            report_rows.append({
                **base_report,
                "状态": "跳过",
                "模板文件": None,
                "导出文件": None,
                "原因": f"已有真实 ASIN {existing_asin}，不能再次导出 Amazon 导入表格",
            })
            continue
        try:
            mapping = _load_template_mapping(product, pd)
            template_path = Path(mapping["template_path"]).expanduser()
            if not template_path.is_file():
                raise FileNotFoundError(f"模板文件不存在: {template_path}")
            category = pd.leaf_category or mapping.get("category_type") or item.leaf_category or "未分类"
            key = (str(template_path), str(category))
            group = grouped.setdefault(key, {
                "template_path": template_path,
                "category": str(category),
                "mapping": mapping,
                "products": [],
            })
            group["products"].append(product)
        except Exception as exc:
            report_rows.append({
                **base_report,
                "状态": "跳过",
                "模板文件": None,
                "导出文件": None,
                "原因": f"{type(exc).__name__}: {exc}",
            })

    if not grouped:
        if report_rows and all("已有真实 ASIN" in str(row.get("原因") or "") for row in report_rows):
            raise HTTPException(400, "选中的商品都已有真实 ASIN，不能再次导出 Amazon 导入表格")
        raise HTTPException(400, "没有可导出的 Amazon 导入表格数据")

    zip_stream = BytesIO()
    with zipfile.ZipFile(zip_stream, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        for (_, category), group in grouped.items():
            products = group["products"]
            template_path: Path = group["template_path"]
            mapping = group["mapping"]
            safe_category = _safe_export_name(category)
            template_stem = _safe_export_name(template_path.stem, "amazon_template")
            for chunk_index in range(0, len(products), 500):
                chunk = products[chunk_index:chunk_index + 500]
                wb = load_workbook(template_path, keep_vba=True, data_only=False)
                if "Template" not in wb.sheetnames:
                    raise HTTPException(400, f"模板缺少 Template 工作表: {template_path}")
                ws = wb["Template"]
                _clear_template_data_rows(ws, len(chunk))
                part = chunk_index // 500 + 1
                export_name = f"{safe_category}_{template_stem}_{part}.xlsm"
                exported_in_workbook = 0

                for offset, product in enumerate(chunk):
                    pd = product.data
                    row_number = DATA_ROW + offset
                    report_base = {
                        "商品ID": product.id,
                        "商品Code": pd.item_code if pd else None,
                        "类目": category,
                        "模板文件": str(template_path),
                        "导出文件": export_name,
                    }
                    try:
                        if not pd:
                            raise ValueError("商品资料不存在")
                        catalog = catalog_by_source_id.get(product.id)
                        stock_override = _catalog_stock_export_override(ws, mapping, catalog)
                        source_path = _amazon_template_cache_path(pd)
                        template_result = None
                        if not source_path:
                            template_result = await run_amazon_template(product.id)
                            source_path = Path(template_result["path"]).expanduser()
                        _copy_import_data_row(source_path, ws, row_number)
                        if stock_override:
                            quantity_col, stock_quantity = stock_override
                            ws.cell(row_number, quantity_col).value = stock_quantity
                        exported_in_workbook += 1
                        report_rows.append({
                            **report_base,
                            "状态": "已导出",
                            "原因": ("使用已生成表格" if template_result is None else "现场重新生成表格")
                            + (f"，数量按运营库存 {stock_override[1]} 覆盖" if stock_override else ""),
                        })
                    except Exception as exc:
                        report_rows.append({
                            **report_base,
                            "状态": "跳过",
                            "原因": f"{type(exc).__name__}: {exc}",
                        })

                if exported_in_workbook:
                    workbook_stream = BytesIO()
                    wb.save(workbook_stream)
                    archive.writestr(export_name, workbook_stream.getvalue())

        archive.writestr("导出报告.xlsx", _summary_workbook(report_rows))

    if not any(row.get("状态") == "已导出" for row in report_rows):
        raise HTTPException(400, "选中的商品没有成功生成 Amazon 导入表格，请查看商品详情中的导入表格检查。")

    zip_stream.seek(0)
    filename = f"amazon_import_templates_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
    return StreamingResponse(
        zip_stream,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/catalog/inventory-template/export")
async def export_inventory_update_template(ids: list[int], db: AsyncSession = Depends(get_db)):
    """导出 Amazon Price & Quantity 库存同步模板。模板按 SKU 更新，仅导出已有真实 ASIN 的商品。"""
    selected_ids = list(dict.fromkeys(ids or []))
    if not selected_ids:
        raise HTTPException(400, "请选择要导出库存同步模板的商品")
    if len(selected_ids) > 5000:
        raise HTTPException(400, "单次最多导出 5000 个商品")

    template_path = Path(settings.PRICE_QUANTITY_TEMPLATE_PATH).expanduser()
    if not template_path.is_file():
        raise HTTPException(400, f"库存同步模板不存在: {template_path}")

    result = await db.execute(
        select(CatalogProduct)
        .options(selectinload(CatalogProduct.source_product).selectinload(Product.data))
        .where(CatalogProduct.id.in_(selected_ids))
    )
    catalog_by_id = {item.id: item for item in result.scalars().all()}

    report_rows: list[dict] = []
    export_items: list[CatalogProduct] = []
    for catalog_id in selected_ids:
        item = catalog_by_id.get(catalog_id)
        product = item.source_product if item else None
        product_data = product.data if product and product.data else None
        sku = _catalog_price_quantity_sku(item) if item else ""
        real_asin = ((item.amazon_asin if item else None) or (product.amazon_asin if product else None) or "").strip()
        base_report = {
            "商品资料ID": catalog_id,
            "任务ID": item.source_product_id if item else None,
            "商品Code": (item.item_code if item else None) or (product_data.item_code if product_data else None),
            "真实ASIN": real_asin or None,
            "SKU": sku or None,
            "库存": item.stock if item else None,
        }
        if not item:
            report_rows.append({**base_report, "状态": "跳过", "原因": "商品资料不存在"})
            continue
        if not item.confirmed_at:
            report_rows.append({**base_report, "状态": "跳过", "原因": "商品还未确认入库"})
            continue
        if not real_asin:
            report_rows.append({**base_report, "状态": "跳过", "原因": "缺少真实 ASIN，不能导出库存同步模板"})
            continue
        if not sku:
            report_rows.append({**base_report, "状态": "跳过", "原因": "缺少 SKU/商品Code，Amazon 库存模板无法定位商品"})
            continue
        if item.stock is None:
            report_rows.append({**base_report, "状态": "跳过", "原因": "缺少运营库存"})
            continue
        if item.stock < 0:
            report_rows.append({**base_report, "状态": "跳过", "原因": f"运营库存为 {item.stock}，不能导出负数库存"})
            continue
        export_items.append(item)

    if not export_items:
        raise HTTPException(400, "选中的商品没有可导出的库存同步模板数据；需要已有真实 ASIN、SKU 和运营库存。")

    wb = load_workbook(template_path, keep_vba=True, data_only=False)
    if "Template" not in wb.sheetnames:
        raise HTTPException(400, f"库存同步模板缺少 Template 工作表: {template_path}")
    ws = wb["Template"]
    columns = _template_attribute_columns(ws)
    required_columns = {
        PRICE_QUANTITY_SKU_ATTR: "SKU",
        PRICE_QUANTITY_FULFILLMENT_ATTR: "Fulfillment Channel Code",
        PRICE_QUANTITY_QUANTITY_ATTR: "Quantity",
    }
    missing = [label for attr, label in required_columns.items() if attr not in columns]
    if missing:
        raise HTTPException(400, f"库存同步模板缺少字段: {', '.join(missing)}")

    _clear_price_quantity_data_rows(ws, len(export_items))
    inventory_always_col = columns.get(PRICE_QUANTITY_INVENTORY_ALWAYS_AVAILABLE_ATTR)
    export_name = f"price_quantity_inventory_update_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsm"
    for offset, item in enumerate(export_items):
        row_number = PRICE_QUANTITY_DATA_ROW + offset
        sku = _catalog_price_quantity_sku(item)
        product = item.source_product
        real_asin = (item.amazon_asin or (product.amazon_asin if product else None) or "").strip()
        ws.cell(row_number, columns[PRICE_QUANTITY_SKU_ATTR]).value = sku
        ws.cell(row_number, columns[PRICE_QUANTITY_FULFILLMENT_ATTR]).value = PRICE_QUANTITY_FBM_VALUE
        ws.cell(row_number, columns[PRICE_QUANTITY_QUANTITY_ATTR]).value = int(item.stock or 0)
        if inventory_always_col:
            ws.cell(row_number, inventory_always_col).value = None
        report_rows.append({
            "状态": "已导出",
            "商品资料ID": item.id,
            "任务ID": item.source_product_id,
            "商品Code": item.item_code,
            "真实ASIN": real_asin,
            "SKU": sku,
            "库存": item.stock,
            "导出文件": export_name,
            "原因": "按 SKU 写入库存；价格列留空，不更新价格",
        })

    workbook_stream = BytesIO()
    wb.save(workbook_stream)
    zip_stream = BytesIO()
    with zipfile.ZipFile(zip_stream, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(export_name, workbook_stream.getvalue())
        archive.writestr("库存模板导出报告.xlsx", _inventory_update_report_workbook(report_rows))
    zip_stream.seek(0)
    filename = f"inventory_update_templates_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
    return StreamingResponse(
        zip_stream,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/catalog/inventory-sync", response_model=InventorySyncBatchResponse)
async def create_inventory_sync_batch(body: InventorySyncCreateRequest, db: AsyncSession = Depends(get_db)):
    """创建大建云仓库存同步批次。默认同步全部已确认商品资料。"""
    selected_ids = list(dict.fromkeys(body.catalog_product_ids or []))
    query = (
        select(CatalogProduct)
        .options(selectinload(CatalogProduct.source_product).selectinload(Product.data))
        .where(CatalogProduct.confirmed_at.is_not(None))
        .order_by(CatalogProduct.imported_at.desc())
    )
    if selected_ids:
        query = query.where(CatalogProduct.id.in_(selected_ids))
    result = await db.execute(query)
    catalog_items = result.scalars().all()
    if not catalog_items:
        raise HTTPException(400, "没有找到可同步库存的商品资料")

    if selected_ids:
        found_ids = {item.id for item in catalog_items}
        missing_ids = [item_id for item_id in selected_ids if item_id not in found_ids]
        if missing_ids:
            raise HTTPException(400, f"部分商品不存在或还未确认入库: {missing_ids[:10]}")

    try:
        await assert_gigab2b_logged_in_for_inventory(catalog_items)
    except InventorySyncLoginRequired as exc:
        raise HTTPException(400, str(exc)) from exc

    batch = InventorySyncBatch(
        status="pending",
        total_count=len(catalog_items),
        created_at=datetime.now(),
    )
    db.add(batch)
    await db.flush()
    for catalog in catalog_items:
        sync_item = build_inventory_sync_item(catalog)
        sync_item.batch_id = batch.id
        db.add(sync_item)
        catalog.stock_sync_status = "skipped" if sync_item.status == "skipped" else "pending"
        catalog.stock_sync_error = sync_item.error_message
        catalog.updated_at = datetime.now()
    await db.commit()
    await db.refresh(batch)

    start_inventory_sync_batch(batch.id)
    return batch


@router.get("/inventory-sync-batches", response_model=PaginatedInventorySyncBatches)
async def list_inventory_sync_batches(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    total_result = await db.execute(select(func.count(InventorySyncBatch.id)))
    total = total_result.scalar() or 0
    result = await db.execute(
        select(InventorySyncBatch)
        .order_by(InventorySyncBatch.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return PaginatedInventorySyncBatches(items=result.scalars().all(), total=total, page=page, page_size=page_size)


@router.get("/inventory-sync-batches/{batch_id}", response_model=InventorySyncBatchDetail)
async def get_inventory_sync_batch(batch_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(InventorySyncBatch)
        .options(selectinload(InventorySyncBatch.items))
        .where(InventorySyncBatch.id == batch_id)
    )
    batch = result.scalar_one_or_none()
    if not batch:
        raise HTTPException(404, "Inventory sync batch not found")
    return batch


@router.post("/catalog/{catalog_id}/asin", response_model=CatalogProductResponse)
async def update_catalog_asin(catalog_id: int, body: CatalogAsinUpdateRequest, db: AsyncSession = Depends(get_db)):
    """手动重新关联真实 ASIN，不创建领星同步任务。"""
    asin = body.amazon_asin.strip().upper()
    if not re.fullmatch(r"B0[A-Z0-9]{8}", asin):
        raise HTTPException(400, "ASIN 格式不正确，应为 B0 开头的 10 位编码")

    result = await db.execute(
        select(CatalogProduct)
        .options(selectinload(CatalogProduct.source_product).selectinload(Product.data))
        .where(CatalogProduct.id == catalog_id)
    )
    catalog = result.scalar_one_or_none()
    if not catalog:
        raise HTTPException(404, "商品资料不存在")

    catalog.amazon_asin = asin
    catalog.asin_sync_status = "manual_linked"
    catalog.asin_sync_error = None
    catalog.asin_synced_at = datetime.now()
    catalog.updated_at = datetime.now()

    product = catalog.source_product
    if product:
        product.amazon_asin = asin
        product.asin_sync_status = "manual_linked"
        product.asin_sync_error = None
        product.asin_synced_at = catalog.asin_synced_at
        product.updated_at = datetime.now()

    await db.commit()
    await db.refresh(catalog)
    return catalog


@router.delete("/catalog/{catalog_id}/asin", response_model=CatalogProductResponse)
async def clear_catalog_asin(catalog_id: int, db: AsyncSession = Depends(get_db)):
    """清除真实 ASIN，让商品回到可同步状态。"""
    result = await db.execute(
        select(CatalogProduct)
        .options(selectinload(CatalogProduct.source_product).selectinload(Product.data))
        .where(CatalogProduct.id == catalog_id)
    )
    catalog = result.scalar_one_or_none()
    if not catalog:
        raise HTTPException(404, "商品资料不存在")

    now = datetime.now()
    catalog.amazon_asin = None
    catalog.asin_sync_status = "not_synced"
    catalog.asin_sync_error = None
    catalog.asin_synced_at = now
    catalog.updated_at = now

    product = catalog.source_product
    if product:
        product.amazon_asin = None
        product.asin_sync_status = "not_synced"
        product.asin_sync_error = None
        product.asin_synced_at = now
        product.updated_at = now

    await db.commit()
    await db.refresh(catalog)
    return catalog


@router.post("/catalog/asin-sync", response_model=AsinSyncBatchResponse)
async def create_asin_sync_batch(body: AsinSyncCreateRequest, db: AsyncSession = Depends(get_db)):
    """为选中的商品资料创建 ASIN 同步批次，并在后台按 UPC/商品编码查询领星 Listing。"""
    result = await db.execute(
        select(CatalogProduct)
        .options(selectinload(CatalogProduct.source_product).selectinload(Product.data))
        .where(CatalogProduct.id.in_(body.catalog_product_ids))
    )
    catalog_items = result.scalars().all()
    if not catalog_items:
        raise HTTPException(400, "没有找到可同步的商品")
    unconfirmed = [item.id for item in catalog_items if item.confirmed_at is None]
    if unconfirmed:
        raise HTTPException(400, f"以下商品还未确认入库，不能同步 ASIN: {unconfirmed[:10]}")

    found_ids = {item.id for item in catalog_items}
    missing_ids = [item_id for item_id in body.catalog_product_ids if item_id not in found_ids]
    if missing_ids:
        raise HTTPException(400, f"部分商品不存在: {missing_ids[:10]}")

    batch = AsinSyncBatch(
        store=body.store or "Andy店-US",
        status="pending",
        total_count=len(catalog_items),
        created_at=datetime.now(),
    )
    db.add(batch)
    await db.flush()
    for catalog in catalog_items:
        sync_item = build_sync_item(catalog)
        sync_item.batch_id = batch.id
        db.add(sync_item)
        catalog.asin_sync_status = "pending" if sync_item.lookup_code else "skipped"
        catalog.asin_sync_error = sync_item.error_message
        product = catalog.source_product
        if product:
            product.asin_sync_status = catalog.asin_sync_status
            product.asin_sync_error = catalog.asin_sync_error
    await db.commit()
    await db.refresh(batch)

    start_asin_sync_batch(batch.id)
    return batch


@router.get("/asin-sync-batches", response_model=PaginatedAsinSyncBatches)
async def list_asin_sync_batches(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    total_result = await db.execute(select(func.count(AsinSyncBatch.id)))
    total = total_result.scalar() or 0
    result = await db.execute(
        select(AsinSyncBatch)
        .order_by(AsinSyncBatch.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return PaginatedAsinSyncBatches(items=result.scalars().all(), total=total, page=page, page_size=page_size)


@router.get("/asin-sync-batches/{batch_id}", response_model=AsinSyncBatchDetail)
async def get_asin_sync_batch(batch_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(AsinSyncBatch)
        .options(selectinload(AsinSyncBatch.items))
        .where(AsinSyncBatch.id == batch_id)
    )
    batch = result.scalar_one_or_none()
    if not batch:
        raise HTTPException(404, "ASIN sync batch not found")
    return batch


@router.post("/catalog/aplus-upload", response_model=AplusUploadBatchResponse)
async def create_aplus_upload_batch(body: AplusUploadCreateRequest, db: AsyncSession = Depends(get_db)):
    """为选中的商品资料创建领星 A+ 上传批次。默认自动提交审批。"""
    result = await db.execute(
        select(CatalogProduct)
        .options(selectinload(CatalogProduct.source_product).selectinload(Product.data))
        .where(CatalogProduct.id.in_(body.catalog_product_ids))
    )
    catalog_items = result.scalars().all()
    if not catalog_items:
        raise HTTPException(400, "没有找到可上传 A+ 的商品")
    unconfirmed = [item.id for item in catalog_items if item.confirmed_at is None]
    if unconfirmed:
        raise HTTPException(400, f"以下商品还未确认入库，不能上传 A+: {unconfirmed[:10]}")

    batch = AplusUploadBatch(
        store=body.store or "Andy店-US",
        submit_for_approval=1 if body.submit_for_approval else 0,
        status="pending",
        total_count=len(catalog_items),
        created_at=datetime.now(),
    )
    db.add(batch)
    await db.flush()
    for catalog in catalog_items:
        upload_item = build_upload_item(catalog)
        upload_item.batch_id = batch.id
        product = catalog.source_product
        if not upload_item.amazon_asin:
            upload_item.status = "skipped"
            upload_item.error_message = "缺少真实 ASIN，请先同步 ASIN"
            catalog.aplus_upload_status = "skipped"
            catalog.aplus_upload_error = upload_item.error_message
            catalog.aplus_uploaded_at = datetime.now()
            if product:
                product.aplus_upload_status = "skipped"
                product.aplus_upload_error = upload_item.error_message
                product.aplus_uploaded_at = datetime.now()
        else:
            catalog.aplus_upload_status = "pending"
            catalog.aplus_upload_error = None
            if product:
                product.aplus_upload_status = "pending"
                product.aplus_upload_error = None
        db.add(upload_item)
    await db.commit()
    await db.refresh(batch)
    start_aplus_upload_batch(batch.id)
    return batch


@router.get("/aplus-upload-batches", response_model=PaginatedAplusUploadBatches)
async def list_aplus_upload_batches(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    total_result = await db.execute(select(func.count(AplusUploadBatch.id)))
    total = total_result.scalar() or 0
    result = await db.execute(
        select(AplusUploadBatch)
        .order_by(AplusUploadBatch.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return PaginatedAplusUploadBatches(items=result.scalars().all(), total=total, page=page, page_size=page_size)


@router.get("/aplus-upload-batches/{batch_id}", response_model=AplusUploadBatchDetail)
async def get_aplus_upload_batch(batch_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(AplusUploadBatch)
        .options(selectinload(AplusUploadBatch.items))
        .where(AplusUploadBatch.id == batch_id)
    )
    batch = result.scalar_one_or_none()
    if not batch:
        raise HTTPException(404, "A+ upload batch not found")
    return batch


@router.post("/{product_id}/confirm", response_model=ProductResponse)
async def confirm_product(product_id: int, db: AsyncSession = Depends(get_db)):
    """人工确认商品生成结果，并同步进入商品列表。"""
    result = await db.execute(
        select(Product)
        .options(selectinload(Product.data), selectinload(Product.catalog_item))
        .where(Product.id == product_id)
    )
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(404, "Product not found")
    if is_running(product.id):
        raise HTTPException(400, "任务还在运行中，完成后再确认")
    if product.status not in {PENDING_REVIEW, COMPLETED}:
        raise HTTPException(400, "只有生成完成、待人工确认的商品可以确认入库")
    if product.current_step < 10:
        raise HTTPException(400, "导入表格还没有生成完成")

    product.status = COMPLETED
    product.current_step = 10
    product.error_message = None
    product.updated_at = datetime.now()
    _sync_catalog_item(product, db, confirm=True)
    await db.commit()
    await db.refresh(product)
    return product


@router.get("/{product_id}", response_model=ProductDetail)
async def get_product(product_id: int, db: AsyncSession = Depends(get_db)):
    """商品详情（含子表数据）"""
    result = await db.execute(
        select(Product)
        .options(selectinload(Product.data), selectinload(Product.images), selectinload(Product.aplus), selectinload(Product.files))
        .where(Product.id == product_id)
    )
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(404, "Product not found")

    detail = ProductDetail.model_validate(product)
    detail.current_task_status = _current_task_status(product)
    detail.amazon_export_preview = _build_amazon_export_preview(product)
    if product.data and product.data.material_dir:
        material_dir = Path(product.data.material_dir).expanduser()
        if material_dir.is_dir():
            video_dir = organize_video_files(material_dir)
            detail.zip_files = _scan_zip_files(material_dir)
            if detail.data:
                detail.data.image_count = _count_material_images(material_dir)
            detail.video_folder = folder_summary(video_dir, VIDEO_EXTENSIONS) if video_dir else None
            detail.aplus_folder = aplus_folder_summary(aplus_image_folder(material_dir))
    detail.generated_files = sorted(product.files or [], key=lambda item: item.created_at or datetime.min, reverse=True)
    return detail


@router.post("/{product_id}/files/open")
async def open_product_file(
    product_id: int,
    path: str | None = None,
    directory: bool = False,
    db: AsyncSession = Depends(get_db),
):
    """在 Finder 中打开素材目录或指定文件/文件夹"""
    result = await db.execute(
        select(Product)
        .options(selectinload(Product.data))
        .where(Product.id == product_id)
    )
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(404, "Product not found")

    material_dir = _safe_material_dir(product)
    target = Path(path).expanduser().resolve() if path else material_dir
    if not _is_in_dir(target, material_dir):
        raise HTTPException(403, "只能打开当前商品素材目录内的文件")
    if not target.exists():
        raise HTTPException(404, f"文件不存在: {target}")
    if directory and target.is_file():
        target = target.parent

    subprocess.Popen(["open", str(target)])
    return {"status": "ok", "path": str(target)}


@router.post("/{product_id}/files/extract")
async def extract_product_zip(
    product_id: int,
    path: str,
    db: AsyncSession = Depends(get_db),
):
    """解压素材目录内的 zip 文件"""
    result = await db.execute(
        select(Product)
        .options(selectinload(Product.data))
        .where(Product.id == product_id)
    )
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(404, "Product not found")

    material_dir = _safe_material_dir(product)
    zip_path = Path(path).expanduser().resolve()
    if not _is_in_dir(zip_path, material_dir):
        raise HTTPException(403, "只能解压当前商品素材目录内的压缩包")
    if not zip_path.is_file() or zip_path.suffix.lower() not in ZIP_EXTENSIONS:
        raise HTTPException(400, "请选择 zip 压缩包")

    output_dir = zip_path.with_suffix("")
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        with zipfile.ZipFile(zip_path) as archive:
            for member in archive.infolist():
                member_path = (output_dir / member.filename).resolve()
                if not _is_in_dir(member_path, output_dir):
                    raise HTTPException(400, "压缩包包含不安全路径")
            archive.extractall(output_dir)
    except zipfile.BadZipFile:
        raise HTTPException(400, "压缩包无法读取")

    return {
        "status": "ok",
        "extracted_dir": str(output_dir),
        "files": _summarize_extracted_files(output_dir),
    }


@router.patch("/{product_id}", response_model=ProductResponse)
async def update_product(
    product_id: int,
    body: ProductUpdate,
    db: AsyncSession = Depends(get_db),
):
    """更新商品任务"""
    result = await db.execute(
        select(Product)
        .options(selectinload(Product.data), selectinload(Product.catalog_item))
        .where(Product.id == product_id)
    )
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(404, "Product not found")

    update_data = body.model_dump(exclude_unset=True)
    if "upc" in update_data:
        requested_upc = str(update_data.pop("upc") or "").strip() or None
        current_upc = str(product.upc or "").strip() or None
        if requested_upc != current_upc:
            raise HTTPException(400, "UPC由UPC池子绑定后不可手动修改")
    categories_value = update_data.pop("categories", None)
    leaf_category_value = update_data.pop("leaf_category", None)
    product_data_updates = {
        key: update_data.pop(key)
        for key in list(update_data.keys())
        if key in {
            "listing_title",
            "listing_bullets",
            "listing_search_terms",
            "listing_title_zh",
            "listing_bullets_zh",
            "listing_search_terms_zh",
            "listing_primary_keyword",
        }
    }
    for key, value in update_data.items():
        setattr(product, key, value)
    if categories_value is not None or leaf_category_value is not None or product_data_updates:
        if not product.data:
            product.data = ProductData(product_id=product.id)
            db.add(product.data)
        if categories_value is not None:
            if isinstance(categories_value, list):
                categories = [str(item).strip() for item in categories_value if str(item).strip()]
            else:
                categories = [
                    part.strip()
                    for part in re.split(r"\s*>\s*|\s*›\s*", str(categories_value))
                    if part.strip()
                ]
            category_key = _category_option_key(categories, leaf_category_value or (categories[-1] if categories else None))
            if category_key and category_key not in await _allowed_category_keys(db):
                raise HTTPException(400, "Amazon 类目只能从已有类目列表中选择")
            product.data.categories = json.dumps(categories, ensure_ascii=False) if categories else None
            if categories and leaf_category_value is None:
                product.data.leaf_category = categories[-1]
        if leaf_category_value is not None:
            product.data.leaf_category = leaf_category_value.strip() or None
        for key, value in product_data_updates.items():
            if key in {"listing_bullets", "listing_bullets_zh"}:
                if isinstance(value, list):
                    normalized = [" ".join(str(item).split()).strip() for item in value if str(item).strip()]
                else:
                    normalized = [" ".join(line.split()).strip() for line in str(value or "").splitlines() if line.strip()]
                setattr(product.data, key, json.dumps(normalized, ensure_ascii=False))
            else:
                setattr(product.data, key, str(value).strip() if value is not None else None)
    product.updated_at = datetime.now()
    _sync_catalog_item(product, db)
    await db.commit()
    await db.refresh(product)
    return product


@router.delete("/{product_id}", status_code=204)
async def delete_product(product_id: int, db: AsyncSession = Depends(get_db)):
    """删除商品任务"""
    result = await db.execute(select(Product).options(selectinload(Product.catalog_item)).where(Product.id == product_id))
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(404, "Product not found")
    cancel_pipeline(product_id)
    catalog_id = product.catalog_item.id if product.catalog_item else None
    await db.execute(delete(AplusRegenerateTask).where(AplusRegenerateTask.product_id == product_id))
    await db.execute(delete(AsinSyncItem).where(AsinSyncItem.product_id == product_id))
    await db.execute(delete(AplusUploadItem).where(AplusUploadItem.product_id == product_id))
    await db.execute(delete(InventorySyncItem).where(InventorySyncItem.product_id == product_id))
    if catalog_id is not None:
        await db.execute(delete(AsinSyncItem).where(AsinSyncItem.catalog_product_id == catalog_id))
        await db.execute(delete(AplusUploadItem).where(AplusUploadItem.catalog_product_id == catalog_id))
        await db.execute(delete(InventorySyncItem).where(InventorySyncItem.catalog_product_id == catalog_id))
    await db.delete(product)
    await db.commit()


@router.post("/{product_id}/start", response_model=ProductResponse)
async def start_pipeline(product_id: int, db: AsyncSession = Depends(get_db)):
    """启动Pipeline（触发Step1）"""
    result = await db.execute(select(Product).where(Product.id == product_id))
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(404, "Product not found")
    if product.status != "created":
        raise HTTPException(400, f"Cannot start: current status is {product.status}")

    _mark_pipeline_starting(product)
    await db.commit()
    await db.refresh(product)
    
    # 触发Pipeline引擎
    enqueue_pipeline(product.id)
    return product


@router.post("/{product_id}/restart", response_model=ProductResponse)
async def restart_pipeline(product_id: int, db: AsyncSession = Depends(get_db)):
    """删除旧素材和结果，从 Step1 重新开始 Pipeline"""
    result = await db.execute(
        select(Product)
        .options(
            selectinload(Product.data),
            selectinload(Product.images),
            selectinload(Product.aplus),
            selectinload(Product.files),
            selectinload(Product.catalog_item),
        )
        .where(Product.id == product_id)
    )
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(404, "Product not found")
    if is_running(product.id):
        raise HTTPException(400, "任务正在运行中，请先暂停后再重新开始")
    try:
        await ensure_product_upc(db, product)
    except UpcPoolEmptyError as exc:
        raise HTTPException(400, str(exc))

    _delete_material_dir(product.data.material_dir if product.data else None)

    if product.data:
        _reset_product_data(product.data)
    else:
        db.add(ProductData(product_id=product.id))

    if product.images:
        _reset_product_images(product.images)
    else:
        db.add(ProductImage(product_id=product.id))

    if product.aplus:
        _reset_product_aplus(product.aplus)
    else:
        db.add(ProductAplus(product_id=product.id))

    for file_record in list(product.files or []):
        await db.delete(file_record)

    product.gigab2b_product_id = None
    product.aplus_upload_status = "not_uploaded"
    product.aplus_uploaded_at = None
    product.aplus_upload_error = None
    product.status = "step1_collecting"
    product.current_step = 1
    product.error_message = None
    product.updated_at = datetime.now()
    if product.catalog_item:
        product.catalog_item.confirmed_at = None
        product.catalog_item.upc = product.upc
        product.catalog_item.aplus_upload_status = product.aplus_upload_status
        product.catalog_item.aplus_uploaded_at = None
        product.catalog_item.aplus_upload_error = None
        product.catalog_item.status = product.status
        product.catalog_item.updated_at = datetime.now()
    await db.commit()
    await db.refresh(product)

    enqueue_pipeline(product.id)
    return product


@router.post("/{product_id}/retry", response_model=ProductResponse)
async def retry_step(product_id: int, db: AsyncSession = Depends(get_db)):
    """重试当前失败的步骤"""
    result = await db.execute(select(Product).where(Product.id == product_id))
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(404, "Product not found")
    if product.status != "failed":
        raise HTTPException(400, "Can only retry failed tasks")

    step = product.current_step
    product.status = STEP_STATUS_MAP.get(step, "created")
    product.error_message = None
    product.updated_at = datetime.now()
    await db.commit()
    await db.refresh(product)
    
    # 重新触发Pipeline引擎
    enqueue_pipeline(product.id, start_step=step)
    return product


@router.post("/{product_id}/resume", response_model=ProductResponse)
async def resume_pipeline(product_id: int, db: AsyncSession = Depends(get_db)):
    """从暂停时记录的当前步骤继续 Pipeline。"""
    result = await db.execute(select(Product).where(Product.id == product_id))
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(404, "Product not found")
    if product.status not in {"paused", PENDING_REVIEW}:
        raise HTTPException(400, f"只能继续已暂停或待人工处理的任务，当前状态: {product.status}")
    if is_running(product.id):
        raise HTTPException(400, "任务已经在运行中")

    step = product.current_step or 1
    if step < 1:
        step = 1
    if step > 10:
        raise HTTPException(400, f"当前步骤无效，无法继续: {step}")
    if product.status == PENDING_REVIEW and step >= 10:
        raise HTTPException(400, "当前任务已生成完成，请确认入库或重新开始")

    product.status = STEP_STATUS_MAP.get(step, "created")
    product.error_message = None
    product.updated_at = datetime.now()
    await db.commit()
    await db.refresh(product)

    enqueue_pipeline(product.id, start_step=step)
    return product


@router.post("/{product_id}/step/{step}")
async def run_single_step(product_id: int, step: int, db: AsyncSession = Depends(get_db)):
    """单独执行某个步骤（调试/重试用）"""
    if step not in STEP_RUNNERS:
        raise HTTPException(400, f"Invalid step: {step}. Must be 1-10.")

    result = await db.execute(select(Product).where(Product.id == product_id))
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(404, "Product not found")

    try:
        runner = STEP_RUNNERS[step]
        data = await runner(product_id)
        return {"status": "ok", "step": step, "data": data}
    except Exception as e:
        raise HTTPException(500, f"Step {step} failed: {e}")


@router.post("/{product_id}/aplus/regenerate")
async def regenerate_aplus_module(product_id: int, body: AplusRegenerateRequest, db: AsyncSession = Depends(get_db)):
    """提交单个 A+ 模块重新生成任务，写入数据库队列后后台执行。"""
    result = await db.execute(
        select(Product)
        .options(selectinload(Product.aplus))
        .where(Product.id == product_id)
    )
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(404, "Product not found")
    if not product.aplus or not product.aplus.aplus_plan or not product.aplus.aplus_scripts:
        raise HTTPException(400, "未找到A+规划/脚本，请先执行Step7/Step8")
    try:
        scripts_data = json.loads(product.aplus.aplus_scripts)
    except json.JSONDecodeError:
        raise HTTPException(400, "A+脚本数据损坏")
    scripts = scripts_data.get("scripts") if isinstance(scripts_data, dict) else None
    if not isinstance(scripts, list) or not any(item.get("module_position") == body.module_position for item in scripts if isinstance(item, dict)):
        raise HTTPException(400, f"未找到模块 {body.module_position} 的A+脚本")

    task = await create_regenerate_task(product_id, body.module_position, body.reason.strip())
    return {
        "status": task.status,
        "message": "已提交后台重新生成" if task.status == "queued" else "该模块正在后台重新生成",
        "module_position": body.module_position,
        "task_id": task.id,
    }


@router.post("/{product_id}/aplus/regenerate/retry")
async def retry_aplus_regenerate_tasks(product_id: int, db: AsyncSession = Depends(get_db)):
    """重试该商品最新一批失败/中断的 A+ 重新生图任务。"""
    result = await db.execute(
        select(Product)
        .options(selectinload(Product.aplus))
        .where(Product.id == product_id)
    )
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(404, "Product not found")
    if not product.aplus or not product.aplus.aplus_scripts:
        raise HTTPException(400, "未找到A+脚本，不能重试重新生图")

    tasks = await retry_latest_regenerate_tasks(product_id)
    if not tasks:
        raise HTTPException(400, "没有找到可重试的 A+ 重新生图任务，请在对应模块手动重新生成")
    return {
        "status": "queued",
        "message": f"已重新排队 {len(tasks)} 个 A+ 重新生图任务",
        "task_ids": [task.id for task in tasks],
        "module_positions": [task.module_position for task in tasks],
    }


@router.post("/{product_id}/pause", response_model=ProductResponse)
async def pause_pipeline(product_id: int, db: AsyncSession = Depends(get_db)):
    """暂停Pipeline"""
    result = await db.execute(select(Product).where(Product.id == product_id))
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(404, "Product not found")
    product.status = "paused"
    product.updated_at = datetime.now()
    await db.commit()
    await db.refresh(product)
    
    # 取消后台任务
    cancel_pipeline(product.id)
    return product
