# FBM Pipeline 集成加固技术方案状态复查与精简路线图

状态：IH-R0_PRUNE_COMPLETE / IH-R1_HISTORICAL_RUNNER_REVIEW_QA_COMPLETE / REAL_INVENTORY_NOT_EXECUTED
更新：2026-07-26
Owner：若命（agentKey: `ruoming`）
原技术方案 SHA256：`1a24d17c754e82fdd030a54ca326cba5bb17c57e08af314a229b256bafba969c`
产品基线 SHA256：`91e03e2e1f1ed0f8819a08b9538f2fa0fec40f7a343891700607df931c90b0c6`
候选分支基点：`codex/integration-hardening-candidate@4ba2a1a616f5304d812791d7ac768733f7a4d1bf`
当前交付范围：上述基点加已完成实现、代码评审与 QA 的 pending changes；最终提交 SHA 在提交前不自引用。

## 1. 复查结论

原技术方案不能继续按原顺序实施。

业务问题仍然成立：旧 StyleSnap/workflow 数据不能丢失，Lingxing 外部写入结果不确定时不能自动重复创建草稿，Step 10 的 Seller SKU、映射变更和已有输出必须受保护，最终候选必须在隔离环境形成可复查证据。

但原方案第 9 节和原 Phase 0 把本地单操作者的发布验证扩张成了一个高对抗特权供应链平台。root broker/reaper、多个 OS principal、cgroup/Seatbelt、独立 Rust Git verifier、签名 anchor、Ed25519 轮换、WAL 与两阶段 PASS receipt 不解决上述业务根因，并把真正修复推迟到大量基础设施完成之后。本轮删除这些实施要求；未来若要执行不可信候选代码，应使用成熟 CI、临时 VM 或容器，并作为独立安全项目立项。

原技术方案文件头的 `READY_FOR_IMPLEMENTATION` 也不能继续作为授权依据：文件末尾引用的终审 SHA 与当前固定技术方案 SHA 不一致。后续只按本文精简路线图派工。

## 2. 当前事实

### 2.1 已完成

- 独立候选分支当前以 `4ba2a1a616f5304d812791d7ac768733f7a4d1bf` 为基点；本轮仍未 stage/commit/push。
- IH-P0-I1、I2、I3 曾完成 pure-contract 验证：18/18、31/31、17/17 focused tests 通过；I1 证明不可执行 command skeleton 默认关闭，I2 证明 source manifest canonical body、detached digest 和 backup hash 字段可以一致绑定，I3 证明 setup/marker/lifecycle/ready/cleanup 的纯值合同具有判别性。
- R0 已把 I1 command manifest skeleton 与 I3 non-runnable MySQL skeleton 的活跃实现、focused tests 和 project-rule registrations 从候选删除；I1/I3 结果只保留为历史评审证据。I2 source-manifest binding 与可执行 Legacy inventory 保留。
- `IH-R1-LEGACY-INVENTORY` 的 fixture 路径和 historical-backup runner 已完成实现、独立代码评审与 QA：clean-HEAD/SQL sanitizer、旧列 compatibility、source/canonical dump/target 一致性、私有原子 evidence、命令观测和 owned-resource cleanup 均已闭环。
- 当前 focused 结果：Legacy core 21/21、I2 source manifest 33/33、backup/profile pure 20/20、sanitizer 15/15、MySQL E2E 15/15。项目规则仍只有 I2 与 Legacy 两个顶层 integration-hardening gate；Legacy gate 内顺序执行 core、backup/profile pure 和 sanitizer。
- fixture primary evidence：33 个 candidate/capture/workflow 物理 source row exactly-once，25 条 records，8 条 `review_required`；`records_sha256=a00ecce1e2fd792cda20c22f628bc317ec436d3e401ebb949aa0a4b06d11acde`，`source_row_ownership_sha256=6b6deb8702a4f0f74d96b7922ea3fa3e807ee65736a78409f1e1b1462189af88`。
- 来源提交 `3c57810` 已有但尚未组装进当前候选的能力包括：LOCAL Chrome adapter 与默认关闭配置、Lingxing listing/publish 基础链路、Amazon 导出 Seller SKU 双 mirror、分域 R1 脚本。

### 2.2 不能算完成

- 当前基点是 `4ba2a1a`，其上 reviewed pending changes 尚未形成最终提交；A1-A10 产品/运行时层仍未组装。
- 指定 54.5MB 真实备份尚未执行 restore inventory；现有 PASS 只证明 runner 合同和合成/fixture 行为，不能判断真实 legacy 数据为 0 或非 0，也不能批准 R2。
- `lingxing_recovery.py`、`step10_contract.py`、`candidate_evidence.py` 和 `evidence_command.py` 仍不存在；Lingxing once-only、Step 10 no-overwrite 和最终 R1 尚未验证。
- 当前 change log 没有 `change_set_id=IH-20260724-STEP10-SELLER-SKU`。
- 当前候选没有 durable publish intent、`result_unknown`、legacy reconciliation/apply 或最终 evidence runner。
- 当前只保留 I2、Legacy executable 两个 targeted project-rule gates；Legacy gate 已纳入 core、backup/profile pure 与 sanitizer，MySQL E2E 继续作为独立 focused runtime 验证。全量项目规则必须以实际命令结果为准，不由 focused PASS 代替。

### 2.3 当前威胁模型

- 产品是本机单一运营操作者使用的 FBM 应用；候选代码来自受 review 的项目源码，不把操作者、Git pack 和证据消费者同时视为敌对方。
- 本轮真正需要隔离的是业务数据库、真实外部凭据、真实外部写入、已有模板输出和测试产物。
- 发布证据要防脏工作树、旧数据库、旧服务、假 fixture、未清理资源和遗漏命令；不自建抵御恶意 candidate 的 root 级执行平台。

## 3. 原技术方案第 3-13 节状态矩阵

| 原节 | 裁决 | 已完成或可复用 | 继续保留 | 删除、简化或后置 |
|---|---|---|---|---|
| 3. 集成与 stack 拓扑 | `SIMPLIFY` | 独立候选分支已建立；来源范围已固定 | 来源提交可追溯、兼容激活单元、外部能力默认关闭 | 十层审批栈收敛为 Legacy、Lingxing、Step 10、Final R1 四个交付包；Enhanced A+/叙事不是本轮 hardening gate |
| 4. Legacy migration | `KEEP_REQUIRED` | source-manifest 合同与非空 fixture inventory/backup/restore gate 已完成 | 真实业务备份只读 inventory、结果驱动的 R2 决策；若需 apply，再保留确定性匹配、preserve-first、幂等、人工核对 | fixture 不能替代真实盘点；先有真实结果再决定三表模型、API/UI 和 apply；MySQL broker、全库 global lock、OS principal 模型删除 |
| 5. Lingxing recovery | `KEEP_REQUIRED` | 来源分支已有 `uploading -> save_draft -> draft_saved` 基础链路和默认关闭 flag | durable intent、scope 唯一开放意图、`result_unknown`、统一重试保护、独立 provider 故障注入、显式人工处置 | 全局 `closed_safe` TaskStep/Group/Run 状态删除；外呼前安全失败沿用现有终态；真实 query、自动阴性解锁和稳定窗口后置 |
| 6. Step 10 | `KEEP_REQUIRED / SIMPLIFY` | 来源分支已有 item_code 作为导出 SKU、成功后 Product/Catalog mirror 基础 | 三阶段 SKU 决策、真实 ASIN 禁止重导出、exact change-set、temp+fsync+no-clobber、hash/size、existing-output sentinel | recording writer 全字段闭包与大型 output journal 不作为前置；先禁用不安全 reuse 和完成最小原子发布，真实 crash 仍有缺口时再加最小 journal；历史自动 mirror repair 后置到 inventory 后 |
| 7. Flags | `KEEP_REQUIRED` | LOCAL Chrome、Lingxing create/listing、submit 默认关闭在来源分支已有 | 保留默认关闭和 fail-closed；增加单一 create kill switch 与写入口重验 | 不增加无启动入口的 migration startup flag；negative stability 配置等真实 query 存在后再加 |
| 8. Primary commands | `SIMPLIFY` | I1 静态 command inventory 仅保留历史证据；Legacy fixture 与 historical-backup runner 已完成 | Lingxing、Step 10、Final R1 各保留一个可执行入口和统一最小 JSON summary；真实 Legacy 命令必须使用 clean HEAD、固定 backup SHA 和外置私有 evidence | 删除 I1 active manifest/loader/gate、broker capability envelope、descriptor/FD transport 和未实现时的精确 17-command 顺序冻结 |
| 9. Trusted source / final gate | `DROP_MOST` | R1 已绑定实际 HEAD、dirty status、9 个运行源码 hash、隔离 DB/temp 和 owned cleanup；尚非 final gate | 最终仍需 detached clean worktree 或 `git archive`、外置 evidence、secret scan、开始/结束 clean 检查 | 删除 root broker/reaper、四 OS principal、cgroup/Seatbelt、自研 Rust Git verifier、anchor service、Ed25519 轮换、WAL、two-phase PASS、root installer；恶意代码隔离后置为独立项目 |
| 10. 实施蓝图 | `REPLACE` | I1/I2/I3 pure-contract 历史验证完成，R1 fixture gate 完成 | active candidate 只保留 I2 与可执行 Legacy inventory；按本文第 4 节从真实备份决策或 R3 checkpoint 继续 | I1/I3 active skeleton 与 gate 已按 R0 删除；原 Phases 1-6 不能按旧 gate 直接推进 |
| 11. 发布与回退 | `KEEP_REQUIRED` | flags 默认关闭的基础存在于来源分支 | 数据库备份/恢复、cohort、真实外部 canary 单独授权、forward repair | 不把代码合并和真实外部启用绑定；不要求特权 evidence service |
| 12. 评审重点 | `KEEP_REQUIRED` | 已完成本轮架构与验证价值复查 | legacy 不覆盖、Lingxing 不重复、Step 10 不覆盖、证据不假绿 | 增加威胁模型与运维可执行性审查；不再把安全机制数量当成质量 |
| 13. 历史 finding 映射 | `DROP_FROM_ACTIVE_PLAN` | 仅作为旧评审追溯记录有价值 | 可移入 review/archive 文档 | 不再作为实施 backlog；其中大部分 finding 是自建特权平台内部矛盾，不属于 FBM 产品交付 |

## 4. 精简后的执行路线图

### R0：收缩错误的 Phase 0

- 状态：`PRUNE_COMPLETE`。停止继续扩展 command/broker/MySQL pure skeleton。
- I2 的 source manifest/backup binding 作为下一片输入保留并收敛；canonical JSON 公共核只保留 I2/R1 caller 使用的部分。
- I1 command manifest skeleton 与 I3 non-runnable MySQL skeleton 的实现、focused tests 和 project-rule registrations 已从 active candidate 删除；既有 pure-contract 结果只作历史证据。
- 当前 integration-hardening 顶层 project-rule gate 仅为 I2 source-manifest binding 与 Legacy；Legacy gate 内顺序执行 core、backup/profile pure 和 sanitizer，MySQL E2E 作为独立 focused runtime 验证；不再把 I1/I3 当候选测试入口。
- 本阶段不宣布任何 PRD AC、Phase 0 或 merge-ready。

### R1：可执行 Legacy 只读 inventory 与 backup/restore verification

状态：`HISTORICAL_RUNNER_REVIEW_QA_COMPLETE`；指定 54.5MB 真实业务备份 inventory 尚未执行。

先回答“真实旧数据到底有多少、是否需要迁移”，再建设 migration/API/UI。

- 使用非空 legacy fixture backup；恢复到全新隔离 MySQL。
- 对 source/restore 的旧 workflow、candidate、selected、capture 做 count、PK 范围和关键字段 checksum 对账。
- 每个 source ID 输出唯一归属、无须迁移、需要核对或失败原因；覆盖单一 selected+capture、selected 无 capture、多 selected、孤儿、重复 ASIN和四种旧 workflow status。
- 连续运行两次得到相同分类与 digest；全程不写业务表，不创建 TaskRun，不启动浏览器，不访问外部网络，不生成 Step 10 输出。
- 错误 backup hash、manifest tamper、缺表和 checksum 差异必须失败；退出后隔离 schema、连接和临时目录零残留。
- inventory 结果为 0 时，legacy apply/API/UI 直接取消，只保留 no-op 证据；结果非 0 时再批准 R2。

### R2：条件式 Legacy apply 与 compatibility

状态：`NOT_AUTHORIZED`；必须先取得指定真实业务备份 inventory 结果，再由用户根据结果明确决定是否进入 R2。

- 仅在 R1 证明存在需迁移数据时实施。
- 使用 additive reconciliation/run 账本和最少 Product blocker 字段；是否需要独立 evidence 表、review API/UI 由 inventory 规模和冲突类型决定。
- 迁移 preserve-first、按商品事务、幂等；旧表不删除。
- A1/A2 source assembly 在任何旧库环境启用前必须与 compatibility 同一激活单元。

### R3：来源 stack 组装

- 按产品边界而非原十层表组装来源提交；collaboration framework 独立。
- Amazon 主流程/A+ trigger 保持真实能力关闭；每个 source commit manifest 记录选择和排除原因。
- Enhanced A+ 和 A+ narrative 只在核心 hardening 完成且仍有产品价值时继续，不作为 legacy/Lingxing/Step 10 的前置。

### R4：Lingxing durable intent 与 `result_unknown`

- Lingxing base publish 和 durable-intent hardening 必须进入同一可部署包；在此之前真实 create 始终关闭。
- 一个 scope 只允许一个开放 intent；外呼开始前持久化 intent；不能证明未创建时进入 `result_unknown`。
- startup、重试、批量重试和并发 worker 都不得产生第二次 create。
- 使用独立 fake provider ledger 覆盖 remote-success/SIGKILL 与 local success-commit failure；每个 intent create count 固定为 1。
- 首版只交付 evidence view、显式 reconcile 入口和具名人工处置；自动阴性解锁等待真实查询能力确认。

### R5：Step 10 SKU、change-set 与 no-overwrite

- 落地三阶段 SKU resolver，消除 listing/publish 对当前 item_code 的回退。
- 追加并精确校验 `change_set_id=IH-20260724-STEP10-SELLER-SKU`；删除条目 mutation 必须失败。
- 已有真实 ASIN继续禁止首次导出；已有输出不自动覆盖。
- 新文件采用同目录 temp、fsync、no-clobber publish，并持久化 hash/size；历史输出缺锚点时返回 conflict，不静默回填或重写。
- 先用故障注入验证最小方案；只有仍出现无法追踪的 final/DB 窗口时才增加最小 journal。

### R6：Final R1 与发布证据

- 使用固定 candidate SHA 的 detached clean worktree；开始/结束都检查 clean。
- 使用隔离 MySQL、真实 FastAPI/Vite/Playwright Chromium、现有分域 R1、compile/build、remote guard、secret scan 和资源清理；其中两个顶层 integration-hardening project-rule gate 固定为 I2 与 Legacy，Legacy gate 内执行 core、backup/profile pure 和 sanitizer，MySQL E2E 作为独立 focused runtime gate。
- 记录实际命令、cwd、runtime/source hash、退出码、测试计数、数据库、PID/port/temp、artifact SHA256 和未覆盖范围。
- 最终 manifest 在候选外原子写入并附 detached SHA256；崩溃只产生 `incomplete`，不产生 PASS。
- LOCAL Chrome adapter 未改且 flag=false 时只做静态/fail-closed 回归；真实 LOCAL Chrome smoke 仅在启用前或用户授权 canary 时执行，Playwright Chromium不能替代它。

## 5. 当前实施状态与下一决策

`IH-R1-LEGACY-INVENTORY` 的 fixture 与 historical-backup runner 实现、代码质量复审和 QA 已闭环。它证明 inventory/restore verification 可以在受控合成历史形态上运行并对假绿、误删、证据残留和保护事实 fail closed；指定 54.5MB 真实备份仍未执行，因此不证明真实业务数据规模，也不执行迁移。

本轮明确不做：migration apply、业务 schema 变更、review API/UI、A1-A10 source assembly、LOCAL Chrome、Amazon/Lingxing/GIGA/OSS 外部调用、真实商品/模板输出/历史任务修改、stage/commit/push。

下一决策分两条，不能混淆：

1. 若要决定 R2，按已评审的 clean-HEAD 命令合同执行指定真实备份 inventory，并把完整 records 仅保存在 worktree 外私有 evidence；真实结果为 0 时取消 apply/API/UI，非 0 时再按冲突规模设计 R2。R2 在该结果和后续决策前保持 `NOT_AUTHORIZED`。
2. 若暂不提供真实备份，应先把当前 R1 作为独立可回滚 checkpoint 收口，再进入 R3 source assembly；不得在未提交的 R1 工作树上继续叠加来源 stack。

## 6. Review gate

- 镜花已完成 historical-backup runner 的设计与最终代码复审：`PASS`，确认 single outer-finally ownership、完整命令观测和 post-cleanup 原子 evidence 边界闭合。
- 听云已完成 runner 实现和根因返工；当前 focused 结果为 core 21/21、I2 33/33、backup/profile pure 20/20、sanitizer 15/15、MySQL E2E 15/15，未 stage/commit/push。
- I1 18/18、I3 17/17 是 R0 前历史 pure-contract evidence；对应 active implementation、focused tests 和 project-rule registrations 已删除，不再参与候选 gate。
- 观止最终 `QA / PASS`；pure failure matrix、合成 historical restore、source/target 对账、stdout 隐私、evidence no-clobber/可恢复失败和 protected-schema residue 均通过。
- Gate 含义为 `IH-R1_HISTORICAL_RUNNER_GATE_PASS`；不代表 54.5MB 真实业务备份已盘点、R2 已授权、legacy migration/PRD AC/merge-ready 或提交许可。
