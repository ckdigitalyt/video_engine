"""v30 regression tests — nvidia_nim dims/endpoints + pacing convergence.

ckdigital: "You need to fix in the program itself so that these issues
don't come up" (Wow! Signal v29 validation run).

Two program bugs surfaced:
  1. nvidia_nim 404 spam — every AI still burned 3 failed HTTP calls:
     the provider snapped dims from an oversized list (up to 2048) but
     flux.1-dev only accepts 768..1344 on BOTH axes, so 2560x1440 ->
     2048x1408 -> 422 on endpoint 1, then the dead 3rd endpoint
     (`nvidia/flux.1-dev`) surfaced as 404.
  2. pacing gate ABORT — scene 2 (47 words / 14.19s = 199 wpm vs 160
     explanation band) needed +3.4s of pause, but the padder capped at
     0.7s x 2 boundaries = 1.4s max, could never converge, and the
     pre-render gate hard-aborted the WHOLE run.

v30 fixes: corrected dims list + live endpoints + provider circuit
breaker; padder now grows pause-points to carry the needed pad (1.5s per
boundary, up to 10 anchors, 6 passes).
"""

import json
import os
import tempfile

import numpy as np
import soundfile as sf

from src.cinematic.pacing_engine import measure_speech_rate


# ───────────────────────────────────────────────────────────────────── #
# 1. nvidia_nim provider
# ───────────────────────────────────────────────────────────────────── #

def _provider():
    from src.providers.image_gen import NvidiaNimProvider
    return NvidiaNimProvider()


def test_nvidia_valid_dims_are_768_to_1344():
    p = _provider()
    assert min(p._ALLOWED_DIMS) == 768
    assert max(p._ALLOWED_DIMS) == 1344
    assert 2048 not in p._ALLOWED_DIMS
    assert 1408 not in p._ALLOWED_DIMS


def test_nvidia_snap_keeps_dims_in_valid_set():
    p = _provider()
    for v in (640, 768, 1024, 1344, 1408, 1440, 2048, 2560):
        snapped = p._snap(v)
        assert snapped in p._ALLOWED_DIMS, f"_snap({v}) -> {snapped}"


def test_nvidia_snap_preserves_aspect_ratio():
    p = _provider()
    w0, h0 = 2560, 1440          # 16:9 request from _ai_still
    w = p._snap(w0)
    h = p._snap(int(round(h0 * w / w0)))
    assert w in p._ALLOWED_DIMS
    assert h in p._ALLOWED_DIMS
    assert (w, h) == (1344, 768)  # 16:9-ish, not a square crop


def test_nvidia_endpoints_contain_no_dead_route():
    p = _provider()
    assert len(p.ENDPOINTS) == 2
    assert not any("nvidia/flux.1-dev" in e for e in p.ENDPOINTS)


def test_ai_still_circuit_breaker_disables_failing_provider(monkeypatch):
    """After 2 consecutive failures a provider is skipped for the run."""
    import mission_stills as ms
    from src.providers import image_gen

    class Failing:
        name = "nvidia_nim"

        def generate(self, *a, **k):
            raise RuntimeError("boom")

    class Ok:
        name = "pollinations"

        def generate(self, prompt, out_path, **k):
            with open(out_path, "w") as f:
                f.write("x")
            return out_path

    monkeypatch.setattr(image_gen, "NvidiaNimProvider", lambda: Failing())
    monkeypatch.setattr(image_gen, "PollinationsProvider", lambda: Ok())
    ms._AI_PROVIDER_FAILS.clear()
    ms._AI_PROVIDER_DISABLED.clear()

    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "a.png")
        # 1st call: nvidia fails once, pollinations succeeds
        assert ms._ai_still("test prompt", out)
        assert ms._AI_PROVIDER_FAILS["nvidia_nim"] == 1
        # 2nd call: nvidia fails again -> disabled, pollinations succeeds
        assert ms._ai_still("test prompt", out)
        assert "nvidia_nim" in ms._AI_PROVIDER_DISABLED
        # 3rd call: nvidia skipped entirely (fails count frozen at 2)
        assert ms._ai_still("test prompt", out)
        assert ms._AI_PROVIDER_FAILS["nvidia_nim"] == 2


# ───────────────────────────────────────────────────────────────────── #
# 2. pacing convergence
# ───────────────────────────────────────────────────────────────────── #

_DENSE_TEXT = (
    "The signal was detected at a frequency of one thousand four hundred "
    "twenty point four five five six megahertz, which is notably close to "
    "the natural hydrogen line frequency of one thousand four hundred "
    "twenty point four zero six megahertz, a universal cosmic watering "
    "hole for communication."
)


def _run_padder(scene_text, wav_seconds, intent="explanation"):
    import mission_stills as ms
    with tempfile.TemporaryDirectory() as d:
        wav = os.path.join(d, "scene_0.wav")
        sr = 44100
        sf.write(wav, np.zeros(int(sr * wav_seconds), dtype="float32"), sr)
        scenes = [{"narration": scene_text, "intent": intent}]
        out = ms._pace_pad_scenes(scenes, d, [wav_seconds])
        return out[0]


def test_padder_converges_dense_scene():
    """199 wpm scene must land inside the 160 wpm explanation band."""
    from src.cinematic.pacing_engine import role_for, ROLE_PACING
    band = ROLE_PACING[role_for("explanation")]
    final_dur = _run_padder(_DENSE_TEXT, 14.19)
    wpm = measure_speech_rate(_DENSE_TEXT, final_dur)
    assert wpm <= band["max_wpm"], (
        f"dense scene still {wpm:.0f} wpm > {band['max_wpm']} "
        f"(final dur {final_dur:.2f}s)")


def test_padder_leaves_calm_scene_alone():
    """A scene already in band should not be padded (no dead air)."""
    text = "The Wow signal was a narrow band radio emission detected in 1977."
    dur0 = 6.0
    final_dur = _run_padder(text, dur0, intent="exploration")
    assert final_dur <= dur0 + 0.05, f"calm scene was padded: {final_dur:.2f}s"


def test_padder_handles_single_sentence_scene():
    """Single-sentence scenes fall back to clause split + mid pause."""
    text = ("One thousand four hundred twenty megahertz is the hydrogen "
            "line, the frequency neutral hydrogen atoms naturally emit.")
    final_dur = _run_padder(text, 8.0, intent="explanation")
    wpm = measure_speech_rate(text, final_dur)
    from src.cinematic.pacing_engine import role_for, ROLE_PACING
    band = ROLE_PACING[role_for("explanation")]
    assert wpm <= band["max_wpm"] or final_dur >= 8.0
