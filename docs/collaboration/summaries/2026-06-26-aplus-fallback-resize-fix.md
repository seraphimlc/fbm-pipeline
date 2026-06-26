# 2026-06-26 A+ Fallback Script And Provider Resize Fix

## Gate

- Message: `MSG-20260626-002`
- Role: 听云（agentKey: `tingyun`）
- Result: `DONE_CLAIMED`
- 若命复核: validation pass, waiting for 镜花 rereview

## Changed Files

- `backend/app/pipeline/step8_aplus_script.py`
- `backend/app/pipeline/step9_aplus_image.py`
- `scripts/test_project_rules.py`
- `docs/collaboration/inbox.md`

## What Changed

- Step8 keeps the fallback continuation behavior: after repeated transient LLM connection/timeout failures, it stores `_fallback_aplus_scripts()` output instead of terminating the A+ chain.
- Step9 now injects script source metadata into legacy and enhanced image work:
  - `script_source`
  - `script_fallback`
  - `script_fallback_reason`
- Step9 generated image manifests now persist provider raw dimensions and upscale evidence:
  - `provider_raw_width`
  - `provider_raw_height`
  - `upscaled_from_provider`
- Existing-image reuse and single legacy module regeneration also receive script source metadata.

## P1 Closure

1. Fallback scripts no longer become unmarked `done` images.
   - `script_source=fallback_script` and `script_fallback=true` are persisted into image results.
   - Non-fallback scripts use `script_source=llm` and `script_fallback=false`.

2. Provider raw size is no longer only temporary payload data.
   - `_ensure_provider_image_large_enough()` records provider raw size.
   - `_provider_image_metadata()` carries that into final image results.

3. Repeatable regression coverage was added.
   - New project rule: `test_aplus_fallback_script_and_provider_resize_metadata_behaviour`.
   - It covers Step8 transient timeout fallback, Step9 fallback script metadata, provider 970x600 -> 1940x1200 adaptation metadata, and keeps the existing enhanced slot schema guard.

## Validation

- `make test-project-rules` PASS, 70 project rule tests.
- `cd backend && .venv/bin/python -m compileall -q app` PASS.
- `git diff --check` PASS.

## Not Covered

- No real Lingxing or Amazon calls.
- No draft save or submit.
- No visual/business QA of generated images.
- No mapper payload assembly, Lingxing client/worker/policy, workflow, work_status, task center, list filter, or overview changes.

## Next Step

Send `MSG-20260626-002` to 镜花 for rereview. If 镜花 passes, 若命 can decide whether to scoped commit immediately or first send 观止 to QA the generated artifact/publish evidence path.
