from __future__ import annotations

from app.pipeline.amazon_export.context import AmazonExportContext


def apply_bicycle_strategy(ctx: AmazonExportContext) -> None:
    from app.pipeline import step10_amazon_template as legacy

    ctx.warnings.extend(
        legacy._apply_bicycle_fill(ctx.fill, ctx.fields, ctx.product, ctx.product_data, ctx.mapping)
    )

