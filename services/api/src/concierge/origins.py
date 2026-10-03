"""Origin and hostname rules for embedding and CORS."""

import re
from urllib.parse import urlsplit

_HOST = re.compile(
    r"^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)*(:\d{1,5})?$"
)
LOCAL_HOSTS = {"localhost", "127.0.0.1"}


def normalise_hostname(value: str) -> str:
    """Lower-case host (optionally with port). Rejects schemes, paths and wildcards."""
    host = value.strip().lower()
    if not _HOST.match(host):
        raise ValueError("Enter a bare hostname such as www.example.co.uk (no https://, path or *)")
    return host


def parse_origin(origin: str | None) -> tuple[str, str] | None:
    """Return (scheme, host[:port]) for a browser Origin header, else None."""
    if not origin or origin == "null":
        return None
    parts = urlsplit(origin)
    if parts.scheme not in {"http", "https"} or not parts.hostname or parts.path not in {"", "/"}:
        return None
    host = parts.hostname.lower()
    netloc = f"{host}:{parts.port}" if parts.port else host
    return parts.scheme, netloc


def origin_allowed(origin: str | None, hostnames: list[str], *, production: bool) -> bool:
    """Exact host match (a bare entry also matches that host on any port in non-production).

    Subdomains are never implied; list each hostname explicitly. In production only https
    is accepted, except for localhost.
    """
    parsed = parse_origin(origin)
    if parsed is None:
        return False
    scheme, netloc = parsed
    host = netloc.split(":")[0]
    if production and scheme != "https" and host not in LOCAL_HOSTS:
        return False
    for entry in hostnames:
        if netloc == entry:
            return True
        if not production and ":" not in entry and host == entry:
            return True
    return False
