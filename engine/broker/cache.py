"""cache.py — Deterministic broker cache (directive §25).

Key = sha256(prompt + model + seed + input_hash + style_hash + duration +
aspect + renderer_version). Layout: cache/broker/<aa>/<key>.<ext>.

Every broker operation consults the cache before any network call.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_CACHE_ROOT = PROJECT_ROOT / "cache" / "broker"


def _stable_hash(text: str) -> str:
    """Process-independent hash (hash() is salted per process — never use)."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _file_hash(path: str | Path | None) -> str:
    if not path:
        return ""
    p = Path(path)
    if not p.exists():
        return _stable_hash(str(path))
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def _style_hash(style: Any) -> str:
    if not style:
        return ""
    if isinstance(style, str):
        return _stable_hash(style)
    try:
        return _stable_hash(json.dumps(style, sort_keys=True, default=str))
    except (TypeError, ValueError):
        return _stable_hash(str(style))


def broker_cache_key(
    *,
    prompt: str = "",
    model: str = "",
    seed: int | str | None = None,
    input_path: str | Path | None = None,
    style: Any = None,
    duration: float | None = None,
    aspect: str | None = None,
    renderer_version: str = "",
    op: str = "",
    extra: dict[str, Any] | None = None,
) -> str:
    """Deterministic cache key over every input that can change the output.

    Same inputs (in any process, any order of dict keys) → same key.
    """
    parts = [
        op,
        prompt or "",
        model or "",
        str(seed) if seed is not None else "",
        _file_hash(input_path),
        _style_hash(style),
        f"{duration:.3f}" if duration is not None else "",
        aspect or "",
        renderer_version or "",
    ]
    if extra:
        parts.append(json.dumps(extra, sort_keys=True, default=str))
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


@dataclass
class CacheEntry:
    path: Path
    key: str
    size_bytes: int


class BrokerCache:
    """On-disk cache under ``cache/broker/`` with deterministic keys."""

    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root) if root else DEFAULT_CACHE_ROOT

    def _path_for(self, key: str, ext: str) -> Path:
        ext = ext.lstrip(".") or "bin"
        return self.root / key[:2] / f"{key}.{ext}"

    @staticmethod
    def key_for_url(url: str) -> str:
        """Deterministic key for a downloaded remote asset (by source URL)."""
        return hashlib.sha256(url.encode("utf-8")).hexdigest()

    def get(self, key: str, ext: str = "bin") -> Path | None:
        """Return the cached artifact path, or None on miss."""
        p = self._path_for(key, ext)
        if p.exists() and p.stat().st_size > 0:
            return p
        return None

    def store(self, key: str, src_path: str | Path, ext: str | None = None) -> Path:
        """Copy *src_path* into the cache under *key*; returns cached path."""
        src = Path(src_path)
        if ext is None:
            ext = src.suffix or "bin"
        dest = self._path_for(key, ext)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if src.resolve() != dest.resolve():
            shutil.copyfile(src, dest)
        return dest

    def store_bytes(self, key: str, data: bytes, ext: str = "bin") -> Path:
        dest = self._path_for(key, ext)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        return dest

    def metadata_path(self, key: str) -> Path:
        return self._path_for(key, "json")

    def store_metadata(self, key: str, meta: dict[str, Any]) -> Path:
        p = self.metadata_path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(meta, indent=2, sort_keys=True), encoding="utf-8")
        return p

    def load_metadata(self, key: str) -> dict[str, Any] | None:
        p = self.metadata_path(key)
        if not p.exists():
            return None
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None

    def stats(self) -> dict[str, int]:
        files = list(self.root.glob("*/*")) if self.root.exists() else []
        return {
            "entries": len(files),
            "bytes": sum(f.stat().st_size for f in files if f.is_file()),
        }
