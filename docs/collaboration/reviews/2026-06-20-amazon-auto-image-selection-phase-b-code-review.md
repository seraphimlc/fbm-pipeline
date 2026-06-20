# Amazon Auto Image Selection Phase B Code Review

- Reviewer: 镜花（agentKey: `jinghua`）
- Time: 2026-06-20 CST
- Related inbox: `MSG-20260620-004`
- Conclusion: `CODE_REVIEW / NEEDS_FIX`

## Review Scoping

- Nodes:
  - `IMPLEMENTATION_REVIEW`
  - `DATA_REVIEW`
  - `TEST_REVIEW`
  - `DOCUMENTATION_REVIEW`
- Scope:
  - Phase B implementation from `MSG-20260620-003`
  - `MSG-20260620-004` review request
  - New Amazon product entry into automatic image selection
  - automatic image selection retry API
  - workbench/list/frontend status and actions
  - protection gate coverage
  - manual image reset boundary
  - tests, PRD addendum, domain indexes
- Out of scope:
  - Page QA
  - real product creation path execution
  - real VLM / StyleSnap / Chrome
  - external platform validation
  - `tmp/`
  - `docs/collaboration/roles/jinghua.md`

## Evidence Sources

- Indexes:
  - `docs/project-index.md`
  - `docs/domain-index/product-flow.md`
  - `docs/domain-index/task-runtime.md`
- PRD / inbox:
  - `docs/superpowers/specs/2026-06-19-amazon-auto-image-selection-prd.md`
  - `docs/collaboration/inbox.md`
- Code:
  - `backend/app/services/stylesnap_product_tasks.py`
  - `backend/app/api/products.py`
  - `backend/app/api/schemas.py`
  - `backend/app/services/product_protection.py`
  - `backend/app/product_tasks/actions.py`
  - `backend/app/product_tasks/workflow.py`
  - `frontend/src/api/index.ts`
  - `frontend/src/pages/ProductList.tsx`
  - `frontend/src/pages/ProductImageReview.tsx`
  - `scripts/test_project_rules.py`

## Blocking Findings

### [P1] Phase B exposes `auto_select_images` as a list filter, but the backend still implements `work_status` filtering by loading all matching products and paginating in memory

- Location:
  - `backend/app/api/products.py:2694`
  - `backend/app/api/products.py:2778`
  - `backend/app/api/products.py:2781`
  - `frontend/src/pages/ProductList.tsx:82`
- Judgment standard:
  - Product list is a high-frequency user path. Project rules explicitly disallow in-memory filtering and pagination for list APIs.
  - Phase B makes `auto_select_images` a formal workbench/list status bucket and exposes it in the frontend filter, so this is no longer a hidden legacy branch for this workflow.
- Facts:
  - `auto_select_images` is accepted as a `work_status` at `backend/app/api/products.py:169`.
  - The frontend exposes `auto_select_images` in `WORK_STATUS_FILTERS` at `frontend/src/pages/ProductList.tsx:82`.
  - When any `work_status` is supplied, the API executes the base query without DB-level status predicate, loads all rows with `result.scalars().unique().all()`, then filters in Python and slices the page in memory at `backend/app/api/products.py:2778-2787`.
- Impact:
  - Filtering `auto_select_images` can scan and materialize the whole product set before pagination.
  - This breaks the list API performance/total contract and violates the project data/query boundary.
  - It also makes the new Phase B status bucket depend on a known redline path from the moment it becomes a primary workflow filter.
- Minimum fix requirement:
  - At minimum, implement DB-level filtering and count for the newly exposed `auto_select_images` work status so `?work_status=auto_select_images` does not load all products before pagination.
  - Keep the filter semantics consistent with `build_product_workflow()`:
    - `auto_select_images/pending` belongs to `auto_select_images`.
    - `auto_select_images/processing` belongs to `running`.
    - `auto_select_images/failed` belongs to `failed`.
  - Add a behavior/project-rule test that proves the `auto_select_images` list filter is backed by SQL predicates and does not use the Python list-comprehension path.
  - If 听云 chooses to fix all `work_status` filters now, that is acceptable, but the minimum gate for Phase B is the new `auto_select_images` bucket.

## Passed Checks

- New product entry:
  - `backend/app/services/stylesnap_product_tasks.py:541` initializes new products to `auto_select_images/pending`.
  - `backend/app/services/stylesnap_product_tasks.py:634` commits/refreshes the product before creating the task run.
  - `backend/app/services/stylesnap_product_tasks.py:636` only auto-creates the task run for `created=True`.
  - Duplicate/update products keep the existing workflow unless no workflow exists, where old compatibility remains scoped.
- Retry API:
  - `backend/app/api/products.py:5074` adds `POST /api/products/{product_id}/auto-image-selection/retry`.
  - The route checks `workflow_node`, accepts pending/failed, returns processing without creating a duplicate run, and uses `create_product_auto_image_selection_runs()`.
  - It does not use `BackgroundTasks`, `create_task`, temporary threads, or an in-memory queue.
- Workflow/action projection:
  - `backend/app/product_tasks/workflow.py:296` maps `auto_select_images/pending` to `work_status="auto_select_images"`.
  - `backend/app/product_tasks/workflow.py:353` maps failed automatic image selection to `retry_auto_image_selection` and `manual_adjust_images`.
  - `backend/app/product_tasks/workflow.py:264` exposes a correlation key for task-center navigation.
  - `frontend/src/pages/ProductList.tsx:728` uses `related_correlation_key` for `open_task_center`.
  - `frontend/src/pages/ProductList.tsx:734` and `:899` consume backend workflow actions rather than `current_step` or `error_message`.
- Protection gate:
  - `backend/app/services/product_protection.py:9` centralizes automatic-image-selection protection reasons.
  - `backend/app/services/product_protection.py:27` covers `ProductData.amazon_template_*`.
  - `backend/app/services/product_protection.py:34` covers `Product.files` file types `amazon_import_template` and legacy `amazon_template`.
  - `backend/app/product_tasks/actions.py:98` preloads `Product.files`.
  - `backend/app/product_tasks/actions.py:381`, `:392`, and `:449` cover validate, reserve, and success-race protection.
  - `backend/app/api/products.py:5076` retry preloads `Product.files`.
- Manual image reset:
  - `backend/app/api/products.py:2101` calls `raise_if_image_selection_reset_protected(product)` before destructive reset.
  - `backend/app/api/products.py:2118` clears stale automatic image selection analysis fields.
  - Existing reset guard tests still assert ProductFile/template outputs are not deleted by reset.
- Tests:
  - `scripts/test_project_rules.py:3205` covers `auto_select_images` work status bucket behavior.
  - `scripts/test_project_rules.py:3242` covers ProductData and ProductFile protection evidence.
  - `scripts/test_project_rules.py:3120` covers the Phase B contract at project-rule level.
- Documentation/index:
  - `docs/domain-index/product-flow.md` records Phase B entry, retry API, protection gate, and status bucket.
  - `docs/domain-index/task-runtime.md` records that Phase B product automatic image selection creates/retries through the planner.

## Non-Blocking Risks

- `backend/app/api/products.py:2538` workbench overview still loads all products and counts workflow buckets in Python. This predates Phase B and is not the same user-triggered pagination bug as the blocking list filter, but it is the same structural direction and should be considered for follow-up if product volume grows.
- `backend/app/api/products.py` still owns a large amount of list filtering, workflow projection consumption, retry API logic, and image reset orchestration. Phase B did improve protection-gate ownership by extracting `backend/app/services/product_protection.py`, but reset/projection/list query concerns remain concentrated in the API module.
- Project-rule tests still contain several string-structure assertions for Phase B. They are useful as guardrails, but they do not replace API-level behavior tests with a real AsyncSession/query boundary.

## Verification

```bash
python -m compileall backend/app
# PASS

make test-project-rules
# PASS: OK: 50 project rule test(s)

cd frontend && npm run build
# PASS, with existing Vite chunk-size warning

git diff --check
# PASS
```

## Gate Meaning

- This review does not approve Phase B for commit yet.
- The implementation should return for review after the P1 list-filter issue is fixed and verified.
- This review does not represent QA PASS, real product creation validation, real VLM quality validation, or external platform validation.
