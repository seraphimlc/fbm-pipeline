# Lingxing Enhanced Basic A+ Phase 6 Docs And Rules Summary

- Date: 2026-06-30 CST
- Owner: 若命（agentKey: `ruoming`）
- Implementer: 听云（agentKey: `tingyun`）
- Inbox: `MSG-20260630-004`
- Branch: `codex/amazon-auto-competitor-search-phase-a`

## Conclusion

Phase 6 docs/index/project-rule closure is locally validated by 若命 and has passed 镜花 code review with scope. The implementation documents `enhanced_basic_aplus_v1` as a registry-backed basic A+ profile and adds a reverse closure project rule that exercises the producer-to-publisher chain with registry/helper facts.

This does not claim real Lingxing QA, real draft save, `draft_visible`, submit approval, or Amazon Seller Central visibility.

## Changed Files

- `docs/lingxing-aplus-upload.md`
- `docs/domain-index/product-flow.md`
- `docs/domain-index/task-runtime.md`
- `docs/domain-index/runtime-security.md`
- `docs/project-index.md`
- `scripts/test_project_rules.py`
- `scripts/test_task_runtime_autostart.py`
- `docs/collaboration/inbox.md`

## Documentation Updates

- `docs/lingxing-aplus-upload.md` now records enhanced profile scope: basic tier, five standard modules, seven required image slots, Step7/8/9 slot manifest, policy/mapper fail-closed behavior, client slot-map assembly, and draft-save-only non-goals.
- `docs/domain-index/product-flow.md` routes A+ questions to registry, Step7/8/9, policy, mapper, client, planner, and worker, and states enhanced A+ remains outside Product workflow/work_status.
- `docs/domain-index/task-runtime.md` documents enhanced task behavior and verification commands while preserving draft-save-only semantics.
- `docs/domain-index/runtime-security.md` records that multi-slot upload does not change the default fail-closed external-call boundary.
- `docs/project-index.md` adds the Lingxing A+ profile/module/slot verification entry.

## Reverse Closure Rule

`test_lingxing_aplus_enhanced_phase6_reverse_closure_contract()` now checks the enhanced chain with helper imports:

- registry `producer_contract_for_profile()` and `required_image_slots()`
- Step7 `build_aplus_plan_from_business_content()`
- Step8 `normalize_aplus_scripts_for_plan()`
- Step9 `enhanced_image_slot_work_items()`
- policy `collect_aplus_publish_assets()`
- mapper `preflight_validate()` and `assemble_payload()`
- client `_uploaded_slot_map()`

It also links to Phase 5 behavior tests for preflight ordering, fail-closed behavior, slot-map assembly, and draft-save-only success.

## Test Stabilization

`make test-project-rules` exposed a stable failure in `scripts/test_task_runtime_autostart.py`: the probe step had reached `succeeded` while the run was still in the runner refresh middle state. The script now waits for the scheduler runner lifecycle to become idle before reading the final DB status. The final assertion is unchanged: both `TaskRun.status` and `TaskStep.status` must be `succeeded`.

## Verification

- PASS `cd backend && .venv/bin/python ../scripts/test_lingxing_aplus_module_mapper.py`
- PASS `cd backend && .venv/bin/python ../scripts/test_lingxing_aplus_publish_policy.py`
- PASS `cd backend && .venv/bin/python ../scripts/test_lingxing_aplus_publish_tasks.py`
  - Printed fake auth/api/request failure traces are expected retry-path evidence.
- PASS `cd backend && .venv/bin/python ../scripts/test_task_runtime_autostart.py`
- PASS `make test-project-rules`
  - 72 project rule tests.
- PASS `make backend-compile`
- PASS scoped `git diff --check`

## Review

- PASS `CODE_REVIEW / PASS_WITH_SCOPE` by 镜花（agentKey: `jinghua`）
- Blocking findings: none.
- Scope: Phase 6 docs/rules files plus inbox/summary evidence only.
- Residual risk: this does not cover M3.3 real Lingxing QA, real draft save, `draft_visible`, submit, or Amazon Seller Central visibility.
- PASS `CODE_REVIEW / PASS_WITH_SCOPE` by 镜花（agentKey: `jinghua`）for `scripts/test_task_runtime_autostart.py` wait-condition stabilization.
- Residual risk: `_wait_for_runner_idle()` depends on scheduler private lifecycle fields in a dedicated runner lifecycle test; if the scheduler lifecycle is refactored, this test must be updated with it.

## Not Covered

- No real Lingxing/Amazon call.
- No real draft save.
- No submit.
- No M3.3 real QA.
- No `draft_visible`, submit approval, Premium/高级 A+, brand story, or Seller Central visibility.
- No Product workflow/work_status, task center UI, list filter, or overview change.

## Next Gate

若命 can scoped commit/push the reviewed Phase 6 files, then create the M3.3 real Lingxing QA handoff for 观止.
