# Lingxing A+ Publish T3 Code Review

结论：`CODE_REVIEW_REREVIEW / PASS_WITH_SCOPE`

## Scope

- 审查对象：T3 Lingxing A+ Draft Save Task。
- 审查范围：draft save task runtime、policy/client、API/labels/config、行为脚本、project rules、domain indexes。
- 不审：真实领星页面 QA、Amazon draft visibility、submit approval、T4/T6、商品主 workflow / `work_status`。

## Initial Review

结论：`CODE_REVIEW / NEEDS_FIX`

### P1 - 外部保存失败被标记成 task 成功

`backend/app/task_runtime/lingxing_aplus_publish_workers.py` 捕获 `LingxingAplusDraftSaveClientError` 后写 `auth_required/failed`，但正常 `return`。scheduler 对正常返回会把 step/run 置为 succeeded，导致 `auth_required`、`request_failed`、`api_failed` 等外部失败不能走 failed-step retry，任务中心审计也会误报成功。

完整修复边界：

- 保留 typed domain status 和 sanitized evidence。
- 外部保存失败必须抛回 task runtime，使 `TaskStep` / `TaskRun` failed/retryable。
- policy stop，例如 `waiting_listing`、`skipped`、已有 `draft_saved/idHash`，不得被误改成 runtime failed。
- 行为脚本必须覆盖 external failure 的 runtime failed/retry，以及 retry 后不重复创建草稿。

## Rereview

结论：`CODE_REVIEW_REREVIEW / PASS_WITH_SCOPE`

- P1 已闭合：`LingxingAplusDraftSaveClientError` 分支现在先写 typed domain status、sanitized event/progress/result_json，然后 `commit` 并重新 `raise`，交由 scheduler 标记 `TaskStep` / `TaskRun` failed。
- domain status 保留：`auth_required` 写 `auth_required`；`api_failed/request_failed` 等外部保存失败写 `failed`。
- policy stop 未扩大：`waiting_listing`、`skipped`、已有 `draft_saved/idHash` protected stop 仍结构化完成，不变成 runtime failed。
- 行为脚本已覆盖 `auth_required`、`api_failed`、`request_failed` 的 run/step failed、typed result/evidence、同一 run/step retry 成功，以及 retry 后只生成一个 draft item/idHash。
- project rules 已加反向规则，禁止外部失败 catch 分支正常 return 成 succeeded，并要求行为脚本保留 runtime failed/retry 断言。
- 范围未越界：未写 `draft_visible` / `submitted` / 对应时间戳，未实现 visibility/submit，未开启 `AUTO_LINGXING_APLUS_AFTER_DONE`，未并入商品主 workflow / `work_status`。

## Verification

- `cd backend && .venv/bin/python -m compileall -q app`：PASS。
- `cd backend && .venv/bin/python ../scripts/test_lingxing_aplus_publish_policy.py`：PASS。
- `cd backend && .venv/bin/python ../scripts/test_lingxing_aplus_publish_tasks.py`：PASS。预期 traceback 来自 scheduler 捕获外部失败样本，进程 exit 0。
- `make test-project-rules`：PASS，65 tests。
- `git diff --check`：PASS。

## Gate Meaning

- 允许若命 scoped commit/push T3。
- 允许进入观止真实 Lingxing save QA。
- 本 PASS 只代表 T3 Draft Save Task code/task-runtime/security review 通过；不代表真实 Lingxing QA 通过，不代表 `draft_visible`，不代表 submit approval。
