import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import GigaInventory, GigaInventoryAlert, GigaSku, GigaSyncBatch
from app.services.giga_openapi import (
    API_INVENTORY,
    GigaDataSourceContext,
    GigaOpenApiClient,
    GigaOpenApiError,
    SOURCE_PLATFORM,
    resolve_giga_data_source_context,
)

logger = logging.getLogger(__name__)

INVENTORY_SNAPSHOT_CATEGORY = "inventory_snapshot"
PRICE_SNAPSHOT_CATEGORY = "price_snapshot"
GIGA_DYNAMIC_SNAPSHOT_CATEGORIES = {INVENTORY_SNAPSHOT_CATEGORY, PRICE_SNAPSHOT_CATEGORY}
VALID_GIGA_SITES = {"US", "JP"}


@dataclass(frozen=True)
class GigaInventorySyncOptions:
    batch_id: str
    site: str
    data_source_id: int
    task_id: str | None = None
    sku_codes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class GigaInventorySyncResult:
    batch_id: str
    site: str
    data_source_id: int | None
    data_source_name: str | None
    task_id: str | None
    total_skus: int
    success_count: int
    failed_count: int
    alert_count: int
    out_of_stock_count: int
    restocked_count: int
    previous_batch_id: str | None
    pulled_at: datetime
    failed_skus: list[dict[str, str]]


def validate_giga_site(site: str) -> str:
    normalized = (site or "").strip().upper()
    if not normalized:
        raise GigaOpenApiError("site is required; must be US or JP")
    if normalized not in VALID_GIGA_SITES:
        raise GigaOpenApiError(f"invalid site: {site}; must be US or JP")
    return normalized


def validate_inventory_sync_context(options: GigaInventorySyncOptions) -> GigaInventorySyncOptions:
    batch_id = (options.batch_id or "").strip()
    if not batch_id:
        raise GigaOpenApiError("batch_id is required")
    return GigaInventorySyncOptions(
        batch_id=batch_id,
        site=validate_giga_site(options.site),
        data_source_id=options.data_source_id,
        task_id=(options.task_id or "").strip() or None,
        sku_codes=_normalize_sku_codes(options.sku_codes),
    )


def _normalize_sku_codes(sku_codes: list[str]) -> list[str]:
    return list(dict.fromkeys(str(sku).strip() for sku in sku_codes if str(sku or "").strip()))


def _chunks(items: list[str], size: int) -> list[list[str]]:
    return [items[index:index + size] for index in range(0, len(items), size)]


def _int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _stock_qty(record: dict[str, Any]) -> int:
    seller = record.get("sellerInventoryInfo") or {}
    buyer = record.get("buyerInventoryInfo") or {}
    seller_qty = _int(seller.get("sellerAvailableInventory"))
    buyer_qty = _int(buyer.get("totalBuyerAvailableInventory"))
    if seller_qty is not None and seller_qty > 0:
        return seller_qty
    if buyer_qty is not None and buyer_qty > 0:
        return buyer_qty
    if seller_qty is not None:
        return seller_qty
    if buyer_qty is not None:
        return buyer_qty
    return 0


def _stock_status(stock_qty: int | None) -> str:
    return "in_stock" if (stock_qty or 0) > 0 else "out_of_stock"


async def _latest_product_skus(db: AsyncSession, site: str, data_source_id: int | None) -> list[str]:
    batch_query = (
        select(GigaSyncBatch)
        .where(
            GigaSyncBatch.site == site,
            GigaSyncBatch.status == "done",
            GigaSyncBatch.sku_count > 0,
            or_(
                GigaSyncBatch.current_category.is_(None),
                GigaSyncBatch.current_category.notin_(GIGA_DYNAMIC_SNAPSHOT_CATEGORIES),
            ),
        )
        .order_by(GigaSyncBatch.created_at.desc())
        .limit(1)
    )
    if data_source_id:
        batch_query = batch_query.where(GigaSyncBatch.data_source_id == data_source_id)
    batch_result = await db.execute(batch_query)
    batch = batch_result.scalar_one_or_none()
    if not batch:
        source_part = f", data_source_id={data_source_id}" if data_source_id else ""
        raise GigaOpenApiError(f"site={site}{source_part} 没有可用于库存同步的 GIGA SKU 商品池，请先执行商品同步")
    sku_query = (
        select(GigaSku.sku_code)
        .where(GigaSku.batch_id == batch.batch_id, GigaSku.site == site)
        .order_by(GigaSku.sku_code.asc())
    )
    if data_source_id:
        sku_query = sku_query.where(GigaSku.data_source_id == data_source_id)
    sku_result = await db.execute(sku_query)
    sku_codes = _normalize_sku_codes([row[0] for row in sku_result.fetchall()])
    if not sku_codes:
        raise GigaOpenApiError(f"site={site} 最新商品池 batch={batch.batch_id} 没有 SKU")
    return sku_codes


async def _fetch_inventory_resilient(
    client: GigaOpenApiClient,
    sku_codes: list[str],
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    records: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    for batch in _chunks(sku_codes, 200):
        try:
            data = await client.call(API_INVENTORY, {"skus": batch})
            batch_records = data.get("data", [])
            if isinstance(batch_records, list):
                records.extend([item for item in batch_records if isinstance(item, dict)])
            await asyncio.sleep(0.2)
            continue
        except Exception as batch_exc:
            logger.warning("[GIGA Inventory] batch inventory fetch failed, fallback to single SKU: %s", batch_exc)

        for sku_code in batch:
            try:
                data = await client.call(API_INVENTORY, {"skus": [sku_code]})
                item_records = data.get("data", [])
                if isinstance(item_records, list):
                    records.extend([item for item in item_records if isinstance(item, dict)])
                await asyncio.sleep(0.2)
            except Exception as exc:
                failures.append({"sku_code": sku_code, "error": f"{type(exc).__name__}: {exc}"})
    return records, failures


async def _upsert_snapshot_batch(
    db: AsyncSession,
    options: GigaInventorySyncOptions,
    context: GigaDataSourceContext,
    total_skus: int,
    pulled_at: datetime,
) -> GigaSyncBatch:
    result = await db.execute(
        select(GigaSyncBatch).where(
            GigaSyncBatch.batch_id == options.batch_id,
            GigaSyncBatch.site == options.site,
            GigaSyncBatch.data_source_id == context.id,
        )
    )
    batch = result.scalar_one_or_none()
    if not batch:
        batch = GigaSyncBatch(batch_id=options.batch_id, site=options.site)
        db.add(batch)
    batch.task_id = options.task_id
    batch.data_source_id = context.id
    batch.data_source_name = context.name
    batch.fulfillment_mode = context.fulfillment_mode
    batch.current_category = INVENTORY_SNAPSHOT_CATEGORY
    batch.status = "running"
    batch.source_platform = SOURCE_PLATFORM
    batch.sku_count = total_skus
    batch.started_at = pulled_at
    batch.error_message = None
    await db.flush()
    return batch


async def _previous_inventory_batch_id(
    db: AsyncSession,
    batch_id: str,
    site: str,
    data_source_id: int | None,
) -> str | None:
    query = (
        select(GigaSyncBatch.batch_id)
        .where(
            GigaSyncBatch.site == site,
            GigaSyncBatch.batch_id != batch_id,
            GigaSyncBatch.status == "done",
            GigaSyncBatch.inventory_count > 0,
        )
        .order_by(GigaSyncBatch.finished_at.is_(None).asc(), GigaSyncBatch.finished_at.desc(), GigaSyncBatch.created_at.desc())
        .limit(1)
    )
    if data_source_id:
        query = query.where(GigaSyncBatch.data_source_id == data_source_id)
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def _sku_metadata(db: AsyncSession, site: str, sku_codes: list[str], data_source_id: int | None) -> dict[str, GigaSku]:
    batch_query = (
        select(GigaSyncBatch.batch_id)
        .where(
            GigaSyncBatch.site == site,
            GigaSyncBatch.status == "done",
            GigaSyncBatch.sku_count > 0,
            or_(
                GigaSyncBatch.current_category.is_(None),
                GigaSyncBatch.current_category.notin_(GIGA_DYNAMIC_SNAPSHOT_CATEGORIES),
            ),
        )
        .order_by(GigaSyncBatch.created_at.desc())
        .limit(1)
    )
    if data_source_id:
        batch_query = batch_query.where(GigaSyncBatch.data_source_id == data_source_id)
    batch_result = await db.execute(batch_query)
    product_batch_id = batch_result.scalar_one_or_none()
    if not product_batch_id:
        return {}
    sku_query = (
        select(GigaSku).where(
            GigaSku.batch_id == product_batch_id,
            GigaSku.site == site,
            GigaSku.sku_code.in_(sku_codes),
        )
    )
    if data_source_id:
        sku_query = sku_query.where(GigaSku.data_source_id == data_source_id)
    result = await db.execute(sku_query)
    return {sku.sku_code: sku for sku in result.scalars().all()}


async def _previous_inventory_by_sku(
    db: AsyncSession,
    previous_batch_id: str | None,
    site: str,
    sku_codes: list[str],
    data_source_id: int | None,
) -> dict[str, GigaInventory]:
    if not previous_batch_id or not sku_codes:
        return {}
    query = (
        select(GigaInventory).where(
            GigaInventory.batch_id == previous_batch_id,
            GigaInventory.site == site,
            GigaInventory.sku_code.in_(sku_codes),
        )
    )
    if data_source_id:
        query = query.where(GigaInventory.data_source_id == data_source_id)
    result = await db.execute(query)
    return {row.sku_code: row for row in result.scalars().all()}


def _alert_for_change(
    *,
    batch_id: str,
    site: str,
    data_source_id: int | None,
    sku_code: str,
    current_stock: int,
    previous: GigaInventory,
    metadata: GigaSku | None,
) -> GigaInventoryAlert | None:
    previous_stock = previous.stock_qty
    if previous_stock is None:
        previous_stock = previous.seller_available_inventory
    if previous_stock is None:
        previous_stock = previous.total_buyer_available_inventory
    previous_status = _stock_status(previous_stock)
    current_status = _stock_status(current_stock)
    if previous_status == current_status:
        return None
    change_type = "restocked" if current_status == "in_stock" else "out_of_stock"
    item_code = metadata.item_code if metadata else None
    product_name = metadata.product_name if metadata else None
    label = item_code or sku_code
    message = (
        f"{label} 库存从无货变为有货: {previous_stock or 0} -> {current_stock}"
        if change_type == "restocked"
        else f"{label} 库存从有货变为无货: {previous_stock or 0} -> {current_stock}"
    )
    return GigaInventoryAlert(
        batch_id=batch_id,
        site=site,
        data_source_id=data_source_id,
        sku_code=sku_code,
        item_code=item_code,
        product_name=product_name,
        previous_batch_id=previous.batch_id,
        previous_stock_qty=previous_stock,
        current_stock_qty=current_stock,
        previous_status=previous_status,
        current_status=current_status,
        change_type=change_type,
        message=message,
        source_platform=SOURCE_PLATFORM,
        created_at=datetime.now(),
    )


async def sync_giga_inventory_snapshot(
    db: AsyncSession,
    options: GigaInventorySyncOptions,
) -> GigaInventorySyncResult:
    options = validate_inventory_sync_context(options)
    context = await resolve_giga_data_source_context(db, options.data_source_id, options.site)
    options = GigaInventorySyncOptions(
        batch_id=options.batch_id,
        site=context.site,
        data_source_id=context.id,
        task_id=options.task_id,
        sku_codes=options.sku_codes,
    )
    pulled_at = datetime.now()
    sku_codes = options.sku_codes or await _latest_product_skus(db, options.site, options.data_source_id)

    batch = await _upsert_snapshot_batch(db, options, context, len(sku_codes), pulled_at)
    await db.execute(delete(GigaInventory).where(
        GigaInventory.batch_id == options.batch_id,
        GigaInventory.site == options.site,
        GigaInventory.data_source_id == options.data_source_id,
    ))
    await db.execute(delete(GigaInventoryAlert).where(
        GigaInventoryAlert.batch_id == options.batch_id,
        GigaInventoryAlert.site == options.site,
        GigaInventoryAlert.data_source_id == options.data_source_id,
    ))
    await db.commit()

    try:
        records, failures = await _fetch_inventory_resilient(
            GigaOpenApiClient(
                client_id=context.client_id,
                client_secret=context.client_secret,
                api_base=context.api_base,
            ),
            sku_codes,
        )
    except Exception as exc:
        result = await db.execute(
            select(GigaSyncBatch).where(
                GigaSyncBatch.batch_id == options.batch_id,
                GigaSyncBatch.site == options.site,
                GigaSyncBatch.data_source_id == options.data_source_id,
            )
        )
        failed_batch = result.scalar_one_or_none()
        if failed_batch:
            failed_batch.status = "failed"
            failed_batch.error_message = f"{type(exc).__name__}: {exc}"
            failed_batch.finished_at = datetime.now()
            await db.commit()
        raise
    records_by_sku = {
        str(record.get("sku")).strip(): record
        for record in records
        if str(record.get("sku") or "").strip()
    }
    failed_codes = {item["sku_code"] for item in failures}
    missing_skus = [sku for sku in sku_codes if sku not in records_by_sku and sku not in failed_codes]
    failures.extend({"sku_code": sku, "error": "GIGA Open API 未返回该 SKU 库存"} for sku in missing_skus)

    success_skus = [sku for sku in sku_codes if sku in records_by_sku]
    previous_batch_id = await _previous_inventory_batch_id(db, options.batch_id, options.site, options.data_source_id)
    previous_by_sku = await _previous_inventory_by_sku(
        db,
        previous_batch_id,
        options.site,
        success_skus,
        options.data_source_id,
    )
    metadata_by_sku = await _sku_metadata(db, options.site, success_skus, options.data_source_id)

    inventory_rows: list[GigaInventory] = []
    alert_rows: list[GigaInventoryAlert] = []
    for sku_code in success_skus:
        record = records_by_sku[sku_code]
        seller = record.get("sellerInventoryInfo") or {}
        buyer = record.get("buyerInventoryInfo") or {}
        stock_qty = _stock_qty(record)
        inventory_rows.append(GigaInventory(
            batch_id=options.batch_id,
            site=options.site,
            data_source_id=options.data_source_id,
            fulfillment_mode=context.fulfillment_mode,
            inventory_mode=context.inventory_mode,
            sku_code=sku_code,
            task_id=options.task_id,
            stock_qty=stock_qty,
            seller_available_inventory=_int(seller.get("sellerAvailableInventory")),
            total_buyer_available_inventory=_int(buyer.get("totalBuyerAvailableInventory")),
            seller_inventory_distribution=_json_dump(seller.get("sellerInventoryDistribution") or []),
            buyer_inventory_distribution=_json_dump(buyer.get("buyerInventoryDistribution") or []),
            next_arrival_inventory=_json_dump(seller.get("nextArrivalInventory") or {}),
            availability_status=_stock_status(stock_qty),
            source_platform=SOURCE_PLATFORM,
            pulled_at=pulled_at,
        ))
        previous = previous_by_sku.get(sku_code)
        if previous:
            alert = _alert_for_change(
                batch_id=options.batch_id,
                site=options.site,
                data_source_id=options.data_source_id,
                sku_code=sku_code,
                current_stock=stock_qty,
                previous=previous,
                metadata=metadata_by_sku.get(sku_code),
            )
            if alert:
                alert_rows.append(alert)

    result = await db.execute(
        select(GigaSyncBatch).where(
            GigaSyncBatch.batch_id == options.batch_id,
            GigaSyncBatch.site == options.site,
            GigaSyncBatch.data_source_id == options.data_source_id,
        )
    )
    batch = result.scalar_one()
    db.add_all(inventory_rows + alert_rows)
    batch.status = "done"
    batch.inventory_count = len(inventory_rows)
    batch.finished_at = datetime.now()
    batch.error_message = None if not failures else f"{len(failures)} 个 SKU 库存同步失败"
    await db.commit()

    return GigaInventorySyncResult(
        batch_id=options.batch_id,
        site=options.site,
        data_source_id=options.data_source_id,
        data_source_name=context.name,
        task_id=options.task_id,
        total_skus=len(sku_codes),
        success_count=len(inventory_rows),
        failed_count=len(failures),
        alert_count=len(alert_rows),
        out_of_stock_count=sum(1 for alert in alert_rows if alert.change_type == "out_of_stock"),
        restocked_count=sum(1 for alert in alert_rows if alert.change_type == "restocked"),
        previous_batch_id=previous_batch_id,
        pulled_at=pulled_at,
        failed_skus=failures,
    )


def _json_dump(value: Any) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, sort_keys=True)
