from __future__ import annotations

"""TaskAction is the Product-domain adapter layer, not the whole V1 runtime.

V1 task runtime still supports generic planner/worker tasks such as GIGA pull,
catalog export, A+, and inventory/price sync. Only product_image_analysis and
product_listing_generation are actionized in the current PRD scope.
"""

from dataclasses import dataclass, field
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import TaskRun, TaskStep


@dataclass(frozen=True)
class TaskStepPlan:
    step_key: str
    step_type: str
    title: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    sort_order: int = 1
    max_attempts: int = 1


@dataclass(frozen=True)
class TaskGroupPlan:
    group_key: str
    title: str
    steps: list[TaskStepPlan]
    sort_order: int = 1
    depends_on_group_keys: list[str] = field(default_factory=list)
    failure_policy: str = "require_all_success"
    retry_policy: str = "failed_steps_only"


@dataclass(frozen=True)
class TaskRunPlan:
    task_type: str
    title: str
    groups: list[TaskGroupPlan]
    payload: dict[str, Any] = field(default_factory=dict)


class TaskAction(Protocol):
    action_type: str

    async def validate(self, db: AsyncSession, payload: dict[str, Any]) -> None:
        """Validate business preconditions before creating a task run."""

    def dedupe_key(self, payload: dict[str, Any]) -> str | None:
        """Return an opaque active-run mutual exclusion key."""

    def correlation_key(self, payload: dict[str, Any]) -> str | None:
        """Return an opaque historical lineage key."""

    async def reserve(self, db: AsyncSession, payload: dict[str, Any], run: TaskRun) -> None:
        """Project queued state to the business domain after the run is created."""

    def build_plan(self, payload: dict[str, Any]) -> TaskRunPlan:
        """Build task groups and steps for persistence."""

    async def execute_step(self, db: AsyncSession, step: TaskStep, payload: dict[str, Any]) -> dict[str, Any]:
        """Execute the business step and return a step result."""

    async def on_step_success(self, db: AsyncSession, step: TaskStep, result: dict[str, Any]) -> None:
        """Project business success state after the step succeeds."""

    async def on_step_failure(self, db: AsyncSession, step: TaskStep, error: Exception) -> None:
        """Project business failure state after the step fails."""

    async def on_step_interrupted(self, db: AsyncSession, step: TaskStep, reason: str | None = None) -> None:
        """Project business interrupted state after runtime recovery or manual interrupt."""

    async def on_cancel_requested(self, db: AsyncSession, run: TaskRun, reason: str | None = None) -> None:
        """Project business cancel-request state."""


_actions: dict[str, TaskAction] = {}


def register_action(action: TaskAction) -> None:
    _actions[action.action_type] = action


def action_for(action_type: str) -> TaskAction:
    action = _actions.get(action_type)
    if not action:
        raise RuntimeError(f"未注册 TaskAction: {action_type}")
    return action


def all_actions() -> dict[str, TaskAction]:
    return dict(_actions)
