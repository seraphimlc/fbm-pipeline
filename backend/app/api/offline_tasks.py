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
    OfflineTaskGigaPullRequest,
    OfflineTaskQueuedResponse,
    PaginatedOfflineTasks,
)
from app.config import settings
from app.database import get_db
from app.models import OfflineTask
from app.services.oss_uploader import download_private_file
from app.services.offline_tasks import (
    create_catalog_export_tasks,
    create_giga_dynamic_sync_task,
    create_giga_pull_task,
    pause_offline_task,
    rerun_offline_task,
    resume_offline_task,
)


router = APIRouter(prefix="/api/offline-tasks", tags=["offline-tasks"])


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
    return PaginatedOfflineTasks(
        items=result.scalars().all(),
        total=total_result.scalar() or 0,
        page=page,
        page_size=page_size,
    )


@router.post("/giga-pull", response_model=OfflineTaskQueuedResponse)
async def create_giga_pull_offline_task(
    body: OfflineTaskGigaPullRequest,
    db: AsyncSession = Depends(get_db),
):
    try:
        task = await create_giga_pull_task(db, body)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    created = await _load_task_with_steps(db, task.id)
    return OfflineTaskQueuedResponse(task=created, steps=created.steps)


@router.post("/giga-inventory-sync", response_model=OfflineTaskQueuedResponse)
async def create_giga_inventory_sync_offline_task(
    body: OfflineTaskGigaDynamicSyncRequest,
    db: AsyncSession = Depends(get_db),
):
    try:
        task = await create_giga_dynamic_sync_task(db, body, kind="inventory")
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    created = await _load_task_with_steps(db, task.id)
    return OfflineTaskQueuedResponse(task=created, steps=created.steps)


@router.post("/giga-price-sync", response_model=OfflineTaskQueuedResponse)
async def create_giga_price_sync_offline_task(
    body: OfflineTaskGigaDynamicSyncRequest,
    db: AsyncSession = Depends(get_db),
):
    try:
        task = await create_giga_dynamic_sync_task(db, body, kind="price")
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    created = await _load_task_with_steps(db, task.id)
    return OfflineTaskQueuedResponse(task=created, steps=created.steps)


@router.post("/catalog-export", response_model=OfflineTaskBatchQueuedResponse)
async def create_catalog_export_offline_tasks(
    body: OfflineTaskCatalogExportRequest,
    db: AsyncSession = Depends(get_db),
):
    try:
        tasks, errors = await create_catalog_export_tasks(db, body)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return OfflineTaskBatchQueuedResponse(tasks=tasks, errors=errors)


@router.get("/{task_id}", response_model=OfflineTaskDetailResponse)
async def get_offline_task(task_id: int, db: AsyncSession = Depends(get_db)):
    return await _load_task_with_steps(db, task_id)


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
    return await _load_task_with_steps(db, task.id)


@router.post("/{task_id}/pause", response_model=OfflineTaskDetailResponse)
async def pause_offline_task_api(task_id: int, db: AsyncSession = Depends(get_db)):
    try:
        task = await pause_offline_task(db, task_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return await _load_task_with_steps(db, task.id)


@router.post("/{task_id}/resume", response_model=OfflineTaskDetailResponse)
async def resume_offline_task_api(task_id: int, db: AsyncSession = Depends(get_db)):
    try:
        task = await resume_offline_task(db, task_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return await _load_task_with_steps(db, task.id)
