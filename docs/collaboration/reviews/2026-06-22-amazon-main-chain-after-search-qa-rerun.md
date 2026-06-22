# QA / PASS_WITH_SCOPE - Amazon Main Chain After Search QA Rerun

Reviewer: 观止 (`agentKey: guanzhi`)
Date: 2026-06-22 CST

## Scope

Reran `MSG-20260622-079` for the `MSG-072` after-search QA fixes.

This QA did not attempt to prove the full real external Amazon detail chain to `export_ready`, because the default Amazon detail adapter remains intentionally fail-closed. The validated scope is:

- VLM/API/TLS/model failure projection no longer crashes the runner or leaves stale running.
- Visual success creates/reuses `product_competitor_candidate_capture` instead of silently stopping at `capture_competitor_candidates/pending`.
- Default detail adapter failure is typed and traceable as `adapter_not_configured`.
- Candidate capture uses the new visual run/step current-set payload when an old visual run already succeeded.
- Fixture/detail adapter success was used only as controlled continuation evidence, not as real Amazon detail success.

## Test Matrix

| Case | Goal | Evidence | Result |
| --- | --- | --- | --- |
| TC-079-001 | VLM/API/TLS/model failure becomes traceable failed state, no stale runner | `scripts/test_amazon_main_chain_after_search_qa_fixes.py` injects `CompetitorVisualMatchError("...APIConnectionError: TLS certificate verify failed")`; assertions require run/group/step `failed`, cleared `locked_until`, product `visual_match_competitors/failed`, workflow error containing `APIConnectionError` and `竞品视觉初筛失败` | PASS |
| TC-079-002 | Visual success creates downstream candidate capture task | Script calls `ProductCompetitorVisualMatchAction.on_step_success()` with selected candidates; assertions require `product_competitor_candidate_capture` run exists, step is `ready`, visual run summary includes `candidate_capture_task_run_ids`, and next node is `capture_competitor_candidates` | PASS |
| TC-079-003 | Default detail adapter fails typed and traceably | Runtime drains the created candidate capture task; assertions require capture run/step `failed`, product `capture_competitor_candidates/failed`, and workflow error containing `adapter_not_configured` | PASS |
| TC-079-004 | Old visual succeeded + new visual success uses new current set | Script creates an old succeeded visual run and a new running visual run; assertions require capture run/step payload `visual_task_run_id` / `visual_task_step_id` to match the new visual run/step, new rows used, old rows not captured | PASS |
| TC-079-005 | Controlled continuation beyond detail capture is not misrepresented as real Amazon success | Fixture adapter case creates successful detail facts, auto competitor selection, final competitor facts, and a pending `product_image_analysis` task; evidence is explicitly fixture-only | PASS_WITH_SCOPE |

## Commands

- `cd backend && .venv/bin/python ../scripts/test_amazon_main_chain_after_search_qa_fixes.py`: PASS. Expected scheduler tracebacks were emitted for injected VLM failure and default detail-adapter `adapter_not_configured`; final line: `amazon main-chain after-search QA fix behavior checks passed`.
- `cd backend && python -m compileall -q app`: PASS.
- `make test-project-rules`: PASS, 62 tests.
- Read-only cleanup check: `qa_fix_products=0 qa_fix_runs=0`.
- Scoped whitespace check: `git diff --check -- backend/app/product_tasks/actions.py backend/app/task_runtime/scheduler.py scripts/test_amazon_main_chain_after_search_qa_fixes.py scripts/test_project_rules.py docs/domain-index/product-flow.md docs/domain-index/task-runtime.md`: PASS.

## White-Box Evidence

- `backend/app/product_tasks/actions.py:3107-3124` rolls back, reloads the failed product task step, calls `on_step_failure()`, isolates secondary projection errors, and re-raises the original worker error.
- `backend/app/task_runtime/scheduler.py:296-319` catches worker exceptions, rolls back, reloads step/run/group, writes `STEP_STATUS_FAILED`, clears locks, emits an error event, and commits the failed state.
- `backend/app/product_tasks/actions.py:1518-1532` creates/reuses `product_competitor_candidate_capture` from visual success with explicit `visual_task_run_id` and `visual_task_step_id`, `auto_start=True`.
- `backend/app/product_tasks/actions.py:1857-1873` and `1932-1940` make candidate capture validation/execution prefer payload visual ids before fallback inference.
- `backend/app/product_tasks/actions.py:1905-1925` writes the explicit visual ids to both run and step payloads.
- `backend/app/product_tasks/actions.py:2018-2047` records typed detail-capture failures; all-candidate default adapter failure raises `候选竞品详情抓取全失败: adapter_not_configured`.
- `backend/app/product_tasks/actions.py:3007-3028` refreshes active candidate-capture run payload and only pending/ready step payloads when explicit visual ids are present.

## Side Effects

Allowed local side effects:

- The focused script created temporary `QA_FIX_%` products, task runs, task steps, task events, candidates, images/data/catalog rows, then cleaned them in `finally`.
- Read-only cleanup check confirmed `qa_fix_products=0 qa_fix_runs=0`.

Forbidden side effects avoided:

- No business code edit.
- No commit or push.
- No inbox edit.
- No manual DB success write.
- No mock/fake result represented as real QA PASS.
- No product `92` rerun, no Amazon export/template output, no Seller Central, no A+ upload, no TikTok, no real publish, no real ASIN overwrite.

## Residual Risk

- Real Amazon detail adapter remains unconfigured/fail-closed by default. This QA treats `adapter_not_configured` as the expected safe blocker, not as a real external detail success.
- Fixture detail success proves controlled continuation from successful candidate detail facts into auto competitor selection and image-analysis task creation, but it does not prove live Amazon detail page access or final `export_ready`.
- Public UI/API retry entry for candidate capture and auto competitor selection remains outside this rerun's success claim; the validated fix is that visual success now creates/starts the downstream task and failure is traceable rather than silent.

## Conclusion

`QA / PASS_WITH_SCOPE`.

The previous `MSG-072` failure modes covered by `MSG-079` did not reproduce: no runner crash, no stale running, no silent `capture_competitor_candidates/pending`, and no old visual run ownership leak. The remaining blocker to a full real-world chain is the intentionally unconfigured real Amazon detail adapter, which is now surfaced as a typed, traceable failure.
