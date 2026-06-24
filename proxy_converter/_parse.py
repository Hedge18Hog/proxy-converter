"""Proxy-string parser: turn any common format into a :class:`ProxyInfo`.

Supported input formats. The credential separator is ``@`` OR ``|`` (never both);
the scheme is case-insensitive. When no scheme is present you must pass
``default_scheme`` — the protocol cannot be guessed from a bare ``host:port``, so
there is no built-in default:

==  ==========================================  ===========================
 #  Example                                     Notes
==  ==========================================  ===========================
 1  ``socks5://user:pass@1.2.3.4:1080``         URL, standard
 2  ``socks5://1.2.3.4:1080@user:pass``         URL, reversed credentials
 3  ``http://1.2.3.4:8080``                     URL, no credentials
 4  ``http://1.2.3.4:1080:user:pass``           URL, proxy-list style
 5  ``user:pass@1.2.3.4:1080``                  no scheme, with credentials
 6  ``1.2.3.4:1080@user:pass``                  no scheme, reversed
 7  ``1.2.3.4:1080``                            no scheme, no credentials
 8  ``1.2.3.4:1080:user:pass``                  proxy-list
==  ==========================================  ===========================

``|`` is a drop-in alias for ``@``: any ``@``-separated form above (1, 2, 5, 6)
also works with ``|`` (e.g. ``user:pass|1.2.3.4:1080``). The proxy-list and
no-credential forms have no separator and are unaffected.

Auto-detection (separator forms): the side whose last ``:``-segment is a valid
port (1-65535) is taken as ``host:port``; the other side is credentials. When
*both* sides look like ``host:port`` it is ambiguous — a literal-IP host breaks
the tie (the IP side is the endpoint); otherwise the standard order
``creds@host:port`` is assumed. Domain names are not sniffed.

Credentials are stored exactly as written — never percent-decoded or otherwise
transformed — and the adapters emit them verbatim. ``pa%40ss`` stays ``pa%40ss``.
Host and port are always whitespace-trimmed (whitespace is never valid there).
Credentials are trimmed too by default (``strip_credentials=True``); pass
``strip_credentials=False`` to keep the username/password byte-for-byte.

Limitations:
    - proxy-list ``host:port:user:pass`` (formats 4 and 8): the password cannot
      contain ``:``, ``@`` or ``|`` (they collide with the format's separators).
      For such a password use an ``@``- or ``|``-form, picking the separator the
      password does not contain (a password with both ``@`` and ``|`` is not
      representable in any format).
    - ``to_url`` embeds credentials verbatim, so a password containing ``@`` or
      ``:`` yields a URL a strict parser may mis-split. For such passwords prefer
      the field-based adapters (``to_python_socks_kwargs`` / ``to_aiohttp_socks``
      / ``to_native_aiohttp``), which pass the password as a separate field.
    - reversed detection is heuristic; prefer the standard
      ``user:pass@host:port`` or an explicit scheme when the password is numeric.
    - IPv6 with a port must be bracketed: ``[2001:db8::1]:1080``.
"""

import ipaddress
from collections.abc import Iterable

from .errors import ProxyParseError
from .model import ProxyInfo
from .schemes import resolve_scheme


def _is_valid_port(port_str: str) -> bool:
    """True if *port_str* is a decimal port in 1..65535 (no allocation on fail)."""
    if not (port_str.isascii() and port_str.isdigit()) or len(port_str) > 5:
        return False
    return 1 <= int(port_str) <= 65535


def _is_ip_literal(host: str) -> bool:
    """True if *host* is a literal IPv4/IPv6 address (used for the tie-break)."""
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def _split_host_port(endpoint: str) -> tuple[str, int]:
    """``'host:port'`` / ``'[ipv6]:port'`` -> ``(host, port)``; strips brackets.

    Host and port are always whitespace-trimmed — neither can legitimately carry
    surrounding whitespace. Unbracketed IPv6 with a port is ambiguous and
    rejected. Error messages do not echo the raw value (it may carry credentials);
    the offending port is shown only when it is purely numeric.
    """
    if endpoint.startswith("["):
        close_bracket = endpoint.find("]")
        if close_bracket == -1 or not endpoint[close_bracket + 1 :].startswith(":"):
            raise ProxyParseError("malformed IPv6 endpoint; expected '[address]:port'")
        host = endpoint[1:close_bracket]
        port_str = endpoint[close_bracket + 2 :]
        if ":" in port_str:  # a port never contains ':' -> trailing junk
            raise ProxyParseError("malformed IPv6 endpoint; expected '[address]:port'")
    else:
        colon_count = endpoint.count(":")
        if colon_count == 0:
            raise ProxyParseError("port is missing; expected 'host:port'")
        if colon_count > 1:
            raise ProxyParseError(
                "unrecognized host:port form; bracket IPv6 like [::1]:1080"
            )
        host, _, port_str = endpoint.partition(":")
    host, port_str = host.strip(), port_str.strip()
    if not host:
        raise ProxyParseError("host must not be empty")
    if not _is_valid_port(port_str):
        if port_str.isascii() and port_str.isdigit():
            raise ProxyParseError(f"invalid port {port_str!r}; must be 1-65535")
        raise ProxyParseError("invalid port; must be a number 1-65535")
    return host, int(port_str)


def _try_host_port(value: str) -> tuple[str, int] | None:
    """Parse *value* as ``host:port``, or return ``None`` if it is not one."""
    try:
        return _split_host_port(value)
    except ProxyParseError:
        return None


def _split_credentials(credentials: str, *, strip: bool) -> tuple[str, str]:
    """``'user:pass'`` -> ``(username, password)``.

    Splits on the first ``:`` so the password may contain colons. Credentials are
    never decoded — only surrounding whitespace is trimmed when *strip* is true
    (the default); otherwise both parts are returned exactly as written.
    """
    username, separator, password = credentials.partition(":")
    if strip:
        username, password = username.strip(), password.strip()
    if not separator or not username:
        # Never echo the value — it is the credentials and may hold a password.
        raise ProxyParseError("invalid credentials; expected 'username:password'")
    if not password:
        raise ProxyParseError("username is present but password is missing")
    return username, password


def _split_authority(
    rest: str, separator: str, *, strip: bool
) -> tuple[str, int, str | None, str | None]:
    """Split a ``creds<sep>host:port`` (or reversed) string, auto-detecting sides.

    Each side is parsed at most once.
    """
    left, _, right = rest.rpartition(separator)
    left_endpoint = _try_host_port(left)
    right_endpoint = _try_host_port(right)

    if right_endpoint is not None and left_endpoint is None:
        (host, port), credentials = right_endpoint, left  # creds @ host:port
    elif left_endpoint is not None and right_endpoint is None:
        (host, port), credentials = left_endpoint, right  # host:port @ creds
    elif left_endpoint is not None and right_endpoint is not None:
        (host, port), credentials = _resolve_ambiguous(
            left, left_endpoint, right, right_endpoint
        )
    else:
        raise ProxyParseError(
            f"no valid host:port on either side of {separator!r}"
        )

    username, password = _split_credentials(credentials, strip=strip)
    return host, port, username, password


def _resolve_ambiguous(
    left: str,
    left_endpoint: tuple[str, int],
    right: str,
    right_endpoint: tuple[str, int],
) -> tuple[tuple[str, int], str]:
    """Both sides parse as ``host:port`` — pick the endpoint, return ``(it, creds)``.

    Signals, strongest first: a bracketed ``[..]`` side is unambiguously a host
    (credentials are never bracketed), then a literal-IP host. With no
    distinguishing signal, assume the standard order ``creds@host:port``.
    """
    left_bracketed = left.startswith("[")
    right_bracketed = right.startswith("[")
    if left_bracketed and right_bracketed:
        raise ProxyParseError("ambiguous: both sides look like an endpoint")
    if left_bracketed:
        return left_endpoint, right
    if right_bracketed:
        return right_endpoint, left

    left_ip = _is_ip_literal(left_endpoint[0])
    right_ip = _is_ip_literal(right_endpoint[0])
    if left_ip and not right_ip:
        return left_endpoint, right
    return right_endpoint, left  # right-IP-only, both, or neither -> standard


def _split_proxy_list(
    rest: str, *, strip: bool
) -> tuple[str, int, str | None, str | None]:
    """``'host:port:user:pass'`` -> parts. Credentials are not decoded (only
    whitespace-trimmed when *strip* is true)."""
    host, port_str, username, password = rest.split(":")
    host, port_str = host.strip(), port_str.strip()  # host/port: always trimmed
    if strip:
        username, password = username.strip(), password.strip()
    # Echo only non-secret fields here — the password is one of the segments.
    if not host:
        raise ProxyParseError("host must not be empty in proxy-list form")
    if not _is_valid_port(port_str):
        if port_str.isascii() and port_str.isdigit():
            raise ProxyParseError(f"invalid port {port_str!r} in proxy-list form")
        raise ProxyParseError("invalid port in proxy-list form; must be 1-65535")
    username = username or None
    password = password or None
    if (username is None) != (password is None):
        raise ProxyParseError(
            "proxy-list needs both username and password (or neither)"
        )
    return host, int(port_str), username, password


def _split_scheme(text: str, default_scheme: str | None) -> tuple[str, bool, str]:
    """Strip ``scheme://`` -> ``(proxy_type, rdns, rest)``.

    When *text* carries no scheme, fall back to *default_scheme*; if that is
    ``None`` the protocol cannot be guessed from ``host:port``, so raise. The
    message must not echo *text* (it may contain credentials).
    """
    marker = text.find("://")
    if marker != -1:
        proxy_type, rdns = resolve_scheme(text[:marker])
        return proxy_type, rdns, text[marker + 3 :]
    if default_scheme is None:
        raise ProxyParseError(
            "proxy string has no scheme and no default_scheme was given; "
            "pass default_scheme='http' or 'socks5' (it cannot be guessed "
            "from host:port)"
        )
    proxy_type, rdns = resolve_scheme(default_scheme)
    return proxy_type, rdns, text


def _pick_separator(rest: str) -> str | None:
    """Return the credential separator in *rest* (``@`` or ``|``), or ``None``."""
    has_at = "@" in rest
    has_pipe = "|" in rest
    if has_at and has_pipe:
        # Do not echo the value — it carries the credentials.
        raise ProxyParseError(
            "both '@' and '|' credential separators present; use only one"
        )
    if has_at:
        return "@"
    if has_pipe:
        return "|"
    return None


def parse_proxy(
    proxy: str,
    default_scheme: str | None = None,
    *,
    strip_credentials: bool = True,
) -> ProxyInfo:
    """Parse a proxy string in any supported format into a :class:`ProxyInfo`.

    See the module docstring for the full format catalog and the auto-detection
    rules.

    Args:
        proxy: The proxy string in any supported format.
        default_scheme: Scheme to assume when the string carries none. There is
            no built-in default — the protocol cannot be inferred from a bare
            ``host:port``, so schemeless input requires this argument (e.g.
            ``"http"`` or ``"socks5"``). Inputs that already carry a scheme
            ignore it.
        strip_credentials: Trim surrounding whitespace from the username and
            password (default). Set to ``False`` to keep them byte-for-byte, e.g.
            if a password legitimately has leading/trailing spaces.

    Returns:
        A validated, frozen :class:`ProxyInfo`.

    Raises:
        ProxyParseError: On any malformed, ambiguous, or empty input, or when the
            string has no scheme and no ``default_scheme`` was given.

    Example:
        >>> parse_proxy("1.2.3.4:1080@user:pass", default_scheme="socks5").to_url()
        'socks5://user:pass@1.2.3.4:1080'
        >>> parse_proxy("socks5h://user:pass@[::1]:1080").rdns
        True
    """
    text = proxy.strip()
    if not text:
        raise ProxyParseError("empty proxy string")

    proxy_type, rdns, rest = _split_scheme(text, default_scheme)
    separator = _pick_separator(rest)

    if separator is not None:
        host, port, username, password = _split_authority(
            rest, separator, strip=strip_credentials
        )
    elif "[" not in rest and rest.count(":") == 3:
        host, port, username, password = _split_proxy_list(
            rest, strip=strip_credentials
        )
    else:
        host, port = _split_host_port(rest)
        username = password = None

    return ProxyInfo(proxy_type, host, port, username, password, rdns)


def parse_many(
    lines: Iterable[str],
    default_scheme: str | None = None,
    *,
    on_error: str = "raise",
    strip_credentials: bool = True,
) -> (
    list[ProxyInfo]
    | tuple[list[ProxyInfo], list[tuple[int, str, ProxyParseError]]]
):
    """Parse many proxy strings in one pass (for large proxy lists).

    Args:
        lines: Iterable of proxy strings.
        default_scheme: Forwarded to :func:`parse_proxy`; required if any line is
            schemeless (there is no built-in default).
        on_error: How to handle a line that fails to parse:

            - ``"raise"`` (default): stop on the first bad line.
            - ``"skip"``: drop bad lines, return only the parsed ones.
            - ``"collect"``: return ``(parsed, errors)`` where ``errors`` is a
              list of ``(index, line, exception)``. ``line`` is the raw input
              and may contain credentials — redact it before logging.
        strip_credentials: Forwarded to :func:`parse_proxy` (default ``True``).

    Returns:
        ``list[ProxyInfo]`` for ``"raise"``/``"skip"``; ``(parsed, errors)`` for
        ``"collect"``.

    Raises:
        ProxyParseError: In ``"raise"`` mode, on the first unparseable line.
        ValueError: If ``on_error`` is not one of the three accepted values.
    """
    parse = parse_proxy  # local binding trims attribute lookups in the loop
    if on_error == "raise":
        return [parse(line, default_scheme, strip_credentials=strip_credentials)
                for line in lines]
    if on_error == "skip":
        parsed: list[ProxyInfo] = []
        for line in lines:
            try:
                parsed.append(parse(line, default_scheme, strip_credentials=strip_credentials))
            except ProxyParseError:
                continue
        return parsed
    if on_error == "collect":
        parsed = []
        errors: list[tuple[int, str, ProxyParseError]] = []
        for index, line in enumerate(lines):
            try:
                parsed.append(parse(line, default_scheme, strip_credentials=strip_credentials))
            except ProxyParseError as exc:
                errors.append((index, line, exc))
        return parsed, errors
    raise ValueError(
        f"on_error must be 'raise', 'skip', or 'collect', got {on_error!r}"
    )
