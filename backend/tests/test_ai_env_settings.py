from app.core.settings import Settings


def test_ai_provider_secrets_and_metadata_load_from_environment(monkeypatch) -> None:
    monkeypatch.setenv("LAB_AI_PROVIDER", "deepseek")
    monkeypatch.setenv("LAB_AI_MODEL", "deepseek-flash")
    monkeypatch.setenv("LAB_AI_API_KEY", "local-chat-test-key")
    monkeypatch.setenv("LAB_AI_EMBEDDING_API_KEY", "local-embedding-test-key")
    monkeypatch.setenv("LAB_AI_MINERU_API_KEY", "local-mineru-test-key")
    monkeypatch.setenv("LAB_AI_USER_DAILY_TOKEN_CAP", "1234")

    settings = Settings(_env_file=None)

    assert settings.ai_provider == "deepseek"
    assert settings.ai_model == "deepseek-flash"
    assert settings.ai_api_key == "local-chat-test-key"
    assert settings.ai_embedding_api_key == "local-embedding-test-key"
    assert settings.ai_mineru_api_key == "local-mineru-test-key"
    assert settings.ai_user_daily_token_cap == 1234
