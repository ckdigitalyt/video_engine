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

        scored: list[tuple[dict, float]] = []
        for video in results:
            # ── Resolution score ───────────────────────────────────────
            w = video.get("width", 0) or 0
            h = video.get("height", 0) or 0
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
            res = requests.get(self._base_url, params=params).json()
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
