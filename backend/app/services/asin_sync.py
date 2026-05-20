"""ASIN sync batches backed by Lingxing Listing lookup."""

import asyncio
import json
import logging
import re
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database import async_session
from app.models import AsinSyncBatch, AsinSyncItem, CatalogProduct, Product
from app.pipeline.chrome_ctrl import chrome_execute_js, chrome_navigate, chrome_workflow

logger = logging.getLogger(__name__)

DEFAULT_STORE = "Andy店-US"
LINGXING_LISTING_URL = "https://erp.lingxing.com/erp/listing"
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


def _looks_like_upc(value: str | None) -> bool:
    return bool(value and re.fullmatch(r"\d{8,14}", value.strip()))


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

        async with chrome_workflow(f"asin_sync batch={batch_id}"):
            page_ready = await _prepare_lingxing_listing()
            if not page_ready.get("ok"):
                await _fail_whole_batch(batch_id, page_ready.get("error") or "领星 Listing 页面不可用")
                return

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

            for item_id in item_ids:
                await _run_item(item_id, store)

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


async def _run_item(item_id: int, store: str) -> None:
    async with async_session() as db:
        result = await db.execute(select(AsinSyncItem).where(AsinSyncItem.id == item_id))
        item = result.scalar_one_or_none()
        if not item:
            return
        item.status = "running"
        item.started_at = datetime.now()
        await db.commit()
        lookup_code = item.lookup_code
        lookup_type = item.lookup_type or "商品编码"

    if not lookup_code:
        await _finish_item(item_id, "skipped", error="缺少 UPC 或商品编码，无法查询")
        return

    try:
        lookup = await _lookup_asin(lookup_code, store)
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
        if not asin or _normalize_code(matched_code) != _normalize_code(lookup_code):
            await _finish_item(item_id, "failed", error="查询结果未通过商品编码校验")
            return
        await _finish_item(item_id, "success", asin=asin, matched_code=matched_code)
    except Exception as exc:
        await _finish_item(item_id, "failed", error=f"{type(exc).__name__}: {exc}")


async def _finish_item(
    item_id: int,
    status: str,
    asin: str | None = None,
    matched_code: str | None = None,
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
            if asin:
                target.amazon_asin = asin
                target.asin_synced_at = datetime.now()
            elif status in {"not_found", "multiple_found", "failed", "skipped"}:
                target.asin_synced_at = datetime.now()

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


async def _lookup_asin(code: str, store: str) -> dict:
    search_js = f"""
(function() {{
  const targetCode = {json.dumps(code)};
  const norm = (value) => String(value || '').replace(/\\s+/g, '').toUpperCase();
  const visible = (el) => {{
    const rect = el.getBoundingClientRect();
    const style = window.getComputedStyle(el);
    return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
  }};
  const text = () => document.body ? document.body.innerText : '';
  if (/登录|login/i.test(text()) && !/Listing|商品编码|产品|销售/.test(text())) {{
    return JSON.stringify({{status:'not_logged_in'}});
  }}
  const clickByText = (needle) => {{
    const nodes = Array.from(document.querySelectorAll('button,span,div,input,[role=button]')).filter(visible);
    const found = nodes.find(el => norm(el.innerText || el.value || el.getAttribute('title')).includes(norm(needle)));
    if (found) {{
      found.click();
      return true;
    }}
    return false;
  }};
  clickByText('商品编码');

  const inputs = Array.from(document.querySelectorAll('input')).filter(visible);
  const searchInput = inputs.reverse().find(el => !/date|time|checkbox|radio/.test(el.type || '')) || inputs[0];
  if (!searchInput) {{
    return JSON.stringify({{status:'failed', error:'未找到搜索输入框'}});
  }}
  searchInput.focus();
  searchInput.value = targetCode;
  searchInput.dispatchEvent(new Event('input', {{bubbles:true}}));
  searchInput.dispatchEvent(new Event('change', {{bubbles:true}}));
  searchInput.dispatchEvent(new KeyboardEvent('keydown', {{key:'Enter', code:'Enter', bubbles:true}}));
  searchInput.dispatchEvent(new KeyboardEvent('keyup', {{key:'Enter', code:'Enter', bubbles:true}}));
  const searchButton = Array.from(document.querySelectorAll('button')).filter(visible).find(el => /搜索|查询/.test(el.innerText || ''));
  if (searchButton) searchButton.click();
  return JSON.stringify({{status:'search_triggered'}});
}})()
"""
    raw = await chrome_execute_js(search_js, timeout=20)
    try:
        initial = json.loads(raw or "{}")
    except json.JSONDecodeError:
        initial = {"status": "failed", "error": "领星搜索触发失败"}
    if initial.get("status") in {"not_logged_in", "failed"}:
        return initial

    await asyncio.sleep(3.5)

    extract_js = f"""
(function() {{
  const targetCode = {json.dumps(code)};
  const norm = (value) => String(value || '').replace(/\\s+/g, '').toUpperCase();
  const visible = (el) => {{
    const rect = el.getBoundingClientRect();
    const style = window.getComputedStyle(el);
    return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
  }};
  const cleanText = (value) => String(value || '').replace(/\\s+/g, ' ').trim();
  const hasDeletedStatusText = (value) => /(?:商品状态|Listing状态|listing状态|刊登状态|销售状态|状态)\\s*[:：]?\\s*(已删除|删除|DELETED)(?:\\s|$|[，,。；;|/])/i.test(value || '');
  const isInteractiveDelete = (el) => {{
    const interactive = el.matches('a,button,[role=button]')
      ? el
      : (el.querySelector('a,button,[role=button]') || el.closest('a,button,[role=button]'));
    if (!interactive) return false;
    return /^删除$/i.test(cleanText(interactive.innerText || interactive.value || interactive.getAttribute('title')));
  }};
  const isDeletedListing = (linkedRows, combinedText) => {{
    if (hasDeletedStatusText(combinedText)) return true;
    const statusNodes = linkedRows.flatMap(row => Array.from(row.querySelectorAll('td,.ant-table-cell,[role=cell],.ant-tag,.ant-badge-status-text'))).filter(visible);
    return statusNodes.some(el => {{
      const value = cleanText(el.innerText || el.textContent || '');
      if (/^(已删除|DELETED)$/i.test(value)) return true;
      return /^删除$/i.test(value) && !isInteractiveDelete(el);
    }});
  }};
  const text = () => document.body ? document.body.innerText : '';
  if (/登录|login/i.test(text()) && !/Listing|商品编码|产品|销售/.test(text())) {{
    return JSON.stringify({{status:'not_logged_in'}});
  }}
  const bodyText = text();
  if (/暂无数据|无数据|没有数据|No Data|no data/i.test(bodyText) && !bodyText.includes(targetCode)) {{
    return JSON.stringify({{status:'not_found'}});
  }}

  const rows = Array.from(document.querySelectorAll('tr,.ant-table-row,[role=row]')).filter(visible);
  const matches = [];
  for (const row of rows) {{
    const rowText = row.innerText || '';
    if (norm(rowText).includes(norm(targetCode))) {{
      const rowId = row.getAttribute('rowid') || row.getAttribute('data-rowid');
      const linkedRows = rowId
        ? rows.filter(candidate => (candidate.getAttribute('rowid') || candidate.getAttribute('data-rowid')) === rowId)
        : [row, row.nextElementSibling].filter(candidate => candidate && visible(candidate));
      const combined = linkedRows.map(candidate => candidate.innerText || '').join('\\n');
      if (combined && !matches.some(match => match.text === combined)) {{
        matches.push({{
          text: combined,
          deleted: isDeletedListing(linkedRows, combined)
        }});
      }}
    }}
  }}
  if (!matches.length) {{
    if (!norm(bodyText).includes(norm(targetCode))) return JSON.stringify({{status:'not_found'}});
    matches.push({{text: bodyText, deleted: hasDeletedStatusText(bodyText)}});
  }}

  const activeMatches = matches.filter(match => !match.deleted);
  if (!activeMatches.length) {{
    return JSON.stringify({{
      status:'not_found',
      matched_count: matches.length,
      deleted_count: matches.filter(match => match.deleted).length,
      error:'匹配到的 Listing 是删除状态，未写入 ASIN'
    }});
  }}

  const matchedAsins = Array.from(new Set(activeMatches.flatMap(match => match.text.match(/\\bB[A-Z0-9]{{9}}\\b/g) || [])));
  if (activeMatches.length > 1 || matchedAsins.length > 1) {{
    return JSON.stringify({{
      status:'multiple_found',
      matched_count: Math.max(activeMatches.length, matchedAsins.length),
      error:'匹配到多个 Listing，请人工确认'
    }});
  }}

  const matchedText = activeMatches[0].text || '';
  const asinMatch = matchedText.match(/\\bB[A-Z0-9]{{9}}\\b/);
  if (!asinMatch) {{
    return JSON.stringify({{status:'not_found'}});
  }}
  return JSON.stringify({{
    status:'success',
    asin: asinMatch[0],
    matched_code: targetCode
  }});
}})()
"""
    raw = await chrome_execute_js(extract_js, timeout=20)
    try:
        data = json.loads(raw or "{}")
    except json.JSONDecodeError:
        data = {"status": "failed", "error": "领星查询结果解析失败"}
    if data.get("status") == "success":
        asin = data.get("asin")
        if not asin or not ASIN_RE.fullmatch(asin):
            return {"status": "failed", "error": "ASIN 格式无效"}
    return data


def build_sync_item(catalog: CatalogProduct) -> AsinSyncItem:
    product = catalog.source_product
    item_code = product.data.item_code if product and product.data else catalog.item_code
    lookup_code = (catalog.upc or (product.upc if product else None) or item_code or "").strip()
    lookup_type = "UPC" if _looks_like_upc(lookup_code) else "商品编码"
    return AsinSyncItem(
        catalog_product_id=catalog.id,
        product_id=catalog.source_product_id,
        lookup_code=lookup_code or None,
        lookup_type=lookup_type,
        status="pending" if lookup_code else "skipped",
        error_message=None if lookup_code else "缺少 UPC 或商品编码，无法查询",
    )
