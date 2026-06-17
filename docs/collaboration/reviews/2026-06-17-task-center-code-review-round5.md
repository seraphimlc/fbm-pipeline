# Task Center Code Review Round 5

日期：2026-06-17
Reviewer：若命（agentKey: `ruoming`）
范围：听云 2026-06-17 00:14 返工后的任务中心、ProductTaskAction backfill、状态展示和前端 URL 初始化。

## 结论

不能 PASS，也不建议交最终 QA。听云这轮修掉了观止提出的部分问题：

- ProductTaskAction 增加了商品域 backfill，方向上解决“存量 product task 缺 dedupe/correlation/superseded key”的问题。
- `history` 默认视图条件从重型 terminal 子查询收敛为轻量终态 + superseded 条件，方向上解决历史页 19s 级延迟。
- 任务中心页面已支持从 URL 初始化 `view/display_status/task_type/q/correlation_key`。
- scan-limit / 内存分页路径仍未恢复，`step_key` 通用 superseded 兜底也没有恢复。

但当前实现仍存在一个 P0 状态/操作错误，以及两项 P1 风险。下面是代码级证据。

## 验证

- `make backend-compile`：PASS。
- `make test-project-rules`：PASS，28 项。
- `cd frontend && npm run build`：PASS，仅 Vite chunk size warning。
- `git diff --check -- backend/app/api/task_runs.py backend/app/product_tasks/actions.py backend/app/main.py frontend/src/pages/TaskRunCenter.tsx scripts/test_project_rules.py`：PASS。
- 本地 API `127.0.0.1:8190` 当前不可连接，未做现场 API 复验。

## P0 Findings

### 1. 失败任务如果仍有 pending 后续步骤，会被展示成“等待前置步骤”，并暴露错误操作

位置：

- `backend/app/api/task_runs.py:196-245`
- `backend/app/api/task_runs.py:411-475`
- `backend/app/task_runtime/scheduler.py:152-163`

问题：

`_run_display()` 的优先级是：

1. running
2. ready
3. pending
4. run.status failed / partial_failed / interrupted

这会导致多阶段任务只要某一步失败、后续步骤仍然是 pending，就不会显示为失败，而会显示为 `waiting_dependency`。

最小复现：

```bash
cd backend
.venv/bin/python - <<'PY'
from types import SimpleNamespace
from app.api.task_runs import _run_display
from app.task_runtime.constants import RUN_STATUS_FAILED, STEP_STATUS_FAILED, STEP_STATUS_PENDING

def step(id, order, status, err=None):
    return SimpleNamespace(
        id=id,
        sort_order=order,
        status=status,
        step_type='giga_pull_detail_chunk',
        error_message=err,
        heartbeat_at=None,
        locked_until=None,
        progress_total=1,
        progress_current=0,
    )

run = SimpleNamespace(
    id=10,
    status=RUN_STATUS_FAILED,
    task_type='giga_pull',
    summary_json=None,
    steps=[step(1, 1, STEP_STATUS_FAILED, 'boom'), step(2, 2, STEP_STATUS_PENDING)],
    groups=[],
    dedupe_key=None,
    correlation_key=None,
    cancel_requested_at=None,
    created_at=None,
)
display = _run_display(run, superseded_by_run_id=None)
print({k: display[k] for k in ('display_status', 'display_reason', 'available_actions', 'error_summary')})
PY
```

实际输出：

```text
{'display_status': 'waiting_dependency', 'display_reason': '等待前置步骤完成', 'available_actions': ['view_detail', 'cancel', 'refresh'], 'error_summary': 'boom'}
```

期望：

- 这种 run 必须显示为 `failed` 或 `interrupted`。
- 操作应为 `retry_failed_steps / copy_error / detail / refresh`，不应给 `cancel`。
- `display_status=failed` 筛选必须能查到它。

影响：

- GIGA 拉品、导出、A+、批量提交这类多 step/group 任务，一旦前序 step 失败且后续 step 保持 pending，用户会看到“等待前置步骤”，而不是“失败”。
- 任务中心的状态标签、筛选 total 和按钮矩阵会再次互相打架。
- 这是任务中心核心语义错误，不是 UI 文案问题。

修复要求：

- `_run_display()` 应先处理 terminal run.status（failed/partial_failed/interrupted/canceled/succeeded）和 superseded/cancel_requested，再处理 running/ready/pending，或至少在存在 failed/interrupted step 时优先失败态。
- `_display_status_sql_condition()` 必须同步同一优先级。`display_status=failed` 不能排除存在 pending step 的 failed run。
- 补行为测试，不要只用字符串规则。测试必须覆盖：`run.status=failed` + `failed step` + `pending step` 返回 `display_status=failed` 且有重试动作。

## P1 Findings

### 2. 创建接口直接 `_run_response(run)`，可能拿不到刚创建的 steps/groups 或触发 async lazy load

位置：

- `backend/app/api/task_runs.py:682-743`
- `backend/app/task_planners/giga_pull.py:108-112`
- `backend/app/task_planners/catalog_export.py:179-183`
- `backend/app/product_tasks/actions.py:648-650`

问题：

多个创建接口在 planner commit/refresh 后直接调用 `_run_response(run)`。`_run_display()` 依赖 `run.steps` 和 `run.groups`，但这些 run 通常没有通过 `selectinload` 重新加载关系。

风险：

- 如果 SQLAlchemy async lazy load 被触发，可能出现 `MissingGreenlet` 类错误。
- 如果关系没有加载，创建响应可能把刚创建且已有 ready step 的任务显示成 `planned` 或 progress=0。
- 列表接口后续会重新加载 steps，所以这个问题可能只出现在“创建任务返回值”路径，容易被现有列表测试漏掉。

修复要求：

- 创建接口返回前按 `_load_run()` 或专门的 lightweight loader 重新加载 run + groups + steps，再 `_run_response()`。
- 或 planner 返回已装配的关系，但需要明确测试证明。
- 补 API 样本/测试：创建一个 `auto_start=False/True` 的 task_run 后，创建响应中的 `display_status/current_step_label/available_actions/progress` 必须和随后 GET detail/list 一致。

### 3. backfill 只有字符串级规则，没有行为测试锁住“补 key、标 superseded、只改 task metadata”

位置：

- `backend/app/product_tasks/actions.py:507-555`
- `backend/app/main.py:51-54`
- `scripts/test_project_rules.py:992-998`

问题：

`backfill_product_action_task_run_keys()` 作为启动期写库逻辑，方向正确，但现在测试只检查字符串存在：

- 是否有函数名。
- 是否写了说明。
- 是否在 `main.py` 调用。
- 是否出现 `superseded_by_run_id = ordered[index + 1].id`。

这不能证明真实行为：

- 能否从 legacy run 正确推导 product_id。
- 是否把同一 product/action 的旧 failed/interrupted run 标成 superseded。
- 是否不会误改 succeeded/current run。
- 是否不会触碰 Product/CatalogProduct/ASIN/模板/素材等业务数据。
- 再次启动是否幂等。

修复要求：

- 补最小行为测试，至少用内存对象或测试 DB 验证：
  - 两个同 product/action 的 failed -> later run，旧 run 被写 `superseded_by_run_id`。
  - succeeded run 不被 superseded。
  - 已有 `superseded_by_run_id` 不被覆盖。
  - 无 product_id 的 run 不被猜测、不被误改。
  - 除 `task_runs.dedupe_key/correlation_key/superseded_by_run_id/superseded_at` 外，不写商品域表。
- 如果 legacy product_id 实际存在于 step payload 而不是 run payload，需要在 Product Domain backfill 中明确处理；不要把兼容解析塞回 task center API。

## 已收敛项

- `frontend/src/pages/TaskRunCenter.tsx:134-214` 已支持 URL 初始化 `view/display_status/task_type/q/correlation_key`，观止提出的 URL 参数问题代码层已收敛。
- `backend/app/api/task_runs.py:430-434` 已把 history 默认条件收敛为 superseded + succeeded/canceled，性能方向正确；仍需观止现场复测实际耗时。
- `backend/app/product_tasks/actions.py:507-555` 把存量 product task key backfill 放在商品域，不在 task center API 里写商品正则，边界方向正确。

## 下一步

需要听云继续修 P0，并补 P1 的行为测试。修完后再让观止按页面/API/DB 现场复验：

- 默认当前页不应再把已 superseded 的历史 product task 当当前失败任务。
- 多阶段失败任务必须显示失败并可重试。
- history 接口耗时需要重新测。
- 创建任务响应和列表/详情响应状态一致。
