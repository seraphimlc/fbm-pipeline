#!/usr/bin/env python
import argparse
import asyncio
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.database import async_session, init_db  # noqa: E402
from app.services.giga_inventory_sync import GigaInventorySyncOptions, sync_giga_inventory_snapshot, validate_giga_site  # noqa: E402


def _default_batch_id(site: str) -> str:
    return f"{datetime.now().strftime('%Y%m%d')}-{site.lower()}-inventory"


async def main() -> None:
    parser = argparse.ArgumentParser(description="Sync GIGA inventory snapshot into the local FBM database.")
    parser.add_argument("--site", required=True, help="GIGA site, must be US or JP.")
    parser.add_argument("--data-source-id", type=int, required=True, help="Product data source id that stores the GIGA AK/SK.")
    parser.add_argument("--batch-id", help="Inventory snapshot batch id. Defaults to YYYYMMDD-{site}-inventory.")
    parser.add_argument("--task-id", default="daily-giga-inventory", help="Optional task id for logs.")
    parser.add_argument("--sku", action="append", default=[], help="Optional SKU to sync. Repeatable. Defaults to latest GIGA SKU pool.")
    args = parser.parse_args()

    site = validate_giga_site(args.site)
    batch_id = args.batch_id or _default_batch_id(site)

    await init_db()
    async with async_session() as db:
        result = await sync_giga_inventory_snapshot(
            db,
            GigaInventorySyncOptions(
                batch_id=batch_id,
                site=site,
                data_source_id=args.data_source_id,
                task_id=args.task_id,
                sku_codes=args.sku,
            ),
        )
    print({
        "batch_id": result.batch_id,
        "site": result.site,
        "task_id": result.task_id,
        "total_skus": result.total_skus,
        "success_count": result.success_count,
        "failed_count": result.failed_count,
        "alert_count": result.alert_count,
        "out_of_stock_count": result.out_of_stock_count,
        "restocked_count": result.restocked_count,
        "previous_batch_id": result.previous_batch_id,
        "pulled_at": result.pulled_at.isoformat(),
    })


if __name__ == "__main__":
    asyncio.run(main())
