from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.product_tasks.actions import create_product_action_runs


async def create_product_auto_competitor_selection_runs(
    db: AsyncSession,
    product_ids: list[int],
    *,
    created_by: str | None = "web",
    auto_start: bool = True,
):
    return await create_product_action_runs(
        db,
        "product_auto_competitor_selection",
        [{"product_id": product_id} for product_id in product_ids],
        created_by=created_by,
        auto_start=auto_start,
    )
