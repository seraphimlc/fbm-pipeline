from __future__ import annotations

from app.pipeline.amazon_export.context import AmazonExportContext


def apply_ride_on_toy_strategy(ctx: AmazonExportContext) -> None:
    from app.pipeline import step10_amazon_template as legacy

    item_type_option = legacy.select_ride_on_category(legacy._facts_text(ctx.product_data))
    if item_type_option:
        ctx.fill["item_type_keyword[marketplace_id=ATVPDKIKX0DER]#1.value"] = item_type_option.item_type_keyword
    else:
        ctx.warnings.append("未能匹配 RIDE_ON_TOY 细分类目，沿用模板默认儿童电瓶车类目。")
    ctx.warnings.extend(
        legacy._apply_ride_on_toy_fill(ctx.fill, ctx.fields, ctx.product, ctx.product_data)
    )

