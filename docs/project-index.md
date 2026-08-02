# Project Runtime Index

Status: route map, not source of truth
Updated: 2026-07-22

Use this file to route investigation. Do not treat it as proof. Verify facts in code, commands, APIs, DB read-only evidence, pages, artifacts, or explicit user decisions.

## Read Contract

Before broad code search, read this file and then the smallest relevant `docs/domain-index/*.md`.

If this file is stale, update it only for the routes affected by the current task.

## Domain Map

| Domain | Domain index | Main roots | Validation |
|---|---|---|---|
| Amazon template/export | `docs/domain-index/README.md` | `backend/app/pipeline/` | mapping/template checks |
| Product flow / A+ | `docs/domain-index/product-flow.md` | `backend/app/pipeline/`, `backend/app/product_tasks/`, `backend/app/task_planners/` | A+ pipeline/task checks |
| Task runtime | `docs/domain-index/task-runtime.md` | `backend/app/task_runtime/`, `backend/app/task_planners/` | task runtime scripts |
| Runtime security | `docs/domain-index/runtime-security.md` | `backend/app/main.py`, `backend/app/services/` | security/startup checks |
| Collaboration | `docs/collaboration.md` | `docs/collaboration/` | `init_collaboration.py --validate-only` |

## Main Entrypoints

Fill or update with stable routes only:

- Backend: `backend/app/`
- Frontend: `frontend/`
- Workers/tasks: `backend/app/tasks/`, `backend/app/pipeline/`
- A+ narrative diagnosis: `backend/app/pipeline/aplus_narrative_diagnosis.py`
- Templates/exports: `backend/app/pipeline/template_mappings/`, `backend/app/pipeline/templates/`
- Lingxing enhanced A+ readiness: `scripts/check_lingxing_enhanced_aplus_qa_readiness.py`
- Lingxing enhanced A+ sample dry-run: `scripts/prepare_lingxing_enhanced_aplus_qa_sample.py`
- Data/migrations:
- Tests:
- Workflow action contract: `contracts/product_workflow_actions.json`, `scripts/test_stability_repair_r1_workflow_actions.py`, `frontend/scripts/test-product-workflow-actions.mjs`
- Catalog export outcome/UI: `backend/app/task_runtime/catalog_export_status.py`, `scripts/test_stability_repair_r1_catalog_export.py`, `scripts/test_stability_repair_r1_catalog_frontend.py`
- TikTok channel status/UI: `backend/app/services/tiktok_status.py`, `backend/app/api/products.py`, `backend/app/api/tiktok.py`, `scripts/test_stability_repair_r1_tiktok.py`, `scripts/test_stability_repair_r1_tiktok_frontend.py`
- Remote dev write guard: `scripts/start.sh`, `scripts/read_startup_env.py`, `frontend/dev-api-write-guard.ts`, `frontend/vite.config.ts`, `backend/app/main.py`, `scripts/test_stability_repair_r1_remote_guard.py`
- Local environment configuration UI/API: `frontend/src/pages/SystemConfigurationPage.tsx`, `frontend/src/components/LocalEnvConfigTable.tsx`, `backend/app/api/config_api.py`
- Product keyword task: `backend/app/task_planners/product_keyword_research.py`, `backend/app/product_tasks/actions.py`, `backend/app/pipeline/step3_keywords.py`
- Product customer-mindset task: `backend/app/pipeline/customer_mindset.py`, `backend/app/task_planners/product_customer_mindset.py`, `backend/app/product_tasks/actions.py`, `scripts/test_customer_mindset.py`, `scripts/test_image_analysis_listing_e5.py`
- Product Listing short-copy contracts: `backend/app/pipeline/step5_listing.py`, `scripts/test_listing_title_highlights.py`
- Product image evidence cards and gallery coverage: `backend/app/pipeline/step6_image.py`, `frontend/src/pages/ProductDetail.tsx`, `scripts/test_image_evidence_cards.py`
- GIGA material-to-A+ chain: `backend/app/services/product_material_prepare.py`, `backend/app/task_planners/product_material_prepare.py`, `backend/app/services/product_pipeline_artifacts.py`, `backend/app/product_tasks/auto_image_selection.py`, `scripts/test_giga_aplus_material_chain.py`
- Amazon AI 人像图片合规：`backend/app/services/amazon_image_compliance.py`, `backend/app/pipeline/step9_aplus_image.py`, `backend/app/pipeline/step10_amazon_template.py`, `scripts/test_amazon_image_compliance_oss.py`
- A+ planned reference selection: `backend/app/pipeline/step7_aplus_plan.py`, `backend/app/pipeline/step8_aplus_script.py`, `scripts/test_aplus_reference_planning.py`
- Frontend mutation D2b static/runtime gates: `frontend/src/api/index.ts`, `frontend/src/api/mutationRunner.ts`, `frontend/src/api/mutationInventory.generated.ts`, `frontend/src/api/mutationOwnerContract.ts`, `frontend/src/workflow/productWorkflowActionRegistry.ts`, `frontend/scripts/generate-mutation-inventory.mjs`, `frontend/scripts/test-mutation-inventory.mjs`, `frontend/scripts/test-mutation-foundation.mjs`, `frontend/tests/mutation-ux.r1.spec.ts`, `frontend/playwright.mutation.r1.config.ts`, `scripts/test_stability_repair_r1_mutation_frontend.py`

## Validation Entrypoints

Fill with commands that agents may run locally:

```bash
python3 /Users/liuchang/.codex/skills/multi-agent-collaboration/scripts/init_collaboration.py --project . --validate-only
cd frontend && npm run contracts:check
cd frontend && npm run mutations:check
cd frontend && npm run test:workflow-actions:e2e
cd backend && .venv/bin/python ../scripts/test_customer_mindset.py
cd backend && .venv/bin/python ../scripts/test_image_analysis_listing_e5.py
cd backend && .venv/bin/python ../scripts/test_listing_title_highlights.py
cd backend && .venv/bin/python ../scripts/test_image_evidence_cards.py
cd backend && .venv/bin/python ../scripts/test_amazon_image_compliance_oss.py
cd backend && .venv/bin/python ../scripts/test_amazon_image_compliance.py
cd backend && .venv/bin/python ../scripts/test_aplus_reference_planning.py
cd backend && .venv/bin/python ../scripts/test_giga_aplus_material_chain.py
cd backend && R1_TEST_MYSQL_ADMIN_URL='mysql+asyncmy://root@127.0.0.1:3306/' .venv/bin/python ../scripts/test_stability_repair_r1_workflow_actions.py --with-mysql
cd backend && R1_TEST_MYSQL_ADMIN_URL='mysql+asyncmy://root@127.0.0.1:3306/' .venv/bin/python ../scripts/test_stability_repair_r1_catalog_export.py
R1_TEST_MYSQL_ADMIN_URL='mysql+asyncmy://root@127.0.0.1:3306/' backend/.venv/bin/python scripts/test_stability_repair_r1_catalog_frontend.py
R1_TEST_MYSQL_ADMIN_URL='mysql+asyncmy://root@127.0.0.1:3306/' backend/.venv/bin/python scripts/test_stability_repair_r1_tiktok.py
R1_TEST_MYSQL_ADMIN_URL='mysql+asyncmy://root@127.0.0.1:3306/' backend/.venv/bin/python scripts/test_stability_repair_r1_tiktok_frontend.py
python3 scripts/test_stability_repair_r1_remote_guard.py
python3 scripts/test_stability_repair_r1_mutation_frontend.py
R1_TEST_MYSQL_ADMIN_URL='mysql+asyncmy://root@127.0.0.1:3306/' python3 scripts/testing/run_with_r1_mysql.py -- make test-project-rules
# DB behavior requires explicit R1_TEST_MYSQL_ADMIN_URL and --with-mysql; never reuse application DATABASE_URL.
```

## Hard Boundaries

Agents must not:

- overwrite real product data, manual categories, true ASINs, generated assets, exports, or templates unless the task explicitly requires it
- run irreversible external-platform actions without explicit authorization
- use this index as a substitute for code or runtime evidence

## Maintenance Contract

Update this index when adding or changing:

- major page or route
- API endpoint
- task/worker type
- state machine
- DB table or important field contract
- export/import path
- external integration
- primary validation command
- generated artifact location

Keep entries short and path-oriented.
