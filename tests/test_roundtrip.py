"""Round-trip property: parse(to_url(p)) reproduces p for URL-renderable proxies."""

import pytest

from proxy_converter import parse_proxy

ROUNDTRIP_CASES = [
    "socks5://user:pass@1.2.3.4:1080",
    "socks5h://user:pass@1.2.3.4:1080",
    "socks4a://1.2.3.4:1080",
    "http://1.2.3.4:8080",
    "https://user:pass@1.2.3.4:8080",
    "socks5://user:pass@[2001:db8::1]:1080",
    "socks5h://1.2.3.4:1080",
]


@pytest.mark.parametrize("raw", ROUNDTRIP_CASES)
def test_parse_to_url_roundtrip(raw):
    proxy = parse_proxy(raw)
    assert parse_proxy(proxy.to_url()) == proxy


def test_roundtrip_preserves_credentials_verbatim():
    # percent sequences stay literal through parse -> to_url -> parse
    original = parse_proxy("socks5://user:pa%40ss@1.2.3.4:1080")
    restored = parse_proxy(original.to_url())
    assert restored == original
    assert restored.password == "pa%40ss"


# Non-canonical inputs -> assert the exact normalized URL (not a round-trip), so a
# shared bug in both parse and render directions cannot hide.
@pytest.mark.parametrize(
    "raw,expected_url",
    [
        ("1.2.3.4:1080@user:pass", "socks5://user:pass@1.2.3.4:1080"),  # reversed
        ("1.2.3.4:1080:user:pass", "socks5://user:pass@1.2.3.4:1080"),  # proxy-list
        ("user:pass|1.2.3.4:1080", "socks5://user:pass@1.2.3.4:1080"),  # pipe
        ("socks5h://1.2.3.4:1080@user:pass", "socks5h://user:pass@1.2.3.4:1080"),
        ("HTTP://1.2.3.4:8080", "http://1.2.3.4:8080"),  # scheme case
    ],
)
def test_non_canonical_normalizes_to_expected_url(raw, expected_url):
    # default_scheme covers the schemeless rows; schemed rows ignore it.
    assert parse_proxy(raw, default_scheme="socks5").to_url() == expected_url
