"""The library's core promise: a password never leaks except via `to_url()`."""

import pytest

from proxy_converter import ProxyParseError, parse_proxy

SECRET = "hunter2SuperSecret"

# Malformed inputs that embed the secret in a credential (or credential-adjacent)
# position. None of them parse; none must echo the secret in the exception text.
LEAKY_INPUTS = [
    f"user:{SECRET}@badhost",            # no valid host:port either side
    f"user:{SECRET}|1.2.3.4:1080@x",     # both separators
    f"1.2.3.4:1080:user:{SECRET}:extra", # 5 segments -> unrecognized
    f"[2001:db8::1]:1080:user:{SECRET}", # malformed bracketed
    f"host:{SECRET}",                    # non-numeric port slot
    f"1.2.3.4:{SECRET}:user:pass",       # non-numeric port in proxy-list
    f"user:{SECRET}@5.6.7.8:99999",      # creds present; both sides invalid
    f"1.2.3.4:1080:user:{SECRET[:4]}:x", # password-with-colon overflow
]

# Special characters that must survive parsing and never leak in error text.
SPECIAL_SECRET = "p@ss:w%rd!#"


@pytest.mark.parametrize("raw", LEAKY_INPUTS)
def test_password_not_in_exception_text(raw):
    with pytest.raises(ProxyParseError) as excinfo:
        parse_proxy(raw, default_scheme="socks5")
    assert SECRET not in str(excinfo.value)
    assert SECRET[:8] not in str(excinfo.value)


def test_valid_parse_does_not_leak_in_str_or_repr():
    proxy = parse_proxy(f"socks5://user:{SECRET}@1.2.3.4:1080")
    assert SECRET not in str(proxy)
    assert SECRET not in repr(proxy)


def test_to_url_is_the_only_password_path():
    proxy = parse_proxy(f"socks5://user:{SECRET}@1.2.3.4:1080")
    # to_url() is the explicit, opt-in path -> the real password appears here
    assert SECRET in proxy.to_url()
    # ...and nowhere implicit
    assert SECRET not in str(proxy)
    assert SECRET not in repr(proxy)
    assert SECRET not in f"{proxy}"


def test_to_url_without_auth_omits_password():
    proxy = parse_proxy(f"socks5://user:{SECRET}@1.2.3.4:1080")
    assert SECRET not in proxy.to_url(auth=False)


def test_numeric_password_is_not_echoed():
    # A numeric password sits in the password slot (segment 4); the port-slot
    # echo must never reach it. Error is on the (non-numeric) port slot here.
    with pytest.raises(ProxyParseError) as excinfo:
        parse_proxy("1.2.3.4:notaport:user:9999999", default_scheme="socks5")
    assert "9999999" not in str(excinfo.value)


def test_numeric_port_slot_may_be_echoed():
    # Intended: a purely-numeric token in the PORT position is a port, not a
    # secret, so echoing it is allowed (and helpful).
    with pytest.raises(ProxyParseError) as excinfo:
        parse_proxy("1.2.3.4:99999", default_scheme="socks5")
    assert "99999" in str(excinfo.value)


def test_special_char_password_does_not_leak():
    # malformed input carrying a special-char secret -> not echoed
    with pytest.raises(ProxyParseError) as excinfo:
        parse_proxy(f"user:{SPECIAL_SECRET}@badhost", default_scheme="socks5")
    assert SPECIAL_SECRET not in str(excinfo.value)
    # ...but it round-trips and stays out of str/repr when valid
    proxy = parse_proxy(f"user:{SPECIAL_SECRET}@1.2.3.4:1080", default_scheme="socks5")
    assert proxy.password == SPECIAL_SECRET
    assert SPECIAL_SECRET not in str(proxy)
    assert SPECIAL_SECRET not in repr(proxy)
