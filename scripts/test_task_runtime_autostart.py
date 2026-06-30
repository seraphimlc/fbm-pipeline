from __future__ import annotations

import asyncio
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from sqlalchemy import delete, select

from app.database import async_session
from app.models import TaskGroup, TaskRun, TaskStep, TaskStepEvent
from app.task_runtime import scheduler
from app.task_runtime.constants import RUN_STATUS_SUCCEEDED, STEP_STATUS_READY, STEP_STATUS_SUCCEEDED
from app.task_runtime.json_utils import json_dumps
from app.task_runtime.registry import TaskContext, register_worker

PROBE_STEP_TYPE = "test_runtime_autostart_probe"


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


async def _create_ready_probe_run() -> int:
    now = datetime.now()
    async with async_session() as db:
        run = TaskRun(
            task_type=PROBE_STEP_TYPE,
            title="Task runtime autostart probe",
            status="pending",
            payload_json=json_dumps({"probe": True}),
            created_by="test_task_runtime_autostart",
            dedupe_key=f"{PROBE_STEP_TYPE}:{now.timestamp()}",
            correlation_key=PROBE_STEP_TYPE,
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
            step_type=PROBE_STEP_TYPE,
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
        result = await db.execute(select(TaskRun.id).where(TaskRun.task_type == PROBE_STEP_TYPE))
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


if __name__ == "__main__":
    asyncio.run(main())
