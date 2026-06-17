from sqlalchemy.ext.asyncio import AsyncSession

from app.models import TaskRun
from app.product_tasks.actions import create_product_action_runs


async def create_product_image_analysis_runs(
    db: AsyncSession,
    product_ids: list[int],
    *,
    created_by: str | None = "web",
    auto_start: bool = True,
) -> list[TaskRun]:
    requested_ids = list(dict.fromkeys(int(product_id) for product_id in product_ids))
    if not requested_ids:
        raise ValueError("请选择要执行图片分析的商品")
    return await create_product_action_runs(
        db,
        "product_image_analysis",
        [{"product_id": product_id} for product_id in requested_ids],
        created_by=created_by,
        auto_start=auto_start,
    )
