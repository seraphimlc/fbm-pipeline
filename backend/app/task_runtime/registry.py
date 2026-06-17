from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import TaskGroup, TaskRun, TaskStep


@dataclass
class TaskContext:
    db: AsyncSession
    run: TaskRun
    group: TaskGroup
    step: TaskStep


TaskWorker = Callable[[TaskContext], Awaitable[dict[str, Any] | None]]

_workers: dict[str, TaskWorker] = {}


def register_worker(step_type: str, worker: TaskWorker) -> None:
    _workers[step_type] = worker


def worker_for(step_type: str) -> TaskWorker:
    worker = _workers.get(step_type)
    if not worker:
        raise RuntimeError(f"未注册新任务 step worker: {step_type}")
    return worker
