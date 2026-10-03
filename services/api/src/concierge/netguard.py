"""Outbound URL safety for the crawler (SSRF defence).

Rules: http/https only, standard ports, host must be on the tenant's allow-list, and every
address the host resolves to must be public. Redirects are re-checked hop by hop by the caller.
Known limit: the check resolves the name and the HTTP client resolves it again, leaving a small
DNS-rebinding window. Crawling a customer's own domain from a locked-down network keeps this
acceptable for the demo; production hardening is connecting to the validated IP (WP3).
"""

import ipaddress
import socket
from urllib.parse import urlsplit


class UnsafeUrl(ValueError):
    pass


def _is_public(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
        or (
            isinstance(ip, ipaddress.IPv6Address)
            and ip.ipv4_mapped is not None
            and not _is_public(ip.ipv4_mapped)
        )
    )


def resolve_all(host: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise UnsafeUrl(f"Cannot resolve {host}") from exc
    return [ipaddress.ip_address(info[4][0]) for info in infos]


def validate_url(url: str, allowed_hosts: set[str], *, allow_private: bool = False) -> str:
    """Return the URL if it is safe to fetch, else raise UnsafeUrl."""
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"}:
        raise UnsafeUrl("Only http and https are allowed")
    host = (parts.hostname or "").lower()
    if not host or host not in allowed_hosts:
        raise UnsafeUrl(f"Host {host or '(none)'} is not on the allow-list")
    if parts.username or parts.password:
        raise UnsafeUrl("Credentials in URLs are not allowed")
    if not allow_private:
        if parts.port not in {None, 80, 443}:
            raise UnsafeUrl("Non-standard port")
        for ip in resolve_all(host):
            if not _is_public(ip):
                raise UnsafeUrl(f"{host} resolves to a non-public address")
    return url


def is_public_host(host: str) -> bool:
    """For browser subresources: allow only hosts that resolve entirely to public addresses."""
    try:
        return all(_is_public(ip) for ip in resolve_all(host))
    except UnsafeUrl:
        return False
