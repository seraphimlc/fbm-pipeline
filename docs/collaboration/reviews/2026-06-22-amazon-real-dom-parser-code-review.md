# CODE_REVIEW / NEEDS_FIX

Date: 2026-06-22 CST
Reviewer: 镜花（agentKey: `jinghua`）
Scope: focused review for `MSG-20260622-069 - AMAZON_SEARCH_REAL_DOM_EMPTY_RESULTS_PARSER`

## Scope

Reviewed only:

- `backend/app/services/amazon_search_page.py`
- `scripts/test_amazon_search_page_real_adapter_boundaries.py`
- `scripts/test_project_rules.py` targeted entry/fixture changes

Out of scope:

- Real Chrome S4 QA rerun
- Candidate DB landing behavior beyond parser contract
- Runtime auto-start changes except where referenced by project rules
- Commit, push, or inbox edits

## Blocking Findings

### P1: Result block slicing can still capture unrelated links after a result shell

`_result_blocks()` now starts only at `<div ... data-component-type="s-search-result" ...>` opening tags, which is the correct entry guard. However it ends each block at the next result opening tag or end of document, not at the actual closing boundary of the result element.

Impact: if a result shell has empty/invalid `data-asin` and a navigation/promo `/dp/{ASIN}` link appears after that result before the next result opening tag, `_extract_product_url()` can treat the unrelated link as same-block fallback and create a false candidate.

Evidence:

- `backend/app/services/amazon_search_page.py:407`-`418` slices by next result opening tag.
- `backend/app/services/amazon_search_page.py:327`-`334` allows `/dp` fallback inside that sliced block when `data-asin` is invalid.
- `backend/app/services/amazon_search_page.py:456`-`468` accepts the first product link found in the sliced text.
- Reproducer run during review:

```text
post_result_nav_fallback [('B0NAVIG001', 'https://www.amazon.com/dp/B0NAVIG001', 'Shell')]
```

This violates the requested safety condition that fallback ASIN extraction not come from navigation or full-page unrelated links. The existing test only puts the navigation fake ASIN before the result block, so it does not catch this post-result slicing case.

### P1: Candidate ASIN and URL can become inconsistent

When the result opening tag has a valid `data-asin`, `_extract_product_url()` first searches for a matching product link, but if none is found it returns the first fallback `/dp` or `/gp/product` URL even when that URL contains a different ASIN. The candidate is then emitted with the opening-tag ASIN and the mismatched URL.

Evidence:

- `backend/app/services/amazon_search_page.py:330`-`354` keeps the valid opening-tag ASIN but uses the URL returned by `_extract_product_url()`.
- `backend/app/services/amazon_search_page.py:463`-`468` stores and returns a fallback URL even when `href_asin != data-asin`.
- Reproducer run during review:

```text
mismatch_valid_data_asin [('B0RIGHT001', 'https://www.amazon.com/dp/B0WRONG001', 'Right')]
```

This is specifically within the P0/P1 review checklist: candidate URL/ASIN inconsistency. It can poison candidate records even though ASIN parsing itself appears successful.

## Passed Checks

- `_result_blocks()` no longer requires `data-asin` in the same opening tag or a fixed attribute order; it still starts only from `s-search-result` result openings.
- ASIN priority is correct in the normal case: valid opening-tag `data-asin` wins, with `/dp/{ASIN}` and `/gp/product/{ASIN}` as fallback.
- `script` and `style` content is stripped before candidate extraction and evidence snippets.
- `title`, `image_url`, `price`, `rating`, and `review_count` are best-effort fields; missing values do not block candidate creation when ASIN is available.
- Typed failure semantics are still present for `captcha`, `bot_check`, `rate_limited`, `login_required`, `region_page`, `unsupported_page_structure`, and `empty_results`.
- `empty_results` evidence now includes `html_length`, a capped `body_text_sample`, `result_count_hint`, `data_asin_hint`, `dp_link_hint`, and up to three capped result snippets. It does not save the full 2.9MB HTML page.
- Tests cover attribute order, single/double quotes and spaces, `/dp` fallback, script/navigation fake ASIN before a result block, region page, unsupported page structure, and empty-results evidence.

## Command Results

```text
python -m compileall backend/app
PASS

make test-project-rules
PASS, 62 project rule test(s)

cd backend && .venv/bin/python ../scripts/test_amazon_search_page_real_adapter_boundaries.py
PASS

git diff --check -- backend/app/services/amazon_search_page.py scripts/test_amazon_search_page_real_adapter_boundaries.py scripts/test_project_rules.py
PASS
```

Additional review repro command:

```text
cd backend && .venv/bin/python - <<'PY'
from app.services.amazon_search_page import parse_amazon_search_results_html, AmazonSearchPageError

cases = {
  'mismatch_valid_data_asin': '''<html><body><div data-component-type="s-search-result" data-asin="B0RIGHT001"><h2><span>Right</span></h2><a href="/dp/B0WRONG001">Wrong</a></div></body></html>''',
  'post_result_nav_fallback': '''<html><body><div data-component-type="s-search-result" data-asin=""><h2><span>Shell</span></h2></div><nav><a href="/dp/B0NAVIG001">Nav</a></nav></body></html>''',
}
for name, html in cases.items():
    try:
        c = parse_amazon_search_results_html(html, query='x')
        print(name, [(x.asin, x.url, x.title) for x in c])
    except AmazonSearchPageError as exc:
        print(name, exc.error_type)
PY
```

Observed:

```text
mismatch_valid_data_asin [('B0RIGHT001', 'https://www.amazon.com/dp/B0WRONG001', 'Right')]
post_result_nav_fallback [('B0NAVIG001', 'https://www.amazon.com/dp/B0NAVIG001', 'Shell')]
```

## Residual Risks

- This review did not inspect the real Amazon evidence HTML directly beyond the summarized task context.
- The parser remains regex-based rather than DOM-parser-based; after the P1 issues are fixed, a focused rerun should include post-result navigation and mismatched URL/ASIN regression tests.
- Passing local tests does not prove real Amazon candidates will land; only the next真实 Chrome S4 rerun can prove that.

## Gate

Do not send to 观止 for real Chrome S4 yet.

观止 S4 rerun is not allowed until the parser prevents:

- fallback ASIN capture from links outside the actual result item boundary, and
- emitted candidates whose `asin` and product URL ASIN disagree.

---

### CODE_REVIEW_REREVIEW / PASS_WITH_SCOPE - 镜花（agentKey: `jinghua`）- 2026-06-22 19:02 CST

结论：

- `MSG-20260622-070 - AMAZON_SEARCH_REAL_DOM_PARSER_SAFETY_FIX` 闭合上次打回的两个 P1。未在本次 focused 范围内发现新的 P0/P1。
- 允许观止重跑真实 Chrome S4。

Review Scoping：

- 节点：focused code rereview。
- 范围：只复审 `MSG-20260622-070` 对上次两个 P1 的闭合情况。
- 已读/核对文件：`backend/app/services/amazon_search_page.py`、`scripts/test_amazon_search_page_real_adapter_boundaries.py`、`scripts/test_project_rules.py` 中专项测试入口/fixture 变更。
- 不审：真实 Chrome S4、候选落库、task runtime auto-start、提交/push、其它协作规则改动。
- 通过标准：fallback ASIN 只能来自实际 result item 内；合法 `data-asin` 与 URL ASIN 不一致时不得输出错配 URL；原 typed failure/evidence 安全语义不被破坏；专项测试不是 mock/fixture 冒充真实成功。

Passed Checks：

- P1-1 已闭合：`_result_blocks()` 现在从 `s-search-result` opening `<div>` 开始，并用 `_balanced_div_end()` 找当前 result `<div>` 的 closing boundary；找不到可靠 closing 时，`_fallback_result_fragment_end()` 会在 `nav/header/footer/main/aside` 或 30000 字符上限截断。证据：`backend/app/services/amazon_search_page.py:407`-`440`。
- 上次 repro `post_result_nav_fallback` 输出已从候选变为 `empty_results`：

```text
post_result_nav_fallback empty_results
```

- P1-2 已闭合：`_extract_product_url()` 在 `data-asin` 合法时只接受 URL 中 ASIN 与 expected ASIN 相同的 `/dp` 或 `/gp/product` 链接；错配 URL 被跳过并返回 `None`。证据：`backend/app/services/amazon_search_page.py:478`-`493`。
- 上次 repro `mismatch_valid_data_asin` 输出已从错配 URL 变为 URL `None`：

```text
mismatch_valid_data_asin [('B0RIGHT001', None, 'Right')]
```

- result 内 `/dp/{ASIN}` fallback 仍可用。证据：`scripts/test_amazon_search_page_real_adapter_boundaries.py:207`-`221` 覆盖空 `data-asin` result 内 `/dp/B0FALLBK01` 可解析为候选。
- script/style/nav 假 ASIN 不生成候选。证据：候选解析先用 `_strip_script_like_blocks()` 清理 block，`scripts/test_amazon_search_page_real_adapter_boundaries.py:224`-`241` 和 `:244`-`:274` 覆盖 nav/script/post-result nav/畸形 result shell。
- `captcha` / `bot_check` / `rate_limited` / `login_required` / `region_page` / `unsupported_page_structure` / `empty_results` 语义未被本轮破坏。证据：分类逻辑仍在 `backend/app/services/amazon_search_page.py:372`-`388`，专项脚本覆盖 true region、unsupported、empty evidence，`make test-project-rules` 也检查 typed failure 字符串和专项脚本入口。
- `empty_results` evidence snippets 仍安全截断，不保存整页 HTML。证据：`_amazon_dom_summary()` 只写 `html_length`、`body_text_sample[:1200]`、计数 hint 和前三个 `_safe_dom_snippet()`；`_safe_dom_snippet()` 先剥离 script/style 并限制 900 字符。位置：`backend/app/services/amazon_search_page.py:443`-`471`。
- 本次没有发现误抓假 ASIN、输出 ASIN/URL 错配、block 截断过窄导致现有 result fallback 失效、或 fixture/mock 冒充真实成功的 P0/P1。注意：真实 Amazon DOM 是否仍有未覆盖结构，必须由观止 S4 继续验证。

Command Results：

```text
python -m compileall backend/app
PASS

make test-project-rules
PASS, 62 project rule test(s)

cd backend && .venv/bin/python ../scripts/test_amazon_search_page_real_adapter_boundaries.py
PASS

git diff --check -- backend/app/services/amazon_search_page.py scripts/test_amazon_search_page_real_adapter_boundaries.py scripts/test_project_rules.py
PASS
```

Additional repro command:

```text
cd backend && .venv/bin/python - <<'PY'
from app.services.amazon_search_page import parse_amazon_search_results_html, AmazonSearchPageError

cases = {
  'mismatch_valid_data_asin': '''<html><body><div data-component-type="s-search-result" data-asin="B0RIGHT001"><h2><span>Right</span></h2><a href="/dp/B0WRONG001">Wrong</a></div></body></html>''',
  'post_result_nav_fallback': '''<html><body><div data-component-type="s-search-result" data-asin=""><h2><span>Shell</span></h2></div><nav><a href="/dp/B0NAVIG001">Nav</a></nav></body></html>''',
}
for name, html in cases.items():
    try:
        c = parse_amazon_search_results_html(html, query='x')
        print(name, [(x.asin, x.url, x.title) for x in c])
    except AmazonSearchPageError as exc:
        print(name, exc.error_type)
PY
```

Observed:

```text
mismatch_valid_data_asin [('B0RIGHT001', None, 'Right')]
post_result_nav_fallback empty_results
```

Residual Risks：

- 本结论只证明 scoped parser safety fix 闭合，不证明真实 Amazon candidates 已落库。
- Parser 仍是 regex/balanced-fragment 方案，不是完整 DOM parser；若真实 Amazon result HTML 出现非 `<div>` result root、严重畸形嵌套或商品链接不在当前 result fragment 内，仍可能 `empty_results`。这属于下一次真实 S4 的观测风险，不阻断本次两个 P1 闭合。
- `main` / `aside` 作为畸形 HTML fallback 截断 marker 是保守 fail-closed 策略；极端真实 result 内若嵌入这些标签，可能导致少抓而非误抓。当前任务优先级是防假候选，风险可接受。

Gate Meaning：

- 本结论代表：`MSG-070` 两个 P1 在代码和专项测试证据上已闭合，可以交观止重跑真实 Chrome S4。
- 本结论不代表：真实 Amazon S4 PASS、真实候选落库成功、外部平台验收、commit/push 许可或整条工作线最终完成。
