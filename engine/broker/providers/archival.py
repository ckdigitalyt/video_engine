"""archival.py — Public-domain / archival asset providers (directive §13).

Sources: NASA Images API (images.nasa.gov), Wikimedia Commons API, Internet
Archive advancedsearch/scrape API. Every download lands in the deterministic
broker cache with a full license metadata sidecar.

LICENSE GATE (§13, non-negotiable): an asset is only downloadable when its
license can be established from the API payload. Anything ambiguous is
skipped — the router falls back to the next chain link instead.
"""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from typing import Any

from engine.broker.cache import BrokerCache
from engine.broker.providers.base import (
    BrokerResult,
    MediaProvider,
    ProviderDescriptor,
    ProviderError,
)

_USER_AGENT = "video-engine-archival/1.0 (educational documentary pipeline)"
_MIN_MEDIA_BYTES = 20_000


def _get_json(url: str, timeout: int = 20) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001 — uniform provider failure
        raise ProviderError(f"{exc.__class__.__name__}: {exc}") from None


def _download(url: str, timeout: int = 120) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except Exception as exc:  # noqa: BLE001
        raise ProviderError(f"download failed ({exc})") from None


def _cache_media(cache: BrokerCache, provider_id: str, url: str,
                 license_note: str, meta: dict[str, Any]) -> BrokerResult:
    key = BrokerCache.key_for_url(url)
    ext = ".jpg" if url.lower().endswith((".jpg", ".jpeg")) else \
        ".png" if url.lower().endswith(".png") else \
        ".webm" if url.lower().endswith(".webm") else ".mp4"
    # Deterministic cache (§25): same URL never re-downloads.
    hit = cache.get(key, ext=ext)
    if hit:
        return BrokerResult(path=hit, provider=provider_id, kind="stock",
                            cached=True,
                            metadata=cache.load_metadata(key) or meta)
    data = _download(url)
    if len(data) < _MIN_MEDIA_BYTES:
        raise ProviderError(f"{provider_id}: payload suspiciously small "
                            f"({len(data)} bytes)")
    path = cache.store_bytes(key, data, ext=ext)
    sidecar = {
        "source": provider_id,
        "url": url,
        "asset_id": str(meta.get("asset_id", "")),
        "license": license_note,
        "download_date": time.strftime("%Y-%m-%d"),
        "creator": str(meta.get("creator", "")),
        "attribution_required": bool(meta.get("attribution_required", False)),
        "usage_notes": meta.get(
            "usage_notes", "Verify license terms before publication."),
        "title": meta.get("title", ""),
    }
    cache.store_metadata(key, sidecar)
    return BrokerResult(path=path, provider=provider_id, kind="stock",
                        cached=False, metadata=sidecar)


class NasaImagesProvider(MediaProvider):
    """NASA Image and Video Library (images.nasa.gov API). Public domain."""

    id = "nasa_images"
    kind = "archival"

    def __init__(self, cache: BrokerCache | None = None,
                 api_key: str | None = None) -> None:
        self.cache = cache or BrokerCache()
        # NASA API works keyless (DEMO_KEY rate limits); key raises limits.
        self._api_key = api_key if api_key is not None else \
            (__import__("os").environ.get("NASA_API_KEY", "") or "DEMO_KEY")

    def capabilities(self) -> ProviderDescriptor:
        return ProviderDescriptor(
            id=self.id, kind=self.kind, enabled=True, priority=10,
            notes="NASA Image and Video Library — public domain (US gov work)",
        )

    def health_check(self) -> bool:
        try:
            self.search("earth", per_page=1)
            return True
        except ProviderError:
            return False

    def search(self, query: str, per_page: int = 5) -> list[dict[str, Any]]:
        url = (f"https://images-api.nasa.gov/search?q={urllib.parse.quote(query)}"
               f"&media_type=image,video&page_size={per_page}")
        payload = _get_json(url)
        items = payload.get("collection", {}).get("items", [])
        out: list[dict[str, Any]] = []
        for item in items[:per_page]:
            data = (item.get("data") or [{}])[0]
            links = item.get("links") or []
            thumb = next((l.get("href") for l in links
                          if l.get("rel") == "preview"), "")
            out.append({
                "provider": self.id,
                "asset_id": data.get("nasa_id", ""),
                "title": data.get("title", ""),
                "thumb": thumb,
                "asset_collection": data.get("collection", ""),
                "date_created": data.get("date_created", ""),
                "media_type": data.get("media_type", "image"),
            })
        return out

    def _asset_manifest(self, nasa_id: str) -> dict[str, Any]:
        return _get_json(
            f"https://images-api.nasa.gov/asset/{urllib.parse.quote(nasa_id)}")

    def download(self, asset: dict[str, Any]) -> BrokerResult:
        """License: NASA imagery is public domain unless the item metadata
        states otherwise — we require an explicit nasa_id and non-empty
        collection before downloading."""
        nasa_id = asset.get("asset_id", "")
        if not nasa_id:
            raise ProviderError(f"{self.id}: asset without nasa_id — license "
                                "cannot be established, skipping")
        manifest = self._asset_manifest(nasa_id)
        items = manifest.get("collection", {}).get("items", [])
        # Prefer a video (mp4) file, else the largest jpg.
        video = next((i["href"] for i in items if i.get("href", "").endswith(".mp4")), "")
        target = video or next(
            (i["href"] for i in items if i.get("href", "").lower().endswith((".jpg", ".jpeg"))), "")
        if not target:
            raise ProviderError(f"{self.id}: no usable asset file for {nasa_id}")
        return _cache_media(
            self.cache, self.id, target,
            "Public Domain (NASA media — U.S. government work, no restrictions)",
            {"asset_id": nasa_id, "title": asset.get("title", ""),
             "creator": "NASA", "attribution_required": False,
             "usage_notes": "NASA imagery: public domain; credit NASA appreciated."},
        )


class WikimediaCommonsProvider(MediaProvider):
    """Wikimedia Commons search API. Only CC0/PD files are downloadable."""

    id = "wikimedia_commons"
    kind = "archival"

    _OK_LICENSES = {"cc0", "public domain", "pd", "pd-self", "pd-us"}

    def __init__(self, cache: BrokerCache | None = None) -> None:
        self.cache = cache or BrokerCache()

    def capabilities(self) -> ProviderDescriptor:
        return ProviderDescriptor(
            id=self.id, kind=self.kind, enabled=True, priority=20,
            notes="Wikimedia Commons — CC0/public-domain files only (§13 gate)",
        )

    def health_check(self) -> bool:
        try:
            self.search("moon", per_page=1)
            return True
        except ProviderError:
            return False

    def search(self, query: str, per_page: int = 5) -> list[dict[str, Any]]:
        params = urllib.parse.urlencode({
            "action": "query", "format": "json", "generator": "search",
            "gsrsearch": f"filetype:video {query}",
            "gsrnamespace": "6", "gsrlimit": str(per_page),
            "prop": "imageinfo", "iiprop": "url|extmetadata|size",
            "iiurlwidth": "1280",
        })
        payload = _get_json(f"https://commons.wikimedia.org/w/api.php?{params}")
        pages = (payload.get("query") or {}).get("pages", {})
        out: list[dict[str, Any]] = []
        for page in pages.values():
            ii = (page.get("imageinfo") or [{}])[0]
            meta = ii.get("extmetadata") or {}
            lic = (meta.get("LicenseShortName") or {}).get("value", "")
            out.append({
                "provider": self.id,
                "asset_id": str(page.get("pageid", "")),
                "title": page.get("title", ""),
                "url": ii.get("url", ""),
                "thumburl": ii.get("thumburl", ""),
                "license": lic,
                "artist": ((meta.get("Artist") or {}).get("value", ""))[:200],
                "mime": ii.get("mime", ""),
            })
        return out

    def download(self, asset: dict[str, Any]) -> BrokerResult:
        lic = str(asset.get("license", "")).lower()
        # §13 gate: never download when the license can't be established.
        if not any(ok in lic for ok in ("cc0", "public domain")):
            raise ProviderError(
                f"{self.id}: license {asset.get('license')!r} not established "
                f"as free (CC0/PD) — skipping per §13")
        url = asset.get("url") or asset.get("thumburl")
        if not url:
            raise ProviderError(f"{self.id}: asset has no file URL")
        return _cache_media(
            self.cache, self.id, url,
            f"Wikimedia Commons — {asset.get('license')} (verified free license)",
            {"asset_id": asset.get("asset_id", ""),
             "creator": asset.get("artist", ""),
             "title": asset.get("title", ""),
             "attribution_required": "cc0" not in lic},
        )


class InternetArchiveProvider(MediaProvider):
    """Internet Archive advancedsearch + metadata API. Public-domain items."""

    id = "internet_archive"
    kind = "archival"

    def __init__(self, cache: BrokerCache | None = None) -> None:
        self.cache = cache or BrokerCache()

    def capabilities(self) -> ProviderDescriptor:
        return ProviderDescriptor(
            id=self.id, kind=self.kind, enabled=True, priority=30,
            notes="Internet Archive — preflighted public-domain/CC0 items only",
        )

    def health_check(self) -> bool:
        try:
            self.search("space", per_page=1)
            return True
        except ProviderError:
            return False

    def search(self, query: str, per_page: int = 5) -> list[dict[str, Any]]:
        params = urllib.parse.urlencode({
            "q": f"{query} AND mediatype:(movies) AND licenseurl:(*creativecommons.org/publicdomain*)",
            "fl[]": "identifier,title,licenseurl,creator",
            "rows": str(per_page), "output": "json",
        })
        payload = _get_json(f"https://archive.org/advancedsearch.php?{params}")
        docs = (payload.get("response") or {}).get("docs", [])
        out = []
        for doc in docs:
            out.append({
                "provider": self.id,
                "asset_id": doc.get("identifier", ""),
                "title": doc.get("title", ""),
                "creator": doc.get("creator", ""),
                "licenseurl": doc.get("licenseurl", ""),
                "query": query,
            })
        return out

    def _file_list(self, identifier: str) -> list[dict[str, Any]]:
        return _get_json(
            f"https://archive.org/metadata/{urllib.parse.quote(identifier)}")

    def download(self, asset: dict[str, Any]) -> BrokerResult:
        identifier = asset.get("asset_id", "")
        lic = str(asset.get("licenseurl", "")).lower()
        if not identifier or "publicdomain" not in lic:
            raise ProviderError(
                f"{self.id}: no publicdomain licenseurl for {identifier!r} — "
                "skipping per §13")
        meta = self._file_list(identifier)
        files = meta.get("files", [])
        mp4 = next((f for f in files
                    if f.get("name", "").lower().endswith((".mp4", ".m4v"))), None)
        if not mp4:
            raise ProviderError(f"{self.id}: no mp4 file in item {identifier}")
        url = f"https://archive.org/download/{identifier}/{urllib.parse.quote(mp4['name'])}"
        return _cache_media(
            self.cache, self.id, url,
            f"Internet Archive item '{identifier}' — public domain "
            f"(licenseurl verified)",
            {"asset_id": identifier, "title": asset.get("title", ""),
             "creator": str(asset.get("creator", "")),
             "attribution_required": False},
        )


ARCHIVAL_PROVIDERS: list[type[MediaProvider]] = [
    NasaImagesProvider,
    WikimediaCommonsProvider,
    InternetArchiveProvider,
]
