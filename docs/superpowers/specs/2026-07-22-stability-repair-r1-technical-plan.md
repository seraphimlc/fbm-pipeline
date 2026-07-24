# FBM Pipeline 稳定性修复 R1 技术方案

状态：READY_FOR_TECHNICAL_REREVIEW
日期：2026-07-22
Owner：听云（agentKey: `tingyun`）
依据：`2026-07-22-stability-repair-r1-prd.md`

## 1. 推荐方案

R1 采用四个局部闭环，不做数据库迁移或 task runtime 重构：

1. 用共享机器 manifest 定义 workflow action 闭包；后端只输出真实动作，未知 action 显式禁用并报警。
2. catalog worker 返回 typed outcome envelope；scheduler 将业务 outcome 原子投影到 step/group/run，系统异常仍走异常失败。
3. TikTok 详情与商品列表共用渠道状态 projector，资料完整只能是 `unsupported`，不能由 `Product.status=completed` 推成 `export_ready`。
4. Vite 用原始 socket 在 proxy 前拦截远程写请求；后端根据远程代理标记再次校验同一调用方 token。

方案只修复错误结论、无效动作、部分失败伪成功和远程写保护。真实 Amazon detail、TikTok 导出、runtime lease/outbox、数据库迁移和 Amazon 模板均不进入 R1。

## 2. 当前根因

- `workflow.py::_failed_overrides()` 输出前端不存在的 `retry_competitor_capture`；两个页面又会静默丢弃未知 action。
- catalog payload 已有 `done|partial_failed|failed`，但 `scheduler._execute_step()` 将所有正常 return 固定写为 succeeded。
- 旧 `TaskRun.status=succeeded + summary.status=partial_failed` 仅响应层改标签不能满足 current/history、分页和计数一致性。
- TikTok detail 返回 `export_ready`；ProductList 还会用 `product.status=completed` 自行推导待导出。
- Vite proxy 让后端看到 loopback；现有后端 guard 无法识别请求原本来自远程浏览器。
- R1 focused tests 如果沿用配置业务库，将可能改变真实商品与任务事实。

## 3. Workflow action 闭包

### 3.1 后端输出

修改 `backend/app/product_tasks/workflow.py`：

- 提取 `_related_correlation_key(product, node)`，由 `_state()` 和失败动作共同使用。
- 新增 `_workflow_error_code(product)`：优先解析 JSON `error_type|code`，仅兼容文本中的精确 token `adapter_not_configured`，不做模糊中文猜测。
- `capture_competitor_candidates/failed`、`auto_select_competitor/failed`：有 correlation 时 primary=`open_task_center`、allowed=`open_task_center|open_detail`；缺失时退到 `open_detail`。
- `capture_competitor_detail/failed` 当前没有 correlation，primary/allowed 仅 `open_detail`。
- 三个失败节点删除 `retry_competitor_capture` 和 `restart_competitor_search`；R1 不发明详情重试或 destructive reset。
- `adapter_not_configured` 文案固定为：`当前版本尚未接入真实 Amazon 详情抓取，本商品已停止自动推进。`
- 其它失败：有 correlation 显示 `任务执行失败，可在任务中心查看原因。`；否则显示 `任务执行失败，请在商品详情查看原因。`

pending 节点的 `restart_competitor_search` 只有在现有 `/api/products/{id}/competitor-search/retry` 前置真实接受时保留，测试必须调用 route 验证，不能只扫字符串。

### 3.2 机器契约与前端降级

新增源 manifest `contracts/product_workflow_actions.json`，每项固定：

```json
{
  "action": "retry_competitor_search",
  "kind": "api",
  "client_export": "retryProductCompetitorSearch",
  "method": "POST",
  "route": "/api/products/{product_id}/competitor-search/retry",
  "default_label": "重试 Amazon 搜索"
}
```

导航项使用 `kind=navigate` 和 `target`；manifest 是闭包测试和前端 registry 的共同输入，不允许 Python 正则解析 TS。

为避免前端 `rootDir` 外 JSON import，新增 `frontend/scripts/generate-product-workflow-actions.mjs`：读取源 manifest，确定性生成 `frontend/src/workflow/productWorkflowActions.generated.ts`；新增 `frontend/src/workflow/productWorkflowActionRegistry.ts` import 该 generated TS 并构建 dispatcher。`frontend/package.json` 增加 `contracts:generate` 和 `contracts:check`，`build` 先执行 check；check 在生成内容与已提交文件不一致时失败。无需启用 `resolveJsonModule`，也不从仓库根直接 import JSON。修改：

- `ProductList.tsx::renderPrimaryRowAction()`
- `ProductDetail.tsx::runWorkflowAction()`
- `ProductDetail.tsx::renderWorkflowActionButton()`

未知 action 不再返回 `null`：显示禁用按钮 `当前版本无法执行`，Tooltip/Alert 为 `未知工作流动作：<action>`，development/test `console.error`。未知 action 网络调用为 0，且不改 workflow、表单或任务事实。

### 3.3 闭包证据

`scripts/test_stability_repair_r1_workflow_actions.py` 使用隔离 MySQL：

1. 调用真实 `build_product_workflow()`，覆盖正式 node/status/error，收集实际 action set。
2. 加载 JSON manifest，断言 `backend_action_set - manifest_action_set = ∅`。
3. 对 API action 用 `app.routes` introspection 校验 method/path，并通过真实 TestClient/ASGI 调用验证创建或复用正确 task run、correlation 和 workflow。
4. 前置不满足样本记录调用前 workflow/task 快照；断言 4xx 后均不改变。
5. Playwright 对 manifest 每项驱动实际页面；删除 manifest、dispatcher client 或后端 route 任一项，至少一个闭包、构建、route 或行为断言必须失败。
6. 注入未知 action，断言显式降级可见且网络 0 次。
7. `make frontend-build` 必须执行 generated contract freshness check 和 TypeScript 编译，证明 manifest 生成物可构建。

## 4. Catalog export outcome

### 4.1 Single validated outcome

`backend/app/services/offline_tasks.py::_catalog_export_result_payload()` 继续生成新结果；历史 summary/step 先解析为 `payload/json_valid/material/malformed` provenance。`select_catalog_export_payload()` 只选择 parse-valid material：parse-valid material summary 优先，status-only 或 invalid/malformed summary 则按 step id 倒序回退最新 parse-valid material step；invalid JSON、NaN/Infinity、溢出数值、深度/内存解析失败均为 nonmaterial，不形成 barrier。选中的 raw payload随后恰好一次进入 `normalize_catalog_export_response()`；invalid-only 不制造 authoritative failed，parse-valid unsafe row 仍 fail closed。后者产出的 validated outcome 是响应、artifact gate、类目聚合和 existing-result 复用的唯一事实源：

```text
status: done | partial_failed | failed
requested_count, success_count, skipped_count, failed_count: int
artifact_available: bool | missing
filename, file_path, oss_object_key, file_size
rows[]: catalog_id, product_id, item_code, seller_sku, category,
        status(exported|skipped|failed), reason, template_file, output_file
```

rows 非空时以 normalized rows 重算全部 counts/status，`requested_count=report_count=len(rows)`；超 JS-safe integer、lone surrogate、nested known field 或非法 row status 均把该行投影为 `failed / 导出结果行格式异常`。显式 `artifact_available=false|null|malformed` 强制 failed。rows 缺失/空时允许 counts 全缺失的 legacy done/partial safe refs；一旦提供任一 count，必须满足 `requested=success+skipped+failed` 和 status 语义，否则 failed。

- `done`：全部成功且 artifact 可用。
- `partial_failed`：至少一项成功、至少一项 skipped/failed，且 artifact 可用。
- `failed`：成功为 0，或没有可用 artifact。

### 4.2 四条 worker 控制流

在 `backend/app/task_runtime/registry.py` 增加 `TaskWorkerOutcome`：

```text
payload: canonical dict
terminal_status: succeeded | partial_failed | failed
event_type: status | warning | error
event_message: str
propagate_single_step_run: bool
```

`catalog_export_workers.catalog_export_template()` 禁止为业务全失败抛普通 `RuntimeError`：

| 控制流 | worker 行为 | scheduler 结果 | 下载 |
|---|---|---|---|
| 全成功 | return done envelope | 三层 succeeded | 是 |
| 混合 | return partial envelope | 三层 partial_failed | 是 |
| 业务全失败，如保护门/模板/字段 | return failed envelope，保留 rows/reasons | 三层 failed | 否 |
| 系统异常，如 DB/文件 IO/OSS/代码错误 | raise 原异常 | exception 分支 failed，记录异常类型 | 否 |

`CatalogExportBuildError` 属于业务 outcome，必须 canonicalize 后正常返回 failed envelope；未知异常不得伪装业务 rows。

`TaskWorkerOutcome` 若保留为通用类型，scheduler 也只允许 `step.step_type == catalog_export_template` 消费 `propagate_single_step_run=true`；运行时必须查询并断言该 run 恰有一个 group、一个 step，且当前 step 即唯一 step。任一条件不满足都抛 `TaskOutcomeContractError`，走系统异常失败，不允许提前把 group/run 标成 terminal。其它 worker 返回该 flag 同样是内部契约失败。

catalog planner 固定一个 run、一个 group、一个 step。为消除 worker 内 commit 与终态原子写冲突：

- `catalog_export_template()` 删除 existing-result、recovery、build-error 和 success 路径中的 `ctx.run.summary_json` 写入及 `ctx.db.commit()`。
- `backend/app/task_runtime/events.py` 增加 `update_step_progress_in_session()`：只更新 progress/event 并 `flush()`，绝不 commit；catalog worker 只用该接口。
- catalog worker 在任何 `CatalogProduct.exported_*` / seller SKU mutation 后都不得调用 commitful helper；文件生成和 fake/real upload 在 DB mutations 前完成。
- scheduler 收到 envelope 后，在同一 DB transaction 内写入：

- `step.status/result_json/error_message/finished_at`
- `group.status/summary_json/progress_current/progress_total/finished_at`
- `run.status/summary_json/finished_at`
- 对应 terminal event
- worker 在同一 session 中产生的 CatalogProduct exported 事实

然后一次 commit，并跳过会覆盖该结果的普通 success 刷新。done 发 success event；partial 发 warning；业务 failed 发 error，但不能先写“step 执行成功”；系统异常只走现有 exception event。文件/OSS 本身不能与 DB 事务原子，但 DB 中 outcome、rows、状态和事件必须原子一致。

focused test 分别在 CatalogProduct mutation 后、step/group/run 赋值后、terminal event flush 后和 commit 时注入异常；用新 session 断言 CatalogProduct、step/group/run payload/status、terminal event 全部回滚到调用前。已经写出的本地文件或 OSS object 可成为孤儿，测试只记录并清理本地孤儿，不把文件原子性伪装为 DB 原子性。

修改 `constants.py` 增加 `STEP_STATUS_PARTIAL_FAILED`，纳入 terminal、不纳入自动 retry。catalog partial 的动作只含查看、下载、复制原因、刷新。

### 4.3 全历史 effective terminal projection

Text JSON 的历史脏数据不能安全承担列表 SQL 分类事实源；R1 不在 MySQL 中解析 summary/result JSON，也不做分页后补过滤。`backend/app/task_runtime/catalog_export_status.py` 在每次相关列表请求中按 owner kind 建立共享 projection：

1. 一次读取全部 catalog owner 的标量 `id/status/summary_json|result_json`；detail 路径可用 `owner_ids` 限定单个 owner。
2. 再一次 batch 读取这些 owner 的 `owner_id/step.id/result_json`，按 step id 倒序跳过 invalid/malformed nonmaterial，选择 newest parse-valid material step；不加载 groups/events/完整 steps，不做 N+1。
3. 每个 owner 只调用一次 `project_catalog_effective_terminal_record()` / `normalize_catalog_export_response()`，生成 `records_by_id`、`authoritative_ids` 和 succeeded/done/partial_failed/failed ID 集。
4. SQL condition 由“raw target status 且排除 authoritative IDs”与“target projected IDs”组成，供 items/count/page 共用；没有分页后 Python 过滤。

投影只覆盖业务 outcome 终态：TaskRun `succeeded|partial_failed|failed`、OfflineTask `done|partial_failed|failed`。有 parse-valid material evidence 时，validated `done|partial_failed|failed` 覆盖 raw 业务终态；无 material 的 terminal 保持 raw；status-only legacy partial 继续投影为 partial。invalid JSON 解析失败本身不算 material evidence，因此 raw succeeded + invalid summary/no valid step 仍是 succeeded，invalid newer + older valid material 使用 older evidence，而 raw succeeded + material unsafe row（如 `2**53` ID）必须成为 failed。canceled/interrupted/paused 不被 catalog outcome 覆盖，也不因 material done 获得下载权限。

同一 projection/condition 必须用于：

- `_history_display_sql_condition()`：history 含 effective succeeded，不含 effective partial/failed；current 对其取反。
- `_display_status_sql_condition('succeeded'|'partial_failed'|'failed')`。
- `list_task_runs()` 的 items、view 后 `base_total`、display filter 后 `filtered_total/total/page`。
- OfflineTask 的 `done|partial_failed|failed` items/count/page。
- TaskRun list/detail 的 `status/display_status/label/reason/actions`，以及 Export Files/Categories/download/existing-result 复用；Export 两个 endpoint 每 owner kind 恰好加载一次 projection，owner SQL 与 row/category builder 直接消费同一 `records_by_id`/ID sets，不再调用 legacy partial helper或二次 selector/normalize/project。

性能语义固定为“全历史 owner scalar + 一次 step batch + 正常 SQL count/page”：没有 JSON SQL、step JOIN、`EXISTS`、相关子查询、N+1 或内存分页。成本随 catalog owner 历史数量线性增长；这是 R1 为历史异常 JSON 安全和筛选/total/page 一致性接受的边界，持久化 projection/backfill 属于后续设计，不能在本轮暗加 schema 或状态同步链路。

### 4.4 恢复、API 与页面

修改 `_catalog_export_result_ready()`、`_recover_catalog_export_result_from_file()`：ready 只消费 validated outcome，并要求 `done|partial_failed` 与可解析 artifact source；显式 unavailable 失败，缺少 availability flag 的 legacy safe refs 继续兼容。恢复 zip 时解析真实 `导出报告.xlsx`；混合 zip恢复为 partial，全失败报告 zip不阻止显式重跑。

API：

- `task_runs.py::_catalog_export_payload()` 返回 validated outcome。
- `download_task_run_result()`、OfflineTask download、Export Center `can_download` 与 existing-result 复用均消费同一 effective record；下载必须同时满足 effective terminal 与 validated artifact resolver，raw canceled/interrupted/paused 不能被 material done 复活。
- `TaskRunResponse` 增加可选 `catalog_export_result`。
- `CatalogExportFileResponse` 增加 `rows`；`can_download` 由 outcome 决定。
- `list_catalog_export_files/categories()` 纳入 effective partial。

`TaskRunCenter.tsx` 显示结构化计数和逐商品原因；`CatalogList.tsx` 已导出列表支持展开 rows，partial 可下载，failed 禁用下载。

## 5. TikTok 渠道状态

### 5.1 单一 projector

新增 `backend/app/services/tiktok_status.py`，唯一事实源是 `build_tiktok_classification_cte(product_ids=None, data_source_id=None)`。该 MySQL 8 CTE 每个 product 只产一行：`product_id,data_source_id,sales_channel,display_sku_count,missing_price_count,missing_warehouse_count,channel_status`。详情、list items、filter、count、overview 都 join/读取该 CTE，不再分别实现 Python 与 SQL 分类。

CTE 先限定 `ProductDataSource.sales_channel='tiktok'`；当前 GigaSku key 与 detail 一致，为商品的 `source_data_source_id + source_site + source_batch_id + item_code`。若该 key 存在 GigaSku 行，则只使用 GigaSku；否则用 MySQL `JSON_TABLE(safe_variants)` 展开 fallback。Text JSON 一律使用不依赖 SQL `AND` 短路的两阶段表达式：

```text
valid_variants_json = CASE
  WHEN COALESCE(JSON_VALID(product_data.variants), 0) = 1 THEN product_data.variants
  ELSE JSON_ARRAY()
END
safe_variants = CASE
  WHEN JSON_TYPE(valid_variants_json) = 'ARRAY' THEN valid_variants_json
  ELSE JSON_ARRAY()
END
```

SKU key 优先 `sku > sku_code > seller_sku`；不得把两套来源 union 后重复计数。`JSON_TABLE` 的 sku、price、cost和 quantity候选列均显式声明 `NULL ON EMPTY NULL ON ERROR`；数值先取 nullable文本/decimal列，再按现有 `_number()` 等价规则接受可转数字值，畸形数值成为 NULL，不得抛 SQL error或返回500。

采购价优先级与现有 detail 完全一致：`GigaPrice.effective_price > discounted_price > exclusive_price > price > variant.cost > cost_total > price > purchase_price`；只接受可转数字且 `>0`。GigaSku 路径按 sku_code 关联价格；variants fallback 仍允许对应 GigaPrice 优先，缺失才读 variant 字段。

warehouse 完整性的唯一 SQL规则：`GigaInventory.seller_inventory_distribution` 使用相同两阶段形式：先以 `CASE WHEN COALESCE(JSON_VALID(value),0)=1 THEN value ELSE JSON_ARRAY() END` 得到 `valid_warehouse_json`，再以 `CASE WHEN JSON_TYPE(valid_warehouse_json)='ARRAY' THEN valid_warehouse_json ELSE JSON_ARRAY() END` 得到 `safe_warehouse_json`，最后交给 `JSON_TABLE`。禁止写成 `JSON_VALID(value)=1 AND JSON_TYPE(value)='ARRAY'` 并假设短路。数组中至少一个 OBJECT，warehouse code 命中 `warehouseCode|warehouse_code|warehouse|sellerCode|seller_code|code`，quantity 命中 `quantity|qty|availableQty|available_qty|sellerAvailableInventory|seller_available_inventory|stock`；所有 `JSON_TABLE` 列显式 `NULL ON EMPTY NULL ON ERROR`。NULL、空串、invalid JSON、合法但非数组 JSON、空数组、只有非 object、缺 warehouse code或畸形/缺失 quantity均计为 missing；quantity=0是有效库存事实。

focused SQL/API fixture必须分别覆盖 invalid JSON、合法 OBJECT/SCALAR、空数组、缺字段和畸形数值，断言 classification按 fallback落入 draft/missing而不是500；详情、list items/filter/count/overview使用同一 CTE时结果一致。

优先级固定：

1. `Product.status=failed` → `failed`
2. 没有可展示 SKU → `draft`
3. 任一 SKU 缺采购价或分仓库存 → `missing_required_info`
4. 当前接入字段齐全 → `unsupported`

`Product.status=completed` 不参与 TikTok `unsupported/export_ready` 判断。

### 5.2 API、筛选与统计

`GET /api/products` 的商品响应增加：

```text
sales_channel: amazon | tiktok
channel_status: failed | draft | missing_required_info | unsupported | null
channel_status_label: str | null
channel_status_reason: str | null
channel_capabilities: { export_supported: false, publish_supported: false } | null
```

`channel_status` query 必须同时提供明确属于 TikTok 的 `data_source_id`；缺失、Amazon data source 或不存在均返回 400。`channel_status` 与 Amazon `work_status` 同时传返回 400。没有指定 TikTok data source 的混合列表不 join/套用 TikTok分类，`channel_status=null`；Amazon work_status 语义不变。

TikTok 数据源下 overview 增加 `channel_status_counts` 四桶。items、filter、total、分页和 overview counts 都从同一 classification CTE派生，不能分页后过滤或用另一个 helper重算。

`GET /api/tiktok/products/{id}` 按 product id join同一 CTE，`status` 改为相同 union；SKU展示细节可复用当前 loader，但最终分类只能读取 CTE `channel_status`。资料齐全返回 `unsupported`。

`ProductList.tsx` 在 TikTok 渠道只读 `channel_status`：四个标签、筛选项和统计卡与 API 一致；删除 completed→export_ready fallback。unsupported 标签为 `资料已齐 · 导出暂未接入`，说明为 `TikTok 导出/发布尚未接入`；所有 TikTok 行无导出、发布或 Amazon Export Center CTA。

`TikTokProductDetail.tsx` 使用同一标签，并显示：`当前版本暂不支持 TikTok 导出或发布；不会生成文件，也不会提交到平台`。页面只保留刷新。

## 6. 远程 Vite 写保护

### 6.1 Token 唯一事实源与启动

`backend/.env` 的 `DEV_API_WRITE_TOKEN` 是 Vite server 唯一事实源；`API_DEV_TOKEN` 仍是 FastAPI guard 配置，远程模式要求两者非空且值相等。

`scripts/start.sh` 用现有 `read_env` 读取两者。若 `FRONTEND_HOST` 非 loopback，则空值或不一致立即退出；loopback 不要求。启动 Vite 时只通过 server process 环境传入：

```bash
DEV_API_WRITE_TOKEN="$DEV_API_WRITE_TOKEN" FRONTEND_PORT=... BACKEND_PORT=... npx vite ...
```

`vite.config.ts` 只读 `process.env.DEV_API_WRITE_TOKEN`。禁止 `VITE_*`、`define`、`import.meta.env`、HTML/global 注入和 token 日志。直接手工远程启动 Vite 且无 token 时 guard fail closed：远程写全拒绝。

### 6.2 Proxy 前 middleware

新增 `frontend/dev-api-write-guard.ts`；`vite.config.ts` 注册 `enforce:'pre'` plugin，其 `configureServer(server)` 直接执行 `server.middlewares.use('/api', guard)`，不返回 post hook。按 Vite middleware 顺序它先于内建 proxy；多进程测试以 upstream 0 calls 作为最终行为证明。

guard：

- 来源只读 `req.socket.remoteAddress`；归一化 `::ffff:127.0.0.1`、方括号 IPv6，loopback 为 `127.0.0.0/8|::1`。
- 不读取/信任 `X-Forwarded-For` 或 `Forwarded`。
- `GET|HEAD|OPTIONS` 放行；loopback 写请求无 token 保持。
- 远程写从 `X-FBM-Dev-Token` 或 Bearer 取 token并常量时间比较。
- 无/空/错 token 在 proxy 前返回 403：`code=REMOTE_DEV_READ_ONLY`、`detail=当前是远程只读访问`。
- 远程转发只添加 `X-FBM-Proxy-Client: remote`，保留原 token，不代注 token。

`main.py::mutating_api_guard()` 对 socket 非本机，或本机 socket 带 remote marker 的写请求，都再次校验 `API_DEV_TOKEN`。marker 只能收紧权限，不能授权；XFF 永不用于本机判断。

### 6.3 真实多进程 harness

新增 `scripts/test_stability_repair_r1_remote_guard.py`：

该 harness 直接启动 Vite/FastAPI 子进程，不经 `scripts/start.sh`；只有这样才能在测试中故意构造 A≠B。生产启动仍必须遵守 start.sh 的非空且一致 fail-fast。

1. 启动真实 FastAPI 子进程，bind 到确定的非 loopback 本机地址，挂载仅测试用 mutating probe route并使用生产 `mutating_api_guard`。
2. 在其前启动带原子计数器的 loopback upstream proxy；每次转发计数并继续到 FastAPI。
3. 启动真实 Vite 子进程，bind `0.0.0.0`，target 指向计数 proxy。
4. 自动选择确定的非 loopback 本机地址；找不到则测试失败而非退到 localhost。
5. Vite token=A、FastAPI token=A：远程正确 A 到 upstream count=1，FastAPI probe成功。
6. Vite token=A、FastAPI token=B：远程正确 A 必须通过 Vite到 upstream count=1，但 FastAPI 返回标准 403；这是“后端确实二次校验”的判别性 oracle，不能只测 A=A 成功。
7. 无/空/错 Vite token断言 403 且 upstream/backend count=0。
8. 直接访问非 loopback FastAPI：匿名/错 B 均403，正确 B成功；证明直接后端边界独立存在。
9. 从 `127.0.0.1` 经 Vite无 token写成功；伪造 `X-Forwarded-For: 127.0.0.1` 的远程请求仍拒绝。
10. 单元覆盖 IPv4、IPv4-mapped IPv6、`::1` 和非 loopback IPv6。
11. 使用高熵 fixture secret，扫描 `frontend/dist`、HTML/JS/CSS/source map和浏览器可获取配置/模块响应，均不得出现 secret。

子进程使用随机空闲端口、就绪探针、超时和 finally terminate，日志做 token redact。

## 7. 标准 403 与全量 mutation inventory

`frontend/src/api/index.ts` 的真实 axios response interceptor 识别 status=403 且 `code=REMOTE_DEV_READ_ONLY`，导出 `isRemoteReadOnlyError()`、`apiErrorMessage()`。它只标准化错误并 reject；不 toast、reload、redirect或清状态。

调用页统一：catch 显示 `当前是远程只读访问`；finally 结束 loading；catch 不 reset owner state。

新增 `frontend/scripts/generate-mutation-inventory.mjs`，使用 TypeScript Compiler API AST 做 callsite 级发现：

1. 先解析 `frontend/src/api/index.ts`，识别全部 `api.post|put|patch|delete` mutating client export。
2. 以 `ProductList.tsx`、`ProductDetail.tsx`、`CatalogList.tsx`、`TaskRunCenter.tsx` 为必扫 roots，并递归扫描它们在 `frontend/src/pages|components|hooks` 下的本地相关 import；解析 named/aliased import和实际 `CallExpression`，不能只统计 client定义。
3. 为每个调用生成稳定 `callsite_id = <client_export>|<repo_relative_source>|<enclosing_named_handler>`；同一 handler内同一client多次调用时追加基于 AST 调用顺序的局部 ordinal。禁止使用纯行号，移动无关代码不得改变 id。
4. 同一 client在多个页面、组件或 handler出现时生成多个 owner record，不能合并成一个 client级契约。

生成 `frontend/src/api/mutationInventory.generated.ts` 的 `MutationCallsiteId` union、client/endpoint/method/source/handler表。新增 `frontend/src/api/mutationOwnerContract.ts`，以 `satisfies Record<MutationCallsiteId, MutationOwnerContract>` 为每个 callsite填写：`owner_component, owner_state, loading_state, catch_policy, finally_policy, playwright_case`。

每个实际 mutation 调用通过统一 `runMutationWithUX(callsiteId, operation, owners)` 包装，axios request config携带测试可见但不发往服务端的 `fbmMutationCallsiteId`；wrapper负责把标准403交给页面 catch策略，并在 finally执行登记的 loading clear。AST checker同时验证 callsite位于该wrapper内，owner contract含 catch/finally policy，且对应 state setter/owner引用仍存在。删除任一页面的 catch policy、finally loading clear或wrapper关联，`contracts:check` 必须失败。

inventory 必须覆盖当前 API client 的每个 mutating export，包括以下族，不能用“等”省略：商品创建/导入、bulk-start、auto-start-ready-generation、bulk-advance/by-filter、UPC import；模板启停/删除/上传；catalog task/legacy/category/inventory export、ASIN写入/删除、inventory sync、ASIN sync、A+ upload/generate；GIGA sync/background/pull/inventory/price；offline task rerun/pause/resume；task run retry step/run、wake/cancel/mark interrupted；data source create/update/delete；product update/listing images/auto-image retry/competitor search/visual retry/confirm/delete/refresh/restart/retry/run-from-step/resume/step/pause/file open/extract；A+ regenerate/retry/generate；config patch。

四个 R1页面的 owner基线：

| 页面 | mutation族 | loading owner | 必须保留的 owner state |
|---|---|---|---|
| ProductList | workflow retry/resume、批量推进、删除 | `rerunningId`及对应批量/delete loading | 筛选、分页、选中行、当前数据 |
| ProductDetail | workflow action、保存、restart/pause/resume、A+ generate/regenerate | 各 mutation loading | 表单字段、A+草稿、已加载 detail/tab |
| CatalogList | export、模板、ASIN、inventory/A+任务 | `exporting/templateUploading/templateFileMutatingId`及对应 loading | `selectedIds/selectedItemMap`、筛选、待上传文件 |
| TaskRunCenter | retry、wake、cancel、mark interrupted | `retryingId/actingRunId` | filters、expanded rows、details cache |

其余 owner组件也必须在 generated inventory中有相同字段。coverage gate固定比较四个集合并要求完全相等：`AST discovered callsite_ids == owner contract ids == static catch/finally verified ids == runtime/Playwright observed ids`。Playwright可按共享参数化 case执行，但每个 callsite都必须实际触发并上报自己的 id；同一client的多个owner必须分别出现。每种状态容器 form、draft、selection、detail cache、loading至少一例经真实标准403验证统一文案、loading结束和状态保留，不得只测 interceptor helper。

## 8. 测试数据库隔离

新增 `scripts/testing/r1_mysql.py`，所有 R1 DB focused test 必须使用：

1. 从显式 `R1_TEST_MYSQL_ADMIN_URL` 连接测试 MySQL；不默认复用应用 `DATABASE_URL`。
2. 生成并校验库名 `fbm_pipeline_r1_<pid>_<random>`；不匹配前缀立即拒绝 CREATE/DROP。
3. 创建专用 database/schema；在任何 `app.*` import 前设置 `DATABASE_URL`、临时 `DATA_DIR`、关闭真实外部调用/OSS。
4. 调用应用 schema 初始化；只写该库与临时目录。
5. finally 关闭连接并 DROP 专用库；`R1_KEEP_TEST_DB=1` 仅保留用于诊断并打印库名，不打印密码。

测试进程启动后断言 `settings.DATABASE_URL` 的 database name 等于生成库名；否则 fail fast。禁止对配置业务库 truncate、delete、backfill或创建 fixture。

新增 `scripts/testing/run_with_r1_mysql.py -- <command...>`：父进程先创建专用库和临时 DATA_DIR，再把覆写后的 `DATABASE_URL`/安全环境传给完整子进程树，command退出后关闭测试engine并DROP库。canonical 公开输入只接受字面 argv `make test-project-rules`；绝对/相对 make 路径和其它 argv 都是 generic command。canonical 输入必须改写为经 `resolve(strict=True)` 和 executable 检查的 `/usr/bin/make`（fallback `/bin/make`），固定执行 `-C <repo> -f <repo>/Makefile test-project-rules`，不得使用 caller PATH 或 caller 提供的 make executable。

generic child 启动前必须清除 marker path/nonce/command id 环境；只有 trusted canonical child 获得一次性 64 字符 nonce、实际 database name/check、`make:test-project-rules:v1` command id 和 wrapper active。显式 fake make 即使尝试写 marker也拿不到 secrets且不得输出 VERIFIED；PATH 前置 fake make 时，字面 canonical 输入必须绕过 fake 并执行 trusted system make。markerless/wrong nonce/db/command 返回 3，找不到 executable 返回 127。`make test-project-rules` 必须通过该 wrapper完整运行；若发现某用例绕过环境或无法隔离，实施前置就是拆分/改造该用例使其继承环境，AC-5不允许跳过。

命令固定为：`python3 scripts/testing/run_with_r1_mysql.py -- make test-project-rules`。wrapper及其helper不得 import `app.*` 后才覆写环境。

## 9. 跨层验收矩阵

### 9.0 单一 E2E orchestrator

新增 `scripts/testing/run_r1_e2e.py` 作为唯一跨层入口：

1. 复用 `r1_mysql.py` 创建一个专用 MySQL database和临时 DATA_DIR，在任何 app import前导出环境。
2. 用 seed子进程一次写入 workflow、六类 catalog fixture、四类 TikTok fixture和四页面 mutation所需数据。
3. 启动真实 FastAPI与真实 Vite；Vite bind `0.0.0.0`，FastAPI/Vite URL、确定的非 loopback访问地址、token和fixture ids写入临时 `r1-e2e-state.json`。
4. 启动 `npx playwright test --config frontend/tests/playwright.r1.config.ts`，通过 `R1_E2E_STATE_PATH` 传递 baseURL/ids；config的 `globalSetup` 只读取状态和健康检查，不另建DB或mock API。
5. Catalog/TikTok页面禁止 `page.route()`/HAR mock；必须连接上述实际 API。ProductList、ProductDetail、CatalogList、TaskRunCenter 的403用例都从非 loopback baseURL经过真实 Vite guard。
6. Playwright结束后 finally依次终止 Vite/FastAPI、释放 seed/测试engine、清理临时目录、DROP专用库；任何阶段失败也执行相同 teardown。

Playwright config不得自行启动第二套 webServer，避免数据库、端口和token事实源分裂。

### 9.1 Catalog export

`scripts/test_stability_repair_r1_catalog_export.py` 必须运行真实 planner→worker→scheduler，落隔离 MySQL，并通过真实 API读取：

测试只 fake `backend/app/task_runtime/catalog_export_workers.py` 已导入的 `upload_private_file` 外部边界：fake返回确定 object key/url、记录调用次数，并配合出站socket guard断言网络请求为0。真实 planner、`build_catalog_export_zip()`、report workbook、worker、canonicalizer、TaskWorkerOutcome projector、scheduler、DB和API一律不得 mock；download优先读取真实临时本地 zip。

| fixture | payload/run | artifact | 必验 |
|---|---|---|---|
| 全成功 | done/succeeded | 有 | rows/report/count 全一致 |
| 混合 | partial/partial | 有 | 可下载、partial filter命中 |
| 零成功 | failed/failed | 无 | 业务 envelope、不可下载 |
| 缺失报告行 | partial或failed | 按成功数 | 自动补 failed row，不变量成立 |
| 旧 succeeded+summary partial | effective partial | 有 | current 命中、history/succeeded 排除、items/count一致 |
| raw succeeded + material unsafe row | effective failed | 无 | current/failed 命中，history/succeeded 排除，items/count/page一致 |
| raw failed/succeeded + no material | 保持 raw | 按 raw | projection 不制造新的业务 outcome |
| invalid newer + older valid material | older outcome | 按 older | TaskRun/OfflineTask、download、Export Files/Categories 一致回退 |
| invalid-only succeeded/done | 保持 raw | 无 | 不制造 authoritative failed、不可下载 |
| raw interrupted/canceled/paused + material done | 保持 raw | 不授权 | Task Center 保持 raw，Export Files/Categories 排除 |
| raw failed + safe material done | effective succeeded/done | 有 | Export Files/Categories 出现且可下载 |
| 已有混合 zip恢复 | partial | 有 | 不重建为 succeeded，报告与 rows一致 |

API 验证 `status/display_status/catalog_export_result`、current/history、两页分页、`base_total/filtered_total/total`、partial/failed/succeeded 筛选、download 200/拒绝和 Export Center rows。Playwright 连接实际 FastAPI/Vite/MySQL，核对 unsafe TaskRun/OfflineTask 的外层 failed、表格标签、failed-current 与 succeeded-history count/page、结果计数/原因和下载按钮；禁止 mock worker/canonicalizer/projector和页面 route。

### 9.2 TikTok

同一隔离 DB fixture矩阵驱动 `GET /api/tiktok/products/{id}`、`GET /api/products` 和两个页面：

| fixture | expected |
|---|---|
| source failed | failed |
| 无 SKU | draft |
| 缺采购价或分仓库存 | missing_required_info |
| 当前字段完整 | unsupported |

验证 route/detail/ProductList 标签文案一致；list filter/count/page一致；unsupported 无导出、发布、Amazon Export Center CTA。任何层出现 `export_ready/待 TikTok 导出` 均失败。

### 9.3 命令

```bash
(cd backend && R1_TEST_MYSQL_ADMIN_URL='mysql+asyncmy://.../' .venv/bin/python ../scripts/test_stability_repair_r1_workflow_actions.py --with-mysql)
(cd backend && R1_TEST_MYSQL_ADMIN_URL='mysql+asyncmy://.../' .venv/bin/python ../scripts/test_stability_repair_r1_catalog_export.py)
(cd backend && R1_TEST_MYSQL_ADMIN_URL='mysql+asyncmy://.../' .venv/bin/python ../scripts/test_stability_repair_r1_tiktok.py)
R1_TEST_MYSQL_ADMIN_URL='mysql+asyncmy://.../' python3 scripts/testing/run_r1_e2e.py
python3 scripts/test_stability_repair_r1_remote_guard.py
make backend-compile
make frontend-build
R1_TEST_MYSQL_ADMIN_URL='mysql+asyncmy://.../' python3 scripts/testing/run_with_r1_mysql.py -- make test-project-rules
```

测试不得触发真实 Amazon、TikTok、GIGA、领星、OSS、A+，不得改模板或真实业务库。

## 10. 发布、兼容与回滚

发布顺序：共享 manifest/TikTok projector/catalog predicates与 envelope → 后端 API/guard → Vite guard/interceptor → 页面 → focused tests。先 loopback 回归，再运行远程多进程 harness。

无 schema/data migration。新 catalog run持久化正确三层状态；旧合法 summary 用 effective predicate兼容；invalid/null summary回退 raw status。回滚按同一提交整体回滚，不删除已有 zip、商品、ASIN或任务。

若远程 guard异常，恢复 loopback监听，不放宽后端 guard。实现后同步更新 `docs/project-index.md`、`docs/domain-index/product-flow.md`、`task-runtime.md`、`runtime-security.md`、`frontend-pages.md`。

## 11. 非目标与残余风险

非目标：真实 Amazon listing detail、TikTok 类目/导出/发布、runtime lease/heartbeat/outbox/projection retry、数据库迁移、Amazon模板/mapping/Step 10、真实外部副作用。

残余风险：summary损坏且仅剩 zip 的旧 run只有在显式恢复路径中才能重建 outcome；R1不扫描或 backfill 全库。远程模式仍是开发期单 token边界，不是账号、RBAC或生产网关。
