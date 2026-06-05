"""
模块9：A+ 出图 — 使用 GPT Image API 批量生成 A+ Content 图片

基于模块8的出图脚本，并发调用 GPT Image API 生成图片
5个并发，每张图 15-30秒
"""

import asyncio
import base64
import json
import logging
import math
import re
import shutil
import time
from io import BytesIO
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote, urlparse

import httpx
from PIL import Image, ImageDraw, ImageFont

from app.config import settings
from app.database import async_session
from app.models import Product, ProductAplus
from app.services.oss_uploader import oss_configured, upload_private_image
from sqlalchemy import select
from sqlalchemy.orm import selectinload

logger = logging.getLogger(__name__)


def _aspect_ratio(width: int, height: int) -> str:
    divisor = math.gcd(width, height)
    return f"{width // divisor}:{height // divisor}"


def _is_remote_url(value: str | None) -> bool:
    return bool(value and str(value).strip().lower().startswith(("http://", "https://")))


def _reference_image_sources(script: dict) -> list[str]:
    refs = script.get("reference_images") or []
    sources: list[str] = []
    if not isinstance(refs, list):
        return sources
    for ref in refs:
        path = ref if isinstance(ref, str) else ref.get("path") if isinstance(ref, dict) else None
        if path:
            sources.append(str(path).strip())
    return sources


def _reference_image_paths(script: dict) -> list[Path]:
    return [Path(source).expanduser() for source in _reference_image_sources(script) if not _is_remote_url(source)]


def _reference_image_name(source: str) -> str:
    if _is_remote_url(source):
        return Path(unquote(urlparse(source).path)).name or "remote-reference.jpg"
    return Path(source).expanduser().name


def _reference_image_names(sources: list[str]) -> str:
    return ", ".join(_reference_image_name(source) for source in sources)


def _reference_image_upload(path: Path, max_side: int = 1200, quality: int = 88) -> tuple[str, bytes, str]:
    with Image.open(path) as image:
        image = image.convert("RGB")
        image.thumbnail((max_side, max_side))
        buffer = BytesIO()
        image.save(buffer, format="JPEG", quality=quality, optimize=True)
    return f"{path.stem}.jpg", buffer.getvalue(), "image/jpeg"


def _reference_image_data_url(path: Path, max_side: int = 1200, quality: int = 88) -> str:
    _, img_bytes, _ = _reference_image_upload(path, max_side, quality)
    return "data:image/jpeg;base64," + base64.b64encode(img_bytes).decode("ascii")


def _reference_image_generation_input(source: str) -> str:
    if _is_remote_url(source):
        return source
    return _reference_image_data_url(Path(source).expanduser())


async def _reference_image_upload_source(source: str) -> tuple[str, bytes, str]:
    if not _is_remote_url(source):
        return _reference_image_upload(Path(source).expanduser())
    async with httpx.AsyncClient(timeout=httpx.Timeout(connect=10, read=30, write=20, pool=20), follow_redirects=True) as client:
        response = await client.get(source)
        response.raise_for_status()
        content_type = response.headers.get("content-type") or "image/jpeg"
        content = response.content
    with Image.open(BytesIO(content)) as image:
        image = image.convert("RGB")
        image.thumbnail((1200, 1200))
        buffer = BytesIO()
        image.save(buffer, format="JPEG", quality=88, optimize=True)
    return f"{Path(unquote(urlparse(source).path)).stem or 'remote-reference'}.jpg", buffer.getvalue(), "image/jpeg"


def _generation_quality() -> str:
    return "high"


def _generation_quality_attempts() -> list[str]:
    return ["high", "auto"]


def _image_size(img_bytes: bytes) -> tuple[int, int]:
    with Image.open(BytesIO(img_bytes)) as image:
        return image.size


def _image_extension(img_bytes: bytes) -> str:
    try:
        with Image.open(BytesIO(img_bytes)) as image:
            image_format = (image.format or "").upper()
    except Exception:
        return ".img"
    return {
        "JPEG": ".jpg",
        "JPG": ".jpg",
        "PNG": ".png",
        "WEBP": ".webp",
        "GIF": ".gif",
        "BMP": ".bmp",
        "TIFF": ".tiff",
    }.get(image_format, ".img")


def _encode_jpeg(image: Image.Image, quality: int) -> bytes:
    buffer = BytesIO()
    image.save(
        buffer,
        "JPEG",
        quality=quality,
        optimize=True,
        progressive=True,
        subsampling=2,
    )
    return buffer.getvalue()


def _encode_jpeg_under_limit(image: Image.Image) -> tuple[bytes, int]:
    max_bytes = settings.APLUS_IMAGE_MAX_BYTES
    start_quality = min(max(settings.APLUS_IMAGE_JPEG_QUALITY, 1), 95)
    min_quality = min(max(settings.APLUS_IMAGE_MIN_JPEG_QUALITY, 1), start_quality)

    best_bytes = b""
    best_quality = start_quality
    for quality in range(start_quality, min_quality - 1, -1):
        encoded = _encode_jpeg(image, quality)
        best_bytes = encoded
        best_quality = quality
        if len(encoded) <= max_bytes:
            return encoded, quality

    raise RuntimeError(
        f"A+图片压缩后仍超过限制: {len(best_bytes)} bytes, "
        f"目标不超过 {max_bytes} bytes, 最低质量 {best_quality}"
    )


def _module_output_path(output_dir: Path, position: int) -> Path:
    return output_dir / f"aplus_{position:02d}.jpg"


def _should_overwrite_existing() -> bool:
    policy = (settings.APLUS_IMAGE_OVERWRITE_POLICY or "skip_success").strip().lower()
    if policy not in {"skip_success", "overwrite_all"}:
        logger.warning(f"[Step9] 未识别的A+覆盖策略 {policy!r}，回退到 skip_success")
        return False
    return policy == "overwrite_all"


def _existing_result_map(pa: ProductAplus | None) -> dict[int, dict]:
    if not pa or not pa.aplus_images:
        return {}
    try:
        parsed = json.loads(pa.aplus_images)
    except json.JSONDecodeError:
        return {}
    if not isinstance(parsed, list):
        return {}
    result: dict[int, dict] = {}
    for item in parsed:
        if not isinstance(item, dict):
            continue
        try:
            position = int(item.get("position") or 0)
        except (TypeError, ValueError):
            continue
        if position:
            result[position] = item
    return result


def _file_result(output_path: Path, position: int, script: dict, reused_from: str, oss_info: dict | None = None) -> dict:
    oss_info = oss_info or {}
    display_url = oss_info.get("oss_url") or str(output_path)
    return {
        "position": position,
        "status": "done",
        "path": str(output_path),
        "url": display_url,
        "display_url": display_url,
        "size": output_path.stat().st_size,
        "model": settings.GPT_IMAGE_MODEL,
        "target_width": settings.APLUS_IMAGE_WIDTH,
        "target_height": settings.APLUS_IMAGE_HEIGHT,
        "reference_count": len(_reference_image_sources(script)),
        "reference_paths": _reference_image_sources(script),
        **oss_info,
        "skipped": True,
        "reused_existing": True,
        "reused_from": reused_from,
        "skip_reason": "已有成功A+图片，按配置跳过重新生成",
    }


def _existing_success_result(position: int, script: dict, output_path: Path, old_results: dict[int, dict], product_key: str) -> dict | None:
    old = old_results.get(position)
    if old and old.get("status") == "done":
        old_path = Path(str(old.get("path") or output_path)).expanduser()
        if old_path.is_file():
            oss_info = old if old.get("oss_url") else _upload_generated_image_to_oss(old_path, product_key, position)
            result = {**old}
            result.update({
                "position": position,
                "status": "done",
                "path": str(old_path),
                "url": oss_info.get("oss_url") or result.get("url") or str(old_path),
                "display_url": oss_info.get("oss_url") or result.get("display_url") or result.get("url") or str(old_path),
                "size": old_path.stat().st_size,
                **oss_info,
                "skipped": True,
                "reused_existing": True,
                "reused_from": "database",
                "skip_reason": "已有成功A+图片，按配置跳过重新生成",
            })
            return result
    if output_path.is_file():
        return _file_result(output_path, position, script, "file", _upload_generated_image_to_oss(output_path, product_key, position))
    return None


def _api_mode() -> str:
    mode = (settings.APLUS_IMAGE_API_MODE or "generations").strip().lower()
    if mode not in {"generations", "edits"}:
        logger.warning(f"[Step9] 未识别的A+生图通道 {mode!r}，回退到 generations")
        return "generations"
    return mode


def _edit_provider_size(width: int, height: int) -> str:
    provider_width = math.ceil(width / 16) * 16
    provider_height = math.ceil(height / 16) * 16
    return f"{provider_width}x{provider_height}"


def _backup_existing_module_images(output_dir: Path, position: int) -> None:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    for suffix in (".jpg", ".jpeg", ".png", ".webp"):
        candidate = output_dir / f"aplus_{position:02d}{suffix}"
        if candidate.exists():
            backup_path = output_dir / f"{candidate.stem}_backup_{timestamp}{candidate.suffix}"
            shutil.copy2(candidate, backup_path)
            logger.info(f"[Step9] 已备份旧A+图片: {backup_path.name}")


def _extract_image_urls(result: dict) -> list[str]:
    urls: list[str] = []
    data = result.get("data")
    if isinstance(data, list):
        urls.extend([img.get("url") for img in data if isinstance(img, dict) and img.get("url")])
    if isinstance(data, dict):
        nested = data.get("data", {}).get("data", [])
        if isinstance(nested, list):
            urls.extend([img.get("url") for img in nested if isinstance(img, dict) and img.get("url")])
    return urls


def _extract_b64_images(result: dict) -> list[str]:
    data = result.get("data")
    if isinstance(data, list):
        return [img.get("b64_json") for img in data if isinstance(img, dict) and img.get("b64_json")]
    return []


def _decode_data_image_url(url: str) -> bytes | None:
    if not url.startswith("data:image/"):
        return None
    header, _, encoded = url.partition(",")
    if not encoded or ";base64" not in header:
        return None
    return base64.b64decode(encoded)


async def _poll_image_task(client: httpx.AsyncClient, task_id: str) -> dict:
    task_url = f"{settings.resolved_gpt_image_api_base.rstrip('/')}/images/tasks/{task_id}"
    for _ in range(90):
        response = await client.get(task_url)
        response.raise_for_status()
        result = response.json()
        status_text = json.dumps(result, ensure_ascii=False).lower()
        if _extract_image_urls(result) or _extract_b64_images(result):
            return result
        if any(word in status_text for word in ("failed", "error", "cancelled")):
            raise RuntimeError(f"图片任务失败: {json.dumps(result, ensure_ascii=False)[:800]}")
        await asyncio.sleep(2)
    raise TimeoutError(f"图片任务超时: {task_id}")


async def _image_payload_from_result(client: httpx.AsyncClient, result: dict) -> dict:
    task_id = result.get("task_id") or result.get("id")
    data = result.get("data")
    if isinstance(data, dict):
        task_id = task_id or data.get("task_id") or data.get("id")
    if task_id and not (_extract_image_urls(result) or _extract_b64_images(result)):
        result = await _poll_image_task(client, task_id)

    b64_images = _extract_b64_images(result)
    if b64_images:
        return {
            "bytes": base64.b64decode(b64_images[0]),
            "provider_source": "b64_json",
        }

    urls = _extract_image_urls(result)
    if urls:
        data_url_image = _decode_data_image_url(urls[0])
        if data_url_image:
            return {
                "bytes": data_url_image,
                "provider_source": "data_url",
            }
        image_response = await client.get(urls[0])
        image_response.raise_for_status()
        return {
            "bytes": image_response.content,
            "provider_url": urls[0],
            "provider_url_accessible": True,
            "provider_source": "url",
            "provider_content_type": image_response.headers.get("content-type"),
        }

    raise RuntimeError(f"图片接口未返回图片: {json.dumps(result, ensure_ascii=False)[:800]}")


async def _submit_reference_generations(prompt: str, ref_sources: list[str], quality: str = "high") -> dict:
    generation_quality = quality if quality in {"high", "auto"} else _generation_quality()
    payload = {
        "model": settings.GPT_IMAGE_MODEL,
        "prompt": prompt,
        "aspect_ratio": settings.APLUS_IMAGE_ASPECT_RATIO,
        "quality": generation_quality,
        "n": 1,
        "response_format": "url",
        "image": [_reference_image_generation_input(source) for source in ref_sources],
    }
    url = f"{settings.resolved_gpt_image_api_base.rstrip('/')}/images/generations"
    headers = {
        "Authorization": f"Bearer {settings.resolved_gpt_image_api_key}",
        "Content-Type": "application/json",
    }

    last_error = ""
    rate_limit_count = 0
    retries = max(settings.APLUS_IMAGE_API_RETRIES, 1)
    async with httpx.AsyncClient(timeout=300, verify=not settings.GPT_IMAGE_USE_LLM_API) as http:
        for attempt in range(1, retries + 1):
            attempt_started = time.monotonic()
            try:
                logger.info(
                    f"[Step9] 提交A+参考图生图: model={settings.GPT_IMAGE_MODEL}, "
                    f"provider={settings.gpt_image_api_provider}, "
                    f"endpoint=images/generations, aspect_ratio={payload['aspect_ratio']}, "
                    f"quality={payload['quality']}, references={len(ref_sources)}, attempt={attempt}/{retries}"
                )
                response = await http.post(url, headers=headers, json=payload)
                if response.status_code >= 400:
                    if response.status_code == 429:
                        rate_limit_count += 1
                    raise RuntimeError(f"图片接口请求失败 {response.status_code}: {response.text[:1000]}")
                image_payload = await _image_payload_from_result(http, response.json())
                logger.info(
                    f"[Step9] generations 生图返回成功: quality={payload['quality']}, "
                    f"attempt={attempt}/{retries}, 耗时={time.monotonic() - attempt_started:.1f}s, "
                    f"429次数={rate_limit_count}"
                )
                return image_payload
            except Exception as e:
                last_error = str(e)
                if attempt >= retries:
                    break
                logger.warning(
                    f"[Step9] A+ generations 生图请求失败，准备重试: {last_error}; "
                    f"attempt={attempt}/{retries}, 耗时={time.monotonic() - attempt_started:.1f}s, "
                    f"429次数={rate_limit_count}"
                )
                await asyncio.sleep(2 * attempt)

    raise RuntimeError(last_error or "图片接口未返回图片")


def _ensure_provider_image_large_enough(image_payload: dict, width: int, height: int, label: str) -> dict:
    raw_width, raw_height = _image_size(image_payload["bytes"])
    if raw_width < width or raw_height < height:
        raise RuntimeError(f"{label} 返回图片尺寸过小: {raw_width}x{raw_height}, 目标 {width}x{height}")
    return image_payload


async def _submit_reference_edits(prompt: str, ref_sources: list[str], width: int, height: int) -> dict:
    data = {
        "model": settings.GPT_IMAGE_MODEL,
        "prompt": prompt,
        "size": _edit_provider_size(width, height),
        "n": "1",
        "response_format": "url",
    }
    files = [("image", await _reference_image_upload_source(source)) for source in ref_sources]
    url = f"{settings.resolved_gpt_image_api_base.rstrip('/')}/images/edits"
    headers = {
        "Authorization": f"Bearer {settings.resolved_gpt_image_api_key}",
    }

    last_error = ""
    rate_limit_count = 0
    retries = max(settings.APLUS_IMAGE_API_RETRIES, 1)
    async with httpx.AsyncClient(timeout=300, verify=not settings.GPT_IMAGE_USE_LLM_API) as http:
        for attempt in range(1, retries + 1):
            attempt_started = time.monotonic()
            try:
                logger.info(
                    f"[Step9] 提交A+参考图生图: model={settings.GPT_IMAGE_MODEL}, "
                    f"provider={settings.gpt_image_api_provider}, "
                    f"endpoint=images/edits, size={data['size']}, "
                    f"references={len(ref_sources)}, attempt={attempt}/{retries}"
                )
                response = await http.post(url, headers=headers, data=data, files=files)
                if response.status_code >= 400:
                    if response.status_code == 429:
                        rate_limit_count += 1
                    raise RuntimeError(f"图片接口请求失败 {response.status_code}: {response.text[:1000]}")
                image_payload = await _image_payload_from_result(http, response.json())
                logger.info(
                    f"[Step9] edits 生图返回成功: size={data['size']}, "
                    f"attempt={attempt}/{retries}, 耗时={time.monotonic() - attempt_started:.1f}s, "
                    f"429次数={rate_limit_count}"
                )
                return image_payload
            except Exception as e:
                last_error = str(e)
                if attempt >= retries:
                    break
                logger.warning(
                    f"[Step9] A+ edits 生图请求失败，准备重试: {last_error}; "
                    f"attempt={attempt}/{retries}, 耗时={time.monotonic() - attempt_started:.1f}s, "
                    f"429次数={rate_limit_count}"
                )
                await asyncio.sleep(2 * attempt)

    raise RuntimeError(last_error or "图片接口未返回图片")


async def _submit_reference_generation(prompt: str, ref_sources: list[str], width: int, height: int) -> dict:
    missing = [source for source in ref_sources if not _is_remote_url(source) and not Path(source).expanduser().is_file()]
    if missing:
        raise FileNotFoundError("参考图不存在: " + "; ".join(missing))
    if not ref_sources:
        raise ValueError("A+生图缺少 reference_images，停止纯文字生图；请先重新执行 Step8 生成带参考图的脚本")

    preferred_mode = _api_mode()
    modes = [preferred_mode, "edits" if preferred_mode == "generations" else "generations"]
    errors: list[str] = []
    for mode in modes:
        try:
            if mode == "generations":
                last_generation_error: Exception | None = None
                quality_attempts = _generation_quality_attempts()
                for quality in quality_attempts:
                    try:
                        return _ensure_provider_image_large_enough(
                            await _submit_reference_generations(prompt, ref_sources, quality),
                            width,
                            height,
                            f"generations/{quality}",
                        )
                    except Exception as generation_error:
                        last_generation_error = generation_error
                        if quality != quality_attempts[-1]:
                            logger.warning(f"[Step9] A+ generations/{quality} 失败，切换 auto 重试: {generation_error}")
                if last_generation_error:
                    raise last_generation_error
            return _ensure_provider_image_large_enough(
                await _submit_reference_edits(prompt, ref_sources, width, height),
                width,
                height,
                "edits",
            )
        except Exception as e:
            error_msg = f"{mode}: {type(e).__name__}: {e}"
            errors.append(error_msg)
            if mode != modes[-1]:
                logger.warning(f"[Step9] A+ {mode} 通道失败，切换备用通道: {e}")

    raise RuntimeError(" | ".join(errors))


def _save_exact_size_image(img_bytes: bytes, raw_path: Path, final_path: Path, width: int, height: int) -> dict:
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_bytes(img_bytes)
    final_path.parent.mkdir(parents=True, exist_ok=True)

    with Image.open(raw_path) as image:
        image = image.convert("RGB")
        raw_width, raw_height = image.size
        if raw_width == width and raw_height == height:
            final = image.copy()
        else:
            if raw_width < width or raw_height < height:
                raise RuntimeError(f"生成图片尺寸过小，不能放大伪造: {raw_width}x{raw_height}, 目标 {width}x{height}")
            source_ratio = raw_width / raw_height
            target_ratio = width / height
            if abs(source_ratio - target_ratio) < 0.002:
                final = image.resize((width, height), Image.Resampling.LANCZOS)
            else:
                scale = max(width / raw_width, height / raw_height)
                resized = image.resize((math.ceil(raw_width * scale), math.ceil(raw_height * scale)), Image.Resampling.LANCZOS)
                left = (resized.width - width) // 2
                top = (resized.height - height) // 2
                final = resized.crop((left, top, left + width, top + height))

        final_bytes, final_quality = _encode_jpeg_under_limit(final)
        final_path.write_bytes(final_bytes)

    with Image.open(final_path) as final_image:
        final_width, final_height = final_image.size

    if final_width != width or final_height != height:
        raise RuntimeError(f"A+图片尺寸校验失败: {final_width}x{final_height}, 目标 {width}x{height}")
    final_size = final_path.stat().st_size
    if final_size > settings.APLUS_IMAGE_MAX_BYTES:
        raise RuntimeError(f"A+图片超过2M限制: {final_size} bytes, 目标不超过 {settings.APLUS_IMAGE_MAX_BYTES} bytes")
    return {
        "raw_path": str(raw_path),
        "raw_width": raw_width,
        "raw_height": raw_height,
        "width": final_width,
        "height": final_height,
        "format": "JPEG",
        "jpeg_quality": final_quality,
        "max_bytes": settings.APLUS_IMAGE_MAX_BYTES,
        "compressed": final_size < len(img_bytes) or raw_width != final_width or raw_height != final_height,
    }


def _upload_generated_image_to_oss(output_path: Path, product_key: str, position: int) -> dict:
    if not oss_configured():
        raise RuntimeError("OSS 未配置，A+生成图无法上传到OSS。")
    try:
        result = upload_private_image(output_path, product_key, f"aplus_{position:02d}")
    except Exception as exc:
        logger.warning(f"[Step9] A+生成图上传OSS失败: position={position}, path={output_path}, error={exc}")
        raise RuntimeError(f"A+生成图上传OSS失败: {type(exc).__name__}: {exc}") from exc
    return {
        "oss_status": "uploaded",
        "oss_url": result.get("url"),
        "oss_object_key": result.get("object_key"),
        "oss_expires_seconds": result.get("expires_seconds"),
    }


def _create_fallback_aplus_image(output_path: Path, script: dict, ref_sources: list[str], width: int, height: int) -> dict:
    canvas = Image.new("RGB", (width, height), "#f8fafc")
    draw = ImageDraw.Draw(canvas)
    title = str(script.get("conversion_goal") or script.get("prompt") or "A+ content image")[:120]
    headline = f"A+ Module {script.get('module_position') or ''}".strip()
    try:
        font_title = ImageFont.truetype("Arial.ttf", 56)
        font_body = ImageFont.truetype("Arial.ttf", 34)
        font_small = ImageFont.truetype("Arial.ttf", 24)
    except Exception:
        font_title = font_body = font_small = ImageFont.load_default()

    draw.rectangle((0, 0, width, 118), fill="#111827")
    draw.text((56, 34), headline, fill="#ffffff", font=font_title)
    draw.text((56, 150), "Fallback A+ visual", fill="#0f172a", font=font_title)
    draw.text((56, 230), title, fill="#334155", font=font_body)
    draw.text(
        (56, height - 76),
        "Image generation service was unavailable. This placeholder preserves the pipeline and can be regenerated later.",
        fill="#64748b",
        font=font_small,
    )

    slots = [
        (56, 320, width // 2 - 28, height - 130),
        (width // 2 + 28, 320, width - 56, height - 130),
    ]
    pasted = 0
    for source, box in zip(ref_sources[:2], slots):
        if _is_remote_url(source):
            continue
        path = Path(source).expanduser()
        if not path.exists():
            continue
        try:
            with Image.open(path) as ref:
                ref = ref.convert("RGB")
                max_w = box[2] - box[0]
                max_h = box[3] - box[1]
                ref.thumbnail((max_w, max_h), Image.Resampling.LANCZOS)
                x = box[0] + (max_w - ref.width) // 2
                y = box[1] + (max_h - ref.height) // 2
                draw.rounded_rectangle(box, radius=18, fill="#ffffff", outline="#cbd5e1", width=2)
                canvas.paste(ref, (x, y))
                pasted += 1
        except Exception:
            continue
    if pasted == 0:
        draw.rounded_rectangle((56, 320, width - 56, height - 130), radius=18, fill="#ffffff", outline="#cbd5e1", width=2)
        draw.text((96, 380), "No local reference image available", fill="#64748b", font=font_body)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_path, format="JPEG", quality=92, optimize=True)
    return {
        "fallback_image": True,
        "fallback_reason": "A+ image generation service failed; placeholder generated locally.",
        "target_width": width,
        "target_height": height,
        "reference_count": len(ref_sources),
        "local_reference_count": pasted,
    }


async def _generate_single_image(
    script: dict,
    output_path: Path,
    semaphore: asyncio.Semaphore,
    product_key: str,
    brand: str | None = None,
) -> dict:
    """
    生成单张 A+ 图片
    
    Returns:
        dict: {path, status, error?}
    """
    async with semaphore:
        image_started = time.monotonic()
        width = settings.APLUS_IMAGE_WIDTH
        height = settings.APLUS_IMAGE_HEIGHT
        prompt = _sanitize_generation_prompt(script.get("prompt", ""), brand, script.get("negative_prompt"))
        position = script.get("module_position", 0)
        ref_sources = _reference_image_sources(script)

        try:
            logger.info(
                f"[Step9] 生成模块 {position} 图片 ({width}x{height}), references={len(ref_sources)}, "
                f"model={settings.GPT_IMAGE_MODEL}, provider={settings.gpt_image_api_provider}, "
                f"reference_files={_reference_image_names(ref_sources)}..."
            )
            if script.get("fallback_script"):
                raise RuntimeError("A+脚本是降级兜底结果，不能生成或上传占位 A+ 图片，请先重跑 A+脚本。")
            image_payload = await _submit_reference_generation(prompt, ref_sources, width, height)
            img_bytes = image_payload["bytes"]
            raw_path = output_path.with_name(f"{output_path.stem}_raw{_image_extension(img_bytes)}")
            size_info = _save_exact_size_image(img_bytes, raw_path, output_path, width, height)
            oss_info = _upload_generated_image_to_oss(output_path, product_key, position)
            display_url = oss_info.get("oss_url")
            if not display_url:
                raise RuntimeError("A+生成图已上传OSS，但未返回可用URL")

            logger.info(f"[Step9] 模块 {position} 图片已保存: {output_path.name}, 耗时={time.monotonic() - image_started:.1f}s")
            return {
                "position": position,
                "status": "done",
                "path": str(output_path),
                "url": display_url,
                "display_url": display_url,
                "provider_url": image_payload.get("provider_url"),
                "provider_url_accessible": image_payload.get("provider_url_accessible"),
                "provider_source": image_payload.get("provider_source"),
                "provider_content_type": image_payload.get("provider_content_type"),
                "size": output_path.stat().st_size,
                "model": settings.GPT_IMAGE_MODEL,
                "generation_quality": _generation_quality(),
                "target_width": width,
                "target_height": height,
                "reference_count": len(ref_sources),
                "reference_paths": ref_sources,
                **oss_info,
                **size_info,
            }

        except Exception as e:
            error_msg = f"{type(e).__name__}: {str(e)}"
            logger.error(f"[Step9] 模块 {position} 生成失败: {error_msg}, 耗时={time.monotonic() - image_started:.1f}s")
            return {"position": position, "status": "failed", "error": error_msg}


def _sanitize_generation_prompt(prompt: str, brand: str | None, negative_prompt: str | None = None) -> str:
    cleaned = re.sub(
        r"Output size requirement:\s*exactly\s*\d+\s*x\s*\d+\s*pixels\.?",
        "",
        prompt or "",
        flags=re.IGNORECASE,
    ).strip()
    size_rule = f"Output size requirement: exactly {settings.APLUS_IMAGE_WIDTH} x {settings.APLUS_IMAGE_HEIGHT} pixels."
    required = (
        f"{size_rule} "
        "Use the uploaded reference images as product identity anchors. "
        "The product in the generated image must match the uploaded references before satisfying scene or layout styling. "
        "Do not render any brand name, logo, or wordmark as on-image text. "
    )
    if brand:
        required += f"Specifically, do not render the brand name '{brand}' anywhere in the image. "
    required += (
        "If people appear, show complete full-body people with natural anatomy and no cropped body parts. "
        "Preserve the original product type, shape, color, dimensions, proportions, key parts, visible accessories, material, texture, surface finish, packaging, labels, and distinctive construction as much as possible; avoid product deformation. "
        "Preserve the exact material and finish shown in the selected product reference images; do not change the reference material, surface treatment, packaging, or visible design. "
        "Make the A+ image primarily express the visible selling point(s) described for the selected references. "
        "Scene, people, lighting, styling, camera framing, and clean A+ layout may change, but the product itself should remain as close as possible to the selected reference images. "
        "Do not add, remove, reshape, resize, recolor, retexture, relabel, or redesign product parts, accessories, packaging, safety features, age cues, mechanisms, or visible construction details. "
        "Do not invent unsupported safety certifications, age ratings, performance claims, included accessories, or product functions."
    )
    if required not in cleaned:
        cleaned = f"{cleaned}\n\n{required}"
    if negative_prompt:
        avoid = negative_prompt.strip()
        if avoid and avoid not in cleaned:
            cleaned = f"{cleaned}\n\nAvoid: {avoid}"
    return cleaned.strip()


async def run_aplus_image(product_id: int) -> dict:
    """
    执行 A+ 出图
    
    读取 A+ 脚本，并发生成所有 A+ 图片
    """
    async with async_session() as db:
        step_started = time.monotonic()
        result = await db.execute(
            select(Product)
            .options(
                selectinload(Product.data),
                selectinload(Product.aplus),
            )
            .where(Product.id == product_id)
        )
        product = result.scalar_one_or_none()
        if not product or not product.data:
            raise ValueError(f"Product {product_id} not found or no data")

        pd = product.data
        pa = product.aplus
        if not pa or not pa.aplus_scripts:
            raise ValueError("未找到A+脚本，请先执行Step8")

        try:
            scripts_data = json.loads(pa.aplus_scripts)
        except:
            raise ValueError("A+脚本数据损坏")

        scripts = scripts_data.get("scripts", [])
        if not scripts:
            raise ValueError("A+脚本中没有出图模块")

        # 准备输出目录
        material_dir = Path(pd.material_dir) if pd.material_dir else Path("/tmp/fbm_unknown")
        output_dir = material_dir / "new aplus image"
        output_dir.mkdir(parents=True, exist_ok=True)
        product_key = pd.item_code or f"product-{product.id}"

        old_results = _existing_result_map(pa)
        overwrite_existing = _should_overwrite_existing()

        # 并发控制
        semaphore = asyncio.Semaphore(settings.APLUS_CONCURRENCY)
        
        # 默认只生成缺失/失败图片，避免重复消耗生图费用。
        tasks = []
        image_results = []
        skipped_count = 0
        for script in scripts[:5]:
            if scripts_data.get("fallback"):
                raise RuntimeError("A+脚本是降级兜底结果，不能进入 A+出图，请先重跑 A+脚本。")
            position = script.get("module_position", 0)
            output_path = _module_output_path(output_dir, position)
            if not overwrite_existing:
                existing = _existing_success_result(position, script, output_path, old_results, product_key)
                if existing:
                    image_results.append(existing)
                    skipped_count += 1
                    continue
            tasks.append(_generate_single_image(script, output_path, semaphore, product_key, product.brand or settings.DEFAULT_BRAND))

        logger.info(
            f"[Step9] 开始生成 {len(tasks)} 张A+图片，跳过 {skipped_count} 张，"
            f"覆盖策略={settings.APLUS_IMAGE_OVERWRITE_POLICY}, 并发数={settings.APLUS_CONCURRENCY}"
        )
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 汇总结果
        success_count = 0
        for item in image_results:
            if item.get("status") == "done":
                success_count += 1
        for r in results:
            if isinstance(r, Exception):
                image_results.append({"status": "failed", "error": str(r)})
            else:
                image_results.append(r)
                if r.get("status") == "done":
                    success_count += 1

        # 保存到数据库
        image_results.sort(key=lambda item: item.get("position") or 0)
        pa.aplus_images = json.dumps(image_results, ensure_ascii=False)
        pa.aplus_image_count = success_count
        pa.aplus_status = "done" if success_count == min(len(scripts), 5) else "partial"
        pa.generated_at = datetime.now()
        await db.commit()

        logger.info(
            f"[Step9] A+出图完成: {success_count}/{len(scripts)} 成功, "
            f"目录={output_dir}, 耗时={time.monotonic() - step_started:.1f}s"
        )
        expected_count = min(len(scripts), 5)
        if success_count < expected_count:
            errors = [
                f"模块{item.get('position')}: {item.get('error')}"
                for item in image_results
                if item.get("status") != "done"
            ]
            raise RuntimeError(
                f"A+出图未全部成功: {success_count}/{expected_count}. "
                + " | ".join(errors[:5])
            )
        return {
            "total": expected_count,
            "success": success_count,
            "skipped": skipped_count,
            "generated": len(tasks),
            "results": image_results,
            "output_dir": str(output_dir),
        }


async def regenerate_aplus_module_image(product_id: int, module_position: int) -> dict:
    """只重新生成一个 A+ 模块图片，并替换数据库中的对应图片结果。"""
    async with async_session() as db:
        result = await db.execute(
            select(Product)
            .options(
                selectinload(Product.data),
                selectinload(Product.aplus),
            )
            .where(Product.id == product_id)
        )
        product = result.scalar_one_or_none()
        if not product or not product.data:
            raise ValueError(f"Product {product_id} not found or no data")

        pd = product.data
        pa = product.aplus
        if not pa or not pa.aplus_scripts:
            raise ValueError("未找到A+脚本，请先执行Step8")

        try:
            scripts_data = json.loads(pa.aplus_scripts)
        except json.JSONDecodeError:
            raise ValueError("A+脚本数据损坏")

        scripts = scripts_data.get("scripts", [])
        if not isinstance(scripts, list) or not scripts:
            raise ValueError("A+脚本中没有出图模块")

        script = next((item for item in scripts if item.get("module_position") == module_position), None)
        if not script:
            raise ValueError(f"未找到模块 {module_position} 的A+脚本")

        material_dir = Path(pd.material_dir) if pd.material_dir else Path("/tmp/fbm_unknown")
        output_dir = material_dir / "new aplus image"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = _module_output_path(output_dir, module_position)
        product_key = pd.item_code or f"product-{product.id}"

        _backup_existing_module_images(output_dir, module_position)

        result_item = await _generate_single_image(
            script,
            output_path,
            asyncio.Semaphore(1),
            product_key,
            product.brand or settings.DEFAULT_BRAND,
        )

        old_results = list(_existing_result_map(pa).values())

        replaced = False
        new_results = []
        for item in old_results:
            if item.get("position") == module_position:
                new_results.append(result_item)
                replaced = True
            else:
                new_results.append(item)
        if not replaced:
            new_results.append(result_item)
        new_results.sort(key=lambda item: item.get("position") or 0)

        success_count = sum(1 for item in new_results if item.get("status") == "done")
        pa.aplus_images = json.dumps(new_results, ensure_ascii=False)
        pa.aplus_image_count = success_count
        pa.aplus_status = "done" if success_count == len(scripts) else "partial"
        pa.generated_at = datetime.now()
        await db.commit()

        if result_item.get("status") != "done":
            raise RuntimeError(result_item.get("error") or "A+图片重新生成失败")

        logger.info(f"[Step9] A+模块图片重新生成完成: product={product_id}, module={module_position}")
        return result_item
