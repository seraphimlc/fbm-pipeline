from __future__ import annotations

from app.pipeline.amazon_export.context import AmazonExportContext


def apply_offer_fill(ctx: AmazonExportContext) -> None:
    from app.pipeline import step10_amazon_template as legacy

    pd = ctx.product_data
    fields = ctx.fields
    shipping_template = legacy._shipping_template_for_product(
        ctx.workbook,
        fields["shipping_template"],
        ctx.mapping,
        ctx.product,
        ctx.warnings,
    )
    stock_quantity = legacy._offer_quantity(pd)

    ctx.fill.update({
        fields["list_price"]: pd.suggested_price,
        fields["fulfillment_channel"]: "Fulfillment by Merchant (Default)",
        fields["quantity"]: stock_quantity,
        fields["price"]: pd.suggested_price,
        fields["country_of_origin"]: pd.origin or "China",
        fields["shipping_template"]: shipping_template,
    })
    if fields.get("handling_time"):
        ctx.fill[fields["handling_time"]] = 1

