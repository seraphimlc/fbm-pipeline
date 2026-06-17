from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database import async_session
from app.models import Product, ProductAplus
from app.pipeline.step7_aplus_plan import run_aplus_plan
from app.pipeline.step8_aplus_script import run_aplus_script
from app.pipeline.step9_aplus_image import run_aplus_image
from app.task_runtime.events import update_step_progress
from app.task_runtime.json_utils import json_dumps, json_loads
from app.task_runtime.registry import TaskContext, register_worker


def _payload(ctx: TaskContext) -> dict[str, Any]:
    value = json_loads(ctx.step.payload_json, {})
    return value if isinstance(value, dict) else {}


async def _set_aplus_status(
    product_id: int,
    status: str,
    *,
    error: str | None = None,
    clear_outputs: bool = False,
) -> None:
    async with async_session() as session:
        result = await session.execute(
            select(Product)
            .where(Product.id == product_id)
            .options(selectinload(Product.aplus), selectinload(Product.catalog_item))
        )
        product = result.scalar_one_or_none()
        if not product:
            return
        if not product.aplus:
            product.aplus = ProductAplus(product_id=product.id)
            session.add(product.aplus)
            await session.flush()
        if clear_outputs:
            product.aplus.aplus_plan = None
            product.aplus.aplus_plan_summary = None
            product.aplus.aplus_scripts = None
            product.aplus.aplus_scripts_summary = None
            product.aplus.aplus_images = None
            product.aplus.aplus_image_count = None
            product.aplus.planned_at = None
            product.aplus.scripted_at = None
            product.aplus.generated_at = None
        product.aplus.aplus_status = status
        if error:
            product.error_message = error
        elif product.error_message and product.error_message.startswith("A+生成"):
            product.error_message = None
        product.updated_at = datetime.now()
        if product.catalog_item:
            product.catalog_item.updated_at = product.updated_at
        await session.commit()


async def aplus_generate_product(ctx: TaskContext) -> dict[str, Any]:
    payload = _payload(ctx)
    product_id = int(payload.get("product_id") or 0)
    force = bool(payload.get("force"))
    item_code = payload.get("item_code")
    if product_id <= 0:
        raise RuntimeError("A+生成 step 缺少 product_id")

    try:
        await _set_aplus_status(product_id, "planning", clear_outputs=force)
        await update_step_progress(
            ctx.db,
            ctx.step,
            current=0,
            total=3,
            message="开始生成 A+ 规划",
            data={"product_id": product_id, "item_code": item_code},
        )
        plan = await run_aplus_plan(product_id)
        await update_step_progress(
            ctx.db,
            ctx.step,
            current=1,
            total=3,
            message="A+ 规划完成，开始生成脚本",
            data={"product_id": product_id, "item_code": item_code},
        )

        await _set_aplus_status(product_id, "scripting")
        script = await run_aplus_script(product_id)
        await update_step_progress(
            ctx.db,
            ctx.step,
            current=2,
            total=3,
            message="A+ 脚本完成，开始出图",
            data={"product_id": product_id, "item_code": item_code},
        )

        await _set_aplus_status(product_id, "imaging")
        image_result = await run_aplus_image(product_id)
        await _set_aplus_status(product_id, "done")
    except Exception as exc:
        error = f"A+生成失败: {type(exc).__name__}: {exc}"
        await _set_aplus_status(product_id, "failed", error=error)
        raise

    result_payload = {
        "product_id": product_id,
        "item_code": item_code,
        "status": "done",
        "plan": plan,
        "script": script,
        "image_result": image_result,
    }
    ctx.run.summary_json = json_dumps({
        "product_id": product_id,
        "item_code": item_code,
        "status": "aplus_done",
    })
    await ctx.db.commit()
    await update_step_progress(
        ctx.db,
        ctx.step,
        current=3,
        total=3,
        message="A+ 生成完成",
        data={"product_id": product_id, "item_code": item_code},
    )
    return result_payload


def register_aplus_generate_workers() -> None:
    register_worker("aplus_generate_product", aplus_generate_product)
