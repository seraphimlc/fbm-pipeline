"""Focused checks for actionable GIGA draft-materialization failures."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.task_runtime.giga_pull_workers import _raise_if_product_draft_materialization_failed  # noqa: E402


def main() -> None:
    empty_upc_result = SimpleNamespace(
        requested_items=6,
        product_ids=[],
        errors=[
            "ITEM-A: UpcPoolEmptyError: UPC池子可用UPC不足，请先到 UPC池子 添加UPC",
            "ITEM-B: UpcPoolEmptyError: UPC池子可用UPC不足，请先到 UPC池子 添加UPC",
        ],
    )
    try:
        _raise_if_product_draft_materialization_failed(empty_upc_result)
    except RuntimeError as exc:
        assert str(exc) == "UPC池子可用UPC不足，请先到 UPC池子 添加UPC"
    else:
        raise AssertionError("empty UPC pool must fail the materialize step")

    partial_result = SimpleNamespace(
        requested_items=2,
        product_ids=[42],
        errors=["ITEM-B: UpcPoolEmptyError: UPC池子可用UPC不足，请先到 UPC池子 添加UPC"],
    )
    _raise_if_product_draft_materialization_failed(partial_result)
    print("giga pull materialize error reporting: PASS")


if __name__ == "__main__":
    main()
