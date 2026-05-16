import os
import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from contextlib import asynccontextmanager

from app.database import init_db
from app.api.products import router as products_router
from app.api.config_api import router as config_router
from app.config import settings


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await init_db()
    yield
    # Shutdown


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


# ─── 静态文件服务：代理本地图片给前端 ───

# 允许的图片根目录（安全白名单）
_IMAGE_ROOTS = [
    str(Path(settings.PRODUCT_BASE_DIR).resolve()),
    str(Path(Path.home() / "Documents").resolve()),
    str(Path("/tmp").resolve()),
]

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tiff"}


@app.get("/api/images/{file_path:path}")
async def serve_image(file_path: str):
    """
    代理本地图片文件。
    
    前端用 /api/images/~/Documents/F/xxx.jpg 访问本地图片。
    安全限制：只能在白名单目录下。
    """
    # 支持 ~ 开头的路径
    if file_path.startswith("~/"):
        file_path = str(Path.home() / file_path[2:])
    elif file_path.startswith("~"):
        file_path = str(Path.home() / file_path[1:])
    elif file_path.startswith("Users/"):
        file_path = "/" + file_path

    abs_path = str(Path(file_path).resolve())

    # 安全检查：路径必须在白名单目录下
    allowed = any(abs_path.startswith(str(Path(r).resolve())) for r in _IMAGE_ROOTS)
    if not allowed:
        raise HTTPException(403, f"Access denied: path outside allowed roots")

    if not os.path.isfile(abs_path):
        raise HTTPException(404, f"File not found: {file_path}")

    # 检查扩展名
    ext = Path(abs_path).suffix.lower()
    if ext not in IMAGE_EXTENSIONS:
        raise HTTPException(400, f"Not an image file: {ext}")

    return FileResponse(abs_path)


@app.get("/api/health")
async def health():
    return {"status": "ok", "version": settings.VERSION}
