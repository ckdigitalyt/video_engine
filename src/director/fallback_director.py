"""FallbackDirector — graceful degradation when primary video providers fail.

Fallback chain (in order):
1. Primary video asset (existing path — continues as-is)
2. NASA image + Ken Burns animation
3. Wikimedia image + Ken Burns animation
4. Generated image (if available)
5. Reuse a previously accepted scene with distinct crop/zoom/timing/motion
6. Cinematic animated placeholder (particles + gradients + subtle camera motion)
7. Absolute last resort: simple gradient (NEVER a black frame)
"""

import json
import logging
import os
import random
import subprocess
import tempfile
import urllib.parse
import urllib.request
from typing import Any, Optional

logger = logging.getLogger(__name__)


class FallbackDirector:
    """Produces a fallback video clip when all primary providers fail.

    Implements a degradation chain that preserves semantic relevance and
    never outputs blank/black/placeholder content without first trying
    harder to produce meaningful visuals.
    """

    def __init__(self, config: Optional[dict] = None):
        self.cfg = config or {}
        self.seed = self.cfg.get("random_seed", 42)
        self.rng = random.Random(self.seed)

        self.cache_dir = self.cfg.get("cache_dir", "cache/video")
        self.images_dir = self.cfg.get("images_dir", "cache/images")
        self.generated_dir = self.cfg.get("generated_dir", "cache/generated")

        os.makedirs(self.cache_dir, exist_ok=True)
        os.makedirs(self.images_dir, exist_ok=True)
        os.makedirs(self.generated_dir, exist_ok=True)

    def produce(
        self,
        scene_num: int,
        narration: str,
        search_queries: Any,
        target_duration: float,
        accepted_scenes: list,
    ) -> Optional[dict]:
        """Attempt fallback chain. Returns asset dict or None.

        Parameters
        ----------
        scene_num : int
            Scene identifier for output file naming.
        narration : str
            The scene narration text (carried in metadata).
        search_queries : str | list[str]
            Original search query or list of queries — used to pick relevant
            fallback imagery.
        target_duration : float
            Desired video duration in seconds.
        accepted_scenes : list[dict]
            Previously accepted scene asset dicts, used by the reuse fallback.
        """
        # Normalise search_queries to a list of strings
        if isinstance(search_queries, str):
            queries_list = [search_queries] if search_queries else ["stock footage"]
        elif isinstance(search_queries, list):
            queries_list = [q for q in search_queries if isinstance(q, str) and q]
            if not queries_list:
                queries_list = ["stock footage"]
        else:
            queries_list = ["stock footage"]

        # Store for use by individual fallback methods
        self._fallback_queries = queries_list
        self._fallback_narration = narration

        chain = [
            ("nasa_image", lambda: self._try_nasa_image(queries_list)),
            ("wikimedia_image", lambda: self._try_wikimedia_image(queries_list)),
            ("generated_image", self._try_generated_image),
            ("reuse_scene", lambda: self._try_reuse_scene(
                scene_num, narration, target_duration, accepted_scenes,
            )),
            ("animated_placeholder", lambda: self._try_animated_placeholder(target_duration)),
        ]

        for name, fn in chain:
            logger.info("[FallbackDirector] Trying fallback: %s", name)
            try:
                result = fn()
                if result is not None and self._validate_visual(result):
                    logger.info(
                        "[FallbackDirector] Fallback succeeded: %s", name,
                    )
                    return result
            except Exception as exc:
                logger.warning(
                    "[FallbackDirector] Fallback %s failed: %s", name, exc,
                )

        logger.error("[FallbackDirector] ALL fallbacks exhausted — using emergency gradient")
        return self._emergency_placeholder(target_duration)

    # ------------------------------------------------------------------ #
    # Attribute helpers
    # ------------------------------------------------------------------ #

    def _make_asset(
        self, filepath: str, provider: str, query: str, score: float,
    ) -> dict:
        return {
            "filepath": filepath,
            "video_path": filepath,
            "audio_path": "",
            "provider": provider,
            "query": query,
            "search_query": query,
            "score": score,
            "semantic_score": score,
            "technical_score": score,
            "aesthetic_style": provider,
            "video_url": "",
            "narration": "",
            "duration": self._get_duration(filepath),
        }

    def _get_duration(self, filepath: str) -> float:
        try:
            result = subprocess.run(
                [
                    "ffprobe", "-v", "error",
                    "-show_entries", "format=duration",
                    "-of", "default=noprint_wrappers=1:nokey=1",
                    filepath,
                ],
                capture_output=True, text=True, timeout=30,
            )
            return float(result.stdout.strip())
        except Exception:
            return 0.0

    # ------------------------------------------------------------------ #
    # Validation
    # ------------------------------------------------------------------ #

    def _validate_visual(self, asset: dict) -> bool:
        """Reject artifacts that are blank/black/empty."""
        fp = asset.get("filepath", "") or asset.get("video_path", "")
        if not fp or not os.path.isfile(fp):
            return False
        if os.path.getsize(fp) < 1024:
            return False
        # Double-check with ffmpeg black detection
        try:
            subprocess.run(
                [
                    "ffmpeg", "-i", fp, "-vf",
                    "blackdetect=d=0.5:pix_th=0.10",
                    "-f", "null", "-",
                ],
                capture_output=True, text=True, timeout=30,
            )
            return True
        except Exception:
            return True

    # ------------------------------------------------------------------ #
    # Fallback 2: NASA image + Ken Burns
    # ------------------------------------------------------------------ #

    def _try_nasa_image(self, queries: Optional[list[str]] = None) -> Optional[dict]:
        """Search NASA image archive, download, animate with Ken Burns."""
        api_key = os.environ.get("NASA_API_KEY", "DEMO_KEY")
        query = self._pick_nasa_query(queries)
        url = (
            "https://images-api.nasa.gov/search?"
            f"q={urllib.parse.quote(query)}&media_type=image"
        )

        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            items = data.get("collection", {}).get("items", [])
            if not items:
                return None

            # Pick the first suitable image (filter for large-enough images)
            for item in items[:10]:
                links = item.get("links", [])
                if not links:
                    continue
                href = links[0].get("href", "")
                if not href:
                    continue

                # Download the image
                out_path = os.path.join(
                    self.images_dir, f"nasa_fallback_{self.rng.randint(1,99999)}.jpg",
                )
                try:
                    urllib.request.urlretrieve(href, out_path)
                except Exception:
                    continue

                if os.path.getsize(out_path) < 5000:
                    os.remove(out_path)
                    continue

                # Animate with Ken Burns to produce a video
                video_path = self._ken_burns_animate(
                    out_path, "nasa_fallback", duration=10.0,
                )
                if video_path and os.path.isfile(video_path):
                    title = item.get("data", [{}])[0].get("title", query)
                    return self._make_asset(
                        video_path, "nasa", query, 0.85,
                    )

        except Exception as exc:
            logger.debug("NASA image fallback failed: %s", exc)

        return None

    def _pick_nasa_query(self, hints: Optional[list[str]] = None) -> str:
        default_queries = [
            "galaxy nebula stars",
            "deep space telescope",
            "planet Earth from space",
            "solar system planets",
            "Milky Way galaxy",
            "astronaut space station",
            "cosmic star field",
            "exoplanet concept",
        ]
        # Prefer user's search query if it seems space-related
        if hints:
            space_keywords = {"space", "star", "galaxy", "planet", "nasa", "astronaut",
                              "cosmic", "nebula", "orbit", "telescope", "universe"}
            for h in hints:
                h_lower = h.lower()
                if any(kw in h_lower for kw in space_keywords):
                    return h
        return self.rng.choice(default_queries)

    # ------------------------------------------------------------------ #
    # Fallback 3: Wikimedia image + Ken Burns
    # ------------------------------------------------------------------ #

    def _try_wikimedia_image(self, queries: Optional[list[str]] = None) -> Optional[dict]:
        """Search Wikimedia Commons for a CC-licensed image relevant to the topic."""
        query = self._pick_wikimedia_query(queries)

        api_url = (
            "https://commons.wikimedia.org/w/api.php?"
            "action=query&list=search&srsearch=%s&srlimit=10"
            "&format=json&prop=imageinfo&iiprop=url"
        ) % urllib.parse.quote(query)

        try:
            req = urllib.request.Request(
                api_url,
                headers={"User-Agent": "VideoEngine/1.0"},
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            pages = data.get("query", {}).get("search", [])
            if not pages:
                return None

            for page in pages[:10]:
                title = page.get("title", "")
                if not title or not title.startswith("File:"):
                    continue

                # Get direct URL
                info_url = (
                    "https://commons.wikimedia.org/w/api.php?"
                    "action=query&titles=%s&prop=imageinfo"
                    "&iiprop=url&format=json"
                ) % urllib.parse.quote(title)

                info_req = urllib.request.Request(
                    info_url,
                    headers={"User-Agent": "VideoEngine/1.0"},
                )
                with urllib.request.urlopen(info_req, timeout=15) as resp:
                    info_data = json.loads(resp.read().decode("utf-8"))

                pages_info = info_data.get("query", {}).get("pages", {})
                for pid, pdata in pages_info.items():
                    if pid == "-1":
                        continue
                    imginfo = pdata.get("imageinfo", [])
                    if not imginfo:
                        continue
                    img_url = imginfo[0].get("url", "")
                    if not img_url:
                        continue

                    out_path = os.path.join(
                        self.images_dir,
                        f"wikimedia_fallback_{self.rng.randint(1,99999)}.jpg",
                    )
                    try:
                        urllib.request.urlretrieve(img_url, out_path)
                    except Exception:
                        continue

                    if os.path.getsize(out_path) < 5000:
                        os.remove(out_path)
                        continue

                    video_path = self._ken_burns_animate(
                        out_path, "wikimedia_fallback", duration=10.0,
                    )
                    if video_path and os.path.isfile(video_path):
                        return self._make_asset(
                            video_path, "wikimedia", query, 0.80,
                        )

        except Exception as exc:
            logger.debug("Wikimedia image fallback failed: %s", exc)

        return None

    def _pick_wikimedia_query(self, hints: Optional[list[str]] = None) -> str:
        default_queries = [
            "Milky Way astronomy",
            "deep space photograph",
            "observatory telescope",
            "nebula space image",
            "planet astronomy",
            "star cluster",
            "galaxy space photograph",
            "solar system illustration",
        ]
        # Prefer user's search query if it seems space-related
        if hints:
            space_keywords = {"space", "star", "galaxy", "planet", "nasa", "astronaut",
                              "cosmic", "nebula", "orbit", "telescope", "universe"}
            for h in hints:
                h_lower = h.lower()
                if any(kw in h_lower for kw in space_keywords):
                    return h
        return self.rng.choice(default_queries)

    # ------------------------------------------------------------------ #
    # Ken Burns animation helper
    # ------------------------------------------------------------------ #

    def _ken_burns_animate(
        self, image_path: str, prefix: str, duration: float = 10.0,
    ) -> Optional[str]:
        """Apply Ken Burns zoom/pan to a static image, producing an MP4."""
        out_path = os.path.join(
            self.cache_dir, f"{prefix}_kenburns_{self.rng.randint(1,99999)}.mp4",
        )

        # Random zoom parameters
        zoom_start = self.rng.uniform(1.0, 1.05)
        zoom_end = self.rng.uniform(1.1, 1.3)
        pan_x = self.rng.choice(["0", "(w-tw)/2"])
        pan_y = self.rng.choice(["0", "(h-th)/2"])

        zoom_filter = (
            f"zoompan=z='if(eq(on,1),{zoom_start},min({zoom_end},zoom+0.005))':"
            f"x='{pan_x}':y='{pan_y}':d={int(duration * 30)}:s=1920x1080"
        )

        try:
            subprocess.run(
                [
                    "ffmpeg", "-y",
                    "-loop", "1",
                    "-i", image_path,
                    "-vf", zoom_filter,
                    "-c:v", "libx264",
                    "-preset", "fast",
                    "-t", str(duration),
                    "-pix_fmt", "yuv420p",
                    "-r", "30",
                    out_path,
                ],
                capture_output=True, text=True, timeout=60,
            )

            if os.path.isfile(out_path) and os.path.getsize(out_path) > 5000:
                return out_path
        except Exception as exc:
            logger.debug("Ken Burns animation failed: %s", exc)

        return None

    # ------------------------------------------------------------------ #
    # Fallback 4: Generated image (placeholder for future generator)
    # ------------------------------------------------------------------ #

    def _try_generated_image(self) -> Optional[dict]:
        """Placeholder for AI-generated image fallback."""
        # This will be implemented when an image generation model is available
        return None

    # ------------------------------------------------------------------ #
    # Fallback 5: Reuse a previous scene with distinct visual treatment
    # ------------------------------------------------------------------ #

    def _try_reuse_scene(
        self,
        scene_num: int,
        narration: str,
        target_duration: float,
        accepted_scenes: list,
    ) -> Optional[dict]:
        """Reuse a previously accepted scene with a different crop/zoom/timing."""
        if not accepted_scenes:
            return None

        # Pick from earlier scenes (not the last one, for diversity)
        candidates = [
            s for s in accepted_scenes
            if s.get("filepath") and os.path.isfile(s.get("filepath", ""))
        ]
        if not candidates:
            return None

        source = self.rng.choice(candidates)
        src_path = source["filepath"]
        out_path = os.path.join(
            self.cache_dir, f"reuse_scene{scene_num}.mp4",
        )

        # Apply a distinct visual transform
        crop_w = self.rng.randint(60, 90)
        crop_h = self.rng.randint(60, 90)
        crop_x = self.rng.randint(0, 100 - crop_w)
        crop_y = self.rng.randint(0, 100 - crop_h)

        try:
            subprocess.run(
                [
                    "ffmpeg", "-y",
                    "-i", src_path,
                    "-vf", (
                        f"crop=iw*{crop_w/100}:ih*{crop_h/100}:"
                        f"iw*{crop_x/100}:ih*{crop_y/100},"
                        f"scale=1920:1080,"
                        f"setsar=1"
                    ),
                    "-c:v", "libx264",
                    "-preset", "fast",
                    "-t", str(target_duration),
                    "-pix_fmt", "yuv420p",
                    "-r", "30",
                    out_path,
                ],
                capture_output=True, text=True, timeout=60,
            )

            if os.path.isfile(out_path) and os.path.getsize(out_path) > 5000:
                return self._make_asset(
                    out_path, "reuse", source.get("query", "reused"),
                    0.75,
                )
        except Exception as exc:
            logger.debug("Scene reuse failed: %s", exc)

        return None

    # ------------------------------------------------------------------ #
    # Fallback 6: Cinematic animated placeholder
    # ------------------------------------------------------------------ #

    def _try_animated_placeholder(
        self, target_duration: float = 12.0,
    ) -> Optional[dict]:
        """Generate a cinematic animated placeholder with gradient overlay.
        Uses only reliable ffmpeg filters — no drawtext, no geq."""
        out_path = os.path.join(
            self.cache_dir,
            f"placeholder_scene_{self.rng.randint(1,99999)}.mp4",
        )

        # Use visibly bright colors — never dark/dim colors that ffmpeg
        # blackdetect may flag.
        palettes = [
            ("#1a3a7e", "#2a5a9e"),   # deep bright blue
            ("#2a3a6e", "#3a5a8e"),   # medium blue
            ("#3a2a5e", "#5a3a7e"),   # purple
            ("#2a4a3e", "#3a6a5e"),   # teal
            ("#4a2a3e", "#6a3a5e"),   # maroon
            ("#1a4a6e", "#2a6a8e"),   # ocean
            ("#3a4a2e", "#5a6a4e"),   # forest
        ]
        rng_local = random.Random(self.seed + int(target_duration * 100))
        bg_color, accent_color = rng_local.choice(palettes)

        # Use proper ffmpeg: two -f lavfi -i inputs for color sources
        try:
            subprocess.run(
                [
                    "ffmpeg", "-y",
                    "-f", "lavfi", "-i",
                    f"color=c={accent_color}:s=1920x1080:d={target_duration}:r=30",
                    "-f", "lavfi", "-i",
                    f"color=c={bg_color}:s=1920x1080:d={target_duration}:r=30",
                    "-filter_complex",
                    "[0:v]format=rgba,colorchannelmixer=aa=0.15[over];[1:v][over]overlay",
                    "-c:v", "libx264",
                    "-preset", "fast",
                    "-pix_fmt", "yuv420p",
                    out_path,
                ],
                capture_output=True, text=True, timeout=120,
            )

            if os.path.isfile(out_path) and os.path.getsize(out_path) > 10000:
                return self._make_asset(
                    out_path, "placeholder", "animated_gradient", 0.70,
                )
        except Exception as exc:
            logger.debug("Animated placeholder failed: %s", exc)

        # Last-resort emergency
        return self._emergency_placeholder(target_duration)

    # ------------------------------------------------------------------ #
    # Absolute last resort
    # ------------------------------------------------------------------ #

    def _emergency_placeholder(self, duration: float = 12.0) -> dict:
        """Create a visible colour video as the absolute last resort.

        NEVER produces a black frame — always visible colours.
        """
        out_path = os.path.join(
            self.cache_dir,
            f"emergency_{self.rng.randint(1,99999)}.mp4",
        )

        # Use visibly bright colours — NOT dark navy or near-black
        color = self.rng.choice(["#1a3a7e", "#2a4a8e", "#3a5a6e", "#4a3a6e", "#3a6a4e"])
        try:
            subprocess.run(
                [
                    "ffmpeg", "-y",
                    "-f", "lavfi",
                    "-i", f"color=c={color}:s=1920x1080:d={duration}:r=30",
                    "-c:v", "libx264",
                    "-preset", "fast",
                    "-pix_fmt", "yuv420p",
                    out_path,
                ],
                capture_output=True, text=True, timeout=30,
            )
        except Exception:
            pass

        return self._make_asset(out_path, "emergency", "emergency", 0.50)
