from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from sqlalchemy.engine import make_url
from sqlalchemy import delete, select


def _require_isolated_r1_database() -> None:
    """Never let a probe task race with a developer's running backend."""
    database_url = str(os.environ.get("DATABASE_URL") or "").strip()
    database_name = str(os.environ.get("R1_MYSQL_WRAPPER_DATABASE") or "").strip()
    if os.environ.get("R1_MYSQL_WRAPPER_ACTIVE") != "1":
        raise RuntimeError(
            "task runtime autostart 测试只能在 R1 隔离 MySQL 中运行；"
            "请使用 scripts/testing/run_with_r1_mysql.py -- make test-project-rules"
        )
    if not database_url or not database_name.startswith("fbm_pipeline_r1_"):
        raise RuntimeError("task runtime autostart 测试缺少受控的 R1 隔离数据库")
    if make_url(database_url).database != database_name:
        raise RuntimeError("task runtime autostart 测试 DATABASE_URL 未指向当前 R1 隔离数据库")


_require_isolated_r1_database()

from app.database import async_session
from app.models import TaskGroup, TaskRun, TaskStep, TaskStepEvent
from app.task_runtime import scheduler
from app.task_runtime.constants import (
    RUN_STATUS_FAILED,
    RUN_STATUS_SUCCEEDED,
    STEP_STATUS_INTERRUPTED,
    STEP_STATUS_READY,
    STEP_STATUS_SUCCEEDED,
)
from app.task_runtime.json_utils import json_dumps
from app.task_runtime.exceptions import TaskStepInterrupted
from app.task_runtime.registry import TaskContext, register_worker

PROBE_STEP_TYPE = "test_runtime_autostart_probe"
HEARTBEAT_PROBE_STEP_TYPE = "test_runtime_lease_heartbeat_probe"
FAILURE_PROBE_STEP_TYPE = "test_runtime_lease_failure_probe"
CANCEL_PROBE_STEP_TYPE = "test_runtime_lease_cancel_probe"
TIMEOUT_PROBE_STEP_TYPE = "test_runtime_lease_timeout_probe"


async def _assert_runner_lifecycle_cleanup() -> None:
    original_drain = scheduler.drain_ready_steps
    original_task = scheduler._runner_task
    original_handle = scheduler._runner_handle
    calls = 0
    event = asyncio.Event()

    async def fake_drain_ready_steps() -> None:
        nonlocal calls
        calls += 1
        event.set()

    try:
        if scheduler._runner_handle and not scheduler._runner_handle.cancelled():
            scheduler._runner_handle.cancel()
        scheduler._runner_task = None
        scheduler._runner_handle = None
        scheduler.drain_ready_steps = fake_drain_ready_steps

        scheduler.kick_task_runtime()
        await asyncio.wait_for(event.wait(), timeout=1.0)
        assert calls == 1, calls
        if scheduler._runner_task:
            await scheduler._runner_task
        await asyncio.sleep(0)
        assert scheduler._runner_task is None, "completed runner task must be cleared"

        stale_handle = asyncio.get_running_loop().call_later(60, lambda: None)
        stale_handle.cancel()
        scheduler._runner_handle = stale_handle
        event.clear()
        scheduler.kick_task_runtime()
        await asyncio.wait_for(event.wait(), timeout=1.0)
        assert calls == 2, calls
    finally:
        if scheduler._runner_handle and not scheduler._runner_handle.cancelled():
            scheduler._runner_handle.cancel()
        scheduler.drain_ready_steps = original_drain
        scheduler._runner_task = original_task
        scheduler._runner_handle = original_handle


async def _assert_ready_step_is_claimed_and_executed_without_wake() -> None:
    await _cleanup_probe_runs()
    register_worker(PROBE_STEP_TYPE, _probe_worker)
    run_id = await _create_ready_probe_run()
    try:
        scheduler.kick_task_runtime()
        await _wait_for_runner_idle()
        async with async_session() as db:
            result = await db.execute(
                select(TaskRun.status, TaskStep.status)
                .join(TaskStep, TaskStep.task_run_id == TaskRun.id)
                .where(TaskRun.id == run_id)
            )
            final_status = result.first()
        assert final_status and tuple(final_status) == (RUN_STATUS_SUCCEEDED, STEP_STATUS_SUCCEEDED), final_status
    finally:
        await _cleanup_probe_runs()


async def _assert_one_drain_consumes_all_ready_steps() -> None:
    """A serial runner must not strand later ready work after one success."""
    await _cleanup_probe_runs()
    register_worker(PROBE_STEP_TYPE, _probe_worker)
    first_run_id = await _create_ready_probe_run()
    second_run_id = await _create_ready_probe_run()
    try:
        scheduler.kick_task_runtime()
        await _wait_for_runner_idle()
        async with async_session() as db:
            result = await db.execute(
                select(TaskRun.id, TaskRun.status, TaskStep.status)
                .join(TaskStep, TaskStep.task_run_id == TaskRun.id)
                .where(TaskRun.id.in_((first_run_id, second_run_id)))
                .order_by(TaskRun.id.asc())
            )
            final_statuses = result.all()
        assert final_statuses == [
            (first_run_id, RUN_STATUS_SUCCEEDED, STEP_STATUS_SUCCEEDED),
            (second_run_id, RUN_STATUS_SUCCEEDED, STEP_STATUS_SUCCEEDED),
        ], final_statuses
    finally:
        await _cleanup_probe_runs()


async def _assert_long_worker_renews_lease_and_terminal_paths_stop_it() -> None:
    original_lock_seconds = scheduler.LOCK_SECONDS
    original_heartbeat_seconds = scheduler.LEASE_HEARTBEAT_SECONDS
    started = asyncio.Event()
    cancel_started = asyncio.Event()

    async def long_worker(_ctx: TaskContext) -> dict:
        started.set()
        await asyncio.sleep(0.22)
        return {"status": "done"}

    async def failing_worker(_ctx: TaskContext) -> dict:
        await asyncio.sleep(0.08)
        raise RuntimeError("lease probe failure")

    async def cancelable_worker(_ctx: TaskContext) -> dict:
        cancel_started.set()
        await asyncio.Event().wait()
        return {"unreachable": True}

    async def timed_out_worker(_ctx: TaskContext) -> dict:
        await asyncio.sleep(0.08)
        raise TaskStepInterrupted("lease probe timeout")

    try:
        scheduler.LOCK_SECONDS = 0.12
        scheduler.LEASE_HEARTBEAT_SECONDS = 0.03
        register_worker(HEARTBEAT_PROBE_STEP_TYPE, long_worker)
        register_worker(FAILURE_PROBE_STEP_TYPE, failing_worker)
        register_worker(TIMEOUT_PROBE_STEP_TYPE, timed_out_worker)

        heartbeat_run_id = await _create_ready_probe_run(task_type=HEARTBEAT_PROBE_STEP_TYPE)
        scheduler.kick_task_runtime()
        await asyncio.wait_for(started.wait(), timeout=1.0)
        await asyncio.sleep(0.14)
        async with async_session() as db:
            step = (await db.execute(select(TaskStep).where(TaskStep.task_run_id == heartbeat_run_id))).scalar_one()
            assert step.status != STEP_STATUS_SUCCEEDED, step.status
            assert step.heartbeat_at and step.heartbeat_at > step.started_at, (step.heartbeat_at, step.started_at)
            assert step.locked_until and step.locked_until > datetime.now(), step.locked_until
        await _wait_for_runner_idle()
        async with async_session() as db:
            run = await db.get(TaskRun, heartbeat_run_id)
            assert run and run.status == RUN_STATUS_SUCCEEDED, run.status if run else None

        failure_run_id = await _create_ready_probe_run(task_type=FAILURE_PROBE_STEP_TYPE)
        scheduler.kick_task_runtime()
        await _wait_for_runner_idle()
        async with async_session() as db:
            failed_step = (await db.execute(select(TaskStep).where(TaskStep.task_run_id == failure_run_id))).scalar_one()
            failed_heartbeat = failed_step.heartbeat_at
            failed_run = await db.get(TaskRun, failure_run_id)
            assert failed_run and failed_run.status == RUN_STATUS_FAILED, failed_run.status if failed_run else None
        await asyncio.sleep(0.08)
        async with async_session() as db:
            failed_step = (await db.execute(select(TaskStep).where(TaskStep.task_run_id == failure_run_id))).scalar_one()
            assert failed_step.heartbeat_at == failed_heartbeat, "failed worker must stop its lease heartbeat"

        timeout_run_id = await _create_ready_probe_run(task_type=TIMEOUT_PROBE_STEP_TYPE)
        scheduler.kick_task_runtime()
        await _wait_for_runner_idle()
        async with async_session() as db:
            timed_out_step = (await db.execute(select(TaskStep).where(TaskStep.task_run_id == timeout_run_id))).scalar_one()
            timeout_heartbeat = timed_out_step.heartbeat_at
            assert timed_out_step.status == STEP_STATUS_INTERRUPTED, timed_out_step.status
            assert timed_out_step.locked_by is None and timed_out_step.locked_until is None
        await asyncio.sleep(0.08)
        async with async_session() as db:
            timed_out_step = (await db.execute(select(TaskStep).where(TaskStep.task_run_id == timeout_run_id))).scalar_one()
            assert timed_out_step.heartbeat_at == timeout_heartbeat, "timed-out worker must stop its lease heartbeat"

        cancel_run_id = await _create_ready_probe_run(task_type=CANCEL_PROBE_STEP_TYPE)
        register_worker(CANCEL_PROBE_STEP_TYPE, cancelable_worker)
        scheduler.kick_task_runtime()
        await asyncio.wait_for(cancel_started.wait(), timeout=1.0)
        runner = scheduler._runner_task
        assert runner is not None, "cancel probe runner was not started"
        await scheduler.shutdown_task_runtime()
        assert scheduler._runner_task is None, "shutdown must clear the in-process runner state"
        async with async_session() as db:
            canceled_step = (await db.execute(select(TaskStep).where(TaskStep.task_run_id == cancel_run_id))).scalar_one()
            canceled_heartbeat = canceled_step.heartbeat_at
            assert canceled_step.status == STEP_STATUS_INTERRUPTED, canceled_step.status
            assert canceled_step.locked_by is None and canceled_step.locked_until is None
        await asyncio.sleep(0.08)
        async with async_session() as db:
            canceled_step = (await db.execute(select(TaskStep).where(TaskStep.task_run_id == cancel_run_id))).scalar_one()
            assert canceled_step.heartbeat_at == canceled_heartbeat, "cancelled worker must stop its lease heartbeat"
    finally:
        scheduler.LOCK_SECONDS = original_lock_seconds
        scheduler.LEASE_HEARTBEAT_SECONDS = original_heartbeat_seconds
        await _cleanup_probe_runs()


async def _wait_for_runner_idle() -> None:
    deadline = asyncio.get_running_loop().time() + 3.0
    while asyncio.get_running_loop().time() < deadline:
        task = scheduler._runner_task
        handle = scheduler._runner_handle
        if task:
            await task
            await asyncio.sleep(0)
            return
        if not handle or handle.cancelled():
            await asyncio.sleep(0)
            if not scheduler._runner_task:
                return
        await asyncio.sleep(0.05)
    raise AssertionError("task runtime runner did not become idle")


async def _probe_worker(ctx: TaskContext) -> dict:
    return {
        "status": "claimed_and_executed",
        "run_id": ctx.run.id,
        "step_id": ctx.step.id,
    }


async def _create_ready_probe_run(*, task_type: str = PROBE_STEP_TYPE) -> int:
    now = datetime.now()
    async with async_session() as db:
        run = TaskRun(
            task_type=task_type,
            title="Task runtime autostart probe",
            status="pending",
            payload_json=json_dumps({"probe": True}),
            created_by="test_task_runtime_autostart",
            dedupe_key=f"{task_type}:{now.timestamp()}",
            correlation_key=task_type,
            created_at=now,
            updated_at=now,
        )
        db.add(run)
        await db.flush()
        group = TaskGroup(
            task_run_id=run.id,
            group_key="probe",
            title="Probe",
            status="pending",
            sort_order=1,
            depends_on_group_keys_json=json_dumps([]),
            failure_policy="require_all_success",
            retry_policy="failed_steps_only",
            progress_current=0,
            progress_total=1,
            created_at=now,
            updated_at=now,
        )
        db.add(group)
        await db.flush()
        db.add(TaskStep(
            task_run_id=run.id,
            task_group_id=group.id,
            step_key="probe-step",
            step_type=task_type,
            status=STEP_STATUS_READY,
            sort_order=1,
            payload_json=json_dumps({"probe": True}),
            progress_current=0,
            progress_total=1,
            max_attempts=1,
            created_at=now,
            updated_at=now,
        ))
        await db.commit()
        return run.id


async def _cleanup_probe_runs() -> None:
    async with async_session() as db:
        result = await db.execute(select(TaskRun.id).where(TaskRun.task_type.in_((
            PROBE_STEP_TYPE,
            HEARTBEAT_PROBE_STEP_TYPE,
            FAILURE_PROBE_STEP_TYPE,
            CANCEL_PROBE_STEP_TYPE,
            TIMEOUT_PROBE_STEP_TYPE,
        ))))
        run_ids = [row[0] for row in result.all()]
        if run_ids:
            await db.execute(delete(TaskStepEvent).where(TaskStepEvent.task_run_id.in_(run_ids)))
            await db.execute(delete(TaskStep).where(TaskStep.task_run_id.in_(run_ids)))
            await db.execute(delete(TaskGroup).where(TaskGroup.task_run_id.in_(run_ids)))
            await db.execute(delete(TaskRun).where(TaskRun.id.in_(run_ids)))
            await db.commit()


async def main() -> None:
    await _assert_runner_lifecycle_cleanup()
    await _assert_ready_step_is_claimed_and_executed_without_wake()
    await _assert_one_drain_consumes_all_ready_steps()
    await _assert_long_worker_renews_lease_and_terminal_paths_stop_it()


if __name__ == "__main__":
    asyncio.run(main())
