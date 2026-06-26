# 2026-06-26 A+ Fallback Script And Provider Resize Review

## Gate

- Message: `MSG-20260626-001`
- Role: 镜花（agentKey: `jinghua`）
- Result: `CODE_REVIEW / NEEDS_FIX`
- Scope: current uncommitted diff in `backend/app/pipeline/step8_aplus_script.py` and `backend/app/pipeline/step9_aplus_image.py`

## Reviewed Change

- Step8 changes LLM connection/timeout exhaustion from hard failure to `_fallback_aplus_scripts()` continuation.
- Step9 allows fallback/fallback_script A+ scripts to enter real image generation.
- Step9 allows provider images below target size but above A+ minimum size to be adapted locally to target size, with upscale metadata.

## Conclusion

Do not commit yet. The product direction can be accepted only if the degradation and resize facts are preserved through generated image metadata and publish evidence, and if behavior tests lock the new semantics.

## Blocking Findings

1. Fallback scripts entering real image generation are not sufficiently marked in final image/publish evidence.
   - Step8 has top-level `fallback=true` and per-script `fallback_script=true`.
   - Step9 generated image results do not yet persist fields such as `script_fallback`, `script_fallback_reason`, or `script_source`.
   - Risk: downstream users see `done` real generated images and may treat them as normal high-quality LLM-script outputs.

2. Provider raw dimensions are not persisted as provider evidence.
   - `_ensure_provider_image_large_enough()` writes `provider_raw_width` / `provider_raw_height` on the temporary payload.
   - `_generate_single_image()` does not return those fields into the final manifest.
   - Risk: later audit cannot distinguish provider raw size evidence from local raw file size fields.

3. The semantic change lacks repeatable tests or project rules.
   - Required coverage:
     - Step8 transient LLM failure continues with fallback scripts.
     - Step9 accepts fallback scripts only while marking degraded source.
     - Provider image below target but above minimum saves final output and persists provider/raw/upscale metadata.

## Passed Checks

- Current diff does not appear to break the enhanced slot schema guard from `147aa9c`.
- Enhanced path still fails closed for required slots, dimensions, duplicate/missing/unknown slots.
- Provider resizing does not directly pretend the original image was target size; final/raw size and `upscaled_from_provider` exist, but provider fields still need persistence.

## Local Validation

- `cd backend && .venv/bin/python -m compileall -q app` PASS.
- `git diff --check -- backend/app/pipeline/step8_aplus_script.py backend/app/pipeline/step9_aplus_image.py docs/collaboration/inbox.md` PASS.

## Recommended Next Step

Create a fix task for 听云:

- Persist script degradation source into Step9 image manifest and downstream publish/evidence path where assets are collected.
- Persist provider raw dimensions and upscale flag in generated image results.
- Add focused behavior tests or project rules for the three semantic changes.
- Re-run compileall, focused tests/project rules, and `git diff --check`.

After that, send the result back to 镜花 for rereview. Only after code review passes should 观止 QA check real generated artifacts or Lingxing/Amazon-facing evidence.
