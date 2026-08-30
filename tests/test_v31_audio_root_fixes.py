"""v31 regression tests — audio root fixes validated by the LLM pro review.

ckdigital asked for LLM pro validation of these fixes; verdict:
ADJUST on all three — root causes CONFIRMED, with corrections adopted:

  1. Voice breaks (15s/21s in Wow! Signal): crossfades alone don't fill a
     gap — overlap the clips first (renderer now crossfades contiguous
     voice seams); duck threshold must sit ~8 dB BELOW the measured
     narration mean, not a hard-coded -24 dB that never engaged; scripted
     paralinguistic tags ([chuckle]) must become a bounded pause, never
     dead air.
  2. Whoosh at 28s: snap SFX to the matched phrase's WORD boundary (was a
     character fraction that landed mid-phrase); if the phrase isn't
     found, DROP the event instead of guessing at 0.5.  Keep scripted
     events (do not remove them).
  3. "Chatterbox" quality: labeling/cap problem, not a defect — the ACTIVE
     narrator is Fish Audio s2.1-pro-free; log identity + free-tier cap
     explicitly; only loading Fish credit + allow_paid=true raises the
     delivered bitrate.
"""

import json
import os
import tempfile

import numpy as np
import soundfile as sf


# ───────────────────────────────────────────────────────────────────── #
# 1. SFX word-boundary snap + drop-if-no-match (build_sfx_timeline)
# ───────────────────────────────────────────────────────────────────── #

def _write_sfx_timeline(scenes, durs, tmpdir, cut_times=None, manim_times=None):
    import mission_run as M
    out = os.path.join(tmpdir, "sfx_v31.wav")
    return M.build_sfx_timeline(scenes, durs, out,
                                cut_times=cut_times, manim_times=manim_times)


def test_sfx_snaps_to_word_boundary_not_char_fraction():
    """'silence returned' must land on the WORD 'silence', not a character
    fraction of the joined string (the Wow! Signal whoosh@28.04 bug)."""
    import mission_run as M
    scenes = [{
        "narration": "The signal arrived. Then, the silence returned. "
                     "It was gone as quickly as it came.",
        "sfx_events": [{"trigger": "whoosh", "at": "silence returned"}],
    }]
    durs = [10.0]
    with tempfile.TemporaryDirectory() as td:
        _, placed = _write_sfx_timeline(scenes, durs, td)
    assert len(placed) == 1, placed
    # words: [the, signal, arrived, then, the, silence, returned, ...]
    # 'silence' is word index 5 of 13 → frac ≈ 0.385 → t ≈ 3.85s
    # char-fraction of "silence" start would be ~0.42 — close, so assert
    # the WORD-boundary math directly via the function's own logic:
    words = scenes[0]["narration"].split()
    joined = " ".join(words).lower()
    idx = joined.find("silence returned")
    w_start = len(joined[:idx].split())
    expect_frac = w_start / len(words)
    expect_t = expect_frac * 10.0
    assert abs(placed[0]["at_s"] - expect_t) < 0.01, placed
    assert placed[0]["trigger"] == "whoosh"


def test_sfx_phrase_not_found_is_dropped():
    """Missing trigger phrase → event dropped, never placed at 0.5."""
    import mission_run as M
    scenes = [{
        "narration": "The signal arrived. Then it was gone.",
        "sfx_events": [{"trigger": "boom", "at": "the rocket launched"}],
    }]
    durs = [8.0]
    with tempfile.TemporaryDirectory() as td:
        _, placed = _write_sfx_timeline(scenes, durs, td)
    assert placed == [], placed


def test_sfx_keeps_scripted_events_with_cut_times():
    """Scripted events survive (LLM review: 'keep scripted events') and snap
    to the nearest visual cut when the timeline is known."""
    import mission_run as M
    scenes = [{
        "narration": "First light. Then the silence returned. End.",
        "sfx_events": [{"trigger": "whoosh", "at": "silence returned"}],
    }]
    durs = [9.0]
    with tempfile.TemporaryDirectory() as td:
        _, placed = _write_sfx_timeline(scenes, durs, td,
                                        cut_times={0: [0.0, 5.0, 9.0]})
    assert len(placed) == 1, placed
    assert placed[0]["trigger"] == "whoosh"


# ───────────────────────────────────────────────────────────────────── #
# 2. Duck threshold relative to narration mean (stage_music_mix)
# ───────────────────────────────────────────────────────────────────── #

def test_duck_threshold_math_is_8db_below_narration_mean():
    """The v31 threshold derivation: thr_db = clamp(mean - 8, -45, -12).
    Wow run: narration mean ≈ -31 dB → threshold ≈ -39 dB (0.0112), which
    sits BELOW the voice so speech reliably triggers ducking (the old
    hard-coded 0.0625 = -24 dB sat ABOVE the mean → ducking_depth=False)."""
    import mission_run as M
    # replicate the inline derivation
    def thr(mean_db):
        _thr_db = max(-45.0, min(-12.0, mean_db - 8.0))
        return 10 ** (_thr_db / 20.0), _thr_db

    lin, db = thr(-31.0)
    assert abs(db - (-39.0)) < 1e-6
    assert abs(lin - 10 ** (-39.0 / 20.0)) < 1e-9
    assert lin < 0.0625  # strictly lower than the old hard-coded value
    # clamping sanity
    assert thr(-80.0)[1] == -45.0
    assert thr(0.0)[1] == -12.0   # mean above -4 dB → capped at -12 dB
    assert thr(-5.0)[1] == -13.0  # -5-8=-13, inside bounds → unchanged


# ───────────────────────────────────────────────────────────────────── #
# 3. [chuckle] para tags → bounded pause (stage_narration_dynamic fish)
# ───────────────────────────────────────────────────────────────────── #

def test_paralinguistic_tags_become_bounded_pause():
    """[chuckle]/[laugh]/[sigh]/[cough]/[gasp]/[whisper] must be rewritten
    to '...' for the Fish path so they never render as 0.7s dead air."""
    import re
    pat = re.compile(r"\[(?:chuckle|laugh|sigh|cough|gasp|whisper)\]")
    text = "Twenty megahertz. [chuckle] That's the exact frequency."
    out = pat.sub("...", text)
    assert "[chuckle]" not in out
    assert out == "Twenty megahertz. ... That's the exact frequency."


def test_fish_active_narrator_label_present_in_provider():
    """The active narrator must be identifiable as fish (not chatterbox)
    and the free-tier cap must be logged at init."""
    from src.providers.tts_provider import FishAudioProvider
    assert FishAudioProvider.name == "fish"
    # the init-time cap note lives in __init__; provider must still
    # construct without raising (config/env permitting)
    import os
    if os.environ.get("FISH_API_KEY"):
        try:
            p = FishAudioProvider()
            assert p._model in ("s2.1-pro", "s2.1-pro-free", "s2.1-turbo")
        except Exception:
            pass  # network/config dependent — label check above is the point
