# Product Detail Read-Only Materials Code Review

日期：2026-06-17
Reviewer：镜花（agentKey: `jinghua`）
范围：`MSG-20260617-007` / `docs/superpowers/specs/2026-06-17-product-detail-readonly-materials-prd.md`
结论：CODE_REVIEW / NEEDS_FIX

## 范围

- 审查文件：
  - `backend/app/api/products.py`
  - `backend/app/services/material_assets.py`
  - `scripts/test_project_rules.py`
  - `docs/domain-index/product-flow.md`
- 未做：
  - 未触发真实商品详情 API。
  - 未触碰真实素材、真实 ASIN、导出文件、GIGA、A+、StyleSnap 或外部平台。

## 验证

- `make backend-compile`：PASS。
- `make test-project-rules`：PASS，36 tests。
- `git diff --check -- backend/app/api/products.py backend/app/services/material_assets.py scripts/test_project_rules.py docs/domain-index/product-flow.md docs/collaboration/inbox.md`：PASS。
- Scoped code read:
  - `GET /api/products/{product_id}` 已从 `organize_video_files(material_dir)` 改为 `video_folder_summary(material_dir)`。
  - `video_folder_summary()` 只读扫描并返回相对路径，不创建 `video/`，不 `shutil.move()`。

## Findings

### P0：商品详情 GET 仍可能上传本地文件到 OSS 并写库

- 位置：
  - `backend/app/api/products.py:1072`
  - `backend/app/api/products.py:1120`
  - `backend/app/api/products.py:1129`
  - `backend/app/api/products.py:4958`
- 事实：
  - `get_product()` 非 compact 路径仍调用 `await _ensure_contact_sheet_oss_urls(product, db)`。
  - `_ensure_contact_sheet_oss_urls()` 遇到 `image_analysis.contact_sheets[].sheet_path` 为本地文件且无 `oss_object_key` 时，会调用 `upload_private_file(path, object_key)`。
  - 上传后会修改 `images.image_analysis/contact_sheet_path/analyzed_at`、`product.updated_at`，并 `await db.commit()` / `await db.refresh(product)`。
- 影响：
  - `GET /api/products/{id}` 仍不是只读接口；打开商品详情可能触发外部 OSS 上传和 DB 写入。
  - 这违反本 PRD “商品详情 GET 路径只能查询 DB、读取目录结构、汇总文件信息、返回只读状态”的设计要求，也与 `DONE_CLAIMED` 的“未触发外部平台”边界不一致。
  - 当前新增测试只覆盖视频整理路径，没有覆盖 GET 中其它 ensure/upload/commit 副作用。
- 修复要求：
  - 从 `GET /api/products/{id}` 路径移除 `_ensure_contact_sheet_oss_urls()` 或改为纯只读签名/摘要逻辑。
  - 如确需上传 contact sheet，应另建显式 mutating action，例如 `POST`，并有预览、确认、错误恢复和测试。
  - 补项目规则或最小行为测试，确保 `get_product()` 段不调用 `upload_private_file`、不 `db.commit()`，并不调用会触发外部平台或写库的 ensure helper。

## 已确认通过

- 视频素材 P0 主路径已收敛：`get_product()` 不再 import/call `organize_video_files()`，也不再通过该函数移动素材视频。
- `video_folder_summary()` 是只读 helper，当前测试覆盖散落视频和嵌套视频路径不变化、未创建 `video/` 目录。
- `docs/domain-index/product-flow.md` 已补充商品详情 GET 只能只读扫描素材目录的口径。

## 未覆盖 / 风险

- 现有测试仍偏字符串护栏；本轮发现的 `_ensure_contact_sheet_oss_urls()` 副作用正是测试没覆盖的 GET 读路径外部/DB 写风险。
- 本 review 未做真实服务现场验证；修复后仍建议观止做只读 QA。
