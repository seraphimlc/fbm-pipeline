from __future__ import annotations

from app.config import settings
from app.pipeline.amazon_export.context import AmazonExportContext
from app.pipeline.search_terms import normalize_search_terms


def apply_listing_fill(ctx: AmazonExportContext) -> None:
    from app.pipeline import step10_amazon_template as legacy

    product = ctx.product
    pd = ctx.product_data
    fields = ctx.fields

    ctx.fill.update({
        fields["sku"]: pd.item_code,
        fields["title"]: pd.listing_title,
        fields["brand"]: product.brand,
        fields["product_id_type"]: "UPC" if product.upc else "GTIN Exempt",
        fields["product_id_value"]: product.upc,
        fields["model_number"]: pd.item_code,
        fields["model_name"]: pd.item_code,
        fields["manufacturer"]: product.brand,
        fields["description"]: legacy._description(pd),
        fields["search_terms"]: normalize_search_terms(
            pd.listing_search_terms,
            visible_copy=" ".join([pd.listing_title or "", *ctx.bullets]),
            max_bytes=settings.STEP5_SEARCH_TERMS_MAX_BYTES,
        )[0],
    })


def apply_bullet_fill(ctx: AmazonExportContext) -> None:
    for field, bullet in zip(ctx.mapping.get("bullet_fields", []), ctx.bullets[:5]):
        ctx.fill[field] = bullet
