from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from openpyxl.worksheet.worksheet import Worksheet

from app.models import Product, ProductData


@dataclass
class AmazonExportContext:
    product: Product
    product_data: ProductData
    mapping: dict[str, Any]
    template_path: Path
    output_path: Path
    workbook: Any
    worksheet: Worksheet
    columns: dict[str, str]
    data_row: int
    fields: dict[str, Any]
    fill: dict[str, Any]
    bullets: list[str]
    existing_image_urls: dict[str, str]
    package: dict[str, Any] | None = None
    warnings: list[str] = field(default_factory=list)
    uploaded_images: list[dict[str, Any]] = field(default_factory=list)

