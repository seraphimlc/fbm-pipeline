import json
from pathlib import Path
from datetime import datetime, timedelta

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import and_, func, not_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.schemas import (
    AplusGenerateRequest,
    OfflineTaskCatalogExportRequest,
    OfflineTaskGigaDynamicSyncRequest,
    OfflineTaskGigaPullRequest,
    PaginatedTaskRuns,
    TaskRunBatchQueuedResponse,
    TaskRunDetailResponse,
    TaskRunResponse,
    TaskStepResponse,
)
from app.config import settings
from app.database import get_db
from app.models import TaskGroup, TaskRun, TaskStep, TaskStepEvent
from app.services.oss_uploader import download_private_file
from app.task_planners.aplus_generate import create_aplus_generate_runs
from app.task_planners.catalog_export import create_catalog_export_runs
from app.task_planners.giga_dynamic_sync import create_giga_dynamic_sync_runs
from app.task_planners.giga_pull import create_giga_pull_runs
from app.task_runtime.constants import (
    RUN_STATUS_CANCELED,
    RUN_STATUS_FAILED,
    RUN_STATUS_INTERRUPTED,
    RUN_STATUS_PARTIAL_FAILED,
    RUN_STATUS_PAUSED,
    RUN_STATUS_PENDING,
    RUN_STATUS_RUNNING,
    RUN_STATUS_SUCCEEDED,
    STEP_STATUS_CANCELED,
    STEP_STATUS_FAILED,
    STEP_STATUS_INTERRUPTED,
    STEP_STATUS_PENDING,
    STEP_STATUS_READY,
    STEP_STATUS_RUNNING,
    STEP_STATUS_SUCCEEDED,
)
from app.task_runtime.actions import action_for
from app.task_runtime.display import compute_task_run_display
from app.task_runtime.events import emit_event
from app.task_runtime.scheduler import kick_task_runtime, recover_task_runtime, retry_failed_steps, retry_step


router = APIRouter(prefix="/api/task-runs", tags=["task-runs"])

STALE_HEARTBEAT_SECONDS = 600

TASK_TYPE_LABELS = {
    "giga_pull": "GIGA 拉品",
    "product_auto_image_selection": "自动选图",
    "product_image_analysis": "图片分析",
    "product_listing_generation": "Listing 生成",
    "catalog_export": "导出文件",
    "aplus_generate": "A+生成",
    "giga_inventory_sync": "GIGA 库存同步",
    "giga_price_sync": "GIGA 价格同步",
    "product_bulk_advance": "批量提交生成任务",
}

STEP_TYPE_LABELS = {
    "giga_pull_plan": "规划 SKU",
    "giga_pull_detail_chunk": "SKU 详情",
    "giga_pull_inventory_chunk": "SKU 库存",
    "giga_pull_price_chunk": "SKU 价格",
    "giga_pull_finalize_snapshot": "快照校验",
    "giga_pull_aggregate_items": "聚合 Item/Group",
    "giga_pull_materialize_products": "生成商品草稿",
    "product_auto_image_selection": "自动选图",
    "product_image_analysis": "图片分析",
    "product_listing_generation": "Listing 生成",
    "catalog_export_template": "导出文件",
    "aplus_generate_product": "A+生成",
    "giga_inventory_sync": "库存同步",
    "giga_price_sync": "价格同步",
    "product_bulk_advance_product": "提交商品生成任务",
}

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


def _registered_action_for_step(step_type: str):
    try:
        return action_for(step_type)
    except RuntimeError:
        return None


def _step_label(step: TaskStep | None) -> str | None:
    if not step:
        return None
    return STEP_TYPE_LABELS.get(step.step_type, step.step_type)


def _task_type_label(task_type: str) -> str:
    return TASK_TYPE_LABELS.get(task_type, task_type)


def _object_fields(run: TaskRun) -> tuple[str | None, int | None, str | None]:
    return None, None, None


def _latest_event_message(run: TaskRun) -> str | None:
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


def _display_payload_from_detail(run: TaskRun, display: dict, *, superseded_by_run_id: int | None) -> dict:
    object_type, object_id, object_label = _object_fields(run)
    return {
        "task_type_label": _task_type_label(run.task_type),
        "object_type": object_type,
        "object_id": object_id,
        "object_label": object_label,
        "dedupe_key": run.dedupe_key,
        "correlation_key": run.correlation_key,
        "superseded_by_run_id": superseded_by_run_id,
        "display_status": display["display_status"],
        "display_status_label": DISPLAY_STATUS_LABELS.get(display["display_status"], display["display_status"]),
        "display_reason": display["display_reason"],
        "current_step_label": display["current_step_label"],
        "progress_current": display["progress_current"],
        "progress_total": display["progress_total"],
        "progress_percent": display["progress_percent"],
        "error_summary": display["error_summary"],
        "latest_event_message": display["latest_event_message"],
        "last_heartbeat_at": display["last_heartbeat_at"],
        "current_effective_run_id": superseded_by_run_id or run.id,
        "available_actions": list(dict.fromkeys(display["available_actions"])),
    }


def _step_display(step: TaskStep, *, superseded: bool = False) -> dict:
    now = datetime.now()
    error_summary = _compact_error(step.error_message)
    if superseded:
        status, reason, actions = "superseded", "该步骤所属任务已被新任务取代", []
    elif step.status == STEP_STATUS_RUNNING and (
        (step.locked_until and step.locked_until < now)
        or (not step.locked_until and step.heartbeat_at and step.heartbeat_at < now - timedelta(seconds=STALE_HEARTBEAT_SECONDS))
    ):
        status, reason, actions = "stale_running", "执行锁已过期，可能服务中断", ["retry_step"]
    elif step.status == STEP_STATUS_READY:
        status, reason, actions = "queued", "已就绪，等待执行器领取", []
    elif step.status == STEP_STATUS_RUNNING:
        status, reason, actions = "running", f"正在执行：{_step_label(step) or 'step'}", []
    elif step.status == STEP_STATUS_PENDING:
        status, reason, actions = "waiting_dependency", "等待前置步骤完成", []
    elif step.status == STEP_STATUS_FAILED:
        status, reason, actions = "failed", f"失败：{error_summary or '请查看错误详情'}", ["retry_step"]
    elif step.status == STEP_STATUS_INTERRUPTED:
        status, reason, actions = "interrupted", "任务未完成，可重试", ["retry_step"]
    elif step.status == STEP_STATUS_CANCELED:
        status, reason, actions = "canceled", "用户已取消", []
    elif step.status == STEP_STATUS_SUCCEEDED:
        status, reason, actions = "succeeded", "step 完成", []
    else:
        status, reason, actions = step.status, step.status, []
    return {
        "step_label": _step_label(step),
        "display_status": status,
        "display_status_label": DISPLAY_STATUS_LABELS.get(status, status),
        "display_reason": reason,
        "error_summary": error_summary,
        "available_actions": actions,
    }


def _run_display(run: TaskRun, *, superseded_by_run_id: int | None) -> dict:
    display = compute_task_run_display(run, superseded_by_run_id=superseded_by_run_id)
    return _display_payload_from_detail(run, display, superseded_by_run_id=superseded_by_run_id)


def _run_list_display(run: TaskRun, *, superseded_by_run_id: int | None) -> dict:
    error_summary = _summary_error(run.summary_json)
    if superseded_by_run_id:
        status = "superseded"
        reason = f"已创建新任务 #{superseded_by_run_id}"
        actions = ["view_detail", "go_current_run", "copy_error"]
    elif run.cancel_requested_at and run.status in {RUN_STATUS_PENDING, RUN_STATUS_RUNNING}:
        status = "cancel_requested"
        reason = "已请求取消，等待执行器处理"
        actions = ["view_detail", "refresh"]
    elif run.status == RUN_STATUS_PENDING:
        status = "queued"
        reason = "已进入任务队列，等待执行器领取"
        actions = ["view_detail", "wake_runtime", "cancel", "refresh"]
    elif run.status == RUN_STATUS_RUNNING:
        status = "running"
        reason = "任务执行中"
        actions = ["view_detail", "refresh", "cancel"]
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
    elif run.status == RUN_STATUS_CANCELED:
        status = "canceled"
        reason = "用户已取消"
        actions = ["view_detail", "copy_error"] if error_summary else ["view_detail"]
    elif run.status == RUN_STATUS_SUCCEEDED:
        status = "succeeded"
        reason = "生成子任务提交完成" if run.task_type == "product_bulk_advance" else "任务完成"
        actions = ["view_detail", "refresh"]
        if run.task_type == "catalog_export":
            actions.insert(0, "download_result")
    else:
        status = run.status
        reason = run.status or "任务状态未知"
        actions = ["view_detail", "refresh"]

    progress_total = 1 if status in {"queued", "running", "succeeded", "canceled", "superseded"} else 0
    progress_current = 1 if status in {"succeeded", "canceled", "superseded"} else 0
    object_type, object_id, object_label = _object_fields(run)
    return {
        "task_type_label": _task_type_label(run.task_type),
        "object_type": object_type,
        "object_id": object_id,
        "object_label": object_label,
        "dedupe_key": run.dedupe_key,
        "correlation_key": run.correlation_key,
        "superseded_by_run_id": superseded_by_run_id,
        "display_status": status,
        "display_status_label": DISPLAY_STATUS_LABELS.get(status, status),
        "display_reason": reason,
        "current_step_label": None,
        "progress_current": progress_current,
        "progress_total": progress_total,
        "progress_percent": 100 if progress_total and progress_current == progress_total else 0,
        "error_summary": error_summary,
        "latest_event_message": None,
        "last_heartbeat_at": None,
        "current_effective_run_id": superseded_by_run_id or run.id,
        "available_actions": list(dict.fromkeys(actions)),
    }


def _superseded_map(runs: list[TaskRun]) -> dict[int, int]:
    return {run.id: run.superseded_by_run_id for run in runs if run.superseded_by_run_id}


def _run_response(run: TaskRun, superseded_by_run_id: int | None = None, *, list_view: bool = False) -> TaskRunResponse:
    response = TaskRunResponse.model_validate(run)
    display_fn = _run_list_display if list_view else _run_display
    display = display_fn(run, superseded_by_run_id=superseded_by_run_id)
    for key, value in display.items():
        setattr(response, key, value)
    return response


def _superseded_sql_condition():
    return TaskRun.superseded_by_run_id.is_not(None)


def _apply_condition(query, count_query, condition):
    return query.where(condition), count_query.where(condition)


def _apply_view_filter(query, count_query, view: str):
    history = _history_display_sql_condition()
    if view == "current":
        return _apply_condition(query, count_query, not_(history))
    if view == "history":
        return _apply_condition(query, count_query, history)
    if view == "all":
        return query, count_query
    raise HTTPException(400, "view 只支持 current/history/all")


def _terminal_base_condition(status: str):
    return and_(
        TaskRun.status == status,
        not_(_superseded_sql_condition()),
    )


def _canceled_sql_condition():
    return and_(
        TaskRun.status == RUN_STATUS_CANCELED,
        not_(_superseded_sql_condition()),
    )


def _history_display_sql_condition():
    return or_(
        _superseded_sql_condition(),
        TaskRun.status.in_((RUN_STATUS_SUCCEEDED, RUN_STATUS_CANCELED)),
    )


def _display_status_sql_condition(display_status: str | None):
    if not display_status:
        return None
    superseded = _superseded_sql_condition()
    if display_status == "superseded":
        return superseded
    if display_status == "cancel_requested":
        return and_(not_(superseded), TaskRun.cancel_requested_at.is_not(None), TaskRun.status.in_((RUN_STATUS_PENDING, RUN_STATUS_RUNNING)))
    if display_status in {"stale_running", "waiting_dependency", "planned"}:
        raise HTTPException(400, "该状态仅在详情诊断中展示，当前列表不支持筛选")
    if display_status == "running":
        return and_(not_(superseded), TaskRun.cancel_requested_at.is_(None), TaskRun.status == RUN_STATUS_RUNNING)
    if display_status == "queued":
        return and_(not_(superseded), TaskRun.cancel_requested_at.is_(None), TaskRun.status == RUN_STATUS_PENDING)
    status_map = {
        "failed": RUN_STATUS_FAILED,
        "partial_failed": RUN_STATUS_PARTIAL_FAILED,
        "interrupted": RUN_STATUS_INTERRUPTED,
        "succeeded": RUN_STATUS_SUCCEEDED,
        "paused": RUN_STATUS_PAUSED,
    }
    if display_status in status_map:
        return _terminal_base_condition(status_map[display_status])
    if display_status == "canceled":
        return _canceled_sql_condition()
    raise HTTPException(400, f"display_status 不支持: {display_status}")


def _step_response(step: TaskStep, *, superseded: bool = False) -> TaskStepResponse:
    response = TaskStepResponse.model_validate(step)
    for key, value in _step_display(step, superseded=superseded).items():
        setattr(response, key, value)
    return response


async def _emit_task_run_event(
    db: AsyncSession,
    run: TaskRun,
    *,
    event_type: str,
    message: str | None = None,
    step: TaskStep | None = None,
    data: dict | None = None,
) -> None:
    if step:
        await emit_event(db, step=step, event_type=event_type, message=message, data=data)
        return
    db.add(
        TaskStepEvent(
            task_run_id=run.id,
            task_group_id=None,
            task_step_id=None,
            event_type=event_type,
            message=message,
            data_json=json.dumps(data or {}, ensure_ascii=False) if data is not None else None,
            created_at=datetime.now(),
        )
    )


def _sort_run_detail(run: TaskRun) -> TaskRun:
    run.groups.sort(key=lambda group: (group.sort_order, group.id))
    for group in run.groups:
        group.steps.sort(key=lambda step: (step.sort_order, step.id))
        for step in group.steps:
            step.events.sort(key=lambda event: event.id)
    return run


def _json_loads(value: str | None) -> dict:
    if not value:
        return {}
    try:
        import json

        parsed = json.loads(value)
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _catalog_export_payload(run: TaskRun) -> dict:
    payload = _json_loads(run.summary_json)
    if payload.get("filename") or payload.get("file_path") or payload.get("oss_object_key"):
        return payload
    for step in sorted(run.steps, key=lambda item: item.id, reverse=True):
        if step.step_type != "catalog_export_template":
            continue
        step_payload = _json_loads(step.result_json)
        if step_payload.get("filename") or step_payload.get("file_path") or step_payload.get("oss_object_key"):
            return step_payload
    return payload


async def _load_run(db: AsyncSession, run_id: int) -> TaskRun:
    result = await db.execute(
        select(TaskRun)
        .where(TaskRun.id == run_id)
        .options(
            selectinload(TaskRun.groups)
            .selectinload(TaskGroup.steps)
            .selectinload(TaskStep.events),
            selectinload(TaskRun.steps).selectinload(TaskStep.events),
            selectinload(TaskRun.events),
        )
    )
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(404, "任务不存在")
    return _sort_run_detail(run)


async def _reload_created_runs_for_response(db: AsyncSession, runs: list[TaskRun]) -> list[TaskRun]:
    return [await _load_run(db, run.id) for run in runs]


def _decorate_detail_response(run: TaskRun, superseded_by_run_id: int | None = None) -> TaskRunDetailResponse:
    response = TaskRunDetailResponse.model_validate(run)
    for key, value in _run_display(run, superseded_by_run_id=superseded_by_run_id).items():
        setattr(response, key, value)
    superseded = bool(superseded_by_run_id)
    for group_response, group in zip(response.groups, run.groups, strict=False):
        step_statuses = [_step_display(step, superseded=superseded) for step in group.steps]
        failed = next((item for item in step_statuses if item["display_status"] in {"failed", "interrupted", "stale_running"}), None)
        queued = next((item for item in step_statuses if item["display_status"] == "queued"), None)
        running = next((item for item in step_statuses if item["display_status"] == "running"), None)
        chosen = failed or running or queued or (step_statuses[0] if step_statuses else None)
        if chosen:
            group_response.display_status = "superseded" if superseded else chosen["display_status"]
            group_response.display_status_label = DISPLAY_STATUS_LABELS.get(group_response.display_status, group_response.display_status)
            group_response.display_reason = "该阶段所属任务已被新任务取代" if superseded else chosen["display_reason"]
            group_response.error_summary = chosen["error_summary"]
            group_response.available_actions = [] if superseded else chosen["available_actions"]
        for step_response, step in zip(group_response.steps, group.steps, strict=False):
            for key, value in _step_display(step, superseded=superseded).items():
                setattr(step_response, key, value)
    return response


@router.get("", response_model=PaginatedTaskRuns)
async def list_task_runs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    view: str = Query("current"),
    display_status: str | None = None,
    task_type: str | None = None,
    status: str | None = None,
    dedupe_key: str | None = None,
    correlation_key: str | None = None,
    q: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    base_query = (
        select(TaskRun)
        .order_by(TaskRun.id.desc())
    )
    count_query = select(func.count(TaskRun.id))
    if task_type:
        base_query = base_query.where(TaskRun.task_type == task_type)
        count_query = count_query.where(TaskRun.task_type == task_type)
    if status:
        base_query = base_query.where(TaskRun.status == status)
        count_query = count_query.where(TaskRun.status == status)
    if dedupe_key:
        base_query = base_query.where(TaskRun.dedupe_key == dedupe_key)
        count_query = count_query.where(TaskRun.dedupe_key == dedupe_key)
    if correlation_key:
        base_query = base_query.where(TaskRun.correlation_key == correlation_key)
        count_query = count_query.where(TaskRun.correlation_key == correlation_key)
    if q:
        q_value = q.strip()
        if q_value.startswith("#") and q_value[1:].isdigit():
            base_query = base_query.where(TaskRun.id == int(q_value[1:]))
            count_query = count_query.where(TaskRun.id == int(q_value[1:]))
        elif q_value.isdigit():
            base_query = base_query.where(TaskRun.id == int(q_value))
            count_query = count_query.where(TaskRun.id == int(q_value))
        else:
            like = f"%{q_value}%"
            base_query = base_query.where(TaskRun.title.like(like))
            count_query = count_query.where(TaskRun.title.like(like))

    display_condition = _display_status_sql_condition(display_status)

    page_query, base_count_query = _apply_view_filter(base_query, count_query, view)
    base_total_result = await db.execute(base_count_query)
    base_total = base_total_result.scalar() or 0
    page_count_query = base_count_query
    if display_condition is not None:
        page_query, page_count_query = _apply_condition(page_query, page_count_query, display_condition)
        total_result = await db.execute(page_count_query)
        filtered_total = total_result.scalar() or 0
    else:
        filtered_total = base_total
    result = await db.execute(page_query.offset((page - 1) * page_size).limit(page_size))
    page_runs = result.scalars().unique().all()
    superseded = _superseded_map(page_runs)
    return PaginatedTaskRuns(
        items=[
            _run_response(run, superseded_by_run_id=superseded.get(run.id) or run.superseded_by_run_id, list_view=True)
            for run in page_runs
        ],
        total=filtered_total,
        base_total=base_total,
        filtered_total=filtered_total,
        is_limited=False,
        scan_limit=None,
        page=page,
        page_size=page_size,
    )


@router.post("/giga-pull", response_model=TaskRunBatchQueuedResponse)
async def create_giga_pull_task_runs(
    body: OfflineTaskGigaPullRequest,
    db: AsyncSession = Depends(get_db),
):
    try:
        runs = await create_giga_pull_runs(db, body)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    runs = await _reload_created_runs_for_response(db, runs)
    return TaskRunBatchQueuedResponse(runs=[_run_response(run) for run in runs])


@router.post("/giga-inventory-sync", response_model=TaskRunBatchQueuedResponse)
async def create_giga_inventory_sync_task_runs(
    body: OfflineTaskGigaDynamicSyncRequest,
    db: AsyncSession = Depends(get_db),
):
    try:
        runs = await create_giga_dynamic_sync_runs(db, body, kind="inventory")
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    runs = await _reload_created_runs_for_response(db, runs)
    return TaskRunBatchQueuedResponse(runs=[_run_response(run) for run in runs])


@router.post("/giga-price-sync", response_model=TaskRunBatchQueuedResponse)
async def create_giga_price_sync_task_runs(
    body: OfflineTaskGigaDynamicSyncRequest,
    db: AsyncSession = Depends(get_db),
):
    try:
        runs = await create_giga_dynamic_sync_runs(db, body, kind="price")
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    runs = await _reload_created_runs_for_response(db, runs)
    return TaskRunBatchQueuedResponse(runs=[_run_response(run) for run in runs])


@router.post("/catalog-export", response_model=TaskRunBatchQueuedResponse)
async def create_catalog_export_task_runs(
    body: OfflineTaskCatalogExportRequest,
    db: AsyncSession = Depends(get_db),
):
    try:
        runs, errors = await create_catalog_export_runs(db, body)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    runs = await _reload_created_runs_for_response(db, runs)
    return TaskRunBatchQueuedResponse(runs=[_run_response(run) for run in runs], errors=errors)


@router.post("/aplus-generate", response_model=TaskRunBatchQueuedResponse)
async def create_aplus_generate_task_runs(
    body: AplusGenerateRequest,
    db: AsyncSession = Depends(get_db),
):
    try:
        runs, errors, _started_product_ids = await create_aplus_generate_runs(
            db,
            body.catalog_product_ids,
            force=body.force,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    runs = await _reload_created_runs_for_response(db, runs)
    return TaskRunBatchQueuedResponse(runs=[_run_response(run) for run in runs], errors=errors)


@router.get("/{run_id}", response_model=TaskRunDetailResponse)
async def get_task_run(run_id: int, db: AsyncSession = Depends(get_db)):
    run = await _load_run(db, run_id)
    superseded = _superseded_map([run])
    return _decorate_detail_response(run, superseded_by_run_id=superseded.get(run.id))


@router.get("/{run_id}/download")
async def download_task_run_result(run_id: int, db: AsyncSession = Depends(get_db)):
    run = await _load_run(db, run_id)
    if run.task_type != "catalog_export":
        raise HTTPException(400, "当前新任务没有可下载的导出文件")
    payload = _catalog_export_payload(run)
    file_path = str(payload.get("file_path") or "").strip()
    filename = str(payload.get("filename") or Path(file_path).name or f"catalog_export_run_{run_id}.zip")
    object_key = str(payload.get("oss_object_key") or "").strip()
    if file_path.lower().startswith(("http://", "https://")):
        file_path = ""
    if not file_path:
        if not object_key:
            raise HTTPException(400, "导出文件尚未生成")
        file_path = str(settings.DATA_DIR / "exports" / f"task_run_{run_id}" / filename)
    path = Path(file_path).expanduser().resolve()
    export_root = (settings.DATA_DIR / "exports").resolve()
    if export_root not in path.parents:
        raise HTTPException(400, "导出文件路径非法")
    if not path.is_file():
        if object_key:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                download_private_file(object_key, path)
            except Exception as exc:
                raise HTTPException(404, f"导出文件本地缓存不存在，且从 OSS 下载失败: {type(exc).__name__}: {exc}")
        else:
            raise HTTPException(404, "导出文件不存在，可能已被清理")
    return FileResponse(path, media_type="application/zip", filename=filename)


@router.post("/{run_id}/retry-failed", response_model=TaskRunDetailResponse)
async def retry_failed_task_run_steps(run_id: int, db: AsyncSession = Depends(get_db)):
    run = await _load_run(db, run_id)
    superseded = _superseded_map([run])
    if superseded.get(run_id):
        raise HTTPException(400, f"该任务已被 #{superseded[run_id]} 取代，请处理当前任务")
    if run.status == RUN_STATUS_CANCELED:
        raise HTTPException(400, "已取消任务不能重试")
    if not run:
        raise HTTPException(404, "任务不存在")
    try:
        await retry_failed_steps(run_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    refreshed = await _load_run(db, run_id)
    refreshed_superseded = _superseded_map([refreshed])
    return _decorate_detail_response(refreshed, superseded_by_run_id=refreshed_superseded.get(run_id))


@router.post("/steps/{step_id}/retry", response_model=TaskStepResponse)
async def retry_task_step(step_id: int, db: AsyncSession = Depends(get_db)):
    step = await db.get(TaskStep, step_id)
    if not step:
        raise HTTPException(404, "step 不存在")
    run = await _load_run(db, step.task_run_id)
    superseded = _superseded_map([run])
    if superseded.get(run.id):
        raise HTTPException(400, f"该任务已被 #{superseded[run.id]} 取代，请处理当前任务")
    try:
        await retry_step(step_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    result = await db.execute(
        select(TaskStep)
        .where(TaskStep.id == step_id)
        .options(selectinload(TaskStep.events))
    )
    step = result.scalar_one()
    return _step_response(step)


@router.post("/{run_id}/wake", response_model=TaskRunDetailResponse)
async def wake_task_run(run_id: int, db: AsyncSession = Depends(get_db)):
    run = await _load_run(db, run_id)
    response = _decorate_detail_response(run, superseded_by_run_id=_superseded_map([run]).get(run.id))
    if response.display_status not in {"queued", "stale_running"}:
        raise HTTPException(400, f"当前任务状态不能唤醒: {response.display_status_label}")
    if response.display_status == "stale_running":
        await recover_task_runtime()
    kick_task_runtime()
    await _emit_task_run_event(db, run, step=run.steps[0] if run.steps else None, event_type="action", message="用户唤醒执行器")
    await db.commit()
    return _decorate_detail_response(await _load_run(db, run_id))


@router.post("/{run_id}/cancel", response_model=TaskRunDetailResponse)
async def cancel_task_run(run_id: int, body: dict = Body(default_factory=dict), db: AsyncSession = Depends(get_db)):
    run = await _load_run(db, run_id)
    response = _decorate_detail_response(run, superseded_by_run_id=_superseded_map([run]).get(run.id))
    if response.display_status in {"succeeded", "failed", "partial_failed", "superseded", "canceled"}:
        raise HTTPException(400, f"当前任务状态不能取消: {response.display_status_label}")
    now = datetime.now()
    reason = str(body.get("reason") or "用户取消")
    running_steps = [step for step in run.steps if step.status == STEP_STATUS_RUNNING]
    run.cancel_requested_at = now
    run.cancel_requested_by = "user"
    run.cancel_reason = reason
    try:
        action = action_for(run.task_type)
    except RuntimeError:
        action = None
    if action:
        await action.on_cancel_requested(db, run, reason)
    if running_steps:
        await _emit_task_run_event(db, run, step=running_steps[0], event_type="action", message=f"用户请求取消：{reason}")
    else:
        run.status = RUN_STATUS_CANCELED
        run.finished_at = now
        for group in run.groups:
            group.status = RUN_STATUS_CANCELED
            group.finished_at = now
            group.updated_at = now
        for step in run.steps:
            if step.status in {STEP_STATUS_PENDING, STEP_STATUS_READY}:
                step.status = STEP_STATUS_CANCELED
                step.finished_at = now
                step.updated_at = now
        await _emit_task_run_event(db, run, step=run.steps[0] if run.steps else None, event_type="action", message=f"用户取消任务：{reason}")
    run.updated_at = now
    await db.commit()
    return _decorate_detail_response(await _load_run(db, run_id))


@router.post("/{run_id}/mark-interrupted", response_model=TaskRunDetailResponse)
async def mark_task_run_interrupted(run_id: int, body: dict = Body(default_factory=dict), db: AsyncSession = Depends(get_db)):
    run = await _load_run(db, run_id)
    response = _decorate_detail_response(run, superseded_by_run_id=_superseded_map([run]).get(run.id))
    if response.display_status != "stale_running":
        raise HTTPException(400, f"当前任务状态不能标记中断: {response.display_status_label}")
    now = datetime.now()
    reason = str(body.get("reason") or "锁超时，人工标记中断")
    for step in run.steps:
        if step.status == STEP_STATUS_RUNNING:
            step.status = STEP_STATUS_INTERRUPTED
            step.error_message = step.error_message or reason
            step.locked_by = None
            step.locked_until = None
            step.finished_at = now
            step.updated_at = now
            action = _registered_action_for_step(step.step_type)
            if action:
                await action.on_step_interrupted(db, step, reason)
            await emit_event(db, step=step, event_type="action", message=reason)
    run.status = RUN_STATUS_INTERRUPTED
    run.updated_at = now
    await db.commit()
    return _decorate_detail_response(await _load_run(db, run_id))
