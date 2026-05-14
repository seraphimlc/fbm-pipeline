#!/usr/bin/env python3
"""Build labeled high-resolution contact sheets for multimodal review."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont, ImageOps
except ImportError as exc:  # pragma: no cover
    raise SystemExit("Missing dependency: Pillow. Install with: python3 -m pip install pillow") from exc


def load_font(size: int):
    for name in ["Arial.ttf", "Helvetica.ttc", "DejaVuSans.ttf"]:
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            pass
    return ImageFont.load_default()


def draw_centered(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], text: str, font, fill):
    x1, y1, x2, y2 = box
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text((x1 + (x2 - x1 - tw) / 2, y1 + (y2 - y1 - th) / 2), text, font=font, fill=fill)


def chunks(items, size):
    for i in range(0, len(items), size):
        yield i, items[i : i + size]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--index", required=True)
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--max-per-sheet", type=int, default=9)
    parser.add_argument("--thumb-size", type=int, default=720)
    parser.add_argument("--label-height", type=int, default=72)
    parser.add_argument("--columns", type=int, default=3)
    parser.add_argument("--quality", type=int, default=94)
    args = parser.parse_args()

    index_path = Path(args.index).expanduser().resolve()
    index = json.loads(index_path.read_text(encoding="utf-8"))
    if len(index.get("products", [])) != 1:
        raise SystemExit("Single-product red line: contact sheets require an index containing exactly one product.")
    run_dir = Path(index.get("run_dir") or index_path.parent)
    out_dir = Path(args.output_dir).expanduser().resolve() if args.output_dir else run_dir / "contact_sheets"
    out_dir.mkdir(parents=True, exist_ok=True)

    label_font = load_font(max(18, args.label_height // 3))
    small_font = load_font(max(12, args.label_height // 5))
    manifest = {"source_index": str(index_path), "contact_sheets": []}

    for product in index["products"]:
        images = product.get("images", [])
        product_sheets = []
        for offset, batch in chunks(images, args.max_per_sheet):
            page = offset // args.max_per_sheet + 1
            rows = math.ceil(len(batch) / args.columns)
            tile_w = args.thumb_size
            tile_h = args.thumb_size + args.label_height
            sheet = Image.new("RGB", (args.columns * tile_w, rows * tile_h), "white")
            draw = ImageDraw.Draw(sheet)
            sheet_name = f"{product['product_key']}_sheet_{page:02d}.jpg".replace("/", "_")
            sheet_path = out_dir / sheet_name

            for idx, img in enumerate(batch):
                col = idx % args.columns
                row = idx // args.columns
                x = col * tile_w
                y = row * tile_h
                draw.rectangle((x, y, x + tile_w - 1, y + tile_h - 1), outline=(210, 210, 210), width=2)
                try:
                    with Image.open(img["path"]) as source:
                        source = ImageOps.exif_transpose(source).convert("RGB")
                        source.thumbnail((tile_w - 24, args.thumb_size - 24), Image.LANCZOS)
                        px = x + (tile_w - source.width) // 2
                        py = y + (args.thumb_size - source.height) // 2
                        sheet.paste(source, (px, py))
                except Exception as exc:
                    draw_centered(draw, (x, y, x + tile_w, y + args.thumb_size), f"OPEN FAILED: {exc}", small_font, "red")
                label = f"{img['image_id']}  {img['filename']}"
                draw.rectangle((x, y + args.thumb_size, x + tile_w, y + tile_h), fill=(246, 246, 246))
                draw.text((x + 12, y + args.thumb_size + 8), label[:90], font=label_font, fill=(20, 20, 20))
                img["contact_sheet_evidence"] = {
                    "sheet_path": str(sheet_path),
                    "sheet_page": page,
                    "sheet_label": img["image_id"],
                }

            sheet.save(sheet_path, "JPEG", quality=args.quality, optimize=True, progressive=True)
            record = {
                "product_key": product["product_key"],
                "folder_id": product.get("folder_id", ""),
                "sheet_page": page,
                "sheet_path": str(sheet_path),
                "image_ids": [img["image_id"] for img in batch],
            }
            manifest["contact_sheets"].append(record)
            product_sheets.append(record)
        product["contact_sheets"] = product_sheets

    manifest_path = out_dir / "contact_sheets_index.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {manifest_path}")
    print(f"Updated {index_path}")


if __name__ == "__main__":
    main()
