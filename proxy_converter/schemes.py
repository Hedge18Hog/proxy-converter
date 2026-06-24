"""Scheme tables and the single source of truth for ``scheme <-> (type, rdns)``.

A proxy "scheme" as written in a URL (``socks5h``) collapses to a *base* proxy
type (``socks5``) plus a remote-DNS flag (``rdns=True``). ``socks5h``/``socks4a``
are not separate protocols — the ``h``/``a`` only means "resolve DNS on the
proxy". Keeping the two apart lets the library round-trip the scheme and emit the
right shape for each consumer (a URL string for httpx/requests, but a base type
plus a separate ``rdns`` kwarg for aiohttp_socks/python-socks).

To support a new scheme, edit the tables here — the parser and ``ProxyInfo``
pick it up automatically.
"""

from .errors import ProxyParseError

#: Base proxy types, with no ``h``/``a`` remote-DNS suffix.
BASE_TYPES: frozenset[str] = frozenset({"http", "https", "socks4", "socks5"})

#: Scheme-as-written -> (base proxy type, rdns). Base types map to rdns=False.
_SCHEME_TO_TYPE: dict[str, tuple[str, bool]] = {
    "http": ("http", False),
    "https": ("https", False),
    "socks4": ("socks4", False),
    "socks4a": ("socks4", True),
    "socks5": ("socks5", False),
    "socks5h": ("socks5", True),
}

#: (base type, rdns=True) -> scheme-as-written. Only the rdns variants differ
#: from the base type; everything else composes back to the type itself.
_RDNS_TO_SCHEME: dict[str, str] = {
    "socks5": "socks5h",
    "socks4": "socks4a",
}


def resolve_scheme(scheme: str) -> tuple[str, bool]:
    """Map a URL scheme to ``(base_type, rdns)``.

    Args:
        scheme: Scheme as written, case-insensitive, e.g. ``"socks5h"``.

    Returns:
        ``(base_type, rdns)``, e.g. ``("socks5", True)`` for ``"socks5h"``.

    Raises:
        ProxyParseError: If the scheme is not recognized.

    Example:
        >>> resolve_scheme("SOCKS5H")
        ('socks5', True)
    """
    try:
        return _SCHEME_TO_TYPE[scheme.lower()]
    except KeyError:
        allowed = ", ".join(sorted(_SCHEME_TO_TYPE))
        raise ProxyParseError(
            f"unsupported scheme: {scheme!r}; allowed: {allowed}"
        ) from None


def compose_scheme(proxy_type: str, rdns: bool) -> str:
    """Inverse of :func:`resolve_scheme`: ``(type, rdns)`` -> scheme-as-written.

    Example:
        >>> compose_scheme("socks4", True)
        'socks4a'
        >>> compose_scheme("socks5", False)
        'socks5'
    """
    if rdns:
        return _RDNS_TO_SCHEME.get(proxy_type, proxy_type)
    return proxy_type
