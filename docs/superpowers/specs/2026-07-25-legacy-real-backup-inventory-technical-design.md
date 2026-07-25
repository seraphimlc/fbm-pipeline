# Legacy 真实备份只读 Inventory 技术增量

状态：READY_FOR_REREVIEW
日期：2026-07-25
Owner：听云（agentKey: `tingyun`）
产品授权：用户已授权真实备份只读 inventory、受保护临时 schema、证据落盘、后续评审通过后的实现/执行/提交/推送

## 1. 结论

在现有 `legacy_migration.py` 中新增与 `--fixture-e2e` 互斥的 `--backup-inventory` 模式。该模式只读取一个已经落地的本地 SQL 备份，只连接 `127.0.0.1:3306`，仅创建并删除本轮随机生成的 protected source/target schema；不连接备份 header 中的远程 host，不读取应用 `DATABASE_URL`，不修改业务 schema，不启动浏览器、服务或外部平台调用。

证据范围固定为 `historical_archive_restore_inventory`。它证明“指定备份文件 -> protected source -> canonical dump -> protected target”的六表恢复与 inventory 一致性，不证明该备份是线上库的实时或事务一致快照。

## 2. 固定输入事实

本轮候选备份：

- 路径：`/Users/liuchang/Documents/gitproject/fbm-pipeline/tmp/db-backups/fbm_pipeline_before_clear_20260612_151753.sql`
- 类型：regular file、non-symlink、Git untracked
- 大小：`54,500,527` bytes
- SHA-256：`b608c6a1f3200ea2df6b4e3f438f1db00bd22eb185bbecb5986e84c9778c4663`
- header：mysqldump 9.6.0；Host `visitworld.me`；Database `fbm_pipeline`；Server 8.0.46
- 六张 inventory 必需表均存在；`task_runs`、`task_steps` 不存在
- 未发现 `CREATE/DROP DATABASE|SCHEMA`、`USE`、用户/授权、`SET GLOBAL`、DEFINER、trigger、procedure、function 或 event
- `products` 有 `source_site/source_batch_id`，但没有 `workflow_node/workflow_status/workflow_error`
- `catalog_products` 有 `exported_at/export_task_id/export_file_path`

以上事实只用于锁定本轮输入和设计，不替代运行时重新校验。

## 3. CLI 契约

`--backup-inventory` 与 `--fixture-e2e` 必须二选一。

真实模式必填：

- `--backup-path <absolute-path>`：必须是 regular、non-symlink 文件。
- `--expected-backup-sha256 <64-lower-hex>`：必须与流式计算结果一致。
- `--evidence-output <absolute-path>`：必须位于所有 Git worktree 之外，目标文件不存在。
- `--candidate-sha <40-lower-hex>`：必须等于 clean HEAD。
- `--mysql-binary <absolute-path>`、`--mysqldump-binary <absolute-path>`。
- `--host 127.0.0.1 --port 3306`。
- `--user <token>`。
- 本轮认证必须显式使用 `--allow-passwordless-local`；未来若支持 login path，另行设计和测试，不在本切片隐式读取 defaults 或环境密码。

调用者不能提供 source/target schema。运行器生成：

- `fbm_pipeline_ih_<16-lower-hex>_source`
- `fbm_pipeline_ih_<16-lower-hex>_target`

schema collision 在创建任何 schema 前失败。

## 4. 离线备份安全校验

运行器以单一只读文件描述符打开备份，导入前完成全文件扫描，导入后重新 `fstat` 并复算摘要。设备号、inode、size、mtime 或 SHA-256 变化均返回 `backup_changed_during_run`。

允许普通 mysqldump 表级 DDL/DML及批准的 session `SET`。必须拒绝：

- `CREATE/DROP DATABASE|SCHEMA`、`USE`
- 跨 schema 限定对象
- `USER/ROLE/GRANT/REVOKE`
- `SET GLOBAL|PERSIST`
- `DEFINER`、trigger、procedure、function、event
- `LOAD DATA`、`INTO OUTFILE|DUMPFILE`、`SOURCE`
- plugin/component/install/shutdown 等服务器级操作

sanitizer 必须处理字符串、普通注释、语句边界和 MySQL executable comment。`/*!<version> ... */` 不是普通注释：必须抽出其 SQL body 后按实际执行语义分类。闭合 allowlist 只允许 mysqldump 所需的 session `SET`，以及针对当前 protected schema 内已创建表的 `ALTER TABLE ... DISABLE|ENABLE KEYS`；executable comment 内出现其它语句一律失败。

mysql client 必须显式使用 `--commands=OFF --disable-named-commands`。sanitizer 同时拒绝所有 client meta-command，包括 `\!`、`SYSTEM`、`CONNECT`、`SOURCE`、`DELIMITER`、`TEE`、`PAGER`、`PROMPT`、`QUIT` 及其它反斜杠命令，不能依赖客户端默认值作为唯一防线。

不能只对原始字节做容易被注释、大小写或 executable comment 绕过的单一子串判断。任何无法可靠分类的非普通 mysqldump 语句都 fail closed。

所有 preflight 校验必须在创建 schema 前完成。

## 5. 执行链与数据绑定

1. 校验 candidate clean HEAD、CLI、工具、端点、认证、备份、证据路径和 protected schema collision。
2. source 名称通过 collision preflight 后，在发出 `CREATE DATABASE` 前登记 `creation_attempted` cleanup reservation；该 reservation 只覆盖本轮随机且 preflight 已证明不存在的精确名称。
3. 将原始备份仅导入 source；禁止 SQL 改变当前 schema。
4. 读取 source 六张 Legacy 表，生成 compatibility profile、canonical source snapshot 和 inventory。
5. 对 source 使用固定参数生成 canonical dump：`--single-transaction --set-gtid-purged=OFF --skip-comments --skip-dump-date --no-tablespaces`。
6. 使用 historical archive 专用 source manifest proof/position 绑定原始备份 SHA、protected source snapshot 和 canonical dump；不得复用 fixture 标签。
7. 创建 target，成功后立即登记 owned；导入 canonical dump。
8. 生成 target snapshot 与第二次 inventory；source/target 表快照、投影、records count/digest 必须逐项一致。
9. 验证 task sentinel 和 Step 10 隔离目录无变化。
10. `finally` 逆序删除 target/source；只删除 owned schema，并确认 protected schema 与临时目录无本轮残留。
11. cleanup 成功后，以 no-clobber 私有写入方式落盘完整证据；fsync 成功后才允许 exit 0。

原始备份摘要、protected source manifest、canonical dump 摘要、source/target snapshot 摘要与 records 摘要必须同时进入证据，避免把 fixture 或另一个 dump 的结果冒充本轮结果。

### 5.1 Historical archive manifest

在 `database_source_manifest.py` generation 1 中新增且只新增以下兼容分支：

- `consistency_proof.proof_mode = historical_archive_restored_quiesced_logical_backup`
- `backup.snapshot_position.kind = historical_archive_sha256`
- `backup.snapshot_position.value = <原始备份 64 位小写 SHA-256>`
- `consistency_proof.manifest_snapshot_position` 必须与上述 position 完全一致
- source schema 仍必须是 protected `fbm_pipeline_ih_<nonce>_source`
- `writer_quiesced=true`、`global_read_lock_held=false`、`storage_snapshot_id=null`
- manifest 的 `backup.backup_sha256` 继续绑定从 protected source 生成的 canonical dump，而不是原始备份

因此同一个 manifest 同时通过 position 绑定原始 archive SHA，通过 table/projection snapshots 绑定 protected source 读取结果，通过 `backup.backup_sha256` 绑定 canonical dump。完整 evidence 再记录原始 archive metadata 与 sanitizer 结果。原有 `fixture_copy/fixture_quiesced_logical_backup` 合同、fixture tests 和现有 CLI 语义保持不变。

## 6. 旧 schema 兼容

- `products.workflow_node/workflow_status/workflow_error` 同时缺失时，兼容投影固定为 JSON `null`；禁止从 `status/current_step/error_message` 猜测。
- 三个 workflow 字段部分缺失时返回 `unsupported_legacy_shape`，避免混合语义。
- source 与 target 必须使用同一个 compatibility profile；profile、实际列集合和缺列集合进入证据并参与摘要。
- 其它 inventory 身份、精确关联、模板/Catalog/A+ preserve-first 所需列缺失时直接 `unsupported_legacy_shape`，不得静默补默认值。
- 当前备份已有 `source_site/source_batch_id` 和 Catalog export 字段，因此 candidate/capture 仍使用精确 `batch/site/item_code` Product 匹配，不回退为 item_code-only。

## 7. Task/Step 10 副作用 sentinel

当前备份没有 `task_runs/task_steps`，使用 absence sentinel：

- source：inventory 前后都必须 absent。
- target：restore 后和 inventory 后都必须 absent。
- 任一阶段出现即 `task_sentinel_changed`。

不得为了 sentinel 创建 task 表。若未来备份原本包含 task 表，需另行扩展为表存在性、行数、PK 边界和 canonical checksum 前后对比；本切片不自动改变合同。

Step 10 继续使用隔离 `DATA_DIR` 和目录快照，新增、删除、修改或 symlink 变化均失败。

## 8. Evidence 与 stdout

`--evidence-output`：

- parent 必须已存在、non-symlink、当前用户所有且权限严格为 `0700`
- output 必须不存在
- 使用 `O_CREAT|O_EXCL|O_NOFOLLOW` 创建为 `0600`
- 禁止位于任一 Git worktree
- 完整 records、ASIN、item_code 只能进入该私有文件

完整 evidence 至少包含：

- scope、candidate SHA、运行源码摘要
- 原始备份 metadata/SHA-256及脱敏 header facts
- sanitizer 结果与 compatibility profile
- protected source manifest/detached digest/canonical dump digest
- source/target snapshot digest
- classification counts、record count、records digest 与完整 records
- subprocess/endpoint allowlist、task/Step 10 sentinel
- cleanup 结果

evidence 文件是“不含自身摘要字段”的 canonical JSON payload。文件以固定 UTF-8 canonical bytes 写入并 fsync 后，对实际落盘的完整字节计算 SHA-256；该 `evidence_sha256` 只进入 stdout 成功摘要，不写回 evidence 文件，也不生成可覆盖的隐式 sidecar。验证者以文件全部字节为唯一 preimage 重算。

stdout 成功摘要只允许：status、scope、classification counts、record count、backup/source/target/records/evidence digests、cleanup success。失败摘要只允许 error code、phase、cleanup success 和脱敏消息；不得输出 full records、ASIN、item_code、凭据、备份正文或原始 MySQL stderr。

## 9. 错误与 cleanup

稳定错误码至少包括：

- `backup_path_invalid`
- `backup_hash_mismatch`
- `backup_changed_during_run`
- `unsafe_backup_sql`
- `forbidden_database_endpoint`
- `invalid_auth_transport`
- `candidate_source_not_clean`
- `evidence_path_unsafe`
- `protected_schema_collision`
- `source_restore_failed`
- `required_table_missing`
- `unsupported_legacy_shape`
- `source_target_snapshot_mismatch`
- `inventory_digest_mismatch`
- `task_sentinel_changed`
- `cleanup_failed`

每个 schema 都有 `creation_attempted`、`create_returned_success` 和 `observed_present` 状态。collision preflight 通过后、发出 CREATE 前即建立 cleanup reservation。若 CREATE 在服务端生效后客户端断连、超时或返回错误，运行器重新列出 protected schemas；发现精确名称时标记 `observed_present=true`。即使 reconciliation 查询也失败，finally 仍可对该 preflight-absent、非用户提供的精确随机名称执行 `DROP DATABASE IF EXISTS`，并记录 reconciliation/cleanup 证据，防止未知结果漏清理。

创建 source 后的所有异常进入同一个 `finally`。主错误保留为 `primary_error_code`；CREATE 结果未知不能覆盖主错误。cleanup 再失败时附加 `cleanup_failed=true`。cleanup 失败优先决定最终失败，即使 inventory 与证据内容已经生成也不能返回成功。

## 10. 实现蓝图

- `scripts/integration_hardening/legacy_migration.py`
  - 新模式参数、`run_backup_inventory()`、compact stdout 和稳定错误 phase/code。
- `scripts/integration_hardening/legacy_inventory_mysql.py`
  - 流式 import/dump、列 introspection、compatibility projection、task absence sentinel、schema creation reconciliation 与 owned cleanup reservation。
- 新增 `scripts/integration_hardening/legacy_backup_sanitizer.py`
  - SQL tokenizer、MySQL executable comment 展开、session SET/ALTER KEYS allowlist、client meta-command/危险语句/跨 schema 拒绝、fd metadata/hash 稳定性。
- `scripts/integration_hardening/database_source_manifest.py`
  - 新增 historical archive proof/position；fixture proof 保持不变。
- `scripts/integration_hardening/legacy_run_evidence.py`
  - 私有 no-clobber writer、evidence digest、stdout/error 脱敏。
- `scripts/testing/test_integration_hardening_legacy_inventory_mysql.py`
  - backup 模式 MySQL E2E、workflow 缺列兼容、task absence、source/target/cleanup。
- 新增或扩展 focused pure tests
  - CLI 互斥/必填、sanitizer 绕过矩阵（含 executable comment 与 client meta-command）、hash/file-swap/symlink、historical/fixture manifest 分流、compatibility profile、evidence 固定字节向量/权限/no-clobber/stdout 隐私、CREATE unknown result reconciliation、primary+cleanup error。
- `scripts/test_project_rules.py`
  - 保持 I2/Legacy 两个 active targeted gate；扩展现有 Legacy gate，不增加已退休 command skeleton。
- `docs/domain-index/runtime-security.md`、`docs/project-index.md`
  - 新增真实备份入口、证据范围、验证命令和不连接远端的边界。
- 本文与状态复查文档
  - 执行后写入真实 inventory 的范围、digest、分类计数和 R2 决策；不写完整 records。

## 11. 验收

- 危险 SQL（含 executable comment/client command）、hash/file swap、symlink、证据路径、wrong SHA、wrong candidate、schema collision 在任何业务或 protected schema 写入前失败。
- 只创建符合正则的随机 source/target；失败与成功均 owned-only cleanup，零残留。
- 当前真实备份可以在缺 workflow 三列、缺 task 两表的情况下按本设计执行；其它关键缺列 fail closed。
- 两次 inventory 和 source/target snapshot/digest 一致；tamper 负向失败。
- stdout 无 records/ASIN/item_code/credential/原始 stderr；完整证据权限 `0600`，parent `0700`，不可覆盖。
- evidence SHA 的 preimage 是落盘文件全部 canonical bytes；单字段篡改必须导致重算失败。
- historical manifest 不出现 fixture proof/position；原 fixture manifest 和 focused tests 保持原结果。
- 故障注入模拟 CREATE 服务端生效后客户端报错，精确 schema 仍被 reconciliation/cleanup 删除，主错误保留。
- 不连接 `visitworld.me`，不读取应用 `DATABASE_URL`，不启动 LOCAL Chrome、FastAPI、Vite、Playwright 或外部平台调用。
- 镜花设计/代码评审与观止 QA 均 PASS 后，才允许执行指定真实备份并据结果决定 R2。
