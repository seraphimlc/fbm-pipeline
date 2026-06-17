import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.schemas import (
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


router = APIRouter(prefix="/api/offline-tasks", tags=["offline-tasks"])
COMPLETED_TASK_STATUSES = {"done", "partial_failed"}


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


def _json_loads(value: str | None) -> dict:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _task_response(task: OfflineTask) -> OfflineTaskResponse:
    response = OfflineTaskResponse.model_validate(task)
    if response.status in COMPLETED_TASK_STATUSES:
        response.error_message = None
    return response


def _task_detail_response(task: OfflineTask) -> OfflineTaskDetailResponse:
    response = OfflineTaskDetailResponse.model_validate(task)
    if response.status in COMPLETED_TASK_STATUSES:
        response.error_message = None
    return response


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


def _catalog_export_payload(task: OfflineTask) -> dict:
    payload = _json_loads(task.result_json)
    if payload.get("filename") or payload.get("file_path") or payload.get("oss_object_key"):
        return payload
    for step in sorted(task.steps, key=lambda item: item.id, reverse=True):
        if step.step_type != "catalog_export_template" or step.status != "done":
            continue
        step_payload = _json_loads(step.result_json)
        if step_payload.get("filename") or step_payload.get("file_path") or step_payload.get("oss_object_key"):
            return step_payload
    return payload


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
    if task_type:
        query = query.where(OfflineTask.task_type == task_type)
        count_query = count_query.where(OfflineTask.task_type == task_type)
    if status:
        query = query.where(OfflineTask.status == status)
        count_query = count_query.where(OfflineTask.status == status)
    total_result = await db.execute(count_query)
    result = await db.execute(query.offset((page - 1) * page_size).limit(page_size))
    tasks = result.scalars().all()
    responses = []
    for task in tasks:
        response = _task_response(task)
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
    response = _task_detail_response(task)
    return await _with_product_bulk_advance_progress(db, response)


@router.get("/{task_id}/download")
async def download_offline_task_result(task_id: int, db: AsyncSession = Depends(get_db)):
    task = await _load_task_with_steps(db, task_id)
    if task.task_type != "catalog_export":
        raise HTTPException(400, "当前任务没有可下载的导出文件")
    payload = _catalog_export_payload(task)
    file_path = str(payload.get("file_path") or "").strip()
    filename = str(payload.get("filename") or Path(file_path).name or f"catalog_export_{task_id}.zip")
    object_key = str(payload.get("oss_object_key") or "").strip()
    if file_path.lower().startswith(("http://", "https://")):
        file_path = ""
    if not file_path:
        if not object_key:
            raise HTTPException(400, "导出文件尚未生成")
        file_path = str(settings.DATA_DIR / "exports" / f"task_{task_id}" / filename)
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


@router.post("/{task_id}/rerun", response_model=OfflineTaskDetailResponse)
async def rerun_offline_task_api(task_id: int, db: AsyncSession = Depends(get_db)):
    try:
        task = await rerun_offline_task(db, task_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    task = await _load_task_with_steps(db, task.id)
    return _task_detail_response(task)


@router.post("/{task_id}/pause", response_model=OfflineTaskDetailResponse)
async def pause_offline_task_api(task_id: int, db: AsyncSession = Depends(get_db)):
    try:
        task = await pause_offline_task(db, task_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    task = await _load_task_with_steps(db, task.id)
    return _task_detail_response(task)


@router.post("/{task_id}/resume", response_model=OfflineTaskDetailResponse)
async def resume_offline_task_api(task_id: int, db: AsyncSession = Depends(get_db)):
    try:
        task = await resume_offline_task(db, task_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    task = await _load_task_with_steps(db, task.id)
    return _task_detail_response(task)
