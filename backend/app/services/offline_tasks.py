import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.schemas import OfflineTaskCatalogExportRequest, OfflineTaskGigaDynamicSyncRequest, OfflineTaskGigaPullRequest
from app.config import settings
from app.database import async_session
from app.models import CatalogProduct, OfflineTask, OfflineTaskStep, Product, ProductAplus, ProductDataSource
from app.pipeline.engine import is_running
from app.pipeline.step7_aplus_plan import run_aplus_plan
from app.pipeline.step8_aplus_script import run_aplus_script
from app.pipeline.step9_aplus_image import run_aplus_image
from app.services.giga_inventory_sync import GigaInventorySyncOptions, sync_giga_inventory_snapshot
from app.services.giga_image_download_tasks import download_giga_batch_images
from app.services.giga_openapi import GigaSyncOptions, resolve_giga_data_source_context, sync_giga_products
from app.services.giga_price_sync import GigaPriceSyncOptions, sync_giga_price_snapshot
from app.services.oss_uploader import upload_private_file
from app.services.stylesnap_product_tasks import upsert_product_drafts_from_giga_batch

logger = logging.getLogger(__name__)

_active_offline_tasks: dict[int, asyncio.Task] = {}

TASK_STATUS_ACTIVE = {"pending", "running"}
STEP_STATUS_SUCCESS = "done"
STEP_STATUS_FAILURES = {"failed", "interrupted"}
STEP_STATUS_RESUMABLE = {"pending", "running", "paused", "interrupted"}
STEP_STATUS_CLAIMABLE = {"pending", "interrupted"}
SUPPORTED_TASK_TYPES = {"giga_pull", "giga_inventory_sync", "giga_price_sync", "aplus_generate", "catalog_export"}
APLUS_GENERATE_ACTIVE_STATUSES = {"queued", "planning", "scripting", "imaging"}


def _json_dumps(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _json_loads(value: str | None, default: object | None = None) -> object:
    if not value:
        return {} if default is None else default
    try:
        return json.loads(value)
    except Exception:
        return {} if default is None else default


def _safe_filename_part(value: str | None, fallback: str = "export") -> str:
    raw = (value or fallback).strip() or fallback
    cleaned = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in raw)
    return cleaned[:90] or fallback


def _catalog_export_object_key(task_id: int, filename: str) -> str:
    prefix = settings.OSS_EXPORT_UPLOAD_PREFIX.strip().strip("/")
    raw = Path(filename)
    safe_filename = _safe_filename_part(raw.stem, "catalog_export") + (raw.suffix.lower() or ".zip")
    key = f"task_{task_id}/{safe_filename}"
    return f"{prefix}/{key}" if prefix else key


def _catalog_export_result_ready(payload: object) -> bool:
    if not isinstance(payload, dict):
        return False
    file_path = str(payload.get("file_path") or "").strip()
    object_key = str(payload.get("oss_object_key") or "").strip()
    if file_path and Path(file_path).expanduser().is_file():
        return True
    return bool(object_key and payload.get("filename"))


def _catalog_export_row_status(row: dict) -> str:
    status = str(row.get("状态") or "").strip()
    if status == "已导出":
        return "exported"
    if status == "失败":
        return "failed"
    return "skipped"


def _catalog_export_result_rows(report_rows: list[dict]) -> list[dict]:
    rows: list[dict] = []
    for row in report_rows:
        rows.append({
            "catalog_id": row.get("商品资料ID"),
            "product_id": row.get("商品ID"),
            "item_code": row.get("商品Code"),
            "category": row.get("类目"),
            "status": _catalog_export_row_status(row),
            "reason": row.get("原因"),
            "template_file": row.get("模板文件"),
            "output_file": row.get("导出文件"),
        })
    return rows


def _catalog_export_result_payload(
    *,
    category: str,
    categories: list[str],
    template_name: str | None,
    template_path: object,
    catalog_ids: list[int],
    report_rows: list[dict],
    created_at: datetime,
    filename: str | None = None,
    file_path: str | None = None,
    oss_object_key: str | None = None,
    oss_url: str | None = None,
    file_size: int | None = None,
) -> dict:
    rows = _catalog_export_result_rows(report_rows)
    success_count = sum(1 for row in rows if row["status"] == "exported")
    skipped_count = sum(1 for row in rows if row["status"] == "skipped")
    failed_count = sum(1 for row in rows if row["status"] == "failed")
    status = "failed"
    if success_count and (skipped_count or failed_count):
        status = "partial_failed"
    elif success_count:
        status = "done"
    return {
        "status": status,
        "category": category,
        "categories": categories or [category],
        "template_name": template_name or None,
        "template_path": template_path,
        "catalog_product_ids": catalog_ids,
        "requested_count": len(catalog_ids),
        "success_count": success_count,
        "exported_count": success_count,
        "skipped_count": skipped_count,
        "failed_count": failed_count,
        "report_count": len(report_rows),
        "filename": filename,
        "file_path": file_path,
        "oss_object_key": oss_object_key,
        "oss_url": oss_url,
        "file_size": file_size,
        "report_filename": "导出报告.xlsx" if report_rows else None,
        "created_at": created_at.isoformat(),
        "rows": rows,
    }


async def _refresh_task_stats(db: AsyncSession, task_id: int) -> OfflineTask | None:
    task = await db.get(OfflineTask, task_id)
    if not task:
        return None
    result = await db.execute(select(OfflineTaskStep).where(OfflineTaskStep.task_id == task_id))
    steps = result.scalars().all()
    total = len(steps)
    success = sum(1 for step in steps if step.status == STEP_STATUS_SUCCESS)
    failed = sum(1 for step in steps if step.status in STEP_STATUS_FAILURES)
    running = sum(1 for step in steps if step.status == "running")
    pending = sum(1 for step in steps if step.status == "pending")
    paused = sum(1 for step in steps if step.status == "paused")
    task.total_steps = total
    task.success_steps = success
    task.failed_steps = failed
    task.running_steps = running
    now = datetime.now()
    task.updated_at = now
    if paused or task.status == "paused":
        task.status = "paused"
        task.finished_at = None
    elif running:
        task.status = "running"
        task.started_at = task.started_at or now
        task.finished_at = None
    elif pending:
        task.status = "pending" if not task.started_at else "running"
        task.finished_at = None
    elif total and success == total:
        task.status = "done"
        task.finished_at = task.finished_at or now
    elif failed and success:
        task.status = "partial_failed"
        task.finished_at = task.finished_at or now
    elif failed:
        task.status = "failed"
        task.finished_at = task.finished_at or now
    else:
        task.status = "pending"
        task.finished_at = None
    if task.task_type == "catalog_export" and task.status == "done":
        payload = _json_loads(task.result_json, {})
        if not isinstance(payload, dict) or not payload:
            for step in steps:
                if step.step_type == "catalog_export_template" and step.status == STEP_STATUS_SUCCESS:
                    payload = _json_loads(step.result_json, {})
                    if isinstance(payload, dict) and payload:
                        break
        if isinstance(payload, dict) and payload.get("status") == "partial_failed":
            task.status = "partial_failed"
    return task


async def _set_step_status(
    db: AsyncSession,
    step: OfflineTaskStep,
    status: str,
    *,
    result: dict | None = None,
    error: str | None = None,
    progress_current: int | None = None,
    progress_total: int | None = None,
) -> None:
    now = datetime.now()
    step.status = status
    step.updated_at = now
    if status == "running":
        step.started_at = step.started_at or now
        step.finished_at = None
        step.error_message = None
    if status in {"done", "failed", "interrupted"}:
        step.finished_at = now
    if result is not None:
        step.result_json = _json_dumps(result)
    if error is not None:
        step.error_message = error
    if progress_current is not None:
        step.progress_current = progress_current
    if progress_total is not None:
        step.progress_total = progress_total
    await _refresh_task_stats(db, step.task_id)
    await db.commit()


async def _claim_offline_step(db: AsyncSession, step_id: int) -> OfflineTaskStep | None:
    now = datetime.now()
    result = await db.execute(
        update(OfflineTaskStep)
        .where(
            OfflineTaskStep.id == step_id,
            OfflineTaskStep.status.in_(tuple(STEP_STATUS_CLAIMABLE)),
        )
        .values(
            status="running",
            started_at=now,
            finished_at=None,
            error_message=None,
            updated_at=now,
        )
    )
    if (result.rowcount or 0) != 1:
        await db.rollback()
        return None
    await db.commit()
    claimed = await db.get(OfflineTaskStep, step_id)
    if claimed:
        await _refresh_task_stats(db, claimed.task_id)
        await db.commit()
    return claimed


async def _ensure_image_step(db: AsyncSession, sync_step: OfflineTaskStep) -> OfflineTaskStep:
    result = await db.execute(
        select(OfflineTaskStep).where(
            OfflineTaskStep.task_id == sync_step.task_id,
            OfflineTaskStep.step_type == "giga_image_download",
            OfflineTaskStep.batch_id == sync_step.batch_id,
            OfflineTaskStep.data_source_id == sync_step.data_source_id,
        )
    )
    existing = result.scalar_one_or_none()
    if existing:
        existing.status = "pending" if existing.status in STEP_STATUS_FAILURES else existing.status
        existing.error_message = None if existing.status == "pending" else existing.error_message
        existing.updated_at = datetime.now()
        await db.commit()
        return existing

    step = OfflineTaskStep(
        task_id=sync_step.task_id,
        step_type="giga_image_download",
        title=f"下载图片：{sync_step.data_source_name or sync_step.data_source_id}",
        status="pending",
        data_source_id=sync_step.data_source_id,
        data_source_name=sync_step.data_source_name,
        site=sync_step.site,
        batch_id=sync_step.batch_id,
        progress_current=0,
        progress_total=0,
        payload_json=_json_dumps({"batch_id": sync_step.batch_id, "site": sync_step.site}),
        updated_at=datetime.now(),
    )
    db.add(step)
    await _refresh_task_stats(db, sync_step.task_id)
    await db.commit()
    await db.refresh(step)
    return step


async def _run_image_step(db: AsyncSession, step: OfflineTaskStep) -> None:
    await _set_step_status(db, step, "running")

    async def update_progress(counts: dict[str, int]) -> None:
        await db.refresh(step)
        task = await db.get(OfflineTask, step.task_id)
        if task and task.status == "paused":
            raise asyncio.CancelledError()
        step.progress_current = counts.get("done", 0)
        step.progress_total = counts.get("total", 0)
        pending = counts.get("pending", 0)
        failed = counts.get("failed", 0)
        step.result_json = _json_dumps(counts)
        step.error_message = f"图片下载中：待下载 {pending}，失败 {failed}" if pending or failed else None
        step.updated_at = datetime.now()
        await _refresh_task_stats(db, step.task_id)
        await db.commit()

    try:
        result = await download_giga_batch_images(
            batch_id=step.batch_id or "",
            site=step.site or "US",
            data_source_id=step.data_source_id,
            progress_callback=update_progress,
        )
        await upsert_product_drafts_from_giga_batch(
            db,
            batch_id=step.batch_id or "",
            site=step.site or "US",
            data_source_id=step.data_source_id,
        )
        await _set_step_status(
            db,
            step,
            "done" if result.get("failed", 0) == 0 else "failed",
            result=result,
            error=None if result.get("failed", 0) == 0 else f"{result.get('failed', 0)} 张图片下载失败",
            progress_current=result.get("done", 0),
            progress_total=result.get("total", 0),
        )
    except Exception as exc:
        await db.rollback()
        await _set_step_status(db, step, "failed", error=f"{type(exc).__name__}: {exc}")


async def _run_sync_step(db: AsyncSession, step: OfflineTaskStep) -> None:
    await _set_step_status(db, step, "running")
    payload = json.loads(step.payload_json or "{}")
    try:
        result = await sync_giga_products(
            db,
            GigaSyncOptions(
                task_id=f"offline-task-{step.task_id}-step-{step.id}",
                batch_id=step.batch_id or "",
                site=step.site or "US",
                data_source_id=step.data_source_id,
                current_category=payload.get("current_category"),
                page_size=payload.get("page_size") or 200,
                max_pages=payload.get("max_pages"),
                skip_existing=True,
                download_images=False,
            ),
        )
        draft_result = await upsert_product_drafts_from_giga_batch(
            db,
            batch_id=result.batch_id,
            site=result.site,
            data_source_id=result.data_source_id,
        )
        await _set_step_status(
            db,
            step,
            "done",
            result={**result.__dict__, "product_drafts": draft_result.__dict__},
            progress_current=result.sku_count,
            progress_total=result.sku_count,
        )
    except Exception as exc:
        await db.rollback()
        logger.exception("[OfflineTask] GIGA pull step failed: task=%s step=%s", step.task_id, step.id)
        await _set_step_status(db, step, "failed", error=f"{type(exc).__name__}: {exc}")


async def _run_inventory_sync_step(db: AsyncSession, step: OfflineTaskStep) -> None:
    await _set_step_status(db, step, "running")
    payload = json.loads(step.payload_json or "{}")
    try:
        result = await sync_giga_inventory_snapshot(
            db,
            GigaInventorySyncOptions(
                task_id=f"offline-task-{step.task_id}-step-{step.id}",
                batch_id=step.batch_id or "",
                site=step.site or "US",
                data_source_id=step.data_source_id or 0,
                sku_codes=payload.get("sku_codes") or [],
            ),
        )
        await _set_step_status(
            db,
            step,
            "done" if result.failed_count == 0 else "failed",
            result=result.__dict__,
            error=None if result.failed_count == 0 else f"{result.failed_count} 个 SKU 库存同步失败",
            progress_current=result.success_count,
            progress_total=result.total_skus,
        )
    except Exception as exc:
        await db.rollback()
        logger.exception("[OfflineTask] GIGA inventory sync step failed: task=%s step=%s", step.task_id, step.id)
        await _set_step_status(db, step, "failed", error=f"{type(exc).__name__}: {exc}")


async def _run_price_sync_step(db: AsyncSession, step: OfflineTaskStep) -> None:
    await _set_step_status(db, step, "running")
    payload = json.loads(step.payload_json or "{}")
    try:
        result = await sync_giga_price_snapshot(
            db,
            GigaPriceSyncOptions(
                task_id=f"offline-task-{step.task_id}-step-{step.id}",
                batch_id=step.batch_id or "",
                site=step.site or "US",
                data_source_id=step.data_source_id or 0,
                sku_codes=payload.get("sku_codes") or [],
            ),
        )
        await _set_step_status(
            db,
            step,
            "done" if result.failed_count == 0 else "failed",
            result=result.__dict__,
            error=None if result.failed_count == 0 else f"{result.failed_count} 个 SKU 价格同步失败",
            progress_current=result.success_count,
            progress_total=result.total_skus,
        )
    except Exception as exc:
        await db.rollback()
        logger.exception("[OfflineTask] GIGA price sync step failed: task=%s step=%s", step.task_id, step.id)
        await _set_step_status(db, step, "failed", error=f"{type(exc).__name__}: {exc}")


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
            .options(
                selectinload(Product.aplus),
                selectinload(Product.catalog_item),
            )
        )
        product = result.scalar_one_or_none()
        if not product:
            return
        if not product.aplus:
            product.aplus = ProductAplus(product_id=product.id)
            session.add(product.aplus)
            await session.flush()
        if clear_outputs:
            product.aplus.aplus_plan = None
            product.aplus.aplus_plan_summary = None
            product.aplus.aplus_scripts = None
            product.aplus.aplus_scripts_summary = None
            product.aplus.aplus_images = None
            product.aplus.aplus_image_count = None
            product.aplus.planned_at = None
            product.aplus.scripted_at = None
            product.aplus.generated_at = None
        product.aplus.aplus_status = status
        if error:
            product.error_message = error
        elif product.error_message and product.error_message.startswith("A+生成"):
            product.error_message = None
        product.updated_at = datetime.now()
        if product.catalog_item:
            product.catalog_item.updated_at = product.updated_at
        await session.commit()


async def _ensure_task_not_paused(db: AsyncSession, task_id: int) -> None:
    task = await db.get(OfflineTask, task_id)
    if task and task.status == "paused":
        raise asyncio.CancelledError()


async def _run_aplus_generate_step(db: AsyncSession, step: OfflineTaskStep) -> None:
    payload = _json_loads(step.payload_json, {})
    product_id = int(payload.get("product_id") or 0) if isinstance(payload, dict) else 0
    force = bool(payload.get("force")) if isinstance(payload, dict) else False
    if product_id <= 0:
        await _set_step_status(db, step, "failed", error="A+生成步骤缺少 product_id")
        return

    try:
        await _set_step_status(db, step, "running", progress_current=0, progress_total=3)
        await _set_aplus_status(product_id, "planning", clear_outputs=force)
        await run_aplus_plan(product_id)
        await _ensure_task_not_paused(db, step.task_id)
        await _set_step_status(
            db,
            step,
            "running",
            result={"stage": "规划完成"},
            progress_current=1,
            progress_total=3,
        )

        await _set_aplus_status(product_id, "scripting")
        await run_aplus_script(product_id)
        await _ensure_task_not_paused(db, step.task_id)
        await _set_step_status(
            db,
            step,
            "running",
            result={"stage": "脚本完成"},
            progress_current=2,
            progress_total=3,
        )

        await _set_aplus_status(product_id, "imaging")
        image_result = await run_aplus_image(product_id)
        await _ensure_task_not_paused(db, step.task_id)
        await _set_aplus_status(product_id, "done")
        await _set_step_status(
            db,
            step,
            "done",
            result={"stage": "出图完成", "image_result": image_result},
            progress_current=3,
            progress_total=3,
        )
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        error = f"A+生成失败: {type(exc).__name__}: {exc}"
        logger.exception("[OfflineTask] A+ generate step failed: task=%s step=%s product=%s", step.task_id, step.id, product_id)
        await _set_aplus_status(product_id, "failed", error=error)
        await _set_step_status(db, step, "failed", error=error)


async def _run_catalog_export_step(db: AsyncSession, step: OfflineTaskStep) -> None:
    step_id = step.id
    task_id = step.task_id
    existing_result = _json_loads(step.result_json, {})
    if step.status == STEP_STATUS_SUCCESS and _catalog_export_result_ready(existing_result):
        task = await db.get(OfflineTask, step.task_id)
        if task and isinstance(existing_result, dict):
            if not task.result_json:
                task.result_json = _json_dumps(existing_result)
            if existing_result.get("status") == "partial_failed":
                task.status = "partial_failed"
            task.updated_at = datetime.now()
            await db.commit()
        return
    if _catalog_export_result_ready(existing_result):
        progress_total = step.progress_total or len((existing_result if isinstance(existing_result, dict) else {}).get("catalog_product_ids") or [])
        await _set_step_status(
            db,
            step,
            "done",
            result=existing_result if isinstance(existing_result, dict) else None,
            progress_current=progress_total,
            progress_total=progress_total,
        )
        task = await db.get(OfflineTask, step.task_id)
        if task and not task.result_json:
            task.result_json = _json_dumps(existing_result)
            task.updated_at = datetime.now()
            await db.commit()
        return

    payload = _json_loads(step.payload_json, {})
    if not isinstance(payload, dict):
        await _set_step_status(db, step, "failed", error="导出步骤参数格式错误")
        return
    catalog_ids = list(dict.fromkeys(int(item_id) for item_id in payload.get("catalog_product_ids") or []))
    categories = [str(item) for item in (payload.get("categories") or []) if str(item).strip()]
    category = str(payload.get("category") or (categories[0] if categories else "未分类"))
    template_name = str(payload.get("template_name") or "").strip()
    if not catalog_ids:
        await _set_step_status(db, step, "failed", error="导出步骤缺少商品")
        return

    from app.api.products import CatalogExportBuildError, build_catalog_export_zip

    try:
        await _set_step_status(db, step, "running", progress_current=0, progress_total=len(catalog_ids))
        result = await db.execute(select(CatalogProduct).where(CatalogProduct.id.in_(catalog_ids)))
        catalog_items = result.scalars().all()
        if not catalog_items:
            raise ValueError("导出商品不存在")

        # Reuse the exact same export builder as the direct download endpoint,
        # so task export and manual export cannot drift apart.
        zip_bytes, filename, report_rows = await build_catalog_export_zip(catalog_items, db)
        export_dir = settings.DATA_DIR / "exports" / f"task_{step.task_id}"
        export_dir.mkdir(parents=True, exist_ok=True)
        safe_scope = _safe_filename_part(Path(template_name).stem if template_name else category, "template")
        target_path = export_dir / f"{safe_scope}_{filename}"
        target_path.write_bytes(zip_bytes)
        uploaded = upload_private_file(target_path, _catalog_export_object_key(step.task_id, target_path.name))
        exported_source_ids = {
            int(row.get("商品ID"))
            for row in report_rows
            if row.get("状态") == "已导出" and row.get("商品ID") is not None
        }
        exported_at = datetime.now()
        for item in catalog_items:
            if item.source_product_id in exported_source_ids:
                item.exported_at = exported_at
                item.export_task_id = step.task_id
                item.export_file_path = str(uploaded.get("url") or target_path)
                item.updated_at = exported_at
        result_payload = _catalog_export_result_payload(
            category=category,
            categories=categories,
            template_name=template_name or None,
            template_path=payload.get("template_path"),
            catalog_ids=catalog_ids,
            report_rows=report_rows,
            created_at=exported_at,
            filename=target_path.name,
            file_path=str(target_path),
            oss_object_key=uploaded.get("object_key"),
            oss_url=uploaded.get("url"),
            file_size=target_path.stat().st_size,
        )
        await _set_step_status(
            db,
            step,
            "done",
            result=result_payload,
            progress_current=len(catalog_ids),
            progress_total=len(catalog_ids),
        )
        task = await db.get(OfflineTask, step.task_id)
        if task:
            task.result_json = _json_dumps(result_payload)
            task.status = result_payload["status"]
            task.updated_at = datetime.now()
            await db.commit()
    except CatalogExportBuildError as exc:
        await db.rollback()
        step = await db.get(OfflineTaskStep, step_id)
        if not step:
            return
        failed_at = datetime.now()
        result_payload = _catalog_export_result_payload(
            category=category,
            categories=categories,
            template_name=template_name or None,
            template_path=payload.get("template_path"),
            catalog_ids=catalog_ids,
            report_rows=exc.report_rows,
            created_at=failed_at,
        )
        await _set_step_status(
            db,
            step,
            "failed",
            result=result_payload,
            error=exc.message,
            progress_current=0,
            progress_total=len(catalog_ids),
        )
        task = await db.get(OfflineTask, task_id)
        if task:
            task.result_json = _json_dumps(result_payload)
            task.status = "failed"
            task.error_message = exc.message
            task.updated_at = datetime.now()
            await db.commit()
    except Exception as exc:
        await db.rollback()
        step = await db.get(OfflineTaskStep, step_id)
        if not step:
            return
        logger.exception("[OfflineTask] catalog export step failed: task=%s step=%s", task_id, step_id)
        await _set_step_status(db, step, "failed", error=f"{type(exc).__name__}: {exc}")


async def _execute_offline_task(task_id: int, step_ids: list[int] | None = None) -> None:
    try:
        async with async_session() as db:
            query = select(OfflineTaskStep).where(OfflineTaskStep.task_id == task_id)
            if step_ids:
                query = query.where(OfflineTaskStep.id.in_(step_ids))
            else:
                query = query.where(OfflineTaskStep.status.in_(tuple(STEP_STATUS_CLAIMABLE)))
            result = await db.execute(query.order_by(OfflineTaskStep.id.asc()))
            steps = result.scalars().all()
            task = await db.get(OfflineTask, task_id)
            if task and task.status == "paused":
                return
            if task:
                task.status = "running"
                task.started_at = task.started_at or datetime.now()
                task.updated_at = datetime.now()
                await db.commit()
            for step in steps:
                claimed_step = await _claim_offline_step(db, step.id)
                if not claimed_step:
                    continue
                step = claimed_step
                task = await db.get(OfflineTask, task_id)
                if task and task.status == "paused":
                    break
                if step.step_type == "giga_sync":
                    await _run_sync_step(db, step)
                elif step.step_type == "giga_image_download":
                    await _run_image_step(db, step)
                elif step.step_type == "giga_inventory_sync":
                    await _run_inventory_sync_step(db, step)
                elif step.step_type == "giga_price_sync":
                    await _run_price_sync_step(db, step)
                elif step.step_type == "aplus_generate_product":
                    await _run_aplus_generate_step(db, step)
                elif step.step_type == "catalog_export_template":
                    await _run_catalog_export_step(db, step)
            await _refresh_task_stats(db, task_id)
            await db.commit()
    finally:
        _active_offline_tasks.pop(task_id, None)


def _schedule_offline_task(task_id: int, step_ids: list[int] | None = None) -> None:
    existing = _active_offline_tasks.get(task_id)
    if existing and not existing.done():
        return
    _active_offline_tasks[task_id] = asyncio.create_task(_execute_offline_task(task_id, step_ids))


async def _cancel_active_offline_task(task_id: int) -> None:
    active = _active_offline_tasks.get(task_id)
    if not active or active.done():
        _active_offline_tasks.pop(task_id, None)
        return
    active.cancel()
    try:
        await asyncio.wait_for(active, timeout=5)
    except asyncio.CancelledError:
        pass
    except TimeoutError:
        logger.warning("[OfflineTask] task=%s did not stop within pause timeout", task_id)
    except Exception:
        logger.exception("[OfflineTask] task=%s stopped with error while pausing", task_id)


async def _load_task_detail(db: AsyncSession, task_id: int) -> OfflineTask:
    task = await db.get(OfflineTask, task_id)
    if not task:
        raise ValueError("任务不存在")
    if task.task_type not in SUPPORTED_TASK_TYPES:
        raise ValueError("当前任务类型暂不支持控制")
    return task


async def pause_offline_task(db: AsyncSession, task_id: int) -> OfflineTask:
    task = await _load_task_detail(db, task_id)
    if task.status in {"done", "failed", "partial_failed"}:
        raise ValueError(f"任务已结束，不能挂起，当前状态: {task.status}")
    if task.status == "paused":
        return task

    await _cancel_active_offline_task(task_id)
    result = await db.execute(
        select(OfflineTaskStep).where(
            OfflineTaskStep.task_id == task_id,
            OfflineTaskStep.status.in_(("pending", "running")),
        )
    )
    steps = result.scalars().all()
    now = datetime.now()
    for step in steps:
        step.status = "paused"
        step.error_message = "任务已挂起，恢复后继续执行。"
        step.finished_at = None
        step.updated_at = now
    task.status = "paused"
    task.error_message = "任务已挂起，恢复后会继续未完成步骤。"
    task.running_steps = 0
    task.finished_at = None
    task.updated_at = now
    await db.commit()
    await db.refresh(task)
    return task


async def resume_offline_task(db: AsyncSession, task_id: int) -> OfflineTask:
    task = await _load_task_detail(db, task_id)
    if task.status != "paused":
        raise ValueError(f"只能恢复已挂起任务，当前状态: {task.status}")

    result = await db.execute(
        select(OfflineTaskStep).where(
            OfflineTaskStep.task_id == task_id,
            OfflineTaskStep.status == "paused",
        )
    )
    steps = result.scalars().all()
    if not steps:
        raise ValueError("没有可恢复的挂起步骤")

    now = datetime.now()
    for step in steps:
        step.status = "pending"
        step.error_message = None
        step.finished_at = None
        step.updated_at = now
    task.status = "pending"
    task.error_message = None
    task.finished_at = None
    task.updated_at = now
    await _refresh_task_stats(db, task_id)
    await db.commit()
    _schedule_offline_task(task_id, [step.id for step in steps])
    await db.refresh(task)
    return task


async def _load_enabled_sources(db: AsyncSession, data_source_ids: list[int]) -> tuple[list[int], list[ProductDataSource]]:
    deduped_ids = list(dict.fromkeys(data_source_ids))
    result = await db.execute(
        select(ProductDataSource)
        .where(ProductDataSource.id.in_(deduped_ids), ProductDataSource.enabled == 1)
        .order_by(ProductDataSource.id.asc())
    )
    sources = result.scalars().all()
    found_ids = {source.id for source in sources}
    missing_ids = [source_id for source_id in deduped_ids if source_id not in found_ids]
    if missing_ids:
        raise ValueError(f"店铺不存在或未启用: {', '.join(map(str, missing_ids))}")
    return deduped_ids, sources


async def create_giga_pull_task(
    db: AsyncSession,
    body: OfflineTaskGigaPullRequest,
    *,
    auto_start: bool = True,
) -> OfflineTask:
    data_source_ids, sources = await _load_enabled_sources(db, body.data_source_ids)

    task = OfflineTask(
        task_type="giga_pull",
        title=f"同步店铺商品（{len(sources)} 个店铺）",
        status="pending",
        total_steps=len(sources),
        success_steps=0,
        failed_steps=0,
        running_steps=0,
        payload_json=_json_dumps({
            "data_source_ids": data_source_ids,
            "current_category": body.current_category,
            "page_size": body.page_size,
            "max_pages": body.max_pages,
        }),
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    db.add(task)
    await db.flush()
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    for source in sources:
        context = await resolve_giga_data_source_context(db, source.id, source.site)
        batch_id = f"workbench-giga-t{task.id}-ds{source.id}-{timestamp}"
        db.add(
            OfflineTaskStep(
                task_id=task.id,
                step_type="giga_sync",
                title=f"同步商品：{context.name}",
                status="pending",
                data_source_id=context.id,
                data_source_name=context.name,
                site=context.site,
                batch_id=batch_id,
                progress_current=0,
                progress_total=0,
                payload_json=_json_dumps({
                    "batch_id": batch_id,
                    "site": context.site,
                    "data_source_id": context.id,
                    "current_category": body.current_category,
                    "page_size": body.page_size,
                    "max_pages": body.max_pages,
                    "skip_existing": True,
                }),
                updated_at=datetime.now(),
            )
        )
    await db.commit()
    await db.refresh(task)
    if auto_start:
        _schedule_offline_task(task.id)
    return task


async def create_giga_dynamic_sync_task(
    db: AsyncSession,
    body: OfflineTaskGigaDynamicSyncRequest,
    *,
    kind: str,
    auto_start: bool = True,
) -> OfflineTask:
    if kind not in {"inventory", "price"}:
        raise ValueError(f"不支持的同步类型: {kind}")
    data_source_ids, sources = await _load_enabled_sources(db, body.data_source_ids)
    sku_codes = list(dict.fromkeys(str(sku).strip() for sku in (body.sku_codes or []) if str(sku or "").strip()))
    is_inventory = kind == "inventory"
    task_type = "giga_inventory_sync" if is_inventory else "giga_price_sync"
    step_type = task_type
    title_prefix = "同步大健库存" if is_inventory else "同步大健价格"
    step_prefix = "库存同步" if is_inventory else "价格同步"

    task = OfflineTask(
        task_type=task_type,
        title=f"{title_prefix}（{len(sources)} 个店铺）",
        status="pending",
        total_steps=len(sources),
        success_steps=0,
        failed_steps=0,
        running_steps=0,
        payload_json=_json_dumps({
            "data_source_ids": data_source_ids,
            "sku_codes": sku_codes,
        }),
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    db.add(task)
    await db.flush()

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    for source in sources:
        context = await resolve_giga_data_source_context(db, source.id, source.site)
        batch_kind = "inventory" if is_inventory else "price"
        batch_id = f"giga-{batch_kind}-t{task.id}-ds{context.id}-{timestamp}"
        db.add(
            OfflineTaskStep(
                task_id=task.id,
                step_type=step_type,
                title=f"{step_prefix}：{context.name}",
                status="pending",
                data_source_id=context.id,
                data_source_name=context.name,
                site=context.site,
                batch_id=batch_id,
                progress_current=0,
                progress_total=0,
                payload_json=_json_dumps({
                    "batch_id": batch_id,
                    "site": context.site,
                    "data_source_id": context.id,
                    "sku_codes": sku_codes,
                }),
                updated_at=datetime.now(),
            )
        )
    await db.commit()
    await db.refresh(task)
    if auto_start:
        _schedule_offline_task(task.id)
    return task


async def _active_export_catalog_ids(db: AsyncSession) -> set[int]:
    result = await db.execute(
        select(OfflineTaskStep).where(
            OfflineTaskStep.step_type == "catalog_export_template",
            OfflineTaskStep.status.in_(("pending", "running", "paused")),
        )
    )
    active_ids: set[int] = set()
    for step in result.scalars().all():
        payload = _json_loads(step.payload_json, {})
        if not isinstance(payload, dict):
            continue
        for catalog_id in payload.get("catalog_product_ids") or []:
            try:
                parsed = int(catalog_id)
            except (TypeError, ValueError):
                continue
            if parsed > 0:
                active_ids.add(parsed)
    return active_ids


async def create_catalog_export_tasks(
    db: AsyncSession,
    body: OfflineTaskCatalogExportRequest,
    *,
    auto_start: bool = True,
) -> tuple[list[OfflineTask], list[str]]:
    requested_ids = list(dict.fromkeys(int(item_id) for item_id in body.catalog_product_ids))
    if not requested_ids:
        raise ValueError("请选择要导出的商品")
    if len(requested_ids) > 1000:
        raise ValueError("单次最多导出 1000 个商品")

    result = await db.execute(
        select(CatalogProduct)
        .where(CatalogProduct.id.in_(requested_ids))
        .options(selectinload(CatalogProduct.source_product).selectinload(Product.data))
    )
    catalog_items = result.scalars().all()
    catalog_by_id = {item.id: item for item in catalog_items}
    active_catalog_ids = await _active_export_catalog_ids(db)

    from app.api.products import _catalog_category, _catalog_existing_asin, _template_status_for_catalog

    errors: list[str] = []
    grouped: dict[str, dict[str, object]] = {}
    for catalog_id in requested_ids:
        catalog = catalog_by_id.get(catalog_id)
        if not catalog:
            errors.append(f"商品资料 {catalog_id} 不存在")
            continue
        product = catalog.source_product
        item_code = (product.data.item_code if product and product.data else None) or catalog.item_code or str(catalog_id)
        if catalog.confirmed_at is None:
            errors.append(f"{item_code}: 还不是待导出商品")
            continue
        existing_asin = _catalog_existing_asin(product, catalog)
        if existing_asin:
            errors.append(f"{item_code}: 已有真实 ASIN {existing_asin}，不能再次导出")
            continue
        if catalog.id in active_catalog_ids:
            errors.append(f"{item_code}: 已在导出任务中")
            continue
        available, template_name, template_path, template_error = _template_status_for_catalog(product, catalog)
        if not available:
            errors.append(f"{item_code}: 类目模板未就绪：{template_error or '缺模板'}")
            continue
        category = _catalog_category(product, catalog)
        template_key = str(Path(str(template_path or template_name or "unknown_template")).expanduser().resolve())
        group = grouped.setdefault(
            template_key,
            {
                "items": [],
                "template_name": template_name,
                "template_path": template_path,
                "categories": [],
                "item_codes": [],
            },
        )
        (group["items"]).append(catalog)
        if category not in group["categories"]:
            (group["categories"]).append(category)
        (group["item_codes"]).append(item_code)

    if not grouped:
        await db.commit()
        return [], errors

    now = datetime.now()
    created_tasks: list[OfflineTask] = []
    requested_count = len(requested_ids)
    for _template_key, group in sorted(grouped.items(), key=lambda pair: str(pair[1].get("template_name") or pair[0])):
        items = group["items"]
        catalog_ids = [item.id for item in items]
        categories = sorted(str(category) for category in (group.get("categories") or []))
        template_name = str(group.get("template_name") or Path(str(group.get("template_path") or "amazon_template")).name)
        category_label = "、".join(categories[:3]) + (f" 等{len(categories)}类目" if len(categories) > 3 else "")
        task = OfflineTask(
            task_type="catalog_export",
            title=f"导出Amazon表格：{template_name}（{len(items)} 个商品）",
            status="pending",
            total_steps=1,
            success_steps=0,
            failed_steps=0,
            running_steps=0,
            payload_json=_json_dumps({
                "categories": categories,
                "catalog_product_ids": catalog_ids,
                "item_codes": group.get("item_codes") or [],
                "template_name": template_name,
                "template_path": group.get("template_path"),
                "requested_catalog_product_ids": requested_ids,
                "requested_count": requested_count,
                "errors": errors,
            }),
            created_at=now,
            updated_at=now,
        )
        db.add(task)
        await db.flush()
        db.add(
            OfflineTaskStep(
                task_id=task.id,
                step_type="catalog_export_template",
                title=f"按模板生成导出文件：{template_name}",
                status="pending",
                progress_current=0,
                progress_total=len(items),
                payload_json=_json_dumps({
                    "categories": categories,
                    "category_label": category_label,
                    "catalog_product_ids": catalog_ids,
                    "item_codes": group.get("item_codes") or [],
                    "template_name": template_name,
                    "template_path": group.get("template_path"),
                }),
                updated_at=now,
            )
        )
        created_tasks.append(task)

    await db.commit()
    for task in created_tasks:
        await db.refresh(task)
        if auto_start:
            _schedule_offline_task(task.id)
    return created_tasks, errors


async def _active_aplus_product_ids(db: AsyncSession) -> set[int]:
    result = await db.execute(
        select(OfflineTaskStep).where(
            OfflineTaskStep.step_type == "aplus_generate_product",
            OfflineTaskStep.status.in_(("pending", "running", "paused")),
        )
    )
    active_ids: set[int] = set()
    for step in result.scalars().all():
        payload = _json_loads(step.payload_json, {})
        if not isinstance(payload, dict):
            continue
        try:
            product_id = int(payload.get("product_id") or 0)
        except (TypeError, ValueError):
            product_id = 0
        if product_id > 0:
            active_ids.add(product_id)
    return active_ids


def _aplus_ready_error(product: Product | None, catalog: CatalogProduct | None) -> str | None:
    if not product:
        return "缺少关联商品，不能生成 A+"
    if not catalog or catalog.confirmed_at is None:
        return "未加入待导出，不能生成 A+"
    if is_running(product.id):
        return "商品主流程仍在运行，不能生成 A+"
    if not product.data or not product.data.listing_title or not product.data.listing_bullets:
        return "Listing 文案未完成，不能生成 A+"
    if not product.images or not product.images.image_analysis:
        return "图片分析未完成，不能生成 A+"
    return None


async def create_aplus_generate_task(
    db: AsyncSession,
    catalog_product_ids: list[int],
    *,
    force: bool = False,
    auto_start: bool = True,
) -> tuple[OfflineTask | None, list[str], list[int]]:
    requested_ids = list(dict.fromkeys(int(item_id) for item_id in catalog_product_ids))
    if not requested_ids:
        raise ValueError("请选择要生成 A+ 的商品")

    result = await db.execute(
        select(CatalogProduct)
        .where(CatalogProduct.id.in_(requested_ids))
        .options(
            selectinload(CatalogProduct.source_product).selectinload(Product.data),
            selectinload(CatalogProduct.source_product).selectinload(Product.images),
            selectinload(CatalogProduct.source_product).selectinload(Product.aplus),
        )
    )
    catalog_items = result.scalars().all()
    catalog_by_id = {item.id: item for item in catalog_items}
    active_product_ids = await _active_aplus_product_ids(db)
    errors: list[str] = []
    eligible: list[tuple[CatalogProduct, Product]] = []
    now = datetime.now()

    for catalog_id in requested_ids:
        catalog = catalog_by_id.get(catalog_id)
        if not catalog:
            errors.append(f"商品资料 {catalog_id} 不存在")
            continue
        product = catalog.source_product
        ready_error = _aplus_ready_error(product, catalog)
        if ready_error:
            errors.append(f"商品资料 {catalog_id}: {ready_error}")
            continue
        if product.id in active_product_ids:
            errors.append(f"商品 {product.id} A+ 已在任务中心生成中")
            continue
        if not product.aplus:
            product.aplus = ProductAplus(product_id=product.id)
            db.add(product.aplus)
            await db.flush()
        if product.aplus.aplus_status in APLUS_GENERATE_ACTIVE_STATUSES:
            errors.append(f"商品 {product.id} A+ 已在生成中")
            continue
        if product.aplus.aplus_status == "done" and not force:
            errors.append(f"商品 {product.id} A+ 已生成，如需重跑请使用强制重跑")
            continue
        product.aplus.aplus_status = "queued"
        if product.error_message and product.error_message.startswith("A+生成"):
            product.error_message = None
        product.updated_at = now
        catalog.updated_at = now
        eligible.append((catalog, product))

    if not eligible:
        await db.commit()
        return None, errors, []

    task = OfflineTask(
        task_type="aplus_generate",
        title=f"A+生成（{len(eligible)} 个商品）",
        status="pending",
        total_steps=len(eligible),
        success_steps=0,
        failed_steps=0,
        running_steps=0,
        payload_json=_json_dumps({
            "catalog_product_ids": [catalog.id for catalog, _ in eligible],
            "requested_catalog_product_ids": requested_ids,
            "force": force,
            "errors": errors,
        }),
        created_at=now,
        updated_at=now,
    )
    db.add(task)
    await db.flush()

    for catalog, product in eligible:
        item_code = product.data.item_code if product.data else None
        title = item_code or f"Product {product.id}"
        db.add(
            OfflineTaskStep(
                task_id=task.id,
                step_type="aplus_generate_product",
                title=f"A+生成：{title}",
                status="pending",
                progress_current=0,
                progress_total=3,
                payload_json=_json_dumps({
                    "catalog_product_id": catalog.id,
                    "product_id": product.id,
                    "item_code": item_code,
                    "force": force,
                }),
                updated_at=now,
            )
        )

    await db.commit()
    await db.refresh(task)
    if auto_start:
        _schedule_offline_task(task.id)
    return task, errors, [product.id for _, product in eligible]


async def rerun_offline_task(db: AsyncSession, task_id: int) -> OfflineTask:
    task = await db.get(OfflineTask, task_id)
    if not task:
        raise ValueError("任务不存在")
    if task.task_type not in SUPPORTED_TASK_TYPES:
        raise ValueError("当前任务类型暂不支持重跑")
    result = await db.execute(
        select(OfflineTaskStep).where(
            OfflineTaskStep.task_id == task_id,
            OfflineTaskStep.status.in_(("failed", "interrupted")),
        )
    )
    steps = result.scalars().all()
    if not steps:
        raise ValueError("没有可重跑的失败步骤")
    for step in steps:
        step.status = "pending"
        step.error_message = None
        step.finished_at = None
        step.updated_at = datetime.now()
    task.status = "pending"
    task.finished_at = None
    task.error_message = None
    await _refresh_task_stats(db, task_id)
    await db.commit()
    _schedule_offline_task(task_id, [step.id for step in steps])
    await db.refresh(task)
    return task


async def recover_offline_tasks() -> None:
    affected_task_ids: set[int] = set()
    async with async_session() as db:
        result = await db.execute(select(OfflineTask).where(OfflineTask.status.in_(("running", "interrupted"))))
        tasks = result.scalars().all()
        for task in tasks:
            affected_task_ids.add(task.id)
            if task.status == "running":
                task.status = "interrupted"
                task.error_message = "服务重启导致任务中断，系统正在恢复执行。"
                task.finished_at = None
            task.updated_at = datetime.now()
        step_result = await db.execute(select(OfflineTaskStep).where(OfflineTaskStep.status.in_(("running", "interrupted"))))
        steps = step_result.scalars().all()
        for step in steps:
            affected_task_ids.add(step.task_id)
            if step.status == "running":
                step.status = "interrupted"
                step.error_message = "服务重启导致步骤中断，系统正在恢复执行。"
                step.finished_at = None
            step.updated_at = datetime.now()
        for task_id in affected_task_ids:
            await _refresh_task_stats(db, task_id)

        active_aplus_ids = await _active_aplus_product_ids(db)
        orphan_result = await db.execute(
            select(Product)
            .join(ProductAplus)
            .where(ProductAplus.aplus_status.in_(APLUS_GENERATE_ACTIVE_STATUSES))
            .options(selectinload(Product.aplus), selectinload(Product.catalog_item))
        )
        now = datetime.now()
        for product in orphan_result.scalars().all():
            if product.id in active_aplus_ids:
                continue
            if product.aplus:
                product.aplus.aplus_status = "failed"
            product.error_message = "A+生成失败: 旧后台任务已中断，请重新发起 A+生成。"
            product.updated_at = now
            if product.catalog_item:
                product.catalog_item.updated_at = now
        await db.commit()
    for task_id in affected_task_ids:
        _schedule_offline_task(task_id)


async def cancel_active_offline_tasks() -> None:
    tasks = [task for task in _active_offline_tasks.values() if not task.done()]
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    _active_offline_tasks.clear()
