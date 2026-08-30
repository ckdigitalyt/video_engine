"""stock.py — Pexels / Pixabay stock-footage broker clients.

Wraps the proven search/download logic in ``src/providers/asset_provider.py``
(Wave-1 rule: reuse, don't fork). Every download lands in the deterministic
broker cache, keyed by source URL, with a license metadata sidecar
(directive §13: never publish an asset whose license cannot be established).
"""

from __future__ import annotations

import json
import os
import time
import urllib.request
from abc import abstractmethod
from pathlib import Path
from typing import Any

from engine.broker.cache import BrokerCache
from engine.broker.providers.base import (
    BrokerResult,
    MediaProvider,
    ProviderDescriptor,
    ProviderError,
)


def _pick_best_variant_link(asset: dict) -> str:
    """Highest-quality variant link (mirrors src/providers/asset_provider.py)."""
    vf = asset.get("video_files", [])
    best, best_score = None, -1
    for entry in vf or []:
        if not entry or not entry.get("link"):
            continue
        q = str(entry.get("quality", "")).lower()
        try:
            w, h = int(entry.get("width", 0) or 0), int(entry.get("height", 0) or 0)
        except (TypeError, ValueError):
            w = h = 0
        score = max(w, 0) * max(h, 0)
        if q in ("uhd", "4k"):
            score += 10 ** 10
        elif q == "hd":
            score += 10 ** 8
        if score > best_score:
            best, best_score = entry.get("link"), score
    if best:
        return best
    return asset.get("url", asset.get("link", ""))


class _StockProviderBase(MediaProvider):
    """Shared search/download flow; subclasses set API endpoints."""

    kind = "stock"

    def __init__(self, cache: BrokerCache | None = None, api_key: str | None = None) -> None:
        self.cache = cache or BrokerCache()
        self._api_key = (
            api_key if api_key is not None else os.environ.get(self.ENV_KEY, "")
        )

    ENV_KEY: str = ""

    @abstractmethod
    def _search_url(self, query: str, per_page: int) -> str: ...

    @abstractmethod
    def _parse_results(self, payload: dict[str, Any]) -> list[dict[str, Any]]: ...

    @abstractmethod
    def _license_note(self) -> str: ...

    def capabilities(self) -> ProviderDescriptor:
        return ProviderDescriptor(
            id=self.id,
            kind=self.kind,
            models=[],
            enabled=bool(self._api_key),
            priority=10,
            notes=self._license_note(),
        )

    def health_check(self) -> bool:
        if not self._api_key:
            return False
        try:
            self.search("nature", per_page=1)
            return True
        except ProviderError:
            return False

    def _headers(self) -> dict[str, str]:
        raise NotImplementedError

    def search(self, query: str, per_page: int = 5) -> list[dict[str, Any]]:
        """Raw search results (provider-specific dicts)."""
        if not self._api_key:
            raise ProviderError(f"{self.id}: {self.ENV_KEY} not set")
        url = self._search_url(query, per_page)
        req = urllib.request.Request(url, headers=self._headers())
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except Exception as exc:  # urllib + JSON errors → uniform failure
            raise ProviderError(f"{self.id}: search failed ({exc})") from None
        return self._parse_results(payload)

    def download(self, asset: dict[str, Any], *, force: bool = False) -> BrokerResult:
        """Download the best variant of *asset* into the deterministic cache."""
        link = _pick_best_variant_link(asset)
        if not link:
            raise ProviderError(f"{self.id}: asset has no downloadable link")
        key = BrokerCache.key_for_url(link)
        ext = Path(link.split("?")[0]).suffix or ".mp4"
        if not force:
            hit = self.cache.get(key, ext=ext)
            if hit:
                return BrokerResult(
                    path=hit, provider=self.id, kind="stock", cached=True,
                    metadata=self.cache.load_metadata(key) or {},
                )
        req = urllib.request.Request(link, headers={"User-Agent": "video-engine-broker/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = resp.read()
        except Exception as exc:
            raise ProviderError(f"{self.id}: download failed ({exc})") from None
        path = self.cache.store_bytes(key, data, ext=ext)
        meta = {
            "source": self.id,
            "url": link,
            "asset_id": str(asset.get("id", "")),
            "license": self._license_note(),
            "download_date": time.strftime("%Y-%m-%d"),
            "creator": str(asset.get("user", {}).get("name", "")),
            "attribution_required": self.id == "pexels",
            "usage_notes": "Per provider license terms; verify before publication.",
            "duration": asset.get("duration"),
            "width": asset.get("width"),
            "height": asset.get("height"),
        }
        self.cache.store_metadata(key, meta)
        return BrokerResult(path=path, provider=self.id, kind="stock",
                            cached=False, metadata=meta)


class PexelsStockProvider(_StockProviderBase):
    id = "pexels"
    ENV_KEY = "PEXELS_API_KEY"

    def _search_url(self, query: str, per_page: int) -> str:
        from urllib.parse import quote

        return (f"https://api.pexels.com/videos/search"
                f"?query={quote(query)}&per_page={per_page}")

    def _headers(self) -> dict[str, str]:
        return {"Authorization": self._api_key}

    def _parse_results(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        return list(payload.get("videos", []))

    def _license_note(self) -> str:
        return "Pexels License: free to use, attribution appreciated not required."


class PixabayStockProvider(_StockProviderBase):
    id = "pixabay"
    ENV_KEY = "PIXABAY_API_KEY"

    def _search_url(self, query: str, per_page: int) -> str:
        from urllib.parse import quote

        return (f"https://pixabay.com/api/videos/?key={self._api_key}"
                f"&q={quote(query)}&per_page={per_page}")

    def _headers(self) -> dict[str, str]:
        return {}  # pixabay auth is via query param

    def _parse_results(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        hits = list(payload.get("hits", []))
        # Pixabay exposes per-quality video dicts ("videos": {"large": {...}}),
        # not Pexels' "video_files" list. Normalize to the common shape so
        # _pick_best_variant_link works (previously every candidate raised
        # "asset has no downloadable link" — observed live 2026-08-30).
        for hit in hits:
            if hit.get("video_files"):
                continue
            files = []
            for quality, v in (hit.get("videos") or {}).items():
                if isinstance(v, dict) and v.get("url"):
                    files.append({
                        "link": v.get("url"),
                        "width": v.get("width"),
                        "height": v.get("height"),
                        "quality": quality,
                    })
            hit["video_files"] = files
        return hits

    def _license_note(self) -> str:
        return "Pixabay Content License: free to use, no attribution required."  # noqa: ARG002 — normalized _parse_results converts pixabay "videos" → video_files
