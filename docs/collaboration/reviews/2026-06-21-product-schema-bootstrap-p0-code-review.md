# Product Schema Bootstrap P0 Code Review

结论：`CODE_REVIEW / PASS`

本结论只代表 `MSG-20260621-024` 指定的 schema/bootstrap/startup 修复代码 review 通过；不是 QA PASS，不代表自动主链路、真实商品任务、导出、A+、TikTok 或外部平台验收。

## 审查范围

- `MSG-20260621-024`
- `docs/project-index.md`
- `docs/domain-index/runtime-security.md`
- `backend/app/database.py`
- `backend/app/main.py`
- `backend/app/config.py`
- `scripts/start.sh`
- `scripts/test_project_rules.py`

## 通过判断

1. `python -m app.database` 作为显式 schema maintenance 入口可以接受。

   `backend/app/database.py` 新增 `run_schema_maintenance()` 并在 module main 中调用；入口只由显式命令触发。`backend/app/main.py` 的普通 lifespan 仍然只在 `settings.STARTUP_RUN_DB_MAINTENANCE` 为 true 时调用 `init_db()`，而 `backend/app/config.py` 默认值仍为 `False`，没有改变普通 API startup 的 no-DDL 默认原则。

2. `_ensure_mysql_registered_tables()` 的顺序安全。

   当前 `init_db()` 先 `Base.metadata.create_all`，再逐表 `table.create(checkfirst=True)`，随后执行列/索引 ensure。第二次 table create 确实冗余，但 `checkfirst=True` 不会 drop/replace 已有表，也不覆盖数据；它补强了“缺整表时先建表，再跑表级列/索引 ensure”的恢复路径。

3. 缺整表、缺列、缺索引的恢复路径可重复。

   缺整表由 metadata create/table create 处理；缺列由 `_mysql_column_exists()` 后 `ALTER TABLE ADD COLUMN`；缺索引由 `_mysql_index_exists()` 后 `ALTER TABLE ADD INDEX`；GIGA scoped unique index 逻辑仍只在同名索引列定义不匹配时 drop/recreate。没有看到会在已有表上重建或清空数据的路径。

4. `scripts/start.sh` 的边界符合当前本地一键启动定位。

   脚本在 uvicorn 前执行 `python -m app.database`，能解决本地/测试库 ORM 新字段缺列导致商品 API 500 的问题；uvicorn 之后的 lifespan 仍由 `STARTUP_RUN_*` 开关控制，不会因为脚本改动让普通服务默认恢复 task、跑 backfill 或 kick runtime。

5. 文档/索引边界已同步。

   `docs/domain-index/runtime-security.md` 明确区分本地一键启动脚本的 schema maintenance 和普通 API lifespan 的 no-DDL 默认边界；`docs/project-index.md` 已把 runtime-security 和 database schema review 导航补齐。

## 验证

- `python -m compileall backend/app` PASS。
- `make test-project-rules` PASS，56 项。
- `git diff --check -- backend/app/database.py scripts/start.sh scripts/test_project_rules.py docs/domain-index/runtime-security.md` PASS。

若命/观止已提供但本轮未重复执行的环境证据：

- `cd backend && .venv/bin/python -m app.database` PASS。
- DB 抽样确认 `products.workflow_node`、`amazon_competitor_search_candidates.final_selected`、`task_runs.correlation_key` 存在。
- 商品列表/详情 API 已恢复 2xx；观止 `MSG-20260621-025` smoke rerun PASS。

## 非阻断风险

1. `scripts/start.sh` 仍会按当前 `.env` 指向的数据库直接跑 DDL。

   当前按“本地一键启动脚本”接受，不阻断提交；如果后续有人用该脚本连接远程/生产库，建议增加显式环境名、确认变量或只允许 local profile 跑 schema maintenance。

2. 新增项目规则仍偏结构字符串检查。

   这轮有若命手动 `python -m app.database` 和 DB/API 抽样补证据，足以通过 P0 code gate；但长期建议补一个最小 MySQL bootstrap 行为测试或脚本，覆盖“缺整表 -> 缺列 -> 缺索引 -> 重跑幂等”。

3. `init_db()` 仍承担 create table、列 ensure、索引 ensure 和少量数据补齐更新。

   这符合当前项目现状，不作为本轮返工项；后续如果引入正式 migration，应把这些 bootstrap ensure 逐步收敛到 migration/maintenance 边界。

## 未覆盖

- 未做页面 QA。
- 未触发真实商品 task run。
- 未运行真实导出、Amazon/VLM、A+、TikTok 或外部平台路径。
- 未执行会改库的 `python -m app.database`；本轮接受若命/观止已给出的环境证据。
