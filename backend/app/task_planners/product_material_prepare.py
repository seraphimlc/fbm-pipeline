from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import TaskRun
from app.product_tasks.actions import create_product_action_runs


async def create_product_material_prepare_runs(
    db: AsyncSession,
    product_ids: list[int],
    *,
    pipeline_target: str = "export_ready",
    test_session_key: str | None = None,
    origin_task_run_id: int | None = None,
    created_by: str | None = "web",
    auto_start: bool = True,
) -> list[TaskRun]:
    requested_ids = list(dict.fromkeys(int(product_id) for product_id in product_ids))
    if not requested_ids:
        raise ValueError("请选择要准备素材的商品")
    return await create_product_action_runs(
        db,
        "product_material_prepare",
        [
            {
                "product_id": product_id,
                "pipeline_target": pipeline_target,
                "test_session_key": test_session_key,
                "origin_task_run_id": origin_task_run_id,
            }
            for product_id in requested_ids
        ],
        created_by=created_by,
        auto_start=auto_start,
    )
