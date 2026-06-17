# Codex Cold Start Guide

这份文档给新的 Codex/开发代理使用，目标是在最短时间内理解本地项目、启动服务、定位问题，并避免破坏真实业务数据。

## 1. 先读这些文件

冷启动分两档。普通日常对话、heartbeat、短任务或已知身份会话，不要默认读取完整长文档。

最小启动：

1. 当前用户消息
2. `AGENTS.md`
3. `git status --short`
4. `docs/project-index.md`
5. `docs/collaboration/inbox.md` 中给当前身份或全体的 OPEN/ACKED/待处理消息

以下文件按条件补读：

6. 多会话协作首次进入、身份/协作规约不确定或规则变化时，读 `docs/collaboration.md`
7. 环境不熟、长时间缺席、复杂 handoff 或需要完整项目冷启动时，读 `README.md`、`docs/README.md`、`docs/configuration.md`、`docs/runbook.md`
8. 做商品拉取到导出主链路 QA 或发布前复核时，再读：
   - `docs/main-flow-qa-checklist.md`
   - `docs/main-flow-user-path.md`
9. 涉及 GIGA 商品池、库存同步、价格同步、库存告警或库存模板导出时，再读：
   - `docs/giga-buyer-openapi-reference.md`
   - `docs/giga-inventory-sync.md`
   - `backend/app/services/giga_openapi.py`
   - `backend/app/services/giga_inventory_sync.py`
   - `backend/app/services/giga_price_sync.py`
   - `backend/app/api/giga.py`
10. 涉及 Amazon 导入模板、类目、字段名或上架检查时，再读：
   - `docs/template-mapping-spec.md`
   - `docs/add-category-template-sop.md`
   - `docs/template-mapping-change-log.md`
   - `backend/app/pipeline/template_mappings/*.json`
   - `backend/app/pipeline/step10_amazon_template.py`

读取 `docs/collaboration/inbox.md` 等长文件时，先用 `rg` 搜索当前 `agentKey`、消息编号、topic 或文件路径，只读取相关段落和引用链。日常对话只带当前问题所需事实，不要把完整 inbox、旧聊天记录、完整日志或大段真实商品数据装入上下文。

## 2. 项目定位

- 本地路径：进入当前 clone 的仓库根目录即可；用户常用路径是 `/Users/jiyuhang/code/fbm-pipeline`
- 后端：FastAPI + SQLAlchemy async + MySQL
- 前端：React + TypeScript + Ant Design + Vite
- 默认端口：
  - 后端 API：`http://localhost:8190`
  - API 文档：`http://localhost:8190/docs`
  - 前端：`http://localhost:3190`
- Pipeline 流程：Step 1 商品采集到 Step 10 Amazon 导入表格，最后进入人工复核/确认。

## 2.1 多会话身份协作

当用户在不同 Codex 会话中指定身份时，按 `docs/collaboration.md` 工作：

- 若命（agentKey: `ruoming`）：产品方向、架构边界、review、handoff 和多 agent 协作控制。
- 听云（agentKey: `tingyun`）：工程实现、测试、本地验证和收口。
- 清秋（agentKey: `qingqiu`）：页面体验、信息架构和用户路径。
- 观止（agentKey: `guanzhi`）：QA gate、验收路径和风险复核。
- 霜弦（agentKey: `shuangxian`）：Amazon/GIGA/库存/价格/类目映射运营口径复核。

每个身份都必须从磁盘事实和 `git status --short` 开始，不依赖另一个会话的口头结论。

跨会话正式消息写入 `docs/collaboration/inbox.md`；复杂交接写入 `docs/codex-handoff-YYYY-MM-DD-*.md`，再在 inbox 留链接。

## 3. 本地环境准备

首次 clone 后优先运行：

```bash
./scripts/setup_local.sh
```

这个脚本会：

- 如果缺失，则从 `backend/.env.example` 创建 `backend/.env`
- 创建 `backend/.venv`
- 如果缺失，则从 `frontend/.env.example` 创建 `frontend/.env`
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

### 3.1 新机器最小配置

其他人下载代码后，正常流程是：

```bash
git clone git@github.com:seraphimlc/fbm-pipeline.git
cd fbm-pipeline
./scripts/setup_local.sh
```

初始化完成后，主要编辑 `backend/.env`。`frontend/.env` 一般不需要动，除非更改后端端口或要连接远程后端。

`backend/.env` 里最常需要确认的配置：

```text
PRODUCT_BASE_DIR
LLM_API_KEY
GPT_IMAGE_API_KEY
GPT_IMAGE_USE_LLM_API
OSS_ACCESS_KEY_ID
OSS_ACCESS_KEY_SECRET
OSS_BUCKET
OSS_ENDPOINT
SELLERSPRITE_TOKEN
```

配置要求按使用场景区分：

- 只打开页面、看接口、做普通前后端开发：可以先不填 API key。
- 跑 Listing、图片分析、A+ 规划或 A+ 脚本：需要 `LLM_API_KEY`。
- 跑 A+ 出图：需要 `GPT_IMAGE_API_KEY`，或设置 `GPT_IMAGE_USE_LLM_API=true` 复用 LLM 通道。
- 生成带图片 URL 的 Amazon 导入表：需要 OSS 配置。
- 跑卖家精灵关键词：需要 `SELLERSPRITE_TOKEN` 或可用浏览器登录态。
- 采集真实商品素材：`PRODUCT_BASE_DIR` 必须改成当前机器存在的商品素材根目录。

配置好后启动：

```bash
./scripts/start.sh
```

## 4. 快速启动

一键启动：

```bash
./scripts/start.sh
```

分别启动，适合调试：

```bash
cd backend
source .venv/bin/activate
uvicorn app.main:app --host 127.0.0.1 --port 8190
```

```bash
cd frontend
npm run dev -- --host 127.0.0.1 --port 3190
```

不要默认使用 `0.0.0.0` 暴露服务；如确需远程访问，先按 `docs/superpowers/specs/2026-06-17-p0-security-startup-triage-prd.md` 确认访问边界。

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
- 生图 skill 也会读取 `backend/.env`
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
