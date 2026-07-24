# FBM Pipeline 稳定性修复 R1 PRD

状态：READY_FOR_TECHNICAL_DESIGN；清秋 UX 校验与观止可测性校验已通过
日期：2026-07-22
Owner：若命（agentKey: `ruoming`）
后续执行：听云（技术方案与实现）/ 镜花（独立评审）/ 观止（QA）/ 清秋（UX 验收）

## 1. 决策摘要

本轮只修复四类会让用户得到错误结论或执行无效操作的问题：

1. 商品 workflow 返回前端无法执行的竞品详情失败动作。
2. Amazon 导出部分失败时任务中心仍显示成功。
3. TikTok 尚无导出能力却显示 `export_ready / 待导出`。
4. 远程暴露 Vite 前端时，代理请求可能被后端误认为本机可信写请求。

本轮保留本地浏览器能力。Amazon 搜索页 Chrome adapter、卖家精灵登录态和领星网页登录态仍作为可选能力存在；不在 R1 删除或替换。

R1 的价值不是打通所有真实外部平台，而是保证：页面状态不说谎、按钮确实可执行、部分失败不会伪装成功、远程模式不会绕过写接口保护。

## 2. 用户与价值

目标用户：在本机运行 FBM Pipeline 的单一运营操作者。

用户需要可靠回答四个问题：

- 当前能力是否真的可用。
- 当前任务是全部成功、部分成功还是失败。
- 页面给出的按钮点击后是否能执行对应动作。
- 将前端临时开放到局域网时，匿名访问者是否能修改数据或创建任务。

## 3. 已确认事实与假设

### 3.1 Confirmed

- 当前产品定位仍是本地单操作者工具，默认监听 loopback。
- 本地浏览器能力保留，不作为本轮退役对象。
- `capture_competitor_detail/failed` 会返回 `retry_competitor_capture`，但当前前端没有可执行实现。
- 当前真实 Amazon listing detail adapter 未配置；R1 不宣称真实详情链路可用。
- catalog export payload 可以表达 `partial_failed`，但新任务 runtime 会把正常返回的 worker 统一标记为 succeeded。
- TikTok 当前只有商品详情读取，没有独立导出或发布 API。
- Vite `/api` proxy 会让后端看到代理连接来源，而不是原始浏览器来源。

### 3.2 Assumed

- R1 不改变现有真实商品、ASIN、模板、导出文件和外部平台状态。
- R1 可以调整 API 展示字段、workflow action、任务 outcome 投影、前端状态文案和本地远程访问配置。
- 后续 R2 会处理 task runtime lease、projection retry、幂等与崩溃恢复；这些不混入 R1。

## 4. 范围

### R1-A：竞品详情失败状态必须诚实且可处理

当商品位于候选详情抓取或自动选竞品失败节点，而当前没有可执行的真实详情重试能力时：

- 后端不得返回 `retry_competitor_capture` 等未实现 action。
- 主动作统一为当前确实可执行的诊断入口：打开关联任务中心；如果缺少 correlation，则打开商品详情。
- 用户可见文案必须明确区分：
  - `adapter_not_configured`：能力未配置，不是偶发运行失败。
  - 其它运行失败：任务执行失败，可在任务中心查看原因。
- 能力未配置文案：`当前版本尚未接入真实 Amazon 详情抓取，本商品已停止自动推进。`
- 其它未知失败默认只允许查看任务，不推断可以重试。
- `restart_competitor_search` 只允许出现在现有 API 确实接受的 workflow 节点；R1 不为候选详情/自动选竞品失败节点发明新的 destructive reset 语义。
- 页面不得显示“重新抓取”按钮，除非对应 API、前置条件和恢复语义已经真实存在。
- 未知 action 不能静默消失；开发/测试环境至少应产生可检测的降级提示或契约失败。

R1 不实现真实 Amazon listing detail adapter，不把 fixture 成功当作真实能力。

### R1-B：导出 outcome 与任务状态一致

Amazon 导出任务必须区分：

- `succeeded`：请求中的可处理商品全部成功，且没有失败/跳过导致的不完整结果。
- `partial_failed`：已经生成可下载产物，但至少一个商品失败或被业务保护门跳过。
- `failed`：没有形成可用导出产物，或任务级错误导致本轮导出不可用。

用户行为：

- `partial_failed` 任务仍可下载已生成文件和报告。
- 任务中心与导出中心必须显示成功、跳过、失败数量。
- `partial_failed` 必须可被任务中心对应筛选发现。
- 页面不得用统一“任务完成”覆盖部分失败原因。
- 本轮不定义自动重试策略；用户至少能看到失败 rows 和原因。

### R1-C：TikTok 不再显示虚假导出就绪

TikTok 商品资料完整但导出能力未接入时：

- API 状态使用 `unsupported`，含义是“当前已接入的数据字段完整，但渠道导出/发布能力尚未实现”。
- 页面标签显示“资料已齐 · 导出暂未接入”。
- 页面同时显示说明：“TikTok 导出/发布尚未接入”。
- 不显示导出、发布或跳转 Amazon 导出中心的动作。
- `data_ready` 不代表类目、平台规则、图片规范或发布资格已经校验。

保留状态：

- `draft`：没有可展示 SKU。
- `missing_required_info`：当前已接入字段仍缺采购价或分仓库存。
- `failed`：来源商品处于失败状态。

R1 不实现 TikTok 类目、导出或发布能力。

### R1-D：远程前端模式不得绕过写接口保护

访问口径：

- 默认本机 loopback 模式保持可用，不要求用户额外输入 token。
- 用户显式将前端开放到非 loopback 地址时，远程页面默认是只读模式。
- 远程浏览器通过 Vite proxy 发出的 mutating API 请求必须在 proxy 层校验请求携带的有效 token；无 token、空 token 或错误 token 必须在转发前返回 403，后端调用次数为 0。
- R1 不新增 token 持久化或自动注入 UI；token 不得由 Vite 无条件代所有远程访问者注入，否则等同于匿名放行。
- 如果调用方显式携带正确 Header/Bearer token，proxy 可以转发并由后端再次验证。
- 直接访问后端的非本机 mutating 请求仍必须提供有效 token。
- token 不得写入前端 bundle、页面源码、日志或 API 错误详情。

只读 API 仍按当前边界开放；R1 不建设完整账号、RBAC 或多租户系统。

## 5. 主流程与异常流程

### 5.1 商品竞品详情失败

```text
详情抓取失败
→ workflow 返回能力未配置或运行失败的真实原因
→ 主动作进入关联任务中心/商品详情
→ 不显示不存在的“重新抓取”
```

### 5.2 Amazon 导出部分失败

```text
用户提交多个商品
→ 部分商品成功写入文件
→ 部分商品因真实 ASIN/模板/字段问题失败或跳过
→ 任务状态 partial_failed
→ 用户可下载产物与报告，并看到逐商品结果
```

### 5.3 TikTok 资料完整

```text
采购价与分仓库存完整
→ 状态 unsupported / 资料已齐 · 导出暂未接入
→ 显示“导出/发布尚未接入”
→ 无导出动作
```

### 5.4 远程前端访问

```text
FRONTEND_HOST 非 loopback
→ 无 token 的 mutating 请求由 proxy 直接 403
→ 正确 token 请求才允许转发
→ 后端再次验证 token
```

## 6. 非目标

- 不删除本地 Chrome/AppleScript 支持。
- 不实现真实 Amazon listing detail adapter。
- 不实现 TikTok 导出、发布、类目校验或库存分仓业务规则。
- 不重构整个 task runtime，不处理 lease、heartbeat、runner kick、projection retry 或 outbox。
- 不解决导出并发幂等和崩溃恢复；归入 R2。
- 不建设登录、RBAC、多租户或生产网关。
- 不修改 Amazon 模板、`template_mappings`、Step 10 字段填充规则。
- 不覆盖或重建真实商品、人工类目、真实 ASIN、素材、历史任务和导出文件。
- 不触发真实 GIGA、Amazon、SellerSprite、Lingxing、OSS、A+ 或其它外部副作用。

## 7. 验收标准

### AC-1 Workflow action 闭包

- 针对所有正式 workflow `primary_action/allowed_actions`，测试证明前端存在执行、导航或明确禁用呈现。
- `capture_competitor_detail/failed` 不再返回 `retry_competitor_capture`。
- `adapter_not_configured` 页面可见文案包含“能力未配置”语义。
- 构造未知 action 时，测试必须失败或页面出现明确降级信息，不能静默无按钮。
- 自动闭包 oracle：`backend_action_set - frontend_handler_or_navigation_set = ∅`；API 型 action 还必须存在对应 route 和 API client。
- action 成功必须创建或复用正确任务并进入预期 workflow；前置不满足时不得误改 workflow 和既有任务事实。

### AC-2 导出状态一致性

- 全成功样本：API、任务中心、导出中心均为 succeeded，计数一致。
- 部分失败样本：三处均为 partial_failed，产物仍可下载，逐商品原因可见。
- 全失败/无产物样本：三处均为 failed，下载入口不可用。
- `partial_failed` 筛选能找到部分失败任务。
- 共同计数 oracle：`requested_count = success_count + skipped_count + failed_count`，且 `rows[]`、API 计数与 zip 报告一致。
- 已有混合结果 zip 的恢复展示不得降级为 succeeded。

### AC-3 TikTok 状态真实性

- 资料完整样本返回 `unsupported`，页面显示“资料已齐 · 导出暂未接入”和“当前版本暂不支持 TikTok 导出或发布；不会生成文件，也不会提交到平台”。
- 缺采购价或分仓库存样本仍为 `missing_required_info`。
- 页面不存在 TikTok 导出/发布按钮，也不跳转 Amazon 导出中心。

### AC-4 远程写保护

- 默认 loopback 本机前端仍能执行写请求。
- 非 loopback 前端的 proxy 写请求无 token、空 token或错误 token时返回 403，且未到达后端。
- 请求显式携带正确 token 后，远程 proxy 写请求可以通过，并由后端再次验证。
- 直接远程后端匿名写请求返回 403。
- 伪造 `X-Forwarded-For: 127.0.0.1` 不能改变拒绝结果。
- 前端构建产物和浏览器可见配置中不包含 token。
- 页面收到该 403 时显示“当前是远程只读访问”，结束 loading，但不清空表单、草稿或现有页面数据。

### AC-5 回归与安全边界

- `make test-project-rules`、相关 focused tests、`make backend-compile`、`make frontend-build` 通过。
- 不产生真实外部请求，不修改真实业务数据或模板。
- 对应 `docs/project-index.md`、`docs/domain-index/product-flow.md`、`docs/domain-index/task-runtime.md`、`docs/domain-index/runtime-security.md` 按实际变化更新。

## 8. 禁止的假通过证据

- fixture Amazon detail 成功不能证明真实详情能力可用。
- 仅检查 payload 内有 `partial_failed`，不能证明任务列表/API 状态正确。
- 仅修改 TikTok 标签文案，后端仍返回 `export_ready`，不能验收。
- 仅证明直接远程请求被拒绝，未覆盖远程浏览器经 Vite proxy 的请求，不能验收。
- 仅做字符串扫描而没有状态/action 行为断言，不能验收。

## 9. 下游交付门禁

1. 清秋确认状态、文案、动作和异常路径可理解。
2. 观止确认验收矩阵能发现四类假通过。
3. 若命将本文更新为 `READY_FOR_TECHNICAL_DESIGN`。
4. 听云基于固定版本 PRD 写技术方案，不能自行扩展 R2。
5. 镜花独立评审技术方案；观止评审可测试性。
6. 只有评审结论不存在 P0/P1/P2 finding 时才允许修改代码。

## 10. 后续里程碑

- R2：task runtime projection recovery、lease/heartbeat、pending kick、导出幂等与崩溃恢复。
- R3：真实 Amazon listing detail adapter 或完整人工详情确认路径。
- R4：状态/类型收敛、模块拆分、版本化 migration、测试和可观测性。
