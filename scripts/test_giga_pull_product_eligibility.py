#!/usr/bin/env python3
"""Regression: raw GIGA cache must not block re-creating deleted products."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.task_runtime.giga_pull_workers import _sku_codes_without_materialized_products  # noqa: E402


def main() -> None:
    listed = ["SKU-A-RED", "SKU-A-BLUE", "SKU-B"]
    item_codes = {"SKU-A-RED": "ITEM-A", "SKU-A-BLUE": "ITEM-A", "SKU-B": "ITEM-B"}

    # A raw GIGA cache with no Product rows must allow every remote SKU back in.
    assert _sku_codes_without_materialized_products(listed, item_codes, set()) == listed
    # A real product draft for ITEM-A suppresses its variants, not unrelated SKU-B.
    assert _sku_codes_without_materialized_products(listed, item_codes, {"ITEM-A"}) == ["SKU-B"]
    print("giga pull product eligibility: PASS")


if __name__ == "__main__":
    main()
