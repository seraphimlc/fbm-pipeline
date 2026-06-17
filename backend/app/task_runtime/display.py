from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.models import TaskRun, TaskStep

RUN_STATUS_PENDING = "pending"
RUN_STATUS_RUNNING = "running"
RUN_STATUS_SUCCEEDED = "succeeded"
RUN_STATUS_FAILED = "failed"
RUN_STATUS_PARTIAL_FAILED = "partial_failed"
RUN_STATUS_INTERRUPTED = "interrupted"
RUN_STATUS_PAUSED = "paused"
RUN_STATUS_CANCELED = "canceled"

STEP_STATUS_PENDING = "pending"
STEP_STATUS_READY = "ready"
STEP_STATUS_RUNNING = "running"
STEP_STATUS_SUCCEEDED = "succeeded"
STEP_STATUS_FAILED = "failed"
STEP_STATUS_INTERRUPTED = "interrupted"
STEP_STATUS_CANCELED = "canceled"

HISTORY_DISPLAY_STATUSES = {"succeeded", "canceled", "superseded"}
DB_PAGEABLE_DISPLAY_STATUSES = {
    "queued",
    "running",
    "failed",
    "partial_failed",
    "interrupted",
    "paused",
    "cancel_requested",
    "canceled",
    "superseded",
    "succeeded",
}

STALE_HEARTBEAT_SECONDS = 600

DISPLAY_STATUS_LABELS = {
    "planned": "待规划",
    "waiting_dependency": "等待前置步骤",
    "queued": "排队中",
    "running": "执行中",
    "stale_running": "疑似卡住",
    "failed": "失败",
    "partial_failed": "部分失败",
    "interrupted": "已中断",
    "paused": "已挂起",
    "cancel_requested": "正在取消",
    "canceled": "已取消",
    "superseded": "已被新任务取代",
    "succeeded": "已完成",
}

STEP_TYPE_LABELS = {
    "giga_pull_plan": "规划 SKU",
    "giga_pull_detail_chunk": "SKU 详情",
    "giga_pull_inventory_chunk": "SKU 库存",
    "giga_pull_price_chunk": "SKU 价格",
    "giga_pull_finalize_snapshot": "快照校验",
    "giga_pull_aggregate_items": "聚合 Item/Group",
    "giga_pull_materialize_products": "生成商品草稿",
    "product_image_analysis": "图片分析",
    "product_listing_generation": "Listing 生成",
    "catalog_export_template": "导出文件",
    "aplus_generate_product": "A+生成",
    "giga_inventory_sync": "库存同步",
    "giga_price_sync": "价格同步",
    "product_bulk_advance_product": "提交商品生成任务",
}


def task_run_list_is_db_pageable(*, view: str, display_status_filter: str | None = None) -> bool:
    return view in {"current", "history", "all"} and (
        not display_status_filter or display_status_filter in DB_PAGEABLE_DISPLAY_STATUSES
    )


def task_run_matches_display_filters(
    *,
    display_status: str | None,
    view: str,
    display_status_filter: str | None = None,
) -> bool:
    if display_status_filter and display_status != display_status_filter:
        return False
    if view == "current":
        return display_status not in HISTORY_DISPLAY_STATUSES
    if view == "history":
        return display_status in HISTORY_DISPLAY_STATUSES
    return True


def _json_loads(value: str | None) -> dict:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _compact_error(value: str | None, limit: int = 80) -> str | None:
    if not value:
        return None
    text = " ".join(str(value).split())
    for prefix in ("RuntimeError: ", "ValueError: ", "Exception: "):
        if text.startswith(prefix):
            text = text[len(prefix):]
    return text[:limit]


def _summary_error(summary_json: str | None) -> str | None:
    summary = _json_loads(summary_json)
    for key in ("error_summary", "error_message", "error", "detail", "reason"):
        value = summary.get(key)
        if value:
            return _compact_error(str(value))
    errors = summary.get("errors")
    if isinstance(errors, list) and errors:
        first = errors[0]
        if isinstance(first, dict):
            return _compact_error(str(first.get("error") or first.get("message") or first.get("reason") or first))
        return _compact_error(str(first))
    return None


def step_label(step: TaskStep | None) -> str | None:
    if not step:
        return None
    return STEP_TYPE_LABELS.get(step.step_type, step.step_type)


def latest_event_message(run: TaskRun) -> str | None:
    events = sorted(run.__dict__.get("events") or [], key=lambda item: item.id, reverse=True)
    for event in events:
        if event.message:
            return event.message
    for step in sorted(run.__dict__.get("steps") or [], key=lambda item: item.id, reverse=True):
        events = sorted(step.__dict__.get("events") or [], key=lambda item: item.id, reverse=True)
        for event in events:
            if event.message:
                return event.message
    return None


def compute_task_run_display(run: TaskRun, *, superseded_by_run_id: int | None = None) -> dict[str, Any]:
    steps = sorted(getattr(run, "steps", []) or [], key=lambda item: (item.sort_order, item.id))
    now = datetime.now()
    failed_step = next((step for step in steps if step.status in {STEP_STATUS_FAILED, STEP_STATUS_INTERRUPTED}), None)
    running_step = next((step for step in steps if step.status == STEP_STATUS_RUNNING), None)
    ready_step = next((step for step in steps if step.status == STEP_STATUS_READY), None)
    pending_step = next((step for step in steps if step.status == STEP_STATUS_PENDING), None)
    current_step = running_step or ready_step or failed_step or pending_step or (steps[-1] if steps else None)
    error_summary = _compact_error(failed_step.error_message if failed_step else None) or _summary_error(run.summary_json)
    last_heartbeat = max((step.heartbeat_at for step in steps if step.heartbeat_at), default=None)

    if superseded_by_run_id:
        status = "superseded"
        reason = f"已创建新任务 #{superseded_by_run_id}"
        actions = ["view_detail", "go_current_run", "copy_error"]
    elif run.cancel_requested_at and run.status in {RUN_STATUS_PENDING, RUN_STATUS_RUNNING}:
        status = "cancel_requested"
        reason = "已请求取消，等待当前步骤结束"
        actions = ["view_detail", "refresh"]
    elif run.status == RUN_STATUS_CANCELED:
        status = "canceled"
        reason = "用户已取消"
        actions = ["view_detail", "copy_error"] if error_summary else ["view_detail"]
    elif run.status == RUN_STATUS_FAILED:
        status = "failed"
        reason = f"失败：{error_summary or '请查看错误详情'}"
        actions = ["view_detail", "retry_failed_steps", "copy_error", "refresh"]
    elif run.status == RUN_STATUS_PARTIAL_FAILED:
        status = "partial_failed"
        reason = "部分完成，存在失败项"
        actions = ["view_detail", "retry_failed_steps", "copy_error", "refresh"]
        if run.task_type == "catalog_export":
            actions.insert(1, "download_result")
    elif run.status == RUN_STATUS_INTERRUPTED:
        status = "interrupted"
        reason = "任务未完成，可重试"
        actions = ["view_detail", "retry_failed_steps", "refresh"]
    elif run.status == RUN_STATUS_PAUSED:
        status = "paused"
        reason = "任务已挂起"
        actions = ["view_detail", "refresh"]
    elif run.status == RUN_STATUS_SUCCEEDED:
        status = "succeeded"
        reason = "生成子任务提交完成" if run.task_type == "product_bulk_advance" else "任务完成"
        actions = ["view_detail", "refresh"]
        if run.task_type == "catalog_export":
            actions.insert(0, "download_result")
    elif running_step and (
        (running_step.locked_until and running_step.locked_until < now)
        or (not running_step.locked_until and running_step.heartbeat_at and running_step.heartbeat_at < now - timedelta(seconds=STALE_HEARTBEAT_SECONDS))
    ):
        status = "stale_running"
        reason = "执行锁已过期，可能服务中断"
        actions = ["view_detail", "wake_runtime", "mark_interrupted", "refresh"]
    elif running_step:
        status = "running"
        reason = f"正在执行：{step_label(running_step) or 'step'}"
        actions = ["view_detail", "refresh", "cancel"]
    elif ready_step:
        status = "queued"
        reason = "已就绪，等待执行器领取"
        actions = ["view_detail", "wake_runtime", "cancel", "refresh"]
    elif pending_step:
        status = "waiting_dependency"
        reason = "等待前置步骤完成"
        actions = ["view_detail", "cancel", "refresh"]
    elif not steps and run.status == RUN_STATUS_PENDING:
        status = "planned"
        reason = "任务已创建，等待生成步骤"
        actions = ["view_detail", "cancel", "refresh"]
    else:
        status = run.status
        reason = run.status or "任务状态未知"
        actions = ["view_detail", "refresh"]

    progress_total = sum(step.progress_total or 0 for step in steps) or sum(group.progress_total or 0 for group in getattr(run, "groups", []) or [])
    progress_current = sum(step.progress_current or 0 for step in steps) or sum(group.progress_current or 0 for group in getattr(run, "groups", []) or [])
    if progress_total <= 0:
        progress_total = len(steps)
        progress_current = sum(1 for step in steps if step.status == STEP_STATUS_SUCCEEDED)
    percent = min(100, round((progress_current / progress_total) * 100)) if progress_total else 0
    return {
        "display_status": status,
        "display_status_label": DISPLAY_STATUS_LABELS.get(status, status),
        "display_reason": reason,
        "current_step_id": getattr(current_step, "id", None),
        "current_step_status": getattr(current_step, "status", None),
        "current_step_label": step_label(current_step),
        "progress_current": progress_current,
        "progress_total": progress_total,
        "progress_percent": percent,
        "error_summary": error_summary,
        "latest_event_message": latest_event_message(run),
        "last_heartbeat_at": last_heartbeat,
        "available_actions": list(dict.fromkeys(actions)),
    }
