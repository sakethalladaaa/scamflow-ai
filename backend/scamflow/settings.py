"""Validated application settings for ScamFlow AI."""

from enum import StrEnum
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(StrEnum):
    """Supported runtime environments."""

    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


class LogLevel(StrEnum):
    """Supported application log levels."""

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


class Settings(BaseSettings):
    """Application settings loaded from SCAMFLOW_* environment variables.

    Local .env files are intentionally not loaded automatically. This keeps
    tests and application startup independent from developer-specific files.
    """

    model_config = SettingsConfigDict(
        env_prefix="SCAMFLOW_",
        env_file=None,
        case_sensitive=False,
        extra="ignore",
    )

    environment: Environment = Environment.DEVELOPMENT
    log_level: LogLevel = LogLevel.INFO

    database_path: Path = Path("data/scamflow.sqlite3")
    sqlite_busy_timeout_ms: int = Field(default=5_000, ge=1, le=60_000)

    session_ttl_seconds: int = Field(default=86_400, ge=60, le=604_800)
    case_retention_seconds: int = Field(default=86_400, ge=60, le=604_800)
    assessment_timeout_seconds: float = Field(default=2.0, ge=0.01, le=30.0)

    trusted_origin: str = "http://127.0.0.1:8000"
    secure_cookies: bool | None = None

    @field_validator("trusted_origin")
    @classmethod
    def validate_trusted_origin(cls, value: str) -> str:
        """Require one exact HTTP(S) origin without path, query, or fragment."""

        normalized = value.rstrip("/")
        parsed = urlsplit(normalized)

        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
            or parsed.username
            or parsed.password
        ):
            raise ValueError("trusted_origin must be a single HTTP(S) origin")

        return normalized

    @model_validator(mode="after")
    def validate_production_security(self) -> "Settings":
        """Require HTTPS browser origin in production."""

        if self.environment is Environment.PRODUCTION and not self.trusted_origin.startswith(
            "https://"
        ):
            raise ValueError("production trusted_origin must use HTTPS")
        return self

    @property
    def session_cookie_secure(self) -> bool:
        """Require Secure cookies in production, with an explicit HTTPS dev override."""

        if self.environment is Environment.PRODUCTION:
            return True
        return bool(self.secure_cookies)
