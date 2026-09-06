# Domain Index: Product Flow

## 范围

- 商品列表、商品详情、图片选择、竞品选择、商品状态流转。
- Amazon/TikTok 商品详情页分流。
- 商品进入导出或平台铺货前的人工确认节点。

## 当前口径

- 商品列表可以按数据源/店铺过滤。
- Amazon 与 TikTok 商品详情页应分流；详情页状态、操作、类目和导出链路不能混用。
- TikTok 有强类目约束；Amazon 当前以模板/导出链路为主。
- 旧主流程中图片、竞品、类目、ASIN、导出等人工确认节点不能自动推进；自动选图/自动竞品选择的新目标流程见 `docs/superpowers/specs/2026-06-19-amazon-auto-image-competitor-selection-prd.md`。执行设计已拆为 `docs/superpowers/specs/2026-06-19-amazon-auto-image-selection-prd.md` 和 `docs/superpowers/specs/2026-06-19-amazon-auto-competitor-selection-prd.md`，将图片选择和竞品选择改为系统自动异步节点，人工页面降级为失败/低置信度/主动纠偏入口。
- 前端不应重新实现后端业务规则。
- `GET /api/products/{id}` 商品详情必须是只读接口；素材目录只能扫描汇总，不能移动、创建、删除、重命名或改写用户素材文件。
- 商品状态只表达业务节点和业务结果，不表达任务执行细节；Amazon 主流程最终 PRD 以 `docs/superpowers/specs/2026-06-18-amazon-product-workflow-prd.md` 为准。
- Amazon workflow T1 已进入结构层：`products.workflow_node/workflow_status/workflow_error/workflow_updated_at` 和集中枚举常量定义在后端模型/状态常量中；后续投影和写入统一入口仍按 PRD 分阶段推进。
- Amazon workflow T2 的 Product Workflow Service 位于 `backend/app/product_tasks/workflow.py`：集中提供 `set_product_workflow()`、`build_product_workflow()` 和 node/action 映射；商品列表/详情 workflow 投影应同源调用该 service。
- Amazon 商品详情页 `frontend/src/pages/ProductDetail.tsx` 的主 stepper、状态提示、默认 tab、轮询判断和主动作区域必须优先消费 `product.workflow` / `work_status` / `allowed_actions`；旧 `status/current_step`、图片/竞品/Listing 内容推断只能在没有 workflow 时作为 legacy fallback，不能覆盖 API/list/overview 的 workflow 事实。
- ProductWorkStatus registry 位于 `backend/app/product_tasks/work_status.py`，是商品工作台状态 key、展示元信息、overview 归属、是否可列表筛选、DB predicate 绑定名和事实源说明的后端领域事实源。`workflow.py` 生产端必须引用 registry key；`backend/app/api/products.py` 的 `WORKBENCH_STATUS_KEYS` / `PRODUCT_LIST_WORK_STATUS_KEYS` 必须从 registry 派生；前端 `WorkStatus` / meta / filter 仍手写但由 `scripts/test_project_rules.py` 与 registry 和 producer outputs 做反向闭包校验。`interrupted` / `suspended` / `manual_review` 是 legacy diagnostic row fallback，不再属于正式 ProductWorkStatus，也不再作为 `work_status` 列表筛选项。
- 空 workflow 字段投影为 `needs_initialization` 正式工作状态；后端 overview/list/filter/schema 和前端工作台类型、元信息、筛选入口都必须接住该状态，不得回退到旧 `status/current_step` 猜成图片确认等其它桶。
- Amazon workflow T3：旧人工图片确认入口仍由 `PUT /api/products/{id}/listing-images` 保存主图/副图并执行 destructive reset，成功后进入 `search_competitor/pending`；该入口现在是自动选图失败/用户主动纠偏入口，保存前必须保护真实 ASIN、导出历史、Amazon 模板输出和 A+ 上传证据。
- GIGA 素材准备与 Amazon 自动选图：新建商品先进入 `prepare_materials/pending`，由 `product_material_prepare` 使用项目浏览器执行器按 Item Code 精确映射 GIGA 搜索结果和详情页数字 `product_id`，复制 Downloads 中的 ZIP、显式登记 `to_b/information/retail_ready`、解压并逐文件写入 `product_material_assets`。To B 必须包含可读图片；Information 表格/HTML/文本生成 `material_facts.json` 并进入用户心智证据目录，PDF/视频/图片至少具有安全预览和明确 `preview_only` 用途。素材完成后创建 `product_auto_image_selection`：先对全部 To B 候选图片做视觉分析，超过单页容量时生成多张 Contact Sheet，逐页分析后做一次全局合并，再严格证明全部图片等于 `1 MAIN + 最多 8 Gallery + rejected`。已选图片的视觉证据写入 `product_image_analysis`，全候选审核写入 `product_image_selection`，`ProductImage` 只保留路径、顺序与摘要热字段；后续用户心智、Listing 与 A+ 通过 payload repository 复用正文，不再对同一批图二次调用 VLM。成功写回 Contact Sheet 页码/标签和 downstream usage，再自动创建 `product_competitor_search`；不再停在 pending 等人工点击。远程候选仍保持 URL 优先，本地 To B 候选没有 URL 时保存受控本地路径。`POST /api/products/{id}/auto-image-selection/retry` 仍是失败/人工纠偏入口。
- 自动选图与 Step 6 的 01-09 图库共用转化顺序：01 必须是合规白底主图；02-04 优先三个信息不重复、构图/场景不同的好看实景；05 材质或做工细节；06 功能/使用；07 第二个不同的关键细节；08 最多一张其他全貌角度；09 有尺寸图时固定为尺寸/空间适配图。任一目标角色缺失时，以评分最高的非尺寸、非额外角度图片补位，仍以 9 图为目标。
- GIGA 拉品的“新增 SKU”以实际已创建的 `ProductData.item_code` 为准，GIGA 的 `giga_skus` 只是可复用的源数据缓存；删除商品后再次同步必须仍可从缓存/远端创建商品。同步入口跳转任务中心时固定定位刚创建的任务并使用 `view=all`，避免快速完成的任务从默认“当前任务”视图中看似消失。
- Amazon 自动竞品搜索 Phase A：`search_competitor/pending|failed` 可通过 `POST /api/products/{id}/competitor-search/retry` 创建/复用 `product_competitor_search` task run；reserve 投影 `search_competitor/processing`，成功把 Amazon 页面搜索候选写入 `amazon_competitor_search_candidates` 并进入 `visual_match_competitors/pending`，失败回到 `search_competitor/failed`。查询计划优先使用标题中的完整具体商品类型（例如 `over the toilet storage cabinet`、`platform bed frame`），再组合可购买规格和材质/颜色事实，仅在没有明确规格时才使用物理尺寸；不能让泛化的 `storage cabinet` 覆盖更具体的商品类型。多 query 候选按 rank 轮询合并，不能让前两个 query 提前耗尽候选池。`amazon_competitor_search_candidates` 是自动竞品搜索主事实源。本阶段不做视觉初筛、抓详情或自动选择竞品。
- Amazon 真实页面搜索 adapter S2：`backend/app/services/amazon_search_page.py` 默认仍 fail closed；只有 `AMAZON_SEARCH_PAGE_ADAPTER=chrome` 且 `AMAZON_SEARCH_ENABLE_REAL_BROWSER=true` 时才复用本机 macOS Google Chrome/AppleScript 控制器访问 Amazon 搜索页。真实 adapter 只读搜索页、分类外部阻塞、解析候选并写 evidence，不登录、不绕过验证码、不访问 Seller Central/A+/TikTok/导出上传。typed failure 包括 `adapter_not_configured`、`browser_unavailable`、`browser_permission_denied`、`navigation_timeout`、`login_required`、`captcha`、`bot_check`、`region_page`、`unsupported_page_structure`、`empty_results`、`parser_error`、`rate_limited`；fixture/parser 测试不得作为真实成功路径。evidence 归属为 `task_run_id/task_step_id/query_index`，默认目录为 `DATA_DIR/task_evidence/amazon_search_page`。搜索候选落库合并去重上限以 `AMAZON_SEARCH_MAX_CANDIDATES` 为事实源，默认 20。
- Amazon 竞品视觉初筛 Phase B：`visual_match_competitors/pending|failed` 可通过 `POST /api/products/{id}/competitor-visual-match/retry` 创建/复用 `product_competitor_visual_match` task run；`processing` 状态由 API 直接返回当前 workflow/task-center correlation，不调用 planner。reserve 会清空同商品旧视觉当前事实和 `visual_selected_for_capture`，execute 只读取最近成功 `product_competitor_search` run/step 的候选，默认用源商品主图 URL + 候选 `image_url` direct VLM 做视觉初筛，不下载候选图、不生成 Contact Sheet、不做拼接兜底；只在显式测试 fixture 路径使用 fake review。`visual_similarity` 表示同一买家的直接竞品可比性，不要求接近同款；品牌、标准尺寸、颜色和装饰差异进入分数但不单独 hard reject，配件、单独部件、错误商品类型和不完整商品仍 fail closed。成功给当前 run/step Top 4-6 写 `visual_selected_for_capture=1`，投影到 `capture_competitor_candidates`，并通过 success hook 创建/复用 `product_competitor_candidate_capture` task；失败/取消/中断回到 `visual_match_competitors/failed` 且不保留 current selected candidates。VLM/API/TLS/model failure 必须稳定成为 task failed + `visual_match_competitors/failed`，不能让 runner crash 或留下 stale processing。
- Amazon 候选详情抓取 / 自动选竞品 E4A：`capture_competitor_candidates` 已增加 `visual_task_run_id/visual_task_step_id` current-set evidence；视觉初筛 success 会给当前 Top 候选写入 visual task run/step，并把当前 visual run/step id 显式写入候选详情 task run/step payload 后创建/复用候选详情 task，避免同商品旧 succeeded visual run 抢占 current set。`backend/app/services/amazon_listing_detail.py` 默认仍 fail closed；仅当 `AMAZON_LISTING_DETAIL_ADAPTER=chrome` 且 `AMAZON_LISTING_DETAIL_ENABLE_REAL_BROWSER=true` 时，复用本机专用 Chrome worker tab 按 ASIN 访问真实详情页，逐候选写入绑定 task run/step、candidate 和 visual rank 的 evidence，不登录、不绕过验证码；五点只读取 `feature-bullets`，产品详情只读取 Amazon 产品概览/详情模块，不能把导航或保障计划文案混入下游。`validate()` / `execute_step()` 优先使用 payload 中的 visual ids，缺失时才兼容 fallback；`execute_step()` 只返回结构化候选详情结果、不写候选表；`on_step_success()` 单事务写 `detail_* / capture_*` current facts，并创建/复用 `product_auto_competitor_selection` task。`product_auto_competitor_selection` 后端以商品标题、类型、材质、颜色和类目等身份字段做 deterministic rule scoring，配件 hard reject 只看标题/类目身份证据，不让描述或保修中的 `parts/cover` 误伤；`execute_step()` 只返回评分结果，`on_step_success()` 重查 current set 和保护门后写 selected row `final_*`、`products.competitor_asin`、`catalog_products.competitor_asin` 和 snapshot selected competitor，并创建/复用 `product_keyword_research` task run；关键词成功后才创建图片分析任务。低置信度、事实不足、硬拒绝、保护门、取消或中断回到失败态且不清 search/visual/detail facts。公开详情 retry 入口仍未启用：pending 只在现有竞品搜索 API 前置允许时保留 `restart_competitor_search`；failed 不暴露 restart 或详情 retry，有 task correlation 时只允许任务中心/详情，无 correlation 时只允许详情；processing 用 `open_task_center`。
- 自动选竞品成功后，商品必须先进入 `keyword_research` 商品准备任务。该任务依次执行关键词反查（卖家精灵无结果才 LLM 兜底）、建议售价计算和 Amazon 类目匹配；关键词 LLM 兜底受 `STEP3_LLM_TIMEOUT_SECONDS` 限制，超时作为可恢复基础设施异常在 step 预算内自动重试。Step4 的 Chrome 类目读取受 `STEP4_CATEGORY_FETCH_TIMEOUT_SECONDS` 硬超时保护；失败或超时先使用已有类目/ride-on 模板，再仅在商品自身文本命中已登记模板的明确 marker 时使用该模板类目兜底，未命中仍人工复核，不能自由猜测类目。若 `value_total`/`estimated_total` 因 materialize 顺序缺失，会先且仅从该商品 `source_batch_id` 的同 SKU `GigaPrice` 记录恢复成本，找不到完整同批次证据仍 fail closed。只有 `ProductData.keywords_top`、`suggested_price` 和 `leaf_category` 都已落库，才创建图片分析任务。图片分析和 Listing 的前置校验也要求这三项输入，不能把问题拖到导出阶段。
- Amazon 图片分析 / 用户心智梳理 / Listing 生成：候选图片视觉分析在自动选图前已完成，关键词、定价和类目完成后直接创建或复用 `product_customer_mindset` run，不得直接创建 Listing 或重复调用图片分析。心智任务基于商品事实、关键词、当前选中竞品和 `ProductImage.image_analysis` 回答 13 个固定核心问题，并按商品证据生成 2 至 5 个商品特有动态问题，总计 15 至 18 题；只有该产物落库后才创建或复用 `product_listing_generation`。Listing 与 A+规划消费同一简报。Listing success 仅进入 `pending_review + generate_aplus/pending`，并创建/复用 A+ 任务；A+ 五张图成功后才进入 `confirm_images_aplus/pending` / 商品列表“待确认图片与 A+”。详情页必须人工确认 Listing 图片和 A+，确认接口再写 `flow_done/succeeded`、`Product.status=completed` 与 `CatalogProduct.confirmed_at`，商品才显示 `export_ready/待导出` 并可导出 Excel。A+ 失败维持不可导出状态；已确认或导出的商品手动重生 A+ 不得回退其导出资格。
- 今日自动主链路目标见 `docs/superpowers/specs/2026-06-21-amazon-auto-flow-to-export-ready-prd.md`：从 GIGA 商品入库/分组自动推进到 A+ 完成后的人工确认；不包含自动导出、Amazon 上传或外部平台发布。
- A+ 自动触发在 `ProductListingGenerationAction.on_step_success()` 写入 `generate_aplus/pending` 后，按 `AUTO_APLUS_AFTER_EXPORT_READY=true` best-effort 创建/复用 `aplus_generate` task；配置关闭时商品停留在 A+ 生图等待状态，不获得导出资格。
- A+ Step7 默认仍走旧 `standard_header_image_text_v1` 五张横幅范式。`backend/app/pipeline/aplus_narrative_diagnosis.py` 是命名的商品叙事诊断阶段，定义 prompt/schema、归一化和保守兜底；Step7 作为兼容规划入口调用该阶段，并要求 LLM plan 输出顶层 `product_narrative_diagnosis`，包括购买动机、使用场景、主要疑虑、证据强度/缺口、差异化角度、各横幅叙事任务和禁用 claim。普通 A+ 每个模块还由 Step7 从真实候选中指定 `primary_reference_image_id` / `secondary_reference_image_id`、选择理由和各自用途；Step8 必须优先保留该业务选择并验证路径与高风险标记，只有缺失、失效或高风险时才按模块角色评分兜底，同时保存 `reference_selection_audit`。Step7/8 的长 JSON 输出分别使用 `APLUS_PLAN_LLM_TIMEOUT_SECONDS` / `APLUS_SCRIPT_LLM_TIMEOUT_SECONDS`，避免短超时误触发 fallback。Step8 继续把诊断连同五个模块一起传给脚本 LLM，并让每张横幅说明如何使用诊断，避免生成可套任意商品的泛化 A+ 图。
- 单商品 `pipeline_target=aplus_done` 会在 export-ready 后继续 A+ 派生链路。Step6 对已选本地/远程图片保持逐图 URL/data-URL 直传、fail-closed，不下载远程图或切换 Contact Sheet 兜底；高分辨率图片按 `STEP6_VLM_BATCH_SIZE` 小批次提交，并用 `STEP6_VLM_TIMEOUT_SECONDS` 给真实多模态推理保留足够时间。自动选图写 `image_selling_points`、`gallery_selection` 和 `aplus_planner_input`；Step7 写并注册 `aplus_image_plan.json/.md`；Step8 写并注册 `gpt_image_scripts.json/.md`，并把真实参考图反写为素材用途 `aplus_reference`。普通 A+ 必须恰好有 5 个位置 1-5 的脚本且每份至少有一张参考图。Step9 固定使用支持参考图的 T8Star/OpenAI-compatible `images/generations` 通道与 `97:60` 比例，当前实测生成 `3104x1920` 母图后等比缩小为精确 `1940x1200`；不再 high→auto 或 generations→edits 自动降级。本机未显式配置 `GPT_IMAGE_API_KEY` 时，可由 `GPT_IMAGE_EXTERNAL_CONFIG_PATH` 读取个人 gpt-image-async 配置，服务器仍建议显式环境变量。不允许占位图或无 provider 证据的本地文件冒充成功，供应商原图宽高必须均不小于目标，最终图精确 `1940x1200` 且满足字节限制；每张 final/raw 图旁写 `*.metadata.json`，记录 prompt、参考图、provider/model、原始/最终尺寸、SHA-256、OSS 和状态证据。五张缺一张都只能是 partial/failed，不能标记 done。
- 领星 ERP A+ 上传/发布的既有逻辑见 `docs/lingxing-aplus-upload.md` 和 `backend/app/services/aplus_upload.py`；重新打通方案见 `docs/superpowers/specs/2026-06-23-lingxing-aplus-publish-after-aplus-done-prd.md`，技术方案见 `docs/superpowers/specs/2026-06-23-lingxing-aplus-publish-technical-plan.md`。T1 已新增数据基础：`backend/app/aplus_publish/status.py` 是 `aplus_upload_status` 状态 registry，`backend/app/services/aplus_publish_state.py` 是 CatalogProduct 主事实/Product 兼容镜像/AplusUploadItem 外部证据的统一写入入口，`products/catalog_products/aplus_upload_items` 已预留 seller SKU、ASIN 匹配证据和 Lingxing 草稿/可见性/提交证据字段。T2 已将 Amazon 导出成功时实际写入模板 `sku` 字段的 seller SKU/MSKU 持久化到 `CatalogProduct.amazon_seller_sku` / `Product.amazon_seller_sku`，并新增 `backend/app/services/asin_match_policy.py`、`backend/app/services/lingxing_listing_client.py`、`backend/app/task_planners/lingxing_listing_sync.py`、`backend/app/task_runtime/lingxing_listing_sync_workers.py` 和 `POST /api/task-runs/lingxing-listing-sync`，用 seller SKU/MSKU exact match 作为 Lingxing Listing / ASIN 对齐主规则；UPC 只能作为辅助查询/诊断。T3 已新增 `backend/app/services/lingxing_aplus_publish_policy.py`、`backend/app/services/lingxing_aplus_publish_client.py`、`backend/app/task_planners/lingxing_aplus_publish.py`、`backend/app/task_runtime/lingxing_aplus_publish_workers.py` 和 `POST /api/task-runs/lingxing-aplus-publish`，只保存领星 A+ 草稿并写 `draft_saved + amazon_draft_visibility=unconfirmed`。T3.5/M2 已新增 `backend/app/aplus_publish/module_registry.py` 和 `backend/app/services/lingxing_aplus_module_mapper.py`：发布 profile 已从单一旧 profile 扩展为 registry-backed `standard_header_image_text_v1` legacy profile + `enhanced_basic_aplus_v1` enhanced basic profile。旧 profile 仍是 5 个 `STANDARD_HEADER_IMAGE_TEXT`；enhanced profile 固定 5 个普通 A+ 标准模块：`STANDARD_IMAGE_TEXT_OVERLAY`、`STANDARD_THREE_IMAGE_TEXT`、`STANDARD_SINGLE_IMAGE_SPECS_DETAIL`、`STANDARD_COMPARISON_TABLE`、`STANDARD_TECH_SPECS`，由 registry 定义 7 个必需 image slot。Step7/8/9 只在显式 enhanced profile 时生产 enhanced modules 和 slot manifest；policy/mapper/client/planner/worker 在外部调用前按 registry/helper fail closed，并按 `asset_slot_id` 组装 slot upload map。增强版普通 A+ 见 `docs/superpowers/specs/2026-06-24-lingxing-aplus-enhanced-basic-prd.md`：当前结论是只做普通 A+ 标准模块组合，Premium/高级 A+ 暂不实现自动创建/编辑，因为领星帮助中心显示创建/编辑当前只支持基本 A+。旧已导出记录如果没有持久化 `amazon_seller_sku`，不能只凭 `exported_at` 或当前 `item_code` 作为 A+ 发布前置主匹配键，必须进入 `waiting_listing` 并等待明确 seller SKU 证据。当前仍未新增 draft visibility、提交审批、A+ done 自动触发或前端按钮；不得并入 Amazon 主 workflow / 商品列表 `work_status`，A+ 失败也不能让商品退出待导出。
- TikTok 链路重设计见 `docs/superpowers/specs/2026-06-21-tiktok-listing-flow-redesign-prd.md`：TikTok 需要独立状态、类目、库存、价格和导出/发布口径，不能复用 Amazon 类目/竞品/导出语义。
- TikTok R1 渠道状态以 `backend/app/services/tiktok_status.py` 的 MySQL 8 CTE 为唯一事实源：详情、商品列表 items/filter/total/page 和明确 TikTok 数据源 overview 共用 `failed | draft | missing_required_info | unsupported` 四桶；字段齐全固定为 `unsupported / 资料已齐 · 导出暂未接入`，不从 `Product.status=completed` 推导待导出。GigaSku 与 variants 二选一，价格和分仓库存的 invalid/非数组/畸形字段 fail closed 且 quantity=0 有效；TikTok 页面不提供导出、发布或 Amazon Export Center 动作。
- 旧 StyleSnap 模式已退役：后端不再注册或保留 `/api/amazon-stylesnap` router，旧前端竞品确认页已删除，`/products/competitor-review` 仅重定向到商品列表；代码层不再保留旧 `AmazonStyleSnapCandidate` / `AmazonListingCapture` 模型、旧 snapshot key 读取或导出兼容逻辑。已存在的旧物理表不由应用启动逻辑维护或自动 drop。
- 已修 P0：ProductTaskAction reserve 后的图片分析/Listing 入队态不能再被旧 pipeline `is_running(product.id)` 误判为中断。后续结构治理应把商品主状态从 task queued/running 语义收敛为业务节点四态。

## 关键入口

- 商品列表：`frontend/src/pages/ProductList.tsx`
- Amazon 详情：`frontend/src/pages/ProductDetail.tsx`
- TikTok 详情：`frontend/src/pages/TikTokProductDetail.tsx`
- 图片确认：`frontend/src/pages/ProductImageReview.tsx`
- 新建商品：`frontend/src/pages/CreateProduct.tsx`
- 前端 API client：`frontend/src/api/index.ts`
- 商品 API：`backend/app/api/products.py`
- 自动选图：`backend/app/services/giga_product_drafts.py`, `backend/app/services/product_image_candidates.py`, `backend/app/services/product_image_vlm.py`, `backend/app/services/product_protection.py`, `backend/app/product_tasks/auto_image_selection.py`, `backend/app/task_planners/product_auto_image_selection.py`
- GIGA 素材准备与产物：`backend/app/services/product_material_prepare.py`, `backend/app/task_planners/product_material_prepare.py`, `backend/app/services/product_pipeline_artifacts.py`, `ProductMaterialAsset`, `GET /api/products/{id}/materials`, `GET /api/products/{id}/materials/{asset_id}/preview`
- 自动竞品搜索/视觉初筛/候选详情/自动选竞品：`backend/app/services/amazon_competitor_query.py`, `backend/app/services/amazon_search_page.py`, `backend/app/services/amazon_competitor_visual_match.py`, `backend/app/services/amazon_listing_detail.py`, `backend/app/task_planners/product_competitor_search.py`, `backend/app/task_planners/product_competitor_visual_match.py`, `backend/app/task_planners/product_competitor_candidate_capture.py`, `backend/app/task_planners/product_auto_competitor_selection.py`, `backend/app/product_tasks/actions.py`
- 关键词采集：`backend/app/task_planners/product_keyword_research.py`, `backend/app/pipeline/step3_keywords.py`, `backend/app/product_tasks/actions.py`
- 用户心智梳理：`backend/app/pipeline/customer_mindset.py`, `backend/app/task_planners/product_customer_mindset.py`, `backend/app/product_tasks/actions.py`, `product_customer_mindset.payload_json`
- A+ 自动触发 policy/hook：`backend/app/services/aplus_auto_trigger.py`；Listing success hook 位于 `backend/app/product_tasks/actions.py` 的 `ProductListingGenerationAction.on_step_success()`
- 领星 A+ 发布状态/证据基础：`backend/app/aplus_publish/status.py`, `backend/app/services/aplus_publish_state.py`, `backend/app/models/models.py`, `backend/app/database.py`
- 领星 Listing / ASIN 对齐 T2：`backend/app/services/asin_match_policy.py`, `backend/app/services/lingxing_listing_client.py`, `backend/app/task_planners/lingxing_listing_sync.py`, `backend/app/task_runtime/lingxing_listing_sync_workers.py`, `POST /api/task-runs/lingxing-listing-sync`
- 领星 A+ 草稿保存 T3/T3.5：`backend/app/aplus_publish/module_registry.py`, `backend/app/services/lingxing_aplus_module_mapper.py`, `backend/app/services/lingxing_aplus_publish_policy.py`, `backend/app/services/lingxing_aplus_publish_client.py`, `backend/app/task_planners/lingxing_aplus_publish.py`, `backend/app/task_runtime/lingxing_aplus_publish_workers.py`, `POST /api/task-runs/lingxing-aplus-publish`
- 领星 A+ 上传旧批次入口：`backend/app/services/aplus_upload.py`, `POST /api/products/catalog/aplus-upload`, `frontend/src/pages/AplusUploadList.tsx`（旧批次页组件）
- TikTok API：`backend/app/api/tiktok.py`
- TikTok 渠道状态 projector：`backend/app/services/tiktok_status.py`
- pipeline：`backend/app/pipeline/engine.py`, `backend/app/pipeline/step*.py`
- 模型：`backend/app/models/models.py`
- 表：`products`, `product_data`, `product_images`, `product_aplus`, `catalog_products`, `amazon_competitor_search_candidates`

## 关键流程

- 商品列表/详情：页面 -> `frontend/src/api/index.ts` -> `backend/app/api/products.py`；compact 首屏不加载全部素材，文件 tab 再读取完整详情。素材事实来自 `product_material_assets`，图片/视频/PDF/HTML/文本/表格均通过商品目录 containment 校验后预览，ZIP 可展开成员；GET 详情和预览不得移动、删除或改写原始供应商文件。
- 图片确认：`ProductImageReview.tsx` -> 商品 API -> `product_images`。图片分析在 `backend/app/pipeline/step6_image.py` 对每张已确认图片保存可见事实、不可宣称/不确定项、建议文案用途、质量评估与风险；每个 URL VLM 批次必须逐张返回结果，缺图或重复图会失败重试，不能用部分分析继续。`selection_diagnostics.image_evidence_cards` 提供逐图证据卡，`gallery_evidence_coverage` 汇总商品身份、尺寸、材质、功能、场景、安装/维护和包装证据是否覆盖。Step 6 前 Listing 对齐明确为 `pending_listing`；`step5_listing.py` 保存最终标题、Product Highlights、五点和描述后才重算 `listing_image_alignment` 与图片健康度。详情页图片批次表可展开查看这些字段；旧分析结果保持兼容并显示现有字段。
- Amazon 图片合规：Step 6 逐图保存 `contains_person`；A+ Step 9 和 Step 10 对含人物的最终投放副本写入 `XMP-dc:Subject=contains-synthetic-performer`。Step 10 对含人物远程 URL 自动下载并上传受管 OSS 副本，上传后必须回读验证 XMP 与 SHA-256；失败会阻止受影响商品导出。审计结果位于 `ProductImage.image_compliance_manifest`。
- 自动竞品搜索：商品列表/详情 workflow action -> `POST /api/products/{id}/competitor-search/retry` -> `product_competitor_search` task run -> `amazon_competitor_search_candidates`。
- 真实 Amazon 搜索 evidence：`product_competitor_search` action 只传 `product_id/item_code/task_run_id/task_step_id` 上下文给 `run_amazon_search_queries()`；浏览器访问、页面分类和证据文件写入都在 `amazon_search_page` adapter 内完成，adapter 不写商品 workflow。
- 竞品视觉初筛：商品列表 workflow action -> `POST /api/products/{id}/competitor-visual-match/retry` -> `product_competitor_visual_match` task run -> 当前搜索 run/step 的 `amazon_competitor_search_candidates.visual_*` 字段 -> 创建/复用 `product_competitor_candidate_capture` task；默认 detail adapter 未配置时，下游 task typed failed 到 `capture_competitor_candidates/failed`。
- 候选详情抓取/自动选竞品 E4A：pending 节点可保留现有 API 已接受的 `restart_competitor_search`；`capture_competitor_candidates/failed` 与 `auto_select_competitor/failed` 有 correlation 时只允许 `open_task_center` / `open_detail`，`capture_competitor_detail/failed` 无 correlation 时只允许 `open_detail`，不得暴露未实现的详情 retry 或 destructive reset。`adapter_not_configured` 必须明确显示真实 Amazon 详情抓取能力未接入。后端 candidate capture action 已支持 fixture/configured adapter 执行、success hook 落库并自动创建/复用 auto competitor selection；auto competitor selection action 已支持 deterministic final competitor scoring/write 和 image_analysis task 创建/复用。真实 API retry、前端按钮、真实 Amazon adapter 和真实图片分析执行仍未启用。
- Workflow action 机器契约位于 `contracts/product_workflow_actions.json`，由 `frontend/scripts/generate-product-workflow-actions.mjs` 生成 `frontend/src/workflow/productWorkflowActions.generated.ts`，页面通过 `frontend/src/workflow/productWorkflowActionRegistry.ts` 分发；未知 action 必须显示禁用降级，不得静默消失。下游 TaskRun 创建失败使用 `task_run_creation_failed`，不得伪造 correlation；已有真实失败 run 才保留任务中心定位。验证入口：`cd frontend && npm run contracts:check && npm run test:workflow-actions:e2e`、`cd backend && .venv/bin/python ../scripts/test_stability_repair_r1_workflow_actions.py`；DB 行为必须显式提供 `R1_TEST_MYSQL_ADMIN_URL` 并加 `--with-mysql`，只使用 `fbm_pipeline_r1_*` 隔离库。
- 图片分析/心智梳理/Listing：图片分析 success hook -> `product_customer_mindset` -> `product_customer_mindset.payload_json` -> `product_listing_generation` -> `product_listing_content.payload_json` -> `generate_aplus/pending` -> A+ 五图完成 -> `confirm_images_aplus/pending` -> 页面人工确认 -> `flow_done/succeeded` / 商品列表 `export_ready`。`CatalogProduct.confirmed_at` 只在最后的人工确认写入，因此 Excel 导出不会绕过确认。心智或 A+ 失败均不可伪装为待导出。
- Amazon/TikTok 详情分流：前端路由和数据源类型共同决定详情入口。
- TikTok 状态闭环：`build_tiktok_classification_cte()` -> `GET /api/products` / `GET /api/products/overview` / `GET /api/tiktok/products/{id}` -> `ProductList.tsx` / `TikTokProductDetail.tsx`；TikTok 筛选不能与 Amazon `work_status` 同传。

## 相关文档

- `docs/main-flow-user-path.md`
- `docs/main-flow-qa-checklist.md`
- `docs/item-workbench-redesign-plan.md`
- `docs/documentation-rewrite-brief.md`
- `docs/superpowers/specs/2026-06-18-amazon-product-workflow-prd.md`
- `docs/superpowers/specs/2026-06-19-amazon-auto-image-competitor-selection-prd.md`
- `docs/superpowers/specs/2026-06-19-amazon-auto-image-selection-prd.md`
- `docs/superpowers/specs/2026-06-19-amazon-auto-competitor-selection-prd.md`
- `docs/superpowers/specs/2026-06-21-amazon-auto-flow-to-export-ready-prd.md`
- `docs/superpowers/specs/2026-06-21-amazon-aplus-auto-after-export-ready-prd.md`
- `docs/superpowers/specs/2026-06-23-lingxing-aplus-publish-after-aplus-done-prd.md`
- `docs/superpowers/specs/2026-06-23-lingxing-aplus-publish-technical-plan.md`
- `docs/superpowers/specs/2026-06-23-lingxing-aplus-module-mapping-prd.md`
- `docs/superpowers/specs/2026-06-24-lingxing-aplus-enhanced-basic-prd.md`
- `docs/lingxing-aplus-upload.md`
- `docs/superpowers/specs/2026-06-21-tiktok-listing-flow-redesign-prd.md`
- `docs/superpowers/specs/2026-06-22-product-work-status-registry.md`
- `docs/superpowers/specs/2026-06-17-product-workflow-node-state-prd.md`
- `docs/superpowers/specs/2026-06-16-product-task-action-refactor-prd.md`

## 验证入口

- 商品列表：`http://localhost:3190/products`
- 图片确认：`http://localhost:3190/products/image-review?data_source_id=<id>`
- Amazon 详情：`http://localhost:3190/products/<id>`
- TikTok 详情：`http://localhost:3190/tiktok/products/<id>`
- 商品总览：`GET /api/products/overview?data_source_id=<id>`
- TikTok 隔离 SQLite/API：`backend/.venv/bin/python scripts/test_stability_repair_r1_tiktok.py`
- TikTok 真实 API 页面：`backend/.venv/bin/python scripts/test_stability_repair_r1_tiktok_frontend.py`
- E5 行为脚本：`cd backend && .venv/bin/python ../scripts/test_image_analysis_listing_e5.py`
- 用户心智问题/证据/消费契约：`cd backend && .venv/bin/python ../scripts/test_customer_mindset.py`
- Listing 短标题、单条标题补充（最多 120 字符）、旧五点与真实模板列契约：`cd backend && .venv/bin/python ../scripts/test_listing_title_highlights.py`。标题补充承接标题未覆盖的已证实属性或适配信息；自动生成五点另有固定的买家决策职责（购买理由、已证实体验、场景、适配实用性、购买边界），尽量将每条写成不同的用户使用/决策情景 + 已证实功能 + 实际结果，目标每条不超过 320 字符；要求内部审计记录具体事实和用户心智证据，拒绝空泛营销词和重复的情景、宣称或结果。
- A+ 自动触发 A1/A2 行为脚本：`cd backend && .venv/bin/python ../scripts/test_aplus_auto_trigger_a1_a2.py --stage a1` / `--stage a2`

## 常见定位

- 状态/按钮/统计问题：先看 `backend/app/api/products.py` 返回字段，再看页面消费逻辑。
- 商品详情打开后素材文件位置变化：先看 `backend/app/api/products.py` 的 GET 详情链路和 `backend/app/services/material_assets.py`，GET 路径不得调用 mutating 素材整理函数。
- 图片选择问题：手动纠偏看 `ProductImageReview.tsx`、`PUT /api/products/{id}/listing-images`、`product_images` 和 `backend/app/services/product_protection.py`；自动选图入口/重试看 `backend/app/services/giga_product_drafts.py`、`POST /api/products/{id}/auto-image-selection/retry`、`backend/app/task_planners/product_auto_image_selection.py`、`backend/app/product_tasks/actions.py`、`backend/app/product_tasks/auto_image_selection.py`。
- 自动竞品搜索问题：先看 `POST /api/products/{id}/competitor-search/retry`、`backend/app/task_planners/product_competitor_search.py`、`backend/app/product_tasks/actions.py` 的 `ProductCompetitorSearchAction`、`backend/app/services/amazon_competitor_query.py` 和 `backend/app/services/amazon_search_page.py`。
- 真实 Amazon search adapter 问题：先确认 `.env` 中 `AMAZON_SEARCH_PAGE_ADAPTER` / `AMAZON_SEARCH_ENABLE_REAL_BROWSER`；默认未启用时应返回 `adapter_not_configured`。启用 Chrome adapter 后如果没有本机 GUI Chrome 授权、AppleScript 权限、Amazon 登录/地区/CAPTCHA 处理，会以 typed failure 写入 task workflow error 和 evidence；不要改用 fixture 或旧 evidence 冒充成功。
- 竞品视觉初筛问题：先看 `POST /api/products/{id}/competitor-visual-match/retry`、`backend/app/task_planners/product_competitor_visual_match.py`、`backend/app/product_tasks/actions.py` 的 `ProductCompetitorVisualMatchAction` 和 `backend/app/services/amazon_competitor_visual_match.py`；重点核对当前成功 Phase A run/step 限定、processing API bypass、旧 selected 清理和失败态不保留 current selected。
- 候选详情抓取/自动选竞品问题：先看 `backend/app/task_planners/product_competitor_candidate_capture.py`、`backend/app/task_planners/product_auto_competitor_selection.py`、`backend/app/product_tasks/actions.py` 的 `ProductCompetitorCandidateCaptureAction` / `ProductAutoCompetitorSelectionAction` 和 `backend/app/services/amazon_listing_detail.py`；E4A 只允许 fixture/configured adapter 的候选详情抓取落库和 deterministic final competitor scoring/write，不应出现真实 Amazon 访问、前端 retry 入口或真实图片分析执行。
- A+ 自动触发 eligibility/hook 问题：先看 `backend/app/services/aplus_auto_trigger.py` 的 decision code 和 `try_auto_start_aplus_after_export_ready()`；A1/A2 检查 `completed`、`flow_done/succeeded`、`CatalogProduct.confirmed_at`、Listing/image facts、未被取代的 active 主流程/A+ task、A+ 状态、真实 ASIN、A+ 上传、导出历史和 Amazon 模板输出保护。Listing hook 只在 E5 commit 后执行，默认开启并创建或复用 task；可由配置显式关闭。
- 领星 A+ 上传/发布问题：先看 `docs/superpowers/specs/2026-06-23-lingxing-aplus-publish-after-aplus-done-prd.md`、`docs/superpowers/specs/2026-06-23-lingxing-aplus-publish-technical-plan.md`、`docs/superpowers/specs/2026-06-23-lingxing-aplus-module-mapping-prd.md`、`docs/superpowers/specs/2026-06-24-lingxing-aplus-enhanced-basic-prd.md` 和 `docs/lingxing-aplus-upload.md`；Listing / ASIN 前置看 `backend/app/services/asin_match_policy.py`、`backend/app/services/lingxing_listing_client.py`、`backend/app/task_planners/lingxing_listing_sync.py` 和 `backend/app/task_runtime/lingxing_listing_sync_workers.py`；profile/module/slot 事实源看 `backend/app/aplus_publish/module_registry.py`，Step7/8/9 enhanced 生产端看 `backend/app/pipeline/step7_aplus_plan.py`、`backend/app/pipeline/step8_aplus_script.py`、`backend/app/pipeline/step9_aplus_image.py`；草稿保存和 fail-closed 看 `backend/app/services/lingxing_aplus_publish_policy.py`、`backend/app/services/lingxing_aplus_module_mapper.py`、`backend/app/services/lingxing_aplus_publish_client.py`、`backend/app/task_planners/lingxing_aplus_publish.py` 和 `backend/app/task_runtime/lingxing_aplus_publish_workers.py`；旧上传批次看 `backend/app/services/aplus_upload.py`、`POST /api/products/catalog/aplus-upload` 和 `AplusUploadBatch/AplusUploadItem`。注意当前新链路只做到 `draft_saved + unconfirmed`，不确认 draft visibility、不提交审批，且真实领星读取/保存默认 fail closed；M3.3 前不得声明真实领星字段可见或 Amazon 草稿可见。
- 旧 StyleSnap 残留问题：先确认是否还有 `/api/amazon-stylesnap`、旧 service、旧前端页面、旧 ORM 模型、旧 snapshot key 读取或 Step 10/export 兼容读取；不要恢复旧运行入口。
- 数据源分流问题：先看 `frontend/src/App.tsx`、详情页和 `backend/app/api/products.py`。

## 维护规则

只有页面/API/核心 service/table/状态语义/人工确认节点/验证入口变化时更新本文。普通 bug fix、函数内部重构、样式微调、测试补充不需要更新。

## Product Large Content Storage

- SQLite cutover migration: `backend/app/migrations/product_large_fields.py`. It moves product JSON/text bodies into optional 1:1 child tables and leaves legacy columns untouched and read-only after cutover.
- Detail read contract: `backend/app/api/products.py` returns section metadata in the product summary. Full content is read only from `sections/source`, `sections/mindset`, `sections/listing`, `sections/images?part=...`, `sections/aplus?part=...`, and `sections/export-artifact`.
- The 用户心智 tab is read-only: loading it must only GET `sections/mindset`; generation and retry remain explicit workflow mutations.
- Mindset freshness checks must hydrate canonical `source` and `source_snapshot` together with `mindset` before recomputing the input fingerprint; any `ProductData` refresh must re-project those sections before readiness or downstream checks.
