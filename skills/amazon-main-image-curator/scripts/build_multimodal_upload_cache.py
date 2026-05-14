#!/usr/bin/env python3
"""Create resized per-image copies for optional multimodal upload workflows."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

try:
    from PIL import Image, ImageOps
except ImportError as exc:  # pragma: no cover
    raise SystemExit("Missing dependency: Pillow. Install with: python3 -m pip install pillow") from exc


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--index", required=True)
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--max-size", type=int, default=1600)
    parser.add_argument("--quality", type=int, default=92)
    args = parser.parse_args()

    index_path = Path(args.index).expanduser().resolve()
    index = json.loads(index_path.read_text(encoding="utf-8"))
    if len(index.get("products", [])) != 1:
        raise SystemExit("Single-product red line: upload cache requires an index containing exactly one product.")
    run_dir = Path(index.get("run_dir") or index_path.parent)
    out_dir = Path(args.output_dir).expanduser().resolve() if args.output_dir else run_dir / "multimodal_upload_cache"
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = {"source_index": str(index_path), "max_size": args.max_size, "images": []}

    for product in index["products"]:
        product_dir = out_dir / str(product["product_key"])
        product_dir.mkdir(parents=True, exist_ok=True)
        for img in product.get("images", []):
            safe_name = f"{img['image_id'].strip('#')}_{Path(img['filename']).stem}.jpg"
            dest = product_dir / safe_name
            try:
                with Image.open(img["path"]) as source:
                    source = ImageOps.exif_transpose(source).convert("RGB")
                    source.thumbnail((args.max_size, args.max_size), Image.LANCZOS)
                    source.save(dest, "JPEG", quality=args.quality, optimize=True, progressive=True)
            except Exception as exc:
                img["upload_cache_error"] = str(exc)
                continue
            img["upload_cache_path"] = str(dest)
            manifest["images"].append(
                {
                    "product_key": product["product_key"],
                    "image_id": img["image_id"],
                    "source_path": img["path"],
                    "upload_cache_path": str(dest),
                }
            )

    manifest_path = out_dir / "upload_cache_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {manifest_path}")
    print(f"Updated {index_path}")


if __name__ == "__main__":
    main()
