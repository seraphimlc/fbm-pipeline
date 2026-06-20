# 2026-06-21 Auto Image And Step6 Direct URL Code Review

Reviewer: 镜花 (`jinghua`)

Source message: `MSG-20260621-005`

Conclusion: `CODE_REVIEW / PASS`

## Scope

本次审查范围限于 `MSG-20260621-005`：自动选图 URL-first、自动选图失败不下载/不拼 Contact Sheet 兜底、成功写 URL、Step6 图片分析 direct image input only、前端详情页展示兼容、测试和文档一致性。

本次不审 `docs/project-index.md`、`docs/database-schema-review.md`、协作/角色文档、`frontend/tsconfig.tsbuildinfo`、`tmp/`，不做页面 QA，不跑真实商品 task run，不触发真实 VLM，不访问外部平台，不审竞品搜索、抓详情、最终选竞品、Listing、A+、导出、Amazon 上传、Step 10、模板映射、真实 ASIN、人工确认态或真实导出产物。

## Blocking Findings

无阻断项。

## Passed Checks

1. 自动选图候选 URL-first 成立。
   - `backend/app/services/product_image_candidates.py` 的 `normalize_image_path()` 按 `image_url -> path -> local_path` 归一。
   - `_candidate_rank()` 对有 `image_url` 的候选优先排序；`_dedupe_key()` 优先用 `image_url` 去重，没有 URL 时才回退 `path/local_path`。
   - `_add_candidate()` 写入候选时把 `path` 设为 `image_url or path`，同时保留 `local_path`，所以有 URL 时不会把本地路径当主输入，没有 URL 的历史/人工素材仍保留。

2. 自动选图默认路径不再下载或 Contact Sheet fallback。
   - `backend/app/product_tasks/auto_image_selection.py` 只从 `product_image_vlm` 导入 `build_image_url_batches()`、`analyze_image_url_batch()`、`is_remote_url()`，未导入/调用 `download_image_records`、`build_contact_sheets`、`analyze_contact_sheet`。
   - `_records_from_candidates()` 有 URL 时直接作为 source；没有 URL 的本地文件仍检查存在性，并由 `analyze_image_url_batch()` 转 data URL 输入 VLM。
   - `_run_with_db()` direct image URL VLM 失败时抛 `AutoImageSelectionError("自动选图 direct image URL VLM 失败...")`，由 ProductTaskAction failure 投影到 `auto_select_images/failed`，没有下载/拼图兜底。

3. 自动选图成功写 URL 成立。
   - `backend/app/product_tasks/actions.py` 的 `_selected_listing_image_ref()` 按 `image_url -> path -> local_path` 取值。
   - `ProductAutoImageSelectionAction.on_step_success()` 用该 helper 写 `ProductImage.main_image_path` 和 `gallery_images`；`gallery_order` 保留 selected role、score、reason、risk flags、候选字段等解释证据。

4. Step6 纳入本 gate 的边界成立。
   - `backend/app/pipeline/step6_image.py` 的 `run_image_analysis()` 仅调用 `_build_image_url_batches()` / `_analyze_image_url_batch()`；旧 `_download_image_records`、`_build_contact_sheets`、`_analyze_contact_sheet` 已不在当前运行段。
   - direct URL 调用失败立即抛 `RuntimeError("图片URL直传VLM失败，未下载图片或切换 Contact Sheet 兜底...")`，不会静默下载、生成 Contact Sheet、逐张 fallback 或伪造部分成功。
   - 本地历史/人工素材未被破坏：`_prepare_confirmed_image_sources()` 从已确认主图/副图生成 image records；`analyze_image_url_batch()` 对非远程路径使用 `image_data_url(Path(...))` 传给 VLM。
   - 新结果写 `image_batches`，`pi.contact_sheet_path = None`；缓存恢复只读兼容旧 `contact_sheets`，并转写到 `image_batches`。

5. 前端详情页展示契约成立。
   - `frontend/src/pages/ProductDetail.tsx` 读取 `imageAnalysisPayload?.image_batches || legacyContactSheets`。
   - `isVirtualImageBatch()` 识别 `url_batch:*`；虚拟批次不生成展示 URL、不显示打开按钮、不渲染 Contact Sheet 图片。
   - legacy `contact_sheets` / `images.contact_sheet_path` 仍只读展示；标题和空态文案已从 Contact Sheet 改为“图片分析批次”。

6. 文档和索引一致。
   - `docs/superpowers/specs/2026-06-19-amazon-auto-image-selection-prd.md` 已更新为 URL direct image input、URL 失败不下载/不 Contact Sheet、输出 `image_batches`、候选 URL-first 去重。
   - `docs/domain-index/product-flow.md` 已同步自动选图候选和成功写库 URL 优先、已有 URL 不下载/不生成 Contact Sheet、不写本地路径。

7. 禁止范围未见污染。
   - scoped search 和 diff 未见本 gate 进入竞品搜索、抓详情、最终选竞品、Listing、A+、导出、Amazon 上传、Step 10、模板映射、真实 ASIN、人工确认态或真实导出产物。

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
- `cd frontend && npm run build`: PASS；仅既有 Vite chunk-size warning
- `git diff --check`: PASS

## Non-blocking Risks

1. 测试仍有字符串契约成分。
   - 当前有函数级行为测试覆盖候选 URL 优先和 action 成功写 URL；但 Step6 “失败不 fallback”和前端虚拟 batch 展示主要靠字符串规则锁住。
   - 不阻断本轮，因为代码事实和验证命令已支撑当前 gate；建议后续补轻量行为测试：mock `_analyze_image_url_batch()` 抛错，验证不调用旧 fallback，且不写 `contact_sheet_path`。

2. `product_image_vlm.py` 仍保留旧 Contact Sheet helper。
   - 当前自动选图和 Step6 主路径不调用这些 helper；保留属于底层历史能力/其它路径兼容，不阻断本 gate。
   - 后续如要彻底退役旧 helper，需要单独确认其它调用方，例如旧 pipeline 或历史图片确认路径。

3. 未做真实 VLM 和页面 QA。
   - 本 PASS 不证明真实 URL 可达性、多图 direct input 稳定性、页面视觉效果或真实商品端到端成功。

## Gate Meaning

`CODE_REVIEW / PASS` 表示 `MSG-20260621-005` 指定范围通过代码、结构边界、失败语义、数据兼容、前端展示契约、测试和文档一致性审查，建议进入 scoped commit gate。

它不代表页面 QA PASS、真实商品 task run PASS、真实 VLM 质量验收 PASS 或外部平台验收 PASS。
