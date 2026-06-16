"""Agent 配置管理 — 从环境变量读取"""

import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    OPENAI_BASE_URL: str = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    LLM_MODEL: str = os.getenv("LLM_MODEL", "gpt-5.5")
    BLENDER_EXECUTABLE: str = os.getenv("BLENDER_EXECUTABLE", "blender")
    MAX_REVISIONS: int = 3
    OUTPUT_DIR: str = os.getenv("OUTPUT_DIR", "./output")

    @classmethod
    def validate(cls) -> list[str]:
        errors = []
        if not cls.OPENAI_API_KEY:
            errors.append("OPENAI_API_KEY 未设置，请在 .env 中配置")
        return errors
