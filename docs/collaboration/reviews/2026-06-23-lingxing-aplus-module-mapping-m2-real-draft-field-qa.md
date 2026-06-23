# Lingxing A+ Module Mapping M2 Real Draft Field QA

结论：`QA / PASS_WITH_SCOPE`

日期：2026-06-23 CST  
角色：观止（agentKey: `guanzhi`）  
对应消息：`MSG-20260623-012`

## Scope

本轮只验证 M2 mapper 生成的 5 个 `STANDARD_HEADER_IMAGE_TEXT` 模块，在真实 Lingxing 保存草稿后，于 Lingxing 草稿编辑器中顺序正确，主标题、副标题和正文非空、可见、可读，并能和本地 plan/script/mapper 预期对账。

本轮不验证：

- `draft_visible`
- Amazon Seller Central A+ 草稿箱可见
- submit approval / 发布 / 送审
- A+ 内容审美或最终业务质量

## Required Materials Read

- `AGENTS.md`
- `docs/collaboration.md`
- `docs/collaboration/roles/guanzhi.md`
- `docs/collaboration/playbooks/qa.md`
- `docs/collaboration/inbox.md` 中 `MSG-20260623-012`、`MSG-20260623-011`、`MSG-20260623-010`
- `docs/superpowers/specs/2026-06-23-lingxing-aplus-module-mapping-prd.md`
- `docs/superpowers/specs/2026-06-23-lingxing-aplus-module-mapping-technical-plan.md`
- `docs/collaboration/reviews/2026-06-23-lingxing-standard-header-image-text-payload.md`
- `docs/lingxing-aplus-upload.md`

## Environment

- Database: MySQL `fbm_pipeline` on configured backend `DATABASE_URL` host.
- Default backend config before QA: `LINGXING_APLUS_ALLOW_REAL_EXTERNAL_CALLS=false`, `LINGXING_APLUS_SUBMIT_FOR_APPROVAL=false`, no default Lingxing store configured.
- Real-save command env for this QA only:
  - `LINGXING_APLUS_ALLOW_REAL_EXTERNAL_CALLS=true`
  - `LINGXING_APLUS_SUBMIT_FOR_APPROVAL=false`
  - `LINGXING_APLUS_STORE_ID=10372`
  - `LINGXING_APLUS_STORE_NAME=idea_lc@163.com-US`
  - `LINGXING_APLUS_SITE=US`
- Chrome Lingxing login: usable; target edit page opened without login block.

## Sample

Current DB did not have a ready M2 profile sample before QA:

- `product_aplus_total=111`
- `product_aplus_done=1`
- only ready done sample was old T3 sample `CatalogProduct 1300 / Product 1435 / ProductAplus 838`, with `m2_profile_ok=false` and `aplus_upload_status=draft_saved`.

Created QA-only sample:

- Marker: `QA_ONLY_LINGXING_APLUS_M2_REAL_DRAFT_FIELDS_20260623`
- Product: `1472`
- CatalogProduct: `1337`
- ProductAplus: `875`
- AplusUploadItem: `39`
- TaskRun / TaskStep: `1280 / 1286`
- Lingxing `idHash`: `7bdbd01f14dda52fd3363c70c8e535d5`
- Store: `idea_lc@163.com-US` / `10372`
- Site: `US`
- ASIN: `B0GX2GFR73`
- Seller SKU/MSKU: `N726P248345C`
- Local image dir: `/Users/liuchang/Documents/gitproject/fbm-pipeline/tmp/lingxing-aplus-m2-real-draft-field-qa`

QA sample plan used 5 modules with:

- `publish_profile=standard_header_image_text_v1`
- `lingxing_content_module_type=STANDARD_HEADER_IMAGE_TEXT`
- positions `1..5`
- non-empty `headline`, `subheading`, and `text_content`

## Test Matrix

| Case | Goal | Expected | Actual | Result |
| --- | --- | --- | --- | --- |
| TC-M2-001 | Local code gate | compile/tests/project rules pass | compileall, mapper, policy, task, project rules, diff check passed | PASS |
| TC-M2-002 | Mapper preflight | 5 modules, positions 1..5, rich-text body shape | `preflight.ok=true`, body shape `rich_text_object_list` | PASS |
| TC-M2-003 | Real draft save | Lingxing add path saves draft only with `submitFlag=0` | task succeeded, `draft_saved`, `submitFlag=0`, status text `草稿` | PASS |
| TC-M2-004 | Lingxing editor module order | 5 `带文字的标准图片标题` cards in order | DOM card tops `149, 1359, 2569, 3779, 4989`; positions `1..5` | PASS |
| TC-M2-005 | Field visibility/readability | title/subtitle/body visible and readable for all 5 cards | all 5 titles/subtitles match plan; body candidates contain exact expected text | PASS |
| TC-M2-006 | Local/mapper/page reconciliation | plan/script/assembled payload/page fields align by position | each position matched expected headline/subheading/body | PASS |
| TC-M2-007 | Side-effect boundary | no submit, no draft_visible, no sensitive evidence | `submitted_at=None`, `draft_visible_at=None`, `amazon_draft_visibility=unconfirmed`, event secret scan no hits | PASS |

## Execution Evidence

Real save used the formal planner + task runtime worker path, not direct client-only invocation.

Task result:

- TaskRun `1280`: `succeeded`
- TaskStep `1286`: `succeeded`
- Step result:
  - `status=draft_saved`
  - `lingxing_aplus_id_hash=7bdbd01f14dda52fd3363c70c8e535d5`
  - `amazon_draft_visibility=unconfirmed`
  - `source_task_run_id=1280`
  - `source_task_step_id=1286`

DB / evidence summary:

- `Product.aplus_upload_status=draft_saved`
- `CatalogProduct.aplus_upload_status=draft_saved`
- `AplusUploadItem.status=success`
- `AplusUploadItem.amazon_draft_visibility=unconfirmed`
- `AplusUploadItem.store_id=10372`
- `AplusUploadItem.site=US`
- `AplusUploadItem.seller_sku_used=N726P248345C`
- `publish_evidence_json.submitFlag=0`
- `publish_evidence_json.status_text=草稿`
- `publish_evidence_json.uploaded_image_count=5`
- `publish_evidence_json.module_mapping.content_module_count=5`
- `publish_evidence_json.module_mapping.positions=[1,2,3,4,5]`
- `submitted_at=None`
- `draft_visible_at=None`

Task events:

- Event types: `status`, `external_call`, `external_result`, `progress`, `status`
- Secret scan terms checked in task event message/data: `cookie`, `auth-token`, `authorization`, `x-ak-uid`, `x-ak-company-id`, `x-ak-env-key`, `x-ak-zid`, `headers`
- Result: no hits

## Mapper / Plan / Script Reconciliation

`preflight_validate()` evidence:

- `profile=standard_header_image_text_v1`
- `content_module_type=STANDARD_HEADER_IMAGE_TEXT`
- `module_count=5`
- `positions=[1,2,3,4,5]`
- `body_text_list_shape=rich_text_object_list`
- field sources for all 5 modules:
  - `headline=plan.headline`
  - `subheading=plan.subheading`
  - `body=plan.text_content`
  - `alt_text=plan.headline`

`assemble_payload()` evidence:

- `content_module_count=5`
- `uploaded_positions=[1,2,3,4,5]`
- crop size `970x600`
- each assembled body used `[{"value": "...", "decoratorSet": []}]`

Per-position expected field values:

| Position | Role | Headline | Subheading | Body |
| --- | --- | --- | --- | --- |
| 1 | `hero` | `QA M2 Module 1 Value Promise` | `Controlled subtitle 1 for Lingxing field QA` | `Controlled body 1: verifies rich text object list is saved and readable.` |
| 2 | `lifestyle` | `QA M2 Module 2 Everyday Setup` | `Controlled subtitle 2 for Lingxing field QA` | `Controlled body 2: verifies module order remains aligned with plan position.` |
| 3 | `feature_proof` | `QA M2 Module 3 Material Proof` | `Controlled subtitle 3 for Lingxing field QA` | `Controlled body 3: verifies text_content is preferred over key_message.` |
| 4 | `spec_objection` | `QA M2 Module 4 Buyer Questions` | `Controlled subtitle 4 for Lingxing field QA` | `Controlled body 4: verifies the subtitle and body are both visible.` |
| 5 | `closing` | `QA M2 Module 5 Confidence Close` | `Controlled subtitle 5 for Lingxing field QA` | `Controlled body 5: verifies the final module is not dropped or blank.` |

## Lingxing Editor Evidence

Page:

`https://erp.lingxing.com/erp/editAplus?tag_name=%E7%BC%96%E8%BE%91A%2B&idHash=7bdbd01f14dda52fd3363c70c8e535d5&isEdit=1#fbm-pipeline-worker`

DOM audit:

- `document.title=领星ERP - 跨境电商管理系统`
- Login block: not present
- Store visible: `idea_lc@163.com-US`
- Language visible: `英语（美国）`
- Document name visible: `B0GX2GFR73_N726P248345C_1472`
- ASIN table contains `B0GX2GFR73`
- `.ak-card.container` module count containing `带文字的标准图片标题`: `5`
- Each module has exactly one non-placeholder visible image, natural size `970x600`, rendered `970x600`.

Page field extraction:

| Position | Title input | Subtitle input | Body field |
| --- | --- | --- | --- |
| 1 | matched expected | matched expected | expected body text present in visible rich text candidates |
| 2 | matched expected | matched expected | expected body text present in visible rich text candidates |
| 3 | matched expected | matched expected | expected body text present in visible rich text candidates |
| 4 | matched expected | matched expected | expected body text present in visible rich text candidates |
| 5 | matched expected | matched expected | expected body text present in visible rich text candidates |

Screenshot evidence:

- `/Users/liuchang/Documents/gitproject/fbm-pipeline/tmp/lingxing-aplus-m2-real-draft-field-qa-worker-page.png`
- Screenshot shows target document `B0GX2GFR73_N726P248345C_1472`, first module type `带文字的标准图片标题`, title `QA M2 Module 1 Value Promise`, and target QA image.

## Verification Commands

- `git status --short`: dirty tree existed before QA; treated as current collaboration work and not reverted.
- `cd backend && .venv/bin/python -m compileall -q app`: PASS
- `cd backend && .venv/bin/python ../scripts/test_lingxing_aplus_module_mapper.py`: PASS
- `cd backend && .venv/bin/python ../scripts/test_lingxing_aplus_publish_policy.py`: PASS
- `cd backend && .venv/bin/python ../scripts/test_lingxing_aplus_publish_tasks.py`: PASS; fake `auth_required/api_failed/request_failed` tracebacks are expected test branches.
- `make test-project-rules`: PASS, 66 project rule tests.
- `git diff --check`: PASS

## Side Effects

Allowed side effects that occurred:

- Created QA-only local DB sample `Product 1472 / CatalogProduct 1337 / ProductAplus 875`.
- Created 5 local QA images under `/Users/liuchang/Documents/gitproject/fbm-pipeline/tmp/lingxing-aplus-m2-real-draft-field-qa`.
- Created task run `1280`, task step `1286`.
- Saved one real Lingxing test draft through `amazon/aplus/add`, `submitFlag=0`.
- Created local `AplusUploadItem 39` / corresponding completed batch evidence for the QA draft.

Forbidden side effects checked:

- Did not click submit approval.
- Did not set `submitFlag=1`.
- Did not claim or write `draft_visible`.
- Did not confirm Amazon Seller Central visibility.
- Did not change business code.
- Did not commit or push.
- Did not edit `docs/collaboration/inbox.md`.
- Did not save cookie/token/header or full sensitive request.

## Findings

P0: none.

P1: none.

P2: none for the scoped M2 draft field gate.

Non-blocking residual risk:

- QA used a controlled QA-only sample because the current DB had no existing M2-ready `ProductAplus` sample.
- The live FastAPI HTTP endpoint was not exercised; planner + task runtime worker path was exercised directly and is the same save worker path.
- This does not prove `draft_visible`, submit approval, Amazon Seller Central visibility, or content aesthetic/business quality.

## Conclusion

`QA / PASS_WITH_SCOPE`

M2 passes the scoped real Lingxing draft field QA: the mapper-generated 5 `STANDARD_HEADER_IMAGE_TEXT` modules were saved with `submitFlag=0`, re-opened in the Lingxing editor in order, and title/subtitle/body fields were non-empty, visible, readable, and reconciled against local plan/script/mapper expectations.

This conclusion only covers `draft_saved` field visibility/readability for the tested QA sample. It does not cover `draft_visible`, submit approval, Amazon Seller Central visibility, final publication, or content aesthetics.
