from __future__ import annotations

from app.pipeline.amazon_export.context import AmazonExportContext


def apply_storage_furniture_strategy(ctx: AmazonExportContext) -> None:
    from app.pipeline import step10_amazon_template as legacy

    ctx.warnings.extend(
        legacy._apply_general_template_fill(ctx.fill, ctx.fields, ctx.mapping, ctx.product_data)
    )

