from __future__ import annotations

import hashlib
import json
import mimetypes
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image

from app.aplus_publish.status import (
    STATUS_FAILED,
    STATUS_READY_TO_UPLOAD,
    STATUS_SKIPPED,
    STATUS_WAITING_LISTING,
    is_protected_status,
)
from app.models import CatalogProduct, Product, ProductAplus
from app.services.asin_match_policy import seller_sku_candidate


MIN_APLUS_IMAGE_WIDTH = 970
MIN_APLUS_IMAGE_HEIGHT = 600
REQUIRED_APLUS_IMAGE_COUNT = 5


@dataclass(frozen=True)
class AplusPublishAsset:
    position: int
    path: Path
    alt_text: str
    width: int
    height: int
    content_type: str
    size: int


@dataclass(frozen=True)
class AplusPolicyResult:
    ok: bool
    status: str
    reason_code: str | None = None
    message: str | None = None
    protected: bool = False
    assets: list[AplusPublishAsset] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)


def _json_loads(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except Exception:
        return fallback


def _clean(value: str | int | None) -> str | None:
    text = str(value or "").strip()
    return text or None


def _module_alt_text(product: Product, modules: list[Any], index: int) -> str:
    module = modules[index] if index < len(modules) and isinstance(modules[index], dict) else {}
    fallback = ((product.data.listing_title or product.data.title) if product.data else None) or product.amazon_asin
    return str(
        module.get("headline")
        or module.get("subheading")
        or module.get("key_message")
        or fallback
        or "Amazon A+ product image"
    )[:100]


def collect_aplus_publish_assets(product: Product) -> AplusPolicyResult:
    product_aplus = product.aplus
    if not product_aplus or not product_aplus.aplus_images:
        return AplusPolicyResult(
            ok=False,
            status=STATUS_FAILED,
            reason_code="aplus_images_missing",
            message="缺少 A+ 图片，请先完成 A+ 出图",
        )

    parsed_images = _json_loads(product_aplus.aplus_images, [])
    if not isinstance(parsed_images, list):
        return AplusPolicyResult(
            ok=False,
            status=STATUS_FAILED,
            reason_code="aplus_images_invalid",
            message="A+ 图片 JSON 格式无效",
        )
    done = [item for item in parsed_images if isinstance(item, dict) and item.get("status") == "done" and item.get("path")]
    done.sort(key=lambda item: item.get("position") or 0)
    if len(done) < REQUIRED_APLUS_IMAGE_COUNT:
        return AplusPolicyResult(
            ok=False,
            status=STATUS_FAILED,
            reason_code="aplus_images_incomplete",
            message=f"A+ 图片不足 {REQUIRED_APLUS_IMAGE_COUNT} 张：{len(done)}/{REQUIRED_APLUS_IMAGE_COUNT}",
            evidence={"done_count": len(done), "required_count": REQUIRED_APLUS_IMAGE_COUNT},
        )

    modules = _json_loads(product_aplus.aplus_plan, {}).get("modules", [])
    if not isinstance(modules, list):
        modules = []
    assets: list[AplusPublishAsset] = []
    for index, item in enumerate(done[:REQUIRED_APLUS_IMAGE_COUNT]):
        raw_path = item.get("path")
        path = Path(str(raw_path)).expanduser()
        if not path.is_file():
            return AplusPolicyResult(
                ok=False,
                status=STATUS_FAILED,
                reason_code="image_missing",
                message=f"A+ 图片不存在: {path}",
                evidence={"position": item.get("position") or index + 1, "path": str(path)},
            )
        try:
            with Image.open(path) as img:
                width, height = img.size
        except Exception as exc:
            return AplusPolicyResult(
                ok=False,
                status=STATUS_FAILED,
                reason_code="image_invalid",
                message=f"A+ 图片无法读取: {path.name}: {exc}",
                evidence={"position": item.get("position") or index + 1, "path": str(path)},
            )
        if width < MIN_APLUS_IMAGE_WIDTH or height < MIN_APLUS_IMAGE_HEIGHT:
            return AplusPolicyResult(
                ok=False,
                status=STATUS_FAILED,
                reason_code="image_too_small",
                message=f"A+ 图片尺寸小于 {MIN_APLUS_IMAGE_WIDTH}x{MIN_APLUS_IMAGE_HEIGHT}: {path.name} {width}x{height}",
                evidence={
                    "position": item.get("position") or index + 1,
                    "width": width,
                    "height": height,
                    "min_width": MIN_APLUS_IMAGE_WIDTH,
                    "min_height": MIN_APLUS_IMAGE_HEIGHT,
                },
            )
        assets.append(
            AplusPublishAsset(
                position=int(item.get("position") or index + 1),
                path=path,
                alt_text=_module_alt_text(product, modules, index),
                width=width,
                height=height,
                content_type=mimetypes.guess_type(str(path))[0] or "image/jpeg",
                size=path.stat().st_size,
            )
        )

    return AplusPolicyResult(ok=True, status=STATUS_READY_TO_UPLOAD, assets=assets)


def build_aplus_content_fingerprint(product_aplus: ProductAplus | None, assets: list[AplusPublishAsset]) -> str:
    payload = {
        "product_aplus_id": getattr(product_aplus, "id", None),
        "aplus_status": getattr(product_aplus, "aplus_status", None),
        "aplus_plan": getattr(product_aplus, "aplus_plan", None),
        "aplus_scripts": getattr(product_aplus, "aplus_scripts", None),
        "assets": [
            {
                "position": asset.position,
                "path": str(asset.path),
                "width": asset.width,
                "height": asset.height,
                "size": asset.size,
            }
            for asset in assets
        ],
    }
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def evaluate_aplus_publish_prerequisites(
    catalog: CatalogProduct,
    *,
    store_id: str | int | None,
    site: str | None,
) -> AplusPolicyResult:
    current_status = _clean(catalog.aplus_upload_status)
    if current_status and is_protected_status(current_status):
        return AplusPolicyResult(
            ok=False,
            status=current_status,
            reason_code="protected_status",
            message=f"A+ 发布状态 {current_status} 受保护，停止重复保存草稿",
            protected=True,
            evidence={"aplus_upload_status": current_status},
        )

    product = catalog.source_product
    if not product:
        return AplusPolicyResult(ok=False, status=STATUS_FAILED, reason_code="product_missing", message="缺少源商品")
    if not product.aplus or product.aplus.aplus_status != "done":
        return AplusPolicyResult(
            ok=False,
            status=STATUS_SKIPPED,
            reason_code="product_aplus_not_done",
            message="ProductAplus 尚未完成，不能保存领星草稿",
        )

    seller_sku = seller_sku_candidate(catalog).value
    if not seller_sku:
        return AplusPolicyResult(
            ok=False,
            status=STATUS_WAITING_LISTING,
            reason_code="seller_sku_missing",
            message="缺少 Amazon seller SKU/MSKU，等待 Listing 对齐",
        )
    asin = _clean(catalog.amazon_asin) or _clean(product.amazon_asin)
    if not asin or catalog.asin_sync_status != "synced":
        return AplusPolicyResult(
            ok=False,
            status=STATUS_WAITING_LISTING,
            reason_code="asin_not_aligned",
            message="CatalogProduct 尚未完成 seller SKU/MSKU -> ASIN 对齐",
            evidence={"asin_sync_status": catalog.asin_sync_status, "has_asin": bool(asin)},
        )
    if not _clean(store_id):
        return AplusPolicyResult(
            ok=False,
            status=STATUS_FAILED,
            reason_code="store_config_required",
            message="保存领星 A+ 草稿需要显式 store_id",
        )
    if not _clean(site):
        return AplusPolicyResult(
            ok=False,
            status=STATUS_FAILED,
            reason_code="site_required",
            message="保存领星 A+ 草稿需要显式 site",
        )

    return AplusPolicyResult(
        ok=True,
        status=STATUS_READY_TO_UPLOAD,
        evidence={"asin": asin, "seller_sku": seller_sku, "store_id": _clean(store_id), "site": _clean(site)},
    )
