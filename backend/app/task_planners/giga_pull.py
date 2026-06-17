from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import OfflineTaskGigaPullRequest
from app.models import ProductDataSource, TaskGroup, TaskRun, TaskStep
from app.services.giga_openapi import resolve_giga_data_source_context
from app.task_runtime.constants import GIGA_PULL_GROUPS, STEP_STATUS_PENDING, STEP_STATUS_READY
from app.task_runtime.json_utils import json_dumps
from app.task_runtime.scheduler import kick_task_runtime


async def _load_enabled_sources(db: AsyncSession, data_source_ids: list[int]) -> list[ProductDataSource]:
    deduped = list(dict.fromkeys(data_source_ids))
    result = await db.execute(
        select(ProductDataSource)
        .where(ProductDataSource.id.in_(deduped), ProductDataSource.enabled == 1)
        .order_by(ProductDataSource.id.asc())
    )
    sources = result.scalars().all()
    found = {source.id for source in sources}
    missing = [source_id for source_id in deduped if source_id not in found]
    if missing:
        raise ValueError(f"店铺不存在或未启用: {', '.join(map(str, missing))}")
    return sources


async def create_giga_pull_runs(
    db: AsyncSession,
    body: OfflineTaskGigaPullRequest,
    *,
    created_by: str | None = None,
    auto_start: bool = True,
) -> list[TaskRun]:
    sources = await _load_enabled_sources(db, body.data_source_ids)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    runs: list[TaskRun] = []
    for source in sources:
        context = await resolve_giga_data_source_context(db, source.id, source.site)
        run = TaskRun(
            task_type="giga_pull",
            title=f"同步店铺商品：{context.name}",
            status="pending",
            created_by=created_by,
            payload_json=json_dumps({
                "data_source_id": context.id,
                "data_source_name": context.name,
                "site": context.site,
                "current_category": body.current_category,
                "page_size": body.page_size,
                "max_pages": body.max_pages,
                "skip_existing": True,
            }),
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        db.add(run)
        await db.flush()

        groups: dict[str, TaskGroup] = {}
        for sort_order, (group_key, title) in enumerate(GIGA_PULL_GROUPS, start=1):
            group = TaskGroup(
                task_run_id=run.id,
                group_key=group_key,
                title=title,
                status="pending",
                sort_order=sort_order,
                depends_on_group_keys_json=json_dumps([GIGA_PULL_GROUPS[sort_order - 2][0]]) if sort_order > 1 else json_dumps([]),
                failure_policy="require_all_success",
                retry_policy="failed_steps_only",
                progress_current=0,
                progress_total=0,
                created_at=datetime.now(),
                updated_at=datetime.now(),
            )
            db.add(group)
            await db.flush()
            groups[group_key] = group

        batch_id = f"giga-pull-r{run.id}-ds{context.id}-{timestamp}"
        db.add(
            TaskStep(
                task_run_id=run.id,
                task_group_id=groups["plan"].id,
                step_key="plan",
                step_type="giga_pull_plan",
                status=STEP_STATUS_READY if auto_start else STEP_STATUS_PENDING,
                sort_order=1,
                payload_json=json_dumps({
                    "batch_id": batch_id,
                    "site": context.site,
                    "data_source_id": context.id,
                    "data_source_name": context.name,
                    "current_category": body.current_category,
                    "page_size": body.page_size,
                    "max_pages": body.max_pages,
                    "skip_existing": True,
                }),
                progress_current=0,
                progress_total=0,
                max_attempts=3,
                created_at=datetime.now(),
                updated_at=datetime.now(),
            )
        )
        runs.append(run)
    await db.commit()
    for run in runs:
        await db.refresh(run)
    if auto_start:
        kick_task_runtime()
    return runs
