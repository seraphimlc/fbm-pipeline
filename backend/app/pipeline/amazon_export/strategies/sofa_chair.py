from __future__ import annotations

from app.pipeline.amazon_export.context import AmazonExportContext


def apply_sofa_chair_strategy(ctx: AmazonExportContext) -> None:
    from app.pipeline import step10_amazon_template as legacy

    pd = ctx.product_data
    fields = ctx.fields
    category_option, category_warnings = legacy._apply_furniture_category_fill(ctx.fill, ctx.mapping, pd)
    ctx.warnings.extend(category_warnings)
    seating = legacy._estimated_sofa_seating_capacity(pd)
    if category_option and category_option.get("product_type") == "CHAIR" and not seating:
        seating = 1
    if seating is None:
        ctx.warnings.append("未能从标题/描述识别座位数，Seating Capacity 暂未填写。")
    product_type = (category_option or {}).get("product_type")
    material = legacy._material_value(pd)
    frame_material = legacy._frame_material_value(pd)
    ctx.fill.update({
        fields["material"]: material,
        fields["fabric_type"]: legacy._fabric_value(pd),
        fields["color"]: pd.color,
        fields["size"]: f'{pd.dimension_length:g}" x {pd.dimension_width:g}" x {pd.dimension_height:g}"'
        if pd.dimension_length and pd.dimension_width and pd.dimension_height else None,
        fields["number_of_pieces"]: 1,
        fields["part_number"]: pd.item_code,
        fields["is_fragile"]: "No",
        fields["frame_material"]: frame_material,
        fields["frame_material_structured"]: frame_material,
        fields["unit_count"]: 1,
        fields["unit_count_type"]: "Count",
        fields["seat_depth"]: legacy._seat_depth(pd),
        fields["seat_depth_unit"]: "Inches",
        fields["seat_height"]: 16,
        fields["seat_height_unit"]: "Inches",
        fields["weight_capacity_maximum"]: legacy._weight_capacity_maximum(seating, pd),
        fields["weight_capacity_maximum_unit"]: "Pounds",
        fields["maximum_weight_recommendation"]: legacy._weight_capacity_maximum(seating, pd),
        fields["maximum_weight_recommendation_unit"]: "Pounds",
        fields["depth_value"]: pd.dimension_width,
        fields["depth_unit"]: "Inches",
        fields["height_value"]: pd.dimension_height,
        fields["height_unit"]: "Inches",
        fields["width_value"]: pd.dimension_length,
        fields["width_unit"]: "Inches",
        fields["item_width_value"]: pd.dimension_length,
        fields["item_width_unit"]: "Inches",
        fields["item_length_value"]: pd.dimension_width,
        fields["item_length_unit"]: "Inches",
    })
    legacy._fields(ctx.fill, fields, "item_shape", legacy._semantic_values_from_listing_check(pd, "item_shape"))
    legacy._fields(
        ctx.fill,
        fields,
        "included_components",
        legacy._semantic_values_from_listing_check(pd, "included_components"),
    )
    if seating:
        ctx.fill[fields["seating_capacity"]] = seating
    if product_type == "CHAIR":
        legacy._omit_fields(ctx.fill, fields, (
            "number_of_pieces",
            "seating_capacity",
            "weight_capacity_maximum",
            "weight_capacity_maximum_unit",
            "item_length_value",
            "item_length_unit",
        ))
    if pd.weight:
        ctx.fill[fields["item_weight_value"]] = pd.weight
        ctx.fill[fields["item_weight_unit"]] = "Pounds"
