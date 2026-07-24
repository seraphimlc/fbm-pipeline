# Domain Index: Frontend Pages

## 范围

- 前端路由、页面入口、API client、导航和页面冒烟路径。
- 页面交互问题的定位顺序。
- 不记录具体 UI bug 修复过程。

## 当前口径

- 路由定义在 `frontend/src/App.tsx`。
- 页面 API 调用集中从 `frontend/src/api/index.ts` 定位。
- 状态/按钮/统计问题优先确认后端稳定字段，不让前端自行推导。
- 不通过隐藏按钮、堆 badge、堆说明文案掩盖后端语义不清。
- Catalog export 在新旧任务中心和导出中心只消费 API 的 `catalog_export_result` / `CatalogExportFile.rows`：展示请求、成功、跳过、失败、报告计数及逐商品原因；每行使用后端 1-based `row_ordinal`，React key / E2E selector 只由外层 task/file key + ordinal 构成，重复/空 ID、相似 Code 或 Unicode 不参与身份推导。`OfflineTaskCenter.tsx` 的 catalog summary、rows、下载文件名只读 typed result，catalog 分支不解析 `result_json`；空 rows 显示安全空态。新任务中心下载只认 `available_actions`，旧任务中心和导出中心只认 `can_download`，不从 `summary_json`、规范化展示字段或原始状态自行授权。
- TikTok 商品列表和详情只消费后端 `channel_status` 四桶，不从 raw `status/completed` 或 Amazon `work_status` 推导待导出。`unsupported` 固定显示“资料已齐 · 导出暂未接入”和“TikTok 导出/发布尚未接入”；TikTok 行无导出、发布或 Amazon Export Center CTA，详情只保留刷新。
- 非 loopback Vite 开发服务的 `/api` 写请求先经过 `frontend/dev-api-write-guard.ts`；远程调用方必须显式携带正确 token，非空 token Header 优先于 Bearer，guard 不向浏览器暴露或代注 token。启动 helper 从一次 dotenv 快照绑定 effective `FRONTEND_HOST` 与双 token：remote snapshot 仅接受 1..4096 字节可见 ASCII且字节一致，最终 Vite `--host` 只使用 proof 注入的同快照 host；`vite.config.ts` 的 mode env 只恢复非敏感 backend URL/frontend port，写 token 只读 server process env。D1 只建立传输边界，不包含页面 mutation inventory 或统一错误 UX。
- D2b 静态与 runtime coverage 已启用：57 个 mutation callsite（47 direct + 10 workflow-registry）全部通过 `runMutationWithUX`，58 个 mutating API export 均只把 `fbmMutationCallsiteId` 合并进 axios config，不覆盖原 timeout/params/headers/responseType，也不把 metadata 发进 URL/header/query/body。runner 统一调用 `apiErrorMessage -> message.error`、原样 rethrow，并在 `clearLoading` 中结束登记 loading；页面边界必须用标准 `.catch(() => undefined)` 吞掉 rethrow，`onError` / `clearLoading` 的静态证据不进入未调用的嵌套 function-like，且 setter clear 值必须匹配 owner 的显式 `useState(false|null)`。失败不重置 form/draft/selection/detail cache；ProductDetail 文件打开和 Catalog 模板上传使用 operation+path/category key，只锁定目标按钮。AST gate 固定要求 `inventory ids == owner contract ids == static wrapper verified ids`。Playwright 第四集合通过 `page.evaluate` 动态 import 真实 `/src/api/index.ts`，test-only request interceptor 只读取 `config.fbmMutationCallsiteId`；GET fixture 只提供页面读模型，所有 mutation 继续到真实非 loopback Vite pre-guard 403。57/57 case 精确比较 runtime ids，page error / unhandled rejection 立即失败，并覆盖 form、draft、selection、detail cache 与 target-owned loading；harness 最终断言 upstream/backend 写入计数均为 0。

## 关键入口

- 路由：`frontend/src/App.tsx`
- Layout/导航：`frontend/src/components/MainLayout.tsx`
- API client：`frontend/src/api/index.ts`
- Mutation foundation/runtime：`frontend/src/api/mutationRunner.ts`, `frontend/src/api/mutationInventory.generated.ts`, `frontend/src/api/mutationOwnerContract.ts`, `frontend/src/workflow/productWorkflowActionRegistry.ts`, `frontend/scripts/generate-mutation-inventory.mjs`, `frontend/tests/mutation-ux.r1.spec.ts`, `frontend/playwright.mutation.r1.config.ts`, `scripts/test_stability_repair_r1_mutation_frontend.py`
- Vite 开发代理写保护：`frontend/dev-api-write-guard.ts`, `frontend/vite.config.ts`
- Workflow action registry：`frontend/src/workflow/productWorkflowActionRegistry.ts`；源 manifest 为 `contracts/product_workflow_actions.json`
- 全局样式：`frontend/src/index.css`
- 商品列表：`frontend/src/pages/ProductList.tsx`
- Amazon 详情：`frontend/src/pages/ProductDetail.tsx`
- TikTok 详情：`frontend/src/pages/TikTokProductDetail.tsx`
- 图片确认：`frontend/src/pages/ProductImageReview.tsx`
- 竞品确认旧页已退役：`/products/competitor-review` 仅重定向到商品列表；竞品搜索入口在商品列表 workflow action 和任务中心。
- 新任务中心：`frontend/src/pages/TaskRunCenter.tsx`
- 旧离线任务中心：`frontend/src/pages/OfflineTaskCenter.tsx`
- 导出中心：`frontend/src/pages/CatalogList.tsx`
- 数据源：`frontend/src/pages/ProductDataSourceList.tsx`

## 关键流程

- 页面定位：路由 -> page component -> API client -> backend API。
- 状态/按钮问题：page component -> API response fields -> backend display/projection。
- 页面冒烟：打开页面 -> 检查 loading/error/empty/data 状态 -> 对应 API 样本。

## 相关文档

- `docs/domain-index/product-flow.md`
- `docs/domain-index/task-runtime.md`
- `docs/domain-index/export-flow.md`
- `docs/domain-index/data-sources.md`
- `docs/collaboration/playbooks/qa.md`
- `docs/collaboration/playbooks/code-review.md`

## 验证入口

- 构建：`cd frontend && npm run build`
- Workflow action 契约：`cd frontend && npm run contracts:check`
- Mutation inventory/foundation：`cd frontend && npm run mutations:check`
- Mutation remote-read-only runtime：`python3 scripts/test_stability_repair_r1_mutation_frontend.py`
- Workflow unknown-action Chromium 渲染：`cd frontend && npm run test:workflow-actions:e2e`
- Catalog export 真实 API Chromium：`R1_TEST_MYSQL_ADMIN_URL='mysql+asyncmy://root@127.0.0.1:3306/' backend/.venv/bin/python scripts/test_stability_repair_r1_catalog_frontend.py`
- TikTok 真实 API Chromium：`R1_TEST_MYSQL_ADMIN_URL='mysql+asyncmy://root@127.0.0.1:3306/' backend/.venv/bin/python scripts/test_stability_repair_r1_tiktok_frontend.py`
- 远程 Vite/FastAPI 写保护：`python3 scripts/test_stability_repair_r1_remote_guard.py`
- 商品列表：`http://localhost:3190/products`
- 任务中心：`http://localhost:3190/task-runs`
- 导出中心：`http://localhost:3190/export-center`
- 数据源：`http://localhost:3190/data-sources`

## 常见定位

- 路由问题：先看 `frontend/src/App.tsx`。
- 导航问题：先看 `frontend/src/components/MainLayout.tsx`。
- API 字段问题：先看 `frontend/src/api/index.ts`，再到对应后端 API。
- 页面慢/阻塞：先看页面首屏请求和非首屏请求是否拆开。
- 状态/按钮/统计问题：先看后端是否提供明确字段。
- Catalog export 结构化结果问题：先对照 `/api/task-runs` 的 `catalog_export_result` 和 `/api/products/catalog/export-files` 的 `rows/can_download`；真实页面链路用 catalog frontend orchestrator，不用 `page.route()` 或 HAR。
- TikTok 状态问题：先看 `backend/app/services/tiktok_status.py` 的共享 CTE 和 `/api/products` 的 `channel_status*`，再看 `ProductList.tsx` / `TikTokProductDetail.tsx`；真实页面链路不用 `page.route()`、HAR 或 API mock。

## 维护规则

只有路由、页面入口、API client 主要方法、导航入口或主要验证入口变化时更新本文。普通 bug fix、函数内部重构、样式微调、测试补充不需要更新。
