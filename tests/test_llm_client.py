"""测试 LLM 客户端配置。"""


def test_create_client_uses_configured_timeout(monkeypatch):
    from agent.config import Config
    import agent.llm as llm

    captured = {}

    class FakeOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(llm, "OpenAI", FakeOpenAI)
    monkeypatch.setattr(Config, "OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(Config, "OPENAI_BASE_URL", "https://example.test/v1")
    monkeypatch.setattr(Config, "LLM_TIMEOUT", 12.5)

    llm.create_client()

    assert captured["timeout"] == 12.5
