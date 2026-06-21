from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
import sys

from sqlalchemy import delete, select

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.database import async_session, run_schema_maintenance  # noqa: E402
from app.models import AmazonCompetitorSearchCandidate, Product, ProductData, TaskGroup, TaskRun, TaskStep, TaskStepEvent  # noqa: E402
from app.models.status import WORKFLOW_NODE_AUTO_SELECT_COMPETITOR, WORKFLOW_NODE_CAPTURE_COMPETITOR_CANDIDATES, WORKFLOW_STATUS_FAILED, WORKFLOW_STATUS_PENDING  # noqa: E402
from app.product_tasks import actions as product_actions  # noqa: E402
from app.services.amazon_listing_detail import FixtureAmazonListingDetailAdapter  # noqa: E402
from app.task_runtime.constants import RUN_STATUS_RUNNING, RUN_STATUS_SUCCEEDED, STEP_STATUS_RUNNING, STEP_STATUS_SUCCEEDED  # noqa: E402
from app.task_runtime.json_utils import json_dumps  # noqa: E402


HTML = """
<html><body data-asin="{asin}">
  <span id="productTitle">{title}</span>
  <a id="bylineInfo">Visit the Phase2A Store</a>
  <a id="sellerProfileTriggerId">Phase2A Seller LLC</a>
  <img id="landingImage" src="https://images.example/{asin}.jpg" />
  <div id="feature-bullets">
    <ul>
      <li><span class="a-list-item">Deterministic fixture bullet one.</span></li>
      <li><span class="a-list-item">Deterministic fixture bullet two.</span></li>
    </ul>
  </div>
  <table>
    <tr><th>Best Sellers Rank</th><td>#12 in Home & Kitchen &gt; Furniture &gt; Sofas</td></tr>
  </table>
</body></html>
"""


async def _make_run(session, *, product_id: int, task_type: str, suffix: str, status: str) -> tuple[TaskRun, TaskStep]:
    now = datetime.now()
    run = TaskRun(
        task_type=task_type,
        title=f"Phase2A {task_type} {suffix}",
        status=status,
        payload_json=json_dumps({"product_id": product_id}),
        created_by="phase2a-test",
        correlation_key=f"product:{product_id}:{suffix}",
        created_at=now,
        updated_at=now,
    )
    if task_type == "product_competitor_visual_match":
        run.correlation_key = f"product:{product_id}:competitor_visual_match"
    elif task_type == "product_competitor_candidate_capture":
        run.correlation_key = f"product:{product_id}:competitor_candidate_capture"
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


async def _make_product(session, marker: str) -> Product:
    now = datetime.now()
    product = Product(
        gigab2b_url=f"https://phase2a.example/{marker}",
        gigab2b_product_id=marker,
        status="created",
        current_step=2,
        workflow_node=WORKFLOW_NODE_CAPTURE_COMPETITOR_CANDIDATES,
        workflow_status=WORKFLOW_STATUS_PENDING,
        created_at=now,
        updated_at=now,
    )
    product.data = ProductData(item_code=marker, title="Phase2A modular sofa")
    session.add(product)
    await session.flush()
    return product


async def _make_candidate(
    session,
    *,
    product_id: int,
    asin: str,
    search_run_id: int,
    search_step_id: int,
    visual_run_id: int,
    visual_step_id: int,
    visual_rank: int,
    selected: int = 1,
) -> AmazonCompetitorSearchCandidate:
    row = AmazonCompetitorSearchCandidate(
        product_id=product_id,
        task_run_id=search_run_id,
        task_step_id=search_step_id,
        search_query="phase2a sofa",
        search_rank=visual_rank,
        asin=asin,
        url=f"https://www.amazon.com/dp/{asin}",
        title=f"Search title {asin}",
        image_url=f"https://images.example/{asin}.jpg",
        visual_task_run_id=visual_run_id,
        visual_task_step_id=visual_step_id,
        visual_rank=visual_rank,
        visual_selected_for_capture=selected,
        visual_matched_at=datetime.now(),
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
        await session.execute(delete(AmazonCompetitorSearchCandidate).where(AmazonCompetitorSearchCandidate.product_id.in_(product_ids)))
        await session.execute(delete(ProductData).where(ProductData.product_id.in_(product_ids)))
        await session.execute(delete(Product).where(Product.id.in_(product_ids)))
        await _delete_runs(session, run_ids)
        await session.commit()


def _seed_stale_detail_and_final(
    row: AmazonCompetitorSearchCandidate,
    *,
    run_id: int,
    step_id: int,
) -> None:
    row.detail_task_run_id = run_id
    row.detail_task_step_id = step_id
    row.detail_captured_at = datetime.now()
    row.brand = "STALE_BRAND"
    row.seller = "STALE_SELLER"
    row.category_rank = "STALE_RANK"
    row.leaf_category = "STALE_CATEGORY"
    row.main_image_url = "https://images.example/stale.jpg"
    row.bullets_json = json_dumps(["stale bullet"])
    row.description = "stale description"
    row.product_details_json = json_dumps({"stale": "value"})
    row.aplus_text = "stale aplus"
    row.capture_status = "succeeded"
    row.capture_error = None
    row.capture_raw_json = json_dumps({"stale": True})
    row.final_selected = 1
    row.final_rank = 1
    row.final_score = 0.99
    row.final_confidence = "high"
    row.final_dimension_scores_json = json_dumps({"stale": 1})
    row.final_reason = "stale final reason"
    row.final_risks_json = json_dumps([])
    row.final_model = "stale_model"
    row.final_rule_version = "stale_rule"
    row.final_raw_json = json_dumps({"stale": True})
    row.final_selected_at = datetime.now()


def _assert_stale_detail_and_final_cleared(row: AmazonCompetitorSearchCandidate) -> None:
    assert row.detail_task_run_id is None, row.detail_task_run_id
    assert row.detail_task_step_id is None, row.detail_task_step_id
    assert row.detail_captured_at is None, row.detail_captured_at
    assert row.brand is None, row.brand
    assert row.seller is None, row.seller
    assert row.category_rank is None, row.category_rank
    assert row.leaf_category is None, row.leaf_category
    assert row.main_image_url is None, row.main_image_url
    assert row.bullets_json is None, row.bullets_json
    assert row.description is None, row.description
    assert row.product_details_json is None, row.product_details_json
    assert row.aplus_text is None, row.aplus_text
    assert row.capture_status is None, row.capture_status
    assert row.capture_error is None, row.capture_error
    assert row.capture_raw_json is None, row.capture_raw_json
    assert row.final_selected == 0, row.final_selected
    assert row.final_rank is None, row.final_rank
    assert row.final_score is None, row.final_score
    assert row.final_confidence is None, row.final_confidence
    assert row.final_dimension_scores_json is None, row.final_dimension_scores_json
    assert row.final_reason is None, row.final_reason
    assert row.final_risks_json is None, row.final_risks_json
    assert row.final_model is None, row.final_model
    assert row.final_rule_version is None, row.final_rule_version
    assert row.final_raw_json is None, row.final_raw_json
    assert row.final_selected_at is None, row.final_selected_at


async def _test_partial_success_current_set() -> tuple[int, list[int]]:
    async with async_session() as session:
        product = await _make_product(session, "PHASE2A_TEST_PARTIAL")
        old_visual_run, old_visual_step = await _make_run(
            session,
            product_id=product.id,
            task_type="product_competitor_visual_match",
            suffix="old_visual",
            status=RUN_STATUS_SUCCEEDED,
        )
        current_visual_run, current_visual_step = await _make_run(
            session,
            product_id=product.id,
            task_type="product_competitor_visual_match",
            suffix="current_visual",
            status=RUN_STATUS_SUCCEEDED,
        )
        capture_run, capture_step = await _make_run(
            session,
            product_id=product.id,
            task_type="product_competitor_candidate_capture",
            suffix="candidate_capture",
            status=RUN_STATUS_RUNNING,
        )
        old_candidate = await _make_candidate(
            session,
            product_id=product.id,
            asin="B0OLDPHASE2A",
            search_run_id=old_visual_run.id,
            search_step_id=old_visual_step.id,
            visual_run_id=old_visual_run.id,
            visual_step_id=old_visual_step.id,
            visual_rank=1,
        )
        first = await _make_candidate(
            session,
            product_id=product.id,
            asin="B0GOODPH2A1",
            search_run_id=current_visual_run.id,
            search_step_id=current_visual_step.id,
            visual_run_id=current_visual_run.id,
            visual_step_id=current_visual_step.id,
            visual_rank=1,
        )
        second = await _make_candidate(
            session,
            product_id=product.id,
            asin="B0MISSPH2A2",
            search_run_id=current_visual_run.id,
            search_step_id=current_visual_step.id,
            visual_run_id=current_visual_run.id,
            visual_step_id=current_visual_step.id,
            visual_rank=2,
        )
        await session.commit()

        original_adapter = product_actions.get_amazon_listing_detail_adapter
        product_actions.get_amazon_listing_detail_adapter = lambda: FixtureAmazonListingDetailAdapter({
            "B0GOODPH2A1": HTML.format(asin="B0GOODPH2A1", title="Good Phase2A Candidate")
        })
        try:
            action = product_actions.ProductCompetitorCandidateCaptureAction()
            await action.validate(session, {"product_id": product.id})
            result = await action.execute_step(session, capture_step, {"product_id": product.id})
            assert result["success_count"] == 1, result
            await action.on_step_success(session, capture_step, result)
        finally:
            product_actions.get_amazon_listing_detail_adapter = original_adapter

        refreshed = (await session.execute(select(Product).where(Product.id == product.id))).scalar_one()
        rows = {
            row.id: row
            for row in (
                await session.execute(
                    select(AmazonCompetitorSearchCandidate)
                    .where(AmazonCompetitorSearchCandidate.product_id == product.id)
                )
            ).scalars().all()
        }
        assert refreshed.workflow_node == WORKFLOW_NODE_AUTO_SELECT_COMPETITOR, refreshed.workflow_node
        assert refreshed.workflow_status == WORKFLOW_STATUS_PENDING, refreshed.workflow_status
        assert refreshed.competitor_asin is None, refreshed.competitor_asin
        assert rows[old_candidate.id].capture_status is None, rows[old_candidate.id].capture_status
        assert rows[first.id].capture_status == "succeeded", rows[first.id].capture_status
        assert rows[first.id].detail_task_run_id == capture_run.id, rows[first.id].detail_task_run_id
        assert rows[second.id].capture_status == "failed", rows[second.id].capture_status
        assert rows[second.id].detail_task_step_id == capture_step.id, rows[second.id].detail_task_step_id
        return product.id, [old_visual_run.id, current_visual_run.id, capture_run.id]


async def _test_full_failure_leaves_no_current_facts() -> tuple[int, list[int]]:
    async with async_session() as session:
        product = await _make_product(session, "PHASE2A_TEST_FAIL")
        visual_run, visual_step = await _make_run(
            session,
            product_id=product.id,
            task_type="product_competitor_visual_match",
            suffix="current_visual",
            status=RUN_STATUS_SUCCEEDED,
        )
        capture_run, capture_step = await _make_run(
            session,
            product_id=product.id,
            task_type="product_competitor_candidate_capture",
            suffix="candidate_capture",
            status=RUN_STATUS_RUNNING,
        )
        await _make_candidate(
            session,
            product_id=product.id,
            asin="B0FAILPH2A1",
            search_run_id=visual_run.id,
            search_step_id=visual_step.id,
            visual_run_id=visual_run.id,
            visual_step_id=visual_step.id,
            visual_rank=1,
        )
        await session.commit()

        original_adapter = product_actions.get_amazon_listing_detail_adapter
        product_actions.get_amazon_listing_detail_adapter = lambda: FixtureAmazonListingDetailAdapter({})
        try:
            action = product_actions.ProductCompetitorCandidateCaptureAction()
            try:
                await action.execute_step(session, capture_step, {"product_id": product.id})
            except RuntimeError:
                await action.on_step_failure(session, capture_step, RuntimeError("fixture all failed"))
            else:
                raise AssertionError("full failure must raise")
        finally:
            product_actions.get_amazon_listing_detail_adapter = original_adapter

        refreshed = (await session.execute(select(Product).where(Product.id == product.id))).scalar_one()
        rows = (
            await session.execute(
                select(AmazonCompetitorSearchCandidate)
                .where(AmazonCompetitorSearchCandidate.product_id == product.id)
            )
        ).scalars().all()
        assert refreshed.workflow_node == WORKFLOW_NODE_CAPTURE_COMPETITOR_CANDIDATES, refreshed.workflow_node
        assert refreshed.workflow_status == WORKFLOW_STATUS_FAILED, refreshed.workflow_status
        assert all(row.capture_status is None for row in rows), [row.capture_status for row in rows]
        return product.id, [visual_run.id, capture_run.id]


async def _test_same_asin_reused_row_clears_old_detail_and_final() -> tuple[int, list[int]]:
    async with async_session() as session:
        product = await _make_product(session, "PHASE2A_TEST_SAME_ASIN")
        old_visual_run, old_visual_step = await _make_run(
            session,
            product_id=product.id,
            task_type="product_competitor_visual_match",
            suffix="same_asin_old_visual",
            status=RUN_STATUS_SUCCEEDED,
        )
        current_visual_run, current_visual_step = await _make_run(
            session,
            product_id=product.id,
            task_type="product_competitor_visual_match",
            suffix="same_asin_current_visual",
            status=RUN_STATUS_SUCCEEDED,
        )
        capture_run, capture_step = await _make_run(
            session,
            product_id=product.id,
            task_type="product_competitor_candidate_capture",
            suffix="same_asin_candidate_capture",
            status=RUN_STATUS_RUNNING,
        )
        candidate = await _make_candidate(
            session,
            product_id=product.id,
            asin="B0SAMEPH2A",
            search_run_id=old_visual_run.id,
            search_step_id=old_visual_step.id,
            visual_run_id=old_visual_run.id,
            visual_step_id=old_visual_step.id,
            visual_rank=1,
        )
        _seed_stale_detail_and_final(candidate, run_id=old_visual_run.id, step_id=old_visual_step.id)
        await session.commit()

        candidate.visual_task_run_id = current_visual_run.id
        candidate.visual_task_step_id = current_visual_step.id
        candidate.visual_rank = 1
        candidate.visual_selected_for_capture = 1
        candidate.visual_matched_at = datetime.now()
        await session.commit()

        original_adapter = product_actions.get_amazon_listing_detail_adapter
        product_actions.get_amazon_listing_detail_adapter = lambda: FixtureAmazonListingDetailAdapter({
            "B0SAMEPH2A": HTML.format(asin="B0SAMEPH2A", title="Reused Same Asin Candidate")
        })
        try:
            action = product_actions.ProductCompetitorCandidateCaptureAction()
            await action.validate(session, {"product_id": product.id})
            await action.reserve(session, {"product_id": product.id}, capture_run)
            result = await action.execute_step(session, capture_step, {"product_id": product.id})
            assert result["candidate_results"][0]["candidate_id"] == candidate.id, result
            await action.on_step_success(session, capture_step, result)
        finally:
            product_actions.get_amazon_listing_detail_adapter = original_adapter

        row = (
            await session.execute(
                select(AmazonCompetitorSearchCandidate)
                .where(AmazonCompetitorSearchCandidate.id == candidate.id)
            )
        ).scalar_one()
        assert row.visual_task_run_id == current_visual_run.id, row.visual_task_run_id
        assert row.visual_task_step_id == current_visual_step.id, row.visual_task_step_id
        assert row.detail_task_run_id == capture_run.id, row.detail_task_run_id
        assert row.detail_task_step_id == capture_step.id, row.detail_task_step_id
        assert row.capture_status == "succeeded", row.capture_status
        assert row.brand != "STALE_BRAND", row.brand
        assert row.final_selected == 0, row.final_selected
        assert row.final_reason is None, row.final_reason
        return product.id, [old_visual_run.id, current_visual_run.id, capture_run.id]


async def _test_result_ids_mismatch_clears_current_facts() -> tuple[int, list[int]]:
    async with async_session() as session:
        product = await _make_product(session, "PHASE2A_TEST_IDS_MISMATCH")
        visual_run, visual_step = await _make_run(
            session,
            product_id=product.id,
            task_type="product_competitor_visual_match",
            suffix="ids_mismatch_visual",
            status=RUN_STATUS_SUCCEEDED,
        )
        capture_run, capture_step = await _make_run(
            session,
            product_id=product.id,
            task_type="product_competitor_candidate_capture",
            suffix="ids_mismatch_capture",
            status=RUN_STATUS_RUNNING,
        )
        first = await _make_candidate(
            session,
            product_id=product.id,
            asin="B0IDSPH2A1",
            search_run_id=visual_run.id,
            search_step_id=visual_step.id,
            visual_run_id=visual_run.id,
            visual_step_id=visual_step.id,
            visual_rank=1,
        )
        second = await _make_candidate(
            session,
            product_id=product.id,
            asin="B0IDSPH2A2",
            search_run_id=visual_run.id,
            search_step_id=visual_step.id,
            visual_run_id=visual_run.id,
            visual_step_id=visual_step.id,
            visual_rank=2,
        )
        _seed_stale_detail_and_final(first, run_id=capture_run.id, step_id=capture_step.id)
        _seed_stale_detail_and_final(second, run_id=capture_run.id, step_id=capture_step.id)
        await session.commit()

        action = product_actions.ProductCompetitorCandidateCaptureAction()
        missing_result = {
            "product_id": product.id,
            "visual_task_run_id": visual_run.id,
            "visual_task_step_id": visual_step.id,
            "candidate_results": [
                {
                    "candidate_id": first.id,
                    "asin": first.asin,
                    "visual_rank": first.visual_rank,
                    "status": "succeeded",
                    "detail": {"title": "Only one result", "bullets": ["one"]},
                    "raw": {"title": "Only one result"},
                }
            ],
            "success_count": 1,
        }
        try:
            await action.on_step_success(session, capture_step, missing_result)
        except RuntimeError as exc:
            assert "未完整匹配" in str(exc), str(exc)
        else:
            raise AssertionError("missing result ids must fail")

        refreshed = (await session.execute(select(Product).where(Product.id == product.id))).scalar_one()
        rows = {
            row.id: row
            for row in (
                await session.execute(
                    select(AmazonCompetitorSearchCandidate)
                    .where(AmazonCompetitorSearchCandidate.product_id == product.id)
                )
            ).scalars().all()
        }
        assert refreshed.workflow_node == WORKFLOW_NODE_CAPTURE_COMPETITOR_CANDIDATES, refreshed.workflow_node
        assert refreshed.workflow_status == WORKFLOW_STATUS_FAILED, refreshed.workflow_status
        _assert_stale_detail_and_final_cleared(rows[first.id])
        _assert_stale_detail_and_final_cleared(rows[second.id])

        _seed_stale_detail_and_final(rows[first.id], run_id=capture_run.id, step_id=capture_step.id)
        _seed_stale_detail_and_final(rows[second.id], run_id=capture_run.id, step_id=capture_step.id)
        refreshed.workflow_node = WORKFLOW_NODE_CAPTURE_COMPETITOR_CANDIDATES
        refreshed.workflow_status = WORKFLOW_STATUS_PENDING
        await session.commit()

        extra_result = {
            "product_id": product.id,
            "visual_task_run_id": visual_run.id,
            "visual_task_step_id": visual_step.id,
            "candidate_results": [
                {"candidate_id": first.id, "asin": first.asin, "visual_rank": 1, "status": "failed", "raw": {}},
                {"candidate_id": second.id, "asin": second.asin, "visual_rank": 2, "status": "failed", "raw": {}},
                {"candidate_id": 999999999, "asin": "B0EXTRAPH2A", "visual_rank": 3, "status": "succeeded", "detail": {"title": "extra", "bullets": ["extra"]}, "raw": {}},
            ],
            "success_count": 1,
        }
        try:
            await action.on_step_success(session, capture_step, extra_result)
        except RuntimeError as exc:
            assert "未完整匹配" in str(exc), str(exc)
        else:
            raise AssertionError("extra result ids must fail")

        rows = {
            row.id: row
            for row in (
                await session.execute(
                    select(AmazonCompetitorSearchCandidate)
                    .where(AmazonCompetitorSearchCandidate.product_id == product.id)
                )
            ).scalars().all()
        }
        _assert_stale_detail_and_final_cleared(rows[first.id])
        _assert_stale_detail_and_final_cleared(rows[second.id])
        return product.id, [visual_run.id, capture_run.id]


async def _test_cancel_and_interrupted_clear_current_facts() -> tuple[list[int], list[int]]:
    product_ids: list[int] = []
    run_ids: list[int] = []
    async with async_session() as session:
        action = product_actions.ProductCompetitorCandidateCaptureAction()
        for marker, mode in (
            ("PHASE2A_TEST_CANCEL", "cancel"),
            ("PHASE2A_TEST_INTERRUPTED", "interrupted"),
        ):
            product = await _make_product(session, marker)
            product.workflow_status = "processing"
            visual_run, visual_step = await _make_run(
                session,
                product_id=product.id,
                task_type="product_competitor_visual_match",
                suffix=f"{mode}_visual",
                status=RUN_STATUS_SUCCEEDED,
            )
            capture_run, capture_step = await _make_run(
                session,
                product_id=product.id,
                task_type="product_competitor_candidate_capture",
                suffix=f"{mode}_capture",
                status=RUN_STATUS_RUNNING,
            )
            candidate = await _make_candidate(
                session,
                product_id=product.id,
                asin=f"B0{mode.upper()[:6]}2A",
                search_run_id=visual_run.id,
                search_step_id=visual_step.id,
                visual_run_id=visual_run.id,
                visual_step_id=visual_step.id,
                visual_rank=1,
            )
            _seed_stale_detail_and_final(candidate, run_id=capture_run.id, step_id=capture_step.id)
            await session.commit()

            if mode == "cancel":
                await action.on_cancel_requested(session, capture_run, "test cancel")
            else:
                await action.on_step_interrupted(session, capture_step, "test interrupted")

            refreshed = (await session.execute(select(Product).where(Product.id == product.id))).scalar_one()
            row = (
                await session.execute(
                    select(AmazonCompetitorSearchCandidate)
                    .where(AmazonCompetitorSearchCandidate.id == candidate.id)
                )
            ).scalar_one()
            assert refreshed.workflow_node == WORKFLOW_NODE_CAPTURE_COMPETITOR_CANDIDATES, refreshed.workflow_node
            assert refreshed.workflow_status == WORKFLOW_STATUS_FAILED, refreshed.workflow_status
            assert row.task_run_id == visual_run.id, row.task_run_id
            assert row.visual_task_run_id == visual_run.id, row.visual_task_run_id
            assert row.visual_task_step_id == visual_step.id, row.visual_task_step_id
            assert row.visual_selected_for_capture == 1, row.visual_selected_for_capture
            _assert_stale_detail_and_final_cleared(row)
            product_ids.append(product.id)
            run_ids.extend([visual_run.id, capture_run.id])
    return product_ids, run_ids


async def _test_success_hook_all_failed_rolls_back_current_facts() -> tuple[int, list[int]]:
    async with async_session() as session:
        product = await _make_product(session, "PHASE2A_TEST_HOOK_FAILURE")
        visual_run, visual_step = await _make_run(
            session,
            product_id=product.id,
            task_type="product_competitor_visual_match",
            suffix="hook_failure_visual",
            status=RUN_STATUS_SUCCEEDED,
        )
        capture_run, capture_step = await _make_run(
            session,
            product_id=product.id,
            task_type="product_competitor_candidate_capture",
            suffix="hook_failure_capture",
            status=RUN_STATUS_RUNNING,
        )
        first = await _make_candidate(
            session,
            product_id=product.id,
            asin="B0HOOKPH2A1",
            search_run_id=visual_run.id,
            search_step_id=visual_step.id,
            visual_run_id=visual_run.id,
            visual_step_id=visual_step.id,
            visual_rank=1,
        )
        second = await _make_candidate(
            session,
            product_id=product.id,
            asin="B0HOOKPH2A2",
            search_run_id=visual_run.id,
            search_step_id=visual_step.id,
            visual_run_id=visual_run.id,
            visual_step_id=visual_step.id,
            visual_rank=2,
        )
        await session.commit()

        action = product_actions.ProductCompetitorCandidateCaptureAction()
        result = {
            "product_id": product.id,
            "visual_task_run_id": visual_run.id,
            "visual_task_step_id": visual_step.id,
            "candidate_results": [
                {"candidate_id": first.id, "asin": first.asin, "visual_rank": 1, "status": "failed", "error_message": "fixture failure", "raw": {}},
                {"candidate_id": second.id, "asin": second.asin, "visual_rank": 2, "status": "failed", "error_message": "fixture failure", "raw": {}},
            ],
            "success_count": 0,
        }
        try:
            await action.on_step_success(session, capture_step, result)
        except RuntimeError as exc:
            assert "没有任何合格成功结果" in str(exc), str(exc)
        else:
            raise AssertionError("all failed success hook result must fail")

        refreshed = (await session.execute(select(Product).where(Product.id == product.id))).scalar_one()
        rows = (
            await session.execute(
                select(AmazonCompetitorSearchCandidate)
                .where(AmazonCompetitorSearchCandidate.product_id == product.id)
            )
        ).scalars().all()
        assert refreshed.workflow_node == WORKFLOW_NODE_CAPTURE_COMPETITOR_CANDIDATES, refreshed.workflow_node
        assert refreshed.workflow_status == WORKFLOW_STATUS_FAILED, refreshed.workflow_status
        assert all(row.capture_status is None for row in rows), [row.capture_status for row in rows]
        assert all(row.detail_task_run_id is None for row in rows), [row.detail_task_run_id for row in rows]
        return product.id, [visual_run.id, capture_run.id]


async def main() -> None:
    await run_schema_maintenance()
    product_ids: list[int] = []
    run_ids: list[int] = []
    try:
        product_id, ids = await _test_partial_success_current_set()
        product_ids.append(product_id)
        run_ids.extend(ids)
        product_id, ids = await _test_full_failure_leaves_no_current_facts()
        product_ids.append(product_id)
        run_ids.extend(ids)
        product_id, ids = await _test_same_asin_reused_row_clears_old_detail_and_final()
        product_ids.append(product_id)
        run_ids.extend(ids)
        product_id, ids = await _test_result_ids_mismatch_clears_current_facts()
        product_ids.append(product_id)
        run_ids.extend(ids)
        ids_product, ids_run = await _test_cancel_and_interrupted_clear_current_facts()
        product_ids.extend(ids_product)
        run_ids.extend(ids_run)
        product_id, ids = await _test_success_hook_all_failed_rolls_back_current_facts()
        product_ids.append(product_id)
        run_ids.extend(ids)
    finally:
        if product_ids or run_ids:
            await _cleanup(product_ids, run_ids)


if __name__ == "__main__":
    asyncio.run(main())
