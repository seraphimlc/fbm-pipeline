#!/usr/bin/env python3
import argparse
import asyncio
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from app.database import async_session, init_db  # noqa: E402
from app.services.giga_openapi import GigaSyncOptions, sync_giga_products  # noqa: E402


async def main() -> None:
    parser = argparse.ArgumentParser(description="Sync GIGA Open API products into the local FBM database.")
    parser.add_argument("--batch-id", required=True)
    parser.add_argument("--site", default="US")
    parser.add_argument("--data-source-id", type=int, required=True)
    parser.add_argument("--task-id")
    parser.add_argument("--category")
    parser.add_argument("--page-size", type=int, default=200)
    parser.add_argument("--max-pages", type=int)
    args = parser.parse_args()

    await init_db()
    async with async_session() as db:
        result = await sync_giga_products(
            db,
            GigaSyncOptions(
                task_id=args.task_id,
                batch_id=args.batch_id,
                site=args.site,
                data_source_id=args.data_source_id,
                current_category=args.category,
                page_size=args.page_size,
                max_pages=args.max_pages,
            ),
        )
    print("giga-pull-products: 完成")
    print(f"- 状态: 成功")
    print(f"- batch_id: {result.batch_id}")
    print(f"- site: {result.site}")
    print(f"- SKU: {result.sku_count}")
    print(f"- Item: {result.item_count}")
    print(f"- 有效分组数: {result.group_count}")
    print(f"- 删除的单SKU组: {result.deleted_single_sku_group_count}")


if __name__ == "__main__":
    asyncio.run(main())
