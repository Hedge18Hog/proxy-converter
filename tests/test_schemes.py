"""Tests for the scheme table helpers in `proxy_converter.schemes`."""

import pytest

from proxy_converter.errors import ProxyParseError
from proxy_converter.schemes import compose_scheme, resolve_scheme


@pytest.mark.parametrize(
    "scheme,expected",
    [
        ("http", ("http", False)),
        ("https", ("https", False)),
        ("socks4", ("socks4", False)),
        ("socks5", ("socks5", False)),
        ("socks4a", ("socks4", True)),
        ("socks5h", ("socks5", True)),
        ("SOCKS5H", ("socks5", True)),  # case-insensitive
    ],
)
def test_resolve_scheme(scheme, expected):
    assert resolve_scheme(scheme) == expected


def test_resolve_scheme_rejects_unknown():
    with pytest.raises(ProxyParseError):
        resolve_scheme("ftp")


@pytest.mark.parametrize(
    "ptype,rdns,expected",
    [
        ("socks5", True, "socks5h"),
        ("socks4", True, "socks4a"),
        ("socks5", False, "socks5"),
        ("http", False, "http"),
        ("https", False, "https"),
    ],
)
def test_compose_scheme(ptype, rdns, expected):
    assert compose_scheme(ptype, rdns) == expected


@pytest.mark.parametrize("scheme", ["socks5h", "socks4a", "http", "socks5"])
def test_resolve_compose_are_inverse(scheme):
    proxy_type, rdns = resolve_scheme(scheme)
    assert compose_scheme(proxy_type, rdns) == scheme
