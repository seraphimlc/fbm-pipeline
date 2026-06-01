# Codex Cold Start Guide

这份文档给新的 Codex/开发代理使用，目标是在最短时间内理解本地项目、启动服务、定位问题，并避免破坏真实业务数据。

## 1. 先读这些文件

按顺序读：

1. `AGENTS.md`
2. `README.md`
3. `docs/runbook.md`
4. 涉及 Amazon 导入模板、类目、字段名或上架检查时，再读：
   - `docs/template-mapping-spec.md`
   - `docs/add-category-template-sop.md`
   - `docs/template-mapping-change-log.md`
   - `backend/app/pipeline/template_mappings/*.json`
   - `backend/app/pipeline/step10_amazon_template.py`

## 2. 项目定位

- 本地路径：进入当前 clone 的仓库根目录即可；用户常用路径是 `/Users/jiyuhang/code/fbm-pipeline`
- 后端：FastAPI + SQLAlchemy async + SQLite
- 前端：React + TypeScript + Ant Design + Vite
- 默认端口：
  - 后端 API：`http://localhost:8190`
  - API 文档：`http://localhost:8190/docs`
  - 前端：`http://localhost:3190`
- Pipeline 流程：Step 1 商品采集到 Step 10 Amazon 导入表格，最后进入人工复核/确认。

## 3. 本地环境准备

首次 clone 后优先运行：

```bash
./scripts/setup_local.sh
```

这个脚本会：

- 如果缺失，则从 `backend/.env.example` 创建 `backend/.env`
- 创建 `backend/.venv`
- 安装后端依赖
- 安装前端依赖
- 创建 `data/products` 和 `logs`

手动准备后端：

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

手动准备前端：

```bash
cd frontend
npm install
```

环境变量模板在 `backend/.env.example`。真实 `backend/.env` 不应提交到 GitHub。没有 `.env` 时，后端默认把数据库和商品素材放到仓库内的 `data/` 和 `data/products/`，保证新 clone 能启动。

## 4. 快速启动

一键启动：

```bash
./scripts/start.sh
```

分别启动，适合调试：

```bash
cd backend
source .venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8190
```

```bash
cd frontend
npm run dev -- --host 0.0.0.0 --port 3190
```

如果本机已配置开机启动，相关 LaunchAgent 文件在：

```text
/Users/jiyuhang/Library/LaunchAgents/com.fbm-pipeline.backend.plist
/Users/jiyuhang/Library/LaunchAgents/com.fbm-pipeline.frontend.plist
```

查看状态：

```bash
launchctl print gui/$(id -u)/com.fbm-pipeline.backend
launchctl print gui/$(id -u)/com.fbm-pipeline.frontend
```

## 5. 常用检查

轻量检查：

```bash
make check
```

完整检查：

```bash
make full-check
```

单项检查：

```bash
make validate-template-mappings
make test-project-rules
make backend-compile
cd frontend && npm run build
```

服务连通性：

```bash
curl -fsS http://127.0.0.1:8190/docs >/dev/null && echo backend ok
curl -fsS http://127.0.0.1:3190 >/dev/null && echo frontend ok
```

## 6. 调试入口

后端常看：

- `backend/app/main.py`：FastAPI 入口和路由注册
- `backend/app/config.py`：配置项
- `backend/app/api/products.py`：商品 CRUD、批量启动、Step 重跑、导出等主要接口
- `backend/app/pipeline/engine.py`：Pipeline 调度
- `backend/app/pipeline/step*.py`：各步骤实现
- `backend/app/models/models.py`：数据库模型

前端常看：

- `frontend/src/api/index.ts`：API 客户端和类型定义
- `frontend/src/pages/ProductList.tsx`：商品列表
- `frontend/src/pages/CreateProduct.tsx`：创建商品
- `frontend/src/pages/ProductDetail.tsx`：商品详情和 Step 操作
- `frontend/src/pages/CatalogList.tsx`：目录/批量视图

日志常看：

```text
logs/backend-8190.log
logs/frontend-3190.log
```

如果服务由手动终端启动，优先看当前终端输出。

## 7. 数据和安全边界

不要整体覆盖或清空这些内容，除非用户明确要求：

- `data/`
- `backend/data/`
- 用户已有商品数据
- 人工类目
- 真实 Amazon ASIN
- 已生成素材、图片、A+ 图
- Amazon 导入模板输出
- `backend/.env`

不要提交真实密钥。测试密钥也默认留在本地环境变量或本地配置文件里。

配置入口优先级：

- 后端主配置：`backend/.env`
- 后端默认模板：`backend/.env.example`
- 生图 skill 环境变量：`GPT_IMAGE_API_KEY`、`GPT_IMAGE_API_BASE`、`GPT_IMAGE_MODEL`
- 生图 skill 本地文件：`codex-skills/gpt-image-async/scripts/config.local.json`
- 生图 skill 默认模板：`codex-skills/gpt-image-async/scripts/config.json`

## 8. 模板映射修改规则

只要改动会影响 Step 10 类目匹配、字段填充或 Amazon 导入模板输出，就必须同步追加 `docs/template-mapping-change-log.md`。

常见触发范围：

- `backend/app/pipeline/template_mappings/*.json`
- `backend/app/pipeline/step10_amazon_template.py`
- `backend/app/pipeline/templates/*.xlsm`
- 影响 Step 10 导出字段或类目匹配的文档/配置

记录至少包含：日期、改动文件、涉及类目/模板、原因、验证命令和结果、后续注意事项。

## 9. GitHub 上传前检查

推送前至少跑：

```bash
git status --short --branch
git ls-files --others --exclude-standard
rg -n -i --hidden --glob '!.git/**' --glob '!**/node_modules/**' --glob '!**/.venv/**' --glob '!data/**' --glob '!logs/**' 'sk-[A-Za-z0-9_-]{20,}|api_key\"\\s*:\\s*\"sk-|secret_key\"\\s*:\\s*\"[^Y]' .
```

如果发现真实密钥，不要上传。先替换为占位符，并确认历史里也没有残留。

当前 GitHub 远程通常为：

```text
git@github.com:seraphimlc/fbm-pipeline.git
```
