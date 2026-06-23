from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.models import AplusUploadItem, CatalogProduct, Product, TaskGroup, TaskRun, TaskStep
from app.services.asin_match_policy import seller_sku_candidate
from app.services.lingxing_aplus_module_mapper import preflight_validate
from app.services.lingxing_aplus_publish_policy import build_aplus_content_fingerprint, collect_aplus_publish_assets
from app.task_runtime.constants import STEP_STATUS_PENDING, STEP_STATUS_READY
from app.task_runtime.json_utils import json_dumps
from app.task_runtime.scheduler import kick_task_runtime


ACTIVE_RUN_STATUSES = {"pending", "running"}
PROTECTED_DRAFT_STATUSES = {"draft_saved", "draft_visible", "submitted", "uploading"}


def _clean_optional(value: str | int | None) -> str | None:
    cleaned = str(value or "").strip()
    return cleaned or None


def _base_dedupe_key(*, product_id: int, product_aplus_id: int | None, fingerprint: str) -> str:
    aplus_key = product_aplus_id or "missing"
    return f"lingxing_aplus_publish:product:{product_id}:aplus:{aplus_key}:fp:{fingerprint}"


async def _existing_draft_item(db: AsyncSession, catalog: CatalogProduct) -> AplusUploadItem | None:
    product_aplus_id = getattr(getattr(catalog.source_product, "aplus", None), "id", None)
    query = (
        select(AplusUploadItem)
        .where(AplusUploadItem.catalog_product_id == catalog.id)
        .where(AplusUploadItem.lingxing_aplus_id_hash.is_not(None))
        .order_by(AplusUploadItem.id.desc())
        .limit(1)
    )
    if product_aplus_id:
        query = query.where(AplusUploadItem.product_aplus_id == product_aplus_id)
    return (await db.execute(query)).scalar_one_or_none()


async def create_lingxing_aplus_publish_runs(
    db: AsyncSession,
    catalog_product_ids: list[int],
    *,
    store_name: str | None = None,
    store_id: str | int | None = None,
    site: str | None = None,
    created_by: str | None = "web",
    auto_start: bool = True,
) -> tuple[list[TaskRun], list[str]]:
    requested_ids = list(dict.fromkeys(int(item_id) for item_id in catalog_product_ids))
    if not requested_ids:
        raise ValueError("请选择要保存 A+ 草稿的商品")
    if len(requested_ids) > 1000:
        raise ValueError("单次最多创建 1000 个 A+ 草稿保存任务")

    result = await db.execute(
        select(CatalogProduct)
        .where(CatalogProduct.id.in_(requested_ids))
        .options(
            selectinload(CatalogProduct.source_product).selectinload(Product.data),
            selectinload(CatalogProduct.source_product).selectinload(Product.aplus),
        )
    )
    catalog_by_id = {item.id: item for item in result.scalars().all()}
    errors: list[str] = []
    runs: list[TaskRun] = []
    now = datetime.now()
    default_store_id = _clean_optional(store_id) or _clean_optional(settings.LINGXING_APLUS_STORE_ID)
    default_site = _clean_optional(site) or _clean_optional(settings.LINGXING_APLUS_SITE)

    for catalog_id in requested_ids:
        catalog = catalog_by_id.get(catalog_id)
        if not catalog:
            errors.append(f"商品资料 {catalog_id} 不存在")
            continue
        product = catalog.source_product
        if not product:
            errors.append(f"商品资料 {catalog_id} 缺少源商品")
            continue

        existing_draft = await _existing_draft_item(db, catalog)
        if (
            (catalog.aplus_upload_status or "").strip() in PROTECTED_DRAFT_STATUSES
            and existing_draft
            and existing_draft.lingxing_aplus_id_hash
        ):
            errors.append(f"商品资料 {catalog.id} 已有 draft_saved/idHash，停止重复创建草稿")
            continue

        assets_result = collect_aplus_publish_assets(product)
        if assets_result.ok:
            module_mapping = preflight_validate(product, assets_result.assets)
            fingerprint = (
                build_aplus_content_fingerprint(
                    product.aplus,
                    assets_result.assets,
                    module_mapping_evidence=module_mapping.evidence,
                )
                if module_mapping.ok
                else f"invalid-{module_mapping.reason_code or 'module_mapping'}"
            )
        else:
            fingerprint = f"invalid-{assets_result.reason_code or 'assets'}"
        dedupe_key = _base_dedupe_key(
            product_id=product.id,
            product_aplus_id=getattr(product.aplus, "id", None),
            fingerprint=fingerprint,
        )
        existing = (
            await db.execute(
                select(TaskRun)
                .where(TaskRun.dedupe_key == dedupe_key)
                .where(TaskRun.status.in_(tuple(ACTIVE_RUN_STATUSES)))
            )
        ).scalar_one_or_none()
        if existing:
            runs.append(existing)
            continue

        seller_sku = seller_sku_candidate(catalog).value
        asin = _clean_optional(catalog.amazon_asin) or _clean_optional(product.amazon_asin)
        title_sku = seller_sku or catalog.item_code or f"catalog-{catalog.id}"
        payload = {
            "catalog_product_id": catalog.id,
            "product_id": product.id,
            "product_aplus_id": getattr(product.aplus, "id", None),
            "seller_sku": seller_sku,
            "asin": asin,
            "store_name": _clean_optional(store_name) or _clean_optional(settings.LINGXING_APLUS_STORE_NAME),
            "store_id": default_store_id,
            "site": default_site,
            "aplus_content_fingerprint": fingerprint,
        }
        run = TaskRun(
            task_type="lingxing_aplus_publish",
            title=f"领星 A+ 草稿保存：{title_sku}",
            status="pending",
            created_by=created_by,
            dedupe_key=dedupe_key,
            correlation_key=f"product:{product.id}:lingxing_aplus_publish",
            idempotency_key=dedupe_key,
            payload_json=json_dumps(payload),
            created_at=now,
            updated_at=now,
        )
        db.add(run)
        await db.flush()
        group = TaskGroup(
            task_run_id=run.id,
            group_key="aplus_publish",
            title="保存领星 A+ 草稿",
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
        db.add(group)
        await db.flush()
        db.add(
            TaskStep(
                task_run_id=run.id,
                task_group_id=group.id,
                step_key=f"catalog:{catalog.id}:lingxing_aplus_publish_product",
                step_type="lingxing_aplus_publish_product",
                status=STEP_STATUS_READY if auto_start else STEP_STATUS_PENDING,
                sort_order=1,
                payload_json=run.payload_json,
                progress_current=0,
                progress_total=1,
                max_attempts=2,
                created_at=now,
                updated_at=now,
            )
        )
        runs.append(run)

    await db.commit()
    for run in runs:
        await db.refresh(run)
    if auto_start and runs:
        kick_task_runtime()
    return runs, errors
