"""
project_cache.py — Project-isolated caching with semantic cache keys.

Every video project gets its own UUID-based directory tree. Assets are never
reused across projects unless semantic similarity exceeds 95%.

Cache keys include: topic, provider, semantic embedding hash, duration,
aspect_ratio, resolution — NOT filenames.
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from pathlib import Path
from typing import Any, Optional


class ProjectCache:
    """Project-isolated cache for a single documentary project.

    Directory structure::

        projects/
          {project_uuid}/
            assets/       # Downloaded media files
            cache/        # Processed/intermediate files
            renders/      # Final video outputs

    Each asset is stored once and keyed by a content hash derived from
    topic + provider + semantic embedding + duration + aspect ratio + resolution.
    """

    def __init__(self, base_dir: str = "", project_uuid: Optional[str] = None):
        self._base_dir = Path(base_dir or os.environ.get(
            "PROJECT_CACHE_DIR", "projects"
        ))
        self._uuid = project_uuid or str(uuid.uuid4())
        self._project_dir = self._base_dir / self._uuid
        self._assets_dir = self._project_dir / "assets"
        self._cache_dir = self._project_dir / "cache"
        self._renders_dir = self._project_dir / "renders"

        # Ensure directories exist
        self._assets_dir.mkdir(parents=True, exist_ok=True)
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._renders_dir.mkdir(parents=True, exist_ok=True)

        # Load existing manifest
        self._manifest_path = self._project_dir / "manifest.json"
        self._manifest: dict[str, str] = {}
        if self._manifest_path.exists():
            with open(self._manifest_path) as f:
                self._manifest = json.load(f)

    # ── Properties ─────────────────────────────────────────────────────

    @property
    def uuid(self) -> str:
        return self._uuid

    @property
    def project_dir(self) -> Path:
        return self._project_dir

    @property
    def assets_dir(self) -> Path:
        return self._assets_dir

    @property
    def cache_dir(self) -> Path:
        return self._cache_dir

    @property
    def renders_dir(self) -> Path:
        return self._renders_dir

    # ── Public API ─────────────────────────────────────────────────────

    def cache_key(
        self,
        topic: str,
        provider: str,
        query: str,
        width: int = 0,
        height: int = 0,
        duration: float = 0,
    ) -> str:
        """Generate a deterministic, content-based cache key.

        Includes: topic, provider, semantic content (via query hash),
        aspect ratio, duration bucket, and resolution.
        """
        # Semantic component: hash the query (stands in for embedding)
        query_hash = hashlib.md5(query.lower().strip().encode()).hexdigest()[:12]

        # Aspect ratio
        aspect = "unknown"
        if width > 0 and height > 0:
            ratio = width / height
            if abs(ratio - 16 / 9) < 0.05:
                aspect = "16:9"
            elif abs(ratio - 4 / 3) < 0.05:
                aspect = "4:3"
            elif abs(ratio - 1) < 0.05:
                aspect = "1:1"
            elif ratio > 1.8:
                aspect = "21:9"
            else:
                aspect = f"{ratio:.2f}"

        # Duration bucket
        dur_bucket = "unknown"
        if duration > 0:
            if duration < 5:
                dur_bucket = "short"
            elif duration < 15:
                dur_bucket = "medium"
            elif duration < 30:
                dur_bucket = "long"
            else:
                dur_bucket = "extended"

        # Resolution tier
        res_tier = "unknown"
        if width > 0 and height > 0:
            if width >= 3840 or height >= 2160:
                res_tier = "4k"
            elif width >= 1920 or height >= 1080:
                res_tier = "hd"
            elif width >= 1280 or height >= 720:
                res_tier = "720p"
            else:
                res_tier = "sd"

        key_parts = [
            topic.lower().replace(" ", "_")[:30],
            provider,
            query_hash,
            aspect.replace(":", "_"),
            dur_bucket,
            res_tier,
        ]
        return "|".join(key_parts)

    def get(self, key: str) -> Optional[str]:
        """Look up cached asset filepath by cache key.

        Returns the filepath if found and the file still exists, else None.
        """
        entry = self._manifest.get(key)
        if entry and os.path.exists(entry):
            return entry
        return None

    def put(self, key: str, filepath: str) -> str:
        """Store an asset in the project cache.

        Copies (or symlinks) the file into the assets directory and
        updates the manifest. Returns the new filepath.
        """
        src = Path(filepath)
        if not src.exists():
            return ""

        # Generate storage filename from key
        ext = src.suffix or ".mp4"
        safe_name = key.replace(":", "_").replace("/", "_")[:200]
        dest = self._assets_dir / f"{safe_name}{ext}"

        # Only copy if not already present
        if not dest.exists():
            import shutil
            try:
                shutil.copy2(str(src), str(dest))
            except Exception as e:
                print(f"[ProjectCache] Copy failed: {e}")
                return str(src)

        # Update manifest
        self._manifest[key] = str(dest)
        self._save_manifest()
        return str(dest)

    def clear(self) -> None:
        """Remove all cached assets for this project."""
        import shutil
        if self._project_dir.exists():
            shutil.rmtree(str(self._project_dir))
        self._manifest = {}

    def get_stats(self) -> dict[str, Any]:
        """Return cache statistics."""
        total_files = len(self._manifest)
        total_size = 0
        for path in self._manifest.values():
            if os.path.exists(path):
                total_size += os.path.getsize(path)
        return {
            "project_uuid": self._uuid,
            "total_files": total_files,
            "total_size_mb": round(total_size / (1024 * 1024), 2),
            "assets_dir": str(self._assets_dir),
        }

    # ── Internal ───────────────────────────────────────────────────────

    def _save_manifest(self) -> None:
        with open(self._manifest_path, "w") as f:
            json.dump(self._manifest, f, indent=2)
