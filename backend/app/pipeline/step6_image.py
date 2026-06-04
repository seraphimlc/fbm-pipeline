"""
图片分析 — 使用 VLM 分析已确认的商品图片，提取图片卖点和证据

流程：
1. 从已确认的主图/副图读取商品图片
2. 生成 Contact Sheet（缩略图拼接）
3. VLM 分析每张图片的卖点
4. 输出图片卖点、证据缺口和 A+ 参考素材
"""

import base64
import hashlib
import asyncio
import json
import logging
import mimetypes
import math
import re
import shutil
from datetime import datetime
from io import BytesIO
from pathlib import Path
from urllib.parse import unquote, urlparse

import httpx
from PIL import Image, ImageDraw, ImageFont, ImageOps

from app.config import settings
from app.database import async_session
from app.models import Product, ProductData, ProductImage
from sqlalchemy import select
from sqlalchemy.orm import selectinload

logger = logging.getLogger(__name__)

# 支持的图片格式
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tiff"}

# Contact Sheet 参数：压缩到新多模态网关可接受的请求体大小，同时保留标签可读性。
THUMB_SIZE = 420
LABEL_HEIGHT = 52
SHEET_COLS = 3
SHEET_MAX = 6  # 每页最多6张，避免 base64 后请求体过大
SHEET_JPEG_QUALITY = 82
SHEET_MIN_JPEG_QUALITY = 60
SHEET_MAX_BYTES = 550_000

# VLM 系统提示
VLM_SYSTEM_PROMPT = """You are an expert Amazon product image analyst. Analyze every labeled tile in the contact sheet.

Amazon slot 01 MAIN hard rejects:
- Non-white or visibly tinted/scene background unless category rules allow it.
- Text overlays, icons, badges, measurements, logos, watermarks, or promotional claims.
- Props/accessories not included in the offer, unless unambiguously contextual and category-allowed.
- Lifestyle scene, model/hand use, packaging-only photo, collage, multi-panel layout, or comparison graphic.
- Box-label-first images, shipping labels/waybills, raw warehouse snapshots, unretouched casual phone photos, and mailing/outer shipping packaging.
- Wrong variant, wrong quantity, mismatched color, cropped product, blur, low resolution, or unclear product identity.

Supporting images slots 02-09 should answer buyer doubts: exact set/variant, alternate angle, size/scale, material/detail, function/use process, usage scenario, installation/storage/cleaning, package/included parts, or strongest remaining proof.

Use a clear conversion_role for each image. Prefer one of:
exact_set, alternate_angle, size_scale, material_detail, function_use, lifestyle, setup_storage, package_contents, proof, exclude.

When there are not enough distinct image types, still rank every remaining image honestly so the system can fill slots with the best available data up to 9. Avoid box-label-first images, raw casual snapshots, and mailing outer packaging for supporting slots too unless no better product image exists. Mark weak, blurry, wrong-variant, watermarked, duplicate, box-label, casual snapshot, mailing packaging, or risky images clearly in risk_flags and decision_reason instead of omitting them silently.

Do not invent material, certification, capacity, waterproofing, safety, or included accessories unless visible or supported by the product facts. Mark uncertainty.
Output valid JSON only, no markdown fences."""

VLM_ANALYSIS_PROMPT = """Analyze this contact sheet page for Amazon listing gallery selection.

Product: {title}
Brand: {brand}
Category: {category}
Known product facts:
{facts}

Category gallery strategy:
{gallery_strategy}

The contact sheet tiles are labeled with image_id and filename. Analyze every tile on this page.

Output JSON:
{{
  "images": [
    {{
      "image_id": "#01",
      "filename": "source.jpg",
      "multimodal_result": {{
        "visual_summary": "",
        "product_angle": "",
        "product_state": "",
        "color_reading": "",
        "size_scale_cues": "",
        "visible_parts": "",
        "completeness": "",
        "material_texture": "",
        "scene_type": "",
        "background_props": "",
        "text_graphics": "",
        "aplus_reference_value": "",
        "confidence": "high|medium|low",
        "uncertainty": []
      }},
      "image_type": "",
      "visible_selling_point": "",
      "matched_title_bullet_evidence": "",
      "conversion_role": "",
      "risk_flags": [],
      "slot01_score": 0,
      "gallery_score": 0,
      "decision_reason": ""
    }}
  ],
  "overall_assessment": ""
}}"""

DEFAULT_IMAGE_STRATEGY = {
    "name": "general",
    "prompt": (
        "Build a gallery that follows a buyer decision path for this specific product and category: clean product identity, "
        "alternate view, size/scale, material/detail, use/function, lifestyle scene, setup/storage/cleaning, "
        "package or included parts. Treat size/scale and function/use as critical only when the product facts or category make them important. "
        "Do not give several images the same role unless the later image proves a clearly different buyer doubt. "
        "If distinct roles are not available, fill remaining slots with the strongest usable images up to 9."
    ),
    "role_order": [
        "alternate_angle",
        "size_scale",
        "material_detail",
        "function_use",
        "lifestyle",
        "setup_storage",
        "package_contents",
        "proof",
    ],
    "role_limits": {
        "alternate_angle": 1,
        "size_scale": 1,
        "material_detail": 1,
        "function_use": 1,
        "lifestyle": 1,
        "setup_storage": 1,
        "package_contents": 1,
        "proof": 1,
    },
    "role_fill_limits": {
        "alternate_angle": 2,
        "size_scale": 1,
        "material_detail": 2,
        "function_use": 2,
        "lifestyle": 2,
        "setup_storage": 1,
        "package_contents": 1,
        "proof": 2,
    },
    "critical_roles": ["alternate_angle"],
    "high_risk_missing_roles": [],
    "high_risk_claim_roles": ["function_use"],
    "buyer_focus": [
        "确认商品身份、款式、颜色和套装数量是否清楚",
        "优先补齐当前类目最影响购买决策的尺寸、功能、材质或配件证据",
        "避免多张图片承担同一个卖点导致图库信息重复",
    ],
}

IMAGE_STRATEGIES = [
    (
        ("sofas & couches", "sofa", "couch", "sectional", "loveseat"),
        {
            "name": "sofas & couches",
            "prompt": (
                "For sofas, avoid repeating several similar room/lifestyle views. After the MAIN image, prioritize: "
                "one alternate full-product angle, one dimensions/fit image, one fabric/material detail, one strongest room scene, "
                "one modular/function or move-in/setup proof, and package/included-parts proof if available. "
                "Buyer doubts are room fit, comfort, fabric texture, seat depth/scale, configuration, setup, and what arrives. "
                "If there are not enough distinct sofa proofs, fill remaining slots with the best usable alternate/detail/lifestyle images up to 9."
            ),
            "role_order": [
                "alternate_angle",
                "size_scale",
                "material_detail",
                "lifestyle",
                "function_use",
                "setup_storage",
                "package_contents",
                "proof",
            ],
            "role_limits": {
                "alternate_angle": 1,
                "size_scale": 1,
                "material_detail": 1,
                "lifestyle": 1,
                "function_use": 1,
                "setup_storage": 1,
                "package_contents": 1,
                "proof": 1,
            },
            "role_fill_limits": {
                "alternate_angle": 2,
                "size_scale": 1,
                "material_detail": 2,
                "lifestyle": 2,
                "function_use": 2,
                "setup_storage": 1,
                "package_contents": 1,
                "proof": 2,
            },
            "critical_roles": ["alternate_angle", "size_scale", "material_detail"],
            "high_risk_missing_roles": ["size_scale", "material_detail"],
            "high_risk_claim_roles": ["size_scale", "material_detail", "function_use", "setup_storage"],
            "buyer_focus": [
                "房间适配、整体尺寸、座深和比例是否能被图片证明",
                "面料纹理、坐垫厚度、舒适感和做工细节是否清楚",
                "组合方式、搬入安装、包装件数和到货内容是否降低大件购买顾虑",
            ],
        },
    ),
    (
        ("ride on", "ride-on", "powered ride", "electric ride", "kids car", "childrens-powered-ride-ons", "children's powered ride"),
        {
            "name": "ride-on toys",
            "prompt": (
                "For kids ride-on toys, the gallery should prove safety-relevant identity and play value before repeating beauty shots: "
                "alternate full-product angle, child/size scale, dashboard/control features, wheels/seat/belt or stability details, "
                "battery/charging or remote-control proof if supported, outdoor/indoor use scene, and package/included parts. "
                "Do not imply safety certifications, speed, battery capacity, or remote-control features unless visible or supported by facts."
            ),
            "role_order": [
                "alternate_angle",
                "size_scale",
                "function_use",
                "material_detail",
                "lifestyle",
                "package_contents",
                "proof",
            ],
            "role_limits": {
                "alternate_angle": 1,
                "size_scale": 1,
                "function_use": 2,
                "material_detail": 1,
                "lifestyle": 1,
                "package_contents": 1,
                "proof": 1,
            },
            "role_fill_limits": {
                "alternate_angle": 2,
                "size_scale": 1,
                "function_use": 3,
                "material_detail": 2,
                "lifestyle": 2,
                "package_contents": 1,
                "proof": 2,
            },
            "critical_roles": ["alternate_angle", "size_scale", "function_use"],
            "high_risk_missing_roles": ["size_scale", "function_use"],
            "high_risk_claim_roles": ["size_scale", "function_use"],
            "buyer_focus": [
                "适龄/尺寸比例、孩子乘坐空间或承重相关证据是否清楚",
                "驾驶功能、控制台、轮胎、座椅/安全带、电池或遥控等核心卖点是否有图",
                "不要把未被图片或商品事实支持的安全认证、速度、电池容量写成确定卖点",
            ],
        },
    ),
    (
        ("flashlight", "torch", "lantern", "headlamp", "work light"),
        {
            "name": "lighting",
            "prompt": (
                "For lighting products, the gallery should prove beam/use before repeating product angles: alternate view, "
                "brightness or beam distance, battery/charging, durability/weather proof if supported, night/emergency scene, "
                "size-in-hand or package contents."
            ),
            "role_order": [
                "alternate_angle",
                "function_use",
                "size_scale",
                "material_detail",
                "lifestyle",
                "package_contents",
                "proof",
            ],
            "role_limits": {
                "alternate_angle": 1,
                "function_use": 2,
                "size_scale": 1,
                "material_detail": 1,
                "lifestyle": 1,
                "package_contents": 1,
                "proof": 1,
            },
            "role_fill_limits": {
                "alternate_angle": 2,
                "function_use": 3,
                "size_scale": 1,
                "material_detail": 2,
                "lifestyle": 2,
                "package_contents": 1,
                "proof": 2,
            },
            "critical_roles": ["alternate_angle", "function_use"],
            "high_risk_missing_roles": ["function_use"],
            "high_risk_claim_roles": ["function_use"],
            "buyer_focus": [
                "亮度、光束范围、夜间/应急使用效果是否有图片证据",
                "电池、充电方式、防水防摔等承诺必须有可见证据或商品事实支持",
                "尺寸握持、开关/接口、包装配件是否降低购买疑问",
            ],
        },
    ),
]

ROLE_LABELS = {
    "identity": "主图/商品识别",
    "alternate_angle": "全貌/角度",
    "size_scale": "尺寸/比例",
    "material_detail": "材质/细节",
    "function_use": "功能/卖点",
    "lifestyle": "场景代入",
    "setup_storage": "安装/收纳/清洁",
    "package_contents": "包装/配件",
    "proof": "补充证明",
}

ROLE_BUYER_QUESTIONS = {
    "identity": "这是不是我要的产品？",
    "alternate_angle": "商品全貌和实际款式是什么样？",
    "size_scale": "尺寸、比例、空间适配是否合适？",
    "material_detail": "材质、纹理、做工是否可信？",
    "function_use": "核心功能或结构卖点是否真实？",
    "lifestyle": "放到真实场景里是否好看、适合？",
    "setup_storage": "安装、搬入、收纳或清洁是否麻烦？",
    "package_contents": "到货包含什么、包装是什么样？",
    "proof": "还有哪些补充证据能降低顾虑？",
}

IMAGE_HEALTH_LABELS = {
    "pass": "素材够用",
    "warning": "建议补素材",
    "high_risk": "高风险，最终确认需重点看",
    "review_recommended": "建议人工确认",
}


def _scan_images(material_dir: str) -> list[Path]:
    """扫描素材目录中的所有图片"""
    dir_path = Path(material_dir)
    if not dir_path.exists():
        return []
    
    images = []
    for ext in IMAGE_EXTENSIONS:
        images.extend(dir_path.rglob(f"*{ext}"))
        images.extend(dir_path.rglob(f"*{ext.upper()}"))
    
    # 排序：优先原图，排除 new main image / new aplus image 子目录
    result = []
    for img in sorted(images):
        name = img.name.lower()
        path_text = str(img).lower()
        if "new " not in path_text and "image analysis" not in path_text and name != "contact_sheet.jpg":
            result.append(img)
    return result


def _json_loads(value, fallback):
    if not value:
        return fallback
    try:
        return json.loads(value)
    except Exception:
        return fallback


def _is_remote_url(value: str | None) -> bool:
    return bool(value and re.match(r"^https?://", str(value).strip(), flags=re.I))


def _image_ext_from_url(url: str, content_type: str | None = None) -> str:
    suffix = Path(unquote(urlparse(url).path)).suffix.lower()
    if suffix in IMAGE_EXTENSIONS:
        return suffix
    guessed = mimetypes.guess_extension((content_type or "").split(";")[0].strip())
    if guessed and guessed.lower() in IMAGE_EXTENSIONS:
        return guessed.lower()
    return ".jpg"


async def _download_remote_image(url: str, target_dir: Path) -> str:
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


def _source_filename(value: str, index: int) -> str:
    if _is_remote_url(value):
        name = Path(unquote(urlparse(value).path)).name
    else:
        name = Path(value).expanduser().name
    return name or f"source_image_{index:02d}.jpg"


def _selected_image_sources(pi: ProductImage) -> list[str]:
    gallery_paths = _json_loads(pi.gallery_images, [])
    if not isinstance(gallery_paths, list):
        gallery_paths = []
    selected_paths = [pi.main_image_path, *gallery_paths]
    unique: list[str] = []
    seen: set[str] = set()
    for path in selected_paths:
        text = str(path or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        unique.append(text)
    return unique


def _image_source_records(sources: list[str]) -> list[dict]:
    return [
        {
            "image_id": f"#{idx:02d}",
            "filename": _source_filename(source, idx),
            "path": source,
            "source_type": "url" if _is_remote_url(source) else "file",
        }
        for idx, source in enumerate(sources, 1)
    ]


def _image_source_fingerprint(records: list[dict]) -> list[dict]:
    fingerprint: list[dict] = []
    for record in records:
        path = str(record.get("path") or "")
        if _is_remote_url(path):
            fingerprint.append({
                "path": path,
                "source_type": "url",
            })
            continue
        local = Path(path).expanduser()
        if not local.is_file():
            fingerprint.append({
                "path": path,
                "source_type": "missing_file",
            })
            continue
        stat = local.stat()
        fingerprint.append({
            "path": str(local),
            "source_type": "file",
            "size": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
        })
    return fingerprint


async def _prepare_confirmed_image_sources(pd: ProductData, pi: ProductImage) -> tuple[Path, list[dict]]:
    material_dir = Path(pd.material_dir or settings.PRODUCT_BASE_DIR / "PRODUCT" / str(pd.product_id)).expanduser()
    material_dir.mkdir(parents=True, exist_ok=True)
    pd.material_dir = str(material_dir)

    sources = _selected_image_sources(pi)
    if sources:
        pi.main_image_path = sources[0]
        pi.main_image_source = pi.main_image_source or "manual_selected"
        pi.gallery_images = json.dumps(sources[1:], ensure_ascii=False)
    return material_dir, _image_source_records(sources)


async def _download_image_records(records: list[dict], target_dir: Path) -> list[dict]:
    downloaded: list[dict] = []
    for record in records:
        source = str(record.get("path") or "").strip()
        if not source:
            continue
        path = await _download_remote_image(source, target_dir) if _is_remote_url(source) else source
        local = Path(path).expanduser()
        if not local.is_file():
            continue
        downloaded.append({
            **record,
            "path": str(local),
            "source_url": source if _is_remote_url(source) else record.get("source_url"),
            "source_type": "file",
            "filename": local.name,
        })
    return downloaded


def _image_fingerprint(images: list[Path]) -> list[dict]:
    fingerprint = []
    for path in images:
        stat = path.stat()
        fingerprint.append({
            "path": str(path),
            "size": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
        })
    return fingerprint


def _load_cached_image_analysis(
    material_dir: Path,
    images: list[Path] | None = None,
    *,
    source_fingerprint: list[dict] | None = None,
) -> dict | None:
    analysis_path = material_dir / "image analysis" / "image_selling_points.json"
    if not analysis_path.is_file():
        return None
    try:
        payload = json.loads(analysis_path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning(f"[Step6] 图片分析缓存读取失败，将重新分析: {analysis_path}, error={exc}")
        return None
    if not isinstance(payload, dict):
        return None

    reviews = payload.get("image_reviews") or payload.get("images")
    gallery = payload.get("gallery_selection")
    if not isinstance(reviews, list) or not isinstance(gallery, list) or not reviews:
        return None

    images = images or []
    current_fingerprint = source_fingerprint or _image_fingerprint(images)
    cached_fingerprint = payload.get("source_images")
    if isinstance(cached_fingerprint, list):
        if cached_fingerprint == current_fingerprint:
            payload["source_images"] = current_fingerprint
            return payload
        return None

    if not images:
        return None
    newest_source_mtime = max((path.stat().st_mtime for path in images), default=0)
    if analysis_path.stat().st_mtime >= newest_source_mtime:
        payload["source_images"] = current_fingerprint
        return payload
    return None


def _load_font(size: int):
    for name in ["Arial.ttf", "Helvetica.ttc", "DejaVuSans.ttf"]:
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            pass
    return ImageFont.load_default()


def _image_records(images: list[Path]) -> list[dict]:
    return [
        {
            "image_id": f"#{idx:02d}",
            "filename": path.name,
            "path": str(path),
        }
        for idx, path in enumerate(images, 1)
    ]


def _build_contact_sheets(image_records: list[dict], output_dir: Path, product_key: str) -> list[dict]:
    """生成所有 Contact Sheet，并把每张图与 sheet/page/label 建立映射。"""
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
            except Exception as e:
                logger.warning(f"无法处理图片 {record['path']}: {e}")
                draw.text((x + 20, y + 20), f"OPEN FAILED: {e}", font=small_font, fill="red")

            label = f"{record['image_id']}  {record['filename']}"
            draw.rectangle((x, y + THUMB_SIZE, x + tile_w, y + tile_h), fill=(246, 246, 246))
            draw.text((x + 12, y + THUMB_SIZE + 10), label[:90], font=label_font, fill=(20, 20, 20))
            record["contact_sheet_evidence"] = {
                "sheet_path": str(sheet_path),
                "sheet_page": page,
                "sheet_label": record["image_id"],
            }

        _save_contact_sheet(sheet, sheet_path)
        sheets.append({
            "sheet_page": page,
            "sheet_path": str(sheet_path),
            "image_ids": [record["image_id"] for record in batch],
        })

    return sheets


def _build_image_url_batches(image_records: list[dict]) -> list[dict]:
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


def _save_contact_sheet(sheet: Image.Image, sheet_path: Path) -> None:
    """保存 Contact Sheet，并在必要时降低质量/尺寸以避开网关请求体限制。"""
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
            logger.warning(
                f"Contact Sheet 仍超过目标大小: {sheet_path.name}, bytes={size}, "
                f"target={SHEET_MAX_BYTES}"
            )
            sheet_path.write_bytes(buffer.getvalue())
            return
        current = current.resize(next_size, Image.Resampling.LANCZOS)


def _image_data_url(image_path: Path) -> str:
    """OpenAI-compatible 多模态接口对 JPG 示例使用 image/jpg。"""
    suffix = image_path.suffix.lower()
    mime = {
        ".jpg": "image/jpg",
        ".jpeg": "image/jpg",
        ".png": "image/png",
        ".webp": "image/webp",
    }.get(suffix, "image/jpg")
    img_b64 = base64.b64encode(image_path.read_bytes()).decode()
    return f"data:{mime};base64,{img_b64}"


def _facts_from_product(pd: ProductData) -> str:
    facts = {
        "color": pd.color,
        "material": pd.material,
        "filler": pd.filler,
        "product_type": pd.product_type,
        "dimensions_in": [pd.dimension_length, pd.dimension_width, pd.dimension_height],
        "weight_lbs": pd.weight,
        "features": None,
        "description": pd.description,
    }
    if pd.features:
        try:
            facts["features"] = json.loads(pd.features)
        except Exception:
            facts["features"] = pd.features
    return json.dumps(facts, ensure_ascii=False)


def _clean_json_content(content: str) -> str:
    content_clean = content.strip()
    if content_clean.startswith("```"):
        content_clean = content_clean.split("\n", 1)[1] if "\n" in content_clean else content_clean[3:]
    if content_clean.endswith("```"):
        content_clean = content_clean[:-3]
    return content_clean.strip()


def _normalize_sheet_reviews(analysis: dict, batch_records: list[dict], sheet_record: dict) -> list[dict]:
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


def _is_data_inspection_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return (
        "data_inspection_failed" in text
        or "datainspectionfailed" in text
        or "input image data may contain inappropriate content" in text
    )


def _is_transient_vlm_error(exc: Exception) -> bool:
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


async def _analyze_contact_sheet(client, image_analysis_model: str, sheet: dict, batch_records: list[dict], prompt: str) -> tuple[dict, list[dict]]:
    sheet_path = Path(sheet["sheet_path"])
    image_url = _image_data_url(sheet_path)

    logger.info(
        f"[Step6] 调用VLM分析图片: model={image_analysis_model}, "
        f"provider={'LLM_API' if settings.VLM_USE_LLM_API else 'VLM_API'}, "
        f"sheet={sheet_path.name}, page={sheet['sheet_page']}, "
        f"images={len(batch_records)}, bytes={sheet_path.stat().st_size}"
    )
    request_client = client.with_options(timeout=45, max_retries=0) if hasattr(client, "with_options") else client
    max_attempts = 2 if len(batch_records) > 1 else 3
    response = None
    for attempt in range(1, max_attempts + 1):
        try:
            response = await request_client.chat.completions.create(
                model=image_analysis_model,
                messages=[
                    {"role": "system", "content": VLM_SYSTEM_PROMPT},
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
            )
            break
        except Exception as exc:
            if _is_data_inspection_error(exc) or not _is_transient_vlm_error(exc) or attempt >= max_attempts:
                raise
            wait_seconds = attempt * 5
            logger.warning(
                "[Step6] VLM图片分析连接异常，准备重试: sheet=%s, attempt=%s/%s, wait=%ss, error=%s: %s",
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
        sheet_analysis = json.loads(_clean_json_content(content))
    except json.JSONDecodeError as e:
        logger.warning(f"VLM JSON解析失败，保存原始内容: {e}")
        sheet_analysis = {"raw": content, "images": []}

    reviews = _normalize_sheet_reviews(sheet_analysis, batch_records, sheet)
    return sheet_analysis, reviews


def _image_url_batch_descriptor(batch_records: list[dict]) -> str:
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


async def _analyze_image_url_batch(client, image_analysis_model: str, batch: dict, batch_records: list[dict], prompt: str) -> tuple[dict, list[dict]]:
    logger.info(
        f"[Step6] 调用VLM分析图片URL: model={image_analysis_model}, "
        f"provider={'LLM_API' if settings.VLM_USE_LLM_API else 'VLM_API'}, "
        f"batch={batch['sheet_page']}, images={len(batch_records)}"
    )
    content: list[dict] = []
    for record in batch_records:
        source = str(record.get("path") or "")
        image_url = source if _is_remote_url(source) else _image_data_url(Path(source).expanduser())
        content.append({"type": "image_url", "image_url": {"url": image_url}})
    content.append({
        "type": "text",
        "text": (
            prompt.replace("Analyze this contact sheet page", "Analyze these product images")
            + "\n\n"
            + _image_url_batch_descriptor(batch_records)
            + "\n\nThere is no contact sheet. Each attached image corresponds to the list above."
        ),
    })

    request_client = client.with_options(timeout=60, max_retries=0) if hasattr(client, "with_options") else client
    max_attempts = 2 if len(batch_records) > 1 else 3
    response = None
    for attempt in range(1, max_attempts + 1):
        try:
            response = await request_client.chat.completions.create(
                model=image_analysis_model,
                messages=[
                    {"role": "system", "content": VLM_SYSTEM_PROMPT},
                    {"role": "user", "content": content},
                ],
                max_tokens=4000,
                temperature=0.2,
            )
            break
        except Exception as exc:
            if _is_data_inspection_error(exc) or not _is_transient_vlm_error(exc) or attempt >= max_attempts:
                raise
            wait_seconds = attempt * 5
            logger.warning(
                "[Step6] VLM图片URL分析连接异常，准备重试: batch=%s, attempt=%s/%s, wait=%ss, error=%s: %s",
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
        batch_analysis = json.loads(_clean_json_content(response_content))
    except json.JSONDecodeError as exc:
        logger.warning(f"VLM URL JSON解析失败，保存原始内容: {exc}")
        batch_analysis = {"raw": response_content, "images": []}

    reviews = _normalize_sheet_reviews(batch_analysis, batch_records, batch)
    return batch_analysis, reviews


def _score(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _ensure_list(value) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _image_strategy(category: str, pd: ProductData) -> dict:
    haystack = " ".join([
        category or "",
        pd.leaf_category or "",
        pd.product_type or "",
        pd.title or "",
        pd.description or "",
    ]).lower()
    for keywords, strategy in IMAGE_STRATEGIES:
        if any(keyword in haystack for keyword in keywords):
            return strategy
    return DEFAULT_IMAGE_STRATEGY


def _gallery_strategy_prompt(strategy: dict) -> str:
    focus_lines = "\n".join(f"- {item}" for item in (strategy.get("buyer_focus") or []))
    return (
        f"{strategy.get('prompt', '')}\n"
        f"Preferred role order: {', '.join(strategy.get('role_order') or [])}.\n"
        f"Category-specific buyer focus:\n{focus_lines or '- Use the product facts to decide which visual doubts matter most.'}\n"
        f"Roles that become high-risk if missing for this category: {', '.join(strategy.get('high_risk_missing_roles') or []) or 'none'}.\n"
        "Use conversion_role consistently so selection can avoid repeated image types."
    )


def _image_text(item: dict) -> str:
    mm = item.get("multimodal_result") or {}
    parts = [
        item.get("filename"),
        item.get("image_type"),
        item.get("visible_selling_point"),
        item.get("matched_title_bullet_evidence"),
        item.get("conversion_role"),
        item.get("decision_reason"),
    ]
    if isinstance(mm, dict):
        parts.extend([
            mm.get("visual_summary"),
            mm.get("product_angle"),
            mm.get("product_state"),
            mm.get("size_scale_cues"),
            mm.get("visible_parts"),
            mm.get("material_texture"),
            mm.get("scene_type"),
            mm.get("background_props"),
            mm.get("text_graphics"),
            mm.get("aplus_reference_value"),
        ])
    parts.extend(item.get("risk_flags") or [])
    return " ".join(str(part or "") for part in parts).lower()


def _has_any_marker(text: str, markers: tuple[str, ...]) -> bool:
    return any(marker in text for marker in markers)


BOX_LABEL_MARKERS = (
    "box label", "carton label", "package label", "packaging label", "label on box",
    "label on carton", "barcode label", "warehouse label", "sku label", "shipping label",
    "waybill", "tracking label", "sticker label", "sticker on box", "sticker on carton",
    "箱标", "纸箱标签", "外箱标签", "条码标签", "物流标签", "快递面单", "面单",
)

CASUAL_RAW_PHOTO_MARKERS = (
    "casual photo", "casual snapshot", "snapshot", "random shot", "quick photo",
    "raw photo", "unretouched", "un-retouched", "unprocessed", "unpolished",
    "unstyled", "no editing", "no retouch", "poor lighting", "harsh lighting",
    "cluttered background", "messy background", "warehouse floor", "warehouse photo",
    "phone photo", "amateur photo", "随手拍", "实拍随手", "未修图", "未修饰",
    "无修饰", "杂乱背景", "仓库地面", "手机拍摄",
)

MAILING_PACKAGING_MARKERS = (
    "shipping carton", "shipping box", "mailing box", "mailing package", "outer carton",
    "outer packaging", "delivery box", "delivery package", "postal package", "parcel",
    "poly mailer", "shipping bag", "corrugated shipping", "logistics packaging",
    "transport packaging", "快递外包装", "邮寄外包装", "物流外包装", "运输外包装",
    "发货纸箱", "快递箱", "包裹外包装",
)


def _discouraged_image_reasons(item: dict) -> list[str]:
    text = _image_text(item)
    reasons = []
    if _has_any_marker(text, BOX_LABEL_MARKERS):
        reasons.append("box_label")
    if _has_any_marker(text, CASUAL_RAW_PHOTO_MARKERS):
        reasons.append("casual_raw_photo")
    if _has_any_marker(text, MAILING_PACKAGING_MARKERS):
        reasons.append("mailing_packaging")
    return reasons


def _discouraged_image_penalty(item: dict, *, for_main: bool) -> float:
    penalties = {
        "box_label": 7.0 if for_main else 4.0,
        "casual_raw_photo": 5.0 if for_main else 2.0,
        "mailing_packaging": 8.0 if for_main else 5.0,
    }
    return sum(penalties.get(reason, 0.0) for reason in _discouraged_image_reasons(item))


def _token_set(text: str) -> set[str]:
    stop_words = {
        "the", "and", "for", "with", "this", "that", "from", "image", "product",
        "show", "shows", "view", "photo", "picture", "scene", "style", "shot",
    }
    return {
        token
        for token in re.findall(r"[a-z0-9]+", text.lower())
        if len(token) > 2 and token not in stop_words
    }


def _text_similarity(left: str, right: str) -> float:
    left_tokens = _token_set(left)
    right_tokens = _token_set(right)
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def _angle_marker(text: str) -> str:
    for marker in ("front", "side", "back", "top", "profile", "close up", "close-up"):
        if marker in text:
            return marker.replace(" ", "_").replace("-", "_")
    return ""


def _selection_role(item: dict) -> str:
    text = _image_text(item)
    role = str(item.get("conversion_role") or "").lower().replace("-", "_").replace(" ", "_")
    if "exclude" in role:
        return "exclude"
    if any(word in role for word in ("dimension", "measurement", "size", "scale", "fit")):
        return "size_scale"
    if any(word in role for word in ("material", "fabric", "texture", "detail", "close")):
        return "material_detail"
    if any(word in role for word in ("assembly", "install", "setup", "storage", "clean")):
        return "setup_storage"
    if any(word in role for word in ("package", "included", "parts", "accessor")):
        return "package_contents"
    if any(word in role for word in ("lifestyle", "scene", "context", "room", "home")):
        return "lifestyle"
    if any(word in role for word in ("function", "use", "modular", "configuration", "comfort", "beam", "charging", "battery")):
        return "function_use"
    if any(word in role for word in ("alternate", "angle", "front", "side", "back", "product", "identity", "exact_set", "variant")):
        return "alternate_angle"
    if any(word in role for word in ("proof", "infographic", "comparison", "feature")):
        return "proof"
    if any(word in text for word in ("dimension", "dimensions", "measurement", "measurements", "size", "scale", "height", "width", "depth")):
        return "size_scale"
    if any(word in text for word in ("fabric", "material", "texture", "close-up", "close up", "detail", "stitch", "foam", "surface")):
        return "material_detail"
    if any(word in text for word in ("assembly", "install", "setup", "storage", "cleaning", "washable", "move-in", "move in")):
        return "setup_storage"
    if any(word in text for word in ("package", "packaging", "included", "parts", "accessories", "box")):
        return "package_contents"
    if any(word in text for word in ("lifestyle", "scene", "room", "home", "living", "use case", "model", "person", "human", "family")):
        return "lifestyle"
    if any(word in text for word in ("function", "use process", "modular", "configuration", "convert", "fold", "adjust", "recline", "beam", "charging", "battery")):
        return "function_use"
    if any(word in text for word in ("infographic", "proof", "comparison", "benefit", "feature education", "claim")):
        return "proof"
    if any(word in text for word in ("alternate", "angle", "front", "side", "back", "profile", "product shot", "exact set", "variant", "full assembly")):
        return "alternate_angle"
    return "proof"


def _main_candidate_score(item: dict) -> float:
    score = _score(item.get("slot01_score"))
    text = _image_text(item)
    reject_words = (
        "text overlay", "badge", "measurement", "watermark", "logo", "lifestyle",
        "scene", "model", "hand", "packaging", "collage", "comparison", "wrong",
        "cropped", "blur", "non-white",
    )
    if any(word in text for word in reject_words):
        score -= 4
    score -= _discouraged_image_penalty(item, for_main=True)
    return score


def _main_reject_reasons(item: dict) -> list[str]:
    text = _image_text(item)
    checks = [
        ("non_white_background", ("non-white", "tinted background", "scene background", "colored background")),
        ("text_or_graphics", ("text overlay", "badge", "measurement", "watermark", "logo", "icons", "infographic")),
        ("lifestyle_or_model", ("lifestyle", "scene", "model", "hand", "person", "human", "room")),
        ("props_or_packaging", ("props", "accessories not included", "packaging", "package-only", "box only")),
        ("box_label", BOX_LABEL_MARKERS),
        ("casual_raw_photo", CASUAL_RAW_PHOTO_MARKERS),
        ("mailing_packaging", MAILING_PACKAGING_MARKERS),
        ("wrong_variant", ("wrong variant", "wrong color", "mismatched", "different product")),
        ("quality_or_crop", ("cropped", "blur", "blurry", "low resolution", "unclear product")),
        ("collage_or_comparison", ("collage", "multi-panel", "comparison")),
    ]
    reasons = []
    for reason, words in checks:
        if any(word in text for word in words):
            reasons.append(reason)
    return reasons


def _is_compliant_main_candidate(item: dict) -> bool:
    return _score(item.get("slot01_score")) >= 7 and not _main_reject_reasons(item)


def _substitute_main_score(item: dict) -> float:
    score = _main_candidate_score(item)
    reasons = set(_main_reject_reasons(item))

    # Identity-breaking issues are worse than presentation issues when we must keep moving.
    for reason in reasons:
        if reason in {"wrong_variant", "quality_or_crop"}:
            score -= 6
        elif reason in {"box_label", "mailing_packaging"}:
            score -= 7
        elif reason == "casual_raw_photo":
            score -= 4
        elif reason in {"text_or_graphics", "collage_or_comparison"}:
            score -= 3
        elif reason in {"non_white_background", "lifestyle_or_model", "props_or_packaging"}:
            score -= 1.5

    role = _selection_role(item)
    if role in {"alternate_angle", "exact_set"}:
        score += 2
    elif role in {"lifestyle", "function_use"}:
        score -= 1
    return score


def _select_main_image(reviews: list[dict]) -> tuple[dict | None, dict]:
    if not reviews:
        return None, {
            "main_image_status": "missing",
            "main_image_source": None,
            "main_image_warnings": ["素材中没有可分析图片。"],
        }

    compliant = [item for item in reviews if _is_compliant_main_candidate(item)]
    if compliant:
        main = sorted(compliant, key=_main_candidate_score, reverse=True)[0]
        return {**main, "main_selection_status": "compliant"}, {
            "main_image_status": "compliant",
            "main_image_source": "vlm_selected",
            "main_image_warnings": [],
        }

    ranked = sorted(reviews, key=_substitute_main_score, reverse=True)
    main = ranked[0]
    reasons = _main_reject_reasons(main)
    warnings = [
        "没有找到完全符合主图规则的图片，已用现有素材中风险最低的一张替代。",
    ]
    if reasons:
        warnings.append("替代主图风险: " + ", ".join(reasons))
    fallback = {
        **main,
        "main_selection_status": "fallback_substitute",
        "selection_warnings": warnings,
        "fallback_reasons": reasons,
    }
    return fallback, {
        "main_image_status": "fallback_substitute",
        "main_image_source": "fallback_substitute",
        "main_image_warnings": warnings,
        "fallback_image_id": main.get("image_id"),
        "fallback_filename": main.get("filename"),
    }


def _role_candidate_score(item: dict, role: str) -> float:
    score = _score(item.get("gallery_score"))
    text = _image_text(item)
    score -= _discouraged_image_penalty(item, for_main=False)
    if role == "size_scale":
        if any(word in text for word in ("dimension", "dimensions", "measurement", "measurements", "width", "height", "depth", "exact dimensions", "fit")):
            score += 2
        if any(word in text for word in ("human", "person", "model", "scale reference")):
            score += 0.5
    elif role == "material_detail":
        if any(word in text for word in ("fabric", "material", "texture", "close-up", "close up", "surface")):
            score += 1.5
    elif role == "lifestyle":
        if any(word in text for word in ("lifestyle", "room", "home", "living room", "contextual")):
            score += 1
    elif role == "alternate_angle":
        if any(word in text for word in ("product shot", "front", "side", "back", "full assembly", "exact set")):
            score += 1
        if any(word in text for word in ("lifestyle", "scene", "room")):
            score -= 1
    elif role == "package_contents":
        if any(word in text for word in ("package", "included", "parts", "box")):
            score += 1.5
        if _has_any_marker(text, MAILING_PACKAGING_MARKERS) or _has_any_marker(text, BOX_LABEL_MARKERS):
            score -= 4
    return score


def _is_usable_gallery_item(item: dict) -> bool:
    role = _selection_role(item)
    if role == "exclude":
        return False
    text = _image_text(item)
    hard_rejects = (
        "wrong variant",
        "wrong color",
        "mismatched",
        "blur",
        "blurry",
        "cropped product",
        "unclear product",
        "watermark",
        "logo",
    )
    if any(flag in text for flag in hard_rejects):
        return False
    discouraged = set(_discouraged_image_reasons(item))
    if discouraged & {"box_label", "mailing_packaging"}:
        return False
    return _score(item.get("gallery_score")) >= 5


def _gallery_fallback_score(item: dict) -> float:
    score = _score(item.get("gallery_score"))
    text = _image_text(item)
    role = _selection_role(item)
    if role == "exclude":
        score -= 6
    penalties = {
        "wrong variant": 8,
        "wrong color": 8,
        "mismatched": 8,
        "unclear product": 6,
        "blur": 5,
        "blurry": 5,
        "cropped product": 4,
        "watermark": 4,
        "logo": 4,
        "low resolution": 3,
    }
    for marker, penalty in penalties.items():
        if marker in text:
            score -= penalty
    score -= _discouraged_image_penalty(item, for_main=False)
    if any(word in text for word in ("product shot", "front", "side", "back", "detail", "dimension", "lifestyle", "room")):
        score += 1
    return score


def _duplicate_reason(item: dict, selected_items: list[dict]) -> str | None:
    role = _selection_role(item)
    text = _image_text(item)
    angle = _angle_marker(text)
    for selected in selected_items:
        selected_role = selected.get("selection_role") or _selection_role(selected)
        if selected_role != role:
            continue
        selected_text = _image_text(selected)
        selected_angle = _angle_marker(selected_text)
        similarity = _text_similarity(text, selected_text)
        if angle and selected_angle and angle == selected_angle:
            return f"与已选 {selected.get('image_id')} 同角色同角度"
        if similarity >= 0.68:
            return f"与已选 {selected.get('image_id')} 同角色内容相似"
        if role == "lifestyle" and similarity >= 0.48:
            return f"与已选 {selected.get('image_id')} 场景信息重复"
    return None


def _gallery_role_entry(item: dict) -> dict:
    role = item.get("selection_role") or _selection_role(item)
    return {
        "slot": item.get("slot"),
        "image_id": item.get("image_id"),
        "filename": item.get("filename"),
        "role": role,
        "role_label": ROLE_LABELS.get(role, role),
        "buyer_question": ROLE_BUYER_QUESTIONS.get(role, ""),
        "reason": item.get("decision_reason") or item.get("visible_selling_point") or "",
        "is_duplicate_backfill": bool(item.get("duplicate_backfill")),
        "duplicate_reason": item.get("duplicate_reason"),
    }


def _dedupe_diagnostic_items(items: list[dict]) -> list[dict]:
    seen = set()
    result = []
    for item in items:
        key = (item.get("image_id"), item.get("role"), item.get("reason"))
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _missing_gallery_roles(gallery: list[dict], strategy: dict) -> list[dict]:
    present = {item.get("selection_role") or _selection_role(item) for item in gallery}
    missing = []
    for role in strategy.get("role_order") or []:
        if role not in present:
            missing.append({
                "role": role,
                "role_label": ROLE_LABELS.get(role, role),
                "buyer_question": ROLE_BUYER_QUESTIONS.get(role, ""),
            })
    return missing


def _json_loads(value, fallback):
    if not value:
        return fallback
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except Exception:
        return fallback


def _listing_alignment_text(pd: ProductData) -> str:
    bullets = _json_loads(pd.listing_bullets, [])
    check = _json_loads(pd.listing_check, {})
    keyword_plan = check.get("keyword_plan") if isinstance(check, dict) else {}
    positioning = check.get("positioning") if isinstance(check, dict) else {}
    parts = [
        pd.listing_title,
        " ".join(bullets) if isinstance(bullets, list) else bullets,
        pd.listing_primary_keyword,
    ]
    if isinstance(keyword_plan, dict):
        parts.extend(keyword_plan.get("title_keywords") or [])
        parts.extend(keyword_plan.get("bullet_keywords") or [])
    if isinstance(positioning, dict):
        parts.append(positioning.get("main_click_reason"))
        risks = positioning.get("conversion_risks") or []
        if isinstance(risks, list):
            parts.extend(risks)
    return " ".join(str(part or "") for part in parts).lower()


def _claim_terms_for_product(pd: ProductData) -> list[tuple[str, str, list[str]]]:
    text = " ".join(str(part or "").lower() for part in (
        pd.title,
        pd.product_type,
        pd.leaf_category,
        pd.description,
    ))
    is_ride_on = any(
        marker in text
        for marker in ("ride on", "ride-on", "powered ride", "kids car", "electric ride", "toy car")
    )
    is_lighting = any(
        marker in text
        for marker in ("flashlight", "torch", "lantern", "headlamp", "work light")
    )

    material_terms = [
        "fabric", "chenille", "linen", "velvet", "leather", "faux leather",
        "wood", "metal", "steel", "texture", "upholstery", "foam", "cushion",
    ]
    if pd.material:
        material_terms.extend(part.strip().lower() for part in re.split(r"[,;/|]+", pd.material) if len(part.strip()) > 2)
    if pd.filler:
        material_terms.extend(part.strip().lower() for part in re.split(r"[,;/|]+", pd.filler) if len(part.strip()) > 2)
    size_terms = [
        "small space", "apartment", "compact", "dimension", "dimensions", "inch",
        "inches", "width", "depth", "height", "seat depth", "scale", "fit",
        "spacious", "roomy",
    ]
    function_terms = [
        "reversible", "modular", "chaise", "sleeper", "storage", "recliner",
        "reclining", "adjustable", "convert", "convertible", "fold", "extendable",
        "cup holder", "usb", "charging", "ottoman",
    ]
    lifestyle_terms = [
        "living room", "bedroom", "office", "dorm", "studio", "patio", "home",
        "family", "lounge",
    ]
    if is_ride_on:
        size_terms.extend(["age", "ages", "kids", "children", "child", "toddler", "weight capacity", "capacity"])
        function_terms.extend([
            "remote", "remote control", "battery", "charging", "music", "lights", "horn",
            "dashboard", "seat belt", "suspension", "speed", "wheel", "wheels", "ride",
        ])
        material_terms.extend(["plastic", "pp", "wheels", "seat", "belt"])
        lifestyle_terms.extend(["outdoor", "driveway", "yard", "play", "ride"])
    if is_lighting:
        size_terms.extend(["pocket", "handheld", "compact", "portable", "lightweight"])
        function_terms.extend([
            "beam", "brightness", "lumen", "lumens", "rechargeable", "battery", "usb",
            "waterproof", "weatherproof", "mode", "modes", "emergency", "magnetic",
        ])
        material_terms.extend(["aluminum", "abs", "rubber", "impact", "durable"])
        lifestyle_terms.extend(["camping", "garage", "emergency", "night", "outdoor"])

    return [
        ("size_scale", "尺寸/空间适配", [
            *size_terms,
        ]),
        ("material_detail", "材质/细节", list(dict.fromkeys(material_terms))),
        ("function_use", "功能/结构卖点", list(dict.fromkeys(function_terms))),
        ("setup_storage", "安装/清洁/维护", [
            "assembly", "assemble", "install", "setup", "tool-free", "tool free",
            "easy to clean", "washable", "removable", "cleaning", "maintenance",
        ]),
        ("package_contents", "包装/配件/到货内容", [
            "package", "packages", "box", "boxes", "included", "includes", "parts",
            "hardware", "accessories",
        ]),
        ("lifestyle", "使用场景", list(dict.fromkeys(lifestyle_terms))),
    ]


def _listing_claims(pd: ProductData) -> list[dict]:
    listing_text = _listing_alignment_text(pd)
    claims = []
    for role, label, terms in _claim_terms_for_product(pd):
        matched = [term for term in terms if term and term in listing_text]
        if matched:
            claims.append({
                "role": role,
                "role_label": ROLE_LABELS.get(role, role),
                "claim_label": label,
                "matched_terms": list(dict.fromkeys(matched))[:8],
            })
    return claims


def _listing_image_alignment(pd: ProductData, gallery: list[dict]) -> dict:
    claims = _listing_claims(pd)
    role_to_items: dict[str, list[dict]] = {}
    for item in gallery:
        role = item.get("selection_role") or _selection_role(item)
        role_to_items.setdefault(role, []).append(item)

    evidence_aliases = {
        "size_scale": {"size_scale"},
        "material_detail": {"material_detail"},
        "function_use": {"function_use", "setup_storage"},
        "setup_storage": {"setup_storage", "package_contents"},
        "package_contents": {"package_contents"},
        "lifestyle": {"lifestyle"},
    }
    supported = []
    missing = []
    for claim in claims:
        allowed_roles = evidence_aliases.get(claim["role"], {claim["role"]})
        evidence_items = [
            item
            for role in allowed_roles
            for item in role_to_items.get(role, [])
            if item.get("slot") != "01"
        ]
        if evidence_items:
            supported.append({
                **claim,
                "evidence": [
                    {
                        "slot": item.get("slot"),
                        "image_id": item.get("image_id"),
                        "filename": item.get("filename"),
                    }
                    for item in evidence_items[:3]
                ],
            })
        else:
            missing.append({
                **claim,
                "message": f"Listing 提到{claim['claim_label']}，但副图中缺少对应证据。",
            })

    return {
        "checked_claims": claims,
        "supported_claims": supported,
        "missing_evidence": missing,
        "warnings": [item["message"] for item in missing],
    }


def _image_health(diagnostics: dict, strategy: dict | None = None) -> dict:
    strategy = strategy or DEFAULT_IMAGE_STRATEGY
    issues: list[dict] = []
    main_status = diagnostics.get("main_image_status")
    fallback_reasons = set(diagnostics.get("fallback_reasons") or [])
    main_warnings = diagnostics.get("main_image_warnings") or []
    gallery_count = int(diagnostics.get("gallery_count") or 0)
    missing_roles = diagnostics.get("missing_gallery_roles") or []
    duplicate_backfill = diagnostics.get("duplicate_backfill") or []
    best_available_backfill = diagnostics.get("best_available_backfill") or []
    alignment = diagnostics.get("listing_image_alignment") or {}
    missing_evidence = alignment.get("missing_evidence") or []

    if main_status == "missing":
        issues.append({"severity": "review", "message": "缺少可用主图。"})
    elif main_status == "fallback_substitute":
        severity = "review" if fallback_reasons & {"wrong_variant", "quality_or_crop", "text_or_graphics", "collage_or_comparison"} else "high"
        issues.append({
            "severity": severity,
            "message": "主图为替代素材，需确认是否适合作为 Amazon 01 主图。",
            "details": main_warnings,
        })

    if gallery_count < 4:
        issues.append({"severity": "high", "message": f"图库仅选择 {gallery_count} 张图，转化信息不足。"})
    elif gallery_count < 6:
        issues.append({"severity": "warning", "message": f"图库仅选择 {gallery_count} 张图，建议补充更多转化证据。"})

    role_set = {item.get("role") for item in missing_roles}
    high_risk_missing_roles = set(strategy.get("high_risk_missing_roles") or [])
    critical_roles = set(strategy.get("critical_roles") or [])
    for role in high_risk_missing_roles:
        if role in role_set:
            issues.append({
                "severity": "high",
                "message": f"缺少{ROLE_LABELS.get(role, role)}图片，{strategy.get('name', '当前类目')}转化风险较高。",
            })
    for item in missing_roles:
        role = item.get("role")
        if role not in high_risk_missing_roles:
            if role in critical_roles:
                issues.append({
                    "severity": "warning",
                    "message": f"缺少{item.get('role_label') or role}图片。",
                })

    high_risk_claim_roles = set(strategy.get("high_risk_claim_roles") or [])
    for item in missing_evidence:
        role = item.get("role")
        severity = "high" if role in high_risk_claim_roles else "warning"
        issues.append({
            "severity": severity,
            "message": item.get("message") or f"Listing 卖点缺少图片证据: {item.get('claim_label')}",
            "matched_terms": item.get("matched_terms") or [],
        })

    if duplicate_backfill:
        issues.append({
            "severity": "warning",
            "message": f"有 {len(duplicate_backfill)} 张重复图片被兜底使用，图库信息密度偏低。",
        })
    if best_available_backfill:
        issues.append({
            "severity": "review",
            "message": f"有 {len(best_available_backfill)} 张图片因数量不足按现有素材最优兜底选择，需要人工复核。",
        })

    severities = {item["severity"] for item in issues}
    if "review" in severities:
        level = "review_recommended"
    elif "high" in severities:
        level = "high_risk"
    elif "warning" in severities:
        level = "warning"
    else:
        level = "pass"

    return {
        "level": level,
        "label": IMAGE_HEALTH_LABELS[level],
        "issues": issues,
        "issue_count": len(issues),
        "requires_attention": level in {"high_risk", "review_recommended"},
    }


def _select_gallery(reviews: list[dict], strategy: dict) -> tuple[dict | None, list[dict], dict]:
    if not reviews:
        return None, [], {
            "main_image_status": "missing",
            "main_image_source": None,
            "main_image_warnings": ["素材中没有可分析图片。"],
        }

    main, diagnostics = _select_main_image(reviews)

    gallery = []
    selected_ids = set()
    role_counts: dict[str, int] = {}
    duplicate_suppressed: list[dict] = []
    duplicate_backfill: list[dict] = []
    best_available_backfill: list[dict] = []
    if main:
        gallery.append({**main, "slot": "01", "selection_role": "identity"})
        selected_ids.add(main.get("image_id"))

    all_remaining = [item for item in reviews if item.get("image_id") not in selected_ids]
    candidates = sorted(
        [item for item in all_remaining if _is_usable_gallery_item(item)],
        key=lambda item: _score(item.get("gallery_score")),
        reverse=True,
    )
    max_gallery_slots = min(9, len(reviews))

    def add_item(item: dict, role: str, allow_duplicate: bool = False, backfill_reason: str | None = None) -> bool:
        if len(gallery) >= max_gallery_slots:
            return False
        image_id = item.get("image_id")
        if image_id in selected_ids:
            return False
        duplicate_reason = _duplicate_reason(item, gallery)
        if duplicate_reason and not allow_duplicate:
            duplicate_suppressed.append({
                "image_id": item.get("image_id"),
                "filename": item.get("filename"),
                "role": role,
                "role_label": ROLE_LABELS.get(role, role),
                "reason": duplicate_reason,
            })
            return False
        selected_ids.add(image_id)
        role_counts[role] = role_counts.get(role, 0) + 1
        selected_item = {**item, "slot": f"{len(gallery) + 1:02d}", "selection_role": role}
        if backfill_reason:
            selected_item["best_available_backfill"] = True
            selected_item["backfill_reason"] = backfill_reason
            selected_item["selection_warnings"] = [
                *(_ensure_list(selected_item.get("selection_warnings"))),
                backfill_reason,
            ]
            best_available_backfill.append({
                "image_id": item.get("image_id"),
                "filename": item.get("filename"),
                "role": role,
                "role_label": ROLE_LABELS.get(role, role),
                "reason": backfill_reason,
            })
        if duplicate_reason:
            selected_item["duplicate_backfill"] = True
            selected_item["duplicate_reason"] = duplicate_reason
            duplicate_backfill.append({
                "image_id": item.get("image_id"),
                "filename": item.get("filename"),
                "role": role,
                "role_label": ROLE_LABELS.get(role, role),
                "reason": duplicate_reason,
            })
        gallery.append(selected_item)
        return True

    role_limits = strategy.get("role_limits") or {}
    for role in strategy.get("role_order") or []:
        limit = int(role_limits.get(role, 1))
        if limit <= 0:
            continue
        role_candidates = sorted(candidates, key=lambda item: _role_candidate_score(item, role), reverse=True)
        for item in role_candidates:
            item_role = _selection_role(item)
            if item_role == "exclude" or item_role != role:
                continue
            if role_counts.get(role, 0) >= limit:
                break
            add_item(item, role)
        if len(gallery) >= max_gallery_slots:
            break

    fill_limits = strategy.get("role_fill_limits") or role_limits
    for item in candidates:
        role = _selection_role(item)
        if role == "exclude":
            continue
        if role_counts.get(role, 0) >= int(fill_limits.get(role, 1)):
            continue
        add_item(item, role)
        if len(gallery) >= max_gallery_slots:
            break

    # If distinct roles run out, use duplicate backups to keep a workable gallery.
    duplicate_backfill_target = max_gallery_slots
    for item in candidates:
        if len(gallery) >= duplicate_backfill_target:
            break
        role = _selection_role(item)
        if role == "exclude":
            continue
        add_item(item, role, allow_duplicate=True)

    # 最后兜底：如果合规图片不够，使用现有分析图片里评分最高、风险最低的素材补齐。
    fallback_candidates = sorted(
        [item for item in all_remaining if item.get("image_id") not in selected_ids],
        key=_gallery_fallback_score,
        reverse=True,
    )
    for item in fallback_candidates:
        if len(gallery) >= max_gallery_slots:
            break
        role = _selection_role(item)
        fallback_score = _gallery_fallback_score(item)
        reason = (
            "合规副图数量不足，已按现有素材中相对最优图片补齐；"
            f"需人工复核风险，fallback_score={fallback_score:.1f}"
        )
        add_item(item, role if role != "exclude" else "proof", allow_duplicate=True, backfill_reason=reason)

    for item in candidates:
        if item.get("image_id") in selected_ids:
            continue
        role = _selection_role(item)
        reason = _duplicate_reason(item, gallery)
        if reason:
            duplicate_suppressed.append({
                "image_id": item.get("image_id"),
                "filename": item.get("filename"),
                "role": role,
                "role_label": ROLE_LABELS.get(role, role),
                "reason": reason,
            })

    diagnostics["gallery_roles"] = [_gallery_role_entry(item) for item in gallery]
    diagnostics["gallery_count"] = len(gallery)
    diagnostics["missing_gallery_roles"] = _missing_gallery_roles(gallery, strategy)
    diagnostics["duplicate_suppressed"] = _dedupe_diagnostic_items(duplicate_suppressed)
    diagnostics["duplicate_backfill"] = _dedupe_diagnostic_items(duplicate_backfill)
    diagnostics["best_available_backfill"] = _dedupe_diagnostic_items(best_available_backfill)
    diagnostics["target_gallery_count"] = max_gallery_slots
    return main, gallery, diagnostics


def _write_image_analysis_files(
    material_dir: Path,
    sheets: list[dict],
    reviews: list[dict],
    gallery: list[dict],
    diagnostics: dict | None = None,
    source_images: list[dict] | None = None,
) -> None:
    out_dir = material_dir / "image analysis"
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "contact_sheets": sheets,
        "image_reviews": reviews,
        "gallery_selection": gallery,
        "selection_diagnostics": diagnostics or {},
        "source_images": source_images or [],
    }
    (out_dir / "image_selling_points.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    lines = ["# 图片分析", "", "## Contact Sheets"]
    for sheet in sheets:
        lines.append(f"- Page {sheet['sheet_page']}: {sheet['sheet_path']}")
    lines.extend(["", "## 主图/副图选择"])
    if diagnostics and diagnostics.get("main_image_warnings"):
        lines.extend(["", "## 主图替代提醒"])
        for warning in diagnostics.get("main_image_warnings") or []:
            lines.append(f"- {warning}")
        lines.append("")
        for item in gallery:
            lines.append(
                f"- Slot {item.get('slot')}: {item.get('image_id')} {item.get('filename')} "
                f"role={item.get('selection_role') or _selection_role(item)} "
                f"score={item.get('slot01_score') if item.get('slot') == '01' else item.get('gallery_score')} "
                f"reason={item.get('decision_reason') or item.get('visible_selling_point') or ''}"
            )
    if diagnostics and diagnostics.get("missing_gallery_roles"):
        lines.extend(["", "## 缺失图片角色"])
        for item in diagnostics.get("missing_gallery_roles") or []:
            lines.append(f"- {item.get('role_label')}: {item.get('buyer_question')}")
    if diagnostics and diagnostics.get("duplicate_suppressed"):
        lines.extend(["", "## 重复图片压制"])
        for item in diagnostics.get("duplicate_suppressed") or []:
            lines.append(f"- {item.get('image_id')} {item.get('filename')}: {item.get('reason')}")
    if diagnostics and diagnostics.get("best_available_backfill"):
        lines.extend(["", "## 数量不足兜底图片"])
        for item in diagnostics.get("best_available_backfill") or []:
            lines.append(f"- {item.get('image_id')} {item.get('filename')}: {item.get('reason')}")
    alignment = (diagnostics or {}).get("listing_image_alignment") or {}
    if alignment.get("missing_evidence"):
        lines.extend(["", "## Listing 图片证据缺口"])
        for item in alignment.get("missing_evidence") or []:
            lines.append(f"- {item.get('message')} matched_terms={', '.join(item.get('matched_terms') or [])}")
    health = (diagnostics or {}).get("image_health") or {}
    if health:
        lines.extend(["", "## 图片健康等级"])
        lines.append(f"- {health.get('label')} ({health.get('level')})")
        for issue in health.get("issues") or []:
            lines.append(f"- [{issue.get('severity')}] {issue.get('message')}")
    lines.extend(["", "## 全部图片分析"])
    for item in reviews:
        mm = item.get("multimodal_result") or {}
        summary = mm.get("visual_summary") if isinstance(mm, dict) else ""
        lines.append(
            f"- {item.get('image_id')} {item.get('filename')}: "
            f"{item.get('image_type') or ''}; {item.get('visible_selling_point') or ''}; {summary or ''}"
        )
    (out_dir / "image_selling_points.md").write_text("\n".join(lines).strip() + "\n", encoding="utf-8")


def _restore_cached_image_analysis(
    pi: ProductImage,
    cached: dict,
    images: list[Path] | None,
    image_analysis_model: str,
    pd: ProductData,
    strategy: dict,
    material_dir: Path,
    *,
    source_fingerprint: list[dict] | None = None,
) -> dict:
    images = images or []
    source_images = cached.get("source_images") or source_fingerprint or _image_fingerprint(images)
    source_count = len(source_images) or len(images)
    reviews = cached.get("image_reviews") or cached.get("images") or []
    previous_diagnostics = cached.get("selection_diagnostics") or {}
    contact_sheets = cached.get("contact_sheets") or []
    sheet_payloads = cached.get("sheet_payloads") or []
    strategy_name = strategy.get("name") or cached.get("gallery_strategy") or "cached"

    main_item, gallery_selection, diagnostics = _select_gallery(reviews, strategy)
    if previous_diagnostics.get("analysis_warnings"):
        diagnostics["analysis_warnings"] = previous_diagnostics.get("analysis_warnings")
    diagnostics["listing_image_alignment"] = _listing_image_alignment(pd, gallery_selection)
    diagnostics["image_strategy"] = {
        "name": strategy.get("name"),
        "buyer_focus": strategy.get("buyer_focus") or [],
        "critical_roles": strategy.get("critical_roles") or [],
        "high_risk_missing_roles": strategy.get("high_risk_missing_roles") or [],
        "high_risk_claim_roles": strategy.get("high_risk_claim_roles") or [],
    }
    diagnostics["image_health"] = _image_health(diagnostics, strategy)

    main_image_path = main_item.get("path") if isinstance(main_item, dict) else None
    gallery_items = [
        item for item in gallery_selection
        if isinstance(item, dict) and item.get("path") and item.get("path") != main_image_path
    ]
    gallery_paths = [item.get("path") for item in gallery_items]
    gallery_order = [item.get("image_id") for item in gallery_items]

    selling_points = []
    for item in reviews:
        if not isinstance(item, dict):
            continue
        if item.get("visible_selling_point"):
            selling_points.append(item.get("visible_selling_point"))
        mm = item.get("multimodal_result")
        if isinstance(mm, dict) and mm.get("aplus_reference_value"):
            selling_points.append(mm.get("aplus_reference_value"))
    selling_points = list(dict.fromkeys(selling_points))[:15]

    _write_image_analysis_files(
        material_dir,
        contact_sheets,
        reviews,
        gallery_selection,
        diagnostics,
        source_images=source_images,
    )

    pi.contact_sheet_path = str(contact_sheets[0].get("sheet_path")) if contact_sheets else pi.contact_sheet_path
    pi.image_analysis = json.dumps({
        "contact_sheets": contact_sheets,
        "sheet_payloads": sheet_payloads,
        "images": reviews,
        "gallery_selection": gallery_selection,
        "selection_diagnostics": diagnostics,
        "gallery_strategy": strategy_name,
        "cache_source": "image_selling_points.json",
        "cache_reselected": True,
        "source_images": source_images,
    }, ensure_ascii=False)
    pi.image_selling_points = json.dumps(selling_points, ensure_ascii=False)
    pi.category_style = f"multi_sheet:{strategy_name}"
    pi.main_image_summary = (
        f"复用图片分析缓存，覆盖 {len(reviews)}/{source_count} 张图片，"
        f"生成 {len(gallery_selection)} 张图片分析建议，不覆盖人工确认的图片顺序。"
        + f" 图片健康等级: {diagnostics.get('image_health', {}).get('label', '未知')}。"
        + (
            " 主图使用替代素材: " + "；".join(diagnostics.get("main_image_warnings") or [])
            if diagnostics.get("main_image_status") == "fallback_substitute"
            else ""
        )
    )
    pi.analyzed_at = datetime.now()
    pi.vlm_model = image_analysis_model

    return {
        "contact_sheets": contact_sheets,
        "sheet_payloads": sheet_payloads,
        "images": reviews,
        "gallery_selection": gallery_selection,
        "main_image_path": main_image_path,
        "main_image_source": pi.main_image_source,
        "selection_diagnostics": diagnostics,
        "gallery_strategy": strategy_name,
        "cache_hit": True,
        "cache_reselected": True,
    }


async def reselect_image_gallery_from_cache(product_id: int) -> dict:
    """复用已有图片分析结果，仅按当前选择规则重排主图/副图。"""
    async with async_session() as db:
        result = await db.execute(
            select(Product)
            .options(selectinload(Product.data), selectinload(Product.images))
            .where(Product.id == product_id)
        )
        product = result.scalar_one_or_none()
        if not product or not product.data or not product.images:
            raise ValueError(f"Product {product_id} not found or no image cache")

        pd = product.data
        if not pd.material_dir:
            raise ValueError("未设置素材目录，无法重选图片")

        material_dir = Path(pd.material_dir)
        images = _scan_images(pd.material_dir)
        cached = _load_cached_image_analysis(material_dir, images) if images else None
        if not cached and product.images.image_analysis:
            payload = _json_loads(product.images.image_analysis, {})
            reviews = payload.get("images") if isinstance(payload, dict) else None
            if isinstance(reviews, list) and reviews:
                cached = {
                    "contact_sheets": payload.get("contact_sheets") or [],
                    "sheet_payloads": payload.get("sheet_payloads") or [],
                    "image_reviews": reviews,
                    "gallery_selection": payload.get("gallery_selection") or [],
                    "selection_diagnostics": payload.get("selection_diagnostics") or {},
                    "gallery_strategy": payload.get("gallery_strategy"),
                    "source_images": payload.get("source_images") or _image_fingerprint(images),
                }

        if not cached:
            raise ValueError("未找到可复用的图片分析缓存")

        category = pd.leaf_category or "General"
        strategy = _image_strategy(category, pd)
        result_payload = _restore_cached_image_analysis(
            product.images,
            cached,
            images,
            settings.VLM_MODEL,
            pd,
            strategy,
            material_dir,
        )
        await db.commit()
        return result_payload


async def run_image_analysis(product_id: int) -> dict:
    """
    执行图片分析
    
    1. 准备已确认的主图/副图
    2. 生成 Contact Sheet
    3. VLM 分析
    4. 输出图片卖点和证据缺口
    """
    async with async_session() as db:
        result = await db.execute(
            select(Product)
            .options(selectinload(Product.data), selectinload(Product.images))
            .where(Product.id == product_id)
        )
        product = result.scalar_one_or_none()
        if not product or not product.data:
            raise ValueError(f"Product {product_id} not found or no data")

        pd = product.data
        # 准备已确认图片；远程 URL 默认直接传给 VLM，只有兜底路径才按需下载。
        pi = product.images
        if not pi or not pi.main_image_path:
            raise ValueError("请先确认商品主图和 Listing 图片")
        material_dir, image_records = await _prepare_confirmed_image_sources(pd, pi)
        if not image_records:
            raise ValueError("已确认图片为空，请重新确认商品图片")
        source_fingerprint = _image_source_fingerprint(image_records)

        logger.info(f"[Step6] 找到 {len(image_records)} 张图片")

        image_analysis_model = settings.VLM_MODEL
        category = pd.leaf_category or "General"
        strategy = _image_strategy(category, pd)
        cached_analysis = _load_cached_image_analysis(material_dir, source_fingerprint=source_fingerprint)
        if cached_analysis:
            result_payload = _restore_cached_image_analysis(
                pi,
                cached_analysis,
                None,
                image_analysis_model,
                pd,
                strategy,
                material_dir,
                source_fingerprint=source_fingerprint,
            )
            await db.commit()
            logger.info(
                f"[Step6] 命中图片分析缓存: product={product_id}, images={len(image_records)}, "
                f"source=image_selling_points.json, reselected=True"
            )
            return result_payload

        analysis_dir = material_dir / "image analysis"
        contact_sheet_dir = analysis_dir / "contact_sheets"
        if contact_sheet_dir.exists():
            shutil.rmtree(contact_sheet_dir)
        product_key = pd.item_code or product.gigab2b_product_id or str(product.id)

        # 调用 VLM 分析
        client = settings.get_image_analysis_client()

        facts = _facts_from_product(pd)
        gallery_strategy = _gallery_strategy_prompt(strategy)
        all_reviews: list[dict] = []
        sheet_payloads: list[dict] = []
        analysis_contact_sheets: list[dict] = []
        analysis_warnings: list[str] = []
        prompt = VLM_ANALYSIS_PROMPT.format(
            title=pd.title or "Unknown",
            brand=product.brand or settings.DEFAULT_BRAND,
            category=category,
            facts=facts,
            gallery_strategy=gallery_strategy,
        )

        direct_batches = _build_image_url_batches(image_records)
        direct_error: Exception | None = None
        try:
            for sheet in direct_batches:
                batch_records = [record for record in image_records if record["image_id"] in set(sheet["image_ids"])]
                sheet_analysis, reviews = await _analyze_image_url_batch(client, image_analysis_model, sheet, batch_records, prompt)
                all_reviews.extend(reviews)
                sheet_payloads.append({
                    **sheet,
                    "analysis": sheet_analysis,
                    "reviews": reviews,
                    "mode": "direct_image_url",
                })
            analysis_contact_sheets = list(direct_batches)
            pi.contact_sheet_path = str(direct_batches[0]["sheet_path"]) if direct_batches else pi.contact_sheet_path
        except Exception as exc:
            direct_error = exc
            all_reviews = []
            sheet_payloads = []
            analysis_contact_sheets = []
            warning = (
                f"图片URL直传VLM失败，已按需下载图片并切换到Contact Sheet兜底: "
                f"{type(exc).__name__}: {exc}"
            )
            logger.warning(f"[Step6] {warning}")
            analysis_warnings.append(warning)

        if direct_error is not None:
            local_image_records = await _download_image_records(image_records, material_dir)
            if not local_image_records:
                raise RuntimeError("图片URL直传失败，且已确认图片未能下载到本地，无法继续图片分析") from direct_error
            missing_downloads = len(image_records) - len(local_image_records)
            if missing_downloads > 0:
                analysis_warnings.append(f"{missing_downloads} 张图片下载失败，已用可下载图片继续分析。")
            contact_sheets = _build_contact_sheets(local_image_records, contact_sheet_dir, product_key)
            if not contact_sheets:
                raise RuntimeError("Contact Sheet 生成失败")
            pi.contact_sheet_path = str(contact_sheets[0]["sheet_path"])
            analysis_contact_sheets = list(contact_sheets)

            for sheet in contact_sheets:
                batch_records = [record for record in local_image_records if record["image_id"] in set(sheet["image_ids"])]
                try:
                    sheet_analysis, reviews = await _analyze_contact_sheet(client, image_analysis_model, sheet, batch_records, prompt)
                except Exception as exc:
                    is_data_inspection = _is_data_inspection_error(exc)
                    is_transient = _is_transient_vlm_error(exc)
                    if not (is_data_inspection or is_transient):
                        raise

                    if is_data_inspection:
                        warning = (
                            f"Contact Sheet {sheet['sheet_page']} 被VLM内容安全检查拦截，"
                            "已改为逐张图片重试分析。"
                        )
                        fallback_status = "data_inspection_failed"
                    else:
                        warning = (
                            f"Contact Sheet {sheet['sheet_page']} 多图请求连接异常，"
                            "已跳过逐张重试并使用保守图片分析保底。"
                        )
                        fallback_status = "transient_connection_failed"
                    logger.warning(f"[Step6] {warning} error={exc}")
                    analysis_warnings.append(warning)
                    sheet_payloads.append({
                        **sheet,
                        "analysis": {"images": []},
                        "reviews": [],
                        "status": fallback_status,
                        "error": str(exc),
                    })
                    if is_transient and not is_data_inspection:
                        continue

                    for record in batch_records:
                        fallback_dir = contact_sheet_dir / f"fallback_sheet_{sheet['sheet_page']:02d}"
                        fallback_key = f"{product_key}_sheet_{sheet['sheet_page']:02d}_{record['image_id'].lstrip('#')}"
                        fallback_sheets = _build_contact_sheets([record], fallback_dir, fallback_key)
                        if not fallback_sheets:
                            continue
                        fallback_sheet = fallback_sheets[0]
                        analysis_contact_sheets.append(fallback_sheet)
                        try:
                            single_analysis, single_reviews = await _analyze_contact_sheet(
                                client,
                                image_analysis_model,
                                fallback_sheet,
                                [record],
                                prompt,
                            )
                        except Exception as single_exc:
                            single_data_inspection = _is_data_inspection_error(single_exc)
                            single_transient = _is_transient_vlm_error(single_exc)
                            if not (single_data_inspection or single_transient):
                                raise
                            if single_data_inspection:
                                image_warning = (
                                    f"图片 {record['image_id']} {record['filename']} 被VLM内容安全检查拦截，"
                                    "已跳过该图继续流程。"
                                )
                                single_status = "data_inspection_failed"
                            else:
                                image_warning = (
                                    f"图片 {record['image_id']} {record['filename']} VLM连接异常，"
                                    "已跳过该图继续流程。"
                                )
                                single_status = "transient_connection_failed"
                            logger.warning(f"[Step6] {image_warning} error={single_exc}")
                            analysis_warnings.append(image_warning)
                            sheet_payloads.append({
                                **fallback_sheet,
                                "analysis": {"images": []},
                                "reviews": [],
                                "status": single_status,
                                "error": str(single_exc),
                            })
                            continue
                        all_reviews.extend(single_reviews)
                        sheet_payloads.append({
                            **fallback_sheet,
                            "analysis": single_analysis,
                            "reviews": single_reviews,
                            "fallback_from_sheet_page": sheet["sheet_page"],
                        })
                    continue

                all_reviews.extend(reviews)
                sheet_payloads.append({
                    **sheet,
                    "analysis": sheet_analysis,
                    "reviews": reviews,
                    "mode": "contact_sheet_fallback",
                })

        if not all_reviews:
            warning = "VLM 未返回任何图片分析结果，已使用保守图片分析保底继续流程。"
            logger.warning(f"[Step6] {warning}")
            analysis_warnings.append(warning)
            all_reviews = []
            for index, record in enumerate(image_records):
                role = "main" if index == 0 else "alternate_angle"
                score = 8 if index == 0 else 6
                filename = record.get("filename") or f"image_{index + 1}"
                fallback_review = {
                    "image_id": record.get("image_id") or f"#{index + 1}",
                    "slot": record.get("slot") or f"{index + 1:02d}",
                    "filename": filename,
                    "path": record.get("path") or record.get("url"),
                    "source_url": record.get("source_url") or record.get("url") or record.get("path"),
                    "image_type": role,
                    "selection_role": role,
                    "slot01_score": score,
                    "gallery_score": score,
                    "visible_selling_point": "Use this image as a conservative product reference; avoid unsupported claims.",
                    "aplus_reference_value": "Product identity reference only; preserve visible shape, color, material, and construction.",
                    "risk_notes": ["Fallback analysis: VLM unavailable or timed out."],
                    "analysis_source": "fallback_no_vlm",
                    "multimodal_result": {
                        "aplus_reference_value": "Product identity reference only; preserve visible shape, color, material, and construction.",
                        "visual_risks": ["VLM analysis unavailable; keep downstream claims conservative."],
                    },
                }
                all_reviews.append(fallback_review)
            sheet_payloads.append({
                "sheet_page": 0,
                "sheet_path": pi.contact_sheet_path,
                "image_ids": [item.get("image_id") for item in all_reviews],
                "analysis": {"images": all_reviews, "fallback": True},
                "reviews": all_reviews,
                "mode": "fallback_no_vlm",
                "status": "fallback_no_vlm",
            })

        main_review, gallery_selection, selection_diagnostics = _select_gallery(all_reviews, strategy)
        if analysis_warnings:
            selection_diagnostics["analysis_warnings"] = analysis_warnings
        selection_diagnostics["listing_image_alignment"] = _listing_image_alignment(pd, gallery_selection)
        selection_diagnostics["image_strategy"] = {
            "name": strategy.get("name"),
            "buyer_focus": strategy.get("buyer_focus") or [],
            "critical_roles": strategy.get("critical_roles") or [],
            "high_risk_missing_roles": strategy.get("high_risk_missing_roles") or [],
            "high_risk_claim_roles": strategy.get("high_risk_claim_roles") or [],
        }
        selection_diagnostics["image_health"] = _image_health(selection_diagnostics, strategy)
        main_image_path = main_review.get("path") if main_review else None
        gallery_items = [
            item for item in gallery_selection
            if item.get("path") and item.get("path") != main_image_path
        ]
        gallery_paths = [item.get("path") for item in gallery_items]
        gallery_order = [item.get("image_id") for item in gallery_items]

        # 卖点提取
        selling_points = []
        for img_a in all_reviews:
            if img_a.get("visible_selling_point"):
                selling_points.append(img_a.get("visible_selling_point"))
            mm = img_a.get("multimodal_result")
            if isinstance(mm, dict) and mm.get("aplus_reference_value"):
                selling_points.append(mm.get("aplus_reference_value"))
        selling_points = list(dict.fromkeys(selling_points))[:15]  # 去重取前15

        _write_image_analysis_files(
            material_dir,
            analysis_contact_sheets,
            all_reviews,
            gallery_selection,
            selection_diagnostics,
            source_images=source_fingerprint,
        )

        # 保存到数据库
        pi.image_analysis = json.dumps({
            "contact_sheets": analysis_contact_sheets,
            "sheet_payloads": sheet_payloads,
            "images": all_reviews,
            "gallery_selection": gallery_selection,
            "selection_diagnostics": selection_diagnostics,
            "gallery_strategy": strategy.get("name"),
            "source_images": source_fingerprint,
        }, ensure_ascii=False)
        pi.image_selling_points = json.dumps(selling_points, ensure_ascii=False)
        pi.category_style = f"multi_sheet:{strategy.get('name')}"
        pi.main_image_summary = (
            f"分析 {len(all_reviews)}/{len(image_records)} 张图片，"
            f"{'URL直传' if direct_error is None else 'Contact Sheet兜底'} {len(analysis_contact_sheets)} 组，"
            f"生成 {len(gallery_selection)} 张图片分析建议，不覆盖人工确认的图片顺序。"
            + f" 图片健康等级: {selection_diagnostics.get('image_health', {}).get('label', '未知')}。"
            + (
                f" Listing图片证据缺口 {len(selection_diagnostics.get('listing_image_alignment', {}).get('missing_evidence') or [])} 个。"
                if selection_diagnostics.get("listing_image_alignment", {}).get("missing_evidence")
                else ""
            )
            + (
                " 主图使用替代素材: " + "；".join(selection_diagnostics.get("main_image_warnings") or [])
                if selection_diagnostics.get("main_image_status") == "fallback_substitute"
                else ""
            )
            + (
                f" VLM安全检查跳过/降级 {len(analysis_warnings)} 项。"
                if analysis_warnings
                else ""
            )
        )
        pi.analyzed_at = datetime.now()
        pi.vlm_model = image_analysis_model
        await db.commit()

        logger.info(
            f"[Step6] 图片分析完成: {len(all_reviews)}/{len(image_records)} 张图, groups={len(analysis_contact_sheets)}, "
            f"主图={main_image_path}, 副图={len(gallery_paths)} 张"
        )
        return {
            "contact_sheets": analysis_contact_sheets,
            "sheet_payloads": sheet_payloads,
            "images": all_reviews,
            "gallery_selection": gallery_selection,
            "main_image_path": main_image_path,
            "main_image_source": pi.main_image_source,
            "selection_diagnostics": selection_diagnostics,
            "gallery_strategy": strategy.get("name"),
        }
