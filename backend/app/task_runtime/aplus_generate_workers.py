from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database import async_session
from app.models import Product, ProductAplus
from app.models.status import (
    PENDING_REVIEW,
    WORKFLOW_NODE_CONFIRM_IMAGES_APLUS,
    WORKFLOW_NODE_GENERATE_APLUS,
    WORKFLOW_STATUS_FAILED,
    WORKFLOW_STATUS_PENDING,
    WORKFLOW_STATUS_PROCESSING,
)
from app.product_tasks.workflow import set_product_workflow
from app.pipeline.step7_aplus_plan import run_aplus_plan
from app.pipeline.step8_aplus_script import run_aplus_script
from app.pipeline.step9_aplus_image import run_aplus_image
from app.services.product_payloads import invalidate_sections, large_field_storage_enabled, load_section, parse_payload
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
            product.aplus.aplus_plan_summary = None
            product.aplus.aplus_scripts_summary = None
            product.aplus.aplus_image_count = None
            product.aplus.planned_at = None
            product.aplus.scripted_at = None
            product.aplus.generated_at = None
            if await large_field_storage_enabled(session):
                await invalidate_sections(session, product.id, ("aplus_plan", "aplus_script", "aplus_assets"))
            else:
                product.aplus.aplus_plan = None
                product.aplus.aplus_scripts = None
                product.aplus.aplus_images = None
        product.aplus.aplus_status = status
        # Auto A+ is the final generated asset gate before export.  Preserve
        # already confirmed/exported products when a user manually regenerates
        # A+, but make the automatic pending-review path explicitly reviewable.
        is_pre_export_review = (
            product.status == PENDING_REVIEW
            and product.workflow_node in {WORKFLOW_NODE_GENERATE_APLUS, WORKFLOW_NODE_CONFIRM_IMAGES_APLUS}
        )
        if is_pre_export_review:
            if status in {"done", "regen_done"}:
                set_product_workflow(
                    product,
                    node=WORKFLOW_NODE_CONFIRM_IMAGES_APLUS,
                    status=WORKFLOW_STATUS_PENDING,
                    error=None,
                )
            elif status == "failed":
                set_product_workflow(
                    product,
                    node=WORKFLOW_NODE_GENERATE_APLUS,
                    status=WORKFLOW_STATUS_FAILED,
                    error=error or "A+ 图片生成失败",
                )
            else:
                set_product_workflow(
                    product,
                    node=WORKFLOW_NODE_GENERATE_APLUS,
                    status=WORKFLOW_STATUS_PROCESSING,
                    error=None,
                )
        if error:
            product.error_message = error
        elif product.error_message and product.error_message.startswith("A+生成"):
            product.error_message = None
        product.updated_at = datetime.now()
        if product.catalog_item:
            product.catalog_item.updated_at = product.updated_at
        await session.commit()


async def _has_verified_complete_aplus_images(product_id: int) -> bool:
    """Return true only for a fully persisted, locally readable five-image result."""
    async with async_session() as session:
        aplus = await session.scalar(select(ProductAplus).where(ProductAplus.product_id == product_id))
        if not aplus or int(aplus.aplus_image_count or 0) != 5:
            return False
        if await large_field_storage_enabled(session):
            record = await load_section(session, product_id, "aplus_assets")
            images = parse_payload(record.payload_json) if record and record.payload_json else []
        else:
            images = json_loads(aplus.aplus_images, [])
        if not isinstance(images, list) or len(images) != 5:
            return False
        positions: set[int] = set()
        for image in images:
            if not isinstance(image, dict) or image.get("status") != "done":
                return False
            position = int(image.get("position") or 0)
            path = str(image.get("path") or "").strip()
            if position < 1 or position > 5 or not path or not Path(path).is_file():
                return False
            positions.add(position)
        return positions == {1, 2, 3, 4, 5}


async def _load_verified_aplus_phase(product_id: int, field_name: str, item_key: str) -> dict[str, Any] | None:
    """Reuse a persisted Step 7/8 artifact after a runner restart.

    Step 7 and Step 8 commit their own validated artifacts before the next
    network phase starts.  Recalling an LLM only because the worker stopped
    later is wasteful and can turn a recoverable transport close into a second
    failure.  Require all five ordered modules/scripts before reuse.
    """
    async with async_session() as session:
        aplus = await session.scalar(select(ProductAplus).where(ProductAplus.product_id == product_id))
        if await large_field_storage_enabled(session):
            section = "aplus_plan" if field_name == "aplus_plan" else "aplus_script"
            record = await load_section(session, product_id, section)
            value = parse_payload(record.payload_json) if record and record.payload_json else {}
        else:
            raw_value = getattr(aplus, field_name, None) if aplus else None
            value = json_loads(raw_value, {})
        items = value.get(item_key) if isinstance(value, dict) else None
        if not isinstance(items, list) or len(items) != 5:
            return None
        positions: set[int] = set()
        for item in items:
            if not isinstance(item, dict):
                return None
            position = int(item.get("position") or item.get("module_position") or 0)
            if position < 1 or position > 5:
                return None
            positions.add(position)
        return value if positions == {1, 2, 3, 4, 5} else None


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
        plan = await _load_verified_aplus_phase(product_id, "aplus_plan", "modules")
        if plan is None:
            plan = await run_aplus_plan(product_id)
        else:
            await update_step_progress(
                ctx.db,
                ctx.step,
                current=0,
                total=3,
                message="复用已验证 A+ 规划，开始生成脚本",
                data={"product_id": product_id, "item_code": item_code, "reused_phase": "plan"},
            )
        await update_step_progress(
            ctx.db,
            ctx.step,
            current=1,
            total=3,
            message="A+ 规划完成，开始生成脚本",
            data={"product_id": product_id, "item_code": item_code},
        )

        await _set_aplus_status(product_id, "scripting")
        script = await _load_verified_aplus_phase(product_id, "aplus_scripts", "scripts")
        if script is None:
            script = await run_aplus_script(product_id)
        else:
            await update_step_progress(
                ctx.db,
                ctx.step,
                current=1,
                total=3,
                message="复用已验证 A+ 脚本，开始出图",
                data={"product_id": product_id, "item_code": item_code, "reused_phase": "script"},
            )
        await update_step_progress(
            ctx.db,
            ctx.step,
            current=2,
            total=3,
            message="A+ 脚本完成，开始出图",
            data={"product_id": product_id, "item_code": item_code},
        )

        await _set_aplus_status(product_id, "imaging")
        try:
            image_result = await run_aplus_image(product_id)
        except Exception as image_exc:
            # A provider transport can close while Step 9 is exiting its HTTP
            # client after it has already committed all five validated images.
            # Treat that verifiable completed state as success instead of
            # rerunning paid image generation or overwriting it as failed.
            if not await _has_verified_complete_aplus_images(product_id):
                raise
            image_result = {
                "total": 5,
                "success": 5,
                "generated": 0,
                "recovered_after_image_transport_error": f"{type(image_exc).__name__}: {image_exc}",
            }
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
