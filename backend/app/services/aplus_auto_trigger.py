"""A+ auto-start eligibility and post-export-ready trigger helpers."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.models import CatalogProduct, Product, ProductFile, TaskRun, TaskStep
from app.models.status import COMPLETED, WORKFLOW_NODE_FLOW_DONE, WORKFLOW_STATUS_SUCCEEDED
from app.task_planners.aplus_generate import create_aplus_generate_runs
from app.task_runtime.constants import RUN_STATUS_PENDING, RUN_STATUS_RUNNING, STEP_STATUS_PENDING, STEP_STATUS_READY, STEP_STATUS_RUNNING
from app.task_runtime.json_utils import json_loads


PRODUCT_MAIN_ACTION_TYPES = (
    "product_auto_image_selection",
    "product_competitor_search",
    "product_competitor_visual_match",
    "product_competitor_candidate_capture",
    "product_auto_competitor_selection",
    "product_image_analysis",
    "product_listing_generation",
)
ACTIVE_RUN_STATUSES = (RUN_STATUS_PENDING, RUN_STATUS_RUNNING)
ACTIVE_STEP_STATUSES = (STEP_STATUS_PENDING, STEP_STATUS_READY, STEP_STATUS_RUNNING)
APLUS_ACTIVE_STATUSES = {"queued", "planning", "scripting", "imaging"}
APLUS_DONE_STATUSES = {"done", "regen_done"}
APLUS_RETRYABLE_STATUSES = {None, "", "failed", "partial"}
SAFE_APLUS_UPLOAD_STATUSES = {None, "", "not_uploaded", "failed"}


@dataclass(frozen=True)
class AplusAutoStartDecision:
    eligible: bool
    code: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)


def _decision(eligible: bool, code: str, message: str, **details: Any) -> AplusAutoStartDecision:
    return AplusAutoStartDecision(eligible=eligible, code=code, message=message, details=details)


def _has_listing_bullets(value: str | None) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    try:
        parsed = json.loads(text)
    except Exception:
        return True
    if isinstance(parsed, list):
        return any(str(item or "").strip() for item in parsed)
    if isinstance(parsed, dict):
        return bool(parsed)
    return bool(str(parsed or "").strip())


def _has_listing_content(product: Product) -> bool:
    data = product.data
    return bool(data and str(data.listing_title or "").strip() and _has_listing_bullets(data.listing_bullets))


def _has_image_analysis(product: Product) -> bool:
    return bool(product.images and str(product.images.image_analysis or "").strip())


def _upload_protected(product: Product, catalog: CatalogProduct | None) -> tuple[bool, dict[str, Any]]:
    product_status = str(product.aplus_upload_status or "").strip()
    catalog_status = str(catalog.aplus_upload_status or "").strip() if catalog else ""
    details = {
        "product_aplus_upload_status": product_status or None,
        "catalog_aplus_upload_status": catalog_status or None,
        "product_aplus_uploaded_at": product.aplus_uploaded_at.isoformat() if product.aplus_uploaded_at else None,
        "catalog_aplus_uploaded_at": catalog.aplus_uploaded_at.isoformat() if catalog and catalog.aplus_uploaded_at else None,
    }
    protected = (
        product.aplus_uploaded_at is not None
        or bool(catalog and catalog.aplus_uploaded_at is not None)
        or product_status not in SAFE_APLUS_UPLOAD_STATUSES
        or catalog_status not in SAFE_APLUS_UPLOAD_STATUSES
    )
    return protected, details


def _has_template_output(product: Product) -> tuple[bool, dict[str, Any]]:
    data = product.data
    data_fields = {}
    if data:
        data_fields = {
            "amazon_template_path": data.amazon_template_path,
            "amazon_template_fill_summary": data.amazon_template_fill_summary,
            "amazon_template_warnings": data.amazon_template_warnings,
            "amazon_template_generated_at": data.amazon_template_generated_at.isoformat() if data.amazon_template_generated_at else None,
        }
    data_protected = any(bool(str(value or "").strip()) for value in data_fields.values())
    file_evidence: list[dict[str, Any]] = []
    for file in product.files or []:
        text = " ".join(str(part or "") for part in (file.file_type, file.label, file.path)).lower()
        if "amazon" in text and "template" in text:
            file_evidence.append({
                "id": file.id,
                "file_type": file.file_type,
                "label": file.label,
                "path": file.path,
            })
    return data_protected or bool(file_evidence), {"product_data": data_fields, "product_files": file_evidence}


async def _load_product(db: AsyncSession, product: Product) -> Product | None:
    product_id = int(getattr(product, "id", 0) or 0)
    if product_id <= 0:
        return None
    result = await db.execute(
        select(Product)
        .where(Product.id == product_id)
        .options(
            selectinload(Product.data),
            selectinload(Product.images),
            selectinload(Product.aplus),
            selectinload(Product.catalog_item),
            selectinload(Product.files),
        )
    )
    return result.scalar_one_or_none()


async def _has_active_main_workflow_task(db: AsyncSession, product_id: int, *, exclude_task_run_id: int | None) -> tuple[bool, dict[str, Any]]:
    query = (
        select(TaskRun.id, TaskRun.task_type, TaskRun.status, TaskRun.correlation_key, TaskStep.id.label("step_id"), TaskStep.step_type, TaskStep.status.label("step_status"))
        .join(TaskStep, TaskStep.task_run_id == TaskRun.id)
        .where(TaskRun.task_type.in_(PRODUCT_MAIN_ACTION_TYPES))
        .where(TaskRun.status.in_(ACTIVE_RUN_STATUSES))
        .where(TaskStep.status.in_(ACTIVE_STEP_STATUSES))
        .where(
            (TaskRun.correlation_key.like(f"product:{product_id}:%"))
            | (TaskStep.payload_json.like(f'%"product_id": {product_id}%'))
        )
        .order_by(TaskRun.id.asc(), TaskStep.id.asc())
    )
    if exclude_task_run_id:
        query = query.where(TaskRun.id != exclude_task_run_id)
    row = (await db.execute(query)).first()
    if not row:
        return False, {}
    return True, {
        "task_run_id": row.id,
        "task_type": row.task_type,
        "task_status": row.status,
        "correlation_key": row.correlation_key,
        "task_step_id": row.step_id,
        "step_type": row.step_type,
        "step_status": row.step_status,
    }


async def _has_active_aplus_task(db: AsyncSession, product_id: int) -> tuple[bool, dict[str, Any]]:
    result = await db.execute(
        select(TaskRun, TaskStep)
        .join(TaskStep, TaskStep.task_run_id == TaskRun.id)
        .where(TaskStep.step_type == "aplus_generate_product")
        .where(TaskRun.status.in_(ACTIVE_RUN_STATUSES))
        .where(TaskStep.status.in_(ACTIVE_STEP_STATUSES))
        .order_by(TaskRun.id.asc(), TaskStep.id.asc())
    )
    for run, step in result.all():
        payload = json_loads(step.payload_json, {})
        if isinstance(payload, dict) and int(payload.get("product_id") or 0) == product_id:
            return True, {
                "task_run_id": run.id,
                "task_status": run.status,
                "task_step_id": step.id,
                "step_status": step.status,
            }
    return False, {}


async def should_auto_start_aplus(
    db: AsyncSession,
    product: Product,
    *,
    exclude_task_run_id: int | None = None,
    auto_enabled: bool | None = None,
) -> AplusAutoStartDecision:
    """Return a structured A+ auto-start decision without side effects."""
    enabled = settings.AUTO_APLUS_AFTER_EXPORT_READY if auto_enabled is None else bool(auto_enabled)
    if not enabled:
        return _decision(False, "disabled_by_config", "A+ 自动触发配置未开启", auto_enabled=False)

    loaded = await _load_product(db, product)
    if not loaded:
        return _decision(False, "not_completed", "商品不存在或未落库", product_id=getattr(product, "id", None))
    product = loaded
    catalog = product.catalog_item

    if product.status != COMPLETED:
        return _decision(False, "not_completed", "商品主流程尚未 completed", product_id=product.id, status=product.status)
    if product.workflow_node != WORKFLOW_NODE_FLOW_DONE or product.workflow_status != WORKFLOW_STATUS_SUCCEEDED:
        return _decision(
            False,
            "not_flow_done",
            "商品 workflow 尚未到 flow_done/succeeded",
            product_id=product.id,
            workflow_node=product.workflow_node,
            workflow_status=product.workflow_status,
        )
    if not catalog or catalog.confirmed_at is None:
        return _decision(False, "missing_catalog_export_ready", "缺少待导出 CatalogProduct.confirmed_at 证据", product_id=product.id)
    if not _has_listing_content(product):
        return _decision(False, "missing_listing_content", "Listing 标题或五点未完成", product_id=product.id)
    if not _has_image_analysis(product):
        return _decision(False, "missing_image_analysis", "图片分析未完成", product_id=product.id)

    has_main_task, main_task_details = await _has_active_main_workflow_task(db, product.id, exclude_task_run_id=exclude_task_run_id)
    if has_main_task:
        return _decision(False, "main_workflow_active", "商品主流程仍有 active task", product_id=product.id, **main_task_details)

    has_aplus_task, aplus_task_details = await _has_active_aplus_task(db, product.id)
    if has_aplus_task:
        return _decision(False, "active_aplus_task", "A+ 已有 active task", product_id=product.id, **aplus_task_details)

    aplus_status = product.aplus.aplus_status if product.aplus else None
    normalized_aplus_status = str(aplus_status or "").strip()
    if normalized_aplus_status in APLUS_ACTIVE_STATUSES:
        return _decision(False, "active_aplus_task", "A+ 状态已处于生成中", product_id=product.id, aplus_status=normalized_aplus_status)
    if normalized_aplus_status in APLUS_DONE_STATUSES:
        return _decision(False, "aplus_done", "A+ 已生成完成", product_id=product.id, aplus_status=normalized_aplus_status)
    if normalized_aplus_status not in APLUS_RETRYABLE_STATUSES:
        return _decision(False, "aplus_done", "A+ 状态不允许自动重跑", product_id=product.id, aplus_status=normalized_aplus_status)

    upload_protected, upload_details = _upload_protected(product, catalog)
    if upload_protected:
        return _decision(False, "aplus_upload_protected", "存在 A+ 上传中或已上传证据", product_id=product.id, **upload_details)

    if product.amazon_asin or catalog.amazon_asin:
        return _decision(
            False,
            "real_asin_protected",
            "存在真实 ASIN，自动 A+ 不覆盖",
            product_id=product.id,
            product_amazon_asin=product.amazon_asin,
            catalog_amazon_asin=catalog.amazon_asin,
        )

    if catalog.exported_at or catalog.export_task_id or catalog.export_file_path:
        return _decision(
            False,
            "export_history_protected",
            "存在导出历史，自动 A+ 不覆盖",
            product_id=product.id,
            exported_at=catalog.exported_at.isoformat() if catalog.exported_at else None,
            export_task_id=catalog.export_task_id,
            export_file_path=catalog.export_file_path,
        )

    template_protected, template_details = _has_template_output(product)
    if template_protected:
        return _decision(False, "template_output_protected", "存在 Amazon 模板输出证据，自动 A+ 不覆盖", product_id=product.id, **template_details)

    return _decision(
        True,
        "eligible",
        "商品满足 A+ 自动触发 A1 eligibility",
        product_id=product.id,
        catalog_product_id=catalog.id,
        confirmed_at=catalog.confirmed_at.isoformat(),
        aplus_status=normalized_aplus_status or None,
    )


def _decision_result(decision: AplusAutoStartDecision, *, source_task_run_id: int | None = None, source_task_step_id: int | None = None) -> dict[str, Any]:
    status = "reused" if decision.code == "active_aplus_task" else "skipped"
    return {
        "status": status,
        "code": decision.code,
        "message": decision.message,
        "details": decision.details,
        "source_task_run_id": source_task_run_id,
        "source_task_step_id": source_task_step_id,
    }


async def try_auto_start_aplus_after_export_ready(
    db: AsyncSession,
    product_id: int,
    *,
    source_task_run_id: int | None = None,
    source_task_step_id: int | None = None,
    created_by: str = "auto_after_export_ready",
) -> dict[str, Any]:
    """Best-effort A+ trigger after Listing success has committed export-ready.

    The helper returns structured evidence for task summaries and logs. Planner
    failures are contained here so callers do not roll back the product main
    workflow after it reached export-ready.
    """
    result = await db.execute(
        select(Product)
        .where(Product.id == product_id)
        .options(selectinload(Product.catalog_item))
    )
    product = result.scalar_one_or_none()
    if not product:
        return {
            "status": "skipped",
            "code": "not_completed",
            "message": "商品不存在或未落库",
            "details": {"product_id": product_id},
            "source_task_run_id": source_task_run_id,
            "source_task_step_id": source_task_step_id,
        }

    decision = await should_auto_start_aplus(
        db,
        product,
        exclude_task_run_id=source_task_run_id,
    )
    if not decision.eligible:
        return _decision_result(
            decision,
            source_task_run_id=source_task_run_id,
            source_task_step_id=source_task_step_id,
        )

    catalog_product_id = int(decision.details.get("catalog_product_id") or 0)
    if catalog_product_id <= 0:
        return {
            "status": "failed",
            "code": "trigger_failed",
            "message": "A+ 自动触发缺少 catalog_product_id",
            "details": {"product_id": product_id, "decision": decision.details},
            "source_task_run_id": source_task_run_id,
            "source_task_step_id": source_task_step_id,
        }

    try:
        runs, errors, queued_product_ids = await create_aplus_generate_runs(
            db,
            [catalog_product_id],
            force=False,
            created_by=created_by,
            auto_start=True,
        )
    except Exception as exc:
        await db.rollback()
        return {
            "status": "failed",
            "code": "trigger_failed",
            "message": f"{type(exc).__name__}: {exc}",
            "details": {
                "product_id": product_id,
                "catalog_product_id": catalog_product_id,
            },
            "source_task_run_id": source_task_run_id,
            "source_task_step_id": source_task_step_id,
        }

    if runs:
        return {
            "status": "queued",
            "code": "queued",
            "message": "A+ 自动生成任务已创建或加入队列",
            "details": {
                "product_id": product_id,
                "catalog_product_id": catalog_product_id,
                "task_run_ids": [run.id for run in runs],
                "queued_product_ids": queued_product_ids,
                "planner_errors": errors,
            },
            "source_task_run_id": source_task_run_id,
            "source_task_step_id": source_task_step_id,
        }

    return {
        "status": "skipped",
        "code": "planner_skipped",
        "message": "A+ planner 未创建任务",
        "details": {
            "product_id": product_id,
            "catalog_product_id": catalog_product_id,
            "planner_errors": errors,
            "queued_product_ids": queued_product_ids,
        },
        "source_task_run_id": source_task_run_id,
        "source_task_step_id": source_task_step_id,
    }
