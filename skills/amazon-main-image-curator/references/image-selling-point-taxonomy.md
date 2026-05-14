# Image Selling Point Taxonomy

## Listing Intent Extraction

From title and five bullets, identify:

- Product identity: noun, variant, model, color, material, size, pack count.
- Buyer problem: organize, protect, decorate, repair, store, clean, cook, carry, fit, replace, gift, etc.
- Objective visible claims: shape, color, quantity, visible parts, texture, included accessories, dimensions if printed.
- Caution claims: waterproof, load bearing, safety, medical, certification, durability, compatibility, performance, age suitability, or any claim the image cannot prove alone.

## Selling Point Labels

Use concise normalized labels:

- product_identity
- full_set_or_quantity
- color_variant
- size_or_scale
- dimension_information
- material_or_texture
- construction_detail
- core_function
- usage_scenario
- installation_or_setup
- storage_or_portability
- package_contents
- compatibility_or_fit
- comparison_or_before_after
- care_or_cleaning
- gift_or_aesthetic
- low_value_or_duplicate
- irrelevant_or_wrong_product

## Image Type Labels

- white_background_product
- full_set
- alternate_angle
- lifestyle
- dimension
- detail
- function
- installation
- comparison
- packaging
- infographic
- duplicate
- low_quality
- irrelevant

## Conversion Role Labels

- click
- confirm_product
- explain_size
- prove_material
- show_use
- remove_risk
- show_package
- explain_installation
- no_useful_role

## Evidence Discipline

Tie each visible selling point to either direct image evidence or title/bullet evidence. If an image suggests but does not prove a claim, mark it in `uncertainty` and avoid using it as a decisive reason.
