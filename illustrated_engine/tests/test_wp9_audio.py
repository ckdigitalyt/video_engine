"""WP9 — mood-tagged music library, library SFX, sting wiring, and
beat-snapped cuts (engine.v16_audio + the v14_assembly hooks it drives).

Run: python3 tests/test_wp9_audio.py   (exit 0 = all passed; no network)
"""
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]      # illustrated_engine
REPO = ROOT.parent                              # video_engine
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(ROOT))

from engine import v14_assembly as asm  # noqa: E402
from engine import v16_audio as va  # noqa: E402
from engine.procedural_audio import SR, save_wav  # noqa: E402

MUSIC_DIR = REPO / "assets" / "music"
SFX_DIR = REPO / "assets" / "sfx"


# ----------------------------------------------------------- arc -> mood --

def test_arc_mood_weights_dominant_by_duration():
    w = va.arc_mood_weights(
        ["HOOK", "EXPLANATION", "ESCALATION", "REVEAL", "PAYOFF"],
        [3, 10, 8, 5, 4])
    assert abs(sum(w.values()) - 1.0) < 1e-9
    assert va.dominant_mood(w) == "calm"  # EXPLANATION=10 is the biggest bloc


def test_arc_mood_weights_unknown_function_falls_back():
    w = va.arc_mood_weights(["SOMETHING_NEW"], [10.0])
    assert w == {va.DEFAULT_MOOD: 1.0}


def test_dominant_mood_tiebreak_is_alphabetical():
    assert va.dominant_mood({"triumph": 0.5, "calm": 0.5}) == "calm"


# ------------------------------------------------------------- libraries --

def test_load_music_library_has_all_moods_with_licensed_tracks():
    lib = va.load_music_library(MUSIC_DIR)
    assert set(lib.keys()) == set(va.MOODS)
    for mood in va.MOODS:
        assert lib[mood], f"no tracks for mood {mood}"
        for t in lib[mood]:
            row = t["licence"]
            for col in ("title", "artist", "source", "license",
                       "commercial_ok"):
                assert row.get(col), f"{t['path']}: missing {col}"


def test_load_sfx_library_has_tick_and_pulse_licensed():
    lib = va.load_sfx_library(SFX_DIR)
    for kind in ("tick", "pulse"):
        assert kind in lib
        row = lib[kind]["licence"]
        assert row.get("license") == "CC0-1.0"
        assert row.get("commercial_ok") == "true"
    assert "whoosh" not in lib  # no library file yet: procedural fallback


def test_library_asset_without_licence_row_raises():
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        (d / "wonder").mkdir()
        save_wav(d / "wonder" / "orphan.wav", np.zeros((SR, 2), np.float32))
        (d / "licences.csv").write_text("mood,file\n")
        try:
            va.load_music_library(d)
            assert False, "expected ValueError for an unlicensed asset"
        except ValueError as e:
            assert "orphan.wav" in str(e)


def test_select_track_deterministic_by_seed():
    lib = va.load_music_library(MUSIC_DIR)
    t1, m1 = va.select_track({"wonder": 1.0}, lib, seed="story_a")
    t2, m2 = va.select_track({"wonder": 1.0}, lib, seed="story_a")
    assert m1 == m2 == "wonder"
    assert t1["path"] == t2["path"]


def test_select_track_none_for_empty_library():
    t, mood = va.select_track({"wonder": 1.0}, {"wonder": []}, seed="x")
    assert t is None and mood == "wonder"


# -------------------------------------------------------------- bed loop --

def test_build_library_bed_trims_when_track_is_longer():
    track = va.load_music_library(MUSIC_DIR)["calm"][0]["path"]
    y = va.build_library_bed(track, total_s=2.0, gain=0.16)
    assert y.shape == (int(round(2.0 * SR)), 2)
    assert abs(float(np.max(np.abs(y))) - 0.16) < 1e-3


def test_build_library_bed_loops_when_track_is_shorter():
    with tempfile.TemporaryDirectory() as d:
        short = Path(d) / "short.wav"
        t = np.arange(int(0.5 * SR)) / SR
        y = np.sin(2 * np.pi * 220 * t).astype(np.float32)
        save_wav(short, np.stack([y, y], axis=1))
        out = va.build_library_bed(short, total_s=3.0, gain=0.1)
        assert out.shape == (int(round(3.0 * SR)), 2)
        assert not np.any(np.isnan(out))
        assert abs(float(np.max(np.abs(out))) - 0.1) < 1e-3


# ------------------------------------------------------------ sfx clips --

def test_load_sfx_clip_peak_matches_procedural_convention():
    lib = va.load_sfx_library(SFX_DIR)
    y = va.load_sfx_clip(lib["tick"]["path"])
    assert abs(float(np.max(np.abs(y))) - 0.25) < 1e-3


# ------------------------------------------------------------------ sting --

def test_overlay_sting_is_additive_at_head_only():
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        mix = d / "mix.wav"
        save_wav(mix, np.zeros((int(2 * SR), 2), np.float32))
        sting = d / "sting.wav"
        st = np.full((int(0.4 * SR), 2), 0.2, dtype=np.float32)
        save_wav(sting, st)
        out = va.overlay_sting(mix, sting, d / "out.wav")
        from engine.procedural_audio import load_wav
        y = load_wav(out)
        assert np.allclose(y[: int(0.4 * SR)], 0.2, atol=1e-3)
        assert np.allclose(y[int(0.4 * SR):], 0.0, atol=1e-6)


# ------------------------------------------------------- beat-snapped cuts --

def _click_track(bpm: float, dur_s: float) -> np.ndarray:
    n = int(dur_s * SR)
    mono = np.zeros(n)
    period = 60.0 / bpm
    t = 0.0
    click = np.hanning(200)
    while t < dur_s:
        i = int(t * SR)
        mono[i:i + len(click)] += click
        t += period
    return np.stack([mono, mono], axis=1)


def test_detect_beats_recovers_known_tempo():
    y = _click_track(120.0, 8.0)
    beats, bpm = va.detect_beats(y, sr=SR)
    assert abs(bpm - 120.0) < 3.0
    diffs = np.diff(beats)
    assert np.allclose(diffs, 0.5, atol=0.02)


def test_snap_cuts_to_beats_snaps_when_word_and_beat_are_close():
    out = va.snap_cuts_to_beats([1.00], [1.00], [1.02], tol=0.08)
    assert out == [1.02]


def test_snap_cuts_to_beats_leaves_cut_when_no_word_nearby():
    out = va.snap_cuts_to_beats([5.00], [5.50], [4.98], tol=0.08)
    assert out == [5.00]


def test_snap_cuts_to_beats_leaves_cut_when_beat_too_far():
    out = va.snap_cuts_to_beats([1.00], [1.02], [1.50], tol=0.08)
    assert out == [1.00]


# --------------------------------------------------------------- manifest --

def test_manifest_rows_shape_and_bool_coercion():
    lib = va.load_music_library(MUSIC_DIR)
    track, mood = va.select_track({"triumph": 1.0}, lib, seed="m")
    sfx_lib = va.load_sfx_library(SFX_DIR)
    rows = va.manifest_rows(track, sfx_lib, Path("/tmp/sting.wav"))
    kinds = [r["kind"] for r in rows]
    assert kinds.count("music") == 1
    assert kinds.count("sfx") == len(sfx_lib)
    assert kinds.count("sting") == 1
    music_row = next(r for r in rows if r["kind"] == "music")
    assert music_row["commercial_ok"] is True
    assert music_row["attribution_required"] is True


def test_manifest_rows_empty_when_nothing_selected():
    assert va.manifest_rows(None, None, None) == []


# ------------------------------------------------- v14_assembly wiring --

def _fixture_video(path: Path, dur: float = 2.0) -> Path:
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
         f"color=c=black:s=320x568:d={dur}:r=30", "-c:v", "libx264",
         "-pix_fmt", "yuv420p", str(path)], check=True)
    return path


def test_build_underscore_track_falls_back_without_library_track():
    """No 'track' key -> byte-identical procedural path (no regression)."""
    with tempfile.TemporaryDirectory() as d:
        out_old = Path(d) / "old.wav"
        out_new = Path(d) / "new.wav"
        scenes = [{"_dur": 2.0, "intensity": 0.7}]
        asm.build_underscore_track(scenes, 2.0, out_old, {"gain": 0.9})
        asm.build_underscore_track(scenes, 2.0, out_new,
                                   {"gain": 0.9, "track": None})
        assert out_old.read_bytes() == out_new.read_bytes()


def test_build_underscore_track_uses_library_track_when_given():
    track = va.load_music_library(MUSIC_DIR)["calm"][0]["path"]
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "bed.wav"
        scenes = [{"_dur": 2.0, "intensity": 0.6}]
        asm.build_underscore_track(scenes, 2.0, out,
                                   {"gain": 0.16, "track": track})
        from engine.procedural_audio import load_wav
        y = load_wav(out)
        assert y.shape[0] == int(round(2.0 * SR))
        assert abs(float(np.max(np.abs(y))) - 0.16) < 1e-3


def test_build_sfx_track_uses_library_for_matching_kind_only():
    sfx_lib = va.load_sfx_library(SFX_DIR)
    scenes = [{"scene_id": "s1", "_start": 0.0,
              "sfx": [{"t": 0.1, "kind": "tick", "gain": 1.0},
                     {"t": 0.5, "kind": "whoosh", "gain": 1.0}]}]
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "sfx.wav"
        warnings = []
        _, placed = asm.build_sfx_track(scenes, 2.0, out, warnings,
                                        sfx_library=sfx_lib)
        assert not warnings
        assert {p["kind"] for p in placed} == {"tick", "whoosh"}


def test_assemble_overlays_sting_when_plan_provides_one():
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        vid = _fixture_video(d / "s1.mp4")
        sting = d / "sting.wav"
        save_wav(sting, np.full((int(0.3 * SR), 2), 0.3, dtype=np.float32))
        plan = {"story_id": "wp9smoke",
               "scenes": [{"scene_id": "s1", "video": str(vid)}],
               "music": {"gain": 0.1}, "sting_audio": str(sting),
               "single_pass": True, "out": str(d / "final.mp4")}
        rep = asm.assemble(plan, d / "work", plan_dir=d)
        assert rep["audio_mix"]["sting"] == str(sting)
        assert Path(rep["final"]["path"]).exists()


def test_assemble_without_sting_key_has_no_sting_in_report():
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        vid = _fixture_video(d / "s1.mp4")
        plan = {"story_id": "wp9smoke2",
               "scenes": [{"scene_id": "s1", "video": str(vid)}],
               "music": {"gain": 0.1}, "single_pass": True,
               "out": str(d / "final.mp4")}
        rep = asm.assemble(plan, d / "work", plan_dir=d)
        assert rep["audio_mix"]["sting"] is None


if __name__ == "__main__":
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except Exception as e:  # noqa: BLE001
                fails += 1
                print(f"FAIL {name}: {e!r}"[:400])
    print(f"{'ALL PASS' if not fails else f'{fails} FAILED'}")
    sys.exit(1 if fails else 0)
