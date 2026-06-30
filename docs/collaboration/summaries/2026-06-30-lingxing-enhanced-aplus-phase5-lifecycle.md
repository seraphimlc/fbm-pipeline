# Lingxing Enhanced Basic A+ Phase 5 Lifecycle Summary

- Date: 2026-06-30 CST
- Owner: 若命（agentKey: `ruoming`）
- Implementer: 听云（agentKey: `tingyun`）
- Inbox: `MSG-20260630-003`
- Branch: `codex/amazon-auto-competitor-search-phase-a`

## Conclusion

Phase 5 implementation is locally validated by 若命 and ready for 镜花 code/lifecycle review. It wires `enhanced_basic_aplus_v1` into the existing Lingxing A+ draft-save planner/worker/client path without changing the T3 lifecycle boundary.

This does not claim real Lingxing QA, real draft save, `draft_visible`, submit approval, Amazon Seller Central visibility, Premium A+, or product workflow/work_status changes.

## Changed Files

- `backend/app/task_planners/lingxing_aplus_publish.py`
- `backend/app/task_runtime/lingxing_aplus_publish_workers.py`
- `backend/app/services/lingxing_aplus_publish_client.py`
- `scripts/test_lingxing_aplus_publish_tasks.py`
- `scripts/test_project_rules.py`
- `docs/collaboration/inbox.md`

## Implementation Notes

- Planner keeps `collect_aplus_publish_assets()` + `preflight_validate()` before task creation and stores profile-aware `aplus_content_evidence` / `aplus_publish_profile` in task payload.
- Worker still performs asset collection and mapper preflight before `external_call`, `STATUS_UPLOADING`, client invocation, auth, upload destination, object upload, or add/save draft.
- Worker emits a local policy event after preflight success with profile/module/slot evidence and `external_call_started=false`, so tests can assert event ordering.
- Client upload results now preserve `asset_slot_id`, `slot_id`, `payload_slot`, `module_position`, `semantic_role`, and `upload_key`.
- Client passes slot-keyed uploaded assets into mapper `assemble_payload()` when enhanced slot ids exist, with legacy position upload fallback preserved.
- Mapper remains the only enhanced payload assembly owner; client does not hard-code enhanced payload fallback.

## Verification

- PASS `cd backend && .venv/bin/python ../scripts/test_lingxing_aplus_publish_tasks.py`
  - The printed auth/api/request stack traces are expected failure-path evidence for runtime retry tests.
- PASS `make test-project-rules`
  - 71 project rule tests.
- PASS `make backend-compile`
- PASS scoped `git diff --check`

## Not Covered

- No real Lingxing/Amazon call.
- No real draft save.
- No submit.
- No M3.3 real QA.
- No `draft_visible`, submit approval, Premium/高级 A+, brand story, or Seller Central visibility.
- No Product workflow/work_status, task center UI, list filter, or overview change.
- Docs/index closure remains Phase 6.

## Next Gate

Send to 镜花 for Phase 5 code/lifecycle review. Required review scope: task lifecycle, external-call boundary, enhanced slot upload map, mapper assembly ownership, legacy compatibility, draft-save-only boundary, and tests/project-rule quality.
