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
    FAILED,
    WORKFLOW_NODE_AUTO_SELECT_COMPETITOR,
    WORKFLOW_NODE_CAPTURE_COMPETITOR_CANDIDATES,
    WORKFLOW_NODE_IMAGE_ANALYSIS,
    WORKFLOW_NODE_VISUAL_MATCH_COMPETITORS,
    WORKFLOW_STATUS_FAILED,
    WORKFLOW_STATUS_PENDING,
    WORKFLOW_STATUS_PROCESSING,
)
from app.product_tasks import actions as product_actions  # noqa: E402
from app.services.amazon_competitor_visual_match import CompetitorVisualMatchError  # noqa: E402
from app.services.amazon_listing_detail import FixtureAmazonListingDetailAdapter  # noqa: E402
from app.task_runtime import scheduler  # noqa: E402
from app.task_runtime.constants import (  # noqa: E402
    RUN_STATUS_FAILED,
    RUN_STATUS_PENDING,
    RUN_STATUS_RUNNING,
    RUN_STATUS_SUCCEEDED,
    STEP_STATUS_FAILED,
    STEP_STATUS_PENDING,
    STEP_STATUS_READY,
    STEP_STATUS_RUNNING,
    STEP_STATUS_SUCCEEDED,
)
from app.task_runtime.json_utils import json_dumps, json_loads  # noqa: E402


DETAIL_HTML = """
<html><body data-asin="{asin}">
  <span id="productTitle">{title}</span>
  <a id="bylineInfo">Visit the QA Fix Store</a>
  <a id="sellerProfileTriggerId">QA Fix Seller LLC</a>
  <img id="landingImage" src="https://images.example/{asin}.jpg" />
  <div id="feature-bullets">
    <ul>
      <li><span class="a-list-item">Modular sofa with storage chaise.</span></li>
      <li><span class="a-list-item">Linen upholstery for living rooms.</span></li>
    </ul>
  </div>
  <table>
    <tr><th>Best Sellers Rank</th><td>#12 in Home & Kitchen &gt; Furniture &gt; Sofas</td></tr>
  </table>
</body></html>
"""


def _ensure_actions_registered() -> None:
    try:
        product_actions.register_product_task_actions()
    except Exception:
        pass
    product_actions.kick_task_runtime = lambda: None


async def _delete_runs(session, run_ids: list[int]) -> None:
    if not run_ids:
        return
    await session.execute(delete(TaskStepEvent).where(TaskStepEvent.task_run_id.in_(run_ids)))
    await session.execute(delete(TaskStep).where(TaskStep.task_run_id.in_(run_ids)))
    await session.execute(delete(TaskGroup).where(TaskGroup.task_run_id.in_(run_ids)))
    await session.execute(delete(TaskRun).where(TaskRun.id.in_(run_ids)))


async def _cleanup(product_ids: list[int], run_ids: list[int]) -> None:
    async with async_session() as session:
        marker_product_ids = [
            int(value)
            for value in (
                await session.execute(select(Product.id).where(Product.gigab2b_product_id.like("QA_FIX_%")))
            ).scalars().all()
        ]
        product_ids = sorted(set(product_ids + marker_product_ids))
        marker_run_ids = [
            int(value)
            for value in (
                await session.execute(select(TaskRun.id).where(TaskRun.created_by == "qa-fix-test"))
            ).scalars().all()
        ]
        run_ids = sorted(set(run_ids + marker_run_ids))
        if product_ids:
            await session.execute(delete(AmazonCompetitorSearchCandidate).where(AmazonCompetitorSearchCandidate.product_id.in_(product_ids)))
            await session.execute(delete(ProductImage).where(ProductImage.product_id.in_(product_ids)))
            await session.execute(delete(ProductData).where(ProductData.product_id.in_(product_ids)))
            await session.execute(delete(CatalogProduct).where(CatalogProduct.source_product_id.in_(product_ids)))
            await session.execute(delete(Product).where(Product.id.in_(product_ids)))
        await _delete_runs(session, run_ids)
        await session.commit()


async def _make_product(
    session,
    marker: str,
    *,
    node: str = WORKFLOW_NODE_VISUAL_MATCH_COMPETITORS,
    status: str = WORKFLOW_STATUS_PROCESSING,
) -> Product:
    now = datetime.now()
    product = Product(
        gigab2b_url=f"https://qa-fix.example/{marker}",
        gigab2b_product_id=marker,
        status="competitor_visual_matching",
        current_step=2,
        workflow_node=node,
        workflow_status=status,
        created_at=now,
        updated_at=now,
    )
    product.data = ProductData(
        item_code=marker,
        title="QA fix modular sofa",
        product_type="modular sofa",
        material="linen",
        description="A safe local test product for Amazon main-chain QA fixes.",
    )
    product.images = ProductImage(
        main_image_path="https://images.example/source-sofa.jpg",
        main_image_source="auto",
    )
    product.catalog_item = CatalogProduct(
        gigab2b_url=product.gigab2b_url,
        gigab2b_product_id=marker,
        item_code=marker,
        title="QA fix modular sofa",
        status="created",
    )
    session.add(product)
    await session.flush()
    return product


async def _make_run(
    session,
    *,
    product_id: int,
    task_type: str,
    suffix: str,
    run_status: str,
    step_status: str,
) -> tuple[TaskRun, TaskStep]:
    now = datetime.now()
    correlation_by_type = {
        "product_competitor_search": "competitor_search",
        "product_competitor_visual_match": "competitor_visual_match",
        "product_competitor_candidate_capture": "competitor_candidate_capture",
        "product_auto_competitor_selection": "auto_competitor_selection",
        "product_image_analysis": "image_analysis",
    }
    run = TaskRun(
        task_type=task_type,
        title=f"QA fix {task_type} {suffix}",
        status=run_status,
        payload_json=json_dumps({"product_id": product_id}),
        created_by="qa-fix-test",
        correlation_key=f"product:{product_id}:{correlation_by_type[task_type]}",
        created_at=now,
        updated_at=now,
    )
    session.add(run)
    await session.flush()
    group = TaskGroup(
        task_run_id=run.id,
        group_key=suffix,
        title=suffix,
        status=run_status,
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
        step_key=f"product:{product_id}:{correlation_by_type[task_type]}",
        step_type=task_type,
        status=step_status,
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


async def _make_search_candidate(
    session,
    *,
    product_id: int,
    asin: str,
    search_run_id: int,
    search_step_id: int,
    rank: int,
) -> AmazonCompetitorSearchCandidate:
    row = AmazonCompetitorSearchCandidate(
        product_id=product_id,
        task_run_id=search_run_id,
        task_step_id=search_step_id,
        search_query="qa fix modular sofa",
        search_rank=rank,
        source="amazon_search_page",
        asin=asin,
        url=f"https://www.amazon.com/dp/{asin}",
        title=f"QA fix competitor {rank}",
        image_url=f"https://images.example/{asin}.jpg",
        visual_selected_for_capture=0,
        updated_at=datetime.now(),
    )
    session.add(row)
    await session.flush()
    return row


async def _test_visual_failure_runner_projection_is_stable() -> tuple[int, list[int]]:
    async with async_session() as session:
        product = await _make_product(session, "QA_FIX_VISUAL_FAILURE")
        run, _step = await _make_run(
            session,
            product_id=product.id,
            task_type="product_competitor_visual_match",
            suffix="visual_failure",
            run_status=RUN_STATUS_PENDING,
            step_status=STEP_STATUS_READY,
        )
        await session.commit()

    original = product_actions.run_competitor_visual_match

    async def _raise_vlm_failure(*_args, **_kwargs):
        raise CompetitorVisualMatchError("VLM direct URL 调用失败: APIConnectionError: TLS certificate verify failed")

    product_actions.run_competitor_visual_match = _raise_vlm_failure
    try:
        await scheduler.drain_ready_steps()
    finally:
        product_actions.run_competitor_visual_match = original

    async with async_session() as session:
        refreshed_product = (
            await session.execute(select(Product).where(Product.id == product.id))
        ).scalar_one()
        refreshed_run = (
            await session.execute(
                select(TaskRun)
                .where(TaskRun.id == run.id)
                .options(selectinload(TaskRun.groups).selectinload(TaskGroup.steps))
            )
        ).scalar_one()
        refreshed_step = refreshed_run.groups[0].steps[0]
        assert refreshed_run.status == RUN_STATUS_FAILED, refreshed_run.status
        assert refreshed_run.groups[0].status == RUN_STATUS_FAILED, refreshed_run.groups[0].status
        assert refreshed_step.status == STEP_STATUS_FAILED, refreshed_step.status
        assert refreshed_step.locked_until is None, refreshed_step.locked_until
        assert refreshed_product.status == FAILED, refreshed_product.status
        assert refreshed_product.workflow_node == WORKFLOW_NODE_VISUAL_MATCH_COMPETITORS, refreshed_product.workflow_node
        assert refreshed_product.workflow_status == WORKFLOW_STATUS_FAILED, refreshed_product.workflow_status
        message = refreshed_product.workflow_error or refreshed_product.error_message or ""
        assert "APIConnectionError" in message and "竞品视觉初筛失败" in message, message
    return product.id, [run.id]


async def _test_visual_success_auto_starts_candidate_capture_and_typed_blocker() -> tuple[int, list[int]]:
    async with async_session() as session:
        product = await _make_product(
            session,
            "QA_FIX_VISUAL_CONTINUE",
            node=WORKFLOW_NODE_VISUAL_MATCH_COMPETITORS,
            status=WORKFLOW_STATUS_PROCESSING,
        )
        search_run, search_step = await _make_run(
            session,
            product_id=product.id,
            task_type="product_competitor_search",
            suffix="search_success",
            run_status=RUN_STATUS_SUCCEEDED,
            step_status=STEP_STATUS_SUCCEEDED,
        )
        visual_run, visual_step = await _make_run(
            session,
            product_id=product.id,
            task_type="product_competitor_visual_match",
            suffix="visual_success",
            run_status=RUN_STATUS_RUNNING,
            step_status=STEP_STATUS_RUNNING,
        )
        product_id = product.id
        search_run_id = search_run.id
        search_step_id = search_step.id
        visual_run_id = visual_run.id
        first = await _make_search_candidate(
            session,
            product_id=product_id,
            asin="B0QAFIX001",
            search_run_id=search_run_id,
            search_step_id=search_step_id,
            rank=1,
        )
        second = await _make_search_candidate(
            session,
            product_id=product_id,
            asin="B0QAFIX002",
            search_run_id=search_run_id,
            search_step_id=search_step_id,
            rank=2,
        )
        first_id = first.id
        second_id = second.id
        await session.commit()

        action = product_actions.ProductCompetitorVisualMatchAction()
        result_payload = {
            "product_id": product_id,
            "item_code": "QA_FIX_VISUAL_CONTINUE",
            "search_run_id": search_run_id,
            "search_step_id": search_step_id,
            "valid_image_count": 2,
            "model": "qa_fix_visual_model",
            "candidate_results": [
                {
                    "candidate_id": first_id,
                    "visual_rank": 1,
                    "visual_similarity": 0.93,
                    "same_product_type": True,
                    "selected_for_capture": True,
                },
                {
                    "candidate_id": second_id,
                    "visual_rank": 2,
                    "visual_similarity": 0.88,
                    "same_product_type": True,
                    "selected_for_capture": True,
                },
            ],
        }
        await action.on_step_success(
            session,
            visual_step,
            result_payload,
        )

        capture_run = (
            await session.execute(
                select(TaskRun)
                .where(TaskRun.task_type == "product_competitor_candidate_capture")
                .where(TaskRun.correlation_key == f"product:{product_id}:competitor_candidate_capture")
                .options(selectinload(TaskRun.groups).selectinload(TaskGroup.steps))
            )
        ).scalar_one_or_none()
        if capture_run is None:
            debug_product = (await session.execute(select(Product).where(Product.id == product_id))).scalar_one()
            debug_visual_run = (await session.execute(select(TaskRun).where(TaskRun.id == visual_run_id))).scalar_one()
            debug_summary = json_loads(debug_visual_run.summary_json, {})
            raise AssertionError(
                "visual success must create or reuse candidate capture task; "
                f"result={result_payload!r} workflow={debug_product.workflow_node}/{debug_product.workflow_status} "
                f"error={debug_product.workflow_error or debug_product.error_message!r} summary={debug_summary!r}"
            )
        assert capture_run.status in {RUN_STATUS_PENDING, RUN_STATUS_RUNNING}, capture_run.status
        assert capture_run.groups[0].steps[0].status == STEP_STATUS_READY, capture_run.groups[0].steps[0].status
        summary = json_loads(visual_run.summary_json, {})
        assert summary.get("candidate_capture_task_run_ids") == [capture_run.id], summary
        assert summary.get("next_node") == WORKFLOW_NODE_CAPTURE_COMPETITOR_CANDIDATES, summary

        capture_run_id = capture_run.id

    await scheduler.drain_ready_steps()

    async with async_session() as session:
        refreshed_product = (await session.execute(select(Product).where(Product.id == product_id))).scalar_one()
        refreshed_capture_run = (
            await session.execute(
                select(TaskRun)
                .where(TaskRun.id == capture_run_id)
                .options(selectinload(TaskRun.groups).selectinload(TaskGroup.steps))
            )
        ).scalar_one()
        capture_step = refreshed_capture_run.groups[0].steps[0]
        assert refreshed_capture_run.status == RUN_STATUS_FAILED, refreshed_capture_run.status
        assert capture_step.status == STEP_STATUS_FAILED, capture_step.status
        assert refreshed_product.workflow_node == WORKFLOW_NODE_CAPTURE_COMPETITOR_CANDIDATES, refreshed_product.workflow_node
        assert refreshed_product.workflow_status == WORKFLOW_STATUS_FAILED, refreshed_product.workflow_status
        blocker = refreshed_product.workflow_error or refreshed_product.error_message or ""
        assert "adapter_not_configured" in blocker, blocker

        auto_selection = (
            await session.execute(
                select(TaskRun)
                .where(TaskRun.task_type == "product_auto_competitor_selection")
                .where(TaskRun.correlation_key == f"product:{product_id}:auto_competitor_selection")
            )
        ).scalar_one_or_none()
        assert auto_selection is None, "auto selection must wait for successful detail capture facts"
        return product_id, [search_run_id, visual_run_id, capture_run_id]


async def _test_new_visual_success_owns_capture_set_when_old_visual_succeeded() -> tuple[int, list[int]]:
    async with async_session() as session:
        product = await _make_product(
            session,
            "QA_FIX_CURRENT_VISUAL_OWNER",
            node=WORKFLOW_NODE_VISUAL_MATCH_COMPETITORS,
            status=WORKFLOW_STATUS_PROCESSING,
        )
        product_id = product.id
        old_visual_run, old_visual_step = await _make_run(
            session,
            product_id=product_id,
            task_type="product_competitor_visual_match",
            suffix="old_visual_success",
            run_status=RUN_STATUS_SUCCEEDED,
            step_status=STEP_STATUS_SUCCEEDED,
        )
        old_candidate = await _make_search_candidate(
            session,
            product_id=product_id,
            asin="B0QAOLD001",
            search_run_id=old_visual_run.id,
            search_step_id=old_visual_step.id,
            rank=1,
        )
        old_candidate.visual_task_run_id = old_visual_run.id
        old_candidate.visual_task_step_id = old_visual_step.id
        old_candidate.visual_rank = 1
        old_candidate.visual_selected_for_capture = 0
        old_candidate.visual_matched_at = datetime.now()
        search_run, search_step = await _make_run(
            session,
            product_id=product_id,
            task_type="product_competitor_search",
            suffix="new_search_success",
            run_status=RUN_STATUS_SUCCEEDED,
            step_status=STEP_STATUS_SUCCEEDED,
        )
        new_visual_run, new_visual_step = await _make_run(
            session,
            product_id=product_id,
            task_type="product_competitor_visual_match",
            suffix="new_visual_running",
            run_status=RUN_STATUS_RUNNING,
            step_status=STEP_STATUS_RUNNING,
        )
        first = await _make_search_candidate(
            session,
            product_id=product_id,
            asin="B0QANEW001",
            search_run_id=search_run.id,
            search_step_id=search_step.id,
            rank=1,
        )
        second = await _make_search_candidate(
            session,
            product_id=product_id,
            asin="B0QANEW002",
            search_run_id=search_run.id,
            search_step_id=search_step.id,
            rank=2,
        )
        old_visual_run_id = old_visual_run.id
        search_run_id = search_run.id
        search_step_id = search_step.id
        new_visual_run_id = new_visual_run.id
        new_visual_step_id = new_visual_step.id
        first_id = first.id
        second_id = second.id
        await session.commit()

        result_payload = {
            "product_id": product_id,
            "item_code": "QA_FIX_CURRENT_VISUAL_OWNER",
            "search_run_id": search_run_id,
            "search_step_id": search_step_id,
            "valid_image_count": 2,
            "model": "qa_fix_visual_model",
            "candidate_results": [
                {
                    "candidate_id": first_id,
                    "visual_rank": 1,
                    "visual_similarity": 0.94,
                    "same_product_type": True,
                    "selected_for_capture": True,
                },
                {
                    "candidate_id": second_id,
                    "visual_rank": 2,
                    "visual_similarity": 0.89,
                    "same_product_type": True,
                    "selected_for_capture": True,
                },
            ],
        }
        action = product_actions.ProductCompetitorVisualMatchAction()
        await action.on_step_success(session, new_visual_step, result_payload)

        capture_run = (
            await session.execute(
                select(TaskRun)
                .where(TaskRun.task_type == "product_competitor_candidate_capture")
                .where(TaskRun.correlation_key == f"product:{product_id}:competitor_candidate_capture")
                .options(selectinload(TaskRun.groups).selectinload(TaskGroup.steps))
            )
        ).scalar_one_or_none()
        assert capture_run is not None, "new visual success must create capture task even when old visual succeeded exists"
        capture_step = capture_run.groups[0].steps[0]
        run_payload = json_loads(capture_run.payload_json, {})
        step_payload = json_loads(capture_step.payload_json, {})
        assert run_payload["visual_task_run_id"] == new_visual_run_id, run_payload
        assert run_payload["visual_task_step_id"] == new_visual_step_id, run_payload
        assert step_payload["visual_task_run_id"] == new_visual_run_id, step_payload
        assert step_payload["visual_task_step_id"] == new_visual_step_id, step_payload
        capture_run_id = capture_run.id

    await scheduler.drain_ready_steps()

    async with async_session() as session:
        refreshed_product = (await session.execute(select(Product).where(Product.id == product_id))).scalar_one()
        refreshed_capture_run = (
            await session.execute(
                select(TaskRun)
                .where(TaskRun.id == capture_run_id)
                .options(selectinload(TaskRun.groups).selectinload(TaskGroup.steps))
            )
        ).scalar_one()
        new_rows = (
            await session.execute(
                select(AmazonCompetitorSearchCandidate)
                .where(AmazonCompetitorSearchCandidate.product_id == product_id)
                .where(AmazonCompetitorSearchCandidate.visual_task_run_id == new_visual_run_id)
                .where(AmazonCompetitorSearchCandidate.visual_task_step_id == new_visual_step_id)
                .order_by(AmazonCompetitorSearchCandidate.visual_rank.asc())
            )
        ).scalars().all()
        old_rows = (
            await session.execute(
                select(AmazonCompetitorSearchCandidate)
                .where(AmazonCompetitorSearchCandidate.product_id == product_id)
                .where(AmazonCompetitorSearchCandidate.visual_task_run_id == old_visual_run_id)
            )
        ).scalars().all()
        assert refreshed_capture_run.status == RUN_STATUS_FAILED, refreshed_capture_run.status
        assert refreshed_product.workflow_node == WORKFLOW_NODE_CAPTURE_COMPETITOR_CANDIDATES, refreshed_product.workflow_node
        assert refreshed_product.workflow_status == WORKFLOW_STATUS_FAILED, refreshed_product.workflow_status
        assert "adapter_not_configured" in (refreshed_product.workflow_error or refreshed_product.error_message or ""), refreshed_product.workflow_error
        assert len(new_rows) == 2, [(row.asin, row.capture_status) for row in new_rows]
        assert all(row.capture_status is None for row in old_rows), [(row.asin, row.capture_status) for row in old_rows]
        return product_id, [old_visual_run_id, search_run_id, new_visual_run_id, capture_run_id]


async def _test_fixture_detail_success_continues_to_image_analysis() -> tuple[int, list[int]]:
    async with async_session() as session:
        product = await _make_product(
            session,
            "QA_FIX_DETAIL_SUCCESS",
            node=WORKFLOW_NODE_CAPTURE_COMPETITOR_CANDIDATES,
            status=WORKFLOW_STATUS_PENDING,
        )
        product.status = "created"
        product_id = product.id
        visual_run, visual_step = await _make_run(
            session,
            product_id=product_id,
            task_type="product_competitor_visual_match",
            suffix="fixture_visual_success",
            run_status=RUN_STATUS_SUCCEEDED,
            step_status=STEP_STATUS_SUCCEEDED,
        )
        first = await _make_search_candidate(
            session,
            product_id=product_id,
            asin="B0QASUCC001",
            search_run_id=visual_run.id,
            search_step_id=visual_step.id,
            rank=1,
        )
        second = await _make_search_candidate(
            session,
            product_id=product_id,
            asin="B0QASUCC002",
            search_run_id=visual_run.id,
            search_step_id=visual_step.id,
            rank=2,
        )
        for rank, row in enumerate((first, second), start=1):
            row.visual_task_run_id = visual_run.id
            row.visual_task_step_id = visual_step.id
            row.visual_rank = rank
            row.visual_similarity_score = 0.96 - (rank * 0.04)
            row.visual_same_product_type = 1
            row.visual_selected_for_capture = 1
            row.visual_matched_at = datetime.now()
        visual_run_id = visual_run.id
        await session.commit()

        original_adapter = product_actions.get_amazon_listing_detail_adapter
        product_actions.get_amazon_listing_detail_adapter = lambda: FixtureAmazonListingDetailAdapter({
            "B0QASUCC001": DETAIL_HTML.format(asin="B0QASUCC001", title="Modern modular sofa with storage chaise"),
            "B0QASUCC002": DETAIL_HTML.format(asin="B0QASUCC002", title="Linen modular sectional sofa"),
        })
        try:
            capture_runs = await product_actions.create_product_action_runs(
                session,
                "product_competitor_candidate_capture",
                [{"product_id": product_id, "created_by": "qa_fixture_success"}],
                created_by="qa_fixture_success",
                auto_start=False,
            )
            capture_run = capture_runs[0]
            capture_step = capture_run.groups[0].steps[0]
            capture_action = product_actions.ProductCompetitorCandidateCaptureAction()
            result = await capture_action.execute_step(session, capture_step, {"product_id": product_id})
            assert result["success_count"] == 2, result
            await capture_action.on_step_success(session, capture_step, result)
        finally:
            product_actions.get_amazon_listing_detail_adapter = original_adapter

        auto_run = (
            await session.execute(
                select(TaskRun)
                .where(TaskRun.task_type == "product_auto_competitor_selection")
                .where(TaskRun.correlation_key == f"product:{product_id}:auto_competitor_selection")
                .options(selectinload(TaskRun.groups).selectinload(TaskGroup.steps))
            )
        ).scalar_one_or_none()
        assert auto_run is not None, "candidate capture success must create or reuse auto competitor selection task"
        assert auto_run.groups[0].steps[0].status == STEP_STATUS_READY, auto_run.groups[0].steps[0].status
        capture_summary = json_loads(capture_run.summary_json, {})
        assert capture_summary.get("auto_competitor_selection_task_run_ids") == [auto_run.id], capture_summary
        auto_run_id = auto_run.id
        capture_run_id = capture_run.id

    await scheduler.drain_ready_steps()

    async with async_session() as session:
        refreshed_product = (
            await session.execute(
                select(Product)
                .where(Product.id == product_id)
                .options(selectinload(Product.catalog_item), selectinload(Product.data))
            )
        ).scalar_one()
        refreshed_auto_run = (
            await session.execute(
                select(TaskRun)
                .where(TaskRun.id == auto_run_id)
                .options(selectinload(TaskRun.groups).selectinload(TaskGroup.steps))
            )
        ).scalar_one()
        image_run = (
            await session.execute(
                select(TaskRun)
                .where(TaskRun.task_type == "product_image_analysis")
                .where(TaskRun.correlation_key == f"product:{product_id}:image_analysis")
                .options(selectinload(TaskRun.groups).selectinload(TaskGroup.steps))
            )
        ).scalar_one_or_none()
        assert refreshed_auto_run.status == RUN_STATUS_SUCCEEDED, refreshed_auto_run.status
        assert refreshed_auto_run.groups[0].steps[0].status == STEP_STATUS_SUCCEEDED, refreshed_auto_run.groups[0].steps[0].status
        assert image_run is not None, "auto competitor success must create or reuse image analysis task"
        assert image_run.status == RUN_STATUS_PENDING, image_run.status
        assert image_run.groups[0].steps[0].status == STEP_STATUS_PENDING, image_run.groups[0].steps[0].status
        assert refreshed_product.workflow_node == WORKFLOW_NODE_IMAGE_ANALYSIS, refreshed_product.workflow_node
        assert refreshed_product.workflow_status == WORKFLOW_STATUS_PROCESSING, refreshed_product.workflow_status
        assert refreshed_product.competitor_asin == "B0QASUCC001", refreshed_product.competitor_asin
        assert refreshed_product.catalog_item.competitor_asin == "B0QASUCC001", refreshed_product.catalog_item.competitor_asin
        snapshot = json_loads(refreshed_product.data.gigab2b_raw_snapshot, {})
        assert snapshot["selected_competitor"]["asin"] == "B0QASUCC001", snapshot
        return product_id, [visual_run_id, capture_run_id, auto_run_id, image_run.id]


async def main() -> None:
    await run_schema_maintenance()
    _ensure_actions_registered()
    product_ids: list[int] = []
    run_ids: list[int] = []
    try:
        product_id, ids = await _test_visual_failure_runner_projection_is_stable()
        product_ids.append(product_id)
        run_ids.extend(ids)
        product_id, ids = await _test_visual_success_auto_starts_candidate_capture_and_typed_blocker()
        product_ids.append(product_id)
        run_ids.extend(ids)
        product_id, ids = await _test_new_visual_success_owns_capture_set_when_old_visual_succeeded()
        product_ids.append(product_id)
        run_ids.extend(ids)
        product_id, ids = await _test_fixture_detail_success_continues_to_image_analysis()
        product_ids.append(product_id)
        run_ids.extend(ids)
        print("amazon main-chain after-search QA fix behavior checks passed")
    finally:
        await _cleanup(product_ids, run_ids)


if __name__ == "__main__":
    asyncio.run(main())
