from genppt.llm import config_from_env, qwen_config_from_env


def test_config_from_env_prefers_deepseek(monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-key")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key")
    monkeypatch.delenv("QWEN_BASE_URL", raising=False)
    monkeypatch.delenv("QWEN_MODEL", raising=False)

    config = config_from_env()

    assert config.provider == "deepseek"
    assert config.api_key == "deepseek-key"
    assert config.base_url == "https://api.deepseek.com/v1"
    assert config.model == "deepseek-chat"


def test_qwen_config_from_env_reads_dashscope(monkeypatch) -> None:
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("QWEN_BASE_URL", raising=False)
    monkeypatch.delenv("QWEN_MODEL", raising=False)

    config = qwen_config_from_env()

    assert config.provider == "qwen"
    assert config.api_key == "test-key"
    assert config.base_url == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    assert config.model == "qwen-plus"
