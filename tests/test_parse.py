"""Tests for `parse_proxy`: the format matrix, schemes, IPv6, and dispatch."""

import pytest

from proxy_converter import ProxyParseError, parse_proxy

# (input, proxy_type, host, port, username, password, rdns)
FORMATS = [
    (
        "socks5://user:pass@1.2.3.4:1080",
        "socks5",
        "1.2.3.4",
        1080,
        "user",
        "pass",
        False,
    ),
    (
        "socks5://1.2.3.4:1080@user:pass",
        "socks5",
        "1.2.3.4",
        1080,
        "user",
        "pass",
        False,
    ),
    ("http://1.2.3.4:8080", "http", "1.2.3.4", 8080, None, None, False),
    ("http://1.2.3.4:1080:user:pass", "http", "1.2.3.4", 1080, "user", "pass", False),
    ("user:pass@1.2.3.4:1080", "socks5", "1.2.3.4", 1080, "user", "pass", False),
    ("1.2.3.4:1080@user:pass", "socks5", "1.2.3.4", 1080, "user", "pass", False),
    ("1.2.3.4:1080", "socks5", "1.2.3.4", 1080, None, None, False),
    ("1.2.3.4:1080:user:pass", "socks5", "1.2.3.4", 1080, "user", "pass", False),
    # pipe alias (9-11)
    (
        "socks5://user:pass|1.2.3.4:1080",
        "socks5",
        "1.2.3.4",
        1080,
        "user",
        "pass",
        False,
    ),
    ("user:pass|1.2.3.4:1080", "socks5", "1.2.3.4", 1080, "user", "pass", False),
    ("1.2.3.4:1080|user:pass", "socks5", "1.2.3.4", 1080, "user", "pass", False),
]


@pytest.mark.parametrize("raw,ptype,host,port,user,pw,rdns", FORMATS)
def test_all_formats(raw, ptype, host, port, user, pw, rdns):
    # default_scheme only affects the schemeless rows; schemed rows ignore it.
    proxy = parse_proxy(raw, default_scheme="socks5")
    assert (proxy.proxy_type, proxy.host, proxy.port) == (ptype, host, port)
    assert (proxy.username, proxy.password, proxy.rdns) == (user, pw, rdns)


@pytest.mark.parametrize(
    "scheme,ptype,rdns,full",
    [
        ("http", "http", False, "http"),
        ("https", "https", False, "https"),
        ("socks4", "socks4", False, "socks4"),
        ("socks5", "socks5", False, "socks5"),
        ("socks4a", "socks4", True, "socks4a"),
        ("socks5h", "socks5", True, "socks5h"),
        ("SOCKS5H", "socks5", True, "socks5h"),  # case-insensitive
    ],
)
def test_scheme_resolution(scheme, ptype, rdns, full):
    proxy = parse_proxy(f"{scheme}://1.2.3.4:1080")
    assert proxy.proxy_type == ptype
    assert proxy.rdns is rdns
    assert proxy.scheme == full


def test_schemeless_without_default_raises():
    # the protocol can't be guessed from host:port -> explicit error, no silent default
    with pytest.raises(ProxyParseError, match="no scheme"):
        parse_proxy("1.2.3.4:1080")


def test_default_scheme_applied():
    assert parse_proxy("1.2.3.4:1080", default_scheme="http").proxy_type == "http"
    assert parse_proxy("1.2.3.4:1080", default_scheme="socks5").proxy_type == "socks5"
    assert parse_proxy("1.2.3.4:1080", default_scheme="socks5h").rdns is True


def test_explicit_scheme_overrides_default():
    proxy = parse_proxy("http://1.2.3.4:1080", default_scheme="socks5")
    assert proxy.proxy_type == "http"


def test_pipe_equals_at():
    assert parse_proxy(
        "user:pass|1.2.3.4:1080", default_scheme="socks5"
    ) == parse_proxy("user:pass@1.2.3.4:1080", default_scheme="socks5")


def test_whitespace_is_stripped():
    assert parse_proxy("  1.2.3.4:1080\n", default_scheme="socks5") == parse_proxy(
        "1.2.3.4:1080", default_scheme="socks5"
    )


class TestIPv6:
    def test_bracketed_host_port(self):
        proxy = parse_proxy("[2001:db8::1]:1080", default_scheme="socks5")
        assert proxy.host == "2001:db8::1"
        assert proxy.port == 1080

    def test_brackets_stripped_then_re_added(self):
        proxy = parse_proxy("socks5://user:pass@[2001:db8::1]:1080")
        assert proxy.host == "2001:db8::1"
        assert proxy.to_url() == "socks5://user:pass@[2001:db8::1]:1080"

    def test_reversed_with_ipv6(self):
        proxy = parse_proxy("[2001:db8::1]:1080@user:pass", default_scheme="socks5")
        assert proxy.host == "2001:db8::1"
        assert (proxy.username, proxy.password) == ("user", "pass")

    def test_unbracketed_ipv6_rejected(self):
        with pytest.raises(ProxyParseError):
            parse_proxy("2001:db8::1:1080", default_scheme="socks5")


class TestAmbiguityTieBreak:
    def test_ip_side_wins_reversed(self):
        # numeric "password" 8080; the IP literal side is the endpoint
        proxy = parse_proxy("1.2.3.4:1080@admin:8080", default_scheme="socks5")
        assert proxy.host == "1.2.3.4"
        assert (proxy.username, proxy.password) == ("admin", "8080")

    def test_no_ip_falls_back_to_standard_order(self):
        proxy = parse_proxy("user:9050@admin:8080", default_scheme="socks5")
        assert proxy.host == "admin"
        assert (proxy.username, proxy.password) == ("user", "9050")

    def test_ipv6_bracket_wins_over_ipv4(self):
        proxy = parse_proxy("[2001:db8::1]:1080@5.6.7.8:8080", default_scheme="socks5")
        assert proxy.host == "2001:db8::1"

    def test_both_bracketed_is_ambiguous(self):
        with pytest.raises(ProxyParseError, match="ambiguous"):
            parse_proxy(
                "[2001:db8::1]:1080@[2001:db8::2]:8080", default_scheme="socks5"
            )

    def test_both_ips_fall_back_to_standard_order(self):
        # documented limitation: both sides are IPs -> standard creds@host:port
        proxy = parse_proxy("1.2.3.4:1080@5.6.7.8:8080", default_scheme="socks5")
        assert proxy.host == "5.6.7.8"
        assert (proxy.username, proxy.password) == ("1.2.3.4", "1080")

    def test_ip_on_right_wins(self):
        proxy = parse_proxy("admin:8080@1.2.3.4:1080", default_scheme="socks5")
        assert proxy.host == "1.2.3.4"
        assert (proxy.username, proxy.password) == ("admin", "8080")


class TestErrors:
    @pytest.mark.parametrize(
        "raw",
        [
            "",
            "   ",
            "ftp://1.2.3.4:1080",  # bad scheme
            "socks5://1.2.3.4",  # missing port
            "socks5://1.2.3.4:99999",  # port out of range
            "socks5://1.2.3.4:0",  # port 0
            "1.2.3.4:1080:user",  # 3 segments
            "1.2.3.4:1080:user:pass:more",  # 5 segments
            "user:pass@host|1.2.3.4:1080",  # @ and | together
            "host:port",  # non-numeric port
        ],
    )
    def test_raises_proxy_parse_error(self, raw):
        # default_scheme set so schemeless entries test their real error, not "no scheme"
        with pytest.raises(ProxyParseError):
            parse_proxy(raw, default_scheme="socks5")

    def test_proxy_parse_error_is_value_error(self):
        with pytest.raises(ValueError):
            parse_proxy("ftp://1.2.3.4:1080")

    def test_proxy_list_colon_in_password_unsupported(self):
        # exactly 4 segments expected; a colon in the password overflows
        with pytest.raises(ProxyParseError):
            parse_proxy("1.2.3.4:1080:user:pa:ss", default_scheme="socks5")


class TestProxyListCredentialMatrix:
    def test_both_segments_empty_means_no_credentials(self):
        proxy = parse_proxy("1.2.3.4:1080::", default_scheme="socks5")
        assert proxy.username is None
        assert proxy.password is None

    @pytest.mark.parametrize("raw", ["1.2.3.4:1080:user:", "1.2.3.4:1080::pass"])
    def test_only_one_segment_set_is_error(self, raw):
        with pytest.raises(ProxyParseError):
            parse_proxy(raw, default_scheme="socks5")


class TestCredentials:
    def test_url_credentials_are_verbatim(self):
        # percent sequences are kept literally, never decoded
        proxy = parse_proxy("socks5://user:p%40ss@1.2.3.4:1080")
        assert proxy.password == "p%40ss"

    def test_proxy_list_creds_are_verbatim(self):
        proxy = parse_proxy("1.2.3.4:1080:user:%40", default_scheme="socks5")
        assert proxy.password == "%40"

    def test_password_may_contain_colons_in_at_form(self):
        proxy = parse_proxy("user:pa:ss:word@1.2.3.4:1080", default_scheme="socks5")
        assert proxy.password == "pa:ss:word"

    def test_whitespace_trimmed_by_default(self):
        proxy = parse_proxy("socks5://user : pass @1.2.3.4:1080")
        assert (proxy.username, proxy.password) == ("user", "pass")

    def test_strip_credentials_false_keeps_whitespace(self):
        proxy = parse_proxy(
            "socks5://user : pass @1.2.3.4:1080", strip_credentials=False
        )
        assert (proxy.username, proxy.password) == ("user ", " pass ")

    def test_whitespace_trimmed_in_proxy_list(self):
        proxy = parse_proxy("1.2.3.4:1080: user : pass ", default_scheme="socks5")
        assert (proxy.username, proxy.password) == ("user", "pass")

    def test_host_and_port_always_trimmed(self):
        # host/port whitespace is never valid -> trimmed even with strip off;
        # credentials sit in the middle so their spaces survive the outer strip()
        proxy = parse_proxy(
            "socks5:// user : pass @ 1.2.3.4 : 1080", strip_credentials=False
        )
        assert proxy.host == "1.2.3.4"
        assert proxy.port == 1080
        assert (proxy.username, proxy.password) == (" user ", " pass ")


class TestPortBoundaries:
    @pytest.mark.parametrize("port", [1, 80, 1080, 65535])
    def test_valid_ports(self, port):
        assert parse_proxy(f"1.2.3.4:{port}", default_scheme="socks5").port == port

    @pytest.mark.parametrize("raw", ["1.2.3.4:0", "1.2.3.4:65536", "1.2.3.4:999999"])
    def test_invalid_ports(self, raw):
        with pytest.raises(ProxyParseError):
            parse_proxy(raw, default_scheme="socks5")
