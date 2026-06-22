# Amazon Real Search Adapter Status Summary

Date: 2026-06-22 CST
Audience: 用户
Owner: 若命（agentKey: `ruoming`）
Status: real Chrome S4 PASS; 20 Amazon candidates landed; paused before visual match continuation

## Current Stop Point

当前工作线停在真实搜索候选已落库后的后续推进点：

- 真实 Amazon search adapter + task runtime auto-start 的 S2/S3 实现已完成。
- `empty_results` evidence、`region_page` false positive、真实 DOM parser、parser safety 两轮问题均已修复并通过镜花 focused review/rereview。
- 观止已执行 `MSG-20260622-071`：使用真实 Chrome adapter 走正式 API `POST /api/products/92/competitor-search/retry`。
- 本轮真实 Chrome task run `769` / step `775` 成功。
- 真实 Amazon candidates 已落库 20 条，`asin_url_mismatch_count=0`。
- Product `92 / W808P389332` 已进入 `visual_match_competitors/pending`，下一步可继续视觉初筛。
- QA 结论：`QA / PASS_WITH_SCOPE`，范围仅覆盖真实 Amazon search candidate landing 和进入后续可继续状态。
- 本结论不覆盖视觉初筛、详情抓取、自动选竞品、图片分析、Listing、导出、A+、TikTok 或 Seller Central。
- 当前还没有针对本工作线执行 scoped commit/push。


## Related Messages And Files

- `MSG-20260622-060`: 观止 QA rerun，结论 `QA / BLOCKED / REAL_EXTERNAL_DEPENDENCY`
- `MSG-20260622-061`: 听云技术方案
- `MSG-20260622-062`: 镜花设计 review，结论 `DESIGN_REVIEW / PASS_WITH_CONSTRAINTS`
- `MSG-20260622-063`: 听云 S2/S3 实现，结论 `DONE_CLAIMED`
- `MSG-20260622-064`: 镜花代码 review，结论 `CODE_REVIEW / NEEDS_FIX`
- `MSG-20260622-071`: 观止真实 Chrome S4 rerun after parser safety fix，结论 `QA / PASS_WITH_SCOPE`
- QA 报告：`docs/collaboration/reviews/2026-06-22-amazon-auto-flow-full-real-scenario-qa.md`
- 技术方案：`docs/superpowers/specs/2026-06-22-real-amazon-search-adapter-runtime-autostart-plan.md`

## What Each Role Did

### 观止

观止围绕 product `92 / W808P389332` 多次走正式 API：

```text
POST /api/products/92/competitor-search/retry
```

历史阻塞演进：

- 初次 S4 到达真实 Amazon search adapter 边界，但失败于 `adapter_not_configured`。
- 用户授权真实 Chrome adapter 后，S4 访问到 Amazon 页面，但误判为 `region_page`。
- 修复 `region_page` false positive 后，页面分类越过，但失败于 `empty_results`；evidence 显示正常搜索结果页且 `result_count_hint=48`。
- parser/evidence 和 parser safety 修复完成并通过镜花后，观止执行 `MSG-20260622-071`。

最新结果：

- `MSG-20260622-071` 结论：`QA / PASS_WITH_SCOPE`。
- 正式 API 返回 200。
- 真实 Chrome task run `769` / step `775` 成功。
- `amazon_competitor_search_candidates` 落库 20 条。
- `asin_url_mismatch_count=0`。
- Product `92` 进入 `visual_match_competitors/pending`。
- Evidence root：`tmp/qa-evidence-20260622-s4-after-parser-safety-fix/`。

结论边界：这是真实 Amazon search candidate landing 的 scoped QA PASS，不代表视觉初筛、详情抓取、自动选竞品、图片分析、Listing、导出、A+、TikTok 或 Seller Central 已验收。

### 听云

听云先写了技术方案，后实现 S2/S3：

- 新增默认关闭的真实 Amazon search adapter 配置
- 只有 `AMAZON_SEARCH_PAGE_ADAPTER=chrome` 且 `AMAZON_SEARCH_ENABLE_REAL_BROWSER=true` 才启用真实 Chrome adapter
- 复用本机 macOS Google Chrome / AppleScript 控制器做只读 Amazon 搜索页访问
- evidence 按 `task_run_id / task_step_id / query_index` 写入
- typed failure 包括 `adapter_not_configured`、`browser_unavailable`、`browser_permission_denied`、`navigation_timeout`、`login_required`、`captcha`、`bot_check`、`region_page`、`unsupported_page_structure`、`empty_results`、`parser_error`、`rate_limited`
- runtime 增加 runner 生命周期日志、异常可见性、stale runner/handle 清理
- `scripts/test_task_runtime_autostart.py` 已升级为真实 probe task run/step，触达 `_claim_next_step` / `_execute_step` / worker 路径

听云第一次实现后，若命打回了两个问题：

- `AMAZON_SEARCH_MAX_CANDIDATES` 配置没有成为候选落库上限事实源
- runtime auto-start 测试只证明 runner 调度，没有证明 ready step 被领取执行

听云已返工闭合这两点。

### 镜花

镜花设计 review 通过，允许进入 S2/S3，但要求：

- 默认 fail closed
- evidence 必须可追溯
- fixture/mock/cache/evidence 不能冒充真实成功
- action 不写浏览器逻辑，adapter 不写 workflow
- runtime 不能用自动 wake 冒充修复

镜花代码 review 后打回 1 个 P1：

`ChromeAmazonSearchPageAdapter.search()` 在页面分类 blocker 和成功分支会写 evidence，但如果 `parse_amazon_search_results_html()` 抛 `AmazonSearchPageError("empty_results", ...)`，当前代码直接 re-raise，没有写 evidence。

影响：

- S4 如果遇到 Amazon 页面结构变化、空结果或解析失败边界，会有 typed failure，但没有 `run/step/query` evidence 文件。
- 观止无法追溯 URL、title、DOM summary、错误上下文。

修复要求：

- parse 抛 `AmazonSearchPageError` 时也写 evidence。
- evidence 至少包含 `error_type`、`error_message`、`finished_at`、`candidate_count=0`、page URL/title/classification/dom summary。
- 补测试：模拟 navigate 成功、DOM 有 search result 结构但无可解析 ASIN，断言 `empty_results` 且 evidence path 存在。

## Current Changed Files In This Work Line

Code:

- `backend/app/config.py`
- `backend/app/services/amazon_search_page.py`
- `backend/app/product_tasks/actions.py`
- `backend/app/task_runtime/scheduler.py`

Tests / rules:

- `scripts/test_project_rules.py`
- `scripts/test_amazon_search_page_real_adapter_boundaries.py`
- `scripts/test_task_runtime_autostart.py`

Docs:

- `docs/domain-index/product-flow.md`
- `docs/domain-index/task-runtime.md`
- `docs/superpowers/specs/2026-06-22-real-amazon-search-adapter-runtime-autostart-plan.md`
- `docs/collaboration/reviews/2026-06-22-amazon-auto-flow-full-real-scenario-qa.md`
- `docs/collaboration/inbox.md`

Collaboration rule files updated by this user-visible-summary rule:

- `docs/collaboration.md`
- `docs/collaboration/roles/ruoming.md`
- `docs/domain-index/collaboration.md`

## Verified So Far

### Before 镜花 P1 Finding

若命曾 rerun:

```bash
python -m compileall backend/app
make test-project-rules
cd backend && .venv/bin/python ../scripts/test_amazon_search_page_real_adapter_boundaries.py
cd backend && .venv/bin/python ../scripts/test_task_runtime_autostart.py
git diff --check -- <scoped files>
```

Results at that time:

- compile: PASS
- project rules: PASS, 62 tests
- Amazon adapter boundary script: PASS
- task runtime auto-start script: PASS
- diff check: PASS

These results do not close the current P1, because `empty_results` evidence behavior was found afterward by 镜花.

### After P1 Fix

若命已重新核对 `backend/app/services/amazon_search_page.py` 和 `scripts/test_amazon_search_page_real_adapter_boundaries.py`：

- `ChromeAmazonSearchPageAdapter.search()` 在 `parse_amazon_search_results_html()` 抛 `AmazonSearchPageError` 时，会写 evidence 后 re-raise。
- evidence 包含 `finished_at`、`candidate_count=0`、`error_type`、`error_message`，并保留前面已采集的 `page_url`、`page_title`、`classification`、`dom_summary`。
- 专项测试新增/保留反例：Chrome navigate 成功，DOM 有 `data-component-type="s-search-result"`，但没有可解析 ASIN；断言抛 `empty_results`，且 evidence 写到 `run-9301/step-9402/query-3.json`。

若命本轮验证：

```bash
python -m compileall backend/app
make test-project-rules
cd backend && .venv/bin/python ../scripts/test_amazon_search_page_real_adapter_boundaries.py
cd backend && .venv/bin/python ../scripts/test_task_runtime_autostart.py
git diff --check -- <scoped files>
```

结果：

- compile: PASS
- project rules: PASS, 62 tests
- Amazon adapter boundary script: PASS
- task runtime auto-start script: PASS
- scoped diff check: PASS

### Focused 镜花 Rereview

镜花子 agent 已完成 focused rereview，报告文件：

- `docs/collaboration/reviews/2026-06-22-amazon-empty-results-evidence-rereview.md`

结论：

- `CODE_REVIEW_REREVIEW / PASS_WITH_SCOPE`
- P1 已闭合。
- 允许进入观止 S4 QA。

镜花复审命令：

```bash
cd backend && .venv/bin/python ../scripts/test_amazon_search_page_real_adapter_boundaries.py
python -m compileall backend/app
git diff --check -- backend/app/services/amazon_search_page.py scripts/test_amazon_search_page_real_adapter_boundaries.py
```

结果：

- Amazon adapter boundary script: PASS
- compile: PASS
- scoped diff check: PASS

镜花边界声明：

- 本结论只代表 focused code rereview 通过。
- 不代表真实 Amazon 页面 QA、真实候选落库成功、外部平台验收、commit/push 或整体 S2/S3 全量复审。

### 观止 S4 QA After Code Gate

观止子 agent 已完成 `MSG-20260622-065`，报告文件：

- `docs/collaboration/reviews/2026-06-22-amazon-auto-flow-full-real-scenario-qa.md`

结论：

- `QA / BLOCKED / REAL_EXTERNAL_DEPENDENCY`
- product `92 / W808P389332`
- API：`POST /api/products/92/competitor-search/retry`
- 新 task run：`755`
- 新 task step：`761`
- runtime wake：未使用；task run 自动执行到 adapter 边界。
- 候选落库：`0`
- 最终商品状态：`search_competitor/failed`，可重试。

阻塞原因：

```text
AmazonSearchPageError: Amazon search page adapter is not configured; real Amazon search requires explicit browser authorization
```

证据目录：

- `tmp/qa-evidence-20260622-s4-after-code-gate/`

关键判断：

- 这不是 `QA / PASS_WITH_SCOPE`，因为没有真实 Amazon candidates landed，商品没有进入下一流程节点。
- 这也不是新的代码 `NEEDS_FIX`：本次已经证明正式 API、planner/action/task runtime 能自动到达 adapter 边界；阻塞点是当前运行环境没有启用/授权真实 Chrome Amazon search adapter。
- 因 active adapter 是 `unconfigured`，本次没有生成 `data/task_evidence/amazon_search_page` 页面级 evidence；这符合 fail-closed 配置阻塞的行为。

### 观止 S4 QA With Real Chrome Adapter

用户授权后，观止子 agent 已完成 `MSG-20260622-066`，报告文件：

- `docs/collaboration/reviews/2026-06-22-amazon-auto-flow-full-real-scenario-qa.md`

运行事实：

- 环境：`AMAZON_SEARCH_PAGE_ADAPTER=chrome`，`AMAZON_SEARCH_ENABLE_REAL_BROWSER=true`
- Product：`92 / W808P389332`
- API：`POST /api/products/92/competitor-search/retry`
- New task run：`756`
- New task step：`762`
- Adapter：`ChromeAmazonSearchPageAdapter`
- Page evidence：`tmp/qa-evidence-20260622-s4-real-chrome/amazon-search-page/run-756/step-762/query-1.json`
- Amazon URL：`https://www.amazon.com/s?k=cabinet+adjustable+freestanding+mdf+bathroom&language=en_US&ref=nb_sb_noss`
- Page title：`Amazon.com : cabinet adjustable freestanding mdf bathroom`
- Classification：`region_page`
- Candidate landing：`0`

若命复核判断：

- 本次不能判 `PASS_WITH_SCOPE`，因为没有真实候选落库。
- 但也不能简单收口为真实外部 `region_page` blocker。
- Evidence 显示 `dom_summary.result_count_hint=48`，`body_text_sample` 开头包含 `Results` / `Filters` / search page navigation，说明 Chrome 已经拿到正常搜索结果页结构。
- 当前 `classify_amazon_search_page()` 的 region 规则过粗：普通 Amazon 搜索页导航也会出现 `deliver to` / `choose your location` 文案，导致误判。

新的执行任务：

- `MSG-20260622-067 - AMAZON_SEARCH_REGION_PAGE_FALSE_POSITIVE`
- Owner：听云
- 目标：修复正常搜索结果页被 `region_page` 误杀的问题，补真实 evidence 形态回归测试。
- 修复后仍需若命 review、必要时镜花 review、再交观止重跑 S4。

### 听云 Region Page False Positive Fix

听云子 agent 已完成 `MSG-20260622-067`，若命已复核。

改动文件：

- `backend/app/services/amazon_search_page.py`
- `scripts/test_amazon_search_page_real_adapter_boundaries.py`

修复摘要：

- `captcha` / `bot_check` / `rate_limited` / `login_required` 仍优先 fail closed。
- 正常搜索结果页只要存在可靠搜索结果结构，不再被配送导航文案如 `deliver to` / `choose your location` 误判为 `region_page`。
- 真正 region/location blocker 仍返回 `region_page`。
- `unsupported_page_structure` 仍在确实没有搜索结果结构/ASIN 信号时 fail closed。
- 新增真实 evidence 形态回归测试：搜索页包含 `Results`、`Filters`、`Deliver to`、`choose your location`、`s-search-result` 和可解析 ASIN 时，不判 `region_page` 且可解析候选。
- 保留/新增真正 region blocker、unsupported page、empty_results evidence 回归。

若命复跑验证：

```bash
python -m compileall backend/app
make test-project-rules
cd backend && .venv/bin/python ../scripts/test_amazon_search_page_real_adapter_boundaries.py
git diff --check -- backend/app/services/amazon_search_page.py scripts/test_amazon_search_page_real_adapter_boundaries.py scripts/test_project_rules.py
```

结果：

- compile: PASS
- project rules: PASS, 62 tests
- Amazon adapter boundary script: PASS
- scoped diff check: PASS

### 镜花 Focused Review For Region Fix

镜花子 agent 已完成 `MSG-067` focused code review。

Review 文件：

- `docs/collaboration/reviews/2026-06-22-amazon-region-page-false-positive-code-review.md`

结论：

- `CODE_REVIEW / PASS_WITH_SCOPE`
- 未发现 P0/P1。
- 允许观止重跑真实 Chrome S4。

镜花验证：

```bash
python -m compileall backend/app
make test-project-rules
cd backend && .venv/bin/python ../scripts/test_amazon_search_page_real_adapter_boundaries.py
git diff --check -- backend/app/services/amazon_search_page.py scripts/test_amazon_search_page_real_adapter_boundaries.py scripts/test_project_rules.py
```

结果：

- compile: PASS
- project rules: PASS, 62 tests
- Amazon adapter boundary script: PASS
- scoped diff check: PASS

边界：

- 该 PASS 不代表真实 Amazon candidates 已落库。
- 不代表端到端 QA PASS。
- 不授权 commit/push。

### 观止 S4 Rerun After Region Fix

观止子 agent 已完成 `MSG-20260622-068`。

运行事实：

- Product：`92 / W808P389332`
- API：`POST /api/products/92/competitor-search/retry`
- New task run：`761`
- New task step：`767`
- Adapter evidence：`tmp/qa-evidence-20260622-s4-after-region-fix/amazon-search-page/run-761/step-767/query-1.json`
- Page title：`Amazon.com : cabinet adjustable freestanding mdf bathroom`
- Classification：`null`
- Error type：`empty_results`
- `dom_summary.result_count_hint=48`
- Candidate landing：`0`

观止结论：

- `QA / BLOCKED / REAL_EXTERNAL_DEPENDENCY`

若命复核判断：

- 不接受把本轮直接作为外部 blocker 收口。
- `region_page` false positive 已被真实页面复验修掉。
- Evidence 显示页面有搜索结果结构，但 parser 没识别出候选。
- 这更可能是 `parse_amazon_search_results_html()` 对真实 Amazon DOM 支持不足，或 `empty_results` evidence 不足以定位真实 DOM 缺口。

新的执行任务：

- `MSG-20260622-069 - AMAZON_SEARCH_REAL_DOM_EMPTY_RESULTS_PARSER`
- Owner：听云
- 目标：修复真实 DOM 候选解析能力，并增强 `empty_results` evidence，让下次失败可定位。
- 修复后仍需若命 review、必要时镜花 review、再交观止重跑真实 Chrome S4。

### 听云 Real DOM Parser Fix

听云子 agent 已完成 `MSG-20260622-069`，若命已复核。

改动文件：

- `backend/app/services/amazon_search_page.py`
- `scripts/test_amazon_search_page_real_adapter_boundaries.py`
- `scripts/test_project_rules.py`

修复摘要：

- `s-search-result` 结果块识别不再要求 `data-asin` 同 tag、同顺序或双引号。
- `data-asin` 支持单双引号、额外空格、未加引号和属性顺序变化。
- ASIN 优先取 result block opening tag 的合法 10 位 `data-asin`；为空/无效时 fallback 到同一 result block 内 `/dp/{ASIN}` 或 `/gp/product/{ASIN}` 商品链接。
- 解析前剥离 `script/style`，避免脚本里的假 ASIN 生成候选；导航假 ASIN 不在 result block 内也不会生成候选。
- `empty_results` evidence 的 `dom_summary` 增加 `data_asin_hint`、`dp_link_hint`、前 3 个安全截断 `result_block_snippets`，不保存整页 HTML。

若命复核重点：

- fallback 没有变成全页抓 ASIN。
- `captcha` / `bot_check` / `rate_limited` / `login_required` / `region_page` / `unsupported_page_structure` / `empty_results` 语义仍保留。
- 测试覆盖属性顺序、单双引号/空格、`/dp/{ASIN}` fallback、脚本/导航假 ASIN、region/unsupported/empty_results evidence 回归。

若命复跑验证：

```bash
python -m compileall backend/app
make test-project-rules
cd backend && .venv/bin/python ../scripts/test_amazon_search_page_real_adapter_boundaries.py
git diff --check -- backend/app/services/amazon_search_page.py scripts/test_amazon_search_page_real_adapter_boundaries.py scripts/test_project_rules.py
```

结果：

- compile: PASS
- project rules: PASS, 62 tests
- Amazon adapter boundary script: PASS
- scoped diff check: PASS

### 镜花 Parser Safety Review

镜花子 agent 已完成 `MSG-069` focused code review。

Review 文件：

- `docs/collaboration/reviews/2026-06-22-amazon-real-dom-parser-code-review.md`

结论：

- `CODE_REVIEW / NEEDS_FIX`
- 暂不允许观止重跑真实 Chrome S4。

P1-1：result block slicing 可能捕获 result 后面的无关 `/dp` 链接。

- 当前 `_result_blocks()` 以当前 result opening tag 到下一个 result opening tag 或文档结尾作为 block 边界。
- 如果当前 result shell 的 `data-asin` 为空/无效，后续导航/promo 出现 `/dp/{ASIN}`，fallback 可能误抓。
- 镜花复现：`post_result_nav_fallback [('B0NAVIG001', 'https://www.amazon.com/dp/B0NAVIG001', 'Shell')]`

P1-2：candidate ASIN 和 URL ASIN 可能不一致。

- opening tag 有合法 `data-asin` 时，如果没有匹配该 ASIN 的链接，当前逻辑会返回第一个 fallback `/dp` URL，即使 URL 中 ASIN 不同。
- 镜花复现：`mismatch_valid_data_asin [('B0RIGHT001', 'https://www.amazon.com/dp/B0WRONG001', 'Right')]`

新的执行任务：

- `MSG-20260622-070 - AMAZON_SEARCH_REAL_DOM_PARSER_SAFETY_FIX`
- Owner：听云
- 目标：修复 result block fallback 边界和 candidate ASIN/URL 一致性，再补回归测试。

### 听云 Parser Safety Fix

听云子 agent 已完成 `MSG-20260622-070`，若命已复核。

改动文件：

- `backend/app/services/amazon_search_page.py`
- `scripts/test_amazon_search_page_real_adapter_boundaries.py`

修复摘要：

- `_result_blocks()` 改为按 result `<div>` 的 balanced closing boundary 截取。
- 若 HTML 畸形找不到可靠 closing，会在 `nav/header/footer/main/aside` 或 30000 字符上限处截断，避免把后续导航/promo/全页 `/dp` 链接纳入 fallback。
- `_extract_product_url()` 在 opening tag 有合法 `data-asin` 时，只接受同 ASIN 的 `/dp` 或 `/gp/product` URL。
- 如果只有错配 URL，则保留 candidate ASIN，但 URL 返回 `None`，不再输出 ASIN/URL 不一致候选。

新增/保留测试：

- 空 `data-asin` result shell 后跟 nav `/dp`，断言 `empty_results`。
- 畸形 result shell 缺 closing `</div>` 后跟 nav `/dp`，断言 `empty_results`。
- `data-asin="B0RIGHT001"` 且唯一链接 `/dp/B0WRONG001`，断言 ASIN 保持、URL 为 `None`。
- 保留 result 内 `/dp/{ASIN}` fallback 可用、script/style/nav 假 ASIN 不生成候选、typed failure 和 empty evidence snippet 回归。

若命复跑验证：

```bash
python -m compileall backend/app
make test-project-rules
cd backend && .venv/bin/python ../scripts/test_amazon_search_page_real_adapter_boundaries.py
git diff --check -- backend/app/services/amazon_search_page.py scripts/test_amazon_search_page_real_adapter_boundaries.py scripts/test_project_rules.py
```

结果：

- compile: PASS
- project rules: PASS, 62 tests
- Amazon adapter boundary script: PASS
- scoped diff check: PASS

### 镜花 Parser Safety Rereview

镜花子 agent 已完成 `MSG-070` focused rereview。

Review 文件：

- `docs/collaboration/reviews/2026-06-22-amazon-real-dom-parser-code-review.md`

结论：

- `CODE_REVIEW_REREVIEW / PASS_WITH_SCOPE`
- 两个 P1 已闭合。
- 允许观止重跑真实 Chrome S4。

关键证据：

- `post_result_nav_fallback` 从错误候选变为 `empty_results`。
- `mismatch_valid_data_asin` 从错配 URL 变为 `('B0RIGHT001', None, 'Right')`。
- result 内 `/dp/{ASIN}` fallback 仍可用。
- script/style/nav 假 ASIN 不生成候选。
- typed failure 和 empty evidence snippet 语义未破坏。

镜花验证：

```bash
python -m compileall backend/app
make test-project-rules
cd backend && .venv/bin/python ../scripts/test_amazon_search_page_real_adapter_boundaries.py
git diff --check -- backend/app/services/amazon_search_page.py scripts/test_amazon_search_page_real_adapter_boundaries.py scripts/test_project_rules.py
```

结果：

- compile: PASS
- project rules: PASS, 62 tests
- Amazon adapter boundary script: PASS
- scoped diff check: PASS

## What Is Not Done

- No commit or push for this work line.
- No real Amazon successful candidate landing has been proven yet.
- Real Chrome authorization / Amazon page navigation has been proven, but parser has not successfully reached candidate landing.
- No S4 rerun after the parser fix yet.
- Playwright, remote headless execution, durable cross-restart worker, and leader election remain out of scope.

## Next Options

1. Rerun S4 with real Chrome adapter:
   - Use user-authorized Chrome adapter config.
   - Product `92 / W808P389332` unless a new safe sample is selected.
   - Expected result is real candidate landing, or a defensible typed external blocker after parser safety fix.
2. Pause for user inspection:
   - User reviews the files above before any more agent work.
3. Change direction:
   - Stop local Chrome/AppleScript route and discuss a Playwright or plugin/client-side route instead.

Default next step if user says “继续” again:

- Continue option 1. Do not commit or push until parser safety fix passes review and a real S4 rerun reaches a valid PASS or a defensible typed external blocker.
