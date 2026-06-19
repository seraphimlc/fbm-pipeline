from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import math
import mimetypes
import re
from io import BytesIO
from pathlib import Path
from urllib.parse import unquote, urlparse

import httpx
from PIL import Image, ImageDraw, ImageFont, ImageOps

from app.config import settings

logger = logging.getLogger(__name__)

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tiff"}

THUMB_SIZE = 420
LABEL_HEIGHT = 52
SHEET_COLS = 3
SHEET_MAX = 6
SHEET_JPEG_QUALITY = 82
SHEET_MIN_JPEG_QUALITY = 60
SHEET_MAX_BYTES = 550_000

DEFAULT_VLM_SYSTEM_PROMPT = "You are an expert Amazon product image analyst. Output valid JSON only, no markdown fences."


def is_remote_url(value: str | None) -> bool:
    return bool(value and re.match(r"^https?://", str(value).strip(), flags=re.I))


def image_data_url(image_path: Path) -> str:
    suffix = image_path.suffix.lower()
    mime = {
        ".jpg": "image/jpg",
        ".jpeg": "image/jpg",
        ".png": "image/png",
        ".webp": "image/webp",
    }.get(suffix, "image/jpg")
    img_b64 = base64.b64encode(image_path.read_bytes()).decode()
    return f"data:{mime};base64,{img_b64}"


def clean_json_content(content: str) -> str:
    content_clean = content.strip()
    if content_clean.startswith("```"):
        content_clean = content_clean.split("\n", 1)[1] if "\n" in content_clean else content_clean[3:]
    if content_clean.endswith("```"):
        content_clean = content_clean[:-3]
    return content_clean.strip()


def is_data_inspection_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return (
        "data_inspection_failed" in text
        or "datainspectionfailed" in text
        or "input image data may contain inappropriate content" in text
    )


def is_transient_vlm_error(exc: Exception) -> bool:
    name = type(exc).__name__.lower()
    text = str(exc).lower()
    return (
        "apiconnectionerror" in name
        or "apitimeouterror" in name
        or "timeout" in name
        or "remoteprotocolerror" in name
        or "connection error" in text
        or "server disconnected" in text
        or "temporarily unavailable" in text
    )


def _image_ext_from_url(url: str, content_type: str | None = None) -> str:
    suffix = Path(unquote(urlparse(url).path)).suffix.lower()
    if suffix in IMAGE_EXTENSIONS:
        return suffix
    guessed = mimetypes.guess_extension((content_type or "").split(";")[0].strip())
    if guessed and guessed.lower() in IMAGE_EXTENSIONS:
        return guessed.lower()
    return ".jpg"


async def download_remote_image(url: str, target_dir: Path) -> str:
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
    for existing in sorted(target_dir.glob(f"source_image_{digest[:16]}.*")):
        if existing.is_file():
            return str(existing)
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(connect=10, read=30, write=20, pool=20),
        follow_redirects=True,
        headers={"User-Agent": "Mozilla/5.0"},
    ) as client:
        response = await client.get(url)
        response.raise_for_status()
        content_type = response.headers.get("content-type")
        content = response.content
    target = target_dir / f"source_image_{digest[:16]}{_image_ext_from_url(url, content_type)}"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    return str(target)


async def download_image_records(records: list[dict], target_dir: Path) -> list[dict]:
    downloaded: list[dict] = []
    for record in records:
        source = str(record.get("path") or "").strip()
        if not source:
            continue
        path = await download_remote_image(source, target_dir) if is_remote_url(source) else source
        local = Path(path).expanduser()
        if not local.is_file():
            continue
        downloaded.append({
            **record,
            "path": str(local),
            "source_url": source if is_remote_url(source) else record.get("source_url"),
            "source_type": "file",
            "filename": local.name,
        })
    return downloaded


def _load_font(size: int):
    for name in ["Arial.ttf", "Helvetica.ttc", "DejaVuSans.ttf"]:
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            pass
    return ImageFont.load_default()


def build_contact_sheets(image_records: list[dict], output_dir: Path, product_key: str) -> list[dict]:
    output_dir.mkdir(parents=True, exist_ok=True)
    label_font = _load_font(24)
    small_font = _load_font(16)
    sheets: list[dict] = []

    for offset in range(0, len(image_records), SHEET_MAX):
        batch = image_records[offset:offset + SHEET_MAX]
        page = offset // SHEET_MAX + 1
        rows = math.ceil(len(batch) / SHEET_COLS)
        tile_w = THUMB_SIZE
        tile_h = THUMB_SIZE + LABEL_HEIGHT
        sheet = Image.new("RGB", (SHEET_COLS * tile_w, rows * tile_h), "white")
        draw = ImageDraw.Draw(sheet)
        sheet_path = output_dir / f"{product_key}_sheet_{page:02d}.jpg"

        for i, record in enumerate(batch):
            row = i // SHEET_COLS
            col = i % SHEET_COLS
            x = col * tile_w
            y = row * tile_h
            draw.rectangle((x, y, x + tile_w - 1, y + tile_h - 1), outline=(210, 210, 210), width=2)
            try:
                with Image.open(record["path"]) as source:
                    source = ImageOps.exif_transpose(source).convert("RGB")
                    source.thumbnail((tile_w - 24, THUMB_SIZE - 24), Image.Resampling.LANCZOS)
                    px = x + (tile_w - source.width) // 2
                    py = y + (THUMB_SIZE - source.height) // 2
                    sheet.paste(source, (px, py))
            except Exception as exc:
                logger.warning("无法处理图片 %s: %s", record.get("path"), exc)
                draw.text((x + 20, y + 20), f"OPEN FAILED: {exc}", font=small_font, fill="red")

            label = f"{record['image_id']}  {record['filename']}"
            draw.rectangle((x, y + THUMB_SIZE, x + tile_w, y + tile_h), fill=(246, 246, 246))
            draw.text((x + 12, y + THUMB_SIZE + 10), label[:90], font=label_font, fill=(20, 20, 20))
            record["contact_sheet_evidence"] = {
                "sheet_path": str(sheet_path),
                "sheet_page": page,
                "sheet_label": record["image_id"],
            }

        save_contact_sheet(sheet, sheet_path)
        sheets.append({
            "sheet_page": page,
            "sheet_path": str(sheet_path),
            "image_ids": [record["image_id"] for record in batch],
        })

    return sheets


def build_image_url_batches(image_records: list[dict]) -> list[dict]:
    batches: list[dict] = []
    for offset in range(0, len(image_records), SHEET_MAX):
        batch_records = image_records[offset:offset + SHEET_MAX]
        page = offset // SHEET_MAX + 1
        sheet_path = f"url_batch:{page:02d}"
        for record in batch_records:
            record["contact_sheet_evidence"] = {
                "sheet_path": sheet_path,
                "sheet_page": page,
                "sheet_label": record["image_id"],
                "source": "direct_image_url",
            }
        batches.append({
            "sheet_page": page,
            "sheet_path": sheet_path,
            "image_ids": [record["image_id"] for record in batch_records],
            "source": "direct_image_url",
        })
    return batches


def save_contact_sheet(sheet: Image.Image, sheet_path: Path) -> None:
    current = sheet
    quality = SHEET_JPEG_QUALITY
    while True:
        buffer = BytesIO()
        current.save(buffer, "JPEG", quality=quality, optimize=True, progressive=True)
        size = buffer.tell()
        if size <= SHEET_MAX_BYTES:
            sheet_path.write_bytes(buffer.getvalue())
            return

        if quality > SHEET_MIN_JPEG_QUALITY:
            quality = max(SHEET_MIN_JPEG_QUALITY, quality - 8)
            continue

        width, height = current.size
        next_size = (max(720, int(width * 0.88)), max(540, int(height * 0.88)))
        if next_size == current.size:
            logger.warning("Contact Sheet 仍超过目标大小: %s, bytes=%s, target=%s", sheet_path.name, size, SHEET_MAX_BYTES)
            sheet_path.write_bytes(buffer.getvalue())
            return
        current = current.resize(next_size, Image.Resampling.LANCZOS)


def normalize_sheet_reviews(analysis: dict, batch_records: list[dict], sheet_record: dict) -> list[dict]:
    by_id = {record["image_id"]: record for record in batch_records}
    by_filename = {record["filename"]: record for record in batch_records}
    reviews = []
    for idx, item in enumerate(analysis.get("images") or [], 1):
        image_id = item.get("image_id") or item.get("sheet_label") or f"#{idx:02d}"
        record = by_id.get(image_id) or by_filename.get(item.get("filename"))
        if not record and 0 <= idx - 1 < len(batch_records):
            record = batch_records[idx - 1]
        if not record:
            continue

        normalized = {
            **item,
            "image_id": record["image_id"],
            "filename": record["filename"],
            "path": record["path"],
            "contact_sheet_evidence": record.get("contact_sheet_evidence") or {
                "sheet_path": sheet_record["sheet_path"],
                "sheet_page": sheet_record["sheet_page"],
                "sheet_label": record["image_id"],
            },
        }
        normalized.setdefault("slot01_score", 0)
        normalized.setdefault("gallery_score", 0)
        normalized.setdefault("risk_flags", [])
        reviews.append(normalized)
    return reviews


async def analyze_contact_sheet(
    client,
    image_analysis_model: str,
    sheet: dict,
    batch_records: list[dict],
    prompt: str,
    *,
    system_prompt: str = DEFAULT_VLM_SYSTEM_PROMPT,
    log_prefix: str = "ProductImageVLM",
) -> tuple[dict, list[dict]]:
    sheet_path = Path(sheet["sheet_path"])
    image_url = image_data_url(sheet_path)

    logger.info(
        "[%s] 调用VLM分析图片: model=%s, provider=%s, sheet=%s, page=%s, images=%s, bytes=%s",
        log_prefix,
        image_analysis_model,
        "LLM_API" if settings.VLM_USE_LLM_API else "VLM_API",
        sheet_path.name,
        sheet["sheet_page"],
        len(batch_records),
        sheet_path.stat().st_size,
    )
    request_client = client.with_options(timeout=45, max_retries=0) if hasattr(client, "with_options") else client
    max_attempts = 2 if len(batch_records) > 1 else 3
    response = None
    for attempt in range(1, max_attempts + 1):
        try:
            response = await asyncio.wait_for(
                request_client.chat.completions.create(
                    model=image_analysis_model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {
                            "role": "user",
                            "content": [
                                {"type": "image_url", "image_url": {"url": image_url}},
                                {"type": "text", "text": prompt},
                            ],
                        },
                    ],
                    max_tokens=4000,
                    temperature=0.2,
                ),
                timeout=60,
            )
            break
        except Exception as exc:
            if is_data_inspection_error(exc) or not is_transient_vlm_error(exc) or attempt >= max_attempts:
                raise
            wait_seconds = attempt * 5
            logger.warning(
                "[%s] VLM图片分析连接异常，准备重试: sheet=%s, attempt=%s/%s, wait=%ss, error=%s: %s",
                log_prefix,
                sheet_path.name,
                attempt,
                max_attempts,
                wait_seconds,
                type(exc).__name__,
                exc,
            )
            await asyncio.sleep(wait_seconds)
    if response is None:
        raise RuntimeError(f"VLM 未返回响应: contact_sheet={sheet_path.name}")

    content = response.choices[0].message.content
    if not content:
        raise RuntimeError(f"VLM 返回空结果: contact_sheet={sheet_path.name}")

    try:
        sheet_analysis = json.loads(clean_json_content(content))
    except json.JSONDecodeError as exc:
        logger.warning("VLM JSON解析失败，保存原始内容: %s", exc)
        sheet_analysis = {"raw": content, "images": []}

    reviews = normalize_sheet_reviews(sheet_analysis, batch_records, sheet)
    return sheet_analysis, reviews


def image_url_batch_descriptor(batch_records: list[dict]) -> str:
    lines = [
        "The images are attached individually in the same order as this list.",
        "Use the provided image_id values exactly in the JSON output:",
    ]
    for index, record in enumerate(batch_records, 1):
        lines.append(
            f"{index}. {record['image_id']} filename={record.get('filename') or ''} "
            f"source={record.get('path') or ''}"
        )
    return "\n".join(lines)


async def analyze_image_url_batch(
    client,
    image_analysis_model: str,
    batch: dict,
    batch_records: list[dict],
    prompt: str,
    *,
    system_prompt: str = DEFAULT_VLM_SYSTEM_PROMPT,
    log_prefix: str = "ProductImageVLM",
) -> tuple[dict, list[dict]]:
    logger.info(
        "[%s] 调用VLM分析图片URL: model=%s, provider=%s, batch=%s, images=%s",
        log_prefix,
        image_analysis_model,
        "LLM_API" if settings.VLM_USE_LLM_API else "VLM_API",
        batch["sheet_page"],
        len(batch_records),
    )
    content: list[dict] = []
    for record in batch_records:
        source = str(record.get("path") or "")
        image_url = source if is_remote_url(source) else image_data_url(Path(source).expanduser())
        content.append({"type": "image_url", "image_url": {"url": image_url}})
    content.append({
        "type": "text",
        "text": (
            prompt.replace("Analyze this contact sheet page", "Analyze these product images")
            + "\n\n"
            + image_url_batch_descriptor(batch_records)
            + "\n\nThere is no contact sheet. Each attached image corresponds to the list above."
        ),
    })

    request_client = client.with_options(timeout=60, max_retries=0) if hasattr(client, "with_options") else client
    max_attempts = 2 if len(batch_records) > 1 else 3
    response = None
    for attempt in range(1, max_attempts + 1):
        try:
            response = await asyncio.wait_for(
                request_client.chat.completions.create(
                    model=image_analysis_model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": content},
                    ],
                    max_tokens=4000,
                    temperature=0.2,
                ),
                timeout=75,
            )
            break
        except Exception as exc:
            if is_data_inspection_error(exc) or not is_transient_vlm_error(exc) or attempt >= max_attempts:
                raise
            wait_seconds = attempt * 5
            logger.warning(
                "[%s] VLM图片URL分析连接异常，准备重试: batch=%s, attempt=%s/%s, wait=%ss, error=%s: %s",
                log_prefix,
                batch["sheet_page"],
                attempt,
                max_attempts,
                wait_seconds,
                type(exc).__name__,
                exc,
            )
            await asyncio.sleep(wait_seconds)
    if response is None:
        raise RuntimeError(f"VLM 未返回响应: image_url_batch={batch['sheet_page']}")

    response_content = response.choices[0].message.content
    if not response_content:
        raise RuntimeError(f"VLM 返回空结果: image_url_batch={batch['sheet_page']}")

    try:
        batch_analysis = json.loads(clean_json_content(response_content))
    except json.JSONDecodeError as exc:
        logger.warning("VLM URL JSON解析失败，保存原始内容: %s", exc)
        batch_analysis = {"raw": response_content, "images": []}

    reviews = normalize_sheet_reviews(batch_analysis, batch_records, batch)
    return batch_analysis, reviews
