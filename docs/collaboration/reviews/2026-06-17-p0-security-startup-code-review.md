# CODE_REVIEW - P0 Security / Startup Boundary

- Reviewer: 镜花（agentKey: `jinghua`）
- Time: 2026-06-17 17:05 CST
- Message: `MSG-20260617-004`
- PRD: `docs/superpowers/specs/2026-06-17-p0-security-startup-triage-prd.md`
- Conclusion: `PASS`
- Scope: 默认 host、mutating API guard、startup 副作用开关、TLS verify 默认值、image proxy 根目录/路径校验、runtime-security 文档/索引、项目规则测试。
- Out of scope: task center `stale_running` 投影、`products.py` 结构审计、读详情移动素材 P0、完整登录权限系统、真实服务 QA、真实任务/导出/上传/外部平台调用。

## Summary

听云本轮 P0 安全/启动边界修复可以通过镜花 code review。当前实现已把默认启动收回 `127.0.0.1`，对 `/api` 下非安全方法加了本机或 dev token guard，把 startup DDL/backfill/recover/kick 改成默认关闭的显式 `STARTUP_RUN_*` 开关，移除了本轮命中的默认 `verify=False`，并把 `/api/images` 默认根目录收窄到 `PRODUCT_BASE_DIR` + 显式 `IMAGE_PROXY_EXTRA_ROOTS`，路径归属使用 `Path.relative_to()`。

本轮没有发现 P0/P1 未解决问题。保留两个非阻塞风险：独立 VLM client 仍依赖 SDK 默认 TLS 行为且未接入 `EXTERNAL_HTTP_CA_BUNDLE`；未做真实服务级 QA，需观止后续按只读/最小副作用路径复验。

## Index Review

使用索引:

- `docs/project-index.md`
- `docs/domain-index/runtime-security.md`

结论:

- `docs/domain-index/runtime-security.md` 已同步当前启动、安全配置、startup 开关、TLS 和 image proxy 口径。
- `docs/project-index.md` 已有 runtime-security 路由，本轮 P0 修复无需改总索引。
- 后续如果新增独立管理命令或改启动验证入口，需要再更新索引。

## Findings

无 P0/P1 findings。

### P2 Residual: 独立 VLM client 未统一接入 CA bundle helper

- 位置: `backend/app/config.py:153`
- 事实: `get_llm_client()` 使用 `httpx.AsyncClient(verify=self.external_http_verify)`；`get_vlm_client()` 创建 `AsyncOpenAI` 时未显式传 `http_client`。
- 影响: 默认 TLS verify 仍应由 SDK/httpx 默认开启，因此不阻塞 P0；但如果 VLM 独立通道使用私有 CA bundle，当前不能统一复用 `EXTERNAL_HTTP_CA_BUNDLE`。
- 期望: 后续顺手把 `get_vlm_client()` 也接入 `external_http_verify`，保持所有 OpenAI-compatible token client 的 TLS/CA 行为一致。
- 修复要求: 不阻塞本轮；可并入下一次配置/TLS 清理。

### P2 Residual: 缺少真实服务级 QA

- 位置: `MSG-20260617-004` 验证记录
- 事实: 听云未启动真实服务、未触发真实 mutating API；镜花本轮补了 middleware 函数级样本，但未起 uvicorn 做 HTTP 级复验。
- 影响: code review 可基于实现通过，但最终验收仍需要观止用只读/最小副作用方式验证远程 POST 403、本机健康检查、image proxy 拒绝样本等。
- 期望: 观止后续 QA 不触发真实 GIGA/导出/A+/商品状态推进，只验证边界。
- 修复要求: 不阻塞镜花 PASS；交观止 QA。

## Verified

- 默认启动: `scripts/start.sh:24-27` 从 `.env` 读取 host，默认 `127.0.0.1`；README 示例也改成 `127.0.0.1`。
- Mutating guard: `backend/app/main.py:41-58` 定义安全方法、本机 host 和 dev token；`backend/app/main.py:137-145` 保护 `/api` 下非 `GET/HEAD/OPTIONS`。
- Startup: `backend/app/main.py:81-102` 仅在 `STARTUP_RUN_DB_MAINTENANCE/BACKFILLS/RECOVER_TASKS/KICK_TASK_RUNTIME` 为真时执行维护动作。
- TLS: `backend/app/config.py:179-186` 默认返回 `True` 或 CA bundle；`aplus_upload.py` 和 `step9_aplus_image.py` 使用 `settings.external_http_verify`；scoped `rg` 未发现本轮相关文件残留 `verify=False`。
- Image proxy: `backend/app/config.py:188-196` 默认只包含 `PRODUCT_BASE_DIR` 和显式额外根；`backend/app/main.py:61-69` 用 `relative_to()` 判断路径；`backend/app/main.py:173-178` 拒绝越界且不回显本机完整路径。
- Mutating route coverage: scoped `rg` 显示 mutating routers 均挂在 `/api/...` prefix 下；未发现 `@app.post/put/patch/delete` 绕过 router guard。

## Verification

- `make test-project-rules`: PASS，33 项。
- `make backend-compile`: PASS。
- `git diff --check -- scripts/start.sh README.md backend/.env.example backend/app/config.py backend/app/main.py backend/app/services/aplus_upload.py backend/app/pipeline/step9_aplus_image.py docs/domain-index/runtime-security.md scripts/test_project_rules.py docs/collaboration/inbox.md`: PASS。
- 额外函数级样本: 从 `backend/` 运行 Python 片段，确认 remote POST `/api/config` 无 token 返回 403、本机 POST 放行、remote GET 放行，`_has_valid_dev_token()` 支持 header token。

## Next Action

- `MSG-20260617-004` 可交观止做只读/最小副作用 QA。
- 不要把 task center projection 或结构审计问题混入本 P0 修复；它们走后续消息。
