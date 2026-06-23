# Lingxing A+ Module Mapping Technical Plan

状态：T3.5 technical plan，已补 M2.0 payload evidence，等待镜花 rereview 后才能实现  
日期：2026-06-23  
Owner：听云（agentKey: `tingyun`）  
PRD：`docs/superpowers/specs/2026-06-23-lingxing-aplus-module-mapping-prd.md`  
Inbox：`MSG-20260623-008`

## 1. 目标和边界

本方案只覆盖 T3.5：把 A+ 生成结果显式映射为当前可信的 Lingxing A+ 草稿模块 payload，阻断空文本或不受支持模块继续保存草稿。

目标：

- 建立 A+ 发布模块 registry，首版只支持 `standard_header_image_text_v1` -> Lingxing `STANDARD_HEADER_IMAGE_TEXT`。
- Step7 / Step8 显式产出并继承 `publish_profile=standard_header_image_text_v1` 和 `lingxing_content_module_type=STANDARD_HEADER_IMAGE_TEXT`。
- 新增 mapper，把 `ProductAplus.aplus_plan`、`aplus_scripts`、`aplus_images` 和上传后的图片 asset 映射为 `contentModuleList`。
- 对未知 profile、未知 Lingxing module type、缺 headline/body、数量或 position 错位、图片尺寸不合格等情况 fail closed，不保存半成品草稿。
- 接入 T3 policy / client / worker：模块映射失败走 policy typed failure；真实外部请求失败仍沿用 T3 task failed/retryable 语义。
- 用测试和 project rules 防止 client 再次硬编码空 `headline.value` 或空 `body.textList`。

禁止范围：

- 不实现 T4 `draft_visible`。
- 不实现 submit approval。
- 不把 Lingxing 发布状态并入商品主 workflow 或商品列表 `work_status`。
- 不猜 17 种 Lingxing 模块全集的 API payload。
- 不用 fixture 或旧空文本草稿当作真实内容结构通过。
- 不修改后端代码、测试脚本或配置，直到本技术方案通过 gate。

## 2. 当前代码事实

已核实文件：

- `backend/app/pipeline/step7_aplus_plan.py`
- `backend/app/pipeline/step8_aplus_script.py`
- `backend/app/services/lingxing_aplus_publish_policy.py`
- `backend/app/services/lingxing_aplus_publish_client.py`
- `backend/app/task_planners/lingxing_aplus_publish.py`
- `backend/app/task_runtime/lingxing_aplus_publish_workers.py`
- `docs/lingxing-aplus-upload.md`
- `scripts/test_project_rules.py`

关键事实：

- Step7 prompt 仍要求混合 A+ 模块，并要求至少一个 comparison/spec 模块；fallback 也产出 `Standard Comparison Chart`、`Standard 4 Image / Text` 等发布端当前不支持的原生语义。
- Step7 保存 `ProductAplus.aplus_plan` JSON 到 `product_aplus.aplus_plan`，当前只强制 5 个模块和 position，未写发布 profile。
- Step8 从 Step7 modules 生成 5 张脚本，设置 `module_position`、图片宽高，并继承 conversion / buyer objection 等策略字段；当前未校验或传播发布 profile。
- Step9 生成 `ProductAplus.aplus_images`；T3 policy 当前只收集 5 张本地 done 图片、校验文件存在和尺寸 `970x600`，并从 plan headline/subheading/key_message 生成 alt text。
- T3 client `_module_payload(image, position)` 当前硬编码 `STANDARD_HEADER_IMAGE_TEXT`，且 `standardHeaderImageText.headline.value=""`、`block.headline.value=""`、`block.body.textList=[]`。
- T3 worker 外部失败分支会先写 sanitized evidence，再抛出 `LingxingAplusDraftSaveClientError`，让 task runtime 标记 failed/retryable；policy 不满足则正常完成并写 typed reason。
- `docs/lingxing-aplus-upload.md` 已记录 `STANDARD_HEADER_IMAGE_TEXT` 非空 payload 结构；M2.0 证据文件为 `docs/collaboration/reviews/2026-06-23-lingxing-standard-header-image-text-payload.md`。

## 3. 总体方案

新增两个实现边界：

1. `backend/app/aplus_publish/module_registry.py`
   - 作为发布模块契约事实源。
   - 定义支持 profile、Lingxing `contentModuleType`、字段要求、图片尺寸、position 范围、错误码和文本限制。
   - mapper、policy/client、project rules 都读取或检查它，禁止 client 独立维护支持字符串。

2. `backend/app/services/lingxing_aplus_module_mapper.py`
   - 作为生成端 JSON 到 Lingxing payload 的唯一映射层。
   - 分成两个阶段：`preflight_validate()` 在任何 Lingxing 外部调用前校验 `ProductAplus` 内容、本地图片、profile、文本、数量和 position；`assemble_payload()` 只在 preflight 通过且图片上传成功后注入 `uploadDestinationId` 并生成 `contentModuleList`。
   - preflight 输入 `ProductAplus` 内容和本地 `AplusPublishAsset`，输出 normalized module draft、模块 evidence 和 typed failure。
   - post-upload assembly 输入 preflight 结果和上传后的 asset，输出 `contentModuleList`。
   - client 只负责认证、图片上传和发送 mapper 组装后的 payload，不再硬编码模块 payload，也不得在 preflight 失败后上传图片。

数据流：

```text
Step7 aplus_plan.modules
  -> explicit publish profile and Lingxing module type
Step8 aplus_scripts.scripts
  -> inherits module_position/profile/type for traceability
Step9 aplus_images
  -> done images with position/path
T3 policy
  -> prerequisites + local image validation + mapper preflight before any Lingxing call
T3 client
  -> upload images only after preflight PASS -> mapper assemble with uploaded ids -> save draft
Lingxing add API
  -> contentModuleList from mapper, submitFlag=0 only
```

## 4. Module Registry

建议新增 `backend/app/aplus_publish/module_registry.py`。

首版 registry 只注册一个 profile：

```python
APLUS_PUBLISH_PROFILE_STANDARD_HEADER_IMAGE_TEXT_V1 = "standard_header_image_text_v1"
LINGXING_STANDARD_HEADER_IMAGE_TEXT = "STANDARD_HEADER_IMAGE_TEXT"
SUPPORTED_APLUS_MODULE_COUNT = 5
SUPPORTED_POSITIONS = range(1, 6)
```

建议结构：

```python
@dataclass(frozen=True)
class AplusPublishModuleSpec:
    profile_key: str
    content_module_type: str
    ui_name: str
    image_min_width: int
    image_min_height: int
    required_fields: tuple[str, ...]
    optional_fields: tuple[str, ...]
    supported_positions: tuple[int, ...]
    body_source_priority: tuple[str, ...]
    alt_text_source_priority: tuple[str, ...]
```

首版 spec：

```python
STANDARD_HEADER_IMAGE_TEXT_V1 = AplusPublishModuleSpec(
    profile_key="standard_header_image_text_v1",
    content_module_type="STANDARD_HEADER_IMAGE_TEXT",
    ui_name="带文字的标准图片标题",
    image_min_width=970,
    image_min_height=600,
    required_fields=("headline", "body"),
    optional_fields=("subheading",),
    supported_positions=(1, 2, 3, 4, 5),
    body_source_priority=("text_content", "key_message"),
    alt_text_source_priority=("headline", "key_message", "product_title"),
)
```

Registry 同时定义 mapper failure codes，供 tests/project rules 校验：

- `unsupported_aplus_publish_profile`
- `unsupported_aplus_module_type`
- `aplus_plan_missing`
- `aplus_modules_invalid`
- `aplus_module_count_invalid`
- `aplus_module_position_invalid`
- `aplus_module_position_duplicate`
- `aplus_module_position_mismatch`
- `aplus_module_headline_missing`
- `aplus_module_body_missing`
- `aplus_asset_count_invalid`
- `aplus_asset_position_mismatch`
- `aplus_asset_image_too_small`
- `lingxing_payload_structure_unverified`

`lingxing_payload_structure_unverified` 是实现 gate 专用错误：如果实现阶段仍无法确认非空 body payload 的真实结构，mapper/client 不能生成草稿保存请求。

## 5. Step7 / Step8 对齐

### Step7

`backend/app/pipeline/step7_aplus_plan.py` 应从“规划多种 Amazon A+ 原生模块”调整为“规划 5 个业务语义段落，并显式声明同一发布 profile”。

Step7 prompt 和 fallback 的目标模块固定为：

1. `hero` / value promise
2. `lifestyle` / usage context
3. `feature_proof` / material or function
4. `spec_objection` / size, compatibility, setup, safety, or buyer doubt
5. `closing` / confidence or cross-sell

每个 `ProductAplus.aplus_plan.modules[*]` 必须包含：

```json
{
  "position": 1,
  "type": "standard_header_image_text",
  "semantic_role": "hero",
  "publish_profile": "standard_header_image_text_v1",
  "lingxing_content_module_type": "STANDARD_HEADER_IMAGE_TEXT",
  "headline": "...",
  "subheading": "...",
  "key_message": "...",
  "text_content": "...",
  "image_concept": "...",
  "conversion_goal": "...",
  "buyer_objection": "...",
  "evidence_source": "...",
  "experience_angle": "...",
  "gallery_overlap_avoidance": "...",
  "risk_guardrails": ["..."],
  "visual_do_not_claim": ["..."]
}
```

Step7 normalization must enforce:

- exactly 5 modules;
- position rewritten to `1..5`;
- `publish_profile` and `lingxing_content_module_type` set from registry, not from LLM free text;
- `type` treated as project-internal semantic/presentation hint, not Lingxing API type;
- no requirement that one module be comparison/spec native module; `spec_objection` is a semantic role rendered through `STANDARD_HEADER_IMAGE_TEXT`.

Fallback modules must be rewritten to the same profile. Existing `Standard Comparison Chart` and `Standard 4 Image / Text` fallback labels should not survive into publishable plans.

### Step8

`backend/app/pipeline/step8_aplus_script.py` should inherit the publish contract for traceability, but Step8 must not become the publishing source of truth.

Required behavior:

- Each script keeps `module_position` aligned with plan position.
- Script entries copy `publish_profile`, `lingxing_content_module_type`, and `semantic_role` from the matching plan module.
- Prompt language should describe the 5 semantic roles and the 1940x1200 image output, not unsupported Lingxing native module types.
- Regeneration functions must preserve or reattach the profile fields when replacing one module script.
- If Step8 receives old modules without profile, it can still generate images for user preview, but later publish mapper must fail closed. Step8 should not silently upgrade old data unless the plan migration rules are approved separately.

## 6. Mapper Contract

建议新增 `backend/app/services/lingxing_aplus_module_mapper.py`。

### Inputs

```python
@dataclass(frozen=True)
class LingxingAplusModuleMappingInput:
    product_id: int
    product_title: str | None
    product_aplus_id: int
    aplus_plan: dict[str, Any]
    aplus_scripts: dict[str, Any] | None
    aplus_images: list[dict[str, Any]]
    uploaded_assets: list[dict[str, Any]]
```

`uploaded_assets` 来自 client 图片上传结果，至少包含：

- `position`
- `uploadDestinationId`
- `altText`
- `width`
- `height`
- `contentType`
- `size`

### Outputs

```python
@dataclass(frozen=True)
class LingxingAplusModuleMappingResult:
    ok: bool
    content_module_list: list[dict[str, Any]] = field(default_factory=list)
    reason_code: str | None = None
    message: str | None = None
    evidence: dict[str, Any] = field(default_factory=dict)
```

Success evidence should include:

- `profile`
- `content_module_type`
- `module_count`
- `positions`
- per-position field source summary, for example `headline=plan.headline`, `body=plan.text_content`, `subheading=plan.subheading|headline_fallback`
- truncation flags and original lengths
- payload structure confirmation source, for example `network_capture_YYYYMMDD` or approved evidence document path

Failure evidence should include the failing position, expected/actual values, and no sensitive external auth headers.

### Validation

Mapper validation order:

1. Parse `aplus_plan` as dict; `modules` must be a list.
2. `modules` count must equal 5.
3. Each module position must be int in `1..5` and unique.
4. Each module `publish_profile` must equal registry `standard_header_image_text_v1`.
5. Each module `lingxing_content_module_type` must equal `STANDARD_HEADER_IMAGE_TEXT`.
6. `headline` after trim must be non-empty.
7. `body` must be derived from first non-empty value in `text_content`, then `key_message`; after trim it must be non-empty.
8. `subheading` may be empty; if empty, `block.headline.value` uses headline only if the confirmed Lingxing payload semantics require a non-empty block headline. This fallback must be recorded in evidence.
9. `uploaded_assets` count must equal 5.
10. Uploaded asset positions must exactly match module positions.
11. Uploaded asset dimensions must satisfy registry image size.
12. Payload structure confirmation gate must pass before producing non-empty `contentModuleList`.

### Text Handling

Mapper should centralize text normalization:

- Convert value to string.
- Trim surrounding whitespace.
- Replace control characters with a single space, except normal line breaks inside body if confirmed accepted by Lingxing.
- Collapse excessive whitespace.
- Enforce field length limits from confirmed Lingxing UI/API facts. If exact limits are not known, use conservative internal limits only after documenting that Lingxing accepted them in a test payload.
- Truncation is allowed only after field remains non-empty; every truncation writes evidence with original length, final length and field name.

Source mapping:

- `headline.value`: `module.headline`; required.
- `block.headline.value`: `module.subheading` if non-empty; otherwise confirmed fallback from headline or omitted/empty according to captured API shape.
- `block.body.textList`: body from `module.text_content`, else `module.key_message`; required.
- image `altText`: `headline`, else `key_message`, else product title; max 100 characters, current T3 behavior can be preserved but should live in mapper or registry-backed helper.

## 7. STANDARD_HEADER_IMAGE_TEXT Payload Confirmation

Current reliable facts:

- The UI module name and image requirement are confirmed in `docs/lingxing-aplus-upload.md`.
- Old code can save empty `STANDARD_HEADER_IMAGE_TEXT` payload with image fields.
- M2.0 confirmed the non-empty serializer structure from the logged-in Lingxing `editAplus` page DOM and public frontend bundle:
  - Evidence: `docs/collaboration/reviews/2026-06-23-lingxing-standard-header-image-text-payload.md`
  - Bundle files: `contentModule-0af405eb.js` and `asinModule-4c23da27.js`
  - `standardHeaderImageText.headline.value` stores title.
  - `standardHeaderImageText.block.headline.value` stores subtitle.
  - `standardHeaderImageText.block.body.textList` is a rich-text object list, not a string list.
  - Plain text body item shape is `{ "value": "...", "decoratorSet": [] }`.

Implementation must use the confirmed rich-text object list structure. It must not change `body.textList` into a string list or another guessed shape.

M2.0 did not capture a real network request body. That is acceptable for implementation because the production frontend serializer and DOM binding are direct evidence for the subtree shape, but the implementation must record this residual risk and QA must verify saved draft field visibility after code gate.

Confirmed payload subtree shape:

```json
{
  "contentModuleType": "STANDARD_HEADER_IMAGE_TEXT",
  "standardHeaderImageText": {
    "headline": {
      "value": "Title",
      "decoratorSet": []
    },
    "block": {
      "image": {
        "uploadDestinationId": "<uploaded-id>",
        "altText": "...",
        "imageCropSpecification": {}
      },
      "headline": {
        "value": "Subtitle",
        "decoratorSet": []
      },
      "body": {
        "textList": [
          {
            "value": "Body text",
            "decoratorSet": []
          }
        ]
      }
    }
  }
}
```

Remaining unknowns:

- `$gwPost` may add wrapper/envelope fields outside `contentDocument`; mapper only owns the `contentModuleList[*].standardHeaderImageText` subtree.
- Lingxing service-side max length, newline and complex rich-text style acceptance are not confirmed. The mapper should emit plain text body items with `decoratorSet=[]`, apply conservative internal limits, and record truncation evidence.
- Real QA after implementation must verify that saved draft fields are visible or readable in Lingxing edit page; this QA still does not mean `draft_visible` or submit.

## 8. T3 Policy / Client / Worker接入

### Policy

`collect_aplus_publish_assets(product)` should remain responsible for local image existence and dimensions, but it should stop being the only content check.

Recommended split:

- Keep local image file validation in policy.
- Move alt text derivation and module validation into mapper, or call a registry-backed helper shared by policy and mapper.
- Extend `AplusPolicyResult` with `module_mapping` or create a separate `build_lingxing_aplus_modules(...)` result used before external call.

Policy failure for mapper errors:

- `status=STATUS_FAILED`
- `reason_code=<mapper reason>`
- `message` in Chinese, explaining publish profile/module/text/image mismatch
- `evidence` with position and source JSON field names

These are local content failures and should complete the step with typed result, not retry external runtime.

### Planner

`backend/app/task_planners/lingxing_aplus_publish.py` currently computes fingerprint from `aplus_plan`, `aplus_scripts` and assets. After mapper exists, fingerprint should include the supported profile and normalized module text evidence so changed headline/body creates a new dedupe key.

Planner still must not:

- create `draft_visible`;
- create submit task;
- trigger automatically from A+ done;
- use product main workflow/work_status.

### Client

`LingxingAplusDraftSaveRequest` should receive a preflight-passed module mapping object, not raw unvalidated `ProductAplus` JSON.

Preferred boundary:

1. Worker/policy calls mapper `preflight_validate()` before constructing or invoking the Lingxing client.
2. If preflight fails, worker writes typed local failure and does not call Lingxing auth, `uploadDestination`, object storage, or `amazon/aplus/add`.
3. Client uploads images only after preflight success.
4. Client or worker calls mapper `assemble_payload(preflight_result, uploaded_assets)` to inject `uploadDestinationId` and image crop data.
5. `_save_draft()` receives `content_module_list` and sends it.

This keeps all semantic validation before external side effects. Post-upload assembly is not allowed to discover unsupported profile, missing text, bad counts, or position mismatch; those must already have been proven by preflight. Assembly may only fail for upload-result mismatches such as missing `uploadDestinationId` or uploaded asset positions that no longer match preflight.

`_save_draft()` must become:

```python
"contentModuleList": mapped.content_module_list
```

`_module_payload(image, position)` should be removed or converted into a registry-backed private helper that requires normalized headline/body input. It must not accept only image+position.

### Worker

`lingxing_aplus_publish_product()` should fail before `STATUS_UPLOADING` and before `external_call` event when mapper validation fails.

Flow:

1. Evaluate prerequisites.
2. Validate local images.
3. Run mapper preflight on plan/scripts/images/assets and registry version.
4. Build content fingerprint from preflight normalized module evidence, plan/scripts/images/assets and registry version.
5. Prepare request metadata.
6. Set `STATUS_READY_TO_UPLOAD`.
7. Client uploads images.
8. Mapper assembles content modules using uploaded ids.
9. Save draft.

External call failure semantics stay unchanged:

- `auth_required`, `api_failed`, `request_failed`, `object_upload_failed`, `upload_destination_missing` continue to raise `LingxingAplusDraftSaveClientError`.
- Worker writes sanitized evidence then raises, preserving task failed/retryable.
- Policy/mapper failures do not call Lingxing and do not become retryable external failures unless code chooses a separate retryable local reason, which this PRD does not require.

## 9. 旧数据策略

Default policy: fail closed.

Old `ProductAplus.aplus_plan` without `publish_profile` or `lingxing_content_module_type` must not be published by the new T3.5 path. It should return:

- `unsupported_aplus_publish_profile` when profile is missing/unknown;
- `unsupported_aplus_module_type` when Lingxing module type is missing/unknown;
- `aplus_module_body_missing` or `aplus_module_headline_missing` when old modules lack text fields.

No automatic migration/backfill in T3.5:

- Existing empty-text Lingxing drafts are not repaired.
- Existing old plans can still be viewed and regenerated through A+ generation flows.
- To publish old data, user must rerun Step7/Step8/Step9 after profile support lands, or a separately approved migration must define deterministic conversion rules.

Reasoning:

- Old `type` values include `Standard Comparison Chart`, `Standard 4 Image / Text` and other unsupported native modules.
- Converting them to `STANDARD_HEADER_IMAGE_TEXT` without user-approved semantics would hide data loss and recreate the current silent coercion bug.

## 10. Cross-Layer Contract Closure

Fact source:

- `backend/app/aplus_publish/module_registry.py`

Producer outputs:

- Step7 `ProductAplus.aplus_plan.modules[*].publish_profile`
- Step7 `ProductAplus.aplus_plan.modules[*].lingxing_content_module_type`
- Step8 `ProductAplus.aplus_scripts.scripts[*]` copied trace fields
- Mapper normalized module payload and evidence

Consumers:

- `lingxing_aplus_module_mapper.py`
- `lingxing_aplus_publish_policy.py`
- `lingxing_aplus_publish_client.py`
- `lingxing_aplus_publish_workers.py`
- `scripts/test_lingxing_aplus_publish_policy.py`
- `scripts/test_lingxing_aplus_publish_tasks.py`
- `scripts/test_project_rules.py`
- `docs/domain-index/product-flow.md`
- `docs/domain-index/task-runtime.md`
- `docs/lingxing-aplus-upload.md`

Unknown/empty/old value strategy:

- Unknown profile: fail closed.
- Unknown Lingxing content module type: fail closed.
- Missing headline/body: fail closed.
- Missing subheading: allowed only if confirmed payload can represent it; evidence records fallback/empty behavior.
- Old plan without profile: fail closed.
- Mapper validation failure: local typed policy failure, no external save.
- External Lingxing failure: T3 existing retryable task failed path.

No DB predicate/index/statistics change:

- This task adds no database field and no product work status.
- It does not change task list status schema beyond existing T3 failed/succeeded behavior.
- It does not add product list filter, overview bucket, or workflow node.

## 11. Testing Strategy

### Mapper tests

Create focused behavior tests, likely `scripts/test_lingxing_aplus_module_mapper.py`:

- valid 5-module `standard_header_image_text_v1` plan produces 5 `STANDARD_HEADER_IMAGE_TEXT` payloads.
- headline/subheading/body are populated from `headline`, `subheading`, `text_content`.
- when `text_content` is empty, body uses `key_message`.
- source text present means payload title/body are non-empty.
- missing headline fails with `aplus_module_headline_missing`.
- missing body fails with `aplus_module_body_missing`.
- missing/unknown profile fails with `unsupported_aplus_publish_profile`.
- missing/unknown Lingxing module type fails with `unsupported_aplus_module_type`.
- module count not 5 fails with `aplus_module_count_invalid`.
- duplicate/out-of-range positions fail with position reason codes.
- uploaded asset positions not equal module positions fail with `aplus_asset_position_mismatch`.
- image too small fails with registry-backed size code.
- text normalization trims and records truncation evidence.

### Policy / worker tests

Extend existing T3 scripts:

- `scripts/test_lingxing_aplus_publish_policy.py`
  - `collect_aplus_publish_assets` or the new policy boundary reports mapper failure reason before external call.
  - old plan without profile fails closed.

- `scripts/test_lingxing_aplus_publish_tasks.py`
  - worker does not invoke fake client when module mapping fails.
  - mapping failure writes task result/progress with typed reason and does not create `AplusUploadItem`.
  - external `auth_required/api_failed/request_failed` still makes TaskRun failed/retryable as T3 requires.
  - success evidence includes module profile, module count and non-empty field-source summary.

### Project rules

Extend `scripts/test_project_rules.py`:

- registry file exists and contains `standard_header_image_text_v1`, `STANDARD_HEADER_IMAGE_TEXT`, positions 1..5 and reason code constants.
- client no longer contains production path with `headline": {"value": ""}` or `body": {"textList": []}`.
- client `_save_draft` consumes mapper output or calls mapper; it must not build modules from only `(image, position)`.
- Step7 prompt/fallback no longer require unsupported comparison/spec native module types as publishable modules.
- Step7 writes publish profile and Lingxing module type from constants/registry.
- Step8 preserves publish profile/module type through script generation and regeneration.
- mapper tests are listed in project rule runner.

### Verification commands for implementation phase

Expected verification after code implementation:

```bash
cd backend && .venv/bin/python -m compileall -q app
cd backend && .venv/bin/python ../scripts/test_lingxing_aplus_module_mapper.py
cd backend && .venv/bin/python ../scripts/test_lingxing_aplus_publish_policy.py
cd backend && .venv/bin/python ../scripts/test_lingxing_aplus_publish_tasks.py
make test-project-rules
git diff --check
```

Real QA after code gate:

- With approved real Lingxing test context, save a draft and verify 5 modules stay in order.
- Confirm each module title/subtitle/body is visible in Lingxing editor or readable through a confirmed draft payload.
- Do not confirm `draft_visible`.
- Do not submit.

## 12. 文档和索引影响

Implementation should update:

- `docs/lingxing-aplus-upload.md`
  - Add confirmed non-empty `STANDARD_HEADER_IMAGE_TEXT` payload structure evidence.
  - Record whether confirmation involved an external draft side effect.

- `docs/domain-index/product-flow.md`
  - Update Lingxing A+ section after mapper/profile lands.

- `docs/domain-index/task-runtime.md`
  - Add mapper validation gate and new verification script.

- `docs/project-index.md`
  - Add `backend/app/aplus_publish/module_registry.py` and `backend/app/services/lingxing_aplus_module_mapper.py` to A+ route after implementation.

No update required in this T3.5 document-only task beyond this technical plan and the inbox summary.

## 13. 分阶段实现计划

### M2.0 Payload Evidence Gate

- Goal: Confirm non-empty `STANDARD_HEADER_IMAGE_TEXT` payload structure before code maps body.
- Inputs: logged-in Lingxing session or existing non-empty payload evidence.
- Outputs: evidence note in docs; exact body/title/subtitle payload subtree.
- Files: `docs/lingxing-aplus-upload.md` or `docs/collaboration/reviews/<date>-lingxing-standard-header-image-text-payload.md`.
- Forbidden: submit approval, draft visibility sync, unapproved external write.
- Verification: evidence includes redacted request subtree and no-submit statement.
- Gate: complete. Evidence file exists at `docs/collaboration/reviews/2026-06-23-lingxing-standard-header-image-text-payload.md`; no real save occurred in this M2.0 pass.

### M2.1 Registry and Mapper

- Goal: Add module registry and mapper with fail-closed preflight and post-upload assembly.
- Inputs: PRD, payload evidence, current ProductAplus JSON shapes.
- Outputs: registry, mapper preflight, mapper post-upload assembly, mapper behavior tests.
- Files:
  - `backend/app/aplus_publish/module_registry.py`
  - `backend/app/services/lingxing_aplus_module_mapper.py`
  - `scripts/test_lingxing_aplus_module_mapper.py`
- Forbidden: Lingxing external call behavior changes beyond proving that semantic preflight is callable before any client invocation.
- Verification: mapper script + compileall.
- Gate: 若命 review; 镜花 review recommended because this is a cross-layer semantic contract.

### M2.2 Step7 / Step8 Producer Alignment

- Goal: Make new A+ generation explicitly produce supported publish profile.
- Inputs: registry constants and existing Step7/Step8 behavior.
- Outputs: Step7 prompt/fallback/normalization aligned; Step8 generation/regeneration preserves trace fields.
- Files:
  - `backend/app/pipeline/step7_aplus_plan.py`
  - `backend/app/pipeline/step8_aplus_script.py`
  - mapper/Step tests as needed
- Forbidden: changing Step9 image generation, product workflow, A+ done auto publish.
- Verification: focused Step7/Step8 fixture test if available; mapper tests with generated sample; project rules.
- Gate: 若命 review; 镜花 review if prompt/producer contract concerns remain.

### M2.3 T3 Policy / Client / Worker Integration

- Goal: Save Lingxing draft only with mapper-produced `contentModuleList`.
- Inputs: registry, mapper, current T3 policy/client/worker.
- Outputs: policy typed failures; preflight runs before Lingxing auth/upload/add; client no hardcoded empty payload; worker stops before external call on mapping failure; post-upload assembly injects only uploaded IDs/crop data; success evidence includes module mapping summary.
- Files:
  - `backend/app/services/lingxing_aplus_publish_policy.py`
  - `backend/app/services/lingxing_aplus_publish_client.py`
  - `backend/app/task_planners/lingxing_aplus_publish.py`
  - `backend/app/task_runtime/lingxing_aplus_publish_workers.py`
  - `scripts/test_lingxing_aplus_publish_policy.py`
  - `scripts/test_lingxing_aplus_publish_tasks.py`
- Forbidden: draft visibility, submit, product workflow/work_status.
- Verification: policy/task scripts + compileall.
- Gate: 若命 review; 镜花 code review required due to external side effect and task lifecycle.

### M2.4 Project Rules, Docs, Indexes

- Goal: Lock contract and update navigation.
- Inputs: final implemented files.
- Outputs: project rules prevent regression; docs/indexes point to new registry/mapper.
- Files:
  - `scripts/test_project_rules.py`
  - `docs/lingxing-aplus-upload.md`
  - `docs/project-index.md`
  - `docs/domain-index/product-flow.md`
  - `docs/domain-index/task-runtime.md`
- Forbidden: unrelated doc cleanup.
- Verification:
  - `make test-project-rules`
  - `git diff --check`
- Gate: 若命 review; 观止 QA only after code gate and real test context is approved.

## 14. 未解决问题 / REQUEST 条件

1. Exact Lingxing service-side text length limits are not known from current docs. Implementation should use documented conservative limits, plain text rich-text objects with `decoratorSet=[]`, and truncation evidence; real QA must verify the saved draft remains readable.
2. Whether `block.headline.value` must be non-empty is not service-side confirmed. Mapper should populate it from `subheading` when available, and fall back to `headline` only when `subheading` is empty, recording the fallback in evidence.
3. M2.0 did not capture the actual network request body. This is acceptable for implementation because the production frontend serializer is direct evidence for the module subtree, but it remains a real QA check after code gate.

## 15. Completion Definition for T3.5 Implementation

After implementation, the task is complete only when:

- New generated plans explicitly carry `standard_header_image_text_v1` and `STANDARD_HEADER_IMAGE_TEXT`.
- Mapper is the only production path that creates `contentModuleList`.
- Client no longer hardcodes empty headline/body payload.
- Missing/unsupported/old module data fails closed before external save.
- T3 external failures still enter failed/retryable task semantics.
- Project rules catch producer/consumer drift and empty payload regression.
- Docs/indexes identify registry, mapper, payload evidence and verification entry points.
- Real QA can verify non-empty title/subtitle/body in Lingxing draft without advancing `draft_visible` or submit.
