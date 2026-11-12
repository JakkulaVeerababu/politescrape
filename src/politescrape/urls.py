"""URL helpers: normalising, comparing and taking URLs apart."""

from __future__ import annotations

import re
from urllib.parse import quote, unquote, urlsplit, urlunsplit

DEFAULT_PORTS = {"http": 80, "https": 443}

# Query parameters that only track where a visitor came from. Removing them
# stops a crawler from fetching the same page again under a different address.
TRACKING_PARAMS = re.compile(
    r"^(utm_[a-z0-9_]+|gclid|dclid|fbclid|msclkid|yclid|mc_cid|mc_eid|igshid|_ga|_gl)$",
    re.IGNORECASE,
)

_UNRESERVED = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~")
_ESCAPE = re.compile(r"%([0-9A-Fa-f]{2})")
# Reserved characters (RFC 3986) plus "%", so existing escapes are left alone.
_KEEP = "!#$%&'()*+,/:;=?@[]"


def is_http_url(url: str) -> bool:
    """True for absolute ``http://`` and ``https://`` URLs."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    return parts.scheme.lower() in DEFAULT_PORTS and bool(parts.netloc)


def normalize_percent_encoding(value: str) -> str:
    """Make two spellings of the same path compare equal.

    Escapes of unreserved characters are decoded (``%7E`` becomes ``~``), the
    remaining escapes are upper-cased, and anything outside ASCII is encoded.
    """

    def fix(match: re.Match[str]) -> str:
        char = chr(int(match.group(1), 16))
        return char if char in _UNRESERVED else "%" + match.group(1).upper()

    return quote(_ESCAPE.sub(fix, value), safe=_KEEP)


def normalize_url(url: str, *, strip_tracking: bool = True) -> str:
    """Return a canonical form of ``url`` for fetching and de-duplicating.

    Lower-cases the scheme and host, drops default ports and the fragment,
    normalises percent-encoding and (by default) removes tracking parameters.
    The order of the remaining query parameters is kept.

    Raises :class:`ValueError` for URLs that cannot be parsed.
    """
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    host = (parts.hostname or "").lower()
    if ":" in host:  # IPv6 literal
        host = f"[{host}]"
    netloc = host
    if parts.username:
        userinfo = parts.username + (f":{parts.password}" if parts.password else "")
        netloc = f"{userinfo}@{netloc}"
    port = parts.port
    if port is not None and DEFAULT_PORTS.get(scheme) != port:
        netloc = f"{netloc}:{port}"
    path = normalize_percent_encoding(parts.path) or "/"
    query = parts.query
    if strip_tracking and query:
        kept = [
            segment
            for segment in query.split("&")
            if segment and not TRACKING_PARAMS.match(unquote(segment.split("=", 1)[0]))
        ]
        query = "&".join(kept)
    return urlunsplit((scheme, netloc, path, normalize_percent_encoding(query), ""))


def origin(url: str) -> str:
    """Return ``scheme://host[:port]`` for a URL, lower-cased."""
    parts = urlsplit(url)
    return f"{parts.scheme.lower()}://{parts.netloc.lower()}"


def path_and_query(url: str) -> str:
    """Return the part of a URL that robots.txt rules are matched against."""
    parts = urlsplit(url)
    path = parts.path or "/"
    return f"{path}?{parts.query}" if parts.query else path


def site_name(url: str) -> str:
    """Return the host name without a leading ``www.``."""
    host = (urlsplit(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def same_site(first: str, second: str) -> bool:
    """True when two URLs are on the same host (ignoring a leading ``www.``)."""
    name = site_name(first)
    return bool(name) and name == site_name(second)
