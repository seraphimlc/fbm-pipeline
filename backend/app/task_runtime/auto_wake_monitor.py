"""Durable, conservative recovery for task-runtime steps that were never claimed or became stale."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from collections.abc import Iterable
from datetime import datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import selectinload

from app.config import settings
from app.database import async_session
from app.models import TaskGroup, TaskRun, TaskStep, TaskStepEvent
from app.task_runtime.constants import (
    RUN_STATUS_PENDING,
    RUN_STATUS_RUNNING,
    STEP_STATUS_PENDING,
    STEP_STATUS_READY,
    STEP_STATUS_RUNNING,
)
from app.task_runtime.events import emit_event
from app.task_runtime.json_utils import json_loads
from app.task_runtime.scheduler import kick_task_runtime

logger = logging.getLogger(__name__)

AUTO_WAKE_EVENT_TYPE = "auto_wake"
AUTO_WAKE_LIMIT_EVENT_TYPE = "auto_wake_limit"
STALE_HEARTBEAT_SECONDS = 600

# These indicate a defect in our process/code/configuration.  A scheduler must not hide one by
# repeatedly rerunning it.  Unknown error text is also skipped when a stale step has an error.
SYSTEM_EXCEPTION_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\b(?:type|attribute|key|index|value|assertion|runtime|syntax|name|import|module\s+not\s+found)error\b",
        r"\b(?:missinggreenlet|operationalerror|integrityerror|programmingerror|databaseerror)\b",
        r"\btaskoutcomecontracterror\b",
        r"\b(traceback|configuration error|adapter_not_configured|not configured)\b",
    )
)
TRANSIENT_FAILURE_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\b(?:timeout|timed out|connection reset|connection aborted|temporarily unavailable)\b",
        r"\b(?:rate limit(?:ed)?|too many requests|http 429|http 5\d\d)\b",
        r"\b(?:network|dns|browser.*(?:closed|disconnected)|executor.*not.*claim)\b",
    )
)


def _compact(value: str | None) -> str:
    return " ".join(str(value or "").split())[:1000]


def classify_system_exception(error_message: str | None) -> str | None:
    """Return a reason when the error should stay for engineering diagnosis, not auto-wake."""
    normalized = _compact(error_message)
    if not normalized:
        return None
    for pattern in SYSTEM_EXCEPTION_PATTERNS:
        if pattern.search(normalized):
            return "检测到系统代码、配置或数据库异常"
    for pattern in TRANSIENT_FAILURE_PATTERNS:
        if pattern.search(normalized):
            return None
    # A stale step with a message is ambiguous.  Fail closed instead of consuming external quota.
    return "卡死步骤存在未分类错误，等待人工确认"


def issue_fingerprint(*, issue_kind: str, error_message: str | None = None) -> str:
    normalized = _compact(error_message).lower()
    raw = f"{issue_kind}|{normalized}".encode("utf-8")
    return f"{issue_kind}:{hashlib.sha256(raw).hexdigest()[:20]}"


def _event_attempt_count(events: Iterable[TaskStepEvent], fingerprint: str) -> int:
    count = 0
    for event in events:
        if event.event_type != AUTO_WAKE_EVENT_TYPE:
            continue
        data = json_loads(event.data_json, {})
        if isinstance(data, dict) and data.get("issue_fingerprint") == fingerprint and data.get("action") == "woke":
            count += 1
    return count


def _has_limit_event(events: Iterable[TaskStepEvent], fingerprint: str) -> bool:
    for event in events:
        if event.event_type != AUTO_WAKE_LIMIT_EVENT_TYPE:
            continue
        data = json_loads(event.data_json, {})
        if isinstance(data, dict) and data.get("issue_fingerprint") == fingerprint:
            return True
    return False


def _has_action_event(events: Iterable[TaskStepEvent], fingerprint: str, action: str) -> bool:
    for event in events:
        if event.event_type != AUTO_WAKE_EVENT_TYPE:
            continue
        data = json_loads(event.data_json, {})
        if isinstance(data, dict) and data.get("issue_fingerprint") == fingerprint and data.get("action") == action:
            return True
    return False


def _stale_issue_kind(step: TaskStep, now: datetime) -> str | None:
    if step.status != STEP_STATUS_RUNNING:
        return None
    if step.locked_until is None or step.locked_until < now:
        return "stale_lock"
    if step.heartbeat_at and step.heartbeat_at < now - timedelta(seconds=STALE_HEARTBEAT_SECONDS):
        return "stale_heartbeat"
    return None


def _is_unactivated_initial_step(step: TaskStep, group: TaskGroup) -> bool:
    """Recognize only a safe, stranded first step from an auto-start task.

    A normal planner persists its first step as ``ready``.  ``pending`` is
    therefore recoverable only when it is the first step in the first group,
    every step in that group is still pending, and it has never been leased.
    This deliberately excludes later/dependent work, where promoting a step
    could bypass a group dependency or failure policy.
    """
    if step.status != STEP_STATUS_PENDING or group.sort_order != 1:
        return False
    if step.locked_by or step.locked_until or step.started_at or step.finished_at:
        return False
    steps = sorted(group.steps, key=lambda item: (item.sort_order, item.id))
    return bool(steps) and steps[0].id == step.id and all(item.status == STEP_STATUS_PENDING for item in steps)


def _ready_step_needs_wake(*, healthy_serial_work_active: bool) -> bool:
    """A ready step behind the one serial worker is normal queueing, not a fault."""
    return not healthy_serial_work_active


async def run_auto_wake_scan_once() -> dict[str, int]:
    """Scan eligible steps once.  Each successful wake is persisted in task_step_events."""
    now = datetime.now()
    stats = {"scanned": 0, "woke": 0, "skipped_system_error": 0, "waiting_serial": 0, "limit_reached": 0}
    stale_before = now - timedelta(seconds=STALE_HEARTBEAT_SECONDS)
    should_kick = False

    async with async_session() as db:
        # The runtime deliberately executes one step globally at a time.  Ready
        # work waiting behind a healthy holder is expected and must not consume
        # its auto-wake budget or create misleading recovery events.
        healthy_serial_work_active = bool(
            await db.scalar(
                select(TaskStep.id)
                .join(TaskRun, TaskRun.id == TaskStep.task_run_id)
                .where(TaskRun.status == RUN_STATUS_RUNNING)
                .where(TaskRun.cancel_requested_at.is_(None))
                .where(TaskRun.superseded_by_run_id.is_(None))
                .where(TaskStep.status == STEP_STATUS_RUNNING)
                .where(TaskStep.locked_until.is_not(None))
                .where(TaskStep.locked_until >= now)
                .where(TaskStep.heartbeat_at.is_not(None))
                .where(TaskStep.heartbeat_at >= stale_before)
                .limit(1)
            )
        )
        result = await db.execute(
            select(TaskStep, TaskRun, TaskGroup)
            .join(TaskRun, TaskRun.id == TaskStep.task_run_id)
            .join(TaskGroup, TaskGroup.id == TaskStep.task_group_id)
            .where(TaskRun.status.in_((RUN_STATUS_PENDING, RUN_STATUS_RUNNING)))
            .where(TaskRun.cancel_requested_at.is_(None))
            .where(TaskRun.superseded_by_run_id.is_(None))
            .where(
                or_(
                    TaskStep.status == STEP_STATUS_READY,
                    # A service restart between plan persistence and runner
                    # scheduling can leave the first auto-start step pending.
                    # It is filtered again below with a strict structural
                    # guard before being made ready.
                    (TaskStep.status == STEP_STATUS_PENDING) & (TaskGroup.sort_order == 1),
                    (TaskStep.status == STEP_STATUS_RUNNING)
                    & or_(
                        TaskStep.locked_until.is_(None),
                        TaskStep.locked_until < now,
                        TaskStep.heartbeat_at < stale_before,
                    ),
                )
            )
            .order_by(TaskRun.id.asc(), TaskStep.sort_order.asc(), TaskStep.id.asc())
        )
        candidates = result.all()
        if not candidates:
            return stats

        step_ids = [step.id for step, _run, _group in candidates]
        event_result = await db.execute(
            select(TaskStepEvent)
            .where(TaskStepEvent.task_step_id.in_(step_ids))
            .where(TaskStepEvent.event_type.in_((AUTO_WAKE_EVENT_TYPE, AUTO_WAKE_LIMIT_EVENT_TYPE)))
        )
        events_by_step: dict[int, list[TaskStepEvent]] = {}
        for event in event_result.scalars():
            if event.task_step_id is not None:
                events_by_step.setdefault(event.task_step_id, []).append(event)

        pending_group_ids = [group.id for step, _run, group in candidates if step.status == STEP_STATUS_PENDING]
        if pending_group_ids:
            await db.execute(
                select(TaskGroup)
                .where(TaskGroup.id.in_(pending_group_ids))
                .options(selectinload(TaskGroup.steps))
            )

        for step, run, group in candidates:
            stats["scanned"] += 1
            if step.status == STEP_STATUS_READY:
                if not _ready_step_needs_wake(healthy_serial_work_active=healthy_serial_work_active):
                    stats["waiting_serial"] += 1
                    continue
                issue_kind = "ready_not_claimed"
            elif step.status == STEP_STATUS_PENDING:
                issue_kind = "unactivated_initial_step" if _is_unactivated_initial_step(step, group) else None
            else:
                issue_kind = _stale_issue_kind(step, now)
            if not issue_kind:
                continue
            error_message = _compact(step.error_message)
            fingerprint = issue_fingerprint(issue_kind=issue_kind, error_message=error_message)
            events = events_by_step.get(step.id, [])
            system_reason = classify_system_exception(error_message) if issue_kind != "ready_not_claimed" else None
            if system_reason:
                if not _has_action_event(events, fingerprint, "skipped_system_error"):
                    await emit_event(
                        db,
                        step=step,
                        event_type=AUTO_WAKE_EVENT_TYPE,
                        message=f"自动巡检未唤醒：{system_reason}",
                        data={"action": "skipped_system_error", "issue_fingerprint": fingerprint, "issue_kind": issue_kind},
                    )
                stats["skipped_system_error"] += 1
                continue

            attempts = _event_attempt_count(events, fingerprint)
            max_attempts = max(1, settings.TASK_RUNTIME_AUTO_WAKE_MAX_ATTEMPTS_PER_ISSUE)
            if attempts >= max_attempts:
                if not _has_limit_event(events, fingerprint):
                    await emit_event(
                        db,
                        step=step,
                        event_type=AUTO_WAKE_LIMIT_EVENT_TYPE,
                        message=f"自动巡检停止唤醒：同一问题已达到 {attempts} 次上限",
                        data={"issue_fingerprint": fingerprint, "issue_kind": issue_kind, "attempts": attempts},
                    )
                stats["limit_reached"] += 1
                continue

            if issue_kind == "unactivated_initial_step":
                step.status = STEP_STATUS_READY
                step.updated_at = now
                group.status = RUN_STATUS_RUNNING
                group.started_at = group.started_at or now
                group.finished_at = None
                group.updated_at = now
                run.status = RUN_STATUS_RUNNING
                run.finished_at = None
                run.updated_at = now
            elif issue_kind != "ready_not_claimed":
                # Unlike recover_task_runtime(), this is a targeted wake: restore the exact stale
                # step to ready so the normal runner can claim it.  Do not mark it interrupted.
                step.status = STEP_STATUS_READY
                step.locked_by = None
                step.locked_until = None
                step.heartbeat_at = None
                step.finished_at = None
                step.updated_at = now
                run.status = RUN_STATUS_RUNNING
                run.finished_at = None
                run.updated_at = now
            next_attempt = attempts + 1
            await emit_event(
                db,
                step=step,
                event_type=AUTO_WAKE_EVENT_TYPE,
                message=f"自动巡检唤醒执行器（同一问题第 {next_attempt}/{max_attempts} 次）",
                data={"action": "woke", "issue_fingerprint": fingerprint, "issue_kind": issue_kind, "attempt": next_attempt},
            )
            stats["woke"] += 1
            should_kick = True
        await db.commit()

    if should_kick:
        kick_task_runtime()
    logger.info("[TaskRuntimeAutoWake] scan completed: %s", stats)
    return stats


async def auto_wake_monitor_loop() -> None:
    """Wait one interval before the first scan, then keep monitoring until application shutdown."""
    interval = max(60, settings.TASK_RUNTIME_AUTO_WAKE_INTERVAL_SECONDS)
    logger.info("[TaskRuntimeAutoWake] enabled; interval=%ss max_attempts=%s", interval, settings.TASK_RUNTIME_AUTO_WAKE_MAX_ATTEMPTS_PER_ISSUE)
    while True:
        await asyncio.sleep(interval)
        try:
            await run_auto_wake_scan_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("[TaskRuntimeAutoWake] scan failed")
