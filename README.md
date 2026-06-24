# proxy-converter

Parse any common proxy-string format once, then hand it to the major HTTP/SOCKS
libraries — the `socks5h`/`socks4a` incompatibility between requests/httpx and
aiohttp_socks/python-socks is handled for you.

[![PyPI](https://img.shields.io/pypi/v/proxy-converter.svg)](https://pypi.org/project/proxy-converter/)
[![Python](https://img.shields.io/pypi/pyversions/proxy-converter.svg)](https://pypi.org/project/proxy-converter/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

## Install

```bash
pip install proxy-converter
# or
uv add proxy-converter
```

Zero runtime dependencies. The PyPI name is `proxy-converter`; the import name is
`proxy_converter`.

## Quick start

```python
from proxy_converter import parse_proxy

# a messy provider format in -> clean, usable output out
proxy = parse_proxy("1.2.3.4:1080:user:pass", default_scheme="socks5")

proxy.to_url()              # "socks5://user:pass@1.2.3.4:1080"   -> httpx / requests
proxy.to_aiohttp_socks()   # ready aiohttp_socks.ProxyConnector
proxy.host, proxy.port      # ("1.2.3.4", 1080)
```

It also accepts schemeless and "weird" shapes — reversed credentials, the
proxy-list `host:port:user:pass`, a `|` separator, IPv6, and more. Schemeless
input needs an explicit `default_scheme` (the protocol can't be guessed from a
bare `host:port`):

```python
parse_proxy("1.2.3.4:1080:user:pass", default_scheme="socks5")   # proxy-list
parse_proxy("user:pass@1.2.3.4:1080", default_scheme="http")     # standard creds
parse_proxy("1.2.3.4:1080@user:pass", default_scheme="socks5")   # reversed creds
parse_proxy("user:pass|1.2.3.4:1080", default_scheme="socks5")   # pipe separator
```

## Why

Proxy providers hand out the *same* proxy in a dozen shapes, and the schemes are
not portable across clients: `requests`/`httpx` understand `socks5h://`, but
`aiohttp_socks`/`python-socks` reject it and instead want a base `socks5` type
plus a separate `rdns=True` flag. `parse_proxy` normalizes every shape into one
`ProxyInfo`, and the `to_*` adapters emit exactly what each library expects — so
you never copy a `socks5h://` URL into a connector that silently breaks.

## Supported formats

The credential separator is `@` **or** `|` (never both). The scheme is
case-insensitive; when absent, you must pass `default_scheme` — the protocol
can't be guessed from a bare `host:port`, so there is no built-in default.

| # | Example | Notes |
|---|---|---|
| 1 | `socks5://user:pass@1.2.3.4:1080` | URL, standard |
| 2 | `socks5://1.2.3.4:1080@user:pass` | URL, reversed credentials |
| 3 | `http://1.2.3.4:8080` | URL, no credentials |
| 4 | `http://1.2.3.4:1080:user:pass` | URL, proxy-list style |
| 5 | `user:pass@1.2.3.4:1080` | no scheme, with credentials |
| 6 | `1.2.3.4:1080@user:pass` | no scheme, reversed |
| 7 | `1.2.3.4:1080` | no scheme, no credentials |
| 8 | `1.2.3.4:1080:user:pass` | proxy-list |

`|` is a drop-in alias for `@`: any `@`-form above (1, 2, 5, 6) also works with
`|`. Schemes: `http`, `https`, `socks4`, `socks5`, `socks4a`, `socks5h` — where
`socks5h`/`socks4a` mean "resolve DNS on the proxy" (stored as `rdns=True`).

## Adapters

Each adapter returns plain data; the SOCKS/aiohttp ones import their target
library lazily, so the core stays dependency-free. Install the extras only for
what you use: `pip install proxy-converter[aiohttp]` /
`proxy-converter[python-socks]`.

### `to_url(auth=True)` — httpx, and a generic URL

```python
import httpx
proxy = parse_proxy("socks5h://user:pass@1.2.3.4:1080")
client = httpx.Client(proxy=proxy.to_url())

proxy.to_url(auth=False)   # "socks5h://1.2.3.4:1080" — credentials omitted
```

### `to_requests()` — requests

```python
import requests
requests.get("https://example.com", proxies=proxy.to_requests())
# {"http": "socks5h://...", "https": "socks5h://..."}
```

### `to_native_aiohttp()` — aiohttp's built-in proxy (HTTP/HTTPS only)

```python
proxy = parse_proxy("http://user:pass@1.2.3.4:8080")
async with session.get(url, **proxy.to_native_aiohttp()) as resp:
    ...
# {"proxy": "http://1.2.3.4:8080", "proxy_auth": BasicAuth(...)}
# Raises ProxyParseError on a SOCKS proxy — use to_aiohttp_socks() instead.
```

### `to_aiohttp_socks()` — aiohttp_socks (SOCKS and HTTP)

```python
import aiohttp
proxy = parse_proxy("socks5h://user:pass@1.2.3.4:1080")
async with aiohttp.ClientSession(connector=proxy.to_aiohttp_socks()) as session:
    ...
```

### `to_python_socks_kwargs()` — python-socks (any backend)

```python
from python_socks.async_.asyncio import Proxy   # or .trio / .sync
p = Proxy(**proxy.to_python_socks_kwargs())
# {"proxy_type": ProxyType.SOCKS5, "host": ..., "port": ..., "rdns": True, ...}
```

## The `ProxyInfo` object

`parse_proxy` returns a frozen `ProxyInfo`. Stored fields plus two read-only
properties:

```python
proxy = parse_proxy("socks5h://user:pass@1.2.3.4:1080")

proxy.proxy_type   # "socks5"   (base type; never socks5h/socks4a)
proxy.host         # "1.2.3.4"
proxy.port         # 1080
proxy.username     # "user"
proxy.password     # "pass"
proxy.rdns         # True       (the "h"/"a" — resolve DNS on the proxy)

proxy.scheme       # "socks5h"  (computed: proxy_type + rdns)
proxy.auth         # ("user", "pass")  or  None
```

It is immutable (hashable → usable in `set()` / as a `dict` key). To change a
field, build a new one — which also re-validates:

```python
import dataclasses
other = dataclasses.replace(proxy, port=1234)
```

## Gotchas

- **Don't feed a `socks5h://` URL straight into aiohttp_socks/python-socks.**
  They reject it. Use `to_aiohttp_socks()` / `to_python_socks_kwargs()`, which
  emit the base type + `rdns` flag. (`to_url()` keeps `socks5h` for httpx/requests.)
- **Reversed-format detection is heuristic.** For `creds@host:port` vs
  `host:port@creds`, the side whose last `:`-segment is a valid port wins; a
  literal-IP host breaks ties. It can misread `user:9050@admin:8080`-style
  inputs where both sides look like `host:port` and neither is an IP. Prefer the
  standard `user:pass@host:port` or an explicit scheme when in doubt.
- **Credentials are stored and emitted verbatim** — never percent-decoded or
  encoded. `pa%40ss` stays `pa%40ss`. (Proxy passwords aren't URL-encoded in
  practice, so this is what you want.) The only touch is trimming surrounding
  whitespace from the username/password; pass `strip_credentials=False` to keep
  even that byte-for-byte:

  ```python
  parse_proxy("socks5://user: pass @1.2.3.4:1080").password                          # "pass"
  parse_proxy("socks5://user: pass @1.2.3.4:1080", strip_credentials=False).password # " pass "
  ```

  Two more consequences of verbatim credentials: a proxy-list password can't
  contain `:`, `@`, or `|` (they collide with the format's separators) — use an
  `@`/`|` form instead, picking the separator your password doesn't contain. And a
  password containing `@`/`:` makes `to_url()` ambiguous to a strict URL parser —
  for those, use the field-based adapters (`to_python_socks_kwargs`,
  `to_aiohttp_socks`).
- **IPv6 needs brackets when a port is present:** `[2001:db8::1]:1080`.
- **Passwords are masked.** `str()`, `repr()`, and error messages never reveal
  the password; only an explicit `to_url()` does.

## Batch parsing

`parse_many` parses an iterable of lines (for proxy-list files) with an error
policy:

```python
from proxy_converter import parse_many

proxies = parse_many(lines, default_scheme="socks5")                    # raise on first bad line
proxies = parse_many(lines, default_scheme="socks5", on_error="skip")   # drop bad lines
ok, errors = parse_many(lines, default_scheme="socks5", on_error="collect")  # (parsed, [(index, line, exc), ...])
```

It is fast — ~650k lines/sec on a laptop (~1.5 µs per line).

## License

[MIT](LICENSE)
