from pydantic_settings import BaseSettings
from pathlib import Path
from typing import Literal
import httpx
import json
from openai import AsyncOpenAI


BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent


def _resolve_local_path(path: Path) -> Path:
    """Resolve user paths and backend/.env relative paths to absolute paths."""
    expanded = path.expanduser()
    if expanded.is_absolute():
        return expanded
    return (BACKEND_DIR / expanded).resolve()


def _load_gpt_image_external_config(path: Path | None) -> dict[str, str]:
    """Load an optional personal GPT Image provider config without exposing credentials."""
    if path is None:
        return {}
    resolved = _resolve_local_path(path)
    if not resolved.is_file():
        return {}
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("GPT Image external config is unreadable or invalid JSON") from exc
    base_url = str(payload.get("base_url") or "").strip().rstrip("/")
    api_key = str(payload.get("api_key") or "").strip()
    model = str(payload.get("model") or "").strip()
    if not base_url or not api_key:
        raise ValueError("GPT Image external config requires base_url and api_key")
    if not base_url.endswith("/v1"):
        base_url += "/v1"
    return {"base_url": base_url, "api_key": api_key, "model": model}


class Settings(BaseSettings):
    # 项目
    PROJECT_NAME: str = "FBM Pipeline"
    VERSION: str = "0.1.0"
    DEBUG: bool = True

    # 数据库
    DATA_DIR: Path = REPO_ROOT / "data"
    # DATABASE_BACKEND is deliberately restart-only.  A live process cannot
    # safely swap an async engine while requests and task workers hold sessions.
    DATABASE_BACKEND: Literal["mysql", "sqlite"] = "mysql"
    DATABASE_URL: str = ""  # MySQL 模式必填；SQLite 模式不读取此项
    SQLITE_DATABASE_PATH: Path = REPO_ROOT / "data" / "fbm-pipeline.db"
    DATABASE_CONNECT_TIMEOUT_SECONDS: int = 15
    DATABASE_READ_TIMEOUT_SECONDS: int = 120

    # 服务端口
    BACKEND_HOST: str = "127.0.0.1"
    BACKEND_PORT: int = 8190
    FRONTEND_HOST: str = "127.0.0.1"
    FRONTEND_PORT: int = 3190

    # Local runtime security. Defaults are intentionally local-only and no-maintenance.
    API_DEV_TOKEN: str = ""
    STARTUP_RUN_DB_MAINTENANCE: bool = False
    STARTUP_RUN_BACKFILLS: bool = False
    STARTUP_RECOVER_TASKS: bool = False
    STARTUP_KICK_TASK_RUNTIME: bool = False
    # 常驻任务巡检：只重新唤醒 ready 或确认已卡死的运行步骤；业务失败不会自动重跑。
    TASK_RUNTIME_AUTO_WAKE_ENABLED: bool = True
    TASK_RUNTIME_AUTO_WAKE_INTERVAL_SECONDS: int = 30 * 60
    TASK_RUNTIME_AUTO_WAKE_MAX_ATTEMPTS_PER_ISSUE: int = 30
    EXTERNAL_HTTP_VERIFY_TLS: bool = True
    EXTERNAL_HTTP_CA_BUNDLE: Path | None = None
    IMAGE_PROXY_EXTRA_ROOTS: str = ""
    IMAGE_COMPLIANCE_EXIFTOOL_PATH: str = "exiftool"
    IMAGE_COMPLIANCE_VERIFY_OSS_ROUND_TRIP: bool = True

    # 商品文件存储根目录
    PRODUCT_BASE_DIR: Path = REPO_ROOT / "data" / "products"

    # 默认品牌
    DEFAULT_BRAND: str = "Vindhvisk"

    # LLM API (sub2api — Listing/A+规划/A+脚本)
    LLM_API_BASE: str = "https://sub2api.127space.com/v1"
    LLM_API_KEY: str = ""
    LLM_MODEL: str = "gpt-5.5"

    # VLM API (默认复用 LLM API 的 GPT-5.5 多模态能力做主图分析)
    VLM_API_BASE: str = "https://sub2api.127space.com/v1"
    VLM_API_KEY: str = ""
    VLM_MODEL: str = "gpt-5.5"
    VLM_USE_LLM_API: bool = True  # True 时使用 LLM_API_BASE/LLM_API_KEY 跑图片分析
    # Step6 会同时处理本地 To B 素材和远程供应商图片。高分辨率图片一次塞太多会让
    # OpenAI-compatible 网关在默认 60 秒内超时，因此限制每批图片数并给真实视觉
    # 推理保留足够时间；失败仍然 fail-closed，不下载远程图、不切 Contact Sheet 兜底。
    STEP6_VLM_BATCH_SIZE: int = 2
    STEP6_VLM_TIMEOUT_SECONDS: int = 150
    # Supplier image contact sheets are independent within one product.  Keep
    # this modest to shorten large galleries without overwhelming the VLM API.
    AUTO_IMAGE_SELECTION_VLM_CONCURRENCY: int = 2
    # 用户心智梳理会在两次长模型调用后才持久化结果。远程 MySQL 连接若在此期间
    # 被中间网络回收，使用新 session 对幂等 UPDATE 做有限重试，避免浪费生成结果。
    CUSTOMER_MINDSET_PERSIST_RETRY_ATTEMPTS: int = 3
    CUSTOMER_MINDSET_DYNAMIC_QUESTION_ATTEMPTS: int = 3

    # GPT Image API (t8star — A+出图)
    GPT_IMAGE_API_BASE: str = "https://ai.t8star.cn/v1"
    GPT_IMAGE_API_KEY: str = ""
    GPT_IMAGE_MODEL: str = "gpt-image-2"
    GPT_IMAGE_USE_LLM_API: bool = False  # True 时复用 LLM_API_BASE/LLM_API_KEY 跑生图，模型仍使用 GPT_IMAGE_MODEL
    GPT_IMAGE_EXTERNAL_CONFIG_PATH: Path | None = Path.home() / ".codex/skills/gpt-image-async/scripts/config.json"
    APLUS_IMAGE_API_MODE: str = "generations"
    APLUS_IMAGE_GENERATION_QUALITY: str = "high"
    APLUS_IMAGE_WIDTH: int = 1940
    APLUS_IMAGE_HEIGHT: int = 1200
    APLUS_IMAGE_ASPECT_RATIO: str = "97:60"
    APLUS_IMAGE_MAX_BYTES: int = 2_000_000
    APLUS_IMAGE_JPEG_QUALITY: int = 88
    APLUS_IMAGE_MIN_JPEG_QUALITY: int = 55
    # A+ generations 失败后必须停在失败态，交给人工决定是否再次消耗生图额度。
    APLUS_IMAGE_API_RETRIES: int = 1
    APLUS_IMAGE_OVERWRITE_POLICY: str = "skip_success"  # skip_success/overwrite_all
    APLUS_PLAN_LLM_TIMEOUT_SECONDS: int = 120
    APLUS_SCRIPT_LLM_TIMEOUT_SECONDS: int = 180
    # 新商品默认在 Listing 完成后继续创建 A+ 派生任务；A+ 失败不会回退商品的待导出状态。
    AUTO_APLUS_AFTER_EXPORT_READY: bool = True
    LINGXING_APLUS_STORE_NAME: str = ""
    LINGXING_APLUS_STORE_ID: str = ""
    LINGXING_APLUS_SITE: str = "US"
    LINGXING_LISTING_SYNC_ALLOW_REAL_EXTERNAL_CALLS: bool = False
    LINGXING_APLUS_ALLOW_REAL_EXTERNAL_CALLS: bool = False
    LINGXING_APLUS_SUBMIT_FOR_APPROVAL: bool = False

    # OSS 图片上传（Step10 Amazon导入表格图片URL）
    OSS_ACCESS_KEY_ID: str = ""
    OSS_ACCESS_KEY_SECRET: str = ""
    OSS_BUCKET: str = ""
    OSS_ENDPOINT: str = ""
    OSS_UPLOAD_PREFIX: str = "main_image/"
    OSS_TEMPLATE_UPLOAD_PREFIX: str = "category_templates/"
    OSS_EXPORT_UPLOAD_PREFIX: str = "catalog_exports/"
    OSS_SIGNED_URL_EXPIRES_SECONDS: int = 30 * 24 * 60 * 60
    OSS_UPLOAD_TIMEOUT_SECONDS: int = 15

    # Amazon Price & Quantity 库存同步模板
    PRICE_QUANTITY_TEMPLATE_PATH: Path = Path(__file__).resolve().parent / "pipeline" / "templates" / "PriceAndQuantity.xlsm"

    # 卖家精灵
    SELLERSPRITE_TOKEN: str = ""
    SELLERSPRITE_OPENAPI_SECRET_KEY: str = ""

    # GIGA Open API runtime options. Store/API credentials are maintained in product_data_sources.
    GIGA_SYNC_PAGE_SIZE: int = 200

    # Chrome 控制
    CHROME_LOCK_TIMEOUT: int = 300  # Chrome串行操作锁超时(秒)
    BROWSER_WORKFLOW_CONCURRENCY: int = 1  # 完整浏览器业务流程并发数。当前共用一个 worker tab，建议保持 1。

    # Amazon search page adapter. Defaults are fail-closed; real browser access must be explicitly enabled.
    AMAZON_SEARCH_PAGE_ADAPTER: str = "unconfigured"  # unconfigured/chrome
    AMAZON_SEARCH_ENABLE_REAL_BROWSER: bool = False
    AMAZON_SEARCH_MARKETPLACE: str = "US"
    AMAZON_SEARCH_BASE_URL: str = "https://www.amazon.com"
    AMAZON_SEARCH_PER_QUERY_LIMIT: int = 12
    AMAZON_SEARCH_MAX_CANDIDATES: int = 20
    AMAZON_SEARCH_NAV_TIMEOUT_SECONDS: int = 45
    AMAZON_SEARCH_AFTER_LOAD_WAIT_SECONDS: float = 4.0
    AMAZON_SEARCH_BETWEEN_QUERY_DELAY_SECONDS: float = 10.0
    AMAZON_SEARCH_EVIDENCE_DIR: Path | None = None

    # Amazon listing detail adapter. Uses the same dedicated local Chrome worker tab
    # as search, but remains separately fail-closed and must be explicitly enabled.
    AMAZON_LISTING_DETAIL_ADAPTER: str = "unconfigured"  # unconfigured/chrome
    AMAZON_LISTING_DETAIL_ENABLE_REAL_BROWSER: bool = False
    AMAZON_LISTING_DETAIL_NAV_TIMEOUT_SECONDS: int = 45
    AMAZON_LISTING_DETAIL_AFTER_LOAD_WAIT_SECONDS: float = 4.0
    AMAZON_LISTING_DETAIL_BETWEEN_CANDIDATE_DELAY_SECONDS: float = 8.0
    AMAZON_LISTING_DETAIL_EVIDENCE_DIR: Path | None = None

    # Pipeline
    PIPELINE_MAX_CONCURRENCY: int = 2  # 同时运行的Pipeline任务数上限
    BULK_START_MAX_TASKS: int = 100    # 单次批量启动最大任务数
    STEP3_4_PARALLEL: bool = True  # Step3/4是否并行
    STEP1_EXTRACT_RETRY_ATTEMPTS: int = 5  # Step1页面信息提取重试次数
    STEP1_EXTRACT_RETRY_DELAY_SECONDS: int = 3  # Step1页面信息提取重试间隔
    STEP1_AFTER_READY_WAIT_SECONDS: float = 1.0  # 页面有内容后再等价格/规格等异步区渲染
    STEP1_DOWNLOAD_TIMEOUT_SECONDS: int = 300  # Step1素材包下载超时时间
    STEP1_BROWSER_DOWNLOAD_START_TIMEOUT_SECONDS: int = 60  # Chrome 点击下载后未开始时，尽快回退 API
    # browser: 先打开商品页并点击“下载素材包”，失败后回退网页登录接口；api: 顺序相反。
    STEP1_MATERIAL_DOWNLOAD_MODE: str = "browser"
    STEP1_MATERIAL_PACKAGE_PRIORITY: str = "To B素材包,Retail Ready素材包,Information"
    STEP1_PRICE_MISSING_POLICY: str = "manual_review"  # fail/manual_review/continue
    STEP1_MATERIAL_MISSING_POLICY: str = "manual_review"  # fail/manual_review/continue
    STEP1_ALLOW_EXISTING_MATERIALS: bool = True
    # Amazon FBM 定价（美元）。完整推导见 pipeline/step2_pricing.py。
    PRICING_COMMISSION_RATE: float = 0.10  # Amazon 销售佣金：售价的 10%
    PRICING_RETURN_RATE: float = 0.04  # 实际退货率：4%
    PRICING_INSURANCE_RATE: float = 0.025  # 大建退货保障保费：货值的 2.5%
    PRICING_INSURANCE_PAYOUT_RATE: float = 0.60  # 退货保障赔付：只赔货值的 60%，不赔物流
    PRICING_RETURN_MANAGEMENT_FEE_RATE: float = 0.20  # Amazon 退货管理费：佣金的 20%
    PRICING_RETURN_MANAGEMENT_FEE_CAP: float = 5.0  # Amazon 单笔退货管理费封顶（美元）
    PRICING_ADVERTISING_COST: float = 2.0  # 每成交订单的广告成本预留（美元）
    PRICING_TARGET_MARGIN_RATE: float = 0.05  # 目标净利率，按预期利润/售价计算
    PRICING_MIN_PROFIT: float = 10.0  # 单件最低预期利润（美元）
    STEP3_MANUAL_LOGIN_ON_AUTH_FAILURE: bool = True  # 卖家精灵未登录/过期时打开页面等待人工登录
    STEP3_LLM_TIMEOUT_SECONDS: int = 120  # 卖家精灵无结果时的关键词 LLM 兜底上限
    STEP4_MISSING_ASIN_POLICY: str = "manual_review"  # fail/manual_review/continue
    STEP4_CATEGORY_MISSING_POLICY: str = "manual_review"  # fail/manual_review/continue
    STEP4_ALLOW_EXISTING_CATEGORY: bool = True
    STEP4_CATEGORY_FETCH_TIMEOUT_SECONDS: int = 45
    # Listing 需要完整的买家心智和商品事实；输出采用较低随机性，避免改写时漂移。
    STEP5_LLM_TEMPERATURE: float = 0.3
    STEP5_LLM_MAX_TOKENS: int = 4500
    STEP5_LLM_TIMEOUT_SECONDS: int = 120
    STEP5_LLM_RETRY_ATTEMPTS: int = 2
    # 用户心智要一次回答 15-18 题并生成 Listing/A+ 共用策略，真实输出可达 7500 tokens，
    # 不应沿用普通 Listing 的短请求超时。
    CUSTOMER_MINDSET_LLM_TIMEOUT_SECONDS: int = 300
    STEP5_DESCRIPTION_INPUT_MAX_CHARS: int = 8000
    STEP5_FEATURES_INPUT_MAX_CHARS: int = 4000
    STEP5_STRUCTURED_INPUT_MAX_CHARS: int = 6000
    STEP5_IMAGE_CONTEXT_MAX_ITEMS: int = 6
    STEP5_IMAGE_EVIDENCE_MAX_CHARS: int = 500
    STEP5_IMAGE_DIAGNOSTICS_MAX_CHARS: int = 1000
    STEP5_TITLE_MAX_CHARS: int = 75
    STEP5_PRODUCT_HIGHLIGHT_MAX_CHARS: int = 120
    STEP5_BULLET_MAX_CHARS: int = 500
    STEP5_SEARCH_TERMS_MAX_BYTES: int = 250
    APLUS_CONCURRENCY: int = 1     # A+图并发数
    POLL_INTERVAL: int = 3         # 前端轮询间隔(秒)

    def model_post_init(self, __context):
        self.DATA_DIR = _resolve_local_path(self.DATA_DIR)
        self.PRODUCT_BASE_DIR = _resolve_local_path(self.PRODUCT_BASE_DIR)
        self.SQLITE_DATABASE_PATH = _resolve_local_path(self.SQLITE_DATABASE_PATH)
        self.PRICE_QUANTITY_TEMPLATE_PATH = _resolve_local_path(self.PRICE_QUANTITY_TEMPLATE_PATH)
        if self.AMAZON_SEARCH_EVIDENCE_DIR is None:
            self.AMAZON_SEARCH_EVIDENCE_DIR = self.DATA_DIR / "task_evidence" / "amazon_search_page"
        else:
            self.AMAZON_SEARCH_EVIDENCE_DIR = _resolve_local_path(self.AMAZON_SEARCH_EVIDENCE_DIR)
        if self.EXTERNAL_HTTP_CA_BUNDLE:
            self.EXTERNAL_HTTP_CA_BUNDLE = _resolve_local_path(self.EXTERNAL_HTTP_CA_BUNDLE)
        if self.DATABASE_BACKEND == "mysql":
            if not self.DATABASE_URL:
                raise ValueError("DATABASE_URL is required in mysql mode; configure mysql+asyncmy://... for fbm-pipeline.")
            if not self.DATABASE_URL.startswith("mysql+asyncmy://"):
                raise ValueError("DATABASE_URL must be a MySQL asyncmy connection string in mysql mode, e.g. mysql+asyncmy://user:pass@host:3306/fbm_pipeline?charset=utf8mb4.")
        else:
            # SQLite is intentionally local and single-user.  These values are
            # consumed during module import, so enforce the safe limits before
            # worker/pipeline modules construct their semaphores.
            self.PIPELINE_MAX_CONCURRENCY = 1
            self.APLUS_CONCURRENCY = 1
            self.AUTO_IMAGE_SELECTION_VLM_CONCURRENCY = 1

    @property
    def is_sqlite(self) -> bool:
        return self.DATABASE_BACKEND == "sqlite"

    @property
    def effective_database_url(self) -> str:
        """Return the only connection URL the current process may use."""
        if self.is_sqlite:
            return f"sqlite+aiosqlite:///{self.SQLITE_DATABASE_PATH}"
        return self.DATABASE_URL

    model_config = {"env_file": BACKEND_DIR / ".env", "env_file_encoding": "utf-8", "extra": "ignore"}

    def get_llm_client(self) -> AsyncOpenAI:
        """创建LLM OpenAI客户端。"""
        return AsyncOpenAI(
            base_url=self.LLM_API_BASE,
            api_key=self.LLM_API_KEY,
            http_client=httpx.AsyncClient(verify=self.external_http_verify),
        )

    def get_vlm_client(self) -> AsyncOpenAI:
        """创建VLM OpenAI客户端"""
        return AsyncOpenAI(
            base_url=self.VLM_API_BASE,
            api_key=self.VLM_API_KEY,
        )

    def get_image_analysis_client(self) -> AsyncOpenAI:
        """创建图片分析客户端，可按配置走独立VLM通道或LLM通道。"""
        return self.get_llm_client() if self.VLM_USE_LLM_API else self.get_vlm_client()

    @property
    def resolved_gpt_image_api_base(self) -> str:
        """返回Step9实际使用的生图API地址。"""
        if self.GPT_IMAGE_USE_LLM_API:
            return self.LLM_API_BASE
        external = _load_gpt_image_external_config(self.GPT_IMAGE_EXTERNAL_CONFIG_PATH)
        base_url = (external.get("base_url") or self.GPT_IMAGE_API_BASE).rstrip("/")
        # gpt-image-async 的个人配置保存的是服务根地址（例如 https://ai.t8star.cn），
        # 而应用内独立配置保存的是 /v1 地址。Step 9 使用 OpenAI-compatible paths，
        # 因此统一为带 /v1 的 base，避免切到 T8Star 后意外请求 /images/... 根路径。
        return base_url if base_url.endswith("/v1") else f"{base_url}/v1"

    @property
    def resolved_gpt_image_api_key(self) -> str:
        """返回Step9实际使用的生图API Key。"""
        if self.GPT_IMAGE_USE_LLM_API:
            return self.LLM_API_KEY
        if self.GPT_IMAGE_API_KEY:
            return self.GPT_IMAGE_API_KEY
        return _load_gpt_image_external_config(self.GPT_IMAGE_EXTERNAL_CONFIG_PATH).get("api_key") or ""

    @property
    def resolved_gpt_image_model(self) -> str:
        """返回Step9实际使用的生图模型。"""
        if self.GPT_IMAGE_USE_LLM_API or self.GPT_IMAGE_API_KEY:
            return self.GPT_IMAGE_MODEL
        return _load_gpt_image_external_config(self.GPT_IMAGE_EXTERNAL_CONFIG_PATH).get("model") or self.GPT_IMAGE_MODEL

    @property
    def gpt_image_api_provider(self) -> str:
        """返回Step9生图通道名称，便于日志和配置页确认。"""
        if self.GPT_IMAGE_USE_LLM_API:
            return "LLM_API"
        if self.GPT_IMAGE_API_KEY:
            return "GPT_IMAGE_API"
        external = _load_gpt_image_external_config(self.GPT_IMAGE_EXTERNAL_CONFIG_PATH)
        if "ai.t8star.cn" in str(external.get("base_url") or "").lower():
            return "T8Star"
        return "GPT_IMAGE_EXTERNAL_CONFIG" if self.resolved_gpt_image_api_key else "GPT_IMAGE_API"

    @property
    def external_http_verify(self) -> bool | str:
        """Return httpx verify setting for external token-bearing requests."""
        if not self.EXTERNAL_HTTP_VERIFY_TLS:
            return False
        if self.EXTERNAL_HTTP_CA_BUNDLE:
            return str(self.EXTERNAL_HTTP_CA_BUNDLE)
        return True

    @property
    def image_proxy_roots(self) -> list[Path]:
        """Default image proxy roots plus explicitly configured extra roots."""
        roots = [self.PRODUCT_BASE_DIR]
        for raw in (self.IMAGE_PROXY_EXTRA_ROOTS or "").split(","):
            value = raw.strip()
            if value:
                roots.append(_resolve_local_path(Path(value)))
        return [root.resolve() for root in roots]


settings = Settings()
