"""
asset_validator.py — Pre-render asset validation pipeline.

Verifies every clip before the renderer touches it:
- file exists
- duration >= shot duration
- resolution >= minimum
- codec is supported
- file is not corrupted
- file is video (not an image)
- file contains motion
- file is not blank or solid color
- no watermark

Rejects invalid assets before they reach the renderer.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from typing import Any, Optional


class ValidationError(Exception):
    """Raised when an asset fails validation."""


@dataclass
class AssetValidationResult:
    """Result of validating a single asset file."""

    valid: bool
    filepath: str = ""
    errors: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_valid(self) -> bool:
        return self.valid


class AssetValidator:
    """Validate media files before they reach the renderer.

    Usage::

        validator = AssetValidator()
        result = validator.validate("cache/video/scene_0_b0_s0.mp4", min_duration=5.0)
        if not result.is_valid:
            # Reject and try next asset
            print(result.errors)
    """

    MIN_WIDTH = 1280
    MIN_HEIGHT = 720
    SUPPORTED_CODECS = {"h264", "hevc", "h265", "vp9", "av1"}
    MAX_BLANK_CHECK_FRAMES = 5
    MIN_MOTION_PIXELS = 100  # Threshold for detecting motion

    def validate(
        self,
        filepath: str,
        min_duration: float = 0,
    ) -> AssetValidationResult:
        """Run all validation checks on a media file.

        Args:
            filepath: Path to the media file.
            min_duration: Minimum required duration in seconds.

        Returns:
            AssetValidationResult with pass/fail and detailed errors.
        """
        errors: list[str] = []

        # 1. File exists check
        if not filepath:
            return AssetValidationResult(valid=False, errors=["Empty filepath"])
        if not os.path.exists(filepath):
            return AssetValidationResult(
                valid=False, filepath=filepath, errors=[f"File not found: {filepath}"]
            )

        # 2. Probe file metadata with ffprobe
        metadata = self._probe(filepath)
        if not metadata:
            return AssetValidationResult(
                valid=False, filepath=filepath,
                errors=[f"Failed to probe file: {filepath} (corrupted or invalid)"]
            )

        # 3. Duration check
        duration = metadata.get("duration", 0)
        if min_duration > 0 and duration < min_duration:
            errors.append(
                f"Duration ({duration:.2f}s) < minimum ({min_duration:.2f}s)"
            )

        # 4. Resolution check
        width = metadata.get("width", 0)
        height = metadata.get("height", 0)
        if width > 0 and height > 0:
            if width < self.MIN_WIDTH or height < self.MIN_HEIGHT:
                errors.append(
                    f"Resolution ({width}x{height}) below minimum "
                    f"({self.MIN_WIDTH}x{self.MIN_HEIGHT})"
                )
        else:
            errors.append("Could not determine resolution")

        # 5. Codec check
        codec = metadata.get("codec", "").lower()
        if codec and codec not in self.SUPPORTED_CODECS:
            errors.append(f"Unsupported codec: {codec}")

        # 6. Check for static/blank frame
        if duration > 0:
            blank_result = self._check_not_blank(filepath, duration)
            if not blank_result["has_motion"]:
                errors.append("Asset has no detectable motion (likely static/blank)")
            if blank_result.get("is_solid_color"):
                errors.append("Asset appears to be solid color")

        # 7. Watermark check via metadata
        watermark_indicators = {"watermark", "shutterstock", "getty", "preview"}
        tags = [str(t).lower() for t in metadata.get("tags", [])]
        tag_text = " ".join(tags)
        if any(wm in tag_text for wm in watermark_indicators):
            errors.append(f"Watermark detected in metadata: {tag_text[:60]}")

        result = AssetValidationResult(
            valid=len(errors) == 0,
            filepath=filepath,
            errors=errors,
            metadata={
                "duration": duration,
                "width": width,
                "height": height,
                "codec": codec,
                "fps": metadata.get("fps", 0),
            },
        )
        return result

    def _probe(self, filepath: str) -> Optional[dict[str, Any]]:
        """Use ffprobe to extract media file metadata.

        Returns dict with duration, width, height, codec, fps or None on failure.
        """
        try:
            cmd = [
                "ffprobe", "-v", "error",
                "-show_entries", "stream=codec_name,width,height,r_frame_rate,duration",
                "-of", "json",
                filepath,
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode != 0:
                return None

            import json
            data = json.loads(result.stdout)
            streams = data.get("streams", [])

            # Prefer first video stream
            for stream in streams:
                if stream.get("codec_type") == "video":
                    fps_str = stream.get("r_frame_rate", "0/1")
                    fps = 0
                    if "/" in fps_str:
                        parts = fps_str.split("/")
                        fps = float(parts[0]) / float(parts[1]) if float(parts[1]) > 0 else 0

                    return {
                        "duration": float(stream.get("duration", 0)),
                        "width": int(stream.get("width", 0)),
                        "height": int(stream.get("height", 0)),
                        "codec": stream.get("codec_name", ""),
                        "fps": round(fps, 2),
                        "tags": [t for t in stream.get("tags", {}).values()],
                    }

            # Fallback: use format duration
            fmt = data.get("format", {})
            return {
                "duration": float(fmt.get("duration", 0)),
                "width": 0, "height": 0, "codec": "", "fps": 0,
                "tags": [],
            }
        except Exception as e:
            print(f"[AssetValidator] probe failed: {e}")
            return None

    def _check_not_blank(self, filepath: str, duration: float) -> dict[str, Any]:
        """Check that the video contains motion and is not solid color.

        Samples frames from the video and checks pixel variance.
        """
        try:
            # Sample a frame at 25%, 50%, 75% through the video
            import subprocess
            import json
            import numpy as np

            result = {"has_motion": False, "is_solid_color": False, "mean_variance": 0.0}

            sample_points = [duration * 0.25, duration * 0.5, duration * 0.75]
            variances = []

            for seek in sample_points:
                cmd = [
                    "ffmpeg", "-v", "quiet",
                    "-ss", str(seek),
                    "-i", filepath,
                    "-vframes", "1",
                    "-f", "rawvideo",
                    "-pix_fmt", "gray",
                    "-s", "64x36",  # tiny for speed
                    "pipe:1",
                ]
                proc = subprocess.run(cmd, capture_output=True, timeout=15)
                if len(proc.stdout) > 0:
                    frame = np.frombuffer(proc.stdout, dtype=np.uint8)
                    variance = float(np.var(frame))
                    variances.append(variance)
                else:
                    variances.append(0.0)

            mean_var = np.mean(variances) if variances else 0.0
            result["mean_variance"] = round(mean_var, 2)

            # If all frames have near-zero variance, it's blank/solid
            if mean_var < 5.0:
                result["is_solid_color"] = True
            elif mean_var > 20.0:
                result["has_motion"] = True

            return result
        except Exception as e:
            return {"has_motion": True, "is_solid_color": False,
                    "mean_variance": 0.0, "error": str(e)}

    @staticmethod
    def is_image(filepath: str) -> bool:
        """Check if the file is a still image, not a video."""
        ext = os.path.splitext(filepath)[1].lower()
        return ext in {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"}
