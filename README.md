# FBM Pipeline

亚马逊 FBM 铺货自动化管线系统

## 快速开始

```bash
# 首次 clone 后先初始化本地环境
./scripts/setup_local.sh

# 一键启动（后端 8190 + 前端 3190）
./scripts/start.sh

# 或分别启动
cd backend && source .venv/bin/activate && uvicorn app.main:app --host 0.0.0.0 --port 8190
cd frontend && npm run dev -- --host 0.0.0.0 --port 3190
```

`scripts/setup_local.sh` 会创建 `backend/.env`、`backend/.venv`、`data/products` 并安装前后端依赖。真实 API Key、OSS、卖家精灵 Token 和本机商品素材路径放在 `backend/.env`，不要提交。

## 常用命令

```bash
make help
make check
make full-check
make validate-template-mappings
make test-project-rules
make backend-compile
make frontend-build
```

## 项目规则与维护文档

- `AGENTS.md`：项目级协作规则。
- `docs/codex-collaboration-roles.md`：多 Codex 会话身份协作规约，可用于指定若命、听云、清秋、观止、霜弦等身份。
- `docs/collaboration/inbox.md`：多会话之间的轻量任务、回执、阻塞和验收留言板。
- 上下文预算：日常对话、新会话和 heartbeat 每轮优先使用当前用户消息、`AGENTS.md`、`git status --short` 和 inbox 相关消息；协作角色文档、冷启动文档、长 handoff 按需补读。
- `.cursor/rules/projectRule.mdc`：Cursor Project Rule，默认全项目生效。
- `docs/configuration.md`：正式配置归属、读取顺序和本地初始化规则。
- `docs/template-mapping-spec.md`：Amazon 模板映射规范。
- `docs/add-category-template-sop.md`：新增类目模板 SOP。
- `docs/runbook.md`：Pipeline 操作与故障手册。

## 端口

| 服务 | 端口 |
|------|------|
| 后端 API | http://localhost:8190 |
| API 文档 | http://localhost:8190/docs |
| 前端 | http://localhost:3190 |

## 技术栈

- **后端**: FastAPI + SQLAlchemy (async) + SQLite
- **前端**: React + TypeScript + Ant Design + Vite
- **AI**: GPT-5.5 (LLM/VLM) + GPT Image

## 当前主链路

当前 P0 主线聚焦“商品拉取到 Amazon 导出任务结果文件”。旧的浏览器 Step1 商品采集已停用，A+ 规划/脚本/出图已从商品主流程拆出，作为后续独立能力处理。

```
GIGA OpenAPI 拉品/图片
→ Product 草稿
→ 利润计算、关键词、类目
→ 选图、搜索/选择参考竞品、抓取竞品详情
→ 图片分析
→ Listing 文案
→ CatalogProduct 待导出
→ 用户在导出中心创建离线导出任务
→ OfflineTask 生成 Amazon 导入表格 zip 和报告
```

主页面：

- `/products`：商品工作台，展示 Product 草稿和当前下一步动作。
- `/products/{id}`：商品详情，处理选图、竞品、类目、图片分析和 Listing。
- `/export-center`：导出中心，人工创建导出任务、查看历史任务和下载产物。
- `/offline-tasks`：任务中心，查看 GIGA 拉品、库存/价格同步、A+生成、Amazon 导出等离线任务事实。
- `/inventory-sync`：GIGA 库存事实页；库存 0 不阻断商品进入待导出，导出首次导入表时写入 Quantity `0`。

关键边界：

- Step1 浏览器采集不可再作为入口；商品来源以商品数据源/GIGA OpenAPI 拉取为准。
- A+ 缺失不阻断当前导出主链路。
- “已导出”表示历史任务或文件可追溯，不表示永久禁止再次创建导出任务。
- 已有真实 Amazon ASIN 的商品不能再次生成首次导入表格。
- Amazon 导出任务只生成文件和风险提示，完成后仍需人工确认，不等于“可运营完成”。

## 项目结构

```
fbm-pipeline/
├── backend/
│   ├── app/
│   │   ├── main.py          # FastAPI 入口
│   │   ├── config.py        # 配置管理
│   │   ├── database.py      # 数据库连接
│   │   ├── models/          # SQLAlchemy 模型
│   │   │   ├── models.py    # Product、CatalogProduct、OfflineTask、GIGA、ASIN、A+、UPC 等业务表
│   │   │   └── status.py    # Pipeline 步骤定义
│   │   └── api/
│   │       ├── products.py       # 商品、目录、导出、ASIN、库存、A+ 等接口
│   │       ├── offline_tasks.py  # 离线任务创建、状态、下载、重跑、暂停/恢复
│   │       ├── data_sources.py   # 商品数据源配置
│   │       ├── giga.py           # GIGA 拉品、库存、价格、告警查询
│   │       ├── amazon_stylesnap.py # Amazon 候选竞品搜索、选择、抓取
│   │       ├── config_api.py     # 系统配置
│   │       └── schemas.py        # Pydantic 模型
│   ├── app/pipeline/
│   │   ├── engine.py                 # 商品主流程编排
│   │   ├── step10_amazon_template.py # Amazon 模板映射和导出入口
│   │   ├── amazon_export/            # Amazon 导出字段填充规则层
│   │   ├── template_mappings/        # 类目模板映射 JSON
│   │   └── templates/                # Amazon xlsm 模板
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── App.tsx
│   │   ├── api/index.ts     # API 客户端 + 类型定义
│   │   ├── components/
│   │   │   └── MainLayout.tsx
│   │   └── pages/
│   │       ├── ProductList.tsx        # 商品工作台
│   │       ├── ProductDetail.tsx      # 商品详情 + 主流程操作
│   │       ├── CatalogList.tsx        # 导出中心
│   │       ├── OfflineTaskCenter.tsx  # 离线任务中心
│   │       ├── InventorySyncList.tsx  # 库存同步与库存事实
│   │       ├── AplusManagement.tsx    # A+ 管理
│   │       └── ProductDataSourceList.tsx # 商品数据源
│   ├── index.html
│   └── package.json
├── data/                    # 本地数据、导出文件和商品素材目录
├── docs/                    # 规则、SOP、runbook、协作和验收文档
└── scripts/
    ├── setup_local.sh       # 首次本地初始化
    ├── start.sh             # 一键启动
    ├── validate_template_mappings.py # 模板映射校验
    └── test_project_rules.py         # 项目规则回归检查
```
