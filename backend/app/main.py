import os
import hmac
import ipaddress
import logging
import asyncio
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.responses import FileResponse
from contextlib import asynccontextmanager

from app.database import async_session, init_db
from app.api.products import router as products_router
from app.api.config_api import router as config_router
from app.api.data_sources import router as data_sources_router
from app.api.giga import router as giga_router
from app.api.tiktok import router as tiktok_router
from app.api.task_runs import router as task_runs_router
from app.api.offline_tasks import router as offline_tasks_router
from app.config import settings
from app.pipeline.engine import cancel_all_pipelines, recover_interrupted_pipelines
from app.services.aplus_regenerate import cancel_active_regenerate_tasks, recover_regenerate_tasks
from app.services.giga_image_download_tasks import cancel_active_giga_image_downloads
from app.services.giga_sync_tasks import cancel_active_giga_sync_tasks
from app.services.offline_tasks import cancel_active_offline_tasks, recover_offline_tasks
from app.task_runtime import (
    kick_task_runtime,
    recover_cancel_requested_task_runtime,
    recover_task_runtime,
    shutdown_task_runtime,
)
from app.task_runtime.auto_wake_monitor import auto_wake_monitor_loop
from app.task_runtime.aplus_generate_workers import register_aplus_generate_workers
from app.task_runtime.catalog_export_workers import register_catalog_export_workers
from app.task_runtime.giga_dynamic_sync_workers import register_giga_dynamic_sync_workers
from app.task_runtime.giga_pull_workers import register_giga_pull_workers
from app.task_runtime.lingxing_aplus_publish_workers import register_lingxing_aplus_publish_workers
from app.task_runtime.lingxing_listing_sync_workers import register_lingxing_listing_sync_workers
from app.task_runtime.product_bulk_advance_workers import register_product_bulk_advance_workers
from app.task_runtime.registry import assert_workers_registered
from app.product_tasks.actions import PRODUCT_ACTION_TYPES, backfill_product_action_task_run_keys, register_product_task_actions


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

SAFE_HTTP_METHODS = {"GET", "HEAD", "OPTIONS"}
REMOTE_PROXY_HEADER = "X-FBM-Proxy-Client"
REMOTE_PROXY_VALUE = "remote"
REMOTE_READ_ONLY_RESPONSE = {
    "code": "REMOTE_DEV_READ_ONLY",
    "detail": "当前是远程只读访问",
}


def _normalize_client_host(value: str | None) -> str:
    host = str(value or "").strip().lower()
    if host.startswith("["):
        closing_bracket = host.find("]")
        if closing_bracket > 0:
            host = host[1:closing_bracket]
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return host
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        return str(address.ipv4_mapped)
    return str(address)


def _is_local_client(client) -> bool:
    host = _normalize_client_host(getattr(client, "host", None) if client else None)
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _has_valid_dev_token(request: Request, configured_token: str | None) -> bool:
    token = (configured_token or "").strip()
    if not token:
        return False
    header_token = request.headers.get("X-FBM-Dev-Token", "").strip()
    if header_token:
        return hmac.compare_digest(header_token.encode("utf-8"), token.encode("utf-8"))
    authorization = request.headers.get("Authorization", "").strip()
    prefix = "Bearer "
    bearer_token = authorization[len(prefix):].strip() if authorization.startswith(prefix) else ""
    return bool(bearer_token) and hmac.compare_digest(
        bearer_token.encode("utf-8"),
        token.encode("utf-8"),
    )


def _path_is_within_roots(path: Path, roots: list[Path]) -> bool:
    resolved = path.resolve()
    for root in roots:
        try:
            resolved.relative_to(root.resolve())
            return True
        except ValueError:
            continue
    return False


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    register_giga_pull_workers()
    register_giga_dynamic_sync_workers()
    register_product_task_actions()
    register_product_bulk_advance_workers()
    register_catalog_export_workers()
    register_aplus_generate_workers()
    register_lingxing_listing_sync_workers()
    register_lingxing_aplus_publish_workers()
    # Product actions are persisted as ready steps. Refuse to serve if even one
    # can be created but has no in-process worker to execute it.
    assert_workers_registered(PRODUCT_ACTION_TYPES, scope="商品任务运行时")
    # A brand-new SQLite file has no task tables yet.  Initialize it before
    # startup recovery queries, while preserving MySQL's explicit-maintenance
    # behavior for existing shared databases.
    if settings.is_sqlite:
        await init_db()
        logging.info("Initialized local SQLite database: %s", settings.SQLITE_DATABASE_PATH)
    canceled_recovered = await recover_cancel_requested_task_runtime()
    if canceled_recovered:
        logging.info("Recovered %s cancellation-requested task runtime steps on startup.", canceled_recovered)
    if settings.STARTUP_RUN_DB_MAINTENANCE:
        await init_db()
    else:
        logging.info("Startup DB maintenance disabled; skipping init_db/create_all/ensure-indexes.")
    if settings.STARTUP_RUN_BACKFILLS:
        async with async_session() as db:
            changed = await backfill_product_action_task_run_keys(db)
            if changed:
                logging.info("Backfilled ProductTaskAction task_run metadata: changed=%s", changed)
    else:
        logging.info("Startup backfills disabled.")
    if settings.STARTUP_RECOVER_TASKS:
        await recover_task_runtime()
        await recover_offline_tasks()
        await recover_interrupted_pipelines()
        await recover_regenerate_tasks()
    else:
        logging.info("Startup task recovery disabled.")
    if settings.STARTUP_KICK_TASK_RUNTIME:
        kick_task_runtime()
    else:
        logging.info("Startup task runtime kick disabled.")
    auto_wake_task: asyncio.Task | None = None
    if settings.TASK_RUNTIME_AUTO_WAKE_ENABLED:
        auto_wake_task = asyncio.create_task(auto_wake_monitor_loop(), name="task-runtime-auto-wake")
    else:
        logging.info("Task runtime auto-wake monitor disabled.")
    yield
    # Shutdown
    if auto_wake_task:
        auto_wake_task.cancel()
        try:
            await auto_wake_task
        except asyncio.CancelledError:
            pass
    await shutdown_task_runtime()
    await cancel_active_offline_tasks()
    await cancel_active_giga_sync_tasks()
    await cancel_active_giga_image_downloads()
    await cancel_all_pipelines()
    await cancel_active_regenerate_tasks()


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    lifespan=lifespan,
)

# CORS — 允许前端跨域
app.add_middleware(
    CORSMiddleware,
    allow_origins=[f"http://localhost:{settings.FRONTEND_PORT}", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(products_router)
app.include_router(config_router)
app.include_router(data_sources_router)
app.include_router(giga_router)
app.include_router(tiktok_router)
app.include_router(task_runs_router)
app.include_router(offline_tasks_router)


@app.middleware("http")
async def mutating_api_guard(request: Request, call_next):
    if request.url.path.startswith("/api") and request.method.upper() not in SAFE_HTTP_METHODS:
        marked_remote = request.headers.get(REMOTE_PROXY_HEADER, "").strip().lower() == REMOTE_PROXY_VALUE
        if (
            (not _is_local_client(request.client) or marked_remote)
            and not _has_valid_dev_token(request, settings.API_DEV_TOKEN)
        ):
            return JSONResponse(
                status_code=403,
                content=REMOTE_READ_ONLY_RESPONSE,
            )
    return await call_next(request)


# ─── 静态文件服务：代理本地图片给前端 ───

# 允许的图片根目录（安全白名单）
_IMAGE_ROOTS = settings.image_proxy_roots

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tiff"}


@app.get("/api/images/{file_path:path}")
async def serve_image(file_path: str):
    """
    代理本地图片文件。

    安全限制：只能在配置允许的业务图片目录下。
    """
    # 支持 ~ 开头的路径
    if file_path.startswith("~/"):
        file_path = str(Path.home() / file_path[2:])
    elif file_path.startswith("~"):
        file_path = str(Path.home() / file_path[1:])
    elif file_path.startswith("Users/"):
        file_path = "/" + file_path

    abs_path = Path(file_path).resolve()

    # 安全检查：路径必须在白名单目录下
    if not _path_is_within_roots(abs_path, _IMAGE_ROOTS):
        raise HTTPException(403, "Access denied")

    if not os.path.isfile(abs_path):
        raise HTTPException(404, "File not found")

    # 检查扩展名
    ext = Path(abs_path).suffix.lower()
    if ext not in IMAGE_EXTENSIONS:
        raise HTTPException(400, f"Not an image file: {ext}")

    return FileResponse(abs_path)


@app.get("/api/health")
async def health():
    return {"status": "ok", "version": settings.VERSION}
