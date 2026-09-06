"""Isolated smoke test for the restart-only local SQLite database mode."""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / "backend"


async def main() -> None:
    with tempfile.TemporaryDirectory(prefix="fbm-sqlite-mode-") as raw_dir:
        database_path = Path(raw_dir) / "fbm-pipeline.db"
        os.environ["DATABASE_BACKEND"] = "sqlite"
        os.environ["SQLITE_DATABASE_PATH"] = str(database_path)
        os.environ["DATA_DIR"] = raw_dir
        os.environ["PRODUCT_BASE_DIR"] = str(Path(raw_dir) / "products")
        os.environ["TASK_RUNTIME_AUTO_WAKE_ENABLED"] = "false"
        # The SQLite mode must not need a usable remote MySQL connection.
        os.environ.pop("DATABASE_URL", None)
        sys.path.insert(0, str(BACKEND_DIR))

        from app.config import settings
        from app.database import Base, async_session, engine, init_db

        assert settings.is_sqlite
        assert settings.effective_database_url == f"sqlite+aiosqlite:///{database_path}"
        assert settings.PIPELINE_MAX_CONCURRENCY == 1
        assert settings.APLUS_CONCURRENCY == 1

        await init_db()
        await init_db()  # The local schema initialization is repeatable.

        async with engine.connect() as connection:
            foreign_keys = await connection.exec_driver_sql("PRAGMA foreign_keys")
            table_names = await connection.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
            )
            assert foreign_keys.scalar_one() == 1
            assert set(Base.metadata.tables).issubset({row[0] for row in table_names})

        from sqlalchemy import select, update
        from sqlalchemy.orm import selectinload

        from app.api.products import _latest_giga_inventory_by_catalog_id
        from app.models import (
            CatalogProduct,
            GigaInventory,
            GigaPrice,
            GigaSku,
            GigaSyncBatch,
            Product,
            ProductData,
            ProductDataSource,
            TaskGroup,
            TaskRun,
            TaskStep,
        )
        from app.task_runtime.events import update_step_progress

        now = datetime.now()
        async with async_session() as db:
            source_a = ProductDataSource(name="sqlite-giga-a", site="US", country="US")
            source_b = ProductDataSource(name="sqlite-giga-b", site="US", country="US")
            db.add_all([source_a, source_b])
            await db.flush()
            product_a = Product(
                gigab2b_url="https://example.invalid/SKU-A",
                source_data_source_id=source_a.id,
                source_site="US",
            )
            product_a.data = ProductData(item_code="SKU-A")
            product_a.catalog_item = CatalogProduct(
                gigab2b_url=product_a.gigab2b_url,
                item_code="SKU-A",
            )
            product_b = Product(
                gigab2b_url="https://example.invalid/SKU-B",
                source_data_source_id=source_a.id,
                source_site="US",
            )
            product_b.data = ProductData(item_code="SKU-B")
            product_b.catalog_item = CatalogProduct(
                gigab2b_url=product_b.gigab2b_url,
                item_code="SKU-B",
            )
            db.add_all([product_a, product_b])
            batches = [
                GigaSyncBatch(
                    batch_id="sqlite-old-a",
                    site="US",
                    data_source_id=source_a.id,
                    status="done",
                    sku_count=1,
                    inventory_count=1,
                    finished_at=now - timedelta(days=2),
                ),
                GigaSyncBatch(
                    batch_id="sqlite-new-partial-b",
                    site="US",
                    data_source_id=source_a.id,
                    status="done",
                    sku_count=1,
                    inventory_count=1,
                    finished_at=now,
                ),
                GigaSyncBatch(
                    batch_id="sqlite-other-store-a",
                    site="US",
                    data_source_id=source_b.id,
                    status="done",
                    sku_count=1,
                    inventory_count=1,
                    finished_at=now,
                ),
                GigaSyncBatch(
                    batch_id="sqlite-incomplete-a",
                    site="US",
                    data_source_id=source_a.id,
                    status="running",
                    inventory_count=1,
                ),
            ]
            db.add_all(batches)
            db.add_all([
                GigaInventory(
                    batch_id="sqlite-old-a",
                    site="US",
                    data_source_id=source_a.id,
                    sku_code="SKU-A",
                    stock_qty=11,
                    pulled_at=now - timedelta(days=2),
                ),
                GigaInventory(
                    batch_id="sqlite-new-partial-b",
                    site="US",
                    data_source_id=source_a.id,
                    sku_code="SKU-B",
                    stock_qty=22,
                    pulled_at=now,
                ),
                GigaInventory(
                    batch_id="sqlite-other-store-a",
                    site="US",
                    data_source_id=source_b.id,
                    sku_code="SKU-A",
                    stock_qty=99,
                    pulled_at=now,
                ),
                GigaInventory(
                    batch_id="sqlite-incomplete-a",
                    site="US",
                    data_source_id=source_a.id,
                    sku_code="SKU-A",
                    stock_qty=77,
                    pulled_at=now + timedelta(minutes=1),
                ),
            ])
            db.add_all([
                GigaPrice(
                    batch_id="sqlite-old-a",
                    site="US",
                    data_source_id=source_a.id,
                    sku_code="SKU-A",
                    effective_price=10.0,
                    pulled_at=now - timedelta(days=2),
                ),
                GigaPrice(
                    batch_id="sqlite-new-partial-b",
                    site="US",
                    data_source_id=source_a.id,
                    sku_code="SKU-B",
                    effective_price=20.0,
                    pulled_at=now,
                ),
                GigaPrice(
                    batch_id="sqlite-other-store-a",
                    site="US",
                    data_source_id=source_b.id,
                    sku_code="SKU-A",
                    effective_price=99.0,
                    pulled_at=now,
                ),
            ])
            db.add_all([
                GigaSku(
                    batch_id="sqlite-old-a",
                    site="US",
                    data_source_id=source_a.id,
                    sku_code="SKU-A",
                    item_code="SKU-A",
                ),
                GigaSku(
                    batch_id="sqlite-new-partial-b",
                    site="US",
                    data_source_id=source_a.id,
                    sku_code="SKU-B",
                    item_code="SKU-B",
                ),
                GigaSku(
                    batch_id="sqlite-other-store-a",
                    site="US",
                    data_source_id=source_b.id,
                    sku_code="SKU-OTHER-STORE",
                    item_code="SKU-OTHER-STORE",
                ),
            ])
            await db.commit()

        async with async_session() as db:
            catalog_items = (
                await db.execute(
                    select(CatalogProduct)
                    .options(selectinload(CatalogProduct.source_product).selectinload(Product.data))
                    .order_by(CatalogProduct.id)
                )
            ).scalars().all()
            latest = await _latest_giga_inventory_by_catalog_id(db, catalog_items)
            assert latest[product_a.catalog_item.id].stock_qty == 11
            assert latest[product_b.catalog_item.id].stock_qty == 22

            from app.services.giga_inventory_sync import _latest_product_skus as inventory_product_skus
            from app.services.giga_price_sync import _latest_product_skus as price_product_skus
            from app.services.giga_snapshot_queries import (
                latest_completed_inventory_by_sku,
                latest_completed_price_by_sku,
                latest_completed_product_metadata_by_sku,
            )

            assert await inventory_product_skus(db, "US", source_a.id) == ["SKU-A", "SKU-B"]
            assert await price_product_skus(db, "US", source_a.id) == ["SKU-A", "SKU-B"]
            latest_inventory = await latest_completed_inventory_by_sku(
                db,
                site="US",
                data_source_id=source_a.id,
                sku_codes=["SKU-A", "SKU-B"],
            )
            assert {sku: row.stock_qty for sku, row in latest_inventory.items()} == {"SKU-A": 11, "SKU-B": 22}
            latest_price = await latest_completed_price_by_sku(
                db,
                site="US",
                data_source_id=source_a.id,
                sku_codes=["SKU-A", "SKU-B"],
            )
            assert {sku: row.effective_price for sku, row in latest_price.items()} == {"SKU-A": 10.0, "SKU-B": 20.0}
            latest_metadata = await latest_completed_product_metadata_by_sku(
                db,
                site="US",
                data_source_id=source_a.id,
                sku_codes=["SKU-A", "SKU-B"],
            )
            assert set(latest_metadata) == {"SKU-A", "SKU-B"}

        async with async_session() as db:
            run = TaskRun(task_type="catalog_export", title="sqlite lease", status="running")
            db.add(run)
            await db.flush()
            group = TaskGroup(task_run_id=run.id, group_key="export", title="export", status="running")
            db.add(group)
            await db.flush()
            step = TaskStep(
                task_run_id=run.id,
                task_group_id=group.id,
                step_key="export",
                step_type="catalog_export_template",
                status="running",
                locked_by="sqlite-test",
            )
            db.add(step)
            await db.commit()
            step_id = step.id

        async with async_session() as worker_db:
            step = await worker_db.get(TaskStep, step_id)
            assert step is not None
            await update_step_progress(worker_db, step, current=0, total=1, message="before slow work")
            async with worker_db.begin_nested():
                async with async_session() as heartbeat_db:
                    heartbeat_at = datetime.now()
                    await asyncio.wait_for(
                        heartbeat_db.execute(
                            update(TaskStep)
                            .where(TaskStep.id == step_id)
                            .values(heartbeat_at=heartbeat_at)
                        ),
                        timeout=2,
                    )
                    await heartbeat_db.commit()
            await worker_db.commit()

        async with async_session() as db:
            persisted_step = await db.get(TaskStep, step_id)
            assert persisted_step is not None
            assert persisted_step.heartbeat_at is not None

        await engine.dispose()
        assert database_path.is_file()

        # A real FastAPI lifespan must also work with an empty local database.
        from fastapi.testclient import TestClient
        from app.main import app

        with TestClient(app) as client:
            response = client.get("/api/health")
            assert response.status_code == 200, response.text
            config_response = client.get("/api/config")
            assert config_response.status_code == 200, config_response.text
            assert config_response.json()["database_backend"] == "sqlite"
            assert config_response.json()["sqlite_database_path"] == str(database_path)

    print("sqlite database mode smoke test passed")


if __name__ == "__main__":
    asyncio.run(main())
