"""ASIN sync batches backed by Lingxing Listing lookup."""

import asyncio
import json
import logging
import re
from datetime import datetime
from urllib.parse import unquote

import httpx
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database import async_session
from app.models import AsinSyncBatch, AsinSyncItem, CatalogProduct, Product
from app.pipeline.chrome_ctrl import chrome_execute_js, chrome_get_cookie_for_domain, chrome_navigate, chrome_workflow

logger = logging.getLogger(__name__)

DEFAULT_STORE = "Andy店-US"
DEFAULT_STORE_ID = 17983
STORE_IDS = {
    "Andy店-US": 17983,
}
LINGXING_LISTING_URL = "https://erp.lingxing.com/erp/listing"
LINGXING_LISTING_API_URL = "https://gw.lingxingerp.com/listing-api/api/product/showOnline"
ASIN_RE = re.compile(r"\bB[A-Z0-9]{9}\b")
_running_batches: dict[int, asyncio.Task] = {}


def is_batch_running(batch_id: int) -> bool:
    task = _running_batches.get(batch_id)
    return task is not None and not task.done()


def start_asin_sync_batch(batch_id: int) -> bool:
    if batch_id in _running_batches:
        return False
    task = asyncio.create_task(_run_batch(batch_id))
    _running_batches[batch_id] = task
    return True


def _normalize_code(value: str | None) -> str:
    return re.sub(r"\s+", "", value or "").upper()


def _normalize_lookup_type(value: str | None) -> str:
    normalized = (value or "").strip()
    if normalized.upper() == "UPC":
        return "商品编码"
    if normalized.upper() == "SKU":
        return "MSKU"
    return normalized or "商品编码"


async def _update_batch_counts(db, batch: AsinSyncBatch) -> None:
    statuses = [item.status for item in batch.items]
    batch.success_count = statuses.count("success")
    batch.not_found_count = statuses.count("not_found") + statuses.count("multiple_found")
    batch.failed_count = statuses.count("failed")
    batch.skipped_count = statuses.count("skipped")
    done = batch.success_count + batch.not_found_count + batch.failed_count + batch.skipped_count
    if done >= batch.total_count:
        batch.status = "completed" if batch.failed_count == 0 else "partial"
        batch.finished_at = datetime.now()
    await db.commit()


async def _run_batch(batch_id: int) -> None:
    try:
        async with async_session() as db:
            result = await db.execute(
                select(AsinSyncBatch)
                .options(selectinload(AsinSyncBatch.items))
                .where(AsinSyncBatch.id == batch_id)
            )
            batch = result.scalar_one_or_none()
            if not batch:
                return
            batch.status = "running"
            batch.started_at = datetime.now()
            await db.commit()

        async with async_session() as db:
            result = await db.execute(
                select(AsinSyncBatch)
                .options(selectinload(AsinSyncBatch.items))
                .where(AsinSyncBatch.id == batch_id)
            )
            batch = result.scalar_one()
            item_ids = [item.id for item in batch.items if item.status == "pending"]
            store = batch.store or DEFAULT_STORE
            if not item_ids:
                await _update_batch_counts(db, batch)
                return

        auth = await _get_lingxing_listing_auth(store)
        if not auth.get("ok"):
            await _fail_whole_batch(batch_id, auth.get("error") or "领星未登录，无法查询 ASIN")
            return

        for item_id in item_ids:
            await _run_item(item_id, store, auth)

        async with async_session() as db:
            result = await db.execute(
                select(AsinSyncBatch)
                .options(selectinload(AsinSyncBatch.items))
                .where(AsinSyncBatch.id == batch_id)
            )
            batch = result.scalar_one_or_none()
            if batch:
                await _update_batch_counts(db, batch)
    except Exception as exc:
        logger.exception("[ASIN Sync] Batch %s failed", batch_id)
        await _fail_whole_batch(batch_id, f"{type(exc).__name__}: {exc}")
    finally:
        _running_batches.pop(batch_id, None)


async def _fail_whole_batch(batch_id: int, error: str) -> None:
    async with async_session() as db:
        result = await db.execute(
            select(AsinSyncBatch)
            .options(selectinload(AsinSyncBatch.items))
            .where(AsinSyncBatch.id == batch_id)
        )
        batch = result.scalar_one_or_none()
        if not batch:
            return
        batch.status = "failed"
        batch.error_message = error
        batch.finished_at = datetime.now()
        for item in batch.items:
            if item.status in {"pending", "running"}:
                item.status = "failed"
                item.error_message = error
                item.finished_at = datetime.now()
                product = await db.get(Product, item.product_id)
                catalog = await db.get(CatalogProduct, item.catalog_product_id)
                for target in (product, catalog):
                    if target:
                        target.asin_sync_status = "failed"
                        target.asin_sync_error = error
                        target.asin_synced_at = datetime.now()
        await _update_batch_counts(db, batch)


async def _run_item(item_id: int, store: str, auth: dict | None = None) -> None:
    async with async_session() as db:
        result = await db.execute(select(AsinSyncItem).where(AsinSyncItem.id == item_id))
        item = result.scalar_one_or_none()
        if not item:
            return
        item.status = "running"
        item.started_at = datetime.now()
        await db.commit()
        lookup_code = item.lookup_code
        lookup_type = _normalize_lookup_type(item.lookup_type)

    if not lookup_code:
        await _finish_item(item_id, "skipped", error="缺少 ASIN、UPC/商品编码或 SKU，无法查询")
        return

    try:
        lookup = await _lookup_asin(lookup_code, store, lookup_type, auth)
        if lookup.get("status") == "not_logged_in":
            await _finish_item(item_id, "failed", error="领星未登录，无法查询 ASIN")
            return
        if lookup.get("status") == "not_found":
            await _finish_item(item_id, "not_found", error=lookup.get("error") or "没查到数据")
            return
        if lookup.get("status") == "multiple_found":
            await _finish_item(item_id, "multiple_found", error=lookup.get("error") or "匹配到多个 Listing，未写入 ASIN")
            return
        if lookup.get("status") == "failed":
            await _finish_item(item_id, "failed", error=lookup.get("error") or "领星查询失败")
            return
        asin = lookup.get("asin")
        matched_code = lookup.get("matched_code")
        amazon_product_status = lookup.get("amazon_product_status")
        if not asin or _normalize_code(matched_code) != _normalize_code(lookup_code):
            await _finish_item(item_id, "failed", error="查询结果未通过商品编码校验")
            return
        await _finish_item(item_id, "success", asin=asin, matched_code=matched_code, amazon_product_status=amazon_product_status)
    except Exception as exc:
        await _finish_item(item_id, "failed", error=f"{type(exc).__name__}: {exc}")


async def _finish_item(
    item_id: int,
    status: str,
    asin: str | None = None,
    matched_code: str | None = None,
    amazon_product_status: str | None = None,
    error: str | None = None,
) -> None:
    async with async_session() as db:
        result = await db.execute(select(AsinSyncItem).where(AsinSyncItem.id == item_id))
        item = result.scalar_one_or_none()
        if not item:
            return
        item.status = status
        item.amazon_asin = asin
        item.matched_code = matched_code
        item.amazon_product_status = amazon_product_status
        item.error_message = error
        item.finished_at = datetime.now()

        product = await db.get(Product, item.product_id)
        catalog = await db.get(CatalogProduct, item.catalog_product_id)
        sync_status = {
            "success": "synced",
            "not_found": "not_found",
            "multiple_found": "multiple_found",
            "failed": "failed",
            "skipped": "skipped",
        }.get(status, status)
        for target in (product, catalog):
            if not target:
                continue
            target.asin_sync_status = sync_status
            target.asin_sync_error = error
            target.amazon_product_status_error = error
            if asin:
                target.amazon_asin = asin
                target.asin_synced_at = datetime.now()
                target.amazon_product_status = amazon_product_status
                target.amazon_product_status_synced_at = datetime.now()
                target.amazon_product_status_error = None if amazon_product_status else "领星 Listing 接口未返回亚马逊商品状态"
            elif status in {"not_found", "multiple_found", "failed", "skipped"}:
                target.asin_synced_at = datetime.now()
                target.amazon_product_status_synced_at = datetime.now()

        batch_result = await db.execute(
            select(AsinSyncBatch)
            .options(selectinload(AsinSyncBatch.items))
            .where(AsinSyncBatch.id == item.batch_id)
        )
        batch = batch_result.scalar_one_or_none()
        if batch:
            await _update_batch_counts(db, batch)
        else:
            await db.commit()


async def _prepare_lingxing_listing() -> dict:
    opened = await chrome_navigate(LINGXING_LISTING_URL, wait=4)
    if not opened:
        return {"ok": False, "error": "无法打开领星 Listing 页面"}
    js = """
(function() {
  const text = document.body ? document.body.innerText : '';
  if (/登录|login/i.test(text) && !/Listing|商品编码|产品|销售/.test(text)) {
    return JSON.stringify({ok:false, error:'not_logged_in'});
  }
  if (!/Listing|商品编码|产品|销售|ASIN/.test(text)) {
    return JSON.stringify({ok:false, error:'领星 Listing 页面未加载完成'});
  }
  return JSON.stringify({ok:true});
})()
"""
    raw = await chrome_execute_js(js, timeout=20)
    try:
        data = json.loads(raw or "{}")
    except json.JSONDecodeError:
        data = {"ok": False, "error": "无法读取领星页面状态"}
    if data.get("error") == "not_logged_in":
        return {"ok": False, "error": "领星未登录，无法查询 ASIN"}
    return data


def _parse_cookie(cookie: str) -> dict[str, str]:
    parsed = {}
    for part in cookie.split(";"):
        if "=" in part:
            key, value = part.split("=", 1)
            parsed[key.strip()] = unquote(value.strip())
    return parsed


async def _get_lingxing_listing_auth(store: str = DEFAULT_STORE) -> dict:
    async with chrome_workflow("asin_sync_auth"):
        opened = await chrome_navigate(LINGXING_LISTING_URL, wait=3)
        if not opened:
            return {"ok": False, "error": "无法打开领星 Listing 页面"}
        cookie = await chrome_get_cookie_for_domain("erp.lingxing.com")
        if not cookie:
            return {"ok": False, "error": "领星未登录，无法读取 Cookie"}
        page_ready = await _prepare_lingxing_listing()
        if not page_ready.get("ok"):
            return page_ready
        js = """
(function() {
  return JSON.stringify({
    ok: true,
    language: localStorage.getItem('language') || 'zh',
    loginEnv: sessionStorage.getItem('loginEnv') || '1',
    origin: location.origin
  });
})()
"""
        raw = await chrome_execute_js(js, timeout=20)
        try:
            data = json.loads(raw or "{}")
        except json.JSONDecodeError:
            data = {"ok": False, "error": "无法读取领星页面状态"}
        if not data.get("ok"):
            return data
        cookies = _parse_cookie(cookie)

    headers = {
        "Cookie": cookie,
        "X-AK-Language": data.get("language") or "zh",
        "X-AK-Request-Source": "erp",
        "X-AK-Zid": cookies.get("zid", ""),
        "X-AK-Version": "3.8.3.3.0.141",
        "X-AK-ENV-KEY": cookies.get("envKey", ""),
        "X-AK-PLATFORM": data.get("loginEnv") or "1",
        "AK-Client-Type": "web",
        "auth-token": cookies.get("authToken", ""),
        "X-AK-Uid": cookies.get("uid", ""),
        "X-AK-Company-Id": cookies.get("company_id", ""),
        "AK-Origin": data.get("origin") or "https://erp.lingxing.com",
        "Origin": "https://erp.lingxing.com",
        "Referer": "https://erp.lingxing.com/",
    }
    return {"ok": True, "headers": headers, "store_id": STORE_IDS.get(store, DEFAULT_STORE_ID)}


def _lookup_api_field(search_type: str) -> str:
    lookup_type = _normalize_lookup_type(search_type)
    if lookup_type == "商品编码":
        return "amz_product_id"
    if lookup_type == "MSKU":
        return "msku"
    if lookup_type == "ASIN":
        return "asin"
    return lookup_type


def _row_match_code(row: dict, api_field: str) -> str:
    if api_field == "amz_product_id":
        return str(row.get("amz_product_id") or "")
    if api_field == "msku":
        return str(row.get("msku") or "")
    if api_field == "asin":
        return str(row.get("asin") or "")
    return str(row.get(api_field) or "")


def _is_deleted_listing(row: dict) -> bool:
    status_text = str(row.get("status_text") or "").strip().lower()
    is_delete = str(row.get("is_delete") or "").strip().lower()
    return is_delete in {"1", "true", "yes"} or status_text in {"已删除", "deleted"}


def _listing_status_text(row: dict) -> str | None:
    for key in (
        "status_text",
        "statusText",
        "status_name",
        "statusName",
        "listing_status",
        "listingStatus",
        "sale_status",
        "saleStatus",
        "state",
    ):
        value = row.get(key)
        if value not in (None, ""):
            return str(value).strip()
    numeric_status = row.get("status")
    if str(numeric_status) == "0":
        return "停售"
    return None


async def _lookup_asin(
    code: str,
    store: str,
    search_type: str = "商品编码",
    auth: dict | None = None,
) -> dict:
    auth = auth or await _get_lingxing_listing_auth(store)
    if not auth.get("ok"):
        return {"status": "not_logged_in", "error": auth.get("error") or "领星未登录，无法查询 ASIN"}

    api_field = _lookup_api_field(search_type)
    payload = {
        "sids": str(auth.get("store_id") or STORE_IDS.get(store, DEFAULT_STORE_ID)),
        "search_field": api_field,
        "search_value": [code],
        "offset": 0,
        "length": 20,
    }
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(LINGXING_LISTING_API_URL, headers=auth["headers"], json=payload)
            response.raise_for_status()
            data = response.json()
    except Exception as exc:
        return {"status": "failed", "error": f"领星 API 查询失败: {type(exc).__name__}: {exc}"}

    if data.get("code") != 1:
        return {"status": "failed", "error": data.get("msg") or "领星 API 返回失败"}

    rows = ((data.get("data") or {}).get("list") or [])
    matched_rows = [
        row for row in rows
        if _normalize_code(_row_match_code(row, api_field)) == _normalize_code(code)
    ]
    if not matched_rows:
        return {"status": "not_found"}

    active_rows = [row for row in matched_rows if not _is_deleted_listing(row)]
    if not active_rows:
        return {
            "status": "not_found",
            "matched_count": len(matched_rows),
            "deleted_count": len(matched_rows),
            "error": "匹配到的 Listing 是删除状态，未写入 ASIN",
        }

    matched_asins = sorted({str(row.get("asin") or "").strip() for row in active_rows if row.get("asin")})
    if len(active_rows) > 1 or len(matched_asins) > 1:
        return {
            "status": "multiple_found",
            "matched_count": max(len(active_rows), len(matched_asins)),
            "error": "匹配到多个 Listing，请人工确认",
        }

    asin = matched_asins[0] if matched_asins else ""
    if not asin or not ASIN_RE.fullmatch(asin):
        return {"status": "not_found"}
    return {
        "status": "success",
        "asin": asin,
        "matched_code": _row_match_code(active_rows[0], api_field),
        "amazon_product_status": _listing_status_text(active_rows[0]),
    }


def build_sync_item(catalog: CatalogProduct) -> AsinSyncItem:
    product = catalog.source_product
    item_code = product.data.item_code if product and product.data else catalog.item_code
    asin = (catalog.amazon_asin or (product.amazon_asin if product else None) or "").strip()
    upc = (catalog.upc or (product.upc if product else None) or "").strip()
    lookup_code = (asin or upc or item_code or "").strip()
    lookup_type = "ASIN" if asin else ("商品编码" if upc else "MSKU")
    return AsinSyncItem(
        catalog_product_id=catalog.id,
        product_id=catalog.source_product_id,
        lookup_code=lookup_code or None,
        lookup_type=lookup_type,
        status="pending" if lookup_code else "skipped",
        error_message=None if lookup_code else "缺少 ASIN、UPC/商品编码或 SKU，无法查询",
    )
