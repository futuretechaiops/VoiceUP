from functools import lru_cache
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

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

    @model_validator(mode="after")
    def validate_auth(self) -> "Settings":
        if self.dev_auth_enabled:
            if self.app_env in {"staging", "production"}:
                raise ValueError("DEV_AUTH_ENABLED must be false outside development/test")
        elif not (self.oidc_issuer and self.oidc_audience and self.oidc_jwks_url):
            raise ValueError("OIDC_ISSUER, OIDC_AUDIENCE and OIDC_JWKS_URL are required")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
