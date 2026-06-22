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
from app.models.status import COMPLETED, STEP5_LISTING, WORKFLOW_NODE_FLOW_DONE, WORKFLOW_NODE_LISTING_GENERATION, WORKFLOW_STATUS_PENDING, WORKFLOW_STATUS_PROCESSING, WORKFLOW_STATUS_SUCCEEDED  # noqa: E402
from app.product_tasks import actions as product_actions  # noqa: E402
from app.services import aplus_auto_trigger as aplus_service  # noqa: E402
from app.services.aplus_auto_trigger import should_auto_start_aplus, try_auto_start_aplus_after_export_ready  # noqa: E402
from app.task_planners import aplus_generate as aplus_planner  # noqa: E402
from app.task_runtime.constants import RUN_STATUS_RUNNING, STEP_STATUS_RUNNING  # noqa: E402
from app.task_runtime.json_utils import json_dumps, json_loads  # noqa: E402


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
                await session.execute(
                    select(TaskRun.id).where(TaskRun.created_by.in_(("aplus-a1-test", "auto_after_export_ready")))
                )
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


async def _aplus_steps_for_product(session, product_id: int) -> list[tuple[TaskRun, TaskStep]]:
    result = await session.execute(
        select(TaskRun, TaskStep)
        .join(TaskStep, TaskStep.task_run_id == TaskRun.id)
        .where(TaskStep.step_type == "aplus_generate_product")
        .order_by(TaskRun.id.asc(), TaskStep.id.asc())
    )
    rows: list[tuple[TaskRun, TaskStep]] = []
    for run, step in result.all():
        payload = json_loads(step.payload_json, {})
        if isinstance(payload, dict) and int(payload.get("product_id") or 0) == product_id:
            rows.append((run, step))
    return rows


async def _product_state(session, product_id: int) -> Product:
    return (
        await session.execute(
            select(Product)
            .where(Product.id == product_id)
            .options(selectinload(Product.aplus), selectinload(Product.catalog_item))
            .execution_options(populate_existing=True)
        )
    ).scalar_one()


async def _run_summary(session, task_run_id: int) -> dict:
    run = await session.get(TaskRun, task_run_id)
    assert run is not None, task_run_id
    return json_loads(run.summary_json, {})


def _set_auto_enabled(value: bool) -> bool:
    previous = bool(aplus_service.settings.AUTO_APLUS_AFTER_EXPORT_READY)
    aplus_service.settings.AUTO_APLUS_AFTER_EXPORT_READY = value
    return previous


async def _listing_success(
    session,
    product: Product,
    marker: str,
) -> tuple[TaskRun, TaskStep, dict]:
    listing_run, listing_step = await _make_active_task(
        session,
        product.id,
        task_type="product_listing_generation",
        step_type="product_listing_generation",
        suffix=f"listing_{marker.lower()}",
    )
    await session.commit()
    result = {"product_id": product.id, "item_code": f"{TEST_PREFIX}{marker}", "listing": {"fixture": True}}
    await product_actions.ProductListingGenerationAction().on_step_success(session, listing_step, result)
    return listing_run, listing_step, result


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


async def _test_listing_success_default_off_noops() -> None:
    previous = _set_auto_enabled(False)
    try:
        async with async_session() as session:
            product = await _make_product(
                session,
                "A2_DEFAULT_OFF",
                status=STEP5_LISTING,
                workflow_node=WORKFLOW_NODE_LISTING_GENERATION,
                workflow_status=WORKFLOW_STATUS_PROCESSING,
                confirmed_at=None,
            )
            listing_run, _listing_step, result = await _listing_success(session, product, "A2_DEFAULT_OFF")

            refreshed = await _product_state(session, product.id)
            summary = json_loads(listing_run.summary_json, {})
            aplus_rows = await _aplus_steps_for_product(session, product.id)
            assert refreshed.status == COMPLETED, refreshed.status
            assert refreshed.workflow_node == WORKFLOW_NODE_FLOW_DONE, refreshed.workflow_node
            assert refreshed.workflow_status == WORKFLOW_STATUS_SUCCEEDED, refreshed.workflow_status
            assert refreshed.catalog_item.confirmed_at is not None, refreshed.catalog_item.confirmed_at
            assert refreshed.aplus is None, refreshed.aplus
            assert aplus_rows == [], [(run.id, step.id) for run, step in aplus_rows]
            assert summary["status"] == "listing_done", summary
            assert summary["aplus_auto_trigger"]["code"] == "disabled_by_config", summary
            assert result["aplus_auto_trigger"]["code"] == "disabled_by_config", result
    finally:
        _set_auto_enabled(previous)


async def _test_listing_success_enabled_creates_aplus_task() -> tuple[int, int, int]:
    previous = _set_auto_enabled(True)
    old_kick = aplus_planner.kick_task_runtime
    aplus_planner.kick_task_runtime = lambda: None
    try:
        async with async_session() as session:
            product = await _make_product(
                session,
                "A2_ENABLED_QUEUE",
                status=STEP5_LISTING,
                workflow_node=WORKFLOW_NODE_LISTING_GENERATION,
                workflow_status=WORKFLOW_STATUS_PROCESSING,
                confirmed_at=None,
            )
            listing_run, _listing_step, result = await _listing_success(session, product, "A2_ENABLED_QUEUE")

            refreshed = await _product_state(session, product.id)
            summary = json_loads(listing_run.summary_json, {})
            aplus_rows = await _aplus_steps_for_product(session, product.id)
            assert refreshed.status == COMPLETED, refreshed.status
            assert refreshed.workflow_node == WORKFLOW_NODE_FLOW_DONE, refreshed.workflow_node
            assert refreshed.workflow_status == WORKFLOW_STATUS_SUCCEEDED, refreshed.workflow_status
            assert refreshed.catalog_item.confirmed_at is not None, refreshed.catalog_item.confirmed_at
            assert refreshed.aplus and refreshed.aplus.aplus_status == "queued", refreshed.aplus
            assert len(aplus_rows) == 1, [(run.id, step.id) for run, step in aplus_rows]
            aplus_run, aplus_step = aplus_rows[0]
            assert aplus_run.created_by == "auto_after_export_ready", aplus_run.created_by
            assert aplus_run.dedupe_key == f"aplus_generate:product:{product.id}", aplus_run.dedupe_key
            assert aplus_run.correlation_key == f"product:{product.id}:aplus_generate", aplus_run.correlation_key
            assert aplus_step.status in {"ready", "running", "pending"}, aplus_step.status
            assert summary["status"] == "listing_done", summary
            assert summary["aplus_auto_trigger"]["status"] == "queued", summary
            assert summary["aplus_auto_trigger"]["code"] == "queued", summary
            assert summary["aplus_auto_trigger"]["details"]["task_run_ids"] == [aplus_run.id], summary
            assert result["aplus_auto_trigger"]["status"] == "queued", result
            return product.id, aplus_run.id, listing_run.id
    finally:
        aplus_planner.kick_task_runtime = old_kick
        _set_auto_enabled(previous)


async def _test_try_helper_reuses_existing_active_aplus(product_id: int, existing_run_id: int, source_listing_run_id: int) -> None:
    previous = _set_auto_enabled(True)
    try:
        async with async_session() as session:
            before_rows = await _aplus_steps_for_product(session, product_id)
            result = await try_auto_start_aplus_after_export_ready(
                session,
                product_id,
                source_task_run_id=source_listing_run_id,
                created_by="aplus-a1-test",
            )
            after_rows = await _aplus_steps_for_product(session, product_id)
            assert result["status"] == "reused", result
            assert result["code"] == "active_aplus_task", result
            assert [run.id for run, _ in before_rows] == [run.id for run, _ in after_rows], result
            assert len(after_rows) == 1, [(run.id, step.id) for run, step in after_rows]
            assert after_rows[0][0].id == existing_run_id, after_rows[0][0].id
    finally:
        _set_auto_enabled(previous)


async def _test_listing_success_aplus_failure_does_not_rollback_export_ready() -> None:
    previous = _set_auto_enabled(True)
    original_create = aplus_service.create_aplus_generate_runs

    async def _raise_planner_failure(*args, **kwargs):
        raise RuntimeError("forced aplus planner failure")

    aplus_service.create_aplus_generate_runs = _raise_planner_failure
    try:
        async with async_session() as session:
            product = await _make_product(
                session,
                "A2_PLANNER_FAIL",
                status=STEP5_LISTING,
                workflow_node=WORKFLOW_NODE_LISTING_GENERATION,
                workflow_status=WORKFLOW_STATUS_PROCESSING,
                confirmed_at=None,
            )
            product_id = product.id
            listing_run, _listing_step, result = await _listing_success(session, product, "A2_PLANNER_FAIL")
            listing_run_id = listing_run.id

            refreshed = await _product_state(session, product_id)
            summary = await _run_summary(session, listing_run_id)
            aplus_rows = await _aplus_steps_for_product(session, product_id)
            assert refreshed.status == COMPLETED, refreshed.status
            assert refreshed.workflow_node == WORKFLOW_NODE_FLOW_DONE, refreshed.workflow_node
            assert refreshed.workflow_status == WORKFLOW_STATUS_SUCCEEDED, refreshed.workflow_status
            assert not refreshed.workflow_error, refreshed.workflow_error
            assert refreshed.catalog_item.confirmed_at is not None, refreshed.catalog_item.confirmed_at
            assert refreshed.aplus is None, refreshed.aplus
            assert aplus_rows == [], [(run.id, step.id) for run, step in aplus_rows]
            assert summary["aplus_auto_trigger"]["status"] == "failed", summary
            assert summary["aplus_auto_trigger"]["code"] == "trigger_failed", summary
            assert "forced aplus planner failure" in summary["aplus_auto_trigger"]["message"], summary
            assert result["aplus_auto_trigger"]["status"] == "failed", result
    finally:
        aplus_service.create_aplus_generate_runs = original_create
        _set_auto_enabled(previous)


async def _run_a2() -> None:
    await run_schema_maintenance()
    await _cleanup_markers()
    try:
        await _test_listing_success_default_off_noops()
        product_id, aplus_run_id, listing_run_id = await _test_listing_success_enabled_creates_aplus_task()
        await _test_try_helper_reuses_existing_active_aplus(product_id, aplus_run_id, listing_run_id)
        await _test_listing_success_aplus_failure_does_not_rollback_export_ready()
    finally:
        await _cleanup_markers()


async def _run_a1_then_a2() -> None:
    await _run_a1()
    await _run_a2()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", default="a1", choices=("a1", "a2"))
    args = parser.parse_args()
    if args.stage == "a1":
        asyncio.run(_run_a1())
        print("A+ auto trigger A1 policy behavior checks passed")
        return 0
    if args.stage == "a2":
        asyncio.run(_run_a1_then_a2())
        print("A+ auto trigger A1/A2 behavior checks passed")
        return 0
    raise AssertionError(f"Unsupported stage: {args.stage}")


if __name__ == "__main__":
    raise SystemExit(main())
