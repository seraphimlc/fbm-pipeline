from __future__ import annotations

from app.pipeline.amazon_export.context import AmazonExportContext


def apply_storage_furniture_strategy(ctx: AmazonExportContext) -> None:
    from app.pipeline import step10_amazon_template as legacy

    ctx.warnings.extend(
        legacy._apply_general_template_fill(ctx.fill, ctx.fields, ctx.mapping, ctx.product_data)
    )
    # Category-specific dropdown decisions are produced by the pre-export
    # semantic analysis and must be copied verbatim from its allow-list.
    for key in ("special_features", "shelf_type"):
        values = legacy._semantic_values_from_listing_check(ctx.product_data, key)
        legacy._fields(ctx.fill, ctx.fields, key, values)

    # The gate branch requires an explicit compliance declaration. The user
    # approved Not Applicable as the standard value for this field.
    option = legacy._select_general_category_option(ctx.mapping, ctx.product_data)
    if option and option.get("product_type") == "TEMPORARY_GATE":
        target = ctx.fields.get("required_product_compliance_certificate")
        if target:
            ctx.fill[target] = "Not Applicable"
