import json
from pathlib import Path

import pytest
from pydantic import ValidationError

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


SERVICE_ACCOUNT = {"type": "service_account", "project_id": "example"}


def test_fcm_key_path_in_the_json_setting_is_rejected_at_startup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FCM_PROJECT_ID", "example")
    monkeypatch.setenv(
        "FCM_SERVICE_ACCOUNT_JSON", "/etc/everycred/secrets/firebase-sa.json"
    )

    with pytest.raises(ValidationError, match="FCM_SERVICE_ACCOUNT_FILE"):
        Settings()


def test_fcm_key_is_read_from_the_json_setting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FCM_PROJECT_ID", "example")
    monkeypatch.setenv("FCM_SERVICE_ACCOUNT_JSON", json.dumps(SERVICE_ACCOUNT))

    assert Settings().fcm_service_account_info() == SERVICE_ACCOUNT


def test_fcm_key_is_read_from_the_file_setting(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    key_file = tmp_path / "firebase-sa.json"
    key_file.write_text(json.dumps(SERVICE_ACCOUNT), encoding="utf-8")
    monkeypatch.setenv("FCM_PROJECT_ID", "example")
    monkeypatch.setenv("FCM_SERVICE_ACCOUNT_FILE", str(key_file))

    assert Settings().fcm_service_account_info() == SERVICE_ACCOUNT


def test_unmounted_fcm_key_file_names_the_problem(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("FCM_PROJECT_ID", "example")
    monkeypatch.setenv(
        "FCM_SERVICE_ACCOUNT_FILE", str(tmp_path / "missing.json")
    )
    settings = Settings()

    with pytest.raises(ValueError, match="mount the key file"):
        settings.fcm_service_account_info()


@pytest.mark.parametrize(
    ("variables", "message"),
    [
        (
            {
                "FCM_PROJECT_ID": "example",
                "FCM_SERVICE_ACCOUNT_JSON": json.dumps(SERVICE_ACCOUNT),
                "FCM_SERVICE_ACCOUNT_FILE": "/run/secrets/firebase-sa.json",
            },
            "not both",
        ),
        ({"FCM_PROJECT_ID": "example"}, "FCM_PROJECT_ID needs"),
        (
            {"FCM_SERVICE_ACCOUNT_FILE": "/run/secrets/firebase-sa.json"},
            "needs FCM_PROJECT_ID",
        ),
    ],
)
def test_incomplete_fcm_settings_are_rejected(
    monkeypatch: pytest.MonkeyPatch, variables: dict[str, str], message: str
) -> None:
    for name, value in variables.items():
        monkeypatch.setenv(name, value)

    with pytest.raises(ValidationError, match=message):
        Settings()
