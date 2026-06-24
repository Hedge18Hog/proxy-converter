"""The :class:`ProxyInfo` value object and its per-library adapters."""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .errors import ProxyParseError
from .schemes import BASE_TYPES, compose_scheme

if TYPE_CHECKING:  # only for type checkers; never imported at runtime
    from aiohttp_socks import ProxyConnector

_SOCKS_TYPES = ("socks4", "socks5")
_HTTP_TYPES = ("http", "https")


@dataclass(frozen=True, slots=True)
class ProxyInfo:
    """Immutable, validated description of a single proxy endpoint.

    The proxy is stored as a *base* ``proxy_type`` plus a separate ``rdns`` flag.
    The ``h``/``a`` in ``socks5h``/``socks4a`` only means "resolve DNS on the
    proxy" — so we keep the base type (``socks5``) and carry that bit in ``rdns``.
    This lets each adapter emit the right shape: a ``socks5h://`` URL for
    httpx/requests, but a base ``socks5`` type with ``rdns=True`` for
    aiohttp_socks/python-socks.

    The object is frozen — to change a field, build a new one with
    :func:`dataclasses.replace`. ``str()`` and ``repr()`` mask the password; the
    real password is only ever emitted by an explicit :meth:`to_url` call.

    Attributes:
        proxy_type: Base type, one of ``http``, ``https``, ``socks4``, ``socks5``
            (the ``socks5h``/``socks4a`` form lives in ``scheme``; ``rdns`` is its
            underlying flag).
        host: Hostname or IP literal; IPv6 brackets are stripped.
        port: TCP port, ``1..65535``.
        username: Auth username, or ``None``.
        password: Auth password, or ``None``.
        rdns: Whether DNS is resolved by the proxy; ``True`` for
            ``socks5h``/``socks4a``, ``False`` otherwise.
        scheme: (read-only) Full URL scheme, e.g. ``socks5h`` or ``http``.
        auth: (read-only) ``(username, password)`` tuple, or ``None``.
    """

    proxy_type: str
    host: str
    port: int
    username: str | None
    password: str | None
    rdns: bool = False

    def __post_init__(self) -> None:
        if self.proxy_type not in BASE_TYPES:
            allowed = ", ".join(sorted(BASE_TYPES))
            raise ProxyParseError(
                f"invalid proxy_type {self.proxy_type!r}; allowed: {allowed}"
            )
        if not self.host:
            raise ProxyParseError("host must not be empty")
        if not 1 <= self.port <= 65535:
            raise ProxyParseError(f"port out of range 1-65535: {self.port}")
        if (self.username is None) != (self.password is None):
            raise ProxyParseError(
                "username and password must both be set or both be None"
            )
        if self.rdns and self.proxy_type not in _SOCKS_TYPES:
            raise ProxyParseError(
                f"rdns is only valid for socks proxies, not {self.proxy_type!r}"
            )

    # ── computed ──────────────────────────────────────────────────────────────

    @property
    def scheme(self) -> str:
        """Full URL scheme, recomposing ``rdns`` (``socks5`` + rdns -> ``socks5h``)."""
        return compose_scheme(self.proxy_type, self.rdns)

    @property
    def auth(self) -> tuple[str, str] | None:
        """``(username, password)`` when credentials are set, else ``None``."""
        if self.username is None:
            return None
        return (self.username, self.password)  # type: ignore[return-value]

    # ── rendering ─────────────────────────────────────────────────────────────

    def _bracketed_host(self) -> str:
        # An IPv6 literal contains ':'; it must be bracketed in a URL.
        return f"[{self.host}]" if ":" in self.host else self.host

    def __str__(self) -> str:
        credentials = f"{self.username}:***@" if self.username is not None else ""
        return f"{self.scheme}://{credentials}{self._bracketed_host()}:{self.port}"

    def __repr__(self) -> str:
        password = "'***'" if self.password is not None else "None"
        return (
            f"ProxyInfo(proxy_type={self.proxy_type!r}, host={self.host!r}, "
            f"port={self.port}, username={self.username!r}, "
            f"password={password}, rdns={self.rdns})"
        )

    # ── adapters ──────────────────────────────────────────────────────────────

    def to_url(self, auth: bool = True) -> str:
        """Render the proxy as a URL string.

        Args:
            auth: Include credentials (default ``True``). ``False`` omits them,
                e.g. when the consumer takes auth separately.

        Returns:
            The proxy as a URL string, with IPv6 hosts bracketed. Credentials are
            emitted verbatim — exactly as stored, no encoding (see the example).

        Note:
            The scheme reflects ``rdns`` (``socks5h``/``socks4a``). Do NOT feed
            this string straight into ``aiohttp_socks``/``python_socks`` — they
            reject ``socks5h``/``socks4a``; use :meth:`to_aiohttp_socks` /
            :meth:`to_python_socks_kwargs` instead. A password containing ``@`` or
            ``:`` makes this URL ambiguous to a strict parser — for such passwords
            use the field-based adapters instead.

        Example:
            >>> from proxy_converter import parse_proxy
            >>> parse_proxy("socks5h://user:pass@1.2.3.4:1080").to_url()
            'socks5h://user:pass@1.2.3.4:1080'
        """
        credentials = ""
        if auth and self.username is not None:
            credentials = f"{self.username}:{self.password}@"
        return f"{self.scheme}://{credentials}{self._bracketed_host()}:{self.port}"

    def to_requests(self) -> dict[str, str]:
        """Build the ``proxies=`` mapping for ``requests``.

        Returns:
            A mapping with ``http`` and ``https`` keys, each set to the proxy URL
            (see the example for the exact shape).

        Note:
            SOCKS proxies need ``requests``' optional extra — ``pip install
            requests[socks]``.

        Example:
            >>> from proxy_converter import parse_proxy
            >>> parse_proxy("1.2.3.4:8080", default_scheme="http").to_requests()
            {'http': 'http://1.2.3.4:8080', 'https': 'http://1.2.3.4:8080'}
        """
        url = self.to_url(auth=True)
        return {"http": url, "https": url}

    def to_native_aiohttp(self) -> dict[str, object]:
        """Build kwargs for aiohttp's built-in proxy support (HTTP/HTTPS only).

        Returns:
            A mapping with a ``proxy`` key (the URL without credentials) and a
            ``proxy_auth`` key (an ``aiohttp.BasicAuth`` or ``None``), ready to
            splat into ``session.get(url, **proxy.to_native_aiohttp())``.
            ``aiohttp.BasicAuth`` is imported lazily.

        Raises:
            ProxyParseError: For SOCKS proxies — aiohttp has no native SOCKS
                support; use :meth:`to_aiohttp_socks`.

        Example:
            >>> from proxy_converter import parse_proxy
            >>> parse_proxy("http://1.2.3.4:8080").to_native_aiohttp()["proxy"]
            'http://1.2.3.4:8080'
        """
        if self.proxy_type not in _HTTP_TYPES:
            raise ProxyParseError(
                f"native aiohttp supports http/https proxies only, got "
                f"{self.proxy_type!r}; use to_aiohttp_socks() for SOCKS"
            )
        proxy_auth = None
        if self.username is not None:
            # BasicAuth is aiohttp's API for proxy_auth; aiohttp 4.0-pre marks it
            # deprecated, but it is still the supported path — revisit on 4.0.
            try:
                from aiohttp import BasicAuth  # lazy: keep core dependency-free
            except ImportError as exc:
                raise ProxyParseError(
                    "to_native_aiohttp() needs aiohttp to build BasicAuth for "
                    "credentialed proxies; install with `pip install aiohttp`"
                ) from exc
            proxy_auth = BasicAuth(self.username, self.password)
        return {"proxy": self.to_url(auth=False), "proxy_auth": proxy_auth}

    def to_aiohttp_socks(self) -> "ProxyConnector":
        """Build a ready ``aiohttp_socks.ProxyConnector`` for this proxy.

        Uses the base type + ``rdns`` flag (not a ``socks5h`` URL), so it works
        for SOCKS and HTTP proxies alike. ``aiohttp_socks`` is imported lazily.

        Raises:
            ProxyParseError: If ``aiohttp_socks`` is not installed.

        Example:
            >>> from proxy_converter import parse_proxy
            >>> conn = parse_proxy("socks5h://1.2.3.4:1080").to_aiohttp_socks()  # doctest: +SKIP
        """
        try:
            from aiohttp_socks import ProxyConnector  # lazy
        except ImportError as exc:
            raise ProxyParseError(
                "to_aiohttp_socks() requires aiohttp_socks; install with "
                "`pip install proxy-converter[aiohttp]` (or `pip install aiohttp_socks`)"
            ) from exc
        return ProxyConnector(**self.to_python_socks_kwargs())

    def to_python_socks_kwargs(self) -> dict[str, object]:
        """Build constructor kwargs for ``python_socks`` (any backend).

        Returns:
            A kwargs mapping with keys ``proxy_type`` (a ``python_socks.ProxyType``),
            ``host``, ``port``, ``username``, ``password`` and ``rdns``. The base
            type and ``rdns`` flag are kept separate (``python_socks`` does not
            understand ``socks5h``). An ``https`` proxy maps to ``ProxyType.HTTP``
            (``python_socks`` has no separate HTTPS type).
            ``python_socks.ProxyType`` is imported lazily.

        Splat it into whichever backend ``Proxy`` you use::

            from python_socks.async_.asyncio import Proxy  # or .trio / .sync
            Proxy(**proxy.to_python_socks_kwargs())

        Raises:
            ProxyParseError: If ``python_socks`` is not installed.
        """
        try:
            from python_socks import ProxyType  # lazy
        except ImportError as exc:
            raise ProxyParseError(
                "to_python_socks_kwargs() requires python_socks; install with "
                "`pip install proxy-converter[python-socks]` (or `pip install python-socks`)"
            ) from exc
        type_map = {
            "http": ProxyType.HTTP,
            "https": ProxyType.HTTP,  # python_socks has no separate HTTPS type
            "socks4": ProxyType.SOCKS4,
            "socks5": ProxyType.SOCKS5,
        }
        return {
            "proxy_type": type_map[self.proxy_type],
            "host": self.host,
            "port": self.port,
            "username": self.username,
            "password": self.password,
            "rdns": self.rdns,
        }
