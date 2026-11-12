"""A small on-disk cache for responses.

Each entry is two files named after the SHA-256 of the URL: a ``.json`` file
with the status, headers and time, and a ``.body`` file with the raw bytes.
The client uses the stored ``ETag`` and ``Last-Modified`` headers to ask the
server "has this changed?" instead of downloading the page again.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

# Headers that describe the transfer, not the stored (already decoded) body.
_TRANSFER_HEADERS = frozenset({"content-encoding", "content-length", "transfer-encoding"})


@dataclass
class CachedResponse:
    url: str
    status: int
    headers: dict[str, str]
    content: bytes
    stored_at: float
    """Seconds since the epoch when the entry was stored or last confirmed fresh."""

    def age(self) -> float:
        return max(0.0, time.time() - self.stored_at)


class DiskCache:
    """Store responses in a directory, one entry per URL."""

    def __init__(self, directory: str | os.PathLike[str]) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    def _paths(self, url: str) -> tuple[Path, Path]:
        key = hashlib.sha256(url.encode("utf-8")).hexdigest()
        folder = self.directory / key[:2]
        return folder / f"{key}.json", folder / f"{key}.body"

    def get(self, url: str) -> CachedResponse | None:
        """Return the stored entry for ``url``, or ``None`` if missing or unreadable."""
        meta_path, body_path = self._paths(url)
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            content = body_path.read_bytes()
            return CachedResponse(
                url=str(meta["url"]),
                status=int(meta["status"]),
                headers={str(name): str(value) for name, value in meta["headers"].items()},
                content=content,
                stored_at=float(meta["stored_at"]),
            )
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            return None

    def set(self, entry: CachedResponse) -> None:
        """Store ``entry``, replacing whatever was there for its URL."""
        meta_path, body_path = self._paths(entry.url)
        meta_path.parent.mkdir(parents=True, exist_ok=True)
        headers = {k: v for k, v in entry.headers.items() if k not in _TRANSFER_HEADERS}
        meta = {
            "url": entry.url,
            "status": entry.status,
            "headers": headers,
            "stored_at": entry.stored_at,
        }
        _replace(body_path, entry.content)
        _replace(meta_path, json.dumps(meta, ensure_ascii=False, indent=2).encode("utf-8"))

    def clear(self) -> None:
        """Delete every stored entry."""
        for child in self.directory.iterdir():
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)
            else:
                with contextlib.suppress(OSError):
                    child.unlink()


def _replace(path: Path, data: bytes) -> None:
    """Write through a temporary file so a crash never leaves half an entry."""
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(data)
    os.replace(temporary, path)
