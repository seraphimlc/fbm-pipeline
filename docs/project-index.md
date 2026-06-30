# Project Index

状态：当前项目导航索引
更新：2026-06-21

本文只做“找路”，不替代代码事实。每次任务先用本文定位领域，再读取对应 `docs/domain-index/*.md`，最后用 `git status --short`、`rg` 和关键文件片段核实当前实现。

## 读取规则

1. 先读当前用户问题、`AGENTS.md` 和本索引。
2. 根据“问题类型”进入一个或少数几个 domain index。
3. 在 domain index 指定范围内用 `rg` 验证当前事实，不做全仓库盲搜。
4. 只读取关键文件片段；发现索引过期时，任务结束同步更新索引。

## 问题路由

| 问题类型 | 先读领域索引 | 关键入口 |
|---|---|---|
| 任务中心、新任务框架、任务状态、重试/取消/恢复、异步任务 | `docs/domain-index/task-runtime.md` | `frontend/src/pages/TaskRunCenter.tsx`, `backend/app/api/task_runs.py`, `backend/app/task_runtime/` |
| 老离线任务、历史任务页面、尚未迁移任务 | `docs/domain-index/task-runtime.md` | `frontend/src/pages/OfflineTaskCenter.tsx`, `backend/app/api/offline_tasks.py`, `backend/app/services/offline_tasks.py` |
| 商品列表、商品详情、图片选择、竞品选择、商品状态流转 | `docs/domain-index/product-flow.md` | `docs/superpowers/specs/2026-06-18-amazon-product-workflow-prd.md`, `docs/superpowers/specs/2026-06-19-amazon-auto-image-competitor-selection-prd.md`, `docs/superpowers/specs/2026-06-19-amazon-auto-image-selection-prd.md`, `docs/superpowers/specs/2026-06-19-amazon-auto-competitor-selection-prd.md`, `docs/superpowers/specs/2026-06-21-amazon-auto-flow-to-export-ready-prd.md`, `docs/superpowers/specs/2026-06-21-amazon-aplus-auto-after-export-ready-prd.md`, `frontend/src/pages/ProductList.tsx`, `frontend/src/pages/ProductDetail.tsx`, `backend/app/api/products.py` |
| TikTok 商品详情/铺货链路 | `docs/domain-index/product-flow.md`, `docs/domain-index/data-sources.md` | `docs/superpowers/specs/2026-06-21-tiktok-listing-flow-redesign-prd.md`, `frontend/src/pages/TikTokProductDetail.tsx`, `backend/app/api/tiktok.py` |
| GIGA 拉品、商品池、库存/价格同步、数据源配置 | `docs/domain-index/data-sources.md` | `backend/app/api/giga.py`, `backend/app/services/giga_openapi.py`, `backend/app/task_planners/giga_pull.py` |
| Amazon 导出、导出中心、导入模板、类目映射、Step 10 | `docs/domain-index/export-flow.md` | `frontend/src/pages/CatalogList.tsx`, `backend/app/task_planners/catalog_export.py`, `backend/app/pipeline/amazon_export/`, `backend/app/pipeline/step10_amazon_template.py` |
| A+ 生成、A+ 管理、领星 ERP A+ 上传/发布 | `docs/domain-index/product-flow.md`, `docs/domain-index/task-runtime.md`, `docs/domain-index/runtime-security.md` | `docs/superpowers/specs/2026-06-23-lingxing-aplus-publish-after-aplus-done-prd.md`, `docs/superpowers/specs/2026-06-23-lingxing-aplus-publish-technical-plan.md`, `docs/superpowers/specs/2026-06-23-lingxing-aplus-module-mapping-prd.md`, `docs/superpowers/specs/2026-06-24-lingxing-aplus-enhanced-basic-prd.md`, `docs/lingxing-aplus-upload.md`, `frontend/src/pages/AplusManagement.tsx`, `backend/app/task_planners/aplus_generate.py`, `backend/app/task_planners/lingxing_listing_sync.py`, `backend/app/task_planners/lingxing_aplus_publish.py`, `backend/app/task_runtime/lingxing_listing_sync_workers.py`, `backend/app/task_runtime/lingxing_aplus_publish_workers.py`, `backend/app/services/asin_match_policy.py`, `backend/app/services/lingxing_listing_client.py`, `backend/app/aplus_publish/module_registry.py`, `backend/app/services/lingxing_aplus_module_mapper.py`, `backend/app/services/lingxing_aplus_publish_policy.py`, `backend/app/services/lingxing_aplus_publish_client.py`, `backend/app/aplus_publish/status.py`, `backend/app/services/aplus_publish_state.py`, `backend/app/services/aplus_upload.py`, `backend/app/services/aplus_auto_trigger.py` |
| 页面路由、导航、前端接口消费、交互入口 | `docs/domain-index/frontend-pages.md` | `frontend/src/App.tsx`, `frontend/src/api/index.ts`, `frontend/src/components/MainLayout.tsx` |
| 启动边界、本地访问保护、TLS、文件/图片代理 | `docs/domain-index/runtime-security.md` | `scripts/start.sh`, `backend/app/main.py`, `backend/app/config.py`, `backend/app/database.py` |
| 数据库表结构、字段用途、历史字段审查 | `docs/database-schema-review.md` | `backend/app/models/models.py`, `backend/app/database.py`, `docs/domain-index/product-flow.md`, `docs/domain-index/task-runtime.md`, `docs/domain-index/data-sources.md` |
| 协作规则、角色、消息、review/QA 文档、multi-agent-collaboration skill | `docs/domain-index/collaboration.md` | `docs/collaboration.md`, `docs/collaboration/inbox.md`, `/Users/liuchang/.codex/skills/multi-agent-collaboration/` |
| 文档整理、文档重写、索引维护 | `docs/README.md`, `docs/collaboration/playbooks/context-indexing.md` | `docs/documentation-rewrite-brief.md`, `docs/project-index.md`, `docs/domain-index/` |
| 模板类目映射 | `docs/domain-index/export-flow.md` | `backend/app/pipeline/template_mappings/`, `docs/template-mapping-spec.md`, `docs/template-mapping-change-log.md` |

## 关键运行入口

- 后端应用入口：`backend/app/main.py`
- 后端模型：`backend/app/models/models.py`
- 后端配置：`backend/app/config.py`, `backend/.env.example`
- 前端应用入口：`frontend/src/App.tsx`
- 前端 API client：`frontend/src/api/index.ts`
- 项目规则：`AGENTS.md`
- 协作入口：`docs/collaboration.md`

## 常用验证入口

- 后端健康检查：`GET /api/health`
- 任务中心列表：`GET /api/task-runs`
- 领星 A+ 草稿保存任务：`POST /api/task-runs/lingxing-aplus-publish`
- 领星 A+ profile/module/slot 验证：`cd backend && .venv/bin/python ../scripts/test_lingxing_aplus_module_mapper.py`、`cd backend && .venv/bin/python ../scripts/test_lingxing_aplus_publish_policy.py`、`cd backend && .venv/bin/python ../scripts/test_lingxing_aplus_publish_tasks.py`、`cd backend && .venv/bin/python ../scripts/check_lingxing_enhanced_aplus_qa_readiness.py`、`cd backend && .venv/bin/python ../scripts/prepare_lingxing_enhanced_aplus_qa_sample.py`、`make test-project-rules`
- 商品列表：`GET /api/products`
- 商品总览：`GET /api/products/overview?data_source_id=<id>`
- 图片分析到 Listing 待导出行为脚本：`cd backend && .venv/bin/python ../scripts/test_image_analysis_listing_e5.py`
- GIGA 商品池：`GET /api/giga/items`
- 库存页面接口：`GET /api/giga/inventory`
- 前端页面：`http://localhost:3190/products`, `http://localhost:3190/task-runs`, `http://localhost:3190/export-center`

## 硬边界

- 不要用本索引替代当前代码事实；索引只导航。
- 不要把长日志、完整聊天、完整数据样本、完整代码复制进索引。
- 不要为了省事全量读取所有 domain index。
- 涉及真实数据、生成产物、外部平台、导出文件或状态推进时，先确认授权。

## 维护规则

- 新增、删除或迁移页面/API/核心 service/action/table/任务类型/导出链路/状态语义/验证入口时，更新对应 domain index。
- 发现索引指向过期文件、遗漏关键入口或误导定位时，把索引修复纳入本轮交付。
- 局部 bug fix、函数内部重构、样式/文案微调、测试补充，且不改变入口/语义/状态/表/验证方式时，不需要更新索引。
- 大型 review / QA 如果发现索引缺失，应作为文档问题记录。
