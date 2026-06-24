"""proxy-converter — parse any common proxy-string format, hand it to the major libraries.

Parse a proxy string once and emit the right shape for each HTTP/SOCKS client,
hiding per-library quirks such as the ``socks5h``/``socks4a`` incompatibility
(requests/httpx take the scheme string; aiohttp_socks/python-socks need a base
type plus a separate ``rdns`` flag).

    >>> from proxy_converter import parse_proxy
    >>> proxy = parse_proxy("socks5h://user:pass@1.2.3.4:1080")
    >>> proxy.to_url()
    'socks5h://user:pass@1.2.3.4:1080'
    >>> proxy.proxy_type, proxy.rdns
    ('socks5', True)
"""

from ._parse import parse_many, parse_proxy
from .errors import ProxyParseError
from .model import ProxyInfo

__version__ = "0.1.0"

__all__ = [
    "parse_proxy",
    "parse_many",
    "ProxyInfo",
    "ProxyParseError",
    "__version__",
]
