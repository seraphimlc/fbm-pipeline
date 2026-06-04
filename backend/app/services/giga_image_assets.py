import asyncio
import hashlib
import mimetypes
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import httpx

from app.config import settings
from app.models import GigaProductImage

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tiff"}
SOURCE_PLATFORM = "GIGA"


@dataclass(frozen=True)
class GigaImageCandidate:
    sku_code: str
    item_code: str | None
    image_url: str
    image_type: str
    sort_order: int


def _safe_path_part(value: str | None, fallback: str) -> str:
    text = (value or "").strip() or fallback
    keep = []
    for char in text:
        if char.isalnum() or char in ("-", "_", "."):
            keep.append(char)
        else:
            keep.append("_")
    return "".join(keep).strip("._") or fallback


def _url_hash(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def _extension_from_url(url: str, content_type: str | None = None) -> str:
    parsed = urlparse(url)
    suffix = Path(unquote(parsed.path)).suffix.lower()
    if suffix in IMAGE_EXTENSIONS:
        return suffix
    guessed = mimetypes.guess_extension((content_type or "").split(";")[0].strip())
    if guessed and guessed.lower() in IMAGE_EXTENSIONS:
        return guessed.lower()
    return ".jpg"


def _is_image_url(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    text = value.strip()
    if not text.startswith(("http://", "https://")):
        return False
    path = urlparse(text).path.lower()
    return any(path.endswith(ext) for ext in IMAGE_EXTENSIONS)


def _append_unique(candidates: list[tuple[str, str]], seen: set[str], url: Any, image_type: str) -> None:
    if not _is_image_url(url):
        return
    text = str(url).strip()
    if text in seen:
        return
    seen.add(text)
    candidates.append((text, image_type))


def extract_giga_image_candidates(
    *,
    sku_code: str,
    item_code: str | None,
    detail: dict[str, Any],
) -> list[GigaImageCandidate]:
    raw_candidates: list[tuple[str, str]] = []
    seen: set[str] = set()

    main_url = detail.get("mainImageUrl")
    _append_unique(raw_candidates, seen, main_url, "main")

    for url in detail.get("imageUrls") or []:
        image_type = "main" if url == main_url else "gallery"
        _append_unique(raw_candidates, seen, url, image_type)

    for url in detail.get("fileUrls") or []:
        _append_unique(raw_candidates, seen, url, "file")

    brand_info = detail.get("brandInfo") or {}
    if isinstance(brand_info, dict):
        brand_pictures = brand_info.get("brandPictures") or []
        if isinstance(brand_pictures, list):
            for url in brand_pictures:
                _append_unique(raw_candidates, seen, url, "brand")

    return [
        GigaImageCandidate(
            sku_code=sku_code,
            item_code=item_code,
            image_url=url,
            image_type=image_type,
            sort_order=index,
        )
        for index, (url, image_type) in enumerate(raw_candidates, start=1)
    ]


def _target_path(site: str, candidate: GigaImageCandidate, content_type: str | None = None) -> Path:
    site_part = _safe_path_part(site.upper(), "unknown_site")
    item_part = _safe_path_part(candidate.item_code, "unknown_item")
    ext = _extension_from_url(candidate.image_url, content_type)
    filename = f"source_image_{_url_hash(candidate.image_url)[:16]}{ext}"
    return settings.PRODUCT_BASE_DIR / "GIGA" / site_part / item_part / filename


def build_pending_giga_product_image_rows(
    *,
    batch_id: str,
    site: str,
    candidates: list[GigaImageCandidate],
    data_source_id: int | None = None,
) -> list[GigaProductImage]:
    pulled_at = datetime.now()
    return [
        GigaProductImage(
            batch_id=batch_id,
            site=site,
            data_source_id=data_source_id,
            item_code=candidate.item_code,
            sku_code=candidate.sku_code,
            image_url=candidate.image_url,
            local_path=None,
            image_type=candidate.image_type,
            sort_order=candidate.sort_order,
            url_hash=_url_hash(candidate.image_url),
            content_hash=None,
            file_size=None,
            mime_type=None,
            download_status="pending",
            error_message=None,
            source_platform=SOURCE_PLATFORM,
            pulled_at=pulled_at,
        )
        for candidate in candidates
    ]


async def download_giga_product_images(
    *,
    batch_id: str,
    site: str,
    candidates: list[GigaImageCandidate],
    concurrency: int = 64,
) -> list[GigaProductImage]:
    pulled_at = datetime.now()
    semaphore = asyncio.Semaphore(max(concurrency, 1))
    unique_candidates: dict[tuple[str | None, str], GigaImageCandidate] = {}
    for candidate in candidates:
        unique_candidates.setdefault((candidate.item_code, candidate.image_url), candidate)

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(connect=10, read=20, write=20, pool=80),
        follow_redirects=True,
        headers={"User-Agent": "Mozilla/5.0"},
    ) as client:

        async def download_one(candidate: GigaImageCandidate) -> dict[str, Any]:
            async with semaphore:
                result: dict[str, Any] = {
                    "local_path": None,
                    "content_hash": None,
                    "file_size": None,
                    "mime_type": None,
                    "download_status": "failed",
                    "error_message": None,
                }
                try:
                    target = _target_path(site, candidate)
                    if target.exists() and target.is_file():
                        content = target.read_bytes()
                        result.update({
                            "local_path": str(target),
                            "content_hash": hashlib.sha256(content).hexdigest(),
                            "file_size": len(content),
                            "mime_type": mimetypes.guess_type(target.name)[0],
                            "download_status": "done",
                        })
                    else:
                        response = await client.get(candidate.image_url)
                        response.raise_for_status()
                        mime_type = response.headers.get("content-type")
                        content = response.content
                        content_hash = hashlib.sha256(content).hexdigest()
                        file_size = len(content)
                        target = _target_path(site, candidate, mime_type)
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_bytes(content)
                        result.update({
                            "local_path": str(target),
                            "content_hash": content_hash,
                            "file_size": file_size,
                            "mime_type": mime_type,
                            "download_status": "done",
                        })
                except Exception as exc:
                    result["error_message"] = f"{type(exc).__name__}: {exc}"
                return result

        unique_results = await asyncio.gather(*(download_one(candidate) for candidate in unique_candidates.values()))
        result_by_key = {
            key: result
            for key, result in zip(unique_candidates.keys(), unique_results, strict=False)
        }

    image_rows: list[GigaProductImage] = []
    for candidate in candidates:
        result = result_by_key.get((candidate.item_code, candidate.image_url), {})
        image_rows.append(GigaProductImage(
            batch_id=batch_id,
            site=site,
            item_code=candidate.item_code,
            sku_code=candidate.sku_code,
            image_url=candidate.image_url,
            local_path=result.get("local_path"),
            image_type=candidate.image_type,
            sort_order=candidate.sort_order,
            url_hash=_url_hash(candidate.image_url),
            content_hash=result.get("content_hash"),
            file_size=result.get("file_size"),
            mime_type=result.get("mime_type"),
            download_status=result.get("download_status") or "failed",
            error_message=result.get("error_message"),
            source_platform=SOURCE_PLATFORM,
            pulled_at=pulled_at,
        ))
    return image_rows
