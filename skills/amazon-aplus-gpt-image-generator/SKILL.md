---
name: "amazon-aplus-gpt-image-generator"
description: "Generate Amazon A+ images from Amazon A+ GPT Image Scriptwriter outputs using required reference images. Use when converting `image analysis/gpt_image_scripts.json` prompts and their `reference_images` into real generated images through an OpenAI-compatible GPT image API; defaults to `/v1/images/generations` with `aspect_ratio=97:60`, `quality=high`, and refuses to run without existing reference images."
---

# Amazon A+ GPT Image Generator

Use this after `amazon-aplus-gpt-image-scriptwriter`.

This skill turns one Scriptwriter image script into a real generated image while preserving product identity through required reference images.

## Hard Rules

- Process one product ID and one A+ image slot at a time.
- Read only that product folder's `image analysis/gpt_image_scripts.json`.
- Reference images are mandatory, but the count is flexible. Use exactly the reference images selected by Scriptwriter for that image: one is acceptable when it is enough, two or more are acceptable when the script needs multiple anchors. Do not require exactly two.
- Do not add missing product-identity references by yourself. If the Scriptwriter selected the wrong reference direction or all five scripts repeat the same stale reference pair, regenerate or revise the Scriptwriter output first.
- Do not fall back to text-only generation.
- If any selected reference image path is missing, stop and report the missing path.
- Save generated outputs inside the product folder, matching the existing per-product gallery pattern: `<product_id>/new a plus/`.
- Do not overwrite source reference images.
- Keep the raw provider image and the final post-processed image separate.
- Default final usable size is `1940x1200`. In the default generations path, the provider returns a larger `97:60` image such as `3104x1920`, then the script locally resizes/crops to `1940x1200`.
- Do not upscale a smaller provider image to fake an Amazon-ready result. If the legacy edits path returns smaller output, fail instead of padding or inventing pixels.

## API Behavior

Default behavior uses the documented GPT image generations endpoint with JSON:

- endpoint: `/v1/images/generations`
- fields: `model`, `prompt`, `aspect_ratio`, `quality`, `n`, `response_format`, `image`
- default `aspect_ratio`: `97:60`, matching `1940x1200`
- default `quality`: `high`
- default `response_format`: `url`
- `image`: reference images embedded as base64 data URLs

The script sends every reference listed in that image script's `reference_images` array. It does not assume a fixed number of references. Reference images are downsampled before base64 embedding to keep JSON requests stable; this does not change the source files.

It reuses the API config from:

`~/.openclaw/workspace/skills/gpt-image-async/scripts/config.json`

The legacy edits path is still available with `--api-mode edits`, but it is no longer the default because testing showed `/v1/images/edits?async=true` can return smaller images around `1600x984` even when `size=1952x1200` is requested.

If the provider returns an async `task_id`, the query endpoint is:

`/v1/images/tasks/{task_id}`

If the provider does not support reference-image generations, the script will fail loudly instead of silently generating from prompt only.

By default the script uses `--text-mode minimal`, which allows controlled A+ text: short headline, 1-4 short selling-point phrases, and simple clean feature icons. It still forbids brand names, store names, brand wordmarks, brand logos, Amazon logos, fake badges, certification seals, prices, discounts, star ratings, review quotes, QR codes, URLs, dense paragraphs, and tiny unreadable labels. Use `--text-mode no-text` only when the user wants a clean image for later manual copy design, or `--text-mode none` to use the Scriptwriter prompt exactly as-is.

## Usage

Generate one A+ image from a product script:

```bash
python scripts/generate_from_aplus_script.py \
  --product-dir "/absolute/path/to/product_id" \
  --image-no 1 \
  --timeout 300
```

Optional arguments:

- `--script-json`: path to `gpt_image_scripts.json`; defaults to `<product-dir>/image analysis/gpt_image_scripts.json`
- `--output`: output image path; defaults to `<product-dir>/new a plus/a_plus_01.png`
- `--api-mode`: `generations` default, or `edits` for the older multipart async path
- `--aspect-ratio`: generations mode aspect ratio, default `97:60`
- `--quality`: generations mode quality, default `high`
- `--size`: legacy edits mode output size
- `--final-size`: final usable local output size, default `1940x1200`; use `none` to keep raw output only
- `--text-mode`: `minimal` default, `no-text`, or `none`
- `--n`: number of images, default 1
- `--workbook`: optional Excel workbook path; on success updates the matching product row to `9-A Plus Image`

## Output

The script writes:

- generated `.png` file(s)
- final Amazon-ready `.png` file(s), default `_final_1940x1200.png`, when final processing is enabled
- sidecar metadata JSON next to the output, including task id, source script, prompt, references, URLs, and provider response

Default folder pattern:

```text
<product_id>/
└── new a plus/
    ├── a_plus_01.png
    ├── a_plus_01.metadata.json
    └── a_plus_01_final_1940x1200.png
```

Use `--final-size none` only when you need the raw provider output. For Amazon A+ delivery, keep the default final file.

## Workbook Update

When `--workbook` is provided, the script updates only the matched product row:

- `当前工作节点` = `9-A Plus Image`
- `处理备注` = `A+成图完成`
- `A+成图文件` = final output path(s), or raw output path(s) if final crop is disabled
- `A+成图元数据` = sidecar metadata path

## Operator Check

After generation, open the image and check:

- product color, shape, proportions, parts, and material match references
- short A+ copy and simple feature icons are acceptable; no brand names, store names, brand wordmarks, brand logos, Amazon logos, fake badges, ratings, certifications, prices, QR codes, URLs, or dense/tiny text
- the image proves the intended A+ selling point
- the product is recognizable and readable on mobile; it does not need to be centered or oversized when a wider lifestyle/action composition better proves the point
- people, hands, children, sitters, drivers, installers, or caregivers appear when the script made them mandatory
- across a five-image set, the generated images do not collapse into the same product-only angle; if they do, revise Scriptwriter reference selection and camera directions before regenerating
