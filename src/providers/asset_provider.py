"""
asset_provider.py — Abstract asset provider and concrete implementations.

Defines the AssetProvider interface, then implements:
- PexelsProvider (stock video search / download)
"""

import os
import requests
from abc import ABC, abstractmethod

from src.utils.config import get_config


# ── Abstract base ──────────────────────────────────────────────────────────

class AssetProvider(ABC):
    """Interface for media-asset search and download."""

    @abstractmethod
    def search(self, query: str, **kwargs) -> list:
        """
        Search for assets matching *query*.

        Returns a list of item dicts; the exact schema is provider-specific.
        """
        ...

    @abstractmethod
    def download(self, url: str, output_path: str) -> str:
        """
        Download from *url* to *output_path*.

        Returns the local path of the downloaded file.
        """
        ...


# ── Pexels ─────────────────────────────────────────────────────────────────

class PexelsProvider(AssetProvider):
    """Asset provider backed by the Pexels video API, with SQLite cache
    and deterministic asset quality scoring."""

    def __init__(self, cache=None):
        from src.assets.asset_cache import AssetCache as _AC
        self._api_key = os.environ.get("PEXELS_API_KEY")
        self._base_url = get_config("providers.pexels.base_url", "https://api.pexels.com/videos/search")
        self._per_page = get_config("providers.pexels.per_page", 10)
        self._orientation = get_config("providers.pexels.orientation", "landscape")
        self._cache = cache or _AC()
        self._last_query: str | None = None

    # ── Public API ─────────────────────────────────────────────────────

    def search(self, query: str, **kwargs) -> list:
        """Search Pexels for *query*, score up to ``per_page`` candidates,
        and return results sorted by quality (best first).

        Accepts optional ``target_duration`` (in seconds) via kwargs
        to inform duration-match scoring.
        """
        target_duration = kwargs.get("target_duration")

        # ── Check cache first ──────────────────────────────────────────
        cached = self._cache.lookup("pexels", query)
        if cached is not None:
            print(f"-> Cache HIT: '{query}' → {cached['local_path']}")
            return [{"video_files": [{"link": cached["asset_url"]}]}]

        print(f"-> Cache MISS: '{query}' — calling Pexels API")
        headers = {"Authorization": self._api_key}
        url = f"{self._base_url}?query={query}&per_page={self._per_page}&orientation={self._orientation}"
        res = requests.get(url, headers=headers).json()
        results = res.get("videos", [])

        if not results:
            return results

        # ── Score and sort candidates ──────────────────────────────────
        scored = self._score_candidates(results, target_duration)
        scored.sort(key=lambda x: x[1], reverse=True)
        sorted_results = [item for item, _ in scored]

        # Log scores for transparency
        for i, (item, score) in enumerate(scored):
            dur = item.get("duration", 0)
            w, h = item.get("width", 0), item.get("height", 0)
            label = f"  Candidate {i+1}: id={item['id']} {w}x{h} dur={dur}s score={score:.3f}"
            if i == 0:
                label += " ← SELECTED"
            print(label)

        # Pre-register the best-scoring result URL so a future lookup
        # (e.g. on a re-run of the same query) finds it, even before download.
        best_url = sorted_results[0]["video_files"][0]["link"]
        self._cache.register("pexels", query, best_url)
        self._last_query = query

        return sorted_results

    def download(self, url: str, output_path: str) -> str:
        # ── Skip download if file already exists ───────────────────────
        if os.path.exists(output_path):
            print(f"-> Already on disk: {output_path}")
            if self._last_query:
                self._cache.touch("pexels", self._last_query)
            return output_path

        # ── Download ───────────────────────────────────────────────────
        print("-> Downloading from Pexels…")
        resp = requests.get(url)
        with open(output_path, "wb") as f:
            f.write(resp.content)

        # Update cache with the local path so future lookups resolve fully
        # Uses the full primary key (provider, search_query) to prevent
        # collisions when different queries share the same Pexels video URL.
        if self._last_query:
            self._cache.update_local_path("pexels", self._last_query, url, output_path)
        print(f"-> Saved: {output_path}")

        return output_path

    # ── Asset scoring ──────────────────────────────────────────────────

    @staticmethod
    def _score_candidates(
        results: list[dict],
        target_duration: float | None = None,
    ) -> list[tuple[dict, float]]:
        """
        Score each Pexels video candidate on resolution, duration match,
        and available quality tier.

        The scoring formula is::

            total = w_res * res_score + w_dur * dur_score + w_hd * hd_score

        where each sub-score is normalised to [0, 1] and weights are
        loaded from ``configs/providers.yaml``.

        Returns a list of (video_dict, score) tuples.
        """
        w_res = get_config("providers.pexels.scoring.resolution_weight", 0.40)
        w_dur = get_config("providers.pexels.scoring.duration_match_weight", 0.40)
        w_hd = get_config("providers.pexels.scoring.hd_bonus_weight", 0.20)
        # v13 (expert review rec #3): hard floor on source resolution — a
        # 640x360 clip upscaled into 1920x1080 is visible softness.  Any
        # candidate below the floor is REJECTED outright (score 0) so the
        # router moves to the next provider instead of shipping soft video.
        _min_w = get_config("providers.pexels.min_width", 1920)
        _min_h = get_config("providers.pexels.min_height", 1080)

        scored: list[tuple[dict, float]] = []
        for video in results:
            # ── Resolution floor (rec #3) ──────────────────────────────
            w = video.get("width", 0) or 0
            h = video.get("height", 0) or 0
            if (_min_w and w and w < _min_w) or (_min_h and h and h < _min_h):
                scored.append((video, 0.0))  # below floor: reject
                continue
            # ── Resolution score ───────────────────────────────────────
            if w * h <= 0:
                res_score = 0.0
            else:
                # Normalise to 1920x1080, cap at 1.0
                res_score = min((w * h) / (1920.0 * 1080.0), 1.0)

            # ── Duration match score ───────────────────────────────────
            dur = video.get("duration", 0) or 0
            if target_duration and target_duration > 0 and dur > 0:
                ratio = dur / target_duration
                if ratio < 1.0:
                    # Penalise clips shorter than the target (need freeze-frame)
                    dur_score = max(0.0, 1.0 - (1.0 - ratio) * 2.0)
                else:
                    # Penalise clips longer than target, less harshly
                    dur_score = max(0.0, 1.0 - (ratio - 1.0) * 0.5)
            else:
                # No target or unknown duration → neutral score
                dur_score = 0.5

            # ── HD bonus ───────────────────────────────────────────────
            video_files = video.get("video_files", [])
            has_hd = any(vf.get("quality") == "hd" for vf in video_files)
            hd_score = 1.0 if has_hd else 0.0

            # ── Weighted total ─────────────────────────────────────────
            total = w_res * res_score + w_dur * dur_score + w_hd * hd_score
            scored.append((video, round(total, 4)))

        return scored


# ── Pixabay ────────────────────────────────────────────────────────────

class PixabayProvider(AssetProvider):
    """Asset provider backed by the Pixabay video API, with SQLite cache
    and the same deterministic asset quality scoring as Pexels.

    Pixabay video API documentation:
        https://pixabay.com/api/docs/#api_videos_search

    Requires the ``PIXABAY_API_KEY`` environment variable.
    When the key is absent the provider silently falls back to empty
    results (so the AssetRouter can continue to the next provider).
    """

    def __init__(self, cache=None):
        from src.assets.asset_cache import AssetCache as _AC
        self._api_key = os.environ.get("PIXABAY_API_KEY", "")
        self._base_url = get_config(
            "providers.pixabay.base_url",
            "https://pixabay.com/api/videos",
        )
        self._per_page = get_config("providers.pixabay.per_page", 10)
        self._orientation = get_config("providers.pixabay.orientation", "horizontal")
        self._safesearch = get_config("providers.pixabay.safesearch", "true")
        self._min_width = get_config("providers.pixabay.min_width", 1920)
        self._cache = cache or _AC()
        self._last_query: str | None = None

    # ── Public API ─────────────────────────────────────────────────────

    def search(self, query: str, **kwargs) -> list:
        """Search Pixabay for *query*, normalise results to the internal
        asset model, score candidates, and return results sorted by
        quality (best first).

        Accepts optional ``target_duration`` (in seconds) via kwargs.
        Returns an empty list when the API key is missing, the query
        is empty, or no results are found.
        """
        if not self._api_key:
            print("-> Pixabay: no API key configured — skipping.")
            return []

        if not query:
            return []

        target_duration = kwargs.get("target_duration")

        # ── Check cache first ──────────────────────────────────────────
        cached = self._cache.lookup("pixabay", query)
        if cached is not None:
            print(f"-> Pixabay Cache HIT: '{query}' → {cached['local_path']}")
            return [{"video_files": [{"link": cached["asset_url"]}]}]

        print(f"-> Pixabay Cache MISS: '{query}' — calling Pixabay API")
        params = {
            "key": self._api_key,
            "q": query,
            "per_page": self._per_page,
            "orientation": self._orientation,
            "safesearch": self._safesearch,
            "min_width": self._min_width,
        }
        try:
            headers = {"User-Agent": "VideoEngine/1.0"}
            res = requests.get(self._base_url, params=params, headers=headers).json()
        except Exception as e:
            print(f"-> Pixabay API request failed: {e}")
            return []

        hits = res.get("hits", [])
        if not hits:
            return []

        # ── Normalise to internal asset model ──────────────────────────
        normalised = [_normalise_pixabay_hit(hit) for hit in hits]

        # ── Score and sort candidates ──────────────────────────────────
        scored = PexelsProvider._score_candidates(normalised, target_duration)
        scored.sort(key=lambda x: x[1], reverse=True)
        sorted_results = [item for item, _ in scored]

        # Log scores for transparency
        for i, (item, score) in enumerate(scored):
            dur = item.get("duration", 0)
            w, h = item.get("width", 0), item.get("height", 0)
            label = f"  Pixabay Candidate {i+1}: id={item['id']} {w}x{h} dur={dur}s score={score:.3f}"
            if i == 0:
                label += " ← SELECTED"
            print(label)

        # Pre-register best result in cache
        best_url = sorted_results[0]["video_files"][0]["link"]
        self._cache.register("pixabay", query, best_url)
        self._last_query = query

        return sorted_results

    def download(self, url: str, output_path: str) -> str:
        # ── Skip download if file already exists ───────────────────────
        if os.path.exists(output_path):
            print(f"-> Already on disk: {output_path}")
            if self._last_query:
                self._cache.touch("pixabay", self._last_query)
            return output_path

        # ── Download ───────────────────────────────────────────────────
        print("-> Downloading from Pixabay…")
        resp = requests.get(url)
        with open(output_path, "wb") as f:
            f.write(resp.content)

        if self._last_query:
            self._cache.update_local_path("pixabay", self._last_query, url, output_path)
        print(f"-> Saved: {output_path}")

        return output_path


# ── Normalisation helper ───────────────────────────────────────────────


def _normalise_pixabay_hit(hit: dict) -> dict:
    """Convert a raw Pixabay API hit dict to the internal asset model
    used by ``PexelsProvider._score_candidates``.

    The normalised dict has the same top-level keys as a Pexels result
    (``id``, ``width``, ``height``, ``duration``, ``video_files``) so
    that the rest of the pipeline treats them identically.
    """
    # Determine video quality tiers present in this hit
    videos = hit.get("videos", {})
    video_files = []

    # Pixabay returns videos in multiple quality tiers
    for quality_key, quality_label in [
        ("large", "hd"),
        ("medium", "sd"),
        ("small", "sd"),
    ]:
        entry = videos.get(quality_key)
        if entry and entry.get("url"):
            video_files.append({
                "link": entry["url"],
                "quality": quality_label,
                "width": entry.get("width", 0),
                "height": entry.get("height", 0),
                "file_size": entry.get("size", 0),
            })

    # Use the largest available video for top-level dimensions
    best_video = videos.get("large") or videos.get("medium") or videos.get("small")
    width = (best_video or {}).get("width", 0) or 0
    height = (best_video or {}).get("height", 0) or 0
    duration = hit.get("duration", 0) or 0

    return {
        "id": hit.get("id", 0),
        "width": int(width),
        "height": int(height),
        "duration": duration,
        "video_files": video_files,
        # Preserve original metadata for debugging
        "_raw": {
            "tags": hit.get("tags", ""),
            "views": hit.get("views", 0),
            "downloads": hit.get("downloads", 0),
            "user": hit.get("user", ""),
        },
    }


# ── NASA Image and Video Library ───────────────────────────────────────

class NasaMediaProvider(AssetProvider):
    """Asset provider backed by the NASA Image and Video Library API.

    NASA API: https://images-api.nasa.gov
    Documentation: https://api.nasa.gov/

    Returns video assets from NASA's public media library.
    Requires the ``NASA_API_KEY`` environment variable (use "DEMO_KEY"
    for limited access).
    """

    def __init__(self):
        from src.assets.asset_cache import AssetCache as _AC
        self._api_key = os.environ.get("NASA_API_KEY", "DEMO_KEY")
        self._base_url = "https://images-api.nasa.gov/search"
        self._media_type = "video"
        self._cache = _AC()
        self._last_query: str | None = None

    def search(self, query: str, **kwargs) -> list:
        """Search NASA media library for *query*.

        Returns normalised result dicts matching the internal asset model
        (same ``video_files`` structure as Pexels).
        """
        if not query:
            return []

        cached = self._cache.lookup("nasa", query)
        if cached is not None:
            print(f"-> NASA Cache HIT: '{query}'")
            return [{"video_files": [{"link": cached["asset_url"]}]}]

        print(f"-> NASA Cache MISS: '{query}' — calling NASA API")
        params = {
            "q": query,
            "media_type": self._media_type,
            "page": 1,
            "page_size": 10,
        }
        try:
            headers = {"User-Agent": "VideoEngine/1.0"}
            res = requests.get(self._base_url, params=params, headers=headers).json()
        except Exception as e:
            print(f"-> NASA API request failed: {e}")
            return []

        items = res.get("collection", {}).get("items", [])
        results = _normalise_nasa_items(items)

        if not results:
            return results

        # Pre-register best result in cache
        best_url = results[0]["video_files"][0]["link"]
        self._cache.register("nasa", query, best_url)
        self._last_query = query

        for i, item in enumerate(results[:5]):
            dur = item.get("duration", 0)
            w, h = item.get("width", 0), item.get("height", 0)
            print(f"  NASA Candidate {i+1}: id={item['id']} {w}x{h} dur={dur}s")

        return results

    def download(self, url: str, output_path: str) -> str:
        if os.path.exists(output_path):
            print(f"-> Already on disk: {output_path}")
            if self._last_query:
                self._cache.touch("nasa", self._last_query)
            return output_path

        print("-> Downloading from NASA…")
        resp = requests.get(url, stream=True)
        with open(output_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)

        if self._last_query:
            self._cache.update_local_path("nasa", self._last_query, url, output_path)
        print(f"-> Saved: {output_path}")
        return output_path


def _normalise_nasa_items(items: list) -> list:
    """Convert NASA API items to the internal asset model.

    Fetches actual video URLs from the NASA asset endpoint, falling back
    to thumbnail images when the asset endpoint fails.
    """
    results = []
    for item in items:
        data_list = item.get("data", [])
        if not data_list:
            continue
        data = data_list[0]

        nasa_id = data.get("nasa_id", "")
        title = data.get("title", "")
        description = data.get("description", "")
        date_created = data.get("date_created", "")

        # Fetch actual video URLs from the asset endpoint
        video_files = []
        try:
            asset_resp = requests.get(
                f"https://images-api.nasa.gov/asset/{nasa_id}",
                timeout=10,
            )
            if asset_resp.status_code == 200:
                asset_data = asset_resp.json()
                asset_items = asset_data.get("collection", {}).get("items", [])
                for ai in asset_items:
                    href = ai.get("href", "")
                    if href.endswith(".mp4"):
                        quality = "hd" if "orig" in href else "sd"
                        video_files.append({
                            "link": href,
                            "quality": quality,
                            "width": 1920,
                            "height": 1080,
                            "file_size": 0,
                        })
        except Exception:
            pass

        # Fallback: use thumbnail images from search response
        if not video_files:
            links = item.get("links", [])
            for link in links:
                href = link.get("href", "")
                if not href:
                    continue
                # Only include actual image files (not captions/subtitles)
                if any(href.endswith(ext) for ext in [".jpg", ".png", ".jpeg"]):
                    video_files.append({
                        "link": href,
                        "quality": "hd" if "large" in href else "sd",
                        "width": 0,
                        "height": 0,
                        "file_size": 0,
                    })

        if not video_files:
            continue

        results.append({
            "id": nasa_id,
            "width": 1920,
            "height": 1080,
            "duration": 30.0,
            "video_files": video_files,
            "_raw": {
                "title": title,
                "description": description,
                "date_created": date_created,
                "nasa_id": nasa_id,
            },
        })
    return results


# ── Wikimedia Commons ──────────────────────────────────────────────────

class WikimediaCommonsProvider(AssetProvider):
    """Asset provider backed by the Wikimedia Commons API.

    Returns images from Wikimedia Commons.  For history category, these
    are typically public-domain historical images rendered with Ken Burns
    effects.

    API: https://commons.wikimedia.org/w/api.php
    """

    def __init__(self):
        from src.assets.asset_cache import AssetCache as _AC
        self._base_url = "https://commons.wikimedia.org/w/api.php"
        self._cache = _AC()
        self._last_query: str | None = None
        # Force image mode for Wikimedia
        self._image_mode = True

    def search(self, query: str, **kwargs) -> list:
        """Search Wikimedia Commons for images matching *query*.

        Returns normalised result dicts with a single ``video_files``
        entry that points to the image URL.  The renderer will apply
        Ken Burns motion to still images.
        """
        if not query:
            return []

        cached = self._cache.lookup("wikimedia", query)
        if cached is not None:
            print(f"-> Wikimedia Cache HIT: '{query}'")
            return [{"_image": True, "video_files": [{"link": cached["asset_url"]}]}]

        print(f"-> Wikimedia Cache MISS: '{query}' — calling Wikimedia API")
        params = {
            "action": "query",
            "format": "json",
            "list": "search",
            "srsearch": query,
            "srnamespace": 6,
            "srlimit": 10,
            "srprop": "size|timestamp",
        }
        try:
            headers = {"User-Agent": "VideoEngine/1.0"}
            raw_resp = requests.get(self._base_url, params=params, headers=headers, timeout=15)
            # Check if response is HTML (rate limiting) rather than JSON
            for attempt in range(3):
                content_type = raw_resp.headers.get("Content-Type", "")
                if "text/html" in content_type or raw_resp.status_code == 429:
                    import time
                    wait = 3 * (attempt + 1)
                    print(f"-> Wikimedia API rate limited, retry {attempt+1} in {wait}s...")
                    time.sleep(wait)
                    raw_resp = requests.get(self._base_url, params=params, headers=headers, timeout=15)
                else:
                    break
            res = raw_resp.json()
        except Exception as e:
            print(f"-> Wikimedia API request failed: {e}")
            return []

        query_results = res.get("query", {}).get("search", [])
        if not query_results:
            return []

        # Get image info URLs for the found pages
        page_ids = [str(r["pageid"]) for r in query_results[:10]]
        info_params = {
            "action": "query",
            "format": "json",
            "pageids": "|".join(page_ids),
            "prop": "imageinfo",
            "iiprop": "url|size|mime",
            "iiurlwidth": 1920,
        }
        try:
            raw_info = requests.get(self._base_url, params=info_params, headers=headers, timeout=15)
            for attempt in range(3):
                content_type = raw_info.headers.get("Content-Type", "")
                if "text/html" in content_type or raw_info.status_code == 429:
                    import time
                    wait = 3 * (attempt + 1)
                    print(f"-> Wikimedia image info rate limited, retry {attempt+1} in {wait}s...")
                    time.sleep(wait)
                    raw_info = requests.get(self._base_url, params=info_params, headers=headers, timeout=15)
                else:
                    break
            info_res = raw_info.json()
        except Exception as e:
            print(f"-> Wikimedia image info request failed: {e}")
            return []

        pages = info_res.get("query", {}).get("pages", {})
        results = []
        for page_id_str, page_data in pages.items():
            image_info = page_data.get("imageinfo", [])
            if not image_info:
                continue
            info = image_info[0]
            url = info.get("url", "")
            thumb_url = info.get("thumburl", url)

            results.append({
                "id": page_id_str,
                "_image": True,
                "width": info.get("width", 0) or 1920,
                "height": info.get("height", 0) or 1080,
                "duration": 10.0,
                "video_files": [{
                    "link": url,
                    "quality": "hd",
                    "width": info.get("width", 0) or 1920,
                    "height": info.get("height", 0) or 1080,
                    "file_size": info.get("size", 0),
                }],
                "_raw": {
                    "thumb_url": thumb_url,
                    "mime": info.get("mime", ""),
                    "page_title": page_data.get("title", ""),
                },
            })

        if not results:
            return results

        best_url = results[0]["video_files"][0]["link"]
        self._cache.register("wikimedia", query, best_url)
        self._last_query = query

        for i, item in enumerate(results[:5]):
            w, h = item.get("width", 0), item.get("height", 0)
            print(f"  Wikimedia Candidate {i+1}: id={item['id']} {w}x{h}")

        return results

    def download(self, url: str, output_path: str) -> str:
        if os.path.exists(output_path):
            print(f"-> Already on disk: {output_path}")
            if self._last_query:
                self._cache.touch("wikimedia", self._last_query)
            return output_path

        print("-> Downloading from Wikimedia…")
        resp = requests.get(url, stream=True)
        with open(output_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)

        if self._last_query:
            self._cache.update_local_path("wikimedia", self._last_query, url, output_path)
        print(f"-> Saved: {output_path}")
        return output_path
