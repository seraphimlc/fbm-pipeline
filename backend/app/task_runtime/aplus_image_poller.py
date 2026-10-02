from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import datetime, timedelta
import hashlib
import json
import logging
from pathlib import Path
from uuid import uuid4

from sqlalchemy import or_, select, update
from sqlalchemy.orm import selectinload

from app.config import settings
from app.database import async_session
from app.models import AplusImageGenerationJob, TaskRun, TaskStep
from app.pipeline.step9_aplus_image import (
    _persist_aplus_image_results,
    _reference_image_sources,
    finalize_aplus_image_payload,
    poll_aplus_image_generation,
    prepare_aplus_image_work,
    submit_aplus_image_generation,
)
from app.task_runtime.constants import (
    STEP_STATUS_CANCELED,
    STEP_STATUS_FAILED,
    STEP_STATUS_SUCCEEDED,
    STEP_STATUS_WAITING_EXTERNAL,
)
from app.task_runtime.events import emit_event
from app.task_runtime.json_utils import json_dumps, json_loads

logger = logging.getLogger(__name__)

ACTIVE_JOB_STATUSES = ("submitting", "submitted", "polling", "uploading")
TERMINAL_JOB_STATUSES = ("done", "failed", "canceled")
JOB_LOCK_SECONDS = 10 * 60


def _slot_key(script: dict) -> str:
    asset_slot_id = str(script.get("asset_slot_id") or script.get("slot_id") or "").strip()
    position = int(script.get("module_position") or script.get("position") or 0)
    return asset_slot_id or f"module:{position}"


def _reference_fingerprint(source: str) -> dict[str, str]:
    path = Path(source).expanduser()
    if source.startswith(("http://", "https://", "data:")) or not path.is_file():
        return {"source": source}
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return {"source": str(path.resolve()), "sha256": digest.hexdigest()}


def _request_fingerprint(script: dict, brand: str | None) -> str:
    payload = {
        "script": script,
        "brand": brand,
        "model": settings.resolved_gpt_image_model,
        "provider": settings.gpt_image_api_provider,
        "api_base": settings.resolved_gpt_image_api_base,
        "aspect_ratio": settings.APLUS_IMAGE_ASPECT_RATIO,
        "quality": settings.APLUS_IMAGE_GENERATION_QUALITY,
        "references": [_reference_fingerprint(source) for source in _reference_image_sources(script)],
    }
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def _next_poll_at(poll_count: int) -> datetime:
    delay = 10 if poll_count <= 0 else 15 if poll_count == 1 else 30
    return datetime.now() + timedelta(seconds=delay)


def _provider_result_snapshot(value):
    if isinstance(value, list):
        return [_provider_result_snapshot(item) for item in value]
    if not isinstance(value, dict):
        return value
    snapshot = {}
    for key, item in value.items():
        if key == "b64_json" and isinstance(item, str):
            snapshot[key] = {
                "omitted": True,
                "encoded_length": len(item),
                "sha256": hashlib.sha256(item.encode("ascii", errors="ignore")).hexdigest(),
            }
        else:
            snapshot[key] = _provider_result_snapshot(item)
    return snapshot


async def _create_or_reuse_jobs(task_step_id: int, product_id: int) -> list[int]:
    work = await prepare_aplus_image_work(product_id)
    now = datetime.now()
    async with async_session() as db:
        step = await db.get(TaskStep, task_step_id)
        if step is None:
            raise RuntimeError(f"A+ task step 不存在: {task_step_id}")
        existing = list((await db.execute(
            select(AplusImageGenerationJob)
            .where(AplusImageGenerationJob.task_step_id == task_step_id)
            .order_by(AplusImageGenerationJob.id.asc())
        )).scalars().all())
        by_slot = {job.asset_slot_key: job for job in existing}
        expected_slots = {_slot_key(item["script"]) for item in work["work_items"]}
        if set(by_slot) - expected_slots:
            raise RuntimeError("A+脚本 slot 与已提交 provider job 不一致，禁止覆盖既有 provider task")
        for item in work["work_items"]:
            script = item["script"]
            slot_key = _slot_key(script)
            fingerprint = _request_fingerprint(script, work["brand"])
            job = by_slot.get(slot_key)
            if job:
                if job.request_fingerprint != fingerprint:
                    raise RuntimeError(f"A+脚本已变化但 slot {slot_key} 存在 provider job，需新建 A+ 任务")
                if job.status in {"failed", "canceled"}:
                    job.status = "submitting"
                    job.provider_task_id = None
                    job.provider_result_json = None
                    job.result_json = None
                    job.error_message = None
                    job.poll_count = 0
                    job.next_poll_at = now
                    job.deadline_at = now + timedelta(seconds=max(60, settings.APLUS_IMAGE_POLL_DEADLINE_SECONDS))
                    job.idempotency_key = f"aplus:{step.id}:{slot_key}:{fingerprint[:12]}:retry:{uuid4().hex[:12]}"
                    job.finished_at = None
                    job.updated_at = now
                continue
            position = int(script.get("module_position") or script.get("position") or 0)
            job = AplusImageGenerationJob(
                product_id=product_id,
                task_run_id=step.task_run_id,
                task_step_id=step.id,
                asset_slot_key=slot_key,
                module_position=position,
                asset_slot_id=str(script.get("asset_slot_id") or "").strip() or None,
                status="submitting",
                request_fingerprint=fingerprint,
                idempotency_key=f"aplus:{step.id}:{slot_key}:{fingerprint[:16]}",
                script_json=json_dumps(script),
                output_path=item["output_path"],
                product_key=work["product_key"],
                brand=work["brand"],
                next_poll_at=now,
                deadline_at=now + timedelta(seconds=max(60, settings.APLUS_IMAGE_POLL_DEADLINE_SECONDS)),
                created_at=now,
                updated_at=now,
            )
            db.add(job)
            await db.flush()
            by_slot[slot_key] = job
        await db.commit()
        return [job.id for job in sorted(by_slot.values(), key=lambda value: (value.module_position, value.id))]


async def _finish_image_job(job: AplusImageGenerationJob, image_payload: dict) -> dict:
    script = json_loads(job.script_json, {})
    if not isinstance(script, dict):
        raise RuntimeError("A+ provider job script_json 无效")
    return await asyncio.to_thread(
        finalize_aplus_image_payload,
        script,
        image_payload,
        output_path=Path(job.output_path),
        product_key=job.product_key,
        brand=job.brand,
    )


async def _apply_provider_result(job_id: int, result: dict) -> None:
    async with async_session() as db:
        job = await db.get(AplusImageGenerationJob, job_id)
        if job is None or job.status not in ACTIVE_JOB_STATUSES:
            return
        now = datetime.now()
        state = result.get("state")
        job.provider_task_id = result.get("provider_task_id") or job.provider_task_id
        provider_result = result.get("provider_result")
        if provider_result is not None:
            job.provider_result_json = json_dumps(_provider_result_snapshot(provider_result))
        if state == "completed":
            job.submitted_at = job.submitted_at or now
            job.status = "uploading"
            job.updated_at = now
            await db.commit()
            try:
                item = await _finish_image_job(job, result["image_payload"])
            except Exception as exc:
                job.status = "failed"
                job.error_message = f"{type(exc).__name__}: {exc}"
            else:
                job.status = "done"
                job.result_json = json_dumps(item)
                job.error_message = None
            job.finished_at = datetime.now()
            job.next_poll_at = None
        elif state == "failed":
            job.submitted_at = job.submitted_at or now
            job.status = "failed"
            job.error_message = f"图片任务失败: {json_dumps(provider_result)[:800]}"
            job.finished_at = now
            job.next_poll_at = None
        else:
            job.status = "submitted" if job.provider_task_id else "submitting"
            if job.provider_task_id:
                job.submitted_at = job.submitted_at or now
            job.poll_count = int(job.poll_count or 0) + 1
            job.next_poll_at = _next_poll_at(job.poll_count)
        job.locked_by = None
        job.locked_until = None
        job.updated_at = datetime.now()
        await db.commit()


async def _process_job(job_id: int, worker_id: str) -> None:
    async with async_session() as db:
        job = await db.get(AplusImageGenerationJob, job_id)
        if job is None or job.status not in ACTIVE_JOB_STATUSES or job.locked_by != worker_id:
            return
        if job.deadline_at <= datetime.now():
            job.status = "failed"
            job.error_message = f"图片任务超过等待期限: {job.provider_task_id or job.id}"
            job.finished_at = datetime.now()
            job.next_poll_at = None
            job.locked_by = None
            job.locked_until = None
            await db.commit()
            return
        script = json_loads(job.script_json, {})
        provider_task_id = job.provider_task_id
        idempotency_key = job.idempotency_key
        brand = job.brand
    try:
        if provider_task_id:
            result = await poll_aplus_image_generation(provider_task_id)
            result["provider_task_id"] = provider_task_id
        else:
            result = await submit_aplus_image_generation(
                script,
                brand=brand,
                idempotency_key=idempotency_key,
            )
        await _apply_provider_result(job_id, result)
    except Exception as exc:
        logger.warning("[AplusPoller] provider job 暂时失败 job_id=%s: %s: %s", job_id, type(exc).__name__, exc)
        async with async_session() as db:
            job = await db.get(AplusImageGenerationJob, job_id)
            if job is None or job.status not in ACTIVE_JOB_STATUSES:
                return
            job.error_message = f"{type(exc).__name__}: {exc}"
            job.poll_count = int(job.poll_count or 0) + 1
            job.next_poll_at = _next_poll_at(job.poll_count)
            job.locked_by = None
            job.locked_until = None
            job.updated_at = datetime.now()
            await db.commit()


async def _finalize_step_if_ready(task_step_id: int) -> bool:
    async with async_session() as db:
        step = (await db.execute(
            select(TaskStep)
            .where(TaskStep.id == task_step_id)
            .options(selectinload(TaskStep.task_run), selectinload(TaskStep.task_group))
        )).scalar_one_or_none()
        if step is None or step.status != STEP_STATUS_WAITING_EXTERNAL:
            return False
        jobs = list((await db.execute(
            select(AplusImageGenerationJob)
            .where(AplusImageGenerationJob.task_step_id == task_step_id)
            .order_by(AplusImageGenerationJob.module_position.asc(), AplusImageGenerationJob.id.asc())
        )).scalars().all())
        if not jobs or any(job.status not in TERMINAL_JOB_STATUSES for job in jobs):
            return False
        now = datetime.now()
        product_id = jobs[0].product_id
        results = [json_loads(job.result_json, {}) for job in jobs if job.status == "done"]
        failed_jobs = [job for job in jobs if job.status == "failed"]
        canceled = bool(step.task_run.cancel_requested_at) or any(job.status == "canceled" for job in jobs)

    success_count = len(results)
    await _persist_aplus_image_results(
        product_id=product_id,
        image_results=results + [
            {"position": job.module_position, "asset_slot_id": job.asset_slot_id, "status": job.status, "error": job.error_message}
            for job in jobs if job.status != "done"
        ],
        success_count=success_count,
        expected_count=len(jobs),
    )
    from app.task_runtime.aplus_generate_workers import _set_aplus_status
    if canceled:
        await _set_aplus_status(product_id, "failed", error="A+生成已取消")
    elif failed_jobs:
        await _set_aplus_status(product_id, "failed", error=f"A+生成失败: {failed_jobs[0].error_message}")
    else:
        await _set_aplus_status(product_id, "done")

    async with async_session() as db:
        step = (await db.execute(
            select(TaskStep)
            .where(TaskStep.id == task_step_id)
            .options(selectinload(TaskStep.task_run), selectinload(TaskStep.task_group))
        )).scalar_one_or_none()
        if step is None or step.status != STEP_STATUS_WAITING_EXTERNAL:
            return False
        now = datetime.now()
        step.locked_by = None
        step.locked_until = None
        step.heartbeat_at = now
        step.finished_at = now
        step.updated_at = now
        if canceled:
            step.status = STEP_STATUS_CANCELED
            step.error_message = "A+生成已取消"
            event_type, message = "status", step.error_message
        elif failed_jobs:
            step.status = STEP_STATUS_FAILED
            step.error_message = f"A+出图未全部成功: {success_count}/{len(jobs)}. {failed_jobs[0].error_message}"
            event_type, message = "error", step.error_message
        else:
            payload = {
                "product_id": product_id,
                "status": "done",
                "image_result": {
                    "total": len(jobs),
                    "success": success_count,
                    "generated": success_count,
                    "results": results,
                },
            }
            step.status = STEP_STATUS_SUCCEEDED
            step.result_json = json_dumps(payload)
            step.error_message = None
            step.progress_current = step.progress_total or 3
            step.task_run.summary_json = json_dumps({"product_id": product_id, "status": "aplus_done"})
            event_type, message = "status", "A+ 外部生图任务全部完成"
        await emit_event(db, step=step, event_type=event_type, message=message)
        await db.commit()
        run_id = step.task_run_id

    from app.task_runtime.scheduler import _refresh_group_and_run, kick_task_runtime
    async with async_session() as db:
        await _refresh_group_and_run(db, run_id)
    kick_task_runtime()
    return True


async def submit_aplus_generation_jobs(task_step_id: int, product_id: int) -> dict:
    job_ids = await _create_or_reuse_jobs(task_step_id, product_id)
    worker_id = f"aplus-submit-{uuid4().hex[:12]}"
    now = datetime.now()
    async with async_session() as db:
        for job_id in job_ids:
            await db.execute(
                update(AplusImageGenerationJob)
                .where(
                    AplusImageGenerationJob.id == job_id,
                    AplusImageGenerationJob.status == "submitting",
                    or_(AplusImageGenerationJob.locked_until.is_(None), AplusImageGenerationJob.locked_until < now),
                )
                .values(locked_by=worker_id, locked_until=now + timedelta(seconds=JOB_LOCK_SECONDS), updated_at=now)
            )
        await db.commit()
    for job_id in job_ids:
        await _process_job(job_id, worker_id)
    async with async_session() as db:
        jobs = list((await db.execute(
            select(AplusImageGenerationJob)
            .where(AplusImageGenerationJob.task_step_id == task_step_id)
            .order_by(AplusImageGenerationJob.module_position.asc(), AplusImageGenerationJob.id.asc())
        )).scalars().all())
    if jobs and all(job.status == "done" for job in jobs):
        results = [json_loads(job.result_json, {}) for job in jobs]
        await _persist_aplus_image_results(
            product_id=product_id,
            image_results=results,
            success_count=len(results),
            expected_count=len(jobs),
        )
        return {
            "state": "completed",
            "job_ids": job_ids,
            "image_result": {"total": len(jobs), "success": len(jobs), "generated": len(jobs), "results": results},
        }
    if jobs and all(job.status in TERMINAL_JOB_STATUSES for job in jobs):
        failed = next((job for job in jobs if job.status != "done"), None)
        return {
            "state": "failed",
            "job_ids": job_ids,
            "completed": sum(job.status == "done" for job in jobs),
            "total": len(jobs),
            "error": failed.error_message if failed else "A+ provider job failed",
        }
    return {
        "state": "waiting_external",
        "job_ids": job_ids,
        "submitted": sum(job.status in {"submitted", "polling"} for job in jobs),
        "completed": sum(job.status == "done" for job in jobs),
        "total": len(jobs),
    }


async def run_aplus_image_poll_batch() -> dict[str, int]:
    now = datetime.now()
    worker_id = f"aplus-poll-{uuid4().hex[:12]}"
    limit = max(1, settings.APLUS_IMAGE_POLL_BATCH_SIZE)
    async with async_session() as db:
        inactive_run_ids = select(TaskRun.id).where(
            or_(TaskRun.cancel_requested_at.is_not(None), TaskRun.superseded_by_run_id.is_not(None))
        )
        await db.execute(
            update(AplusImageGenerationJob)
            .where(AplusImageGenerationJob.task_run_id.in_(inactive_run_ids))
            .where(AplusImageGenerationJob.status.in_(ACTIVE_JOB_STATUSES))
            .values(
                status="canceled",
                error_message="所属任务已取消或被取代",
                next_poll_at=None,
                locked_by=None,
                locked_until=None,
                finished_at=now,
                updated_at=now,
            )
        )
        candidate_ids = list((await db.execute(
            select(AplusImageGenerationJob.id)
            .join(TaskRun, TaskRun.id == AplusImageGenerationJob.task_run_id)
            .where(AplusImageGenerationJob.status.in_(ACTIVE_JOB_STATUSES))
            .where(AplusImageGenerationJob.next_poll_at.is_not(None))
            .where(AplusImageGenerationJob.next_poll_at <= now)
            .where(TaskRun.superseded_by_run_id.is_(None))
            .where(TaskRun.cancel_requested_at.is_(None))
            .where(or_(AplusImageGenerationJob.locked_until.is_(None), AplusImageGenerationJob.locked_until < now))
            .order_by(AplusImageGenerationJob.next_poll_at.asc(), AplusImageGenerationJob.id.asc())
            .limit(limit)
        )).scalars().all())
        claimed: list[int] = []
        for job_id in candidate_ids:
            result = await db.execute(
                update(AplusImageGenerationJob)
                .where(
                    AplusImageGenerationJob.id == job_id,
                    AplusImageGenerationJob.status.in_(ACTIVE_JOB_STATUSES),
                    or_(AplusImageGenerationJob.locked_until.is_(None), AplusImageGenerationJob.locked_until < now),
                )
                .values(locked_by=worker_id, locked_until=now + timedelta(seconds=JOB_LOCK_SECONDS), updated_at=now)
            )
            if result.rowcount == 1:
                claimed.append(job_id)
        await db.commit()
    semaphore = asyncio.Semaphore(max(1, settings.APLUS_IMAGE_POLL_CONCURRENCY))

    async def process(job_id: int) -> None:
        async with semaphore:
            await _process_job(job_id, worker_id)

    await asyncio.gather(*(process(job_id) for job_id in claimed))
    async with async_session() as db:
        step_ids = set((await db.execute(
            select(AplusImageGenerationJob.task_step_id)
            .where(AplusImageGenerationJob.id.in_(claimed))
        )).scalars().all()) if claimed else set()
    finalized = 0
    for step_id in step_ids:
        finalized += int(await _finalize_step_if_ready(step_id))
    return {"claimed": len(claimed), "finalized_steps": finalized}


async def cancel_aplus_jobs_for_run(run_id: int) -> int:
    now = datetime.now()
    async with async_session() as db:
        step_ids = set((await db.execute(
            select(AplusImageGenerationJob.task_step_id)
            .where(AplusImageGenerationJob.task_run_id == run_id)
            .where(AplusImageGenerationJob.status.in_(ACTIVE_JOB_STATUSES))
        )).scalars().all())
        result = await db.execute(
            update(AplusImageGenerationJob)
            .where(AplusImageGenerationJob.task_run_id == run_id)
            .where(AplusImageGenerationJob.status.in_(ACTIVE_JOB_STATUSES))
            .values(
                status="canceled",
                error_message="用户取消",
                next_poll_at=None,
                locked_by=None,
                locked_until=None,
                finished_at=now,
                updated_at=now,
            )
        )
        await db.commit()
        changed = int(result.rowcount or 0)
    for step_id in step_ids:
        await _finalize_step_if_ready(step_id)
    return changed


async def aplus_image_poller_loop() -> None:
    while True:
        try:
            await run_aplus_image_poll_batch()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("[AplusPoller] batch scan failed")
        await asyncio.sleep(max(1, settings.APLUS_IMAGE_POLL_SCAN_INTERVAL_SECONDS))


async def stop_aplus_image_poller(task: asyncio.Task | None) -> None:
    if task is None:
        return
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task
