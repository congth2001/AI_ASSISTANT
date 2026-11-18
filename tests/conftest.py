"""API tests use validated synthetic settings instead of the developer's local secrets."""
import pytest

from config.settings import AuthSettings, LLMSettings, Settings


@pytest.fixture(autouse=True)
def isolated_app_settings(monkeypatch):
    import main

    # Construct only the outer settings container to avoid loading process/dotenv sources.
    # All nested models are validated; remaining nested models use their validated defaults.
    settings = Settings.model_construct(
        llm=LLMSettings(openai_api_key="synthetic-test-api-key"),
        auth=AuthSettings(jwt_secret="synthetic-test-secret-with-at-least-thirty-two-characters"),
    )
    monkeypatch.setattr(main, "get_settings", lambda: settings)
