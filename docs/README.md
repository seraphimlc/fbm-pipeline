# Documentation Hub

状态：当前 docs 入口
更新：2026-07-26

工作树只保留当前导航、长期合同和正在执行的设计。已完成的 review、rereview、handoff、阶段计划和被替代 PRD 由 Git 历史保存，不在 `docs/` 继续充当运行时上下文。

## 阅读顺序

1. 先读当前用户消息、`AGENTS.md` 和 `git status --short`。
2. 用 `docs/project-index.md` 判断问题属于哪个领域。
3. 只读一个或少数几个 `docs/domain-index/*.md`。
4. 用限定范围的 `rg`、代码、API/DB 只读事实或页面行为核实当前实现。
5. 只有身份或协作边界相关任务才读 `docs/collaboration.md` 和当前角色文件。

## 当前文档集

- 导航：`docs/project-index.md`、`docs/domain-index/*.md`
- 协作：`docs/collaboration.md`、`docs/collaboration/roles/*.md`、`docs/collaboration/inbox.md`
- 操作：`docs/configuration.md`、`docs/runbook.md`
- GIGA：`docs/giga-buyer-openapi-reference.md`
- Amazon 模板：`docs/template-mapping-spec.md`、`docs/template-mapping-change-log.md`、`docs/add-category-template-sop.md`
- 当前产品合同：`docs/superpowers/specs/2026-06-17-product-workflow-node-state-prd.md`、`docs/superpowers/specs/2026-06-18-amazon-product-workflow-prd.md`、两份自动选图/竞品执行 PRD
- 当前集成加固：`docs/superpowers/specs/2026-07-25-integration-hardening-plan-status-review.md`、`docs/superpowers/specs/2026-07-25-legacy-real-backup-inventory-technical-design.md`

## 维护规则

- 文档必须改变决策或显著降低定位成本；一次性过程证据不进入当前文档集。
- 旧结论需要追溯时使用 `git log -- docs` 和 `git show <commit>:<path>`。
- 正式协作身份只以 registry 的严格五角色 allowlist 为准；allowlist 外身份不得成为运行时来源，也不在当前文档中保留说明。
- 删除或迁移文档时同步修复 `AGENTS.md`、根 `README.md`、domain index、测试和脚本中的消费者。
- 模板映射变更历史按 `AGENTS.md` 追加维护，不重写既有记录。
