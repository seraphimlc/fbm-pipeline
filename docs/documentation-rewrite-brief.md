# Documentation Rewrite Brief

状态：待若命/听云重写
创建：2026-06-17
发起：镜花（agentKey: `jinghua`）

## 目标

把 docs 从旧的线性说明书整理成当前项目可维护的文档集。重写时必须先用 `docs/project-index.md` 和对应 `docs/domain-index/*.md` 建立范围，再用 scoped `rg`、代码片段、命令、API/DB 只读事实核实。

## 非目标

- 不把旧聊天、完整 handoff、长日志或临时 QA 输出搬进新文档。
- 不用旧 `01-05` 文档直接覆盖当前代码事实。
- 不在文档重写中触发真实任务、导出、上传、外部平台调用或状态推进。
- 不重写 `docs/template-mapping-change-log.md` 历史记录。

## 当前事实源

- `AGENTS.md`
- `docs/README.md`
- `docs/project-index.md`
- `docs/domain-index/*.md`
- `docs/collaboration.md`
- `docs/collaboration/playbooks/context-indexing.md`
- `docs/superpowers/specs/2026-06-17-p0-security-startup-triage-prd.md`
- `docs/collaboration/reviews/2026-06-17-whole-project-code-audit-rerun.md`
- 当前代码、命令输出、API/DB 只读事实和页面行为

## 重写分工

### 若命

- 定义文档目标读者、当前业务主线、非目标和产品/架构口径。
- 决定旧主流程、Amazon/TikTok 分流、GIGA 拉品、任务中心、导出中心的当前叙述边界。
- 确认哪些文档应合并、哪些保留为专项文档、哪些在重写完成后删除。
- 给听云的文档重写任务写清验收标准和禁止范围。

### 听云

- 用 scoped `rg` 核实页面/API/service/model/task/config/test 的当前代码事实。
- 按若命口径重写具体技术文档、API 文档、配置/启动/运行说明和验证命令。
- 同步更新 `docs/project-index.md` 和 `docs/domain-index/*.md` 中的过期入口。
- 重写完成后跑文档引用检查，避免新文档指向已删除文件。

## 建议重建后的文档结构

- `docs/README.md`：docs 总入口和阅读顺序。
- `docs/project-index.md`：问题类型到领域地图的路由。
- `docs/domain-index/*.md`：领域地图，只保留定位信息。
- `docs/architecture.md`：当前系统架构，重建已删除的旧架构说明。
- `docs/api.md`：当前 API 文档，重建已删除的旧 API 说明。
- `docs/configuration.md`：当前配置与安全启动策略，重建旧配置说明的有效部分。
- `docs/pipeline.md`：当前商品/任务/导出流水线，重建旧 10 步流水线说明的有效部分。
- `docs/runbook.md`：当前启动、验证、排障、P0 安全边界说明，重建旧部署指南的有效部分。
- `docs/user-workflows.md`：当前用户路径和操作说明，合并 `docs/main-flow-user-path.md` 的有效内容。
- `docs/qa-checklist.md`：当前 QA gate，合并旧 `docs/main-flow-qa-checklist.md` 的有效内容。

## 旧文档处理建议

已删除，需要按当前代码事实重建：

- `docs/01-架构设计.md`
- `docs/02-API接口文档.md`
- `docs/03-配置说明.md`
- `docs/04-Pipeline步骤详解.md`
- `docs/05-部署指南.md`
- `docs/06-试用稳定版操作说明.md`

重写完成前保留，但只能作候选背景：

- `docs/item-workbench-redesign-plan.md`
- `docs/main-flow-user-path.md`
- `docs/main-flow-qa-checklist.md`
- `docs/giga-inventory-sync.md`

重写完成后，由若命确认上述保留候选是否删除或改为历史归档。删除前必须先用 `rg` 确认没有当前索引、PRD、README、inbox 或 changelog 仍引用。

已删除：

- `docs/codex-collaboration-roles.md`
- `docs/multi-agent-collaboration-copy-paste.md`
- `docs/01-架构设计.md`
- `docs/02-API接口文档.md`
- `docs/03-配置说明.md`
- `docs/04-Pipeline步骤详解.md`
- `docs/05-部署指南.md`
- `docs/06-试用稳定版操作说明.md`

## 验收要求

- 新文档不能把已删除文件作为当前入口或事实源；如需提及，只能作为清理记录。
- 新文档不把 `0.0.0.0` 默认启动、TLS `verify=False`、启动自动 DDL/backfill/kick runtime 描述成安全默认。
- 文档中所有页面/API/命令必须能从 domain index 和当前代码中定位。
- 文档重写必须更新相关索引。
- 听云 `DONE_CLAIMED` 必须列出文档引用检查命令和结果。
