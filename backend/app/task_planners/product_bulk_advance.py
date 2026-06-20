from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Product, TaskGroup, TaskRun, TaskStep
from app.models.status import COMPLETED
from app.pipeline.engine import _assert_step_prerequisites, is_running
from app.task_runtime.constants import STEP_STATUS_READY
from app.task_runtime.json_utils import json_dumps
from app.task_runtime.scheduler import kick_task_runtime

PRODUCT_BULK_ADVANCE_MAX_PRODUCTS = 1000


def _generation_start_step(product: Product) -> int:
    if (product.current_step or 0) >= 6:
        return 6
    if product.images and product.images.image_analysis:
        return 6
    return max(product.current_step or 5, 5)


async def _prerequisite_error(product_id: int, start_step: int) -> str | None:
    try:
        await _assert_step_prerequisites(product_id, start_step)
    except Exception as exc:
        detail = getattr(exc, "detail", None)
        return str(detail or exc)
    return None


async def create_product_bulk_advance_run(
    db: AsyncSession,
    product_ids: list[int],
    *,
    payload_extra: dict | None = None,
    title_suffix: str | None = None,
    start_step_override: int | None = None,
    created_by: str | None = "web",
    auto_start: bool = True,
) -> TaskRun:
    requested_ids = list(dict.fromkeys(int(product_id) for product_id in product_ids))
    if len(requested_ids) > PRODUCT_BULK_ADVANCE_MAX_PRODUCTS:
        raise HTTPException(400, f"单次最多批量推进 {PRODUCT_BULK_ADVANCE_MAX_PRODUCTS} 个商品")

    result = await db.execute(
        select(Product)
        .options(selectinload(Product.data), selectinload(Product.images), selectinload(Product.aplus))
        .where(Product.id.in_(requested_ids))
    )
    products = {product.id: product for product in result.scalars().all()}

    rows: list[dict] = []
    startable: list[dict] = []
    now = datetime.now()
    for product_id in requested_ids:
        product = products.get(product_id)
        if not product:
            rows.append({
                "product_id": product_id,
                "item_code": None,
                "status": "skipped",
                "reason": "商品不存在",
                "current_status": None,
                "current_step": None,
            })
            continue

        item_code = product.data.item_code if product.data else product.gigab2b_product_id
        base_row = {
            "product_id": product.id,
            "item_code": item_code,
            "current_status": product.status,
            "current_step": product.current_step,
        }
        start_step = start_step_override or _generation_start_step(product)
        if start_step > 6:
            start_step = 6
        if product.status == COMPLETED and (product.current_step or 0) >= 6 and start_step != 6:
            rows.append({**base_row, "status": "skipped", "reason": "已在待导出状态，无需推进"})
            continue
        if product.status in {"source_unavailable", "unavailable"}:
            rows.append({**base_row, "status": "skipped", "reason": f"当前状态不能推进: {product.status}"})
            continue
        if product.status == "paused":
            rows.append({**base_row, "status": "skipped", "reason": "商品已挂起，请先在页面点击继续"})
            continue
        if is_running(product.id):
            rows.append({**base_row, "status": "skipped", "reason": "商品流程正在运行中"})
            continue
        if (product.current_step or 0) < 5:
            rows.append({**base_row, "status": "skipped", "reason": "尚未完成图片确认和竞品选择，不能批量进入生成"})
            continue
        prerequisite_error = await _prerequisite_error(product.id, start_step)
        if prerequisite_error:
            rows.append({**base_row, "status": "skipped", "reason": prerequisite_error})
            continue

        row = {
            **base_row,
            "status": "queued",
            "reason": "待提交图片分析子任务，完成后由任务链路继续 Listing"
            if start_step <= 5
            else f"待提交 Step {start_step} 生成子任务",
            "start_step": start_step,
        }
        rows.append(row)
        startable.append(row)

    started_count = len(startable)
    skipped_count = len(rows) - started_count
    status = "pending" if started_count else "partial_failed"
    payload = {"product_ids": requested_ids}
    if payload_extra:
        payload.update(payload_extra)
    summary = {
        "status": status,
        "requested_count": len(requested_ids),
        "started_count": started_count,
        "skipped_count": skipped_count,
        "failed_count": 0,
        "done_count": 0,
        "submitted_count": 0,
        "rows": rows,
        "created_at": now.isoformat(),
    }

    run = TaskRun(
        task_type="product_bulk_advance",
        title=f"批量提交商品生成任务：{len(requested_ids)} 个商品{title_suffix or ''}",
        status=status,
        created_by=created_by,
        payload_json=json_dumps(payload),
        summary_json=json_dumps(summary),
        created_at=now,
        started_at=None,
        finished_at=None if started_count else now,
        updated_at=now,
    )
    db.add(run)
    await db.flush()

    if started_count:
        group = TaskGroup(
            task_run_id=run.id,
            group_key="product_bulk_advance",
            title="批量提交商品生成任务",
            status="pending",
            sort_order=1,
            depends_on_group_keys_json=json_dumps([]),
            failure_policy="allow_partial_success",
            retry_policy="failed_steps_only",
            progress_current=0,
            progress_total=started_count,
            created_at=now,
            updated_at=now,
        )
        db.add(group)
        await db.flush()
        for index, row in enumerate(startable, start=1):
            db.add(TaskStep(
                task_run_id=run.id,
                task_group_id=group.id,
                step_key=f"product:{row['product_id']}:advance",
                step_type="product_bulk_advance_product",
                status=STEP_STATUS_READY if auto_start and index == 1 else "pending",
                sort_order=index,
                progress_current=0,
                progress_total=1,
                payload_json=json_dumps({
                    "product_id": row["product_id"],
                    "item_code": row.get("item_code"),
                    "start_step": row["start_step"],
                    "current_status": row.get("current_status"),
                    "current_step": row.get("current_step"),
                }),
                max_attempts=2,
                created_at=now,
                updated_at=now,
            ))

    await db.commit()
    await db.refresh(run)
    if auto_start and started_count:
        kick_task_runtime()
    return run
