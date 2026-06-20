import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select

from app.database import async_session
from app.models import GigaSyncBatch
from app.services.giga_openapi import (
    GigaOpenApiError,
    GigaSyncOptions,
    resolve_giga_data_source_context,
    sync_giga_products,
)
from app.services.giga_product_drafts import upsert_product_drafts_from_giga_batch

logger = logging.getLogger(__name__)

_active_sync_tasks: dict[str, asyncio.Task] = {}


@dataclass(frozen=True)
class GigaSyncQueuedResult:
    batch_id: str
    site: str
    data_source_id: int | None
    data_source_name: str | None
    status: str
    started: bool


def _task_key(batch_id: str, site: str, data_source_id: int | None) -> str:
    return f"{site}:{data_source_id or 'legacy'}:{batch_id}"


async def _ensure_pending_batch(options: GigaSyncOptions) -> GigaSyncQueuedResult:
    async with async_session() as db:
        context = await resolve_giga_data_source_context(db, options.data_source_id, options.site)
        site = context.site.strip().upper()
        batch_id = options.batch_id.strip()
        if not batch_id:
            raise GigaOpenApiError("缺少 batch_id")
        result = await db.execute(
            select(GigaSyncBatch).where(
                GigaSyncBatch.batch_id == batch_id,
                GigaSyncBatch.site == site,
                GigaSyncBatch.data_source_id == context.id,
            )
        )
        batch = result.scalar_one_or_none()
        if not batch:
            batch = GigaSyncBatch(batch_id=batch_id, site=site)
            db.add(batch)
        if batch.status == "running":
            return GigaSyncQueuedResult(
                batch_id=batch_id,
                site=site,
                data_source_id=context.id,
                data_source_name=context.name,
                status=batch.status,
                started=False,
            )
        now = datetime.now()
        batch.task_id = options.task_id
        batch.data_source_id = context.id
        batch.data_source_name = context.name
        batch.fulfillment_mode = context.fulfillment_mode
        batch.current_category = options.current_category
        batch.status = "pending"
        batch.error_message = None
        batch.started_at = None
        batch.finished_at = None
        batch.updated_at = now
        await db.commit()
        return GigaSyncQueuedResult(
            batch_id=batch_id,
            site=site,
            data_source_id=context.id,
            data_source_name=context.name,
            status="pending",
            started=True,
        )


async def _execute_giga_sync(options: GigaSyncOptions) -> None:
    try:
        async with async_session() as db:
            result = await sync_giga_products(db, options)
        async with async_session() as db:
            draft_result = await upsert_product_drafts_from_giga_batch(
                db,
                batch_id=result.batch_id,
                site=result.site,
                data_source_id=result.data_source_id,
            )
        logger.info(
            "[GIGA Sync] background sync finished: batch=%s site=%s data_source_id=%s sku=%s item=%s product_created=%s product_updated=%s",
            result.batch_id,
            result.site,
            result.data_source_id,
            result.sku_count,
            result.item_count,
            draft_result.created,
            draft_result.updated,
        )
    except Exception:
        logger.exception(
            "[GIGA Sync] background sync failed: batch=%s site=%s data_source_id=%s",
            options.batch_id,
            options.site,
            options.data_source_id,
        )


async def enqueue_giga_sync(options: GigaSyncOptions) -> GigaSyncQueuedResult:
    queued = await _ensure_pending_batch(options)
    key = _task_key(queued.batch_id, queued.site, queued.data_source_id)
    existing = _active_sync_tasks.get(key)
    if existing and not existing.done():
        return GigaSyncQueuedResult(
            batch_id=queued.batch_id,
            site=queued.site,
            data_source_id=queued.data_source_id,
            data_source_name=queued.data_source_name,
            status="running",
            started=False,
        )

    run_options = GigaSyncOptions(
        batch_id=queued.batch_id,
        site=queued.site,
        data_source_id=queued.data_source_id,
        task_id=options.task_id,
        current_category=options.current_category,
        page_size=options.page_size,
        max_pages=options.max_pages,
        skip_existing=options.skip_existing,
        download_images=False,
    )

    async def runner() -> None:
        try:
            await _execute_giga_sync(run_options)
        finally:
            _active_sync_tasks.pop(key, None)

    _active_sync_tasks[key] = asyncio.create_task(runner())
    return queued


async def cancel_active_giga_sync_tasks() -> None:
    tasks = [task for task in _active_sync_tasks.values() if not task.done()]
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    _active_sync_tasks.clear()
