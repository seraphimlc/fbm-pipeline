from __future__ import annotations

from typing import Any

from app.pipeline.amazon_export.context import AmazonExportContext


def write_fill_values(ctx: AmazonExportContext) -> list[str]:
    from app.pipeline import step10_amazon_template as legacy

    missing_columns: list[str] = []
    for attr, value in ctx.fill.items():
        if attr not in ctx.columns:
            missing_columns.append(attr)
            continue
        legacy._set(ctx.worksheet, ctx.columns, ctx.data_row, attr, value)
    return missing_columns


def finalize_warnings(ctx: AmazonExportContext, missing_columns: list[str]) -> None:
    from app.pipeline import step10_amazon_template as legacy

    if missing_columns:
        ctx.warnings.append(f"模板中未找到 {len(missing_columns)} 个预期字段: {', '.join(missing_columns[:5])}")
    ctx.warnings.extend(legacy._listing_template_warnings(ctx.product_data))
    ctx.warnings.extend(legacy._pricing_template_warnings(ctx.product_data))
    ctx.warnings.extend(legacy._inventory_template_warnings(ctx.product_data))
    ctx.warnings.extend(legacy._aplus_template_warnings(ctx.product))
    ctx.warnings.extend(legacy._step6_main_image_warnings(ctx.product))
    ctx.warnings = list(dict.fromkeys(ctx.warnings))


def build_fill_summary(ctx: AmazonExportContext, missing_columns: list[str]) -> dict[str, Any]:
    from app.pipeline import step10_amazon_template as legacy

    return legacy._build_fill_summary(
        ctx.mapping,
        ctx.fill,
        ctx.columns,
        ctx.warnings,
        missing_columns,
        ctx.uploaded_images,
    )

