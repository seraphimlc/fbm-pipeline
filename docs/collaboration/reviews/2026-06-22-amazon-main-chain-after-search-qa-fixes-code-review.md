# CODE_REVIEW / NEEDS_FIX - Amazon Main Chain After Search QA Fixes

Reviewer: 镜花 (`agentKey: jinghua`)
Date: 2026-06-22 CST

## Scope

Reviewed `MSG-20260622-076` / `MSG-20260622-077` after-search QA fixes for:

- `backend/app/product_tasks/actions.py`
- `backend/app/task_runtime/scheduler.py`
- `scripts/test_amazon_main_chain_after_search_qa_fixes.py`
- `scripts/test_project_rules.py`
- `docs/domain-index/product-flow.md`
- `docs/domain-index/task-runtime.md`

This is engineering code/runtime/state/data/test/doc review only. I did not perform product QA, did not edit inbox, did not modify business code, did not commit, and did not push.

## Gate Result

`CODE_REVIEW / NEEDS_FIX`

Do not hand this to 观止 for `MSG-072` QA rerun yet. The failure-projection fix is materially improved, and the new focused behavior script covers the basic visual-failure and continuation paths, but the current-set fallback can select the wrong visual run during the exact visual-success continuation window when an older succeeded visual run exists.

## Blocking Findings

### P1 - Visual success can fail downstream creation by preferring an older succeeded visual run over the current selected set

Evidence:

- Current visual success writes selected rows with the in-flight step/run ids in `ProductCompetitorVisualMatchAction.on_step_success()` (`backend/app/product_tasks/actions.py:1469-1480`) and then creates `product_competitor_candidate_capture` before task runtime refreshes the visual run to `succeeded` (`backend/app/task_runtime/scheduler.py:320-340`).
- Candidate capture validation calls `_current_visual_selected_for_capture(db, product_id)` without explicit visual ids (`backend/app/product_tasks/actions.py:1851`).
- `_current_visual_selected_for_capture()` first uses `_latest_successful_competitor_visual_match_ids()` and only falls back to `_latest_visual_selected_for_capture_ids()` when no successful run exists (`backend/app/product_tasks/actions.py:1744-1800`).
- Therefore, if the product has an older `product_competitor_visual_match` run already marked `succeeded`, the helper chooses that older run while the current success hook is still running. Because visual reserve clears old `visual_selected_for_capture` fields before a newer visual run (`backend/app/product_tasks/actions.py:1393`, `backend/app/services/amazon_competitor_visual_match.py:34-44`), validation can see no selected rows and fail downstream creation even though the current visual success just selected candidates.

Reproduction evidence from a temporary QA_FIX dataset, cleaned afterward:

```text
workflow= capture_competitor_candidates failed
error= 视觉初筛已完成，但候选详情抓取任务创建失败: RuntimeError: 缺少当前视觉初筛 Top 候选，不能抓取候选竞品详情
visual_summary= {'item_code': 'QA_FIX_OLD_VISUAL_CURRENT_SET', 'next_node': 'capture_competitor_candidates', 'product_id': 1224, 'search_run_id': 971, 'search_step_id': 977, 'selected_count': 2, 'status': 'competitor_visual_match_done', 'valid_image_count': 2}
capture_created= False
```

Cleanup check:

```text
qa_fix_products=0 qa_fix_runs=0
```

Impact:

- A normal retry/rerun scenario can turn a successful visual match into `capture_competitor_candidates/failed`.
- The failure is misleading: the selected current facts exist, but validation looked at the wrong run.
- This directly violates the sanctioned continuation path requirement in `MSG-077` and the fallback review item.

Required fix boundary:

- Make the current visual run/step the explicit fact source for the immediately-created candidate capture task. Recommended: include `visual_task_run_id` and `visual_task_step_id` in the candidate capture task payload, preserve them in `build_plan()`, and have `validate()` / `execute_step()` use those ids instead of inferring from latest successful run.
- If keeping fallback inference, change it so it cannot prefer an older succeeded run when current selected rows with newer `visual_matched_at` / `visual_task_run_id` exist. The invariant should be: current selected rows belong to one run/step and downstream capture uses that exact pair.
- Add a focused behavior test for: old visual run succeeded + old selected cleared + new visual success hook creates/reuses candidate capture using the new run/step ids.
- Re-run `cd backend && .venv/bin/python ../scripts/test_amazon_main_chain_after_search_qa_fixes.py`, `make test-project-rules`, `cd backend && python -m compileall -q app`, and scoped `git diff --check`.

### P2 - Regression tests miss the old-run current-set ownership case

Evidence:

- `scripts/test_amazon_main_chain_after_search_qa_fixes.py` covers no prior succeeded visual run in the visual-success continuation case (`scripts/test_amazon_main_chain_after_search_qa_fixes.py:296-427`).
- `scripts/test_project_rules.py` adds useful contract checks, but several new checks are string-presence assertions rather than behavior guards (`scripts/test_project_rules.py:3839-3847`, `scripts/test_project_rules.py:3915-3922`, `scripts/test_project_rules.py:4108-4115`).

Impact:

- The exact P1 above passes the current focused script and project rules.

Required fix boundary:

- Add a behavior assertion to the focused script for explicit visual current-set ownership across reruns.
- Keep the string project rules as broad contract tripwires if desired, but do not rely on them as the only guard for current-set ownership.

## Passed Checks

- ProductTaskAction worker failure path now rolls back and reloads `TaskStep` before calling the failure hook, and failure-hook secondary errors are isolated so the original worker exception is re-raised (`backend/app/product_tasks/actions.py:3051-3080`).
- Scheduler generic failure path now rolls back, reloads step/run/group, and records the original worker exception on the task step (`backend/app/task_runtime/scheduler.py:296-319`).
- Basic VLM/API/TLS failure no longer crashes the runner in the focused script; it projects task failed plus `visual_match_competitors/failed`.
- Visual success creates/reuses candidate capture in the no-prior-run case, and default detail adapter failure is typed as `adapter_not_configured` rather than fake success.
- Fixture detail success creates/reuses auto competitor selection, and auto selection writes final competitor facts and creates/reuses a `product_image_analysis` task run.
- Domain indexes were updated for the after-search continuation and default detail-adapter fail-closed behavior.

## Validation Run

- `cd backend && python -m compileall -q app`: PASS.
- `cd backend && .venv/bin/python ../scripts/test_amazon_main_chain_after_search_qa_fixes.py`: PASS.
- `make test-project-rules`: PASS, 62 tests.
- `git diff --check -- backend/app/product_tasks/actions.py backend/app/task_runtime/scheduler.py scripts/test_amazon_main_chain_after_search_qa_fixes.py scripts/test_project_rules.py docs/domain-index/product-flow.md docs/domain-index/task-runtime.md`: PASS.
- Additional temporary current-set reproduction: FAILS as described above; temporary QA_FIX rows cleaned.

## Gate Meaning

This review does not block on the basic failure-projection implementation, but it blocks the handoff to 观止 because the continuation path can fail in a plausible retry/rerun state and the tests do not cover it.

---

## REREVIEW - MSG-20260622-078 Current Visual Set Ownership Fix

Reviewer: 镜花 (`agentKey: jinghua`)
Date: 2026-06-22 CST

### Scope

Re-reviewed only the `MSG-20260622-078` fix for the previous P1 current visual-set ownership finding:

- `backend/app/product_tasks/actions.py`
- `scripts/test_amazon_main_chain_after_search_qa_fixes.py`
- `scripts/test_project_rules.py`
- `docs/domain-index/product-flow.md`
- `docs/domain-index/task-runtime.md`

This was code/runtime/state/test/doc rereview only. I did not perform QA, did not edit inbox, did not modify business code, did not commit, and did not push.

### Gate Result

`CODE_REVIEW_REREVIEW / PASS_WITH_SCOPE`

The previous P1 is fixed within the requested scope. This allows handoff to 观止 for `MSG-072` QA rerun. It does not mean QA has passed, and it does not approve commit/push by itself.

### Passed Checks

- `ProductCompetitorVisualMatchAction.on_step_success()` now creates/reuses `product_competitor_candidate_capture` with explicit current ownership payload: `visual_task_run_id=step.task_run_id` and `visual_task_step_id=step.id` (`backend/app/product_tasks/actions.py:1518-1532`).
- `ProductCompetitorCandidateCaptureAction.build_plan()` writes the current visual ids to both run payload and step payload when present (`backend/app/product_tasks/actions.py:1905-1925`).
- `validate()` and `execute_step()` parse payload visual ids first and pass them into `_current_visual_selected_for_capture()`; only missing ids fall back to legacy inference (`backend/app/product_tasks/actions.py:1857-1873`, `backend/app/product_tasks/actions.py:1932-1946`).
- Active candidate-capture reuse refreshes run payload and only pending/ready step payloads when visual ids are present; it does not rewrite running/succeeded step history (`backend/app/product_tasks/actions.py:3008-3028`). `ACTIVE_RUN_STATUSES` excludes succeeded runs.
- The focused behavior script now includes an old visual succeeded + new visual running/success ownership case. It builds real DB state, invokes `ProductCompetitorVisualMatchAction.on_step_success()`, asserts the downstream run/step payload ids point to the new visual run/step, drains task runtime, and proves the old visual rows were not used (`scripts/test_amazon_main_chain_after_search_qa_fixes.py:430-579`). This is behavior coverage, not just a string rule.
- Project/domain docs match the new behavior: product-flow and task-runtime indexes now describe explicit visual current-set evidence, payload preference, legacy fallback, and default detail adapter fail-closed behavior.

### Non-blocking Notes

- `scripts/test_project_rules.py` still contains string-level contract tripwires for this area. That is acceptable as a broad guard because the focused script now covers the P1 behavior path directly.
- Legacy payload fallback still prefers latest succeeded visual run before selected-row fallback. That remains compatible behavior for old/manual payloads; the sanctioned visual success continuation no longer depends on that inference path.

### Validation Run

- `cd backend && python -m compileall -q app`: PASS.
- `cd backend && .venv/bin/python ../scripts/test_amazon_main_chain_after_search_qa_fixes.py`: PASS. Expected scheduler tracebacks for injected VLM/detail-adapter failures were emitted; final behavior assertions passed.
- `make test-project-rules`: PASS, 62 tests.
- `git diff --check -- backend/app/product_tasks/actions.py backend/app/task_runtime/scheduler.py scripts/test_amazon_main_chain_after_search_qa_fixes.py scripts/test_project_rules.py docs/domain-index/product-flow.md docs/domain-index/task-runtime.md docs/collaboration/reviews/2026-06-22-amazon-main-chain-after-search-qa-fixes-code-review.md`: PASS.

### Gate Meaning

`PASS_WITH_SCOPE` means the `MSG-077` P1 current visual-set ownership blocker is resolved and the branch can proceed to 观止 `MSG-072` QA rerun. This rereview does not cover product QA, external Amazon behavior, browser automation, or final commit/push readiness.
