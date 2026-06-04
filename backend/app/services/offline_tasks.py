import asyncio
import json
import logging
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import OfflineTaskGigaDynamicSyncRequest, OfflineTaskGigaPullRequest
from app.database import async_session
from app.models import OfflineTask, OfflineTaskStep, ProductDataSource
from app.services.giga_inventory_sync import GigaInventorySyncOptions, sync_giga_inventory_snapshot
from app.services.giga_image_download_tasks import download_giga_batch_images
from app.services.giga_openapi import GigaSyncOptions, resolve_giga_data_source_context, sync_giga_products
from app.services.giga_price_sync import GigaPriceSyncOptions, sync_giga_price_snapshot
from app.services.stylesnap_product_tasks import upsert_product_drafts_from_giga_batch

logger = logging.getLogger(__name__)

_active_offline_tasks: dict[int, asyncio.Task] = {}

TASK_STATUS_ACTIVE = {"pending", "running"}
STEP_STATUS_SUCCESS = "done"
STEP_STATUS_FAILURES = {"failed", "interrupted"}
STEP_STATUS_RESUMABLE = {"pending", "running", "paused", "interrupted"}
SUPPORTED_TASK_TYPES = {"giga_pull", "giga_inventory_sync", "giga_price_sync"}


def _json_dumps(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


async def _refresh_task_stats(db: AsyncSession, task_id: int) -> OfflineTask | None:
    task = await db.get(OfflineTask, task_id)
    if not task:
        return None
    result = await db.execute(select(OfflineTaskStep).where(OfflineTaskStep.task_id == task_id))
    steps = result.scalars().all()
    total = len(steps)
    success = sum(1 for step in steps if step.status == STEP_STATUS_SUCCESS)
    failed = sum(1 for step in steps if step.status in STEP_STATUS_FAILURES)
    running = sum(1 for step in steps if step.status == "running")
    pending = sum(1 for step in steps if step.status == "pending")
    paused = sum(1 for step in steps if step.status == "paused")
    task.total_steps = total
    task.success_steps = success
    task.failed_steps = failed
    task.running_steps = running
    now = datetime.now()
    task.updated_at = now
    if paused or task.status == "paused":
        task.status = "paused"
        task.finished_at = None
    elif running:
        task.status = "running"
        task.started_at = task.started_at or now
        task.finished_at = None
    elif pending:
        task.status = "pending" if not task.started_at else "running"
        task.finished_at = None
    elif total and success == total:
        task.status = "done"
        task.finished_at = task.finished_at or now
    elif failed and success:
        task.status = "partial_failed"
        task.finished_at = task.finished_at or now
    elif failed:
        task.status = "failed"
        task.finished_at = task.finished_at or now
    else:
        task.status = "pending"
        task.finished_at = None
    return task


async def _set_step_status(
    db: AsyncSession,
    step: OfflineTaskStep,
    status: str,
    *,
    result: dict | None = None,
    error: str | None = None,
    progress_current: int | None = None,
    progress_total: int | None = None,
) -> None:
    now = datetime.now()
    step.status = status
    step.updated_at = now
    if status == "running":
        step.started_at = step.started_at or now
        step.finished_at = None
        step.error_message = None
    if status in {"done", "failed", "interrupted"}:
        step.finished_at = now
    if result is not None:
        step.result_json = _json_dumps(result)
    if error is not None:
        step.error_message = error
    if progress_current is not None:
        step.progress_current = progress_current
    if progress_total is not None:
        step.progress_total = progress_total
    await _refresh_task_stats(db, step.task_id)
    await db.commit()


async def _ensure_image_step(db: AsyncSession, sync_step: OfflineTaskStep) -> OfflineTaskStep:
    result = await db.execute(
        select(OfflineTaskStep).where(
            OfflineTaskStep.task_id == sync_step.task_id,
            OfflineTaskStep.step_type == "giga_image_download",
            OfflineTaskStep.batch_id == sync_step.batch_id,
            OfflineTaskStep.data_source_id == sync_step.data_source_id,
        )
    )
    existing = result.scalar_one_or_none()
    if existing:
        existing.status = "pending" if existing.status in STEP_STATUS_FAILURES else existing.status
        existing.error_message = None if existing.status == "pending" else existing.error_message
        existing.updated_at = datetime.now()
        await db.commit()
        return existing

    step = OfflineTaskStep(
        task_id=sync_step.task_id,
        step_type="giga_image_download",
        title=f"下载图片：{sync_step.data_source_name or sync_step.data_source_id}",
        status="pending",
        data_source_id=sync_step.data_source_id,
        data_source_name=sync_step.data_source_name,
        site=sync_step.site,
        batch_id=sync_step.batch_id,
        progress_current=0,
        progress_total=0,
        payload_json=_json_dumps({"batch_id": sync_step.batch_id, "site": sync_step.site}),
        updated_at=datetime.now(),
    )
    db.add(step)
    await _refresh_task_stats(db, sync_step.task_id)
    await db.commit()
    await db.refresh(step)
    return step


async def _run_image_step(db: AsyncSession, step: OfflineTaskStep) -> None:
    await _set_step_status(db, step, "running")

    async def update_progress(counts: dict[str, int]) -> None:
        await db.refresh(step)
        task = await db.get(OfflineTask, step.task_id)
        if task and task.status == "paused":
            raise asyncio.CancelledError()
        step.progress_current = counts.get("done", 0)
        step.progress_total = counts.get("total", 0)
        pending = counts.get("pending", 0)
        failed = counts.get("failed", 0)
        step.result_json = _json_dumps(counts)
        step.error_message = f"图片下载中：待下载 {pending}，失败 {failed}" if pending or failed else None
        step.updated_at = datetime.now()
        await _refresh_task_stats(db, step.task_id)
        await db.commit()

    try:
        result = await download_giga_batch_images(
            batch_id=step.batch_id or "",
            site=step.site or "US",
            data_source_id=step.data_source_id,
            progress_callback=update_progress,
        )
        await upsert_product_drafts_from_giga_batch(
            db,
            batch_id=step.batch_id or "",
            site=step.site or "US",
            data_source_id=step.data_source_id,
        )
        await _set_step_status(
            db,
            step,
            "done" if result.get("failed", 0) == 0 else "failed",
            result=result,
            error=None if result.get("failed", 0) == 0 else f"{result.get('failed', 0)} 张图片下载失败",
            progress_current=result.get("done", 0),
            progress_total=result.get("total", 0),
        )
    except Exception as exc:
        await db.rollback()
        await _set_step_status(db, step, "failed", error=f"{type(exc).__name__}: {exc}")


async def _run_sync_step(db: AsyncSession, step: OfflineTaskStep) -> None:
    await _set_step_status(db, step, "running")
    payload = json.loads(step.payload_json or "{}")
    try:
        result = await sync_giga_products(
            db,
            GigaSyncOptions(
                task_id=f"offline-task-{step.task_id}-step-{step.id}",
                batch_id=step.batch_id or "",
                site=step.site or "US",
                data_source_id=step.data_source_id,
                current_category=payload.get("current_category"),
                page_size=payload.get("page_size") or 200,
                max_pages=payload.get("max_pages"),
                skip_existing=True,
                download_images=False,
            ),
        )
        draft_result = await upsert_product_drafts_from_giga_batch(
            db,
            batch_id=result.batch_id,
            site=result.site,
            data_source_id=result.data_source_id,
        )
        await _set_step_status(
            db,
            step,
            "done",
            result={**result.__dict__, "product_drafts": draft_result.__dict__},
            progress_current=result.sku_count,
            progress_total=result.sku_count,
        )
    except Exception as exc:
        await db.rollback()
        logger.exception("[OfflineTask] GIGA pull step failed: task=%s step=%s", step.task_id, step.id)
        await _set_step_status(db, step, "failed", error=f"{type(exc).__name__}: {exc}")


async def _run_inventory_sync_step(db: AsyncSession, step: OfflineTaskStep) -> None:
    await _set_step_status(db, step, "running")
    payload = json.loads(step.payload_json or "{}")
    try:
        result = await sync_giga_inventory_snapshot(
            db,
            GigaInventorySyncOptions(
                task_id=f"offline-task-{step.task_id}-step-{step.id}",
                batch_id=step.batch_id or "",
                site=step.site or "US",
                data_source_id=step.data_source_id or 0,
                sku_codes=payload.get("sku_codes") or [],
            ),
        )
        await _set_step_status(
            db,
            step,
            "done" if result.failed_count == 0 else "failed",
            result=result.__dict__,
            error=None if result.failed_count == 0 else f"{result.failed_count} 个 SKU 库存同步失败",
            progress_current=result.success_count,
            progress_total=result.total_skus,
        )
    except Exception as exc:
        await db.rollback()
        logger.exception("[OfflineTask] GIGA inventory sync step failed: task=%s step=%s", step.task_id, step.id)
        await _set_step_status(db, step, "failed", error=f"{type(exc).__name__}: {exc}")


async def _run_price_sync_step(db: AsyncSession, step: OfflineTaskStep) -> None:
    await _set_step_status(db, step, "running")
    payload = json.loads(step.payload_json or "{}")
    try:
        result = await sync_giga_price_snapshot(
            db,
            GigaPriceSyncOptions(
                task_id=f"offline-task-{step.task_id}-step-{step.id}",
                batch_id=step.batch_id or "",
                site=step.site or "US",
                data_source_id=step.data_source_id or 0,
                sku_codes=payload.get("sku_codes") or [],
            ),
        )
        await _set_step_status(
            db,
            step,
            "done" if result.failed_count == 0 else "failed",
            result=result.__dict__,
            error=None if result.failed_count == 0 else f"{result.failed_count} 个 SKU 价格同步失败",
            progress_current=result.success_count,
            progress_total=result.total_skus,
        )
    except Exception as exc:
        await db.rollback()
        logger.exception("[OfflineTask] GIGA price sync step failed: task=%s step=%s", step.task_id, step.id)
        await _set_step_status(db, step, "failed", error=f"{type(exc).__name__}: {exc}")


async def _execute_offline_task(task_id: int, step_ids: list[int] | None = None) -> None:
    try:
        async with async_session() as db:
            query = select(OfflineTaskStep).where(OfflineTaskStep.task_id == task_id)
            if step_ids:
                query = query.where(OfflineTaskStep.id.in_(step_ids))
            else:
                query = query.where(OfflineTaskStep.status == "pending")
            result = await db.execute(query.order_by(OfflineTaskStep.id.asc()))
            steps = result.scalars().all()
            task = await db.get(OfflineTask, task_id)
            if task and task.status == "paused":
                return
            if task:
                task.status = "running"
                task.started_at = task.started_at or datetime.now()
                task.updated_at = datetime.now()
                await db.commit()
            for step in steps:
                await db.refresh(step)
                task = await db.get(OfflineTask, task_id)
                if task and task.status == "paused":
                    break
                if step.step_type == "giga_sync":
                    await _run_sync_step(db, step)
                elif step.step_type == "giga_image_download":
                    await _run_image_step(db, step)
                elif step.step_type == "giga_inventory_sync":
                    await _run_inventory_sync_step(db, step)
                elif step.step_type == "giga_price_sync":
                    await _run_price_sync_step(db, step)
            await _refresh_task_stats(db, task_id)
            await db.commit()
    finally:
        _active_offline_tasks.pop(task_id, None)


def _schedule_offline_task(task_id: int, step_ids: list[int] | None = None) -> None:
    existing = _active_offline_tasks.get(task_id)
    if existing and not existing.done():
        return
    _active_offline_tasks[task_id] = asyncio.create_task(_execute_offline_task(task_id, step_ids))


async def _cancel_active_offline_task(task_id: int) -> None:
    active = _active_offline_tasks.get(task_id)
    if not active or active.done():
        _active_offline_tasks.pop(task_id, None)
        return
    active.cancel()
    try:
        await asyncio.wait_for(active, timeout=5)
    except asyncio.CancelledError:
        pass
    except TimeoutError:
        logger.warning("[OfflineTask] task=%s did not stop within pause timeout", task_id)
    except Exception:
        logger.exception("[OfflineTask] task=%s stopped with error while pausing", task_id)


async def _load_task_detail(db: AsyncSession, task_id: int) -> OfflineTask:
    task = await db.get(OfflineTask, task_id)
    if not task:
        raise ValueError("任务不存在")
    if task.task_type not in SUPPORTED_TASK_TYPES:
        raise ValueError("当前任务类型暂不支持控制")
    return task


async def pause_offline_task(db: AsyncSession, task_id: int) -> OfflineTask:
    task = await _load_task_detail(db, task_id)
    if task.status in {"done", "failed", "partial_failed"}:
        raise ValueError(f"任务已结束，不能挂起，当前状态: {task.status}")
    if task.status == "paused":
        return task

    await _cancel_active_offline_task(task_id)
    result = await db.execute(
        select(OfflineTaskStep).where(
            OfflineTaskStep.task_id == task_id,
            OfflineTaskStep.status.in_(("pending", "running")),
        )
    )
    steps = result.scalars().all()
    now = datetime.now()
    for step in steps:
        step.status = "paused"
        step.error_message = "任务已挂起，恢复后继续执行。"
        step.finished_at = None
        step.updated_at = now
    task.status = "paused"
    task.error_message = "任务已挂起，恢复后会继续未完成步骤。"
    task.running_steps = 0
    task.finished_at = None
    task.updated_at = now
    await db.commit()
    await db.refresh(task)
    return task


async def resume_offline_task(db: AsyncSession, task_id: int) -> OfflineTask:
    task = await _load_task_detail(db, task_id)
    if task.status != "paused":
        raise ValueError(f"只能恢复已挂起任务，当前状态: {task.status}")

    result = await db.execute(
        select(OfflineTaskStep).where(
            OfflineTaskStep.task_id == task_id,
            OfflineTaskStep.status == "paused",
        )
    )
    steps = result.scalars().all()
    if not steps:
        raise ValueError("没有可恢复的挂起步骤")

    now = datetime.now()
    for step in steps:
        step.status = "pending"
        step.error_message = None
        step.finished_at = None
        step.updated_at = now
    task.status = "pending"
    task.error_message = None
    task.finished_at = None
    task.updated_at = now
    await _refresh_task_stats(db, task_id)
    await db.commit()
    _schedule_offline_task(task_id, [step.id for step in steps])
    await db.refresh(task)
    return task


async def _load_enabled_sources(db: AsyncSession, data_source_ids: list[int]) -> tuple[list[int], list[ProductDataSource]]:
    deduped_ids = list(dict.fromkeys(data_source_ids))
    result = await db.execute(
        select(ProductDataSource)
        .where(ProductDataSource.id.in_(deduped_ids), ProductDataSource.enabled == 1)
        .order_by(ProductDataSource.id.asc())
    )
    sources = result.scalars().all()
    found_ids = {source.id for source in sources}
    missing_ids = [source_id for source_id in deduped_ids if source_id not in found_ids]
    if missing_ids:
        raise ValueError(f"店铺不存在或未启用: {', '.join(map(str, missing_ids))}")
    return deduped_ids, sources


async def create_giga_pull_task(db: AsyncSession, body: OfflineTaskGigaPullRequest) -> OfflineTask:
    data_source_ids, sources = await _load_enabled_sources(db, body.data_source_ids)

    task = OfflineTask(
        task_type="giga_pull",
        title=f"同步店铺商品（{len(sources)} 个店铺）",
        status="pending",
        total_steps=len(sources),
        success_steps=0,
        failed_steps=0,
        running_steps=0,
        payload_json=_json_dumps({
            "data_source_ids": data_source_ids,
            "current_category": body.current_category,
            "page_size": body.page_size,
            "max_pages": body.max_pages,
        }),
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    db.add(task)
    await db.flush()
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    for source in sources:
        context = await resolve_giga_data_source_context(db, source.id, source.site)
        batch_id = f"workbench-giga-t{task.id}-ds{source.id}-{timestamp}"
        db.add(
            OfflineTaskStep(
                task_id=task.id,
                step_type="giga_sync",
                title=f"同步商品：{context.name}",
                status="pending",
                data_source_id=context.id,
                data_source_name=context.name,
                site=context.site,
                batch_id=batch_id,
                progress_current=0,
                progress_total=0,
                payload_json=_json_dumps({
                    "batch_id": batch_id,
                    "site": context.site,
                    "data_source_id": context.id,
                    "current_category": body.current_category,
                    "page_size": body.page_size,
                    "max_pages": body.max_pages,
                    "skip_existing": True,
                }),
                updated_at=datetime.now(),
            )
        )
    await db.commit()
    await db.refresh(task)
    _schedule_offline_task(task.id)
    return task


async def create_giga_dynamic_sync_task(
    db: AsyncSession,
    body: OfflineTaskGigaDynamicSyncRequest,
    *,
    kind: str,
) -> OfflineTask:
    if kind not in {"inventory", "price"}:
        raise ValueError(f"不支持的同步类型: {kind}")
    data_source_ids, sources = await _load_enabled_sources(db, body.data_source_ids)
    sku_codes = list(dict.fromkeys(str(sku).strip() for sku in (body.sku_codes or []) if str(sku or "").strip()))
    is_inventory = kind == "inventory"
    task_type = "giga_inventory_sync" if is_inventory else "giga_price_sync"
    step_type = task_type
    title_prefix = "同步大健库存" if is_inventory else "同步大健价格"
    step_prefix = "库存同步" if is_inventory else "价格同步"

    task = OfflineTask(
        task_type=task_type,
        title=f"{title_prefix}（{len(sources)} 个店铺）",
        status="pending",
        total_steps=len(sources),
        success_steps=0,
        failed_steps=0,
        running_steps=0,
        payload_json=_json_dumps({
            "data_source_ids": data_source_ids,
            "sku_codes": sku_codes,
        }),
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    db.add(task)
    await db.flush()

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    for source in sources:
        context = await resolve_giga_data_source_context(db, source.id, source.site)
        batch_kind = "inventory" if is_inventory else "price"
        batch_id = f"giga-{batch_kind}-t{task.id}-ds{context.id}-{timestamp}"
        db.add(
            OfflineTaskStep(
                task_id=task.id,
                step_type=step_type,
                title=f"{step_prefix}：{context.name}",
                status="pending",
                data_source_id=context.id,
                data_source_name=context.name,
                site=context.site,
                batch_id=batch_id,
                progress_current=0,
                progress_total=0,
                payload_json=_json_dumps({
                    "batch_id": batch_id,
                    "site": context.site,
                    "data_source_id": context.id,
                    "sku_codes": sku_codes,
                }),
                updated_at=datetime.now(),
            )
        )
    await db.commit()
    await db.refresh(task)
    _schedule_offline_task(task.id)
    return task


async def rerun_offline_task(db: AsyncSession, task_id: int) -> OfflineTask:
    task = await db.get(OfflineTask, task_id)
    if not task:
        raise ValueError("任务不存在")
    if task.task_type not in SUPPORTED_TASK_TYPES:
        raise ValueError("当前任务类型暂不支持重跑")
    result = await db.execute(
        select(OfflineTaskStep).where(
            OfflineTaskStep.task_id == task_id,
            OfflineTaskStep.status.in_(("failed", "interrupted")),
        )
    )
    steps = result.scalars().all()
    if not steps:
        raise ValueError("没有可重跑的失败步骤")
    for step in steps:
        step.status = "pending"
        step.error_message = None
        step.finished_at = None
        step.updated_at = datetime.now()
    task.status = "pending"
    task.finished_at = None
    task.error_message = None
    await _refresh_task_stats(db, task_id)
    await db.commit()
    _schedule_offline_task(task_id, [step.id for step in steps])
    await db.refresh(task)
    return task


async def recover_offline_tasks() -> None:
    async with async_session() as db:
        result = await db.execute(select(OfflineTask).where(OfflineTask.status == "running"))
        tasks = result.scalars().all()
        affected_task_ids = {task.id for task in tasks}
        for task in tasks:
            task.status = "interrupted"
            task.error_message = "服务重启导致任务中断，可重跑。"
            task.finished_at = datetime.now()
            task.updated_at = datetime.now()
        step_result = await db.execute(select(OfflineTaskStep).where(OfflineTaskStep.status == "running"))
        steps = step_result.scalars().all()
        for step in steps:
            affected_task_ids.add(step.task_id)
            step.status = "interrupted"
            step.error_message = "服务重启导致步骤中断，可重跑。"
            step.finished_at = datetime.now()
            step.updated_at = datetime.now()
        for task_id in affected_task_ids:
            await _refresh_task_stats(db, task_id)
        await db.commit()


async def cancel_active_offline_tasks() -> None:
    tasks = [task for task in _active_offline_tasks.values() if not task.done()]
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    _active_offline_tasks.clear()
