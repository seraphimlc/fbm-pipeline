from typing import Any

from app.services.giga_inventory_sync import GigaInventorySyncOptions, sync_giga_inventory_snapshot
from app.services.giga_price_sync import GigaPriceSyncOptions, sync_giga_price_snapshot
from app.task_runtime.events import update_step_progress
from app.task_runtime.json_utils import json_dumps, json_loads
from app.task_runtime.registry import TaskContext, register_worker


def _payload(ctx: TaskContext) -> dict[str, Any]:
    value = json_loads(ctx.step.payload_json, {})
    return value if isinstance(value, dict) else {}


async def giga_inventory_sync(ctx: TaskContext) -> dict[str, Any]:
    payload = _payload(ctx)
    await update_step_progress(ctx.db, ctx.step, current=0, total=0, message="开始同步 GIGA 库存", data=payload)
    result = await sync_giga_inventory_snapshot(
        ctx.db,
        GigaInventorySyncOptions(
            task_id=f"task_run:{ctx.run.id}:step:{ctx.step.id}",
            batch_id=str(payload.get("batch_id") or ""),
            site=str(payload.get("site") or "US"),
            data_source_id=int(payload.get("data_source_id") or 0),
            sku_codes=payload.get("sku_codes") or [],
        ),
    )
    result_payload = result.__dict__
    ctx.run.summary_json = json_dumps(result_payload)
    await ctx.db.commit()
    await update_step_progress(
        ctx.db,
        ctx.step,
        current=result.success_count,
        total=result.total_skus,
        message="GIGA 库存同步完成" if result.failed_count == 0 else f"{result.failed_count} 个 SKU 库存同步失败",
        data=result_payload,
    )
    if result.failed_count:
        raise RuntimeError(f"{result.failed_count} 个 SKU 库存同步失败")
    return result_payload


async def giga_price_sync(ctx: TaskContext) -> dict[str, Any]:
    payload = _payload(ctx)
    await update_step_progress(ctx.db, ctx.step, current=0, total=0, message="开始同步 GIGA 价格", data=payload)
    result = await sync_giga_price_snapshot(
        ctx.db,
        GigaPriceSyncOptions(
            task_id=f"task_run:{ctx.run.id}:step:{ctx.step.id}",
            batch_id=str(payload.get("batch_id") or ""),
            site=str(payload.get("site") or "US"),
            data_source_id=int(payload.get("data_source_id") or 0),
            sku_codes=payload.get("sku_codes") or [],
        ),
    )
    result_payload = result.__dict__
    ctx.run.summary_json = json_dumps(result_payload)
    await ctx.db.commit()
    await update_step_progress(
        ctx.db,
        ctx.step,
        current=result.success_count,
        total=result.total_skus,
        message="GIGA 价格同步完成" if result.failed_count == 0 else f"{result.failed_count} 个 SKU 价格同步失败",
        data=result_payload,
    )
    if result.failed_count:
        raise RuntimeError(f"{result.failed_count} 个 SKU 价格同步失败")
    return result_payload


def register_giga_dynamic_sync_workers() -> None:
    register_worker("giga_inventory_sync", giga_inventory_sync)
    register_worker("giga_price_sync", giga_price_sync)
