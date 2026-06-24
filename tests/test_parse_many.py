"""Tests for the `parse_many` batch helper and its error modes."""

import pytest

from proxy_converter import ProxyInfo, ProxyParseError, parse_many

LINES = ["1.2.3.4:1080", "garbage:::", "user:pass@5.6.7.8:1080", ""]


def test_raise_mode_stops_on_first_bad_line():
    with pytest.raises(ProxyParseError):
        parse_many(LINES, default_scheme="socks5")  # default on_error="raise"


def test_raise_mode_all_good():
    result = parse_many(["1.2.3.4:1080", "5.6.7.8:8080"], default_scheme="socks5")
    assert len(result) == 2
    assert all(isinstance(p, ProxyInfo) for p in result)


def test_skip_mode_drops_bad_lines():
    result = parse_many(LINES, default_scheme="socks5", on_error="skip")
    assert len(result) == 2
    assert {p.host for p in result} == {"1.2.3.4", "5.6.7.8"}


def test_collect_mode_returns_parsed_and_errors():
    parsed, errors = parse_many(LINES, default_scheme="socks5", on_error="collect")
    assert len(parsed) == 2
    assert [index for index, _, _ in errors] == [1, 3]
    # error tuples carry (index, original_line, exception)
    assert errors[0][1] == "garbage:::"
    assert isinstance(errors[0][2], ProxyParseError)


def test_collect_mode_all_good_has_empty_errors():
    parsed, errors = parse_many(
        ["1.2.3.4:1080"], default_scheme="socks5", on_error="collect"
    )
    assert len(parsed) == 1
    assert errors == []


def test_default_scheme_forwarded():
    result = parse_many(["1.2.3.4:1080"], default_scheme="http")
    assert result[0].proxy_type == "http"


def test_schemeless_without_default_raises():
    with pytest.raises(ProxyParseError, match="no scheme"):
        parse_many(["1.2.3.4:1080"])


def test_accepts_any_iterable():
    gen = (line for line in ["1.2.3.4:1080", "5.6.7.8:8080"])
    assert len(parse_many(gen, default_scheme="socks5")) == 2


def test_empty_iterable():
    assert parse_many([]) == []
    assert parse_many([], on_error="skip") == []
    assert parse_many([], on_error="collect") == ([], [])


def test_bad_on_error_value():
    with pytest.raises(ValueError):
        parse_many(["1.2.3.4:1080"], on_error="explode")
