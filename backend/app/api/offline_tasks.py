from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.schemas import (
    OfflineTaskDetailResponse,
    OfflineTaskGigaPullRequest,
    OfflineTaskQueuedResponse,
    PaginatedOfflineTasks,
)
from app.database import get_db
from app.models import OfflineTask
from app.services.offline_tasks import create_giga_pull_task, pause_offline_task, rerun_offline_task, resume_offline_task


router = APIRouter(prefix="/api/offline-tasks", tags=["offline-tasks"])


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


@router.get("/{task_id}", response_model=OfflineTaskDetailResponse)
async def get_offline_task(task_id: int, db: AsyncSession = Depends(get_db)):
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


@router.post("/giga-pull", response_model=OfflineTaskQueuedResponse)
async def create_giga_pull_offline_task(
    body: OfflineTaskGigaPullRequest,
    db: AsyncSession = Depends(get_db),
):
    try:
        task = await create_giga_pull_task(db, body)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    result = await db.execute(
        select(OfflineTask)
        .where(OfflineTask.id == task.id)
        .options(selectinload(OfflineTask.steps))
    )
    created = result.scalar_one()
    created.steps.sort(key=lambda step: step.id)
    return OfflineTaskQueuedResponse(task=created, steps=created.steps)


@router.post("/{task_id}/rerun", response_model=OfflineTaskDetailResponse)
async def rerun_offline_task_api(task_id: int, db: AsyncSession = Depends(get_db)):
    try:
        task = await rerun_offline_task(db, task_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    result = await db.execute(
        select(OfflineTask)
        .where(OfflineTask.id == task.id)
        .options(selectinload(OfflineTask.steps))
    )
    refreshed = result.scalar_one()
    refreshed.steps.sort(key=lambda step: step.id)
    return refreshed


@router.post("/{task_id}/pause", response_model=OfflineTaskDetailResponse)
async def pause_offline_task_api(task_id: int, db: AsyncSession = Depends(get_db)):
    try:
        task = await pause_offline_task(db, task_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    result = await db.execute(
        select(OfflineTask)
        .where(OfflineTask.id == task.id)
        .options(selectinload(OfflineTask.steps))
    )
    refreshed = result.scalar_one()
    refreshed.steps.sort(key=lambda step: step.id)
    return refreshed


@router.post("/{task_id}/resume", response_model=OfflineTaskDetailResponse)
async def resume_offline_task_api(task_id: int, db: AsyncSession = Depends(get_db)):
    try:
        task = await resume_offline_task(db, task_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    result = await db.execute(
        select(OfflineTask)
        .where(OfflineTask.id == task.id)
        .options(selectinload(OfflineTask.steps))
    )
    refreshed = result.scalar_one()
    refreshed.steps.sort(key=lambda step: step.id)
    return refreshed
