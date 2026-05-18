#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from validate_template_mappings import merge_category_options  # noqa: E402


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def test_category_conflict_only_overrides_conflict() -> None:
    first_mapping = {
        "browse_category_options": [
            {
                "product_type": "SOFA",
                "node": "sofas",
                "path": "Home > Furniture > Sofas",
                "markers": ["sofa"],
            },
            {
                "product_type": "CHAIR",
                "node": "chairs",
                "path": "Home > Furniture > Chairs",
                "markers": ["chair"],
            },
        ]
    }
    later_mapping = {
        "browse_category_options": [
            {
                "product_type": "SOFA",
                "node": "sofas",
                "path": "Home > Furniture > Sofas",
                "markers": ["updated sofa"],
            }
        ]
    }

    merged, overrides = merge_category_options([
        ("first", first_mapping),
        ("later", later_mapping),
    ])

    assert_true(len(merged) == 2, "非冲突类目应该保留")
    assert_true(len(overrides) == 1, "只有冲突类目应该产生覆盖事件")
    assert_true(merged["Home > Furniture > Sofas (sofas)"]["source"] == "later", "冲突类目应以后导入为准")
    assert_true(merged["Home > Furniture > Chairs (chairs)"]["source"] == "first", "非冲突类目不应被覆盖")


def test_real_asin_export_guard_is_present() -> None:
    products_py = ROOT / "backend" / "app" / "api" / "products.py"
    text = products_py.read_text(encoding="utf-8")
    assert_true("已有真实 ASIN" in text, "导出逻辑必须保留真实 ASIN 防重复导出提示")
    assert_true("不能再次导出 Amazon 导入表格" in text, "已有真实 ASIN 的商品必须禁止再次导出导入表格")


def test_step10_keeps_sofa_dimensions_and_avoids_inventory_conflict() -> None:
    step10_py = ROOT / "backend" / "app" / "pipeline" / "step10_amazon_template.py"
    text = step10_py.read_text(encoding="utf-8")
    assert_true(
        "SOFA_ITEM_DIMENSION_MAX_WIDTH_INCHES" not in text,
        "SOFA 不能再因为宽度阈值清空 Item Dimensions D x W x H",
    )
    assert_true(
        'fields["inventory_available"]' not in text,
        "使用 Quantity 库存时不能同时写 Inventory Always Available，否则 Amazon 会拒绝 quantity",
    )
    assert_true(
        '"living-room-chaise-lounges"' in text and "high_confidence_nodes" in text,
        "Chaise Lounges 来源类目应优先映射到休闲椅，不能被 sofa 尺寸兜底提前改成 sofas",
    )


def main() -> int:
    tests = [
        test_category_conflict_only_overrides_conflict,
        test_real_asin_export_guard_is_present,
        test_step10_keeps_sofa_dimensions_and_avoids_inventory_conflict,
    ]
    for test in tests:
        test()
        print(f"PASS: {test.__name__}")
    print(f"OK: {len(tests)} project rule test(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
