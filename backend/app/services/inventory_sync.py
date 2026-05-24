"""GigaB2B inventory sync batches for catalog products."""

import asyncio
import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database import async_session
from app.models import CatalogProduct, InventorySyncBatch, InventorySyncItem, Product
from app.pipeline.chrome_ctrl import chrome_workflow
from app.pipeline.step1_collect import _collect_product_data_via_api, _parse_int

logger = logging.getLogger(__name__)

_running_batches: dict[int, asyncio.Task] = {}
GIGAB2B_LOGIN_REQUIRED_ERROR = "大建云仓未登录或登录态已失效，未创建库存同步批次；请先在 Chrome 登录大建云仓后重试。"
GIGAB2B_LOGIN_CHECK_SAMPLE_LIMIT = 3


class InventorySyncLoginRequired(RuntimeError):
    pass


def is_inventory_batch_running(batch_id: int) -> bool:
    task = _running_batches.get(batch_id)
    return task is not None and not task.done()


def start_inventory_sync_batch(batch_id: int) -> bool:
    if batch_id in _running_batches:
        return False
    task = asyncio.create_task(_run_batch(batch_id))
    _running_batches[batch_id] = task
    return True


def _gigab2b_source_from_catalog(catalog: CatalogProduct) -> tuple[str, str] | None:
    product = catalog.source_product
    product_url = catalog.gigab2b_url
    gigab2b_product_id = catalog.gigab2b_product_id or (product.gigab2b_product_id if product else None)
    if not product_url or not gigab2b_product_id:
        return None
    return product_url, gigab2b_product_id


def _looks_like_gigab2b_login_error(exc: Exception) -> bool:
    text = str(exc)
    return any(
        marker in text
        for marker in (
            "未能从 Chrome 读取 GigaB2B 登录 Cookie",
            "GigaB2B API 价格/库存不可见",
            "疑似登录态失效",
            "登录态失效",
            "未登录",
        )
    )


async def _assert_gigab2b_logged_in_for_sources(sources: list[tuple[str, str]]) -> None:
    last_non_auth_error: Exception | None = None
    for product_url, gigab2b_product_id in sources[:GIGAB2B_LOGIN_CHECK_SAMPLE_LIMIT]:
        try:
            data, _cookie = await _collect_product_data_via_api(gigab2b_product_id, product_url)
            if data.get("loginStatus") == "not_logged_in":
                raise InventorySyncLoginRequired(GIGAB2B_LOGIN_REQUIRED_ERROR)
            return
        except InventorySyncLoginRequired:
            raise
        except Exception as exc:
            if _looks_like_gigab2b_login_error(exc):
                raise InventorySyncLoginRequired(GIGAB2B_LOGIN_REQUIRED_ERROR) from exc
            last_non_auth_error = exc

    if last_non_auth_error:
        logger.warning("[Inventory Sync] 大建云仓登录预检未完成，继续逐项同步: %s", last_non_auth_error)


async def assert_gigab2b_logged_in_for_inventory(catalog_items: list[CatalogProduct], *, own_workflow: bool = True) -> None:
    sources = [source for catalog in catalog_items if (source := _gigab2b_source_from_catalog(catalog))]
    if not sources:
        return
    if own_workflow:
        async with chrome_workflow("inventory_sync_login_check"):
            await _assert_gigab2b_logged_in_for_sources(sources)
    else:
        await _assert_gigab2b_logged_in_for_sources(sources)


async def _update_batch_counts(db, batch: InventorySyncBatch) -> None:
    statuses = [item.status for item in batch.items]
    batch.success_count = statuses.count("success")
    batch.unavailable_count = statuses.count("unavailable")
    batch.failed_count = statuses.count("failed")
    batch.skipped_count = statuses.count("skipped")
    done = batch.success_count + batch.unavailable_count + batch.failed_count + batch.skipped_count
    if done >= batch.total_count:
        batch.status = "completed" if batch.failed_count == 0 else "partial"
        batch.finished_at = datetime.now()
    await db.commit()


async def _run_batch(batch_id: int) -> None:
    try:
        async with async_session() as db:
            result = await db.execute(
                select(InventorySyncBatch)
                .options(selectinload(InventorySyncBatch.items))
                .where(InventorySyncBatch.id == batch_id)
            )
            batch = result.scalar_one_or_none()
            if not batch:
                return
            batch.status = "running"
            batch.started_at = datetime.now()
            await db.commit()

        async with chrome_workflow(f"inventory_sync batch={batch_id}"):
            async with async_session() as db:
                result = await db.execute(
                    select(InventorySyncBatch)
                    .options(selectinload(InventorySyncBatch.items))
                    .where(InventorySyncBatch.id == batch_id)
                )
                batch = result.scalar_one()
                item_ids = [item.id for item in batch.items if item.status == "pending"]
                if not item_ids:
                    await _update_batch_counts(db, batch)
                    return
                catalog_ids = [item.catalog_product_id for item in batch.items if item.status == "pending"]
                catalog_result = await db.execute(
                    select(CatalogProduct)
                    .options(selectinload(CatalogProduct.source_product))
                    .where(CatalogProduct.id.in_(catalog_ids))
                )
                pending_catalogs = catalog_result.scalars().all()

            try:
                await assert_gigab2b_logged_in_for_inventory(pending_catalogs, own_workflow=False)
            except InventorySyncLoginRequired as exc:
                await _fail_whole_batch(batch_id, str(exc))
                return

            for item_id in item_ids:
                await _run_item(item_id)

        async with async_session() as db:
            result = await db.execute(
                select(InventorySyncBatch)
                .options(selectinload(InventorySyncBatch.items))
                .where(InventorySyncBatch.id == batch_id)
            )
            batch = result.scalar_one_or_none()
            if batch:
                await _update_batch_counts(db, batch)
    except Exception as exc:
        logger.exception("[Inventory Sync] Batch %s failed", batch_id)
        await _fail_whole_batch(batch_id, f"{type(exc).__name__}: {exc}")
    finally:
        _running_batches.pop(batch_id, None)


async def _fail_whole_batch(batch_id: int, error: str) -> None:
    async with async_session() as db:
        result = await db.execute(
            select(InventorySyncBatch)
            .options(selectinload(InventorySyncBatch.items))
            .where(InventorySyncBatch.id == batch_id)
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
                catalog = await db.get(CatalogProduct, item.catalog_product_id)
                if catalog:
                    catalog.stock_sync_status = "failed"
                    catalog.stock_sync_error = error
                    catalog.stock_synced_at = datetime.now()
                    catalog.updated_at = datetime.now()
        await _update_batch_counts(db, batch)


async def _run_item(item_id: int) -> None:
    async with async_session() as db:
        result = await db.execute(select(InventorySyncItem).where(InventorySyncItem.id == item_id))
        item = result.scalar_one_or_none()
        if not item:
            return
        item.status = "running"
        item.started_at = datetime.now()
        catalog = await db.get(CatalogProduct, item.catalog_product_id)
        if catalog:
            catalog.stock_sync_status = "running"
            catalog.stock_sync_error = None
            catalog.updated_at = datetime.now()
        await db.commit()
        product_url = catalog.gigab2b_url if catalog else None
        gigab2b_product_id = item.gigab2b_product_id or (catalog.gigab2b_product_id if catalog else None)

    if not product_url or not gigab2b_product_id:
        await _finish_item(item_id, "skipped", error="缺少大建云仓商品ID或链接，无法同步库存")
        return

    try:
        data, _cookie = await _collect_product_data_via_api(gigab2b_product_id, product_url)
        availability_status = data.get("availabilityStatus") or "available"
        stock = _parse_int(data.get("stock"))
        if availability_status == "offline":
            await _finish_item(
                item_id,
                "unavailable",
                new_stock=stock if stock is not None else 0,
                availability_status=availability_status,
                error=data.get("availabilityReason") or "大建云仓显示商品不可售",
            )
            return
        if stock is None:
            await _finish_item(item_id, "failed", availability_status=availability_status, error="大建云仓接口未返回库存")
            return
        await _finish_item(item_id, "success", new_stock=stock, availability_status=availability_status)
    except Exception as exc:
        await _finish_item(item_id, "failed", error=f"{type(exc).__name__}: {exc}")


async def _finish_item(
    item_id: int,
    status: str,
    *,
    new_stock: int | None = None,
    availability_status: str | None = None,
    error: str | None = None,
) -> None:
    async with async_session() as db:
        result = await db.execute(select(InventorySyncItem).where(InventorySyncItem.id == item_id))
        item = result.scalar_one_or_none()
        if not item:
            return
        item.status = status
        item.new_stock = new_stock
        item.availability_status = availability_status
        item.error_message = error
        item.finished_at = datetime.now()

        catalog = await db.get(CatalogProduct, item.catalog_product_id)
        if catalog:
            catalog.stock_sync_status = {
                "success": "synced",
                "unavailable": "unavailable",
                "failed": "failed",
                "skipped": "skipped",
            }.get(status, status)
            catalog.stock_sync_error = error
            catalog.stock_synced_at = datetime.now()
            catalog.updated_at = datetime.now()
            if status in {"success", "unavailable"} and new_stock is not None:
                catalog.stock = new_stock

        batch_result = await db.execute(
            select(InventorySyncBatch)
            .options(selectinload(InventorySyncBatch.items))
            .where(InventorySyncBatch.id == item.batch_id)
        )
        batch = batch_result.scalar_one_or_none()
        if batch:
            await _update_batch_counts(db, batch)
        else:
            await db.commit()


def build_inventory_sync_item(catalog: CatalogProduct) -> InventorySyncItem:
    product = catalog.source_product
    product_data = product.data if product and product.data else None
    gigab2b_product_id = catalog.gigab2b_product_id or (product.gigab2b_product_id if product else None)
    item_code = catalog.item_code or (product_data.item_code if product_data else None)
    missing_source = not (catalog.gigab2b_url and gigab2b_product_id)
    return InventorySyncItem(
        catalog_product_id=catalog.id,
        product_id=catalog.source_product_id,
        gigab2b_product_id=gigab2b_product_id,
        item_code=item_code,
        old_stock=catalog.stock,
        status="skipped" if missing_source else "pending",
        error_message="缺少大建云仓商品ID或链接，无法同步库存" if missing_source else None,
    )
