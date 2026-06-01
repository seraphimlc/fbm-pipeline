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
make validate-template-mappings
make test-project-rules
```

## 项目规则与维护文档

- `AGENTS.md`：项目级协作规则。
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

## Pipeline 10步流程

```
0. created → 1. 商品采集 → 2. 利润计算 → 3. 关键词(卖家精灵) → 4. 类目获取
→ 5. Listing构建 → 6. 主图分析 → 7. A+规划 → 8. A+脚本 → 9. A+出图
→ 10. Amazon导入表格 → pending_review → completed
```

## 项目结构

```
fbm-pipeline/
├── backend/
│   ├── app/
│   │   ├── main.py          # FastAPI 入口
│   │   ├── config.py        # 配置管理
│   │   ├── database.py      # 数据库连接
│   │   ├── models/          # SQLAlchemy 模型
│   │   │   ├── models.py    # 4表: products, product_data, product_images, product_aplus
│   │   │   └── status.py    # Pipeline 步骤定义
│   │   └── api/
│   │       ├── products.py  # 商品 CRUD + Pipeline 控制
│   │       ├── config_api.py # 系统配置
│   │       └── schemas.py   # Pydantic 模型
│   ├── data/                # SQLite 数据库文件
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── App.tsx
│   │   ├── api/index.ts     # API 客户端 + 类型定义
│   │   ├── components/
│   │   │   └── MainLayout.tsx
│   │   └── pages/
│   │       ├── ProductList.tsx    # 商品列表
│   │       ├── CreateProduct.tsx  # 创建任务
│   │       └── ProductDetail.tsx  # 商品详情 + Pipeline 进度
│   ├── index.html
│   └── package.json
├── data/                    # 商品数据目录
├── docs/                    # 设计文档
└── scripts/
    ├── setup_local.sh       # 首次本地初始化
    └── start.sh             # 一键启动
```
