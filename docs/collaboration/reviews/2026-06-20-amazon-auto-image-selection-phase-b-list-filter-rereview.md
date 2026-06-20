# Amazon Auto Image Selection Phase B List Filter Rereview

日期：2026-06-20 CST

审查人：镜花（agentKey: `jinghua`）

关联消息：

- `MSG-20260620-004`
- `MSG-20260620-005`

结论：`CODE_REVIEW / PASS`

## Scope

本次只复核 `MSG-20260620-004` 中镜花打回的 P1：`GET /api/products?work_status=auto_select_images` 是否从全量加载后 Python 内存过滤/分页，改为 DB 级筛选和 DB count。

本次不做页面 QA、真实商品创建、真实 task run、真实 VLM、StyleSnap、Chrome 或外部平台验证；不复审 `docs/collaboration/roles/jinghua.md`；不审查 `tmp/`。

## Gate Standard

- `auto_select_images/pending` 必须属于商品列表 `auto_select_images` 筛选桶。
- `auto_select_images/processing` 必须继续归入 `running`。
- `auto_select_images/failed` 必须继续归入 `failed`。
- `work_status=auto_select_images` 必须在 SQL 层追加 `products.workflow_node/products.workflow_status` 谓词，并且 count 查询使用同一口径。
- 该状态不得落入旧的 `result.scalars().unique().all()` 后 Python list-comprehension 过滤和切片分页分支。

## Passed Checks

1. DB 级筛选已落在列表和 count 两条查询上。

   - 证据：`backend/app/api/products.py:688` 的 `_apply_product_work_status_db_filter()` 仅处理 `work_status == "auto_select_images"`。
   - 证据：`backend/app/api/products.py:691-695` 同时返回 `query.where(predicate)` 和 `count_query.where(predicate)`，谓词为 `Product.workflow_node == WORKFLOW_NODE_AUTO_SELECT_IMAGES` 且 `Product.workflow_status == WORKFLOW_STATUS_PENDING`。

2. 旧内存分页分支对 `auto_select_images` 已跳过。

   - 证据：`backend/app/api/products.py:2788` 在旧分支前调用 `_apply_product_work_status_db_filter(query, count_query, work_status)`。
   - 证据：`backend/app/api/products.py:2790` 旧分支条件改为 `if work_status and not db_filtered_work_status:`；因此 helper 命中后走 `count_query` + `offset/limit` DB 分页路径。

3. 状态语义与 Phase B 设计一致。

   - 证据：`scripts/test_project_rules.py:3210` 的 `test_auto_image_selection_phase_b_work_status_behaviour()` 构造 `auto_select_images/pending` 商品，断言 `_product_workbench_status()` 和 `_product_list_work_status()` 均返回 `auto_select_images`。
   - 证据：同一测试把状态改为 `processing` 后断言列表/工作台状态均为 `running`。
   - 证据：Phase B PRD `docs/superpowers/specs/2026-06-19-amazon-auto-image-selection-prd.md:355-356` 已明确 `pending` 是正式筛选桶，`processing` 归入 `running`，列表筛选使用 DB 级 workflow 谓词和 count。

4. 防回归测试不是只看字符串。

   - 证据：`scripts/test_project_rules.py:3245-3258` 直接调用 `_apply_product_work_status_db_filter(select(Product), select(func.count(Product.id)), "auto_select_images")`，编译 query 和 count SQL，并断言二者都包含 `workflow_node=auto_select_images` 与 `workflow_status=pending`。
   - 证据：`scripts/test_project_rules.py:3257-3258` 断言其它旧状态如 `select_images` 不被该 helper 硬处理，符合本轮最小修复边界。

## Non-blocking Risks

- 其它旧 `work_status` 筛选仍保留全量加载后 Python 内存过滤/分页路径，位置仍在 `backend/app/api/products.py:2790-2799`。本次不阻断，原因是 `MSG-20260620-005` 明确只要求修 Phase B 新公开的 `auto_select_images` 桶，且听云没有夹带更大查询治理。建议若命后续单独开商品列表 work_status 查询治理任务。
- `GET /api/products/overview` 仍按当前旧实现加载商品后在 Python 侧统计工作台状态。本次不阻断，原因是本轮 P1 指向列表筛选分页红线，不是 overview 性能治理；但随着 workflow 状态桶继续增加，overview 也应进入后续结构治理观察清单。

## Verification

已执行并通过：

```bash
python -m compileall backend/app
make test-project-rules
cd frontend && npm run build
git diff --check
```

结果：

- `make test-project-rules`：`OK: 50 project rule test(s)`。
- `npm run build`：通过；仍有既有 Vite chunk-size warning。
- `git diff --check`：无输出，通过。

## Gate Meaning

镜花 code review PASS 只表示 `MSG-20260620-004/005` 指定的 Phase B 工程交付包和本次 P1 返工，在代码/数据查询/测试/文档一致性 gate 下通过。

这不等于页面 QA PASS、真实商品路径验收、真实任务执行验收、真实 VLM 质量验收、StyleSnap/Chrome 验收、外部平台验收或用户最终验收。
