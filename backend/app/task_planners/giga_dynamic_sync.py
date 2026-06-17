from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import OfflineTaskGigaDynamicSyncRequest
from app.models import ProductDataSource, TaskGroup, TaskRun, TaskStep
from app.services.giga_openapi import resolve_giga_data_source_context
from app.task_runtime.constants import STEP_STATUS_PENDING, STEP_STATUS_READY
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


async def create_giga_dynamic_sync_runs(
    db: AsyncSession,
    body: OfflineTaskGigaDynamicSyncRequest,
    *,
    kind: str,
    created_by: str | None = "web",
    auto_start: bool = True,
) -> list[TaskRun]:
    if kind not in {"inventory", "price"}:
        raise ValueError(f"不支持的同步类型: {kind}")
    sources = await _load_enabled_sources(db, body.data_source_ids)
    sku_codes = list(dict.fromkeys(str(sku).strip() for sku in (body.sku_codes or []) if str(sku or "").strip()))
    is_inventory = kind == "inventory"
    task_type = "giga_inventory_sync" if is_inventory else "giga_price_sync"
    title_prefix = "同步大健库存" if is_inventory else "同步大健价格"
    group_key = "inventory_sync" if is_inventory else "price_sync"
    step_type = task_type
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    now = datetime.now()
    runs: list[TaskRun] = []

    for source in sources:
        context = await resolve_giga_data_source_context(db, source.id, source.site)
        batch_kind = "inventory" if is_inventory else "price"
        batch_id = f"giga-{batch_kind}-r{{run_id}}-ds{context.id}-{timestamp}"
        run = TaskRun(
            task_type=task_type,
            title=f"{title_prefix}：{context.name}",
            status="pending",
            created_by=created_by,
            payload_json=json_dumps({
                "data_source_id": context.id,
                "data_source_name": context.name,
                "site": context.site,
                "sku_codes": sku_codes,
            }),
            created_at=now,
            updated_at=now,
        )
        db.add(run)
        await db.flush()

        group = TaskGroup(
            task_run_id=run.id,
            group_key=group_key,
            title=title_prefix,
            status="pending",
            sort_order=1,
            depends_on_group_keys_json=json_dumps([]),
            failure_policy="require_all_success",
            retry_policy="failed_steps_only",
            progress_current=0,
            progress_total=1,
            created_at=now,
            updated_at=now,
        )
        db.add(group)
        await db.flush()

        resolved_batch_id = batch_id.format(run_id=run.id)
        db.add(
            TaskStep(
                task_run_id=run.id,
                task_group_id=group.id,
                step_key=step_type,
                step_type=step_type,
                status=STEP_STATUS_READY if auto_start else STEP_STATUS_PENDING,
                sort_order=1,
                payload_json=json_dumps({
                    "batch_id": resolved_batch_id,
                    "site": context.site,
                    "data_source_id": context.id,
                    "data_source_name": context.name,
                    "sku_codes": sku_codes,
                }),
                progress_current=0,
                progress_total=0,
                max_attempts=3,
                created_at=now,
                updated_at=now,
            )
        )
        runs.append(run)

    await db.commit()
    for run in runs:
        await db.refresh(run)
    if auto_start:
        kick_task_runtime()
    return runs
