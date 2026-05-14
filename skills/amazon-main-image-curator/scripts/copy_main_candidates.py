#!/usr/bin/env python3
"""Copy selected gallery images into fresh `new main image` folders."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
from pathlib import Path

try:
    from openpyxl import Workbook
except ImportError:  # pragma: no cover
    Workbook = None


def load_decisions(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return {"products": data}
    return data


def by_product_key(items: list[dict]) -> dict[str, dict]:
    out = {}
    for item in items:
        for key in [item.get("product_key"), item.get("folder_id"), str(item.get("row_number", ""))]:
            if key:
                out[str(key)] = item
    return out


def prepare_output_folder(product_folder: Path, folder_name: str) -> Path:
    out = product_folder / folder_name
    if out.exists() and any(out.iterdir()):
        backup = product_folder / f"{folder_name}_backup_{dt.datetime.now():%Y%m%d_%H%M%S}"
        out.rename(backup)
    out.mkdir(parents=True, exist_ok=True)
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--index", required=True)
    parser.add_argument("--decisions", required=True)
    parser.add_argument("--folder-name", default="new main image")
    args = parser.parse_args()

    index_path = Path(args.index).expanduser().resolve()
    index = json.loads(index_path.read_text(encoding="utf-8"))
    decisions = load_decisions(Path(args.decisions).expanduser().resolve())
    if len(index.get("products", [])) != 1 or len(decisions.get("products", [])) != 1:
        raise SystemExit("Single-product red line: copy_main_candidates requires exactly one indexed product and one decision product.")
    product_index = by_product_key(index.get("products", []))
    manifest = {
        "created_at": dt.datetime.now().isoformat(timespec="seconds"),
        "source_index": str(index_path),
        "products": [],
    }

    for decision in decisions.get("products", []):
        product = product_index.get(str(decision.get("product_key"))) or product_index.get(str(decision.get("folder_id"))) or product_index.get(str(decision.get("row_number")))
        if not product or not product.get("matched_folder"):
            manifest["products"].append(
                {
                    "product_key": decision.get("product_key", ""),
                    "status": "missing_matched_folder",
                    "selected": [],
                }
            )
            continue
        selections = sorted(decision.get("gallery_selection", []), key=lambda x: str(x.get("slot", "")))
        selections = [s for s in selections if s.get("slot") and s.get("path")]
        if not selections:
            manifest["products"].append(
                {
                    "product_key": decision.get("product_key", ""),
                    "matched_folder": product.get("matched_folder", ""),
                    "status": "no_selection",
                    "selected": [],
                }
            )
            continue
        product_folder = Path(product["matched_folder"])
        out_folder = prepare_output_folder(product_folder, args.folder_name)
        copied = []
        for sel in selections:
            slot = str(sel["slot"]).zfill(2)
            source = Path(sel["path"]).expanduser().resolve()
            if not source.exists():
                copied.append({**sel, "copy_status": "source_missing"})
                continue
            dest = out_folder / f"{slot}{source.suffix.lower()}"
            shutil.copy2(source, dest)
            copied.append(
                {
                    "slot": slot,
                    "filename": sel.get("filename", source.name),
                    "source_path": str(source),
                    "copied_path": str(dest),
                    "score": sel.get("score"),
                    "selected_selling_points": sel.get("selected_selling_points", []),
                    "selection_reason": sel.get("selection_reason", ""),
                    "copy_status": "copied",
                }
            )
        product_manifest = {
            "product_key": decision.get("product_key", ""),
            "folder_id": decision.get("folder_id", ""),
            "matched_folder": str(product_folder),
            "output_folder": str(out_folder),
            "status": "copied",
            "selected": copied,
        }
        manifest["products"].append(product_manifest)
        (out_folder / "selection_manifest.json").write_text(json.dumps(product_manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        if Workbook is not None:
            wb = Workbook()
            ws = wb.active
            ws.title = "Selection Manifest"
            ws.append(["slot", "filename", "source_path", "copied_path", "score", "selling_points", "selection_reason", "copy_status"])
            for item in copied:
                ws.append(
                    [
                        item.get("slot", ""),
                        item.get("filename", ""),
                        item.get("source_path", ""),
                        item.get("copied_path", ""),
                        item.get("score"),
                        json.dumps(item.get("selected_selling_points", []), ensure_ascii=False),
                        item.get("selection_reason", ""),
                        item.get("copy_status", ""),
                    ]
                )
            wb.save(out_folder / "selection_manifest.xlsx")

    run_dir = Path(index.get("run_dir") or index_path.parent)
    manifest_path = run_dir / "selection_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {manifest_path}")


if __name__ == "__main__":
    main()
