import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import async_session
from app.models import TaskGroup, TaskRun, TaskStep
from app.task_runtime.actions import action_for
from app.task_runtime.constants import (
    RETRYABLE_STEP_STATUSES,
    RUN_STATUS_CANCELED,
    RUN_STATUS_FAILED,
    RUN_STATUS_INTERRUPTED,
    RUN_STATUS_PENDING,
    RUN_STATUS_PARTIAL_FAILED,
    RUN_STATUS_RUNNING,
    RUN_STATUS_SUCCEEDED,
    STEP_STATUS_FAILED,
    STEP_STATUS_INTERRUPTED,
    STEP_STATUS_CANCELED,
    STEP_STATUS_PENDING,
    STEP_STATUS_READY,
    STEP_STATUS_RUNNING,
    STEP_STATUS_SUCCEEDED,
)
from app.task_runtime.events import emit_event
from app.task_runtime.exceptions import TaskStepCanceled, TaskStepInterrupted
from app.task_runtime.json_utils import json_dumps
from app.task_runtime.json_utils import json_loads
from app.task_runtime.registry import TaskContext, worker_for

logger = logging.getLogger(__name__)

LOCK_SECONDS = 300
_runner_task: asyncio.Task | None = None
_runner_handle: asyncio.Handle | None = None
_runner_lock = asyncio.Lock()


def _registered_action_for_step(step_type: str):
    try:
        return action_for(step_type)
    except RuntimeError:
        return None


def _group_dependencies_satisfied(groups: list[TaskGroup], group: TaskGroup) -> bool:
    deps = json_loads(group.depends_on_group_keys_json, [])
    if not isinstance(deps, list):
        deps = []
    by_key = {item.group_key: item for item in groups}
    if deps:
        return all(
            by_key.get(str(dep)) is not None
            and by_key[str(dep)].status in (RUN_STATUS_SUCCEEDED, RUN_STATUS_PARTIAL_FAILED)
            for dep in deps
        )
    for previous in groups:
        if previous.id == group.id:
            break
        if previous.status not in (RUN_STATUS_SUCCEEDED, RUN_STATUS_PARTIAL_FAILED):
            return False
    return True


async def _claim_next_step(db: AsyncSession, worker_id: str) -> TaskStep | None:
    now = datetime.now()
    result = await db.execute(
        select(TaskStep)
        .join(TaskGroup, TaskGroup.id == TaskStep.task_group_id)
        .join(TaskRun, TaskRun.id == TaskStep.task_run_id)
        .where(TaskStep.status == STEP_STATUS_READY)
        .where(TaskRun.status.in_((RUN_STATUS_PENDING, RUN_STATUS_RUNNING)))
        .order_by(TaskRun.id.asc(), TaskGroup.sort_order.asc(), TaskStep.sort_order.asc(), TaskStep.id.asc())
        .limit(1)
    )
    candidate = result.scalar_one_or_none()
    if not candidate:
        return None
    claim = await db.execute(
        update(TaskStep)
        .where(
            TaskStep.id == candidate.id,
            TaskStep.status == STEP_STATUS_READY,
            or_(TaskStep.locked_until.is_(None), TaskStep.locked_until < now),
        )
        .values(
            status=STEP_STATUS_RUNNING,
            locked_by=worker_id,
            locked_until=now + timedelta(seconds=LOCK_SECONDS),
            heartbeat_at=now,
            started_at=now,
            finished_at=None,
            updated_at=now,
            attempt_count=TaskStep.attempt_count + 1,
        )
    )
    if claim.rowcount != 1:
        await db.rollback()
        return None
    await db.commit()
    result = await db.execute(
        select(TaskStep)
        .where(TaskStep.id == candidate.id)
        .options(selectinload(TaskStep.task_run), selectinload(TaskStep.task_group))
    )
    return result.scalar_one_or_none()


async def _refresh_group_and_run(db: AsyncSession, run_id: int) -> None:
    result = await db.execute(
        select(TaskGroup)
        .where(TaskGroup.task_run_id == run_id)
        .options(selectinload(TaskGroup.steps))
        .order_by(TaskGroup.sort_order.asc(), TaskGroup.id.asc())
    )
    groups = result.scalars().all()
    now = datetime.now()
    for group in groups:
        was_started = bool(group.started_at)
        steps = sorted(group.steps, key=lambda item: (item.sort_order, item.id))
        total = len(steps)
        succeeded = sum(1 for step in steps if step.status == STEP_STATUS_SUCCEEDED)
        failed = sum(1 for step in steps if step.status == STEP_STATUS_FAILED)
        interrupted = sum(1 for step in steps if step.status == STEP_STATUS_INTERRUPTED)
        running = sum(1 for step in steps if step.status == STEP_STATUS_RUNNING)
        ready = sum(1 for step in steps if step.status == STEP_STATUS_READY)
        pending = sum(1 for step in steps if step.status == STEP_STATUS_PENDING)
        allow_partial_success = group.failure_policy == "allow_partial_success"
        group.progress_current = succeeded
        group.progress_total = total
        group.updated_at = now
        if total and succeeded == total:
            group.status = RUN_STATUS_SUCCEEDED
            group.finished_at = group.finished_at or now
        elif allow_partial_success and (failed or interrupted) and pending and not (running or ready):
            next_step = next((step for step in steps if step.status == STEP_STATUS_PENDING), None)
            if next_step:
                next_step.status = STEP_STATUS_READY
                next_step.updated_at = now
            group.status = RUN_STATUS_RUNNING
            group.started_at = group.started_at or now
            group.finished_at = None
        elif allow_partial_success and total and (succeeded + failed + interrupted) == total and (failed or interrupted):
            group.status = RUN_STATUS_PARTIAL_FAILED if succeeded else RUN_STATUS_FAILED
            group.finished_at = group.finished_at or now
        elif failed:
            group.status = RUN_STATUS_FAILED
            group.finished_at = group.finished_at or now
        elif interrupted:
            group.status = RUN_STATUS_INTERRUPTED
            group.finished_at = group.finished_at or now
        elif running or ready:
            group.status = RUN_STATUS_RUNNING
            group.started_at = group.started_at or now
            group.finished_at = None
        elif pending:
            group.status = RUN_STATUS_PENDING
            group.finished_at = None
        if was_started and pending and not (failed or interrupted or running or ready):
            next_step = next((step for step in steps if step.status == STEP_STATUS_PENDING), None)
            if next_step:
                next_step.status = STEP_STATUS_READY
                next_step.updated_at = now
                group.status = RUN_STATUS_RUNNING
                group.started_at = group.started_at or now
                group.finished_at = None

    run = await db.get(TaskRun, run_id)
    if run and run.cancel_requested_at:
        has_running = any(step.status == STEP_STATUS_RUNNING for group in groups for step in group.steps)
        if not has_running:
            for group in groups:
                for step in group.steps:
                    if step.status in (STEP_STATUS_PENDING, STEP_STATUS_READY):
                        step.status = STEP_STATUS_CANCELED
                        step.finished_at = now
                        step.updated_at = now
                if group.status in (RUN_STATUS_PENDING, RUN_STATUS_RUNNING):
                    group.status = RUN_STATUS_CANCELED
                    group.finished_at = now
                    group.updated_at = now
            run.status = RUN_STATUS_CANCELED
            run.finished_at = now
            run.updated_at = now
            await db.commit()
            return

    for next_group in groups:
        next_steps = sorted(next_group.steps, key=lambda item: (item.sort_order, item.id))
        if (
            next_group.status == RUN_STATUS_PENDING
            and next_steps
            and all(step.status == STEP_STATUS_PENDING for step in next_steps)
            and _group_dependencies_satisfied(groups, next_group)
        ):
            next_steps[0].status = STEP_STATUS_READY
            next_steps[0].updated_at = now
            next_group.status = RUN_STATUS_RUNNING
            next_group.started_at = now
            next_group.updated_at = now

    run = await db.get(TaskRun, run_id)
    if run:
        group_statuses = [group.status for group in groups]
        run.updated_at = now
        if group_statuses and all(status == RUN_STATUS_SUCCEEDED for status in group_statuses):
            run.status = RUN_STATUS_SUCCEEDED
            run.finished_at = run.finished_at or now
        elif any(status == RUN_STATUS_PARTIAL_FAILED for status in group_statuses):
            run.status = RUN_STATUS_PARTIAL_FAILED
            run.finished_at = run.finished_at or now
        elif any(status == RUN_STATUS_FAILED for status in group_statuses):
            run.status = RUN_STATUS_FAILED
            run.finished_at = run.finished_at or now
        elif any(status == RUN_STATUS_INTERRUPTED for status in group_statuses):
            run.status = RUN_STATUS_INTERRUPTED
            run.finished_at = run.finished_at or now
        elif any(status == RUN_STATUS_RUNNING for status in group_statuses):
            run.status = RUN_STATUS_RUNNING
            run.started_at = run.started_at or now
            run.finished_at = None
        else:
            run.status = RUN_STATUS_PENDING
    await db.commit()


async def _execute_step(step_id: int, worker_id: str) -> bool:
    async with async_session() as db:
        result = await db.execute(
            select(TaskStep)
            .where(TaskStep.id == step_id)
            .options(selectinload(TaskStep.task_run), selectinload(TaskStep.task_group))
        )
        step = result.scalar_one()
        run = step.task_run
        group = step.task_group
        await emit_event(db, step=step, event_type="status", message="开始执行 step")
        run.status = RUN_STATUS_RUNNING
        run.started_at = run.started_at or datetime.now()
        group.status = RUN_STATUS_RUNNING
        group.started_at = group.started_at or datetime.now()
        await db.commit()
        success_payload: dict[str, Any] | None = None
        success_projection_error: str | None = None
        try:
            worker = worker_for(step.step_type)
            result_payload = await worker(TaskContext(db=db, run=run, group=group, step=step))
            await db.refresh(run)
            if run.cancel_requested_at:
                raise TaskStepCanceled(run.cancel_reason or "用户取消")
            now = datetime.now()
            step.status = STEP_STATUS_SUCCEEDED
            step.result_json = json_dumps(result_payload or {})
            step.error_message = None
            step.locked_by = None
            step.locked_until = None
            step.heartbeat_at = now
            step.finished_at = now
            step.updated_at = now
            await emit_event(db, step=step, event_type="status", message="step 执行成功", data=result_payload or {})
            await db.commit()
            success_payload = result_payload or {}
        except TaskStepCanceled as exc:
            now = datetime.now()
            step.status = STEP_STATUS_CANCELED
            step.error_message = str(exc) or "用户取消"
            step.locked_by = None
            step.locked_until = None
            step.heartbeat_at = now
            step.finished_at = now
            step.updated_at = now
            await emit_event(db, step=step, event_type="status", message=f"step 已取消：{step.error_message}")
            await db.commit()
        except TaskStepInterrupted as exc:
            now = datetime.now()
            step.status = STEP_STATUS_INTERRUPTED
            step.error_message = str(exc) or "step 已中断"
            step.locked_by = None
            step.locked_until = None
            step.heartbeat_at = now
            step.finished_at = now
            step.updated_at = now
            action = _registered_action_for_step(step.step_type)
            if action:
                await action.on_step_interrupted(db, step, step.error_message)
            await emit_event(db, step=step, event_type="status", message=step.error_message)
            await db.commit()
        except Exception as exc:
            logger.exception("[TaskRuntime] step failed: step_id=%s type=%s", step.id, step.step_type)
            now = datetime.now()
            step.status = STEP_STATUS_FAILED
            step.error_message = f"{type(exc).__name__}: {exc}"
            step.locked_by = None
            step.locked_until = None
            step.heartbeat_at = now
            step.finished_at = now
            step.updated_at = now
            await emit_event(db, step=step, event_type="error", message=step.error_message)
            await db.commit()
        if success_payload is not None:
            action = _registered_action_for_step(step.step_type)
            if action:
                try:
                    await action.on_step_success(db, step, success_payload)
                    await emit_event(db, step=step, event_type="status", message="step 成功投影完成")
                    await db.commit()
                except Exception as exc:
                    await db.rollback()
                    result = await db.execute(
                        select(TaskStep)
                        .where(TaskStep.id == step_id)
                        .options(selectinload(TaskStep.task_run), selectinload(TaskStep.task_group))
                    )
                    step = result.scalar_one()
                    message = f"step 已成功，后续业务投影失败: {type(exc).__name__}: {exc}"
                    success_projection_error = message
                    logger.exception("[TaskRuntime] step success projection failed: step_id=%s type=%s", step.id, step.step_type)
                    await emit_event(db, step=step, event_type="error", message=message)
                    await db.commit()
        await _refresh_group_and_run(db, run.id)
        if success_projection_error:
            run = await db.get(TaskRun, run.id)
            if run:
                now = datetime.now()
                run.status = RUN_STATUS_PARTIAL_FAILED
                run.finished_at = run.finished_at or now
                run.updated_at = now
                await db.commit()
    return True


async def drain_ready_steps() -> None:
    worker_id = f"task-runtime-{uuid4().hex[:8]}"
    claimed = 0
    logger.info("[TaskRuntime] runner drain started: worker_id=%s", worker_id)
    while True:
        async with async_session() as db:
            step = await _claim_next_step(db, worker_id)
        if not step:
            logger.info("[TaskRuntime] runner drain finished: worker_id=%s claimed=%s", worker_id, claimed)
            return
        claimed += 1
        logger.info(
            "[TaskRuntime] runner claimed step: worker_id=%s run_id=%s step_id=%s step_type=%s",
            worker_id,
            step.task_run_id,
            step.id,
            step.step_type,
        )
        await _execute_step(step.id, worker_id)


def _clear_stale_runner_state() -> None:
    global _runner_task, _runner_handle
    if _runner_task and _runner_task.done():
        _runner_task = None
    if _runner_handle and _runner_handle.cancelled():
        _runner_handle = None


def _on_runner_done(task: asyncio.Task) -> None:
    global _runner_task
    try:
        task.result()
    except asyncio.CancelledError:
        logger.info("[TaskRuntime] runner task cancelled")
    except Exception:
        logger.exception("[TaskRuntime] runner task crashed")
    finally:
        if _runner_task is task:
            _runner_task = None
        logger.info("[TaskRuntime] runner task finished")


def kick_task_runtime() -> None:
    global _runner_task, _runner_handle
    _clear_stale_runner_state()
    if _runner_task and not _runner_task.done():
        logger.debug("[TaskRuntime] kick ignored: runner task already active")
        return
    if _runner_handle and not _runner_handle.cancelled():
        logger.debug("[TaskRuntime] kick ignored: runner start already scheduled")
        return

    async def runner() -> None:
        async with _runner_lock:
            await drain_ready_steps()

    def start_runner() -> None:
        global _runner_task, _runner_handle
        _runner_handle = None
        _clear_stale_runner_state()
        if _runner_task and not _runner_task.done():
            logger.debug("[TaskRuntime] scheduled runner skipped: runner task already active")
            return
        logger.info("[TaskRuntime] starting runner task")
        _runner_task = asyncio.create_task(runner())
        _runner_task.add_done_callback(_on_runner_done)

    loop = asyncio.get_running_loop()
    logger.info("[TaskRuntime] scheduling runner task")
    _runner_handle = loop.call_later(0.05, start_runner)


async def recover_task_runtime() -> int:
    now = datetime.now()
    recovered = 0
    async with async_session() as db:
        result = await db.execute(
            select(TaskStep)
            .where(TaskStep.status == STEP_STATUS_RUNNING)
            .where(or_(TaskStep.locked_until.is_(None), TaskStep.locked_until < now))
        )
        steps = result.scalars().all()
        for step in steps:
            step.status = STEP_STATUS_INTERRUPTED
            step.error_message = step.error_message or "服务重启或锁超时，step 已中断，可单独重跑"
            step.locked_by = None
            step.locked_until = None
            step.finished_at = now
            step.updated_at = now
            action = _registered_action_for_step(step.step_type)
            if action:
                await action.on_step_interrupted(db, step, step.error_message)
            await emit_event(db, step=step, event_type="status", message=step.error_message)
            recovered += 1
        await db.commit()
        run_ids = sorted({step.task_run_id for step in steps})
        for run_id in run_ids:
            await _refresh_group_and_run(db, run_id)
    return recovered


async def retry_step(step_id: int, *, auto_start: bool = True) -> TaskStep:
    async with async_session() as db:
        step = await db.get(TaskStep, step_id)
        if not step:
            raise ValueError("step 不存在")
        if step.status not in RETRYABLE_STEP_STATUSES:
            raise ValueError(f"当前 step 状态不可重跑: {step.status}")
        if step.max_attempts and step.attempt_count >= step.max_attempts:
            raise ValueError(f"当前 step 已达到最大重试次数: {step.attempt_count}/{step.max_attempts}")
        now = datetime.now()
        step.status = STEP_STATUS_READY
        step.error_message = None
        step.locked_by = None
        step.locked_until = None
        step.finished_at = None
        step.updated_at = now
        group = await db.get(TaskGroup, step.task_group_id)
        run = await db.get(TaskRun, step.task_run_id)
        if group:
            group.status = RUN_STATUS_RUNNING
            group.finished_at = None
            group.updated_at = now
        if run:
            run.status = RUN_STATUS_RUNNING
            run.finished_at = None
            run.updated_at = now
        await emit_event(db, step=step, event_type="status", message="已提交 step 重跑")
        await db.commit()
        await db.refresh(step)
    if auto_start:
        kick_task_runtime()
    return step


async def retry_failed_steps(run_id: int) -> int:
    async with async_session() as db:
        result = await db.execute(
            select(TaskStep)
            .where(TaskStep.task_run_id == run_id, TaskStep.status.in_(tuple(RETRYABLE_STEP_STATUSES)))
            .order_by(TaskStep.sort_order.asc(), TaskStep.id.asc())
        )
        steps = result.scalars().all()
    count = 0
    for step in steps:
        await retry_step(step.id)
        count += 1
    return count
