import asyncio
import json
import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.config import settings
from app.database import async_session
from app.models import AplusRegenerateTask, Product, ProductAplus
from app.pipeline.step8_aplus_script import diagnose_aplus_regeneration_feedback, regenerate_aplus_module_script
from app.pipeline.step9_aplus_image import regenerate_aplus_module_image

logger = logging.getLogger(__name__)

ACTIVE_STATUSES = ("queued", "script_running", "image_running")
RUNNING_STATUSES = ("script_running", "image_running")
FINAL_STATUSES = ("done", "failed", "interrupted")

_active_tasks: dict[int, asyncio.Task] = {}
_worker_semaphore = asyncio.Semaphore(max(1, settings.APLUS_CONCURRENCY))
_product_locks: dict[int, asyncio.Lock] = {}


def _product_lock(product_id: int) -> asyncio.Lock:
    lock = _product_locks.get(product_id)
    if lock is None:
        lock = asyncio.Lock()
        _product_locks[product_id] = lock
    return lock


def _regen_aplus_status(task_status: str) -> str:
    return {
        "queued": "regen_queued",
        "script_running": "regen_script_running",
        "image_running": "regen_image_running",
        "failed": "regen_failed",
        "interrupted": "regen_interrupted",
    }.get(task_status, "regen_done")


async def _set_product_regen_status(product_id: int, status: str) -> None:
    async with async_session() as db:
        result = await db.execute(
            select(Product)
            .options(selectinload(Product.aplus))
            .where(Product.id == product_id)
        )
        product = result.scalar_one_or_none()
        if product and product.aplus:
            now = datetime.now()
            product.aplus.aplus_status = _regen_aplus_status(status)
            product.aplus.generated_at = now
            product.updated_at = now
            await db.commit()


async def _update_task(
    task_id: int,
    status: str,
    *,
    stage: str | None = None,
    error: str | None = None,
    result: dict | None = None,
) -> None:
    async with async_session() as db:
        task = await db.get(AplusRegenerateTask, task_id)
        if not task:
            return
        now = datetime.now()
        task.status = status
        task.stage = stage
        task.updated_at = now
        if status in RUNNING_STATUSES and task.started_at is None:
            task.started_at = now
        if status in FINAL_STATUSES:
            task.finished_at = now
        if error is not None:
            task.error_message = error
        if result is not None:
            task.result_json = json.dumps(result, ensure_ascii=False)
        product_id = task.product_id
        await db.commit()
    await _set_product_regen_status(product_id, status)


async def _execute_task(task_id: int) -> None:
    async with async_session() as db:
        task = await db.get(AplusRegenerateTask, task_id)
        if not task or task.status not in ACTIVE_STATUSES:
            return
        product_id = task.product_id
        module_position = task.module_position
        reason = task.reason

    async with _worker_semaphore:
        async with _product_lock(product_id):
            logger.info(
                f"[AplusRegenerate] 开始任务: task={task_id}, product={product_id}, "
                f"module={module_position}, concurrency={max(1, settings.APLUS_CONCURRENCY)}"
            )
            try:
                await _update_task(task_id, "script_running", stage="diagnosis")
                diagnosis = await diagnose_aplus_regeneration_feedback(product_id, module_position, reason)
                await _update_task(task_id, "script_running", stage="script", result={"diagnosis": diagnosis})
                script = await regenerate_aplus_module_script(product_id, module_position, reason, diagnosis=diagnosis)

                await _update_task(task_id, "image_running", stage="image")
                image = await regenerate_aplus_module_image(product_id, module_position)

                await _update_task(task_id, "done", stage="done", result={"diagnosis": diagnosis, "script": script, "image": image})
                logger.info(
                    f"[AplusRegenerate] 持久化任务完成: task={task_id}, "
                    f"product={product_id}, module={module_position}"
                )
            except asyncio.CancelledError:
                await _update_task(task_id, "interrupted", stage="interrupted", error="服务停止，任务已中断，可重新提交。")
                raise
            except Exception as exc:
                logger.exception(
                    f"[AplusRegenerate] 持久化任务失败: task={task_id}, "
                    f"product={product_id}, module={module_position}"
                )
                await _update_task(task_id, "failed", stage="failed", error=f"{type(exc).__name__}: {exc}")
            finally:
                _active_tasks.pop(task_id, None)


def _schedule_task(task_id: int) -> None:
    existing = _active_tasks.get(task_id)
    if existing and not existing.done():
        return
    _active_tasks[task_id] = asyncio.create_task(_execute_task(task_id))


async def create_regenerate_task(product_id: int, module_position: int, reason: str) -> AplusRegenerateTask:
    async with async_session() as db:
        queued_result = await db.execute(
            select(AplusRegenerateTask)
            .where(
                AplusRegenerateTask.product_id == product_id,
                AplusRegenerateTask.module_position == module_position,
                AplusRegenerateTask.status == "queued",
            )
            .order_by(AplusRegenerateTask.created_at.desc())
            .limit(1)
        )
        queued = queued_result.scalar_one_or_none()
        if queued:
            now = datetime.now()
            queued.reason = reason
            queued.stage = "queued"
            queued.error_message = None
            queued.result_json = None
            queued.started_at = None
            queued.finished_at = None
            queued.updated_at = now
            task_id = queued.id
            task = queued
        else:
            now = datetime.now()
            task = AplusRegenerateTask(
                product_id=product_id,
                module_position=module_position,
                reason=reason,
                status="queued",
                stage="queued",
                created_at=now,
                updated_at=now,
            )
            db.add(task)
            await db.flush()
            task_id = task.id
        await db.commit()
    await _set_product_regen_status(product_id, "queued")
    _schedule_task(task_id)
    return task


async def retry_latest_regenerate_tasks(product_id: int) -> list[AplusRegenerateTask]:
    """重新排队该商品每个模块最新的失败/中断重生成任务。"""
    async with async_session() as db:
        active_result = await db.execute(
            select(AplusRegenerateTask)
            .where(
                AplusRegenerateTask.product_id == product_id,
                AplusRegenerateTask.status.in_(ACTIVE_STATUSES),
            )
            .order_by(AplusRegenerateTask.updated_at.desc())
        )
        active_tasks = active_result.scalars().all()
        if active_tasks:
            task_ids = [task.id for task in active_tasks]
            tasks = active_tasks
        else:
            history_result = await db.execute(
                select(AplusRegenerateTask)
                .where(AplusRegenerateTask.product_id == product_id)
                .order_by(AplusRegenerateTask.module_position.asc(), AplusRegenerateTask.updated_at.desc())
            )
            latest_by_module: dict[int, AplusRegenerateTask] = {}
            for task in history_result.scalars().all():
                latest_by_module.setdefault(task.module_position, task)

            now = datetime.now()
            tasks = [
                task
                for task in latest_by_module.values()
                if task.status in {"failed", "interrupted"}
            ]
            for task in tasks:
                task.status = "queued"
                task.stage = "queued"
                task.error_message = None
                task.result_json = None
                task.started_at = None
                task.finished_at = None
                task.updated_at = now
            task_ids = [task.id for task in tasks]
            if task_ids:
                await db.commit()
        if not task_ids:
            return []
    await _set_product_regen_status(product_id, "queued")
    for task_id in task_ids:
        _schedule_task(task_id)
    return tasks


async def recover_regenerate_tasks() -> None:
    """启动时恢复数据库任务队列：运行中的标记为中断，排队中的继续执行。"""
    async with async_session() as db:
        running_result = await db.execute(
            select(AplusRegenerateTask).where(AplusRegenerateTask.status.in_(RUNNING_STATUSES))
        )
        running_tasks = running_result.scalars().all()
        now = datetime.now()
        for task in running_tasks:
            task.status = "interrupted"
            task.stage = "interrupted"
            task.error_message = "服务重启导致任务中断，可重新提交。"
            task.finished_at = now
            task.updated_at = now

        queued_result = await db.execute(
            select(AplusRegenerateTask)
            .where(AplusRegenerateTask.status == "queued")
            .order_by(AplusRegenerateTask.created_at.asc())
        )
        queued_ids = [task.id for task in queued_result.scalars().all()]
        legacy_result = await db.execute(
            select(ProductAplus).where(ProductAplus.aplus_status == "regenerating")
        )
        legacy_aplus_rows = legacy_result.scalars().all()
        for row in legacy_aplus_rows:
            row.aplus_status = "regen_interrupted"
            row.generated_at = now
        await db.commit()

    for task in running_tasks:
        await _set_product_regen_status(task.product_id, "interrupted")
    for task_id in queued_ids:
        _schedule_task(task_id)
    if running_tasks or queued_ids or legacy_aplus_rows:
        logger.info(
            f"[AplusRegenerate] 启动恢复: interrupted={len(running_tasks)}, "
            f"queued={len(queued_ids)}, legacy={len(legacy_aplus_rows)}"
        )


async def cancel_active_regenerate_tasks() -> None:
    tasks = [task for task in _active_tasks.values() if not task.done()]
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
