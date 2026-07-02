# Domain Index: Collaboration

## 范围

- 多 agent 协作公共规约、角色身份、inbox 消息、topic tree、playbook。
- review gate、QA gate、commit/push 闭环、inbox 归档维护。
- `multi-agent-collaboration` skill 的本机维护入口。
- 项目索引和协作索引本身的维护规则。

## 当前口径

- 协作入口是 `docs/collaboration.md`；新会话启动语是“你是某角色，读一下 docs/collaboration.md”。
- 正式跨 agent 行动和审计结论只写 `docs/collaboration/inbox.md` 顶层 message；topic tree 只记录讨论结构。
- 若命可按需启动角色子 agent，但必须按 `docs/collaboration/playbooks/subagent-dispatch.md` 执行授权检查、身份文件初始化、`IDENTITY_READY/IDENTITY_BLOCKED` 握手和 `SUBAGENT_OPENED/SUBAGENT_RESULT/SUBAGENT_CLOSED` 生命周期记录。生命周期按协作节点定义，不按单条消息、小问题或单次命令频繁创建关闭；听云按工程工作线优先复用，镜花/观止按 gate/rerun 复用并在节点闭环后关闭。运行时英文昵称只作传输元数据，不进入项目可见叙述。
- 每个角色节点结束后，若命必须先给用户一份基于文件的总结，再推进下一节点。总结默认放在 `docs/collaboration/summaries/`，也可链接到已有 PRD/review/QA 报告；用户看到总结前默认暂停，不继续启动实现、review、QA、commit/push 或新角色节点，除非用户预先授权连续执行到指定 gate。
- inbox 是当前行动板，不是历史库；已关闭、被覆盖或只剩追溯价值的消息归档到 `docs/collaboration/archive/`。
- `DONE_CLAIMED` 不是 PASS，也不是 commit/push 许可。
- 低风险任务需若命 `REVIEW_PASS`；高风险任务再加镜花 `CODE_REVIEW_PASS`；用户路径任务再加观止 `QA_PASS` 或用户确认。
- 跨层语义契约必须有事实源、生产端、消费端、未知值策略和反向不变量测试；状态枚举、workflow/work_status/action、字段语义、列表筛选、overview、schema、前端动作、权限、导出资格和外部副作用都是具体场景。相关规则见 `docs/collaboration.md` 的“跨层语义契约闭包”、听云身份的“跨层语义契约闭包检查”和镜花 DATA_REVIEW。
- `multi-agent-collaboration` skill 改动要同步 skill 说明和初始化脚本模板，避免新项目生成旧规约。

## 关键入口

- 公共规约：`docs/collaboration.md`
- 当前行动板：`docs/collaboration/inbox.md`
- 讨论树：`docs/collaboration/topic-tree.md`
- 角色身份：`docs/collaboration/roles/`
- 执行手册：`docs/collaboration/playbooks/`
- 子 agent 派发手册：`docs/collaboration/playbooks/subagent-dispatch.md`
- QA 用例库：`docs/collaboration/qa-cases/`
- review/QA 报告：`docs/collaboration/reviews/`
- 用户可读节点总结：`docs/collaboration/summaries/`
- inbox 归档：`docs/collaboration/archive/`
- skill 说明：`/Users/liuchang/.codex/skills/multi-agent-collaboration/SKILL.md`
- skill 初始化脚本：`/Users/liuchang/.codex/skills/multi-agent-collaboration/scripts/init_collaboration.py`
- skill 命令入口：`/Users/liuchang/.codex/skills/multi-agent-collaboration/scripts/multi-agent-collaboration`

## 关键流程

- 派工：若命写 PRD/spec 或顶层 REQUEST，听云先写 TASK_DEFINITION，若命 PLAN_APPROVED 后再实现。
- 子 agent：若命先读 `subagent-dispatch` playbook，准备 dispatch packet，要求子 agent 读取 `docs/collaboration.md` 和对应 `docs/collaboration/roles/<agentKey>.md`，收到 `IDENTITY_READY` 后才可继续派发；同一角色、同一目标、同一工作线/gate/rerun 且上下文干净时优先复用，换角色、换目标、需要独立判断、上下文变脏或节点闭环后才 `SUBAGENT_CLOSED` 或重建；子 agent 返回证据后由若命整合并决定正式 gate 和 inbox 记录，同时先形成用户可读总结并暂停等待用户看到。
- 验收：听云 DONE_CLAIMED 后，若命决定是否需要镜花 code review、观止 QA 或用户确认。
- 提交：所需 gate 通过后默认由若命做 scoped commit/push；听云只在若命/用户明确授权时提交。
- 归档：任务关闭或被新消息覆盖后，先保存清理前快照，再压缩 inbox 当前行动板。
- skill 更新：公共规约变化时，同步更新 `SKILL.md` 和 `scripts/init_collaboration.py`，并用临时目录跑初始化脚本验证。

## 相关文档

- `docs/collaboration.md`
- `docs/collaboration/inbox.md`
- `docs/collaboration/playbooks/context-indexing.md`
- `docs/collaboration/playbooks/code-review.md`
- `docs/collaboration/playbooks/qa.md`
- `docs/collaboration/playbooks/qa-case-library.md`
- `docs/collaboration/playbooks/subagent-dispatch.md`
- `docs/collaboration/qa-cases/fbm-pipeline-core.md`
- `docs/domain-index/README.md`

## 验证入口

- 协作规约格式检查：`git diff --check -- docs/collaboration.md docs/collaboration/inbox.md docs/collaboration/roles`
- skill 脚本语法：`python3 -m py_compile /Users/liuchang/.codex/skills/multi-agent-collaboration/scripts/init_collaboration.py`
- skill 初始化冒烟：`python3 /Users/liuchang/.codex/skills/multi-agent-collaboration/scripts/init_collaboration.py --project /tmp/mac-skill-test --skip-superpowers-setup`
- 当前消息定位：`rg -n "MSG-|DONE_CLAIMED|NEEDS_FIX|PLAN_APPROVED|IDENTITY_READY|SUBAGENT_CLOSED|agentKey" docs/collaboration/inbox.md`
- skill 规则定位：`rg -n "Review Gate|Inbox Archiving|DONE_CLAIMED|commit/push|Cross-layer semantic|On-Demand Sub-Agent|按需子 agent|subagent-dispatch|生命周期尺度|协作节点|IDENTITY_READY|runtime nickname|运行时昵称|跨层语义|生产端" /Users/liuchang/.codex/skills/multi-agent-collaboration`

## 常见定位

- 要读当前下一步：只看 `docs/collaboration/inbox.md` 当前 open message。
- 要查历史证据：按消息编号 `rg` `docs/collaboration/archive/`，不要整篇读归档。
- 要改角色行为：先改 `docs/collaboration.md` 或 `docs/collaboration/roles/*.md`，再判断是否同步 skill。
- 要查子 agent 协作边界：先读 `docs/collaboration/playbooks/subagent-dispatch.md`，再读 `docs/collaboration.md` 的“按需子 agent 协作模式”和 `docs/collaboration/roles/ruoming.md` 的“按需子 agent 调度职责”。
- 要改可复用初始化模板：改 skill 的 `SKILL.md` 和 `scripts/init_collaboration.py`。
- 要查 review 规则：读 `docs/collaboration/playbooks/code-review.md`。
- 要查 QA 规则：读 `docs/collaboration/playbooks/qa.md`。
- 要查 QA 用例库结构、准入、选择和维护规则：读 `docs/collaboration/playbooks/qa-case-library.md`。
- 要选 FBM Pipeline 核心回归/冒烟/任务/产物用例：读 `docs/collaboration/qa-cases/fbm-pipeline-core.md`。

## 维护规则

- 公共协作规则、角色职责、gate、commit/push、inbox 归档策略变化时，更新本索引。
- `multi-agent-collaboration` skill 路径、初始化脚本、生成文件结构变化时，更新本索引。
- 不把普通聊天历史、长 message 正文、长 review 报告复制进本索引；只保留定位入口和稳定口径。
