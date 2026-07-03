# Subagent Dispatch Playbook

适用角色：若命。其它角色可按需读取以理解子 agent 身份、边界、常驻和 reset 要求。

读取条件：

- 若命准备初始化、复用、reset 或关闭按需子 agent。
- 子 agent 工具返回了英文昵称、通用标签或其它非项目身份。
- 需要把子 agent 结果写入 inbox、summary、review、QA 报告或用户可见结论。

## 核心规则

若命创建子 agent 不是创建新人设，而是把一个运行时执行单元绑定到项目已授权身份。运行时昵称 runtime nickname 只可作为工具传输元数据，不是项目身份，不进入项目可见叙述。

可由若命按需创建的子 agent 只有下列身份：

| agentKey | Display | Identity file | Default lifecycle |
|---|---|---|---|
| `tingyun` | 听云 | `docs/collaboration/roles/tingyun.md` | 身份可常驻；按同一工程工作线复用；上下文变脏或新不相关工作线时 reset |
| `guanzhi` | 观止 | `docs/collaboration/roles/guanzhi.md` | 身份可常驻；按 QA gate/rerun 授权；新不相关 QA 或需独立判断时 reset |
| `jinghua` | 镜花 | `docs/collaboration/roles/jinghua.md` | 身份可常驻；按 review gate/finding 授权；新不相关 review 或需独立判断时 reset |
| `qingqiu` | 清秋 | `docs/collaboration/roles/qingqiu.md` | 身份可常驻；按 UX/IA review 节点授权；新不相关页面/流程时 reset |
| `shuangxian` | 霜弦 | `docs/collaboration/roles/shuangxian.md` | 身份可常驻；按数据/运营/模板复核节点授权；新不相关规则主题时 reset |

`ruoming/若命` 是主控身份。若命是主控身份，不作为若命自己创建的子 agent 身份。新增、改名或替换身份，必须先由用户明确批准，并同步更新 `docs/collaboration.md`、对应 `docs/collaboration/roles/*.md` 和本 playbook。

## 初始化身份池

若运行时支持子 agent 常驻，项目初始化或首次进入多 agent 模式时，若命可以一次性预初始化所有授权子 agent 身份：听云、观止、镜花、清秋、霜弦。预初始化只做身份绑定和身份文件读取，不授予任何具体任务权限。

预初始化要求：

- 每个子 agent 仍必须读取 `docs/collaboration.md` 和自己的 `docs/collaboration/roles/<agentKey>.md`。
- 每个子 agent 必须返回 `IDENTITY_READY`；身份文件不可读或身份不一致时返回 `IDENTITY_BLOCKED`。
- 若命记录该身份进入 identity pool。identity pool 里的子 agent 可以长期保留，不因为一次任务结束就默认释放。
- 身份常驻不等于任务常驻。每次具体任务仍必须由若命重新 dispatch 当前目标、范围、事实来源、权限和停止条件。

## 任务前授权检查

给常驻或新建子 agent 派具体任务前，若命必须先在当前线程完成这组检查；任一项为否，不派任务：

- 角色在上方 registry 内，且身份文件存在。
- 任务属于该角色职责，不触碰该角色禁止权限。
- 子 agent 对本轮有 gate 价值、执行价值或证据价值。
- 生命周期明确：复用现有身份上下文、要求 reset 后再接收任务，还是运行时不可用时重建身份。
- 上下文包足够小且足够完整：当前目标、范围、禁止范围、事实来源、文件路径、验证命令和停止条件。
- 写权限、验证权限和外部副作用权限已明确。

## 生命周期尺度

子 agent 身份可以常驻；任务授权按“协作节点”定义，不按单条消息、单个小问题或单次命令定义。默认倾向是：保留身份、同一节点内复用上下文；节点结束后不默认释放，只等待若命下一次 dispatch 或 reset 判断。

优先复用已有子 agent，当且仅当同时满足：

- 角色身份相同，仍是同一个 `agentKey` 和同一份身份文件。
- 目标相同，仍属于同一工程工作线、同一 review gate、同一 QA rerun、同一 UX/运营复核节点。
- 范围没有扩大到新模块、新语义契约、新验收目标或新角色职责。
- 下一步 follow-up 是同一节点的返工、补证据、复测、自检、解释或收口。
- 上下文仍然干净：没有互相冲突的旧指令、过长历史、过期事实或混入其它任务。
- 保留该子 agent 会提升连续性，不会损害 review/QA 独立性。

必须 reset 或重建，当出现任一情况：

- 角色要改变，或当前子 agent 被要求承担另一个角色职责。
- 目标/gate 改变：新的 PRD、阶段、review 主题、QA 目标、样本批次或业务复核问题。
- 当前节点已经形成 `DONE_CLAIMED/PASS/NEEDS_FIX/BLOCKED/REQUEST`，且没有同范围立即 follow-up。
- 听云工作线已 commit/push、归档、主题切换，或下一阶段需要干净 intake。
- 镜花/观止需要新的独立判断；旧上下文会污染审查或验收。
- 上下文过大、陈旧、互相矛盾，或包含不该继续携带的临时事实。
- 权限、写入范围、外部副作用范围或事实来源发生变化。

reset 由若命判断。默认给子 agent 沟通、分任务或同节点 follow-up 时，不需要强调 reset；只有新不相关任务、上下文变脏、需要独立判断、权限/事实源变化或若命不信任当前上下文时，若命才明确要求 reset。

reset 的含义：

- 优先使用运行时提供的 reset/新会话能力。
- 若运行时没有 reset 能力，则关闭并重新创建同一授权身份。
- 若只能继续同一会话，若命必须显式要求子 agent 忽略旧任务上下文，仅按本次 dispatch 的文件、事实来源和权限执行；这种做法只适合低风险任务。

尺度基准：

- 听云：身份常驻，按工程工作线复用任务上下文；不按文件、报错、测试失败或小修小补频繁 reset。新的不相关 PRD/阶段/返工链路才 reset。
- 镜花：身份常驻，按 review gate 复用任务上下文；不按每条 finding reset。同一 finding 的返工复审可复用；新的 review 主题或需要独立二审时 reset。
- 观止：身份常驻，按 QA gate 或同一 rerun 复用任务上下文；不按每个操作步骤 reset。新的验收目标、样本批次或用户路径时 reset。
- 清秋/霜弦：身份常驻，按一次 UX/运营复核节点复用任务上下文；新的页面/规则主题通常 reset。

## Dispatch Packet

若命发给子 agent 的第一条消息必须包含完整 dispatch packet。不能只说“帮我 review 一下”或“你现在是听云”。

```text
你是 <Display>，agentKey=<agentKey>。这是项目授权身份，不使用运行时昵称作为项目身份。

身份初始化：
- 必须读取：docs/collaboration.md
- 必须读取：docs/collaboration/roles/<agentKey>.md
- 如果无法读取身份文件，或文件里的 agentKey/Display 与本 prompt 不一致，立刻回复：
  IDENTITY_BLOCKED: role=<Display>, agentKey=<agentKey>, reason=<原因>
- 身份初始化成功后，第一行必须回复：
  IDENTITY_READY: role=<Display>, agentKey=<agentKey>, files_read=[docs/collaboration.md, docs/collaboration/roles/<agentKey>.md]

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
- Lifecycle: reuse current identity; reset only if 若命 explicitly says so / same work line / same review gate / same QA rerun

如果身份、权限、范围、事实来源或验证路径不清楚，回复 REQUEST/BLOCKED，不要猜。
```

若命必须看到 `IDENTITY_READY` 后，才把该运行时执行单元视为对应项目角色。收到 `IDENTITY_BLOCKED` 时，不得继续派任务；先修身份文件、路径、角色名或授权。

## Follow-Up Packet

复用存活子 agent 时，每次 follow-up 都必须重新声明当前授权边界：

```text
继续以 <Display>，agentKey=<agentKey> 执行。不要使用运行时昵称作为项目身份。

当前任务：
- Objective:
- Scope:
- Forbidden scope:
- Fact sources:
- Files you may read:
- Files you may change, or READ ONLY:
- Verification allowed:
- External side effects allowed:
- Output format:
- Stop condition:
- Lifecycle: current reuse scale and close condition
```

保留上下文不是扩大权限。若 follow-up 需要另一种角色职责，若命必须关闭当前子 agent，并用新的授权身份重新创建。

## 生命周期记录

如果子 agent 影响项目 gate、风险、交付状态或用户可见结论，若命必须在 inbox、summary、review/QA 报告或当前线程收口中留下 formal identity 记录。记录只能使用授权身份名，不使用运行时昵称。

```text
SUBAGENT_OPENED
- role: <Display>
- agentKey: <agentKey>
- identity_files: docs/collaboration.md, docs/collaboration/roles/<agentKey>.md
- objective:
- lifecycle:
- write_permission:
- verification_permission:

SUBAGENT_RESET
- role: <Display>
- agentKey: <agentKey>
- reason: new unrelated task / dirty context / independent judgment / permission change / stale facts
- new_scope:

SUBAGENT_RESULT
- role: <Display>
- agentKey: <agentKey>
- status: DONE_CLAIMED / PASS / NEEDS_FIX / BLOCKED / REQUEST
- evidence:
- files_changed_or_read:
- residual_risk:

SUBAGENT_CLOSED
- role: <Display>
- agentKey: <agentKey>
- reason: runtime unavailable / reset unavailable / identity blocked / replaced / user requested shutdown
- next_action:
```

## 上下文预算

若命给子 agent 的上下文包必须小而完整：

- 给当前用户目标、正式角色身份、精确 REQUEST/PRD 片段、相关文件、必要的 `git status` 事实、允许验证命令和停止条件。
- 不粘贴完整 inbox、完整聊天历史、长日志、大量生成数据或无关角色文档。
- 优先给文件路径、message ID、短摘录和验证命令；让子 agent 在权限范围内自行读取命名文件。
- 如果任务依赖大量历史，先把历史归档或压缩成有边界的文档，再从该文档派工。
- 存活子 agent 上下文出现陈旧、冲突或过重时，reset 或用干净 prompt 重建授权身份。

## Inbox 和总结边界

`docs/collaboration/inbox.md` 是正式行动板和审计板，不是子 agent 聊天记录。

- 子 agent 的中间分析、内部计划、草稿和短过程不写入 inbox；长证据写入 PRD、review、QA 或其它报告文件。
- 会影响项目闭环的正式结果必须可追溯：任务创建、关键决策、`SUBAGENT_OPENED`、必要时的 `SUBAGENT_RESET`、`SUBAGENT_RESULT`、`DONE_CLAIMED`、`CODE_REVIEW PASS/NEEDS_FIX/BLOCKED`、`QA PASS/NEEDS_FIX/BLOCKED`、用户确认、commit/push、必要时的 `SUBAGENT_CLOSED`、关闭/归档，应在 inbox 留短结论和证据链接，或由若命在关闭消息中汇总。
- 如果一个子 agent 任务只服务于若命当轮判断，且没有形成独立项目动作，可以不写 inbox；若它改变了任务范围、gate、风险结论或交付状态，必须留下正式记录。
- 每个角色节点结束后，若命必须先生成或更新一份基于文件的用户可读总结，再推进下一节点。总结默认放在 `docs/collaboration/summaries/`，也可以链接到本轮已有 PRD、review 或 QA 报告，但必须能独立回答：谁完成了什么、依据哪些文件/命令、改了哪些文件、结论是什么、未覆盖什么、下一步选项是什么。
- 在用户看到该总结前，若命不得继续启动下一个实现、review、QA、commit/push 或新角色节点，除非用户已经在当前消息里明确授权“连续执行到某个 gate”。这个暂停点是协作可见性要求，不是低效 ACK。

## 用户直连角色会话

长期角色会话仍可存在，用户也可以单独打开角色会话直接讨论。此类会话的结论属于建议或用户直连沟通；是否转成项目行动、如何落地、需不需要 gate，仍由若命根据项目事实决定。

## 运行时昵称禁区

禁止把工具返回的英文昵称、通用标签或临时名字写成项目身份。以下写法不能进入 inbox、summary、review、QA 报告、用户结论或项目文档正文：

- `Spawned Bacon to review...`
- `Cicero said PASS`
- `Fermat will implement`
- `Reviewer agent approved`
- `Architect helper found...`

应改为：

- `镜花 CODE_REVIEW: PASS`
- `听云 DONE_CLAIMED`
- `观止 QA: NEEDS_FIX`

如果为了排查工具调用必须记录运行时标签，只能放在私有 scratch/工具传输元数据中；正式项目记录仍以 `Display + agentKey + identity file` 为准。

## Reset 与关闭规则

- 默认不关闭常驻身份。任务结束后，子 agent 留在 identity pool，等待若命下一次 dispatch。
- 若命不需要每次沟通都强调 reset；同一节点 follow-up 默认复用当前上下文。
- 新的不相关任务、上下文变脏、需要独立判断、权限/事实源变化或上下文过长时，若命要求 reset。
- reset 失败、身份阻塞、运行时不可用、用户明确要求释放或安全原因需要切断时，才 `SUBAGENT_CLOSED`。

常驻的是身份，不是权限。保留上下文是便利也是风险；是否 reset 由若命基于任务相关性、上下文健康度和独立性要求判断。
