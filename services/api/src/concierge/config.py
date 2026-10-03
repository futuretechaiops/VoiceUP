from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Read the repo-root .env regardless of the directory a command is run from.
    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[4] / ".env", extra="ignore"
    )

    app_env: Literal["development", "test", "staging", "production"] = "development"
    # Runtime connection: must use the unprivileged ``concierge_app`` role.
    database_url: str = "postgresql+psycopg://concierge_app:concierge_app@localhost:5432/concierge"
    # Migration connection: the owning role. Only Alembic uses it.
    migration_database_url: str | None = None

    dev_auth_enabled: bool = True
    dev_auth_secret: str = "local-development-only"  # noqa: S105 - local adapter only

    oidc_issuer: str | None = None
    oidc_audience: str | None = None
    oidc_jwks_url: str | None = None

    log_level: str = "INFO"

    # Signs short-lived visitor session tokens. Must be set to a strong secret outside dev/test.
    widget_signing_key: str = "dev-only-widget-signing-key-change-me-0123456789"
    widget_session_minutes: int = 30
    # Until DNS verification ships (WP3), domains can be verified by an administrator in dev only.
    allow_manual_domain_verification: bool = True
    widget_rate_per_minute: int = 30

    @model_validator(mode="after")
    def validate_auth(self) -> "Settings":
        if self.app_env in {"staging", "production"}:
            if self.dev_auth_enabled:
                raise ValueError("DEV_AUTH_ENABLED must be false outside development/test")
            if self.allow_manual_domain_verification:
                raise ValueError("ALLOW_MANUAL_DOMAIN_VERIFICATION must be false in production")
            if self.widget_signing_key.startswith("dev-only") or len(self.widget_signing_key) < 32:
                raise ValueError("WIDGET_SIGNING_KEY must be a strong secret in production")
        if not self.dev_auth_enabled and not (
            self.oidc_issuer and self.oidc_audience and self.oidc_jwks_url
        ):
            raise ValueError("OIDC_ISSUER, OIDC_AUDIENCE and OIDC_JWKS_URL are required")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
