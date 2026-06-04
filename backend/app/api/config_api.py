from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.config import settings

router = APIRouter(prefix="/api/config", tags=["config"])

BACKEND_DIR = Path(__file__).resolve().parents[2]
ENV_FILE = BACKEND_DIR / ".env"


class ConfigUpdateRequest(BaseModel):
    default_brand: str | None = Field(default=None, min_length=1, max_length=100)
    product_base_dir: str | None = Field(default=None, min_length=1, max_length=2000)
    pipeline_max_concurrency: int | None = Field(default=None, ge=1, le=20)
    browser_workflow_concurrency: int | None = Field(default=None, ge=1, le=5)
    bulk_start_max_tasks: int | None = Field(default=None, ge=1, le=1000)
    aplus_concurrency: int | None = Field(default=None, ge=1, le=10)
    poll_interval: int | None = Field(default=None, ge=1, le=60)
    step3_4_parallel: bool | None = None
    step1_extract_retry_attempts: int | None = Field(default=None, ge=1, le=20)
    step1_extract_retry_delay_seconds: int | None = Field(default=None, ge=0, le=60)
    step1_download_timeout_seconds: int | None = Field(default=None, ge=30, le=1800)
    step1_material_package_priority: str | None = Field(default=None, min_length=1, max_length=200)
    step1_price_missing_policy: str | None = Field(default=None, pattern="^(fail|manual_review|continue)$")
    step1_material_missing_policy: str | None = Field(default=None, pattern="^(fail|manual_review|continue)$")
    step1_allow_existing_materials: bool | None = None
    pricing_net_revenue_rate: float | None = Field(default=None, gt=0, lt=1)
    pricing_target_margin_rate: float | None = Field(default=None, ge=0, lt=1)
    pricing_min_profit: float | None = Field(default=None, ge=0, le=1000)
    pricing_fixed_cost: float | None = Field(default=None, ge=0, le=1000)
    pricing_return_credit_rate: float | None = Field(default=None, ge=0, lt=1)
    step3_manual_login_on_auth_failure: bool | None = None
    step4_missing_asin_policy: str | None = Field(default=None, pattern="^(fail|manual_review|continue)$")
    step4_category_missing_policy: str | None = Field(default=None, pattern="^(fail|manual_review|continue)$")
    step4_allow_existing_category: bool | None = None
    step5_llm_temperature: float | None = Field(default=None, ge=0, le=2)
    step5_llm_max_tokens: int | None = Field(default=None, ge=500, le=8000)
    step5_title_max_chars: int | None = Field(default=None, ge=80, le=250)
    step5_bullet_max_chars: int | None = Field(default=None, ge=100, le=1000)
    step5_search_terms_max_bytes: int | None = Field(default=None, ge=50, le=500)
    llm_model: str | None = Field(default=None, min_length=1, max_length=100)
    vlm_model: str | None = Field(default=None, min_length=1, max_length=100)
    vlm_use_llm_api: bool | None = None
    gpt_image_model: str | None = Field(default=None, min_length=1, max_length=100)
    gpt_image_use_llm_api: bool | None = None
    aplus_image_width: int | None = Field(default=None, ge=320, le=4096)
    aplus_image_height: int | None = Field(default=None, ge=320, le=4096)
    aplus_image_jpeg_quality: int | None = Field(default=None, ge=40, le=100)
    aplus_image_api_retries: int | None = Field(default=None, ge=0, le=10)
    aplus_image_overwrite_policy: str | None = Field(default=None, pattern="^(skip_success|overwrite_all)$")
    giga_sync_page_size: int | None = Field(default=None, ge=1, le=200)

    @model_validator(mode="after")
    def validate_pricing_rates(self):
        net_rate = self.pricing_net_revenue_rate
        margin_rate = self.pricing_target_margin_rate
        if net_rate is None:
            net_rate = settings.PRICING_NET_REVENUE_RATE
        if margin_rate is None:
            margin_rate = settings.PRICING_TARGET_MARGIN_RATE
        if net_rate <= margin_rate:
            raise ValueError("净收入比例必须大于目标净利率")
        return self


UPDATE_FIELD_MAP = {
    "default_brand": "DEFAULT_BRAND",
    "product_base_dir": "PRODUCT_BASE_DIR",
    "pipeline_max_concurrency": "PIPELINE_MAX_CONCURRENCY",
    "browser_workflow_concurrency": "BROWSER_WORKFLOW_CONCURRENCY",
    "bulk_start_max_tasks": "BULK_START_MAX_TASKS",
    "aplus_concurrency": "APLUS_CONCURRENCY",
    "poll_interval": "POLL_INTERVAL",
    "step3_4_parallel": "STEP3_4_PARALLEL",
    "step1_extract_retry_attempts": "STEP1_EXTRACT_RETRY_ATTEMPTS",
    "step1_extract_retry_delay_seconds": "STEP1_EXTRACT_RETRY_DELAY_SECONDS",
    "step1_download_timeout_seconds": "STEP1_DOWNLOAD_TIMEOUT_SECONDS",
    "step1_material_package_priority": "STEP1_MATERIAL_PACKAGE_PRIORITY",
    "step1_price_missing_policy": "STEP1_PRICE_MISSING_POLICY",
    "step1_material_missing_policy": "STEP1_MATERIAL_MISSING_POLICY",
    "step1_allow_existing_materials": "STEP1_ALLOW_EXISTING_MATERIALS",
    "pricing_net_revenue_rate": "PRICING_NET_REVENUE_RATE",
    "pricing_target_margin_rate": "PRICING_TARGET_MARGIN_RATE",
    "pricing_min_profit": "PRICING_MIN_PROFIT",
    "pricing_fixed_cost": "PRICING_FIXED_COST",
    "pricing_return_credit_rate": "PRICING_RETURN_CREDIT_RATE",
    "step3_manual_login_on_auth_failure": "STEP3_MANUAL_LOGIN_ON_AUTH_FAILURE",
    "step4_missing_asin_policy": "STEP4_MISSING_ASIN_POLICY",
    "step4_category_missing_policy": "STEP4_CATEGORY_MISSING_POLICY",
    "step4_allow_existing_category": "STEP4_ALLOW_EXISTING_CATEGORY",
    "step5_llm_temperature": "STEP5_LLM_TEMPERATURE",
    "step5_llm_max_tokens": "STEP5_LLM_MAX_TOKENS",
    "step5_title_max_chars": "STEP5_TITLE_MAX_CHARS",
    "step5_bullet_max_chars": "STEP5_BULLET_MAX_CHARS",
    "step5_search_terms_max_bytes": "STEP5_SEARCH_TERMS_MAX_BYTES",
    "llm_model": "LLM_MODEL",
    "vlm_model": "VLM_MODEL",
    "vlm_use_llm_api": "VLM_USE_LLM_API",
    "gpt_image_model": "GPT_IMAGE_MODEL",
    "gpt_image_use_llm_api": "GPT_IMAGE_USE_LLM_API",
    "aplus_image_width": "APLUS_IMAGE_WIDTH",
    "aplus_image_height": "APLUS_IMAGE_HEIGHT",
    "aplus_image_jpeg_quality": "APLUS_IMAGE_JPEG_QUALITY",
    "aplus_image_api_retries": "APLUS_IMAGE_API_RETRIES",
    "aplus_image_overwrite_policy": "APLUS_IMAGE_OVERWRITE_POLICY",
    "giga_sync_page_size": "GIGA_SYNC_PAGE_SIZE",
}


def _format_env_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    text = str(value).strip()
    if "\n" in text:
        raise HTTPException(400, "配置值不能包含换行")
    if text == "":
        raise HTTPException(400, "配置值不能为空")
    if any(ch.isspace() for ch in text) or "#" in text:
        escaped = text.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return text


def _write_env_updates(updates: dict[str, Any]) -> None:
    env_updates = {
        UPDATE_FIELD_MAP[field]: _format_env_value(value)
        for field, value in updates.items()
        if field in UPDATE_FIELD_MAP
    }
    if not env_updates:
        return

    lines = ENV_FILE.read_text(encoding="utf-8").splitlines() if ENV_FILE.exists() else []
    seen: set[str] = set()
    next_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            next_lines.append(line)
            continue
        key = line.split("=", 1)[0].strip()
        if key in env_updates:
            next_lines.append(f"{key}={env_updates[key]}")
            seen.add(key)
        else:
            next_lines.append(line)

    missing = [key for key in env_updates if key not in seen]
    if missing:
        if next_lines and next_lines[-1].strip():
            next_lines.append("")
        next_lines.append("# Runtime configuration")
        for key in missing:
            next_lines.append(f"{key}={env_updates[key]}")

    ENV_FILE.write_text("\n".join(next_lines) + "\n", encoding="utf-8")


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
                "VLM_MODEL": "gpt-5.5",
                "VLM_USE_LLM_API": True,
                "GPT_IMAGE_MODEL": "gpt-image-2",
                "GPT_IMAGE_USE_LLM_API": False,
                "APLUS_IMAGE_API_MODE": "edits",
                "APLUS_IMAGE_GENERATION_QUALITY": "high",
                "APLUS_IMAGE_WIDTH": 1940,
                "APLUS_IMAGE_HEIGHT": 1200,
                "APLUS_IMAGE_ASPECT_RATIO": "97:60",
                "APLUS_IMAGE_MAX_BYTES": 2000000,
                "APLUS_IMAGE_JPEG_QUALITY": 88,
                "APLUS_IMAGE_MIN_JPEG_QUALITY": 55,
                "APLUS_IMAGE_API_RETRIES": 3,
                "APLUS_IMAGE_OVERWRITE_POLICY": "skip_success",
                "PIPELINE_MAX_CONCURRENCY": 2,
                "BROWSER_WORKFLOW_CONCURRENCY": 1,
                "BULK_START_MAX_TASKS": 100,
                "STEP1_EXTRACT_RETRY_ATTEMPTS": 5,
                "STEP1_EXTRACT_RETRY_DELAY_SECONDS": 3,
                "STEP1_DOWNLOAD_TIMEOUT_SECONDS": 300,
                "STEP1_MATERIAL_PACKAGE_PRIORITY": "To B素材包,Retail Ready素材包,Information",
                "STEP1_PRICE_MISSING_POLICY": "manual_review",
                "STEP1_MATERIAL_MISSING_POLICY": "manual_review",
                "STEP1_ALLOW_EXISTING_MATERIALS": True,
                "PRICING_NET_REVENUE_RATE": 0.685,
                "PRICING_TARGET_MARGIN_RATE": 0.05,
                "PRICING_MIN_PROFIT": 10.0,
                "PRICING_FIXED_COST": 9.0,
                "PRICING_RETURN_CREDIT_RATE": 0.06,
                "STEP3_MANUAL_LOGIN_ON_AUTH_FAILURE": True,
                "STEP4_MISSING_ASIN_POLICY": "manual_review",
                "STEP4_CATEGORY_MISSING_POLICY": "manual_review",
                "STEP4_ALLOW_EXISTING_CATEGORY": True,
                "STEP5_LLM_TEMPERATURE": 0.7,
                "STEP5_LLM_MAX_TOKENS": 2000,
                "STEP5_TITLE_MAX_CHARS": 200,
                "STEP5_BULLET_MAX_CHARS": 500,
                "STEP5_SEARCH_TERMS_MAX_BYTES": 250,
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
        "vlm_use_llm_api": settings.VLM_USE_LLM_API,
        "gpt_image_model": settings.GPT_IMAGE_MODEL,
        "gpt_image_use_llm_api": settings.GPT_IMAGE_USE_LLM_API,
        "gpt_image_api_provider": settings.gpt_image_api_provider,
        "aplus_image_api_mode": settings.APLUS_IMAGE_API_MODE,
        "aplus_image_generation_quality": settings.APLUS_IMAGE_GENERATION_QUALITY,
        "aplus_image_width": settings.APLUS_IMAGE_WIDTH,
        "aplus_image_height": settings.APLUS_IMAGE_HEIGHT,
        "aplus_image_aspect_ratio": settings.APLUS_IMAGE_ASPECT_RATIO,
        "aplus_image_max_bytes": settings.APLUS_IMAGE_MAX_BYTES,
        "aplus_image_jpeg_quality": settings.APLUS_IMAGE_JPEG_QUALITY,
        "aplus_image_min_jpeg_quality": settings.APLUS_IMAGE_MIN_JPEG_QUALITY,
        "aplus_image_api_retries": settings.APLUS_IMAGE_API_RETRIES,
        "aplus_image_overwrite_policy": settings.APLUS_IMAGE_OVERWRITE_POLICY,
        "product_base_dir": str(settings.PRODUCT_BASE_DIR),
        "pipeline_max_concurrency": settings.PIPELINE_MAX_CONCURRENCY,
        "browser_workflow_concurrency": settings.BROWSER_WORKFLOW_CONCURRENCY,
        "bulk_start_max_tasks": settings.BULK_START_MAX_TASKS,
        "aplus_concurrency": settings.APLUS_CONCURRENCY,
        "poll_interval": settings.POLL_INTERVAL,
        "step3_4_parallel": settings.STEP3_4_PARALLEL,
        "step1_extract_retry_attempts": settings.STEP1_EXTRACT_RETRY_ATTEMPTS,
        "step1_extract_retry_delay_seconds": settings.STEP1_EXTRACT_RETRY_DELAY_SECONDS,
        "step1_download_timeout_seconds": settings.STEP1_DOWNLOAD_TIMEOUT_SECONDS,
        "step1_material_package_priority": settings.STEP1_MATERIAL_PACKAGE_PRIORITY,
        "step1_price_missing_policy": settings.STEP1_PRICE_MISSING_POLICY,
        "step1_material_missing_policy": settings.STEP1_MATERIAL_MISSING_POLICY,
        "step1_allow_existing_materials": settings.STEP1_ALLOW_EXISTING_MATERIALS,
        "pricing_net_revenue_rate": settings.PRICING_NET_REVENUE_RATE,
        "pricing_target_margin_rate": settings.PRICING_TARGET_MARGIN_RATE,
        "pricing_min_profit": settings.PRICING_MIN_PROFIT,
        "pricing_fixed_cost": settings.PRICING_FIXED_COST,
        "pricing_return_credit_rate": settings.PRICING_RETURN_CREDIT_RATE,
        "step3_manual_login_on_auth_failure": settings.STEP3_MANUAL_LOGIN_ON_AUTH_FAILURE,
        "step4_missing_asin_policy": settings.STEP4_MISSING_ASIN_POLICY,
        "step4_category_missing_policy": settings.STEP4_CATEGORY_MISSING_POLICY,
        "step4_allow_existing_category": settings.STEP4_ALLOW_EXISTING_CATEGORY,
        "step5_llm_temperature": settings.STEP5_LLM_TEMPERATURE,
        "step5_llm_max_tokens": settings.STEP5_LLM_MAX_TOKENS,
        "step5_title_max_chars": settings.STEP5_TITLE_MAX_CHARS,
        "step5_bullet_max_chars": settings.STEP5_BULLET_MAX_CHARS,
        "step5_search_terms_max_bytes": settings.STEP5_SEARCH_TERMS_MAX_BYTES,
        "llm_api_configured": bool(settings.LLM_API_KEY),
        "vlm_api_configured": bool(settings.LLM_API_KEY if settings.VLM_USE_LLM_API else settings.VLM_API_KEY),
        "gpt_image_api_configured": bool(settings.resolved_gpt_image_api_key),
        "sellersprite_configured": bool(settings.SELLERSPRITE_TOKEN),
        "giga_sync_page_size": settings.GIGA_SYNC_PAGE_SIZE,
        "env_file": str(ENV_FILE),
    }


@router.patch("")
async def update_config(body: ConfigUpdateRequest):
    """写入后端 .env。配置在后端重启后生效。"""
    updates = body.model_dump(exclude_unset=True)
    _write_env_updates(updates)
    return {
        "status": "saved",
        "restart_required": True,
        "env_file": str(ENV_FILE),
        "updated_fields": sorted(updates.keys()),
    }


@router.get("/status")
async def system_status():
    """系统状态检查"""
    return {
        "status": "ok",
        "database": str(settings.DATABASE_URL).split("/")[-1],
        "product_dir_exists": settings.PRODUCT_BASE_DIR.exists(),
    }
