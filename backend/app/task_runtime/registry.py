from collections.abc import Awaitable, Callable, Iterable
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


def registered_worker_types() -> frozenset[str]:
    """Return a snapshot for startup diagnostics and integrity checks."""
    return frozenset(_workers)


def assert_workers_registered(step_types: Iterable[str], *, scope: str = "任务运行时") -> None:
    """Fail startup before any runnable task can be consumed without a worker."""
    missing = sorted({str(step_type) for step_type in step_types} - set(_workers))
    if missing:
        raise RuntimeError(f"{scope}缺少 step worker 注册: {', '.join(missing)}")


def worker_for(step_type: str) -> TaskWorker:
    worker = _workers.get(step_type)
    if not worker:
        raise RuntimeError(f"未注册新任务 step worker: {step_type}")
    return worker
