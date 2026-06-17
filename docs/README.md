# Documentation Hub

状态：当前 docs 入口
更新：2026-06-17

本文只做文档导航和重写状态说明，不替代代码事实、API/DB 只读事实、页面行为或命令输出。

## 当前阅读顺序

1. 先读 `AGENTS.md`、当前用户消息和 `git status --short`。
2. 需要定位代码、页面、API、表或验证入口时，读 `docs/project-index.md`。
3. 根据问题类型只读一个或少数几个 `docs/domain-index/*.md`。
4. 用 scoped `rg` 和关键文件片段核实当前实现。
5. 复杂协作、review、QA 或全量审计再读 `docs/collaboration.md` 和对应 playbook。

## 当前事实源

- 项目导航：`docs/project-index.md`
- 领域地图：`docs/domain-index/*.md`
- 协作规则：`docs/collaboration.md`
- 角色身份：`docs/collaboration/roles/*.md`
- 执行手册：`docs/collaboration/playbooks/*.md`
- 当前行动板：`docs/collaboration/inbox.md`
- 当前 P0 修复 PRD：`docs/superpowers/specs/2026-06-17-p0-security-startup-triage-prd.md`
- 代码审计证据：`docs/collaboration/reviews/2026-06-17-whole-project-code-audit-rerun.md`

## 需要重写的旧文档

以下文档存在过期风险，不能直接当当前事实源。若命/听云按 `docs/documentation-rewrite-brief.md` 重写前，使用时必须先经 `docs/project-index.md`、domain index 和代码事实核实。

- `docs/configuration.md`
- `docs/runbook.md`
- `docs/item-workbench-redesign-plan.md`
- `docs/main-flow-user-path.md`
- `docs/main-flow-qa-checklist.md`
- `docs/giga-inventory-sync.md`

## 保留的专项文档

- `docs/giga-buyer-openapi-reference.md`：GIGA Open API 速查；实现前仍以官方文档和当前代码为准。
- `docs/template-mapping-spec.md`：Amazon 模板映射规范。
- `docs/template-mapping-change-log.md`：模板/类目映射变更历史，不覆盖历史记录。
- `docs/add-category-template-sop.md`：新增类目模板 SOP。
- `docs/superpowers/specs/*.md`：PRD/spec，按状态字段判断是否当前执行版。
- `docs/collaboration/reviews/*.md`：review/audit 证据。
- 复杂交接：后续按 `AGENTS.md` 新建 `docs/codex-handoff-YYYY-MM-DD-*.md` 并在 inbox 留链接；旧 handoff 已从根 docs 清理。

## 已清理

- 删除 `docs/codex-collaboration-roles.md`：旧协作入口，已由 `docs/collaboration.md` 和 `docs/collaboration/roles/*.md` 取代。
- 删除 `docs/multi-agent-collaboration-copy-paste.md`：通用复制粘贴指南，不再作为当前项目状态文档。
- 删除 `docs/01-架构设计.md`：2026-05 旧架构说明，已被当前索引、PRD 和代码事实取代。
- 删除 `docs/02-API接口文档.md`：2026-05 旧 API 说明，接口以代码/OpenAPI 和待重写 `docs/api.md` 为准。
- 删除 `docs/03-配置说明.md`：2026-05 旧配置说明，安全启动/TLS 口径以 P0 PRD 和待重写 `docs/configuration.md` 为准。
- 删除 `docs/04-Pipeline步骤详解.md`：旧 10 步流水线说明，当前流程按 domain index 和待重写 `docs/pipeline.md` 重建。
- 删除 `docs/05-部署指南.md`：旧部署说明，不能继续把 `0.0.0.0` / `verify=False` 描述成默认方案。
- 删除 `docs/06-试用稳定版操作说明.md`：旧试用说明，当前用户路径按待重写 `docs/user-workflows.md` 重建。
- 删除 `docs/codex-handoff-2026-06-02-amazon-stylesnap.md`：旧 StyleSnap/GIGA 阶段 handoff，已不作当前启动入口。
- 删除 `docs/codex-handoff-2026-06-05-export-rule-layer-and-workflow.md`：旧导出规则层 handoff，已不作当前启动入口。
