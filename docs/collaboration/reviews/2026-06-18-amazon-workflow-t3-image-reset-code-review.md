# Amazon Workflow T3 Image Reset Code Review

- Reviewer: 镜花（agentKey: `jinghua`）
- Time: 2026-06-18 13:27 CST
- Related inbox: `MSG-20260618-009`
- Conclusion: `CODE_REVIEW / PASS`

## Scope

- PRD / request: `docs/superpowers/specs/2026-06-18-amazon-product-workflow-prd.md` T3, `MSG-20260618-006`, `MSG-20260618-009`
- Code reviewed:
  - `backend/app/api/products.py`
  - `backend/app/services/stylesnap_product_tasks.py`
  - `scripts/test_project_rules.py`
  - `docs/domain-index/product-flow.md`
- Focus:
  - New Amazon product initialization to `select_images/pending`
  - `PUT /api/products/{product_id}/listing-images` reset behavior and side-effect boundary
  - `ProductData` / `ProductImage` / `ProductAplus` / `CatalogProduct` clean-vs-preserve boundary
  - Old `competitor_asin` compatibility impact
  - Test and index coverage
- Not covered:
  - Page QA, real product flow, real task run, real export, external platform behavior

## Index Review

- Used indexes:
  - `docs/project-index.md`
  - `docs/domain-index/product-flow.md`
- Result:
  - `product-flow` correctly points this review to product list/detail, image selection, competitor selection, `backend/app/api/products.py`, workflow PRD, and related models.
  - T3 behavior was added to `docs/domain-index/product-flow.md`.
  - `docs/project-index.md` does not need an update because no route/domain entry changed.

## Evidence

- Static review:
  - `backend/app/api/products.py:1977` initializes new products through `set_product_workflow(... select_images/pending ...)`.
  - `backend/app/api/products.py:2064` centralizes image-selection reset and writes `search_competitor/pending`.
  - `backend/app/api/products.py:2092` clears `Product.competitor_asin`; `backend/app/api/products.py:2110` clears `CatalogProduct.competitor_asin`; `backend/app/api/products.py:2114` clears `CatalogProduct.confirmed_at`.
  - `backend/app/api/products.py:4987` no longer accepts `BackgroundTasks` and only normalizes images, calls reset, commits, and returns `ProductImage`.
  - `backend/app/services/stylesnap_product_tasks.py:524` initializes newly materialized GIGA drafts to `select_images/pending`; existing draft backfill is guarded by empty workflow, image-unconfirmed state, and no competitor ASIN.
  - `backend/app/api/products.py:2764` image queue still includes `created/current_step <= 0`, so old ASIN input does not skip image review.
  - `backend/app/api/products.py:2905` competitor queue requires `created/current_step > 0` and `competitor_asin is null`, so new products with legacy ASIN do not enter competitor selection before image confirmation.
  - `backend/app/api/products.py:3535`, `backend/app/api/products.py:3995`, `backend/app/api/products.py:4490`, and `backend/app/api/products.py:4624` keep export/ASIN/A+ operational gates behind `CatalogProduct.confirmed_at`; reset clears that gate while preserving historical export fields.
- Verification commands:
  - `make backend-compile` passed.
  - `make test-project-rules` passed: `OK: 42 project rule test(s)`.
  - `git diff --check -- backend/app/api/products.py backend/app/services/stylesnap_product_tasks.py scripts/test_project_rules.py docs/domain-index/product-flow.md docs/collaboration/inbox.md` passed.

## Findings

No P0/P1 findings.

## Confirmed Passed

- New product initialization covers manual create, Excel import, and GIGA draft create paths with `select_images/pending`.
- Image confirmation no longer starts StyleSnap search, adds a background task, creates a task run, or writes old `competitor_searching/stylesnap_search.running` state in the `listing-images` endpoint.
- Reset clears current competitor facts, old competitor snapshots, image analysis, listing/category derived fields, current A+ DB state, and current export eligibility.
- Reset preserves source data, new selected images, UPC/brand, `ProductFile`, real files, historical export record fields, Amazon template output fields, and Step 10 mappings.
- Old `competitor_asin` compatibility does not become the workflow source of truth and is cleared when image confirmation succeeds.
- Tests include both structural guards and a function-level reset behavior sample; this is sufficient for T3 code review.

## Residual Risk

- Product list may still expose historical export evidence through `catalog_exported_at/export_task_id` after reset. The workflow action/status and export-center eligibility are not driven by that evidence, and export/ASIN/A+ operations remain gated by `confirmed_at`, so this is not a T3 blocker. It is a display/UX nuance for later QA or product cleanup if it confuses users.
- This PASS is code review only. It is not QA PASS, page acceptance, real product verification, or external platform validation.
