# Competitor Candidate Capture Phase 2A Code Review

- Reviewer: 镜花 (`jinghua`)
- Date: 2026-06-21 CST
- Message: `MSG-20260621-026`
- Node: `CODE_REVIEW`
- Result: `NEEDS_FIX`

## Scope

Reviewed Phase 2A code/data/task-runtime changes only:

- `backend/app/models/models.py`
- `backend/app/database.py`
- `backend/app/product_tasks/actions.py`
- `backend/app/services/amazon_competitor_visual_match.py`
- `backend/app/services/amazon_listing_detail.py`
- `scripts/test_project_rules.py`
- `scripts/test_competitor_candidate_capture_phase2a.py`
- `docs/domain-index/product-flow.md`
- `docs/domain-index/task-runtime.md`
- `docs/superpowers/specs/2026-06-19-amazon-auto-competitor-selection-prd.md`
- `docs/superpowers/specs/2026-06-21-competitor-candidate-capture-phase2-plan.md`

Out of scope: page QA, real Amazon, real VLM, real product full-chain execution, API/frontend retry entry, final ASIN selection, export/A+/TikTok.

## Blocking Findings

### P1 - Required DB behavior coverage is incomplete for this gate

`scripts/test_competitor_candidate_capture_phase2a.py` currently has two behavior scenarios:

- `scripts/test_competitor_candidate_capture_phase2a.py:162` partial success with an old different candidate row excluded.
- `scripts/test_competitor_candidate_capture_phase2a.py:252` full failure leaving no capture facts.

That is not enough for the review gate requested in `MSG-20260621-026`. The message explicitly asks whether the script covers partial success, full failure, old run exclusion, same-ASIN/upsert risk, cancel/interrupted cleanup, and result-id mismatch (`docs/collaboration/inbox.md:83`). The Phase 2A plan also requires DB behavior tests for current run/step selection, old run exclusion, partial success, full failure, success hook transaction, cancel/interrupted cleanup, and no final ASIN writes (`docs/superpowers/specs/2026-06-21-competitor-candidate-capture-phase2-plan.md:233`), and says not to skip behavior coverage (`docs/superpowers/specs/2026-06-21-competitor-candidate-capture-phase2-plan.md:245`).

The concrete missing cases are:

- Same ASIN reused across runs through the `UniqueConstraint("product_id", "asin")` row reuse path. This was a prior hard constraint in the Phase 2 design review because `_upsert_competitor_search_candidates()` updates the existing row by ASIN (`backend/app/product_tasks/actions.py:922`) rather than creating a new row. Current script excludes an old different row, but does not prove old visual/detail/final facts are cleared or overwritten when the same row is reused.
- `on_step_success()` result IDs mismatch. The implementation has the guard (`backend/app/product_tasks/actions.py:1607`), but the behavior script does not prove the guard fails cleanly and leaves no current successful capture facts.
- cancel/interrupted cleanup. The implementation projects both through `_project_competitor_candidate_capture_failed()` (`backend/app/product_tasks/actions.py:1695`, `backend/app/product_tasks/actions.py:1705`), but the behavior script does not execute those hooks and assert capture/final facts are cleared while search/visual facts remain.
- success hook transaction/projection failure evidence. The scheduler calls `on_step_success()` after marking the step succeeded and converts projection failure to partial failure (`backend/app/task_runtime/scheduler.py:306`), but the Phase 2A behavior script directly invokes the hook and does not cover the failure branch or rollback expectations.

Minimum fix: add deterministic DB behavior cases to `scripts/test_competitor_candidate_capture_phase2a.py` or an equivalent backend behavior test:

1. Same ASIN old-run row reuse: seed a candidate row with old visual/detail/final facts, simulate new search/visual evidence on the same row, run capture, and assert only current visual run/step facts are used; stale detail/final facts do not leak.
2. Result mismatch: call `on_step_success()` with missing/extra candidate IDs and assert workflow ends failed and no `capture_status="succeeded"` remains current.
3. Cancel and interrupted: seed successful-looking capture/final facts, call `on_cancel_requested()` and `on_step_interrupted()`, and assert detail/final current facts are cleared while search/visual evidence remains.
4. Success hook transaction/failure branch: at least one case should prove hook failure does not leave a partial `auto_select_competitor/pending` projection.

After that, rerun:

```bash
python -m compileall backend/app
make test-project-rules
cd backend && .venv/bin/python ../scripts/test_competitor_candidate_capture_phase2a.py
git diff --check
```

## Passed Checks

- Schema/index direction is correct: `AmazonCompetitorSearchCandidate.visual_task_run_id` and `visual_task_step_id` are nullable FK fields (`backend/app/models/models.py:917`), MySQL startup ensure adds both columns (`backend/app/database.py:209`), and `ix_amz_comp_visual_capture_set` supports single-table current-set filtering (`backend/app/database.py:280`).
- Visual-match success writes current visual run/step evidence into touched candidates (`backend/app/product_tasks/actions.py:1123`, `backend/app/product_tasks/actions.py:1261`), and `clear_current_visual_match()` clears the new fields (`backend/app/services/amazon_competitor_visual_match.py:402`).
- Candidate capture selection uses latest successful `product_competitor_visual_match` run/step and filters by `visual_task_run_id`, `visual_task_step_id`, `visual_selected_for_capture`, and non-null `visual_rank` (`backend/app/product_tasks/actions.py:1363`, `backend/app/product_tasks/actions.py:1387`).
- `execute_step()` returns structured per-candidate results and does not write `amazon_competitor_search_candidates` detail fields (`backend/app/product_tasks/actions.py:1484`).
- `on_step_success()` re-queries current visual set, requires exact candidate ID equality, writes detail current facts, and advances to `auto_select_competitor/pending` without writing final ASIN (`backend/app/product_tasks/actions.py:1589`).
- Failure/cancel/interrupted project through `_project_competitor_candidate_capture_failed()`, which clears capture/final current facts and does not clear search/visual facts (`backend/app/product_tasks/actions.py:374`, `backend/app/product_tasks/actions.py:1281`, `backend/app/product_tasks/actions.py:1313`).
- Boundary check passed: no `retry_competitor_candidate_capture` API/frontend exposure was found; no final `competitor_asin` write appears in the candidate capture action section.
- Documentation/index updates match Phase 2A boundaries: no real Amazon, no frontend retry, no final ASIN, no E4/E5 behavior claimed.

## Verification Run

- `python -m compileall backend/app` PASS.
- `make test-project-rules` PASS, 56 tests.
- `cd backend && .venv/bin/python ../scripts/test_competitor_candidate_capture_phase2a.py` PASS.
- `git diff --check` PASS.

## Gate Meaning

`CODE_REVIEW / NEEDS_FIX` blocks Phase 2A code gate only because required DB behavior evidence is incomplete. This is not a QA result and does not judge real Amazon, real product full-chain execution, frontend behavior, export, A+, TikTok, or E4/E5 readiness.
