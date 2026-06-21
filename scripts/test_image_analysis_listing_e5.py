from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
import sys

from sqlalchemy import delete, select
from sqlalchemy.orm import selectinload

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.database import async_session, run_schema_maintenance  # noqa: E402
from app.models import CatalogProduct, Product, ProductAplus, ProductData, ProductFile, ProductImage, TaskGroup, TaskRun, TaskStep, TaskStepEvent  # noqa: E402
from app.models.status import (  # noqa: E402
    COMPLETED,
    FAILED,
    PAUSED,
    STEP5_LISTING,
    WORKFLOW_NODE_FLOW_DONE,
    WORKFLOW_NODE_IMAGE_ANALYSIS,
    WORKFLOW_NODE_LISTING_GENERATION,
    WORKFLOW_STATUS_FAILED,
    WORKFLOW_STATUS_PROCESSING,
    WORKFLOW_STATUS_SUCCEEDED,
)
from app.product_tasks import actions as product_actions  # noqa: E402
from app.task_runtime.constants import RUN_STATUS_PENDING, RUN_STATUS_RUNNING, STEP_STATUS_READY, STEP_STATUS_RUNNING  # noqa: E402
from app.task_runtime.json_utils import json_dumps, json_loads  # noqa: E402


def _ensure_actions_registered() -> None:
    try:
        product_actions.register_product_task_actions()
    except Exception:
        pass
    product_actions.kick_task_runtime = lambda: None


async def _make_run(session, *, product_id: int, task_type: str, suffix: str, status: str = RUN_STATUS_RUNNING) -> tuple[TaskRun, TaskStep]:
    now = datetime.now()
    correlation_suffix = "image_analysis" if task_type == "product_image_analysis" else "listing_generation"
    run = TaskRun(
        task_type=task_type,
        title=f"E5 {task_type} {suffix}",
        status=status,
        payload_json=json_dumps({"product_id": product_id}),
        created_by="e5-test",
        correlation_key=f"product:{product_id}:{correlation_suffix}",
        created_at=now,
        updated_at=now,
    )
    session.add(run)
    await session.flush()
    group = TaskGroup(
        task_run_id=run.id,
        group_key=suffix,
        title=suffix,
        status=status,
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
        step_key=f"product:{product_id}:{correlation_suffix}",
        step_type=task_type,
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


async def _make_product(
    session,
    marker: str,
    *,
    workflow_node: str = WORKFLOW_NODE_IMAGE_ANALYSIS,
    workflow_status: str = WORKFLOW_STATUS_PROCESSING,
    status: str = "step6_curating",
    current_step: int = 5,
    image_analysis: bool = True,
    confirmed_at: datetime | None = None,
    amazon_asin: str | None = None,
    catalog_amazon_asin: str | None = None,
    catalog_exported: bool = False,
    template_output: bool = False,
    template_file: bool = False,
    aplus_uploaded: bool = False,
) -> Product:
    now = datetime.now()
    product = Product(
        gigab2b_url=f"https://e5.example/{marker}",
        gigab2b_product_id=marker,
        competitor_asin="B0E5COMPET",
        amazon_asin=amazon_asin,
        aplus_upload_status="uploaded" if aplus_uploaded else "not_uploaded",
        aplus_uploaded_at=now if aplus_uploaded else None,
        status=status,
        current_step=current_step,
        workflow_node=workflow_node,
        workflow_status=workflow_status,
        created_at=now,
        updated_at=now,
    )
    product.data = ProductData(
        item_code=marker,
        title="E5 modular sofa",
        leaf_category="Home & Kitchen > Furniture > Sofas",
        listing_title="Existing listing title",
        amazon_template_path="/tmp/e5-template.xlsm" if template_output else None,
        amazon_template_generated_at=now if template_output else None,
    )
    product.images = ProductImage(
        main_image_path="https://images.example/e5-source.jpg",
        gallery_images=json_dumps(["https://images.example/e5-gallery.jpg"]),
        image_analysis=json_dumps({"selling_points": ["modular"], "fixture": True}) if image_analysis else None,
        analyzed_at=now if image_analysis else None,
    )
    product.catalog_item = CatalogProduct(
        gigab2b_url=product.gigab2b_url,
        gigab2b_product_id=marker,
        item_code=marker,
        title="E5 modular sofa",
        status=status,
        competitor_asin=product.competitor_asin,
        amazon_asin=catalog_amazon_asin,
        confirmed_at=confirmed_at,
        exported_at=now if catalog_exported else None,
        export_task_id=8801 if catalog_exported else None,
        export_file_path="/tmp/e5-export.xlsx" if catalog_exported else None,
        aplus_upload_status="uploaded" if aplus_uploaded else "not_uploaded",
        aplus_uploaded_at=now if aplus_uploaded else None,
    )
    product.aplus = ProductAplus(
        aplus_status="uploaded" if aplus_uploaded else None,
        aplus_plan=json_dumps({"fixture": True}) if aplus_uploaded else None,
    )
    if template_file:
        product.files.append(
            ProductFile(
                file_type="amazon_import_template",
                label="E5 template",
                path="/tmp/e5-template-file.xlsm",
                created_at=now,
                updated_at=now,
            )
        )
    session.add(product)
    await session.flush()
    return product


async def _delete_runs(session, run_ids: list[int]) -> None:
    if not run_ids:
        return
    await session.execute(delete(TaskStepEvent).where(TaskStepEvent.task_run_id.in_(run_ids)))
    await session.execute(delete(TaskStep).where(TaskStep.task_run_id.in_(run_ids)))
    await session.execute(delete(TaskGroup).where(TaskGroup.task_run_id.in_(run_ids)))
    await session.execute(delete(TaskRun).where(TaskRun.id.in_(run_ids)))


async def _cleanup(product_ids: list[int], run_ids: list[int]) -> None:
    async with async_session() as session:
        if product_ids:
            await session.execute(delete(ProductFile).where(ProductFile.product_id.in_(product_ids)))
            await session.execute(delete(ProductAplus).where(ProductAplus.product_id.in_(product_ids)))
            await session.execute(delete(ProductImage).where(ProductImage.product_id.in_(product_ids)))
            await session.execute(delete(CatalogProduct).where(CatalogProduct.source_product_id.in_(product_ids)))
            await session.execute(delete(ProductData).where(ProductData.product_id.in_(product_ids)))
            await session.execute(delete(Product).where(Product.id.in_(product_ids)))
        await _delete_runs(session, run_ids)
        await session.commit()


async def _cleanup_e5_markers() -> None:
    product_ids: list[int]
    run_ids: list[int]
    async with async_session() as session:
        product_ids = [
            item
            for item in (
                await session.execute(select(Product.id).where(Product.gigab2b_product_id.like("E5_TEST_%")))
            ).scalars().all()
        ]
        run_ids = [
            item
            for item in (
                await session.execute(select(TaskRun.id).where(TaskRun.created_by == "e5-test"))
            ).scalars().all()
        ]
    await _cleanup(product_ids, run_ids)


async def _get_product(session, product_id: int) -> Product:
    return (
        await session.execute(
            select(Product)
            .where(Product.id == product_id)
            .options(selectinload(Product.data), selectinload(Product.images), selectinload(Product.catalog_item))
        )
    ).scalar_one()


async def _listing_runs(session, product_id: int) -> list[TaskRun]:
    return (
        await session.execute(
            select(TaskRun)
            .where(TaskRun.task_type == "product_listing_generation")
            .where(TaskRun.correlation_key == f"product:{product_id}:listing_generation")
            .options(selectinload(TaskRun.steps))
            .order_by(TaskRun.id.asc())
        )
    ).scalars().all()


async def _test_image_success_creates_listing_processing() -> tuple[int, list[int]]:
    async with async_session() as session:
        product = await _make_product(session, "E5_TEST_IMAGE_SUCCESS")
        image_run, image_step = await _make_run(session, product_id=product.id, task_type="product_image_analysis", suffix="image_success")
        await session.commit()

        result = {"product_id": product.id, "item_code": "E5_TEST_IMAGE_SUCCESS", "image_analysis": {"fixture": True}}
        await product_actions.ProductImageAnalysisAction().on_step_success(session, image_step, result)

        refreshed = await _get_product(session, product.id)
        listing_runs = await _listing_runs(session, product.id)
        assert refreshed.status == STEP5_LISTING, refreshed.status
        assert refreshed.workflow_node == WORKFLOW_NODE_LISTING_GENERATION, refreshed.workflow_node
        assert refreshed.workflow_status == WORKFLOW_STATUS_PROCESSING, refreshed.workflow_status
        assert len(listing_runs) == 1, [run.id for run in listing_runs]
        assert listing_runs[0].status in {RUN_STATUS_PENDING, RUN_STATUS_RUNNING}, listing_runs[0].status
        assert listing_runs[0].steps and listing_runs[0].steps[0].status in {STEP_STATUS_READY, STEP_STATUS_RUNNING}, [step.status for step in listing_runs[0].steps]
        assert result["status"] == "done", result
        assert result["listing_task_run_ids"] == [listing_runs[0].id], result
        return product.id, [image_run.id, listing_runs[0].id]


async def _test_repeated_image_success_reuses_active_listing() -> tuple[int, list[int]]:
    async with async_session() as session:
        product = await _make_product(session, "E5_TEST_IMAGE_REUSE")
        first_run, first_step = await _make_run(session, product_id=product.id, task_type="product_image_analysis", suffix="image_reuse_first")
        second_run, second_step = await _make_run(session, product_id=product.id, task_type="product_image_analysis", suffix="image_reuse_second")
        await session.commit()

        action = product_actions.ProductImageAnalysisAction()
        first_result = {"product_id": product.id, "item_code": "E5_TEST_IMAGE_REUSE"}
        await action.on_step_success(session, first_step, first_result)
        first_listing_id = first_result["listing_task_run_ids"][0]
        second_result = {"product_id": product.id, "item_code": "E5_TEST_IMAGE_REUSE"}
        await action.on_step_success(session, second_step, second_result)

        listing_runs = await _listing_runs(session, product.id)
        assert len(listing_runs) == 1, [run.id for run in listing_runs]
        assert second_result["listing_task_run_ids"] == [first_listing_id], second_result
        return product.id, [first_run.id, second_run.id, first_listing_id]


async def _test_image_success_completed_product_noops() -> tuple[int, list[int]]:
    async with async_session() as session:
        confirmed_at = datetime.now()
        product = await _make_product(
            session,
            "E5_TEST_IMAGE_COMPLETED_NOOP",
            workflow_node=WORKFLOW_NODE_FLOW_DONE,
            workflow_status=WORKFLOW_STATUS_SUCCEEDED,
            status=COMPLETED,
            current_step=6,
            confirmed_at=confirmed_at,
        )
        image_run, image_step = await _make_run(session, product_id=product.id, task_type="product_image_analysis", suffix="image_completed_noop")
        await session.commit()

        result = {"product_id": product.id, "item_code": "E5_TEST_IMAGE_COMPLETED_NOOP"}
        await product_actions.ProductImageAnalysisAction().on_step_success(session, image_step, result)

        refreshed = await _get_product(session, product.id)
        listing_runs = await _listing_runs(session, product.id)
        assert refreshed.status == COMPLETED, refreshed.status
        assert refreshed.workflow_node == WORKFLOW_NODE_FLOW_DONE, refreshed.workflow_node
        assert refreshed.workflow_status == WORKFLOW_STATUS_SUCCEEDED, refreshed.workflow_status
        assert refreshed.catalog_item.confirmed_at == confirmed_at, refreshed.catalog_item.confirmed_at
        assert listing_runs == [], [run.id for run in listing_runs]
        assert result["status"] == "already_completed", result
        return product.id, [image_run.id]


async def _test_downstream_listing_creation_failure_is_visible() -> tuple[int, list[int]]:
    async with async_session() as session:
        product = await _make_product(session, "E5_TEST_LISTING_CREATE_FAIL")
        image_run, image_step = await _make_run(session, product_id=product.id, task_type="product_image_analysis", suffix="listing_create_fail")
        product_id = product.id
        image_run_id = image_run.id
        await session.commit()

        original_create = product_actions.create_product_action_runs

        async def _raise_for_listing(*args, **kwargs):
            if args and args[1] == "product_listing_generation":
                raise RuntimeError("forced listing planner failure")
            return await original_create(*args, **kwargs)

        product_actions.create_product_action_runs = _raise_for_listing
        try:
            result = {"product_id": product.id, "item_code": "E5_TEST_LISTING_CREATE_FAIL"}
            await product_actions.ProductImageAnalysisAction().on_step_success(session, image_step, result)
        finally:
            product_actions.create_product_action_runs = original_create

        refreshed = await _get_product(session, product_id)
        listing_runs = await _listing_runs(session, product_id)
        assert listing_runs == [], [run.id for run in listing_runs]
        assert refreshed.status == FAILED, refreshed.status
        assert refreshed.current_step == 6, refreshed.current_step
        assert refreshed.workflow_node == WORKFLOW_NODE_LISTING_GENERATION, refreshed.workflow_node
        assert refreshed.workflow_status == WORKFLOW_STATUS_FAILED, refreshed.workflow_status
        assert "forced listing planner failure" in (refreshed.workflow_error or refreshed.error_message or ""), refreshed.workflow_error
        assert result["status"] == "downstream_failed", result
        return product_id, [image_run_id]


async def _test_listing_success_reaches_export_ready() -> tuple[int, list[int]]:
    async with async_session() as session:
        product = await _make_product(
            session,
            "E5_TEST_LISTING_SUCCESS",
            workflow_node=WORKFLOW_NODE_LISTING_GENERATION,
            workflow_status=WORKFLOW_STATUS_PROCESSING,
            status=STEP5_LISTING,
            current_step=6,
        )
        listing_run, listing_step = await _make_run(session, product_id=product.id, task_type="product_listing_generation", suffix="listing_success")
        await session.commit()

        result = {"product_id": product.id, "item_code": "E5_TEST_LISTING_SUCCESS", "listing": {"fixture": True}}
        await product_actions.ProductListingGenerationAction().on_step_success(session, listing_step, result)

        refreshed = await _get_product(session, product.id)
        assert refreshed.status == COMPLETED, refreshed.status
        assert refreshed.current_step == 6, refreshed.current_step
        assert refreshed.workflow_node == WORKFLOW_NODE_FLOW_DONE, refreshed.workflow_node
        assert refreshed.workflow_status == WORKFLOW_STATUS_SUCCEEDED, refreshed.workflow_status
        assert refreshed.catalog_item.confirmed_at is not None, refreshed.catalog_item.confirmed_at
        assert result["status"] == "done", result
        assert result["next_step"] == "export", result
        return product.id, [listing_run.id]


async def _test_listing_failure_cancel_interrupted_do_not_complete() -> tuple[list[int], list[int]]:
    product_ids: list[int] = []
    run_ids: list[int] = []
    async with async_session() as session:
        action = product_actions.ProductListingGenerationAction()
        for marker, mode in (
            ("E5_TEST_LISTING_FAILURE", "failure"),
            ("E5_TEST_LISTING_INTERRUPTED", "interrupted"),
            ("E5_TEST_LISTING_CANCEL", "cancel"),
        ):
            product = await _make_product(
                session,
                marker,
                workflow_node=WORKFLOW_NODE_LISTING_GENERATION,
                workflow_status=WORKFLOW_STATUS_PROCESSING,
                status=STEP5_LISTING,
                current_step=6,
            )
            listing_run, listing_step = await _make_run(session, product_id=product.id, task_type="product_listing_generation", suffix=mode)
            await session.commit()
            if mode == "failure":
                await action.on_step_failure(session, listing_step, RuntimeError("listing boom"))
            elif mode == "interrupted":
                await action.on_step_interrupted(session, listing_step, "heartbeat expired")
            else:
                await action.on_cancel_requested(session, listing_run, "user cancel")
            refreshed = await _get_product(session, product.id)
            assert refreshed.status in {FAILED, PAUSED}, (mode, refreshed.status)
            assert refreshed.status != COMPLETED, (mode, refreshed.status)
            assert refreshed.workflow_node == WORKFLOW_NODE_LISTING_GENERATION, (mode, refreshed.workflow_node)
            assert refreshed.workflow_status == WORKFLOW_STATUS_FAILED, (mode, refreshed.workflow_status)
            assert refreshed.catalog_item.confirmed_at is None, (mode, refreshed.catalog_item.confirmed_at)
            product_ids.append(product.id)
            run_ids.append(listing_run.id)
        return product_ids, run_ids


async def _assert_listing_creation_blocked(session, product_id: int, marker: str, expected_reason: str) -> None:
    try:
        await product_actions.create_product_action_runs(
            session,
            "product_listing_generation",
            [{"product_id": product_id}],
            created_by="e5-test",
            auto_start=False,
        )
    except RuntimeError as exc:
        assert expected_reason in str(exc), str(exc)
        await session.rollback()
    else:
        raise AssertionError(f"protected product {marker} unexpectedly queued listing")
    refreshed = await _get_product(session, product_id)
    assert refreshed.status != COMPLETED, refreshed.status


async def _test_listing_protection_blocks_irreversible_results() -> tuple[list[int], list[int]]:
    product_ids: list[int] = []
    async with async_session() as session:
        cases = [
            ("E5_TEST_PROTECT_PRODUCT_ASIN", {"amazon_asin": "B0REALASIN1"}, "真实 Amazon ASIN"),
            ("E5_TEST_PROTECT_CATALOG_ASIN", {"catalog_amazon_asin": "B0REALASIN2"}, "真实 Amazon ASIN"),
            ("E5_TEST_PROTECT_EXPORT", {"catalog_exported": True}, "导出历史"),
            ("E5_TEST_PROTECT_TEMPLATE", {"template_output": True}, "模板输出"),
            ("E5_TEST_PROTECT_TEMPLATE_FILE", {"template_file": True}, "模板文件"),
            ("E5_TEST_PROTECT_APLUS", {"aplus_uploaded": True}, "A+ 上传"),
            ("E5_TEST_PROTECT_CONFIRMED", {"confirmed_at": datetime.now()}, "人工确认"),
        ]
        for marker, kwargs, reason in cases:
            product = await _make_product(
                session,
                marker,
                workflow_node=WORKFLOW_NODE_LISTING_GENERATION,
                workflow_status=WORKFLOW_STATUS_FAILED,
                status=FAILED,
                current_step=6,
                **kwargs,
            )
            product_id = product.id
            await session.commit()
            await _assert_listing_creation_blocked(session, product_id, marker, reason)
            product_ids.append(product_id)
        return product_ids, []


async def main() -> None:
    await run_schema_maintenance()
    _ensure_actions_registered()
    await _cleanup_e5_markers()
    product_ids: list[int] = []
    run_ids: list[int] = []
    try:
        product_id, ids = await _test_image_success_creates_listing_processing()
        product_ids.append(product_id)
        run_ids.extend(ids)
        product_id, ids = await _test_repeated_image_success_reuses_active_listing()
        product_ids.append(product_id)
        run_ids.extend(ids)
        product_id, ids = await _test_image_success_completed_product_noops()
        product_ids.append(product_id)
        run_ids.extend(ids)
        product_id, ids = await _test_downstream_listing_creation_failure_is_visible()
        product_ids.append(product_id)
        run_ids.extend(ids)
        product_id, ids = await _test_listing_success_reaches_export_ready()
        product_ids.append(product_id)
        run_ids.extend(ids)
        ids, runs = await _test_listing_failure_cancel_interrupted_do_not_complete()
        product_ids.extend(ids)
        run_ids.extend(runs)
        ids, runs = await _test_listing_protection_blocks_irreversible_results()
        product_ids.extend(ids)
        run_ids.extend(runs)
        print("E5 image analysis -> listing -> export_ready behavior checks passed")
    finally:
        await _cleanup(product_ids, run_ids)


if __name__ == "__main__":
    asyncio.run(main())
