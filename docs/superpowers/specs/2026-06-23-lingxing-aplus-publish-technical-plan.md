# Lingxing A+ Publish After A+ Done Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** After local A+ generation reaches `ProductAplus.aplus_status=done`, provide a safe, auditable Lingxing ERP A+ publish chain that first saves a draft, separately proves draft visibility, and only submits for approval when explicitly enabled or manually requested.

**Architecture:** Keep Amazon product workflow, local A+ generation, ASIN/listing sync, and Lingxing publish as separate layers. Use `task_runs/task_groups/task_steps/task_step_events` as the execution and recovery fact, `CatalogProduct` as the Amazon-side operational fact, `ProductAplus` as the local A+ content fact, and extended A+ publish item evidence for external responses. Old `aplus_upload.py` and `asin_sync.py` can supply capability code only after they are split out of naked `asyncio.create_task()` batch runners.

**Tech Stack:** FastAPI, SQLAlchemy async ORM, MySQL-compatible bootstrap maintenance, existing task runtime, Lingxing Web Gateway via local Chrome session, React A+ management page, project rule/behavior scripts.

---

#### TECHNICAL_PLAN - 听云（agentKey: `tingyun`）

## PRD / REQUEST

- PRD: `docs/superpowers/specs/2026-06-23-lingxing-aplus-publish-after-aplus-done-prd.md`
- Existing logic note: `docs/lingxing-aplus-upload.md`
- Requested output: this file only.
- Non-goals for this plan task: no business code, no inbox edits, no PRD edits, no commit, no push.

## Current Code Facts

- `task_runs/task_groups/task_steps/task_step_events` already exist in `backend/app/models/models.py`; `TaskRun` has `dedupe_key`, `correlation_key`, `idempotency_key`, cancellation, supersede, summary, and payload fields.
- `backend/app/task_runtime/registry.py` registers workers by `step_type`; `backend/app/main.py` currently registers A+ generation workers but no Lingxing Listing sync or Lingxing A+ publish workers.
- `backend/app/task_planners/aplus_generate.py` creates `aplus_generate` runs with `aplus_generate_product` steps and auto-starts through `kick_task_runtime()`.
- `backend/app/task_runtime/aplus_generate_workers.py` writes `ProductAplus.aplus_status=done` when local A+ content generation completes; it currently does not trigger Lingxing publish.
- `backend/app/services/aplus_auto_trigger.py` is about A+ generation after export-ready, not Lingxing publish after A+ done.
- `backend/app/services/aplus_upload.py` still contains Lingxing auth, image upload, add/edit, batch status writes, and external calls in one module. It starts execution via `asyncio.create_task()` and currently references `settings.external_http_verify` without importing `settings`.
- `backend/app/services/asin_sync.py` still contains Lingxing Listing auth/query and ASIN writeback in one module. It starts via `asyncio.create_task()`. `build_sync_item()` chooses UPC before item code/MSKU, which is unsafe for this PRD.
- `Product` and `CatalogProduct` currently both have `amazon_asin`, `asin_sync_status`, `amazon_product_status`, `aplus_upload_status`, `aplus_uploaded_at`, and `aplus_upload_error`.
- `ProductAplus` currently stores local A+ plan/script/images and `aplus_status`; it does not store Lingxing publish facts.
- `AplusUploadBatch/AplusUploadItem` exist and can retain external publish evidence, but their current status set and default `submit_for_approval=1` are unsafe for automatic linking.
- Amazon export currently fills template `sku` from `ProductData.item_code` in `backend/app/pipeline/amazon_export/listing_fill.py`; there is no separate persisted `amazon_seller_sku`.
- `CatalogProduct.exported_at/export_task_id/export_file_path` are updated by catalog export worker, but current export code does not persist the exact seller code/MSKU fact used for later Lingxing matching.
- Existing UI facts: `/aplus-upload` redirects to `/aplus`; `AplusManagement.tsx` displays `aplus_upload_status` but does not create new Lingxing publish task runs.

## First-Version Endpoint Boundaries

The implementation must not collapse these states:

| State | Meaning | Required evidence | What it does not prove |
| --- | --- | --- | --- |
| `draft_saved` | Lingxing accepted and saved an A+ draft for the aligned ASIN. | `add` or equivalent save response, `idHash`, document name, ASIN, seller SKU/MSKU, store/site, and Lingxing list/detail row showing the draft. | It does not prove Amazon Seller Central A+ draft visibility. |
| `draft_visible` | The saved draft is visible/synced on the Amazon-facing A+ side. | Unique match by `idHash`/ASIN/seller SKU/store/site after Lingxing sync/query, or explicit Seller Central/Amazon A+ draft-box QA evidence. | It is not the same as submitted or approved. |
| `submitted` | The draft was submitted for approval. | Explicit submit action result plus list/detail status such as submitted/reviewing. | It must never be produced by default automatic flow. |

Recommended first release split:

- **Engineering milestone T3:** implement safe `draft_saved` only. A `DONE_CLAIMED` for T3 must say "draft_saved only" and include `amazon_draft_visibility=unconfirmed`.
- **QA acceptance for "publish after A+ done":** should require `draft_visible`, unless 若命/用户 explicitly accept a narrower first release of "save Lingxing draft only". `draft_saved` cannot be reported as `draft_visible`.
- **`submitted`:** outside the default automatic chain. It belongs to an explicit user action or `LINGXING_APLUS_SUBMIT_FOR_APPROVAL=true` with separate gate.

REQUEST / OPEN_QUESTION: 若命/用户 must confirm whether the first externally meaningful product gate is `draft_saved` or `draft_visible`. This plan recommends `draft_visible` for PRD-level PASS and allows `draft_saved` as an intermediate engineering phase only.

## Source Of Truth

| Layer | Source of truth | Owns | Must not own |
| --- | --- | --- | --- |
| Execution | `task_runs`, `task_groups`, `task_steps`, `task_step_events` | Planner/worker lifecycle, retry/cancel/recovery, active dedupe, step events, run summaries, external attempt timeline. | Product business status, local A+ content truth, final ASIN truth. |
| External publish evidence | Extended `AplusUploadBatch/AplusUploadItem` or replacement `lingxing_aplus_publish_items` | Lingxing `idHash`, raw status text, uploaded image evidence, visibility evidence, submission evidence, sanitized external response summaries. | Task runtime status, Product/Catalog final status by itself. |
| Amazon operational product | `CatalogProduct` | Primary Amazon seller SKU/MSKU, ASIN, Amazon listing status, ASIN match source/evidence, Lingxing A+ publish status. | Local A+ content generation internals. |
| Compatibility mirror | `Product` | Mirror fields for existing APIs/destructive-reset protection and legacy views. | Independent writes that can diverge from `CatalogProduct`. |
| Local A+ content | `ProductAplus` | A+ plan/scripts/images/status/version inputs. | Lingxing/Amazon external publish result. |

All writes to `Product.aplus_upload_status` and `CatalogProduct.aplus_upload_status` must go through a single service. That service writes `CatalogProduct` first and mirrors `Product` for compatibility. API handlers, workers, old batches, and reset paths must not scatter status assignments.

## Seller SKU / MSKU Source

The A+ publish chain must match Lingxing Listing rows by the seller code/MSKU that was actually sent to Amazon.

Required changes for implementation:

- Add `CatalogProduct.amazon_seller_sku` and `Product.amazon_seller_sku`.
- During Amazon export, persist the exact value written into the Amazon template `sku` field. Current code fills `sku` with `ProductData.item_code`; if that remains true, explicitly write that same value to `amazon_seller_sku` at export time rather than relying on runtime guessing.
- Include `amazon_seller_sku` in catalog export task result/evidence rows and in `CatalogProduct` update when export succeeds.
- For older exported records, bootstrap `amazon_seller_sku` from `ProductData.item_code` / `CatalogProduct.item_code` only when export evidence and current code prove that was the actual template SKU; otherwise leave null and force `waiting_listing`.
- Update ASIN sync logic so match priority is:
  1. `amazon_seller_sku` exact match against Lingxing `msku` / seller SKU field.
  2. Explicit `CatalogProduct.item_code` / `ProductData.item_code` only as a configured compatibility alias when `amazon_seller_sku` is absent and migration marks it trustworthy.
  3. UPC only as an auxiliary query/diagnostic input, never as the primary writeback match for A+ publish.
- If UPC finds rows but seller SKU/MSKU does not uniquely match, write `waiting_listing` / sync diagnostic. Do not auto-select the UPC row.

## Data Model / Migration / Bootstrap

### New fields

Add to both `Product` and `CatalogProduct`:

- `amazon_seller_sku: String(100), nullable`
- `asin_match_source: String(50), nullable`
- `asin_match_evidence_json: Text, nullable`

Add to `AplusUploadItem` if reusing existing table:

- `lingxing_aplus_id_hash: String(100), nullable`
- `lingxing_status_text: String(100), nullable`
- `amazon_draft_visibility: String(30), default="unconfirmed"`
- `draft_visible_at: DateTime, nullable`
- `submitted_at: DateTime, nullable`
- `publish_evidence_json: Text, nullable`
- `source_task_run_id: Integer, nullable`
- `source_task_step_id: Integer, nullable`
- `product_aplus_id: Integer, nullable`
- `aplus_content_fingerprint: String(100), nullable`
- `seller_sku_used: String(100), nullable`
- `store_id: String(50), nullable`
- `site: String(20), nullable`

If a new table is chosen instead of extending `AplusUploadItem`, it must keep the same semantics and indexes.

### Status registry

Create `backend/app/aplus_publish/status.py` as the only registry for `aplus_upload_status` values:

- `not_uploaded`
- `checking`
- `waiting_listing`
- `syncing_listing`
- `ready_to_upload`
- `uploading`
- `draft_saved`
- `draft_confirming`
- `draft_visible`
- `submitted`
- `failed`
- `skipped`
- `auth_required`

Registry must expose:

- all values and labels
- terminal/nonterminal classification
- retryable classification
- protection classification
- visibility endpoint classification
- unknown/legacy value strategy

Existing legacy statuses map as follows:

- `pending` -> `checking` or `ready_to_upload` during migration only; do not continue producing `pending`.
- `running` -> `uploading` during migration only.
- `success` on item -> not a Product/Catalog status; map by catalog status/evidence.
- `draft_saved`, `submitted`, `failed`, `skipped`, `not_uploaded` remain valid.

### Indexes and bootstrap

Implementation must update:

- `backend/app/models/models.py`
- `backend/app/database.py` schema maintenance for MySQL column/index ensure
- `scripts/test_project_rules.py` so ORM fields and MySQL ensure cannot drift

Recommended indexes:

- `catalog_products.amazon_seller_sku`
- `catalog_products.amazon_asin`
- `catalog_products.aplus_upload_status`
- `aplus_upload_items.lingxing_aplus_id_hash`
- `aplus_upload_items.amazon_draft_visibility`
- optional composite: `aplus_upload_items.product_id, product_aplus_id`

Default values:

- Product/Catalog `aplus_upload_status`: `not_uploaded`
- Item `amazon_draft_visibility`: `unconfirmed`
- New evidence fields: null until a worker writes sanitized evidence

Compatibility:

- Existing test/local dirty data can be treated as legacy.
- Do not run broad production backfill at API startup. Local `scripts/start.sh` can run repeatable schema maintenance as current project convention.
- A maintenance/backfill command or script should explicitly bootstrap `amazon_seller_sku` from current export facts, with dry-run evidence.

## Task Types / Planner / Worker / Events / Idempotency

### Required task types and steps

Add display labels and workers for:

- `lingxing_listing_sync`
- `lingxing_listing_sync_product`
- `lingxing_aplus_publish`
- `lingxing_aplus_publish_product`
- `lingxing_aplus_draft_visibility`
- `lingxing_aplus_draft_visibility_product`
- `lingxing_aplus_submit`
- `lingxing_aplus_submit_product`

The latter two can start as separate task runs or explicit steps after save, but their registry labels, event semantics, and status writes must exist before code starts producing their states.

### Planner files

- `backend/app/task_planners/lingxing_listing_sync.py`
- `backend/app/task_planners/lingxing_aplus_publish.py`
- `backend/app/task_planners/lingxing_aplus_draft_visibility.py`
- `backend/app/task_planners/lingxing_aplus_submit.py`

Planner responsibilities:

- validate config and product/catalog IDs
- compute A+ content fingerprint
- create or reuse active runs
- set `dedupe_key`, `correlation_key`, `idempotency_key`
- write only planned/queued domain state through the publish status service
- call `kick_task_runtime()` only after DB commit

Recommended keys:

- Listing sync: `dedupe_key=lingxing_listing_sync:product:{product_id}:seller_sku:{seller_sku}`
- Publish: `dedupe_key=lingxing_aplus_publish:product:{product_id}:aplus:{product_aplus_id}:fp:{fingerprint}`
- Visibility: `dedupe_key=lingxing_aplus_draft_visibility:product:{product_id}:idHash:{id_hash}`
- Submit: `dedupe_key=lingxing_aplus_submit:product:{product_id}:idHash:{id_hash}`
- Shared correlation: `correlation_key=product:{product_id}:lingxing_aplus_publish`

### Worker files

- `backend/app/task_runtime/lingxing_listing_sync_workers.py`
- `backend/app/task_runtime/lingxing_aplus_publish_workers.py`

Register in `backend/app/main.py`.

Worker event rules:

- Every external call writes a `TaskStepEvent` with sanitized request purpose, endpoint family, target seller SKU/ASIN/store/site, and response status summary.
- Never log cookies, auth-token, complete headers, or full external payloads.
- `auth_required` is a domain status, not a generic code failure.
- Lingxing rate limit, timeout, page structure changes, and external validation errors must be typed.

### Retry and recovery

- Use existing task runtime retry for failed/interrupted steps.
- Retrying `draft_saved` must not create a second draft unless the plan detects no reusable `idHash` and the user/worker is explicitly in "create new draft" mode.
- Retrying visibility should use existing `idHash`.
- Retrying submit should use existing `idHash` and require explicit submit authorization.
- On service restart, no naked in-memory `_running_batches` state is needed; queued/ready task steps are recovered through task runtime settings and manual wake.
- If input facts changed since task creation, publish worker must re-run prerequisites and either proceed with updated evidence or stop with `waiting_listing`/`failed` and a typed reason.

## Old `aplus_upload.py` Split / Reuse Boundary

Do not extend old batch runner for new behavior. Split reusable capability code into:

- `backend/app/services/lingxing_auth.py`
  - local Chrome Lingxing auth check
  - sanitized headers object
  - typed `auth_required` failures
- `backend/app/services/lingxing_aplus_client.py`
  - `uploadDestination`
  - object-storage upload
  - add/save A+ document
  - edit/submit A+ document
  - list/detail/sync/read relation ASIN helpers
- `backend/app/services/aplus_publish_assets.py`
  - collect local A+ images
  - validate existence and dimensions
  - generate alt text and module payload inputs
  - content completeness checks for title/subtitle/body/images
- `backend/app/services/aplus_publish_policy.py`
  - prerequisites and protection gates
  - seller SKU/ASIN/listing status decision
  - draft_saved/draft_visible/submitted transition rules
- `backend/app/services/aplus_publish_state.py`
  - single writer for Product/Catalog status mirrors and item evidence
- `backend/app/services/lingxing_listing_client.py`
  - Lingxing Listing query returning normalized rows with `store`, `site`, `msku`, `asin`, `status`, `title`, raw summary

Legacy `backend/app/services/aplus_upload.py` can remain for historical API compatibility in an early phase, but:

- new automatic chain must not call `start_aplus_upload_batch()`
- new API must not depend on `asyncio.create_task()` batches
- old default `submit_for_approval=true` must not leak into new endpoints
- old functions should either call the new service layer or be marked legacy-only once migration is complete

## Configuration And Safety Gates

Add to `backend/app/config.py` and `backend/.env.example`:

- `AUTO_LINGXING_APLUS_AFTER_DONE=false`
- `LINGXING_APLUS_SUBMIT_FOR_APPROVAL=false`
- `LINGXING_APLUS_STORE_NAME=`
- `LINGXING_APLUS_STORE_ID=`
- `LINGXING_APLUS_SITE=US`
- `LINGXING_APLUS_MAX_CONCURRENCY=1`
- optional `LINGXING_APLUS_ALLOW_REAL_EXTERNAL_CALLS=false` for tests/dev protection

Safety behavior:

- Config off: no task is auto-created after A+ done; manual API can still create task with explicit user action.
- Submit off: workers save draft only and may run visibility check; they do not call submit.
- Missing/expired Chrome login: write `auth_required`, task event, and actionable message. Do not write `failed` unless the code itself failed after valid auth.
- Real external side effects must be impossible from unit tests and fixtures; behavior scripts must explicitly opt in to real Lingxing calls.
- All mutating APIs remain under existing local/dev-token guard.
- TLS verification stays default true through `settings.external_http_verify`; no plan may disable it globally.

## UI / API Minimal Entry

### API

Add task-run based endpoints rather than extending old batch executor:

- `POST /api/task-runs/lingxing-listing-sync`
- `POST /api/task-runs/lingxing-aplus-publish`
- `POST /api/task-runs/lingxing-aplus-draft-visibility`
- `POST /api/task-runs/lingxing-aplus-submit`

or equivalent A+ scoped endpoints that call the same planners. The chosen API must return task run IDs and structured errors.

Do not trigger Lingxing publish from:

- product list GET
- product detail GET
- A+ management page load
- Amazon main workflow retry endpoints

### A+ Management page

Minimum page behavior in `frontend/src/pages/AplusManagement.tsx`:

- show local A+ generation status
- show Lingxing publish status from backend registry values
- show latest related task link by `correlation_key`
- show ASIN sync/listing prerequisite state
- show `auth_required` as a login-required action, not generic failure
- allow manual publish/retry
- allow submit only for `draft_saved` or `draft_visible` with explicit confirmation
- distinguish `draft_saved` from `draft_visible` in labels and filtering

Do not:

- add Lingxing status into product main `work_status`
- change product list workflow buckets
- present submitted as default success
- hide `draft_visible` uncertainty behind a generic "uploaded" tag

## Testing And QA Entrances

### Internal rules and behavior scripts

Add or extend:

- `scripts/test_lingxing_aplus_publish_policy.py`
- `scripts/test_lingxing_listing_sync_tasks.py`
- `scripts/test_lingxing_aplus_publish_tasks.py`
- `scripts/test_project_rules.py`

Required commands per implementation phase:

- `cd backend && .venv/bin/python -m compileall -q app`
- `make test-project-rules`
- phase-specific behavior scripts with safe fixtures
- `git diff --check` scoped to changed files

Fixture tests may prove:

- status registry completeness
- Product/Catalog mirror writes
- seller SKU first matching
- UPC auxiliary-only behavior
- planner dedupe/correlation/idempotency
- no auto task when config off
- no submit when submit config off
- `draft_saved` does not imply `draft_visible`
- retry uses existing `idHash`

Fixture tests may not prove:

- real Lingxing auth works
- real Lingxing save works
- real Amazon/Seller Central draft visibility
- real submit approval path

### Real QA

观止 QA gates must separately report:

- internal behavior script PASS
- page path PASS
- real Lingxing auth PASS
- real Lingxing save draft PASS (`draft_saved`)
- real draft visibility PASS (`draft_visible`)
- real submit PASS (`submitted`), only with user confirmation

Amazon draft visibility verification can be either:

- Lingxing sync/query result that uniquely proves target `idHash`/ASIN/store/site is Amazon-visible, or
- human/automated Seller Central A+ draft-box evidence.

If only Lingxing list shows `草稿`, QA result is `draft_saved` only.

## Phased Implementation Plan

### Phase T1: Data, Registry, And Bootstrap

**Goal:** Establish durable facts and one status writer before any external publish worker exists.

**Files:**

- Modify: `backend/app/models/models.py`
- Modify: `backend/app/database.py`
- Create: `backend/app/aplus_publish/status.py`
- Create: `backend/app/services/aplus_publish_state.py`
- Modify: `backend/app/api/schemas.py`
- Modify: `frontend/src/api/index.ts`
- Modify: `scripts/test_project_rules.py`
- Modify: `docs/project-index.md`
- Modify: `docs/domain-index/product-flow.md`
- Modify: `docs/domain-index/task-runtime.md`
- Modify: `docs/domain-index/runtime-security.md` if config/security wording changes

**Steps:**

- [ ] Add fields and schema maintenance.
- [ ] Add status registry and mirror-write service.
- [ ] Add project rule checks for field/schema/index/status registry closure.
- [ ] Add compatibility mapping for legacy statuses.
- [ ] Run compile and project rules.

**Validation:**

- `cd backend && .venv/bin/python -m compileall -q app`
- `make test-project-rules`
- targeted DB bootstrap dry run on local test DB, if available

**DONE_CLAIMED evidence:**

- ORM fields and DB ensure evidence.
- Registry status list and unknown/legacy strategy.
- Product/Catalog mirror writer behavior evidence.
- Index update checklist.

**Gate:** 若命 review + 镜花 data/status/code review. 观止 not required.

### Phase T2: Seller SKU Persistence And Lingxing Listing Sync Task

**Goal:** Make ASIN/Amazon status a seller SKU/MSKU-aligned fact, not UPC-first lookup.

**Files:**

- Modify: `backend/app/pipeline/amazon_export/listing_fill.py`
- Modify: `backend/app/task_runtime/catalog_export_workers.py`
- Modify: `backend/app/task_planners/catalog_export.py`
- Modify or split: `backend/app/services/asin_sync.py`
- Create: `backend/app/services/lingxing_listing_client.py`
- Create: `backend/app/services/asin_match_policy.py`
- Create: `backend/app/task_planners/lingxing_listing_sync.py`
- Create: `backend/app/task_runtime/lingxing_listing_sync_workers.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/api/task_runs.py`
- Add tests/scripts listed above.

**Steps:**

- [ ] Persist `amazon_seller_sku` when export succeeds.
- [ ] Bootstrap old trusted records explicitly; leave uncertain records null.
- [ ] Implement seller SKU first Lingxing Listing sync worker.
- [ ] Treat UPC as auxiliary query/diagnostic only.
- [ ] Write ASIN match evidence and status through state service.
- [ ] Register task labels, workers, and API.

**Validation:**

- compile
- `make test-project-rules`
- `scripts/test_lingxing_listing_sync_tasks.py`
- cases: no seller SKU, zero match, multiple match, ASIN conflict, wrong store/site, non-sellable, success, duplicate trigger

**DONE_CLAIMED evidence:**

- Export persisted exact seller SKU.
- UPC-first behavior removed from A+ prerequisite path.
- `waiting_listing/syncing_listing` evidence for missing/ambiguous matches.
- No A+ publish task created on ambiguous ASIN.

**Gate:** 若命 review + 镜花 task/data/external-risk review. 观止 optional only for real Listing read QA.

### Phase T3: Lingxing A+ Draft Save Task

**Goal:** Create/save Lingxing A+ drafts through task runtime, default no submit.

**Files:**

- Split/create service files listed in "Old `aplus_upload.py` Split".
- Create: `backend/app/task_planners/lingxing_aplus_publish.py`
- Create: `backend/app/task_runtime/lingxing_aplus_publish_workers.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/api/task_runs.py`
- Modify or legacy-mark: `backend/app/services/aplus_upload.py`
- Add behavior script for publish policy/tasks.

**Steps:**

- [ ] Implement prerequisite check.
- [ ] Implement auth check returning `auth_required`.
- [ ] Implement local A+ image validation and payload completeness check.
- [ ] Implement upload destination and object upload client.
- [ ] Implement `save_draft`.
- [ ] Write `draft_saved`, `idHash`, evidence, and `amazon_draft_visibility=unconfirmed`.
- [ ] Ensure repeat retry reuses existing evidence or stops before duplicate draft creation.

**Validation:**

- compile
- `make test-project-rules`
- `scripts/test_lingxing_aplus_publish_policy.py`
- `scripts/test_lingxing_aplus_publish_tasks.py`
- safe fake client cases: config off, missing ASIN, unaligned ASIN, auth missing, image missing, dimensions too small, save success, save failure, duplicate trigger

**DONE_CLAIMED evidence:**

- New chain never calls `start_aplus_upload_batch()`.
- Default submit is false.
- `draft_saved` evidence includes `idHash` or equivalent record key.
- No claim of `draft_visible`.

**Gate:** 若命 review + 镜花 code/task-runtime/security review. 观止 real Lingxing save QA only after code review.

### Phase T4: Draft Visibility Confirmation

**Goal:** Confirm Amazon-facing draft visibility separately from save.

**Files:**

- Extend: `backend/app/services/lingxing_aplus_client.py`
- Create/modify: `backend/app/task_planners/lingxing_aplus_draft_visibility.py`
- Extend: `backend/app/task_runtime/lingxing_aplus_publish_workers.py` or create `lingxing_aplus_visibility_workers.py`
- Modify: `backend/app/api/task_runs.py`
- Add visibility behavior tests.

**Steps:**

- [ ] Query Lingxing list/detail by `idHash`, ASIN, seller SKU, store, site.
- [ ] Optionally call sync, then query again.
- [ ] Write `draft_visible` only on unique, explicit visibility evidence.
- [ ] Keep `draft_saved + unconfirmed` on sync pending or unclear evidence.
- [ ] Type visibility failures separately from publish failures.

**Validation:**

- fake client tests for visible, not visible, sync pending, ambiguous target, wrong ASIN, wrong store
- real QA if Lingxing/Seller Central evidence is available

**DONE_CLAIMED evidence:**

- Positive proof path for `draft_visible`.
- Negative/uncertain proof path preserving `draft_saved`.
- No path writes `draft_visible` from save response alone.

**Gate:** 若命 + 镜花; 观止 required for real `draft_visible` PASS.

### Phase T5: Auto Trigger After A+ Done

**Goal:** Connect `ProductAplus.aplus_status=done` to Lingxing prerequisite/publish planning when config is enabled.

**Files:**

- Modify: `backend/app/task_runtime/aplus_generate_workers.py`
- Create: `backend/app/services/lingxing_aplus_auto_trigger.py`
- Modify: `backend/app/config.py`
- Modify: `backend/.env.example`
- Add behavior script for auto trigger after A+ done.

**Steps:**

- [ ] After A+ done has committed, call best-effort trigger helper.
- [ ] Config off no-op.
- [ ] Config on creates/reuses listing sync or publish task according to prerequisites.
- [ ] Failures write only A+ publish status/task evidence, not product workflow.
- [ ] Summarize trigger result in A+ generation task summary/event.

**Validation:**

- config off
- config on complete prerequisites
- missing ASIN creates/reuses listing sync
- active publish task reused
- `draft_saved`/`submitted` protected
- auth required
- no Product workflow/status mutation

**DONE_CLAIMED evidence:**

- `ProductAplus.done` remains intact on Lingxing failure.
- product main workflow remains `flow_done/succeeded` / export-ready.
- default off no task created.

**Gate:** 若命 + 镜花. 观止 optional until page/real external path.

### Phase T6: A+ Management UI And Manual Actions

**Goal:** Expose Lingxing status, task links, retry, and explicit submit boundary without polluting product workflow.

**Files:**

- Modify: `frontend/src/pages/AplusManagement.tsx`
- Modify: `frontend/src/api/index.ts`
- Modify: `backend/app/api/schemas.py`
- Possibly modify: `backend/app/api/products.py` A+ list projection
- Keep `frontend/src/pages/AplusUploadList.tsx` legacy/read-only or route it clearly.

**Steps:**

- [ ] Render registry-backed status labels.
- [ ] Add task-center links by `correlation_key` or latest run id.
- [ ] Add manual publish and retry buttons.
- [ ] Add login-required retry affordance for `auth_required`.
- [ ] Add submit button with explicit confirmation.
- [ ] Ensure `draft_saved` and `draft_visible` are visibly distinct.

**Validation:**

- frontend build/check
- browser QA on A+ management
- no product list `work_status` changes

**DONE_CLAIMED evidence:**

- screenshots or Playwright evidence of states and actions.
- API response examples for each status bucket.
- explicit note that product main workflow/list filters are unchanged.

**Gate:** 若命 + 镜花 for API/schema; 观止 UI QA required.

### Phase T7: Explicit Submit Approval

**Goal:** Allow approval submission only through explicit user action or explicit config.

**Files:**

- Create: `backend/app/task_planners/lingxing_aplus_submit.py`
- Extend worker/client submit capability.
- Modify UI/API for confirmation.
- Add submit behavior tests.

**Steps:**

- [ ] Require eligible `draft_saved` or `draft_visible`.
- [ ] Require explicit user action or config true.
- [ ] Revalidate content, ASIN, store/site, and idHash.
- [ ] Submit via edit/submit path.
- [ ] Write `submitted` and `submitted_at` only after evidence.

**Validation:**

- submit config off blocks auto submit
- manual submit creates one task
- duplicate submit reuses active task
- wrong idHash/ASIN blocks
- real submit QA only after user confirms safe test target

**DONE_CLAIMED evidence:**

- Proof no default path submits.
- Submit evidence and status write.
- Human confirmation record for real submit QA.

**Gate:** 若命 + 镜花 + 观止 + user confirmation for real submit.

## Documentation / Index Plan

Implementation phases that add fields, API, task types, page actions, config, or external integration must update:

- `docs/project-index.md`
- `docs/domain-index/product-flow.md`
- `docs/domain-index/task-runtime.md`
- `docs/domain-index/runtime-security.md`
- `docs/lingxing-aplus-upload.md` once old logic is split or legacy-marked
- `backend/.env.example`

If any phase changes Amazon export fields or template fill behavior, update `docs/template-mapping-change-log.md` as required by `AGENTS.md`.

## Risks And Degradation

- Lingxing auth is local-Chrome dependent. Correct degradation is `auth_required`, not silent retry loops or generic failure.
- Lingxing API contracts may drift. Client layer must type endpoint/shape errors and keep raw responses sanitized/truncated.
- Amazon draft visibility may not be machine-provable via Lingxing alone. Keep `draft_saved + unconfirmed` and require 观止/Seller Central evidence for `draft_visible`.
- Multi-instance execution is not supported in v1. Keep concurrency at 1 and avoid designs that assume process-local state is durable.
- A+ content quality is not guaranteed by saving five image modules. Business content acceptance is separate from technical save/publish.

## OPEN_QUESTIONS / REQUESTS

1. Confirm first release PASS gate: `draft_saved` only, or `draft_visible` required. Recommended: T3 can close as engineering draft save, PRD-level external QA PASS requires T4 `draft_visible`.
2. Confirm store/site configuration for first implementation. PRD mentions `Andy店-US / 17983`, but real test used `idea_lc@163.com-US`; code must not hard-code the wrong store.
3. Confirm whether old `AplusUploadBatch/AplusUploadItem` should be extended or replaced by new `lingxing_aplus_publish_items`. Recommended: extend for continuity, but treat `task_runs` as execution fact.
4. Confirm whether `ProductData.item_code` is always the Amazon seller SKU in all existing export templates. If not, export must persist a separate `amazon_seller_sku` before A+ publish can be correct.
5. Confirm acceptable A+ module structure and content completeness rules. Existing code saves image modules with mostly empty title/body; real UI test shows body can be required for quality.
6. Confirm who provides Seller Central/Amazon draft-box visibility evidence if Lingxing sync/list cannot prove `draft_visible`.

## Completion Definition For This Plan

This technical plan is complete when:

- It names source-of-truth boundaries and avoids double fact sources.
- It distinguishes `draft_saved`, `draft_visible`, and `submitted`.
- It prevents UPC-first ASIN matching for A+ publish.
- It moves new Lingxing execution to `task_runs`.
- It preserves default safety flags off.
- It keeps Lingxing publish outside product main workflow and product list `work_status`.
- It defines reviewable, verifiable, committable phases with files, commands, evidence, and gates.
