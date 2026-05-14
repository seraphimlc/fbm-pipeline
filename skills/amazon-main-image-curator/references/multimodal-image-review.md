# Multimodal Contact-Sheet Review

## Review Order

Analyze the high-resolution contact sheet, not the individual source files, unless the user explicitly asks for a second pass.

For each numbered tile:

1. Match product identity against title/bullets.
2. Identify whether it is eligible for slot `01`.
3. Describe what is visibly present.
4. Classify image type and visible selling point.
5. Identify conversion role.
6. Record risk flags.
7. Mark uncertainty instead of guessing.
8. Assign slot `01` score and gallery conversion score.

## Inspect First

- Product type, shape, variant, color, quantity, and included parts.
- Background, props, text overlays, watermarks, logos, badges, callouts, collage panels.
- Crop, blur, resolution impression, lighting, and whether the product fills the frame.
- Visible dimensions, texture, finish, connectors, seams, accessories, packaging, or use process.
- Whether the same selling point appears in clearer duplicate images.

## Do Not Infer

Do not infer material, waterproofing, load capacity, compatibility, certification, age range, safety, battery life, or package contents unless visible or supported by title/bullets. Use "unclear" wording for contact-sheet details that cannot be read.

## Required Per-Image Object

```json
{
  "image_id": "#01",
  "filename": "source.jpg",
  "multimodal_result": {
    "visual_summary": "",
    "product_angle": "",
    "product_state": "",
    "color_reading": "",
    "size_scale_cues": "",
    "visible_parts": "",
    "completeness": "",
    "material_texture": "",
    "scene_type": "",
    "background_props": "",
    "text_graphics": "",
    "aplus_reference_value": "",
    "confidence": "high|medium|low",
    "uncertainty": []
  },
  "contact_sheet_evidence": {
    "sheet_path": "",
    "sheet_page": 1,
    "sheet_label": "#01"
  },
  "image_type": "",
  "visible_selling_point": "",
  "matched_title_bullet_evidence": "",
  "conversion_role": "",
  "risk_flags": [],
  "slot01_score": 0,
  "gallery_score": 0,
  "decision_reason": ""
}
```
