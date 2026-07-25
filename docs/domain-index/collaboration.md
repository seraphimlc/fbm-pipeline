# Domain Index: Collaboration

## 范围

- 若命、听云、观止、镜花、清秋五个正式身份及其职责边界。
- 单会话固定子 Agent 池、人工多会话、任务/结果交接和持久 inbox。
- `multi-agent-collaboration` skill 的项目生成结果、校验入口和防回流合同。
- 当前协作运行时文件、身份路由与持久 inbox。

## 当前口径

- 模型路由入口是 `docs/collaboration.md`，正式身份严格由 `docs/collaboration/agent-registry.json` 定义。
- 单会话模式由若命持有用户上下文，听云、观止、镜花、清秋使用各自独立运行时上下文；禁止同一上下文冒认其它正式身份。
- 运行时优先直接派工和回执；只有需要跨上下文持久保存的 assignment、blocker、result 或 handoff 才写 `docs/collaboration/inbox.md`。
- inbox 是当前行动板，不是聊天历史或归档库；没有活跃消息时保留空的 `Open Messages`。
- 正式身份严格等于 registry 的五角色 allowlist；任何额外身份、角色文件或协作子目录都不得成为运行时来源。
- 专业方法由正式角色按任务加载对应 capability skill；不要把 PRD、技术方案、review 或 QA 方法重新集中复制到协作框架。

## 关键入口

- 公共路由：`docs/collaboration.md`
- 当前行动板：`docs/collaboration/inbox.md`
- 角色身份：`docs/collaboration/roles/`
- 正式注册表：`docs/collaboration/agent-registry.json`
- 生成清单：`docs/collaboration/manifest.json`
- skill：`/Users/liuchang/.codex/skills/multi-agent-collaboration/SKILL.md`
- 初始化/校验：`/Users/liuchang/.codex/skills/multi-agent-collaboration/scripts/init_collaboration.py`

## 关键流程

- 项目刷新：先检查 `AGENTS.md`、`git status --short` 和现有协作目录，再按授权运行初始化脚本；只有明确授权时才使用 `--force --reset-state-files`。
- 运行时初始化：若命为四个正式子角色建立或复用独立上下文；身份握手全部精确通过后才报告 `SUBAGENT_POOL_READY`。
- 派工：使用最小自包含 `TASK`；同角色后续增量使用 `TASK_DELTA`。
- 回执：子角色返回精简 `RESULT`；若命负责范围、交付状态和 commit/push readiness，不代替独立 review 或 QA 结论。
- 持久协作：只有跨会话必须保留的状态写 inbox；复杂证据放 review 或明确 handoff 文件并从 inbox 链接。

## 验证入口

- 官方项目校验：`python3 /Users/liuchang/.codex/skills/multi-agent-collaboration/scripts/init_collaboration.py --project . --profile team --validate-only`
- 项目防回流合同：`make test-project-rules` 中的 `test_multi_agent_collaboration_core_contract`
- 格式检查：`git diff --check`

## 常见定位

- 身份或职责不一致：核对 registry、对应 role 文件和 skill 模板，不凭运行时昵称推断身份。
- 要读当前下一步：只看 inbox 中发给当前 `agentKey` 的活跃消息。
- 要查历史实现证据：使用 Git 历史，不在当前协作目录保存 review archive。
- 要修改可复用协作模型：先改本机 skill 源并验证，再刷新项目生成文件；不要只手改生成角色文件。

## 维护规则

- 正式角色、权限、运行时握手、handoff、inbox 或生成文件结构变化时更新本文。
- 普通业务流程、PRD 模板、技术方案方法、QA 方法和代码评审方法不写入本索引。
- 协作目录只能包含 manifest、registry、五个 role 文件和 team inbox；不得增加未注册运行时来源或 archive。
