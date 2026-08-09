from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.models import TaskGroup, TaskStep, TaskStepEvent
from app.task_runtime.auto_wake_monitor import (
    _event_attempt_count,
    _is_unactivated_initial_step,
    _ready_step_needs_wake,
    classify_system_exception,
    issue_fingerprint,
)
from app.task_runtime.constants import STEP_STATUS_PENDING, STEP_STATUS_READY
from app.task_runtime.json_utils import json_dumps


def main() -> None:
    assert classify_system_exception("TypeError: unexpected keyword argument")
    assert classify_system_exception("adapter_not_configured")
    assert classify_system_exception("supplier request exceeded timeout") is None
    assert classify_system_exception(None) is None
    assert issue_fingerprint(issue_kind="stale_lock", error_message="timeout") == issue_fingerprint(
        issue_kind="stale_lock", error_message=" timeout \n"
    )
    assert issue_fingerprint(issue_kind="stale_lock", error_message="timeout") != issue_fingerprint(
        issue_kind="stale_heartbeat", error_message="timeout"
    )
    fingerprint = issue_fingerprint(issue_kind="ready_not_claimed")
    events = [
        TaskStepEvent(event_type="auto_wake", data_json=json_dumps({"action": "woke", "issue_fingerprint": fingerprint})),
        TaskStepEvent(event_type="auto_wake", data_json=json_dumps({"action": "skipped_system_error", "issue_fingerprint": fingerprint})),
        TaskStepEvent(event_type="auto_wake", data_json=json_dumps({"action": "woke", "issue_fingerprint": "other"})),
    ]
    assert _event_attempt_count(events, fingerprint) == 1
    assert not _ready_step_needs_wake(healthy_serial_work_active=True)
    assert _ready_step_needs_wake(healthy_serial_work_active=False)

    first_group = TaskGroup(id=1, sort_order=1)
    first_step = TaskStep(id=1, status=STEP_STATUS_PENDING)
    first_group.steps = [first_step]
    assert _is_unactivated_initial_step(first_step, first_group)
    first_step.status = STEP_STATUS_READY
    assert not _is_unactivated_initial_step(first_step, first_group)
    later_group = TaskGroup(id=2, sort_order=2)
    later_step = TaskStep(id=2, status=STEP_STATUS_PENDING)
    later_group.steps = [later_step]
    assert not _is_unactivated_initial_step(later_step, later_group)


if __name__ == "__main__":
    main()
