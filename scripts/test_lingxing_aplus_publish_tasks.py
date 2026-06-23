from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path
import sys
import tempfile

from PIL import Image
from sqlalchemy import delete, func, select
from sqlalchemy.orm import selectinload

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.database import async_session, run_schema_maintenance  # noqa: E402
from app.aplus_publish.module_registry import (  # noqa: E402
    APLUS_PUBLISH_PROFILE_STANDARD_HEADER_IMAGE_TEXT_V1,
    LINGXING_STANDARD_HEADER_IMAGE_TEXT,
)
from app.models import (  # noqa: E402
    AplusUploadBatch,
    AplusUploadItem,
    CatalogProduct,
    Product,
    ProductAplus,
    ProductData,
    TaskGroup,
    TaskRun,
    TaskStep,
    TaskStepEvent,
)
from app.services.lingxing_aplus_publish_client import (  # noqa: E402
    LingxingAplusDraftSaveClientError,
    LingxingAplusDraftSaveRequest,
    LingxingAplusDraftSaveResult,
)
from app.task_planners.lingxing_aplus_publish import create_lingxing_aplus_publish_runs  # noqa: E402
from app.task_runtime import lingxing_aplus_publish_workers as worker_mod  # noqa: E402
from app.task_runtime import scheduler  # noqa: E402
from app.task_runtime.constants import (  # noqa: E402
    RUN_STATUS_FAILED,
    RUN_STATUS_SUCCEEDED,
    STEP_STATUS_FAILED,
    STEP_STATUS_READY,
    STEP_STATUS_SUCCEEDED,
)
from app.task_runtime.registry import TaskContext  # noqa: E402


TEST_PREFIX = "T3_LINGXING_APLUS_PUBLISH_"
CREATED_BY = "lingxing-aplus-t3-test"


class FakeDraftSaveClient:
    calls: list[LingxingAplusDraftSaveRequest] = []
    fail_code: str | None = None
    auth_required: bool = False

    async def save_draft(self, request: LingxingAplusDraftSaveRequest) -> LingxingAplusDraftSaveResult:
        self.calls.append(request)
        if self.fail_code:
            raise LingxingAplusDraftSaveClientError(
                self.fail_code,
                f"fake failure: {self.fail_code}",
                auth_required=self.auth_required,
            )
        return LingxingAplusDraftSaveResult(
            id_hash=f"FAKE-IDHASH-{request.seller_sku}",
            status_text="草稿",
            evidence={
                "endpoint_family": "lingxing_aplus_add",
                "idHash": f"FAKE-IDHASH-{request.seller_sku}",
                "submitFlag": 0,
                "request_module_count": len(request.module_mapping.modules),
            },
        )


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _make_image(path: Path, size: tuple[int, int] = (970, 600)) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, "white").save(path, format="JPEG")
    return str(path)


async def _cleanup() -> None:
    async with async_session() as session:
        product_ids = list(
            (
                await session.execute(select(Product.id).where(Product.gigab2b_product_id.like(f"{TEST_PREFIX}%")))
            ).scalars().all()
        )
        run_ids = list(
            (
                await session.execute(
                    select(TaskRun.id).where(
                        (TaskRun.created_by == CREATED_BY) | (TaskRun.dedupe_key.like("lingxing_aplus_publish:%"))
                    )
                )
            ).scalars().all()
        )
        if run_ids:
            await session.execute(delete(TaskStepEvent).where(TaskStepEvent.task_run_id.in_(run_ids)))
            await session.execute(delete(TaskStep).where(TaskStep.task_run_id.in_(run_ids)))
            await session.execute(delete(TaskGroup).where(TaskGroup.task_run_id.in_(run_ids)))
            await session.execute(delete(TaskRun).where(TaskRun.id.in_(run_ids)))
        if product_ids:
            batch_ids = list(
                (
                    await session.execute(
                        select(AplusUploadItem.batch_id).where(AplusUploadItem.product_id.in_(product_ids))
                    )
                ).scalars().all()
            )
            await session.execute(delete(AplusUploadItem).where(AplusUploadItem.product_id.in_(product_ids)))
            if batch_ids:
                await session.execute(delete(AplusUploadBatch).where(AplusUploadBatch.id.in_(batch_ids)))
            await session.execute(delete(AplusUploadBatch).where(AplusUploadBatch.store == CREATED_BY))
            await session.execute(delete(CatalogProduct).where(CatalogProduct.source_product_id.in_(product_ids)))
            await session.execute(delete(ProductAplus).where(ProductAplus.product_id.in_(product_ids)))
            await session.execute(delete(ProductData).where(ProductData.product_id.in_(product_ids)))
            await session.execute(delete(Product).where(Product.id.in_(product_ids)))
        await session.commit()


async def _make_product(
    session,
    tmp: Path,
    marker: str,
    *,
    asin: str | None = "B0T3DRAFT1",
    seller_sku: str | None = None,
    aplus_status: str | None = "done",
    upload_status: str | None = "ready_to_upload",
    existing_id_hash: str | None = None,
    legacy_plan: bool = False,
) -> CatalogProduct:
    now = datetime.now()
    sku = seller_sku or f"T3-SKU-{marker}"
    product = Product(
        gigab2b_url=f"https://t3.example/{marker}",
        gigab2b_product_id=f"{TEST_PREFIX}{marker}",
        amazon_asin=asin,
        amazon_seller_sku=sku,
        asin_sync_status="synced" if asin else "waiting_listing",
        aplus_upload_status=upload_status or "not_uploaded",
        status="completed",
        current_step=6,
        created_at=now,
        updated_at=now,
    )
    product.data = ProductData(item_code=sku, title=f"T3 fixture {marker}", listing_title=f"T3 fixture {marker}")
    if legacy_plan:
        modules = [{"position": index, "headline": f"Module {index}", "key_message": f"Key message {index}"} for index in range(1, 6)]
    else:
        modules = [
            {
                "position": index,
                "type": "standard_header_image_text",
                "semantic_role": ["hero", "lifestyle", "feature_proof", "spec_objection", "closing"][index - 1],
                "publish_profile": APLUS_PUBLISH_PROFILE_STANDARD_HEADER_IMAGE_TEXT_V1,
                "lingxing_content_module_type": LINGXING_STANDARD_HEADER_IMAGE_TEXT,
                "headline": f"Module {index}",
                "subheading": f"Subtitle {index}",
                "key_message": f"Key message {index}",
                "text_content": f"Body text {index}",
            }
            for index in range(1, 6)
        ]
    images = [
        {"status": "done", "path": _make_image(tmp / marker / f"aplus_{index:02d}.jpg"), "position": index}
        for index in range(1, 6)
    ]
    product.aplus = ProductAplus(
        aplus_status=aplus_status,
        aplus_plan=json.dumps({"modules": modules}, ensure_ascii=False),
        aplus_images=json.dumps(images, ensure_ascii=False),
        aplus_image_count=5,
    )
    product.catalog_item = CatalogProduct(
        gigab2b_url=product.gigab2b_url,
        gigab2b_product_id=product.gigab2b_product_id,
        amazon_asin=asin,
        amazon_seller_sku=sku,
        asin_sync_status=product.asin_sync_status,
        aplus_upload_status=upload_status or "not_uploaded",
        item_code=sku,
        title=f"T3 fixture {marker}",
        status="completed",
        confirmed_at=now,
        exported_at=now,
    )
    session.add(product)
    await session.flush()
    if existing_id_hash:
        batch = AplusUploadBatch(store=CREATED_BY, submit_for_approval=0, status="completed", total_count=1, success_count=1)
        session.add(batch)
        await session.flush()
        session.add(
            AplusUploadItem(
                batch_id=batch.id,
                catalog_product_id=product.catalog_item.id,
                product_id=product.id,
                product_aplus_id=product.aplus.id,
                amazon_asin=asin,
                item_code=sku,
                document_name=f"{asin}_{sku}_{product.id}",
                status="success",
                lingxing_aplus_id_hash=existing_id_hash,
                amazon_draft_visibility="unconfirmed",
                publish_evidence_json=json.dumps({"idHash": existing_id_hash}, ensure_ascii=False),
            )
        )
    await session.flush()
    return product.catalog_item


async def _create_and_run(catalog: CatalogProduct) -> dict:
    async with async_session() as session:
        runs, errors = await create_lingxing_aplus_publish_runs(
            session,
            [catalog.id],
            store_id="17983",
            site="US",
            created_by=CREATED_BY,
            auto_start=False,
        )
        assert_true(not errors, f"planner returned errors: {errors}")
        assert_true(len(runs) == 1, "planner should create one run")
        step = (
            await session.execute(
                select(TaskStep)
                .where(TaskStep.task_run_id == runs[0].id)
                .options(selectinload(TaskStep.task_group), selectinload(TaskStep.task_run))
            )
        ).scalar_one()
        result = await worker_mod.lingxing_aplus_publish_product(
            TaskContext(db=session, run=step.task_run, group=step.task_group, step=step)
        )
        await session.commit()
        return result


async def _create_ready_run(catalog: CatalogProduct) -> tuple[int, int]:
    async with async_session() as session:
        runs, errors = await create_lingxing_aplus_publish_runs(
            session,
            [catalog.id],
            store_id="17983",
            site="US",
            created_by=CREATED_BY,
            auto_start=False,
        )
        assert_true(not errors, f"planner returned errors: {errors}")
        assert_true(len(runs) == 1, "planner should create one run")
        step = (
            await session.execute(select(TaskStep).where(TaskStep.task_run_id == runs[0].id))
        ).scalar_one()
        step.status = STEP_STATUS_READY
        await session.commit()
        return int(runs[0].id), int(step.id)


async def _reload_run_step(run_id: int, step_id: int) -> tuple[TaskRun, TaskStep]:
    async with async_session() as session:
        run = (await session.execute(select(TaskRun).where(TaskRun.id == run_id))).scalar_one()
        step = (await session.execute(select(TaskStep).where(TaskStep.id == step_id))).scalar_one()
        return run, step


async def _count_draft_items(catalog_id: int) -> int:
    async with async_session() as session:
        return (
            await session.execute(select(func.count(AplusUploadItem.id)).where(AplusUploadItem.catalog_product_id == catalog_id))
        ).scalar_one()


async def _reload_catalog(catalog_id: int) -> CatalogProduct:
    async with async_session() as session:
        return (
            await session.execute(
                select(CatalogProduct)
                .where(CatalogProduct.id == catalog_id)
                .options(selectinload(CatalogProduct.source_product))
            )
        ).scalar_one()


async def test_save_success_writes_draft_saved_only(tmp: Path) -> None:
    async with async_session() as session:
        catalog = await _make_product(session, tmp, "SUCCESS")
        await session.commit()
    result = await _create_and_run(catalog)
    refreshed = await _reload_catalog(catalog.id)
    assert_true(result["status"] == "draft_saved", "worker success should return draft_saved")
    assert_true(refreshed.aplus_upload_status == "draft_saved", "Catalog status should be draft_saved")
    assert_true(refreshed.source_product.aplus_upload_status == "draft_saved", "Product mirror should be draft_saved")
    async with async_session() as session:
        item = (
            await session.execute(select(AplusUploadItem).where(AplusUploadItem.catalog_product_id == catalog.id))
        ).scalar_one()
        evidence = json.loads(item.publish_evidence_json or "{}")
        assert_true(item.lingxing_aplus_id_hash == "FAKE-IDHASH-T3-SKU-SUCCESS", "item should store idHash")
        assert_true(item.amazon_draft_visibility == "unconfirmed", "T3 must leave Amazon draft visibility unconfirmed")
        assert_true(item.status == "success", "item status may record local draft save success only")
        assert_true(evidence.get("submitFlag") == 0, "draft save evidence must prove submitFlag stayed false")
        assert_true("draft_visible" not in (item.publish_evidence_json or ""), "T3 evidence must not claim draft_visible")
        assert_true(item.submitted_at is None and item.draft_visible_at is None, "T3 must not write submit/visible timestamps")


async def test_prereq_failures_are_structured(tmp: Path) -> None:
    async with async_session() as session:
        missing_asin = await _make_product(session, tmp, "WAITING", asin=None, upload_status="not_uploaded")
        not_done = await _make_product(session, tmp, "NOT_DONE", aplus_status="failed", upload_status="not_uploaded")
        await session.commit()

    wait_result = await _create_and_run(missing_asin)
    wait_catalog = await _reload_catalog(missing_asin.id)
    assert_true(wait_result["status"] == "waiting_listing" and wait_result["reason_code"] == "asin_not_aligned", "missing ASIN should return waiting_listing")
    assert_true(wait_catalog.aplus_upload_status == "waiting_listing", "missing ASIN should write waiting_listing")

    skipped_result = await _create_and_run(not_done)
    skipped_catalog = await _reload_catalog(not_done.id)
    assert_true(skipped_result["status"] == "skipped" and skipped_result["reason_code"] == "product_aplus_not_done", "A+ not done should be skipped")
    assert_true(skipped_catalog.aplus_upload_status == "skipped", "A+ not done should write skipped")


async def test_module_mapping_failure_does_not_call_client(tmp: Path) -> None:
    async with async_session() as session:
        legacy = await _make_product(session, tmp, "LEGACY_PLAN", legacy_plan=True, upload_status="not_uploaded")
        await session.commit()

    calls_before = len(FakeDraftSaveClient.calls)
    result = await _create_and_run(legacy)
    refreshed = await _reload_catalog(legacy.id)
    assert_true(result["status"] == "failed", "legacy plan should fail locally")
    assert_true(result["reason_code"] == "unsupported_aplus_publish_profile", "legacy plan missing profile should return typed mapper reason")
    assert_true(refreshed.aplus_upload_status == "failed", "mapping failure should write domain failed")
    assert_true(len(FakeDraftSaveClient.calls) == calls_before, "mapping failure must not call Lingxing client/auth/upload/add")
    assert_true(await _count_draft_items(legacy.id) == 0, "mapping failure must not create draft item evidence")


async def test_external_failures_mark_runtime_failed_and_retryable(tmp: Path) -> None:
    async with async_session() as session:
        auth = await _make_product(session, tmp, "AUTH")
        api_failed = await _make_product(session, tmp, "API_FAIL")
        retry_failed = await _make_product(session, tmp, "RETRY_FAIL")
        await session.commit()

    FakeDraftSaveClient.fail_code = "auth_required"
    FakeDraftSaveClient.auth_required = True
    auth_run_id, auth_step_id = await _create_ready_run(auth)
    await scheduler.drain_ready_steps()
    auth_run, auth_step = await _reload_run_step(auth_run_id, auth_step_id)
    auth_catalog = await _reload_catalog(auth.id)
    auth_payload = json.loads(auth_step.result_json or "{}")
    assert_true(auth_run.status == RUN_STATUS_FAILED, "auth failure must make TaskRun failed for retry")
    assert_true(auth_step.status == STEP_STATUS_FAILED, "auth failure must make TaskStep failed for retry")
    assert_true(auth_step.attempt_count == 1 and auth_step.max_attempts == 2, "auth failure should remain retryable")
    assert_true(auth_payload.get("status") == "auth_required" and auth_payload.get("reason_code") == "auth_required", "auth failure result evidence should stay typed")
    assert_true("LingxingAplusDraftSaveClientError" in (auth_step.error_message or ""), "auth failure must be raised to runtime")
    assert_true(auth_catalog.aplus_upload_status == "auth_required", "auth failure should write auth_required")

    FakeDraftSaveClient.fail_code = "api_failed"
    FakeDraftSaveClient.auth_required = False
    api_run_id, api_step_id = await _create_ready_run(api_failed)
    await scheduler.drain_ready_steps()
    api_run, api_step = await _reload_run_step(api_run_id, api_step_id)
    api_catalog = await _reload_catalog(api_failed.id)
    api_payload = json.loads(api_step.result_json or "{}")
    assert_true(api_run.status == RUN_STATUS_FAILED, "api_failed must make TaskRun failed for retry")
    assert_true(api_step.status == STEP_STATUS_FAILED, "api_failed must make TaskStep failed for retry")
    assert_true(api_payload.get("status") == "failed" and api_payload.get("reason_code") == "api_failed", "api_failed result evidence should stay typed")
    assert_true(api_catalog.aplus_upload_status == "failed", "api_failed should write domain failed")

    FakeDraftSaveClient.fail_code = "request_failed"
    retry_run_id, retry_step_id = await _create_ready_run(retry_failed)
    await scheduler.drain_ready_steps()
    retry_run, retry_step = await _reload_run_step(retry_run_id, retry_step_id)
    retry_catalog = await _reload_catalog(retry_failed.id)
    retry_payload = json.loads(retry_step.result_json or "{}")
    assert_true(retry_run.status == RUN_STATUS_FAILED, "request_failed must make TaskRun failed for retry")
    assert_true(retry_step.status == STEP_STATUS_FAILED, "request_failed must make TaskStep failed for retry")
    assert_true(retry_payload.get("status") == "failed" and retry_payload.get("reason_code") == "request_failed", "save failure should be typed failed")
    assert_true(retry_catalog.aplus_upload_status == "failed", "save failure should write failed")
    assert_true(await _count_draft_items(retry_failed.id) == 0, "failed external save must not create draft item evidence")

    await scheduler.retry_step(retry_step_id, auto_start=False)
    FakeDraftSaveClient.fail_code = None
    await scheduler.drain_ready_steps()
    retry_run, retry_step = await _reload_run_step(retry_run_id, retry_step_id)
    retry_catalog = await _reload_catalog(retry_failed.id)
    assert_true(retry_run.status == RUN_STATUS_SUCCEEDED, "runtime retry should complete the same TaskRun")
    assert_true(retry_step.status == STEP_STATUS_SUCCEEDED, "runtime retry should complete the same TaskStep")
    assert_true(retry_step.attempt_count == 2, "retry should reuse the same failed step attempt lineage")
    assert_true(retry_catalog.aplus_upload_status == "draft_saved", "successful retry should write draft_saved")
    assert_true(await _count_draft_items(retry_failed.id) == 1, "retry success should create exactly one draft item/idHash")
    assert_true(
        sum(1 for call in FakeDraftSaveClient.calls if call.seller_sku == "T3-SKU-RETRY_FAIL") == 2,
        "request_failed retry should use runtime retry path, not create a second draft record",
    )


async def test_duplicate_trigger_reuses_active_and_stops_after_draft_saved(tmp: Path) -> None:
    async with async_session() as session:
        active = await _make_product(session, tmp, "ACTIVE")
        already = await _make_product(
            session,
            tmp,
            "ALREADY",
            upload_status="draft_saved",
            existing_id_hash="EXISTING-IDHASH",
        )
        await session.commit()

    async with async_session() as session:
        first, first_errors = await create_lingxing_aplus_publish_runs(
            session,
            [active.id],
            store_id="17983",
            site="US",
            created_by=CREATED_BY,
            auto_start=False,
        )
        second, second_errors = await create_lingxing_aplus_publish_runs(
            session,
            [active.id],
            store_id="17983",
            site="US",
            created_by=CREATED_BY,
            auto_start=False,
        )
        assert_true(not first_errors and not second_errors, "active duplicate should not be an error")
        assert_true(first[0].id == second[0].id, "duplicate trigger must reuse active task")
        count = (
            await session.execute(select(func.count(TaskRun.id)).where(TaskRun.dedupe_key == first[0].dedupe_key))
        ).scalar_one()
        assert_true(count == 1, "duplicate trigger must not create a second active run")

    async with async_session() as session:
        protected_runs, protected_errors = await create_lingxing_aplus_publish_runs(
            session,
            [already.id],
            store_id="17983",
            site="US",
            created_by=CREATED_BY,
            auto_start=False,
        )
        assert_true(not protected_runs, "already draft_saved/idHash should stop before creating a publish run")
        assert_true(any("draft_saved" in error for error in protected_errors), "protected stop should explain draft_saved")


async def main() -> None:
    await run_schema_maintenance()
    await _cleanup()
    worker_mod.register_lingxing_aplus_publish_workers()
    original_factory = worker_mod.draft_save_client_factory
    worker_mod.draft_save_client_factory = FakeDraftSaveClient
    try:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            await test_save_success_writes_draft_saved_only(tmp)
            await test_prereq_failures_are_structured(tmp)
            await test_module_mapping_failure_does_not_call_client(tmp)
            await test_external_failures_mark_runtime_failed_and_retryable(tmp)
            await test_duplicate_trigger_reuses_active_and_stops_after_draft_saved(tmp)
    finally:
        worker_mod.draft_save_client_factory = original_factory
        FakeDraftSaveClient.calls.clear()
        FakeDraftSaveClient.fail_code = None
        FakeDraftSaveClient.auth_required = False
        await _cleanup()


if __name__ == "__main__":
    asyncio.run(main())
