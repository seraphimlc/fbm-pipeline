from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import CatalogProduct, Product, ProductAplus, TaskGroup, TaskRun, TaskStep
from app.pipeline.engine import is_running
from app.task_runtime.constants import STEP_STATUS_PENDING, STEP_STATUS_READY
from app.task_runtime.json_utils import json_dumps, json_loads
from app.task_runtime.scheduler import kick_task_runtime

APLUS_GENERATE_ACTIVE_STATUSES = {"queued", "planning", "scripting", "imaging"}


def _aplus_ready_error(product: Product | None, catalog: CatalogProduct | None) -> str | None:
    if not product:
        return "缺少关联商品，不能生成 A+"
    if not catalog or catalog.confirmed_at is None:
        return "未加入待导出，不能生成 A+"
    if is_running(product.id):
        return "商品主流程仍在运行，不能生成 A+"
    if not product.data or not product.data.listing_title or not product.data.listing_bullets:
        return "Listing 文案未完成，不能生成 A+"
    if not product.images or not product.images.image_analysis:
        return "图片分析未完成，不能生成 A+"
    return None


async def _active_aplus_product_ids(db: AsyncSession) -> set[int]:
    result = await db.execute(
        select(TaskStep).where(
            TaskStep.step_type == "aplus_generate_product",
            TaskStep.status.in_(("pending", "ready", "running")),
        )
    )
    active_ids: set[int] = set()
    for step in result.scalars().all():
        payload = json_loads(step.payload_json, {})
        if isinstance(payload, dict) and str(payload.get("product_id") or "").isdigit():
            active_ids.add(int(payload["product_id"]))
    return active_ids


async def create_aplus_generate_runs(
    db: AsyncSession,
    catalog_product_ids: list[int],
    *,
    force: bool = False,
    created_by: str | None = "web",
    auto_start: bool = True,
) -> tuple[list[TaskRun], list[str], list[int]]:
    requested_ids = list(dict.fromkeys(int(item_id) for item_id in catalog_product_ids))
    if not requested_ids:
        raise ValueError("请选择要生成 A+ 的商品")

    result = await db.execute(
        select(CatalogProduct)
        .where(CatalogProduct.id.in_(requested_ids))
        .options(
            selectinload(CatalogProduct.source_product).selectinload(Product.data),
            selectinload(CatalogProduct.source_product).selectinload(Product.images),
            selectinload(CatalogProduct.source_product).selectinload(Product.aplus),
        )
    )
    catalog_items = result.scalars().all()
    catalog_by_id = {item.id: item for item in catalog_items}
    active_product_ids = await _active_aplus_product_ids(db)
    errors: list[str] = []
    eligible: list[tuple[CatalogProduct, Product]] = []
    now = datetime.now()

    for catalog_id in requested_ids:
        catalog = catalog_by_id.get(catalog_id)
        if not catalog:
            errors.append(f"商品资料 {catalog_id} 不存在")
            continue
        product = catalog.source_product
        ready_error = _aplus_ready_error(product, catalog)
        if ready_error:
            errors.append(f"商品资料 {catalog_id}: {ready_error}")
            continue
        if product.id in active_product_ids:
            errors.append(f"商品 {product.id} A+ 已在新任务中心生成中")
            continue
        if not product.aplus:
            product.aplus = ProductAplus(product_id=product.id)
            db.add(product.aplus)
            await db.flush()
        if product.aplus.aplus_status in APLUS_GENERATE_ACTIVE_STATUSES:
            errors.append(f"商品 {product.id} A+ 已在生成中")
            continue
        if product.aplus.aplus_status == "done" and not force:
            errors.append(f"商品 {product.id} A+ 已生成，如需重跑请使用强制重跑")
            continue
        product.aplus.aplus_status = "queued"
        if product.error_message and product.error_message.startswith("A+生成"):
            product.error_message = None
        product.updated_at = now
        catalog.updated_at = now
        eligible.append((catalog, product))

    if not eligible:
        await db.commit()
        return [], errors, []

    run = TaskRun(
        task_type="aplus_generate",
        title=f"A+生成（{len(eligible)} 个商品）",
        status="pending",
        created_by=created_by,
        payload_json=json_dumps({
            "catalog_product_ids": [catalog.id for catalog, _ in eligible],
            "requested_catalog_product_ids": requested_ids,
            "force": force,
            "errors": errors,
        }),
        created_at=now,
        updated_at=now,
    )
    db.add(run)
    await db.flush()
    group = TaskGroup(
        task_run_id=run.id,
        group_key="aplus_generate",
        title="A+生成",
        status="pending",
        sort_order=1,
        depends_on_group_keys_json=json_dumps([]),
        failure_policy="allow_partial_success",
        retry_policy="failed_steps_only",
        progress_current=0,
        progress_total=len(eligible),
        created_at=now,
        updated_at=now,
    )
    db.add(group)
    await db.flush()

    for sort_order, (catalog, product) in enumerate(eligible, start=1):
        item_code = product.data.item_code if product.data else None
        db.add(
            TaskStep(
                task_run_id=run.id,
                task_group_id=group.id,
                step_key=f"product:{product.id}:aplus",
                step_type="aplus_generate_product",
                status=STEP_STATUS_READY if auto_start and sort_order == 1 else STEP_STATUS_PENDING,
                sort_order=sort_order,
                progress_current=0,
                progress_total=3,
                payload_json=json_dumps({
                    "catalog_product_id": catalog.id,
                    "product_id": product.id,
                    "item_code": item_code,
                    "force": force,
                }),
                max_attempts=2,
                created_at=now,
                updated_at=now,
            )
        )

    await db.commit()
    await db.refresh(run)
    if auto_start:
        kick_task_runtime()
    return [run], errors, [product.id for _, product in eligible]
