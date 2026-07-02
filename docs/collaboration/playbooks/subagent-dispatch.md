# Subagent Dispatch Playbook

适用角色：若命。其它角色可按需读取以理解子 agent 身份、边界和生命周期要求。

读取条件：

- 若命准备创建、复用或关闭按需子 agent。
- 子 agent 工具返回了英文昵称、通用标签或其它非项目身份。
- 需要把子 agent 结果写入 inbox、summary、review、QA 报告或用户可见结论。

## 核心规则

若命创建子 agent 不是创建新人设，而是把一个运行时执行单元绑定到项目已授权身份。运行时昵称 runtime nickname 只可作为工具传输元数据，不是项目身份，不进入项目可见叙述。

可由若命按需创建的子 agent 只有下列身份：

| agentKey | Display | Identity file | Default lifecycle |
|---|---|---|---|
| `tingyun` | 听云 | `docs/collaboration/roles/tingyun.md` | 同一工程工作线可复用，阶段 commit/push 或上下文变脏后关闭 |
| `guanzhi` | 观止 | `docs/collaboration/roles/guanzhi.md` | 一次 QA gate 或同一 rerun，可给出 PASS/NEEDS_FIX/BLOCKED 后关闭 |
| `jinghua` | 镜花 | `docs/collaboration/roles/jinghua.md` | 一次 code/design review 或同一 finding 复审，可给出 PASS/NEEDS_FIX/BLOCKED 后关闭 |
| `qingqiu` | 清秋 | `docs/collaboration/roles/qingqiu.md` | 一次 UX/IA review 或同一页面交互复审后关闭 |
| `shuangxian` | 霜弦 | `docs/collaboration/roles/shuangxian.md` | 一次数据/运营/模板规则复核或同一规则复审后关闭 |

`ruoming/若命` 是主控身份。若命是主控身份，不作为若命自己创建的子 agent 身份。新增、改名或替换身份，必须先由用户明确批准，并同步更新 `docs/collaboration.md`、对应 `docs/collaboration/roles/*.md` 和本 playbook。

## 创建前授权检查

创建或复用子 agent 前，若命必须先在当前线程完成这组检查；任一项为否，不创建：

- 角色在上方 registry 内，且身份文件存在。
- 任务属于该角色职责，不触碰该角色禁止权限。
- 子 agent 对本轮有 gate 价值、执行价值或证据价值。
- 生命周期明确：一次性 gate、同一工作线复用，还是同一 finding/rerun 短暂复用。
- 上下文包足够小且足够完整：当前目标、范围、禁止范围、事实来源、文件路径、验证命令和停止条件。
- 写权限、验证权限和外部副作用权限已明确。

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
- Lifecycle: close after this gate / keep for same work line until 若命 closes

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
- Lifecycle:
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
- reason: gate complete / work line committed / needs fresh context / blocked / replaced
- next_action:
```

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

## 关闭规则

- 听云：同一 PRD、实现阶段或返工链路内可以复用；阶段已 commit/push、主题切换、上下文过重、角色边界变化或下个任务需要干净 intake 时关闭。
- 镜花：一次 review gate 或同一 finding 复审后关闭；返回 `PASS/NEEDS_FIX/BLOCKED` 且没有立即同范围复审时关闭。
- 观止：一次 QA gate、同一 rerun 或同一批样本补证据后关闭；返回 `PASS/NEEDS_FIX/BLOCKED` 且没有立即同范围补证据时关闭。
- 清秋：一次 UX/IA review 或同一页面交互复审后关闭；不能转成产品经理或工程实现身份。
- 霜弦：一次数据/运营/模板规则复核后关闭；不能替代人工业务确认或外部平台最终审核。

不要因为子 agent 已存在就保留。保留上下文是成本和风险，不是权限。
