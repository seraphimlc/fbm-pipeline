# 项目级规则

## 工作方式

- 先查看现有流程、映射 JSON、文档和配置，再修改代码。
- 多 Codex 会话协作时，先确认身份和当前待办；如果用户指定身份（如若命、听云、清秋、观止、霜弦），按 `docs/collaboration.md` 的 `agentKey`、职责边界、交接格式和验证要求工作。
- 跨会话正式消息写入 `docs/collaboration/inbox.md`；复杂交接写入 `docs/codex-handoff-YYYY-MM-DD-*.md` 并在 inbox 留链接。
- 未被明确指定身份时，不冒认其它 agent；按普通 Codex 执行当前任务。
- 不要把用户已有商品数据、人工类目、真实 ASIN、已生成素材或模板输出整体覆盖掉；除非需求明确要求重建。
- 涉及 Amazon 导入模板、类目、字段名、上架检查时，优先查看 `backend/app/pipeline/template_mappings/*.json`、`backend/app/pipeline/step10_amazon_template.py` 和 `docs/template-mapping-spec.md`。

## 上下文预算

- 所有日常对话、新会话和 heartbeat 都适用上下文预算；不要为了显得“接上上下文”而默认携带或复述完整历史。
- 每次请求的最小启动上下文是当前用户消息、`git status --short`、`AGENTS.md` 和 `docs/collaboration/inbox.md` 中与当前身份相关的消息；不要默认整篇读取所有协作文档。
- 需要定位代码、页面、API、数据表或验证入口时，先读 `docs/project-index.md`，再按问题类型读取一个或少数几个 `docs/domain-index/*.md`；然后用限定范围的 `rg` 核实当前代码事实。
- `docs/project-index.md` 和 `docs/domain-index/*.md` 只做导航，不替代代码、API、DB 只读事实、页面行为和命令输出。
- 新增或修改页面、API、任务类型、状态机、数据表、导出链路、外部集成或主要验证入口时，同步更新对应索引；发现索引过期也要纳入本轮收口。
- `docs/collaboration.md` 只在首次进入项目、身份/协作规约不确定、规则变化或用户明确要求时补读；`docs/codex-cold-start.md` 只在完整冷启动、环境不熟、长时间缺席或复杂 handoff 时补读。
- 读取长文件时先用 `rg` 定位目标消息、标题或文件路径，再只读取相关段落和引用链；不要把完整 inbox、完整日志、完整导出样例或大段商品数据塞进上下文。
- 日常回复保持短小：只回答当前问题需要的结论、文件路径、命令和下一步；不要把旧 handoff、长聊天记录、完整测试输出或大段代码作为背景复述。
- 跨会话消息保持短小：结论写在 inbox，长证据放文件路径、命令名、截图路径或 handoff 链接；没有当前身份待办时保持安静或返回 `DONT_NOTIFY`。

## 模板类目映射合并

当导入、合并或维护模板类目映射时，如果多个来源映射到同一个类目 key，按导入顺序以后导入的映射为准。

只覆盖发生冲突的类目映射；没有冲突的其他类目必须保留原有映射，不得因为一次导入而整体替换或清空。

## 类目导出文件映射修改记录

- 每次新增、删除或修改 Amazon 类目导出文件映射时，必须同步追加记录到 `docs/template-mapping-change-log.md`。
- 记录范围包括 `backend/app/pipeline/template_mappings/*.json`、`backend/app/pipeline/step10_amazon_template.py` 中的类目选择/字段填充逻辑、`backend/app/pipeline/templates/*.xlsm` 模板文件，以及会影响 Step 10 导出字段或类目匹配的文档/配置。
- 每条记录至少写明日期、改动文件、涉及类目/模板、变更原因、验证命令和结果、后续注意事项。
- 该记录是类目导出文件映射修改专用，不用于泛化记录无关功能改动。

## Amazon 导入表格

- 新增或修改类目模板时，必须同步维护 `template_mappings/*.json`，并跑模板映射校验。
- 已有真实 Amazon ASIN 的商品，不允许再次导出 Amazon 导入表格。
- Step 10 只负责生成导入表格和风险提示；任务完成后仍需人工确认，不能自动进入可运营商品列表。

## 新增类目模板

新增类目模板按 `docs/add-category-template-sop.md` 执行，至少包含模板文件、映射 JSON、类目匹配逻辑、校验结果和一个样例商品生成检查。
