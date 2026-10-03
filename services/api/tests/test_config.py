import pytest
from pydantic import ValidationError

from concierge.config import Settings


def test_dev_auth_refused_in_production() -> None:
    with pytest.raises(ValidationError):
        Settings(app_env="production", dev_auth_enabled=True)


def test_oidc_settings_required_when_dev_auth_off() -> None:
    with pytest.raises(ValidationError):
        Settings(app_env="production", dev_auth_enabled=False)
    ok = Settings(
        app_env="production",
        dev_auth_enabled=False,
        oidc_issuer="https://i/",
        oidc_audience="a",
        oidc_jwks_url="https://i/jwks",
    )
    assert ok.oidc_audience == "a"
