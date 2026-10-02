from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from pathlib import Path
import sys

from sqlalchemy import select, update

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from testing.r1_sqlite_bootstrap import ensure_sqlite_test_process

if __name__ == "__main__":
    ensure_sqlite_test_process(__file__)

sys.path.insert(0, str(ROOT / "backend"))

from app.database import async_session, run_schema_maintenance  # noqa: E402
from app.models import (  # noqa: E402
    AplusImageGenerationJob,
    Product,
    ProductAplus,
    TaskGroup,
    TaskRun,
    TaskStep,
)
from app.task_runtime import aplus_image_poller as poller  # noqa: E402
from app.task_runtime.constants import (  # noqa: E402
    STEP_STATUS_CANCELED,
    STEP_STATUS_FAILED,
    STEP_STATUS_READY,
    STEP_STATUS_RUNNING,
    STEP_STATUS_SUCCEEDED,
    STEP_STATUS_WAITING_EXTERNAL,
)
from app.task_runtime.exceptions import TaskStepWaitingExternal  # noqa: E402
from app.task_runtime.registry import register_worker  # noqa: E402
from app.task_runtime.scheduler import _execute_step  # noqa: E402


async def _fixture(name: str, *, status: str = STEP_STATUS_RUNNING) -> tuple[int, int, int]:
    now = datetime.now()
    async with async_session() as db:
        product = Product(gigab2b_url=f"https://fixture.invalid/{name}", status="pending_review")
        product.aplus = ProductAplus(aplus_status="imaging")
        db.add(product)
        await db.flush()
        run = TaskRun(task_type="aplus_generate", title=name, status="running", created_at=now, updated_at=now)
        db.add(run)
        await db.flush()
        group = TaskGroup(
            task_run_id=run.id,
            group_key="aplus_generate",
            title="A+生成",
            status="running",
            sort_order=1,
            failure_policy="allow_partial_success",
            progress_current=0,
            progress_total=3,
            started_at=now,
            created_at=now,
            updated_at=now,
        )
        db.add(group)
        await db.flush()
        step = TaskStep(
            task_run_id=run.id,
            task_group_id=group.id,
            step_key=f"product:{product.id}:aplus",
            step_type="aplus_generate_product",
            status=status,
            sort_order=1,
            payload_json=f'{{"product_id": {product.id}}}',
            progress_current=2,
            progress_total=3,
            attempt_count=1,
            max_attempts=2,
            created_at=now,
            updated_at=now,
        )
        db.add(step)
        await db.commit()
        return product.id, run.id, step.id


async def _set_jobs_due(step_id: int) -> None:
    async with async_session() as db:
        await db.execute(
            update(AplusImageGenerationJob)
            .where(AplusImageGenerationJob.task_step_id == step_id)
            .values(next_poll_at=datetime.now() - timedelta(seconds=1))
        )
        await db.commit()


async def _test_batch_restart_and_success() -> None:
    product_id, run_id, step_id = await _fixture("batch-restart")
    submit_calls: list[str] = []
    poll_calls: dict[str, int] = {}
    finalized: list[str] = []

    async def fake_prepare(_product_id: int) -> dict:
        assert _product_id == product_id
        return {
            "product_id": product_id,
            "product_key": "ASYNC-TEST",
            "brand": "Test",
            "output_dir": "/tmp/aplus-async-test",
            "expected_count": 2,
            "work_items": [
                {"script": {"module_position": position, "prompt": f"slot {position}"}, "output_path": f"/tmp/aplus-{step_id}-{position}.jpg"}
                for position in (1, 2)
            ],
        }

    async def fake_submit(script: dict, *, brand: str | None, idempotency_key: str) -> dict:
        submit_calls.append(idempotency_key)
        return {"state": "submitted", "provider_task_id": f"provider-{script['module_position']}", "provider_result": {"status": "queued"}}

    async def fake_poll(provider_task_id: str) -> dict:
        poll_calls[provider_task_id] = poll_calls.get(provider_task_id, 0) + 1
        if poll_calls[provider_task_id] == 1:
            return {"state": "pending", "provider_result": {"status": "processing"}}
        return {"state": "completed", "provider_result": {"status": "completed"}, "image_payload": {"bytes": b"fixture"}}

    def fake_finalize(script: dict, image_payload: dict, **_kwargs) -> dict:
        finalized.append(str(script["module_position"]))
        return {"position": script["module_position"], "status": "done", "path": f"/tmp/fake-{script['module_position']}.jpg"}

    originals = (poller.prepare_aplus_image_work, poller.submit_aplus_image_generation, poller.poll_aplus_image_generation, poller.finalize_aplus_image_payload)
    poller.prepare_aplus_image_work = fake_prepare
    poller.submit_aplus_image_generation = fake_submit
    poller.poll_aplus_image_generation = fake_poll
    poller.finalize_aplus_image_payload = fake_finalize
    try:
        submission = await poller.submit_aplus_generation_jobs(step_id, product_id)
        assert submission["state"] == "waiting_external", submission
        assert len(submit_calls) == 2
        async with async_session() as db:
            step = await db.get(TaskStep, step_id)
            step.status = STEP_STATUS_WAITING_EXTERNAL
            await db.commit()

        await _set_jobs_due(step_id)
        first = await poller.run_aplus_image_poll_batch()
        assert first["claimed"] == 2 and first["finalized_steps"] == 0, first
        assert len(submit_calls) == 2, "polling after restart must not resubmit provider tasks"

        await _set_jobs_due(step_id)
        second = await poller.run_aplus_image_poll_batch()
        assert second["claimed"] == 2 and second["finalized_steps"] == 1, second
        assert sorted(finalized) == ["1", "2"]
        third = await poller.run_aplus_image_poll_batch()
        assert third["claimed"] == 0
        assert sorted(finalized) == ["1", "2"], "completed jobs must not finalize twice"
        async with async_session() as db:
            step = await db.get(TaskStep, step_id)
            run = await db.get(TaskRun, run_id)
            product = await db.get(Product, product_id)
            aplus = await db.scalar(select(ProductAplus).where(ProductAplus.product_id == product_id))
            assert step.status == STEP_STATUS_SUCCEEDED
            assert run.status == "succeeded"
            assert product is not None and aplus is not None and aplus.aplus_status == "done"
            assert aplus.aplus_image_count == 2
    finally:
        (
            poller.prepare_aplus_image_work,
            poller.submit_aplus_image_generation,
            poller.poll_aplus_image_generation,
            poller.finalize_aplus_image_payload,
        ) = originals


async def _test_provider_failure() -> None:
    product_id, _run_id, step_id = await _fixture("provider-failure", status=STEP_STATUS_WAITING_EXTERNAL)
    now = datetime.now()
    async with async_session() as db:
        db.add(AplusImageGenerationJob(
            product_id=product_id,
            task_run_id=_run_id,
            task_step_id=step_id,
            asset_slot_key="module:1",
            module_position=1,
            status="submitted",
            provider_task_id="provider-failed",
            request_fingerprint="f" * 64,
            idempotency_key=f"failure-{step_id}",
            script_json='{"module_position": 1}',
            output_path="/tmp/failure.jpg",
            product_key="FAILURE",
            next_poll_at=now - timedelta(seconds=1),
            deadline_at=now + timedelta(minutes=5),
        ))
        await db.commit()
    original = poller.poll_aplus_image_generation
    poller.poll_aplus_image_generation = lambda _task_id: asyncio.sleep(0, result={"state": "failed", "provider_result": {"status": "failed"}})
    try:
        result = await poller.run_aplus_image_poll_batch()
        assert result["finalized_steps"] == 1
        async with async_session() as db:
            assert (await db.get(TaskStep, step_id)).status == STEP_STATUS_FAILED
    finally:
        poller.poll_aplus_image_generation = original


async def _test_immediate_result() -> None:
    product_id, _run_id, step_id = await _fixture("immediate")

    async def fake_prepare(_product_id: int) -> dict:
        return {
            "product_id": _product_id,
            "product_key": "IMMEDIATE",
            "brand": "Test",
            "output_dir": "/tmp",
            "expected_count": 1,
            "work_items": [{"script": {"module_position": 1, "prompt": "immediate"}, "output_path": "/tmp/immediate.jpg"}],
        }

    async def fake_submit(_script: dict, **_kwargs) -> dict:
        return {"state": "completed", "provider_task_id": None, "image_payload": {"bytes": b"fixture"}}

    def fake_finalize(script: dict, _image_payload: dict, **_kwargs) -> dict:
        return {"position": script["module_position"], "status": "done", "path": "/tmp/immediate.jpg"}

    originals = poller.prepare_aplus_image_work, poller.submit_aplus_image_generation, poller.finalize_aplus_image_payload
    poller.prepare_aplus_image_work = fake_prepare
    poller.submit_aplus_image_generation = fake_submit
    poller.finalize_aplus_image_payload = fake_finalize
    try:
        result = await poller.submit_aplus_generation_jobs(step_id, product_id)
        assert result["state"] == "completed" and result["image_result"]["success"] == 1
    finally:
        poller.prepare_aplus_image_work, poller.submit_aplus_image_generation, poller.finalize_aplus_image_payload = originals


async def _test_definite_submit_failure_is_terminal() -> None:
    product_id, _run_id, step_id = await _fixture("submit-failure")

    async def fake_prepare(_product_id: int) -> dict:
        return {
            "product_id": _product_id,
            "product_key": "SUBMIT-FAILURE",
            "brand": "Test",
            "output_dir": "/tmp",
            "expected_count": 1,
            "work_items": [{"script": {"module_position": 1, "prompt": "failure"}, "output_path": "/tmp/submit-failure.jpg"}],
        }

    async def fake_submit(_script: dict, **_kwargs) -> dict:
        return {"state": "failed", "provider_result": {"error_code": "submit_outcome_unknown"}}

    originals = poller.prepare_aplus_image_work, poller.submit_aplus_image_generation
    poller.prepare_aplus_image_work = fake_prepare
    poller.submit_aplus_image_generation = fake_submit
    try:
        result = await poller.submit_aplus_generation_jobs(step_id, product_id)
        assert result["state"] == "failed"
        async with async_session() as db:
            job = await db.scalar(select(AplusImageGenerationJob).where(AplusImageGenerationJob.task_step_id == step_id))
            assert job is not None and job.status == "failed" and job.next_poll_at is None
    finally:
        poller.prepare_aplus_image_work, poller.submit_aplus_image_generation = originals


async def _test_cancel_and_deadline() -> None:
    product_id, run_id, step_id = await _fixture("cancel", status=STEP_STATUS_WAITING_EXTERNAL)
    now = datetime.now()
    async with async_session() as db:
        run = await db.get(TaskRun, run_id)
        run.cancel_requested_at = now
        db.add(AplusImageGenerationJob(
            product_id=product_id, task_run_id=run_id, task_step_id=step_id,
            asset_slot_key="module:1", module_position=1, status="submitted", provider_task_id="cancel-me",
            request_fingerprint="c" * 64, idempotency_key=f"cancel-{step_id}", script_json='{"module_position": 1}',
            output_path="/tmp/cancel.jpg", product_key="CANCEL", next_poll_at=now, deadline_at=now + timedelta(minutes=5),
        ))
        await db.commit()
    assert await poller.cancel_aplus_jobs_for_run(run_id) == 1
    async with async_session() as db:
        assert (await db.get(TaskStep, step_id)).status == STEP_STATUS_CANCELED

    product_id, _run_id, step_id = await _fixture("deadline", status=STEP_STATUS_WAITING_EXTERNAL)
    async with async_session() as db:
        db.add(AplusImageGenerationJob(
            product_id=product_id, task_run_id=_run_id, task_step_id=step_id,
            asset_slot_key="module:1", module_position=1, status="submitted", provider_task_id="too-late",
            request_fingerprint="d" * 64, idempotency_key=f"deadline-{step_id}", script_json='{"module_position": 1}',
            output_path="/tmp/deadline.jpg", product_key="DEADLINE", next_poll_at=now - timedelta(seconds=2), deadline_at=now - timedelta(seconds=1),
        ))
        await db.commit()
    result = await poller.run_aplus_image_poll_batch()
    assert result["finalized_steps"] == 1
    async with async_session() as db:
        assert (await db.get(TaskStep, step_id)).status == STEP_STATUS_FAILED


async def _test_runner_releases_waiting_step() -> None:
    _product_id, _run_id, step_id = await _fixture("runner-release", status=STEP_STATUS_READY)

    async def wait_worker(_ctx):
        raise TaskStepWaitingExternal("waiting", {"provider_jobs": 1})

    register_worker("aplus_generate_product", wait_worker)
    assert await _execute_step(step_id, "test-worker") is True
    async with async_session() as db:
        step = await db.get(TaskStep, step_id)
        assert step.status == STEP_STATUS_WAITING_EXTERNAL
        assert step.locked_by is None and step.locked_until is None and step.finished_at is None


async def main() -> None:
    await run_schema_maintenance()
    await _test_batch_restart_and_success()
    await _test_provider_failure()
    await _test_immediate_result()
    await _test_definite_submit_failure_is_terminal()
    await _test_cancel_and_deadline()
    await _test_runner_releases_waiting_step()
    print("A+ durable async image jobs checks passed")


if __name__ == "__main__":
    asyncio.run(main())
