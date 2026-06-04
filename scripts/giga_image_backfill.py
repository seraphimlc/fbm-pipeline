#!/usr/bin/env python
import argparse
import asyncio
import json
import sys
from pathlib import Path

from sqlalchemy import delete, select

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.database import async_session, init_db  # noqa: E402
from app.models import GigaProductImage, GigaRawSkuDetail, GigaSku  # noqa: E402
from app.services.giga_image_assets import download_giga_product_images, extract_giga_image_candidates  # noqa: E402
from app.services.giga_inventory_sync import validate_giga_site  # noqa: E402


async def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill GIGA product images from raw SKU detail JSON.")
    parser.add_argument("--batch-id", required=True, help="GIGA product batch id, for example 20260602-us-b002.")
    parser.add_argument("--site", required=True, help="GIGA site, must be US or JP.")
    parser.add_argument("--sku", action="append", default=[], help="Optional SKU to backfill. Repeatable.")
    parser.add_argument("--keep-existing", action="store_true", help="Do not delete existing image rows for this scope first.")
    args = parser.parse_args()

    batch_id = args.batch_id.strip()
    site = validate_giga_site(args.site)
    sku_filter = list(dict.fromkeys(str(sku).strip() for sku in args.sku if str(sku).strip()))
    if not batch_id:
        raise ValueError("batch_id is required")

    await init_db()
    async with async_session() as db:
        sku_query = select(GigaSku.sku_code, GigaSku.item_code).where(GigaSku.batch_id == batch_id, GigaSku.site == site)
        if sku_filter:
            sku_query = sku_query.where(GigaSku.sku_code.in_(sku_filter))
        sku_result = await db.execute(sku_query)
        item_by_sku = {sku: item for sku, item in sku_result.all()}

        raw_query = select(GigaRawSkuDetail).where(GigaRawSkuDetail.batch_id == batch_id, GigaRawSkuDetail.site == site)
        if sku_filter:
            raw_query = raw_query.where(GigaRawSkuDetail.sku_code.in_(sku_filter))
        raw_result = await db.execute(raw_query)
        raw_rows = raw_result.scalars().all()

        candidates = []
        for row in raw_rows:
            try:
                detail = json.loads(row.data_json or "{}")
            except json.JSONDecodeError:
                detail = {}
            candidates.extend(
                extract_giga_image_candidates(
                    sku_code=row.sku_code,
                    item_code=item_by_sku.get(row.sku_code),
                    detail=detail,
                )
            )

        if not args.keep_existing:
            delete_query = delete(GigaProductImage).where(GigaProductImage.batch_id == batch_id, GigaProductImage.site == site)
            if sku_filter:
                delete_query = delete_query.where(GigaProductImage.sku_code.in_(sku_filter))
            await db.execute(delete_query)
            await db.commit()

        image_rows = await download_giga_product_images(batch_id=batch_id, site=site, candidates=candidates)
        db.add_all(image_rows)
        await db.commit()

    done = sum(1 for row in image_rows if row.download_status == "done")
    failed = sum(1 for row in image_rows if row.download_status != "done")
    print({
        "batch_id": batch_id,
        "site": site,
        "raw_skus": len(raw_rows),
        "image_candidates": len(candidates),
        "downloaded": done,
        "failed": failed,
    })


if __name__ == "__main__":
    asyncio.run(main())
