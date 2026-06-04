import asyncio
import base64
import hashlib
import hmac
import json
import random
import string
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import (
    GigaGroup,
    GigaInventory,
    GigaItem,
    GigaPrice,
    GigaProductImage,
    GigaRawSkuDetail,
    GigaSku,
    GigaSyncBatch,
    ProductDataSource,
)
from app.services.giga_image_assets import (
    build_pending_giga_product_image_rows,
    download_giga_product_images,
    extract_giga_image_candidates,
)


API_LIST = "/b2b-overseas-api/v1/buyer/product/skus/v1"
API_DETAIL = "/b2b-overseas-api/v1/buyer/product/detailInfo/v1"
API_PRICE = "/b2b-overseas-api/v1/buyer/product/price/v1"
API_INVENTORY = "/b2b-overseas-api/v1/buyer/inventory/quantity/v2"
API_ORDER_DROPSHIP_SYNC = "/b2b-overseas-api/v1/buyer/order/dropShip-sync/v1"
API_ORDER_PICKUP_SELF_LABEL_SYNC = "/b2b-overseas-api/v1/buyer/order/pickUpSelfLabel-sync/v1"
API_ORDER_PICKUP_GIGA_LABEL_SYNC = "/b2b-overseas-api/v1/buyer/order/pickUp-sync/v1"
API_ORDER_STATUS = "/b2b-overseas-api/v1/buyer/order/status/v1"
API_ORDER_TRACK_NO = "/b2b-overseas-api/v1/buyer/order/track-no/v1"
API_WAREHOUSE_QUERY_ADDRESS = "/b2b-overseas-api/v1/buyer/warehouse/query-address/v1"
SOURCE_PLATFORM = "GIGA"

GIGA_BUYER_API_RATE_LIMITS: dict[str, float] = {
    API_LIST: 1.05,  # 10 requests / 10 seconds
    API_DETAIL: 0.55,  # 20 requests / 10 seconds
    API_PRICE: 1.05,
    API_INVENTORY: 1.05,
    API_ORDER_STATUS: 0.55,
    API_ORDER_TRACK_NO: 0.55,
    API_WAREHOUSE_QUERY_ADDRESS: 0.55,
}


class GigaOpenApiError(RuntimeError):
    pass


@dataclass(frozen=True)
class GigaSyncOptions:
    batch_id: str
    site: str
    data_source_id: int
    task_id: str | None = None
    current_category: str | None = None
    page_size: int = 200
    max_pages: int | None = None
    skip_existing: bool = False
    download_images: bool = True
    sku_codes: tuple[str, ...] = ()


@dataclass(frozen=True)
class GigaSyncResult:
    batch_id: str
    site: str
    data_source_id: int | None
    data_source_name: str | None
    raw_sku_count: int
    sku_count: int
    item_count: int
    price_count: int
    inventory_count: int
    group_count: int
    deleted_single_sku_group_count: int
    skipped_existing_count: int = 0


@dataclass(frozen=True)
class GigaDataSourceContext:
    id: int | None
    name: str | None
    site: str
    fulfillment_mode: str | None
    shipping_cost_mode: str | None
    packing_fee: float | None
    inventory_mode: str | None
    api_base: str
    client_id: str
    client_secret: str


def _nonce() -> str:
    return "".join(random.choices(string.ascii_letters + string.digits, k=10))


def _calc_sign(client_id: str, client_secret: str, uri: str, timestamp: str, nonce: str) -> str:
    msg = f"{client_id}&{uri}&{timestamp}&{nonce}"
    key = f"{client_id}&{client_secret}&{nonce}"
    digest = hmac.new(key.encode("utf-8"), msg.encode("utf-8"), hashlib.sha256).hexdigest()
    return base64.b64encode(digest.encode("utf-8")).decode("utf-8")


def _chunks(items: list[str], size: int) -> list[list[str]]:
    return [items[index:index + size] for index in range(0, len(items), size)]


def _normalize_text_list(values: list[str] | tuple[str, ...] | None) -> list[str]:
    return list(dict.fromkeys(_text(value) for value in (values or []) if _text(value)))


def _require_non_empty(values: list[str], field_name: str) -> list[str]:
    if not values:
        raise GigaOpenApiError(f"{field_name} 不能为空")
    return values


async def _respect_rate_limit(path: str) -> None:
    interval = GIGA_BUYER_API_RATE_LIMITS.get(path)
    if interval:
        await asyncio.sleep(interval)


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


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


def _parent_sku_for_item(item_code: str) -> str:
    return f"{item_code}-PARENT"


def _attributes_for_detail(detail: dict[str, Any]) -> dict[str, str]:
    attributes: dict[str, str] = {}
    raw_attributes = detail.get("attributes") or {}
    if isinstance(raw_attributes, dict):
        for key, value in raw_attributes.items():
            key_text = _text(key)
            value_text = _text(value)
            if key_text and value_text:
                attributes[key_text] = value_text
    for source_key, target_key in (
        ("mainColor", "Main Color"),
        ("mainMaterial", "Main Material"),
        ("brandInfo", "Brand"),
    ):
        value = detail.get(source_key)
        if isinstance(value, dict):
            value = value.get("name") or value.get("brandName")
        value_text = _text(value)
        if value_text and target_key not in attributes:
            attributes[target_key] = value_text
    return attributes


def _variation_attributes_by_sku(
    group_skus: list[str],
    details_by_sku: dict[str, dict[str, Any]],
) -> tuple[dict[str, dict[str, str]], list[str]]:
    attributes_by_sku = {
        sku: _attributes_for_detail(details_by_sku.get(sku, {}))
        for sku in group_skus
    }
    keys = sorted({key for attrs in attributes_by_sku.values() for key in attrs})
    variation_keys: list[str] = []
    for key in keys:
        values = {attrs.get(key) for attrs in attributes_by_sku.values() if attrs.get(key)}
        if len(values) > 1:
            variation_keys.append(key)

    if len(group_skus) > 1 and not variation_keys:
        variation_keys = ["sku"]
        return {sku: {"sku": sku} for sku in group_skus}, variation_keys

    return (
        {
            sku: {key: attrs[key] for key in variation_keys if key in attrs}
            for sku, attrs in attributes_by_sku.items()
        },
        variation_keys,
    )


class GigaOpenApiClient:
    def __init__(
        self,
        *,
        client_id: str | None = None,
        client_secret: str | None = None,
        api_base: str | None = None,
    ) -> None:
        self.client_id = (client_id or "").strip()
        self.client_secret = (client_secret or "").strip()
        self.base_url = str(api_base or "").strip().rstrip("/")
        if not self.client_id or not self.client_secret:
            raise GigaOpenApiError("商品数据源缺少 AK/SK")
        if not self.base_url:
            raise GigaOpenApiError("商品数据源缺少 Open API 地址")

    async def call(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        timestamp = str(int(time.time() * 1000))
        nonce = _nonce()
        headers = {
            "Content-Type": "application/json",
            "client-id": self.client_id,
            "timestamp": timestamp,
            "nonce": nonce,
            "sign": _calc_sign(self.client_id, self.client_secret, path, timestamp, nonce),
        }
        async with httpx.AsyncClient(timeout=httpx.Timeout(connect=20, read=180, write=30, pool=20)) as client:
            response = await client.post(f"{self.base_url}{path}", json=payload, headers=headers)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict) or not data.get("success"):
            raise GigaOpenApiError(f"GIGA Open API 返回异常: path={path}, payload={data}")
        return data

    async def fetch_sku_page(
        self,
        *,
        page: int = 1,
        page_size: int = 5000,
        sort: int = 4,
        first_arrival_date: str | None = None,
        last_updated_after: str | None = None,
        query_time_type: int | None = None,
        start_time: str | None = None,
        end_time: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "page": page,
            "pageSize": page_size,
            "sort": sort,
        }
        if first_arrival_date:
            payload["firstArrivalDate"] = first_arrival_date
        if last_updated_after:
            payload["lastUpdatedAfter"] = last_updated_after
        if query_time_type is not None:
            payload["queryTimeType"] = query_time_type
        if start_time:
            payload["startTime"] = start_time
        if end_time:
            payload["endTime"] = end_time
        return await self.call(API_LIST, payload)

    async def fetch_sku_records(
        self,
        page_size: int,
        max_pages: int | None,
        *,
        sort: int = 4,
        first_arrival_date: str | None = None,
        last_updated_after: str | None = None,
        query_time_type: int | None = None,
        start_time: str | None = None,
        end_time: str | None = None,
    ) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        page = 1
        while True:
            data = await self.fetch_sku_page(
                page=page,
                page_size=page_size,
                sort=sort,
                first_arrival_date=first_arrival_date,
                last_updated_after=last_updated_after,
                query_time_type=query_time_type,
                start_time=start_time,
                end_time=end_time,
            )
            page_records = data.get("data", {}).get("records", [])
            if not isinstance(page_records, list) or not page_records:
                break
            records.extend([item for item in page_records if isinstance(item, dict)])
            if max_pages and page >= max_pages:
                break
            if len(page_records) < page_size:
                break
            page += 1
            await _respect_rate_limit(API_LIST)
        return records

    async def fetch_details(self, sku_codes: list[str]) -> list[dict[str, Any]]:
        details: list[dict[str, Any]] = []
        for batch in _chunks(_normalize_text_list(sku_codes), 200):
            data = await self.call(API_DETAIL, {"skus": batch})
            batch_details = data.get("data", [])
            if isinstance(batch_details, list):
                details.extend([item for item in batch_details if isinstance(item, dict)])
            await _respect_rate_limit(API_DETAIL)
        return details

    async def fetch_details_by_product_names(self, product_names: list[str]) -> list[dict[str, Any]]:
        details: list[dict[str, Any]] = []
        for batch in _chunks(_normalize_text_list(product_names), 200):
            data = await self.call(API_DETAIL, {"productNames": batch})
            batch_details = data.get("data", [])
            if isinstance(batch_details, list):
                details.extend([item for item in batch_details if isinstance(item, dict)])
            await _respect_rate_limit(API_DETAIL)
        return details

    async def fetch_prices(self, sku_codes: list[str]) -> list[dict[str, Any]]:
        prices: list[dict[str, Any]] = []
        for batch in _chunks(_normalize_text_list(sku_codes), 200):
            data = await self.call(API_PRICE, {"skus": batch})
            batch_prices = data.get("data", [])
            if isinstance(batch_prices, list):
                prices.extend([item for item in batch_prices if isinstance(item, dict)])
            await _respect_rate_limit(API_PRICE)
        return prices

    async def fetch_inventory(self, sku_codes: list[str]) -> list[dict[str, Any]]:
        inventory: list[dict[str, Any]] = []
        for batch in _chunks(_normalize_text_list(sku_codes), 200):
            data = await self.call(API_INVENTORY, {"skus": batch})
            batch_inventory = data.get("data", [])
            if isinstance(batch_inventory, list):
                inventory.extend([item for item in batch_inventory if isinstance(item, dict)])
            await _respect_rate_limit(API_INVENTORY)
        return inventory

    async def submit_dropship_order(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._validate_order_payload(payload)
        return await self.call(API_ORDER_DROPSHIP_SYNC, payload)

    async def submit_pickup_self_label_order(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._validate_order_payload(payload)
        return await self.call(API_ORDER_PICKUP_SELF_LABEL_SYNC, payload)

    async def submit_pickup_giga_label_order(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._validate_order_payload(payload)
        return await self.call(API_ORDER_PICKUP_GIGA_LABEL_SYNC, payload)

    async def fetch_order_status(self, order_nos: list[str]) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for batch in _chunks(_require_non_empty(_normalize_text_list(order_nos), "orderNo"), 100):
            data = await self.call(API_ORDER_STATUS, {"orderNo": batch})
            batch_records = data.get("data", [])
            if isinstance(batch_records, list):
                records.extend([item for item in batch_records if isinstance(item, dict)])
            await _respect_rate_limit(API_ORDER_STATUS)
        return records

    async def fetch_track_numbers(self, order_nos: list[str]) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for batch in _chunks(_require_non_empty(_normalize_text_list(order_nos), "orderNo"), 100):
            data = await self.call(API_ORDER_TRACK_NO, {"orderNo": batch})
            batch_records = data.get("data", [])
            if isinstance(batch_records, list):
                records.extend([item for item in batch_records if isinstance(item, dict)])
            await _respect_rate_limit(API_ORDER_TRACK_NO)
        return records

    async def fetch_warehouse_addresses(self, warehouse_codes: list[str]) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for batch in _chunks(_require_non_empty(_normalize_text_list(warehouse_codes), "warehouseCodes"), 200):
            data = await self.call(API_WAREHOUSE_QUERY_ADDRESS, {"warehouseCodes": batch})
            batch_records = data.get("data", [])
            if isinstance(batch_records, list):
                records.extend([item for item in batch_records if isinstance(item, dict)])
            await _respect_rate_limit(API_WAREHOUSE_QUERY_ADDRESS)
        return records

    @staticmethod
    def _validate_order_payload(payload: dict[str, Any]) -> None:
        if not isinstance(payload, dict):
            raise GigaOpenApiError("订单请求 payload 必须是 dict")
        for field_name in ("orderNo", "orderLines"):
            if not payload.get(field_name):
                raise GigaOpenApiError(f"订单请求缺少必填字段: {field_name}")


def _is_valid_detail(detail: dict[str, Any] | None) -> bool:
    if not detail:
        return False
    if not _text(detail.get("sku")):
        return False
    return bool(_text(detail.get("productName")) or _text(detail.get("mainImageUrl")))


def _build_item_groups(details: list[dict[str, Any]], sku_codes: list[str]) -> dict[str, list[str]]:
    parent: dict[str, str] = {}
    details_by_sku = {_text(item.get("sku")): item for item in details if _text(item.get("sku"))}
    valid_skus = {sku for sku in sku_codes if _is_valid_detail(details_by_sku.get(sku))}

    def find(value: str) -> str:
        parent.setdefault(value, value)
        if parent[value] != value:
            parent[value] = find(parent[value])
        return parent[value]

    def union(left: str, right: str) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parent[left_root] = right_root

    for sku in valid_skus:
        find(sku)
    for detail in details:
        sku = _text(detail.get("sku"))
        if not sku or sku not in valid_skus:
            continue
        for related in detail.get("associateProductList") or []:
            related_sku = _text(related)
            if related_sku in valid_skus:
                union(sku, related_sku)

    groups: dict[str, list[str]] = {}
    for sku in sorted(parent):
        root = find(sku)
        groups.setdefault(root, []).append(sku)
    return groups


def _missing_related_skus(group_skus: list[str], details_by_sku: dict[str, dict[str, Any]]) -> list[str]:
    group_set = set(group_skus)
    missing: set[str] = set()
    for sku in group_skus:
        detail = details_by_sku.get(sku, {})
        for related in detail.get("associateProductList") or []:
            related_sku = _text(related)
            if related_sku and related_sku not in group_set:
                missing.add(related_sku)
    return sorted(missing)


def _item_code_for_group(group_skus: list[str], details_by_sku: dict[str, dict[str, Any]]) -> str:
    for sku in group_skus:
        associates = details_by_sku.get(sku, {}).get("associateProductList") or []
        for candidate in associates:
            candidate_sku = _text(candidate)
            if candidate_sku in group_skus:
                return candidate_sku
    return sorted(group_skus)[0]


async def resolve_giga_data_source_context(
    db: AsyncSession,
    data_source_id: int | None,
    fallback_site: str | None,
) -> GigaDataSourceContext:
    if not data_source_id:
        raise GigaOpenApiError("请先选择商品数据源，GIGA AK/SK 不再从全局配置读取")
    result = await db.execute(select(ProductDataSource).where(ProductDataSource.id == data_source_id))
    source = result.scalar_one_or_none()
    if not source:
        raise GigaOpenApiError(f"商品数据源不存在: {data_source_id}")
    if not source.enabled:
        raise GigaOpenApiError(f"商品数据源已停用: {source.name}")
    if (source.platform or "giga").lower() != "giga":
        raise GigaOpenApiError(f"商品数据源平台暂不支持 GIGA 同步: {source.platform}")
    client_id = (source.client_id or "").strip()
    client_secret = (source.client_secret or "").strip()
    api_base = (source.api_base or "").strip()
    if not client_id or not client_secret:
        raise GigaOpenApiError(f"商品数据源 {source.name} 缺少 AK/SK")
    if not api_base:
        raise GigaOpenApiError(f"商品数据源 {source.name} 缺少 Open API 地址")
    site = (source.site or fallback_site or "").strip().upper()
    if not site:
        raise GigaOpenApiError(f"商品数据源 {source.name} 缺少站点")
    return GigaDataSourceContext(
        id=source.id,
        name=source.name,
        site=site,
        fulfillment_mode=source.fulfillment_mode,
        shipping_cost_mode=source.shipping_cost_mode,
        packing_fee=source.packing_fee,
        inventory_mode=source.inventory_mode,
        api_base=api_base,
        client_id=client_id,
        client_secret=client_secret,
    )


async def _resolve_data_source_context(db: AsyncSession, options: GigaSyncOptions) -> GigaDataSourceContext:
    return await resolve_giga_data_source_context(db, options.data_source_id, options.site)


async def _clear_batch(db: AsyncSession, batch_id: str, site: str, data_source_id: int | None = None) -> None:
    for model in (GigaGroup, GigaInventory, GigaPrice, GigaProductImage, GigaSku, GigaItem, GigaRawSkuDetail):
        query = delete(model).where(model.batch_id == batch_id, model.site == site)
        if data_source_id:
            query = query.where(model.data_source_id == data_source_id)
        await db.execute(query)


async def _upsert_batch(
    db: AsyncSession,
    options: GigaSyncOptions,
    status: str,
    error_message: str | None = None,
) -> GigaSyncBatch:
    result = await db.execute(
        select(GigaSyncBatch).where(
            GigaSyncBatch.batch_id == options.batch_id,
            GigaSyncBatch.site == options.site,
            GigaSyncBatch.data_source_id == options.data_source_id,
        )
    )
    batch = result.scalar_one_or_none()
    if not batch:
        batch = GigaSyncBatch(batch_id=options.batch_id, site=options.site)
        db.add(batch)
    batch.task_id = options.task_id
    batch.data_source_id = options.data_source_id
    batch.current_category = options.current_category
    batch.status = status
    batch.error_message = error_message
    batch.updated_at = datetime.now()
    if status == "running":
        batch.started_at = datetime.now()
        batch.finished_at = None
    if status in {"done", "failed"}:
        batch.finished_at = datetime.now()
    return batch


async def sync_giga_products(db: AsyncSession, options: GigaSyncOptions) -> GigaSyncResult:
    context = await _resolve_data_source_context(db, options)
    normalized_site = context.site.strip().upper()
    options = GigaSyncOptions(
        batch_id=options.batch_id.strip(),
        site=normalized_site,
        data_source_id=context.id,
        task_id=options.task_id,
        current_category=options.current_category,
        page_size=options.page_size or settings.GIGA_SYNC_PAGE_SIZE,
        max_pages=options.max_pages,
        skip_existing=options.skip_existing,
        download_images=options.download_images,
        sku_codes=tuple(_normalize_text_list(list(options.sku_codes))),
    )
    if not options.batch_id:
        raise GigaOpenApiError("缺少 batch_id")
    if not options.site:
        raise GigaOpenApiError("缺少 site")

    batch = await _upsert_batch(db, options, "running")
    batch.data_source_name = context.name
    batch.fulfillment_mode = context.fulfillment_mode
    if not options.skip_existing:
        await _clear_batch(db, options.batch_id, options.site, options.data_source_id)
    await db.commit()

    try:
        client = GigaOpenApiClient(
            api_base=context.api_base,
            client_id=context.client_id,
            client_secret=context.client_secret,
        )
        if options.sku_codes:
            records = []
            listed_sku_codes = list(options.sku_codes)
        else:
            records = await client.fetch_sku_records(options.page_size, options.max_pages)
            listed_sku_codes = list(dict.fromkeys(_text(item.get("sku")) for item in records if _text(item.get("sku"))))
        if not listed_sku_codes:
            raise GigaOpenApiError("GIGA 商品列表返回 0 个 SKU")

        skipped_existing_count = 0
        sku_codes = listed_sku_codes
        if options.skip_existing:
            existing_query = select(GigaSku.sku_code).where(GigaSku.site == options.site)
            if options.data_source_id:
                existing_query = existing_query.where(GigaSku.data_source_id == options.data_source_id)
            existing_result = await db.execute(existing_query)
            existing_skus = {sku for sku in existing_result.scalars().all() if sku}
            sku_codes = [sku for sku in listed_sku_codes if sku not in existing_skus]
            skipped_existing_count = len(listed_sku_codes) - len(sku_codes)
            if not sku_codes:
                batch.raw_sku_count = 0
                batch.sku_count = 0
                batch.item_count = 0
                batch.price_count = 0
                batch.inventory_count = 0
                batch.group_count = 0
                batch.deleted_single_sku_group_count = 0
                batch.status = "done"
                batch.error_message = None
                batch.finished_at = datetime.now()
                batch.updated_at = datetime.now()
                await db.commit()
                return GigaSyncResult(
                    batch_id=options.batch_id,
                    site=options.site,
                    data_source_id=options.data_source_id,
                    data_source_name=context.name,
                    raw_sku_count=0,
                    sku_count=0,
                    item_count=0,
                    price_count=0,
                    inventory_count=0,
                    group_count=0,
                    deleted_single_sku_group_count=0,
                    skipped_existing_count=skipped_existing_count,
                )

        details = await client.fetch_details(sku_codes)
        details_by_sku = {_text(item.get("sku")): item for item in details if _text(item.get("sku"))}
        related_sku_codes: list[str] = []
        for detail in details_by_sku.values():
            for related in detail.get("associateProductList") or []:
                related_sku = _text(related)
                if related_sku and related_sku not in details_by_sku:
                    related_sku_codes.append(related_sku)
        related_sku_codes = list(dict.fromkeys(related_sku_codes))
        if related_sku_codes:
            related_details = await client.fetch_details(related_sku_codes)
            for detail in related_details:
                sku = _text(detail.get("sku"))
                if sku:
                    details_by_sku[sku] = detail
            sku_codes = list(dict.fromkeys([*sku_codes, *related_sku_codes]))
            details = list(details_by_sku.values())
        valid_sku_codes = [sku for sku in sku_codes if _is_valid_detail(details_by_sku.get(sku))]
        prices = await client.fetch_prices(valid_sku_codes)
        inventory = await client.fetch_inventory(valid_sku_codes)

        if not details:
            raise GigaOpenApiError("GIGA 详情返回 0 条")
        if not prices:
            raise GigaOpenApiError("GIGA 价格返回 0 条")
        if not inventory:
            raise GigaOpenApiError("GIGA 库存返回 0 条")

        groups = _build_item_groups(details, valid_sku_codes)
        sku_to_item: dict[str, str] = {}
        item_rows: list[GigaItem] = []
        item_by_code: dict[str, GigaItem] = {}
        group_rows: list[GigaGroup] = []
        deleted_single_sku_group_count = 0
        for group_skus in groups.values():
            item_code = _item_code_for_group(group_skus, details_by_sku)
            parent_sku_code = _parent_sku_for_item(item_code)
            variation_by_sku, variation_keys = _variation_attributes_by_sku(group_skus, details_by_sku)
            missing_related_skus = _missing_related_skus(group_skus, details_by_sku)
            for sku in group_skus:
                sku_to_item[sku] = item_code
            item_name = next((_text(details_by_sku.get(sku, {}).get("productName")) for sku in group_skus if details_by_sku.get(sku)), None)
            item_row = GigaItem(
                batch_id=options.batch_id,
                site=options.site,
                data_source_id=options.data_source_id,
                data_source_name=context.name,
                item_code=item_code,
                fulfillment_mode=context.fulfillment_mode,
                parent_sku_code=parent_sku_code,
                item_name=item_name,
                category=options.current_category,
                sku_count=len(group_skus),
                sku_codes_json=_json_dumps(group_skus),
                missing_related_skus_json=_json_dumps(missing_related_skus),
                raw_group_json=_json_dumps({
                    "skus": group_skus,
                    "missing_related_skus": missing_related_skus,
                    "parent_sku_code": parent_sku_code,
                    "variation_keys": variation_keys,
                    "variation_attributes_by_sku": variation_by_sku,
                }),
                source_platform=SOURCE_PLATFORM,
            )
            item_rows.append(item_row)
            item_by_code[item_code] = item_row
            is_single = len(group_skus) <= 1
            if is_single:
                deleted_single_sku_group_count += 1
            group_rows.append(GigaGroup(
                batch_id=options.batch_id,
                site=options.site,
                data_source_id=options.data_source_id,
                data_source_name=context.name,
                fulfillment_mode=context.fulfillment_mode,
                group_code=item_code,
                parent_sku_code=parent_sku_code,
                current_category=options.current_category,
                item_codes_json=_json_dumps([item_code]),
                sku_codes_json=_json_dumps(group_skus),
                missing_related_skus_json=_json_dumps(missing_related_skus),
                variation_keys_json=_json_dumps(variation_keys),
                group_size=len(group_skus),
                deleted_single_sku_group=1 if is_single else 0,
            ))

        now = datetime.now()
        raw_rows = [
            GigaRawSkuDetail(
                batch_id=options.batch_id,
                site=options.site,
                data_source_id=options.data_source_id,
                sku_code=sku,
                data_json=_json_dumps(detail),
                source_platform=SOURCE_PLATFORM,
                pulled_at=now,
            )
            for sku, detail in details_by_sku.items()
        ]
        sku_rows = []
        record_by_sku = {_text(item.get("sku")): item for item in records if _text(item.get("sku"))}
        group_skus_by_item: dict[str, list[str]] = {}
        for group_skus in groups.values():
            item_code = _item_code_for_group(group_skus, details_by_sku)
            group_skus_by_item[item_code] = group_skus
        variation_by_item: dict[str, dict[str, dict[str, str]]] = {}
        for item_code, group_skus in group_skus_by_item.items():
            variation_by_item[item_code] = _variation_attributes_by_sku(group_skus, details_by_sku)[0]
        for sku in valid_sku_codes:
            detail = details_by_sku.get(sku, {})
            record = record_by_sku.get(sku, {})
            item_code = sku_to_item.get(sku)
            group_skus = group_skus_by_item.get(item_code or "", [sku])
            sku_rows.append(GigaSku(
                item=item_by_code.get(item_code or ""),
                batch_id=options.batch_id,
                site=options.site,
                data_source_id=options.data_source_id,
                data_source_name=context.name,
                fulfillment_mode=context.fulfillment_mode,
                sku_code=sku,
                item_code=item_code,
                parent_sku_code=_parent_sku_for_item(item_code) if item_code else None,
                parentage="child" if len(group_skus) > 1 else "single",
                child_sequence=(group_skus.index(sku) + 1) if sku in group_skus else None,
                is_primary_child=1 if sku == item_code else 0,
                product_name=_text(detail.get("productName") or record.get("productName")),
                main_image_url=_text(detail.get("mainImageUrl") or record.get("mainImageUrl")),
                description=_text(detail.get("description")),
                attributes_json=_json_dumps(_attributes_for_detail(detail)),
                variation_attributes_json=_json_dumps(variation_by_item.get(item_code or "", {}).get(sku, {})),
                source_platform=SOURCE_PLATFORM,
            ))

        image_candidates = []
        for sku in valid_sku_codes:
            image_candidates.extend(
                extract_giga_image_candidates(
                    sku_code=sku,
                    item_code=sku_to_item.get(sku),
                    detail=details_by_sku.get(sku, {}),
                )
            )
        if image_candidates and options.download_images:
            image_rows = await download_giga_product_images(
                batch_id=options.batch_id,
                site=options.site,
                candidates=image_candidates,
            )
            for image_row in image_rows:
                image_row.data_source_id = options.data_source_id
        else:
            image_rows = build_pending_giga_product_image_rows(
                batch_id=options.batch_id,
                site=options.site,
                candidates=image_candidates,
                data_source_id=options.data_source_id,
            )

        pulled_at = datetime.now()
        price_rows = []
        for price in prices:
            if not _text(price.get("sku")):
                continue
            shipping_fee_min, shipping_fee_max = _shipping_fee_range(price)
            price_rows.append(GigaPrice(
                batch_id=options.batch_id,
                site=options.site,
                data_source_id=options.data_source_id,
                fulfillment_mode=context.fulfillment_mode,
                shipping_cost_mode=context.shipping_cost_mode,
                packing_fee=context.packing_fee,
                sku_code=str(price.get("sku") or ""),
                task_id=options.task_id,
                currency=_text(price.get("currency")) or "USD",
                price=_float(price.get("price")),
                exclusive_price=_float(price.get("exclusivePrice")),
                discounted_price=_float(price.get("discountedPrice")),
                effective_price=_effective_price(price),
                shipping_fee=_float(price.get("shippingFee")),
                shipping_fee_min=shipping_fee_min,
                shipping_fee_max=shipping_fee_max,
                estimated_shipping_fee=_float(price.get("estimatedShippingFee")),
                map_price=_float(price.get("mapPrice")),
                srp_price=_text(price.get("srpPrice")),
                future_map_price=_float(price.get("futureMapPrice")),
                exclusive_price_expire_time=_text(price.get("exclusivePriceExpireTime")),
                promotion_from=_text(price.get("promotionFrom")),
                promotion_to=_text(price.get("promotionTo")),
                purchase_limit=_text(price.get("purchaseLimit")),
                sku_available=_bool_int(price.get("skuAvailable")),
                seller_info_json=_json_dumps(price.get("sellerInfo") or {}),
                spot_price_json=_json_dumps(price.get("spotPrice") or []),
                rebates_price_json=_json_dumps(price.get("rebatesPrice") or []),
                margin_price_json=_json_dumps(price.get("marginPrice") or []),
                future_price_json=_json_dumps(price.get("futurePrice") or []),
                raw_price_json=_json_dumps(price),
                source_platform=SOURCE_PLATFORM,
                pulled_at=pulled_at,
            ))
        inventory_rows = []
        for item in inventory:
            sku = _text(item.get("sku"))
            if not sku:
                continue
            seller = item.get("sellerInventoryInfo") or {}
            buyer = item.get("buyerInventoryInfo") or {}
            available = _int(seller.get("sellerAvailableInventory"))
            total_available = _int(buyer.get("totalBuyerAvailableInventory"))
            stock_qty = available if available is not None and available > 0 else total_available
            if stock_qty is None:
                stock_qty = available if available is not None else total_available
            if stock_qty is None:
                stock_qty = 0
            inventory_rows.append(GigaInventory(
                batch_id=options.batch_id,
                site=options.site,
                data_source_id=options.data_source_id,
                fulfillment_mode=context.fulfillment_mode,
                inventory_mode=context.inventory_mode,
                sku_code=sku,
                task_id=options.task_id,
                stock_qty=stock_qty,
                seller_available_inventory=available,
                total_buyer_available_inventory=total_available,
                seller_inventory_distribution=_json_dumps(seller.get("sellerInventoryDistribution") or []),
                buyer_inventory_distribution=_json_dumps(buyer.get("buyerInventoryDistribution") or []),
                next_arrival_inventory=_json_dumps(seller.get("nextArrivalInventory") or {}),
                availability_status="in_stock" if stock_qty > 0 else "out_of_stock",
                source_platform=SOURCE_PLATFORM,
                pulled_at=pulled_at,
            ))

        db.add_all(raw_rows + item_rows + sku_rows + image_rows + price_rows + inventory_rows + group_rows)
        batch.raw_sku_count = len(raw_rows)
        batch.sku_count = len(sku_rows)
        batch.item_count = len(item_rows)
        batch.price_count = len(price_rows)
        batch.inventory_count = len(inventory_rows)
        batch.group_count = len([row for row in group_rows if not row.deleted_single_sku_group])
        batch.deleted_single_sku_group_count = deleted_single_sku_group_count
        batch.status = "done"
        batch.error_message = None
        batch.finished_at = datetime.now()
        batch.updated_at = datetime.now()
        await db.commit()
        return GigaSyncResult(
            batch_id=options.batch_id,
            site=options.site,
            data_source_id=options.data_source_id,
            data_source_name=context.name,
            raw_sku_count=batch.raw_sku_count,
            sku_count=batch.sku_count,
            item_count=batch.item_count,
            price_count=batch.price_count,
            inventory_count=batch.inventory_count,
            group_count=batch.group_count,
            deleted_single_sku_group_count=batch.deleted_single_sku_group_count,
            skipped_existing_count=skipped_existing_count,
        )
    except Exception as exc:
        batch.status = "failed"
        batch.error_message = f"{type(exc).__name__}: {exc}"
        batch.finished_at = datetime.now()
        batch.updated_at = datetime.now()
        await db.commit()
        raise
