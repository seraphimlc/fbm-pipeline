import asyncio
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.config import settings
from app.models import CatalogProduct, Product
from app.services.offline_tasks import (
    _catalog_export_result_payload,
    _catalog_export_result_ready,
    _recover_catalog_export_result_from_file,
)
from app.services.oss_uploader import upload_private_file
from app.task_runtime.events import update_step_progress
from app.task_runtime.json_utils import json_dumps, json_loads
from app.task_runtime.registry import TaskContext, register_worker


def _payload(ctx: TaskContext) -> dict[str, Any]:
    value = json_loads(ctx.step.payload_json, {})
    return value if isinstance(value, dict) else {}


def _catalog_export_task_run_object_key(run_id: int, filename: str) -> str:
    prefix = settings.OSS_EXPORT_UPLOAD_PREFIX.strip().strip("/")
    raw = Path(filename)
    safe_stem = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in raw.stem)[:90] or "catalog_export"
    safe_filename = safe_stem + (raw.suffix.lower() or ".zip")
    key = f"task_run_{run_id}/{safe_filename}"
    return f"{prefix}/{key}" if prefix else key


async def catalog_export_template(ctx: TaskContext) -> dict[str, Any]:
    payload = _payload(ctx)
    catalog_ids = list(dict.fromkeys(int(item_id) for item_id in payload.get("catalog_product_ids") or []))
    categories = [str(item) for item in (payload.get("categories") or []) if str(item).strip()]
    category = str(payload.get("category") or (categories[0] if categories else "未分类"))
    template_name = str(payload.get("template_name") or "").strip()
    if not catalog_ids:
        raise RuntimeError("导出步骤缺少商品")

    existing_result = json_loads(ctx.step.result_json, {})
    if _catalog_export_result_ready(existing_result):
        if isinstance(existing_result, dict):
            ctx.run.summary_json = json_dumps(existing_result)
            await ctx.db.commit()
            return existing_result

    from app.api.products import CatalogExportBuildError, build_catalog_export_zip

    export_dir = settings.DATA_DIR / "exports" / f"task_run_{ctx.run.id}"
    export_dir.mkdir(parents=True, exist_ok=True)
    recovered_result = _recover_catalog_export_result_from_file(
        export_dir=export_dir,
        category=category,
        categories=categories,
        template_name=template_name or None,
        template_path=payload.get("template_path"),
        catalog_ids=catalog_ids,
    )
    if recovered_result:
        recovered_result["task_source"] = "task_run"
        recovered_result["task_run_id"] = ctx.run.id
        ctx.run.summary_json = json_dumps(recovered_result)
        await ctx.db.commit()
        await update_step_progress(
            ctx.db,
            ctx.step,
            current=len(catalog_ids),
            total=len(catalog_ids),
            message="已复用已有导出文件",
            data={"catalog_product_ids": catalog_ids, "filename": recovered_result.get("filename")},
        )
        return recovered_result

    await update_step_progress(
        ctx.db,
        ctx.step,
        current=0,
        total=len(catalog_ids),
        message="开始生成 Amazon 导入表 zip",
        data={"catalog_product_ids": catalog_ids, "categories": categories},
    )
    result = await ctx.db.execute(select(CatalogProduct).where(CatalogProduct.id.in_(catalog_ids)))
    catalog_items = result.scalars().all()
    if not catalog_items:
        raise RuntimeError("导出商品不存在")

    try:
        zip_bytes, _filename, report_rows = await build_catalog_export_zip(catalog_items, ctx.db)
    except CatalogExportBuildError as exc:
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
        result_payload["task_source"] = "task_run"
        result_payload["task_run_id"] = ctx.run.id
        ctx.run.summary_json = json_dumps(result_payload)
        await ctx.db.commit()
        raise RuntimeError(exc.message) from exc

    target_path = export_dir / f"catalog_export_r{ctx.run.id}_s{ctx.step.id}.zip"
    await asyncio.to_thread(target_path.write_bytes, zip_bytes)
    uploaded = await asyncio.to_thread(upload_private_file, target_path, _catalog_export_task_run_object_key(ctx.run.id, target_path.name))
    exported_source_ids = {
        int(row.get("商品ID"))
        for row in report_rows
        if row.get("状态") == "已导出" and row.get("商品ID") is not None
    }
    exported_seller_sku_by_source_id = {
        int(row.get("商品ID")): str(row.get("Seller SKU") or "").strip()
        for row in report_rows
        if row.get("状态") == "已导出" and row.get("商品ID") is not None and str(row.get("Seller SKU") or "").strip()
    }
    exported_at = datetime.now()
    for item in catalog_items:
        if item.source_product_id in exported_source_ids:
            seller_sku = exported_seller_sku_by_source_id.get(item.source_product_id)
            item.exported_at = exported_at
            item.export_task_id = ctx.run.id
            item.export_file_path = str(uploaded.get("url") or target_path)
            if seller_sku:
                item.amazon_seller_sku = seller_sku
                product = await ctx.db.get(Product, item.source_product_id)
                if product:
                    product.amazon_seller_sku = seller_sku
                    product.updated_at = exported_at
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
    result_payload["task_source"] = "task_run"
    result_payload["task_run_id"] = ctx.run.id
    ctx.run.summary_json = json_dumps(result_payload)
    await ctx.db.commit()
    await update_step_progress(
        ctx.db,
        ctx.step,
        current=len(catalog_ids),
        total=len(catalog_ids),
        message="导出文件生成完成",
        data={
            "filename": target_path.name,
            "success_count": result_payload.get("success_count"),
            "skipped_count": result_payload.get("skipped_count"),
            "failed_count": result_payload.get("failed_count"),
        },
    )
    return result_payload


def register_catalog_export_workers() -> None:
    register_worker("catalog_export_template", catalog_export_template)
