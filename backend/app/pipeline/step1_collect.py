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
from datetime import datetime
from pathlib import Path

from app.config import settings
from app.database import async_session
from app.models import Product, ProductData
from app.pipeline.chrome_ctrl import chrome_navigate, chrome_execute_js, chrome_get_page_info, chrome_workflow
from app.services.material_assets import organize_video_files

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


class Step1NeedsReview(RuntimeError):
    """Step1 已采集到核心资料，但需要人工补充后再继续。"""

    def __init__(self, reasons: list[str]):
        self.reasons = [reason for reason in reasons if reason]
        super().__init__("；".join(self.reasons))


class Step1ProductUnavailable(RuntimeError):
    """商品已下架或无库存，不应继续 Pipeline。"""


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
    match = re.search(r'product_id=(\d+)', url)
    if match:
        return match.group(1)
    match = re.search(r'product-detail/(\d+)', url)
    if match:
        return match.group(1)
    return None


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

        # 更新 product_id 字段
        product.gigab2b_product_id = gigab2b_pid

        # 打开 GigaB2B 页面
        url = f"https://www.gigab2b.com/index.php?route=product/product&product_id={gigab2b_pid}"
        logger.info(f"[Step1] 打开 GigaB2B 页面: {url}")
        
        success = await chrome_navigate(url, wait=4.0)
        if not success:
            raise RuntimeError("Chrome 导航失败，请确认 Chrome 已开启 JS 权限")
        ready_probe = await _wait_for_gigab2b_page_ready(gigab2b_pid)
        logger.info(f"[Step1] GigaB2B 页面加载探测: {ready_probe}")
        after_ready_wait = max(0.0, float(settings.STEP1_AFTER_READY_WAIT_SECONDS))
        if after_ready_wait:
            logger.info(f"[Step1] 页面已有内容，等待 {after_ready_wait:g}s 让价格/规格区完成渲染")
            await asyncio.sleep(after_ready_wait)

        # 执行 JS 提取。页面偶尔还在异步加载，核心字段为空时重试几次。
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
            # 再执行一个极小 JS，帮助判断是未登录、页面空白还是专用标签页异常。
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

        logger.info(f"[Step1] 提取到商品: {data.get('title', 'N/A')}")

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
        pd.dimension_length = _parse_float(data.get("dimensionLength"))
        pd.dimension_width = _parse_float(data.get("dimensionWidth"))
        pd.dimension_height = _parse_float(data.get("dimensionHeight"))
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
        logger.info(f"[Step1] 通过 Chrome 下载大健云仓素材 ZIP 到 {raw_file_dir}...")
        downloaded_files = []
        material_download_failed = False
        try:
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
