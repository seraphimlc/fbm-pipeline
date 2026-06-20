from datetime import datetime
from typing import Any

from sqlalchemy import delete, func, select

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
    TaskGroup,
    TaskStep,
)
from app.services.giga_image_assets import build_pending_giga_product_image_rows, extract_giga_image_candidates
from app.services.giga_openapi import (
    GigaOpenApiClient,
    SOURCE_PLATFORM,
    _attributes_for_detail,
    _bool_int,
    _build_item_groups,
    _clear_batch,
    _effective_price,
    _float,
    _int,
    _is_valid_detail,
    _item_code_for_group,
    _json_dumps,
    _missing_related_skus,
    _parent_sku_for_item,
    _shipping_fee_range,
    _text,
    _variation_attributes_by_sku,
    resolve_giga_data_source_context,
)
from app.services.giga_product_drafts import upsert_product_drafts_from_giga_batch
from app.task_runtime.events import update_step_progress
from app.task_runtime.constants import RUN_STATUS_SUCCEEDED
from app.task_runtime.json_utils import json_dumps, json_loads
from app.task_runtime.registry import TaskContext, register_worker


def _chunks(items: list[str], size: int) -> list[list[str]]:
    return [items[index:index + size] for index in range(0, len(items), size)]


def _payload(step: TaskStep) -> dict[str, Any]:
    value = json_loads(step.payload_json, {})
    return value if isinstance(value, dict) else {}


async def _context_from_payload(ctx: TaskContext, payload: dict[str, Any]):
    return await resolve_giga_data_source_context(
        ctx.db,
        int(payload["data_source_id"]),
        str(payload.get("site") or ""),
    )


async def _group_by_key(ctx: TaskContext, group_key: str) -> TaskGroup:
    result = await ctx.db.execute(
        select(TaskGroup).where(TaskGroup.task_run_id == ctx.run.id, TaskGroup.group_key == group_key)
    )
    group = result.scalar_one_or_none()
    if not group:
        raise RuntimeError(f"任务缺少 group: {group_key}")
    return group


async def _batch(ctx: TaskContext, batch_id: str, site: str, data_source_id: int) -> GigaSyncBatch:
    result = await ctx.db.execute(
        select(GigaSyncBatch).where(
            GigaSyncBatch.batch_id == batch_id,
            GigaSyncBatch.site == site,
            GigaSyncBatch.data_source_id == data_source_id,
        )
    )
    batch = result.scalar_one_or_none()
    if not batch:
        raise RuntimeError(f"GIGA batch 不存在: {batch_id}")
    return batch


async def giga_pull_plan(ctx: TaskContext) -> dict[str, Any]:
    payload = _payload(ctx.step)
    context = await _context_from_payload(ctx, payload)
    batch_id = str(payload["batch_id"])
    site = context.site
    data_source_id = int(context.id or 0)
    page_size = int(payload.get("page_size") or settings.GIGA_SYNC_PAGE_SIZE)
    max_pages = payload.get("max_pages")
    max_pages = int(max_pages) if max_pages else None
    skip_existing = bool(payload.get("skip_existing", True))

    batch_result = await ctx.db.execute(
        select(GigaSyncBatch).where(
            GigaSyncBatch.batch_id == batch_id,
            GigaSyncBatch.site == site,
            GigaSyncBatch.data_source_id == data_source_id,
        )
    )
    batch = batch_result.scalar_one_or_none()
    if not batch:
        batch = GigaSyncBatch(batch_id=batch_id, site=site, data_source_id=data_source_id)
        ctx.db.add(batch)
    batch.task_id = f"task_run:{ctx.run.id}"
    batch.data_source_name = context.name
    batch.fulfillment_mode = context.fulfillment_mode
    batch.current_category = payload.get("current_category")
    batch.status = "running"
    batch.error_message = None
    batch.started_at = batch.started_at or datetime.now()
    batch.finished_at = None
    batch.updated_at = datetime.now()
    if not skip_existing:
        await _clear_batch(ctx.db, batch_id, site, data_source_id)
    ctx.db.add(batch)
    await ctx.db.commit()

    client = GigaOpenApiClient(api_base=context.api_base, client_id=context.client_id, client_secret=context.client_secret)
    records = await client.fetch_sku_records(
        page_size,
        max_pages,
        progress_callback=lambda live: update_step_progress(
            ctx.db,
            ctx.step,
            current=int(live.get("progress_current") or live.get("scanned_sku_count") or 0),
            total=int(live.get("progress_total") or 0),
            message=str(live.get("current_message") or "读取 SKU 列表"),
            data=live,
        ),
    )
    listed_skus = list(dict.fromkeys(_text(item.get("sku")) for item in records if _text(item.get("sku"))))
    if not listed_skus:
        raise RuntimeError("GIGA 商品列表返回 0 个 SKU")

    sku_codes = listed_skus
    skipped_existing_count = 0
    if skip_existing:
        existing_query = select(GigaSku.sku_code).where(GigaSku.site == site, GigaSku.data_source_id == data_source_id)
        existing_result = await ctx.db.execute(existing_query)
        existing_skus = {sku for sku in existing_result.scalars().all() if sku}
        sku_codes = [sku for sku in listed_skus if sku not in existing_skus]
        skipped_existing_count = len(listed_skus) - len(sku_codes)

    details_group = await _group_by_key(ctx, "details")
    inventory_group = await _group_by_key(ctx, "inventory")
    prices_group = await _group_by_key(ctx, "prices")
    finalize_group = await _group_by_key(ctx, "finalize")
    aggregate_group = await _group_by_key(ctx, "aggregate")
    materialize_group = await _group_by_key(ctx, "materialize")

    if not sku_codes:
        now = datetime.now()
        for group in (details_group, inventory_group, prices_group, finalize_group, aggregate_group, materialize_group):
            group.status = RUN_STATUS_SUCCEEDED
            group.progress_current = 0
            group.progress_total = 0
            group.summary_json = json_dumps({"status": "noop", "reason": "所有远端 SKU 已存在，本次无需拉取新 SKU"})
            group.started_at = group.started_at or now
            group.finished_at = now
            group.updated_at = now
        batch.raw_sku_count = 0
        batch.sku_count = 0
        batch.item_count = 0
        batch.price_count = 0
        batch.inventory_count = 0
        batch.group_count = 0
        batch.deleted_single_sku_group_count = 0
        batch.status = "done"
        batch.error_message = None
        batch.finished_at = now
        batch.updated_at = now
        ctx.run.summary_json = json_dumps({
            "status": "noop",
            "batch_id": batch_id,
            "site": site,
            "data_source_id": data_source_id,
            "data_source_name": context.name,
            "listed_sku_count": len(listed_skus),
            "sku_count": 0,
            "skipped_existing_count": skipped_existing_count,
            "chunk_count": 0,
            "message": "所有远端 SKU 已存在，本次无需拉取新 SKU",
        })
        await ctx.db.commit()
        return json_loads(ctx.run.summary_json, {})

    chunk_size = 200
    detail_chunks = _chunks(sku_codes, chunk_size)
    for index, chunk in enumerate(detail_chunks, start=1):
        ctx.db.add(TaskStep(
            task_run_id=ctx.run.id,
            task_group_id=details_group.id,
            step_key=f"details-{index:04d}",
            step_type="giga_pull_detail_chunk",
            status="pending",
            sort_order=index,
            payload_json=json_dumps({**payload, "sku_codes": chunk, "chunk_index": index, "chunk_total": len(detail_chunks)}),
            max_attempts=3,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        ))
        ctx.db.add(TaskStep(
            task_run_id=ctx.run.id,
            task_group_id=inventory_group.id,
            step_key=f"inventory-{index:04d}",
            step_type="giga_pull_inventory_chunk",
            status="pending",
            sort_order=index,
            payload_json=json_dumps({**payload, "sku_codes": chunk, "chunk_index": index, "chunk_total": len(detail_chunks)}),
            max_attempts=3,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        ))
        ctx.db.add(TaskStep(
            task_run_id=ctx.run.id,
            task_group_id=prices_group.id,
            step_key=f"prices-{index:04d}",
            step_type="giga_pull_price_chunk",
            status="pending",
            sort_order=index,
            payload_json=json_dumps({**payload, "sku_codes": chunk, "chunk_index": index, "chunk_total": len(detail_chunks)}),
            max_attempts=3,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        ))

    for group in (details_group, inventory_group, prices_group):
        group.progress_total = len(detail_chunks)
        group.updated_at = datetime.now()
    for group_key, group, step_type in (
        ("finalize", finalize_group, "giga_pull_finalize_snapshot"),
        ("aggregate", aggregate_group, "giga_pull_aggregate_items"),
        ("materialize", materialize_group, "giga_pull_materialize_products"),
    ):
        ctx.db.add(TaskStep(
            task_run_id=ctx.run.id,
            task_group_id=group.id,
            step_key=group_key,
            step_type=step_type,
            status="pending",
            sort_order=1,
            payload_json=json_dumps({
                **payload,
                "listed_sku_count": len(listed_skus),
                "sku_codes": sku_codes,
                "skipped_existing_count": skipped_existing_count,
            }),
            max_attempts=3,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        ))
        group.progress_total = 1
        group.updated_at = datetime.now()

    batch.raw_sku_count = len(listed_skus)
    batch.sku_count = len(sku_codes)
    batch.updated_at = datetime.now()
    ctx.run.summary_json = json_dumps({
        "batch_id": batch_id,
        "site": site,
        "data_source_id": data_source_id,
        "data_source_name": context.name,
        "listed_sku_count": len(listed_skus),
        "sku_count": len(sku_codes),
        "skipped_existing_count": skipped_existing_count,
    })
    await ctx.db.commit()
    return {
        "batch_id": batch_id,
        "site": site,
        "data_source_id": data_source_id,
        "listed_sku_count": len(listed_skus),
        "sku_count": len(sku_codes),
        "skipped_existing_count": skipped_existing_count,
        "chunk_count": len(detail_chunks),
    }


async def giga_pull_detail_chunk(ctx: TaskContext) -> dict[str, Any]:
    payload = _payload(ctx.step)
    context = await _context_from_payload(ctx, payload)
    sku_codes = [str(sku) for sku in payload.get("sku_codes") or [] if str(sku or "").strip()]
    client = GigaOpenApiClient(api_base=context.api_base, client_id=context.client_id, client_secret=context.client_secret)
    details = await client.fetch_details(sku_codes)
    pulled_at = datetime.now()
    await ctx.db.execute(
        delete(GigaRawSkuDetail).where(
            GigaRawSkuDetail.batch_id == payload["batch_id"],
            GigaRawSkuDetail.site == context.site,
            GigaRawSkuDetail.data_source_id == context.id,
            GigaRawSkuDetail.sku_code.in_(sku_codes),
        )
    )
    rows = [
        GigaRawSkuDetail(
            batch_id=payload["batch_id"],
            site=context.site,
            data_source_id=context.id,
            sku_code=str(detail.get("sku") or ""),
            data_json=_json_dumps(detail),
            source_platform=SOURCE_PLATFORM,
            pulled_at=pulled_at,
        )
        for detail in details
        if _text(detail.get("sku"))
    ]
    ctx.db.add_all(rows)
    await ctx.db.commit()
    await update_step_progress(ctx.db, ctx.step, current=len(sku_codes), total=len(sku_codes), message="SKU 详情 chunk 已写入")
    return {"requested_count": len(sku_codes), "detail_count": len(rows)}


async def giga_pull_price_chunk(ctx: TaskContext) -> dict[str, Any]:
    payload = _payload(ctx.step)
    context = await _context_from_payload(ctx, payload)
    sku_codes = [str(sku) for sku in payload.get("sku_codes") or [] if str(sku or "").strip()]
    client = GigaOpenApiClient(api_base=context.api_base, client_id=context.client_id, client_secret=context.client_secret)
    prices = await client.fetch_prices(sku_codes)
    await ctx.db.execute(
        delete(GigaPrice).where(
            GigaPrice.batch_id == payload["batch_id"],
            GigaPrice.site == context.site,
            GigaPrice.data_source_id == context.id,
            GigaPrice.sku_code.in_(sku_codes),
        )
    )
    pulled_at = datetime.now()
    rows: list[GigaPrice] = []
    for price in prices:
        sku = _text(price.get("sku"))
        if not sku:
            continue
        shipping_fee_min, shipping_fee_max = _shipping_fee_range(price)
        rows.append(GigaPrice(
            batch_id=payload["batch_id"],
            site=context.site,
            data_source_id=context.id,
            fulfillment_mode=context.fulfillment_mode,
            shipping_cost_mode=context.shipping_cost_mode,
            packing_fee=context.packing_fee,
            sku_code=sku,
            task_id=f"task_run:{ctx.run.id}",
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
    ctx.db.add_all(rows)
    await ctx.db.commit()
    await update_step_progress(ctx.db, ctx.step, current=len(sku_codes), total=len(sku_codes), message="SKU 价格 chunk 已写入")
    return {"requested_count": len(sku_codes), "price_count": len(rows)}


async def giga_pull_inventory_chunk(ctx: TaskContext) -> dict[str, Any]:
    payload = _payload(ctx.step)
    context = await _context_from_payload(ctx, payload)
    sku_codes = [str(sku) for sku in payload.get("sku_codes") or [] if str(sku or "").strip()]
    client = GigaOpenApiClient(api_base=context.api_base, client_id=context.client_id, client_secret=context.client_secret)
    inventory = await client.fetch_inventory(sku_codes)
    await ctx.db.execute(
        delete(GigaInventory).where(
            GigaInventory.batch_id == payload["batch_id"],
            GigaInventory.site == context.site,
            GigaInventory.data_source_id == context.id,
            GigaInventory.sku_code.in_(sku_codes),
        )
    )
    pulled_at = datetime.now()
    rows: list[GigaInventory] = []
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
        rows.append(GigaInventory(
            batch_id=payload["batch_id"],
            site=context.site,
            data_source_id=context.id,
            fulfillment_mode=context.fulfillment_mode,
            inventory_mode=context.inventory_mode,
            sku_code=sku,
            task_id=f"task_run:{ctx.run.id}",
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
    ctx.db.add_all(rows)
    await ctx.db.commit()
    await update_step_progress(ctx.db, ctx.step, current=len(sku_codes), total=len(sku_codes), message="SKU 库存 chunk 已写入")
    return {"requested_count": len(sku_codes), "inventory_count": len(rows)}


async def giga_pull_finalize_snapshot(ctx: TaskContext) -> dict[str, Any]:
    payload = _payload(ctx.step)
    context = await _context_from_payload(ctx, payload)
    sku_codes = [str(sku) for sku in payload.get("sku_codes") or [] if str(sku or "").strip()]
    batch_id = str(payload["batch_id"])
    queries = {
        "details": select(GigaRawSkuDetail.sku_code).where(GigaRawSkuDetail.batch_id == batch_id, GigaRawSkuDetail.site == context.site, GigaRawSkuDetail.data_source_id == context.id),
        "prices": select(GigaPrice.sku_code).where(GigaPrice.batch_id == batch_id, GigaPrice.site == context.site, GigaPrice.data_source_id == context.id),
        "inventory": select(GigaInventory.sku_code).where(GigaInventory.batch_id == batch_id, GigaInventory.site == context.site, GigaInventory.data_source_id == context.id),
    }
    missing: dict[str, list[str]] = {}
    for key, query in queries.items():
        result = await ctx.db.execute(query)
        found = {value for value in result.scalars().all() if value}
        missing[key] = [sku for sku in sku_codes if sku not in found]
    if any(missing.values()):
        raise RuntimeError(f"GIGA snapshot 不完整: {json_dumps({key: len(value) for key, value in missing.items()})}")
    batch = await _batch(ctx, batch_id, context.site, int(context.id or 0))
    batch.raw_sku_count = len(sku_codes)
    batch.price_count = len(sku_codes)
    batch.inventory_count = len(sku_codes)
    batch.updated_at = datetime.now()
    await ctx.db.commit()
    return {"sku_count": len(sku_codes), "missing": missing}


async def giga_pull_aggregate_items(ctx: TaskContext) -> dict[str, Any]:
    payload = _payload(ctx.step)
    context = await _context_from_payload(ctx, payload)
    batch_id = str(payload["batch_id"])
    result = await ctx.db.execute(
        select(GigaRawSkuDetail).where(
            GigaRawSkuDetail.batch_id == batch_id,
            GigaRawSkuDetail.site == context.site,
            GigaRawSkuDetail.data_source_id == context.id,
        )
    )
    raw_rows = result.scalars().all()
    details_by_sku = {
        row.sku_code: json_loads(row.data_json, {})
        for row in raw_rows
        if row.sku_code and isinstance(json_loads(row.data_json, {}), dict)
    }
    valid_sku_codes = [sku for sku in sorted(details_by_sku) if _is_valid_detail(details_by_sku.get(sku))]
    if not valid_sku_codes:
        raise RuntimeError("没有有效 SKU 详情可聚合")
    groups = _build_item_groups(list(details_by_sku.values()), valid_sku_codes)

    await ctx.db.execute(delete(GigaProductImage).where(GigaProductImage.batch_id == batch_id, GigaProductImage.site == context.site, GigaProductImage.data_source_id == context.id))
    await ctx.db.execute(delete(GigaSku).where(GigaSku.batch_id == batch_id, GigaSku.site == context.site, GigaSku.data_source_id == context.id))
    await ctx.db.execute(delete(GigaItem).where(GigaItem.batch_id == batch_id, GigaItem.site == context.site, GigaItem.data_source_id == context.id))
    await ctx.db.execute(delete(GigaGroup).where(GigaGroup.batch_id == batch_id, GigaGroup.site == context.site, GigaGroup.data_source_id == context.id))
    await ctx.db.flush()

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
            batch_id=batch_id,
            site=context.site,
            data_source_id=context.id,
            data_source_name=context.name,
            fulfillment_mode=context.fulfillment_mode,
            item_code=item_code,
            parent_sku_code=parent_sku_code,
            item_name=item_name,
            category=payload.get("current_category"),
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
            batch_id=batch_id,
            site=context.site,
            data_source_id=context.id,
            data_source_name=context.name,
            fulfillment_mode=context.fulfillment_mode,
            group_code=item_code,
            parent_sku_code=parent_sku_code,
            current_category=payload.get("current_category"),
            item_codes_json=_json_dumps([item_code]),
            sku_codes_json=_json_dumps(group_skus),
            missing_related_skus_json=_json_dumps(missing_related_skus),
            variation_keys_json=_json_dumps(variation_keys),
            group_size=len(group_skus),
            deleted_single_sku_group=1 if is_single else 0,
        ))
    ctx.db.add_all(item_rows)
    await ctx.db.flush()

    group_skus_by_item = {
        _item_code_for_group(group_skus, details_by_sku): group_skus
        for group_skus in groups.values()
    }
    variation_by_item = {
        item_code: _variation_attributes_by_sku(group_skus, details_by_sku)[0]
        for item_code, group_skus in group_skus_by_item.items()
    }
    sku_rows: list[GigaSku] = []
    for sku in valid_sku_codes:
        detail = details_by_sku.get(sku, {})
        item_code = sku_to_item.get(sku)
        group_skus = group_skus_by_item.get(item_code or "", [sku])
        sku_rows.append(GigaSku(
            item=item_by_code.get(item_code or ""),
            batch_id=batch_id,
            site=context.site,
            data_source_id=context.id,
            data_source_name=context.name,
            fulfillment_mode=context.fulfillment_mode,
            sku_code=sku,
            item_code=item_code,
            parent_sku_code=_parent_sku_for_item(item_code) if item_code else None,
            parentage="child" if len(group_skus) > 1 else "single",
            child_sequence=(group_skus.index(sku) + 1) if sku in group_skus else None,
            is_primary_child=1 if sku == item_code else 0,
            product_name=_text(detail.get("productName")),
            main_image_url=_text(detail.get("mainImageUrl")),
            description=_text(detail.get("description")),
            attributes_json=_json_dumps(_attributes_for_detail(detail)),
            variation_attributes_json=_json_dumps(variation_by_item.get(item_code or "", {}).get(sku, {})),
            source_platform=SOURCE_PLATFORM,
        ))
    image_candidates = []
    for sku in valid_sku_codes:
        image_candidates.extend(extract_giga_image_candidates(sku_code=sku, item_code=sku_to_item.get(sku), detail=details_by_sku.get(sku, {})))
    image_rows = build_pending_giga_product_image_rows(
        batch_id=batch_id,
        site=context.site,
        candidates=image_candidates,
        data_source_id=context.id,
    )
    ctx.db.add_all(sku_rows + image_rows + group_rows)
    batch = await _batch(ctx, batch_id, context.site, int(context.id or 0))
    batch.raw_sku_count = len(raw_rows)
    batch.sku_count = len(sku_rows)
    batch.item_count = len(item_rows)
    batch.group_count = len([row for row in group_rows if not row.deleted_single_sku_group])
    batch.deleted_single_sku_group_count = deleted_single_sku_group_count
    batch.updated_at = datetime.now()
    await ctx.db.commit()
    return {
        "raw_sku_count": len(raw_rows),
        "sku_count": len(sku_rows),
        "item_count": len(item_rows),
        "image_url_count": len(image_rows),
        "group_count": batch.group_count,
        "deleted_single_sku_group_count": deleted_single_sku_group_count,
    }


async def giga_pull_materialize_products(ctx: TaskContext) -> dict[str, Any]:
    payload = _payload(ctx.step)
    context = await _context_from_payload(ctx, payload)
    batch_id = str(payload["batch_id"])
    draft_result = await upsert_product_drafts_from_giga_batch(
        ctx.db,
        batch_id=batch_id,
        site=context.site,
        data_source_id=context.id,
    )
    batch = await _batch(ctx, batch_id, context.site, int(context.id or 0))
    price_count = await ctx.db.scalar(select(func.count(GigaPrice.id)).where(GigaPrice.batch_id == batch_id, GigaPrice.site == context.site, GigaPrice.data_source_id == context.id))
    inventory_count = await ctx.db.scalar(select(func.count(GigaInventory.id)).where(GigaInventory.batch_id == batch_id, GigaInventory.site == context.site, GigaInventory.data_source_id == context.id))
    batch.price_count = int(price_count or 0)
    batch.inventory_count = int(inventory_count or 0)
    batch.status = "done"
    batch.error_message = None
    batch.finished_at = datetime.now()
    batch.updated_at = datetime.now()
    ctx.run.summary_json = json_dumps({
        "batch_id": batch_id,
        "site": context.site,
        "data_source_id": context.id,
        "data_source_name": context.name,
        "raw_sku_count": batch.raw_sku_count,
        "sku_count": batch.sku_count,
        "item_count": batch.item_count,
        "price_count": batch.price_count,
        "inventory_count": batch.inventory_count,
        "group_count": batch.group_count,
        "deleted_single_sku_group_count": batch.deleted_single_sku_group_count,
        "product_created": draft_result.created,
        "product_updated": draft_result.updated,
        "product_skipped": draft_result.skipped,
        "product_ids": draft_result.product_ids,
    })
    await ctx.db.commit()
    return json_loads(ctx.run.summary_json, {})


def register_giga_pull_workers() -> None:
    register_worker("giga_pull_plan", giga_pull_plan)
    register_worker("giga_pull_detail_chunk", giga_pull_detail_chunk)
    register_worker("giga_pull_inventory_chunk", giga_pull_inventory_chunk)
    register_worker("giga_pull_price_chunk", giga_pull_price_chunk)
    register_worker("giga_pull_finalize_snapshot", giga_pull_finalize_snapshot)
    register_worker("giga_pull_aggregate_items", giga_pull_aggregate_items)
    register_worker("giga_pull_materialize_products", giga_pull_materialize_products)
