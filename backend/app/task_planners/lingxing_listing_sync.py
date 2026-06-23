from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.models import CatalogProduct, Product, TaskGroup, TaskRun, TaskStep
from app.services.asin_match_policy import seller_sku_candidate
from app.task_runtime.constants import STEP_STATUS_PENDING, STEP_STATUS_READY
from app.task_runtime.json_utils import json_dumps
from app.task_runtime.scheduler import kick_task_runtime


ACTIVE_RUN_STATUSES = {"pending", "running"}


def _clean_optional(value: str | int | None) -> str | None:
    cleaned = str(value or "").strip()
    return cleaned or None


def _dedupe_key(*, catalog_id: int, seller_sku: str | None) -> str:
    key_sku = seller_sku or "missing"
    return f"lingxing_listing_sync:catalog:{catalog_id}:seller_sku:{key_sku}"


async def create_lingxing_listing_sync_runs(
    db: AsyncSession,
    catalog_product_ids: list[int],
    *,
    store_name: str | None = None,
    store_id: str | int | None = None,
    site: str | None = None,
    created_by: str | None = "web",
    auto_start: bool = True,
) -> tuple[list[TaskRun], list[str]]:
    requested_ids = list(dict.fromkeys(int(item_id) for item_id in catalog_product_ids))
    if not requested_ids:
        raise ValueError("请选择要同步的商品")
    if len(requested_ids) > 1000:
        raise ValueError("单次最多同步 1000 个商品")

    result = await db.execute(
        select(CatalogProduct)
        .where(CatalogProduct.id.in_(requested_ids))
        .options(selectinload(CatalogProduct.source_product).selectinload(Product.data))
    )
    catalog_by_id = {item.id: item for item in result.scalars().all()}
    errors: list[str] = []
    runs: list[TaskRun] = []
    now = datetime.now()

    for catalog_id in requested_ids:
        catalog = catalog_by_id.get(catalog_id)
        if not catalog:
            errors.append(f"商品资料 {catalog_id} 不存在")
            continue
        product = catalog.source_product
        candidate = seller_sku_candidate(catalog)
        seller_sku = candidate.value
        dedupe_key = _dedupe_key(catalog_id=catalog.id, seller_sku=seller_sku)
        existing = (
            await db.execute(
                select(TaskRun)
                .where(TaskRun.dedupe_key == dedupe_key)
                .where(TaskRun.status.in_(tuple(ACTIVE_RUN_STATUSES)))
            )
        ).scalar_one_or_none()
        if existing:
            runs.append(existing)
            continue

        title_sku = seller_sku or (catalog.item_code or f"catalog-{catalog.id}")
        run = TaskRun(
            task_type="lingxing_listing_sync",
            title=f"领星 Listing / ASIN 同步：{title_sku}",
            status="pending",
            created_by=created_by,
            dedupe_key=dedupe_key,
            correlation_key=f"product:{catalog.source_product_id}:lingxing_aplus_publish",
            idempotency_key=dedupe_key,
            payload_json=json_dumps({
                "catalog_product_id": catalog.id,
                "product_id": catalog.source_product_id,
                "seller_sku": seller_sku,
                "seller_sku_source": candidate.source,
                "seller_sku_reason": candidate.reason,
                "auxiliary_upc": catalog.upc or (product.upc if product else None),
                "store_name": _clean_optional(store_name) or _clean_optional(settings.LINGXING_APLUS_STORE_NAME),
                "store_id": _clean_optional(store_id) or _clean_optional(settings.LINGXING_APLUS_STORE_ID),
                "site": _clean_optional(site) or _clean_optional(settings.LINGXING_APLUS_SITE),
            }),
            created_at=now,
            updated_at=now,
        )
        db.add(run)
        await db.flush()
        group = TaskGroup(
            task_run_id=run.id,
            group_key="listing_sync",
            title="Listing / ASIN 对齐",
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
        db.add(
            TaskStep(
                task_run_id=run.id,
                task_group_id=group.id,
                step_key=f"catalog:{catalog.id}:lingxing_listing_sync_product",
                step_type="lingxing_listing_sync_product",
                status=STEP_STATUS_READY if auto_start else STEP_STATUS_PENDING,
                sort_order=1,
                payload_json=run.payload_json,
                progress_current=0,
                progress_total=1,
                max_attempts=2,
                created_at=now,
                updated_at=now,
            )
        )
        runs.append(run)

    await db.commit()
    for run in runs:
        await db.refresh(run)
    if auto_start and runs:
        kick_task_runtime()
    return runs, errors
