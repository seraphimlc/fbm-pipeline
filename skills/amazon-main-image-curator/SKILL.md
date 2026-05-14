---
name: amazon-main-image-curator
description: Analyze Amazon supplier product images from Excel-linked ID folders, cache multimodal contact-sheet judgments, select compliant MAIN and supporting gallery images, write full image-selling-point analysis into each product ID folder, keep only lightweight paths/summaries in Excel, and copy selected 01-09 gallery candidates without modifying originals.
---

# Amazon Main Image Curator

## Single-Product Red Lines

This workflow is single-product only.

Absolute red lines:

- Each run may read, scan, analyze, build contact sheets, copy images, write files, or update Excel for exactly one product ID.
- Do not scan all product folders in the workbook directory.
- Do not count images across multiple products.
- Do not generate a multi-product `product_index.json`.
- When selecting the next row to process, read only Excel row data and `当前工作节点`; do not access other product folders.
- After one product ID is determined, every script, index, contact sheet, analysis file, copied image folder, and workbook update must contain only that ID.
- If an input index or decisions file contains more than one product, stop and report the red-line violation instead of continuing.

## Workbook Status Contract

When working from an Excel workbook, update only the corresponding row.

- On success, set `当前工作节点` to `6-图片分析`.
- Keep Excel lightweight with path and summary columns only.
- If a run fails, add or update `处理备注` on the same row with a concise Chinese error summary.
- Do not store full multimodal image analysis or full gallery JSON in Excel cells by default.

## Overview

Use this skill as an Amazon senior-operator workflow for product-image analysis and gallery selection. Treat "main image" in local folder names as the full Amazon gallery set: slot `01` is the search-result MAIN image candidate, and `02`-`09` are supporting gallery images that reduce doubt and increase purchase intent.

## Core Rules

- Never move, rename, overwrite, or delete original supplier images.
- Product-image selling points must come from structured multimodal review over high-resolution contact sheets for each product folder. Build contact sheets in batches of 9 source images by default so each tile remains large enough to inspect product details and text overlays.
- Cache the multimodal result for every image in run JSON first, then export full per-product text/JSON files into each ID-named product folder. Downstream gallery selection, A+ planning, and prompt writing must read this cached text/JSON instead of reopening the same images.
- Do not run a second per-image multimodal pass by default. Use the 9-image contact sheets as the primary vision input; if a detail is still unclear, record the uncertainty and decide from sheet evidence plus title/bullet evidence.
- Always separate compliance from conversion: a persuasive image can still be rejected from slot `01` if it violates MAIN image rules.
- Do not invent product features from an image. Mark unclear details as uncertain and prefer title/bullet evidence.
- Rank fewer than 9 images when assets are weak, repetitive, or misleading.
- Preserve traceability: every selected image must record original path, selected slot, score, and reason in product-folder analysis files and manifests. Excel should only keep file paths and short summaries by default.
- Before high-stakes upload work, verify current Amazon category-specific image rules from official Seller Central or category style guides.

## References

Read only the references needed for the current step:

- `references/main-image-rubric.md`: scoring, hard rejects, user-mindset rules, slot 1 vs slots 2-9 strategy.
- `references/image-selling-point-taxonomy.md`: extract listing claims and classify each image's selling point.
- `references/multimodal-image-review.md`: contact-sheet review directions and required per-image judgment order.
- `references/excel-schema.md`: input columns, product-folder output files, lightweight Excel columns, and decision JSON schema.

## Workflow

### 1. Locate The Workbook And Image Root

Identify the Excel workbook containing product rows. The image root is usually the workbook's sibling directory or the directory containing ID-named folders. Product folders are matched from the final ID in the warehouse URL column.

Run for exactly one row or one product ID:

```bash
python3 scripts/scan_workbook.py --workbook "/path/to/products.xlsx" --image-root "/path/to/image/root" --row-number 12
```

or:

```bash
python3 scripts/scan_workbook.py --workbook "/path/to/products.xlsx" --image-root "/path/to/image/root" --folder-id "123456"
```

The script creates a run folder with:

- `product_index.json`: product rows, URL-derived IDs, matched folders, image metadata, hashes, and dimensions.
- `analysis_decisions_template.json`: empty template for image selling-point analysis and gallery selection.

If folder matching fails, inspect `match_status` and repair the workbook ID/URL or pass the correct image root.

### 2. Build High-Resolution Contact Sheets

Create labeled high-resolution contact sheets so each product image set can be reviewed in clear multimodal batches:

```bash
python3 scripts/build_contact_sheets.py --index "/path/to/product_index.json"
```

Defaults: up to 9 source images per sheet, 720px tile, 72px label area, 3 columns, JPEG quality 94. Use `contact_sheets/contact_sheets_index.json` as the primary multimodal input. Sheet labels `#01`, `#02`, etc. map back to original files in the manifest and `product_index.json`.

For folders with more than 9 images, keep the split sheets and analyze each sheet in order. Do not combine all images into one oversized sheet. If small text or material detail matters more, increase `--thumb-size 800`; only increase `--max-per-sheet` when the user explicitly prefers fewer files over visual clarity.

### 3. Optional: Build Multimodal Upload Cache

Only create resized single-image copies when the user asks for per-image upload files or when contact sheets are not accepted by the model/API:

```bash
python3 scripts/build_multimodal_upload_cache.py --index "/path/to/product_index.json"
```

This keeps supplier images unchanged. The cache is only an alternate model-vision input; original paths remain the traceability source.

### 4. Extract Listing Intent

For each product, summarize from title and five bullets:

- Exact product type, quantity, color, size, and variant.
- Core problem the buyer expects it to solve.
- Objective claims visible in images.
- Claims that require caution because images cannot prove them.

Use `image-selling-point-taxonomy.md` to normalize selling point names.

### 5. Analyze Every Image From Contact Sheets

Use `multimodal-image-review.md` when opening the high-resolution contact sheets with a multimodal model. Analyze every generated sheet, normally 9 images per sheet, then combine those cached judgments before selecting the final 01-09 gallery. First verify product identity against title and bullets, then inspect compliance risks, visible selling points, conversion role, duplication, and missing buyer-answering images.

For every image, write into the decisions JSON:

- `multimodal_result`: visual summary, product angle, state, color reading, scale cues, parts, completeness, material/texture, scene type, background/props, text/graphics, A+ reference value, confidence, uncertainty.
- `contact_sheet_evidence`: sheet path, sheet page, and sheet label such as `#01`.
- `image_type`, `visible_selling_point`, `matched_title_bullet_evidence`, `conversion_role`, `risk_flags`.

Keep Chinese operator-facing wording concise but specific. The `multimodal_result` object is the cached visual truth for downstream skills, even when the image is rejected.

### 6. Select The 1-9 Gallery

Use `main-image-rubric.md`.

- Slot `01`: strongest compliant MAIN candidate. Prioritize exact product identity, clean white background, no text/logo/watermark/props, full product, clarity, thumbnail presence, and title/variant match.
- Slots `02`-`09`: build a conversion story. Prefer full set/alternate angle, size/scale, material/detail, core function, usage scenario, installation/fold/storage, comparison/proof, package/accessories.
- Avoid near-duplicates. If two images express the same point, keep the clearer one.
- If assets cannot support a slot, leave it empty and write what image should be produced.
- Select and order the gallery from cached contact-sheet multimodal JSON. Do not spend a second full multimodal pass on the copied gallery set.

### 7. Export Product-Folder Analysis And Lightweight Excel Links

After decisions are complete, export full analysis files into each matched ID folder and write only lightweight links/summaries into the workbook:

```bash
python3 scripts/write_image_analysis.py --workbook "/path/to/products.xlsx" --index "/path/to/product_index.json" --decisions "/path/to/analysis_decisions.json"
```

By default this saves a new workbook named `_image_analysis_YYYYmmdd_HHMMSS.xlsx`. Use `--in-place` only when the user explicitly wants the original workbook updated; the script still creates a timestamped backup first.

For each matched product folder, create:

- `image analysis/image_selling_points.json`: authoritative full cached image review.
- `image analysis/image_selling_points.md`: human-readable per-image selling-point analysis.
- `image analysis/gallery_selection.md`: selected `01`-`09` gallery slots and reasons.
- `image analysis/aplus_planner_input.json`: structured downstream input for Amazon A+ Image Planner.
- `image analysis/aplus_planner_input.md`: concise downstream input for Amazon A+ Image Planner.

The source product sheet should only include lightweight columns:

- `图片分析文件夹`: path to the product-folder analysis output.
- `A+图片规划输入文件`: path to `aplus_planner_input.md`.
- `图片卖点摘要`: short human-readable Chinese summary.
- `主图选择摘要`: short selected-gallery summary.

Do not write full per-image multimodal JSON into Excel cells unless the user explicitly asks for an Excel-only artifact.

### 8. Create `new main image` Folders

Copy selected images into each matched product folder:

```bash
python3 scripts/copy_main_candidates.py --index "/path/to/product_index.json" --decisions "/path/to/analysis_decisions.json"
```

The script creates `new main image` inside each matched ID folder, copies selected images, renames them as `01.ext` to `09.ext`, and writes `selection_manifest.json` plus `selection_manifest.xlsx`. If `new main image` already exists and contains files, the script renames it to a timestamped backup folder before creating a fresh one.

## Final QA

Before reporting, check:

- Every product row has a matched folder or a clear missing-folder note.
- Each image has a selling-point judgment or a clear rejection reason.
- Slot `01` never uses text, lifestyle scenes, non-included props, wrong variants, or unclear product photos unless current category rules explicitly allow it.
- Slots `02`-`09` answer buyer questions instead of repeating the same angle.
- Excel paths, product-folder analysis files, manifest, and copied folders agree on selected image order.
