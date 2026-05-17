from pydantic_settings import BaseSettings
from pathlib import Path
import httpx
from openai import AsyncOpenAI
import ssl


class Settings(BaseSettings):
    # 项目
    PROJECT_NAME: str = "FBM Pipeline"
    VERSION: str = "0.1.0"
    DEBUG: bool = True

    # 数据库
    DATA_DIR: Path = Path.home() / "code" / "fbm-pipeline" / "data"
    DATABASE_URL: str = ""  # 动态生成

    # 服务端口
    BACKEND_PORT: int = 8190
    FRONTEND_PORT: int = 3190

    # 商品文件存储根目录
    PRODUCT_BASE_DIR: Path = Path.home() / "Documents" / "F" / "亚马逊工作目录" / "亚马逊商品" / "大健云仓"

    # 默认品牌
    DEFAULT_BRAND: str = "Vindhvisk"

    # LLM API (sub2api — Listing/A+规划/A+脚本)
    LLM_API_BASE: str = "https://sub2api.127space.com/v1"
    LLM_API_KEY: str = ""
    LLM_MODEL: str = "gpt-5.5"

    # VLM API (通义千问 DashScope — 主图分析)
    VLM_API_BASE: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    VLM_API_KEY: str = ""
    VLM_MODEL: str = "qwen3.6-plus"
    VLM_USE_LLM_API: bool = False  # True 时使用 LLM_API_BASE/LLM_API_KEY 跑图片分析，便于切到 gpt-5.5

    # GPT Image API (t8star — A+出图)
    GPT_IMAGE_API_BASE: str = "https://ai.t8star.cn/v1"
    GPT_IMAGE_API_KEY: str = ""
    GPT_IMAGE_MODEL: str = "gpt-image-2"
    GPT_IMAGE_USE_LLM_API: bool = False  # True 时复用 LLM_API_BASE/LLM_API_KEY 跑生图，模型仍使用 GPT_IMAGE_MODEL
    APLUS_IMAGE_API_MODE: str = "generations"
    APLUS_IMAGE_GENERATION_QUALITY: str = "high"
    APLUS_IMAGE_WIDTH: int = 1940
    APLUS_IMAGE_HEIGHT: int = 1200
    APLUS_IMAGE_ASPECT_RATIO: str = "97:60"
    APLUS_IMAGE_MAX_BYTES: int = 2_000_000
    APLUS_IMAGE_JPEG_QUALITY: int = 88
    APLUS_IMAGE_MIN_JPEG_QUALITY: int = 55
    APLUS_IMAGE_API_RETRIES: int = 3
    APLUS_IMAGE_OVERWRITE_POLICY: str = "skip_success"  # skip_success/overwrite_all

    # OSS 图片上传（Step10 Amazon导入表格图片URL）
    OSS_ACCESS_KEY_ID: str = ""
    OSS_ACCESS_KEY_SECRET: str = ""
    OSS_BUCKET: str = ""
    OSS_ENDPOINT: str = ""
    OSS_UPLOAD_PREFIX: str = "main_image/"
    OSS_SIGNED_URL_EXPIRES_SECONDS: int = 30 * 24 * 60 * 60

    # 卖家精灵
    SELLERSPRITE_TOKEN: str = ""

    # Chrome 控制
    CHROME_LOCK_TIMEOUT: int = 300  # Chrome串行操作锁超时(秒)
    BROWSER_WORKFLOW_CONCURRENCY: int = 1  # 完整浏览器业务流程并发数。当前共用一个 worker tab，建议保持 1。

    # Pipeline
    PIPELINE_MAX_CONCURRENCY: int = 3  # 同时运行的Pipeline任务数上限
    BULK_START_MAX_TASKS: int = 100    # 单次批量启动最大任务数
    STEP3_4_PARALLEL: bool = True  # Step3/4是否并行
    STEP1_EXTRACT_RETRY_ATTEMPTS: int = 5  # Step1页面信息提取重试次数
    STEP1_EXTRACT_RETRY_DELAY_SECONDS: int = 3  # Step1页面信息提取重试间隔
    STEP1_AFTER_READY_WAIT_SECONDS: float = 1.0  # 页面有内容后再等价格/规格等异步区渲染
    STEP1_DOWNLOAD_TIMEOUT_SECONDS: int = 300  # Step1素材包下载超时时间
    STEP1_MATERIAL_PACKAGE_PRIORITY: str = "To B素材包,Retail Ready素材包,Information"
    STEP1_PRICE_MISSING_POLICY: str = "manual_review"  # fail/manual_review/continue
    STEP1_MATERIAL_MISSING_POLICY: str = "manual_review"  # fail/manual_review/continue
    STEP1_ALLOW_EXISTING_MATERIALS: bool = True
    PRICING_NET_REVENUE_RATE: float = 0.685  # 售价扣除平台/优惠/预估变动费用后的净收入比例
    PRICING_TARGET_MARGIN_RATE: float = 0.05  # 目标净利率，按利润/售价计算
    PRICING_MIN_PROFIT: float = 10.0  # 单件最低利润
    PRICING_FIXED_COST: float = 9.0  # 固定成本预留
    PRICING_RETURN_CREDIT_RATE: float = 0.06  # 按货值估算的退货保险抵扣比例
    STEP3_MANUAL_LOGIN_ON_AUTH_FAILURE: bool = True  # 卖家精灵未登录/过期时打开页面等待人工登录
    STEP4_MISSING_ASIN_POLICY: str = "manual_review"  # fail/manual_review/continue
    STEP4_CATEGORY_MISSING_POLICY: str = "manual_review"  # fail/manual_review/continue
    STEP4_ALLOW_EXISTING_CATEGORY: bool = True
    STEP5_LLM_TEMPERATURE: float = 0.7
    STEP5_LLM_MAX_TOKENS: int = 2000
    STEP5_TITLE_MAX_CHARS: int = 200
    STEP5_BULLET_MAX_CHARS: int = 500
    STEP5_SEARCH_TERMS_MAX_BYTES: int = 250
    APLUS_CONCURRENCY: int = 2     # A+图并发数
    POLL_INTERVAL: int = 3         # 前端轮询间隔(秒)

    def model_post_init(self, __context):
        if not self.DATABASE_URL:
            self.DATA_DIR.mkdir(parents=True, exist_ok=True)
            self.DATABASE_URL = f"sqlite+aiosqlite:///{self.DATA_DIR / 'fbm.db'}"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    def get_llm_client(self) -> AsyncOpenAI:
        """创建LLM OpenAI客户端（处理SSL问题）"""
        return AsyncOpenAI(
            base_url=self.LLM_API_BASE,
            api_key=self.LLM_API_KEY,
            http_client=httpx.AsyncClient(verify=False),
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
        return self.LLM_API_BASE if self.GPT_IMAGE_USE_LLM_API else self.GPT_IMAGE_API_BASE

    @property
    def resolved_gpt_image_api_key(self) -> str:
        """返回Step9实际使用的生图API Key。"""
        return self.LLM_API_KEY if self.GPT_IMAGE_USE_LLM_API else self.GPT_IMAGE_API_KEY

    @property
    def gpt_image_api_provider(self) -> str:
        """返回Step9生图通道名称，便于日志和配置页确认。"""
        return "LLM_API" if self.GPT_IMAGE_USE_LLM_API else "GPT_IMAGE_API"


settings = Settings()
