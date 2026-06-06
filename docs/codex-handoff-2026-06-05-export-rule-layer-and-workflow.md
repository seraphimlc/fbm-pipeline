# Codex Handoff: 商品工作台、Amazon 同款、导出中心与导出规则层

日期：2026-06-05
仓库：`/Users/liuchang/Documents/gitproject/fbm-pipeline`
当前最新提交：`7ad0b82 Refactor Amazon export rule layer`，已 push 到 `origin/main`。
当前重点：主流程已从 GIGA item 维度进入商品工作台，完成图片确认、Amazon 同款候选、竞品选择、Listing 生成后到待导出；导出中心正在按“模板文件维度”拆分导出任务，并已开始沉淀 Amazon 导出规则层。

## 1. 新会话接手先执行

```bash
cd /Users/liuchang/Documents/gitproject/fbm-pipeline
git status --short
git log --oneline -5
sed -n '1,220p' AGENTS.md
sed -n '1,260p' docs/codex-cold-start.md
sed -n '1,260p' docs/codex-handoff-2026-06-05-export-rule-layer-and-workflow.md
```

注意：

- 不要打印 `backend/.env` 的 secret。
- 不要覆盖真实商品数据、真实 ASIN、已生成素材、已上传模板或已导出文件。
- 不要自动 commit / push，除非用户明确要求。
- 当前工作区在写本 handoff 前仍有未提交的非本次导出规则层改动：
  - `.cursor/rules/projectRule.mdc`
  - `AGENTS.md`
  - `README.md`
  - `docs/codex-cold-start.md`
  - `docs/codex-collaboration-roles.md`
- 上述未提交改动不是 `7ad0b82` 的内容，接手时要先看清楚再决定是否处理。

## 2. 用户确定过的业务共识

### 商品维度

- 商品工作台展示的是我们自己的 `Product/CatalogProduct` 维度，不是 raw data。
- 当前阶段以 GIGA item 维度为主，不做 SKU 维度的完整 listing 生成。
- SKU 是 item 下的子体，至少要有独立 SKU 图片、库存、价格。
- 后续关联 SKU 不应只靠 `sku_code + data_source_id`，要尽量通过主键关系关联，避免不同店铺同 SKU code 混淆。

### 店铺/数据源

- 用户不想再叫“数据源”，页面命名倾向“店铺”。
- 拉取商品叫“同步店铺商品”。
- GIGA AK/SK 不再依赖全局配置，应收敛到店铺/数据源表。
- 店铺支持多选同步。
- 后台离线操作应进入“任务中心”，包括同步店铺商品、图片下载、库存同步、价格同步、生成 Excel 等。

### 商品主流程

用户认可的主流程是商品从落盘开始就有一条 pipeline，但实现上不一定需要单独 pipeline 表。

核心节点方向：

1. 确认商品图片：选主图，同时确认 listing 图片，不再拆成两个独立步骤。
2. 搜索候选竞品：用确认的主图去 Amazon StyleSnap 搜索候选。
3. 选择竞品：用户从候选里选一个 item 级竞品。
4. 抓取竞品详情：选择竞品后抓取详情。
5. 图片分析：如果不是同一个功能，就不要和确认商品图片合并。目前按独立节点保留。
6. Listing 文案生成：完成后直接进入待导出，不需要再人工确认；不满意可在详情页重新生成。

关键规则：

- 进入新节点前必须检查前置节点状态，不符合预期就不能乱跳。
- 中间状态，如竞品抓取中、详情抓取中，页面要说明清楚且禁止冲突操作。
- 如果用户切换竞品，商品状态必须回退/阻塞后续流程，后续 Listing、图片分析、导出状态要按依赖重新处理。
- 已导出商品如果重新生成 Listing 或切换竞品，应回到待导出之前的合适状态，不能继续保持“已导出”假象。
- 商品支持“挂起/继续”，挂起后不再跑后续未完成自动流程。

### A+ 流程

用户已确认 A+ 不参与当前主流程。

- 主流程走到 Listing 生成完成即可待导出。
- 菜单里单独有 A+ 管理。
- A+ 管理要能看到“规划、脚本、内容/图片”状态或引导到商品详情查看。
- 只有待导出/已导出的商品可以操作生成 A+。
- 商品详情页保留 A+ 内容，并有 A+ 生成按钮。
- A+ 生成采用后台任务，可批量生成。
- A+ 生成如果没有真实生成，不要做 mock 降级兜底。

## 3. Amazon 同款与竞品

当前更稳定的方案：

- Amazon StyleSnap 获取候选仍需要浏览器打开一次，headless 理论可行但当前主要靠本机 Chrome。
- 只打开浏览器获取/执行 StyleSnap 上传搜索，其它候选增强尽量通过卖家精灵 API。
- 卖家精灵 API key 用户给过，但不要写入文档或输出 secret；应从 `.env` 或配置读取。
- 找竞品分两个动作：
  - 用主图搜索候选，后续追加候选，不应清空旧结果。
  - 用户选择一个候选后，再抓取该竞品详情。
- 候选数量用户要求从 Top 5 改为 Top 10。
- 竞品详情抓取失败时，页面要允许“重新抓取当前竞品”，不能锁死。

重要坑点：

- 页面上不要把“确认图片”“启动任务”“生成 Listing”混到抽卡页里；这些是不同功能。
- 商品工作台列表上不要再放“进入详情选图”这类干扰按钮，用户明确反感。
- 选择竞品的交互应在商品详情下方 tab 的“竞品”页里。
- 切换竞品时如果详情已存在可跳过详情抓取；如果不存在再抓，状态要流转正确。

## 4. 导出中心业务共识

导出是批量操作，不属于单个商品优化流程。

导出中心页面应聚焦：

- 待导出商品。
- 已导出商品。
- 类目模板/模板文件管理。
- 创建导出任务。

用户明确要求：

- 不要在导出中心塞 ASIN 同步、库存同步、A+ 上传等无关操作。
- 商品列表里的无关列要去掉，保留导出相关信息。
- 导出按钮只保留一个逻辑：如果有选中商品，导出选中的；如果没有选中，导出当前筛选/全部待导出。后续可做跨页全选。
- 导出任务不再按类目维度，而是按“模板文件维度”拆分。
- 一个模板文件可以覆盖多个类目。
- 如果某个商品类目没有被任何模板文件覆盖，提示重新下载/上传模板，商品先 hang 着，不影响其它可导出的商品。
- 如果一个类目被多个模板文件覆盖，先选一个可用模板文件即可。
- 模板文件统一上传到 OSS，下载时可缓存到本地。
- 生成的导出文件也要放 OSS，供页面下载。

模板文件列表应按文件维度展示：

- 文件编号
- 文件状态
- 支持类目
- 模板下载
- 模板启用/停用
- 文件删除

不再区分“内置”和“用户上传”，一视同仁。

## 5. 导出规则层重构现状

最新提交 `7ad0b82` 已完成第一版“导出规则层重构”。

新增目录：

```text
backend/app/pipeline/amazon_export/
  context.py
  common_fill.py
  package_fill.py
  image_fill.py
  offer_fill.py
  listing_fill.py
  validators.py
  writer.py
  registry.py
  strategies/
    sofa_chair.py
    bicycle.py
    ride_on_toy.py
    storage_furniture.py
```

当前设计：

- `mapping JSON` 只负责“逻辑字段 -> Amazon 模板列名”和模板基础配置。
- 具体取值、计算、模板族差异放到策略代码里。
- 所有模板先走通用填充：
  - `common_fill`
  - `listing_fill`
  - `offer_fill`
  - `image_fill`
  - `package_fill`
- 再按模板族走策略：
  - `sofa_chair`
  - `bicycle`
  - `ride_on_toy`
  - `home_storage_furniture`
  - `shelf_table_cabinet_gate`
- 最后统一跑校验、写表、报告。
- `backend/app/pipeline/step10_amazon_template.py` 的 `_build_amazon_template_file` 已改为薄适配层，调用 `amazon_export.writer.build_amazon_template_file`。

当前 5 个模板：

```text
backend/app/pipeline/templates/CHAIR_SOFA.xlsm
backend/app/pipeline/templates/BICYCLE_CYCLING.xlsm
backend/app/pipeline/templates/RIDE_ON_TOY.xlsm
backend/app/pipeline/templates/DRESSER_STORAGE_DRAWER_STORAGE_BOX_CABINET_STEP_STOOL.xlsm
backend/app/pipeline/templates/SHELF_TABLE_CABINET_ANIMAL_CAGE_TEMPORARY_GATE.xlsm
```

当前 5 个 mapping：

```text
backend/app/pipeline/template_mappings/vindhvisk_sofa.json
backend/app/pipeline/template_mappings/vindhvisk_bicycle.json
backend/app/pipeline/template_mappings/ride_on_toy.json
backend/app/pipeline/template_mappings/andy_storage_furniture.json
backend/app/pipeline/template_mappings/andy_shelf_table_cabinet_gate.json
```

重构验证已通过：

```bash
cd /Users/liuchang/Documents/gitproject/fbm-pipeline
cd backend && .venv/bin/python -m py_compile app/pipeline/step10_amazon_template.py app/pipeline/amazon_export/*.py app/pipeline/amazon_export/strategies/*.py
cd /Users/liuchang/Documents/gitproject/fbm-pipeline
make validate-template-mappings
```

临时样例生成也跑通过，输出曾写到 `backend/tmp/amazon_export_rule_test`，验证后已删除。

## 6. 导出任务与已验证数据

近期用 5 个商品跑过导出：

| Catalog ID | Product ID | Item Code | 类目 | 结果 |
|---:|---:|---|---|---|
| 1 | 1 | `N726P248345Y` | `Kids' Tricycles` | 已导出 |
| 2 | 2 | `W1019138605` | `Kids' Bikes` | 已导出 |
| 3 | 3 | `W101984862` | `Cruiser Bikes` | 当时按旧口径因最新 GIGA 库存 0 跳过；已被 2026-06-06 新口径废弃 |
| 4 | 4 | `W1019P165868` | `Cruiser Bikes` | 已导出 |
| 297 | 1071 | `W808P350170` | `Bookcases, Cabinets & Shelves` | 已导出 |

生成过的任务：

- Task 9：`BICYCLE_CYCLING` 模板，3 个成功，1 个当时按旧口径因库存 0 跳过；当前规则应继续导出并写入 Quantity `0`。
- Task 10：`SHELF_TABLE_CABINET_ANIMAL_CAGE_TEMPORARY_GATE` 模板，1 个成功。

注意：当时手工调用和后台自动执行重叠，产生过未引用的本地重复 zip。数据库最终已修正到干净结果，但这暴露了任务执行可靠性问题。

## 7. 任务中心稳定性待继续

用户最后明确要求过：检查任务执行稳定性和可靠性，做成可靠稳定的任务执行链路。

已分析出的风险：

1. `create_catalog_export_tasks` 等服务函数创建任务后会立即 `_schedule_offline_task`，函数有副作用。脚本里如果再手动调用执行步骤，容易重复跑。
2. `_active_offline_tasks` 是内存态，服务重启后 DB 中 `running` 任务可能没人接管。
3. `_execute_offline_task` 查询 pending steps 后逐个执行，但没有原子 claim。多调度/多进程可能执行同一步。
4. `_run_*_step` 内部会直接把 step 置 running，没有防止已 done 步骤被重复执行。
5. 导出 step 没有强 idempotency guard，重复跑会重新生成不同时间戳的 zip 并覆盖任务结果。
6. pause/resume 对阻塞中的外部操作不一定能快速生效。

建议下一步优先做：

- 给离线任务 step 增加原子 claim：
  - `UPDATE offline_task_steps SET status='running' WHERE id=:id AND status IN ('pending','interrupted')`
  - `rowcount != 1` 则跳过。
- `_execute_offline_task` 只能执行成功 claim 的 step。
- 已 done 的 step 不允许被 `_run_*_step` 重新跑。
- create 函数增加 `auto_start=True` 参数，脚本/测试可传 `False`，API 默认仍自动启动。
- 服务启动时恢复 DB 中遗留 running/interrupted 任务。
- 导出 step 增加 idempotency guard，已成功并有 result_json/file_path 的不要重复生成。

相关文件：

```text
backend/app/services/offline_tasks.py
backend/app/api/offline_tasks.py
backend/app/models/models.py
backend/app/main.py
```

## 8. 配置和运行

常用后端验证：

```bash
cd /Users/liuchang/Documents/gitproject/fbm-pipeline/backend
.venv/bin/python -m compileall -q app
```

模板映射验证：

```bash
cd /Users/liuchang/Documents/gitproject/fbm-pipeline
make validate-template-mappings
```

前端构建：

```bash
cd /Users/liuchang/Documents/gitproject/fbm-pipeline/frontend
npm run build
```

本地服务常用：

```bash
cd /Users/liuchang/Documents/gitproject/fbm-pipeline/backend
source .venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8190
```

前端端口之前见过 `3190`，接手时以当前 dev server 输出为准。

数据库：

- 用户曾要求把本地 MySQL `fbm_pipeline` 平迁到线上服务器 `visitworld.me`，并让本地项目使用线上数据库。
- 具体 `.env` 连接信息不要在文档中写出；接手时看 `backend/.env`，不要打印 secret。

## 9. 用户偏好和沟通重点

用户非常在意：

- 功能边界清晰，不要把抽卡、任务启动、导出、商品详情混成一团。
- 页面布局不要乱，表格不要被长标题撑爆。
- 状态说明要明确，失败要说明是哪一步失败。
- 失败后要有合理重试，不要锁死。
- 后台自动流程不能乱跳，前置节点不满足就不要执行后续节点。
- 不要做假的功能，不要 mock 冒充真实生成。
- 不要重复抓 GIGA 页面；重新拉 GIGA 商品数据要走 GIGA Open API。
- 能用 URL 的图片交互就用 URL，除非像 StyleSnap 上传这类必须本地文件/二进制上传。

## 10. 下一步建议

优先级建议：

1. 先修任务中心可靠性，避免导出、同步、A+ 生成重复执行或卡死。
2. 再检查导出中心页面是否完全符合“模板文件维度 + 一个导出按钮 + 可选商品”的设计。
3. 继续导出规则层第二阶段：
   - 把 `step10_amazon_template.py` 中被新策略复用的 legacy helper 逐步迁到 `amazon_export` 子模块。
   - 每迁一批都跑 5 模板族样例生成。
   - 不要一次性大改所有模板字段。
4. 后续新增模板时：
   - 上传模板。
   - 解析列名。
   - 选择已有策略族。
   - 补 mapping JSON。
   - 跑样例商品导出测试。
   - 更新 `docs/template-mapping-change-log.md`。

## 11. Git 状态参考

截至本 handoff 生成前：

```text
最新已 push: 7ad0b82 Refactor Amazon export rule layer
上一提交: 2f3822a Refine product workflow and template-based exports
```

本 handoff 文档创建后会成为新的未提交改动。用户如果要求提交，需要注意不要把第 1 节列出的其它未提交文件一起误提交。
