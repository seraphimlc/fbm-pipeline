# 2026-06-30 A+ Fallback / Provider Resize Artifact QA

## Conclusion

- Gate: `ARTIFACT_QA / PASS_WITH_SCOPE`
- Sample: Product `104` / SKU `W808P415447` / ASIN `B0H6JGDHCW`
- Commit under QA: `838e5f7 fix: preserve aplus fallback image evidence`

This PASS means the old real artifact is traceable and internally consistent, and the new Step8/Step9 metadata behavior has repeatable code/test evidence. It does not prove Amazon draft visibility, real Lingxing/Amazon external acceptance, submit/approval, image aesthetics, final human business quality, or that a post-`838e5f7` real DB manifest has already been generated with the new fields.

## Scope And Side Effects

Allowed:

- Read collaboration docs, summaries, code, tests, and local artifact files.
- Run read-only DB `SELECT` queries against the configured MySQL database through `backend/.env`.
- Inspect local image dimensions with `sips`.
- Run project rule tests.
- Write this QA report and append a short conclusion to `docs/collaboration/inbox.md`.

Forbidden and not performed:

- No Step7/Step8/Step9 rerun.
- No Lingxing A+ save/publish task.
- No real Lingxing/Amazon external platform access.
- No DB/image/task status/product artifact/code mutation.
- No claim that the 2026-06-24 old sample already contains post-`838e5f7` fields such as `script_source` or `provider_raw_width`.

## Test Matrix

| ID | Target | Method | Expected | Actual | Result |
| --- | --- | --- | --- | --- | --- |
| TC-ART-001 | Local old A+ image artifacts | `sips -g pixelWidth -g pixelHeight` on 5 final JPG and 5 raw PNG files | Final images `1940x1200`; raw images `1595x986`; directory exists | All 5 final images are `1940x1200`; all 5 raw images are `1595x986` | PASS |
| TC-ART-002 | Old ProductAplus DB facts | Read-only MySQL `SELECT` on `products`, `product_data`, `product_aplus` | Product 104 exists; `aplus_status=done`; image count `5`; manifest matches old summary | Product 104 exists with ASIN `B0H6JGDHCW`, seller SKU `W808P415447`; `ProductAplus.aplus_status=done`, `aplus_image_count=5`, `generated_at=2026-06-24 17:38:48` | PASS |
| TC-ART-003 | Old manifest resize evidence | Parse `product_aplus.aplus_images` JSON | 5 done entries; final `1940x1200`; raw `1595x986`; `upscaled_from_provider=true` | All 5 entries are `status=done`, `width=1940`, `height=1200`, `raw_width=1595`, `raw_height=986`, `upscaled_from_provider=true`, `oss_status=uploaded` | PASS |
| TC-ART-004 | Old Lingxing draft-save boundary | Read-only MySQL `SELECT` on `catalog_products`, `aplus_upload_items`, `task_runs`, `task_steps`, `task_step_events` | `draft_saved` / success evidence, `submitFlag=0`, `amazon_draft_visibility=unconfirmed`, no submit claim | `CatalogProduct 8.aplus_upload_status=draft_saved`; `AplusUploadItem 46.status=success`, idHash present, `amazon_draft_visibility=unconfirmed`, publish evidence `submitFlag=0`; TaskRun 1329/1330 succeeded; restored audit event exists for step 1336 | PASS |
| TC-META-001 | Future Step9 fallback script source metadata | Code inspection and project rule | Step9 final manifests preserve `script_source`, `script_fallback`, `script_fallback_reason` for legacy/enhanced paths | `step9_aplus_image.py` has `_script_source_metadata()` and `_with_script_source_metadata()`; legacy, enhanced work items, and regenerate path call it | PASS |
| TC-META-002 | Future provider raw/upscale metadata | Code inspection and project rule | Step9 final manifests preserve `provider_raw_width`, `provider_raw_height`, `upscaled_from_provider` | `_ensure_provider_image_large_enough()` writes provider raw dimensions; `_provider_image_metadata()` merges raw/upscale fields into generated image result | PASS |
| TC-META-003 | Repeatable focused rule | Run focused rule | `test_aplus_fallback_script_and_provider_resize_metadata_behaviour` passes | `python3 - <<'PY' ... rules.test_aplus_fallback_script_and_provider_resize_metadata_behaviour()` PASS | PASS |
| TC-META-004 | Full project rules context | Run `make test-project-rules` | If full run passes, use as broader evidence; if unrelated failure, record separately | Target rule printed PASS, then full run failed later in unrelated `test_task_runtime_autostart_runner_lifecycle_behaviour` with `('running', 'succeeded')` | NON-BLOCKING GAP |

## Evidence

Local artifact files:

- Directory: `data/products/GIGA/US/W808P415447/new aplus image`
- Final files: `aplus_01.jpg` through `aplus_05.jpg`, all `1940x1200`.
- Raw files: `aplus_01_raw.png` through `aplus_05_raw.png`, all `1595x986`.

Read-only DB facts from configured MySQL:

- `products`: `id=104`, `amazon_asin=B0H6JGDHCW`, `status=completed`, `aplus_upload_status=draft_saved`, `amazon_seller_sku=W808P415447`.
- `product_data`: `product_id=104`, `item_code=W808P415447`, `material_dir=/Users/liuchang/Documents/gitproject/fbm-pipeline/data/products/GIGA/US/W808P415447`.
- `product_aplus`: `product_id=104`, `aplus_status=done`, `aplus_image_count=5`, `generated_at=2026-06-24 17:38:48`.
- `product_aplus.aplus_images`: 5 `done` entries, final `1940x1200`, raw `1595x986`, `upscaled_from_provider=true`, `oss_status=uploaded`.
- `catalog_products`: `id=8`, `source_product_id=104`, `item_code=W808P415447`, `amazon_asin=B0H6JGDHCW`, `amazon_seller_sku=W808P415447`, `aplus_upload_status=draft_saved`.
- `aplus_upload_items`: `id=46`, `catalog_product_id=8`, `product_id=104`, `status=success`, `store_id=10372`, `site=US`, `seller_sku_used=W808P415447`, `lingxing_aplus_id_hash=ec430d189afe5594706d0ff760f125e9`, `amazon_draft_visibility=unconfirmed`, publish evidence `submitFlag=0`, evidence length `2272`.
- `task_runs`: `1329 aplus_generate succeeded`, `1330 lingxing_aplus_publish succeeded`.
- `task_steps`: `1335 aplus_generate_product succeeded`, `1336 lingxing_aplus_publish_product succeeded`.
- `task_step_events`: event `1911` records `restored_audit_record=true` for step `1336`.

Code/test evidence:

- `backend/app/pipeline/step9_aplus_image.py:213` defines `_script_source_metadata()` and defaults fallback source to `fallback_script`, non-fallback source to `llm`.
- `backend/app/pipeline/step9_aplus_image.py:243` defines `_with_script_source_metadata()`.
- `backend/app/pipeline/step9_aplus_image.py:249` defines `_provider_image_metadata()`.
- `backend/app/pipeline/step9_aplus_image.py:624` records provider raw dimensions in `_ensure_provider_image_large_enough()`.
- `backend/app/pipeline/step9_aplus_image.py:898` merges provider metadata into generated image result.
- `backend/app/pipeline/step9_aplus_image.py:1020`, `1085`, and `1183` apply script source metadata to enhanced, legacy, and single-module regenerate paths.
- `scripts/test_project_rules.py:3830` defines `test_aplus_fallback_script_and_provider_resize_metadata_behaviour`.
- `scripts/test_project_rules.py:4111` asserts final manifest entries preserve fallback source metadata.
- `scripts/test_project_rules.py:4126` asserts provider raw size `970x600`, final `1940x1200`, and `upscaled_from_provider=true` for the fake resize path.

Commands:

- `sips -g pixelWidth -g pixelHeight ...` PASS for all 10 local files.
- MySQL read-only `SELECT` via `cd backend && .venv/bin/python - <<'PY' ... async_session ...` PASS for sample/product/upload/task evidence.
- `python3 - <<'PY' import scripts.test_project_rules as rules; rules.test_aplus_fallback_script_and_provider_resize_metadata_behaviour() ...` PASS.
- `make test-project-rules` did not complete: the target A+ metadata rule printed PASS, then an unrelated task runtime autostart rule failed with `AssertionError: ('running', 'succeeded')`.

## Notes On Old Versus New Evidence

The W808P415447 artifact was generated on 2026-06-24, before commit `838e5f7`. Its DB manifest does not contain `script_source`, `script_fallback`, `script_fallback_reason`, `provider_raw_width`, or `provider_raw_height`, and this is not treated as a QA failure for this gate.

The old manifest does contain older resize evidence (`raw_width`, `raw_height`, `upscaled_from_provider`) and local raw/final files match that evidence. The new fields are supported by code and focused project rule evidence; they still need confirmation on a future real regenerated sample.

## Uncovered / Not Proven

- No real Lingxing or Amazon platform was opened or operated.
- No new A+ generation was run after `838e5f7`; post-fix real DB manifest evidence remains a future sample requirement.
- No Amazon draft-box visibility confirmation.
- No submit/approval path.
- No image aesthetic, brand, copywriting, or final human business-quality review.
- Full `make test-project-rules` currently has an unrelated task runtime autostart failure after the A+ focused rule passes; this should be handled separately if 若命 needs a full project-rules gate for another commit.

## Gate Meaning

`ARTIFACT_QA / PASS_WITH_SCOPE` allows 若命 to treat the current evidence chain as sufficient for a later scoped real-chain trial of A+ fallback/provider resize behavior. It does not authorize automatic save/publish/submit, does not close external-platform validation, and does not remove the need to inspect a new post-`838e5f7` real sample manifest.
