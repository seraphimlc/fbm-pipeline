# MSG-20260622-072 - Amazon Main Chain After Search Pass QA

结论：`QA / NEEDS_FIX`

观止按 `MSG-20260622-072` 执行商品主链路后续 QA。使用现有安全样本 product `92 / W808P389332`，从 `visual_match_competitors/pending` 触发正式视觉初筛 API。未改业务代码，未提交，未 push，未触发 Amazon 导出、Seller Central、A+、TikTok、真实上传发布或模板输出。

## Scope

- 样本：product `92 / W808P389332`
- 起点：`visual_match_competitors/pending`
- 目标：验证能否推进到 `flow_done/succeeded` / 商品列表 `export_ready`
- 入口：`POST /api/products/92/competitor-visual-match/retry`
- 服务：本地后端 `127.0.0.1:8190`
- 启动参数：`STARTUP_RUN_DB_MAINTENANCE=false STARTUP_RUN_BACKFILLS=false STARTUP_RECOVER_TASKS=false STARTUP_KICK_TASK_RUNTIME=false`

## Test Matrix

| Case | Goal | Operation | Expected | Actual | Result |
| --- | --- | --- | --- | --- | --- |
| TC-072-001 | Confirm safe sample and current node | `GET /api/products/92` | no real ASIN/export/A+ upload; workflow at visual pending | `amazon_asin=null`, `catalog_exported_at=null`, `aplus_upload_status=not_uploaded`, workflow `visual_match_competitors/pending` | PASS |
| TC-072-002 | Trigger next safe node through official API | `POST /api/products/92/competitor-visual-match/retry` | task run created and product enters processing | API returned 200; product entered `visual_match_competitors/processing`; task run `772`, step `778` created | PASS |
| TC-072-003 | Runtime should land success or typed failure | poll task/product detail | visual success should advance, external VLM failure should become failed and retryable without runtime crash | VLM failed with TLS certificate `APIConnectionError`, then failure projection crashed with `MissingGreenlet`; run stayed stale `running` and product stayed `processing` until manual mark-interrupted | FAIL |
| TC-072-004 | Product/list/detail/task center consistency | `GET /api/task-runs/772`, `GET /api/products/92`, product list filters | consistent traceable failed/retryable or succeeded/export_ready | after manual `mark-interrupted`, product detail became `visual_match_competitors/failed`, run/step became `interrupted`, but task group DB status remained `running`; product was not in `export_ready` | FAIL |
| TC-072-005 | Downstream chain availability by code facts | inspect current API/action paths | if visual succeeds, current implementation can continue to capture/detail/auto-select/image/listing | visual success only projects to `capture_competitor_candidates/pending`; no public product API/client action for candidate capture or auto competitor selection; default detail adapter is unconfigured | FAIL |

## Evidence

### Runtime Evidence

- `POST /api/products/92/competitor-visual-match/retry` returned 200:
  - product status: `competitor_visual_matching`
  - workflow: `visual_match_competitors/processing`
  - allowed actions: `open_detail`, `open_task_center`
  - related correlation key: `product:92:competitor_visual_match`
- Task center created:
  - run `772`: `product_competitor_visual_match`
  - step `778`: `product:92:competitor_visual_match`
  - progress event `679`: `开始竞品视觉初筛`
- Backend log showed the real failure chain:
  - first failure: VLM/OpenAI request failed with TLS certificate verification, surfaced as `openai.APIConnectionError`
  - action wrapped it as `CompetitorVisualMatchError: VLM direct URL 调用失败: APIConnectionError: Connection error.`
  - failure hook then crashed with `sqlalchemy.exc.MissingGreenlet` while reading `step.payload_json`
  - scheduler logged `[TaskRuntime] runner task crashed`
- Before manual recovery, task detail showed:
  - run `772`: `status=running`, detail `display_status=stale_running`
  - step `778`: `status=running`, `locked_until=2026-06-22T19:40:16`, `display_status=stale_running`
  - product `92`: workflow still `visual_match_competitors/processing`

### Recovery Evidence

I used the task-center recovery API after capturing the stale-running evidence:

```text
POST /api/task-runs/772/mark-interrupted
reason="QA observed runner crash after VLM APIConnectionError and MissingGreenlet during failure projection"
```

After recovery:

- product detail:
  - `status=failed`
  - `workflow_node=visual_match_competitors`
  - `workflow_status=failed`
  - primary action `retry_competitor_visual_match`
  - `amazon_asin=null`
  - `catalog_exported_at=null`
  - `aplus_upload_status=not_uploaded`
- task DB/API:
  - run `772`: `interrupted`
  - step `778`: `interrupted`
  - step lock cleared
  - task group DB status still `running`
- candidates DB:
  - `amazon_competitor_search_candidates` for product `92`: total `20`
  - `visual_task_run_id=772`: `0`
  - `visual_selected_for_capture=1`: `0`
  - `capture_status=succeeded`: `0`
  - `final_selected=1`: `0`
- product list:
  - `work_status=export_ready`: product `92` absent
  - `work_status=select_competitor`: product `92` present with workflow `visual_match_competitors/failed`

## White-Box Findings

1. `NEEDS_FIX / P1`: visual-match failure path can crash the task runtime and leave product/task in stale processing.
   - Code path: `backend/app/task_runtime/scheduler.py:251-305` calls the worker and should mark step failed on exceptions.
   - Actual runtime: the worker raised a VLM `APIConnectionError`, then `ProductCompetitorVisualMatchAction.on_step_failure()` hit `MissingGreenlet` during failure projection. The run stayed `running/stale_running` until manual `mark-interrupted`.
   - User impact: a normal external VLM/TLS failure is not reliably converted into a clear failed workflow state. The product can look indefinitely in progress and cannot proceed to export-ready.

2. `NEEDS_FIX / P1`: current implementation does not provide a complete user/API path from visual success to export-ready.
   - Visual success only sets `capture_competitor_candidates/pending` in `backend/app/product_tasks/actions.py:1449-1498`.
   - Candidate capture and auto competitor selection actions exist (`backend/app/product_tasks/actions.py:1775-1812`, `1947-2035`, `2074-2115`), but current public product API/client only exposes visual retry at `backend/app/api/products.py:5090-5128` and `frontend/src/api/index.ts:1473-1480`.
   - The Amazon detail adapter remains fail-closed by default: `backend/app/services/amazon_listing_detail.py:40-45`, `60-61`.
   - User impact: even if visual match succeeds, the main chain is expected to stop at candidate detail pending unless an internal planner or future API is added/enabled.

3. `NEEDS_FIX / P2`: task recovery leaves group/run consistency imperfect.
   - After `mark-interrupted`, run `772` and step `778` became `interrupted`, but DB group status remained `running`.
   - User impact: task detail/list can be harder to reason about during recovery, though product workflow did become retryable.

## Side Effects

Allowed writes performed:

- Created task run `772`, group `781`, step `778`, and task events for product `92`.
- Temporarily moved product `92` to `visual_match_competitors/processing`.
- Used official task-center recovery API to mark run `772` interrupted and return product `92` to `visual_match_competitors/failed`.

Forbidden writes avoided:

- No manual DB success write.
- No mock/fake external success.
- No old evidence replay.
- No Amazon export/template generation.
- No Seller Central, A+, TikTok, upload, publish, real ASIN overwrite, or export history overwrite.
- No business code edit, commit, or push.

## Conclusion

`QA / NEEDS_FIX`.

The current product main chain did not advance product `92 / W808P389332` from `visual_match_competitors/pending` to `flow_done/succeeded` or product list `export_ready`. The immediate blocker is a code/runtime failure path: external VLM TLS failure is not safely projected to a typed failed task/product state and instead crashes the runner with `MissingGreenlet`. A second implementation gap remains visible by code inspection: after visual success, current public product API/client still cannot safely continue candidate detail capture and auto competitor selection to image analysis/listing/export-ready.

Recommended next steps:

1. Fix visual-match failure projection so any VLM/API/TLS/model failure becomes a traceable failed task and `visual_match_competitors/failed`, without runner crash or stale processing.
2. Reconcile task run/group/step status on `mark-interrupted`.
3. Decide and implement the sanctioned continuation path for candidate detail capture and auto competitor selection before rerunning this QA gate.
