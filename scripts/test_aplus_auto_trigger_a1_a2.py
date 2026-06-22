from __future__ import annotations

import argparse
import asyncio
from datetime import datetime
from pathlib import Path
import sys

from sqlalchemy import delete, func, select
from sqlalchemy.orm import selectinload

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.database import async_session, run_schema_maintenance  # noqa: E402
from app.models import CatalogProduct, Product, ProductAplus, ProductData, ProductFile, ProductImage, TaskGroup, TaskRun, TaskStep, TaskStepEvent  # noqa: E402
from app.models.status import COMPLETED, WORKFLOW_NODE_FLOW_DONE, WORKFLOW_NODE_LISTING_GENERATION, WORKFLOW_STATUS_PENDING, WORKFLOW_STATUS_SUCCEEDED  # noqa: E402
from app.services.aplus_auto_trigger import should_auto_start_aplus  # noqa: E402
from app.task_runtime.constants import RUN_STATUS_RUNNING, STEP_STATUS_RUNNING  # noqa: E402
from app.task_runtime.json_utils import json_dumps  # noqa: E402


TEST_PREFIX = "APLUS_A1_TEST_"


async def _cleanup_markers() -> None:
    async with async_session() as session:
        product_ids = list(
            (
                await session.execute(select(Product.id).where(Product.gigab2b_product_id.like(f"{TEST_PREFIX}%")))
            ).scalars().all()
        )
        run_ids = list(
            (
                await session.execute(select(TaskRun.id).where(TaskRun.created_by == "aplus-a1-test"))
            ).scalars().all()
        )
        if run_ids:
            await session.execute(delete(TaskStepEvent).where(TaskStepEvent.task_run_id.in_(run_ids)))
            await session.execute(delete(TaskStep).where(TaskStep.task_run_id.in_(run_ids)))
            await session.execute(delete(TaskGroup).where(TaskGroup.task_run_id.in_(run_ids)))
            await session.execute(delete(TaskRun).where(TaskRun.id.in_(run_ids)))
        if product_ids:
            await session.execute(delete(ProductFile).where(ProductFile.product_id.in_(product_ids)))
            await session.execute(delete(ProductAplus).where(ProductAplus.product_id.in_(product_ids)))
            await session.execute(delete(ProductImage).where(ProductImage.product_id.in_(product_ids)))
            await session.execute(delete(CatalogProduct).where(CatalogProduct.source_product_id.in_(product_ids)))
            await session.execute(delete(ProductData).where(ProductData.product_id.in_(product_ids)))
            await session.execute(delete(Product).where(Product.id.in_(product_ids)))
        await session.commit()


async def _make_product(
    session,
    marker: str,
    *,
    status: str = COMPLETED,
    workflow_node: str | None = WORKFLOW_NODE_FLOW_DONE,
    workflow_status: str | None = WORKFLOW_STATUS_SUCCEEDED,
    confirmed_at: datetime | None | object = ...,
    listing_title: str | None = "A+ ready listing title",
    listing_bullets: str | None = None,
    image_analysis: str | None = None,
    aplus_status: str | None = None,
    product_aplus_upload_status: str | None = "not_uploaded",
    catalog_aplus_upload_status: str | None = "not_uploaded",
    aplus_uploaded: bool = False,
    product_amazon_asin: str | None = None,
    catalog_amazon_asin: str | None = None,
    catalog_exported: bool = False,
    template_output: bool = False,
    template_file: bool = False,
) -> Product:
    now = datetime.now()
    if confirmed_at is ...:
        confirmed_at = now
    product = Product(
        gigab2b_url=f"https://aplus-a1.example/{marker}",
        gigab2b_product_id=f"{TEST_PREFIX}{marker}",
        amazon_asin=product_amazon_asin,
        aplus_upload_status=product_aplus_upload_status,
        aplus_uploaded_at=now if aplus_uploaded else None,
        status=status,
        current_step=6 if status == COMPLETED else 5,
        workflow_node=workflow_node,
        workflow_status=workflow_status,
        created_at=now,
        updated_at=now,
    )
    product.data = ProductData(
        item_code=f"{TEST_PREFIX}{marker}",
        title=f"A1 fixture {marker}",
        listing_title=listing_title,
        listing_bullets=listing_bullets if listing_bullets is not None else json_dumps(["Durable fixture bullet"]),
        amazon_template_path="/tmp/aplus-a1-template.xlsm" if template_output else None,
        amazon_template_fill_summary=json_dumps({"template": "done"}) if template_output else None,
        amazon_template_generated_at=now if template_output else None,
    )
    product.images = ProductImage(
        main_image_path="https://images.example/aplus-a1-main.jpg",
        gallery_images=json_dumps(["https://images.example/aplus-a1-gallery.jpg"]),
        image_analysis=image_analysis if image_analysis is not None else json_dumps({"done": True}),
        analyzed_at=now,
    )
    product.catalog_item = CatalogProduct(
        gigab2b_url=product.gigab2b_url,
        gigab2b_product_id=product.gigab2b_product_id,
        amazon_asin=catalog_amazon_asin,
        item_code=f"{TEST_PREFIX}{marker}",
        title=f"A1 fixture {marker}",
        status=status,
        confirmed_at=confirmed_at,
        exported_at=now if catalog_exported else None,
        export_task_id=99101 if catalog_exported else None,
        export_file_path="/tmp/aplus-a1-export.xlsx" if catalog_exported else None,
        aplus_upload_status=catalog_aplus_upload_status,
        aplus_uploaded_at=now if aplus_uploaded else None,
    )
    if aplus_status is not None:
        product.aplus = ProductAplus(aplus_status=aplus_status)
    if template_file:
        product.files.append(
            ProductFile(
                file_type="amazon_import_template",
                label="Amazon import template",
                path="/tmp/aplus-a1-product-file-template.xlsm",
                created_at=now,
                updated_at=now,
            )
        )
    session.add(product)
    await session.flush()
    return product


async def _make_active_task(session, product_id: int, *, task_type: str, step_type: str, suffix: str) -> tuple[TaskRun, TaskStep]:
    now = datetime.now()
    run = TaskRun(
        task_type=task_type,
        title=f"A1 active {task_type}",
        status=RUN_STATUS_RUNNING,
        created_by="aplus-a1-test",
        correlation_key=f"product:{product_id}:{suffix}",
        payload_json=json_dumps({"product_id": product_id}),
        created_at=now,
        updated_at=now,
    )
    session.add(run)
    await session.flush()
    group = TaskGroup(
        task_run_id=run.id,
        group_key=suffix,
        title=suffix,
        status=RUN_STATUS_RUNNING,
        sort_order=1,
        progress_current=0,
        progress_total=1,
        created_at=now,
        updated_at=now,
    )
    session.add(group)
    await session.flush()
    step = TaskStep(
        task_run_id=run.id,
        task_group_id=group.id,
        step_key=f"product:{product_id}:{suffix}",
        step_type=step_type,
        status=STEP_STATUS_RUNNING,
        sort_order=1,
        payload_json=json_dumps({"product_id": product_id}),
        progress_current=0,
        progress_total=1,
        max_attempts=1,
        created_at=now,
        updated_at=now,
    )
    session.add(step)
    await session.flush()
    return run, step


async def _decision_code(session, product: Product, *, enabled: bool = True) -> str:
    before_runs = await session.scalar(select(func.count(TaskRun.id)).where(TaskRun.created_by == "aplus-a1-test"))
    before_status = await session.scalar(
        select(ProductAplus.aplus_status).where(ProductAplus.product_id == product.id)
    )
    decision = await should_auto_start_aplus(session, product, auto_enabled=enabled)
    after_status = await session.scalar(
        select(ProductAplus.aplus_status).where(ProductAplus.product_id == product.id)
    )
    after_runs = await session.scalar(select(func.count(TaskRun.id)).where(TaskRun.created_by == "aplus-a1-test"))
    assert before_status == after_status, (decision.code, before_status, after_status)
    assert before_runs == after_runs, (decision.code, before_runs, after_runs)
    return decision.code


async def _case(marker: str, expected: str, **overrides) -> None:
    async with async_session() as session:
        product = await _make_product(session, marker, **overrides)
        await session.commit()
        loaded = (
            await session.execute(
                select(Product)
                .where(Product.id == product.id)
                .options(selectinload(Product.aplus))
            )
        ).scalar_one()
        code = await _decision_code(session, loaded, enabled=True)
        assert code == expected, (marker, expected, code)


async def _run_a1() -> None:
    await run_schema_maintenance()
    await _cleanup_markers()
    try:
        await _case("ELIGIBLE", "eligible")
        async with async_session() as session:
            product = await _make_product(session, "DISABLED")
            await session.commit()
            code = await _decision_code(session, product, enabled=False)
            assert code == "disabled_by_config", code

        await _case("MISSING_CATALOG_CONFIRMED", "missing_catalog_export_ready", confirmed_at=None)
        await _case("MISSING_LISTING_TITLE", "missing_listing_content", listing_title="")
        await _case("MISSING_LISTING_BULLETS", "missing_listing_content", listing_bullets="[]")
        await _case("MISSING_IMAGE_ANALYSIS", "missing_image_analysis", image_analysis="")
        await _case("NOT_COMPLETED", "not_completed", status="created")
        await _case("NOT_FLOW_DONE", "not_flow_done", workflow_node=WORKFLOW_NODE_LISTING_GENERATION, workflow_status=WORKFLOW_STATUS_PENDING)

        async with async_session() as session:
            product = await _make_product(session, "ACTIVE_MAIN_TASK")
            await _make_active_task(session, product.id, task_type="product_listing_generation", step_type="product_listing_generation", suffix="listing_generation")
            await session.commit()
            code = await _decision_code(session, product, enabled=True)
            assert code == "main_workflow_active", code

        async with async_session() as session:
            product = await _make_product(session, "ACTIVE_APLUS_TASK")
            await _make_active_task(session, product.id, task_type="aplus_generate", step_type="aplus_generate_product", suffix="aplus_generate")
            await session.commit()
            code = await _decision_code(session, product, enabled=True)
            assert code == "active_aplus_task", code

        await _case("APLUS_DONE", "aplus_done", aplus_status="done")
        await _case("APLUS_REGEN_DONE", "aplus_done", aplus_status="regen_done")
        for status in ("queued", "planning", "scripting", "imaging"):
            await _case(f"APLUS_{status.upper()}", "active_aplus_task", aplus_status=status)
        for status in ("failed", "partial"):
            await _case(f"APLUS_RETRY_{status.upper()}", "eligible", aplus_status=status)

        await _case("UPLOAD_PROTECTED", "aplus_upload_protected", product_aplus_upload_status="uploading")
        await _case("UPLOADED_AT_PROTECTED", "aplus_upload_protected", aplus_uploaded=True)
        await _case("REAL_ASIN_PROTECTED", "real_asin_protected", product_amazon_asin="B0REALASIN1")
        await _case("CATALOG_REAL_ASIN_PROTECTED", "real_asin_protected", catalog_amazon_asin="B0REALASIN2")
        await _case("EXPORT_HISTORY_PROTECTED", "export_history_protected", catalog_exported=True)
        await _case("TEMPLATE_OUTPUT_PROTECTED", "template_output_protected", template_output=True)
        await _case("TEMPLATE_FILE_PROTECTED", "template_output_protected", template_file=True)
    finally:
        await _cleanup_markers()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", default="a1", choices=("a1",))
    args = parser.parse_args()
    if args.stage == "a1":
        asyncio.run(_run_a1())
        print("A+ auto trigger A1 policy behavior checks passed")
        return 0
    raise AssertionError(f"Unsupported stage: {args.stage}")


if __name__ == "__main__":
    raise SystemExit(main())
