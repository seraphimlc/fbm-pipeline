from __future__ import annotations

from app.pipeline.amazon_export.context import AmazonExportContext


def apply_package_fill(ctx: AmazonExportContext) -> None:
    if not ctx.package:
        return
    package_fields = ctx.mapping["package_fields"]
    ctx.fill.update({
        package_fields["length_value"]: ctx.package["length"],
        package_fields["length_unit"]: "Inches",
        package_fields["width_value"]: ctx.package["width"],
        package_fields["width_unit"]: "Inches",
        package_fields["height_value"]: ctx.package["height"],
        package_fields["height_unit"]: "Inches",
        package_fields["weight_value"]: ctx.package["weight"],
        package_fields["weight_unit"]: "Pounds",
    })

