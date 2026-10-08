from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.scamflow.settings import Environment, LogLevel, Settings


@pytest.fixture(autouse=True)
def clear_scamflow_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("SCAMFLOW_ENVIRONMENT", "SCAMFLOW_LOG_LEVEL", "SCAMFLOW_SECURE_COOKIES"):
        monkeypatch.delenv(name, raising=False)


def test_settings_defaults() -> None:
    settings = Settings()

    assert settings.environment is Environment.DEVELOPMENT
    assert settings.log_level is LogLevel.INFO


def test_settings_environment_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SCAMFLOW_ENVIRONMENT", "test")
    monkeypatch.setenv("SCAMFLOW_LOG_LEVEL", "DEBUG")

    settings = Settings()

    assert settings.environment is Environment.TEST
    assert settings.log_level is LogLevel.DEBUG


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("SCAMFLOW_ENVIRONMENT", "staging"),
        ("SCAMFLOW_LOG_LEVEL", "TRACE"),
    ],
)
def test_invalid_configuration_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    value: str,
) -> None:
    monkeypatch.setenv(name, value)

    with pytest.raises(ValidationError):
        Settings()


def test_settings_do_not_leak_between_instances(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SCAMFLOW_LOG_LEVEL", "DEBUG")
    overridden = Settings()

    monkeypatch.delenv("SCAMFLOW_LOG_LEVEL")
    defaults = Settings()

    assert overridden.log_level is LogLevel.DEBUG
    assert defaults.log_level is LogLevel.INFO


def test_local_dotenv_file_is_not_loaded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / ".env").write_text(
        "SCAMFLOW_ENVIRONMENT=production\nSCAMFLOW_LOG_LEVEL=ERROR\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    settings = Settings()

    assert settings.environment is Environment.DEVELOPMENT
    assert settings.log_level is LogLevel.INFO


def test_https_development_host_can_explicitly_require_secure_cookie(tmp_path: Path) -> None:
    settings = Settings(
        environment=Environment.DEVELOPMENT,
        database_path=tmp_path / "hosted-dev.sqlite3",
        trusted_origin="https://example.up.railway.app",
        secure_cookies=True,
    )

    assert settings.session_cookie_secure is True
