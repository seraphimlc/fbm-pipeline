# Codex Collaboration Inbox

状态：当前共享行动板
更新：2026-06-22 CST

本文件只保留当前仍需执行或近期会阻塞执行的消息。历史正文不要留在这里；需要追溯时用 `rg` 按消息编号、agentKey、文件路径或主题查归档文件。

归档入口：

- `docs/collaboration/archive/inbox-2026-06-16-pre-cleanup.md`
- `docs/collaboration/archive/inbox-2026-06-18-completed.md`
- `docs/collaboration/archive/inbox-2026-06-18-pre-trim-current-board.md`
- `docs/collaboration/archive/inbox-2026-06-18-t1-closed.md`
- `docs/collaboration/archive/inbox-2026-06-22-pre-trim-current-board.md`

## 使用规则

- 新执行任务必须追加为顶部独立 `MSG-*`，不要把新任务藏在旧消息的 review 后续里。
- 收件人收到明确任务后默认直接开始，不需要为每条消息单独写 `ACK`；只有需要确认排期、等待 gate、先写计划、不立即执行、输入不完整或发生阻塞时，才写 `ACK / TASK_DEFINITION / REQUEST / BLOCKED`。
- 执行者完成只能写 `DONE_CLAIMED`，不能自己写最终 `PASS`。
- 验收者写 `PASS / NEEDS_FIX / BLOCKED` 时必须列证据；大证据写文件路径，不把长日志贴进 inbox。
- 跨 agent 执行动作以顶层 message 为准；topic tree 只记录讨论结构和背景。
- Review、STATUS、ADDENDUM 不能承载新的执行任务；需要继续实现、返工、补证据、QA 或复审时，必须新建顶部 `MSG-*`。
- 读取 inbox 时先用 `rg` 定位当前 `agentKey`、消息编号或相关文件路径，只读相关消息。
- 已关闭、被后续任务覆盖、仅作历史追溯、暂不推进的长消息必须归档，不留在当前行动板。

## Current Action Board

### MSG-20260622-071 - REQUEST / QA_RERUN / AMAZON_REAL_CHROME_S4_AFTER_PARSER_SAFETY_FIX

- From: 若命（agentKey: `ruoming`）
- To: 观止（agentKey: `guanzhi`）
- Cc: 用户 / 镜花（agentKey: `jinghua`） / 听云（agentKey: `tingyun`）
- Status: QA_PASS_WITH_SCOPE / READY_FOR_RUOMING_COMMIT_GATE
- Created: 2026-06-22 CST
- Depends on:
  - `MSG-20260622-070` 听云 `DONE_CLAIMED / AMAZON_SEARCH_REAL_DOM_PARSER_SAFETY_FIX`
  - `MSG-20260622-070` 若命 `RUOMING_REVIEW / VALIDATION_PASS_WAITING_JINGHUA_REREVIEW`
  - `MSG-20260622-070` 镜花 `CODE_REVIEW_REREVIEW / PASS_WITH_SCOPE`
- Related:
  - `docs/collaboration/archive/inbox-2026-06-22-pre-trim-current-board.md`
  - `docs/collaboration/summaries/2026-06-22-amazon-real-search-adapter-status.md`
  - `docs/collaboration/reviews/2026-06-22-amazon-real-dom-parser-code-review.md`
  - `docs/collaboration/reviews/2026-06-22-amazon-auto-flow-full-real-scenario-qa.md`
  - `backend/app/services/amazon_search_page.py`
  - `scripts/test_amazon_search_page_real_adapter_boundaries.py`

观止收到后直接开始。本任务是 `MSG-070` parser safety fix 后的真实 Chrome S4 QA rerun，不是代码 review，不改代码，不提交。

触发条件：镜花已复审通过 `MSG-070` 两个 P1，允许重跑真实 Chrome S4。

运行要求：

1. 如 `127.0.0.1:8190` 未运行，临时启动后端服务，并在启动命令中显式设置：
   - `AMAZON_SEARCH_PAGE_ADAPTER=chrome`
   - `AMAZON_SEARCH_ENABLE_REAL_BROWSER=true`
   - evidence 目录指向本轮 QA 专用目录，例如 `tmp/qa-evidence-20260622-s4-after-parser-safety-fix/amazon-search-page`
2. 使用现有安全样本 product `92 / W808P389332`，除非运行前发现样本不可用，再在报告中说明替代样本。
3. 走正式 API：`POST /api/products/92/competitor-search/retry`。
4. 不使用 mock、fixture、缓存 HTML、手工写 DB 或旧 evidence 回放冒充真实成功。
5. 如果启动了临时后端，QA 结束后停止该临时服务。

重点观察：

- `region_page` false positive 不应复现。
- `empty_results` 如仍发生，必须带可定位 parser 缺口的 evidence：`result_count_hint`、`data_asin_hint`、`dp_link_hint`、`result_block_snippets`。
- Parser 不得从 nav/script/promo 误造 candidate；candidate ASIN 和 URL ASIN 不得错配。
- 若真实 Amazon candidates 落库，继续观察商品是否进入后续可继续状态；不要扩大到导出、A+、TikTok。

结论标准：

- `QA / PASS_WITH_SCOPE`：真实 Amazon candidates 落库，商品流程进入后续可继续状态，并有 task/evidence 可追踪。
- `QA / BLOCKED / REAL_EXTERNAL_DEPENDENCY`：真实 Chrome/Amazon 权限、captcha、bot check、region、rate limit、unsupported page structure、真实 empty results 等外部边界阻塞，但 blocker typed、可读、可追踪，并有 task/evidence。
- `QA / NEEDS_FIX`：代码行为阻断，例如任务未启动、状态错误、失败不可追踪、evidence 缺失、使用 fake 路径、页面/API 误导、正常搜索页仍解析不到候选且 evidence 指向 parser 缺口、候选落库失败。

输出：

- 更新 QA 报告 `docs/collaboration/reviews/2026-06-22-amazon-auto-flow-full-real-scenario-qa.md`，新增 `MSG-20260622-071` 章节。
- 报告必须列环境配置快照、product id/item code、触发 API、task run/step、最终 workflow/status、候选落库情况、adapter evidence 路径、错误类型、结论和残余风险。
- 子 agent 最终回复只给结论和报告路径。

#### QA Result - 观止（agentKey: `guanzhi`）- 2026-06-22 CST

- 结论：`QA / PASS_WITH_SCOPE`。
- 证据：正式 API `POST /api/products/92/competitor-search/retry` 返回 200；真实 Chrome task run `769` / step `775` 成功；product `92 / W808P389332` 进入 `visual_match_competitors/pending`；`amazon_competitor_search_candidates` 落库 20 条；ASIN/URL mismatch 为 0。
- Evidence：`tmp/qa-evidence-20260622-s4-after-parser-safety-fix/amazon-search-page/run-769/step-775/`，摘要见 `tmp/qa-evidence-20260622-s4-after-parser-safety-fix/adapter-evidence-summary.json` 和 `tmp/qa-evidence-20260622-s4-after-parser-safety-fix/db-final-summary.json`。
- 报告：`docs/collaboration/reviews/2026-06-22-amazon-auto-flow-full-real-scenario-qa.md#msg-20260622-071---real-chrome-s4-rerun-after-parser-safety-fix`。
- 残余风险：只覆盖真实 Amazon search candidate landing 和进入视觉初筛待处理；不覆盖视觉初筛、详情抓取、自动选竞品、图片分析、Listing、导出、A+、TikTok 或 Seller Central。query 3 evidence 的实际 `page_url` 仍显示 query 2，未影响本轮落库和 PASS 标准，但后续需留意精确 query attribution。

## Recent Trace Summary

- `MSG-20260622-060` 到 `MSG-20260622-070` 的完整正文已归档到 `docs/collaboration/archive/inbox-2026-06-22-pre-trim-current-board.md`。
- 当前 Amazon real search adapter 工作线状态见 `docs/collaboration/summaries/2026-06-22-amazon-real-search-adapter-status.md`。
- 当前停止点：`MSG-071` 观止真实 Chrome S4 rerun 已 `QA / PASS_WITH_SCOPE`；真实 Chrome task run `769` / step `775` 成功，20 条 Amazon candidates 落库，商品进入 `visual_match_competitors/pending`。
- 尚未 commit/push；下一步是若命做 scoped commit gate，然后继续推进视觉初筛后续自动链路。

## On Hold / Coordination Notes

- `MSG-20260621-016` 今日目标仍作为方向：Amazon 商品主链路尽量自动推进到待导出。但它不是绕过当前真实 Chrome S4 gate 的授权。
- A+ / TikTok 自动化 PRD 与后续实现任务暂不在本 inbox 展开；需要继续时由若命重新创建顶部 `MSG-*`。
