from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import TaskStep, TaskStepEvent
from app.task_runtime.json_utils import json_dumps


async def emit_event(
    db: AsyncSession,
    *,
    step: TaskStep,
    event_type: str,
    message: str | None = None,
    data: dict[str, Any] | None = None,
) -> None:
    db.add(
        TaskStepEvent(
            task_run_id=step.task_run_id,
            task_group_id=step.task_group_id,
            task_step_id=step.id,
            event_type=event_type,
            message=message,
            data_json=json_dumps(data or {}) if data is not None else None,
            created_at=datetime.now(),
        )
    )


async def update_step_progress(
    db: AsyncSession,
    step: TaskStep,
    *,
    current: int,
    total: int,
    message: str | None = None,
    data: dict[str, Any] | None = None,
) -> None:
    now = datetime.now()
    step.progress_current = max(0, current)
    step.progress_total = max(0, total)
    step.heartbeat_at = now
    step.updated_at = now
    await emit_event(
        db,
        step=step,
        event_type="progress",
        message=message,
        data={
            "progress_current": step.progress_current,
            "progress_total": step.progress_total,
            **(data or {}),
        },
    )
    await db.commit()
