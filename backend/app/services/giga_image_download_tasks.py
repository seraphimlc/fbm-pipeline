import asyncio
import logging
from collections.abc import Awaitable, Callable

from sqlalchemy import func, select

from app.database import async_session
from app.models import GigaProductImage
from app.services.giga_image_assets import GigaImageCandidate, download_giga_product_images

logger = logging.getLogger(__name__)

_active_image_tasks: dict[str, asyncio.Task] = {}


ImageProgressCallback = Callable[[dict[str, int]], Awaitable[None]]


def _task_key(batch_id: str, site: str, data_source_id: int | None) -> str:
    return f"{site}:{data_source_id or 'legacy'}:{batch_id}"


async def _image_status_counts(batch_id: str, site: str, data_source_id: int | None = None) -> dict[str, int]:
    async with async_session() as db:
        base = [
            GigaProductImage.batch_id == batch_id,
            GigaProductImage.site == site,
        ]
        if data_source_id:
            base.append(GigaProductImage.data_source_id == data_source_id)
        total_result = await db.execute(select(func.count(GigaProductImage.id)).where(*base))
        done_result = await db.execute(
            select(func.count(GigaProductImage.id)).where(*base, GigaProductImage.download_status == "done")
        )
        failed_result = await db.execute(
            select(func.count(GigaProductImage.id)).where(*base, GigaProductImage.download_status == "failed")
        )
        pending_result = await db.execute(
            select(func.count(GigaProductImage.id)).where(*base, GigaProductImage.download_status == "pending")
        )
    return {
        "total": total_result.scalar() or 0,
        "done": done_result.scalar() or 0,
        "failed": failed_result.scalar() or 0,
        "pending": pending_result.scalar() or 0,
    }


async def download_giga_batch_images(
    batch_id: str,
    site: str,
    data_source_id: int | None = None,
    *,
    progress_callback: ImageProgressCallback | None = None,
    chunk_size: int = 200,
) -> dict[str, int]:
    initial_counts = await _image_status_counts(batch_id, site, data_source_id)
    if progress_callback:
        await progress_callback(initial_counts)

    async with async_session() as db:
        query = select(GigaProductImage).where(
            GigaProductImage.batch_id == batch_id,
            GigaProductImage.site == site,
            GigaProductImage.download_status.in_(("pending", "failed")),
        )
        if data_source_id:
            query = query.where(GigaProductImage.data_source_id == data_source_id)
        result = await db.execute(query.order_by(GigaProductImage.item_code.asc(), GigaProductImage.sort_order.asc()))
        rows = result.scalars().all()
        if not rows:
            return initial_counts

    for start in range(0, len(rows), max(chunk_size, 1)):
        chunk = rows[start:start + max(chunk_size, 1)]
        candidates = [
            GigaImageCandidate(
                sku_code=row.sku_code,
                item_code=row.item_code,
                image_url=row.image_url,
                image_type=row.image_type or "gallery",
                sort_order=row.sort_order or 0,
            )
            for row in chunk
            if row.image_url
        ]
        downloaded_rows = await download_giga_product_images(batch_id=batch_id, site=site, candidates=candidates)
        downloaded_by_key = {
            (row.sku_code, row.item_code, row.image_url): row
            for row in downloaded_rows
        }

        async with async_session() as db:
            result = await db.execute(select(GigaProductImage).where(GigaProductImage.id.in_([row.id for row in chunk])))
            db_rows = result.scalars().all()
            for row in db_rows:
                downloaded = downloaded_by_key.get((row.sku_code, row.item_code, row.image_url))
                if not downloaded:
                    continue
                row.local_path = downloaded.local_path
                row.content_hash = downloaded.content_hash
                row.file_size = downloaded.file_size
                row.mime_type = downloaded.mime_type
                row.download_status = downloaded.download_status
                row.error_message = downloaded.error_message
                row.pulled_at = downloaded.pulled_at
            await db.commit()

        counts = await _image_status_counts(batch_id, site, data_source_id)
        if progress_callback:
            await progress_callback(counts)
        logger.info(
            "[GIGA Image] batch image download progress: batch=%s site=%s data_source_id=%s done=%s failed=%s pending=%s total=%s",
            batch_id,
            site,
            data_source_id,
            counts["done"],
            counts["failed"],
            counts["pending"],
            counts["total"],
        )

    final_counts = await _image_status_counts(batch_id, site, data_source_id)
    logger.info(
        "[GIGA Image] batch image download finished: batch=%s site=%s data_source_id=%s done=%s failed=%s total=%s",
        batch_id,
        site,
        data_source_id,
        final_counts["done"],
        final_counts["failed"],
        final_counts["total"],
    )
    return final_counts


def schedule_giga_image_download(batch_id: str, site: str, data_source_id: int | None = None) -> bool:
    key = _task_key(batch_id, site, data_source_id)
    existing = _active_image_tasks.get(key)
    if existing and not existing.done():
        return False

    async def runner() -> None:
        try:
            await download_giga_batch_images(batch_id, site, data_source_id)
        except Exception:
            logger.exception(
                "[GIGA Image] batch image download failed: batch=%s site=%s data_source_id=%s",
                batch_id,
                site,
                data_source_id,
            )
        finally:
            _active_image_tasks.pop(key, None)

    _active_image_tasks[key] = asyncio.create_task(runner())
    return True


async def cancel_active_giga_image_downloads() -> None:
    tasks = [task for task in _active_image_tasks.values() if not task.done()]
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    _active_image_tasks.clear()
