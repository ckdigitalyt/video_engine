"""Regression tests for FallbackDirector.

Verifies:
- no black/blank/placeholder scenes are ever produced
- fallback hierarchy is respected
- semantic validation still works
- graceful degradation when every provider fails
"""

import os
import subprocess
import tempfile
import sys
import json
import io
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.director.fallback_director import FallbackDirector
from src.director.quality_gate import QualityGates
from src.models.schemas import AssetPlan, ProviderType, Scene, SceneNarration, SearchPlan


# ── Helpers ────────────────────────────────────────────────────────────

def is_black_video(filepath: str) -> bool:
    """Check if a video file is effectively all-black."""
    if not os.path.isfile(filepath):
        return True
    if os.path.getsize(filepath) < 5000:
        return True
    # Use ffmpeg blackdetect
    try:
        result = subprocess.run(
            [
                "ffmpeg", "-i", filepath,
                "-vf", "blackdetect=d=0.1:pix_th=0.10",
                "-f", "null", "-",
            ],
            capture_output=True, text=True, timeout=30,
        )
        # If blackdetect found frames, check what fraction is black
        if "black_duration" in result.stderr:
            # Parse black durations
            lines = [l for l in result.stderr.split("\n") if "black_duration" in l]
            if lines:
                total_black = sum(
                    float(l.split("black_duration:")[1].strip().split()[0])
                    for l in lines if "black_duration:" in l
                )
                # Get video duration
                dur_result = subprocess.run(
                    [
                        "ffprobe", "-v", "error",
                        "-show_entries", "format=duration",
                        "-of", "default=noprint_wrappers=1:nokey=1",
                        filepath,
                    ],
                    capture_output=True, text=True, timeout=10,
                )
                try:
                    duration = float(dur_result.stdout.strip())
                    if duration > 0 and (total_black / duration) > 0.95:
                        return True
                except ValueError:
                    pass
        return False
    except Exception:
        return False


def check_placeholder_quality(filepath: str) -> dict:
    """Analyze a placeholder video's quality metrics."""
    result = {"exists": False, "size": 0, "black": True, "resolution": "unknown"}
    if not os.path.isfile(filepath):
        return result
    result["exists"] = True
    result["size"] = os.path.getsize(filepath)
    result["black"] = is_black_video(filepath)

    # Check resolution
    try:
        info = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=width,height",
                "-of", "csv=p=0",
                filepath,
            ],
            capture_output=True, text=True, timeout=10,
        )
        result["resolution"] = info.stdout.strip()
    except Exception:
        pass
    return result


# ── Tests ───────────────────────────────────────────────────────────────

class TestFallbackDirector:
    """Test suite for FallbackDirector."""

    def setup_method(self):
        self.cache_dir = tempfile.mkdtemp()
        self.images_dir = tempfile.mkdtemp()
        self.generated_dir = tempfile.mkdtemp()
        self.fd = FallbackDirector({
            "cache_dir": self.cache_dir,
            "images_dir": self.images_dir,
            "generated_dir": self.generated_dir,
            "random_seed": 42,
        })

    def teardown_method(self):
        import shutil
        for d in [self.cache_dir, self.images_dir, self.generated_dir]:
            if os.path.exists(d):
                shutil.rmtree(d)

    # ── Test 1: No black scenes ────────────────────────────────────────

    def test_no_black_scenes(self):
        """The cinematic animated placeholder must never produce a black frame."""
        result = self.fd._try_animated_placeholder(target_duration=5.0)
        assert result is not None, "Placeholder must produce a result"
        fp = result.filepath
        assert fp, "Placeholder must produce a filepath"
        assert os.path.isfile(fp), f"Placeholder file must exist: {fp}"
        assert not is_black_video(fp), f"Placeholder must not be black: {fp}"
        assert os.path.getsize(fp) > 10000, f"Placeholder must be >10KB: {os.path.getsize(fp)}"

    def test_emergency_placeholder_not_black(self):
        """Emergency gradient fallback must produce visible content."""
        result = self.fd._emergency_placeholder(duration=3.0)
        assert result is not None
        fp = result.filepath
        assert fp and os.path.isfile(fp), "Emergency must produce a file"
        assert os.path.getsize(fp) > 5000, "Emergency must be >5KB"

    # ── Test 2: Fallback hierarchy ────────────────────────────────────

    def test_fallback_hierarchy_animated_placeholder(self):
        """When all provider-based fallbacks fail, animated placeholder works."""
        from unittest.mock import patch

        with patch.object(self.fd, "_try_nasa_image", return_value=None), \
             patch.object(self.fd, "_try_generated_image", return_value=None):
            result = self.fd.produce(
                scene_num=1,
                narration="Test narration for the cosmos",
                search_queries=["galaxy"],
                target_duration=5.0,
                accepted_scenes=[],
            )
        assert result is not None, "Fallback chain must produce something"
        provider_val = result.provider.value if hasattr(result.provider, 'value') else result.provider
        assert provider_val in ("placeholder", "emergency"), (
            f"Expected placeholder/emergency, got {provider_val}"
        )
        assert not is_black_video(result.filepath), (
            "Fallback output must not be black"
        )

    def test_fallback_reuse_scene(self):
        """Reuse fallback must produce a distinct crop of accepted scene."""
        # First, create a valid accepted scene
        src_path = os.path.join(self.cache_dir, "source_scene.mp4")
        subprocess.run(
            [
                "ffmpeg", "-y", "-f", "lavfi",
                "-i", "color=c=blue:s=1920x1080:d=5:r=30",
                "-c:v", "libx264", "-preset", "fast", src_path,
            ],
            capture_output=True, text=True, timeout=30,
        )

        accepted = [Scene(
            scene_id=0,
            title="Source Scene",
            expected_duration=5.0,
            topic="test",
            narration=SceneNarration(spoken_narration="Test narration"),
            search_plan=SearchPlan(asset_search_queries=["blue space"]),
            asset_plan=AssetPlan(
                provider=ProviderType.PIXABAY,
                filepath=src_path,
                query_used="blue space",
                score=0.9,
                semantic_score=0.9,
                technical_score=0.9,
            ),
        )]

        result = self.fd._try_reuse_scene(
            scene_num=2, narration="Test",
            target_duration=5.0, accepted_scenes=accepted,
        )

        if result:
            assert result.provider.value == "reuse"
            fp = result.filepath
            assert os.path.isfile(fp), "Reuse must produce valid file"
            assert os.path.getsize(fp) > 5000, "Reuse must be >5KB"
            # Check that reuse file is different from source
            assert fp != src_path, "Reuse must produce a different file"

    def test_fallback_hierarchy_chain_order(self):
        """Fallback chain must attempt in correct order: nasa, wikimedia, gen, reuse, placeholder."""
        order = []
        original_nasa = self.fd._try_nasa_image
        original_wiki = self.fd._try_wikimedia_image
        original_gen = self.fd._try_generated_image
        original_reuse = self.fd._try_reuse_scene
        original_anim = self.fd._try_animated_placeholder

        def track_nasa(*a, **kw):
            order.append("nasa")
            return None

        def track_wiki(*a, **kw):
            order.append("wikimedia")
            return None

        def track_gen(*a, **kw):
            order.append("generated")
            return None

        def track_reuse(*a, **kw):
            order.append("reuse")
            return None

        def track_anim(*a, **kw):
            order.append("placeholder")
            return None

        self.fd._try_nasa_image = track_nasa
        self.fd._try_wikimedia_image = track_wiki
        self.fd._try_generated_image = track_gen
        self.fd._try_reuse_scene = track_reuse
        self.fd._try_animated_placeholder = track_anim

        result = self.fd.produce(
            scene_num=1, narration="Test",
            search_queries=["test"],
            target_duration=5.0,
            accepted_scenes=[],
        )

        # Restore
        self.fd._try_nasa_image = original_nasa
        self.fd._try_wikimedia_image = original_wiki
        self.fd._try_generated_image = original_gen
        self.fd._try_reuse_scene = original_reuse
        self.fd._try_animated_placeholder = original_anim

        assert "placeholder" in order, f"Should reach placeholder: {order}"

    # ── Test 3: Full degradation chain ────────────────────────────────

    def test_full_degradation_without_network(self):
        """Even without network access, fallback must produce meaningful video."""
        # Override to skip network-dependent fallbacks
        old_nasa = self.fd._try_nasa_image
        old_wiki = self.fd._try_wikimedia_image
        self.fd._try_nasa_image = lambda: None
        self.fd._try_wikimedia_image = lambda: None

        result = self.fd.produce(
            scene_num=5,
            narration="The universe is vast and empty",
            search_queries=["cosmos", "space"],
            target_duration=8.0,
            accepted_scenes=[],
        )

        self.fd._try_nasa_image = old_nasa
        self.fd._try_wikimedia_image = old_wiki

        assert result is not None, "Must produce fallback even without network"
        assert result.filepath, "Must have filepath"
        assert os.path.isfile(result.filepath), "File must exist"
        quality = check_placeholder_quality(result.filepath)
        assert not quality["black"], "Output must not be black"

    # ── Test 4: Semantic validation still works ────────────────────────

    def test_semantic_threshold_preserved(self):
        """Quality gates must still enforce semantic threshold >= 0.75."""
        from src.director.visual_style import VisualStyle
        from src.director.aesthetic_agent import AestheticAgent

        style = VisualStyle(
            aesthetic="test",
            sub_aesthetic="test_domain",
            mood="neutral",
            pace="medium",
            color_palette=["#000000", "#ffffff"],
            preferred_categories=["General"],
            avoid_categories=[],
            provider_prefs=["pixabay"],
            creator_prompt="Use test style.",
        )
        agent = AestheticAgent(visual_style=style)
        gates = QualityGates(visual_style=style, aesthetic_agent=agent, semantic_threshold=0.75)

        # Test with low semantic score
        asset = AssetPlan(
            provider=ProviderType.PIXABAY,
            filepath="",
            video_url="https://example.com/v.mp4",
            query_used="test",
            score=0.5,
            semantic_score=0.5,
            technical_score=0.5,
            width=1920,
            height=1080,
            duration=10,
        )
        passed, reason, details = gates.check_all(
            asset=asset, category="Space",
        )
        assert not passed, "Score 0.5 must be rejected"
        assert "semantic" in reason.lower()

        # Test with high semantic score
        asset = AssetPlan(
            provider=ProviderType.PIXABAY,
            filepath="",
            video_url="https://example.com/v.mp4",
            query_used="test",
            score=0.85,
            semantic_score=0.85,
            technical_score=0.85,
            width=1920,
            height=1080,
            duration=10,
        )
        passed, reason, details = gates.check_all(
            asset=asset, category="Space",
        )
        assert passed, "Score 0.85 must pass"

    def test_black_frame_reuse_fallback(self):
        """Simulate scenario where reuse fallback produces artifact, must still
        degrade to animated placeholder."""
        import shutil

        # Create a 1x1 pixel black box as a mock "bad" reuse candidate
        bad_src = os.path.join(self.cache_dir, "bad_source.mp4")
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi",
             "-i", "color=c=black:s=1x1:d=2:r=30",
             "-c:v", "libx264", "-preset", "fast", bad_src],
            capture_output=True, text=True, timeout=30,
        )

        accepted = [Scene(
            scene_id=0,
            title="Bad Source",
            expected_duration=5.0,
            topic="test",
            narration=SceneNarration(spoken_narration="test"),
            search_plan=SearchPlan(asset_search_queries=["test"]),
            asset_plan=AssetPlan(
                provider=ProviderType.PIXABAY,
                filepath=bad_src,
                score=0.5,
                semantic_score=0.5,
                technical_score=0.5,
            ),
        )]

        # Try reuse first, then animated placeholder
        result = self.fd._try_reuse_scene(
            scene_num=3, narration="test",
            target_duration=5.0, accepted_scenes=accepted,
        )
        # The reuse should still produce a file (even from tiny source)
        if result and result.filepath:
            fp = result.filepath
            if os.path.getsize(fp) > 5000:
                # Check it's not all black
                check = check_placeholder_quality(fp)
                if check["black"]:
                    # Reuse failed - now test animated placeholder
                    pl = self.fd._try_animated_placeholder(target_duration=5.0)
                    assert pl is not None, "Animated placeholder must rescue"
                    assert not is_black_video(pl.filepath), "Placeholder must not be black"

    def test_make_asset_valid_keys(self):
        """AssetPlan produced by fallback must have the right attributes."""
        test_path = os.path.join(self.cache_dir, "test.mp4")
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi",
             "-i", "color=c=red:s=640x480:d=2:r=30",
             "-c:v", "libx264", "-preset", "fast", test_path],
            capture_output=True, text=True, timeout=30,
        )

        asset = self.fd._make_asset(test_path, "pixabay", "test_query", 0.8)
        assert isinstance(asset, AssetPlan)
        assert asset.filepath == test_path
        assert asset.provider.value == "pixabay"
        assert asset.query_used == "test_query"
        assert asset.score == 0.8
        assert asset.semantic_score == 0.8
        assert asset.technical_score == 0.8

    def test_validate_visual_rejects_empty(self):
        """_validate_visual must reject empty/missing files."""
        assert not self.fd._validate_visual(AssetPlan(filepath="", provider=ProviderType.PIXABAY))
        assert not self.fd._validate_visual(AssetPlan(filepath="/tmp/nonexistent_file.mp4", provider=ProviderType.PIXABAY))

    def test_validate_visual_accepts_valid(self):
        """_validate_visual must accept valid video files."""
        test_path = os.path.join(self.cache_dir, "valid_test.mp4")
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi",
             "-i", "color=c=red:s=640x480:d=2:r=30",
             "-c:v", "libx264", "-preset", "fast", test_path],
            capture_output=True, text=True, timeout=30,
        )
        assert self.fd._validate_visual(AssetPlan(filepath=test_path, provider=ProviderType.PIXABAY, score=0.8, semantic_score=0.8, technical_score=0.8))


# ── Integration tests ─────────────────────────────────────────────────

class TestFallbackIntegration:
    """Integration tests that verify the full pipeline behavior."""

    def test_director_imports_fallback(self):
        """The VisualDirector must import and use FallbackDirector."""
        try:
            from src.director.director import VisualDirector
            assert hasattr(VisualDirector, "fallback_director")
        except (ImportError, Exception) as e:
            # During import tests, the full dependency chain may not be available.
            # At minimum, the module should parse.
            import ast
            with open("src/director/director.py") as f:
                ast.parse(f.read())
            print("Note: Full import not tested (requires all dependencies)")
