#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import selectinload

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.aplus_publish.module_registry import APLUS_PUBLISH_PROFILE_ENHANCED_BASIC_APLUS_V1  # noqa: E402
from app.config import settings  # noqa: E402
from app.database import async_session, engine  # noqa: E402
from app.models import CatalogProduct, Product, ProductAplus  # noqa: E402
from app.services.lingxing_aplus_module_mapper import preflight_validate  # noqa: E402
from app.services.lingxing_aplus_publish_policy import (  # noqa: E402
    collect_aplus_publish_assets,
    evaluate_aplus_publish_prerequisites,
)

EXIT_READY = 0
EXIT_BLOCKED = 2
EXIT_SAMPLE_NEEDS_FIX = 3


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _hash_present(value: Any) -> str | None:
    cleaned = _clean(value)
    if not cleaned:
        return None
    return hashlib.sha256(cleaned.encode("utf-8")).hexdigest()[:10]


def _json_loads(raw: str | None, default: Any) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except Exception:
        return default


def _env_report() -> tuple[dict[str, Any], list[str]]:
    blockers: list[str] = []
    env = {
        "allow_real_external_calls": bool(settings.LINGXING_APLUS_ALLOW_REAL_EXTERNAL_CALLS),
        "submit_for_approval": bool(settings.LINGXING_APLUS_SUBMIT_FOR_APPROVAL),
        "store_id_present": bool(_clean(settings.LINGXING_APLUS_STORE_ID)),
        "store_name_present": bool(_clean(settings.LINGXING_APLUS_STORE_NAME)),
        "site": _clean(settings.LINGXING_APLUS_SITE) or None,
    }
    if not env["allow_real_external_calls"]:
        blockers.append("LINGXING_APLUS_ALLOW_REAL_EXTERNAL_CALLS must be true for real M3.3 QA")
    if env["submit_for_approval"]:
        blockers.append("LINGXING_APLUS_SUBMIT_FOR_APPROVAL must remain false")
    if not env["store_id_present"]:
        blockers.append("LINGXING_APLUS_STORE_ID is required")
    if not env["site"]:
        blockers.append("LINGXING_APLUS_SITE is required")
    return env, blockers


def _plan_profile(product_aplus: ProductAplus | None) -> str | None:
    plan = _json_loads(getattr(product_aplus, "aplus_plan", None), {})
    if not isinstance(plan, dict):
        return None
    return _clean(plan.get("publish_profile")) or _clean(plan.get("aplus_plan_version")) or None


def _sample_summary(catalog: CatalogProduct, *, store_id: str, site: str) -> dict[str, Any]:
    product = catalog.source_product
    product_aplus = product.aplus if product else None
    summary: dict[str, Any] = {
        "catalog_product_id": catalog.id,
        "product_id": catalog.source_product_id,
        "profile": _plan_profile(product_aplus),
        "aplus_status": getattr(product_aplus, "aplus_status", None),
        "seller_sku_hash": _hash_present(catalog.amazon_seller_sku or (product.amazon_seller_sku if product else None)),
        "has_asin": bool(_clean(catalog.amazon_asin) or _clean(product.amazon_asin if product else None)),
        "asin_sync_status": catalog.asin_sync_status,
        "aplus_upload_status": catalog.aplus_upload_status,
    }
    if not product:
        summary.update({"ready": False, "stage": "catalog", "reason_code": "product_missing"})
        return summary

    prerequisites = evaluate_aplus_publish_prerequisites(catalog, store_id=store_id, site=site)
    summary["prerequisites"] = {
        "ok": prerequisites.ok,
        "status": prerequisites.status,
        "reason_code": prerequisites.reason_code,
        "message": prerequisites.message,
    }
    if not prerequisites.ok:
        summary.update({"ready": False, "stage": "prerequisites", "reason_code": prerequisites.reason_code})
        return summary

    assets = collect_aplus_publish_assets(product)
    summary["assets"] = {
        "ok": assets.ok,
        "reason_code": assets.reason_code,
        "message": assets.message,
        "asset_count": len(assets.assets),
        "required_slot_count": (assets.evidence or {}).get("required_slot_count"),
        "slot_ids": sorted(asset.slot_id for asset in assets.assets if getattr(asset, "slot_id", None)),
    }
    if not assets.ok:
        summary.update({"ready": False, "stage": "assets", "reason_code": assets.reason_code})
        return summary

    mapping = preflight_validate(product, assets.assets)
    summary["mapping"] = {
        "ok": mapping.ok,
        "reason_code": mapping.reason_code,
        "message": mapping.message,
        "module_count": (mapping.evidence or {}).get("module_count"),
        "required_image_slot_count": (mapping.evidence or {}).get("required_image_slot_count"),
        "content_module_types": (mapping.evidence or {}).get("content_module_types"),
    }
    if not mapping.ok:
        summary.update({"ready": False, "stage": "mapping", "reason_code": mapping.reason_code})
        return summary

    summary.update({"ready": True, "stage": "ready", "reason_code": None})
    return summary


async def _load_candidates(args: argparse.Namespace) -> list[CatalogProduct]:
    options = (
        selectinload(CatalogProduct.source_product).selectinload(Product.aplus),
        selectinload(CatalogProduct.source_product).selectinload(Product.data),
    )
    async with async_session() as db:
        if args.catalog_product_id:
            stmt = (
                select(CatalogProduct)
                .where(CatalogProduct.id == args.catalog_product_id)
                .options(*options)
            )
        elif args.product_id:
            stmt = (
                select(CatalogProduct)
                .where(CatalogProduct.source_product_id == args.product_id)
                .options(*options)
            )
        else:
            stmt = (
                select(CatalogProduct)
                .join(CatalogProduct.source_product)
                .join(Product.aplus)
                .where(ProductAplus.aplus_plan.contains(APLUS_PUBLISH_PROFILE_ENHANCED_BASIC_APLUS_V1))
                .order_by(CatalogProduct.updated_at.desc(), CatalogProduct.id.desc())
                .limit(args.limit)
                .options(*options)
            )
        result = await db.execute(stmt)
        return list(result.scalars().unique().all())


async def _run(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    env, env_blockers = _env_report()
    store_id = _clean(args.store_id) or _clean(settings.LINGXING_APLUS_STORE_ID) or "__qa_store_placeholder__"
    site = _clean(args.site) or _clean(settings.LINGXING_APLUS_SITE) or "US"
    placeholder_store_id = store_id == "__qa_store_placeholder__"
    try:
        candidates = await _load_candidates(args)
    except Exception as exc:
        return EXIT_BLOCKED, {
            "status": "BLOCKED",
            "env": env,
            "env_blockers": env_blockers,
            "sample_blockers": [f"database_query_failed: {type(exc).__name__}: {exc}"],
            "external_side_effects": "none",
        }
    finally:
        await engine.dispose()

    samples = [_sample_summary(item, store_id=store_id, site=site) for item in candidates]
    ready_samples = [item for item in samples if item.get("ready")]
    sample_blockers: list[str] = []
    if not candidates:
        sample_blockers.append("no enhanced_basic_aplus_v1 CatalogProduct candidate found")
    elif not ready_samples:
        sample_blockers.append("no candidate passed local prerequisites/assets/mapper preflight")

    blocked = bool(env_blockers or sample_blockers)
    status = "READY" if not blocked else "BLOCKED"
    if placeholder_store_id:
        status = "BLOCKED"
    report = {
        "status": status,
        "external_side_effects": "none",
        "env": env,
        "env_blockers": env_blockers,
        "store_id_placeholder_used_for_local_sample_checks": placeholder_store_id,
        "sample_blockers": sample_blockers,
        "candidate_count": len(samples),
        "ready_candidate_count": len(ready_samples),
        "samples": samples,
        "next_action": (
            "Run M3.3 real Lingxing QA with submitFlag=0 on one ready sample"
            if status == "READY"
            else "Provide missing env/login/store/sample inputs, then rerun this readiness check"
        ),
    }
    if not blocked:
        return EXIT_READY, report
    if samples and not env_blockers and not ready_samples:
        return EXIT_SAMPLE_NEEDS_FIX, report
    return EXIT_BLOCKED, report


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read-only readiness check for Lingxing enhanced basic A+ M3.3 real QA."
    )
    parser.add_argument("--catalog-product-id", type=int, default=None, help="Check one CatalogProduct id.")
    parser.add_argument("--product-id", type=int, default=None, help="Check the CatalogProduct for one source Product id.")
    parser.add_argument("--store-id", default="", help="Override store id for local policy checks only.")
    parser.add_argument("--site", default="", help="Override site for local policy checks only.")
    parser.add_argument("--limit", type=int, default=5, help="Maximum enhanced candidates to inspect.")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    exit_code, report = asyncio.run(_run(args))
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
