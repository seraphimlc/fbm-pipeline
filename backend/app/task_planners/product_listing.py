from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Product, TaskRun
from app.product_tasks.actions import create_product_action_runs


async def create_product_listing_runs(
    db: AsyncSession,
    product_ids: list[int],
    *,
    created_by: str | None = "web",
    auto_start: bool = True,
) -> list[TaskRun]:
    requested_ids = list(dict.fromkeys(int(product_id) for product_id in product_ids))
    if not requested_ids:
        raise ValueError("请选择要生成 Listing 的商品")

    result = await db.execute(
        select(Product)
        .where(Product.id.in_(requested_ids))
        .options(selectinload(Product.data))
        .order_by(Product.id.asc())
    )
    products = {product.id: product for product in result.scalars().all()}
    missing = [product_id for product_id in requested_ids if product_id not in products]
    if missing:
        raise ValueError(f"商品不存在: {', '.join(map(str, missing))}")

    return await create_product_action_runs(
        db,
        "product_listing_generation",
        [
            {
                "product_id": product_id,
                "item_code": products[product_id].data.item_code if products[product_id].data else products[product_id].gigab2b_product_id,
            }
            for product_id in requested_ids
        ],
        created_by=created_by,
        auto_start=auto_start,
    )
