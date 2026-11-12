"""The raw result of one fetch, and decoding its body to text."""

from __future__ import annotations

import codecs
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

_HEADER_CHARSET = re.compile(r"charset\s*=\s*[\"']?\s*([A-Za-z0-9._:-]+)", re.IGNORECASE)
_META_CHARSET = re.compile(rb"<meta[^>]+charset\s*=\s*[\"']?\s*([A-Za-z0-9._:-]+)", re.IGNORECASE)

# Browsers read pages labelled Latin-1 or ASCII as Windows-1252, which is a
# superset of both. Doing the same keeps curly quotes and dashes intact.
_AS_WINDOWS_1252 = frozenset({"iso-8859-1", "iso8859-1", "latin1", "latin-1", "ascii", "us-ascii"})


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _codec(label: str) -> str | None:
    name = label.strip().lower()
    if name in _AS_WINDOWS_1252:
        return "cp1252"
    try:
        return codecs.lookup(name).name
    except LookupError:
        return None


def decode_body(content: bytes, content_type: str = "") -> str:
    """Decode a response body to text.

    Order of preference: a byte-order mark, the charset in the Content-Type
    header, a ``<meta charset>`` near the top of the document, UTF-8, and
    finally Windows-1252. Undecodable bytes are replaced, never raised.
    """
    if content.startswith(codecs.BOM_UTF8):
        return content[len(codecs.BOM_UTF8) :].decode("utf-8", errors="replace")
    if content.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return content.decode("utf-16", errors="replace")
    labels: list[str] = []
    header = _HEADER_CHARSET.search(content_type)
    if header:
        labels.append(header.group(1))
    meta = _META_CHARSET.search(content[:4096])
    if meta:
        labels.append(meta.group(1).decode("ascii", errors="ignore"))
    for label in labels:
        codec = _codec(label)
        if codec:
            return content.decode(codec, errors="replace")
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        return content.decode("cp1252", errors="replace")


@dataclass
class Response:
    """What came back for one URL, after redirects, retries and caching."""

    url: str
    """The URL that was asked for."""
    final_url: str
    """The URL that answered, after any redirects."""
    status: int
    headers: dict[str, str]
    """Response headers with lower-case names."""
    content: bytes
    from_cache: bool = False
    fetched_at: datetime = field(default_factory=_now)

    @property
    def content_type(self) -> str:
        """The media type without parameters, for example ``text/html``."""
        return self.headers.get("content-type", "").split(";")[0].strip().lower()

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300

    @property
    def text(self) -> str:
        return decode_body(self.content, self.headers.get("content-type", ""))
