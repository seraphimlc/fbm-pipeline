# Product Detail Read-Only Materials PRD

日期：2026-06-17
Owner：若命（agentKey: `ruoming`）
执行角色：听云（agentKey: `tingyun`）
验证角色：镜花 / 观止

## 背景

镜花在 `MSG-20260617-JH-004` 中指出 P0：

`GET /api/products/{product_id}` 构建商品详情时调用 `organize_video_files(material_dir)`，该函数会扫描素材目录并用 `shutil.move()` 把视频移动到 `material_dir/video`。这导致用户打开详情页或前端轮询详情时，读接口静默修改本地素材文件。

这是 P0。读接口必须只读。

## 目标

- `GET /api/products/{product_id}` 不再移动、重命名、创建、删除或改写任何素材文件。
- 商品详情仍能返回素材目录摘要和视频文件信息，但只能只读扫描。
- 如果确实需要整理视频文件，后续另做显式 mutating action，不在本任务内实现。
- 补最小行为测试或项目规则测试，证明详情读取链路不会调用 `shutil.move()` / `organize_video_files()` 这类写文件整理行为。

## 非目标

- 不重构整个 `backend/app/api/products.py`。
- 不新增素材管理页面。
- 不自动整理历史素材目录。
- 不触发真实商品状态推进、导出、A+、GIGA、StyleSnap 或外部平台调用。
- 不触碰 `data/`、`backend/data/`、真实 ASIN、人工类目、Amazon 模板、`template_mappings`、已生成素材、真实导出文件。

## 当前事实

- 入口：`backend/app/api/products.py`
- 风险函数：`backend/app/services/material_assets.py`
- 前端详情：`frontend/src/pages/ProductDetail.tsx`
- 领域索引：`docs/domain-index/product-flow.md`
- 审计报告：`docs/collaboration/reviews/2026-06-17-docs-code-structure-audit.md`

## 设计要求

### 只读详情

商品详情 GET 路径只能做：

- 查询 DB。
- 读取目录结构。
- 汇总文件名、大小、类型、URL 或可展示路径。
- 返回不存在/不可访问/空目录等只读状态。

商品详情 GET 路径禁止：

- `shutil.move/copy/rmtree`
- `Path.rename/unlink/mkdir/write_text/write_bytes`
- 任何会改变素材目录结构或文件内容的操作。

### 显式整理动作

如代码中确有“整理视频到 video 子目录”的业务需要，本任务只允许：

- 从 GET 路径移除。
- 保留函数但不被 GET 调用，或改名标记为 mutating。
- 在后续 PRD 中设计 `POST` action，包含预览、确认、结果和失败恢复。

本任务不实现该 `POST` action。

## 验收标准

- `GET /api/products/{id}` 代码路径不再调用 `organize_video_files()` 或任何文件移动整理函数。
- `organize_video_files()` 如保留，不能被商品详情 GET 间接调用。
- 增加测试/规则覆盖：
  - 商品详情读取链路不得包含 `organize_video_files(`。
  - `organize_video_files()` 内部的 mutating 行为不能出现在 GET handler 路径。
  - 如能做函数级测试，构造临时素材目录，调用详情摘要读取函数后，文件路径不变化。
- `make backend-compile`
- `make test-project-rules`
- `git diff --check`
- 如改前端，再跑 `cd frontend && npm run build`

## DONE_CLAIMED 必填

- 改动文件。
- GET 详情只读链路说明。
- 是否保留 `organize_video_files()`，如果保留，谁还能调用。
- 测试/规则证据。
- 副作用说明：未移动真实素材、未触发真实商品状态、未触发外部平台。
- 索引更新情况。
