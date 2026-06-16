"""LLM 客户端 — OpenAI 兼容接口封装"""

from openai import OpenAI
from .config import Config


def create_client() -> OpenAI:
    return OpenAI(
        api_key=Config.OPENAI_API_KEY,
        base_url=Config.OPENAI_BASE_URL,
    )


def chat(
    system_prompt: str,
    user_message: str,
    *,
    model: str | None = None,
    temperature: float = 0.3,
    max_tokens: int = 4096,
) -> str:
    """发送 chat completion 请求，返回文本响应"""
    client = create_client()
    response = client.chat.completions.create(
        model=model or Config.LLM_MODEL,
        temperature=temperature,
        max_tokens=max_tokens,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
    )
    return response.choices[0].message.content or ""
