---
name: amazon-listing-copywriter
description: Rewrite and optimize Amazon listing copy from provided listing materials. Use when Codex needs to turn product attributes, an existing Amazon title, five bullets, top keywords, prohibited words, marketplace/category limits, or rough listing drafts into a cleaner, truthful, buyer-centered title, five bullet points, search terms, and a short listing compliance check.
---

# Amazon Listing Copywriter

## Single-Product Red Lines

This workflow is single-product only.

Absolute red lines:

- Process exactly one product ID / one Excel row per run.
- Do not batch process multiple rows.
- Do not scan product image folders.
- Do not count images for multiple products.
- Do not generate or consume a multi-product index.
- When selecting the next row to process, read only Excel row data and `当前工作节点`; do not access other product folders.
- After one product ID is determined, all reading, analysis, writing, and workbook updates must apply only to that ID.

## Workbook Status Contract

When working from an Excel workbook, update only the corresponding row.

- On success, set `当前工作节点` to `5-Listing 文本构建`.
- If writing listing output columns, update only this row's title, bullets, search terms, and listing check fields.
- If the run fails or information is missing, add or update `处理备注` on the same row with a concise Chinese summary of the issue.
- Do not write long reasoning into Excel cells; keep detailed output in chat or a product-folder file when needed.

## North Star

Treat Amazon listing copy as a buyer decision tool, not a keyword container. Optimize for the right purchase: attract likely buyers, filter out mismatched clicks, reduce hesitation, and make the product easy to choose without exaggeration.

Prioritize:

- Searchable but natural language.
- Product truth and variant accuracy over high-volume but mismatched keywords.
- Scenario-driven benefits that help shoppers decide.
- Clear answers to buyer doubts about fit, use, durability, care, portability, contents, compatibility, or limits.

Before writing, make sure the copy helps shoppers answer:

- What is this product?
- Who or what situation is it for?
- Why is it worth clicking or buying?

## Input Priority

Work from provided material in this order:

1. Product attributes: product type, color, size, material, quantity, compatibility, model, audience, usage limits, certifications, included accessories.
2. Existing title and five bullets: use for positioning clues, but do not preserve weak wording by default.
3. Top 20 keywords: treat as candidates, not requirements.
4. Prohibited or restricted word lists: obey strictly; remove exact matches and risky variants.
5. Marketplace/category limits: obey exact title, bullet, and search-term limits when provided.

If key information is missing, infer conservatively from the listing. Ask a concise question only when product identity, variant, or a major claim cannot be determined safely. If keywords conflict with product attributes, product attributes win.

Never invent dimensions, materials, waterproof ratings, medical effects, safety certifications, age ranges, battery life, compatibility, performance numbers, package contents, or compliance claims.

## Workflow

### 1. Build Product Truth

Internally identify:

- Precise product noun buyers would search.
- Sold variant: color, size, pack count, model, material, compatibility.
- Likely user and scenario: home, travel, camping, office, car, pets, kids, professionals, etc.
- True differentiators: functional features, included parts, design details, convenience, durability, comfort, organization, safety, aesthetics.
- Supported claims only.

Form a compact optimization brief before drafting:

- Search intent: likely ready-to-buy query.
- Click hook: strongest true reason to open the listing.
- Buyer promise: practical problem solved.
- Proof points: attributes supporting the promise.
- Buyer objections: doubts the copy can answer.
- Risk points: tempting keywords or claims to avoid.

### 2. Clean and Classify Keywords

Review top keywords one by one. Remove or downgrade:

- Wrong variant: color, size, pack count, material, style, scent, flavor, gender, age group, model.
- Wrong product, accessory, replacement part, or unrelated use case.
- Unsupported compatibility or brand/model/device terms.
- Competitor or trademark terms unless legitimate compatibility is supported and phrasing is allowed.
- Risky claims: medical, safety, guarantee, "best", "No.1", "cure", "FDA approved", etc.
- Awkward duplicates that add no useful meaning.

Classify usable keywords as:

- Core identity keywords.
- Feature keywords.
- Scenario keywords.
- Audience keywords, only when true.
- Long-tail keywords for bullets or backend search terms.

### 3. Select Title Keywords

Choose one primary keyword and optionally one secondary keyword for the title.

Primary keyword: answer "what is this product?" in the buyer's language.
Secondary keyword: use a natural alternate product phrase or high-value feature/product phrase.

Rank title keyword candidates by:

1. Relevance to exact product and variant.
2. Buyer purchase intent.
3. Ability to identify the product clearly.
4. Natural readability near the beginning.
5. Search value from the provided keyword list.

Good choices: "rechargeable flashlight", "makeup organizer", "dog car seat cover", "USB-C rechargeable flashlight", "stackable drawer organizer".

Weak choices: scene-only slogans, vague benefits, wrong variant keywords, or keyword chains.

### 4. Write the Title

Default Amazon US-style English title length: about 120-170 characters unless the category has stricter limits. For Chinese drafts, write one clean line instead of filling the limit.

Use this structure when it fits:

`Primary Keyword + Key Selling Point + Product Type + Use Scenario/User + Spec/Quantity/Color/Compatibility`

Title rules:

- Front-load the primary keyword in the first 2-5 words.
- Make the first 70-90 characters understandable on cropped mobile results.
- Include 1-2 core/product keywords; do not force more.
- Add 1-3 strong, true selling points.
- Add 2-4 scenarios only when they help buyers self-identify.
- Include color, size, pack count, or compatibility only when accurate and useful.
- Avoid keyword chains, slogan-first titles, repeated words, hype, decorative symbols, all-caps emphasis, and unsupported superlatives.

Example:

`Rechargeable LED Flashlight, High-Lumen Waterproof Handheld Flashlight for Camping, Emergency, Hiking and Night Walking`

### 5. Write Five Bullet Points

Each bullet should sell one clear reason to buy and connect feature, benefit, and scenario or proof point.

Default length:

- English: about 130-230 characters each unless asked for longer.
- Chinese: about 60-110 Chinese characters each.

Recommended sequence:

1. Core benefit: main function and immediate buyer outcome.
2. Scenario use: concrete places and moments where the product fits.
3. Quality or material: durability, comfort, construction, care, or design details that are true.
4. Ease of use: setup, carrying, storage, cleaning, adjustment, charging, compatibility, or operation.
5. Purchase confidence: package contents, gifting, backup use, everyday value, after-use care, or broad user fit.

Bullet rules:

- Start with a short varied benefit label when useful, such as `Bright Light for Night Use:` or `Organized Storage:`.
- Use buyer-centered language: "helps you", "designed for", "easy to keep in", "ideal for", "whether you are".
- Use keywords only where they fit naturally.
- Avoid repeating the same exact phrase across bullets.
- Avoid "we/our" where possible.
- Replace vague hype with concrete facts or realistic uses.
- Make each bullet specific to the product.

### 6. Generate Keyword Output

After rewriting, produce a clean keyword set:

- Core keywords: 2-4 phrases central to the product.
- Scenario keywords: 4-8 relevant use cases.
- Feature/attribute keywords: 4-8 true descriptors.
- Long-tail keywords: useful phrases that were not natural in the title.
- Removed keywords: list only important removed terms with short reasons.

For backend/search-term style output, avoid unnecessary repetition and commas when the user asks for Amazon backend search terms.

### 7. Compliance and Prohibited Words Pass

Default to safe, factual copy suitable for direct listing upload. This is not a full legal review, but it should catch common Amazon listing risks.

If a prohibited-word list is provided, scan title, bullets, and keywords against it and remove or replace risky words.

If no list is provided, avoid:

- Promotional/deal language: "free shipping", "sale", "discount", "deal", "coupon", "clearance", "limited time", "buy one get one".
- Unsupported superiority/ranking: "best", "No.1", "#1", "top rated", "best seller", "hot item", "premium", "perfect", "ultimate", "amazing".
- Guarantees/absolutes: "100% quality guaranteed", "satisfaction guaranteed", "risk free", "lifetime", "always", "never", "indestructible", "unbreakable".
- Regulated claims: "cure", "treat", "prevent disease", "FDA approved", "antibacterial", "antiviral", "kills germs", "pesticide", unless explicitly supported and category-appropriate.
- Competitor or trademark terms without supported compatibility.
- Seller, price, shipping, warranty, review, URL, email, phone, or off-Amazon references.
- Decorative symbols, emojis, repeated punctuation, and all-caps attention language.

For Chinese drafts, also avoid equivalents such as "最好的", "第一", "爆款", "热卖", "免费送货", "保证", "100%保证", "治愈", "治疗", "杀菌", "抗病毒", "FDA认证/批准" unless supported and allowed.

Replace risky wording with factual alternatives:

- "perfect gift" -> "practical gift" or a specific user scenario.
- "best quality" -> actual material, construction, or feature.
- "guaranteed" -> supported package, care, or usage detail.
- Medical/safety claims -> neutral product functions.

### 8. Optimizer Pass

Before final output:

- Remove phrases that sound impressive but add little buyer clarity.
- Replace vague adjectives with concrete product facts or use cases.
- Tighten title repetition while preserving the strongest core keyword.
- Check that each bullet has a distinct job.
- Answer likely buyer objections without overpromising.
- Remove keywords or scenarios that attract wrong-variant or wrong-use traffic.
- Keep one best version by default. Offer alternatives only when asked or when two keyword strategies are genuinely close.

## Output Format

Default to direct listing copy for bulk listing. Do not show full reasoning unless asked for analysis.

Use:

```markdown
**Title**
...

**Bullet Points**
1. ...
2. ...
3. ...
4. ...
5. ...

**Search Terms**
...

**Listing Check**
- Prohibited words: Pass / Removed: ...
- Variant accuracy: Pass / Check: ...
- Unsupported claims: Pass / Check: ...
```

Keep the listing check short. If everything is clean, use "Pass". Mention assumptions only when they affect upload safety, such as inferred material, unclear compatibility, uncertain variant, or missing marketplace/category limits.

If the user asks for analysis or review, add:

```markdown
**Optimization Notes**
- Main keyword: ...
- Removed keywords: ... (reason)
- Conversion logic: ...
```

## Quality Checklist

Verify before finalizing:

- Title identifies the product quickly and includes 1-2 strong core keywords.
- Early title words work for search results and mobile cropping.
- Wrong color, size, model, compatibility, and unrelated high-volume keywords are removed.
- Every attribute and claim is supported by provided data.
- Copy is buyer-centered, scenario-rich, and not empty advertising.
- Strongest purchase reason appears in the title or first bullet.
- Likely buyer objections are answered without overpromising.
- Keywords are embedded naturally.
- Bullets have distinct purposes.
- No unsupported competitor brand, medical/safety claim, superlative, promotional claim, decorative symbol, or prohibited word remains.
