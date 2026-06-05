from __future__ import annotations

from app.pipeline.amazon_export.context import AmazonExportContext


def apply_image_fill(ctx: AmazonExportContext) -> None:
    from app.pipeline import step10_amazon_template as legacy

    image_fill, image_warnings, uploaded_images = legacy._upload_listing_images(
        ctx.product,
        ctx.product_data,
        ctx.mapping,
        ctx.existing_image_urls,
    )
    ctx.fill.update(image_fill)
    ctx.warnings.extend(image_warnings)
    ctx.uploaded_images = uploaded_images

