import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import GigaPrice, GigaPriceAlert, GigaSku, GigaSyncBatch
from app.services.giga_inventory_sync import GIGA_DYNAMIC_SNAPSHOT_CATEGORIES, PRICE_SNAPSHOT_CATEGORY, validate_giga_site
from app.services.giga_openapi import (
    API_PRICE,
    GigaDataSourceContext,
    GigaOpenApiClient,
    GigaOpenApiError,
    SOURCE_PLATFORM,
    resolve_giga_data_source_context,
)

logger = logging.getLogger(__name__)
PRICE_REQUEST_INTERVAL_SECONDS = 1.05


@dataclass(frozen=True)
class GigaPriceSyncOptions:
    batch_id: str
    site: str
    data_source_id: int
    task_id: str | None = None
    sku_codes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class GigaPriceSyncResult:
    batch_id: str
    site: str
    data_source_id: int | None
    data_source_name: str | None
    task_id: str | None
    total_skus: int
    success_count: int
    failed_count: int
    alert_count: int
    price_changed_count: int
    previous_batch_id: str | None
    pulled_at: datetime
    failed_skus: list[dict[str, str]]


def validate_price_sync_context(options: GigaPriceSyncOptions) -> GigaPriceSyncOptions:
    batch_id = (options.batch_id or "").strip()
    if not batch_id:
        raise GigaOpenApiError("batch_id is required")
    return GigaPriceSyncOptions(
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


def _float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _bool_int(value: Any) -> int | None:
    if value is None:
        return None
    return 1 if bool(value) else 0


def _effective_price(record: dict[str, Any]) -> float | None:
    exclusive_price = _float(record.get("exclusivePrice"))
    if exclusive_price is not None:
        return exclusive_price
    discounted_price = _float(record.get("discountedPrice"))
    if discounted_price is not None:
        return discounted_price
    return _float(record.get("price"))


def _shipping_fee_range(record: dict[str, Any]) -> tuple[float | None, float | None]:
    value = record.get("shippingFeeRange") or {}
    if not isinstance(value, dict):
        return None, None
    return _float(value.get("minAmount")), _float(value.get("maxAmount"))


def _money_changed(previous: float | None, current: float | None) -> bool:
    if previous is None and current is None:
        return False
    if previous is None or current is None:
        return True
    return abs(previous - current) > 0.0001


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
        raise GigaOpenApiError(f"site={site}{source_part} 没有可用于价格同步的 GIGA SKU 商品池，请先执行商品同步")
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


async def _latest_product_batch_id(db: AsyncSession, site: str, data_source_id: int | None) -> str | None:
    query = (
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
        query = query.where(GigaSyncBatch.data_source_id == data_source_id)
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def _fetch_prices_resilient(
    client: GigaOpenApiClient,
    sku_codes: list[str],
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    records: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    for batch in _chunks(sku_codes, 200):
        try:
            data = await client.call(API_PRICE, {"skus": batch})
            batch_records = data.get("data", [])
            if isinstance(batch_records, list):
                records.extend([item for item in batch_records if isinstance(item, dict)])
            await asyncio.sleep(PRICE_REQUEST_INTERVAL_SECONDS)
            continue
        except Exception as batch_exc:
            logger.warning("[GIGA Price] batch price fetch failed, fallback to single SKU: %s", batch_exc)

        for sku_code in batch:
            try:
                data = await client.call(API_PRICE, {"skus": [sku_code]})
                item_records = data.get("data", [])
                if isinstance(item_records, list):
                    records.extend([item for item in item_records if isinstance(item, dict)])
                await asyncio.sleep(PRICE_REQUEST_INTERVAL_SECONDS)
            except Exception as exc:
                failures.append({"sku_code": sku_code, "error": f"{type(exc).__name__}: {exc}"})
    return records, failures


async def _upsert_snapshot_batch(
    db: AsyncSession,
    options: GigaPriceSyncOptions,
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
    batch.current_category = PRICE_SNAPSHOT_CATEGORY
    batch.status = "running"
    batch.source_platform = SOURCE_PLATFORM
    batch.sku_count = total_skus
    batch.started_at = pulled_at
    batch.error_message = None
    await db.flush()
    return batch


async def _previous_price_batch_id(
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
            GigaSyncBatch.price_count > 0,
        )
        .order_by(GigaSyncBatch.finished_at.is_(None).asc(), GigaSyncBatch.finished_at.desc(), GigaSyncBatch.created_at.desc())
        .limit(1)
    )
    if data_source_id:
        query = query.where(GigaSyncBatch.data_source_id == data_source_id)
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def _previous_price_by_sku(
    db: AsyncSession,
    previous_batch_id: str | None,
    site: str,
    sku_codes: list[str],
    data_source_id: int | None,
) -> dict[str, GigaPrice]:
    if not previous_batch_id or not sku_codes:
        return {}
    query = (
        select(GigaPrice).where(
            GigaPrice.batch_id == previous_batch_id,
            GigaPrice.site == site,
            GigaPrice.sku_code.in_(sku_codes),
        )
    )
    if data_source_id:
        query = query.where(GigaPrice.data_source_id == data_source_id)
    result = await db.execute(query)
    return {row.sku_code: row for row in result.scalars().all()}


async def _sku_metadata(db: AsyncSession, site: str, sku_codes: list[str], data_source_id: int | None) -> dict[str, GigaSku]:
    if not sku_codes:
        return {}
    product_batch_id = await _latest_product_batch_id(db, site, data_source_id)
    if not product_batch_id:
        return {}
    query = (
        select(GigaSku).where(
            GigaSku.batch_id == product_batch_id,
            GigaSku.site == site,
            GigaSku.sku_code.in_(sku_codes),
        )
    )
    if data_source_id:
        query = query.where(GigaSku.data_source_id == data_source_id)
    result = await db.execute(query)
    return {sku.sku_code: sku for sku in result.scalars().all()}


def _alert_for_price_change(
    *,
    batch_id: str,
    site: str,
    data_source_id: int | None,
    sku_code: str,
    current: GigaPrice,
    previous: GigaPrice,
    metadata: GigaSku | None,
) -> GigaPriceAlert | None:
    previous_effective = previous.effective_price
    if previous_effective is None:
        previous_effective = previous.exclusive_price or previous.discounted_price or previous.price
    if not _money_changed(previous_effective, current.effective_price):
        return None
    item_code = metadata.item_code if metadata else None
    product_name = metadata.product_name if metadata else None
    label = item_code or sku_code
    message = f"{label} 价格发生变化: {previous_effective} -> {current.effective_price}"
    return GigaPriceAlert(
        batch_id=batch_id,
        site=site,
        data_source_id=data_source_id,
        sku_code=sku_code,
        item_code=item_code,
        product_name=product_name,
        previous_batch_id=previous.batch_id,
        previous_effective_price=previous_effective,
        current_effective_price=current.effective_price,
        previous_price=previous.price,
        current_price=current.price,
        previous_exclusive_price=previous.exclusive_price,
        current_exclusive_price=current.exclusive_price,
        previous_discounted_price=previous.discounted_price,
        current_discounted_price=current.discounted_price,
        previous_shipping_fee=previous.shipping_fee,
        current_shipping_fee=current.shipping_fee,
        change_type="price_changed",
        message=message,
        source_platform=SOURCE_PLATFORM,
        created_at=datetime.now(),
    )


async def sync_giga_price_snapshot(
    db: AsyncSession,
    options: GigaPriceSyncOptions,
) -> GigaPriceSyncResult:
    options = validate_price_sync_context(options)
    context = await resolve_giga_data_source_context(db, options.data_source_id, options.site)
    options = GigaPriceSyncOptions(
        batch_id=options.batch_id,
        site=context.site,
        data_source_id=context.id,
        task_id=options.task_id,
        sku_codes=options.sku_codes,
    )
    pulled_at = datetime.now()
    sku_codes = options.sku_codes or await _latest_product_skus(db, options.site, options.data_source_id)

    await _upsert_snapshot_batch(db, options, context, len(sku_codes), pulled_at)
    await db.execute(delete(GigaPrice).where(
        GigaPrice.batch_id == options.batch_id,
        GigaPrice.site == options.site,
        GigaPrice.data_source_id == options.data_source_id,
    ))
    await db.execute(delete(GigaPriceAlert).where(
        GigaPriceAlert.batch_id == options.batch_id,
        GigaPriceAlert.site == options.site,
        GigaPriceAlert.data_source_id == options.data_source_id,
    ))
    await db.commit()

    try:
        records, failures = await _fetch_prices_resilient(
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
    failures.extend({"sku_code": sku, "error": "GIGA Open API 未返回该 SKU 价格"} for sku in missing_skus)

    success_skus = [sku for sku in sku_codes if sku in records_by_sku]
    previous_batch_id = await _previous_price_batch_id(db, options.batch_id, options.site, options.data_source_id)
    previous_by_sku = await _previous_price_by_sku(
        db,
        previous_batch_id,
        options.site,
        success_skus,
        options.data_source_id,
    )
    metadata_by_sku = await _sku_metadata(db, options.site, success_skus, options.data_source_id)
    price_rows = []
    alert_rows: list[GigaPriceAlert] = []
    for sku_code in success_skus:
        record = records_by_sku[sku_code]
        shipping_fee_min, shipping_fee_max = _shipping_fee_range(record)
        price_row = GigaPrice(
            batch_id=options.batch_id,
            site=options.site,
            data_source_id=options.data_source_id,
            fulfillment_mode=context.fulfillment_mode,
            shipping_cost_mode=context.shipping_cost_mode,
            packing_fee=context.packing_fee,
            sku_code=sku_code,
            task_id=options.task_id,
            currency=_text(record.get("currency")) or "USD",
            price=_float(record.get("price")),
            exclusive_price=_float(record.get("exclusivePrice")),
            discounted_price=_float(record.get("discountedPrice")),
            effective_price=_effective_price(record),
            shipping_fee=_float(record.get("shippingFee")),
            shipping_fee_min=shipping_fee_min,
            shipping_fee_max=shipping_fee_max,
            estimated_shipping_fee=_float(record.get("estimatedShippingFee")),
            map_price=_float(record.get("mapPrice")),
            srp_price=_text(record.get("srpPrice")),
            future_map_price=_float(record.get("futureMapPrice")),
            exclusive_price_expire_time=_text(record.get("exclusivePriceExpireTime")),
            promotion_from=_text(record.get("promotionFrom")),
            promotion_to=_text(record.get("promotionTo")),
            purchase_limit=_text(record.get("purchaseLimit")),
            sku_available=_bool_int(record.get("skuAvailable")),
            seller_info_json=_json_dump(record.get("sellerInfo") or {}),
            spot_price_json=_json_dump(record.get("spotPrice") or []),
            rebates_price_json=_json_dump(record.get("rebatesPrice") or []),
            margin_price_json=_json_dump(record.get("marginPrice") or []),
            future_price_json=_json_dump(record.get("futurePrice") or []),
            raw_price_json=_json_dump(record),
            source_platform=SOURCE_PLATFORM,
            pulled_at=pulled_at,
        )
        price_rows.append(price_row)
        previous = previous_by_sku.get(sku_code)
        if previous:
            alert = _alert_for_price_change(
                batch_id=options.batch_id,
                site=options.site,
                data_source_id=options.data_source_id,
                sku_code=sku_code,
                current=price_row,
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
    db.add_all(price_rows + alert_rows)
    batch.status = "done"
    batch.price_count = len(price_rows)
    batch.finished_at = datetime.now()
    batch.error_message = None if not failures else f"{len(failures)} 个 SKU 价格同步失败"
    await db.commit()

    return GigaPriceSyncResult(
        batch_id=options.batch_id,
        site=options.site,
        data_source_id=options.data_source_id,
        data_source_name=context.name,
        task_id=options.task_id,
        total_skus=len(sku_codes),
        success_count=len(price_rows),
        failed_count=len(failures),
        alert_count=len(alert_rows),
        price_changed_count=sum(1 for alert in alert_rows if alert.change_type == "price_changed"),
        previous_batch_id=previous_batch_id,
        pulled_at=pulled_at,
        failed_skus=failures,
    )
