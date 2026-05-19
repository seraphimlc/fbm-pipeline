import mimetypes
import re
from pathlib import Path

import oss2

from app.config import settings


def oss_configured() -> bool:
    return bool(
        settings.OSS_ACCESS_KEY_ID
        and settings.OSS_ACCESS_KEY_SECRET
        and settings.OSS_BUCKET
        and settings.OSS_ENDPOINT
    )


def _endpoint() -> str:
    endpoint = settings.OSS_ENDPOINT.strip()
    if endpoint and not endpoint.startswith(("http://", "https://")):
        endpoint = f"https://{endpoint}"
    return endpoint


def _safe_part(value: str | None, fallback: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value or "").strip("-._")
    return cleaned or fallback


def _bucket() -> oss2.Bucket:
    auth = oss2.Auth(settings.OSS_ACCESS_KEY_ID, settings.OSS_ACCESS_KEY_SECRET)
    return oss2.Bucket(auth, _endpoint(), settings.OSS_BUCKET, connect_timeout=settings.OSS_UPLOAD_TIMEOUT_SECONDS)


def upload_private_image(path: Path, product_key: str, slot: str) -> dict:
    if not oss_configured():
        raise RuntimeError("OSS 未配置，无法上传商品图片。")
    if not path.is_file():
        raise FileNotFoundError(f"图片不存在: {path}")

    suffix = path.suffix.lower() or ".jpg"
    content_type = mimetypes.types_map.get(suffix, "application/octet-stream")
    prefix = settings.OSS_UPLOAD_PREFIX.strip().strip("/")
    product_dir = _safe_part(product_key, "unknown-product")
    slot_name = _safe_part(slot, "image")
    object_key = f"{prefix}/{product_dir}/{slot_name}{suffix}" if prefix else f"{product_dir}/{slot_name}{suffix}"

    bucket = _bucket()
    result = bucket.put_object_from_file(object_key, str(path), headers={"Content-Type": content_type})
    signed_url = bucket.sign_url("GET", object_key, settings.OSS_SIGNED_URL_EXPIRES_SECONDS, slash_safe=True)
    return {
        "slot": slot,
        "path": str(path),
        "object_key": object_key,
        "url": signed_url,
        "status": result.status,
        "expires_seconds": settings.OSS_SIGNED_URL_EXPIRES_SECONDS,
    }
