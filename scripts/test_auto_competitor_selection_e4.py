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
from app.models import (  # noqa: E402
    AmazonCompetitorSearchCandidate,
    CatalogProduct,
    Product,
    ProductData,
    ProductImage,
    TaskGroup,
    TaskRun,
    TaskStep,
    TaskStepEvent,
)
from app.models.status import (  # noqa: E402
    WORKFLOW_NODE_AUTO_SELECT_COMPETITOR,
    WORKFLOW_NODE_IMAGE_ANALYSIS,
    WORKFLOW_STATUS_FAILED,
    WORKFLOW_STATUS_PENDING,
    WORKFLOW_STATUS_PROCESSING,
)
from app.product_tasks import actions as product_actions  # noqa: E402
from app.task_runtime.constants import (  # noqa: E402
    RUN_STATUS_PENDING,
    RUN_STATUS_RUNNING,
    RUN_STATUS_SUCCEEDED,
    STEP_STATUS_READY,
    STEP_STATUS_RUNNING,
    STEP_STATUS_SUCCEEDED,
)
from app.task_runtime.json_utils import json_dumps, json_loads  # noqa: E402


def _ensure_actions_registered() -> None:
    try:
        product_actions.register_product_task_actions()
    except Exception:
        pass


async def _make_run(
    session,
    *,
    product_id: int,
    task_type: str,
    suffix: str,
    status: str,
) -> tuple[TaskRun, TaskStep]:
    now = datetime.now()
    run = TaskRun(
        task_type=task_type,
        title=f"E4 {task_type} {suffix}",
        status=status,
        payload_json=json_dumps({"product_id": product_id}),
        created_by="e4-test",
        correlation_key=f"product:{product_id}:{suffix}",
        created_at=now,
        updated_at=now,
    )
    if task_type == "product_competitor_visual_match":
        run.correlation_key = f"product:{product_id}:competitor_visual_match"
    elif task_type == "product_auto_competitor_selection":
        run.correlation_key = f"product:{product_id}:auto_competitor_selection"
    elif task_type == "product_image_analysis":
        run.correlation_key = f"product:{product_id}:image_analysis"
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
        step_key=f"product:{product_id}:{suffix}",
        step_type=task_type,
        status=STEP_STATUS_SUCCEEDED if status == RUN_STATUS_SUCCEEDED else STEP_STATUS_RUNNING,
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


async def _make_product(session, marker: str, *, protected: bool = False) -> Product:
    now = datetime.now()
    product = Product(
        gigab2b_url=f"https://e4.example/{marker}",
        gigab2b_product_id=marker,
        status="created",
        current_step=2,
        workflow_node=WORKFLOW_NODE_AUTO_SELECT_COMPETITOR,
        workflow_status=WORKFLOW_STATUS_PENDING,
        created_at=now,
        updated_at=now,
    )
    product.data = ProductData(
        item_code=marker,
        title="Modern modular sofa with chaise storage",
        material="linen wood",
        product_type="modular sofa",
        features=json_dumps(["modular couch", "storage chaise", "linen upholstery"]),
        description="A modular living room sofa with storage chaise.",
    )
    product.images = ProductImage(
        main_image_path="https://images.example/source-sofa.jpg",
        main_image_source="auto",
    )
    product.catalog_item = CatalogProduct(
        gigab2b_url=product.gigab2b_url,
        gigab2b_product_id=marker,
        item_code=marker,
        title="Modern modular sofa with chaise storage",
        status="created",
        confirmed_at=datetime.now() if protected else None,
    )
    session.add(product)
    await session.flush()
    return product


async def _make_candidate(
    session,
    *,
    product_id: int,
    asin: str,
    visual_run_id: int,
    visual_step_id: int,
    visual_rank: int,
    title: str,
    visual_similarity: float,
    visual_type: int = 1,
    capture_status: str = "succeeded",
    selected: int = 1,
    bullets: list[str] | None = None,
    leaf_category: str | None = "Home & Kitchen > Furniture > Living Room Furniture > Sofas",
    description: str = "Detailed Amazon listing copy for a matching modular sofa.",
    product_details: dict | None = None,
    search_rank: int | None = None,
    is_accessory: int = 0,
) -> AmazonCompetitorSearchCandidate:
    row = AmazonCompetitorSearchCandidate(
        product_id=product_id,
        task_run_id=visual_run_id,
        task_step_id=visual_step_id,
        search_query="modular sofa",
        search_rank=search_rank or visual_rank,
        asin=asin,
        url=f"https://www.amazon.com/dp/{asin}",
        title=title,
        image_url=f"https://images.example/{asin}.jpg",
        price="$299.99",
        rating=4.6,
        review_count=384,
        is_accessory=is_accessory,
        visual_task_run_id=visual_run_id,
        visual_task_step_id=visual_step_id,
        visual_rank=visual_rank,
        visual_similarity_score=visual_similarity,
        visual_same_product_type=visual_type,
        visual_attribute_match_score=visual_similarity,
        visual_title_match_score=visual_similarity,
        visual_selected_for_capture=selected,
        visual_matched_at=datetime.now(),
        detail_task_run_id=visual_run_id,
        detail_task_step_id=visual_step_id,
        detail_captured_at=datetime.now(),
        brand="E4 Home",
        seller="E4 Seller",
        category_rank="#42 in Sofas",
        leaf_category=leaf_category,
        main_image_url=f"https://images.example/{asin}-main.jpg",
        bullets_json=json_dumps(bullets or ["Modular sofa with chaise", "Linen upholstery", "Storage seating"]),
        description=description,
        product_details_json=json_dumps(product_details or {"material": "linen", "room": "living room"}),
        aplus_text="Lifestyle detail text",
        capture_status=capture_status,
        capture_raw_json=json_dumps({"fixture": True}),
    )
    session.add(row)
    await session.flush()
    return row


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
            await session.execute(delete(AmazonCompetitorSearchCandidate).where(AmazonCompetitorSearchCandidate.product_id.in_(product_ids)))
            await session.execute(delete(ProductImage).where(ProductImage.product_id.in_(product_ids)))
            await session.execute(delete(CatalogProduct).where(CatalogProduct.source_product_id.in_(product_ids)))
            await session.execute(delete(ProductData).where(ProductData.product_id.in_(product_ids)))
            await session.execute(delete(Product).where(Product.id.in_(product_ids)))
        await _delete_runs(session, run_ids)
        await session.commit()


async def _get_product(session, product_id: int) -> Product:
    return (
        await session.execute(
            select(Product)
            .where(Product.id == product_id)
            .options(
                selectinload(Product.data),
                selectinload(Product.catalog_item),
                selectinload(Product.images),
            )
        )
    ).scalar_one()


async def _run_auto_selection(session, product: Product, run: TaskRun, step: TaskStep) -> dict:
    action = product_actions.ProductAutoCompetitorSelectionAction()
    await action.validate(session, {"product_id": product.id})
    await action.reserve(session, {"product_id": product.id}, run)
    result = await action.execute_step(session, step, {"product_id": product.id})
    await action.on_step_success(session, step, result)
    return result


async def _test_high_success_final_facts_and_image_task() -> tuple[int, list[int]]:
    async with async_session() as session:
        product = await _make_product(session, "E4_TEST_HIGH")
        visual_run, visual_step = await _make_run(
            session,
            product_id=product.id,
            task_type="product_competitor_visual_match",
            suffix="current_visual_high",
            status=RUN_STATUS_SUCCEEDED,
        )
        auto_run, auto_step = await _make_run(
            session,
            product_id=product.id,
            task_type="product_auto_competitor_selection",
            suffix="auto_select_high",
            status=RUN_STATUS_RUNNING,
        )
        selected = await _make_candidate(
            session,
            product_id=product.id,
            asin="B0E4HIGH001",
            visual_run_id=visual_run.id,
            visual_step_id=visual_step.id,
            visual_rank=1,
            title="Modern modular sofa couch with storage chaise",
            visual_similarity=0.96,
        )
        await _make_candidate(
            session,
            product_id=product.id,
            asin="B0E4HIGH002",
            visual_run_id=visual_run.id,
            visual_step_id=visual_step.id,
            visual_rank=2,
            title="Linen modular sectional sofa for living room",
            visual_similarity=0.86,
        )
        await session.commit()

        result = await _run_auto_selection(session, product, auto_run, auto_step)

        refreshed = await _get_product(session, product.id)
        row = (await session.execute(select(AmazonCompetitorSearchCandidate).where(AmazonCompetitorSearchCandidate.id == selected.id))).scalar_one()
        image_runs = (
            await session.execute(
                select(TaskRun)
                .where(TaskRun.task_type == "product_image_analysis")
                .where(TaskRun.correlation_key == f"product:{product.id}:image_analysis")
            )
        ).scalars().all()
        snapshot = json_loads(refreshed.data.gigab2b_raw_snapshot, {})
        assert result["selected_candidate_id"] == selected.id, result
        assert row.final_selected == 1, row.final_selected
        assert row.final_confidence == "high", row.final_confidence
        assert row.final_score is not None and row.final_score >= 0.78, row.final_score
        assert refreshed.competitor_asin == "B0E4HIGH001", refreshed.competitor_asin
        assert refreshed.catalog_item.competitor_asin == "B0E4HIGH001", refreshed.catalog_item.competitor_asin
        assert snapshot["selected_competitor"]["asin"] == "B0E4HIGH001", snapshot
        assert refreshed.workflow_node == WORKFLOW_NODE_IMAGE_ANALYSIS, refreshed.workflow_node
        assert refreshed.workflow_status == WORKFLOW_STATUS_PROCESSING, refreshed.workflow_status
        assert len(image_runs) == 1, [run.id for run in image_runs]
        return product.id, [visual_run.id, auto_run.id, image_runs[0].id]


async def _test_medium_success_writes_risks() -> tuple[int, list[int]]:
    async with async_session() as session:
        product = await _make_product(session, "E4_TEST_MEDIUM")
        visual_run, visual_step = await _make_run(session, product_id=product.id, task_type="product_competitor_visual_match", suffix="current_visual_medium", status=RUN_STATUS_SUCCEEDED)
        auto_run, auto_step = await _make_run(session, product_id=product.id, task_type="product_auto_competitor_selection", suffix="auto_select_medium", status=RUN_STATUS_RUNNING)
        selected = await _make_candidate(
            session,
            product_id=product.id,
            asin="B0E4MEDIUM1",
            visual_run_id=visual_run.id,
            visual_step_id=visual_step.id,
            visual_rank=1,
            title="Modular sofa for living room",
            visual_similarity=0.72,
            bullets=["Modular sofa", "Living room seating"],
            leaf_category="Furniture > Sofas",
        )
        await session.commit()

        await _run_auto_selection(session, product, auto_run, auto_step)

        row = (await session.execute(select(AmazonCompetitorSearchCandidate).where(AmazonCompetitorSearchCandidate.id == selected.id))).scalar_one()
        risks = json_loads(row.final_risks_json, [])
        assert row.final_confidence == "medium", row.final_confidence
        assert row.final_score is not None and 0.68 <= row.final_score < 0.78, row.final_score
        assert row.final_reason and "medium" in row.final_reason, row.final_reason
        assert risks, risks
        image_run_ids = [
            run.id
            for run in (
                await session.execute(select(TaskRun).where(TaskRun.task_type == "product_image_analysis").where(TaskRun.correlation_key == f"product:{product.id}:image_analysis"))
            ).scalars().all()
        ]
        return product.id, [visual_run.id, auto_run.id, *image_run_ids]


async def _test_low_and_insufficient_fail_without_final_write() -> tuple[list[int], list[int]]:
    product_ids: list[int] = []
    run_ids: list[int] = []
    async with async_session() as session:
        action = product_actions.ProductAutoCompetitorSelectionAction()
        for marker, candidate_kwargs in (
            ("E4_TEST_LOW", {"asin": "B0E4LOW0001", "title": "Tiny sofa replacement cover accessory", "visual_similarity": 0.31, "is_accessory": 1}),
            ("E4_TEST_INSUFFICIENT", {"asin": "", "title": "", "visual_similarity": 0.91, "bullets": []}),
        ):
            product = await _make_product(session, marker)
            visual_run, visual_step = await _make_run(session, product_id=product.id, task_type="product_competitor_visual_match", suffix=f"{marker}_visual", status=RUN_STATUS_SUCCEEDED)
            auto_run, auto_step = await _make_run(session, product_id=product.id, task_type="product_auto_competitor_selection", suffix=f"{marker}_auto", status=RUN_STATUS_RUNNING)
            await _make_candidate(
                session,
                product_id=product.id,
                visual_run_id=visual_run.id,
                visual_step_id=visual_step.id,
                visual_rank=1,
                **candidate_kwargs,
            )
            await session.commit()
            try:
                await action.reserve(session, {"product_id": product.id}, auto_run)
                await action.execute_step(session, auto_step, {"product_id": product.id})
            except RuntimeError as exc:
                await action.on_step_failure(session, auto_step, exc)
            else:
                raise AssertionError(f"{marker} must fail")
            refreshed = await _get_product(session, product.id)
            rows = (
                await session.execute(select(AmazonCompetitorSearchCandidate).where(AmazonCompetitorSearchCandidate.product_id == product.id))
            ).scalars().all()
            assert refreshed.workflow_node == WORKFLOW_NODE_AUTO_SELECT_COMPETITOR, refreshed.workflow_node
            assert refreshed.workflow_status == WORKFLOW_STATUS_FAILED, refreshed.workflow_status
            assert refreshed.competitor_asin is None, refreshed.competitor_asin
            assert all(row.final_selected == 0 for row in rows), [row.final_selected for row in rows]
            product_ids.append(product.id)
            run_ids.extend([visual_run.id, auto_run.id])
    return product_ids, run_ids


async def _test_different_product_type_rejected_without_final_write() -> tuple[int, list[int]]:
    async with async_session() as session:
        product = await _make_product(session, "E4_TEST_TYPE_MISMATCH")
        visual_run, visual_step = await _make_run(
            session,
            product_id=product.id,
            task_type="product_competitor_visual_match",
            suffix="type_mismatch_visual",
            status=RUN_STATUS_SUCCEEDED,
        )
        auto_run, auto_step = await _make_run(
            session,
            product_id=product.id,
            task_type="product_auto_competitor_selection",
            suffix="type_mismatch_auto",
            status=RUN_STATUS_RUNNING,
        )
        await _make_candidate(
            session,
            product_id=product.id,
            asin="B0E4CHAIR01",
            visual_run_id=visual_run.id,
            visual_step_id=visual_step.id,
            visual_rank=1,
            title="Ergonomic office chair with adjustable arms",
            visual_similarity=0.99,
            bullets=["Office chair for desk work", "Adjustable seat and arms", "Mesh back support"],
            leaf_category="Office Products > Furniture > Office Chairs",
            description="Detailed office chair listing copy.",
            product_details={"material": "mesh", "room": "office"},
        )
        await session.commit()

        action = product_actions.ProductAutoCompetitorSelectionAction()
        try:
            await action.reserve(session, {"product_id": product.id}, auto_run)
            await action.execute_step(session, auto_step, {"product_id": product.id})
        except RuntimeError as exc:
            await action.on_step_failure(session, auto_step, exc)
        else:
            raise AssertionError("different product type must not be auto-selected")

        refreshed = await _get_product(session, product.id)
        rows = (
            await session.execute(select(AmazonCompetitorSearchCandidate).where(AmazonCompetitorSearchCandidate.product_id == product.id))
        ).scalars().all()
        snapshot = json_loads(refreshed.data.gigab2b_raw_snapshot, {})
        assert refreshed.workflow_node == WORKFLOW_NODE_AUTO_SELECT_COMPETITOR, refreshed.workflow_node
        assert refreshed.workflow_status == WORKFLOW_STATUS_FAILED, refreshed.workflow_status
        assert refreshed.competitor_asin is None, refreshed.competitor_asin
        assert refreshed.catalog_item.competitor_asin is None, refreshed.catalog_item.competitor_asin
        assert "selected_competitor" not in snapshot, snapshot
        assert all(row.final_selected == 0 for row in rows), [row.final_selected for row in rows]
        return product.id, [visual_run.id, auto_run.id]


async def _test_protection_blocks_before_overwrite() -> tuple[int, list[int]]:
    async with async_session() as session:
        product = await _make_product(session, "E4_TEST_PROTECTED", protected=True)
        product.competitor_asin = "B0KEEPOLD00"
        visual_run, visual_step = await _make_run(session, product_id=product.id, task_type="product_competitor_visual_match", suffix="protected_visual", status=RUN_STATUS_SUCCEEDED)
        await _make_candidate(
            session,
            product_id=product.id,
            asin="B0E4PROTECT",
            visual_run_id=visual_run.id,
            visual_step_id=visual_step.id,
            visual_rank=1,
            title="Modern modular sofa couch",
            visual_similarity=0.97,
        )
        await session.commit()

        action = product_actions.ProductAutoCompetitorSelectionAction()
        try:
            await action.validate(session, {"product_id": product.id})
        except RuntimeError as exc:
            assert "不可逆外部结果" in str(exc), str(exc)
        else:
            raise AssertionError("protected product must be blocked")

        refreshed = await _get_product(session, product.id)
        assert refreshed.competitor_asin == "B0KEEPOLD00", refreshed.competitor_asin
        return product.id, [visual_run.id]


async def _test_old_visual_run_excluded() -> tuple[int, list[int]]:
    async with async_session() as session:
        product = await _make_product(session, "E4_TEST_OLD_RUN")
        old_visual_run, old_visual_step = await _make_run(session, product_id=product.id, task_type="product_competitor_visual_match", suffix="old_visual", status=RUN_STATUS_SUCCEEDED)
        current_visual_run, current_visual_step = await _make_run(session, product_id=product.id, task_type="product_competitor_visual_match", suffix="current_visual", status=RUN_STATUS_SUCCEEDED)
        auto_run, auto_step = await _make_run(session, product_id=product.id, task_type="product_auto_competitor_selection", suffix="auto_old_excluded", status=RUN_STATUS_RUNNING)
        old_row = await _make_candidate(session, product_id=product.id, asin="B0E4OLDGOOD", visual_run_id=old_visual_run.id, visual_step_id=old_visual_step.id, visual_rank=1, title="Perfect old modular sofa", visual_similarity=0.99)
        current_row = await _make_candidate(session, product_id=product.id, asin="B0E4CURRENT", visual_run_id=current_visual_run.id, visual_step_id=current_visual_step.id, visual_rank=1, title="Current modular sofa", visual_similarity=0.82)
        await session.commit()

        result = await _run_auto_selection(session, product, auto_run, auto_step)

        rows = {
            row.id: row
            for row in (
                await session.execute(select(AmazonCompetitorSearchCandidate).where(AmazonCompetitorSearchCandidate.product_id == product.id))
            ).scalars().all()
        }
        assert result["selected_candidate_id"] == current_row.id, result
        assert rows[current_row.id].final_selected == 1, rows[current_row.id].final_selected
        assert rows[old_row.id].final_selected == 0, rows[old_row.id].final_selected
        image_run_ids = [
            run.id
            for run in (
                await session.execute(select(TaskRun).where(TaskRun.task_type == "product_image_analysis").where(TaskRun.correlation_key == f"product:{product.id}:image_analysis"))
            ).scalars().all()
        ]
        return product.id, [old_visual_run.id, current_visual_run.id, auto_run.id, *image_run_ids]


async def _test_active_run_reuse() -> tuple[int, list[int]]:
    async with async_session() as session:
        product = await _make_product(session, "E4_TEST_REUSE")
        visual_run, visual_step = await _make_run(session, product_id=product.id, task_type="product_competitor_visual_match", suffix="reuse_visual", status=RUN_STATUS_SUCCEEDED)
        await _make_candidate(session, product_id=product.id, asin="B0E4REUSE01", visual_run_id=visual_run.id, visual_step_id=visual_step.id, visual_rank=1, title="Reusable modular sofa", visual_similarity=0.93)
        await session.commit()

        first = await product_actions.create_product_action_runs(
            session,
            "product_auto_competitor_selection",
            [{"product_id": product.id}],
            created_by="e4-test",
            auto_start=False,
        )
        second = await product_actions.create_product_action_runs(
            session,
            "product_auto_competitor_selection",
            [{"product_id": product.id}],
            created_by="e4-test",
            auto_start=False,
        )
        assert len(first) == 1 and len(second) == 1, (first, second)
        assert first[0].id == second[0].id, (first[0].id, second[0].id)
        return product.id, [visual_run.id, first[0].id]


async def _test_downstream_image_creation_failure_preserves_final_facts() -> tuple[int, list[int]]:
    async with async_session() as session:
        product = await _make_product(session, "E4_TEST_DOWNSTREAM_FAIL")
        visual_run, visual_step = await _make_run(session, product_id=product.id, task_type="product_competitor_visual_match", suffix="downstream_visual", status=RUN_STATUS_SUCCEEDED)
        auto_run, auto_step = await _make_run(session, product_id=product.id, task_type="product_auto_competitor_selection", suffix="downstream_auto", status=RUN_STATUS_RUNNING)
        selected = await _make_candidate(session, product_id=product.id, asin="B0E4DOWNFL", visual_run_id=visual_run.id, visual_step_id=visual_step.id, visual_rank=1, title="Downstream modular sofa", visual_similarity=0.94)
        await session.commit()

        action = product_actions.ProductAutoCompetitorSelectionAction()
        await action.reserve(session, {"product_id": product.id}, auto_run)
        result = await action.execute_step(session, auto_step, {"product_id": product.id})
        original_create = product_actions.create_product_action_runs

        async def _raise_for_image(*args, **kwargs):
            if args and args[1] == "product_image_analysis":
                raise RuntimeError("forced image analysis planner failure")
            return await original_create(*args, **kwargs)

        product_actions.create_product_action_runs = _raise_for_image
        try:
            await action.on_step_success(session, auto_step, result)
        finally:
            product_actions.create_product_action_runs = original_create

        refreshed = await _get_product(session, product.id)
        row = (await session.execute(select(AmazonCompetitorSearchCandidate).where(AmazonCompetitorSearchCandidate.id == selected.id))).scalar_one()
        assert row.final_selected == 1, row.final_selected
        assert refreshed.competitor_asin == "B0E4DOWNFL", refreshed.competitor_asin
        assert refreshed.workflow_node == WORKFLOW_NODE_IMAGE_ANALYSIS, refreshed.workflow_node
        assert refreshed.workflow_status == WORKFLOW_STATUS_FAILED, refreshed.workflow_status
        assert "forced image analysis" in (refreshed.workflow_error or refreshed.error_message or ""), refreshed.workflow_error
        return product.id, [visual_run.id, auto_run.id]


async def main() -> None:
    await run_schema_maintenance()
    _ensure_actions_registered()
    product_ids: list[int] = []
    run_ids: list[int] = []
    try:
        product_id, ids = await _test_high_success_final_facts_and_image_task()
        product_ids.append(product_id)
        run_ids.extend(ids)
        product_id, ids = await _test_medium_success_writes_risks()
        product_ids.append(product_id)
        run_ids.extend(ids)
        ids_product, ids_run = await _test_low_and_insufficient_fail_without_final_write()
        product_ids.extend(ids_product)
        run_ids.extend(ids_run)
        product_id, ids = await _test_different_product_type_rejected_without_final_write()
        product_ids.append(product_id)
        run_ids.extend(ids)
        product_id, ids = await _test_protection_blocks_before_overwrite()
        product_ids.append(product_id)
        run_ids.extend(ids)
        product_id, ids = await _test_old_visual_run_excluded()
        product_ids.append(product_id)
        run_ids.extend(ids)
        product_id, ids = await _test_active_run_reuse()
        product_ids.append(product_id)
        run_ids.extend(ids)
        product_id, ids = await _test_downstream_image_creation_failure_preserves_final_facts()
        product_ids.append(product_id)
        run_ids.extend(ids)
    finally:
        if product_ids or run_ids:
            await _cleanup(product_ids, run_ids)


if __name__ == "__main__":
    asyncio.run(main())
