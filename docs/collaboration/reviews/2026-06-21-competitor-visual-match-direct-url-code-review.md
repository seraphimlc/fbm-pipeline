# 2026-06-21 Competitor Visual Match Direct URL Code Review

Reviewer: 镜花 (`jinghua`)

Source message: `MSG-20260621-002`

Conclusion: `CODE_REVIEW / PASS`

## Scope

本次只审查竞品视觉初筛 Phase B 的 direct URL only 收敛：代码路径、数据契约、任务生命周期、测试规则和文档索引一致性。

本次不做页面 QA、不跑真实商品 task run、不触发真实 VLM、不访问外部平台、不评估最终竞品选择质量，不审 Listing、A+、导出、Step 10、模板映射或真实 ASIN 写入。

## Blocking Findings

无阻断项。

## Passed Checks

1. Direct URL 主路径成立。
   - `backend/app/services/amazon_competitor_visual_match.py` 不 import/call `analyze_contact_sheet()`，也没有 `build_contact_sheets`、`download_candidate_image`、`DownloadedCandidateImage`、`CONTACT_SHEET_SIZE`、`Image.open`、`ImageDraw` 等候选下载/拼图主流程标记。
   - `run_competitor_visual_match()` 默认 `use_fake_vlm=False`，真实路径调用 `_analyze_direct_url_reviews()`；fake fixture 只在显式 `use_fake_vlm=True` 下走 `_fake_visual_reviews()`，并返回 `input_mode=fake_fixture`。
   - `_analyze_direct_url_reviews()` 以第一张 source/reference image 加候选 `image_url` 列表 direct VLM，未保留 URL 失败后的下载/Contact Sheet fallback。

2. 输入绑定和 VLM schema 满足本轮契约。
   - source 图读取 `Product.images.main_image_path`；远程 URL 原样传给 VLM，本地文件通过 `image_data_url()` 转 data URL。结合当前商品图片存储同时存在 remote/local 路径的事实，这是对 source/reference 的必要兼容，不改变候选 direct URL only 的主路径。
   - `_current_successful_search_run_step()` 只取最新成功 `product_competitor_search` run 和成功 step。
   - `_current_search_candidates()` 同时绑定 `product_id + task_run_id + task_step_id`，过滤 `is_excluded=0`、`image_url` 非空，按 rank/id 排序并最多取 20。
   - prompt/schema 要求 `slot`、`asin`、`image_loaded`、`same_product_type`、`visual_similarity`、`attribute_match`、`title_match`、`reject`、`reject_reason`、`reason`。
   - JSON 解析失败、缺少 candidates、非对象项、未知 slot、ASIN 不匹配、重复 slot、缺失 slot 都会抛 `CompetitorVisualMatchError`，没有按顺序猜或静默修正。

3. 写入和失败语义符合当前任务边界。
   - `ProductCompetitorVisualMatchAction.execute_step()` 调用 `run_competitor_visual_match(product_id, db=db)`，不传 fake 参数。
   - `_write_visual_match_results()` 只查询当前 `product_id + search_run_id + search_step_id` 的候选并写入 visual 字段；`visual_sheet_path/page/label` 在当前写入中置空。
   - 服务层先筛 Top 4-6：`MIN_SELECTED=4`、`MAX_SELECTED=6`；Top 不足抛错，不推进。
   - failure/cancel/interrupted 都进入 `_project_competitor_visual_match_failed()`，该函数先 `clear_current_visual_match()`，再投影 `visual_match_competitors/failed`，不保留 current selected candidates。
   - `ProductCompetitorSearchAction.reserve()` 在重搜竞品时清视觉结果，符合“Phase A 重新搜索后旧视觉结果失效”的数据语义；当前未发现越界写后续阶段状态。

4. API、workflow 和前端入口未越界。
   - `POST /api/products/{id}/competitor-visual-match/retry` 只在 `visual_match_competitors/pending|failed` 创建/复用视觉任务，`processing` 时直接返回当前 workflow 状态，不通过 planner 创建重复 run。
   - `workflow.py` 增加视觉初筛节点 action 与 correlation key，成功后等待 `capture_competitor_candidates/pending`，没有自动抓 Amazon 详情或自动最终选竞品。
   - `ProductList.tsx` 只是消费后端 action 调用 retry API；未在前端重新实现 direct URL/VLM/选择规则。

5. 文档和索引口径一致。
   - PRD 已写明 Phase B 默认 direct image URL only，不下载候选图、不生成 Contact Sheet、不调用 `analyze_contact_sheet()`。
   - `docs/domain-index/product-flow.md` 与 `docs/domain-index/task-runtime.md` 均指向 `product_competitor_visual_match` planner/action/service，并写明 current run/step 限定、processing API bypass、失败清理 selected。
   - `docs/project-index.md` 保持导航口径；本轮没有新增顶层问题类型或新 domain index。

6. 禁止范围未见污染。
   - scoped search 未发现本轮进入自动串联、抓 Amazon 详情、最终选竞品、图片分析、Listing、A+、导出、Step 10、模板映射、真实 ASIN 或真实导出文件链路。
   - TLS 默认仍在生产配置中保持 `EXTERNAL_HTTP_VERIFY_TLS=True`；未见 `verify=False` 进入本轮生产代码路径。

## Verification

已复跑：

```bash
python -m compileall backend/app
make test-project-rules
cd frontend && npm run build
git diff --check
```

结果：

- `python -m compileall backend/app`: PASS
- `make test-project-rules`: PASS, `OK: 54 project rule test(s)`
- `cd frontend && npm run build`: PASS；仅有既有 Vite chunk-size warning
- `git diff --check`: PASS

## Non-blocking Risks

1. `visual_sheet_path/page/label` 仍保留在 ORM 和 MySQL startup ensure 中。
   - 当前代码已停止作为证据字段使用，并在写入/清理中置空；不阻断本轮。
   - 后续如要物理删除，需要单独 migration/drop 决策，避免直接删字段影响已有库。

2. 测试里有一部分是字符串契约测试。
   - 它能锁住“不得回到 Contact Sheet 主路径”的硬标记，但对 `_write_visual_match_results()` 的 DB 行为、失败清理 selected 的覆盖仍偏轻。
   - 当前服务层和 action 代码事实已能支撑本轮 PASS；建议后续补一个轻量行为测试，验证 selected 写入数量、run/step 限定和失败清理。

3. source/reference 本地路径转 data URL 需要在口径上继续说清。
   - 候选图已是 direct candidate image URL；source 图兼容本地文件是为了适配当前 `product_images.main_image_path` 存储事实。
   - 这不是 Contact Sheet fallback，也不是候选下载路径；不阻断。

## Gate Meaning

`CODE_REVIEW / PASS` 表示本次 direct URL only 实现通过代码、数据契约、任务生命周期、测试规则和文档一致性审查，可以进入提交 gate。

它不代表页面 QA PASS、不代表真实商品 task run 成功、不代表真实 VLM 质量验收、不代表外部平台或后续抓详情/Listing/A+/导出链路通过。
