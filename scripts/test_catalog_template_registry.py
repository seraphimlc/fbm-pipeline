#!/usr/bin/env python3
"""Regression checks for category template management without catalog products."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


async def main() -> None:
    from app.api.products import _catalog_template_file_summaries, _template_registry_entries

    registry = _template_registry_entries()
    expected_categories = {
        "Bicycle",
        "RIDE_ON_TOY",
        "Shelf Table Cabinet Gate",
        "Sofas & Couches",
        "Storage Furniture",
    }
    assert expected_categories <= set(registry), registry.keys()

    # This function no longer derives its rows from CatalogProduct, so None is sufficient here.
    files = await _catalog_template_file_summaries(None)
    builtin = [item for item in files if item.source == "builtin"]
    assert len(builtin) >= 5, files
    assert all(not item.can_delete for item in builtin), builtin
    assert all(item.support_categories for item in builtin if item.file_status != "unmapped"), builtin
    print(f"OK: {len(registry)} registered categories, {len(files)} managed template files")


if __name__ == "__main__":
    asyncio.run(main())
