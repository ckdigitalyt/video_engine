"""
Asset pipeline: chain-of-responsibility search for video assets.

Provider chain (in order):
  1. NASA   (images-api.nasa.gov)
  2. Pexels  (api.pexels.com/videos)
  3. Pixabay (pixabay.com/api/videos)
  4. Wikimedia (commons.wikimedia.org)
  5. Internet Archive (archive.org)
  6. Fallback (synthetic ken-burns clips)

Cache-first policy: before any provider API call, check
  cache/video/<query_hash>.mp4
for matching cached results.
"""

import hashlib, json, logging, os, random, re, time, urllib.parse, urllib.request
from dataclasses import dataclass, field, asdict
from typing import Optional
from pathlib import Path

# ---------------------------------------------------------------------------
# Structured per-shot logging
# ---------------------------------------------------------------------------

@dataclass
class ShotLogEntry:
    scene_number: int = 0
    beat_number: int = 0
    shot_number: int = 0
    search_query: str = ""
    provider: str = ""
    results_returned: int = 0
    selected_asset: str = ""
    rejection_reason: str = ""
    fallback_reason: str = ""
    final_video_path: str = ""
    duration_s: float = 0.0
    from_cache: bool = False

# Global shot log; reset at the start of each pipeline run
shot_log: list[ShotLogEntry] = []

def reset_shot_log():
    shot_log.clear()

def log_shot(**kw):
    entry = ShotLogEntry(**{k: v for k, v in kw.items() if k in ShotLogEntry.__dataclass_fields__})
    shot_log.append(entry)

def export_shot_log() -> list[dict]:
    return [asdict(e) for e in shot_log]

# ---------------------------------------------------------------------------
# Cache utilities
# ---------------------------------------------------------------------------

CACHE_DIR = Path("cache/video")
CACHE_DIR.mkdir(parents=True, exist_ok=True)
CACHE_INDEX_PATH = CACHE_DIR / "cache_index.json"

_cache_index: dict[str, str] = {}   # query_hash -> local mp4 filename

def _load_cache_index():
    global _cache_index
    if CACHE_INDEX_PATH.exists():
        try:
            with open(CACHE_INDEX_PATH) as f:
                _cache_index = json.load(f)
        except Exception:
            _cache_index = {}

def _save_cache_index():
    with open(CACHE_INDEX_PATH, "w") as f:
        json.dump(_cache_index, f, indent=2)

def _query_hash(query: str, provider: str) -> str:
    raw = f"{provider}:{query.strip().lower()}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]

def check_cache(query: str, provider: str) -> Optional[str]:
    """Return path to cached mp4 if it exists, else None."""
    _load_cache_index()
    fname = _cache_index.get(_query_hash(query, provider))
    if fname:
        p = CACHE_DIR / fname
        if p.exists():
            return str(p)
    return None

def write_cache(query: str, provider: str, local_path: str):
    """Register a local mp4 path as cached for a given query+provider combo."""
    _load_cache_index()
    fname = Path(local_path).name
    _cache_index[_query_hash(query, provider)] = fname
    _save_cache_index()

def cache_first(query: str) -> Optional[str]:
    """Check all providers' caches for this query. Return first hit."""
    _load_cache_index()
    for provider in ("nasa", "pexels", "pixabay", "wikimedia", "internet_archive"):
        fname = _cache_index.get(_query_hash(query, provider))
        if fname:
            p = CACHE_DIR / fname
            if p.exists():
                return str(p)
    return None

# ---------------------------------------------------------------------------
# NASA provider
# ---------------------------------------------------------------------------

NASA_BASE = "https://images-api.nasa.gov/search"

def _search_nasa(query: str) -> list[dict]:
    """Search NASA image/video API. Returns list of asset dicts."""
    params = urllib.parse.urlencode({"q": query, "media_type": "video", "page_size": 5})
    url = f"{NASA_BASE}?{params}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "ckdigitalyt/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
        items = data.get("collection", {}).get("items", [])
        results = []
        for item in items:
            links = item.get("links", [])
            video_link = None
            for link in links:
                href = link.get("href", "")
                if any(href.endswith(ext) for ext in (".mp4", ".mov", ".webm")):
                    video_link = href
                    break
            if video_link:
                results.append({
                    "url": video_link,
                    "title": item.get("data", [{}])[0].get("title", query),
                    "description": item.get("data", [{}])[0].get("description", ""),
                    "provider": "nasa",
                })
            # also check asset URL pattern
            nasa_id = item.get("data", [{}])[0].get("nasa_id")
            if nasa_id and not video_link:
                # Try to get asset manifest
                asset_url = f"https://images-api.nasa.gov/asset/{nasa_id}"
                try:
                    areq = urllib.request.Request(asset_url, headers={"User-Agent": "ckdigitalyt/1.0"})
                    with urllib.request.urlopen(areq, timeout=15) as aresp:
                        asset_data = json.loads(aresp.read())
                    for aitem in asset_data.get("collection", {}).get("items", []):
                        href = aitem.get("href", "")
                        if any(href.endswith(ext) for ext in (".mp4", ".mov", ".webm")):
                            results.append({
                                "url": href,
                                "title": item.get("data", [{}])[0].get("title", query),
                                "description": item.get("data", [{}])[0].get("description", ""),
                                "provider": "nasa",
                            })
                            break
                except Exception:
                    pass
        return results
    except Exception as e:
        logging.debug(f"NASA search error for '{query}': {e}")
        return []

# ---------------------------------------------------------------------------
# Pexels provider
# ---------------------------------------------------------------------------

PEXELS_BASE = "https://api.pexels.com/videos/search"
PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY", "")

def _search_pexels(query: str) -> list[dict]:
    if not PEXELS_API_KEY:
        return []
    params = urllib.parse.urlencode({"query": query, "per_page": 5})
    url = f"{PEXELS_BASE}?{params}"
    try:
        req = urllib.request.Request(url, headers={
            "Authorization": PEXELS_API_KEY,
            "User-Agent": "ckdigitalyt/1.0",
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
        results = []
        for video in data.get("videos", []):
            for f in video.get("video_files", []):
                if f.get("quality") in ("hd", "sd") and f.get("link"):
                    results.append({
                        "url": f["link"],
                        "title": query,
                        "description": video.get("url", ""),
                        "provider": "pexels",
                        "width": f.get("width", 0),
                        "height": f.get("height", 0),
                        "duration": f.get("duration", 0),
                    })
                    break
        return results
    except Exception as e:
        logging.debug(f"Pexels search error for '{query}': {e}")
        return []

# ---------------------------------------------------------------------------
# Pixabay provider
# ---------------------------------------------------------------------------

PIXABAY_BASE = "https://pixabay.com/api/videos"
PIXABAY_API_KEY = os.environ.get("PIXABAY_API_KEY", "")

def _search_pixabay(query: str) -> list[dict]:
    if not PIXABAY_API_KEY:
        return []
    params = urllib.parse.urlencode({"key": PIXABAY_API_KEY, "q": query, "per_page": 5})
    url = f"{PIXABAY_BASE}?{params}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "ckdigitalyt/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
        results = []
        for hit in data.get("hits", []):
            videos = hit.get("videos", {})
            for quality_key in ("large", "medium", "small", "tiny"):
                if quality_key in videos:
                    vinfo = videos[quality_key]
                    results.append({
                        "url": vinfo.get("url", ""),
                        "title": hit.get("tags", query),
                        "description": "",
                        "provider": "pixabay",
                        "width": vinfo.get("width", 0),
                        "height": vinfo.get("height", 0),
                        "duration": hit.get("duration", 0),
                    })
                    break
        return results
    except Exception as e:
        logging.debug(f"Pixabay search error for '{query}': {e}")
        return []

# ---------------------------------------------------------------------------
# Wikimedia provider
# ---------------------------------------------------------------------------

WIKIMEDIA_BASE = "https://commons.wikimedia.org/w/api.php"

def _search_wikimedia(query: str) -> list[dict]:
    params = urllib.parse.urlencode({
        "action": "query",
        "list": "search",
        "srsearch": query,
        "srnamespace": "6",
        "format": "json",
        "srlimit": 10,
    })
    url = f"{WIKIMEDIA_BASE}?{params}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "ckdigitalyt/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
        pages = data.get("query", {}).get("search", [])
        results = []
        for page in pages:
            title = page.get("title", "")
            # Get image info
            iparams = urllib.parse.urlencode({
                "action": "query",
                "titles": title,
                "prop": "imageinfo",
                "iiprop": "url|mime",
                "format": "json",
            })
            iurl = f"{WIKIMEDIA_BASE}?{iparams}"
            try:
                ireq = urllib.request.Request(iurl, headers={"User-Agent": "ckdigitalyt/1.0"})
                with urllib.request.urlopen(ireq, timeout=15) as iresp:
                    idata = json.loads(iresp.read())
                for _, infopage in idata.get("query", {}).get("pages", {}).items():
                    for ii in infopage.get("imageinfo", []):
                        iurl_val = ii.get("url", "")
                        mime = ii.get("mime", "")
                        if mime.startswith("video/"):
                            results.append({
                                "url": iurl_val,
                                "title": title,
                                "description": page.get("snippet", ""),
                                "provider": "wikimedia",
                            })
            except Exception:
                pass
        return results
    except Exception as e:
        logging.debug(f"Wikimedia search error for '{query}': {e}")
        return []

# ---------------------------------------------------------------------------
# Internet Archive provider
# ---------------------------------------------------------------------------

IA_BASE = "https://archive.org/advancedsearch.php"

def _search_ia(query: str) -> list[dict]:
    params = urllib.parse.urlencode({
        "q": query,
        "fl[]": "identifier,title,description",
        "rows": 5,
        "page": 1,
        "output": "json",
    })
    url = f"{IA_BASE}?{params}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "ckdigitalyt/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
        docs = data.get("response", {}).get("docs", [])
        results = []
        for doc in docs:
            identifier = doc.get("identifier", "")
            if not identifier:
                continue
            # Derive a video URL
            vid_url = f"https://archive.org/download/{identifier}/{identifier}.mp4"
            results.append({
                "url": vid_url,
                "title": doc.get("title", query),
                "description": doc.get("description", ""),
                "provider": "internet_archive",
            })
        return results
    except Exception as e:
        logging.debug(f"Internet Archive search error for '{query}': {e}")
        return []

# ---------------------------------------------------------------------------
# Fallback director — synthetic clips
# ---------------------------------------------------------------------------

from src.director.fallback_director import FallbackDirector

_fallback_director = None

def _search_fallback(query: str, scene_id: int = 0) -> list[dict]:
    """Generate a synthetic fallback clip and return as a single-item result list."""
    global _fallback_director
    if _fallback_director is None:
        _fallback_director = FallbackDirector()
    clip_path = _fallback_director.generate_clip(
        topic=query,
        scene_id=scene_id,
        output_dir=str(CACHE_DIR),
    )
    if clip_path and os.path.exists(clip_path):
        return [{
            "url": clip_path,
            "title": query,
            "description": f"Fallback clip for: {query}",
            "provider": "fallback",
        }]
    return []

# ---------------------------------------------------------------------------
# Provider registry
# ---------------------------------------------------------------------------

PROVIDERS = [
    ("nasa",             _search_nasa),
    ("pexels",           _search_pexels),
    ("pixabay",          _search_pixabay),
    ("wikimedia",        _search_wikimedia),
    ("internet_archive", _search_ia),
]

# ---------------------------------------------------------------------------
# Utility: download a video URL to a local file
# ---------------------------------------------------------------------------

def _download(url: str, dest: str) -> bool:
    """Download url to dest. Returns True on success."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "ckdigitalyt/1.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = resp.read()
        with open(dest, "wb") as f:
            f.write(data)
        return True
    except Exception as e:
        logging.debug(f"Download failed: {url[:80]} -> {e}")
        return False

# ---------------------------------------------------------------------------
# Main search orchestrator
# ---------------------------------------------------------------------------

def search_asset(
    query: str,
    scene_id: int = 0,
    beat_num: int = 0,
    shot_num: int = 0,
    scene_number: int = 0,
) -> tuple[Optional[str], str]:
    """
    Search for a video asset across all providers in chain order.

    Returns: (local_filepath, provider_name)
      - If a cached result exists for any provider, it is returned first.
      - Otherwise providers are tried in chain order.
      - If all providers fail, Fallback is used.
    """
    # --- Step 1: Check global cache (any provider) ---
    cached = cache_first(query)
    if cached:
        log_shot(
            scene_number=scene_number,
            beat_number=beat_num,
            shot_number=shot_num,
            search_query=query,
            provider="cache",
            results_returned=1,
            selected_asset=cached,
            final_video_path=cached,
            from_cache=True,
        )
        return cached, "cache"

    # --- Step 2: Try each external provider ---
    for provider_name, search_fn in PROVIDERS:
        # Check provider-specific cache first
        cached = check_cache(query, provider_name)
        if cached:
            log_shot(
                scene_number=scene_number,
                beat_number=beat_num,
                shot_number=shot_num,
                search_query=query,
                provider=f"{provider_name} (cached)",
                results_returned=1,
                selected_asset=cached,
                final_video_path=cached,
                from_cache=True,
            )
            return cached, provider_name

        # Hit the live API
        try:
            results = search_fn(query)
        except Exception as e:
            log_shot(
                scene_number=scene_number,
                beat_number=beat_num,
                shot_number=shot_num,
                search_query=query,
                provider=provider_name,
                results_returned=0,
                rejection_reason=f"API error: {e}",
                fallback_reason=f"{provider_name} failed",
            )
            continue

        if results:
            selected = results[0]
            url = selected["url"]
            # Download
            ext = os.path.splitext(urllib.parse.urlparse(url).path)[1] or ".mp4"
            fname = f"{provider_name}_{_query_hash(query, provider_name)}{ext}"
            dest = str(CACHE_DIR / fname)
            if _download(url, dest):
                write_cache(query, provider_name, dest)
                log_shot(
                    scene_number=scene_number,
                    beat_number=beat_num,
                    shot_number=shot_num,
                    search_query=query,
                    provider=provider_name,
                    results_returned=len(results),
                    selected_asset=url,
                    final_video_path=dest,
                    from_cache=False,
                )
                return dest, provider_name
            else:
                log_shot(
                    scene_number=scene_number,
                    beat_number=beat_num,
                    shot_number=shot_num,
                    search_query=query,
                    provider=provider_name,
                    results_returned=len(results),
                    selected_asset=url,
                    rejection_reason="Download failed",
                    fallback_reason=f"{provider_name} download failed",
                )
        else:
            log_shot(
                scene_number=scene_number,
                beat_number=beat_num,
                shot_number=shot_num,
                search_query=query,
                provider=provider_name,
                results_returned=0,
                rejection_reason="No results",
                fallback_reason=f"{provider_name} returned 0 results",
            )

    # --- Step 3: Fallback ---
    fallback_results = _search_fallback(query, scene_id)
    if fallback_results:
        selected = fallback_results[0]
        local_path = selected["url"]
        log_shot(
            scene_number=scene_number,
            beat_number=beat_num,
            shot_number=shot_num,
            search_query=query,
            provider="fallback",
            results_returned=1,
            selected_asset=local_path,
            final_video_path=local_path,
            fallback_reason="All external providers exhausted",
        )
        return local_path, "fallback"

    log_shot(
        scene_number=scene_number,
        beat_number=beat_num,
        shot_number=shot_num,
        search_query=query,
        provider="fallback",
        results_returned=0,
        rejection_reason="Fallback also failed",
        fallback_reason="Fallback generation failed",
    )
    return None, "none"
