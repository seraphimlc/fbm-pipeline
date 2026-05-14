from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.config import settings

router = APIRouter(prefix="/api/config", tags=["config"])


class ConfigResponse(settings.__class__):
    """返回当前配置（隐藏敏感Key）"""

    class Config:
        json_schema_extra = {
            "example": {
                "PROJECT_NAME": "FBM Pipeline",
                "BACKEND_PORT": 8190,
                "FRONTEND_PORT": 3190,
                "DEFAULT_BRAND": "Vindhvisk",
                "LLM_MODEL": "gpt-5.5",
                "VLM_MODEL": "qwen3.6-plus",
            }
        }


@router.get("")
async def get_config():
    """获取当前配置（脱敏）"""
    return {
        "project_name": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "backend_port": settings.BACKEND_PORT,
        "frontend_port": settings.FRONTEND_PORT,
        "default_brand": settings.DEFAULT_BRAND,
        "llm_model": settings.LLM_MODEL,
        "vlm_model": settings.VLM_MODEL,
        "gpt_image_model": settings.GPT_IMAGE_MODEL,
        "product_base_dir": str(settings.PRODUCT_BASE_DIR),
        "aplus_concurrency": settings.APLUS_CONCURRENCY,
        "poll_interval": settings.POLL_INTERVAL,
        "step3_4_parallel": settings.STEP3_4_PARALLEL,
        "llm_api_configured": bool(settings.LLM_API_KEY),
        "vlm_api_configured": bool(settings.VLM_API_KEY),
        "gpt_image_api_configured": bool(settings.GPT_IMAGE_API_KEY),
        "sellersprite_configured": bool(settings.SELLERSPRITE_TOKEN),
    }


@router.get("/status")
async def system_status():
    """系统状态检查"""
    return {
        "status": "ok",
        "database": str(settings.DATABASE_URL).split("/")[-1],
        "product_dir_exists": settings.PRODUCT_BASE_DIR.exists(),
    }
