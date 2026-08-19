from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.models import ProductData
from app.pipeline.template_category_fallback import select_template_category_fallback


def _category_for(*, product_type: str, title: str) -> dict:
    result = select_template_category_fallback(ProductData(product_type=product_type, title=title))
    assert result is not None
    return result


def main() -> None:
    bike = _category_for(
        product_type="Outdoor Bikes",
        title="24 Inch Cruiser Bike for Girls with Basket",
    )
    assert bike["leafCategory"].endswith("(cruiser-bicycles)"), bike

    dresser = _category_for(product_type="Storage Furniture", title="6 Drawer Dresser Chest")
    assert dresser["leafCategory"].endswith("(dressers)"), dresser

    bookshelf = _category_for(product_type="Furniture", title="Kids Bookshelf with Storage")
    assert bookshelf["leafCategory"].endswith("(childrens-bookcases)"), bookshelf

    bed = _category_for(product_type="Furniture", title="Queen Upholstered Platform Bed Frame")
    assert bed["leafCategory"].endswith("(bed-frames)"), bed

    assert select_template_category_fallback(ProductData(product_type="Furniture", title="Kids Bed Frame")) is None
    assert select_template_category_fallback(ProductData(product_type="Furniture", title="Adjustable Bed Base")) is None
    sofa_bed = select_template_category_fallback(ProductData(product_type="Furniture", title="Sofa Bed Frame"))
    assert sofa_bed is None or not sofa_bed["leafCategory"].endswith("(bed-frames)"), sofa_bed
    assert select_template_category_fallback(ProductData(product_type="Misc", title="Generic item")) is None


if __name__ == "__main__":
    main()
