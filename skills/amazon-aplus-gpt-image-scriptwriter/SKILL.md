---
name: amazon-aplus-gpt-image-scriptwriter
description: Convert Amazon A+ Image Planner outputs into production-ready GPT Image generation scripts. Use when Codex needs to read `image analysis/aplus_image_plan.md` or `.json`, preserve product identity anchors and reference-image evidence, write five detailed image prompts with on-image copy guidance, negative constraints, aspect ratio/size notes, and save `gpt_image_scripts.md` plus `gpt_image_scripts.json` into the same product ID folder for later image generation.
---

# Amazon A+ GPT Image Scriptwriter

## Single-Product Red Lines

This workflow is single-product only.

Absolute red lines:

- Each run may read, analyze, write files, or update Excel for exactly one product ID.
- Do not batch write scripts for multiple workbook rows.
- Do not scan all product folders in the workbook directory.
- Do not count images across multiple products.
- Do not generate or consume a multi-product `product_index`.
- When selecting the next row to process, read only Excel row data and `当前工作节点`; do not access other product folders.
- After one product ID is determined, read only that ID's `image analysis` folder and write only that ID's script files.

## Workbook Status Contract

When working from an Excel workbook, update only the corresponding row.

- On success, set `当前工作节点` to `8-A Scriptwriter`.
- Add `A+生图脚本文件` with the absolute path to `gpt_image_scripts.md`.
- Optionally add `A+生图脚本摘要` as a short row-level summary.
- If the run fails or upstream inputs are missing, add or update `处理备注` on the same row with a concise Chinese summary.
- Do not store full prompts in Excel cells by default.

## Role

Turn A+ image planning into usable GPT Image scripts. This skill is the final writing step before actual image generation.

Do not redo the upstream strategy. Amazon A+ Image Planner decides what each A+ image must prove. This skill translates that plan into clear, controlled, visually specific generation scripts that keep the product recognizable, avoid unsupported claims, and produce Amazon-ready A+ creative directions.

Think as:

- Image prompt director: camera, composition, light, product position, action, materials, environment, realism.
- Amazon conversion editor: one-image-one-message, mobile readability, truthful visual proof, low text density.
- Product accuracy guard: preserve product form, proportions, color, parts, and constraints from upstream references.

## Chain Position

Use this after:

1. `Amazon Listing Copywriter`: produces final title and five bullets.
2. `Amazon Main Image Curator`: exports product-folder image analysis and `aplus_planner_input.md/json`.
3. `Amazon A+ Image Planner`: exports `aplus_image_plan.md/json`.
4. `Amazon A+ GPT Image Scriptwriter`: writes final GPT Image scripts.

## Inputs

Preferred input:

- Product ID folder containing `image analysis/aplus_image_plan.md` or `image analysis/aplus_image_plan.json`.
- Same folder may also contain `aplus_planner_input.md/json`, `image_selling_points.json`, and `gallery_selection.md`; read these only when product form, reference usage, or existing image coverage is unclear.
- Listing title and five bullets from Amazon Listing Copywriter, pasted by the user or present in the planning file.

Direct chat input is acceptable when the user pastes the A+ plan.

Input priority:

1. `aplus_image_plan.json` for structured fields.
2. `aplus_image_plan.md` for human-readable plan.
3. `aplus_planner_input.json/md` for product/reference anchors if plan details are thin.
4. Listing title/five bullets for product truth and claim boundaries.

If critical product-form details are missing, write conservative scripts and mark the uncertainty. Do not invent dimensions, certifications, waterproof ratings, medical effects, load capacity, compatibility, materials, included parts, or performance numbers.

## Outputs

For product-folder workflows, write:

```text
<folder_id>/image analysis/
├── gpt_image_scripts.md      # primary human-readable script output
└── gpt_image_scripts.json    # machine-readable script output
```

If updating Excel is part of the task, add only lightweight columns:

- `A+生图脚本文件`: absolute path to `gpt_image_scripts.md`.
- Optional `A+生图脚本摘要`: short status/coverage summary.

Do not store full prompts in Excel cells by default.

## Script Principles

- Each script must follow the A+ Planner's role and conversion task.
- Each image script must be independently copyable into GPT Image. Do not rely on the reader also copying global notes from the top of the file.
- Repeat the necessary product facts, reference-image instructions, scene requirements, global anchors, text-overlay rules, and negative constraints inside every single image prompt.
- Keep the product instantly recognizable and accurate, but choose product size and placement by the image's conversion task. Lifestyle and emotional scenes may use a wider composition when the product remains clearly readable.
- Use scenario proof rather than decorative lifestyle staging.
- Respect product anti-deformation anchors: shape, openings, handle count, transparent areas, folds, buckles, connectors, thickness, texture boundaries, proportions, visible parts.
- Use reference images as product-form and proof anchors, not as layouts to copy blindly.
- Do not lose reference-image evidence. Every image script should include the exact reference images needed for that image's task, usually 1 or more when available, with label, slot if known, filename, absolute path, intended use, details to preserve, and details not to copy. Do not force two references when one strong reference is enough.
- Avoid repeating current MAIN/supporting gallery images unless the A+ plan explicitly deepens that message.
- Make the image readable on mobile: one dominant subject, one main action/result, low visual clutter.
- Prefer realistic human hands/body interaction over model-like posing. When the A+ plan uses people, hands, children, drivers, sitters, installers, or caregivers to prove the selling point, write them as mandatory scene elements, not optional atmosphere. Use faces only when emotion proves the result.
- On-image copy is allowed when it improves A+ readability: short headline, short selling-point phrase, and simple feature icons are acceptable. The image should still work without relying on dense text.
- Do not add any brand name, store name, brand wordmark, brand logo, or decorative brand label into the image, even if a brand appears in the listing title or workbook.
- Avoid brand logos, brand names, Amazon logos, fake badges, seals, awards, certifications, prices, star ratings, review quotes, QR codes, URLs, dense labels, tiny unreadable icons, thin arrows, exaggerated before/after, or unsupported claims.

## Workflow

### 1. Load The A+ Plan

Identify the five planned images and extract for each:

- Image role.
- Conversion task.
- Main selling point.
- Buyer pain or doubt.
- Scenario.
- Reference-use note.
- Existing-gallery handoff.
- Must-show elements.
- Image requirements.
- Negative constraints.
- One-second check.

If a planned image lacks a clear product action or visual proof, strengthen the scene while preserving the original conversion task.

### 2. Build Product Accuracy Guardrails

Before writing prompts, create a compact guardrail list:

- Product identity: exact product noun, variant, color, material, quantity, included parts.
- Form anchors: shape, proportions, openings, handles, attachments, fold lines, transparent/opaque areas, texture, edge finish.
- Scale anchors: hands, countertop, drawer, suitcase, car seat, body, common objects, or other truthful reference objects.
- Reference anchors: which visual details must be preserved or loosely borrowed.
- Claim limits: what cannot be shown or implied.

These guardrails apply to every image unless a specific script says otherwise.

Then push these guardrails down into every image script. The top-level guardrails are useful for review, but the per-image `prompt`, `global_anchors`, `must_preserve`, and `negative_constraints` fields are the operational source for generation.

### 2.5 Select Reference Images Per Script

For each A+ image, select reference images from upstream data by the role of that specific image, not by a fixed count:

- Use one reference when it sufficiently protects product form, material, action, or detail for the image.
- Use two or more references only when different references are truly needed, such as exact product form plus lifestyle usage, texture plus scale, or dimension proof plus installed/opened state.
- Do not automatically use the main product-identity image as Reference A for every script. Choose Reference A as the strongest visual anchor for that image's conversion task.
- For lifestyle, emotional-result, or real-use scenes, prioritize lifestyle, human, hands, action, posture, room, or usage-state references as the first reference when available; add a product identity reference only if product deformation risk is high.
- For detail, material, mechanism, or quality-proof images, prioritize close-up/detail/material references.
- For scale, capacity, size, or dimension images, prioritize side-view, dimension, scale-object, body/hand, capacity, or layout references.
- Avoid repeating the same reference pair across all five images unless the product folder truly has no better evidence; if repeated, explain why in QA.
- If only one good reference exists, use one and say what it protects.
- If no usable reference exists, write `reference_images: []` and explicitly state the missing reference risk in QA.

For each reference image, preserve:

- `label`: `A`, `B`, etc.
- `slot`: selected gallery slot if known, otherwise `null`.
- `filename`.
- `path`: absolute path to the source image.
- `use_for`: exact reason, such as `exact product form`, `fabric texture`, `dimension proof`, `usage posture`, `living room scene`.
- `preserve`: concrete visual details to keep.
- `avoid_copying`: text overlays, icons, unsupported claims, clutter, non-included props, layout gimmicks.
- `path_exists`: true/false when known.

The generated prompt must include a `References:` section that names every selected reference image and explains how to use each. Use them as visual references, not as a collage.

Also assign a distinct camera/composition role to each script:

- Image 1 core scene: wide lifestyle 3/4 or environmental angle, with real use when the plan calls for it.
- Image 2 pain/workflow: split-view, overhead, process angle, or problem-to-solution composition.
- Image 3 detail proof: macro, close-up, hand interaction, or tight functional crop with context.
- Image 4 scale/material/quantity: side view, orthographic, dimension-style, scale-object, or body/hand scale proof.
- Image 5 emotional outcome: wider lifestyle, over-shoulder, natural usage moment, or finished-result scene.

Do not use these as rigid labels; use them to prevent five outputs from collapsing into the same front-facing product angle.

### 3. Write One Self-Contained Production Script Per A+ Image

For each of the five images, write:

- `image_no`: 1 to 5.
- `image_title`: short Chinese image role name from the plan.
- `reference_images`: selected references with path and usage details; usually 1 or more when available, not fixed to two.
- `prompt`: one complete copy-paste-ready GPT Image prompt.
- `prompt_zh_summary`: one-line Chinese summary for operators.
- `global_anchors`: the global product anchors repeated for this image.
- `must_preserve`: product facts and reference-derived details that must remain correct.
- `scene_requirements`: concrete scene/action/result to create.
- `composition_requirements`: output size, banner shape, hierarchy, mobile readability.
- `lighting_and_style`: realistic ecommerce lighting and category style.
- `text_overlay_rules`: allow controlled short A+ headline/selling-point copy and simple feature icons; forbid brand names, brand wordmarks, logos, fake badges, prices, ratings, QR codes, URLs, dense text, and unreadable labels.
- `negative_constraints`: global negatives plus image-specific avoid list.
- `output_size`: default `1940 x 1200` for historical Amazon A+ horizontal scripts unless the user provides another target or the generation tool requires a different multiple.
- `one_second_goal`: what the buyer should understand instantly.
- `buyer_doubt`: buyer hesitation reduced by this image.
- `selling_point`: one primary selling point.
- `status`: `ready` when complete, otherwise `needs_input`.

Prompts should be specific enough for image generation, but not overloaded with unrelated details. The first sentence should name the product and the exact scene. Later sentences should control composition, material, action, lighting, and text behavior.

Use this prompt skeleton for every image:

```text
Create one photorealistic Amazon A+ ecommerce image at exactly [OUTPUT SIZE] pixels, wide horizontal banner composition, premium but realistic commercial product photography.

Product:
[Full product title]. Product facts and attributes: [variant, color, material, dimensions, quantity, included parts, supported claims].

References:
Use the attached reference images only as visual references, not as a collage:
[List each selected reference image A, B, C... only when selected. For each: use it for [use_for]. Preserve: [details]. Do not copy: [avoid].]

Scene:
- A+ image role: [role].
- Primary selling point to prove: [selling point].
- Buyer doubt to reduce: [buyer doubt].
- Scenario to create: [specific scene].
- Main subject/action and must-show elements: [elements].

Output size requirement: [OUTPUT SIZE] pixels.

Composition:
Make the product recognizable and accurate on mobile; choose scale, placement, and camera angle according to this image's role. Use a clean ecommerce layout with one dominant idea; show real action, scale, material, or outcome instead of decorative posing. Use camera angle, framing, foreground/background, and optional clean negative space to support the one selling point. If the scene requires people, hands, children, drivers, sitters, installers, or caregivers, they must appear naturally in the action and must not be treated as optional background.

Lighting and style:
Use realistic natural or soft studio-commercial light, accurate product color, category-appropriate mood, sharp texture detail, believable shadows, and no overly cinematic darkness.

Constraints:
- Global product anchors to preserve in this image: [anchors].
- Do not change or invent product facts. Avoid: [global and image-specific negatives].
- Additional image-specific avoid list: [specific negatives].
- Text overlay rule: controlled short A+ headline copy, short feature phrases, and simple feature icons are allowed when they support the one selling point. Do not render any brand name, store name, brand wordmark, brand logo, Amazon logo, fake badge, certification seal, price, discount, star rating, review quote, QR code, URL, dense text, tiny label, or fake claim. Leave clean negative space when later design copy may be added; dimension markers are acceptable when the image purpose is size proof.
- Product faithfulness rule: stay as close as possible to the actual product and do not add extra parts, accessories, components, or bundled items that could mislead buyers.

One-second takeaway:
[one-second goal].
```

### 4. Write Negative Constraints

Include global and per-image negatives. Be explicit:

- Wrong product shape, wrong color, missing key part, extra accessory not included.
- Product hidden, too small, cropped, blurred, warped, melted, floating, or fused with props.
- Unrealistic hand anatomy, unsafe use, impossible installation, wrong scale.
- Overly cinematic darkness, excessive depth of field, heavy blur, artificial luxury props.
- Fake certification badges, warranty seals, star ratings, review quotes, price, discount, Amazon logos, competitor logos, brand names, brand wordmarks, brand logos, QR codes, URLs.
- Dense text, tiny unreadable icons, thin arrows, cluttered callouts, unreadable labels.

### 5. Final QA

Before finalizing:

- The five scripts match the five A+ Planner roles.
- Every prompt visually proves one main selling point.
- Every script is self-contained: copying only that image's code block is enough for generation.
- Every available reference image chosen for the script appears in both `reference_images` and the prompt `References:` section.
- Every referenced image has an absolute path, intended use, preserve list, and avoid-copying list.
- The five scripts do not reuse the same reference pair by habit; repeated references are justified by product evidence needs.
- At least three distinct camera/composition types appear across the five scripts.
- If the plan calls for people/hands/body interaction, the prompt makes them mandatory and scene-specific.
- Product identity and anti-deformation anchors are repeated where needed.
- Global anchors and global negative constraints are repeated inside each script, not only at the file top.
- Existing gallery coverage is not merely duplicated.
- On-image copy, when used, is short, truthful, A+ appropriate, and not required for basic understanding; simple feature icons are allowed only when they improve one-second readability; no brand name or brand mark appears in the image.
- At least one script shows real use.
- At least one script supports value/material/size/capacity trust.
- No unsupported claim, certification, rating, guarantee, medical effect, or exact number is introduced.
- Prompts are ready to paste into GPT Image or a batch generation workflow.

## Output Format

Use Chinese operator notes by default. Use English for the actual `prompt` fields unless the user asks otherwise.

```markdown
# A+ 生图脚本

- Product ID:
- Model target: gpt-image
- Scripts: 5/5 ready

## 图 1：...
- 状态：ready
- 引用参考图（按本图需求选择，不固定两张）：
  - A｜slot ...｜filename｜/absolute/path｜用途：...
  - B｜slot ...｜filename｜/absolute/path｜用途：...
- 表达卖点：
- 买家疑虑：
- 一秒理解：

```text
[complete self-contained prompt]
```
```

Machine-readable JSON shape:

```json
{
  "schema": "amazon-aplus-gpt-image-scriptwriter.v1",
  "source_skill": "amazon-aplus-gpt-image-scriptwriter",
  "product_id": "",
  "row_number": "",
  "model_target": "gpt-image",
  "script_count": 5,
  "ready_count": 5,
  "global_product_anchors": [],
  "global_negative_constraints": [],
  "scripts": [
    {
      "image_no": 1,
      "image_title": "",
      "reference_images": [
        {
          "label": "A",
          "slot": null,
          "filename": "",
          "path": "",
          "use_for": "",
          "preserve": [],
          "avoid_copying": [],
          "multimodal_result": {},
          "path_exists": true
        }
      ],
      "prompt": "",
      "prompt_zh_summary": "",
      "global_anchors": [],
      "must_preserve": [],
      "scene_requirements": "",
      "composition_requirements": "",
      "lighting_and_style": "",
      "text_overlay_rules": "",
      "negative_constraints": [],
      "output_size": "1940 x 1200",
      "one_second_goal": "",
      "buyer_doubt": "",
      "selling_point": "",
      "status": "ready"
    }
  ]
}
```
