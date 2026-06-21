# Competitor Candidate Capture Phase 2A Test Gap Rereview

- Reviewer: 镜花 (`jinghua`)
- Date: 2026-06-21 CST
- Messages: `MSG-20260621-027`, follow-up to `MSG-20260621-026`
- Node: `CODE_REREVIEW`
- Result: `PASS`

## Scope

This rereview only checked the `MSG-20260621-026` blocking finding: deterministic DB behavior coverage for Phase 2A candidate capture.

Reviewed:

- `scripts/test_competitor_candidate_capture_phase2a.py`
- Relevant existing implementation in `backend/app/product_tasks/actions.py`
- Boundary scan for API/frontend retry, real Amazon, final ASIN, auto-selection/image/listing/export/A+/TikTok expansion

Out of scope: page QA, real Amazon, real product full-chain execution, E4/E5, frontend behavior, commit/push.

## Result

`CODE_REREVIEW / PASS`.

The P1 test-evidence gap from `MSG-20260621-026` is closed.

## Evidence

- Same-ASIN row reuse is covered by `_test_same_asin_reused_row_clears_old_detail_and_final()` in `scripts/test_competitor_candidate_capture_phase2a.py:370`. It seeds stale visual/detail/final facts on a single candidate row, reuses that row for the current visual run/step, runs `validate -> reserve -> execute_step -> on_step_success`, and asserts current visual evidence and new detail facts are used while stale final facts are cleared.
- Result-id mismatch is covered by `_test_result_ids_mismatch_clears_current_facts()` in `scripts/test_competitor_candidate_capture_phase2a.py:445`. It checks both missing and extra candidate ids, expects `on_step_success()` to fail, and asserts stale detail/final facts are cleared.
- Cancel/interrupted cleanup is covered by `_test_cancel_and_interrupted_clear_current_facts()` in `scripts/test_competitor_candidate_capture_phase2a.py:563`. It asserts detail/final current facts are cleared while search/visual evidence remains.
- Success-hook failure/no partial projection is covered by `_test_success_hook_all_failed_rolls_back_current_facts()` in `scripts/test_competitor_candidate_capture_phase2a.py:625`. It feeds a full selected set with all failed results into `on_step_success()`, expects failure, and asserts the product stays in `capture_competitor_candidates/failed` with no current successful capture facts.
- Main script executes all old and new scenarios in `main()` at `scripts/test_competitor_candidate_capture_phase2a.py:696`.

## Verification

- `cd backend && python -m compileall -q app` PASS.
- `make test-project-rules` PASS, 56 tests.
- `cd backend && .venv/bin/python ../scripts/test_competitor_candidate_capture_phase2a.py` PASS.
- `git diff --check` PASS.

## Boundary Check

No new evidence of Phase 2A scope expansion:

- No `retry_competitor_candidate_capture` or candidate-capture API/frontend retry exposure found.
- No real Amazon adapter or browser/network path added for candidate capture.
- No final `competitor_asin` write in the candidate capture action.
- No auto-selection, image analysis, Listing, export, A+, TikTok, or external platform task was introduced by this fix.

## Gate Meaning

`PASS` here means the code/data/task-runtime review gate for Phase 2A is unblocked after the test-gap fix. It is not QA PASS and does not approve real Amazon execution, API/frontend retry, E4/E5, or commit/push by itself.
