# Domain Index: Collaboration

## 范围

- 多 agent 协作公共规约、角色身份、inbox 消息、topic tree、playbook。
- review gate、QA gate、commit/push 闭环、inbox 归档维护。
- `multi-agent-collaboration` skill 的本机维护入口。
- 项目索引和协作索引本身的维护规则。

## 当前口径

- 协作入口是 `docs/collaboration.md`；新会话启动语是“你是某角色，读一下 docs/collaboration.md”。
- 正式跨 agent 行动只写 `docs/collaboration/inbox.md` 顶层 message；topic tree 只记录讨论结构。
- inbox 是当前行动板，不是历史库；已关闭、被覆盖或只剩追溯价值的消息归档到 `docs/collaboration/archive/`。
- `DONE_CLAIMED` 不是 PASS，也不是 commit/push 许可。
- 低风险任务需若命 `REVIEW_PASS`；高风险任务再加镜花 `CODE_REVIEW_PASS`；用户路径任务再加观止 `QA_PASS` 或用户确认。
- `multi-agent-collaboration` skill 改动要同步 skill 说明和初始化脚本模板，避免新项目生成旧规约。

## 关键入口

- 公共规约：`docs/collaboration.md`
- 当前行动板：`docs/collaboration/inbox.md`
- 讨论树：`docs/collaboration/topic-tree.md`
- 角色身份：`docs/collaboration/roles/`
- 执行手册：`docs/collaboration/playbooks/`
- review/QA 报告：`docs/collaboration/reviews/`
- inbox 归档：`docs/collaboration/archive/`
- skill 说明：`/Users/liuchang/.codex/skills/multi-agent-collaboration/SKILL.md`
- skill 初始化脚本：`/Users/liuchang/.codex/skills/multi-agent-collaboration/scripts/init_collaboration.py`
- skill 命令入口：`/Users/liuchang/.codex/skills/multi-agent-collaboration/scripts/multi-agent-collaboration`

## 关键流程

- 派工：若命写 PRD/spec 或顶层 REQUEST，听云先写 TASK_DEFINITION，若命 PLAN_APPROVED 后再实现。
- 验收：听云 DONE_CLAIMED 后，若命决定是否需要镜花 code review、观止 QA 或用户确认。
- 提交：所需 gate 通过后由执行工程改动者 commit/push，通常是听云。
- 归档：任务关闭或被新消息覆盖后，先保存清理前快照，再压缩 inbox 当前行动板。
- skill 更新：公共规约变化时，同步更新 `SKILL.md` 和 `scripts/init_collaboration.py`，并用临时目录跑初始化脚本验证。

## 相关文档

- `docs/collaboration.md`
- `docs/collaboration/inbox.md`
- `docs/collaboration/playbooks/context-indexing.md`
- `docs/collaboration/playbooks/code-review.md`
- `docs/collaboration/playbooks/qa.md`
- `docs/domain-index/README.md`

## 验证入口

- 协作规约格式检查：`git diff --check -- docs/collaboration.md docs/collaboration/inbox.md docs/collaboration/roles`
- skill 脚本语法：`python3 -m py_compile /Users/liuchang/.codex/skills/multi-agent-collaboration/scripts/init_collaboration.py`
- skill 初始化冒烟：`python3 /Users/liuchang/.codex/skills/multi-agent-collaboration/scripts/init_collaboration.py --project /tmp/mac-skill-test --skip-superpowers-setup`
- 当前消息定位：`rg -n "MSG-|DONE_CLAIMED|NEEDS_FIX|PLAN_APPROVED|agentKey" docs/collaboration/inbox.md`
- skill 规则定位：`rg -n "Review Gate|Inbox Archiving|DONE_CLAIMED|commit/push" /Users/liuchang/.codex/skills/multi-agent-collaboration`

## 常见定位

- 要读当前下一步：只看 `docs/collaboration/inbox.md` 当前 open message。
- 要查历史证据：按消息编号 `rg` `docs/collaboration/archive/`，不要整篇读归档。
- 要改角色行为：先改 `docs/collaboration.md` 或 `docs/collaboration/roles/*.md`，再判断是否同步 skill。
- 要改可复用初始化模板：改 skill 的 `SKILL.md` 和 `scripts/init_collaboration.py`。
- 要查 review 规则：读 `docs/collaboration/playbooks/code-review.md`。
- 要查 QA 规则：读 `docs/collaboration/playbooks/qa.md`。

## 维护规则

- 公共协作规则、角色职责、gate、commit/push、inbox 归档策略变化时，更新本索引。
- `multi-agent-collaboration` skill 路径、初始化脚本、生成文件结构变化时，更新本索引。
- 不把普通聊天历史、长 message 正文、长 review 报告复制进本索引；只保留定位入口和稳定口径。
