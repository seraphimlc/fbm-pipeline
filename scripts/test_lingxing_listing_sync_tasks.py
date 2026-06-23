from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
import sys

from sqlalchemy import delete, func, select
from sqlalchemy.orm import selectinload

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.database import async_session, run_schema_maintenance  # noqa: E402
from app.models import CatalogProduct, Product, ProductData, TaskGroup, TaskRun, TaskStep, TaskStepEvent  # noqa: E402
from app.config import settings  # noqa: E402
from app.services import lingxing_listing_client as listing_client_mod  # noqa: E402
from app.services.asin_match_policy import LingxingListingRow  # noqa: E402
from app.services.lingxing_listing_client import LingxingListingQuery, LingxingListingQueryResult  # noqa: E402
from app.task_planners.lingxing_listing_sync import create_lingxing_listing_sync_runs  # noqa: E402
from app.task_runtime import lingxing_listing_sync_workers as worker_mod  # noqa: E402
from app.task_runtime.registry import TaskContext  # noqa: E402


TEST_PREFIX = "T2_LINGXING_LISTING_SYNC_"


class FakeListingClient:
    rows_by_sku: dict[str, LingxingListingQueryResult] = {}

    async def fetch_listing_rows(self, query: LingxingListingQuery) -> LingxingListingQueryResult:
        return self.rows_by_sku.get(query.seller_sku, LingxingListingQueryResult())


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


async def _cleanup() -> None:
    async with async_session() as session:
        product_ids = list(
            (
                await session.execute(select(Product.id).where(Product.gigab2b_product_id.like(f"{TEST_PREFIX}%")))
            ).scalars().all()
        )
        run_ids = list(
            (
                await session.execute(select(TaskRun.id).where(TaskRun.created_by == "lingxing-listing-t2-test"))
            ).scalars().all()
        )
        if run_ids:
            await session.execute(delete(TaskStepEvent).where(TaskStepEvent.task_run_id.in_(run_ids)))
            await session.execute(delete(TaskStep).where(TaskStep.task_run_id.in_(run_ids)))
            await session.execute(delete(TaskGroup).where(TaskGroup.task_run_id.in_(run_ids)))
            await session.execute(delete(TaskRun).where(TaskRun.id.in_(run_ids)))
        if product_ids:
            await session.execute(delete(CatalogProduct).where(CatalogProduct.source_product_id.in_(product_ids)))
            await session.execute(delete(ProductData).where(ProductData.product_id.in_(product_ids)))
            await session.execute(delete(Product).where(Product.id.in_(product_ids)))
        await session.commit()


async def _make_product(
    session,
    marker: str,
    *,
    seller_sku: str | None,
    item_code: str | None = None,
    exported: bool = True,
    upc: str | None = None,
    existing_asin: str | None = None,
    product_asin: str | None = None,
    catalog_asin: str | None = None,
) -> CatalogProduct:
    now = datetime.now()
    code = item_code or seller_sku or f"{TEST_PREFIX}{marker}"
    product_local_asin = product_asin if product_asin is not None else existing_asin
    catalog_local_asin = catalog_asin if catalog_asin is not None else existing_asin
    product = Product(
        gigab2b_url=f"https://t2.example/{marker}",
        gigab2b_product_id=f"{TEST_PREFIX}{marker}",
        upc=upc,
        amazon_asin=product_local_asin,
        amazon_seller_sku=seller_sku,
        asin_sync_status="not_synced",
        aplus_upload_status="not_uploaded",
        status="completed",
        current_step=6,
        created_at=now,
        updated_at=now,
    )
    product.data = ProductData(item_code=code, title=f"T2 fixture {marker}", listing_title=f"T2 fixture {marker}")
    product.catalog_item = CatalogProduct(
        gigab2b_url=product.gigab2b_url,
        gigab2b_product_id=product.gigab2b_product_id,
        amazon_asin=catalog_local_asin,
        amazon_seller_sku=seller_sku,
        asin_sync_status="not_synced",
        aplus_upload_status="not_uploaded",
        upc=upc,
        item_code=code,
        title=f"T2 fixture {marker}",
        status="completed",
        confirmed_at=now,
        exported_at=now if exported else None,
    )
    session.add(product)
    await session.flush()
    return product.catalog_item


async def _run_sync(catalog: CatalogProduct) -> CatalogProduct:
    async with async_session() as session:
        runs, errors = await create_lingxing_listing_sync_runs(
            session,
            [catalog.id],
            store_id="17983",
            site="US",
            created_by="lingxing-listing-t2-test",
            auto_start=False,
        )
        assert_true(not errors, f"planner returned errors: {errors}")
        assert_true(len(runs) == 1, "planner should create or reuse one run")
        step = (
            await session.execute(
                select(TaskStep)
                .where(TaskStep.task_run_id == runs[0].id)
                .options(selectinload(TaskStep.task_group), selectinload(TaskStep.task_run))
            )
        ).scalar_one()
        await worker_mod.lingxing_listing_sync_product(
            TaskContext(db=session, run=step.task_run, group=step.task_group, step=step)
        )
        await session.commit()

    async with async_session() as session:
        refreshed = (
            await session.execute(
                select(CatalogProduct)
                .where(CatalogProduct.id == catalog.id)
                .options(selectinload(CatalogProduct.source_product))
            )
        ).scalar_one()
        return refreshed


async def _test_planner_idempotency(catalog: CatalogProduct) -> None:
    async with async_session() as session:
        first, errors = await create_lingxing_listing_sync_runs(
            session,
            [catalog.id],
            store_id="17983",
            site="US",
            created_by="lingxing-listing-t2-test",
            auto_start=False,
        )
        assert_true(not errors and len(first) == 1, "first planner call should create one run")
        second, errors = await create_lingxing_listing_sync_runs(
            session,
            [catalog.id],
            store_id="17983",
            site="US",
            created_by="lingxing-listing-t2-test",
            auto_start=False,
        )
        assert_true(not errors and len(second) == 1, "second planner call should reuse one run")
        assert_true(first[0].id == second[0].id, "active duplicate trigger must reuse the same dedupe run")
        count = (
            await session.execute(
                select(func.count(TaskRun.id)).where(
                    TaskRun.created_by == "lingxing-listing-t2-test",
                    TaskRun.dedupe_key == first[0].dedupe_key,
                )
            )
        ).scalar_one()
        assert_true(count == 1, "duplicate trigger must not create a second active run")


async def _test_real_external_requires_store_config() -> None:
    old_allow = settings.LINGXING_LISTING_SYNC_ALLOW_REAL_EXTERNAL_CALLS
    old_store_name = settings.LINGXING_APLUS_STORE_NAME
    old_store_id = settings.LINGXING_APLUS_STORE_ID
    old_auth = listing_client_mod._get_lingxing_listing_auth

    async def forbidden_auth(_store_name):
        raise AssertionError("store_config_required must fail before old auth default fallback is called")

    settings.LINGXING_LISTING_SYNC_ALLOW_REAL_EXTERNAL_CALLS = True
    settings.LINGXING_APLUS_STORE_NAME = ""
    settings.LINGXING_APLUS_STORE_ID = ""
    listing_client_mod._get_lingxing_listing_auth = forbidden_auth
    try:
        try:
            await listing_client_mod.LingxingListingClient().fetch_listing_rows(
                LingxingListingQuery(seller_sku="T2-STORE-CONFIG-MISSING")
            )
        except listing_client_mod.LingxingListingClientError as exc:
            assert_true(exc.code == "store_config_required", "missing store config should raise typed store_config_required")
        else:
            raise AssertionError("missing store config should fail closed before real Lingxing auth")
    finally:
        listing_client_mod._get_lingxing_listing_auth = old_auth
        settings.LINGXING_LISTING_SYNC_ALLOW_REAL_EXTERNAL_CALLS = old_allow
        settings.LINGXING_APLUS_STORE_NAME = old_store_name
        settings.LINGXING_APLUS_STORE_ID = old_store_id


async def main() -> None:
    await run_schema_maintenance()
    await _cleanup()
    original_factory = worker_mod.listing_client_factory
    worker_mod.listing_client_factory = FakeListingClient
    try:
        async with async_session() as session:
            no_sku = await _make_product(session, "NO_SKU", seller_sku=None, item_code="", exported=False)
            zero = await _make_product(session, "ZERO", seller_sku="T2-ZERO")
            multiple = await _make_product(session, "MULTI", seller_sku="T2-MULTI")
            success = await _make_product(session, "SUCCESS", seller_sku="T2-SUCCESS")
            upc_only = await _make_product(session, "UPC", seller_sku="T2-UPC-NOMATCH", upc="UPC123")
            conflict = await _make_product(session, "CONFLICT", seller_sku="T2-CONFLICT", existing_asin="B0LOCAL001")
            product_only_conflict = await _make_product(
                session,
                "PRODUCT_ONLY_CONFLICT",
                seller_sku="T2-PRODUCT-ONLY-CONFLICT",
                product_asin="B0PROD0001",
                catalog_asin=None,
            )
            catalog_only_conflict = await _make_product(
                session,
                "CATALOG_ONLY_CONFLICT",
                seller_sku="T2-CATALOG-ONLY-CONFLICT",
                product_asin=None,
                catalog_asin="B0CAT00001",
            )
            local_mirror_conflict = await _make_product(
                session,
                "LOCAL_MIRROR_CONFLICT",
                seller_sku="T2-LOCAL-MIRROR-CONFLICT",
                product_asin="B0PROD0002",
                catalog_asin="B0CAT00002",
            )
            exported_without_seller_sku = await _make_product(
                session,
                "EXPORTED_NO_SKU",
                seller_sku=None,
                item_code="T2-EXPORTED-ITEM-CODE",
                exported=True,
            )
            wrong_market = await _make_product(session, "MARKET", seller_sku="T2-MARKET")
            not_sellable = await _make_product(session, "UNSELL", seller_sku="T2-UNSELL")
            idem = await _make_product(session, "IDEM", seller_sku="T2-IDEM")
            await session.commit()

        FakeListingClient.rows_by_sku = {
            "T2-MULTI": LingxingListingQueryResult(rows=[
                LingxingListingRow(msku="T2-MULTI", asin="B0MULTI001", store_id="17983", site="US"),
                LingxingListingRow(msku="T2-MULTI", asin="B0MULTI002", store_id="17983", site="US"),
            ]),
            "T2-SUCCESS": LingxingListingQueryResult(rows=[
                LingxingListingRow(msku="T2-SUCCESS", asin="B0SUCCESS1", store_id="17983", site="US", amazon_product_status="在售"),
            ]),
            "T2-UPC-NOMATCH": LingxingListingQueryResult(
                rows=[],
                auxiliary_rows=[LingxingListingRow(msku="OTHER-MSKU", asin="B0UPCONLY1", store_id="17983", site="US")],
            ),
            "T2-CONFLICT": LingxingListingQueryResult(rows=[
                LingxingListingRow(msku="T2-CONFLICT", asin="B0REMOTE01", store_id="17983", site="US"),
            ]),
            "T2-PRODUCT-ONLY-CONFLICT": LingxingListingQueryResult(rows=[
                LingxingListingRow(msku="T2-PRODUCT-ONLY-CONFLICT", asin="B0REMOTE02", store_id="17983", site="US"),
            ]),
            "T2-CATALOG-ONLY-CONFLICT": LingxingListingQueryResult(rows=[
                LingxingListingRow(msku="T2-CATALOG-ONLY-CONFLICT", asin="B0REMOTE03", store_id="17983", site="US"),
            ]),
            "T2-LOCAL-MIRROR-CONFLICT": LingxingListingQueryResult(rows=[
                LingxingListingRow(msku="T2-LOCAL-MIRROR-CONFLICT", asin="B0PROD0002", store_id="17983", site="US"),
            ]),
            "T2-EXPORTED-ITEM-CODE": LingxingListingQueryResult(rows=[
                LingxingListingRow(msku="T2-EXPORTED-ITEM-CODE", asin="B0LEGACY01", store_id="17983", site="US"),
            ]),
            "T2-MARKET": LingxingListingQueryResult(rows=[
                LingxingListingRow(msku="T2-MARKET", asin="B0MARKET01", store_id="99999", site="CA"),
            ]),
            "T2-UNSELL": LingxingListingQueryResult(rows=[
                LingxingListingRow(msku="T2-UNSELL", asin="B0UNSELL01", store_id="17983", site="US", is_sellable=False, status_text="停售"),
            ]),
        }

        no_sku_result = await _run_sync(no_sku)
        assert_true(no_sku_result.asin_sync_status == "waiting_listing", "missing seller SKU should wait for listing")
        assert_true(no_sku_result.amazon_asin is None, "missing seller SKU must not write ASIN")

        zero_result = await _run_sync(zero)
        assert_true(zero_result.asin_sync_status == "not_found", "seller SKU zero match should be not_found")
        assert_true("seller_sku_not_found" in (zero_result.asin_match_source or ""), "zero match should record seller SKU source")

        multi_result = await _run_sync(multiple)
        assert_true(multi_result.asin_sync_status == "multiple_found", "multiple seller SKU rows should be blocked")
        assert_true(multi_result.amazon_asin is None, "multiple match must not write ASIN")

        success_result = await _run_sync(success)
        assert_true(success_result.asin_sync_status == "synced", "unique seller SKU match should sync")
        assert_true(success_result.amazon_asin == "B0SUCCESS1", "unique seller SKU match should write ASIN")
        assert_true(success_result.source_product.amazon_asin == "B0SUCCESS1", "Product mirror should receive ASIN")

        upc_result = await _run_sync(upc_only)
        assert_true(upc_result.asin_sync_status == "not_found", "UPC auxiliary hit must not satisfy seller SKU match")
        assert_true("upc_auxiliary_only" in (upc_result.asin_match_evidence_json or ""), "UPC hit should be diagnostic evidence only")
        assert_true(upc_result.amazon_asin is None, "UPC-only hit must not write ASIN")

        conflict_result = await _run_sync(conflict)
        assert_true(conflict_result.asin_sync_status == "asin_conflict", "ASIN conflict should be blocked")
        assert_true(conflict_result.amazon_asin == "B0LOCAL001", "ASIN conflict must not overwrite local ASIN")
        assert_true(conflict_result.source_product.amazon_asin == "B0LOCAL001", "ASIN conflict must not overwrite Product ASIN")

        product_only_result = await _run_sync(product_only_conflict)
        assert_true(product_only_result.asin_sync_status == "asin_conflict", "Product-only ASIN conflict should be blocked")
        assert_true(product_only_result.amazon_asin is None, "Product-only conflict must not write Catalog ASIN")
        assert_true(product_only_result.source_product.amazon_asin == "B0PROD0001", "Product-only conflict must not overwrite Product ASIN")

        catalog_only_result = await _run_sync(catalog_only_conflict)
        assert_true(catalog_only_result.asin_sync_status == "asin_conflict", "Catalog-only ASIN conflict should be blocked")
        assert_true(catalog_only_result.amazon_asin == "B0CAT00001", "Catalog-only conflict must not overwrite Catalog ASIN")
        assert_true(catalog_only_result.source_product.amazon_asin is None, "Catalog-only conflict must not write Product ASIN")

        local_mirror_result = await _run_sync(local_mirror_conflict)
        assert_true(local_mirror_result.asin_sync_status == "asin_conflict", "Product/Catalog local ASIN mismatch should be blocked before choosing one")
        assert_true(local_mirror_result.amazon_asin == "B0CAT00002", "local mirror conflict must not overwrite Catalog ASIN")
        assert_true(local_mirror_result.source_product.amazon_asin == "B0PROD0002", "local mirror conflict must not overwrite Product ASIN")

        legacy_result = await _run_sync(exported_without_seller_sku)
        assert_true(legacy_result.asin_sync_status == "waiting_listing", "exported_at-only old record must not use item_code as trusted seller SKU")
        assert_true(legacy_result.amazon_asin is None, "exported_at-only old record must not write Catalog ASIN from item_code")
        assert_true(legacy_result.source_product.amazon_asin is None, "exported_at-only old record must not write Product ASIN from item_code")

        wrong_market_result = await _run_sync(wrong_market)
        assert_true(wrong_market_result.asin_sync_status == "waiting_listing", "wrong store/site should wait for correct listing")
        assert_true("wrong_store_or_site" in (wrong_market_result.asin_match_evidence_json or ""), "wrong market evidence should be recorded")

        not_sellable_result = await _run_sync(not_sellable)
        assert_true(not_sellable_result.asin_sync_status == "not_sellable", "not sellable listing should be blocked")
        assert_true(not_sellable_result.amazon_asin is None, "not sellable listing must not write ASIN")

        await _test_planner_idempotency(idem)
        await _test_real_external_requires_store_config()
    finally:
        worker_mod.listing_client_factory = original_factory
        await _cleanup()


if __name__ == "__main__":
    asyncio.run(main())
