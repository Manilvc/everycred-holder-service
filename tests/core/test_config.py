import pytest

from app.core.config import Settings, get_settings


@pytest.fixture(autouse=True)
def clear_settings_cache() -> None:
    get_settings.cache_clear()


def test_empty_optional_values_mean_not_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Mirrors .env.example, where optional keys are listed as "KEY=".
    monkeypatch.setenv("SOCKET_REDIS_URL", "")
    monkeypatch.setenv("FCM_PROJECT_ID", "")
    monkeypatch.setenv("FCM_SERVICE_ACCOUNT_JSON", "")
    monkeypatch.setenv("AWS_REGION", " ")

    settings = Settings()

    assert settings.socket_redis_url is None
    assert settings.fcm_project_id is None
    assert settings.fcm_service_account_json is None
    assert settings.aws_region is None


def test_set_optional_values_are_kept(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SOCKET_REDIS_URL", "redis://localhost:6379/2")

    settings = Settings()

    assert settings.socket_redis_url is not None
    assert (
        settings.socket_redis_url.get_secret_value()
        == "redis://localhost:6379/2"
    )
