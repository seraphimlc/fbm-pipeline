from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models import Product
from app.models.status import STEP5_LISTING, STEP6_CURATING
from app.pipeline.engine import is_running
from app.task_planners.product_image_analysis import create_product_image_analysis_runs
from app.task_planners.product_listing import create_product_listing_runs
from app.task_runtime.events import update_step_progress
from app.task_runtime.json_utils import json_dumps, json_loads
from app.task_runtime.registry import TaskContext, register_worker


def _payload(ctx: TaskContext) -> dict[str, Any]:
    value = json_loads(ctx.step.payload_json, {})
    return value if isinstance(value, dict) else {}


async def _load_product(ctx: TaskContext, product_id: int) -> Product | None:
    result = await ctx.db.execute(
        select(Product)
        .where(Product.id == product_id)
        .options(selectinload(Product.data), selectinload(Product.catalog_item))
    )
    return result.scalar_one_or_none()


def _summary_with_row(run_summary: dict[str, Any], row_update: dict[str, Any]) -> dict[str, Any]:
    rows = run_summary.get("rows")
    if not isinstance(rows, list):
        rows = []
    product_id = row_update.get("product_id")
    replaced = False
    next_rows = []
    for row in rows:
        if isinstance(row, dict) and row.get("product_id") == product_id:
            next_rows.append({**row, **row_update})
            replaced = True
        else:
            next_rows.append(row)
    if not replaced:
        next_rows.append(row_update)
    run_summary["rows"] = next_rows
    run_summary["done_count"] = sum(1 for row in next_rows if isinstance(row, dict) and row.get("status") == "done")
    run_summary["failed_count"] = sum(1 for row in next_rows if isinstance(row, dict) and row.get("status") == "failed")
    run_summary["skipped_count"] = sum(1 for row in next_rows if isinstance(row, dict) and row.get("status") == "skipped")
    run_summary["queued_count"] = sum(1 for row in next_rows if isinstance(row, dict) and row.get("status") == "queued")
    run_summary["submitted_count"] = sum(1 for row in next_rows if isinstance(row, dict) and row.get("status") == "submitted")
    run_summary["updated_at"] = datetime.now().isoformat()
    return run_summary


async def _update_run_row(ctx: TaskContext, row_update: dict[str, Any]) -> None:
    summary = json_loads(ctx.run.summary_json, {})
    if not isinstance(summary, dict):
        summary = {}
    ctx.run.summary_json = json_dumps(_summary_with_row(summary, row_update))
    ctx.run.updated_at = datetime.now()
    await ctx.db.commit()


async def product_bulk_advance_product(ctx: TaskContext) -> dict[str, Any]:
    payload = _payload(ctx)
    product_id = int(payload.get("product_id") or 0)
    start_step = int(payload.get("start_step") or 5)
    item_code = payload.get("item_code")
    if product_id <= 0:
        raise RuntimeError("商品推进步骤缺少 product_id")
    if is_running(product_id):
        raise RuntimeError("商品流程正在运行中")

    await update_step_progress(
        ctx.db,
        ctx.step,
        current=0,
        total=1,
        message=f"开始推进商品 {item_code or product_id}",
        data={"product_id": product_id, "item_code": item_code, "start_step": start_step},
    )

    product = await _load_product(ctx, product_id)
    if not product:
        raise RuntimeError(f"商品 {product_id} 不存在")

    if start_step <= 5:
        runs = await create_product_image_analysis_runs(ctx.db, [product_id], created_by="product_bulk_advance")
        result = {
            "product_id": product_id,
            "item_code": item_code,
            "status": "submitted",
            "reason": "已提交图片分析子任务；完成后由任务链路继续 Listing",
            "latest_status": STEP6_CURATING,
            "latest_step": 5,
            "latest_result": "image_analysis_queued",
            "latest_reason": "图片分析子任务已进入任务中心",
            "task_run_ids": [run.id for run in runs],
        }
        await _update_run_row(ctx, result)
        await update_step_progress(ctx.db, ctx.step, current=1, total=1, message="已提交图片分析子任务", data=result)
        return result

    runs = await create_product_listing_runs(ctx.db, [product_id], created_by="product_bulk_advance")
    result = {
        "product_id": product_id,
        "item_code": item_code,
        "status": "submitted",
        "reason": "已提交 Listing 生成子任务",
        "latest_status": STEP5_LISTING,
        "latest_step": 6,
        "latest_result": "listing_queued",
        "latest_reason": "Listing 生成子任务已进入任务中心",
        "task_run_ids": [run.id for run in runs],
    }
    await _update_run_row(ctx, result)
    await update_step_progress(ctx.db, ctx.step, current=1, total=1, message="已提交 Listing 生成子任务", data=result)
    return result


def register_product_bulk_advance_workers() -> None:
    register_worker("product_bulk_advance_product", product_bulk_advance_product)
