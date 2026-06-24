# Lingxing Enhanced Basic A+ Phase 3 Summary

- Message: `MSG-20260624-006`
- Role node: 听云 implementation, 若命 local validation
- Conclusion: Implementation claimed and 若命 validation passed; pending 镜花 Phase 3 code/design review before scoped commit.

## Scope Completed

- Step8 now supports explicit `enhanced_basic_aplus_v1` plans through registry-backed module scripts with nested `image_slots`.
- Step8 enhanced image slots come from `module_registry.py` producer/required slot contracts, not a separate local slot table.
- Step9 now detects enhanced scripts and generates slot-level work items from `scripts[*].image_slots[*]`.
- Step9 slot generation uses each slot's `target_width` and `target_height`, and writes slot manifest metadata into `ProductAplus.aplus_images`.
- Old `standard_header_image_text_v1` flat 5-image path remains compatible.
- Module-level regeneration for enhanced is fail-closed in Phase 3, because slot-level regeneration has not been designed or implemented yet.

## Changed Files

- `backend/app/pipeline/step8_aplus_script.py`
- `backend/app/pipeline/step9_aplus_image.py`
- `scripts/test_project_rules.py`
- `docs/collaboration/inbox.md`

## Validation

- `make test-project-rules` PASS, 69 tests.
- `cd backend && .venv/bin/python -m compileall -q app` PASS.
- `git diff --check -- backend/app/pipeline/step8_aplus_script.py backend/app/pipeline/step9_aplus_image.py scripts/test_project_rules.py docs/collaboration/inbox.md` PASS.

## Not Covered

- No enhanced mapper payload assembly.
- No Lingxing upload, draft save, submit, policy/client/worker changes.
- No real image generation or browser QA.
- No Premium/advanced A+, brand story, ASIN sync, or Lingxing pre-sync.
- Enhanced existing-image reuse and slot-level regeneration remain review/future-phase concerns.

## Next Gate

Run 镜花 Phase 3 review focused on:

- Registry source-of-truth discipline for slots and dimensions.
- No global `1940x1200` assumption leaking into enhanced path.
- Correct enhanced manifest shape for later mapper integration.
- Old flat path compatibility.
- Whether enhanced no-reuse / no slot-level regeneration is acceptable for this phase or needs a follow-up task.

## Review Fix Addendum

- Review: 镜花 `CODE_REVIEW / NEEDS_FIX`
- Fix message: `MSG-20260624-007`
- Conclusion: 听云返工完成，若命复跑验证通过，pending 镜花复审。

Fixes:

- Step8 enhanced profile resolution now treats `publish_profile`, `aplus_plan_version`, or `profile` as equivalent explicit enhanced triggers.
- Legacy plans with no profile still stay on the old flat path.
- Step9 now detects enhanced profile before building work items. Malformed enhanced scripts fail closed instead of falling back to `scripts[:5]`.
- Step9 validates enhanced slot manifests against registry required slots, including missing slots, duplicate slots, unknown slots, required fields, and slot dimensions.

Additional tests:

- Version-only enhanced plan produces nested `image_slots`.
- Profile-only enhanced plan produces nested `image_slots`.
- Legacy no-profile plan remains flat.
- Enhanced scripts with missing, empty, or invalid `image_slots` raise `ValueError`.
- Happy path still verifies 7 slot work items and registry dimensions.

Validation after fix:

- `make test-project-rules` PASS, 69 tests.
- `cd backend && .venv/bin/python -m compileall -q app` PASS.
- `git diff --check -- backend/app/pipeline/step8_aplus_script.py backend/app/pipeline/step9_aplus_image.py scripts/test_project_rules.py docs/collaboration/inbox.md docs/collaboration/summaries/2026-06-24-lingxing-enhanced-basic-aplus-phase3-step8-step9.md` PASS.
