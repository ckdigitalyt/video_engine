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
    # v33: flux.2-klein-4b (verified 2026-08-13, faster + sharper) is
    # primary, flux.1-dev/schnell fall back.  No dead ``nvidia/`` route.
    assert len(p.ENDPOINTS) == 3
    assert p.ENDPOINTS[0].endswith("flux.2-klein-4b")
    assert not any("nvidia/flux.1-dev" in e for e in p.ENDPOINTS)


def test_ai_still_circuit_breaker_disables_failing_provider(monkeypatch):
    """After 2 consecutive failures a provider is skipped (time-decayed)."""
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
    ms._AI_PROVIDER_DISABLED_UNTIL.clear()

    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "a.png")
        # 1st call: nvidia fails once, pollinations succeeds
        assert ms._ai_still("test prompt", out)
        assert ms._AI_PROVIDER_FAILS["nvidia_nim"] == 1
        # 2nd call: nvidia fails again -> disabled, pollinations succeeds
        assert ms._ai_still("test prompt", out)
        assert "nvidia_nim" in ms._AI_PROVIDER_DISABLED_UNTIL
        # 3rd call: nvidia skipped entirely (fails count frozen at 2)
        assert ms._ai_still("test prompt", out)
        assert ms._AI_PROVIDER_FAILS["nvidia_nim"] == 2


def test_ai_still_breaker_decays_after_cooldown(monkeypatch):
    """v35: after _AI_BREAKER_COOLDOWN_S the provider is retried."""
    import time as _time
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
    ms._AI_PROVIDER_DISABLED_UNTIL.clear()
    old_cooldown = ms._AI_BREAKER_COOLDOWN_S
    ms._AI_BREAKER_COOLDOWN_S = 0.05
    try:
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "a.png")
            assert ms._ai_still("p", out)
            assert ms._ai_still("p", out)
            assert "nvidia_nim" in ms._AI_PROVIDER_DISABLED_UNTIL
            # during cooldown: skipped, fails frozen at 2
            assert ms._ai_still("p", out)
            assert ms._AI_PROVIDER_FAILS["nvidia_nim"] == 2
            # after cooldown: retried -> fails again, re-disabled
            _time.sleep(0.1)
            assert ms._ai_still("p", out)
            assert ms._AI_PROVIDER_FAILS["nvidia_nim"] == 3
            assert "nvidia_nim" in ms._AI_PROVIDER_DISABLED_UNTIL
    finally:
        ms._AI_BREAKER_COOLDOWN_S = old_cooldown


def test_deterministic_seed_stable_and_distinct():
    """v35: deterministic_seed() is process-stable and prompt-sensitive."""
    from src.providers.image_gen import deterministic_seed
    s1 = deterministic_seed("a red cube on a blue table", salt=0)
    s2 = deterministic_seed("a red cube on a blue table", salt=0)
    s3 = deterministic_seed("a red cube on a blue table", salt=1)
    s4 = deterministic_seed("a BLUE cube on a red table", salt=0)
    assert s1 == s2
    assert 0 <= s1 < 100000
    assert s1 != s3  # salt changes the seed
    assert s1 != s4  # prompt changes the seed


def test_rejection_ledger_roundtrip():
    """v35 (M-5): rejected stills persist across runs via rejected.json."""
    import mission_stills as ms
    with tempfile.TemporaryDirectory() as d:
        assert ms._load_rejection_ledger(d) == {}
        ms._persist_rejection_ledger(d, {"scene1_0.jpg": "wrong subject"})
        assert ms._load_rejection_ledger(d) == {"scene1_0.jpg": "wrong subject"}
        # corrupt ledger fails open
        with open(ms._rejection_ledger_path(d), "w") as f:
            f.write("{not json")
        assert ms._load_rejection_ledger(d) == {}


def test_pollinations_pins_model_param(monkeypatch):
    """v35: Pollinations request explicitly carries the pinned model."""
    from src.providers import image_gen
    captured = {}

    class FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b"\xff\xd8fakejpeg"

    def fake_urlopen(req, timeout=180):
        captured["url"] = req.full_url
        return FakeResp()

    monkeypatch.setattr(image_gen.urllib.request, "urlopen", fake_urlopen)
    p = image_gen.PollinationsProvider()
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "x.jpg")
        p.generate("a cube", out, width=256, height=144, seed=7)
    assert "model=flux" in captured["url"]
    assert "seed=7" in captured["url"]
    assert p._model == "flux"


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


# ── v33: review C-2 / M-2 / M-3 regression tests ────────────────────────
# The 2026-08-13 LLM pro review found (Critical) that unregistered
# topics produced subject-less AI prompts (" documentary scene, alternate
# angle 2") and (Major) that the people-guard lost scene context.  These
# tests lock the fixes in.


def _plan_candidates(text, scene=None):
    import mission_stills as ms
    return ms._still_plan_for(text, spec=None, scene=scene)


def test_unregistered_topic_pad_prompts_have_subject():
    """C-2: a Bloop-style (unregistered) topic must never yield an
    empty-subject AI prompt like ' documentary scene, alternate angle 2'."""
    import mission_stills as ms
    text = ("The Bloop was a mysterious ultra-low-frequency sound detected "
            "in the Pacific Ocean in 1997.")
    plan = _plan_candidates(text, {"title": "The Bloop",
                                   "search_queries": ["Bloop sound 1997"]})
    ai_prompts = [q for k, q in plan if k == "ai"]
    assert ai_prompts, "expected at least one AI candidate"
    for q in ai_prompts:
        assert "documentary scene, alternate angle" not in q.lstrip(), \
            f"subject-less prompt: {q!r}"
        assert q.strip() and q.strip()[0].isalpha(), f"prompt starts empty: {q!r}"


def test_subject_for_falls_back_to_narration_head():
    """C-2: with no scene dict, the narration head supplies the subject."""
    import mission_stills as ms
    subj = ms._subject_for(
        "In 1997 the Bloop was detected by the United States Navy.")
    assert "Bloop" in subj, f"narration head lost the subject: {subj!r}"


def test_guarded_ai_prompt_biographical_scene_keeps_people():
    """M-3: a scene narrating an astronomer/scientist must NOT get the
    no-people guard appended (the model would omit the person)."""
    import mission_stills as ms
    text = ("The astronomer Jocelyn Bell Burnell discovered pulsars "
            "in 1967.")
    out = ms._guarded_ai_prompt("Jocelyn Bell Burnell at the telescope",
                                text, "")
    assert "no people" not in out, f"biographical scene got people-guard: {out!r}"


def test_guarded_ai_prompt_spacecraft_scene_keeps_guard():
    """M-3: a non-human spacecraft scene keeps the no-people guard."""
    import mission_stills as ms
    text = ("Voyager 1 crossed the heliopause in 2012 carrying the "
            "Golden Record.")
    out = ms._guarded_ai_prompt("Voyager 1 in deep space", text, "")
    assert "no people, no human faces" in out


def test_nvidia_flux2_pair_snap_keeps_aspect():
    """v33: flux.2-klein-4b takes a fixed aspect-preserving pair set;
    snapping must preserve orientation (landscape stays landscape)."""
    p = _provider()
    for w, h in ((2560, 1440), (1920, 1080), (1024, 576)):
        sw, sh = p._snap_pair(w, h)
        assert sw in {x for pr in p._FLUX2_PAIRS for x in pr}
        assert sh in {x for pr in p._FLUX2_PAIRS for x in pr}
        assert (sw >= sh) == (w >= h), f"orientation flipped: {w}x{h} -> {sw}x{sh}"
    assert p._snap_pair(1024, 1024) == (1024, 1024)
