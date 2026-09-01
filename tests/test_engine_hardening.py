"""v4.1 algorithmic hardening tests.

Covers the four systemic failure classes found in the r4/r5 dino_v2 passes:
  * assembler clone-pad freeze   → fit_beat_durations (no-freeze beat fit)
  * broken clips shipped         → render_shot duration validation +
                                   record_is_stale
  * catastrophic shots hidden in → visual_gate per-shot floor
    the average
  * critic LLM JSON fragility    → extract_json sanitization
"""

import pytest

import subprocess

from engine.v3.assemble.assembler import MAX_CONFORM_STRETCH, fit_beat_durations
from engine.v3.qa.technical import chroma_stats
from engine.v3.qa.video_qa import SHOT_SCORE_FLOOR, VISUAL_SCORE_MIN, visual_gate
from engine.v3.render.runner import RENDER_ENGINE_REV, record_is_stale
from engine.v3.story.llm import LLMError, extract_json


class TestFitBeatDurations:
    def test_redistributes_shortfall_to_headroom(self):
        # S01 clip 5.9s but target 7.8s (deficit 1.9); sibling S02 clip 4.0s
        # with target 1.9s (headroom 2.1). The r4 bug: S01 got clone-padded.
        targets = {"S01": 7.8, "S02": 1.9}
        clips = {"S01": 5.9, "S02": 4.0}
        final, info = fit_beat_durations(targets, clips)
        assert abs(sum(final.values()) - sum(targets.values())) < 1e-6
        assert final["S01"] == pytest.approx(5.9, abs=1e-3)  # full clip, no pad
        assert final["S02"] == pytest.approx(3.8, abs=1e-3)  # absorbs shortfall
        assert final["S02"] <= clips["S02"] + 1e-3  # donor stays within clip
        assert info == {}  # nothing needed stretching or padding

    def test_stretch_covers_moderate_shortfall(self):
        targets = {"A": 6.0}  # clip 5.5 → +9.1%, inside the 15% cap
        clips = {"A": 5.5}
        final, info = fit_beat_durations(targets, clips)
        assert abs(sum(final.values()) - 6.0) < 1e-6
        assert info["A"]["stretch"] == pytest.approx(6.0 / 5.5, abs=1e-3)
        assert info["A"]["freeze_pad"] == 0.0

    def test_residual_freeze_is_visible_after_stretch_caps_out(self):
        targets = {"A": 9.6}  # clip 5.9, no siblings — r4 S01 situation
        clips = {"A": 5.9}
        final, info = fit_beat_durations(targets, clips)
        assert abs(sum(final.values()) - 9.6) < 1e-6
        assert info["A"]["stretch"] == pytest.approx(MAX_CONFORM_STRETCH,
                                                     abs=1e-3)
        assert info["A"]["freeze_pad"] == pytest.approx(
            9.6 - 5.9 * MAX_CONFORM_STRETCH, abs=1e-3)

    def test_unknown_clip_durations_left_untouched(self):
        targets = {"A": 4.0}
        final, info = fit_beat_durations(targets, {})
        assert final == targets
        assert info == {}

    def test_multiple_deficits_share_donor_headroom(self):
        targets = {"A": 8.0, "B": 7.0, "C": 1.0}
        clips = {"A": 5.0, "B": 5.0, "C": 9.0}
        final, info = fit_beat_durations(targets, clips)
        assert abs(sum(final.values()) - sum(targets.values())) < 1e-6
        # C absorbs everything it can; A/B stretch for the rest, no pad.
        assert final["C"] == pytest.approx(6.0, abs=1e-3)
        assert all(v["freeze_pad"] == 0.0 for v in info.values())


class TestVisualGateFloor:
    @staticmethod
    def _reports(scores):
        return {sid: {"score": s, "vision_available": True}
                for sid, s in scores.items()}

    def test_floor_fails_catastrophic_shot_even_when_average_passes(self):
        # avg = 65.0 → average gate alone would pass; the floor must catch
        # the near-black render (S14 = 35), the r5 failure mode.
        reports = self._reports({"S01": 85.0, "S14": 35.0, "S20": 75.0})
        assert sum(r["score"] for r in reports.values()) / 3 >= VISUAL_SCORE_MIN
        g = visual_gate(reports)
        assert not g["pass"]
        assert f"below per-shot floor {SHOT_SCORE_FLOOR}" in str(g)

    def test_passes_when_all_shots_above_floor(self):
        reports = self._reports({f"S{i}": 70.0 + (i % 3) for i in range(6)})
        g = visual_gate(reports)
        assert g["pass"], g


class TestRecordIsStale:
    @staticmethod
    def _rec(tmp_path, **kw):
        p = tmp_path / "clip.mp4"
        p.write_bytes(b"fake")
        rec = {"ok": True, "path": str(p),
               "metadata": {"engine_rev": RENDER_ENGINE_REV}}
        rec.update(kw)
        return rec

    def test_fresh_record(self, tmp_path, monkeypatch):
        monkeypatch.setattr("engine.v3.render.runner.probe_video_duration",
                            lambda p: 7.0)
        assert record_is_stale(self._rec(tmp_path),
                               {"shot_id": "S1", "duration_sec": 6.0}) is None

    def test_missing_artifact(self, tmp_path):
        rec = {"ok": True, "path": str(tmp_path / "gone.mp4"), "metadata": {}}
        assert record_is_stale(rec, {}) == "no rendered artifact"

    def test_engine_rev_mismatch(self, tmp_path):
        rec = self._rec(tmp_path)
        rec["metadata"]["engine_rev"] = "v4.0"
        assert "engine_rev" in record_is_stale(rec, {})

    def test_duration_undershoot(self, tmp_path, monkeypatch):
        # r5 reality: S17 shipped at 1.40s against a 5.69s plan.
        monkeypatch.setattr("engine.v3.render.runner.probe_video_duration",
                            lambda p: 1.4)
        reason = record_is_stale(self._rec(tmp_path),
                                 {"shot_id": "S17", "duration_sec": 5.69})
        assert "60%" in reason


class TestExtractJson:
    def test_plain(self):
        assert extract_json('{"a": 1}') == {"a": 1}

    def test_trailing_commas(self):
        assert extract_json('{"a": [1, 2,], "b": 3,}') == {"a": [1, 2], "b": 3}

    def test_python_literals(self):
        assert extract_json('{"ok": True, "off": False, "x": None}') == \
            {"ok": True, "off": False, "x": None}

    def test_smart_quotes(self):
        assert extract_json('{"reason": “flat frames”}') == \
            {"reason": "flat frames"}

    def test_fenced_with_prose(self):
        text = 'Here you go:\n```json\n{"score": 7}\n```\nDone.'
        assert extract_json(text) == {"score": 7}

    def test_prose_wrapped_with_trailing_comma(self):
        text = 'The critic says {"score": 7, "notes": [1, 2,]} as requested.'
        assert extract_json(text) == {"score": 7, "notes": [1, 2]}

    def test_garbage_raises_llm_error(self):
        with pytest.raises(LLMError):
            extract_json("no json here at all")


class TestChromaStats:
    """r5 S23/S24 shipped uniform green monochrome stills unnoticed."""

    def test_uniform_green_flagged(self, tmp_path):
        png = tmp_path / "green.png"
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=0x00AA00:s=64x64",
             "-frames:v", "1", str(png)], capture_output=True, check=True)
        stats = chroma_stats(png)
        assert stats["available"] and stats["cast"]

    def test_neutral_gray_passes(self, tmp_path):
        png = tmp_path / "gray.png"
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=gray:s=64x64",
             "-frames:v", "1", str(png)], capture_output=True, check=True)
        stats = chroma_stats(png)
        assert stats["available"] and not stats["cast"]
