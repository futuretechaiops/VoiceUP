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
        allow_manual_domain_verification=False,
        widget_signing_key="x" * 40,
    )
    assert ok.oidc_audience == "a"


def test_production_requires_strong_widget_key_and_no_manual_verification() -> None:
    base = {
        "app_env": "production",
        "dev_auth_enabled": False,
        "oidc_issuer": "https://i/",
        "oidc_audience": "a",
        "oidc_jwks_url": "https://i/jwks",
    }
    with pytest.raises(ValidationError):
        Settings(**base, allow_manual_domain_verification=True, widget_signing_key="x" * 40)
    with pytest.raises(ValidationError):
        Settings(**base, allow_manual_domain_verification=False)  # default dev key
