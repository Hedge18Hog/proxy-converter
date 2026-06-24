"""Exception types for :mod:`proxy_converter`."""


class ProxyParseError(ValueError):
    """Raised when a proxy string cannot be parsed or is semantically invalid.

    Subclasses :class:`ValueError`, so existing ``except ValueError`` handlers
    keep working unchanged.
    """
