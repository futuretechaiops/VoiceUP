import pytest

from concierge.origins import normalise_hostname, origin_allowed
from concierge.ratelimit import RateLimiter


@pytest.mark.parametrize(
    "bad", ["https://example.com", "example.com/path", "*.example.com", "", "a b"]
)
def test_hostname_rejects_non_hostnames(bad: str) -> None:
    with pytest.raises(ValueError):
        normalise_hostname(bad)


def test_hostname_is_lowercased() -> None:
    assert normalise_hostname("WWW.Example.CO.UK") == "www.example.co.uk"


@pytest.mark.parametrize(
    ("origin", "expected"),
    [
        ("https://www.acme.co.uk", True),
        ("https://acme.co.uk", False),  # no implied subdomains or apex
        ("https://evil.www.acme.co.uk", False),
        ("https://www.acme.co.uk.evil.com", False),
        ("http://www.acme.co.uk", False),  # production requires https
        ("null", False),
        (None, False),
    ],
)
def test_production_origin_matching(origin: str | None, expected: bool) -> None:
    assert origin_allowed(origin, ["www.acme.co.uk"], production=True) is expected


def test_local_development_allows_any_port_and_http() -> None:
    assert origin_allowed("http://localhost:8080", ["localhost"], production=False)
    assert origin_allowed("http://localhost:8080", ["localhost:8080"], production=False)
    assert not origin_allowed("http://localhost:8081", ["localhost:8080"], production=False)


def test_rate_limiter_blocks_after_limit() -> None:
    limiter = RateLimiter(limit=2)
    assert limiter.allow("a") and limiter.allow("a") and not limiter.allow("a")
    assert limiter.allow("b")
