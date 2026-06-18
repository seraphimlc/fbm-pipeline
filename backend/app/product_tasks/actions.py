from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import CatalogProduct, Product, TaskGroup, TaskRun, TaskStep
from app.models.status import (
    COMPLETED,
    FAILED,
    PAUSED,
    STEP5_LISTING,
    STEP6_CURATING,
    STEP6_DONE,
    WORKFLOW_NODE_FLOW_DONE,
    WORKFLOW_NODE_IMAGE_ANALYSIS,
    WORKFLOW_NODE_LISTING_GENERATION,
    WORKFLOW_STATUS_FAILED,
    WORKFLOW_STATUS_PROCESSING,
    WORKFLOW_STATUS_SUCCEEDED,
)
from app.pipeline.engine import _assert_step_prerequisites
from app.pipeline.step5_listing import run_listing
from app.pipeline.step6_image import run_image_analysis
from app.product_tasks.workflow import set_product_workflow
from app.task_runtime.actions import TaskAction, TaskGroupPlan, TaskRunPlan, TaskStepPlan, action_for, register_action
from app.task_runtime.constants import (
    RUN_STATUS_FAILED,
    RUN_STATUS_INTERRUPTED,
    RUN_STATUS_PENDING,
    RUN_STATUS_RUNNING,
    STEP_STATUS_PENDING,
    STEP_STATUS_READY,
    STEP_STATUS_RUNNING,
)
from app.task_runtime.events import update_step_progress
from app.task_runtime.exceptions import TaskStepCanceled, TaskStepInterrupted
from app.task_runtime.json_utils import json_dumps, json_loads
from app.task_runtime.registry import TaskContext, register_worker
from app.task_runtime.scheduler import kick_task_runtime


ACTIVE_RUN_STATUSES = (RUN_STATUS_PENDING, RUN_STATUS_RUNNING)
ACTIVE_STEP_STATUSES = (STEP_STATUS_PENDING, STEP_STATUS_READY, STEP_STATUS_RUNNING)
logger = logging.getLogger(__name__)

PRODUCT_ACTION_TYPES = {"product_image_analysis", "product_listing_generation"}


def _payload_for_step(step: TaskStep) -> dict[str, Any]:
    value = json_loads(step.payload_json, {})
    return value if isinstance(value, dict) else {}


def _payload_for_run(run: TaskRun) -> dict[str, Any]:
    value = json_loads(run.payload_json, {})
    return value if isinstance(value, dict) else {}


def _legacy_dedupe_key(task_type: str, product_id: int) -> str | None:
    if task_type == "product_image_analysis":
        return f"product_image_analysis:product:{product_id}"
    if task_type == "product_listing_generation":
        return f"product_listing_generation:product:{product_id}"
    return None


def _legacy_correlation_key(task_type: str, product_id: int) -> str | None:
    if task_type == "product_image_analysis":
        return f"product:{product_id}:image_analysis"
    if task_type == "product_listing_generation":
        return f"product:{product_id}:listing_generation"
    return None


def _legacy_payload_product_id(run: TaskRun) -> int | None:
    value = _payload_for_run(run).get("product_id")
    if value is not None and str(value).isdigit():
        product_id = int(value)
        return product_id if product_id > 0 else None
    return None


async def _load_product(db: AsyncSession, product_id: int) -> Product:
    result = await db.execute(
        select(Product)
        .where(Product.id == product_id)
        .options(selectinload(Product.data), selectinload(Product.images), selectinload(Product.catalog_item))
    )
    product = result.scalar_one_or_none()
    if not product:
        raise RuntimeError(f"商品不存在: {product_id}")
    return product


def _product_id(payload: dict[str, Any]) -> int:
    product_id = int(payload.get("product_id") or 0)
    if product_id <= 0:
        raise ValueError("商品任务缺少 product_id")
    return product_id


def _sync_catalog_item(product: Product) -> None:
    if product.catalog_item:
        product.catalog_item.status = product.status
        product.catalog_item.updated_at = product.updated_at


def _workflow_node_for_step(step: int) -> str:
    return WORKFLOW_NODE_IMAGE_ANALYSIS if step == 5 else WORKFLOW_NODE_LISTING_GENERATION


async def _project_product_failure(
    db: AsyncSession,
    *,
    product_id: int,
    step: int,
    label: str,
    error: Exception | str,
) -> None:
    try:
        product = await _load_product(db, product_id)
    except RuntimeError:
        return
    now = datetime.now()
    product.status = FAILED
    product.current_step = step
    product.error_message = f"{label}失败: {type(error).__name__}: {error}" if isinstance(error, Exception) else str(error)
    set_product_workflow(
        product,
        node=_workflow_node_for_step(step),
        status=WORKFLOW_STATUS_FAILED,
        error=product.error_message,
        now=now,
    )
    product.updated_at = now
    _sync_catalog_item(product)
    await db.commit()


async def _project_product_paused(
    db: AsyncSession,
    *,
    product_id: int,
    step: int,
    message: str,
) -> None:
    try:
        product = await _load_product(db, product_id)
    except RuntimeError:
        return
    now = datetime.now()
    product.status = PAUSED
    product.current_step = step
    product.error_message = message
    set_product_workflow(
        product,
        node=_workflow_node_for_step(step),
        status=WORKFLOW_STATUS_FAILED,
        error=message,
        now=now,
    )
    product.updated_at = now
    _sync_catalog_item(product)


async def _best_effort_update_step_progress(
    db: AsyncSession,
    step: TaskStep,
    *,
    current: int,
    total: int,
    message: str,
    data: dict[str, Any],
) -> None:
    try:
        await update_step_progress(
            db,
            step,
            current=current,
            total=total,
            message=message,
            data=data,
        )
    except Exception:
        await db.rollback()
        logger.exception(
            "Product action success projection completed, but final progress event failed: step_id=%s",
            step.id,
        )


def _project_listing_completed(product: Product) -> None:
    now = datetime.now()
    product.status = COMPLETED
    product.current_step = 6
    product.error_message = None
    set_product_workflow(
        product,
        node=WORKFLOW_NODE_FLOW_DONE,
        status=WORKFLOW_STATUS_SUCCEEDED,
        error=None,
        now=now,
    )
    product.updated_at = now

    pd = product.data
    item = product.catalog_item
    if not item:
        item = CatalogProduct(source_product_id=product.id, gigab2b_url=product.gigab2b_url)
        product.catalog_item = item

    item.gigab2b_url = product.gigab2b_url
    item.gigab2b_product_id = product.gigab2b_product_id
    item.competitor_asin = product.competitor_asin
    item.amazon_asin = product.amazon_asin
    item.asin_sync_status = product.asin_sync_status
    item.asin_synced_at = product.asin_synced_at
    item.asin_sync_error = product.asin_sync_error
    item.amazon_product_status = product.amazon_product_status
    item.amazon_product_status_synced_at = product.amazon_product_status_synced_at
    item.amazon_product_status_error = product.amazon_product_status_error
    item.aplus_upload_status = product.aplus_upload_status
    item.aplus_uploaded_at = product.aplus_uploaded_at
    item.aplus_upload_error = product.aplus_upload_error
    item.upc = product.upc
    item.brand = product.brand
    item.item_code = pd.item_code if pd else None
    item.title = pd.title if pd else None
    item.leaf_category = pd.leaf_category if pd else None
    item.status = product.status
    item.confirmed_at = item.confirmed_at or now
    item.updated_at = now


class ProductImageAnalysisAction:
    action_type = "product_image_analysis"

    async def validate(self, db: AsyncSession, payload: dict[str, Any]) -> None:
        product_id = _product_id(payload)
        await _load_product(db, product_id)
        await _assert_step_prerequisites(product_id, 5)

    def dedupe_key(self, payload: dict[str, Any]) -> str | None:
        return f"product_image_analysis:product:{_product_id(payload)}"

    def correlation_key(self, payload: dict[str, Any]) -> str | None:
        return f"product:{_product_id(payload)}:image_analysis"

    async def reserve(self, db: AsyncSession, payload: dict[str, Any], run: TaskRun) -> None:
        product = await _load_product(db, _product_id(payload))
        now = datetime.now()
        product.status = STEP6_CURATING
        product.current_step = 5
        product.error_message = "图片分析已加入任务中心队列"
        set_product_workflow(
            product,
            node=WORKFLOW_NODE_IMAGE_ANALYSIS,
            status=WORKFLOW_STATUS_PROCESSING,
            error=product.error_message,
            now=now,
        )
        product.updated_at = now
        _sync_catalog_item(product)

    def build_plan(self, payload: dict[str, Any]) -> TaskRunPlan:
        product_id = _product_id(payload)
        return TaskRunPlan(
            task_type=self.action_type,
            title=f"图片分析：商品 #{product_id}",
            payload={"product_id": product_id},
            groups=[
                TaskGroupPlan(
                    group_key="image_analysis",
                    title="图片分析",
                    steps=[
                        TaskStepPlan(
                            step_key=f"product:{product_id}:image_analysis",
                            step_type=self.action_type,
                            payload={"product_id": product_id},
                            max_attempts=2,
                        )
                    ],
                )
            ],
        )

    async def execute_step(self, db: AsyncSession, step: TaskStep, payload: dict[str, Any]) -> dict[str, Any]:
        product_id = _product_id(payload)
        product = await _load_product(db, product_id)
        item_code = product.data.item_code if product.data else product.gigab2b_product_id
        await update_step_progress(
            db,
            step,
            current=0,
            total=1,
            message="开始图片分析",
            data={"product_id": product_id, "item_code": item_code},
        )
        return {
            "product_id": product_id,
            "item_code": item_code,
            "image_analysis": await run_image_analysis(product_id),
        }

    async def on_step_success(self, db: AsyncSession, step: TaskStep, result: dict[str, Any]) -> None:
        product_id = int(result.get("product_id") or _payload_for_step(step).get("product_id") or 0)
        try:
            product = await _load_product(db, product_id)
        except RuntimeError:
            return
        now = datetime.now()
        product.status = STEP6_DONE
        product.current_step = 5
        product.error_message = None
        set_product_workflow(
            product,
            node=WORKFLOW_NODE_IMAGE_ANALYSIS,
            status=WORKFLOW_STATUS_SUCCEEDED,
            error=None,
            now=now,
        )
        product.updated_at = now
        _sync_catalog_item(product)
        listing_runs = await create_product_action_runs(
            db,
            self._listing_action_type(),
            [{"product_id": product_id, "created_by": "product_image_analysis"}],
            created_by="product_image_analysis",
        )
        listing_run_ids = [run.id for run in listing_runs]
        step.task_run.summary_json = json_dumps({
            "product_id": product_id,
            "item_code": result.get("item_code"),
            "status": "image_analysis_done",
            "next_step": 6,
            "listing_task_run_ids": listing_run_ids,
        })
        await db.commit()
        await _best_effort_update_step_progress(
            db,
            step,
            current=1,
            total=1,
            message="图片分析完成，已提交 Listing 生成",
            data={"product_id": product_id, "item_code": result.get("item_code"), "listing_task_run_ids": listing_run_ids},
        )
        result["status"] = "done"
        result["next_step"] = 6
        result["listing_task_run_ids"] = listing_run_ids

    async def on_step_failure(self, db: AsyncSession, step: TaskStep, error: Exception) -> None:
        product_id = int(_payload_for_step(step).get("product_id") or 0)
        if product_id <= 0:
            return
        await _project_product_failure(db, product_id=product_id, step=5, label="图片分析", error=error)

    async def on_step_interrupted(self, db: AsyncSession, step: TaskStep, reason: str | None = None) -> None:
        product_id = int(_payload_for_step(step).get("product_id") or 0)
        if product_id <= 0:
            return
        await _project_product_paused(
            db,
            product_id=product_id,
            step=5,
            message=f"图片分析任务已中断: {reason or '服务重启或执行锁超时'}",
        )

    async def on_cancel_requested(self, db: AsyncSession, run: TaskRun, reason: str | None = None) -> None:
        product_id = int(_payload_for_run(run).get("product_id") or 0)
        if product_id <= 0:
            return
        await _project_product_paused(
            db,
            product_id=product_id,
            step=5,
            message=f"图片分析任务已取消: {reason or '用户取消'}",
        )

    @staticmethod
    def _listing_action_type() -> str:
        return "product_listing_generation"


class ProductListingGenerationAction:
    action_type = "product_listing_generation"

    async def validate(self, db: AsyncSession, payload: dict[str, Any]) -> None:
        product_id = _product_id(payload)
        await _load_product(db, product_id)
        await _assert_step_prerequisites(product_id, 6)

    def dedupe_key(self, payload: dict[str, Any]) -> str | None:
        return f"product_listing_generation:product:{_product_id(payload)}"

    def correlation_key(self, payload: dict[str, Any]) -> str | None:
        return f"product:{_product_id(payload)}:listing_generation"

    async def reserve(self, db: AsyncSession, payload: dict[str, Any], run: TaskRun) -> None:
        product = await _load_product(db, _product_id(payload))
        now = datetime.now()
        product.status = STEP5_LISTING
        product.current_step = 6
        product.error_message = "Listing 生成已加入任务中心队列"
        set_product_workflow(
            product,
            node=WORKFLOW_NODE_LISTING_GENERATION,
            status=WORKFLOW_STATUS_PROCESSING,
            error=product.error_message,
            now=now,
        )
        product.updated_at = now
        _sync_catalog_item(product)
        if product.catalog_item:
            product.catalog_item.confirmed_at = None

    def build_plan(self, payload: dict[str, Any]) -> TaskRunPlan:
        product_id = _product_id(payload)
        item_code = payload.get("item_code")
        return TaskRunPlan(
            task_type=self.action_type,
            title=f"Listing 生成：{item_code or f'商品 #{product_id}'}",
            payload={"product_id": product_id, "item_code": item_code},
            groups=[
                TaskGroupPlan(
                    group_key="listing",
                    title="Listing 生成",
                    steps=[
                        TaskStepPlan(
                            step_key=f"product:{product_id}:listing",
                            step_type=self.action_type,
                            payload={"product_id": product_id, "item_code": item_code},
                            max_attempts=2,
                        )
                    ],
                )
            ],
        )

    async def execute_step(self, db: AsyncSession, step: TaskStep, payload: dict[str, Any]) -> dict[str, Any]:
        product_id = _product_id(payload)
        product = await _load_product(db, product_id)
        item_code = product.data.item_code if product.data else product.gigab2b_product_id
        await update_step_progress(
            db,
            step,
            current=0,
            total=1,
            message="开始生成 Listing",
            data={"product_id": product_id, "item_code": item_code},
        )
        return {
            "product_id": product_id,
            "item_code": item_code,
            "listing": await run_listing(product_id),
        }

    async def on_step_success(self, db: AsyncSession, step: TaskStep, result: dict[str, Any]) -> None:
        product_id = int(result.get("product_id") or _payload_for_step(step).get("product_id") or 0)
        product = await _load_product(db, product_id)
        _project_listing_completed(product)
        step.task_run.summary_json = json_dumps({
            "product_id": product_id,
            "item_code": result.get("item_code"),
            "status": "listing_done",
            "next_step": "export",
        })
        await db.commit()
        await _best_effort_update_step_progress(
            db,
            step,
            current=1,
            total=1,
            message="Listing 生成完成，已进入待导出",
            data={"product_id": product_id, "item_code": result.get("item_code")},
        )
        result["status"] = "done"
        result["next_step"] = "export"

    async def on_step_failure(self, db: AsyncSession, step: TaskStep, error: Exception) -> None:
        product_id = int(_payload_for_step(step).get("product_id") or 0)
        if product_id <= 0:
            return
        await _project_product_failure(db, product_id=product_id, step=6, label="Listing 生成", error=error)

    async def on_step_interrupted(self, db: AsyncSession, step: TaskStep, reason: str | None = None) -> None:
        product_id = int(_payload_for_step(step).get("product_id") or 0)
        if product_id <= 0:
            return
        await _project_product_paused(
            db,
            product_id=product_id,
            step=6,
            message=f"Listing 生成任务已中断: {reason or '服务重启或执行锁超时'}",
        )

    async def on_cancel_requested(self, db: AsyncSession, run: TaskRun, reason: str | None = None) -> None:
        product_id = int(_payload_for_run(run).get("product_id") or 0)
        if product_id <= 0:
            return
        await _project_product_paused(
            db,
            product_id=product_id,
            step=6,
            message=f"Listing 生成任务已取消: {reason or '用户取消'}",
        )


async def _existing_active_run(db: AsyncSession, action: TaskAction, payload: dict[str, Any]) -> TaskRun | None:
    dedupe_key = action.dedupe_key(payload)
    if dedupe_key:
        result = await db.execute(
            select(TaskRun)
            .where(TaskRun.dedupe_key == dedupe_key)
            .where(TaskRun.status.in_(ACTIVE_RUN_STATUSES))
            .options(selectinload(TaskRun.steps))
            .order_by(TaskRun.id.asc())
        )
        run = result.scalars().first()
        if run:
            return run
    plan = action.build_plan(payload)
    step_keys = [step.step_key for group in plan.groups for step in group.steps]
    if not step_keys:
        return None
    result = await db.execute(
        select(TaskRun)
        .join(TaskStep, TaskStep.task_run_id == TaskRun.id)
        .where(TaskRun.task_type == action.action_type)
        .where(TaskRun.status.in_(ACTIVE_RUN_STATUSES))
        .where(TaskStep.step_key.in_(step_keys))
        .where(TaskStep.status.in_(ACTIVE_STEP_STATUSES))
        .options(selectinload(TaskRun.steps))
        .order_by(TaskRun.id.asc())
    )
    return result.scalars().first()


async def _lock_product_for_action_payload(db: AsyncSession, payload: dict[str, Any]) -> None:
    product_id = int(payload.get("product_id") or 0)
    if product_id <= 0:
        return
    await db.execute(select(Product.id).where(Product.id == product_id).with_for_update())


async def _mark_previous_runs_superseded(db: AsyncSession, run: TaskRun) -> None:
    if not run.correlation_key:
        return
    result = await db.execute(
        select(TaskRun)
        .where(TaskRun.correlation_key == run.correlation_key)
        .where(TaskRun.id != run.id)
        .where(TaskRun.id < run.id)
        .where(TaskRun.status.in_((RUN_STATUS_FAILED, RUN_STATUS_INTERRUPTED)))
        .where(TaskRun.superseded_by_run_id.is_(None))
    )
    now = datetime.now()
    for previous in result.scalars().all():
        previous.superseded_by_run_id = run.id
        previous.superseded_at = now


async def _reload_action_runs_for_response(db: AsyncSession, runs: list[TaskRun]) -> list[TaskRun]:
    loaded_runs: list[TaskRun] = []
    for run in runs:
        result = await db.execute(
            select(TaskRun)
            .where(TaskRun.id == run.id)
            .options(
                selectinload(TaskRun.groups).selectinload(TaskGroup.steps),
                selectinload(TaskRun.steps),
            )
        )
        loaded = result.scalar_one_or_none()
        if loaded:
            loaded_runs.append(loaded)
    return loaded_runs


async def backfill_product_action_task_run_keys(db: AsyncSession) -> int:
    """Backfill ProductTaskAction metadata for pre-action task_runs.

    This is product-domain compatibility, not task-center framework parsing.
    It only updates task_run metadata keys and superseded pointers; product state,
    ASINs, material assets, and generated outputs are untouched.
    """
    result = await db.execute(
        select(TaskRun)
        .where(TaskRun.task_type.in_(PRODUCT_ACTION_TYPES))
        .order_by(TaskRun.id.asc())
    )
    runs = result.scalars().all()
    changed = 0
    now = datetime.now()
    by_correlation: dict[str, list[TaskRun]] = {}
    for run in runs:
        product_id = _legacy_payload_product_id(run)
        if not product_id:
            if run.correlation_key:
                by_correlation.setdefault(run.correlation_key, []).append(run)
            continue
        dedupe_key = _legacy_dedupe_key(run.task_type, product_id)
        correlation_key = _legacy_correlation_key(run.task_type, product_id)
        if dedupe_key and not run.dedupe_key:
            run.dedupe_key = dedupe_key
            changed += 1
        if correlation_key and not run.correlation_key:
            run.correlation_key = correlation_key
            changed += 1
        if run.correlation_key:
            by_correlation.setdefault(run.correlation_key, []).append(run)

    for correlation_runs in by_correlation.values():
        ordered = sorted(correlation_runs, key=lambda item: (item.created_at or datetime.min, item.id))
        for index, run in enumerate(ordered[:-1]):
            if run.status not in {RUN_STATUS_FAILED, RUN_STATUS_INTERRUPTED}:
                continue
            if run.superseded_by_run_id:
                continue
            run.superseded_by_run_id = ordered[index + 1].id
            run.superseded_at = now
            changed += 1

    if changed:
        await db.commit()
    else:
        await db.rollback()
    return changed


async def create_product_action_runs(
    db: AsyncSession,
    action_type: str,
    payloads: list[dict[str, Any]],
    *,
    created_by: str | None = "web",
    auto_start: bool = True,
) -> list[TaskRun]:
    action = action_for(action_type)
    if not payloads:
        raise ValueError("请选择要执行的商品")

    now = datetime.now()
    runs: list[TaskRun] = []
    for raw_payload in payloads:
        payload = dict(raw_payload)
        if created_by and not payload.get("created_by"):
            payload["created_by"] = created_by
        await action.validate(db, payload)
        await _lock_product_for_action_payload(db, payload)
        existing = await _existing_active_run(db, action, payload)
        if existing:
            existing.dedupe_key = existing.dedupe_key or action.dedupe_key(payload)
            existing.correlation_key = existing.correlation_key or action.correlation_key(payload)
            existing.updated_at = now
            for step in existing.steps:
                if auto_start and step.status == STEP_STATUS_PENDING:
                    step.status = STEP_STATUS_READY
                    step.updated_at = now
            plan = action.build_plan(payload)
            existing.payload_json = existing.payload_json or json_dumps(plan.payload)
            await action.reserve(db, payload, existing)
            runs.append(existing)
            continue

        plan = action.build_plan(payload)
        run = TaskRun(
            task_type=plan.task_type,
            title=plan.title,
            status=RUN_STATUS_PENDING,
            created_by=created_by,
            payload_json=json_dumps(plan.payload),
            dedupe_key=action.dedupe_key(payload),
            correlation_key=action.correlation_key(payload),
            idempotency_key=payload.get("idempotency_key"),
            source_ref=payload.get("source_ref"),
            created_at=now,
            updated_at=now,
        )
        db.add(run)
        await db.flush()

        for group_plan in plan.groups:
            group = TaskGroup(
                task_run_id=run.id,
                group_key=group_plan.group_key,
                title=group_plan.title,
                status=RUN_STATUS_PENDING,
                sort_order=group_plan.sort_order,
                depends_on_group_keys_json=json_dumps(group_plan.depends_on_group_keys),
                failure_policy=group_plan.failure_policy,
                retry_policy=group_plan.retry_policy,
                progress_current=0,
                progress_total=len(group_plan.steps),
                created_at=now,
                updated_at=now,
            )
            db.add(group)
            await db.flush()
            for index, step_plan in enumerate(group_plan.steps):
                db.add(
                    TaskStep(
                        task_run_id=run.id,
                        task_group_id=group.id,
                        step_key=step_plan.step_key,
                        step_type=step_plan.step_type,
                        status=STEP_STATUS_READY if auto_start and group_plan.sort_order == 1 and index == 0 else STEP_STATUS_PENDING,
                        sort_order=step_plan.sort_order,
                        payload_json=json_dumps(step_plan.payload),
                        progress_current=0,
                        progress_total=1,
                        max_attempts=step_plan.max_attempts,
                        created_at=now,
                        updated_at=now,
                    )
                )
        await action.reserve(db, payload, run)
        await _mark_previous_runs_superseded(db, run)
        runs.append(run)

    await db.commit()
    runs = await _reload_action_runs_for_response(db, runs)
    if auto_start:
        kick_task_runtime()
    return runs


async def product_action_worker(ctx: TaskContext) -> dict[str, Any]:
    action = action_for(ctx.step.step_type)
    payload = _payload_for_step(ctx.step)
    try:
        result = await action.execute_step(ctx.db, ctx.step, payload)
        await ctx.db.refresh(ctx.run)
        if ctx.run.cancel_requested_at:
            await action.on_cancel_requested(ctx.db, ctx.run, ctx.run.cancel_reason)
            await ctx.db.commit()
            raise TaskStepCanceled(ctx.run.cancel_reason or "用户取消")
    except Exception as exc:
        if isinstance(exc, (TaskStepCanceled, TaskStepInterrupted)):
            raise
        await ctx.db.rollback()
        await action.on_step_failure(ctx.db, ctx.step, exc)
        raise
    return result


def register_product_task_actions() -> None:
    for action in (ProductImageAnalysisAction(), ProductListingGenerationAction()):
        register_action(action)
        register_worker(action.action_type, product_action_worker)
