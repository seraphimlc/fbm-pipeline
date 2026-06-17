from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.schemas import OfflineTaskCatalogExportRequest
from app.models import CatalogProduct, OfflineTaskStep, Product, TaskGroup, TaskRun, TaskStep
from app.task_runtime.constants import STEP_STATUS_PENDING, STEP_STATUS_READY
from app.task_runtime.json_utils import json_dumps, json_loads
from app.task_runtime.scheduler import kick_task_runtime


async def _active_export_catalog_ids(db: AsyncSession) -> set[int]:
    active_ids: set[int] = set()
    old_result = await db.execute(
        select(OfflineTaskStep).where(
            OfflineTaskStep.step_type == "catalog_export_template",
            OfflineTaskStep.status.in_(("pending", "running", "paused")),
        )
    )
    for step in old_result.scalars().all():
        payload = json_loads(step.payload_json, {})
        if not isinstance(payload, dict):
            continue
        for catalog_id in payload.get("catalog_product_ids") or []:
            if str(catalog_id).isdigit():
                active_ids.add(int(catalog_id))

    new_result = await db.execute(
        select(TaskStep).where(
            TaskStep.step_type == "catalog_export_template",
            TaskStep.status.in_(("pending", "ready", "running")),
        )
    )
    for step in new_result.scalars().all():
        payload = json_loads(step.payload_json, {})
        if not isinstance(payload, dict):
            continue
        for catalog_id in payload.get("catalog_product_ids") or []:
            if str(catalog_id).isdigit():
                active_ids.add(int(catalog_id))
    return active_ids


async def create_catalog_export_runs(
    db: AsyncSession,
    body: OfflineTaskCatalogExportRequest,
    *,
    created_by: str | None = "web",
    auto_start: bool = True,
) -> tuple[list[TaskRun], list[str]]:
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

    from app.api.products import _catalog_category, _template_status_for_catalog

    errors: list[str] = []
    grouped: dict[str, dict[str, object]] = {}
    for catalog_id in requested_ids:
        catalog = catalog_by_id.get(catalog_id)
        if not catalog:
            errors.append(f"商品资料 {catalog_id} 不存在")
            continue
        product = catalog.source_product
        item_code = (product.data.item_code if product and product.data else None) or catalog.item_code or str(catalog_id)
        if catalog.id in active_catalog_ids:
            errors.append(f"{item_code}: 已在导出任务中")
            continue
        available, template_name, template_path, template_error = _template_status_for_catalog(product, catalog)
        category = _catalog_category(product, catalog)
        template_key = str(Path(str(template_path)).expanduser().resolve()) if available and template_path else f"__report_only__:{category}"
        group = grouped.setdefault(
            template_key,
            {
                "items": [],
                "template_name": template_name or ("待报告商品" if not available else None),
                "template_path": template_path,
                "template_error": template_error,
                "categories": [],
                "item_codes": [],
            },
        )
        group["items"].append(catalog)
        if category not in group["categories"]:
            group["categories"].append(category)
        group["item_codes"].append(item_code)

    if not grouped:
        await db.commit()
        return [], errors

    now = datetime.now()
    runs: list[TaskRun] = []
    requested_count = len(requested_ids)
    for template_key, group in sorted(grouped.items(), key=lambda pair: str(pair[1].get("template_name") or pair[0])):
        items = group["items"]
        catalog_ids = [item.id for item in items]
        categories = sorted(str(category) for category in (group.get("categories") or []))
        template_name = str(group.get("template_name") or Path(str(group.get("template_path") or "amazon_template")).name)
        category_label = "、".join(categories[:3]) + (f" 等{len(categories)}类目" if len(categories) > 3 else "")
        run = TaskRun(
            task_type="catalog_export",
            title=f"导出Amazon表格：{template_name}（{len(items)} 个商品）",
            status="pending",
            created_by=created_by,
            payload_json=json_dumps({
                "categories": categories,
                "catalog_product_ids": catalog_ids,
                "item_codes": group.get("item_codes") or [],
                "template_name": template_name,
                "template_path": group.get("template_path"),
                "requested_catalog_product_ids": requested_ids,
                "requested_count": requested_count,
                "errors": errors,
                "task_source": "task_run",
            }),
            created_at=now,
            updated_at=now,
        )
        db.add(run)
        await db.flush()
        task_group = TaskGroup(
            task_run_id=run.id,
            group_key="export_file",
            title="导出文件",
            status="pending",
            sort_order=1,
            depends_on_group_keys_json=json_dumps([]),
            failure_policy="require_all_success",
            retry_policy="failed_steps_only",
            progress_current=0,
            progress_total=1,
            created_at=now,
            updated_at=now,
        )
        db.add(task_group)
        await db.flush()
        db.add(
            TaskStep(
                task_run_id=run.id,
                task_group_id=task_group.id,
                step_key="catalog_export_template",
                step_type="catalog_export_template",
                status=STEP_STATUS_READY if auto_start else STEP_STATUS_PENDING,
                sort_order=1,
                progress_current=0,
                progress_total=len(items),
                payload_json=json_dumps({
                    "categories": categories,
                    "category_label": category_label,
                    "catalog_product_ids": catalog_ids,
                    "item_codes": group.get("item_codes") or [],
                    "template_name": template_name,
                    "template_path": group.get("template_path"),
                    "template_key": template_key,
                    "task_source": "task_run",
                }),
                max_attempts=2,
                created_at=now,
                updated_at=now,
            )
        )
        runs.append(run)

    await db.commit()
    for run in runs:
        await db.refresh(run)
    if auto_start:
        kick_task_runtime()
    return runs, errors
