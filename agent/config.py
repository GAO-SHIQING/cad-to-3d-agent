"""Agent 配置管理 — 从环境变量读取"""

import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    OPENAI_BASE_URL: str = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    LLM_MODEL: str = os.getenv("LLM_MODEL", "gpt-5.5")
    BLENDER_EXECUTABLE: str = os.getenv("BLENDER_EXECUTABLE", "blender")
    MCP_HOST: str = os.getenv("MCP_HOST", "localhost")
    MCP_PORT: int = int(os.getenv("MCP_PORT", "9876"))
    MAX_REVISIONS: int = 3
    QUALITY_THRESHOLD: float = 70.0   # 质量达标线 (0-100)，超过此值视为通过
    OUTPUT_DIR: str = os.getenv("OUTPUT_DIR", "./output")
    # MCP 连接失败时是否自动启动 Blender (加载 MCP Add-on)
    MCP_AUTO_LAUNCH: bool = os.getenv("MCP_AUTO_LAUNCH", "true").lower() in ("1", "true", "yes")
    # 等待 Blender MCP 端口就绪的超时时间 (秒)
    MCP_LAUNCH_TIMEOUT: float = float(os.getenv("MCP_LAUNCH_TIMEOUT", "30"))
    # MCP + 自动启动均失败时是否回退到 Background (subprocess) 模式
    FALLBACK_TO_BACKGROUND: bool = os.getenv("FALLBACK_TO_BACKGROUND", "true").lower() in ("1", "true", "yes")

    @classmethod
    def validate(cls) -> list[str]:
        errors = []
        if not cls.OPENAI_API_KEY:
            errors.append("OPENAI_API_KEY 未设置，请在 .env 中配置")
        return errors
