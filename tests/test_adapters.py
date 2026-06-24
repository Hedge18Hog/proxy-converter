"""Tests for the per-library adapter methods.

The SOCKS/aiohttp adapters lazily import their target library; those tests use
`importorskip` so the suite still runs when the optional libs are absent.
"""

import asyncio
import sys

import pytest

from proxy_converter import ProxyParseError, parse_proxy


class TestToRequests:
    def test_structure(self):
        proxy = parse_proxy("socks5h://user:pass@1.2.3.4:1080")
        url = "socks5h://user:pass@1.2.3.4:1080"
        assert proxy.to_requests() == {"http": url, "https": url}

    def test_no_credentials(self):
        proxy = parse_proxy("http://1.2.3.4:8080")
        assert proxy.to_requests() == {
            "http": "http://1.2.3.4:8080",
            "https": "http://1.2.3.4:8080",
        }


class TestToNativeAiohttp:
    def test_socks_raises(self):
        proxy = parse_proxy("socks5://1.2.3.4:1080")
        with pytest.raises(ProxyParseError, match="to_aiohttp_socks"):
            proxy.to_native_aiohttp()

    def test_http_no_creds_needs_no_aiohttp(self):
        proxy = parse_proxy("http://1.2.3.4:8080")
        result = proxy.to_native_aiohttp()
        assert result == {"proxy": "http://1.2.3.4:8080", "proxy_auth": None}

    # aiohttp 4.0-pre deprecates BasicAuth itself; proxy_auth=BasicAuth is still
    # the supported API for aiohttp's native proxy auth, so we keep it and just
    # silence aiohttp's own deprecation here. Revisit when aiohttp 4.0 lands.
    @pytest.mark.filterwarnings("ignore:BasicAuth is deprecated:DeprecationWarning")
    def test_http_with_creds_builds_basic_auth(self):
        aiohttp = pytest.importorskip("aiohttp")
        proxy = parse_proxy("http://user:pass@1.2.3.4:8080")
        result = proxy.to_native_aiohttp()
        assert result["proxy"] == "http://1.2.3.4:8080"
        assert result["proxy_auth"] == aiohttp.BasicAuth("user", "pass")


class TestToPythonSocksKwargs:
    def test_socks5h_maps_to_base_type_plus_rdns(self):
        ps = pytest.importorskip("python_socks")
        kwargs = parse_proxy("socks5h://user:pass@1.2.3.4:1080").to_python_socks_kwargs()
        assert kwargs == {
            "proxy_type": ps.ProxyType.SOCKS5,
            "host": "1.2.3.4",
            "port": 1080,
            "username": "user",
            "password": "pass",
            "rdns": True,
        }

    def test_socks4a(self):
        ps = pytest.importorskip("python_socks")
        kwargs = parse_proxy("socks4a://1.2.3.4:1080").to_python_socks_kwargs()
        assert kwargs["proxy_type"] == ps.ProxyType.SOCKS4
        assert kwargs["rdns"] is True

    def test_https_maps_to_http_type(self):
        ps = pytest.importorskip("python_socks")
        kwargs = parse_proxy("https://1.2.3.4:8080").to_python_socks_kwargs()
        assert kwargs["proxy_type"] == ps.ProxyType.HTTP

    def test_https_with_credentials(self):
        ps = pytest.importorskip("python_socks")
        kwargs = parse_proxy("https://user:pass@1.2.3.4:8080").to_python_socks_kwargs()
        assert kwargs["proxy_type"] == ps.ProxyType.HTTP
        assert kwargs["username"] == "user"
        assert kwargs["password"] == "pass"
        assert kwargs["rdns"] is False


class TestAdaptersWhenLibraryAbsent:
    """The lazy adapters must raise a clear ProxyParseError if the lib is missing."""

    def test_aiohttp_socks_missing(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "aiohttp_socks", None)
        proxy = parse_proxy("socks5h://1.2.3.4:1080")
        with pytest.raises(ProxyParseError, match="aiohttp_socks"):
            proxy.to_aiohttp_socks()

    def test_python_socks_missing(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "python_socks", None)
        proxy = parse_proxy("socks5h://1.2.3.4:1080")
        with pytest.raises(ProxyParseError, match="python_socks"):
            proxy.to_python_socks_kwargs()

    def test_native_aiohttp_missing_for_credentialed_http(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "aiohttp", None)
        proxy = parse_proxy("http://user:pass@1.2.3.4:8080")
        with pytest.raises(ProxyParseError, match="aiohttp"):
            proxy.to_native_aiohttp()


class TestToAiohttpSocks:
    @staticmethod
    def _build_and_close(proxy):
        # aiohttp connectors want a running loop; build and close inside one.
        async def run():
            connector = proxy.to_aiohttp_socks()
            await connector.close()
            return connector

        return asyncio.run(run())

    def test_returns_proxy_connector(self):
        aiohttp_socks = pytest.importorskip("aiohttp_socks")
        proxy = parse_proxy("socks5h://user:pass@1.2.3.4:1080")
        connector = self._build_and_close(proxy)
        assert isinstance(connector, aiohttp_socks.ProxyConnector)

    def test_works_for_http_proxy_too(self):
        aiohttp_socks = pytest.importorskip("aiohttp_socks")
        proxy = parse_proxy("http://1.2.3.4:8080")
        connector = self._build_and_close(proxy)
        assert isinstance(connector, aiohttp_socks.ProxyConnector)
