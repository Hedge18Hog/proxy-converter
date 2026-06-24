"""Tests for `ProxyInfo`: validation, computed properties, rendering, immutability."""

import dataclasses

import pytest

from proxy_converter import ProxyInfo, ProxyParseError, parse_proxy


class TestPostInitValidation:
    def test_valid_object(self):
        proxy = ProxyInfo("socks5", "1.2.3.4", 1080, "user", "pass", True)
        assert proxy.scheme == "socks5h"

    def test_bad_proxy_type(self):
        with pytest.raises(ProxyParseError):
            ProxyInfo("ftp", "1.2.3.4", 1080, None, None, False)

    @pytest.mark.parametrize("port", [0, -1, 65536, 100000])
    def test_port_out_of_range(self, port):
        with pytest.raises(ProxyParseError):
            ProxyInfo("socks5", "1.2.3.4", port, None, None, False)

    def test_empty_host(self):
        with pytest.raises(ProxyParseError):
            ProxyInfo("socks5", "", 1080, None, None, False)

    def test_username_without_password(self):
        with pytest.raises(ProxyParseError):
            ProxyInfo("socks5", "1.2.3.4", 1080, "user", None, False)

    def test_password_without_username(self):
        with pytest.raises(ProxyParseError):
            ProxyInfo("socks5", "1.2.3.4", 1080, None, "pass", False)

    def test_rdns_only_for_socks(self):
        with pytest.raises(ProxyParseError):
            ProxyInfo("http", "1.2.3.4", 1080, None, None, True)


class TestProperties:
    @pytest.mark.parametrize(
        "ptype,rdns,scheme",
        [
            ("socks5", False, "socks5"),
            ("socks5", True, "socks5h"),
            ("socks4", False, "socks4"),
            ("socks4", True, "socks4a"),
            ("http", False, "http"),
            ("https", False, "https"),
        ],
    )
    def test_scheme(self, ptype, rdns, scheme):
        proxy = ProxyInfo(ptype, "1.2.3.4", 1080, None, None, rdns)
        assert proxy.scheme == scheme

    def test_auth_present(self):
        proxy = ProxyInfo("socks5", "1.2.3.4", 1080, "user", "pass", False)
        assert proxy.auth == ("user", "pass")

    def test_auth_absent(self):
        proxy = ProxyInfo("socks5", "1.2.3.4", 1080, None, None, False)
        assert proxy.auth is None


class TestRendering:
    def test_to_url_with_auth(self):
        proxy = parse_proxy("socks5h://user:pass@1.2.3.4:1080")
        assert proxy.to_url() == "socks5h://user:pass@1.2.3.4:1080"

    def test_to_url_without_auth(self):
        proxy = parse_proxy("socks5h://user:pass@1.2.3.4:1080")
        assert proxy.to_url(auth=False) == "socks5h://1.2.3.4:1080"

    def test_to_url_emits_credentials_verbatim(self):
        proxy = ProxyInfo("socks5", "1.2.3.4", 1080, "user", "p4ss", False)
        assert proxy.to_url() == "socks5://user:p4ss@1.2.3.4:1080"
        # a '%' in the password is kept literally, never encoded
        raw = ProxyInfo("socks5", "1.2.3.4", 1080, "user", "pa%40ss", False)
        assert raw.to_url() == "socks5://user:pa%40ss@1.2.3.4:1080"

    def test_to_url_brackets_ipv6(self):
        proxy = ProxyInfo("socks5", "2001:db8::1", 1080, None, None, False)
        assert proxy.to_url() == "socks5://[2001:db8::1]:1080"

    def test_str_masks_password(self):
        proxy = parse_proxy("socks5h://user:supersecret@1.2.3.4:1080")
        assert str(proxy) == "socks5h://user:***@1.2.3.4:1080"
        assert "supersecret" not in str(proxy)

    def test_repr_masks_password(self):
        proxy = parse_proxy("socks5://user:supersecret@1.2.3.4:1080")
        assert "supersecret" not in repr(proxy)
        assert "password='***'" in repr(proxy)

    def test_repr_no_creds_shows_none(self):
        proxy = parse_proxy("1.2.3.4:1080", default_scheme="socks5")
        assert "password=None" in repr(proxy)


class TestImmutability:
    def test_frozen(self):
        proxy = parse_proxy("1.2.3.4:1080", default_scheme="socks5")
        with pytest.raises(dataclasses.FrozenInstanceError):
            proxy.host = "9.9.9.9"

    def test_replace_makes_new_object(self):
        proxy = parse_proxy("socks5h://user:pass@1.2.3.4:1080")
        other = dataclasses.replace(proxy, host="9.9.9.9")
        assert other.host == "9.9.9.9"
        assert other.to_url() == "socks5h://user:pass@9.9.9.9:1080"
        assert proxy.host == "1.2.3.4"  # original untouched

    def test_replace_revalidates(self):
        proxy = parse_proxy("1.2.3.4:1080", default_scheme="socks5")
        with pytest.raises(ProxyParseError):
            dataclasses.replace(proxy, port=99999)

    def test_hashable(self):
        # frozen dataclass is hashable -> usable in sets / as dict keys
        proxy = parse_proxy("1.2.3.4:1080", default_scheme="socks5")
        assert proxy in {proxy}
