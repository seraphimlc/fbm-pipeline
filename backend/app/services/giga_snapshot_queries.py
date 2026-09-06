from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import GigaInventory, GigaPrice, GigaSku, GigaSyncBatch


GIGA_DYNAMIC_SNAPSHOT_CATEGORIES = {"inventory_snapshot", "price_snapshot"}


def _apply_store_scope(query, model, data_source_id: int | None):
    if data_source_id is not None:
        return query.where(
            GigaSyncBatch.data_source_id == data_source_id,
            model.data_source_id == data_source_id,
        )
    return query.where(
        GigaSyncBatch.data_source_id.is_(None),
        model.data_source_id.is_(None),
    )


async def completed_product_sku_codes(
    db: AsyncSession,
    *,
    site: str,
    data_source_id: int | None,
) -> list[str]:
    query = (
        select(GigaSku.sku_code)
        .join(
            GigaSyncBatch,
            (GigaSyncBatch.batch_id == GigaSku.batch_id)
            & (GigaSyncBatch.site == GigaSku.site),
        )
        .where(
            GigaSyncBatch.site == site,
            GigaSku.site == site,
            GigaSyncBatch.status == "done",
            GigaSyncBatch.sku_count > 0,
            (
                GigaSyncBatch.current_category.is_(None)
                | GigaSyncBatch.current_category.notin_(GIGA_DYNAMIC_SNAPSHOT_CATEGORIES)
            ),
        )
        .distinct()
        .order_by(GigaSku.sku_code.asc())
    )
    query = _apply_store_scope(query, GigaSku, data_source_id)
    result = await db.execute(query)
    return list(dict.fromkeys(str(value).strip() for value in result.scalars().all() if str(value or "").strip()))


async def _latest_completed_rows_by_sku(
    db: AsyncSession,
    *,
    model,
    site: str,
    data_source_id: int | None,
    sku_codes: list[str],
    exclude_batch_id: str | None = None,
    product_batches_only: bool = False,
) -> dict[str, Any]:
    normalized_skus = list(dict.fromkeys(str(sku).strip() for sku in sku_codes if str(sku or "").strip()))
    if not normalized_skus:
        return {}

    order_by = []
    if hasattr(model, "pulled_at"):
        order_by.append(model.pulled_at.desc())
    order_by.extend((
        GigaSyncBatch.finished_at.desc(),
        GigaSyncBatch.created_at.desc(),
        model.created_at.desc(),
        model.id.desc(),
    ))
    ranked = (
        select(
            model.id.label("row_id"),
            model.sku_code.label("sku_code"),
            func.row_number().over(
                partition_by=model.sku_code,
                order_by=tuple(order_by),
            ).label("row_rank"),
        )
        .join(
            GigaSyncBatch,
            (GigaSyncBatch.batch_id == model.batch_id)
            & (GigaSyncBatch.site == model.site),
        )
        .where(
            GigaSyncBatch.status == "done",
            GigaSyncBatch.site == site,
            model.site == site,
            model.sku_code.in_(normalized_skus),
        )
    )
    if exclude_batch_id:
        ranked = ranked.where(model.batch_id != exclude_batch_id)
    if product_batches_only:
        ranked = ranked.where(
            GigaSyncBatch.sku_count > 0,
            (
                GigaSyncBatch.current_category.is_(None)
                | GigaSyncBatch.current_category.notin_(GIGA_DYNAMIC_SNAPSHOT_CATEGORIES)
            ),
        )
    ranked = _apply_store_scope(ranked, model, data_source_id).subquery()
    result = await db.execute(
        select(model)
        .join(ranked, ranked.c.row_id == model.id)
        .where(ranked.c.row_rank == 1)
    )
    return {row.sku_code: row for row in result.scalars().all()}


async def latest_completed_inventory_by_sku(
    db: AsyncSession,
    *,
    site: str,
    data_source_id: int | None,
    sku_codes: list[str],
    exclude_batch_id: str | None = None,
) -> dict[str, GigaInventory]:
    return await _latest_completed_rows_by_sku(
        db,
        model=GigaInventory,
        site=site,
        data_source_id=data_source_id,
        sku_codes=sku_codes,
        exclude_batch_id=exclude_batch_id,
    )


async def latest_completed_price_by_sku(
    db: AsyncSession,
    *,
    site: str,
    data_source_id: int | None,
    sku_codes: list[str],
    exclude_batch_id: str | None = None,
) -> dict[str, GigaPrice]:
    return await _latest_completed_rows_by_sku(
        db,
        model=GigaPrice,
        site=site,
        data_source_id=data_source_id,
        sku_codes=sku_codes,
        exclude_batch_id=exclude_batch_id,
    )


async def latest_completed_product_metadata_by_sku(
    db: AsyncSession,
    *,
    site: str,
    data_source_id: int | None,
    sku_codes: list[str],
) -> dict[str, GigaSku]:
    return await _latest_completed_rows_by_sku(
        db,
        model=GigaSku,
        site=site,
        data_source_id=data_source_id,
        sku_codes=sku_codes,
        product_batches_only=True,
    )
