"""
模块1：商品采集 — 从大健云仓(GigaB2B)采集商品数据
通过 Chrome + AppleScript 控制浏览器，执行 JS 提取商品信息
"""

import json
import re
import logging
import asyncio
import zipfile
import glob
import shutil
import time
import html
import httpx
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from app.config import settings
from app.database import async_session
from app.models import Product, ProductData
from app.pipeline.chrome_ctrl import (
    chrome_navigate,
    chrome_execute_js,
    chrome_get_page_info,
    chrome_get_cookie_for_domain,
    chrome_workflow,
)
from app.services.material_assets import organize_video_files
from app.services.product_duplicates import (
    extract_gigab2b_product_id,
    find_duplicate_by_gigab2b_product_id,
    find_duplicate_by_item_code,
)

logger = logging.getLogger(__name__)

RAW_ASSETS_DIR = "原始素材"
RAW_EXTRACTED_DIR = "解压文件"
DOWNLOADS_DIR = Path.home() / "Downloads"
MATERIAL_FILE_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff",
    ".mp4", ".mov", ".avi", ".m4v", ".zip",
}

DOWNLOAD_TYPE_DIRS = {
    "information": "Information",
    "retail_ready": "Retail_Ready",
    "to_b": "To_B",
    "unknown": "Unknown",
}

GIGAB2B_BASE_URL = "https://www.gigab2b.com"
GIGAB2B_API_TIMEOUT = httpx.Timeout(connect=20, read=180, write=30, pool=20)
GIGAB2B_RESOURCE_TYPES = {
    "To B素材包": 1,
    "Retail Ready素材包": 2,
}


class Step1NeedsReview(RuntimeError):
    """Step1 已采集到核心资料，但需要人工补充后再继续。"""

    def __init__(self, reasons: list[str]):
        self.reasons = [reason for reason in reasons if reason]
        super().__init__("；".join(self.reasons))


class Step1ProductUnavailable(RuntimeError):
    """商品已下架或无库存，不应继续 Pipeline。"""


class Step1DuplicateSkipped(RuntimeError):
    """商品已存在，普通导入任务应跳过后续 Pipeline。"""


def _safe_extract_zip(zip_path: Path, output_dir: Path) -> int:
    extracted = 0
    output_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as archive:
        for member in archive.infolist():
            target = (output_dir / member.filename).resolve()
            try:
                target.relative_to(output_dir.resolve())
            except ValueError:
                raise RuntimeError(f"压缩包包含不安全路径: {member.filename}")
        archive.extractall(output_dir)
        extracted = len([m for m in archive.infolist() if not m.is_dir()])
    return extracted


def _existing_download_zips() -> set[Path]:
    return {Path(p).resolve() for p in glob.glob(str(DOWNLOADS_DIR / "*.zip"))}


def _active_chrome_downloads() -> list[Path]:
    return [Path(p) for p in glob.glob(str(DOWNLOADS_DIR / "*.crdownload"))]


def _match_download_type(zip_path: Path) -> str:
    name = zip_path.name.lower()
    if "retail_ready" in name or "retail ready" in name:
        return "retail_ready"
    if "information" in name:
        return "information"
    if "image+file" in name or "image_file" in name:
        return "to_b"
    return "unknown"


def _new_download_zips(existing: set[Path], item_code: str | None, since_ts: float) -> list[Path]:
    zips = [
        path for path in (_existing_download_zips() - existing)
        if path.exists() and path.stat().st_mtime >= since_ts - 2
    ]
    if item_code:
        matched = [path for path in zips if item_code.lower() in path.name.lower()]
        if matched:
            return sorted(matched)
        if len(zips) > 1:
            raise RuntimeError(
                "检测到多个新 ZIP，但文件名均未包含当前货号，无法安全判断属于哪个商品: "
                f"{', '.join(path.name for path in sorted(zips)[:5])}"
            )
    return sorted(zips)


async def _wait_for_browser_zips(existing: set[Path], item_code: str | None, since_ts: float) -> list[Path]:
    """等待 Chrome 下载目录中新 zip 全部完成。"""
    started_at = time.monotonic()
    last_log = 0.0
    timeout = settings.STEP1_DOWNLOAD_TIMEOUT_SECONDS

    while time.monotonic() - started_at < timeout:
        active = _active_chrome_downloads()
        new_zips = _new_download_zips(existing, item_code, since_ts)
        elapsed = int(time.monotonic() - started_at)

        if time.monotonic() - last_log >= 10:
            if active:
                logger.info(f"[Step1] 等待大健云仓素材下载中: {elapsed}s, 未完成文件={len(active)}")
            elif not new_zips:
                logger.info(f"[Step1] 等待大健云仓开始下载: {elapsed}s")
            last_log = time.monotonic()

        if new_zips and not active:
            await asyncio.sleep(3)
            if not _active_chrome_downloads():
                return _new_download_zips(existing, item_code, since_ts)

        await asyncio.sleep(2)

    active = _active_chrome_downloads()
    new_zips = _new_download_zips(existing, item_code, since_ts)
    if active:
        raise RuntimeError(
            f"大健云仓素材下载超时且仍有未完成文件: {', '.join(p.name for p in active[:5])}"
        )
    if new_zips:
        return new_zips
    raise RuntimeError("大健云仓素材下载超时，未发现新的 ZIP 文件，请确认已登录且浏览器允许下载")


async def _click_download_button() -> bool:
    js = r'''(function() {
    var buttons = Array.from(document.querySelectorAll('button'));
    var candidates = buttons.filter(function(btn) {
        var text = (btn.innerText || btn.textContent || '').trim();
        var rect = btn.getBoundingClientRect();
        return text.includes('下载素材包') && rect.width > 0 && rect.height > 0;
    });
    var btn = candidates[candidates.length - 1];
    if (!btn) return 'false';
    btn.click();
    return 'true';
})()'''
    return await chrome_execute_js(js, timeout=15) == "true"


async def _get_download_options() -> list[str]:
    js = r'''(function() {
    var options = [];
    var popovers = Array.from(document.querySelectorAll('.resource-type-class'));
    var popover = popovers.find(function(el) {
        return el.offsetHeight > 0 && el.offsetWidth > 0;
    });
    if (!popover) return JSON.stringify(options);
    popover.querySelectorAll('div.cursor-pointer').forEach(function(item) {
        var text = (item.innerText || item.textContent || '').trim();
        if (text) options.push(text);
    });
    return JSON.stringify(options);
})()'''
    result = await chrome_execute_js(js, timeout=15)
    if not result:
        return []
    try:
        options = json.loads(result)
    except json.JSONDecodeError:
        return []
    allowed = {"To B素材包", "Retail Ready素材包", "Information"}
    return [text for text in options if text in allowed]


def _download_option_priority() -> list[str]:
    priority = [text.strip() for text in settings.STEP1_MATERIAL_PACKAGE_PRIORITY.split(",") if text.strip()]
    return priority or ["To B素材包", "Retail Ready素材包", "Information"]


def _select_download_option(options: list[str]) -> str:
    priority = _download_option_priority()
    for preferred in priority:
        if preferred in options:
            return preferred
    return options[0]


async def _click_download_option(option_text: str) -> bool:
    js = r'''(function() {
    var targetText = __TARGET_TEXT__;
    var popovers = Array.from(document.querySelectorAll('.resource-type-class'));
    var popover = popovers.find(function(el) {
        return el.offsetHeight > 0 && el.offsetWidth > 0;
    }) || popovers[popovers.length - 1];
    if (!popover) return 'false';
    var items = Array.from(popover.querySelectorAll('div.cursor-pointer'));
    var item = items.find(function(el) {
        return (el.innerText || el.textContent || '').trim() === targetText;
    });
    if (!item) return 'false';
    item.click();
    return 'true';
})()'''.replace("__TARGET_TEXT__", json.dumps(option_text, ensure_ascii=False))
    return await chrome_execute_js(js, timeout=15) == "true"


def _store_and_extract_zips(zip_paths: list[Path], save_dir: Path) -> list[dict]:
    save_dir.mkdir(parents=True, exist_ok=True)
    extracted_root = save_dir / RAW_EXTRACTED_DIR
    results = []

    for zip_path in zip_paths:
        zip_path = zip_path.resolve()
        type_key = _match_download_type(zip_path)
        type_dir = DOWNLOAD_TYPE_DIRS.get(type_key, DOWNLOAD_TYPE_DIRS["unknown"])
        target_zip = save_dir / zip_path.name
        if target_zip.exists():
            stem, suffix = target_zip.stem, target_zip.suffix
            index = 1
            while target_zip.exists():
                target_zip = save_dir / f"{stem}_{index}{suffix}"
                index += 1

        shutil.move(str(zip_path), str(target_zip))
        output_dir = extracted_root / type_dir / target_zip.stem
        extracted_count = _safe_extract_zip(target_zip, output_dir)
        results.append({
            "path": str(target_zip),
            "type": type_key,
            "size": target_zip.stat().st_size,
            "extracted_count": extracted_count,
            "extracted_dir": str(output_dir),
        })
        logger.info(
            f"[Step1] 素材 ZIP 已保存并解压: {target_zip.name}, type={type_key}, "
            f"files={extracted_count}, dir={output_dir}"
        )

    return results


def _unique_target_path(directory: Path, filename: str) -> Path:
    safe_name = Path(filename).name.strip() or "gigab2b_material.zip"
    if not safe_name.lower().endswith(".zip"):
        safe_name = f"{safe_name}.zip"
    target = directory / safe_name
    if not target.exists():
        return target
    stem, suffix = target.stem, target.suffix
    index = 1
    while target.exists():
        target = directory / f"{stem}_{index}{suffix}"
        index += 1
    return target


def _filename_from_content_disposition(value: str | None, fallback: str) -> str:
    if value:
        match = re.search(r"filename\*=UTF-8''([^;]+)", value, re.I)
        if match:
            return unquote(match.group(1).strip().strip('"'))
        match = re.search(r'filename="?([^";]+)"?', value, re.I)
        if match:
            return unquote(match.group(1).strip())
    return fallback


def _store_and_extract_api_zip(zip_path: Path, type_key: str, save_dir: Path) -> dict:
    extracted_root = save_dir / RAW_EXTRACTED_DIR
    type_dir = DOWNLOAD_TYPE_DIRS.get(type_key, DOWNLOAD_TYPE_DIRS["unknown"])
    output_dir = extracted_root / type_dir / zip_path.stem
    extracted_count = _safe_extract_zip(zip_path, output_dir)
    result = {
        "path": str(zip_path),
        "type": type_key,
        "size": zip_path.stat().st_size,
        "extracted_count": extracted_count,
        "extracted_dir": str(output_dir),
    }
    logger.info(
        f"[Step1] API 素材 ZIP 已保存并解压: {zip_path.name}, type={type_key}, "
        f"files={extracted_count}, dir={output_dir}"
    )
    return result


def _html_to_text(value: str | None) -> str | None:
    if not value:
        return None
    text = re.sub(r"</(?:li|p|div|br)\s*>", "\n", str(value), flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    lines = [html.unescape(line).strip() for line in text.splitlines()]
    lines = [line for line in lines if line]
    return "\n".join(lines) or None


def _html_list_items(value: str | None) -> list[str]:
    if not value:
        return []
    items = re.findall(r"<li\b[^>]*>(.*?)</li>", str(value), flags=re.I | re.S)
    cleaned = [_html_to_text(item) for item in items]
    return [item for item in cleaned if item]


def _money_number(value) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if value is None:
        return None
    match = re.search(r"[0-9]+(?:\.[0-9]+)?", str(value).replace(",", ""))
    return float(match.group(0)) if match else None


def _text_value(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, dict):
        for key in ("name", "title", "label", "value", "text", "show", "value_name"):
            if value.get(key) not in (None, ""):
                return str(value[key])
        return None
    text = str(value).strip()
    return text or None


def _property_lookup(specification: dict) -> dict[str, str]:
    props = {}
    for item in specification.get("property_infos") or []:
        if not isinstance(item, dict):
            continue
        name = item.get("property_name") or item.get("name")
        value = item.get("property_value_name") or item.get("value")
        if name and value not in (None, ""):
            props[str(name)] = str(value)
    return props


def _property_any(props: dict[str, str], names: tuple[str, ...]) -> str | None:
    for name in names:
        if props.get(name):
            return props[name]
    return None


def _image_urls_from_api(product_info: dict) -> list[str]:
    urls = []
    for key in ("main_image",):
        value = product_info.get(key)
        if isinstance(value, dict):
            for field in ("popup", "thumb", "url", "src"):
                if value.get(field):
                    urls.append(str(value[field]))
    image_list = product_info.get("image_list") or []
    if isinstance(image_list, dict):
        image_list = list(image_list.values())
    for item in image_list:
        if isinstance(item, dict):
            for field in ("popup", "thumb", "url", "src"):
                if item.get(field):
                    urls.append(str(item[field]))
                    break
        elif item:
            urls.append(str(item))
    return list(dict.fromkeys(urls))


def _package_entries_from_api(specification: dict) -> list[dict]:
    package_size = specification.get("package_size") or {}
    raw_unit_length = str(package_size.get("simple_unit_length") or package_size.get("unit_length") or "in.")
    raw_unit_weight = str(package_size.get("simple_unit_weight") or package_size.get("unit_weight") or "lbs.")
    unit_length = "in." if "英寸" in raw_unit_length or raw_unit_length.lower().startswith("in") else raw_unit_length
    unit_weight = "lbs." if "磅" in raw_unit_weight or raw_unit_weight.lower().startswith("lb") else raw_unit_weight

    def build_entry(item: dict, fallback_code: str | None = None) -> dict | None:
        length = _parse_dimension_float(item.get("length") or item.get("length_show"))
        width = _parse_dimension_float(item.get("width") or item.get("width_show"))
        height = _parse_dimension_float(item.get("height") or item.get("height_show"))
        weight = _parse_dimension_float(item.get("weight") or item.get("weight_show"))
        if not (length and width and height and weight):
            return None
        code = item.get("sku") or item.get("sub_sku") or item.get("code") or fallback_code or ""
        qty = _parse_int(item.get("qty") or item.get("quantity") or item.get("package_quantity")) or 1
        dimensions = f"{length:g} * {width:g} * {height:g} {unit_length} {weight:g} {unit_weight}"
        return {
            "code": str(code),
            "qty": str(qty),
            "length": length,
            "width": width,
            "height": height,
            "weight_value": weight,
            "length_unit": unit_length,
            "weight_unit": unit_weight,
            "dimensions": dimensions,
            "weight": f"{weight:g} {unit_weight}",
        }

    entries = []
    general = package_size.get("general")
    if isinstance(general, dict):
        entry = build_entry(general, specification.get("sku"))
        if entry:
            entries.append(entry)
    for item in package_size.get("combo") or []:
        if isinstance(item, dict):
            entry = build_entry(item, specification.get("sku"))
            if entry:
                entries.append(entry)
    return entries


def _parse_dimension_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = re.search(r"\d+(?:\.\d+)?", str(value).replace(",", ""))
    return float(match.group(0)) if match else None


def _resolve_product_dimensions(data: dict) -> dict[str, float | None]:
    dimensions = {
        "length": _parse_dimension_float(data.get("dimensionLength")),
        "width": _parse_dimension_float(data.get("dimensionWidth")),
        "height": _parse_dimension_float(data.get("dimensionHeight")),
    }
    if not all(dimensions.values()):
        logger.warning(
            "[Step1] 大建产品尺寸缺少组装长宽高，产品尺寸不使用包装尺寸兜底: "
            f"length={data.get('dimensionLength')}, width={data.get('dimensionWidth')}, height={data.get('dimensionHeight')}"
        )
    return dimensions


def _gigab2b_raw_snapshot(base_data: dict, price_data: dict) -> dict:
    product_info = base_data.get("product_info") or {}
    specification = product_info.get("specification") or {}
    return {
        "product": {
            "sku": product_info.get("sku") or specification.get("sku"),
            "product_name": product_info.get("product_name") or specification.get("product_name"),
            "brand_name": product_info.get("brand_name"),
            "product_type": product_info.get("product_type") or specification.get("product_type_name"),
            "category_info": product_info.get("category_info"),
            "retail_ready_flag": product_info.get("retail_ready_flag"),
            "white_labeling_flag": product_info.get("white_labeling_flag"),
            "return_warranty": product_info.get("return_warranty"),
            "first_available_date": product_info.get("first_available_date"),
        },
        "specification": {
            "product_dimensions": specification.get("product_dimensions"),
            "package_size": specification.get("package_size"),
            "property_infos": specification.get("property_infos"),
            "origin_place": specification.get("origin_place"),
            "danger_info": specification.get("danger_info"),
            "upc": specification.get("upc"),
        },
        "pricing": {
            "base_price_info": price_data.get("base_price_info"),
            "fulfillment_options": price_data.get("fulfillment_options"),
            "quantity": price_data.get("quantity"),
        },
    }


def _api_headers(cookie: str | None, referer: str, *, ajax: bool = True) -> dict[str, str]:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*" if ajax else "application/octet-stream,*/*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Referer": referer,
    }
    if ajax:
        headers["X-Requested-With"] = "XMLHttpRequest"
    if cookie:
        headers["Cookie"] = cookie
    return headers


async def _get_gigab2b_cookie(product_url: str) -> str | None:
    cookie = await chrome_get_cookie_for_domain("gigab2b.com")
    if cookie:
        return cookie
    # 打开一次页面只为让 Chrome 暴露当前登录态，不等待完整渲染。
    if await chrome_navigate(product_url, wait=1.0):
        return await chrome_get_cookie_for_domain("gigab2b.com")
    return None


async def _gigab2b_get_json(client: httpx.AsyncClient, route: str, params: dict, headers: dict) -> dict:
    response = await client.get(f"{GIGAB2B_BASE_URL}/index.php", params={"route": route, **params}, headers=headers)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict) or int(payload.get("code", 0)) != 200:
        raise RuntimeError(f"GigaB2B API 返回异常: route={route}, payload={payload}")
    return payload.get("data") or {}


async def _gigab2b_post_json(client: httpx.AsyncClient, route: str, data: dict, headers: dict) -> dict:
    response = await client.post(f"{GIGAB2B_BASE_URL}/index.php", params={"route": route}, data=data, headers=headers)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError(f"GigaB2B API 返回非JSON对象: route={route}")
    return payload


def _normalize_gigab2b_api_data(gigab2b_pid: str, base_data: dict, price_data: dict) -> dict:
    product_info = base_data.get("product_info") or {}
    seller_info = base_data.get("seller_info") or {}
    specification = product_info.get("specification") or {}
    props = _property_lookup(specification)
    product_dimensions = specification.get("product_dimensions") or {}
    dimensions = product_dimensions.get("assemble_info") or {}
    package_entries = _package_entries_from_api(specification)
    image_urls = _image_urls_from_api(product_info)

    base_price = price_data.get("base_price_info") or {}
    fulfillment = price_data.get("fulfillment_options") or {}
    drop_ship = fulfillment.get("drop_ship") or {}
    cloud = fulfillment.get("cloud") or {}
    quantity = price_data.get("quantity") or {}

    value_total = _money_number(base_price.get("price"))
    shipping_cost = _money_number(drop_ship.get("amazon_total_amount") or drop_ship.get("total_amount"))
    estimated_total = round(value_total + shipping_cost, 2) if value_total is not None and shipping_cost is not None else None
    characteristic = product_info.get("characteristic")
    feature_items = _html_list_items(characteristic)

    data = {
        "itemCode": product_info.get("sku") or specification.get("sku"),
        "title": product_info.get("product_name") or specification.get("product_name"),
        "color": _property_any(props, ("Main Color", "颜色", "Color")),
        "material": _property_any(props, ("Main Material", "材质", "Material")),
        "filler": _property_any(props, ("Filler", "填充物", "Fill Material")),
        "productType": specification.get("product_type_name") or product_info.get("product_type_name"),
        "origin": _text_value(specification.get("origin_place")) or _property_any(props, ("Place of Origin", "产地")),
        "dimensionLength": dimensions.get("length_show"),
        "dimensionWidth": dimensions.get("width_show"),
        "dimensionHeight": dimensions.get("height_show"),
        "weight": dimensions.get("weight_show"),
        "_rawProductDimensions": product_dimensions,
        "packages": package_entries,
        "valueTotal": value_total,
        "unitPrice": value_total,
        "estimatedTotal": estimated_total,
        "shippingCost": shipping_cost,
        "shippingCostMin": _money_number(cloud.get("min_total_amount")),
        "shippingCostMax": _money_number(cloud.get("max_total_amount")),
        "stock": quantity.get("quantity"),
        "seller": seller_info.get("store_name") or seller_info.get("store_code"),
        "features": feature_items,
        "characteristic": _html_to_text(characteristic),
        "variants": [],
        "imageUrls": image_urls,
        "imageCount": len(image_urls),
        "fileUrls": [],
        "loginStatus": "logged_in_or_unknown" if price_data.get("price_visible") else "not_logged_in",
        "hasCommerceAction": bool(price_data.get("price_visible") or product_info.get("is_product_available")),
        "commerceFieldsPresent": sum(
            1 for value in (
                value_total,
                estimated_total,
                shipping_cost,
                quantity.get("quantity"),
            )
            if value not in (None, "")
        ),
        "_gigab2bProductId": gigab2b_pid,
        "_gigab2bSellerId": seller_info.get("seller_id"),
        "_gigab2bRetailReady": bool(product_info.get("retail_ready_flag")),
        "_gigab2bApiSource": True,
        "_gigab2bRawSnapshot": _gigab2b_raw_snapshot(base_data, price_data),
    }

    is_available = product_info.get("is_product_available")
    no_login_unavailable = product_info.get("no_login_and_unavaiable")
    if is_available is False or no_login_unavailable:
        data["availabilityStatus"] = "offline"
        data["availabilityReason"] = "页面显示商品不可售"
    else:
        data["availabilityStatus"] = "available"
        data["availabilityReason"] = None
    return data


async def _collect_product_data_via_api(gigab2b_pid: str, product_url: str) -> tuple[dict, str]:
    cookie = await _get_gigab2b_cookie(product_url)
    if not cookie:
        raise RuntimeError("未能从 Chrome 读取 GigaB2B 登录 Cookie")

    headers = _api_headers(cookie, product_url)
    async with httpx.AsyncClient(timeout=GIGAB2B_API_TIMEOUT, follow_redirects=True) as client:
        base_data, price_data = await asyncio.gather(
            _gigab2b_get_json(
                client,
                "/product/info/info/baseInfos",
                {"product_id": gigab2b_pid},
                headers,
            ),
            _gigab2b_get_json(
                client,
                "/product/info/price/list",
                {"product_id": gigab2b_pid},
                headers,
            ),
        )

    data = _normalize_gigab2b_api_data(gigab2b_pid, base_data, price_data)
    if not _extract_ready_to_use(data):
        raise RuntimeError(f"GigaB2B API 字段不完整: {_extract_summary(data)}")
    if data.get("loginStatus") == "not_logged_in" and not _is_offline_product(data):
        raise RuntimeError("GigaB2B API 价格/库存不可见，疑似登录态失效")
    return data, cookie


async def _collect_product_data_via_chrome(gigab2b_pid: str, product_url: str) -> dict:
    logger.info(f"[Step1] 打开 GigaB2B 页面: {product_url}")
    success = await chrome_navigate(product_url, wait=4.0)
    if not success:
        raise RuntimeError("Chrome 导航失败，请确认 Chrome 已开启 JS 权限")
    ready_probe = await _wait_for_gigab2b_page_ready(gigab2b_pid)
    logger.info(f"[Step1] GigaB2B 页面加载探测: {ready_probe}")
    after_ready_wait = max(0.0, float(settings.STEP1_AFTER_READY_WAIT_SECONDS))
    if after_ready_wait:
        logger.info(f"[Step1] 页面已有内容，等待 {after_ready_wait:g}s 让价格/规格区完成渲染")
        await asyncio.sleep(after_ready_wait)

    logger.info("[Step1] 执行 JS 提取商品数据...")
    data = {}
    last_js_result = None
    retry_attempts = max(1, settings.STEP1_EXTRACT_RETRY_ATTEMPTS)
    retry_delay = max(0, settings.STEP1_EXTRACT_RETRY_DELAY_SECONDS)
    for attempt in range(1, retry_attempts + 1):
        js_result = await chrome_execute_js(EXTRACT_JS, timeout=30)
        last_js_result = js_result
        try:
            parsed = _parse_extract_json(js_result)
        except json.JSONDecodeError as e:
            page_info = await chrome_get_page_info()
            logger.warning(
                f"[Step1] 第 {attempt} 次 JS 返回非JSON，等待后重试: {e}; "
                f"page={page_info}; raw={_preview_js_result(js_result)}"
            )
            parsed = None

        if parsed is None:
            if not js_result:
                logger.warning(f"[Step1] 第 {attempt} 次 JS 提取无返回")
            else:
                page_info = await chrome_get_page_info()
                logger.warning(
                    f"[Step1] 第 {attempt} 次 JS 返回不可解析，等待后重试: "
                    f"page={page_info}; raw={_preview_js_result(js_result)}"
                )
        else:
            data = parsed
            if not isinstance(data, dict):
                logger.warning(
                    f"[Step1] 第 {attempt} 次 JS 返回结构不是对象，等待后重试: "
                    f"raw={_preview_js_result(js_result)}"
                )
                data = {}
            else:
                logger.info(f"[Step1] 第 {attempt} 次提取摘要: {_extract_summary(data)}")
                if _extract_ready_to_use(data):
                    break
                logger.warning(
                    "[Step1] 商品标题已出现但价格/规格/库存区仍未完整，等待页面异步数据后重试..."
                )

        if attempt < retry_attempts:
            logger.warning("[Step1] 核心商品字段为空或页面返回异常，等待页面继续加载后重试...")
            await asyncio.sleep(retry_delay)

    if not _has_core_product_data(data) and not _is_offline_product(data):
        page_probe = await chrome_execute_js(
            "JSON.stringify({readyState: document.readyState, url: location.href, title: document.title, bodyText: (document.body && document.body.innerText || '').slice(0, 300)})",
            timeout=10,
        )
        try:
            probe_data = json.loads(page_probe) if page_probe else None
        except json.JSONDecodeError:
            probe_data = {"raw": _preview_js_result(page_probe)}
        page_info = await chrome_get_page_info()
        logger.error(
            "[Step1] 商品核心信息采集失败: "
            f"product_id={gigab2b_pid}, page={page_info}, probe={probe_data}, "
            f"summary={_extract_summary(data)}, raw={_preview_js_result(last_js_result)}, "
            f"raw_len={len(last_js_result or '')}"
        )
        raise RuntimeError(
            "大健商品核心信息采集失败，请确认 Chrome 已登录大健云仓、商品页已正常加载。"
            f"product_id={gigab2b_pid}, page={page_info}, raw={_preview_js_result(last_js_result)}"
        )
    return data


def _select_api_resource_option(data: dict) -> tuple[str, int, str]:
    options = ["To B素材包"]
    if data.get("_gigab2bRetailReady"):
        options.insert(0, "Retail Ready素材包")
    selected = _select_download_option(options)
    product_type = GIGAB2B_RESOURCE_TYPES.get(selected)
    if not product_type:
        raise RuntimeError(f"GigaB2B API 暂不支持素材包类型: {selected}")
    type_key = "retail_ready" if product_type == 2 else "to_b"
    return selected, product_type, type_key


async def _download_material_zips_via_api(save_dir: Path, data: dict, cookie: str | None) -> list[dict]:
    product_id = data.get("_gigab2bProductId")
    seller_id = data.get("_gigab2bSellerId")
    if not product_id or not seller_id:
        raise RuntimeError("GigaB2B API 下载缺少 product_id 或 seller_id")
    if not cookie:
        raise RuntimeError("GigaB2B API 下载缺少登录 Cookie")

    selected, product_type, type_key = _select_api_resource_option(data)
    product_url = f"{GIGAB2B_BASE_URL}/index.php?route=product/product&product_id={product_id}"
    ajax_headers = _api_headers(cookie, product_url, ajax=True)
    download_headers = _api_headers(cookie, product_url, ajax=False)
    trigger_data = {
        "product_id": str(product_id),
        "customer_id": str(seller_id),
        "product_type": str(product_type),
    }

    timeout_at = time.monotonic() + settings.STEP1_DOWNLOAD_TIMEOUT_SECONDS
    async with httpx.AsyncClient(timeout=GIGAB2B_API_TIMEOUT, follow_redirects=True) as client:
        attempt = 0
        while True:
            attempt += 1
            payload = await _gigab2b_post_json(
                client,
                "product/product/download",
                trigger_data,
                ajax_headers,
            )
            code = int(payload.get("code", 0))
            logger.info(f"[Step1] API 素材包打包状态: option={selected}, attempt={attempt}, code={code}")
            if code == 200:
                break
            if code != 300:
                raise RuntimeError(f"GigaB2B API 素材包打包失败: {payload}")
            if time.monotonic() >= timeout_at:
                raise RuntimeError("GigaB2B API 素材包打包超时")
            await asyncio.sleep(3)

        save_dir.mkdir(parents=True, exist_ok=True)
        fallback_name = f"{data.get('itemCode') or product_id}_{type_key}.zip"
        params = {
            "route": "product/product/downloadZip",
            "product_id": str(product_id),
            "product_type": str(product_type),
        }
        async with client.stream(
            "GET",
            f"{GIGAB2B_BASE_URL}/index.php",
            params=params,
            headers=download_headers,
        ) as response:
            response.raise_for_status()
            filename = _filename_from_content_disposition(
                response.headers.get("content-disposition"),
                fallback_name,
            )
            target_zip = _unique_target_path(save_dir, filename)
            tmp_zip = target_zip.with_suffix(f"{target_zip.suffix}.part")
            size = 0
            try:
                with tmp_zip.open("wb") as fh:
                    async for chunk in response.aiter_bytes(1024 * 512):
                        if chunk:
                            fh.write(chunk)
                            size += len(chunk)
                if size == 0:
                    raise RuntimeError("GigaB2B API 下载到空素材 ZIP")
                with tmp_zip.open("rb") as fh:
                    if fh.read(2) != b"PK":
                        raise RuntimeError(
                            "GigaB2B API 下载结果不是 ZIP: "
                            f"content_type={response.headers.get('content-type')}, size={size}"
                        )
                tmp_zip.replace(target_zip)
            except Exception:
                tmp_zip.unlink(missing_ok=True)
                raise

    return [await asyncio.to_thread(_store_and_extract_api_zip, target_zip, type_key, save_dir)]


async def _download_material_zips_via_chrome(save_dir: Path, item_code: str | None) -> list[dict]:
    """参考 gigab2b-product-collector：点击下载按钮，并等待 Chrome 下载出的多个 zip。"""
    existing_zips = _existing_download_zips()
    download_started_at = time.time()
    clicked = await _click_download_button()
    if not clicked:
        page_info = await chrome_get_page_info()
        raise RuntimeError(
            "未找到大健云仓“下载素材包”按钮，请确认 Chrome 已登录大健云仓且商品页正常加载: "
            f"{page_info}"
        )

    await asyncio.sleep(1.5)
    options = await _get_download_options()
    if options:
        selected = _select_download_option(options)
        logger.info(f"[Step1] 检测到素材包选项: {options}，选择: {selected}")
        if not await _click_download_option(selected):
            raise RuntimeError(f"点击大健云仓素材包选项失败: {selected}")
    else:
        logger.info("[Step1] 未检测到素材包选项，按普通商品等待直接下载")

    downloaded_zips = await _wait_for_browser_zips(existing_zips, item_code, download_started_at)
    if not downloaded_zips:
        raise RuntimeError("大健云仓素材下载未产生 ZIP 文件，停止后续步骤")
    logger.info(f"[Step1] 检测到新下载 ZIP: {[p.name for p in downloaded_zips]}")

    return await asyncio.to_thread(_store_and_extract_zips, downloaded_zips, save_dir)


def _download_summary(results: list[dict]) -> tuple[int, int]:
    return len(results), sum(int(item.get("extracted_count") or 0) for item in results)


def _existing_material_count(material_dir: Path) -> int:
    if not material_dir.exists():
        return 0
    return sum(
        1 for path in material_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in MATERIAL_FILE_EXTENSIONS
    )


def _policy_value(value: str | None, default: str = "manual_review") -> str:
    normalized = (value or "").strip().lower()
    return normalized if normalized in {"fail", "manual_review", "continue"} else default


def _handle_step1_issue(issue: str, policy: str, review_reasons: list[str]) -> None:
    policy = _policy_value(policy)
    if policy == "fail":
        raise RuntimeError(issue)
    if policy == "manual_review":
        review_reasons.append(issue)
        logger.warning(f"[Step1] 需要人工处理: {issue}")
        return
    logger.warning(f"[Step1] 按配置继续执行，忽略问题: {issue}")

# GigaB2B 商品信息提取 JS — 从外部文件加载，避免 Python 转义问题
_EXTRACT_JS_PATH = Path(__file__).parent / "extract_product.js"


def _load_extract_js() -> str:
    """加载 JS 提取脚本，避免 Python 三引号转义问题"""
    source = _EXTRACT_JS_PATH.read_text(encoding="utf-8")
    return f"""(function() {{
    try {{
        return (
{source}
        );
    }} catch (e) {{
        return JSON.stringify({{
            __extractError: String(e && e.message || e),
            __extractStack: String(e && e.stack || ''),
            title: document.title,
            url: location.href,
            readyState: document.readyState,
            bodyText: (document.body && document.body.innerText || '').slice(0, 500)
        }});
    }}
}})()"""


EXTRACT_JS = _load_extract_js()


def extract_product_id(url: str) -> str | None:
    """从 GigaB2B URL 提取商品ID"""
    return extract_gigab2b_product_id(url)


def _parse_float(val) -> float | None:
    """安全解析浮点数"""
    if val is None:
        return None
    try:
        # 去掉逗号和空格
        cleaned = str(val).replace(",", "").replace(" ", "").strip()
        return float(cleaned)
    except (ValueError, TypeError):
        return None


def _parse_int(val) -> int | None:
    """安全解析整数"""
    if val is None:
        return None
    try:
        return int(float(str(val).replace(",", "").strip()))
    except (ValueError, TypeError):
        return None


def _has_core_product_data(data: dict) -> bool:
    """判断大健商品核心字段是否采集成功"""
    return bool(data.get("title") or data.get("itemCode") or data.get("productType"))


def _has_detail_product_data(data: dict) -> bool:
    """页面主体已加载后，规格/价格区仍可能异步晚到，这里判断是否足够完整。"""
    return any(
        str(data.get(field) or "").strip()
        for field in (
            "productType",
            "dimensionLength",
            "dimensionWidth",
            "dimensionHeight",
            "valueTotal",
            "estimatedTotal",
            "shippingCost",
            "shippingCostMin",
            "shippingCostMax",
            "stock",
        )
    )


def _extract_ready_to_use(data: dict) -> bool:
    if _is_offline_product(data):
        return True
    if not _has_core_product_data(data):
        return False
    if _looks_like_source_unavailable(data, _parse_int(data.get("stock"))):
        return True
    return _has_detail_product_data(data)


def _is_offline_product(data: dict) -> bool:
    return data.get("availabilityStatus") == "offline"


def _is_not_logged_in(data: dict) -> bool:
    return data.get("loginStatus") == "not_logged_in"


def _has_commerce_values(data: dict) -> bool:
    fields = (
        "valueTotal",
        "estimatedTotal",
        "shippingCost",
        "shippingCostMin",
        "shippingCostMax",
        "priceMin",
        "priceMax",
        "unitPrice",
        "stock",
    )
    return any(str(data.get(field) or "").strip() for field in fields)


def _looks_like_source_unavailable(data: dict, stock: int | None = None) -> bool:
    if _is_not_logged_in(data):
        return False
    if _is_offline_product(data) or stock == 0:
        return True
    has_identity = bool(data.get("itemCode") or data.get("title"))
    if not has_identity:
        return False
    has_action = bool(data.get("hasCommerceAction"))
    commerce_count = _parse_int(data.get("commerceFieldsPresent")) or 0
    return commerce_count == 0 and not has_action and not _has_commerce_values(data)


def _unavailable_reason(data: dict, stock: int | None = None) -> str | None:
    if _is_offline_product(data):
        return data.get("availabilityReason") or "页面显示商品不可售"
    if stock == 0:
        return "商品库存为 0"
    if _looks_like_source_unavailable(data, stock):
        return "页面缺少价格、库存和购买/下载入口，疑似原商品已下架"
    return None


def _price_missing_unavailable_reason(data: dict, stock: int | None = None) -> str | None:
    value_total = _parse_float(data.get("valueTotal"))
    estimated_total = _parse_float(data.get("estimatedTotal"))
    shipping_cost = _parse_float(data.get("shippingCost"))
    shipping_min = _parse_float(data.get("shippingCostMin"))
    shipping_max = _parse_float(data.get("shippingCostMax"))

    if stock == 0:
        return "商品价格/成本信息缺失且库存为 0"
    if value_total == 0 and any(value is not None and value > 0 for value in (estimated_total, shipping_cost, shipping_min, shipping_max)):
        return (
            "商品货值为 0 且仍返回物流/预估成本，通常表示无可售库存或已下架"
        )
    return None


def _download_missing_unavailable_reason(data: dict, stock: int | None, error: Exception) -> str | None:
    error_text = str(error)
    if "未找到大健云仓“下载素材包”按钮" not in error_text:
        return None
    if _is_not_logged_in(data):
        return None
    if _looks_like_source_unavailable(data, stock):
        return "页面缺少价格、库存和下载素材包入口"
    if _has_core_product_data(data) and not _has_commerce_values(data):
        return "商品基础信息仍可见，但价格/库存和下载素材包入口均不存在"
    return None


def _extract_summary(data: dict) -> dict:
    """日志里只放摘要，避免把整页图片和大段文案刷屏"""
    return {
        "itemCode": data.get("itemCode"),
        "__extractError": data.get("__extractError"),
        "title": data.get("title"),
        "productType": data.get("productType"),
        "dimensionLength": data.get("dimensionLength"),
        "dimensionWidth": data.get("dimensionWidth"),
        "dimensionHeight": data.get("dimensionHeight"),
        "valueTotal": data.get("valueTotal"),
        "estimatedTotal": data.get("estimatedTotal"),
        "shippingCost": data.get("shippingCost"),
        "shippingCostMin": data.get("shippingCostMin"),
        "shippingCostMax": data.get("shippingCostMax"),
        "stock": data.get("stock"),
        "availabilityStatus": data.get("availabilityStatus"),
        "availabilityReason": data.get("availabilityReason"),
        "loginStatus": data.get("loginStatus"),
        "hasCommerceAction": data.get("hasCommerceAction"),
        "commerceFieldsPresent": data.get("commerceFieldsPresent"),
        "imageUrls": len(data.get("imageUrls") or []),
        "fileUrls": len(data.get("fileUrls") or []),
        "packages": len(data.get("packages") or []),
        "features": len(data.get("features") or []),
        "variants": len(data.get("variants") or []),
    }


def _preview_js_result(value: str | None, limit: int = 240) -> str:
    if value is None:
        return "<None>"
    text = str(value).replace("\n", "\\n").replace("\r", "\\r")
    return text[:limit]


def _parse_extract_json(js_result: str | None) -> dict | None:
    if not js_result:
        return None

    text = js_result.strip()
    if not text or text in {"missing value", "undefined", "null"}:
        return None
    if not (text.startswith("{") or text.startswith("[")):
        return None

    return json.loads(text)


async def _wait_for_gigab2b_page_ready(gigab2b_pid: str, timeout_seconds: float = 20.0) -> dict | None:
    """等待 Chrome 标签页至少加载出 body，避免在空 DOM 上执行完整提取脚本。"""
    started_at = time.monotonic()
    last_probe = None
    probe_js = r'''JSON.stringify({
        readyState: document.readyState,
        url: location.href,
        title: document.title || '',
        hasBody: !!document.body,
        bodyTextLength: document.body ? (document.body.innerText || document.body.textContent || '').trim().length : 0,
        bodyText: document.body ? (document.body.innerText || document.body.textContent || '').slice(0, 180) : ''
    })'''

    while time.monotonic() - started_at < timeout_seconds:
        raw = await chrome_execute_js(probe_js, timeout=10)
        try:
            last_probe = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            last_probe = {"raw": _preview_js_result(raw)}

        if isinstance(last_probe, dict):
            has_body = bool(last_probe.get("hasBody"))
            text_length = int(last_probe.get("bodyTextLength") or 0)
            if has_body and text_length > 0:
                return last_probe

        await asyncio.sleep(1)

    return last_probe


async def collect_product(product_id: int) -> dict:
    async with chrome_workflow(f"step1_collect product={product_id}"):
        return await _collect_product_locked(product_id)


async def _collect_product_locked(product_id: int) -> dict:
    """
    执行商品采集：
    1. 从 URL 提取 GigaB2B 商品ID
    2. 通过 Chrome 打开页面
    3. 执行 JS 提取商品数据
    4. 解析并保存到数据库
    
    Returns:
        dict: 采集到的商品数据
    """
    async with async_session() as db:
        # 读取商品记录
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload
        result = await db.execute(
            select(Product)
            .options(selectinload(Product.data))
            .where(Product.id == product_id)
        )
        product = result.scalar_one_or_none()
        if not product:
            raise ValueError(f"Product {product_id} not found")

        gigab2b_pid = extract_product_id(product.gigab2b_url)
        if not gigab2b_pid:
            raise ValueError(f"无法从URL提取商品ID: {product.gigab2b_url}")

        duplicate = await find_duplicate_by_gigab2b_product_id(db, gigab2b_pid, exclude_product_id=product.id)
        if duplicate:
            product.gigab2b_product_id = gigab2b_pid
            await db.commit()
            raise Step1DuplicateSkipped(f"{duplicate.message}，当前任务跳过采集")

        product.gigab2b_product_id = gigab2b_pid

        url = f"https://www.gigab2b.com/index.php?route=product/product&product_id={gigab2b_pid}"
        api_cookie = None
        data = {}
        try:
            logger.info(f"[Step1] 尝试通过 GigaB2B API 采集商品数据: {url}")
            data, api_cookie = await _collect_product_data_via_api(gigab2b_pid, url)
            logger.info(f"[Step1] API 提取摘要: {_extract_summary(data)}")
        except Exception as e:
            logger.warning(f"[Step1] GigaB2B API 采集失败，回退 Chrome 页面解析: {type(e).__name__}: {e}")
            data = await _collect_product_data_via_chrome(gigab2b_pid, url)

        logger.info(f"[Step1] 提取到商品: {data.get('title', 'N/A')}")
        resolved_dimensions = _resolve_product_dimensions(data)

        collected_item_code = data.get("itemCode")
        duplicate = await find_duplicate_by_item_code(db, collected_item_code, exclude_product_id=product.id)
        if duplicate:
            pd = product.data
            if not pd:
                pd = ProductData(product_id=product.id)
                db.add(pd)
            pd.item_code = collected_item_code
            await db.commit()
            raise Step1DuplicateSkipped(f"{duplicate.message}，当前任务跳过采集")

        # 创建素材目录
        brand = product.brand or settings.DEFAULT_BRAND
        item_code = data.get("itemCode") or gigab2b_pid
        material_dir = settings.PRODUCT_BASE_DIR / brand / item_code
        material_dir.mkdir(parents=True, exist_ok=True)
        raw_file_dir = material_dir / RAW_ASSETS_DIR

        # 解析并保存数据
        pd = product.data
        if not pd:
            pd = ProductData(product_id=product.id)
            db.add(pd)

        pd.item_code = data.get("itemCode")
        pd.title = data.get("title")
        pd.color = data.get("color")
        pd.material = data.get("material")
        pd.filler = data.get("filler")
        pd.product_type = data.get("productType")
        pd.dimension_length = resolved_dimensions.get("length")
        pd.dimension_width = resolved_dimensions.get("width")
        pd.dimension_height = resolved_dimensions.get("height")
        pd.weight = _parse_float(data.get("weight"))
        pd.packages = json.dumps(data.get("packages", []), ensure_ascii=False) if data.get("packages") else None
        pd.value_total = _parse_float(data.get("valueTotal"))
        pd.estimated_total = _parse_float(data.get("estimatedTotal"))
        pd.shipping_cost = _parse_float(data.get("shippingCost"))  # 一件代发物流费
        pd.shipping_cost_min = _parse_float(data.get("shippingCostMin"))  # 云送仓最低物流费
        pd.shipping_cost_max = _parse_float(data.get("shippingCostMax"))  # 云送仓最高物流费
        pd.features = json.dumps(data.get("features", []), ensure_ascii=False) if data.get("features") else None
        pd.description = data.get("characteristic")  # 大建五点描述
        pd.variants = json.dumps(data.get("variants", []), ensure_ascii=False) if data.get("variants") else None
        pd.gigab2b_raw_snapshot = (
            json.dumps(data.get("_gigab2bRawSnapshot"), ensure_ascii=False)
            if data.get("_gigab2bRawSnapshot")
            else None
        )
        pd.stock = _parse_int(data.get("stock"))
        pd.seller = data.get("seller")
        pd.origin = data.get("origin")
        pd.image_count = _parse_int(data.get("imageCount"))
        pd.material_dir = str(material_dir)
        pd.collected_at = datetime.now()

        unavailable_reason = _unavailable_reason(data, pd.stock)
        if unavailable_reason:
            await db.commit()
            raise Step1ProductUnavailable(unavailable_reason)

        review_reasons: list[str] = []
        price_issue = None
        if not pd.value_total or not pd.estimated_total:
            price_unavailable_reason = _price_missing_unavailable_reason(data, pd.stock)
            if price_unavailable_reason:
                await db.commit()
                raise Step1ProductUnavailable(price_unavailable_reason)
            price_issue = (
                "大健云仓价格/成本信息未收集完整，请确认已登录且页面展示价格后继续："
                f"valueTotal={data.get('valueTotal')}, estimatedTotal={data.get('estimatedTotal')}, "
                f"shippingCost={data.get('shippingCost')}, "
                f"shippingRange={data.get('shippingCostMin')}~{data.get('shippingCostMax')}"
            )

        await db.commit()
        if price_issue:
            _handle_step1_issue(price_issue, settings.STEP1_PRICE_MISSING_POLICY, review_reasons)

        # === 下载原始 zip。页面图片不下载，后续图片来自 zip 解压内容。===
        logger.info(f"[Step1] 下载大健云仓素材 ZIP 到 {raw_file_dir}...")
        downloaded_files = []
        material_download_failed = False
        try:
            try:
                logger.info("[Step1] 尝试通过 GigaB2B API 下载素材 ZIP...")
                downloaded_files = await _download_material_zips_via_api(raw_file_dir, data, api_cookie)
            except Exception as api_error:
                logger.warning(
                    "[Step1] GigaB2B API 素材下载失败，回退 Chrome 点击下载: "
                    f"{type(api_error).__name__}: {api_error}"
                )
                downloaded_files = await _download_material_zips_via_chrome(raw_file_dir, pd.item_code)
        except Exception as e:
            download_unavailable_reason = _download_missing_unavailable_reason(data, pd.stock, e)
            if download_unavailable_reason:
                raise Step1ProductUnavailable(download_unavailable_reason)
            existing_count = _existing_material_count(material_dir)
            if settings.STEP1_ALLOW_EXISTING_MATERIALS and existing_count > 0:
                logger.warning(
                    f"[Step1] 素材包下载失败，但检测到已有本地素材 {existing_count} 个，"
                    f"按配置继续: {type(e).__name__}: {e}"
                )
            else:
                material_download_failed = True
                _handle_step1_issue(
                    f"大健云仓素材包下载失败，请补充素材后继续: {type(e).__name__}: {e}",
                    settings.STEP1_MATERIAL_MISSING_POLICY,
                    review_reasons,
                )
        zip_count, extracted_count = _download_summary(downloaded_files)
        video_dir = await asyncio.to_thread(organize_video_files, material_dir)
        logger.info(f"[Step1] 原始素材下载完成: zip={zip_count}, 解压文件={extracted_count}")
        if video_dir:
            logger.info(f"[Step1] 视频素材已整理到: {video_dir}")
        existing_count = _existing_material_count(material_dir)
        if zip_count == 0 and existing_count == 0 and not material_download_failed:
            _handle_step1_issue(
                "大健云仓未下载到 ZIP 压缩包，且商品目录中没有可用本地素材",
                settings.STEP1_MATERIAL_MISSING_POLICY,
                review_reasons,
            )
        elif zip_count > 0 and extracted_count == 0:
            _handle_step1_issue(
                "大健云仓 ZIP 未成功解压出文件，请检查压缩包内容",
                settings.STEP1_MATERIAL_MISSING_POLICY,
                review_reasons,
            )
        if review_reasons:
            raise Step1NeedsReview(review_reasons)

        logger.info(f"[Step1] 商品采集完成: {pd.item_code} / {pd.title}")
        return data
