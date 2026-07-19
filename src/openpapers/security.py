"""URL & SSRF safety guards for user-supplied download targets.

`download_pdf` accepts an arbitrary URL from the caller (typically the LLM,
which gets it from Unpaywall's `url_for_pdf`). That URL is untrusted input:
it could point at internal services, cloud metadata endpoints, or private
IPs. This module validates URLs before any bytes are fetched.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

import httpx


class UnsafeUrlError(ValueError):
    """Raised when a URL would result in an unsafe request."""


# Schemes we are willing to fetch. httpx already rejects others, but we
# enforce explicitly for defense in depth.
_ALLOWED_SCHEMES = {"http", "https"}

# Networks we will never contact. Anything ip_address(...).is_global returns
# True for is acceptable; everything else is blocked.
#
# Note: is_global already covers loopback, RFC1918, RFC4193 (ULA), link-local
# (169.254/16), CGNAT (100.64/10), multicast, documentation ranges, etc. We
# list them explicitly only to make the policy readable.
_BLOCKED_NETWORK_NAMES = (
    "loopback",
    "private",
    "link_local",
    "reserved",
    "multicast",
    "unspecified",
)


def _is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """True if the IP is in any network we refuse to contact."""
    # is_global is False for all the categories we care about.
    return (not ip.is_global) or ip.is_loopback or ip.is_link_local or ip.is_multicast


def _resolve_host_ips(host: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    """Resolve a hostname to a list of IP addresses. Returns [] on failure."""
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return []
    ips: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    for _family, _, _, _, sockaddr in infos:
        try:
            ip = ipaddress.ip_address(sockaddr[0])
        except (ValueError, IndexError):
            continue
        ips.append(ip)
    return ips


def validate_url(url: str) -> httpx.URL:
    """Validate that `url` is safe to fetch.

    Checks:
      - scheme is http or https
      - host is present
      - host (or all resolved IPs for a hostname) is in a public network

    Raises UnsafeUrlError on any rejection. Returns the parsed httpx.URL on
    success.
    """
    if not url or not url.strip():
        raise UnsafeUrlError("URL must be a non-empty string.")

    parsed = urlparse(url.strip())
    if parsed.scheme.lower() not in _ALLOWED_SCHEMES:
        raise UnsafeUrlError(
            f"Refusing URL with scheme {parsed.scheme!r}; only http/https allowed."
        )
    host = parsed.hostname
    if not host:
        raise UnsafeUrlError(f"URL has no host: {url!r}")

    # If host is already an IP literal, check it directly.
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None

    if ip is not None:
        if _is_blocked_ip(ip):
            raise UnsafeUrlError(f"Refusing to fetch IP in blocked network: {ip}")
    else:
        ips = _resolve_host_ips(host)
        if not ips:
            raise UnsafeUrlError(f"Could not resolve host {host!r}.")
        # Every resolved address must be public. If any resolves to a
        # private IP, refuse — DNS-rebinding attacks rely on mixed answers.
        for resolved in ips:
            if _is_blocked_ip(resolved):
                raise UnsafeUrlError(f"Refusing host {host!r}: resolves to blocked IP {resolved}.")

    return httpx.URL(url)
