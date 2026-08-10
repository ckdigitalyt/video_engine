"""Tests for the content-addressed manifest + dependency graph (v20).

Covers: hash helpers, shot-id parsing, scene/asset diff detection,
per-scene voice reuse decisions, and cross-topic audio-cache protection
(the latent bug: cache/audio/ was global, so all-or-nothing --reuse could
silently reuse another topic's narration).
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + "/..")

import pytest  # noqa: E402

from src.pipeline.manifest import (  # noqa: E402
    Manifest,
    compute_diff,
    hash_file,
    hash_text,
    parse_shot_id,
    shot_id,
)


def _write(path, content=b"data" * 100):
    with open(path, "wb") as f:
        f.write(content)
    return path


class TestHashes:
    def test_hash_text_stable_and_empty(self):
        assert hash_text("hello world") == hash_text("hello world")
        assert hash_text("  padded  ") == hash_text("padded")
        assert hash_text(None) == hash_text("")

    def test_hash_file_missing_returns_empty(self):
        assert hash_file("/nonexistent/definitely/missing.jpg") == ""

    def test_hash_file_changes_with_content(self):
        with tempfile.TemporaryDirectory() as td:
            a = _write(os.path.join(td, "a.jpg"), b"same")
            b = _write(os.path.join(td, "b.jpg"), b"same")
            c = _write(os.path.join(td, "c.jpg"), b"different")
            assert hash_file(a) == hash_file(b)
            assert hash_file(a) != hash_file(c)


class TestShotIds:
    def test_roundtrip(self):
        assert shot_id(6, 1) == "s06_sh01"
        assert parse_shot_id("s06_sh01") == (6, 1)
        assert parse_shot_id("s00_sh00") == (0, 0)

    def test_malformed(self):
        assert parse_shot_id("bogus") is None
        assert parse_shot_id("s06_sh") is None
        assert parse_shot_id("s_xx") is None


class TestDiff:
    def _scene(self, script="hello", voice_hash="v1",
               asset_hash="a1", subs="s1"):
        return {
            "script_hash": hash_text(script),
            "voice": {"hash": voice_hash, "duration": 3.0},
            "shots": [{"id": "s00_sh00", "asset_hash": asset_hash,
                       "clip_hash": "c1"}],
            "subtitles_hash": subs,
        }

    def test_identical_manifests_no_diff(self):
        prev = {"scenes": {"0": self._scene()}}
        curr = {"scenes": {"0": self._scene()}}
        assert compute_diff(prev, curr) == []

    def test_script_change_cascades(self):
        prev = {"scenes": {"0": self._scene(script="hello")}}
        curr = {"scenes": {"0": self._scene(script="changed")}}
        diff = compute_diff(prev, curr)
        assert len(diff) == 1
        assert diff[0]["scene"] == 0
        assert "script" in diff[0]["changed"]
        # script change must invalidate voice + subtitles + scene render
        for a in ("regenerate_voice", "regenerate_subtitles",
                  "regenerate_scene_render"):
            assert a in diff[0]["actions"]

    def test_visual_change_only_scene_render(self):
        prev = {"scenes": {"0": self._scene(asset_hash="a1")}}
        curr = {"scenes": {"0": self._scene(asset_hash="a2")}}
        diff = compute_diff(prev, curr)
        assert diff[0]["changed"] == ["visual:s00_sh00"]
        assert diff[0]["actions"] == ["regenerate_scene_render"]

    def test_voice_change_cascades_subtitles_and_render(self):
        prev = {"scenes": {"0": self._scene(voice_hash="v1")}}
        curr = {"scenes": {"0": self._scene(voice_hash="v2")}}
        diff = compute_diff(prev, curr)
        assert "voice" in diff[0]["changed"]
        for a in ("regenerate_subtitles", "regenerate_scene_render"):
            assert a in diff[0]["actions"]
        assert "regenerate_voice" not in diff[0]["actions"]

    def test_new_scene_detected(self):
        prev = {"scenes": {"0": self._scene()}}
        curr = {"scenes": {"0": self._scene(), "1": self._scene(script="new")}}
        diff = compute_diff(prev, curr)
        assert {d["scene"] for d in diff} == {1}

    def test_global_change_reassembles(self):
        prev = {"scenes": {"0": self._scene()}, "global": {"g": 1}}
        curr = {"scenes": {"0": self._scene()}, "global": {"g": 2}}
        diff = compute_diff(prev, curr)
        assert diff[0]["scene"] is None
        assert diff[0]["actions"] == ["reassemble"]


class TestManifestReuse:
    def test_voice_reusable_requires_hash_match(self):
        with tempfile.TemporaryDirectory() as td:
            wav = _write(os.path.join(td, "scene_0.wav"))
            m = Manifest(td)
            m.set_script(0, "hello")
            m.set_voice(0, wav, 3.2)
            m.save()

            m2 = Manifest(td).load()
            # same script + same wav bytes → reusable
            assert m2.voice_reusable(0, wav, "hello")
            # changed script text → NOT reusable (script hash mismatch)
            assert not m2.voice_reusable(0, wav, "different text")
            # missing wav → not reusable
            assert not m2.voice_reusable(0, os.path.join(td, "nope.wav"), "hello")

    def test_cross_topic_audio_cache_protection(self):
        """The v20 regression test: cache/audio/ is a GLOBAL dir shared by
        all topics.  A topic with the same scene count must NOT reuse
        another topic's narration.  The manifest prevents this because
        script hashes differ → voice_reusable returns False."""
        with tempfile.TemporaryDirectory() as td:
            wav = _write(os.path.join(td, "scene_0.wav"))
            # Topic A records manifest with script A
            m_a = Manifest(os.path.join(td, "topic_a"))
            m_a.set_script(0, "narration about Andromeda")
            m_a.set_voice(0, wav, 3.2)
            m_a.save()
            # Topic B has the same global wav on disk but a DIFFERENT script
            m_b = Manifest(os.path.join(td, "topic_b")).load()
            assert not m_b.voice_reusable(0, wav, "narration about time")

    def test_still_reusable_requires_recorded_hash(self):
        with tempfile.TemporaryDirectory() as td:
            img = _write(os.path.join(td, "s.jpg"))
            m = Manifest(td)
            # no prior record → never reusable
            assert not m.still_reusable(0, img, "")

    def test_add_shot_records_asset_hash_and_query(self):
        with tempfile.TemporaryDirectory() as td:
            asset = _write(os.path.join(td, "asset.jpg"))
            clip = _write(os.path.join(td, "clip.mp4"))
            m = Manifest(td)
            sid = m.add_shot(0, 1, file=clip, asset=asset, kind="ai",
                             query="GPS satellite", camera="push_in")
            assert sid == "s00_sh01"
            entry = m.data["scenes"]["0"]["shots"][0]
            assert entry["asset_hash"] == hash_file(asset)
            assert entry["query"] == "GPS satellite"
            assert entry["verification_passed"] is True


class TestRepairPlanTool:
    def test_plan_build(self):
        sys.path.insert(0, os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
        from repair_plan import build_plan, plan_to_flags
        with tempfile.TemporaryDirectory() as td:
            review = {
                "quality_score": 60,
                "defects": [
                    {"scene": 6, "shot": "s06_sh01",
                     "problem": "irrelevant_asset", "severity": "fatal",
                     "action": "regenerate_visual"},
                    {"scene": 3, "shot": None,
                     "problem": "unsupported_claim", "severity": "high",
                     "action": "rewrite_script"},
                ],
            }
            with open(os.path.join(td, "review_grok.json"), "w") as f:
                json_dump = __import__("json").dump
                json_dump(review, f)
            plan = build_plan(td)
            assert plan["defect_count"] == 2
            assert plan["assets"] == ["s06_sh01"]
            assert "rewrite_script" in plan["scenes"]["3"]
            flags = plan_to_flags(plan)
            assert "--assets s06_sh01" in flags
            assert "--scenes 3" in flags
