# FBM Pipeline Topic Tree

状态：协作主题树，持续维护
更新：2026-06-06 17:12 CST
Owner：若命（agentKey: `ruoming`）主控，所有身份可按事实补充

本文件用于记录项目讨论的大纲、目录、进展和未完话题，避免因为深入某个子话题而丢失其它待讨论事项。轻量跨会话消息写 `docs/collaboration/inbox.md`；复杂交接写 `docs/codex-handoff-YYYY-MM-DD-*.md` 并在 inbox 留链接。

## 使用规则

- 每次开启新主题，先在本文新增或更新节点。
- 每个节点必须标注状态：`OPEN`、`IN_PROGRESS`、`DONE_CLAIMED`、`REVIEWING`、`PASS`、`BLOCKED`、`PARKED`。
- 话题树不只记录讨论结论，也必须能沉淀成可分派任务；开放节点应尽量写清 owner、next action、deliverable、review owner。
- 施工者只能把节点标到 `DONE_CLAIMED`；`PASS` 只能由用户、若命主审、观止 QA 或任务明确指定验收身份给出。
- 不在本文粘贴真实密钥、批量真实 ASIN、完整商品敏感数据、导出文件内容。
- 涉及真实商品数据、人工类目、真实 ASIN、已生成素材、A+ 图片、Amazon 导入表格时，默认只读和小范围修改。
- 涉及 Step 10 / template mappings 时，必须同步维护 `docs/template-mapping-change-log.md` 并跑相关校验。

## 任务化规则

- 若命负责把已收敛的话题节点转成 inbox `REQUEST`，并指定收件身份、范围、边界、验收标准。
- 任务粒度应以能交付和能验收为准，避免一个 REQUEST 同时要求改后端、改页面、改运营规则和做 QA PASS。
- 任务字段最少包含：
  - `Owner`：执行或主责身份。
  - `Next action`：下一步要做什么。
  - `Deliverable`：交付物是代码、设计口径、QA 结论、运营复核还是 handoff。
  - `Reviewer`：谁给 REVIEW/PASS。
  - `Evidence`：期望基于哪些磁盘事实、命令输出、数据库事实、导出样例或页面行为验收。
- 讨论中尚未收敛的节点先保留 `OPEN` 或 `PARKED`，不强行派工。
- 一旦节点拆成任务，应在节点的 `Related inbox` 下追加对应 `MSG-*` 编号，避免后续找不到任务来源。

## 当前总原则

### TT-000 - 先稳任务中心，再动流程自动化

- Status: PASS
- Owner: 若命（agentKey: `ruoming`）
- Decision:
  - 先把任务中心做成可信地基，再继续增加流程自动推进。
  - 否则重复执行、状态漂移、重复导出、A+ 重复生成、库存/价格口径错位会被自动化放大。
- Scope:
  - 任务中心可靠性
  - 导出幂等
  - pause/resume 状态语义
  - 服务重启恢复
  - 后续自动化入口的领取/幂等规则
- Evidence:
  - `docs/codex-handoff-2026-06-05-export-rule-layer-and-workflow.md`
  - `backend/app/services/offline_tasks.py`
  - 用户已明确同意该原则。

## P0 当前主线

### TT-090 - 商品拉取到导出主链路闭环

- Status: REVIEWING
- Owner: 若命（agentKey: `ruoming`）主控
- Implementation owner: 听云（agentKey: `tingyun`）
- UX owner: 清秋（agentKey: `qingqiu`）
- QA owner: 观止（agentKey: `guanzhi`）
- Ops reviewer: 霜弦（agentKey: `shuangxian`）
- Related inbox:
  - `MSG-20260605-029 - DONE_CLAIMED` 听云：商品 pipeline 中断恢复修复
  - `MSG-20260605-033 - REVIEW` 观止：商品 pipeline 恢复策略 PASS
  - `MSG-20260605-032 - REQUEST` 清秋给听云：主链路页面体验问题
  - `MSG-20260605-034 - REQUEST` 若命给听云：导出中心任务工作台口径落地
  - `MSG-20260605-037 - STATUS` 若命：导出任务结构化结果模型
  - `MSG-20260605-039 - STATUS` 若命：暂停多店铺 ASIN 和 A+，聚焦主链路
  - `MSG-20260605-041 - REQUEST` 给观止：主链路端到端 QA 验收路径
  - `MSG-20260605-048 - STATUS` 若命：P0 主链路正式任务包
  - `MSG-20260605-049 - REQUEST` 给听云：P0 主链路工程收口
  - `MSG-20260605-050 - REQUEST` 给清秋：P0 主链路体验/状态复核
  - `MSG-20260605-051 - REQUEST` 给观止：P0 主链路 QA gate
  - `MSG-20260605-052 - REQUEST` 给霜弦：P0 主链路运营口径复核
  - `MSG-20260605-057 - DONE_CLAIMED` 听云：P0/P1 页面和导出规则修复
  - `MSG-20260606-001 - STATUS` 若命：进入复验阶段
- Goal:
  - 先保证从商品拉取到商品导出的主链路完整、合理、稳定、可用。
- Scope:
  - GIGA/OpenAPI 商品拉取和任务记录。
  - 商品详情页不卡首屏，用户能处理选图、搜索/选择竞品、抓竞品详情。
  - 类目来源归属选竞品/抓竞品详情链路。
  - Listing/图片分析完成后，商品进入待导出/导出中心的路径清晰。
  - 导出中心允许人工创建导出任务，不做商品资格总 gate。
  - 导出任务结果结构化，成功/跳过/失败/部分失败可解释、可下载、可追溯。
- Out of scope now:
  - 真实 ASIN 与多 Amazon 店铺模型。
  - A+ 生成、A+ fallback、A+ 上传链路。
  - 新增流程自动化。
  - 大规模 Step 10 映射/模板迁移。
- Verification target:
  - 使用测试环境完整走一条从拉取商品到导出任务完成/部分失败的路径。
  - 页面和任务结果都能解释每一步状态，不出现“后台其实停了但页面还在等”的漂移。
  - 导出任务无重复 zip 副作用，旧文件留档，新任务新文件。
  - 失败或跳过不靠口头解释，必须进入任务 result 或导出报告。
- QA checklist:
  - 商品拉取任务可创建、可查看任务记录，失败/中断有明确归宿。
  - 商品列表和商品详情可进入处理路径，详情页不因竞品候选等非首屏请求卡死。
  - 用户可完成或复核选图、搜索候选竞品、选择竞品、抓取竞品详情。
  - 类目能从选中竞品/抓取详情链路落到商品资料和待导出记录。
  - Listing/图片分析完成后，商品进入待导出/导出中心路径清晰。
  - 导出中心可人工创建导出任务；已导出但无真实 ASIN 的商品可再次新建导出任务。
  - 导出任务同 task/step 幂等，不重复生成同一任务 zip。
  - 导出任务 `result_json.rows` 能解释逐商品 `exported/skipped/failed`，`partial_failed` 有 zip 时可下载，全失败也有结构化原因。
  - 任务中心和导出中心对同一任务状态、下载入口、失败/跳过原因表达一致。

### TT-095 - Raw Data 到 Product 草稿转换设计复核

- Status: OPEN
- Owner: 若命（agentKey: `ruoming`）
- Related topic:
  - `TT-090 - 商品拉取到导出主链路闭环`
- Related inbox:
  - `MSG-20260605-049 - REQUEST` 给听云：raw/source -> Product 草稿转换工程收口
- Related files:
  - `backend/app/services/giga_openapi.py`
  - `backend/app/services/stylesnap_product_tasks.py`
  - `backend/app/services/product_duplicates.py`
  - `backend/app/models/models.py`
  - `backend/app/api/giga.py`
  - `backend/app/api/products.py`
  - `docs/item-workbench-redesign-plan.md`
- Current finding:
  - 设计方向基本合理：GIGA raw/source 层按 batch/site/data_source_id 保存来源事实，Product 是工作台对象，CatalogProduct 是待导出对象。
  - 当前实现把 `GigaItem/GigaSku/GigaRawSkuDetail/GigaPrice/GigaInventory/GigaProductImage` 转成 Product 草稿，保留 `gigab2b_raw_snapshot` 作为来源追溯。
  - 数据库聚合事实：`products=420`、`product_data=420`、`catalog_products=313`、`giga_items=516`、`giga_skus=1082`、`giga_raw_sku_details=1178`；说明 Product 草稿和待导出 CatalogProduct 不是一一自动等同。
- Risks:
  - Product 草稿缺少显式 `source_batch_id/source_data_source_id/source_item_id` 字段，主要依赖 JSON snapshot 和模糊 duplicate 查询。
  - Upsert 会刷新价格、库存、variants、图片候选等动态字段，但对 title/features/description 等采用“已有值优先”，需要明确哪些字段是来源事实、哪些是人工/生成产物。
  - Raw -> Product 的错误和跳过原因目前主要在 draft sync result，缺少逐 item 结构化可视化。
  - `skip_existing=True` 按 SKU 跳过已有 SKU，可能导致已有 Item 的新关联 SKU/变体补充不明显；适合增量，但不适合完整刷新。
- Next discussion:
  - 是否为 Product 增加稳定来源索引字段，还是先把 `gigab2b_raw_snapshot` 的结构和校验规范化。
  - raw/source 到 Product 草稿的字段覆盖策略需要形成白名单。

### TT-100 - 任务中心稳定性和可靠性

- Status: PASS
- Primary owner: 听云（agentKey: `tingyun`）
- Review owner: 观止（agentKey: `guanzhi`）
- Product boundary: 若命（agentKey: `ruoming`）
- Related inbox:
  - `MSG-20260605-004 - REQUEST` 给听云
  - `MSG-20260605-007 - REQUEST` 给观止
  - `MSG-20260605-018 - REVIEW` 观止 PASS 当前最小工程修复范围
- Related files:
  - `backend/app/services/offline_tasks.py`
  - `backend/app/api/offline_tasks.py`
  - `backend/app/models/models.py`
  - `backend/app/database.py`
  - `backend/app/main.py`
  - `frontend/src/pages/OfflineTaskCenter.tsx`
  - `scripts/test_project_rules.py`
- Hard rules:
  - 一个 step 只能被一个执行者领取，不能只靠内存 dict。
  - 已 `done` 的 step 永不自动重跑。
  - 导出 step 已成功并有结果时，再次执行只能复用结果，不能生成第二个 zip。
  - 服务重启后 `running` 不能永久挂着；必须可解释为自动安全恢复或 `interrupted` 待人工处理。
  - `paused` 表示不会继续启动后续未执行动作，不能假装已经开始的外部副作用没发生。
- Open questions:
  - 自动恢复是否只恢复无副作用 step？导出/A+ 是否一律依赖幂等 guard 后再允许恢复？
  - 是否需要新增 `claim_token` / `attempt_count` / `claimed_at` 字段，还是先用 status 条件原子 `UPDATE`？
  - pause 时 running step 标 `paused` 还是 `interrupted` 更符合事实？
- Verification target:
  - 重复调度同一任务不会重复执行同一步。
  - 服务重启后 running 状态有明确归宿。
  - 导出任务重跑不生成第二个 zip。
  - pause/resume 不把 done step 拉回 pending。
- Residual risk:
  - PASS 只覆盖当前最小可靠性修复范围，不代表历史重复 zip 风险已关闭。
  - 外部 API 阻塞中的 pause/resume 即时中断语义仍需后续按实际问题处理。

### TT-110 - 导出文件链路完善

- Status: REVIEWING
- Primary owner: 听云（agentKey: `tingyun`）
- Review owners:
  - 观止（agentKey: `guanzhi`）：QA gate
  - 霜弦（agentKey: `shuangxian`）：Amazon/运营口径
- Product boundary: 若命（agentKey: `ruoming`）
- Related inbox:
  - `MSG-20260605-016 - REQUEST` 给听云
  - `MSG-20260605-034 - REQUEST` 给听云：导出任务创建/执行结果/入口按任务工作台口径修正
  - `MSG-20260605-049 - REQUEST` 给听云：导出任务结构化结果和入口收口
  - `MSG-20260605-051 - REQUEST` 给观止：导出链路 QA gate
  - `MSG-20260605-052 - REQUEST` 给霜弦：导出运营口径复核
  - `MSG-20260605-057 - DONE_CLAIMED` 听云：已导出商品可新建导出任务、真实 ASIN/活跃任务保护、任务中心/导出中心展示修正
  - `MSG-20260606-001 - STATUS` 若命：等待清秋/观止/霜弦复验
- Related files:
  - `backend/app/services/offline_tasks.py`
  - `backend/app/api/offline_tasks.py`
  - `backend/app/api/products.py`
  - `frontend/src/pages/CatalogList.tsx`
  - `frontend/src/pages/OfflineTaskCenter.tsx`
  - `backend/app/pipeline/amazon_export/`
- User direction:
  - 听云可以先继续完善导出文件相关问题，并根据实际情况判断优先修哪些点。
  - 当前为测试环境，允许创建/操作测试数据、测试任务、测试导出文件。
  - 当前仍在调试导出文件质量，同一商品即使已导出，也允许用户人工再创建一个新的导出任务和新文件。
- Confirmed rule:
  - 任务幂等：同一个 `offline_task` / 同一个 step 不能重复执行；成功复用结果，失败留失败。
  - 商品可再次人工导出：调试期同一商品只要没有真实 ASIN，可以由用户人工创建新的导出任务。
  - 文件产物留档：每次新任务生成新文件，旧任务和旧文件保留，不覆盖、不强制重生旧任务。
  - 防重复的目标是“同任务重复执行”和“活跃任务并发冲突”，不是“同商品永远只能导出一次”。
- Scope candidates:
  - 导出任务重复生成 zip 的幂等保护。
  - 导出结果 `file_path` / `oss_object_key` / `oss_url` 的一致性和可下载性。
  - 本地缓存缺失时从 OSS 下载的恢复路径。
  - 已导出商品可再次人工新建导出任务；库存 0、真实 ASIN、模板异常等不做商品维度总 gate，而是在导出任务结果/报告中表达。
  - 导出中心和任务中心对同一导出任务状态/下载入口的展示一致性。
- Result model:
  - `result_json` 至少包含：`status`、`requested_count`、`success_count`、`skipped_count`、`failed_count`、`filename`、`file_path`、`oss_object_key`、`oss_url`、`report_filename`、`created_at`、`rows`。
  - `rows[]` 至少包含：`catalog_id`、`product_id`、`item_code`、`category`、`status`、`reason`、`template_file`、`output_file`。
  - 行状态建议稳定为 `exported / skipped / failed`，页面再映射中文。
  - 全部成功为 `done`；有成功也有跳过/失败为 `partial_failed` 且可下载；全部无成功产物为 `failed`，但仍需保留逐商品原因。
- Boundaries:
  - 不打印 `.env` 密钥。
  - 不做无关批量清空、批量覆盖或不可逆破坏。
  - 不修改 Step 10 mapping 或模板文件，除非实际问题明确落在映射/模板；若涉及必须同步维护 `docs/template-mapping-change-log.md` 并跑校验。
- Verification target:
  - 测试导出任务能生成可下载结果。
  - 已导出但没有真实 ASIN 的测试商品，可以再次人工创建新导出任务；旧任务和旧文件保留。
  - 重复执行同一成功导出 step 不生成第二个 zip。
  - 导出报告能说明成功、跳过和失败原因。
  - 任务中心下载入口和导出中心状态一致。

### TT-120 - 全库商品 Excel 导出

- Status: IN_PROGRESS
- Owner: 若命（agentKey: `ruoming`）主控
- Execution owner: 清秋（agentKey: `qingqiu`）页面主操
- Support owner: 听云（agentKey: `tingyun`）技术待命
- QA owner: 观止（agentKey: `guanzhi`）
- Ops reviewer: 霜弦（agentKey: `shuangxian`）
- Related topic:
  - `TT-090 - 商品拉取到导出主链路闭环`
  - `TT-110 - 导出文件链路完善`
  - `TT-210 - 导出与 Amazon 运营口径`
- Related inbox:
  - `MSG-20260606-002 - REQUEST` 若命：全库商品 Excel 导出
  - `MSG-20260606-003 - REQUEST` 若命：改为必须通过页面操作完成，禁止直接接口创建任务
- User request:
  - 2026-06-06 17:10 CST：用户表示可以进入下一步，把库里所有商品导出到 Excel，并要求若命安排协作身份执行。
  - 2026-06-06 17:12 CST：用户明确该任务必须通过操作页面完成，不能直接调用接口。
- Interpretation:
  - 当前按 Amazon 首次导入表 Excel/zip 导出任务理解；如实际需求是普通商品清单 Excel，执行者需先 `BLOCKED` 回问。
- Goal:
  - 创建新的全量导出任务，覆盖当前库里的全部可导出商品，生成新的 Excel/zip 产物和报告。
  - 旧任务、旧文件和既有导出事实保留，不覆盖、不强制重生旧任务。
- Execution rule:
  - 清秋必须从本地前端页面，优先 `/export-center`，通过页面现有筛选、选择、导出按钮或“当前筛选/全部待导出”行为创建任务。
  - 不允许直接调用创建导出任务 API、跑脚本、写数据库或调用后端函数绕过页面。
  - 如果页面没有“全库所有商品”可操作入口，应先 `BLOCKED`，由若命决定是补 UI 还是调整需求。
- Boundaries:
  - 已有真实 Amazon ASIN 的商品不能生成首次导入表；应在任务结果中跳过并说明原因。
  - 库存 0、模板缺失/停用、字段异常、类目无覆盖等进入 `result_json.rows` 和导出报告。
  - 不修改 Step 10、template mappings 或模板文件；若导出失败落在映射/模板，先 `BLOCKED` 并确认 change log 和校验要求。
  - 不打印密钥，不粘贴批量真实商品敏感数据或真实 ASIN。
- Verification target:
  - 清秋给出页面操作截图、筛选/选择范围、任务 id、请求商品数、成功/跳过/失败数量、文件/报告路径或下载入口。
  - 观止基于任务记录、接口/数据库事实、下载入口和报告验收；如遇页面证据不足、任务状态不一致、下载入口不可用、报告无法解释原因或环境阻塞，必须及时反馈若命调度，不能自行绕过页面或默认接受。
  - 霜弦复核运营口径是否符合真实 ASIN、库存、模板、字段和类目边界。
- Blocker watch:
  - 若当前大型 GIGA 图片下载任务占用后端 worker，需先确认是否会干扰全量导出；无法安全执行则标 `BLOCKED`。

## P1 并行口径

### TT-400 - 已跑完全流程的测试环境操作型验收

- Status: OPEN
- Primary owners:
  - 霜弦（agentKey: `shuangxian`）：运营口径复核
  - 观止（agentKey: `guanzhi`）：QA gate 和证据复核
- Product boundary: 若命（agentKey: `ruoming`）
- Related handoff:
  - `docs/codex-handoff-2026-06-05-export-rule-layer-and-workflow.md`
- Current fact:
  - 之前已经用 5 个商品跑过从商品工作台到导出中心的完整流程。
  - 生成过 Task 9 和 Task 10；其中 4 个商品已导出，1 个因最新 GIGA 库存 0 跳过。
  - 当时手工调用和后台自动执行重叠，产生过未引用的本地重复 zip；数据库最终已修正到干净结果，但暴露任务执行可靠性问题。
- Scope:
  - 在测试环境中复核已跑完整流程的证据、状态、导出结果和风险。
  - 允许创建或操作测试数据、测试任务、测试导出文件来完成验收。
  - 操作型验证必须尽量使用明确标记的测试批次/测试商品/测试导出，避免混入既有人工运营数据。
  - 不打印 `.env` 密钥，不做无关的批量清空、批量覆盖或不可逆破坏。
  - 不把“流程跑通”直接等同于“可运营 PASS”。
- Verification target:
  - 观止复核：可通过测试环境操作验证任务记录、导出记录、失败/跳过原因、页面/接口状态是否能支撑验收结论。
  - 霜弦复核：可通过测试环境操作验证库存 0 跳过、真实 ASIN 禁止重复导出、导出模板按类目/模板文件选择、A+ 不参与主流程等运营口径是否合理。
- Output:
  - 在 inbox 写 `REVIEW`，结论为 `PASS / NEEDS_FIX / BLOCKED` 之一，并列证据。

### TT-200 - 状态树与用户路径表达

- Status: REVIEWING
- Primary owner: 清秋（agentKey: `qingqiu`）
- Product boundary: 若命（agentKey: `ruoming`）
- Related inbox:
  - `MSG-20260605-005 - REQUEST` 给清秋
  - `MSG-20260605-032 - REQUEST` 清秋给听云：页面体验巡检和 UI 修正
  - `MSG-20260605-034 - REQUEST` 若命给听云：导出任务工作台口径落地
  - `MSG-20260605-050 - REQUEST` 给清秋：P0 主链路体验/状态复核
  - `MSG-20260605-057 - DONE_CLAIMED` 听云：页面体验问题修复声明
  - `MSG-20260606-001 - STATUS` 若命：等待页面复验
- Related files:
  - `frontend/src/pages/ProductList.tsx`
  - `frontend/src/pages/ProductDetail.tsx`
  - `frontend/src/pages/OfflineTaskCenter.tsx`
  - `frontend/src/pages/CatalogList.tsx`
  - `docs/item-workbench-redesign-plan.md`
  - `docs/codex-handoff-2026-06-05-export-rule-layer-and-workflow.md`
- Current problem:
  - 状态含义分散在 `products.status`、`catalog_products.confirmed_at/exported_at`、`offline_tasks.status`。
  - 用户需要看懂：运行中、中断、挂起、部分失败、待导出、已导出。
- Current decisions:
  - 不做“导出过期”状态；导出文件生成后就是历史产物，保留即可。
  - 不自动启动导出文件生成任务；导出文件生成由用户在导出中心人工触发。
  - “已导出”表示已有历史文件和下载入口，不表示该商品永久禁止再次创建新导出任务。
  - 导出中心状态和动作应同时表达：历史结果可查、当前任务可追踪、无真实 ASIN 时可再次人工新建导出任务。
  - 导出中心状态主轴应是任务维度，不新增商品维度的“资格状态矩阵”；失败、部分失败、跳过原因沉淀到导出任务结果和报告。
  - 历史产物只用于文件下载和追溯，不决定商品是否可以新建导出任务。
- Open questions:
  - 商品工作台和导出中心如何避免互相抢主路径？
  - 任务中心是否需要展示“可安全重跑 / 不建议重跑 / 只可下载结果”？

### TT-210 - 导出与 Amazon 运营口径

- Status: OPEN
- Primary owner: 霜弦（agentKey: `shuangxian`）
- Product boundary: 若命（agentKey: `ruoming`）
- Related inbox:
  - `MSG-20260605-006 - REQUEST` 给霜弦
  - `MSG-20260605-035 - REQUEST` 给霜弦：多店铺多 ASIN、库存补货、价格/库存更新模板运营口径复核
  - `MSG-20260605-052 - REQUEST` 给霜弦：P0 主链路运营口径复核
- Related files:
  - `docs/template-mapping-spec.md`
  - `docs/add-category-template-sop.md`
  - `docs/template-mapping-change-log.md`
  - `backend/app/pipeline/step10_amazon_template.py`
  - `backend/app/pipeline/amazon_export/`
  - `backend/app/services/offline_tasks.py`
- Current decisions:
  - 已有真实 ASIN 的商品不能再次导出 Amazon 导入表格。
  - Step 10 / template mappings 改动必须维护 change log。
  - 导出中心按模板文件维度拆任务。
  - 不做导出过期；已生成导出文件作为历史文件保留。
  - 不自动生成导出文件；导出任务必须由用户人工触发。
  - 不做强制重新生成；导出任务结束就是结束，失败就是失败。
  - 如需重新尝试，用户新建一个导出任务，不在原任务上强制重生。
  - 当前调试阶段允许同一商品重复人工导出，每次都是新任务、新文件、旧文件留档。
  - 已有真实 ASIN 的商品仍禁止再次生成 Amazon 首次导入表格。
  - 库存今天为 0 不阻断铺货主流程；导出执行时如遇最新库存 0，则在导出报告写跳过原因。
  - 商品 Amazon 类目归属选竞品/抓竞品详情链路；导出中心不承担常规类目确定。
  - 一个商品可能铺到多个 Amazon 店铺并产生多个 ASIN；多店铺 ASIN 关系后续可能需要店铺维度模型支持。
- Code facts:
  - `backend/app/pipeline/step4_category.py`：基于 `product.competitor_asin` 抓 Amazon 类目并写 `ProductData.categories/leaf_category`。
  - `backend/app/api/amazon_stylesnap.py`：选择候选竞品后 `_sync_product_competitor_snapshot()` 从竞品详情或候选信息同步类目到 `ProductData` 和 `CatalogProduct`。
  - `backend/app/api/products.py`：`build_catalog_export_zip()` 已按商品写报告，真实 ASIN、模板异常等进入跳过/原因。
- Open questions:
  - 已导出但库存/价格变化时，是重新导入表格还是走库存/价格更新模板？
  - 多店铺多 ASIN 模型如何设计，避免用商品级 `amazon_asin` 锁死未来店铺铺货。
  - 多模板覆盖同一类目时，运营默认选择规则是否需要固化？

### TT-220 - A+ 生成和 fallback 边界

- Status: PARKED
- Primary owner: 霜弦（agentKey: `shuangxian`）
- Implementation owner: 待定，通常为听云（agentKey: `tingyun`）
- Related files:
  - `backend/app/pipeline/step7_aplus_plan.py`
  - `backend/app/pipeline/step8_aplus_script.py`
  - `backend/app/pipeline/step9_aplus_image.py`
  - `backend/app/services/offline_tasks.py`
  - `frontend/src/pages/AplusManagement.tsx`
  - `frontend/src/pages/ProductDetail.tsx`
- Current decisions:
  - A+ 不参与当前主流程。
  - 只有待导出/已导出的商品可以操作生成 A+。
  - A+ 没有真实生成时不要 mock 冒充真实结果。
- Open questions:
  - fallback plan/script/image 是否只能作为失败诊断，不允许进入上传链路？
  - A+ 重新生成是否也要纳入任务中心统一执行？
  - A+ 生成完成后是否影响导出状态，还是独立运营链路？
- Parking reason:
  - 用户明确当前先保证商品拉取到商品导出的主链路，A+ 生成下一阶段再讨论。

## P2 后续结构化改造

### TT-300 - 商品 workflow_status 与 export_status 拆分

- Status: PARKED
- Owner: 若命（agentKey: `ruoming`）先定边界，听云后续实现
- Related files:
  - `docs/item-workbench-redesign-plan.md`
  - `backend/app/models/models.py`
  - `backend/app/api/products.py`
  - `frontend/src/pages/ProductList.tsx`
  - `frontend/src/pages/CatalogList.tsx`
- Current issue:
  - 第一阶段复用 `products.status` 和 `current_step` 映射业务状态。
  - 后续如需拆状态，只需要区分商品生产状态和导出记录/导出可用性；不引入“导出过期”状态。
- Blocker:
  - 先完成 TT-100 任务中心稳定性。

### TT-310 - 后台 worker 与自动推进

- Status: PARKED
- Owner: 若命（agentKey: `ruoming`）先定规则，听云后续实现
- Related files:
  - `docs/item-workbench-redesign-plan.md`
  - `backend/app/pipeline/engine.py`
  - `backend/app/services/offline_tasks.py`
- Current decision:
  - 先不继续增加新的自动推进。
  - 自动 worker 必须先有领取/幂等/状态保护。
  - 导出文件生成不纳入自动推进；必须人工触发。
- Candidate automatic nodes:
  - 已确认图片后搜索候选竞品。
  - 已选竞品后抓取竞品详情。
  - 前置满足后生成 Listing。
  - 批量 A+ 生成。
- Blocker:
  - 先完成 TT-100。

### TT-320 - 测试体系补强

- Status: OPEN
- Owner: 听云（agentKey: `tingyun`）实现，观止（agentKey: `guanzhi`）复核
- Related files:
  - `Makefile`
  - `scripts/test_project_rules.py`
  - 待新增的专项测试脚本或测试目录
- Current state:
  - 目前主要有模板映射校验、项目规则脚本、后端 compile、前端 build。
  - 缺少 API/状态机/任务执行单测。
- Target coverage:
  - offline task claim
  - restart recovery
  - export idempotency
  - pause/resume
  - switching competitor invalidates downstream state

## Parking Lot

### TT-900 - 文档口径清理

- Status: OPEN
- Owner: 若命（agentKey: `ruoming`）主控，听云可协助
- Related inbox:
  - `MSG-20260605-043 - STATUS` 若命：文档补全身份分工
  - `MSG-20260605-044 - REQUEST` 给听云：工程事实文档
  - `MSG-20260605-045 - REQUEST` 给清秋：页面路径和状态语言
  - `MSG-20260605-046 - REQUEST` 给观止：主链路 QA/验收文档
  - `MSG-20260605-047 - REQUEST` 给霜弦：GIGA/Amazon/库存/价格/类目运营口径
- Scope:
  - 清理旧文档中 Step7-10 主流程、A+ 待复核、Step10 自动导出等历史口径。
  - 保持冷启动文档、runbook、item workbench 计划、handoff 的说法一致。
- Responsibility matrix:
  - 若命：`docs/collaboration/topic-tree.md`、`docs/collaboration/inbox.md`、`docs/codex-cold-start.md` 的当前优先级和协作边界。
  - 听云：`docs/01-架构设计.md`、`docs/04-Pipeline步骤详解.md`、`docs/runbook.md`、`docs/superpowers/specs/2026-06-03-offline-task-center.md` 的工程事实、任务中心、raw -> Product、导出 result 模型。
  - 清秋：`docs/item-workbench-redesign-plan.md`、`docs/runbook.md` 或新增用户路径文档中的页面主路径、状态语言、空/错/等待态。
  - 观止：主链路 QA checklist、验收证据要求、PASS/NEEDS_FIX/BLOCKED 标准。
  - 霜弦：`docs/giga-inventory-sync.md`、`docs/template-mapping-spec.md`、`docs/add-category-template-sop.md`、`docs/runbook.md` 中的 GIGA/Amazon/库存/价格/类目/模板运营口径。

### TT-910 - 导出规则层第二阶段

- Status: PARKED
- Owner: 听云（agentKey: `tingyun`），霜弦（agentKey: `shuangxian`）复核运营口径
- Scope:
  - 继续从 `step10_amazon_template.py` 迁移 legacy helper 到 `amazon_export` 子模块。
  - 每迁一批跑 5 模板族样例生成。
- Blocker:
  - 先完成任务中心可靠性，不同时大改导出规则层。

### TT-920 - GIGA / 店铺 / SKU 主键关系

- Status: PARKED
- Owner: 霜弦（agentKey: `shuangxian`）口径，听云（agentKey: `tingyun`）实现
- Related inbox:
  - `MSG-20260605-035 - REQUEST` 给霜弦
- Scope:
  - 后续关联 SKU 不应只靠 `sku_code + data_source_id`，尽量通过主键关系关联，避免不同店铺同 SKU code 混淆。
  - 后续 Amazon ASIN 不应长期只挂在商品级；一个商品可能铺到多个 Amazon 店铺/站点并产生多个 ASIN，需要店铺/站点维度关系模型。
  - Amazon 首次导入模板和 PriceAndQuantity 库存/价格更新模板的边界需要随多店铺模型一起固化。
- Parking reason:
  - 用户明确先不讨论真实 ASIN 与多店铺关系，当前聚焦商品拉取到商品导出主链路。

## 最近进展

- 2026-06-05 18:30 CST：用户明确先不讨论真实 ASIN 与多店铺关系，也先不进入 A+；当前 P0 聚焦商品拉取到商品导出的主链路完整、稳定、可用。若命新增 `TT-090` 并写 `MSG-20260605-039`。
- 2026-06-05 17:50 CST：用户明确不需要“导出过期”；导出文件生成后保留即可，也不需要自动启动导出生成任务，导出由人工触发。
- 2026-06-05 17:55 CST：用户明确不需要强制重新生成导出文件；导出任务结束就是结束，失败就是失败，如需再做则新建任务。
- 2026-06-05 18:00 CST：用户修正导出口径：当前仍在调试导出文件质量，允许同一商品再次人工创建新的导出任务/新文件，不能要求每次换新数据；已有真实 ASIN 禁止仍保留。
- 2026-06-05 18:05 CST：用户确认三层规则：任务幂等、商品可再次人工导出、文件产物留档；若命在 `MSG-20260605-026` 固化该口径。
- 2026-06-05 18:08 CST：用户要求话题树后续能根据讨论结论给对应身份建任务；若命新增任务化规则。
- 2026-06-05 17:38 CST：观止在 `MSG-20260605-018` 对 `TT-100` 当前最小工程修复范围给出 PASS；历史重复 zip 风险仍留给 `TT-110` 验收。
- 2026-06-05 17:45 CST：用户明确这是测试环境，允许霜弦和观止做操作型验收；若命将 `TT-400` 从只读验收调整为测试环境操作型验收。
- 2026-06-05 17:45 CST：用户同意听云可先继续完善导出文件问题，由听云根据实际情况判断优先级；若命新增 `TT-110 - 导出文件链路完善`。
- 2026-06-05 17:40 CST：用户补充之前完整流程已经跑完，若命新增 `TT-400 - 已跑完全流程的测试环境操作型验收`，并在 inbox 发出：
  - `MSG-20260605-009` 给霜弦做运营口径复核
  - `MSG-20260605-010` 给观止做 QA gate 复核
- 2026-06-05 17:22 CST：若命在 `docs/collaboration/inbox.md` 写入任务中心稳定性相关分工 REQUEST：
  - `MSG-20260605-004` 给听云
  - `MSG-20260605-005` 给清秋
  - `MSG-20260605-006` 给霜弦
  - `MSG-20260605-007` 给观止
- 2026-06-05 17:30 CST：用户确认需要主题树/大纲/目录/进展记录机制；新增本文。
