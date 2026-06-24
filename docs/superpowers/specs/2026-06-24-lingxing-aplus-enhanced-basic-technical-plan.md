# Lingxing Enhanced Basic A+ Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `enhanced_basic_aplus_v1` as a first-class, verified, draft-saveable Lingxing basic A+ publish profile.

**Architecture:** Treat the enhanced A+ layout as a registry-backed profile with fixed business roles, module specs, image slots, text/table specs, and typed failures. Step7/Step8 produce business content and asset intent; registry/mapper/policy own publishability and Lingxing payload assembly; client/worker remain draft-save only.

**Tech Stack:** Python backend, SQLAlchemy models already in place, JSON fields on `ProductAplus`, Lingxing gateway `amazon/aplus/add`, existing task runtime, existing script-style behavior tests and project rules.

---

状态：M3.1 technical plan，等待若命和镜花 gate 后才能实现
日期：2026-06-24
Owner：听云（agentKey: `tingyun`）
Inbox：`MSG-20260624-002`
PRD：`docs/superpowers/specs/2026-06-24-lingxing-aplus-enhanced-basic-prd.md`
Evidence：`docs/collaboration/reviews/2026-06-24-lingxing-enhanced-basic-aplus-payload-evidence.md`

## 1. 目标和边界

本方案覆盖 `enhanced_basic_aplus_v1` 增强版普通 A+，首版固定 5 个 Lingxing basic A+ 标准模块：

| position | semantic_role | Lingxing module | fixed option |
|---|---|---|---|
| 1 | `hero` | `STANDARD_IMAGE_TEXT_OVERLAY` | `overlayColorType="DARK"` |
| 2 | `feature_grid` | `STANDARD_THREE_IMAGE_TEXT` | 3 image/text blocks |
| 3 | `detail_proof` | `STANDARD_SINGLE_IMAGE_SPECS_DETAIL` | 1 image + description/spec blocks |
| 4 | `comparison` | `STANDARD_COMPARISON_TABLE` | 2 product columns minimum |
| 5 | `technical_or_closing` | `STANDARD_TECH_SPECS` | no image, 4+ spec rows |

目标：

- 新增 registry-backed profile：`enhanced_basic_aplus_v1`。
- 让 Step7 从 5 个同形态段落升级为固定业务角色 schema；LLM 只生成业务内容，后端赋值 profile/type/slot contract。
- 让 Step8/Step9 从“每 module 一张 1940x1200 图”升级为按 registry image slot 生成或复用素材；无图模块不生成无用图片。
- 让 mapper 通过 registry 完成多模块 preflight 和 payload assembly，在任何 Lingxing auth/upload/add 前 fail closed。
- 保留旧 `standard_header_image_text_v1` 路径，不静默升级旧 plan，不把增强版失败 fallback 成旧模块。
- 保留 T3 生命周期：只保存草稿，成功只写 `draft_saved + amazon_draft_visibility=unconfirmed`，不声明 `draft_visible`，不 submit。

禁止范围：

- 不实现 Premium / 高级 A+、品牌故事、draft visibility、submit approval、Amazon Seller Central 可见性。
- 不修改商品主 workflow / 商品列表 `work_status`。
- 不恢复旧 `aplus_upload.py` batch runner 或裸 `asyncio.create_task()` 发布路径。
- 不把缺字段、缺图、比较列缺 ASIN、未确认 payload 的模块降级保存为 `STANDARD_HEADER_IMAGE_TEXT`。
- 不编码、不提交、不 push；实现必须等若命和镜花方案 gate 通过。

## 2. 当前代码事实

已核实入口：

- `backend/app/aplus_publish/module_registry.py`
- `backend/app/services/lingxing_aplus_module_mapper.py`
- `backend/app/services/lingxing_aplus_publish_policy.py`
- `backend/app/services/lingxing_aplus_publish_client.py`
- `backend/app/task_planners/lingxing_aplus_publish.py`
- `backend/app/task_runtime/lingxing_aplus_publish_workers.py`
- `backend/app/pipeline/step7_aplus_plan.py`
- `backend/app/pipeline/step8_aplus_script.py`
- `backend/app/pipeline/step9_aplus_image.py`
- `scripts/test_lingxing_aplus_module_mapper.py`
- `scripts/test_lingxing_aplus_publish_policy.py`
- `scripts/test_lingxing_aplus_publish_tasks.py`
- `scripts/test_project_rules.py`
- `docs/lingxing-aplus-upload.md`

关键事实：

- Registry 当前只支持 `standard_header_image_text_v1` / `STANDARD_HEADER_IMAGE_TEXT`，且 `AplusPublishModuleSpec` 假设单模块 spec 可套 5 个 position。
- Mapper 当前 `preflight_validate()` 要求 5 个 module、5 张 asset、position 1..5、同一个 profile/type；`assemble_payload()` 只生成 `standardHeaderImageText`。
- Policy 当前 `collect_aplus_publish_assets()` 只取 `ProductAplus.aplus_images` 前 5 张 `status=done` 本地图片，并按 970x600 校验。
- Client 边界是正确的：先检查 mapping ok；真实外部调用默认关闭；上传图片后调用 mapper `assemble_payload()`，再用 mapper 的 `contentModuleList` 保存草稿；不支持 submit。
- Worker/planner 已在 external call 前做 asset collection 和 mapper preflight；成功只写 `draft_saved` 和 `amazon_draft_visibility=unconfirmed`。
- Step7 当前会强制写旧 profile/type；业务角色是 `hero/lifestyle/feature_proof/spec_objection/closing`，不符合新 PRD 的 `hero/feature_grid/detail_proof/comparison/technical_or_closing`。
- Step8/Step9 当前所有脚本和图片都被规范化为全局 `settings.APLUS_IMAGE_WIDTH/HEIGHT`，运行时只处理前 5 张 module images；这与增强版多图/无图模块不兼容。
- Project rules 当前对 M2 多数是字符串存在检查，能锁旧 client 不硬编码空 payload，但不能反向证明 Step7 可产出的 profile/type/slot 都被 registry/mapper/client/tests 支持。

M3.0 evidence 足以设计首版五模块；不需要对首版模块写 `REQUEST / DESIGN_CHANGE`。但 comparison 模块有业务数据前置：Lingxing `STANDARD_COMPARISON_TABLE` 要求至少 2 个 product columns，且每列 ASIN 满足 `^[A-Z0-9]{10}$`。实现阶段必须从当前商品 ASIN 和已确认竞品/对比 ASIN 取值；缺少第二列 ASIN 时增强版 profile 应 typed fail closed，不能自动降级。

## 3. 总体方案

新增或强化三个边界：

1. Registry 作为跨层语义事实源。
   - 定义 profile、module sequence、module specs、image slots、text/rich-text fields、comparison/spec table fields、length limits、failure codes、payload evidence。
   - Step7/Step8/policy/mapper/tests/docs 全部引用或校验 registry，不从字符串散落定义反推。

2. Asset manifest 作为图片槽位事实。
   - `ProductAplus.aplus_images` 不再只表达 5 个 position images；增强版写入 slot-level assets。
   - 每个 asset 必须包含 `asset_slot_id`、`module_position`、`semantic_role`、`payload_slot`、`target_width`、`target_height`、`path/url/status/width/height/alt_text`。
   - 旧 profile 继续兼容 `position=1..5` 的 5 张图，不迁移旧数据。

3. Mapper 作为 Lingxing payload 唯一生成层。
   - `preflight_validate()` 在任何 Lingxing auth、uploadDestination、对象存储上传、`amazon/aplus/add` 前完成 plan/profile/type/text/table/image slot 校验。
   - `assemble_payload()` 只接收 preflight normalized result 和上传结果，按 registry payload paths 注入 `uploadDestinationId`、alt/crop、rich text、comparison metrics、spec rows，生成 `contentModuleList`。
   - Client 永远不硬编码 fallback module。

数据流：

```text
Step7
  -> plan.profile = enhanced_basic_aplus_v1
  -> modules[5] with fixed business roles and backend-assigned module types
Step8
  -> module scripts + image_slots from registry; no-image modules keep text/spec/table only
Step9
  -> slot-level assets generated/reused; ProductAplus.aplus_images stores asset manifest
Policy / planner / worker
  -> local prerequisites + collect assets by slot + mapper preflight before external call
Client
  -> upload required image slots only after preflight PASS
Mapper assemble
  -> Lingxing contentModuleList in fixed order
Lingxing add
  -> submitFlag=0 only
State
  -> draft_saved + amazon_draft_visibility=unconfirmed only
```

## 4. Registry Design

Modify: `backend/app/aplus_publish/module_registry.py`

New constants:

- `APLUS_PUBLISH_PROFILE_ENHANCED_BASIC_APLUS_V1 = "enhanced_basic_aplus_v1"`
- `LINGXING_STANDARD_IMAGE_TEXT_OVERLAY = "STANDARD_IMAGE_TEXT_OVERLAY"`
- `LINGXING_STANDARD_THREE_IMAGE_TEXT = "STANDARD_THREE_IMAGE_TEXT"`
- `LINGXING_STANDARD_SINGLE_IMAGE_SPECS_DETAIL = "STANDARD_SINGLE_IMAGE_SPECS_DETAIL"`
- `LINGXING_STANDARD_COMPARISON_TABLE = "STANDARD_COMPARISON_TABLE"`
- `LINGXING_STANDARD_TECH_SPECS = "STANDARD_TECH_SPECS"`

Keep existing:

- `APLUS_PUBLISH_PROFILE_STANDARD_HEADER_IMAGE_TEXT_V1`
- `LINGXING_STANDARD_HEADER_IMAGE_TEXT`
- existing M2 failure codes, expanded as below.

Recommended dataclasses:

```python
@dataclass(frozen=True)
class AplusImageSlotSpec:
    slot_id: str
    payload_path: tuple[str, ...]
    required: bool
    min_width: int
    min_height: int
    crop_width: int
    crop_height: int
    alt_text_required: bool = True
    alt_text_max_length: int = 100

@dataclass(frozen=True)
class AplusTextFieldSpec:
    field_id: str
    payload_path: tuple[str, ...]
    required: bool
    max_length: int
    rich_text: bool = False
    max_line_length: int | None = None

@dataclass(frozen=True)
class AplusComparisonSpec:
    min_columns: int
    max_columns: int
    min_metric_rows: int
    max_metric_rows: int
    asin_required: bool
    title_max_length: int
    metric_label_max_length: int
    metric_value_max_length: int

@dataclass(frozen=True)
class AplusSpecTableSpec:
    min_rows: int
    max_rows: int
    label_max_length: int
    description_max_length: int
    table_count_values: tuple[int, ...]

@dataclass(frozen=True)
class AplusModuleSpec:
    spec_key: str
    content_module_type: str
    ui_name: str
    payload_key: str
    image_slots: tuple[AplusImageSlotSpec, ...]
    text_fields: tuple[AplusTextFieldSpec, ...]
    comparison: AplusComparisonSpec | None = None
    spec_table: AplusSpecTableSpec | None = None
    fixed_values: dict[str, Any] = field(default_factory=dict)
    payload_evidence: str = ""

@dataclass(frozen=True)
class AplusProfileModuleBinding:
    position: int
    semantic_role: str
    internal_type: str
    module_spec_key: str

@dataclass(frozen=True)
class AplusProfileSpec:
    profile_key: str
    profile_version: str
    tier: str
    module_count: int
    module_sequence: tuple[AplusProfileModuleBinding, ...]
    payload_evidence: str
```

Enhanced module specs:

- `image_text_overlay_dark`
  - `content_module_type=STANDARD_IMAGE_TEXT_OVERLAY`
  - `payload_key=standardImageTextOverlay`
  - `fixed_values={"overlayColorType": "DARK"}`
  - image slot `hero.image`: 970x300, path `standardImageTextOverlay.block.image`
  - text: `block.headline` max 70 required, `block.body` rich text max 300 required.

- `three_image_text`
  - `content_module_type=STANDARD_THREE_IMAGE_TEXT`
  - image slots `feature_1.image`, `feature_2.image`, `feature_3.image`: each 300x300.
  - text: main headline max 200; each block headline max 160; each block body rich text max 1000.

- `single_image_specs_detail`
  - `content_module_type=STANDARD_SINGLE_IMAGE_SPECS_DETAIL`
  - image slot `detail.image`: 300x300.
  - text: headline max 200; description headline max 160; description block headlines max 200; description bodies rich text max 400; specification headline max 160; spec list rows.

- `comparison_table`
  - `content_module_type=STANDARD_COMPARISON_TABLE`
  - image slots for enabled columns; V1 uses exactly two required columns:
    - `comparison.column_1.image`: 150x300
    - `comparison.column_2.image`: 150x300
  - comparison spec: min/max columns for V1 = 2, metric rows 3..6, ASIN required, title max 80, metric label max 100, metric value max 250.
  - Future columns 3..6 stay unregistered until product and asset sourcing are designed.

- `tech_specs`
  - `content_module_type=STANDARD_TECH_SPECS`
  - no image slots.
  - spec table: min rows 4, max rows 16, label max 30, description max 500, `tableCount` in `(1, 2)`; V1 default `tableCount=1`.

Failure codes to add:

- `aplus_profile_module_sequence_mismatch`
- `aplus_module_semantic_role_mismatch`
- `aplus_module_spec_unregistered`
- `aplus_image_slot_missing`
- `aplus_image_slot_duplicate`
- `aplus_image_slot_unexpected`
- `aplus_image_slot_dimension_invalid`
- `aplus_alt_text_missing`
- `aplus_alt_text_too_long`
- `aplus_text_field_missing`
- `aplus_text_field_too_long`
- `aplus_rich_text_invalid`
- `aplus_comparison_column_count_invalid`
- `aplus_comparison_column_asin_missing`
- `aplus_comparison_column_asin_invalid`
- `aplus_comparison_metric_rows_invalid`
- `aplus_comparison_metric_value_missing`
- `aplus_spec_rows_invalid`
- `aplus_payload_builder_missing`
- `lingxing_payload_structure_unverified`

Registry must expose helper APIs:

- `get_profile_spec(profile_key)`
- `get_module_spec(spec_key)`
- `get_module_spec_for_binding(profile_key, position, module_type)`
- `iter_profile_module_specs(profile_key)`
- `required_image_slots(profile_key)`
- `producer_contract_for_profile(profile_key)` for Step7/Step8/tests.

Evidence file:

- All five enhanced specs must point to `docs/collaboration/reviews/2026-06-24-lingxing-enhanced-basic-aplus-payload-evidence.md`.
- Old `STANDARD_HEADER_IMAGE_TEXT` keeps `docs/collaboration/reviews/2026-06-23-lingxing-standard-header-image-text-payload.md`.

## 5. Step7 Schema

Modify: `backend/app/pipeline/step7_aplus_plan.py`

Design:

- Add a local profile selector, initially hard-coded to `enhanced_basic_aplus_v1` only when the implementing task explicitly switches generation to the enhanced profile. Do not rewrite old existing plans.
- Step7 prompt asks the LLM for business content by semantic role only. It must not ask the LLM to choose Lingxing module types.
- After LLM/fallback returns business content, backend normalizer applies registry bindings:
  - `publish_profile`
  - `profile_version`
  - `type` / internal module type
  - `semantic_role`
  - `lingxing_content_module_type`
  - `module_spec_key`
  - `position`
  - module-specific field scaffolds.

Top-level plan shape:

```json
{
  "aplus_plan_version": "enhanced_basic_aplus_v1",
  "publish_profile": "enhanced_basic_aplus_v1",
  "profile_version": "1",
  "module_contract_source": "backend/app/aplus_publish/module_registry.py",
  "modules": []
}
```

Module shapes:

- `hero`
  - LLM fields: `headline`, `body`, `image_concept`, `alt_text_seed`, conversion fields.
  - Backend fields: `type="standard_image_text_overlay"`, `lingxing_content_module_type="STANDARD_IMAGE_TEXT_OVERLAY"`, `overlayColorType="DARK"`.

- `feature_grid`
  - LLM fields: `headline`, `features[3]`.
  - Each feature: `headline`, `body`, `image_concept`, `alt_text_seed`.
  - Backend fields: `type="standard_three_image_text"`, `feature_slots=["feature_1","feature_2","feature_3"]`.

- `detail_proof`
  - LLM fields: `headline`, `description_headline`, `description_blocks[2]`, `spec_items[3..6]`, `spec_note`, `image_concept`, `alt_text_seed`.
  - Backend fields: `type="standard_single_image_specs_detail"`.

- `comparison`
  - LLM fields: `headline`, `metric_row_labels[3..6]`, `current_product_metric_values`, `comparison_product_metric_values`, `comparison_angle`.
  - Backend sourced fields: product column ASIN/title/image source.
  - Required data source: current product ASIN plus one comparison ASIN from existing competitor/candidate facts. If unavailable, Step7 may still save plan as draft generation content, but publish mapper must fail closed with `aplus_comparison_column_asin_missing`.
  - LLM must not invent ASINs.

- `technical_or_closing`
  - LLM fields: `headline`, `spec_rows[4..10]` with label/description, `closing_note` optional.
  - Backend fields: `type="standard_tech_specs"`, `tableCount=1`.

Fallback:

- Fallback plan must also use the same enhanced schema and registry bindings.
- No fallback module may use `standard_header_image_text_v1` inside an enhanced plan.
- If the implementation keeps a config to generate old `standard_header_image_text_v1`, that config path must produce only the old schema and be tested separately.

## 6. Step8 and Step9 Schema

Modify:

- `backend/app/pipeline/step8_aplus_script.py`
- `backend/app/pipeline/step9_aplus_image.py`

Step8 design:

- Replace `_normalize_script_count_and_size()` for enhanced profile with a registry-driven normalizer.
- Output is module-level scripts plus image slot scripts, not exactly 5 flat image scripts.

Recommended shape:

```json
{
  "publish_profile": "enhanced_basic_aplus_v1",
  "profile_version": "1",
  "scripts": [
    {
      "module_position": 2,
      "semantic_role": "feature_grid",
      "lingxing_content_module_type": "STANDARD_THREE_IMAGE_TEXT",
      "module_spec_key": "three_image_text",
      "text_payload": {},
      "image_slots": [
        {
          "asset_slot_id": "m2_feature_1_image",
          "payload_slot": "standardThreeImageText.block1.image",
          "target_width": 300,
          "target_height": 300,
          "alt_text": "...",
          "prompt": "...",
          "reference_images": []
        }
      ]
    }
  ]
}
```

Rules:

- Hero produces 1 image slot at 970x300.
- Feature grid produces 3 image slots at 300x300.
- Detail proof produces 1 image slot at 300x300.
- Comparison produces 2 image slots at 150x300 for the two enabled product columns.
- Technical specs produces 0 image slots.
- Text/table/spec values remain in the module script or plan and must carry through to mapper; no-image modules must not get placeholder image scripts.
- Each script and slot preserves `publish_profile`, `module_position`, `semantic_role`, `lingxing_content_module_type`, `module_spec_key`.
- Regeneration by module:
  - Regenerating `hero` regenerates its one slot and keeps registry fields fixed.
  - Regenerating `feature_grid` can regenerate all three slots or a specific child slot; if current API only supports module-level regeneration, regenerate all slots in that module.
  - Regenerating `technical_or_closing` regenerates text/spec rows only, no image.
  - Regeneration must never change `publish_profile`, `lingxing_content_module_type`, `semantic_role`, `module_spec_key`, image slot ids, or required table/column count.

Step9 design:

- For enhanced profile, iterate every `scripts[*].image_slots[*]` rather than `scripts[:5]`.
- `_generate_single_image()` must use slot `target_width/target_height`; do not use global `settings.APLUS_IMAGE_WIDTH/HEIGHT` for enhanced slots.
- `ProductAplus.aplus_images` stores slot manifest:

```json
[
  {
    "asset_slot_id": "m2_feature_1_image",
    "module_position": 2,
    "semantic_role": "feature_grid",
    "payload_slot": "standardThreeImageText.block1.image",
    "status": "done",
    "path": "/abs/path.jpg",
    "url": "https://...",
    "width": 300,
    "height": 300,
    "target_width": 300,
    "target_height": 300,
    "alt_text": "...",
    "content_type": "image/jpeg"
  }
]
```

- `ProductAplus.aplus_image_count` counts successful image slots, not modules. Enhanced V1 expected count is 7 image slots: 1 + 3 + 1 + 2 + 0.
- Existing old profile behavior remains position-based 5 images and global size.

## 7. Mapper Multi-Module Design

Modify: `backend/app/services/lingxing_aplus_module_mapper.py`

Preflight input:

- `product` with `ProductAplus.aplus_plan`, `aplus_scripts`, `aplus_images`.
- `assets` from policy, now slot-aware.
- Existing old profile can still pass position-aware assets.

Preflight sequence:

1. Parse plan JSON and require top-level `publish_profile`.
2. Load profile spec from registry; unknown or missing profile returns `unsupported_aplus_publish_profile`.
3. Validate exactly the registry module sequence:
   - positions 1..5,
   - semantic roles match,
   - module spec keys match,
   - `lingxing_content_module_type` matches registry binding.
4. Validate every module field:
   - required text present after cleanup,
   - length limits,
   - rich-text bodies converted only from plain strings/list rows into `{value, decoratorSet: []}`,
   - no empty rich text list.
5. Validate every image slot:
   - all required slots present,
   - no unexpected slots for the profile,
   - local file exists before any upload,
   - actual width/height meet registry crop size,
   - alt text present and <=100.
6. Validate comparison table:
   - exactly 2 enabled columns in V1,
   - each column has image, title, ASIN, highlight, and metric values,
   - ASIN regex `^[A-Z0-9]{10}$`,
   - metric row labels align with every column's metric positions,
   - no empty first metric.
7. Validate tech specs:
   - at least 4 rows,
   - no row with only label or only description,
   - label/description length limits,
   - `tableCount` in registry allowed values.
8. Validate every module spec has `payload_evidence`; missing evidence returns `lingxing_payload_structure_unverified`.

Normalized result should include:

- profile key/version,
- ordered normalized modules,
- ordered required image slots,
- comparison/spec rows after cleanup,
- field source/truncation evidence,
- evidence file path,
- `content_module_types` list.

Assembly:

- Upload result map key must be `asset_slot_id`, not only module position.
- Missing uploaded id returns `aplus_uploaded_asset_missing_id`.
- Generate `contentModuleList` in profile order:
  - Hero:
    - `contentModuleType="STANDARD_IMAGE_TEXT_OVERLAY"`
    - `standardImageTextOverlay.overlayColorType="DARK"`
    - image at `block.image`
    - headline/body rich text object/list.
  - Feature grid:
    - `standardThreeImageText.headline`
    - `block1..3.image/headline/body`.
  - Detail proof:
    - `standardSingleImageSpecsDetail.image`
    - description blocks,
    - `specificationListBlock.block.textList[*].position/text`,
    - `specificationTextBlock`.
  - Comparison:
    - `standardComparisonTable.productColumns[*]`
    - `metricRowLabels[*]`
    - images by column slot,
    - highlight true for current product column only unless plan explicitly marks otherwise.
  - Tech specs:
    - `standardTechSpecs.headline`
    - `tableCount`
    - `specificationList[*].label/description`.

Do not include UI-only fields in Lingxing payload. Keep `position` only if current mapper evidence shows it is tolerated; otherwise position should stay internal evidence, not payload subtree.

## 8. Image Asset Strategy

Modify:

- `backend/app/services/lingxing_aplus_publish_policy.py`
- `backend/app/pipeline/step8_aplus_script.py`
- `backend/app/pipeline/step9_aplus_image.py`

Strategy:

- Source of truth for required images is registry image slots.
- Enhanced V1 requires 7 image slots, not 5 modules and not five 970x600 images.
- Slot sizes:
  - hero: 970x300
  - feature grid: 3 x 300x300
  - detail proof: 300x300
  - comparison: 2 x 150x300
  - technical specs: no image.

Asset source priority:

1. Existing generated enhanced slot asset with matching `asset_slot_id`, `status=done`, local path, and correct dimensions.
2. Existing A+ generated image only when it has matching enhanced slot metadata; do not infer feature grid slots from old position images.
3. Step9 generated new slot image using Step8 slot prompt and selected references.
4. For comparison column images:
   - current product column can use a generated or product identity slot image.
   - comparison column must use confirmed competitor/comparison ASIN facts and an available/generatable image tied to that comparison column.
   - If no second ASIN/image source exists, fail closed with typed reason; do not create fake ASINs or a generic placeholder column.

Policy changes:

- Rename or generalize `collect_aplus_publish_assets()` internally to be profile-aware while preserving public function name if useful for minimizing call-site churn.
- It should parse plan profile first, load registry required slots, then collect exactly those slots.
- For old `standard_header_image_text_v1`, keep current five position image behavior and 970x600 min size.
- For enhanced profile, require slot IDs and slot dimensions.

Fingerprint:

- `build_aplus_content_fingerprint()` must include:
  - profile key/version,
  - registry module sequence version or stable registry snapshot,
  - normalized mapper evidence,
  - slot IDs and dimensions,
  - content module types,
  - comparison ASINs and spec rows.

## 9. Client, Worker, Task Lifecycle

Modify:

- `backend/app/services/lingxing_aplus_publish_client.py`
- `backend/app/task_planners/lingxing_aplus_publish.py`
- `backend/app/task_runtime/lingxing_aplus_publish_workers.py`

Client rules:

- Keep `LINGXING_APLUS_ALLOW_REAL_EXTERNAL_CALLS=false` default.
- Keep `LINGXING_APLUS_SUBMIT_FOR_APPROVAL=false`; if true, still raise `submit_not_supported_in_t3`.
- Keep `submitFlag=0`.
- Upload only image slots from preflight result.
- Use upload result `asset_slot_id` and `payload_slot`; `altText` comes from mapper normalized slot, not client fallback.
- Save only mapper-produced `contentModuleList`.
- Evidence may include sanitized summary:
  - profile,
  - module types,
  - image slot count,
  - submitFlag 0,
  - idHash/status summary.
- Evidence must not include cookie/token/header/full request body.

Worker/planner rules:

- Existing protected duplicate draft behavior remains.
- Planner fingerprint must use profile-aware assets and mapper evidence.
- Worker must run mapper preflight before emitting `external_call`, setting `STATUS_UPLOADING`, auth, uploadDestination, object upload, or add.
- Mapping failure writes domain `failed` and typed reason, then completes locally like current policy failures; it must not call client.
- External Lingxing/auth/API/request failures continue to set sanitized result evidence and raise so task runtime marks failed/retryable.
- Success remains:
  - `STATUS_DRAFT_SAVED`
  - `amazon_draft_visibility="unconfirmed"`
  - no `draft_visible_at`,
  - no `submitted_at`,
  - no submit worker/planner/API.

## 10. Old Path Compatibility

Rules:

- Existing `standard_header_image_text_v1` remains supported exactly as M2/T3.5, including 5 `STANDARD_HEADER_IMAGE_TEXT` modules and 5 position images.
- Old plans missing `publish_profile` or `lingxing_content_module_type` still fail closed. Do not infer enhanced profile from role names or module count.
- Enhanced plan with missing/invalid enhanced module fields fails closed. Do not publish it through old `STANDARD_HEADER_IMAGE_TEXT`.
- Old generated A+ images without slot IDs are not valid enhanced assets. User must rerun enhanced plan/script/image generation.
- Product main workflow and `work_status` remain untouched.

## 11. Cross-Layer Semantic Contract

Fact source:

- `backend/app/aplus_publish/module_registry.py`

Producer endpoints:

- Step7 plan normalizer and fallback.
- Step8 script normalizer and regeneration.
- Step9 image slot manifest writer.
- Any future profile selector/config.

Consumers:

- Policy asset collector and content fingerprint.
- Mapper preflight and payload assembly.
- Client upload loop and save draft request.
- Worker/planner task lifecycle and evidence.
- Tests and project rules.
- Docs/domain indexes.
- Real Lingxing QA checklist.

Unknown/old value strategy:

- Missing profile: `unsupported_aplus_publish_profile`.
- Unknown profile: `unsupported_aplus_publish_profile`.
- Unknown module type/spec: `unsupported_aplus_module_type` or `aplus_module_spec_unregistered`.
- Missing slot/table/spec field: typed mapper failure before external call.
- Old no-profile plan: fail closed; no migration.
- Payload evidence missing: `lingxing_payload_structure_unverified`.

Reverse invariant:

- For every registry profile, Step7 must be able to produce exactly its module sequence.
- For every module type in a profile sequence, mapper must have a payload builder test.
- For every image slot in registry, Step8/Step9/policy/mapper must preserve and validate the same slot id.
- Adding a new registry module without Step7 producer, mapper builder, fixture, and project-rule closure must fail tests.

## 12. Tests and Project Rules

Modify:

- `scripts/test_lingxing_aplus_module_mapper.py`
- `scripts/test_lingxing_aplus_publish_policy.py`
- `scripts/test_lingxing_aplus_publish_tasks.py`
- `scripts/test_project_rules.py`

Mapper behavior tests:

- Enhanced valid fixture assembles exactly five content modules with types:
  - `STANDARD_IMAGE_TEXT_OVERLAY`
  - `STANDARD_THREE_IMAGE_TEXT`
  - `STANDARD_SINGLE_IMAGE_SPECS_DETAIL`
  - `STANDARD_COMPARISON_TABLE`
  - `STANDARD_TECH_SPECS`
- Verify payload subtrees, not string presence:
  - hero overlay dark and 970x300 crop,
  - feature grid block1..3 image/headline/body,
  - detail proof spec list positions,
  - comparison two product columns, ASINs, metric rows, 150x300 crop,
  - tech specs 4+ rows and no image object.
- Fail closed cases:
  - enhanced plan missing profile/type,
  - semantic role order mismatch,
  - image slot missing/extra/duplicate,
  - alt text missing or too long,
  - comparison second ASIN missing/invalid,
  - metric row label/value mismatch,
  - tech specs fewer than 4 rows,
  - payload builder/evidence missing.
- Keep M2 old profile success and fail-closed tests.

Policy/task tests:

- Enhanced asset collection expects 7 slots and correct dimensions.
- `technical_or_closing` requires no image.
- Mapper failure in planner/worker occurs before fake client call.
- Task success with fake client still writes only `draft_saved + unconfirmed`.
- Existing `draft_saved/idHash` remains protected.
- External auth/API/request failures stay runtime failed/retryable.
- Legacy no-profile plan remains local failure with typed mapper reason.

Project rules:

- Replace fragile “string exists” checks for enhanced profile with executable imports where possible:
  - import registry and verify `enhanced_basic_aplus_v1` profile sequence.
  - call Step7 contract helper/fallback to ensure producer output exactly matches registry.
  - inspect mapper exported builder registry or run a small fixture to prove every registry module has a payload builder.
  - prove client does not contain `STANDARD_HEADER_IMAGE_TEXT` fallback assembly for enhanced path.
- Keep a small negative source scan only for hard forbidden paths:
  - no `APLUS_EDIT_URL` in T3 client,
  - no `submitFlag": 1`,
  - no `draft_visible` write in T3 worker/client,
  - no `create_task` in new publish planner/worker.

Verification commands:

```bash
cd backend && .venv/bin/python ../scripts/test_lingxing_aplus_module_mapper.py
cd backend && .venv/bin/python ../scripts/test_lingxing_aplus_publish_policy.py
cd backend && .venv/bin/python ../scripts/test_lingxing_aplus_publish_tasks.py
make test-project-rules
make backend-compile
```

Real QA remains separate M3.3 and must use Lingxing test account/store with `submitFlag=0`.

## 13. Docs and Index Plan

Update during implementation:

- `docs/lingxing-aplus-upload.md`
  - Add enhanced profile payload and slot policy summary.
  - Preserve Premium/high级 A+ non-goal wording.
- `docs/domain-index/product-flow.md`
  - Update T3.5/M3 paragraph from single old profile to registry-backed old + enhanced profiles.
- `docs/domain-index/task-runtime.md`
  - Update verification entry and task-runtime behavior to mention enhanced profile remains draft-save only.
- `docs/domain-index/runtime-security.md`
  - Only if client/worker external-call boundary text changes; likely update summary to mention multi-slot uploads still draft-save only.
- `docs/project-index.md`
  - Only if new verification commands or core entry files are added; otherwise no change.
- This technical plan remains the M3.1 design artifact.

Do not edit `docs/collaboration/inbox.md` in implementation unless 若命 explicitly asks; 若命 owns inbox integration.

## 14. Phased Implementation Plan

### Phase 1: Registry Contract

**Goal:** Establish `enhanced_basic_aplus_v1` as the source of truth before producers or mapper use it.

**Files:**

- Modify: `backend/app/aplus_publish/module_registry.py`
- Modify: `scripts/test_lingxing_aplus_module_mapper.py`
- Modify: `scripts/test_project_rules.py`

- [ ] Add profile/module/image/text/table dataclasses and enhanced specs.
- [ ] Add enhanced failure codes.
- [ ] Keep old `standard_header_image_text_v1` API compatible.
- [ ] Add registry-level tests for profile sequence and required image slots.
- [ ] Run:

```bash
cd backend && .venv/bin/python ../scripts/test_lingxing_aplus_module_mapper.py
make test-project-rules
```

**Gate:** 若命 checks scope; 镜花 reviews registry abstraction before mapper implementation.

### Phase 2: Step7 Producer Schema

**Goal:** Make Step7 produce fixed business roles and backend-assigned module contract.

**Files:**

- Modify: `backend/app/pipeline/step7_aplus_plan.py`
- Modify: `scripts/test_project_rules.py`
- Add or modify focused Step7 behavior fixture if project pattern allows; otherwise project rule imports helper.

- [ ] Add profile contract helper that builds modules from registry bindings.
- [ ] Update prompt and fallback for enhanced roles.
- [ ] Ensure LLM output cannot override profile/type.
- [ ] Ensure old no-profile data is not migrated.
- [ ] Run:

```bash
make test-project-rules
make backend-compile
```

**Gate:** 若命 product semantics review for five roles; 镜花 design review if helper introduces new abstraction.

### Phase 3: Step8/Step9 Slot Assets

**Goal:** Generate script/image assets by registry image slots.

**Files:**

- Modify: `backend/app/pipeline/step8_aplus_script.py`
- Modify: `backend/app/pipeline/step9_aplus_image.py`
- Modify: `scripts/test_project_rules.py`
- Optional focused script fixture if existing scripts test this layer.

- [ ] Add enhanced module script schema with nested `image_slots`.
- [ ] Preserve profile/type/role/spec/slot fields through generation and regeneration.
- [ ] Update Step9 enhanced path to generate slot images using slot dimensions.
- [ ] Keep old flat 5-image path intact.
- [ ] Run:

```bash
make test-project-rules
make backend-compile
```

**Gate:** Review verifies no global 1940x1200 assumption remains on enhanced path.

### Phase 4: Policy and Mapper

**Goal:** Validate enhanced profile completely before any external Lingxing call and assemble all five payload subtrees.

**Files:**

- Modify: `backend/app/services/lingxing_aplus_publish_policy.py`
- Modify: `backend/app/services/lingxing_aplus_module_mapper.py`
- Modify: `scripts/test_lingxing_aplus_module_mapper.py`
- Modify: `scripts/test_lingxing_aplus_publish_policy.py`

- [ ] Make asset collection profile-aware and slot-aware.
- [ ] Build enhanced preflight normalized model.
- [ ] Add payload builders for all five enhanced modules.
- [ ] Add fail-closed tests for text, slot, comparison, specs, evidence, old plan.
- [ ] Run:

```bash
cd backend && .venv/bin/python ../scripts/test_lingxing_aplus_module_mapper.py
cd backend && .venv/bin/python ../scripts/test_lingxing_aplus_publish_policy.py
make backend-compile
```

**Gate:** 镜花 code review required; this is the highest-risk cross-layer contract phase.

### Phase 5: Planner / Worker / Client Lifecycle

**Goal:** Wire enhanced mapping into draft-save task without changing T3 lifecycle.

**Files:**

- Modify: `backend/app/task_planners/lingxing_aplus_publish.py`
- Modify: `backend/app/task_runtime/lingxing_aplus_publish_workers.py`
- Modify: `backend/app/services/lingxing_aplus_publish_client.py`
- Modify: `scripts/test_lingxing_aplus_publish_tasks.py`
- Modify: `scripts/test_project_rules.py`

- [ ] Use profile-aware fingerprint and slot upload map.
- [ ] Ensure worker preflight remains before `external_call` event and `STATUS_UPLOADING`.
- [ ] Ensure client uploads by slot and passes uploaded slot map to mapper.
- [ ] Ensure success/failure lifecycle remains draft-save only.
- [ ] Run:

```bash
cd backend && .venv/bin/python ../scripts/test_lingxing_aplus_publish_tasks.py
make test-project-rules
make backend-compile
```

**Gate:** 若命 confirms no product workflow/work_status change; 镜花 reviews lifecycle and external-call boundary.

### Phase 6: Docs and Index Closure

**Goal:** Make the implementation discoverable and prevent future regressions.

**Files:**

- Modify: `docs/lingxing-aplus-upload.md`
- Modify: `docs/domain-index/product-flow.md`
- Modify: `docs/domain-index/task-runtime.md`
- Modify: `docs/domain-index/runtime-security.md` if external boundary text changed.
- Modify: `docs/project-index.md` only if verification entries or core entry list changed.
- Modify: `scripts/test_project_rules.py`

- [ ] Update docs with enhanced profile, slots, fail-closed behavior, and non-goals.
- [ ] Add reverse closure project rules that import registry/helpers instead of only scanning strings.
- [ ] Run full local verification:

```bash
cd backend && .venv/bin/python ../scripts/test_lingxing_aplus_module_mapper.py
cd backend && .venv/bin/python ../scripts/test_lingxing_aplus_publish_policy.py
cd backend && .venv/bin/python ../scripts/test_lingxing_aplus_publish_tasks.py
make test-project-rules
make backend-compile
git diff --check
```

**Gate:** 若命 and 镜花 approve before M3.3 real Lingxing QA.

### Phase 7: M3.3 Real Lingxing QA Handoff

**Goal:** Prepare QA evidence path; implementation does not claim real draft field visibility without 观止.

**Files:**

- No code unless QA finds implementation defect.
- Expected QA doc path under `docs/collaboration/reviews/`.

- [ ] Use test account/store only.
- [ ] Save draft with `submitFlag=0`.
- [ ] Verify 5 modules, order, UI Chinese module names, images, text, comparison rows, and tech spec rows in Lingxing editor.
- [ ] Do not submit; do not claim Amazon Seller Central visibility.

**Gate:** 观止 QA PASS before 若命 commit/push decision.

## 15. Risks and Required Decisions

Comparison data risk:

- `STANDARD_COMPARISON_TABLE` requires at least two valid ASIN columns. If current product records do not reliably carry a comparison ASIN and image source, enhanced profile will fail closed for those products.
- Recommended implementation stance: fail closed with `aplus_comparison_column_asin_missing`; do not substitute generic text or fallback module.
- 若命 may later decide to add a separate comparison-data sourcing task, but it is not required to design the module payload.

Step9 cost and regeneration risk:

- Enhanced profile increases generated image slots from 5 large images to 7 smaller slot images.
- Slot-level regeneration must avoid accidental regeneration of the entire A+ unless the module requires multiple related slots.

Old UI/API display risk:

- Frontend pages may display `aplus_image_count=7` for enhanced profile. This is acceptable if labels are generic, but implementation should not claim “7 modules.” If UI wording assumes “5 images,” update wording or docs in the implementation phase.

Payload evidence limitation:

- M3.0 evidence is from public frontend bundle, not a live enhanced draft save. This is enough for implementation design because the actual QA gate is M3.3 real draft save. Mapper must keep `payload_evidence` references and fail closed if a spec lacks evidence.

## 16. Completion Definition

M3.1 is complete when this technical plan exists and covers:

- Registry profile/module/slot/text/table/failure/evidence design.
- Step7 fixed-role schema and backend-owned profile/type assignment.
- Step8/Step9 slot script/image schema and regeneration behavior.
- Mapper preflight and assembly design for all five modules.
- Image asset strategy without the old 5 x 970x600 assumption.
- Draft-save-only client/worker lifecycle.
- Old path compatibility and fail-closed strategy.
- Cross-layer semantic contract and reverse invariants.
- Test/project-rule strategy that avoids string-only checks.
- Docs/index plan.
- Phased implementation gates with file ranges and verification commands.

No implementation, commit, push, or inbox edit is part of M3.1.
