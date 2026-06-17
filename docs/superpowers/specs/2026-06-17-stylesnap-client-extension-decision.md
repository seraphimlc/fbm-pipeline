# StyleSnap Client Extension Decision Note

状态：决策记录；当前只记录，不进入实现。
更新：2026-06-17
负责人：若命
关联：`MSG-20260617-020`

## 1. 一句话结论

搜索竞品 / StyleSnap 图片搜索的长期合理方案是 Chrome 客户端插件模式，而不是继续强化后端 AppleScript 控 Chrome。

本事项当前 on hold，不给听云派工。后续如果启动，若命必须先写完整 PRD 和分阶段任务，再交听云执行、镜花 code review、观止 QA。

## 2. 背景

当前实现大体是：

- 前端点击搜索候选。
- 后端接口修改商品状态，并通过后台动作控制本机 Chrome。
- 后端通过 AppleScript/JS 打开 Amazon StyleSnap 页面。
- 后端读取页面里的 `stylesnap` token。
- 后端在 Chrome 页面上下文里执行 `fetch('stylesnap/upload?stylesnapToken=...', { credentials: 'include' })`。
- 结果解析后写入候选竞品表。

这个方案能跑，但它把后端、用户 Chrome、Amazon 页面、登录态、token 和商品状态绑在一起，长期不稳。

## 3. 已确认的产品判断

### 3.1 不要做过渡方案

用户明确不需要“过渡方案”。如果后端控制 Chrome 不是长期最合理方案，就不要继续在这条路上堆队列、线程、恢复和复杂状态。

### 3.2 StyleSnap token 不应由后端持久管理

当前没有可靠证据证明 StyleSnap token 是一次性、可长期复用，或有稳定公开 API 语义。

合理边界：

- 不把 token 存数据库。
- 不把 Amazon cookie 存后端。
- 不假设一次 token 可以支撑批量搜索。
- 每次搜索在浏览器上下文里检查和使用当前可用 token。

### 3.3 普通前端页面不适合直接执行 StyleSnap 搜索

普通 React 前端运行在本地应用域，不能稳定读取 `amazon.com` 页面 token，也不能自然携带 Amazon 页面 cookie 跨域上传。

因此“前端做”如果成立，应是 Chrome Extension / userscript 这类浏览器上下文方案，而不是普通 Web 页面直接做。

## 4. 推荐方案：Chrome 客户端插件

### 4.1 插件职责

插件运行在 Amazon 页面上下文中，负责：

- 检查 Amazon 登录态。
- 检查/读取 StyleSnap token。
- 从本地后端拉取待搜索商品和主图 URL/图片数据。
- 上传主图到 StyleSnap。
- 读取或解析 StyleSnap 返回候选。
- 将候选结果或错误回传本地后端。
- 批量搜索时在插件侧串行执行，避免多个搜索互相抢页面/token。

### 4.2 后端职责

本地后端只负责：

- 提供待搜索商品。
- 接收插件回传的候选结果。
- 接收插件回传的错误。
- 写入候选竞品表。
- 更新商品业务状态。
- 提供商品列表/详情/竞品确认页面展示。

后端禁止：

- 保存 Amazon token。
- 保存 Amazon cookie。
- 继续通过 AppleScript 控制 Chrome 作为长期方案。
- 把 StyleSnap 搜索包装成可恢复任务中心任务。

### 4.3 商品状态口径

StyleSnap 搜索仍是商品流程中的竞品搜索节点，但不进入任务中心。

商品侧关注：

- 待获取 StyleSnap token。
- 待搜索竞品。
- 竞品搜索中。
- 竞品搜索失败。
- 待选择竞品。

商品侧不展示：

- token 是否过期的技术状态。
- 插件内部队列状态。
- Amazon 请求细节。
- queued/running/canceled/interrupted 这类任务状态。

## 5. 为什么不选后端 AppleScript 方案

后端 AppleScript 控 Chrome 的问题：

- 依赖本机 Chrome 配置和 Apple Events JS 权限。
- 依赖 Amazon 页面结构和 token DOM。
- 后端与用户浏览器状态耦合过强。
- 服务端部署、集群、多用户场景都不自然。
- 并发或批量时需要额外做本地队列和状态一致性，复杂度会继续扩大。
- 容易让人误以为这是稳定后台任务，但很多失败本质上需要用户处理浏览器状态。

结论：它可以作为历史实现事实存在，但不作为下一轮产品设计方向继续加固。

## 6. 如果未来启动插件方案

若未来启动，必须先由若命补完整 PRD，至少包括：

- 插件 manifest 权限。
- content script 与 background service worker 分工。
- 插件与本地后端通信协议。
- 待搜索商品 API。
- 候选结果回传 API。
- 错误码与商品状态映射。
- 批量搜索串行策略。
- 用户登录/token 缺失处理。
- 安全边界：token/cookie 不落后端。
- 迁移现有 `backend/app/services/amazon_stylesnap_search.py` 逻辑的取舍。
- 镜花 code review 清单。
- 观止真实 Chrome 插件 QA 用例。

听云不得只凭本决策记录直接实现插件。

## 7. 当前处理

当前仅记录决策，不继续推进。

商品流程同步/半同步/异步节点定义另见：

- `docs/superpowers/specs/2026-06-17-product-workflow-node-state-prd.md`
