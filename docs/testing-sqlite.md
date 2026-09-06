# SQLite 测试环境

更新日期：2026-09-06。

## 运行方式

数据库测试统一使用独立临时 SQLite 文件，不读取业务数据库作为测试目标，也不再需要本机 MySQL 或 `R1_TEST_MYSQL_ADMIN_URL`。

```bash
make test-project-rules
backend/.venv/bin/python scripts/test_stability_repair_r1_catalog_export.py
backend/.venv/bin/python scripts/test_stability_repair_r1_workflow_actions.py
backend/.venv/bin/python scripts/test_stability_repair_r1_tiktok.py
backend/.venv/bin/python scripts/test_stability_repair_r1_catalog_frontend.py
backend/.venv/bin/python scripts/test_stability_repair_r1_tiktok_frontend.py
backend/.venv/bin/python scripts/testing/test_run_with_r1_sqlite.py
```

通用入口：`backend/.venv/bin/python scripts/testing/run_with_r1_sqlite.py -- <command...>`。
旧的 `r1_mysql.py`、`run_with_r1_mysql.py`、`test_run_with_r1_mysql.py` 已由同名 SQLite 版本替代；历史计划中的 MySQL 测试命令不再适用。业务数据库的 MySQL/SQLite 切换能力未删除。

原先直接导入应用数据库的主链路、竞品详情、自动选竞品、图片分析/Listing、A+ 自动触发、领星同步/草稿和任务 autostart 测试，直接执行时也会自动进入隔离 wrapper。纯函数测试不需要数据库。

## 隔离约束

- 在首次导入 app 前设置 `DATABASE_BACKEND=sqlite`、临时 `SQLITE_DATABASE_PATH`、`DATA_DIR` 和 `PRODUCT_BASE_DIR`。
- 使用应用真实 ORM、建表逻辑、外键和 WAL；子进程/API 服务共享同一临时库。
- 强制关闭启动恢复、自动唤醒和真实 Amazon 浏览器/领星调用开关。各测试仍须保留自己的外部 API mock/网络护栏。
- 结束时关闭连接并清理临时文件，子进程错误码不被吞掉。project-rules 仍校验规范命令、数据库路径和一次性 marker。
- 导出集成用例之间重建临时 schema，并清理该临时目录内的 exports/products，避免 UPC 分配顺序与相同任务 ID 的缓存文件串扰。
- `test_run_with_r1_sqlite.py --harness-only` 仅验证隔离/失败清理/子进程/marker 防伪；默认命令仍包含完整 project-rules，不应把 harness-only 当作全套通过。

## 本轮验证

测试环境切换已完成，但全套回归尚未通过。以下失败未改成跳过，也未放宽业务断言。

| 入口 | 结果 |
| --- | --- |
| `test_sqlite_database_mode.py` | 通过，包含跨增量库存查询 |
| `test_run_with_r1_sqlite.py --harness-only` | 通过 |
| `test_task_runtime_autostart.py` | 通过，含租约心跳/终态停止 |
| `test_stability_repair_r1_catalog_export.py` | 通过全部 24 个 DB 用例及纯函数契约 |
| `test_stability_repair_r1_catalog_frontend.py` | 通过，真实 SQLite API + Playwright |
| `test_aplus_auto_trigger_a1_a2.py --stage a2` | 通过 |
| `test_competitor_candidate_capture_phase2a.py` | 通过 |
| `test_lingxing_listing_sync_tasks.py` | 通过 |
| `test_lingxing_aplus_publish_tasks.py` | 通过，外部调用为 fixture |
| `test_listing_title_highlights.py` | 通过 |
| `test_stability_repair_r1_remote_guard.py` | 通过，真实 Vite/FastAPI 写入护栏 |
| `test_stability_repair_r1_mutation_frontend.py` | 未通过：57 个场景共用的 harness 未加载 mutation runner，`observedRuntimeIds=[]` / `upstream_count=0`；独立 remote guard 已通过 |
| `test_project_rules.py` / 默认 wrapper focused test | 通过，自动选图规则按批次级低置信度排除契约校验 |
| `test_stability_repair_r1_workflow_actions.py` | 未通过：旧 fixture 只定义 5 个 API family，当前 manifest 为 8 个，需补确认/素材/关键词场景 |
| `test_auto_competitor_selection_e4.py` | 未通过：medium fixture 实际分数 0.781，旧断言要求小于 0.78，需核对现行评分契约 |
| `test_image_analysis_listing_e5.py` | 通过：心智持久化契约及 Listing 进入 A+ 人工确认门已与现行流程对齐 |
| `test_amazon_main_chain_after_search_qa_fixes.py` | 未通过：旧链路预期直接创建图片分析任务，当前进入关键词/定价路径并因 fixture 缺成本停止 |
| TikTok 后端与页面测试 | 未通过：`backend/app/services/tiktok_status.py` 仍有 `JSON_TABLE ... COLUMNS` 等 MySQL 8 专有 SQL，SQLite 报语法错误，真实列表 API 返回 500 |

TikTok 是真实业务 SQLite 兼容遗留，不是测试连错数据库；需要单独适配查询并保留分页、状态桶、价格精度、SKU 规范化和分仓库存边界验证。其余失败需要逐项确认 fixture/断言与当前业务契约，不能直接修改预期值以追求全绿。
## SQLite Large-Field Migration Maintenance Window

Stop the local API and workers first. The migration targets only the configured
SQLite file; it refuses to use MySQL and does not migrate binary assets.

```bash
cd backend
.venv/bin/python -m app.migrations.product_large_fields preflight --db ../data/fbm-pipeline.db
.venv/bin/python -m app.migrations.product_large_fields migrate --db ../data/fbm-pipeline.db --backup-dir ../data/backups --confirm
.venv/bin/python -m app.migrations.product_large_fields verify --db ../data/fbm-pipeline.db --strict
.venv/bin/python ../scripts/test_product_large_fields_migration.py
```

Do not start the new service version unless strict verification passes. To
rollback, stop services and restore the generated backup using `rollback
--db ../data/fbm-pipeline.db --backup <backup-path>`; it restores the original
database and does not delete legacy columns or product files.

## 2026-09-06 真实库迁移结果

- Marker: `product_large_fields_v1`, applied at `2026-09-06T11:48:38.974609+00:00`.
- Backup: `data/backups/fbm-pipeline.before-product-large-fields-20260906194838399506.db`.
- Backup SHA-256: `de178c92e924b2cf917d8a083ebb89eddd99b44b511c1825a7b80a8a55ddf415`; database and checksum file permissions are `0600`.
- Strict verification: `ok=true`, `integrity_check=ok`, foreign-key violations `0`, migration items `191 ready / 0 unresolved`, legacy INSERT/UPDATE guards `58`.
- Section rows: source `21`, snapshot `21`, mindset `20`, Listing `21`, image analysis `21`, image selection `21`, image compliance `3`, A+ plan/script/assets `20/20/20`, export artifact `3`; all rows are `ready`.
- Mindset migration validated all 20 existing local-file references. The remaining product had no source mindset body and therefore correctly has no child row.
- Browser verification: `frontend/tests/product-sections.r1.spec.ts` covers ready/processing/absent/failed/unresolved states, GET-only mindset loading, retained loaded questions, and independent A+ plan/script/assets requests.

Known unrelated regression failures remain explicit: workflow action SQLite fixture still models 5 of 8 API families; the project-rule auto-image test requires the old literal `confidence == "low"`; the E4 score fixture expects `<0.78` but produces `0.781`; the old Amazon main-chain fixture lacks pricing facts; TikTok status SQL still uses MySQL-only `JSON_TABLE`; and the mutation UX harness does not load its runner. These failures predate and do not mutate or invalidate the large-field migration.
