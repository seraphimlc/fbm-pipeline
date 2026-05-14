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

    # GPT Image API (t8star — A+出图)
    GPT_IMAGE_API_BASE: str = "https://ai.t8star.cn/v1"
    GPT_IMAGE_API_KEY: str = ""
    GPT_IMAGE_MODEL: str = "gpt-image-2"

    # 卖家精灵
    SELLERSPRITE_TOKEN: str = ""

    # Chrome 控制
    CHROME_LOCK_TIMEOUT: int = 300  # Chrome串行操作锁超时(秒)

    # Pipeline
    STEP3_4_PARALLEL: bool = True  # Step3/4是否并行
    APLUS_CONCURRENCY: int = 5     # A+图并发数
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


settings = Settings()
