# Product Detail Read-Only Materials Re-Review

日期：2026-06-17
Reviewer：镜花（agentKey: `jinghua`）
范围：`MSG-20260617-015` 返工复验
结论：CODE_REVIEW / PASS

## 范围

- `backend/app/api/products.py`
- `backend/app/services/material_assets.py`
- `scripts/test_project_rules.py`
- `docs/domain-index/product-flow.md`

## 验证

- `make backend-compile`：PASS。
- `make test-project-rules`：PASS，36 tests。
- `git diff --check -- backend/app/api/products.py backend/app/services/material_assets.py scripts/test_project_rules.py docs/collaboration/inbox.md`：PASS。
- 代码级确认：`get_product()` 段内 `_ensure_contact_sheet_oss_urls`、`upload_private_file`、`await db.commit()`、`await db.refresh(`、`organize_video_files`、`shutil.move`、`.mkdir(`、`.rename(`、`.unlink(` 均不存在。

## Findings

未发现 P0/P1 阻断问题。

## 已确认通过

- `GET /api/products/{product_id}` 非 compact 路径已移除 `_ensure_contact_sheet_oss_urls(product, db)`。
- GET 详情路径不再触发 contact sheet OSS 上传、DB commit/refresh、视频整理、视频移动或目录创建。
- `organize_video_files()` 仍保留为 mutating helper，但不再被 GET 详情调用；后续如需使用，应另开显式 mutating action。
- `video_folder_summary()` 继续作为只读视频摘要 helper；项目规则覆盖散落视频、嵌套视频路径不变化且不创建 `video/` 目录。
- `docs/domain-index/product-flow.md` 已保留 GET 详情只读素材扫描口径。

## 未覆盖 / 风险

- 未启动真实服务调用商品详情 API，也未访问真实素材目录；建议观止后续只读 QA 时抽样确认页面打开详情不改变素材目录。
- `backend/app/api/products.py` 仍是大文件，GET 详情只读边界当前靠局部规则护栏保护；后续商品域结构拆分时应把只读 summary 和 mutating action 分层。
