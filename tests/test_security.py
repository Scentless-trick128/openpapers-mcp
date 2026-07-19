"""Unit tests for the URL/SSRF safety guards."""

from __future__ import annotations

import ipaddress

import pytest

from openpapers.security import UnsafeUrlError, _is_blocked_ip, validate_url


def test_is_blocked_ip_recognizes_loopback():
    assert _is_blocked_ip(ipaddress.ip_address("127.0.0.1"))
    assert _is_blocked_ip(ipaddress.ip_address("::1"))


def test_is_blocked_ip_recognizes_rfc1918():
    assert _is_blocked_ip(ipaddress.ip_address("10.0.0.1"))
    assert _is_blocked_ip(ipaddress.ip_address("172.16.0.1"))
    assert _is_blocked_ip(ipaddress.ip_address("192.168.1.1"))


def test_is_blocked_ip_recognizes_link_local():
    # AWS IMDS / cloud metadata range.
    assert _is_blocked_ip(ipaddress.ip_address("169.254.169.254"))


def test_is_blocked_ip_recognizes_cgnat():
    assert _is_blocked_ip(ipaddress.ip_address("100.64.0.1"))


def test_is_blocked_ip_allows_public():
    assert not _is_blocked_ip(ipaddress.ip_address("8.8.8.8"))
    assert not _is_blocked_ip(ipaddress.ip_address("1.1.1.1"))


def test_validate_url_rejects_empty():
    with pytest.raises(UnsafeUrlError, match="non-empty"):
        validate_url("")


def test_validate_url_rejects_file_scheme():
    with pytest.raises(UnsafeUrlError, match="scheme"):
        validate_url("file:///etc/passwd")


def test_validate_url_rejects_ftp_scheme():
    with pytest.raises(UnsafeUrlError, match="scheme"):
        validate_url("ftp://example.org/x")


def test_validate_url_rejects_no_host():
    with pytest.raises(UnsafeUrlError, match="host"):
        validate_url("https:///path-only")


def test_validate_url_rejects_loopback_ip_literal():
    with pytest.raises(UnsafeUrlError, match="blocked"):
        validate_url("http://127.0.0.1:6379/x")


def test_validate_url_rejects_rfc1918_ip_literal():
    with pytest.raises(UnsafeUrlError, match="blocked"):
        validate_url("http://192.168.1.1/admin")


def test_validate_url_rejects_metadata_ip_literal():
    with pytest.raises(UnsafeUrlError, match="blocked"):
        validate_url("http://169.254.169.254/latest/meta-data/")


def test_validate_url_accepts_public_ip_literal():
    url = validate_url("https://1.1.1.1/x")
    assert str(url).startswith("https://1.1.1.1/")


def test_validate_url_resolves_hostname_and_accepts_public(monkeypatch):
    """A hostname that resolves to a public IP is accepted."""
    fake_ips = [ipaddress.ip_address("93.184.216.34")]  # example.com's real IP

    def fake_resolve(host):
        return fake_ips if "example.com" in host else []

    monkeypatch.setattr("openpapers.security._resolve_host_ips", fake_resolve)
    url = validate_url("https://example.com/x")
    assert "example.com" in str(url)


def test_validate_url_rejects_hostname_resolving_to_private(monkeypatch):
    """DNS-rebinding defense: a hostname resolving to private IP is refused."""
    fake_ips = [ipaddress.ip_address("10.0.0.1")]

    def fake_resolve(host):
        return fake_ips

    monkeypatch.setattr("openpapers.security._resolve_host_ips", fake_resolve)
    with pytest.raises(UnsafeUrlError, match="blocked IP"):
        validate_url("https://looks-legit.example/x")


def test_validate_url_rejects_unresolvable_host(monkeypatch):
    monkeypatch.setattr("openpapers.security._resolve_host_ips", lambda host: [])
    with pytest.raises(UnsafeUrlError, match="resolve"):
        validate_url("https://nonexistent.invalid/x")
