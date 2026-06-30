from __future__ import annotations

import hashlib
import json
import mimetypes
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image

from app.aplus_publish.module_registry import (
    APLUS_PUBLISH_PROFILE_ENHANCED_BASIC_APLUS_V1,
    APLUS_PUBLISH_PROFILE_STANDARD_HEADER_IMAGE_TEXT_V1,
    FAILURE_ALT_TEXT_MISSING,
    FAILURE_ALT_TEXT_TOO_LONG,
    FAILURE_IMAGE_SLOT_DIMENSION_INVALID,
    FAILURE_IMAGE_SLOT_DUPLICATE,
    FAILURE_IMAGE_SLOT_MISSING,
    FAILURE_IMAGE_SLOT_UNEXPECTED,
    STANDARD_HEADER_IMAGE_TEXT_V1,
    SUPPORTED_APLUS_MODULE_COUNT,
    get_profile_spec,
    required_image_slots,
)
from app.aplus_publish.status import (
    STATUS_FAILED,
    STATUS_READY_TO_UPLOAD,
    STATUS_SKIPPED,
    STATUS_WAITING_LISTING,
    is_protected_status,
)
from app.models import CatalogProduct, Product, ProductAplus
from app.services.asin_match_policy import seller_sku_candidate


MIN_APLUS_IMAGE_WIDTH = STANDARD_HEADER_IMAGE_TEXT_V1.image_min_width
MIN_APLUS_IMAGE_HEIGHT = STANDARD_HEADER_IMAGE_TEXT_V1.image_min_height
REQUIRED_APLUS_IMAGE_COUNT = SUPPORTED_APLUS_MODULE_COUNT


@dataclass(frozen=True)
class AplusPublishAsset:
    position: int
    path: Path
    alt_text: str
    width: int
    height: int
    content_type: str
    size: int
    asset_slot_id: str | None = None
    slot_id: str | None = None
    module_position: int | None = None
    semantic_role: str | None = None
    payload_slot: str | None = None
    target_width: int | None = None
    target_height: int | None = None
    min_width: int | None = None
    min_height: int | None = None


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


def _plan_publish_profile(product_aplus: ProductAplus | None) -> str | None:
    plan = _json_loads(getattr(product_aplus, "aplus_plan", None), {})
    if not isinstance(plan, dict):
        return None
    for value in (plan.get("publish_profile"), plan.get("aplus_plan_version")):
        cleaned = _clean(value)
        if cleaned:
            return cleaned
    modules = plan.get("modules")
    if isinstance(modules, list):
        for module in modules:
            if isinstance(module, dict):
                cleaned = _clean(module.get("publish_profile"))
                if cleaned:
                    return cleaned
    return None


def _payload_slot_from_path(payload_path: tuple[str, ...]) -> str:
    return ".".join(str(item) for item in payload_path)


def _enhanced_slot_asset_key(item: dict[str, Any]) -> tuple[int | None, str | None]:
    raw_position = item.get("module_position") or item.get("position")
    try:
        position = int(raw_position)
    except Exception:
        position = None
    slot_id = _clean(item.get("slot_id"))
    return position, slot_id


def _collect_enhanced_aplus_publish_assets(product: Product, parsed_images: list[Any]) -> AplusPolicyResult:
    required_slots = required_image_slots(APLUS_PUBLISH_PROFILE_ENHANCED_BASIC_APLUS_V1)
    required_by_key = {(slot.position, slot.slot.slot_id): slot for slot in required_slots}
    seen: dict[tuple[int, str], dict[str, Any]] = {}
    for item in parsed_images:
        if not isinstance(item, dict) or item.get("status") != "done" or not item.get("path"):
            continue
        key_position, key_slot_id = _enhanced_slot_asset_key(item)
        if key_position is None or key_slot_id is None:
            return AplusPolicyResult(
                ok=False,
                status=STATUS_FAILED,
                reason_code=FAILURE_IMAGE_SLOT_UNEXPECTED,
                message="增强版 A+ 图片缺少 module_position 或 slot_id",
                evidence={"asset_slot_id": item.get("asset_slot_id"), "module_position": item.get("module_position"), "slot_id": item.get("slot_id")},
            )
        key = (key_position, key_slot_id)
        if key not in required_by_key:
            return AplusPolicyResult(
                ok=False,
                status=STATUS_FAILED,
                reason_code=FAILURE_IMAGE_SLOT_UNEXPECTED,
                message="增强版 A+ 图片 slot 不在 registry 契约中",
                evidence={"module_position": key_position, "slot_id": key_slot_id},
            )
        if key in seen:
            return AplusPolicyResult(
                ok=False,
                status=STATUS_FAILED,
                reason_code=FAILURE_IMAGE_SLOT_DUPLICATE,
                message="增强版 A+ 图片 slot 重复",
                evidence={"module_position": key_position, "slot_id": key_slot_id},
            )
        seen[key] = item

    missing = sorted(set(required_by_key) - set(seen))
    if missing:
        return AplusPolicyResult(
            ok=False,
            status=STATUS_FAILED,
            reason_code=FAILURE_IMAGE_SLOT_MISSING,
            message=f"增强版 A+ 图片 slot 不完整：缺少 {len(missing)} 个",
            evidence={"missing_slots": [{"module_position": position, "slot_id": slot_id} for position, slot_id in missing]},
        )

    assets: list[AplusPublishAsset] = []
    for key, slot_spec in sorted(required_by_key.items()):
        item = seen[key]
        raw_path = item.get("path")
        path = Path(str(raw_path)).expanduser()
        if not path.is_file():
            return AplusPolicyResult(
                ok=False,
                status=STATUS_FAILED,
                reason_code="image_missing",
                message=f"A+ 图片不存在: {path}",
                evidence={"module_position": key[0], "slot_id": key[1], "path": str(path)},
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
                evidence={"module_position": key[0], "slot_id": key[1], "path": str(path)},
            )
        slot = slot_spec.slot
        if width < slot.min_width or height < slot.min_height:
            return AplusPolicyResult(
                ok=False,
                status=STATUS_FAILED,
                reason_code=FAILURE_IMAGE_SLOT_DIMENSION_INVALID,
                message=f"增强版 A+ 图片尺寸小于 {slot.min_width}x{slot.min_height}: {path.name} {width}x{height}",
                evidence={
                    "module_position": key[0],
                    "slot_id": key[1],
                    "width": width,
                    "height": height,
                    "min_width": slot.min_width,
                    "min_height": slot.min_height,
                },
            )
        payload_slot = _clean(item.get("payload_slot"))
        expected_payload_slot = _payload_slot_from_path(slot.payload_path)
        if payload_slot != expected_payload_slot:
            return AplusPolicyResult(
                ok=False,
                status=STATUS_FAILED,
                reason_code=FAILURE_IMAGE_SLOT_UNEXPECTED,
                message="增强版 A+ 图片 payload_slot 与 registry 不一致",
                evidence={"module_position": key[0], "slot_id": key[1], "payload_slot": payload_slot, "expected_payload_slot": expected_payload_slot},
            )
        target_width = int(item.get("target_width") or 0)
        target_height = int(item.get("target_height") or 0)
        if target_width != slot.crop_width or target_height != slot.crop_height:
            return AplusPolicyResult(
                ok=False,
                status=STATUS_FAILED,
                reason_code=FAILURE_IMAGE_SLOT_DIMENSION_INVALID,
                message="增强版 A+ 图片目标尺寸与 registry 不一致",
                evidence={
                    "module_position": key[0],
                    "slot_id": key[1],
                    "target_width": target_width,
                    "target_height": target_height,
                    "expected_width": slot.crop_width,
                    "expected_height": slot.crop_height,
                },
            )
        alt_text = str(item.get("alt_text") or "").strip()
        if slot.alt_text_required and not alt_text:
            return AplusPolicyResult(
                ok=False,
                status=STATUS_FAILED,
                reason_code=FAILURE_ALT_TEXT_MISSING,
                message="增强版 A+ 图片 alt text 不能为空",
                evidence={"module_position": key[0], "slot_id": key[1]},
            )
        if len(alt_text) > slot.alt_text_max_length:
            return AplusPolicyResult(
                ok=False,
                status=STATUS_FAILED,
                reason_code=FAILURE_ALT_TEXT_TOO_LONG,
                message=f"增强版 A+ 图片 alt text 超过 {slot.alt_text_max_length} 字符",
                evidence={"module_position": key[0], "slot_id": key[1], "alt_text_length": len(alt_text), "max_length": slot.alt_text_max_length},
            )
        asset_slot_id = _clean(item.get("asset_slot_id"))
        if not asset_slot_id:
            return AplusPolicyResult(
                ok=False,
                status=STATUS_FAILED,
                reason_code=FAILURE_IMAGE_SLOT_UNEXPECTED,
                message="增强版 A+ 图片缺少 asset_slot_id",
                evidence={"module_position": key[0], "slot_id": key[1]},
            )
        assets.append(
            AplusPublishAsset(
                position=slot_spec.position,
                module_position=slot_spec.position,
                path=path,
                alt_text=alt_text,
                width=width,
                height=height,
                content_type=mimetypes.guess_type(str(path))[0] or item.get("content_type") or "image/jpeg",
                size=path.stat().st_size,
                asset_slot_id=asset_slot_id,
                slot_id=slot.slot_id,
                semantic_role=slot_spec.semantic_role,
                payload_slot=payload_slot,
                target_width=target_width,
                target_height=target_height,
                min_width=slot.min_width,
                min_height=slot.min_height,
            )
        )

    return AplusPolicyResult(
        ok=True,
        status=STATUS_READY_TO_UPLOAD,
        assets=assets,
        evidence={
            "publish_profile": APLUS_PUBLISH_PROFILE_ENHANCED_BASIC_APLUS_V1,
            "required_slot_count": len(required_slots),
            "asset_slot_ids": [asset.asset_slot_id for asset in assets],
            "slot_ids": [asset.slot_id for asset in assets],
        },
    )


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
    profile = _plan_publish_profile(product_aplus)
    if profile == APLUS_PUBLISH_PROFILE_ENHANCED_BASIC_APLUS_V1:
        return _collect_enhanced_aplus_publish_assets(product, parsed_images)
    if profile and not get_profile_spec(profile):
        return AplusPolicyResult(
            ok=False,
            status=STATUS_FAILED,
            reason_code="unsupported_aplus_publish_profile",
            message="A+ plan 使用了不支持的 publish_profile",
            evidence={"publish_profile": profile},
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
                module_position=int(item.get("position") or index + 1),
                target_width=MIN_APLUS_IMAGE_WIDTH,
                target_height=MIN_APLUS_IMAGE_HEIGHT,
                min_width=MIN_APLUS_IMAGE_WIDTH,
                min_height=MIN_APLUS_IMAGE_HEIGHT,
            )
        )

    return AplusPolicyResult(
        ok=True,
        status=STATUS_READY_TO_UPLOAD,
        assets=assets,
        evidence={"publish_profile": profile or APLUS_PUBLISH_PROFILE_STANDARD_HEADER_IMAGE_TEXT_V1, "legacy_position_images": len(assets)},
    )


def build_aplus_content_fingerprint(
    product_aplus: ProductAplus | None,
    assets: list[AplusPublishAsset],
    *,
    module_mapping_evidence: dict[str, Any] | None = None,
) -> str:
    payload = {
        "product_aplus_id": getattr(product_aplus, "id", None),
        "aplus_status": getattr(product_aplus, "aplus_status", None),
        "aplus_plan": getattr(product_aplus, "aplus_plan", None),
        "aplus_scripts": getattr(product_aplus, "aplus_scripts", None),
        "assets": [
            {
                "position": asset.position,
                "asset_slot_id": asset.asset_slot_id,
                "slot_id": asset.slot_id,
                "module_position": asset.module_position,
                "semantic_role": asset.semantic_role,
                "payload_slot": asset.payload_slot,
                "path": str(asset.path),
                "width": asset.width,
                "height": asset.height,
                "target_width": asset.target_width,
                "target_height": asset.target_height,
                "size": asset.size,
            }
            for asset in assets
        ],
        "module_mapping_evidence": module_mapping_evidence or {},
        "aplus_publish_profile": (module_mapping_evidence or {}).get("profile") or _plan_publish_profile(product_aplus) or STANDARD_HEADER_IMAGE_TEXT_V1.profile_key,
        "lingxing_content_module_types": (module_mapping_evidence or {}).get("content_module_types") or [STANDARD_HEADER_IMAGE_TEXT_V1.content_module_type],
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
