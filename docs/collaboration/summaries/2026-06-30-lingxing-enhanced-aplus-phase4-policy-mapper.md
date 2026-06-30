# 2026-06-30 Lingxing Enhanced A+ Phase 4 Policy And Mapper

## Gate

- Message: `MSG-20260630-002`
- Role: 听云（agentKey: `tingyun`）
- Result: `DONE_CLAIMED`
- 若命复核: validation pass, waiting for 镜花 code review

## Changed Files

- `backend/app/services/lingxing_aplus_publish_policy.py`
- `backend/app/services/lingxing_aplus_module_mapper.py`
- `scripts/test_lingxing_aplus_module_mapper.py`
- `scripts/test_lingxing_aplus_publish_policy.py`
- `docs/collaboration/inbox.md`

## What Changed

- Policy now branches by A+ publish profile.
  - Legacy `standard_header_image_text_v1` still collects five position-based images.
  - Enhanced `enhanced_basic_aplus_v1` collects seven registry-backed slot assets.
  - Enhanced slot assets are validated by module position, slot id, payload slot, dimensions, local file existence, and alt text.
  - `technical_or_closing` does not receive a placeholder image.

- Mapper now supports enhanced preflight and assembly.
  - Enhanced preflight validates profile, module sequence, semantic role, module spec/type, payload evidence, required text, slot assets, comparison table, and spec rows.
  - Enhanced assembly builds payload subtrees for:
    - `STANDARD_IMAGE_TEXT_OVERLAY`
    - `STANDARD_THREE_IMAGE_TEXT`
    - `STANDARD_SINGLE_IMAGE_SPECS_DETAIL`
    - `STANDARD_COMPARISON_TABLE`
    - `STANDARD_TECH_SPECS`
  - Legacy mapper behavior remains covered and compatible.

## Typed Failures Covered

- Slot and asset failures:
  - `aplus_image_slot_missing`
  - `aplus_image_slot_duplicate`
  - `aplus_image_slot_unexpected`
  - `aplus_image_slot_dimension_invalid`
  - `aplus_alt_text_missing`
  - `aplus_alt_text_too_long`
- Text/spec/comparison failures:
  - `aplus_text_field_missing`
  - `aplus_text_field_too_long`
  - `aplus_rich_text_invalid`
  - `aplus_comparison_column_count_invalid`
  - `aplus_comparison_column_asin_missing`
  - `aplus_comparison_column_asin_invalid`
  - `aplus_comparison_metric_rows_invalid`
  - `aplus_comparison_metric_value_missing`
  - `aplus_spec_rows_invalid`
- Contract and assembly failures:
  - `unsupported_aplus_publish_profile`
  - `unsupported_aplus_module_type`
  - `aplus_profile_module_sequence_mismatch`
  - `aplus_module_semantic_role_mismatch`
  - `aplus_module_spec_unregistered`
  - `lingxing_payload_structure_unverified`
  - `aplus_payload_builder_missing`
  - `aplus_uploaded_asset_missing_id`

## Validation

- `cd backend && .venv/bin/python ../scripts/test_lingxing_aplus_module_mapper.py` PASS.
- `cd backend && .venv/bin/python ../scripts/test_lingxing_aplus_publish_policy.py` PASS.
- `make backend-compile` PASS.
- `git diff --check` PASS.
- Additional validation: `make test-project-rules` PASS, 70 tests.

## Not Covered

- No planner, worker, or client lifecycle wiring.
- No real Lingxing or Amazon calls.
- No draft save or submit.
- No product workflow, work_status, task center, list filter, or overview change.
- Enhanced draft-save lifecycle remains Phase 5.
- Real Lingxing QA remains M3.3.

## Next Step

Send Phase 4 to 镜花 for code review. If it passes, 若命 can scoped commit/push Phase 4 and then open Phase 5 for planner / worker / client lifecycle.
