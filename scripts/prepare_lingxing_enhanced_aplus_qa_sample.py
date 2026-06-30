#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime
import json
from pathlib import Path
import sys
from typing import Any

from PIL import Image, ImageDraw
from sqlalchemy import select
from sqlalchemy.orm import selectinload

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.aplus_publish.module_registry import (  # noqa: E402
    APLUS_PUBLISH_PROFILE_ENHANCED_BASIC_APLUS_V1,
    LINGXING_STANDARD_COMPARISON_TABLE,
    LINGXING_STANDARD_IMAGE_TEXT_OVERLAY,
    LINGXING_STANDARD_SINGLE_IMAGE_SPECS_DETAIL,
    LINGXING_STANDARD_TECH_SPECS,
    LINGXING_STANDARD_THREE_IMAGE_TEXT,
    required_image_slots,
)
from app.config import settings  # noqa: E402
from app.database import async_session, engine  # noqa: E402
from app.models import CatalogProduct, Product, ProductAplus  # noqa: E402
from app.services.lingxing_aplus_module_mapper import preflight_validate  # noqa: E402
from app.services.lingxing_aplus_publish_policy import collect_aplus_publish_assets  # noqa: E402


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _json_loads(raw: str | None, default: Any) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except Exception:
        return default


def _is_asin(value: Any) -> bool:
    text = _clean(value)
    return len(text) == 10 and text.isalnum() and text.upper() == text


def _title(catalog: CatalogProduct) -> str:
    product = catalog.source_product
    data = product.data if product else None
    for value in (
        getattr(data, "listing_title", None),
        getattr(data, "title", None),
        catalog.title,
        catalog.gigab2b_product_id,
        f"Catalog {catalog.id}",
    ):
        cleaned = _clean(value)
        if cleaned:
            return cleaned[:120]
    return f"Catalog {catalog.id}"


def _candidate_summary(catalog: CatalogProduct) -> dict[str, Any]:
    product = catalog.source_product
    product_aplus = product.aplus if product else None
    plan = _json_loads(getattr(product_aplus, "aplus_plan", None), {})
    profile = plan.get("publish_profile") or plan.get("aplus_plan_version") if isinstance(plan, dict) else None
    current_asin = _clean(catalog.amazon_asin) or _clean(product.amazon_asin if product else None)
    comparison_asin = _clean(catalog.competitor_asin) or _clean(product.competitor_asin if product else None)
    blockers: list[str] = []
    if not product:
        blockers.append("source_product_missing")
    if not (_clean(catalog.amazon_seller_sku) or _clean(product.amazon_seller_sku if product else None) or _clean(catalog.item_code)):
        blockers.append("seller_sku_missing")
    if catalog.asin_sync_status != "synced":
        blockers.append("asin_sync_status_not_synced")
    if not _is_asin(current_asin):
        blockers.append("current_asin_missing_or_invalid")
    if not _is_asin(comparison_asin):
        blockers.append("comparison_asin_missing_or_invalid")
    if product_aplus and getattr(product_aplus, "aplus_plan", None) and profile != APLUS_PUBLISH_PROFILE_ENHANCED_BASIC_APLUS_V1:
        blockers.append("existing_non_enhanced_aplus_plan")
    return {
        "catalog_product_id": catalog.id,
        "product_id": catalog.source_product_id,
        "title": _title(catalog),
        "has_seller_sku": "seller_sku_missing" not in blockers,
        "asin_sync_status": catalog.asin_sync_status,
        "has_current_asin": _is_asin(current_asin),
        "has_comparison_asin": _is_asin(comparison_asin),
        "existing_profile": profile,
        "ready_to_prepare": not blockers,
        "blockers": blockers,
    }


def _plan(catalog: CatalogProduct) -> dict[str, Any]:
    title = _title(catalog)
    product = catalog.source_product
    current_asin = _clean(catalog.amazon_asin) or _clean(product.amazon_asin if product else None)
    comparison_asin = _clean(catalog.competitor_asin) or _clean(product.competitor_asin if product else None)
    comparison_title = f"{title[:70]} alternative"
    return {
        "aplus_plan_version": APLUS_PUBLISH_PROFILE_ENHANCED_BASIC_APLUS_V1,
        "publish_profile": APLUS_PUBLISH_PROFILE_ENHANCED_BASIC_APLUS_V1,
        "profile_version": "1",
        "plan_summary": f"M3.3 QA enhanced basic A+ sample for CatalogProduct {catalog.id}",
        "modules": [
            {
                "position": 1,
                "type": "standard_image_text_overlay",
                "semantic_role": "hero",
                "publish_profile": APLUS_PUBLISH_PROFILE_ENHANCED_BASIC_APLUS_V1,
                "profile_version": "1",
                "module_spec_key": "image_text_overlay_dark",
                "lingxing_content_module_type": LINGXING_STANDARD_IMAGE_TEXT_OVERLAY,
                "headline": f"{title[:80]}",
                "body": "QA draft sample for verifying enhanced basic A+ hero text and image placement.",
            },
            {
                "position": 2,
                "type": "standard_three_image_text",
                "semantic_role": "feature_grid",
                "publish_profile": APLUS_PUBLISH_PROFILE_ENHANCED_BASIC_APLUS_V1,
                "profile_version": "1",
                "module_spec_key": "three_image_text",
                "lingxing_content_module_type": LINGXING_STANDARD_THREE_IMAGE_TEXT,
                "headline": "Three QA-visible feature blocks",
                "features": [
                    {"headline": "Slot one", "body": "Confirms first feature image and text are visible."},
                    {"headline": "Slot two", "body": "Confirms second feature image and text are visible."},
                    {"headline": "Slot three", "body": "Confirms third feature image and text are visible."},
                ],
            },
            {
                "position": 3,
                "type": "standard_single_image_specs_detail",
                "semantic_role": "detail_proof",
                "publish_profile": APLUS_PUBLISH_PROFILE_ENHANCED_BASIC_APLUS_V1,
                "profile_version": "1",
                "module_spec_key": "single_image_specs_detail",
                "lingxing_content_module_type": LINGXING_STANDARD_SINGLE_IMAGE_SPECS_DETAIL,
                "headline": "Detail proof QA module",
                "description_headline": "Draft-only verification content",
                "description_blocks": [
                    {"headline": "Image detail", "body": "Confirms detail image is bound to the correct module."},
                    {"headline": "Text detail", "body": "Confirms description fields survive draft save."},
                ],
                "specification_headline": "Detail summary",
                "specification_list_headline": "QA fields",
                "spec_items": [
                    {"label": "Profile", "value": "enhanced_basic_aplus_v1"},
                    {"label": "Lifecycle", "value": "draft save only"},
                    {"label": "Submit", "value": "not submitted"},
                ],
                "specification_text_headline": "QA note",
                "spec_note": "This sample is for M3.3 draft visibility testing only.",
            },
            {
                "position": 4,
                "type": "standard_comparison_table",
                "semantic_role": "comparison",
                "publish_profile": APLUS_PUBLISH_PROFILE_ENHANCED_BASIC_APLUS_V1,
                "profile_version": "1",
                "module_spec_key": "comparison_table",
                "lingxing_content_module_type": LINGXING_STANDARD_COMPARISON_TABLE,
                "headline": "QA comparison table",
                "metric_row_labels": ["Draft mode", "Image slots", "Spec rows"],
                "current_product_metric_values": ["submitFlag=0", "7 required", "4 rows"],
                "comparison_product_metric_values": ["control", "comparison image", "visible fields"],
                "product_columns": [
                    {"column_key": "current_product", "asin": current_asin, "title": title[:80], "highlight": True},
                    {"column_key": "comparison_product", "asin": comparison_asin, "title": comparison_title, "highlight": False},
                ],
            },
            {
                "position": 5,
                "type": "standard_tech_specs",
                "semantic_role": "technical_or_closing",
                "publish_profile": APLUS_PUBLISH_PROFILE_ENHANCED_BASIC_APLUS_V1,
                "profile_version": "1",
                "module_spec_key": "tech_specs",
                "lingxing_content_module_type": LINGXING_STANDARD_TECH_SPECS,
                "headline": "M3.3 QA technical specs",
                "tableCount": 1,
                "spec_rows": [
                    {"label": "Profile", "description": "enhanced_basic_aplus_v1"},
                    {"label": "Lifecycle", "description": "draft save only"},
                    {"label": "Submit flag", "description": "0"},
                    {"label": "External scope", "description": "Lingxing draft only"},
                ],
            },
        ],
    }


def _image(path: Path, *, size: tuple[int, int], label: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", size, (238, 241, 245))
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, size[0] - 1, size[1] - 1), outline=(80, 90, 110), width=3)
    draw.text((16, 16), label[:80], fill=(20, 28, 40))
    image.save(path, format="JPEG", quality=88)


def _image_manifest(catalog: CatalogProduct, output_dir: Path, *, write_images: bool) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for profile_slot in required_image_slots(APLUS_PUBLISH_PROFILE_ENHANCED_BASIC_APLUS_V1):
        slot = profile_slot.slot
        asset_slot_id = f"m{profile_slot.position}_{slot.slot_id.replace('.', '_')}"
        path = output_dir / f"{asset_slot_id}.jpg"
        if write_images:
            _image(
                path,
                size=(slot.crop_width, slot.crop_height),
                label=f"QA {catalog.id} {slot.slot_id}",
            )
        items.append(
            {
                "status": "done",
                "path": str(path),
                "position": profile_slot.position,
                "module_position": profile_slot.position,
                "semantic_role": profile_slot.semantic_role,
                "asset_slot_id": asset_slot_id,
                "slot_id": slot.slot_id,
                "payload_slot": ".".join(slot.payload_path),
                "target_width": slot.crop_width,
                "target_height": slot.crop_height,
                "width": slot.crop_width,
                "height": slot.crop_height,
                "alt_text": f"M3.3 QA image for {slot.slot_id}",
            }
        )
    return items


async def _load_catalogs(args: argparse.Namespace) -> list[CatalogProduct]:
    options = (
        selectinload(CatalogProduct.source_product).selectinload(Product.aplus),
        selectinload(CatalogProduct.source_product).selectinload(Product.data),
    )
    async with async_session() as db:
        if args.catalog_product_id:
            stmt = select(CatalogProduct).where(CatalogProduct.id == args.catalog_product_id).options(*options)
        else:
            stmt = (
                select(CatalogProduct)
                .where(CatalogProduct.asin_sync_status == "synced")
                .where(CatalogProduct.amazon_seller_sku.is_not(None))
                .where(CatalogProduct.amazon_asin.is_not(None))
                .order_by(CatalogProduct.updated_at.desc(), CatalogProduct.id.desc())
                .limit(args.limit)
                .options(*options)
            )
        result = await db.execute(stmt)
        return list(result.scalars().unique().all())


async def _prepare(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    catalogs = await _load_catalogs(args)
    if not catalogs:
        await engine.dispose()
        return 2, {"status": "BLOCKED", "message": "No CatalogProduct candidates found", "external_side_effects": "none"}
    summaries = [_candidate_summary(item) for item in catalogs]
    if not args.catalog_product_id or not args.write:
        await engine.dispose()
        return 0, {
            "status": "DRY_RUN",
            "external_side_effects": "none",
            "write_required_for_db_changes": True,
            "candidates": summaries,
            "next_action": "Choose a ready_to_prepare catalog_product_id and rerun with --catalog-product-id ID --write",
        }

    catalog = catalogs[0]
    summary = summaries[0]
    if not summary["ready_to_prepare"]:
        await engine.dispose()
        return 3, {"status": "NEEDS_FIX", "external_side_effects": "none", "candidate": summary}
    if not catalog.source_product:
        await engine.dispose()
        return 3, {"status": "NEEDS_FIX", "external_side_effects": "none", "candidate": summary}
    product = catalog.source_product
    existing = product.aplus
    existing_plan = getattr(existing, "aplus_plan", None)
    if existing_plan and not args.overwrite_aplus:
        await engine.dispose()
        return 3, {
            "status": "NEEDS_CONFIRMATION",
            "external_side_effects": "none",
            "message": "ProductAplus already has a plan; rerun with --overwrite-aplus if this safe sample may replace it",
            "candidate": summary,
        }

    output_dir = settings.DATA_DIR / "task_evidence" / "lingxing_enhanced_aplus_qa_samples" / f"catalog_{catalog.id}"
    plan = _plan(catalog)
    images = _image_manifest(catalog, output_dir, write_images=True)
    if not product.aplus:
        product.aplus = ProductAplus(product_id=product.id)
    product.aplus.aplus_status = "done"
    product.aplus.aplus_plan = json.dumps(plan, ensure_ascii=False)
    product.aplus.aplus_plan_summary = plan.get("plan_summary")
    product.aplus.aplus_images = json.dumps(images, ensure_ascii=False)
    product.aplus.aplus_image_count = len(images)
    now = datetime.now()
    product.aplus.planned_at = product.aplus.planned_at or now
    product.aplus.generated_at = now

    assets = collect_aplus_publish_assets(product)
    mapping = preflight_validate(product, assets.assets if assets.ok else [])
    if not assets.ok or not mapping.ok:
        await engine.dispose()
        return 3, {
            "status": "NEEDS_FIX",
            "external_side_effects": "local_files_written_only",
            "message": "Generated sample did not pass local policy/mapper preflight; database was not committed",
            "assets": {"ok": assets.ok, "reason_code": assets.reason_code, "message": assets.message},
            "mapping": {"ok": mapping.ok, "reason_code": mapping.reason_code, "message": mapping.message},
        }
    async with async_session() as db:
        await db.merge(product)
        await db.commit()
    await engine.dispose()
    return 0, {
        "status": "READY_SAMPLE_WRITTEN",
        "external_side_effects": "local_db_and_files_only",
        "catalog_product_id": catalog.id,
        "product_id": product.id,
        "image_dir": str(output_dir),
        "asset_count": len(images),
        "mapping_evidence": mapping.evidence,
        "next_action": (
            "Run: cd backend && .venv/bin/python ../scripts/check_lingxing_enhanced_aplus_qa_readiness.py "
            f"--catalog-product-id {catalog.id}"
        ),
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare a local enhanced_basic_aplus_v1 sample for M3.3 QA.")
    parser.add_argument("--catalog-product-id", type=int, default=None, help="CatalogProduct id to prepare.")
    parser.add_argument("--limit", type=int, default=10, help="Dry-run candidate limit.")
    parser.add_argument("--write", action="store_true", help="Write ProductAplus sample data and local slot images.")
    parser.add_argument("--overwrite-aplus", action="store_true", help="Allow replacing existing ProductAplus plan/images.")
    return parser.parse_args()


def main() -> int:
    exit_code, report = asyncio.run(_prepare(_parse_args()))
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True, default=str))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
