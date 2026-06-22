# CODE_REVIEW_REREVIEW / PASS_WITH_SCOPE

日期：2026-06-22 CST
角色：镜花（agentKey: `jinghua`）
范围：仅复审 `MSG-20260622-064` 的 P1：`ChromeAmazonSearchPageAdapter.search()` 在 `parse_amazon_search_results_html()` 抛 `AmazonSearchPageError("empty_results", ...)` 时是否写入可追溯 evidence 并 re-raise，以及专项测试是否能防回归。

## 结论

PASS_WITH_SCOPE。P1 已修复，允许进入观止 S4 QA。

本结论只代表 focused code rereview 通过；不代表真实 Amazon 页面 QA、真实候选落库成功、外部平台验收、commit/push 或整体 S2/S3 全量复审。

## 证据

- `backend/app/services/amazon_search_page.py:169-178` 在读取 DOM 后先把 `page_url`、`page_title`、`classification`、`dom_summary.html_length/body_text_sample/result_count_hint` 放入 evidence。
- `backend/app/services/amazon_search_page.py:184-194` 对 `parse_amazon_search_results_html(...)` 的 `AmazonSearchPageError` 单独捕获，补写 `finished_at`、`candidate_count=0`、`error_type=exc.error_type`、`error_message=str(exc)`，调用 `_write_evidence(evidence)` 后原样 `raise`。因此 `empty_results` 不会被吞成成功候选，也不会返回空成功列表。
- `backend/app/services/amazon_search_page.py:130-146` evidence 初始化包含 `task_run_id`、`task_step_id`、`query_index`、`product_id`、`item_code`、query、marketplace、url、started_at 和 config。
- `backend/app/services/amazon_search_page.py:234-249` `_write_evidence()` 只写 evidence 文件并更新 adapter 的 `last_search_evidence` 摘要；未写商品 workflow。
- `backend/app/services/amazon_search_page.py:490-495` evidence path 归属为 `AMAZON_SEARCH_EVIDENCE_DIR/run-{task_run_id}/step-{task_step_id}/query-{query_index}.json`。生产入口 `run_amazon_search_queries()` 从 `enumerate(..., start=1)` 传入 query index，见 `backend/app/services/amazon_search_page.py:274-284`。
- `scripts/test_amazon_search_page_real_adapter_boundaries.py:100-127` 模拟 Chrome navigate 成功、DOM 返回搜索结果结构 `<div data-component-type="s-search-result"></div>` 但没有可解析 ASIN，并断言抛出 `empty_results`。
- `scripts/test_amazon_search_page_real_adapter_boundaries.py:129-142` 断言 evidence 文件存在于 `run-9301/step-9402/query-3.json`，且内容包含 `task_run_id`、`task_step_id`、`query_index`、`error_type=empty_results`、`candidate_count=0`、page URL、page title、`classification is None`、`dom_summary.result_count_hint == 1`、`finished_at` 和 `error_message`。

## 命令结果

- `cd backend && .venv/bin/python ../scripts/test_amazon_search_page_real_adapter_boundaries.py`：PASS
- `python -m compileall backend/app`：PASS
- `git diff --check -- backend/app/services/amazon_search_page.py scripts/test_amazon_search_page_real_adapter_boundaries.py`：PASS

## 残余风险

- 本次没有执行真实 Amazon 页面 QA，也没有证明真实搜索候选可落库；这属于观止 S4 QA 范围，不阻断本次 P1 复审。
- 本次没有扩大复审到 `product_tasks/actions.py`、`task_runtime/scheduler.py` 或真实浏览器授权路径；只判断 `empty_results` evidence 修复是否闭合。
- `_evidence_path()` 对缺失的 run/step/query 会落到 `unknown`，但当前生产入口为任务上下文传入正整数 run/step 和从 1 开始的 query index；缺失上下文路径不属于本次 P1 返工阻断。

## Gate

允许进入观止 S4 QA：是。
