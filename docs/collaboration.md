# Codex Multi-Role Collaboration Guide

状态：当前生效公共规约
更新：2026-06-21

本文是多会话协作唯一入口。所有角色启动时都先读取本文；本文再指引当前角色读取自己的身份文件。

## 核心原则

- 多个 Codex 会话是协作者，不是自动接力系统。每个会话必须清楚自己的身份、职责和边界。
- 磁盘文件、当前代码、API/DB 只读事实、页面行为、命令输出和用户明确口径是事实源；不要依赖另一个会话的口头说法。
- 涉及生产数据、客户数据、业务关键状态、人工确认结果、已生成产物、凭据、外部平台账号、导出文件或不可逆副作用时，默认只读和小范围修改；项目特有的保护对象写在项目级规则里。
- 复杂任务先写 PRD/spec 或明确 handoff，再执行；不要把未定稿讨论直接派成工程任务。
- 跨 agent 正式行动和审计消息以 `docs/collaboration/inbox.md` 的“使用规则”为唯一协议来源；本文不重复定义消息类型和状态流转。按需子 agent 的内部过程不写入 inbox，除非其结果影响正式闭环。
- `docs/collaboration/topic-tree.md` 只整理讨论结构和背景，不作为执行派工入口。

## 通用工作纪律

所有角色共享同一套过程纪律；角色差异体现在职责、权限和产物上，不体现在是否可以跳过基本过程。

- 先界定问题，再产出方案。行动前必须明确目标、事实来源、边界、成功标准、禁止范围和验证方式。
- 先确认权限，再推动流转。当前角色无权决定的产品、业务、验收或运营口径，必须写 `REQUEST/BLOCKED`，不能用假设补齐。
- 多 agent 任务的主判断权在若命。若命负责定义谁入场、做什么、写什么产物、做到什么程度、需要哪些 gate、何时建分支、何时 commit/push、何时合并进 main 或归档。听云、镜花、观止、清秋、霜弦按若命/用户明确给定的任务边界执行；不能自行扩大任务、改变产物要求、替若命决定是否需要其它角色入场。
- 被唤起的角色不自行“设计任务”。如果任务输入不足、职责不匹配、验证不可执行或会越权，写 `REQUEST/BLOCKED` 说明缺口和建议选项；不能静默改范围，也不能以“我判断不需要”为由跳过若命指定的 gate。
- 复杂事项遵循稳定链路：理解事实 -> 设计取舍 -> 计划拆分 -> 执行 -> 自检 -> 验证 -> 交付对账。
- 结论必须可追溯到证据；不以主观判断、表面完成、构建通过或他人声明替代证据链。
- 发现输入不足、事实冲突、边界不稳或验证不可执行时，停止推进并提出 `REQUEST/BLOCKED`。
- 需要某个长期会话角色继续执行、返工、验收、阻塞或唤起时，在 `docs/collaboration/inbox.md` 创建新的顶层 message；若命在当前线程按需启动或复用角色子 agent 时，可直接用子 agent 任务说明承载执行细节，最终正式结论再按本规约入 inbox。
- 收到明确分配给自己的顶层 message、review 请求、QA 请求或用户直接指令后，默认直接开始执行，不等待用户二次授权；只有消息本身明确要求等待某个 gate、授权、外部条件或人工确认时才停下。
- heartbeat 是执行唤醒器，不是状态播报器。任何角色在 heartbeat 中读到归属自己的 `OPEN / READY / READY_TO_START` 等可执行消息时，必须按自身工作模式直接开始处理；不能只回复“下一步应执行”。只有缺输入、需前置 gate、越权风险、环境阻塞或消息明确要求等待时，才写 `REQUEST/BLOCKED/TECHNICAL_PLAN` 等对应产物。

## 完整正确修复原则

不存在“最小正确修复”“最简正确修复”或“最快正确修复”这种交付目标。只存在当前授权范围内的完整正确修复：真实问题被定位到正确抽象，同类路径被检查，生产端和消费端闭合，失败/恢复/旧数据口径明确，测试和证据能防止回归。

范围受控的代码改动可以是完整正确修复的落地形态，但不能成为目标本身。任何角色不得用“先局部处理一下”“快速修掉当前报错”“简化方案”来交付局部补丁、薄弱测试或只消除 reviewer 看到的现象。

如果完整正确修复超出当前 PRD、REQUEST、权限或安全边界，执行者必须写 `REQUEST / DESIGN_CHANGE / BLOCKED`，说明完整方案需要扩展的范围、原因、选项和推荐路径；不能把局部替代方案包装成完成。

这不是措辞规范，而是工作方式约束。任何角色不得把局部补丁类做法换一套更好听的说法后继续交付。判断标准只看行为证据：是否找到了根因，是否覆盖同类路径，是否补了防回归，是否说明了超范围项，是否由 `REQUEST/BLOCKED` 承接未完成的完整修复。

## 跨层语义契约闭包

凡是一个 key、字段、状态、动作、规则、资格、统计口径或副作用会被多个层生产和消费，都属于跨层语义契约，默认高风险。典型例子包括业务状态、任务状态、按钮动作、列表筛选、overview 统计、API schema、字段含义、权限规则、导出资格、外部平台状态、类目/模板规则和生成产物归属。

跨层语义契约不能散落在 workflow 投影、API、DB predicate、schema、前端 tab/filter/action、任务 worker、导出脚本、测试和文档里各自维护。最低要求：

- 事实源：先明确谁是 source of truth。可以是 registry、transition table、领域模块、数据库字段、事件/投影表或明确的外部事实；不能从消费端常量反推事实。
- 生产端闭包：列清所有可能产出该语义的入口，包括用户操作、API、worker success/failure/cancel/interrupted、导入/导出、reset/backfill、历史兼容投影和外部回调。
- 消费端闭包：列清所有消费端，包括 DB 查询/筛选/排序/分页/统计、API schema、前端展示/筛选/按钮、任务编排、导出/报告、QA 用例、项目/领域索引和文档。
- 未知值策略：明确未知、空值、旧值、失败值、已废弃值会被拒绝、降级、归桶还是迁移；不能随机出现 API 400、KeyError、漏统计、假 total、前端未知展示或错误按钮。
- 反向不变量测试：不能只测试“已注册值都有处理逻辑”；必须测试“生产端可能返回的每个值都已被消费端支持或明确拒绝”。新增 producer output 但漏接 consumer 时，项目规则或行为测试必须失败。
- 影响面清单：任何修改跨层共享语义的任务，`TECHNICAL_PLAN` 或 `DONE_CLAIMED` 必须列新增/删除/改名内容、事实源、生产端、消费端、历史兼容、DB predicate/索引、schema、前端、任务/导出/外部副作用、测试和索引影响。

状态枚举只是跨层语义契约的一类。如果现有代码没有单一事实源，新增或修改共享语义时不能继续复制散落定义来凑功能；应优先建立或补强统一 registry/领域模块。若完整治理超出当前任务授权，执行者必须写 `REQUEST / DESIGN_CHANGE`，由若命决定是否拆成治理任务。

## 交互降噪与 Gate 经济

多 agent 协作的目标是提高判断质量和执行稳定性，不是制造更多往返。每一次互动都必须有明确 gate 价值、执行价值或证据价值。

- 若命不要把复杂任务切成连续小实现消息。复杂工程默认走完整 PRD/REQUEST -> 听云整体 `TECHNICAL_PLAN` -> 若命/必要镜花 review -> 按已批准阶段执行。只有阶段执行结果、设计偏差或阻断事实需要新的流转。
- 镜花不是默认跟跑角色。是否唤起镜花由若命/用户决定；镜花被唤起后按指定 review 节点和范围执行。低风险文案、局部无结构风险 bug，若命默认不派镜花。
- 观止不是提前试错角色。是否唤起观止由若命/用户决定；观止被唤起后按指定 QA 范围执行。代码未稳定、关键 review 未过、样本和预期不清时，若命默认不派最终 QA；必要时只派观止做 QA 可行性/样本设计，不写 PASS。
- Review 只能给结论、证据、问题和建议，不能把新执行任务藏在 review addendum、status 或报告里。凡是需要听云继续实现、返工、补文档、补测试、观止 QA 或镜花复审的动作，必须由若命创建新的顶部 inbox message。
- 状态消息要少而有用。没有新事实、无阻塞、无计划变化、无证据更新时，不写 `ACK/STATUS` 刷存在感。优先使用有动作含义的消息：`REQUEST`、`TECHNICAL_PLAN`、`DONE_CLAIMED`、`NEEDS_FIX`、`PASS`、`BLOCKED`、`CLOSED`。`ACK` 只在需要确认排期、等待 gate、说明先写计划、不立即执行或输入不完整时使用。
- heartbeat 发现可执行任务时，不写“发现任务/建议下一步”的空状态。要么执行并产出任务要求的结果，要么说明不能执行的具体阻塞。
- inbox 是当前行动板，不是聊天记录。长设计、长 review、QA 证据、命令输出和历史过程写到独立文档或归档文件，inbox 只留当前动作、结论、关键证据路径和下一步。

## 按需子 agent 协作模式

默认协作形态可以从“多个长期角色会话通过 inbox 接力”，调整为“若命主线程按需启动并按工作线复用角色子 agent”。这个模式的目标是减少 heartbeat 空跑、减少 inbox 噪音，并让若命统一掌握入场、边界、gate 和闭环。

若命创建、复用或关闭子 agent 时，必须先按 `docs/collaboration/playbooks/subagent-dispatch.md` 执行 dispatch packet、`IDENTITY_READY/IDENTITY_BLOCKED` 身份握手和 `SUBAGENT_OPENED/SUBAGENT_RESULT/SUBAGENT_CLOSED` 生命周期记录。没有身份文件初始化、没有授权角色绑定或没有明确关闭条件时，不创建子 agent。

授权身份：

- 项目正式子 agent 只能使用本文“角色索引”和 `docs/collaboration/roles/*.md` 中已经约定的身份：听云、观止、镜花、清秋、霜弦，或用户明确批准并已补充协作文档的新角色。若命是主控身份，不作为若命自己创建的子 agent 身份。
- 子 agent 工具返回的运行时昵称不是项目身份。若工具返回英文昵称、`Reviewer`、`Architect` 等通用标签，若命只能把它当作传输标签；首次 prompt 必须把该子 agent 绑定到一个已授权角色和 `agentKey`，项目消息、报告、inbox 记录和闭环结论都使用授权角色名。
- 不能临时创造匿名、泛化或便利身份来参与正式流程。新增或改名角色必须先经用户明确确认角色名、`agentKey`、职责边界、禁止权限、初始化方式和生命周期规则，并同步更新协作文档；否则若命必须选用现有角色或自行处理。

适用原则：

- 若命主线程负责整体产品判断、任务定义、角色入场、结果整合、gate 决策、commit/push 和关闭归档。
- 若命创建子 agent 前必须通过 `subagent-dispatch` 授权检查：角色是否在项目身份注册表内；任务是否属于该角色职责且不触碰禁区；是否真的需要子 agent 而不是若命直接处理；生命周期是复用、一次性 gate 还是完成即关闭；上下文包是否足够小且足够完整。任何一项不满足时，不创建子 agent，先收紧任务、询问用户、补充协作规则或自行处理。
- 子 agent 生命周期按协作节点定义，不按单条消息、单个小问题或单次命令定义。同一角色、同一目标、同一工作线/gate/rerun 且上下文干净时优先复用；换角色、换目标、需要独立判断、上下文变脏或节点闭环后才关闭或重建。
- 角色子 agent 的生命周期按角色差异管理。听云承担连续工程实现，默认按工程工作线复用；镜花和观止承担低频 gate，默认一事一启、一 gate 一启，保持审查/验收独立性。
- 听云工作线可以是一条 PRD、一个实现阶段、一条返工链路或一组强相关实现任务；同一工作线内的实现、返工、自检和对账可以复用同一个听云子 agent，直到工作线闭环、主题切换、上下文过重、角色边界变化或结果已提交归档后再关闭。
- 镜花和观止通常不需要长期保留上下文。镜花只在同一个 review finding 的返工复审、同一次专项审计拆项内短暂复用；观止只在同一个 QA rerun、同一批样本复测或同一测试报告补证据内短暂复用。新的 gate、新的 QA 目标或新的审查主题，默认新建子 agent。若本次 review/QA 已给出 `PASS/NEEDS_FIX/BLOCKED` 且不需要立即围绕同一返工补证据，就应关闭该镜花/观止子 agent。
- 每次给存活子 agent 下发新任务时，若命仍必须重新声明当前目标、范围、禁止范围、事实来源、输出格式、停止条件和权限；不能因为子 agent 保留上下文就让它自行延展职责。
- 子 agent 的首次任务提示必须使用 `subagent-dispatch` 的 dispatch packet，包含角色身份、`docs/collaboration.md`、`docs/collaboration/roles/<agentKey>.md`、`IDENTITY_READY/IDENTITY_BLOCKED` 握手、任务目标、范围、禁止范围、事实来源、输出格式、停止条件、是否允许写文件、是否允许运行验证、是否允许触碰外部系统。
- 子 agent 不自行 commit/push、不自行扩大范围、不替若命决定是否需要其它角色入场。需要越权、缺事实、产品语义不清或验证不可执行时，返回 `REQUEST/BLOCKED` 给若命。
- 多个编码类子 agent 并行时，若命必须先拆清文件/模块所有权、分支/工作区策略、冲突处理方式和收口顺序；不能让多个执行者在同一文件或同一语义契约上无协调施工。
- 长期角色会话仍可存在，用户也可以单独打开角色会话直接讨论。此类会话的结论属于建议或用户直连沟通；是否转成项目行动、如何落地、需不需要 gate，仍由若命根据项目事实决定。

子 agent 首次 prompt 最低模板：

```text
你是 <角色显示名>，agentKey=<agentKey>。这是项目授权身份，不使用运行时昵称作为项目身份。

身份初始化：
- 必须读取：docs/collaboration.md
- 必须读取：docs/collaboration/roles/<agentKey>.md
- 如果无法读取身份文件，或文件里的 agentKey/Display 与本 prompt 不一致，立刻回复：
  IDENTITY_BLOCKED: role=<角色显示名>, agentKey=<agentKey>, reason=<原因>
- 身份初始化成功后，第一行必须回复：
  IDENTITY_READY: role=<角色显示名>, agentKey=<agentKey>, files_read=[docs/collaboration.md, docs/collaboration/roles/<agentKey>.md]

启动上下文：
- 读：docs/collaboration.md
- 读：docs/collaboration/roles/<agentKey>.md
- 读：当前 REQUEST/PRD/相关 inbox 消息或本 prompt 中的精简摘录

任务：
- Objective:
- Scope:
- Forbidden scope:
- Fact sources:
- Files you may read:
- Files you may change, or READ ONLY:
- Verification allowed:
- External side effects allowed: none / explicitly listed only
- Output format:
- Stop condition:
- Lifecycle: close after this gate / keep for same work line until 若命 closes

若发现身份、权限、范围、事实来源或验证路径不清楚，回复 REQUEST/BLOCKED，不要猜。
```

生命周期关闭规则：

- 授权 gate 或工作线完成、且没有同范围立即 follow-up 时，若命必须关闭对应子 agent。
- 镜花/观止返回 `PASS/NEEDS_FIX/BLOCKED` 后，除非立即做同一 finding 复审、同一 QA rerun 或同一证据补充，否则关闭。
- 听云在阶段已 commit/push、主题切换、角色边界变化、上下文变脏或下个任务需要干净 intake 时关闭或重建。
- 不因为子 agent 已存在就保留；保留的上下文是成本和风险，不是权限。
- 不复用子 agent 扮演另一个角色。听云不能通过 follow-up prompt 变成镜花、观止或若命；需要新角色时新建已授权身份。

子 agent 上下文预算：

- 给最小完整上下文包：当前用户目标、角色身份、精确 REQUEST/PRD 片段、相关文件、必要的 `git status` 事实和验证命令。
- 不粘贴完整 inbox、完整聊天历史、长日志、大量生成数据或无关角色文档。
- 优先给文件路径、message ID、短摘录和验证命令；让子 agent 在权限范围内自行读取命名文件。
- 如果任务依赖大量历史，先把历史归档或压缩成有边界的文档，再从该文档派工。
- 存活子 agent 上下文出现陈旧、冲突或过重时，关闭并用干净 prompt 重建授权角色。

inbox 使用边界：

- `docs/collaboration/inbox.md` 是正式行动板和审计板，不是子 agent 聊天记录。
- 子 agent 的中间分析、内部计划、草稿和短过程不写入 inbox；长证据写入 PRD、review、QA 或其它报告文件。
- 会影响项目闭环的正式结果必须可追溯：任务创建、关键决策、`SUBAGENT_OPENED`、`SUBAGENT_RESULT`、`DONE_CLAIMED`、`CODE_REVIEW PASS/NEEDS_FIX/BLOCKED`、`QA PASS/NEEDS_FIX/BLOCKED`、用户确认、commit/push、`SUBAGENT_CLOSED`、关闭/归档，应在 inbox 留短结论和证据链接，或由若命在关闭消息中汇总。
- 如果一个子 agent 任务只服务于若命当轮判断，且没有形成独立项目动作，可以不写 inbox；若它改变了任务范围、gate、风险结论或交付状态，必须留下正式记录。
- 每个角色节点结束后，若命必须先生成或更新一份基于文件的用户可读总结，再推进下一节点。总结默认放在 `docs/collaboration/summaries/`，也可以链接到本轮已有 PRD、review 或 QA 报告，但必须能独立回答：谁完成了什么、依据哪些文件/命令、改了哪些文件、结论是什么、未覆盖什么、下一步选项是什么。
- 在用户看到该总结前，若命不得继续启动下一个实现、review、QA、commit/push 或新角色节点，除非用户已经在当前消息里明确授权“连续执行到某个 gate”。这个暂停点是协作可见性要求，不是低效 ACK。

## 文档留痕原则

大型动作必须有迹可循，但不要求所有小动作都写大文档。每个角色开始工作时，都要先判断本轮是否需要新增或更新文档；如果不需要，也要能说明原因。

需要文档留痕的触发条件：

- 产品语义、用户流程、状态枚举、操作规则、权限、副作用或成功标准发生变化。
- 架构、模块边界、数据模型、接口契约、查询口径、任务/异步流程、迁移、配置或外部集成发生变化。
- 需要多人协作、跨会话交接、分阶段执行、长期跟踪或后续复盘。
- 涉及生产数据、客户数据、导出/发布产物、外部平台、不可逆操作或人工确认。
- QA、代码 review、UX review 或运营复核发现需要复现、回归或长期防线的问题。

文档类型和位置：

- 产品设计/PRD/spec：写到 `docs/superpowers/specs/` 或项目约定的 design/spec 目录；inbox 只留链接和行动结论。
- 技术设计/ADR/migration note：写到项目约定的架构、设计、迁移或 runbook 文档；说明取舍、字段、状态、接口、兼容和回滚。
- 测试/验收记录：写到 `docs/collaboration/reviews/`、QA 文档或项目约定测试记录；说明样本、步骤、预期、实际、证据和未覆盖。
- 跨 agent 行动：写 `docs/collaboration/inbox.md` 顶层 message；不要藏在 review、status、topic 或长文档里。
- 讨论结构：只有长期多分支讨论才写 `docs/collaboration/topic-tree.md`；topic 不替代正式任务。
- 执行手册：复杂 review、全量审计、QA、PRD、heartbeat 等方法写到 `docs/collaboration/playbooks/`；身份文件只指向何时读取。
- 项目/领域索引：`docs/project-index.md` 和 `docs/domain-index/*.md` 只做导航，帮助 agent 快速定位代码、API、页面、表和验证入口。

派工文档要求：

- 默认情况下，小任务不要求单独写技术设计文档，也不要求执行者反问是否需要文档。
- 若命给听云或其它执行角色派发工程任务时，由若命判断是否需要技术文档、PRD addendum 或文档 review gate；需要时必须在 REQUEST 中显式写清文档类型、建议路径、最低内容、完成时机和是否需要镜花/其它角色评审。
- REQUEST 未写技术文档要求时，执行者按“不需要新增技术文档”处理，只需按任务要求更新必要索引、变更日志或现有文档。
- inbox 里的 `TASK_DEFINITION` 不能替代若命明确要求的正式技术设计文档；大型任务的长设计只应在 inbox 留摘要和链接。

文档基本要求：

- 明确读者、目标、范围、非目标、事实来源、决策、未决问题、验证方式、风险和下一步。
- 能链接到相关 inbox message、PRD/spec、代码 review、QA 证据、命令、截图或产物路径。
- 不粘贴长日志、完整敏感数据、完整聊天记录或过期讨论；只写摘要和路径。
- 不用文档掩盖实现缺口；未实现、未验证、待确认和外部依赖必须明确标注。

## Inbox 归档维护

`docs/collaboration/inbox.md` 是当前行动板，不是历史消息库。为了降低上下文和 token 消耗，必须定期把已失效内容移出 inbox。

归档触发：

- 当前任务已 `PASS`、被用户确认结束，或已由后续顶层 message 取代。
- `DONE_CLAIMED / REVIEW / NEEDS_FIX / STATUS` 等长过程记录已经没有当前执行动作，只剩追溯价值。
- on-hold、deferred、blocked 的事项近期不会推进；inbox 只保留一行决策摘要和文档链接。
- inbox 行数明显膨胀，读取当前消息需要翻过大量历史内容。

归档方式：

- 先把清理前的 inbox 原文保存到 `docs/collaboration/archive/`，文件名包含日期和用途，例如 `inbox-YYYY-MM-DD-pre-trim-current-board.md`。
- 清理后的 inbox 只保留使用规则、归档入口、当前仍需动作的 open message、少量 on-hold 决策摘要。
- 当前 open message 也要写成可执行摘要：目标、范围、禁止范围、完成定义、验证要求和相关文档路径；不要保留完整聊天式过程。
- 历史追溯通过 `rg` 按消息编号、agentKey、文件路径或 topic 查 archive，不要把归档文件整篇读入上下文。

责任边界：

- 若命负责在多 agent 流转中主动维护 inbox 体积；发现历史消息堆积时，应先归档再继续派工。
- 听云、观止、镜花、清秋、霜弦发现自己读取 inbox 时被历史消息干扰，应写 `REQUEST` 提醒若命归档，必要时可只读当前相关消息继续工作。
- 任何角色新增长证据、长日志、截图说明、审计报告或 QA 记录时，应写到独立文件并在 inbox 留链接，不得把 inbox 当报告正文。

## Review Gate 与提交推送

不要长期积压未提交代码。每个可独立回滚的任务或阶段，在验证和必要 gate 通过后，应及时 `commit` 并 `push`。

## 分支生命周期管理

`main` 只承载已经通过必要 gate、可作为稳定基线继续开发的内容。分支创建、目标分支、阶段提交、合并回 `main` 和是否继续沿用当前分支，由若命统一判断。

基本规则：

- 新功能、重构、数据模型、任务框架、外部集成、批量变更或高风险修复，默认不要直接在 `main` 上施工；由若命决定是否创建 `codex/<topic>` 分支或沿用当前 feature/integration 分支。
- 执行者不能自行把工作切到新分支、合并回 `main`、rebase/merge 其它分支，或把未通过 gate 的代码推到 `main`。如果当前分支不合适，写 `REQUEST` 给若命。
- 一个分支可以承载一个完整 PRD、一个阶段性集成主题，或若命明确批准的一组强相关任务；不把无关功能、协作规则、缓存文件和临时产物混在同一个提交序列里。
- 阶段通过 gate 后由若命做 scoped commit/push 到当前若命批准的分支；这不等于可以合并进 `main`。
- 合并进 `main` 前必须满足：工作区干净或无关改动已隔离；对应 inbox message 已闭环；必要的若命 review、镜花 code/design review、观止 QA 或用户确认已通过；验证命令和风险说明可追溯；commit 范围清楚、可回滚。
- 若命负责决定合并方式和时机，并在合并后安排关闭/归档相关消息、停止无用 heartbeat、必要时更新索引或发布下一阶段任务。

分支命名默认使用 `codex/<short-topic>`。如果项目已有其它分支规范，以项目规范为准，但仍由若命做生命周期决策。

## 复杂工程任务的设计与执行

复杂工程任务不要按“若命一步步派实现、听云一步步临场设计”的方式推进。涉及多模块、多阶段、数据模型、状态机、任务框架、外部集成、链路迁移、旧路径退役或长期维护口径变化时，默认采用“整体技术方案先行、分阶段执行闭环”的模式。

流程：

1. 若命先给出 PRD/spec 或明确 REQUEST：写清目标、非目标、用户路径、状态/动作、数据边界、禁止范围、验收标准和 gate。
2. 听云先读完整 PRD/spec，写整体技术方案和任务规划设计；不要直接写实现代码。
3. 技术方案必须拆成可 review、可验证、可提交的阶段。每个阶段要有输入、输出、范围、禁止范围、涉及文件/模块、验证命令、文档/索引要求和 gate。
4. 若命 review 技术方案的产品语义、范围、执行顺序和验收口径；镜花 review 技术方案的架构、数据模型、模块边界、状态机、任务生命周期、测试策略和可维护性。
5. 方案通过后，听云按已批准阶段逐个执行。每完成一个阶段，只汇报该阶段 `DONE_CLAIMED`，列实际改动、验证结果、偏差和是否仍符合整体方案。
6. 若实现中发现整体方案需要调整，听云写 `REQUEST / DESIGN_CHANGE`，说明原因、选项、影响、推荐方案和需要谁确认；不能直接改方向继续写代码。
7. 若命和镜花按阶段 review 执行结果；通过后由若命及时 commit/push，再进入下一阶段。

小型、低风险、局部 bug 或文案调整可以跳过整体技术方案 gate，但若任务连续返工、范围开始扩大、或 review 暴露出设计问题，应立即回到该模式。

闭环顺序：

1. 执行者完成实现，写 `DONE_CLAIMED`，列范围、文件、验证命令、证据、未覆盖项和索引更新对账。
2. 若命做任务闭环 review：确认是否按 PRD/inbox 执行、是否越界、验证证据是否足够、是否需要镜花或观止出场。
3. 涉及高风险代码面时，若命派镜花 code review。高风险包括跨层语义契约、数据表/字段/索引、任务框架、状态机、异步流程、API 契约、筛选/统计/分页、权限/可见性、外部副作用、安全边界、大重构或若命不踏实的实现。
4. 涉及用户路径、页面行为、导出/生成产物、外部平台或业务验收时，若命派观止 QA。
5. 所需 gate 全部通过后，由若命负责 scoped `commit + push`；听云不再作为默认提交执行者。这样减少跨 agent 往返，并由同一个角色统一把 gate、范围、验证、提交和关闭动作闭环。
6. 提交推送完成后，若命把对应 inbox message 标记关闭或归档。

提交许可：

- 低风险任务：`DONE_CLAIMED` + 若命 `REVIEW_PASS` 后可以提交。
- 高风险任务：再加镜花 `CODE_REVIEW_PASS`。
- 用户路径任务：再加观止 `QA_PASS` 或用户明确确认。
- `DONE_CLAIMED` 不是提交许可；执行者不能自己宣布 PASS 后直接提交，也不能在 gate 通过后自行提交，除非若命/用户在该任务里明确授权。

提交边界：

- 一个 commit 对应一个清晰任务或一个可独立回滚的阶段。
- 不把多个无关主题攒进一个 commit。
- 不提交未验证内容；跑不了的验证必须先在 `DONE_CLAIMED` 和提交说明中写清楚。
- 不提交 `tmp/`、日志、浏览器 profile、本地数据库备份、临时导出文件、真实凭据或其它本机产物。
- 提交前至少执行 `git status --short`、必要验证命令和 `git diff --check`；前端改动需跑项目约定 build。

commit message 格式：

```text
<type>: <short summary>
```

常用 type：

- `feat`: 新功能或新业务能力。
- `fix`: bug 修复。
- `refactor`: 不改变用户行为的重构。
- `docs`: 文档、协作规约、索引。
- `test`: 测试、项目规则、测试夹具。
- `chore`: 配置、依赖、脚本、维护动作。

示例：

```text
feat: add task runtime for giga pull
fix: correct task run pagination totals
refactor: centralize product workflow projection
docs: add multi-agent collaboration guide
test: lock amazon workflow enums
chore: archive collaboration inbox history
```

## 通用工程质量底线

这些底线适用于所有角色的设计、实现、review 和 QA，不是写给某一个角色的。宁可 `REQUEST/BLOCKED`，不能乱做、半实现或用表面证据冒充完成。

- 不允许用“能跑”“编译过”“页面没报错”冒充用户路径正确；构建和编译只是最低门槛。
- 不允许用内存过滤、内存分页、截断扫描后伪造 total，替代数据层真实筛选、排序、分页和统计。
- 不允许用复杂查询弥补数据模型和流程设计缺陷。默认禁止嵌套查询、`EXISTS/IN` 子查询、跨表关联查询、运行时推导状态、重复 count 和查询后再二次拼装过滤；所有业务功能都适用。需要查询的归属、状态、统计口径和可操作性，应在写入、状态变更、事件落库或投影表中形成可直接索引、可单表过滤的字段。确实需要复杂查询时，必须先说明业务必要性、数据规模、索引、EXPLAIN、替代方案和验收口径，经若命/用户确认后再实现。
- 不允许用字符串包含、快照表面检查或 mock 快乐路径，冒充真实行为测试。
- 不允许共享状态、动作、字段语义、筛选 bucket、统计口径、权限规则或导出资格多处散落定义后只补其中一处；跨层语义契约的事实源、生产端和消费端必须闭合，并有反向不变量测试防回归。
- 不允许把长耗时、可失败、需要重试/恢复的流程塞进未追踪的后台任务、临时线程、进程内定时器或一次性脚本，逃避持久化状态、审计、恢复和失败处理。
- 不允许在界面层堆按钮、堆说明文案、堆状态标签来掩盖领域状态、权限、动作规则或错误恢复没有设计清楚。
- 不允许扩大范围、夹带无关重构、绕过既定 PRD、偷偷改变字段含义、接口契约或状态语义。
- 不允许把未完成、未验证、未覆盖、跑不了的内容藏在 `DONE_CLAIMED`、review、handoff 或任何交付说明里。

## 上下文预算

- 每次请求先看当前用户消息；需要落盘事实时，再读 `git status --short`、`AGENTS.md`、`docs/collaboration/inbox.md` 中与当前身份相关的 OPEN/ACKED/待处理消息。
- 首次进入项目、身份或协作规则不确定、inbox/handoff 明确要求、规则刚变化、上下文缺失、长时间缺席或完整冷启动时，再读本文和对应身份文件。
- 读长文件先定位：优先用 `rg` 搜索 `agentKey`、消息编号、topic、文件路径或标题，再读取命中段落附近内容。
- inbox 只放结论、下一步、关键文件和验证命令；长背景、截图、导出样例、命令输出放文件路径或 handoff 链接。
- 没有发给当前身份的消息、没有可恢复中断任务时，保持安静或返回 `DONT_NOTIFY`。

## 角色索引

读取本文后，按当前身份继续读取对应身份文件。

| agentKey | 显示名 | 当前身份还需读取 | 主要职责 |
|---|---|---|---|
| `ruoming` | 若命 | `docs/collaboration/roles/ruoming.md` | 产品经理、产品方向、架构边界、PRD 级任务拆解、review 和多 agent 协作控制 |
| `tingyun` | 听云 | `docs/collaboration/roles/tingyun.md` | 按若命/用户给出的 PRD 规格做工程实现、测试和本地验证 |
| `guanzhi` | 观止 | `docs/collaboration/roles/guanzhi.md` | QA gate、验收路径、回归测试、风险清单、发布前复核 |
| `jinghua` | 镜花 | `docs/collaboration/roles/jinghua.md` | 代码审查 gate、代码结构、架构边界、数据模型、查询性能、错误处理、测试质量和可维护性 review |
| `qingqiu` | 清秋 | `docs/collaboration/roles/qingqiu.md` | 页面体验、信息架构、操作流、空/错/等待状态、用户可理解性 |
| `shuangxian` | 霜弦 | `docs/collaboration/roles/shuangxian.md` | 数据/运营口径、模板/导出、类目/映射、库存/价格和外部平台规则复核 |

可以只开其中几个身份。没有用户明确指定身份时，当前会话按普通 Codex 执行，不冒认其它身份。

## Playbook 索引

复杂任务才按需读取执行手册；不要在普通启动时一次性读取全部 playbook。

- `docs/collaboration/playbooks/code-review.md`：代码 review、结构审查、查询/状态/错误/测试/文档影响判断。
- `docs/collaboration/playbooks/full-audit.md`：全量审计、跨模块审计、历史提交审计、子 agent 只读专项审计和报告模板。
- `docs/collaboration/playbooks/qa.md`：正式 QA gate、测试矩阵、场景验收、证据格式和 PASS/NEEDS_FIX/BLOCKED 判定。
- `docs/collaboration/playbooks/qa-case-library.md`：QA 用例库结构、用例准入、选择规则和维护责任。
- `docs/collaboration/playbooks/subagent-dispatch.md`：若命创建/复用/关闭子 agent 的身份文件初始化、授权检查、运行时昵称禁区和生命周期记录。
- `docs/collaboration/playbooks/context-indexing.md`：项目索引、领域索引、scoped `rg`、索引维护和 token 节约方法。

## 启动语模板

开新会话时只发一句话：

- `你是若命，读一下 docs/collaboration.md`
- `你是听云，读一下 docs/collaboration.md`
- `你是观止，读一下 docs/collaboration.md`
- `你是镜花，读一下 docs/collaboration.md`
- `你是清秋，读一下 docs/collaboration.md`
- `你是霜弦，读一下 docs/collaboration.md`

## 完成标准

一次多角色协作任务完成时，至少满足：

- 角色职责没有互相抢占。
- 真实数据和模板输出没有被无声覆盖。
- 修改过的规则有对应文档或测试。
- 施工者给出验证结果。
- 观止或用户能基于证据判断是否通过。
- 所需 review/QA gate 已闭环；需要提交的改动已 commit/push，或明确说明暂不提交的原因。
