import os
import re
import tempfile
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
ENV_KEY_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*$")
SECRET_KEY_MARKERS = ("KEY", "SECRET", "TOKEN", "PASSWORD", "DATABASE_URL")
PLACEHOLDER_SECRET_VALUES = {"", "xxx", "token", "your_token", "your_key", "your_secret"}


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
    step1_material_download_mode: str | None = Field(default=None, pattern="^(browser|api)$")
    step1_material_package_priority: str | None = Field(default=None, min_length=1, max_length=200)
    step1_price_missing_policy: str | None = Field(default=None, pattern="^(fail|manual_review|continue)$")
    step1_material_missing_policy: str | None = Field(default=None, pattern="^(fail|manual_review|continue)$")
    step1_allow_existing_materials: bool | None = None
    pricing_commission_rate: float | None = Field(default=None, ge=0, lt=1)
    pricing_return_rate: float | None = Field(default=None, ge=0, lt=1)
    pricing_insurance_rate: float | None = Field(default=None, ge=0, lt=1)
    pricing_insurance_payout_rate: float | None = Field(default=None, ge=0, lt=1)
    pricing_return_management_fee_rate: float | None = Field(default=None, ge=0, lt=1)
    pricing_return_management_fee_cap: float | None = Field(default=None, ge=0, le=1000)
    pricing_advertising_cost: float | None = Field(default=None, ge=0, le=1000)
    pricing_target_margin_rate: float | None = Field(default=None, ge=0, lt=1)
    pricing_min_profit: float | None = Field(default=None, ge=0, le=1000)
    step3_manual_login_on_auth_failure: bool | None = None
    step4_missing_asin_policy: str | None = Field(default=None, pattern="^(fail|manual_review|continue)$")
    step4_category_missing_policy: str | None = Field(default=None, pattern="^(fail|manual_review|continue)$")
    step4_allow_existing_category: bool | None = None
    step5_llm_temperature: float | None = Field(default=None, ge=0, le=2)
    step5_llm_max_tokens: int | None = Field(default=None, ge=500, le=8000)
    step5_llm_timeout_seconds: int | None = Field(default=None, ge=30, le=300)
    step5_llm_retry_attempts: int | None = Field(default=None, ge=0, le=5)
    step5_description_input_max_chars: int | None = Field(default=None, ge=1000, le=20000)
    step5_features_input_max_chars: int | None = Field(default=None, ge=500, le=10000)
    step5_structured_input_max_chars: int | None = Field(default=None, ge=1000, le=16000)
    step5_image_context_max_items: int | None = Field(default=None, ge=1, le=16)
    step5_image_evidence_max_chars: int | None = Field(default=None, ge=100, le=1500)
    step5_image_diagnostics_max_chars: int | None = Field(default=None, ge=200, le=3000)
    step5_title_max_chars: int | None = Field(default=None, ge=40, le=75)
    step5_product_highlight_max_chars: int | None = Field(default=None, ge=80, le=120)
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
    auto_aplus_after_export_ready: bool | None = None
    giga_sync_page_size: int | None = Field(default=None, ge=1, le=200)

    @model_validator(mode="after")
    def validate_pricing_rates(self):
        commission_rate = self.pricing_commission_rate
        return_rate = self.pricing_return_rate
        management_fee_rate = self.pricing_return_management_fee_rate
        margin_rate = self.pricing_target_margin_rate
        if commission_rate is None:
            commission_rate = settings.PRICING_COMMISSION_RATE
        if return_rate is None:
            return_rate = settings.PRICING_RETURN_RATE
        if management_fee_rate is None:
            management_fee_rate = settings.PRICING_RETURN_MANAGEMENT_FEE_RATE
        if margin_rate is None:
            margin_rate = settings.PRICING_TARGET_MARGIN_RATE
        retained_rate = (1 - commission_rate) * (1 - return_rate)
        retained_rate -= return_rate * commission_rate * management_fee_rate
        if retained_rate <= margin_rate:
            raise ValueError("佣金、退货与退货管理费后的可留存收入必须大于目标净利率")
        return self


class LocalEnvValueUpdateRequest(BaseModel):
    value: str = Field(default="", max_length=20000)


class LocalEnvImportRequest(BaseModel):
    content: str = Field(min_length=1, max_length=500000)


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
    "step1_material_download_mode": "STEP1_MATERIAL_DOWNLOAD_MODE",
    "step1_material_package_priority": "STEP1_MATERIAL_PACKAGE_PRIORITY",
    "step1_price_missing_policy": "STEP1_PRICE_MISSING_POLICY",
    "step1_material_missing_policy": "STEP1_MATERIAL_MISSING_POLICY",
    "step1_allow_existing_materials": "STEP1_ALLOW_EXISTING_MATERIALS",
    "pricing_commission_rate": "PRICING_COMMISSION_RATE",
    "pricing_return_rate": "PRICING_RETURN_RATE",
    "pricing_insurance_rate": "PRICING_INSURANCE_RATE",
    "pricing_insurance_payout_rate": "PRICING_INSURANCE_PAYOUT_RATE",
    "pricing_return_management_fee_rate": "PRICING_RETURN_MANAGEMENT_FEE_RATE",
    "pricing_return_management_fee_cap": "PRICING_RETURN_MANAGEMENT_FEE_CAP",
    "pricing_advertising_cost": "PRICING_ADVERTISING_COST",
    "pricing_target_margin_rate": "PRICING_TARGET_MARGIN_RATE",
    "pricing_min_profit": "PRICING_MIN_PROFIT",
    "step3_manual_login_on_auth_failure": "STEP3_MANUAL_LOGIN_ON_AUTH_FAILURE",
    "step4_missing_asin_policy": "STEP4_MISSING_ASIN_POLICY",
    "step4_category_missing_policy": "STEP4_CATEGORY_MISSING_POLICY",
    "step4_allow_existing_category": "STEP4_ALLOW_EXISTING_CATEGORY",
    "step5_llm_temperature": "STEP5_LLM_TEMPERATURE",
    "step5_llm_max_tokens": "STEP5_LLM_MAX_TOKENS",
    "step5_llm_timeout_seconds": "STEP5_LLM_TIMEOUT_SECONDS",
    "step5_llm_retry_attempts": "STEP5_LLM_RETRY_ATTEMPTS",
    "step5_description_input_max_chars": "STEP5_DESCRIPTION_INPUT_MAX_CHARS",
    "step5_features_input_max_chars": "STEP5_FEATURES_INPUT_MAX_CHARS",
    "step5_structured_input_max_chars": "STEP5_STRUCTURED_INPUT_MAX_CHARS",
    "step5_image_context_max_items": "STEP5_IMAGE_CONTEXT_MAX_ITEMS",
    "step5_image_evidence_max_chars": "STEP5_IMAGE_EVIDENCE_MAX_CHARS",
    "step5_image_diagnostics_max_chars": "STEP5_IMAGE_DIAGNOSTICS_MAX_CHARS",
    "step5_title_max_chars": "STEP5_TITLE_MAX_CHARS",
    "step5_product_highlight_max_chars": "STEP5_PRODUCT_HIGHLIGHT_MAX_CHARS",
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
    "auto_aplus_after_export_ready": "AUTO_APLUS_AFTER_EXPORT_READY",
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


def _is_secret_key(key: str) -> bool:
    return any(marker in key for marker in SECRET_KEY_MARKERS)


def _has_effective_value(key: str, value: str) -> bool:
    if _is_secret_key(key):
        return value.strip().lower() not in PLACEHOLDER_SECRET_VALUES
    return bool(value.strip())


def _env_section_from_comment(comment: str) -> str | None:
    if "───" in comment:
        return comment.strip("─ ")
    if comment == "Runtime configuration":
        return "运行配置"
    if comment == "Filled missing defaults for local completeness":
        return "本地默认配置"
    if comment.startswith("GIGA Open API runtime options"):
        return "GIGA Open API"
    return None


def _parse_env_entries(content: str) -> list[tuple[str, str, str]]:
    entries: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    section = "未分类"
    for number, line in enumerate(content.splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            section = _env_section_from_comment(stripped[1:].strip()) or section
            continue
        if "=" not in line:
            raise HTTPException(400, f"第 {number} 行不是 KEY=VALUE 格式")
        key, value = line.split("=", 1)
        key = key.strip()
        if not ENV_KEY_PATTERN.fullmatch(key):
            raise HTTPException(400, f"第 {number} 行的变量名无效: {key or '(空)'}")
        if key in seen:
            raise HTTPException(400, f"变量 {key} 重复出现")
        seen.add(key)
        entries.append((key, value.strip(), section))
    if not entries:
        raise HTTPException(400, "配置文件中没有有效的环境变量")
    return entries


def _atomic_write_env(content: str) -> None:
    ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
    normalized = content.rstrip("\n") + "\n"
    fd, temp_name = tempfile.mkstemp(prefix=".env.", dir=ENV_FILE.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as temp_file:
            temp_file.write(normalized)
        os.chmod(temp_name, 0o600)
        os.replace(temp_name, ENV_FILE)
        os.chmod(ENV_FILE, 0o600)
    except Exception:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def _local_env_items() -> list[dict[str, Any]]:
    content = ENV_FILE.read_text(encoding="utf-8") if ENV_FILE.exists() else ""
    return [
        {
            "key": key,
            "value": "已隐藏" if _is_secret_key(key) else value,
            "is_secret": _is_secret_key(key),
            "has_value": _has_effective_value(key, value),
            "section": section,
        }
        for key, value, section in _parse_env_entries(content)
    ]


def _write_local_env_value(key: str, value: str) -> None:
    if not ENV_KEY_PATTERN.fullmatch(key):
        raise HTTPException(400, "变量名无效")
    if "\n" in value or "\r" in value:
        raise HTTPException(400, "配置值不能包含换行")

    lines = ENV_FILE.read_text(encoding="utf-8").splitlines() if ENV_FILE.exists() else []
    found = False
    next_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            next_lines.append(line)
            continue
        existing_key = line.split("=", 1)[0].strip()
        if existing_key == key:
            next_lines.append(f"{key}={value}")
            found = True
        else:
            next_lines.append(line)
    if not found:
        if next_lines and next_lines[-1].strip():
            next_lines.append("")
        next_lines.append(f"{key}={value}")
    _atomic_write_env("\n".join(next_lines))


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

    _atomic_write_env("\n".join(next_lines))


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
                "APLUS_IMAGE_API_MODE": "generations",
                "APLUS_IMAGE_GENERATION_QUALITY": "high",
                "APLUS_IMAGE_WIDTH": 1940,
                "APLUS_IMAGE_HEIGHT": 1200,
                "APLUS_IMAGE_ASPECT_RATIO": "97:60",
                "APLUS_IMAGE_MAX_BYTES": 2000000,
                "APLUS_IMAGE_JPEG_QUALITY": 88,
                "APLUS_IMAGE_MIN_JPEG_QUALITY": 55,
                "APLUS_IMAGE_API_RETRIES": 1,
                "APLUS_IMAGE_OVERWRITE_POLICY": "skip_success",
                "PIPELINE_MAX_CONCURRENCY": 2,
                "BROWSER_WORKFLOW_CONCURRENCY": 1,
                "BULK_START_MAX_TASKS": 100,
                "STEP1_EXTRACT_RETRY_ATTEMPTS": 5,
                "STEP1_EXTRACT_RETRY_DELAY_SECONDS": 3,
                "STEP1_DOWNLOAD_TIMEOUT_SECONDS": 300,
                "STEP1_MATERIAL_DOWNLOAD_MODE": "browser",
                "STEP1_MATERIAL_PACKAGE_PRIORITY": "To B素材包,Retail Ready素材包,Information",
                "STEP1_PRICE_MISSING_POLICY": "manual_review",
                "STEP1_MATERIAL_MISSING_POLICY": "manual_review",
                "STEP1_ALLOW_EXISTING_MATERIALS": True,
                "PRICING_COMMISSION_RATE": 0.10,
                "PRICING_RETURN_RATE": 0.04,
                "PRICING_INSURANCE_RATE": 0.025,
                "PRICING_INSURANCE_PAYOUT_RATE": 0.60,
                "PRICING_RETURN_MANAGEMENT_FEE_RATE": 0.20,
                "PRICING_RETURN_MANAGEMENT_FEE_CAP": 5.0,
                "PRICING_ADVERTISING_COST": 2.0,
                "PRICING_TARGET_MARGIN_RATE": 0.05,
                "PRICING_MIN_PROFIT": 10.0,
                "STEP3_MANUAL_LOGIN_ON_AUTH_FAILURE": True,
                "STEP4_MISSING_ASIN_POLICY": "manual_review",
                "STEP4_CATEGORY_MISSING_POLICY": "manual_review",
                "STEP4_ALLOW_EXISTING_CATEGORY": True,
                "STEP5_LLM_TEMPERATURE": 0.3,
                "STEP5_LLM_MAX_TOKENS": 4500,
                "STEP5_LLM_TIMEOUT_SECONDS": 120,
                "STEP5_LLM_RETRY_ATTEMPTS": 2,
                "STEP5_DESCRIPTION_INPUT_MAX_CHARS": 8000,
                "STEP5_FEATURES_INPUT_MAX_CHARS": 4000,
                "STEP5_STRUCTURED_INPUT_MAX_CHARS": 6000,
                "STEP5_IMAGE_CONTEXT_MAX_ITEMS": 6,
                "STEP5_IMAGE_EVIDENCE_MAX_CHARS": 500,
                "STEP5_IMAGE_DIAGNOSTICS_MAX_CHARS": 1000,
                "STEP5_TITLE_MAX_CHARS": 75,
                "STEP5_PRODUCT_HIGHLIGHT_MAX_CHARS": 120,
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
        "database_backend": settings.DATABASE_BACKEND,
        "sqlite_database_path": str(settings.SQLITE_DATABASE_PATH) if settings.is_sqlite else None,
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
        "auto_aplus_after_export_ready": settings.AUTO_APLUS_AFTER_EXPORT_READY,
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
        "step1_material_download_mode": settings.STEP1_MATERIAL_DOWNLOAD_MODE,
        "step1_material_package_priority": settings.STEP1_MATERIAL_PACKAGE_PRIORITY,
        "step1_price_missing_policy": settings.STEP1_PRICE_MISSING_POLICY,
        "step1_material_missing_policy": settings.STEP1_MATERIAL_MISSING_POLICY,
        "step1_allow_existing_materials": settings.STEP1_ALLOW_EXISTING_MATERIALS,
        "pricing_commission_rate": settings.PRICING_COMMISSION_RATE,
        "pricing_return_rate": settings.PRICING_RETURN_RATE,
        "pricing_insurance_rate": settings.PRICING_INSURANCE_RATE,
        "pricing_insurance_payout_rate": settings.PRICING_INSURANCE_PAYOUT_RATE,
        "pricing_return_management_fee_rate": settings.PRICING_RETURN_MANAGEMENT_FEE_RATE,
        "pricing_return_management_fee_cap": settings.PRICING_RETURN_MANAGEMENT_FEE_CAP,
        "pricing_advertising_cost": settings.PRICING_ADVERTISING_COST,
        "pricing_target_margin_rate": settings.PRICING_TARGET_MARGIN_RATE,
        "pricing_min_profit": settings.PRICING_MIN_PROFIT,
        "step3_manual_login_on_auth_failure": settings.STEP3_MANUAL_LOGIN_ON_AUTH_FAILURE,
        "step4_missing_asin_policy": settings.STEP4_MISSING_ASIN_POLICY,
        "step4_category_missing_policy": settings.STEP4_CATEGORY_MISSING_POLICY,
        "step4_allow_existing_category": settings.STEP4_ALLOW_EXISTING_CATEGORY,
        "step5_llm_temperature": settings.STEP5_LLM_TEMPERATURE,
        "step5_llm_max_tokens": settings.STEP5_LLM_MAX_TOKENS,
        "step5_llm_timeout_seconds": settings.STEP5_LLM_TIMEOUT_SECONDS,
        "step5_llm_retry_attempts": settings.STEP5_LLM_RETRY_ATTEMPTS,
        "step5_description_input_max_chars": settings.STEP5_DESCRIPTION_INPUT_MAX_CHARS,
        "step5_features_input_max_chars": settings.STEP5_FEATURES_INPUT_MAX_CHARS,
        "step5_structured_input_max_chars": settings.STEP5_STRUCTURED_INPUT_MAX_CHARS,
        "step5_image_context_max_items": settings.STEP5_IMAGE_CONTEXT_MAX_ITEMS,
        "step5_image_evidence_max_chars": settings.STEP5_IMAGE_EVIDENCE_MAX_CHARS,
        "step5_image_diagnostics_max_chars": settings.STEP5_IMAGE_DIAGNOSTICS_MAX_CHARS,
        "step5_title_max_chars": settings.STEP5_TITLE_MAX_CHARS,
        "step5_product_highlight_max_chars": settings.STEP5_PRODUCT_HIGHLIGHT_MAX_CHARS,
        "step5_bullet_max_chars": settings.STEP5_BULLET_MAX_CHARS,
        "step5_search_terms_max_bytes": settings.STEP5_SEARCH_TERMS_MAX_BYTES,
        "llm_api_configured": bool(settings.LLM_API_KEY),
        "vlm_api_configured": bool(settings.LLM_API_KEY if settings.VLM_USE_LLM_API else settings.VLM_API_KEY),
        "gpt_image_api_configured": bool(settings.resolved_gpt_image_api_key),
        "sellersprite_configured": bool(
            settings.SELLERSPRITE_OPENAPI_SECRET_KEY.strip()
            or settings.SELLERSPRITE_TOKEN.strip().lower() not in PLACEHOLDER_SECRET_VALUES
        ),
        "sellersprite_openapi_configured": bool(settings.SELLERSPRITE_OPENAPI_SECRET_KEY.strip()),
        "sellersprite_browser_token_configured": settings.SELLERSPRITE_TOKEN.strip().lower()
        not in PLACEHOLDER_SECRET_VALUES,
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


@router.get("/local-env")
async def get_local_env():
    """列出本地 backend/.env；敏感值始终脱敏。"""
    return {
        "env_file": str(ENV_FILE),
        "items": _local_env_items(),
        "restart_required": True,
    }


@router.patch("/local-env/{key}")
async def update_local_env_value(key: str, body: LocalEnvValueUpdateRequest):
    """更新本地 backend/.env 的单个变量，服务重启后生效。"""
    _write_local_env_value(key, body.value)
    return {"status": "saved", "key": key, "restart_required": True}


@router.post("/local-env/import")
async def import_local_env(body: LocalEnvImportRequest):
    """校验后导入完整的本地 backend/.env 文件。"""
    entries = _parse_env_entries(body.content)
    _atomic_write_env(body.content)
    return {"status": "imported", "imported_count": len(entries), "restart_required": True}


@router.get("/status")
async def system_status():
    """系统状态检查"""
    return {
        "status": "ok",
        "database": str(settings.DATABASE_URL).split("/")[-1],
        "product_dir_exists": settings.PRODUCT_BASE_DIR.exists(),
    }
