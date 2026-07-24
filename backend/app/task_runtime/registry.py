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


@dataclass(frozen=True)
class TaskWorkerOutcome:
    payload: dict[str, Any]
    terminal_status: str
    event_type: str
    event_message: str
    propagate_single_step_run: bool = False


class TaskOutcomeContractError(RuntimeError):
    """Raised when a worker outcome cannot be projected safely by the scheduler."""


TaskWorkerResult = dict[str, Any] | TaskWorkerOutcome | None
TaskWorker = Callable[[TaskContext], Awaitable[TaskWorkerResult]]

_workers: dict[str, TaskWorker] = {}


def register_worker(step_type: str, worker: TaskWorker) -> None:
    _workers[step_type] = worker


def worker_for(step_type: str) -> TaskWorker:
    worker = _workers.get(step_type)
    if not worker:
        raise RuntimeError(f"未注册新任务 step worker: {step_type}")
    return worker
