import json

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.schemas import (
    CatalogExportResultResponse,
    OfflineTaskBatchQueuedResponse,
    OfflineTaskCatalogExportRequest,
    OfflineTaskDetailResponse,
    OfflineTaskGigaDynamicSyncRequest,
    OfflineTaskQueuedResponse,
    OfflineTaskResponse,
    PaginatedOfflineTasks,
)
from app.config import settings
from app.database import get_db
from app.models import OfflineTask, Product
from app.models.status import COMPLETED
from app.services.oss_uploader import download_private_file
from app.services.offline_tasks import pause_offline_task, rerun_offline_task, resume_offline_task
from app.task_runtime.catalog_export_status import (
    ARTIFACT_MODE_LOCAL,
    ARTIFACT_MODE_OBJECT_KEY,
    ARTIFACT_MODE_REDIRECT,
    CatalogEffectiveTerminalRecord,
    CATALOG_STEP_OWNER_OFFLINE_TASK,
    catalog_export_resolution_is_ready,
    load_catalog_effective_terminal_projection,
    load_newest_material_catalog_step_results,
    project_catalog_effective_terminal_record,
    projected_offline_task_status_condition,
    resolve_catalog_export_artifact,
)


router = APIRouter(prefix="/api/offline-tasks", tags=["offline-tasks"])
COMPLETED_TASK_STATUSES = {"done", "partial_failed"}


def _catalog_export_record_is_downloadable(
    catalog_record: CatalogEffectiveTerminalRecord,
    resolution,
) -> bool:
    return (
        catalog_record.effective_status in COMPLETED_TASK_STATUSES
        and catalog_export_resolution_is_ready(resolution)
    )


async def _load_task_with_steps(db: AsyncSession, task_id: int) -> OfflineTask:
    result = await db.execute(
        select(OfflineTask)
        .where(OfflineTask.id == task_id)
        .options(selectinload(OfflineTask.steps))
    )
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(404, "任务不存在")
    task.steps.sort(key=lambda step: step.id)
    return task


async def _load_task(db: AsyncSession, task_id: int) -> OfflineTask:
    task = await db.get(OfflineTask, task_id)
    if not task:
        raise HTTPException(404, "任务不存在")
    return task


def _json_loads(value: str | None) -> dict:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _catalog_effective_record(
    task: OfflineTask,
    catalog_step_result: object = None,
    catalog_record: CatalogEffectiveTerminalRecord | None = None,
) -> CatalogEffectiveTerminalRecord | None:
    if task.task_type != "catalog_export":
        return None
    return catalog_record or project_catalog_effective_terminal_record(
        owner_kind=CATALOG_STEP_OWNER_OFFLINE_TASK,
        task_type=task.task_type,
        status=task.status,
        summary_json_or_dict=task.result_json,
        step_result_json_or_dict=catalog_step_result,
    )


def _normalized_catalog_export_result_json(result: dict) -> str:
    return json.dumps(
        result,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _decorate_catalog_export_response(
    task: OfflineTask,
    response: OfflineTaskResponse | OfflineTaskDetailResponse,
    catalog_step_result: object = None,
    catalog_record: CatalogEffectiveTerminalRecord | None = None,
) -> None:
    if task.task_type != "catalog_export":
        return
    catalog_record = _catalog_effective_record(task, catalog_step_result, catalog_record)
    assert catalog_record is not None
    outcome = catalog_record.outcome
    resolution = resolve_catalog_export_artifact(
        outcome,
        allowed_export_root=settings.DATA_DIR / "exports",
        object_cache_subdir=f"task_{task.id}",
    )
    normalized = CatalogExportResultResponse.model_validate(
        outcome
    )
    response.catalog_export_result = normalized
    response.status = catalog_record.effective_status
    response.result_json = _normalized_catalog_export_result_json(outcome)
    response.can_download = _catalog_export_record_is_downloadable(catalog_record, resolution)
    if isinstance(response, OfflineTaskDetailResponse):
        for step in response.steps:
            if step.step_type == "catalog_export_template":
                step.result_json = None


def _task_response(
    task: OfflineTask,
    catalog_step_result: object = None,
    catalog_record: CatalogEffectiveTerminalRecord | None = None,
) -> OfflineTaskResponse:
    response = OfflineTaskResponse.model_validate(task)
    _decorate_catalog_export_response(task, response, catalog_step_result, catalog_record)
    if response.status in COMPLETED_TASK_STATUSES:
        response.error_message = None
    return response


def _task_detail_response(
    task: OfflineTask,
    catalog_step_result: object = None,
    catalog_record: CatalogEffectiveTerminalRecord | None = None,
) -> OfflineTaskDetailResponse:
    response = OfflineTaskDetailResponse.model_validate(task)
    _decorate_catalog_export_response(task, response, catalog_step_result, catalog_record)
    if response.status in COMPLETED_TASK_STATUSES:
        response.error_message = None
    return response


async def _catalog_step_results_for_tasks(db: AsyncSession, tasks: list[OfflineTask]) -> dict[int, dict]:
    return await load_newest_material_catalog_step_results(
        db,
        owner_kind=CATALOG_STEP_OWNER_OFFLINE_TASK,
        owner_ids=[task.id for task in tasks if task.task_type == "catalog_export"],
    )


async def _catalog_record_and_step_result(
    db: AsyncSession,
    task: OfflineTask,
) -> tuple[CatalogEffectiveTerminalRecord | None, object]:
    projection = await load_catalog_effective_terminal_projection(
        db,
        owner_kind=CATALOG_STEP_OWNER_OFFLINE_TASK,
        owner_ids=[task.id],
    )
    record = projection.records_by_id.get(task.id)
    step_results = await _catalog_step_results_for_tasks(db, [] if record else [task])
    return record, step_results.get(task.id)


def _product_bulk_advance_latest_result(product: Product | None) -> tuple[str, str]:
    if not product:
        return "missing", "商品记录不存在或已删除"
    if product.status == COMPLETED and (product.current_step or 0) >= 6:
        return "export_ready", "已到达待导出"
    if product.status == "failed":
        return "failed", product.error_message or "后续生成失败"
    if product.status == "paused":
        return "paused", "后续流程已挂起"
    if product.status in {"source_unavailable", "unavailable"}:
        return "blocked", f"当前状态不能继续推进: {product.status}"
    if (product.current_step or 0) < 5:
        return "blocked", "仍未满足生成前置条件"
    return "in_progress", "已提交后续生成或仍在可生成阶段"


async def _with_product_bulk_advance_progress(
    db: AsyncSession,
    response: OfflineTaskResponse,
) -> OfflineTaskResponse:
    if response.task_type != "product_bulk_advance":
        return response
    payload = _json_loads(response.result_json)
    rows = payload.get("rows")
    if not isinstance(rows, list):
        return response
    product_ids = [
        int(row["product_id"])
        for row in rows
        if isinstance(row, dict)
        and row.get("product_id") is not None
        and str(row.get("product_id")).isdigit()
    ]
    if not product_ids:
        return response
    result = await db.execute(
        select(Product)
        .options(selectinload(Product.data))
        .where(Product.id.in_(set(product_ids)))
    )
    products = {product.id: product for product in result.scalars().all()}
    latest_counts = {"export_ready": 0, "in_progress": 0, "blocked": 0, "failed": 0, "paused": 0, "missing": 0}
    for row in rows:
        if not isinstance(row, dict):
            continue
        product_id = row.get("product_id")
        product = products.get(int(product_id)) if product_id is not None and str(product_id).isdigit() else None
        latest_result, latest_reason = _product_bulk_advance_latest_result(product)
        latest_counts[latest_result] = latest_counts.get(latest_result, 0) + 1
        row["latest_status"] = product.status if product else None
        row["latest_step"] = product.current_step if product else None
        row["latest_result"] = latest_result
        row["latest_reason"] = latest_reason
        if product and not row.get("item_code") and product.data:
            row["item_code"] = product.data.item_code
    payload["rows"] = rows
    payload["latest_counts"] = latest_counts
    payload["export_ready_count"] = latest_counts.get("export_ready", 0)
    response.result_json = json.dumps(payload, ensure_ascii=False, default=str)
    return response


@router.get("", response_model=PaginatedOfflineTasks)
async def list_offline_tasks(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    task_type: str | None = None,
    status: str | None = None,
    include_progress: bool = Query(False, description="是否为 product_bulk_advance 任务补充 rows 最新状态"),
    db: AsyncSession = Depends(get_db),
):
    query = select(OfflineTask).order_by(OfflineTask.id.desc())
    count_query = select(func.count(OfflineTask.id))
    catalog_projection = await load_catalog_effective_terminal_projection(
        db,
        owner_kind=CATALOG_STEP_OWNER_OFFLINE_TASK,
    )
    if task_type:
        query = query.where(OfflineTask.task_type == task_type)
        count_query = count_query.where(OfflineTask.task_type == task_type)
    if status:
        if status in {"done", "partial_failed", "failed"}:
            status_condition = projected_offline_task_status_condition(status, catalog_projection)
        else:
            status_condition = OfflineTask.status == status
        query = query.where(status_condition)
        count_query = count_query.where(status_condition)
    total_result = await db.execute(count_query)
    result = await db.execute(query.offset((page - 1) * page_size).limit(page_size))
    tasks = result.scalars().all()
    catalog_step_results = await _catalog_step_results_for_tasks(
        db,
        [task for task in tasks if task.id not in catalog_projection.records_by_id],
    )
    responses = []
    for task in tasks:
        response = _task_response(
            task,
            catalog_step_results.get(task.id),
            catalog_projection.records_by_id.get(task.id),
        )
        if include_progress:
            response = await _with_product_bulk_advance_progress(db, response)
        responses.append(response)
    return PaginatedOfflineTasks(
        items=responses,
        total=total_result.scalar() or 0,
        page=page,
        page_size=page_size,
    )


@router.post("/giga-inventory-sync", response_model=OfflineTaskQueuedResponse)
async def create_giga_inventory_sync_offline_task(
    body: OfflineTaskGigaDynamicSyncRequest,
    db: AsyncSession = Depends(get_db),
):
    raise HTTPException(410, "库存同步创建已迁移到新任务中心，请使用 /api/task-runs/giga-inventory-sync")


@router.post("/giga-price-sync", response_model=OfflineTaskQueuedResponse)
async def create_giga_price_sync_offline_task(
    body: OfflineTaskGigaDynamicSyncRequest,
    db: AsyncSession = Depends(get_db),
):
    raise HTTPException(410, "价格同步创建已迁移到新任务中心，请使用 /api/task-runs/giga-price-sync")


@router.post("/catalog-export", response_model=OfflineTaskBatchQueuedResponse)
async def create_catalog_export_offline_tasks(
    body: OfflineTaskCatalogExportRequest,
    db: AsyncSession = Depends(get_db),
):
    raise HTTPException(410, "导出文件创建已迁移到新任务中心，请使用 /api/task-runs/catalog-export")


@router.get("/{task_id}", response_model=OfflineTaskDetailResponse)
async def get_offline_task(task_id: int, db: AsyncSession = Depends(get_db)):
    task = await _load_task_with_steps(db, task_id)
    catalog_record, catalog_step_result = await _catalog_record_and_step_result(db, task)
    response = _task_detail_response(task, catalog_step_result, catalog_record)
    return await _with_product_bulk_advance_progress(db, response)


@router.get("/{task_id}/download")
async def download_offline_task_result(task_id: int, db: AsyncSession = Depends(get_db)):
    task = await _load_task(db, task_id)
    if task.task_type != "catalog_export":
        raise HTTPException(400, "当前任务没有可下载的导出文件")
    catalog_record, catalog_step_result = await _catalog_record_and_step_result(db, task)
    catalog_record = _catalog_effective_record(task, catalog_step_result, catalog_record)
    assert catalog_record is not None
    resolution = resolve_catalog_export_artifact(
        catalog_record.outcome,
        allowed_export_root=settings.DATA_DIR / "exports",
        object_cache_subdir=f"task_{task_id}",
    )
    if not _catalog_export_record_is_downloadable(catalog_record, resolution):
        raise HTTPException(400, "导出任务没有可下载的成功结果")
    if resolution.mode == ARTIFACT_MODE_REDIRECT and resolution.redirect_url:
        return RedirectResponse(resolution.redirect_url)
    if resolution.mode == ARTIFACT_MODE_LOCAL and resolution.local_path:
        return FileResponse(
            resolution.local_path,
            media_type="application/zip",
            filename=resolution.filename or resolution.local_path.name,
        )
    if resolution.mode == ARTIFACT_MODE_OBJECT_KEY and resolution.object_key and resolution.cache_path:
        try:
            resolution.cache_path.parent.mkdir(parents=True, exist_ok=True)
            download_private_file(resolution.object_key, resolution.cache_path)
        except Exception as exc:
            if resolution.fallback_url:
                return RedirectResponse(resolution.fallback_url)
            raise HTTPException(404, f"导出文件本地缓存不存在，且从 OSS 下载失败: {type(exc).__name__}: {exc}")
        return FileResponse(
            resolution.cache_path,
            media_type="application/zip",
            filename=resolution.filename or resolution.cache_path.name,
        )
    raise HTTPException(400, "导出文件尚未生成")


@router.post("/{task_id}/rerun", response_model=OfflineTaskDetailResponse)
async def rerun_offline_task_api(task_id: int, db: AsyncSession = Depends(get_db)):
    try:
        task = await rerun_offline_task(db, task_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    task = await _load_task_with_steps(db, task.id)
    catalog_record, catalog_step_result = await _catalog_record_and_step_result(db, task)
    return _task_detail_response(task, catalog_step_result, catalog_record)


@router.post("/{task_id}/pause", response_model=OfflineTaskDetailResponse)
async def pause_offline_task_api(task_id: int, db: AsyncSession = Depends(get_db)):
    try:
        task = await pause_offline_task(db, task_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    task = await _load_task_with_steps(db, task.id)
    catalog_record, catalog_step_result = await _catalog_record_and_step_result(db, task)
    return _task_detail_response(task, catalog_step_result, catalog_record)


@router.post("/{task_id}/resume", response_model=OfflineTaskDetailResponse)
async def resume_offline_task_api(task_id: int, db: AsyncSession = Depends(get_db)):
    try:
        task = await resume_offline_task(db, task_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    task = await _load_task_with_steps(db, task.id)
    catalog_record, catalog_step_result = await _catalog_record_and_step_result(db, task)
    return _task_detail_response(task, catalog_step_result, catalog_record)
