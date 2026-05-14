---
name: amazon-aplus-image-planner
description: Create concise initial scripts/briefs for five Amazon A+ images from a product title, five bullet points, Amazon Listing Copywriter output, and Amazon Main Image Curator product-folder files such as `image analysis/aplus_planner_input.md` or `.json`. Use when Codex needs to analyze the product/category, extract selling points, use cached reference-image selling points and selected-gallery coverage, define visual anchors, assign each of five A+ images a scenario-led conversion purpose, write product-folder A+ planning files, and list negative constraints before later roles write polished image-generation prompts or copy.
---

# Amazon A+ Image Planner

## Single-Product Red Lines

This workflow is single-product only.

Absolute red lines:

- Each run may read, analyze, write files, or update Excel for exactly one product ID.
- Do not batch plan A+ images for multiple workbook rows.
- Do not scan all product folders in the workbook directory.
- Do not count images across multiple products.
- Do not generate or consume a multi-product `product_index`.
- When selecting the next row to process, read only Excel row data and `当前工作节点`; do not access other product folders.
- After one product ID is determined, all inputs and outputs must come from or write to that ID's `image analysis` folder only.

## Workbook Status Contract

When working from an Excel workbook, update only the corresponding row.

- On success, set `当前工作节点` to `7-A Plan`.
- Add `A+图片规划结果文件` with the absolute path to `aplus_image_plan.md`.
- Optionally add `A+图片规划摘要` as a short row-level summary.
- If the run fails or upstream inputs are missing, add or update `处理备注` on the same row with a concise Chinese summary.
- Do not store the full five-image plan in Excel cells by default.

## Core Principle

Plan images that prove selling points through scenarios. Do not make generic "premium product pictures." Every image must answer: what buyer problem does this scene prove the product solves?

Treat the five A+ images as a purchase-reason chain: help the buyer understand the product, believe the claims, remove doubts, justify value, and imagine the result after owning it.

Think from two roles at once:

- Super art director: judge composition, light, color, product beauty, texture, facial expression, realism, and whether the image would look premium in the category.
- Super Amazon operator: judge conversion logic, buyer doubts, selling-point hierarchy, one-second readability, value justification, and whether the image helps the buyer decide.

Use this priority order:

1. Selling-point scenario: the scene must directly demonstrate the main benefit.
2. Product recognizability: the buyer must instantly understand what the product is.
3. Visual evidence: show action, result, scale, quantity, material, fit, or comparison.
4. Category fit: the mood, setting, people, props, and lighting must match the product category.
5. Reference usefulness: borrow only the reference-image details that protect product accuracy or strengthen a proven feature.
6. Aesthetic polish: beauty supports proof; it must not replace proof.

## Inputs

Accept these input modes, in priority order:

1. Product ID folder workflow:
   - A product folder named by the warehouse/product ID beside the Excel workbook.
   - `image analysis/aplus_planner_input.md` or `image analysis/aplus_planner_input.json` from Amazon Main Image Curator.
   - Listing copy from Amazon Listing Copywriter, either pasted by the user or available in the workbook row.
2. Workbook row workflow:
   - Excel workbook path and target row/ID.
   - Product title and five bullets from the original row or Listing Copywriter output columns.
   - `A+图片规划输入文件` column pointing to `aplus_planner_input.md`, when available.
3. Direct chat workflow:
   - Product title.
   - Five bullet points.
   - Optional reference-image selling points.
   - Optional existing main/secondary image coverage.

Preferred upstream handoff files from Amazon Main Image Curator:

- `image analysis/aplus_planner_input.md`: concise human-readable input. Use this first when planning manually in chat.
- `image analysis/aplus_planner_input.json`: structured input. Use this when writing repeatable scripts or batch outputs.
- `image analysis/image_selling_points.json`: full image review cache. Read only when `aplus_planner_input` lacks enough detail.
- `image analysis/gallery_selection.md`: selected 01-09 coverage in operator language.

Use Amazon Listing Copywriter output as the preferred source for final title and five bullets when it is available. If both original listing copy and rewritten listing copy exist, use rewritten copy for buyer-facing selling-point hierarchy, but keep original row attributes as product-truth evidence.

Interpret upstream data as:

- Product title and five bullets: product truth and selling-point hierarchy.
- `reference_image_selling_points`: what existing product/reference images show well, such as product angle, structure, material, use action, scale, installed/opened/closed state, capacity, or detail close-up.
- `selected_gallery_coverage`: what current MAIN/supporting images already communicate, such as white-background product identity, size, included parts, usage, dimensions, comparison, packaging, or feature callouts.
- `missing_recommended_images`: proof gaps that A+ may need to solve if they matter for conversion.

If the user provides extra attributes, keywords, dimensions, variants, target marketplace, or later image references, use them as evidence. Reference count is not fixed: one strong reference can be enough, and multiple references are useful only when they each protect a different need.

If important details are missing, infer conservatively and label assumptions. Do not invent unsupported claims, certifications, capacity, compatibility, medical effects, durability ratings, or safety guarantees.

Treat reference-image selling points as helpful guidance, not hard constraints. Use them to reduce product deformation and preserve important identity details, but still redesign the five A+ images for stronger scenario proof and conversion.

Treat existing main/secondary image coverage as an information map. Avoid repeating it unless repetition is necessary for product recognition. Use A+ images to fill missing proof: deeper scenarios, buyer doubts, value feeling, emotional result, material trust, and usage confidence.

## File Output Contract

For a one-off chat request, returning the structured plan in chat is acceptable. For workbook or ID-folder workflows, write outputs into the same product folder used by Amazon Main Image Curator:

```text
<folder_id>/image analysis/
├── aplus_planner_input.md      # upstream input, read by this skill
├── aplus_planner_input.json    # upstream input, read by this skill
├── aplus_image_plan.md         # primary human-readable output from this skill
└── aplus_image_plan.json       # machine-readable output from this skill
```

These two `aplus_image_plan` files are the required downstream input for `Amazon A+ GPT Image Scriptwriter`, which turns the plan into final GPT Image generation scripts.

If updating the workbook is part of the task, keep Excel lightweight and add only:

- `A+图片规划结果文件`: absolute path to `aplus_image_plan.md`.
- Optional short summary column such as `A+图片规划摘要`.

Do not store the full five-image script in Excel cells by default.

## Workflow

### 1. Identify Product And Category

Determine:

- Product type and exact use.
- Category and subcategory.
- Primary buyer and use environment.
- Buying motivation and key doubts.
- Category-appropriate image expression.
- Claims that are explicit, implied, or unsupported.
- Which reference-image selling points are reliable and useful.
- Which reference-image elements should not be copied because they are weak, generic, off-category, or too restrictive.
- Which buyer doubts most affect conversion.
- Which existing main/secondary image messages are already covered and which conversion gaps remain.

Choose the expression style by category:

- Home, kitchen, storage: clean real-life space, organized results, visible quantity/scale, warm natural light.
- Electronics and accessories: desk, travel, car, charging, compatibility, hand interaction, clean technical clarity.
- Beauty and personal care: texture, routine moment, clean light, believable skin/hair/body context, no unsupported clinical claims.
- Baby, pet, family: safety feeling, softness, caregiver interaction, calm expression, no risky pose or exaggerated promise.
- Outdoor, sports, travel: action, weather/terrain context, portability, durability evidence, sunlight or practical field lighting.
- Tools, hardware, automotive: hands-on use, before/after repair or installation, fit, force, material, close-up proof.
- Apparel and accessories: fit, body scale, movement, material texture, daily outfit/lifestyle context.
- Office and school: desk workflow, organization, repeated-use ergonomics, productivity state, neutral clean palette.

### 2. Interpret Reference-Image Selling Points

When reference-image selling points are provided, classify them before planning:

- Product-form anchors: shape, proportions, color, texture, parts, openings, handles, attachments, transparent areas, fold lines, installation points.
- Proven feature anchors: the specific function or benefit already shown clearly in the reference image.
- Useful scene anchors: a reference scene that truly supports a selling point and fits the category.
- Useful angle anchors: camera angle or product orientation that helps the buyer understand the product.
- Risky reference anchors: anything that could overconstrain creativity, cause a stale copy, mislead buyers, or weaken the A+ story.

Use references lightly:

- Preserve product identity, structure, relative proportions, and critical details.
- Reuse only the selling-point logic or product angle when it helps avoid deformation or confusion.
- Decide the likely reference direction per planned image: product-form reference, lifestyle/action reference, detail/material reference, dimension/scale reference, or no strong reference available.
- Do not plan every image around the same product identity reference. A real-use image should prefer a real-use/lifestyle/action reference when available; a close-up image should prefer a detail/material reference; a scale image should prefer side-view, dimension, body/hand, capacity, or scale-object evidence.
- Reference image count is task-based, not fixed. Use one reference when enough; suggest two or more only when they protect different things.
- Do not force every planned A+ image to follow the same reference scene, layout, color, or camera angle.
- Do not let a weak reference image override stronger title/bullet selling points.
- If reference content conflicts with the title or bullets, prioritize the title/bullets and note the conflict.
- Prefer "inspired by this reference detail" over "copy this reference image."

### 3. Map Existing Main/Secondary Image Coverage

When existing image coverage is provided, separate what is already handled from what A+ should add:

- Already covered: product identity, core feature callouts, dimensions, package contents, basic use, close-up detail, comparison, or lifestyle scene.
- Needs reinforcement: a message already shown but too important to omit entirely from A+.
- Should not repeat: content that would waste an A+ slot if shown again without stronger scene proof.
- A+ gaps: doubts or motivations not yet answered, such as how it fits real life, why the material feels worth buying, whether it is easy to use, how much it holds, how it looks after use, or whether it suits the intended buyer.

Use this map to decide whether each A+ image should introduce, deepen, or avoid a message. A+ should feel like the next persuasive layer after the image stack, not a duplicate gallery.

### 4. Build The Buyer Doubt And Conversion Map

Before planning the five images, identify the conversion tasks:

- Understanding: the buyer quickly knows what the product is and how it is used.
- Belief: the buyer sees visual proof that the claim is true.
- Doubt removal: the buyer's hesitation about size, fit, material, use difficulty, compatibility, cleaning, capacity, durability, or safety feeling is reduced.
- Value justification: the buyer sees why the product feels worth the price through material, structure, versatility, quantity, convenience, giftability, or outcome.
- Ownership imagination: the buyer can picture the product improving a real moment in their life.

Prioritize the selling points that most affect the buying decision. Do not give a full A+ image to a weak or generic feature unless it supports a stronger buyer doubt.

### 5. Build The Anchor Bank

Create enough anchors before planning the five images. Anchors are visual decisions that keep later image prompts reliable.

Include:

- Product identity anchors: shape, color, material, parts, included accessories, packaging if relevant.
- Anti-deformation anchors: critical structure that must not change, such as opening direction, handle count, transparent areas, folding lines, buckles, connection points, thickness, texture boundaries, proportions, or visible parts.
- Reference-use anchors: which existing image details should be kept, loosely borrowed, or ignored.
- Existing-image coverage anchors: what is already covered, what needs reinforcement, and what A+ should newly prove.
- Scene anchors: where it is used, by whom, during which task, at what moment.
- Pain-point anchors: mess, inconvenience, discomfort, risk, wasted time, lack of space, confusion, or comparison state.
- Selling-point evidence anchors: action, before/after, capacity, fit, hands-on operation, texture, close-up, result.
- Scale and quantity anchors: hand, body, countertop, drawer, suitcase, car seat, common objects, grouped items.
- Material and quality anchors: stitching, thickness, edge finish, metal reflection, transparent texture, soft fabric, sturdy structure.
- Light and color anchors: category-appropriate lighting, color temperature, background palette, contrast level.
- Human anchors: age/lifestyle, posture, expression, eye direction, hand position; use people only when they prove the selling point. When hands, people, children, drivers, sitters, installers, or caregivers are necessary visual proof, mark them as must-show elements, not optional decoration.
- Trust anchors: dimensions, parts breakdown, usage steps, compatibility, care/cleaning, warranty only if provided.
- Mobile readability anchors: one dominant subject, large proof object, low text density, clear contrast, and no tiny details required for understanding.
- Exclusion anchors: elements that must not appear because they confuse category, exaggerate claims, or dilute the main scene.

### 6. Allocate The Five Images

Use this default five-image arc, then adapt it to the product:

1. Core selling-point scene: the main benefit in its strongest real-use scenario.
2. Pain solved or workflow image: show the problem-to-solution logic, often with comparison, use steps, or before/after.
3. Functional detail image: prove one or two key mechanisms through close-up plus context.
4. Scale, capacity, material, or quantity proof: reduce buyer uncertainty with visible reference objects and details.
5. Emotional result or lifestyle outcome: show the buyer's desired final state, still tied to a concrete product benefit.

Rules:

- Each image has one primary job. Do not stack unrelated selling points into one picture.
- Each image must carry a conversion task tag: understand, believe, remove doubt, justify value, or imagine ownership.
- The product must be used, held, installed, worn, opened, filled, cleaned, packed, compared, or otherwise visually proven whenever possible.
- Scenario is mandatory. A plain product-only shot is allowed only when the category requires a parts/dimensions/detail layout.
- The five images should not repeat the same scene with small variations.
- The five images should not repeat the same camera angle by habit. Assign a distinct camera/composition direction to each planned image, such as wide lifestyle 3/4 view, overhead workflow, macro detail with hand interaction, side/dimension scale proof, or over-shoulder emotional-result scene.
- A person's face, expression, or gaze is useful only when it clarifies emotion or usage. Avoid meaningless smiling at camera.
- Emotion must come from the result of use: relief after organizing, confidence during use, calm after solving a problem, care for family/pet/baby, or satisfaction with the final state.
- Reference images can guide product form or a specific proof angle, but the five-image plan must still feel newly designed.
- Existing listing images can be reinforced only if the new A+ scene adds stronger proof, value, or emotion.
- Each image must be readable on mobile: one clear main idea, large enough product, and no dependence on dense or tiny copy.
- Short A+ headline ideas, short selling-point phrases, and simple feature icons are allowed when they help one-second readability. Do not plan any brand name, store name, brand wordmark, brand logo, or decorative brand label inside the image. This skill outputs planning-level key content, not final polished marketing copy.

### 7. Write Per-Image Constraints

For every image, list concise key content only. Later roles will turn this into polished scripts or generation prompts.

Include:

- Image role: why this image exists in the five-image sequence.
- Conversion task: understand, believe, remove doubt, justify value, or imagine ownership.
- Main selling point: one sentence or phrase.
- Buyer pain/doubt: what hesitation this image reduces.
- Selling-point scenario: the concrete scene proving the benefit.
- Reference-use note: whether to use, loosely borrow, or ignore an existing reference-image selling point; include likely reference direction and count, such as one product-form reference, one lifestyle/action reference, detail/material reference plus product-form reference, or no strong reference available.
- Existing-image coverage note: whether this image introduces, deepens, or avoids a message already shown in the listing image stack.
- Must-show visual elements: product, props, hands/people, environment, action, scale references, details.
- Image requirements: composition, light, color, camera distance, perspective, camera/composition direction, amount of text/callouts.
- Scene realism check: whether the action, props, location, scale, and body language feel like real use.
- Reverse constraints: what must not appear.
- One-second check: what the buyer should understand instantly.

## General Negative Constraints

Apply these unless the product/category clearly requires otherwise:

- Do not create generic decorative lifestyle scenes that do not prove a selling point.
- Do not hide the product in shadows, blur, crop, excessive depth of field, or overly cinematic atmosphere.
- Do not use unrelated props, luxury cues, plants, coffee cups, laptops, gift boxes, or families unless they support the scenario.
- Do not make the product scale, capacity, thickness, or material look better than the provided information supports.
- Do not show impossible use, unsafe use, incorrect installation, wrong anatomy, wrong compatibility, or misleading before/after results.
- Do not invent or render brand names, store names, brand wordmarks, brand logos, Amazon logos, badges, awards, certifications, warranty terms, prices, discounts, star ratings, review quotes, QR codes, URLs, medical/health claims, waterproof ratings, load-bearing numbers, or lab-test results.
- Do not use crowded collages, too many arrows, too many icons, dense copy, or tiny labels that prevent the image from reading in one second.
- Do not repeat identical camera angles or the same room setup across all five images.
- Do not use exaggerated facial expressions, fake eye contact, unnatural hands, artificial poses, or model-like posing when natural usage is needed.
- Do not choose a color tone only because it looks "premium." Match the category and buyer expectation.
- Do not over-copy reference images so much that the new scene loses conversion logic, visual freshness, or category fit.
- Do not ignore reference-image product details that prevent deformation, such as shape, openings, proportions, connection points, visible texture, or key parts.
- Do not repeat existing main/secondary image messages unless the A+ image adds stronger scenario proof or emotional/value context.
- Do not depend on small text, tiny icons, thin arrows, or subtle details that fail on mobile; simple large feature icons and short A+ copy are acceptable when secondary to the visual proof, but brand names/marks are not acceptable.
- Do not use fake-looking scenarios, unnatural body posture, props that would not appear in real use, or emotional expressions unrelated to the product outcome.
- Do not conduct competitor-difference analysis unless the user explicitly provides competitor context for a separate workflow.
- Do not output final full image prompts unless the user explicitly asks. Output only planning-level key content.

## Output Format

Use Chinese by default. Keep the output concise, structured, and actionable.

When writing `aplus_image_plan.md`, use this Markdown structure. When writing `aplus_image_plan.json`, preserve the same content as structured fields:

```json
{
  "product_judgment": {},
  "reference_image_judgment": {},
  "existing_gallery_coverage": {},
  "selling_points": {},
  "buyer_doubts_and_priority": {},
  "image_anchors": {},
  "aplus_images": [
    {
      "slot": 1,
      "role": "核心卖点场景",
      "conversion_task": "",
      "main_selling_point": "",
      "buyer_pain_or_doubt": "",
      "scenario": "",
      "reference_use": "",
      "reference_direction_and_count": "",
      "gallery_coverage_handoff": "",
      "must_show_visual_elements": [],
      "image_requirements": "",
      "realism_check": "",
      "negative_constraints": [],
      "one_second_check": ""
    }
  ]
}
```

```markdown
## 产品判断
- 商品是什么：
- 类目/子类目：
- 主要买家：
- 核心使用场景：
- 购买动机：
- 主要疑虑：
- 类目表达方向：
- 需要避免的误导：

## 参考图卖点判断
- 已有参考图表现较好的卖点：
- 可轻参考的产品形态/角度/细节：
- 可轻参考的场景/动作：
- 不建议照搬的参考图元素：
- 与标题/五点冲突或不确定之处：

## 主图/副图已表达内容判断
- 已经表达清楚的内容：
- 需要在 A+ 里强化的内容：
- 不建议重复占图的内容：
- A+ 应该补齐的转化缺口：

## 卖点提炼
- 主卖点：
- 次卖点：
- 可视觉证明的卖点：
- 不适合视觉夸大的卖点：

## 买家疑虑与成交优先级
- 最影响下单的疑虑：
- 需要用图片消除的疑虑：
- 最值得优先表达的卖点：
- 价格/价值感支撑点：
- 使用后理想结果：

## 产品图片锚点
- 产品识别锚点：
- 防变形关键结构锚点：
- 参考图利用锚点：
- 主图/副图承接锚点：
- 场景锚点：
- 痛点锚点：
- 卖点证据锚点：
- 量感/尺寸锚点：
- 材质/质感锚点：
- 光影/色调锚点：
- 人物/动作/表情锚点：
- 移动端一秒读懂锚点：
- 排除锚点：

## 五张 A+ 图初步脚本

### 图 1：核心卖点场景
- 转化任务：
- 表达卖点：
- 买家痛点/疑虑：
- 卖点场景：
- 参考图使用：
- 参考图方向/数量：
- 主图/副图承接：
- 关键图像元素：
- 图像要求：
- 场景真实性检查：
- 反向约束：
- 一秒理解：

### 图 2：痛点解决/流程对比
- 转化任务：
- 表达卖点：
- 买家痛点/疑虑：
- 卖点场景：
- 参考图使用：
- 参考图方向/数量：
- 主图/副图承接：
- 关键图像元素：
- 图像要求：
- 场景真实性检查：
- 反向约束：
- 一秒理解：

### 图 3：功能细节证明
- 转化任务：
- 表达卖点：
- 买家痛点/疑虑：
- 卖点场景：
- 参考图使用：
- 参考图方向/数量：
- 主图/副图承接：
- 关键图像元素：
- 图像要求：
- 场景真实性检查：
- 反向约束：
- 一秒理解：

### 图 4：量感/尺寸/材质信任
- 转化任务：
- 表达卖点：
- 买家痛点/疑虑：
- 卖点场景：
- 参考图使用：
- 参考图方向/数量：
- 主图/副图承接：
- 关键图像元素：
- 图像要求：
- 场景真实性检查：
- 反向约束：
- 一秒理解：

### 图 5：情绪结果/理想状态
- 转化任务：
- 表达卖点：
- 买家痛点/疑虑：
- 卖点场景：
- 参考图使用：
- 参考图方向/数量：
- 主图/副图承接：
- 关键图像元素：
- 图像要求：
- 场景真实性检查：
- 反向约束：
- 一秒理解：
```

## Quality Check

Before finalizing, verify:

- Each image has a different role.
- Each image has a clear conversion task.
- Each image proves one main selling point.
- The main selling point is proven by scene evidence, not by text alone.
- The product remains recognizable and accurate; only force a central product composition when that image's job requires it.
- Reference-image selling points are used lightly to preserve product identity or useful proof, not to lock the whole creative direction.
- Reference direction and count are planned per image instead of defaulting to two references.
- At least three distinct camera/composition directions appear across the five images.
- Existing main/secondary image coverage is considered so A+ does not waste slots repeating weakly.
- At least one image reduces size/capacity/material uncertainty.
- At least one image supports value justification.
- At least one image shows the product in real use.
- Each image remains readable on mobile.
- Product anti-deformation anchors are respected.
- Human emotion and body language feel tied to the product result, not generic posing.
- Negative constraints are specific to each image, not only generic.
- No unsupported claim is introduced.
