#!/usr/bin/env python3
"""Backfill empty Step 3 keyword candidates with the LLM fallback generator."""

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database import async_session
from app.models import Product, ProductData
from app.pipeline.step3_keywords import generate_llm_keywords_from_product


def _missing_keywords(value: str | None) -> bool:
    if not value or not value.strip():
        return True
    try:
        parsed = json.loads(value)
    except Exception:
        return False
    return parsed == []


async def _candidate_products(limit: int | None, product_ids: list[int]) -> list[Product]:
    async with async_session() as db:
        query = (
            select(Product)
            .join(ProductData, ProductData.product_id == Product.id)
            .options(selectinload(Product.data))
            .order_by(Product.id)
        )
        if product_ids:
            query = query.where(Product.id.in_(product_ids))
        result = await db.execute(query)
        products = [
            product
            for product in result.scalars().all()
            if product.data and _missing_keywords(product.data.keywords_top)
        ]
        return products[:limit] if limit else products


async def _save_keywords(product_id: int, keywords: list[dict], dry_run: bool) -> None:
    if dry_run:
        return
    async with async_session() as db:
        result = await db.execute(
            select(ProductData).where(ProductData.product_id == product_id)
        )
        pd = result.scalar_one_or_none()
        if not pd:
            raise ValueError(f"ProductData not found for product_id={product_id}")
        pd.keywords_top = json.dumps(keywords, ensure_ascii=False)
        await db.commit()


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--product-id", type=int, action="append", default=[])
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--timeout", type=int, default=90)
    args = parser.parse_args()

    products = await _candidate_products(args.limit, args.product_id)
    print(f"Missing keyword products selected: {len(products)}", flush=True)
    success = 0
    failed = 0
    for index, product in enumerate(products, start=1):
        title = (product.data.listing_title or product.data.title or "") if product.data else ""
        try:
            keywords = await asyncio.wait_for(generate_llm_keywords_from_product(product), timeout=args.timeout)
            await _save_keywords(product.id, keywords, args.dry_run)
            success += 1
            preview = ", ".join(item["keyword"] for item in keywords[:3])
            print(f"[{index}/{len(products)}] OK product_id={product.id} {product.data.item_code if product.data else ''}: {preview}", flush=True)
        except Exception as exc:
            failed += 1
            print(f"[{index}/{len(products)}] FAIL product_id={product.id} title={title[:80]!r}: {type(exc).__name__}: {exc}", flush=True)
    print(f"Done. success={success}, failed={failed}, dry_run={args.dry_run}", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
