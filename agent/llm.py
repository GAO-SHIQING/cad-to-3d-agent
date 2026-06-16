"""LLM 客户端 — OpenAI 兼容接口封装，支持文本与视觉输入"""

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
    """发送纯文本 chat completion 请求，返回文本响应"""
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


def chat_with_vision(
    system_prompt: str,
    user_message: str,
    image_base64: str,
    *,
    model: str | None = None,
    temperature: float = 0.3,
    max_tokens: int = 4096,
) -> str:
    """发送带单张图片的 chat completion 请求（Vision API），返回文本响应。

    Args:
        system_prompt: 系统提示词
        user_message: 用户文本消息
        image_base64: base64 编码的 PNG 图片数据（不含 data: 前缀）
        model: 模型名称，需支持 vision
        temperature: 采样温度
        max_tokens: 最大输出 token

    Returns:
        LLM 文本响应
    """
    return _chat_with_images(
        system_prompt=system_prompt,
        user_message=user_message,
        images_base64=[image_base64],
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
    )


def chat_with_multiple_images(
    system_prompt: str,
    user_message: str,
    images_base64: list[str],
    *,
    model: str | None = None,
    temperature: float = 0.3,
    max_tokens: int = 4096,
) -> str:
    """发送带多张图片的 chat completion 请求，返回文本响应。

    Args:
        system_prompt: 系统提示词
        user_message: 用户文本消息（可用 [image:N] 引用第 N 张图）
        images_base64: base64 编码的 PNG 图片列表
        model: 模型名称，需支持 vision
        temperature: 采样温度
        max_tokens: 最大输出 token

    Returns:
        LLM 文本响应
    """
    return _chat_with_images(
        system_prompt=system_prompt,
        user_message=user_message,
        images_base64=images_base64,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
    )


def _chat_with_images(
    system_prompt: str,
    user_message: str,
    images_base64: list[str],
    *,
    model: str | None = None,
    temperature: float = 0.3,
    max_tokens: int = 4096,
) -> str:
    """内部：发送带图片的 chat completion 请求。"""
    content: list[dict] = [{"type": "text", "text": user_message}]
    for b64 in images_base64:
        content.append({
            "type": "image_url",
            "image_url": {
                "url": f"data:image/png;base64,{b64}",
                "detail": "high",
            },
        })

    client = create_client()
    response = client.chat.completions.create(
        model=model or Config.LLM_MODEL,
        temperature=temperature,
        max_tokens=max_tokens,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": content},
        ],
    )
    return response.choices[0].message.content or ""
