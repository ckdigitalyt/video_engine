"""WP3 — voice layer: whole-video fallback, Fish paid gate, lexicon, round-trip
WER/hard-token gate, script-aligned word timing, designed gaps.

Run: python3 tests/test_wp3_voice.py   (exit 0 = all passed)
Unit tests use fake providers / fake ASR (no models, no network). The two
`live_*` tests need the local Kokoro + faster-whisper models and are skipped
when the models are absent.
"""
import json
import os
import sys
import tempfile
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
FIX = Path(__file__).resolve().parent / "fixtures"

from engine import voice as V  # noqa: E402
from engine.voice import align, qa  # noqa: E402
from engine.voice.fish import FishProvider, parse_segments  # noqa: E402
from engine.voice.lexicon import Lexicon, hard_words  # noqa: E402
from engine.voice.text import (edit_align, flat_tokens, int_to_words,  # noqa: E402
                               norm_tokens, split_sentences)

SCRIPT = ("That pigeon is a dinosaur. Not related to one. It is one. "
          "Sixty-six million years ago, a rock ten kilometres wide slammed "
          "into Mexico, and the age of giants ended. Tyrannosaurus, gone.")
SR = 24000


def _cfg():
    return V.load_config()


class FakeProvider:
    """Fixed-length tone per sentence; records what it was asked."""
    name = "fake"

    def __init__(self, tag="k", fail_after=None):
        self.tag, self.fail_after, self.calls = tag, fail_after, []

    def synth(self, text, speed):
        if self.fail_after is not None and len(self.calls) >= self.fail_after:
            raise V.VoiceUnavailable("forced failure")
        self.calls.append((text, speed))
        n = int(SR * 0.1 * len(text.split()))
        t = np.arange(n) / SR
        return V.Clip((0.3 * np.sin(2 * np.pi * 220 * t)).astype(np.float32),
                      SR, None)


def _asr_perfect(script_of):
    """ASR that hears the script exactly, spread evenly over the wav."""
    def fn(wav):
        text = script_of()
        with wave.open(str(wav)) as w:
            dur = w.getnframes() / w.getframerate()
        ws = text.split()
        return [{"w": x, "t0": dur * i / len(ws), "t1": dur * (i + .9) / len(ws)}
                for i, x in enumerate(ws)]
    return fn


def _beats():
    return [{"beat_id": "B1", "function": "HOOK",
             "narration": "That pigeon is a dinosaur. It is one."},
            {"beat_id": "B2", "function": "EXPLANATION",
             "narration": "A rock ten kilometres wide slammed into Mexico."},
            {"beat_id": "B3", "function": "PAYOFF",
             "narration": "Remember what it is."}]


# ------------------------------------------------------------------ text --

def test_text_helpers():
    assert int_to_words(66) == "sixty six"
    assert int_to_words(1271) == "one thousand two hundred seventy one"
    assert norm_tokens("Sixty-six") == norm_tokens("66") == ["sixty", "six"]
    assert norm_tokens("kilometres") == norm_tokens("kilometers")
    assert norm_tokens("1,271") == norm_tokens("1271")
    assert split_sentences("Hi there. It is one... remember it. Go!") == [
        "Hi there.", "It is one... remember it.", "Go!"]
    ops = edit_align(list("abc"), list("axc"))
    assert [o for *_, o in ops] == ["C", "S", "C"]


# --------------------------------------------------------------- lexicon --

def test_lexicon_respell_phonemes_and_hard_words():
    lex = Lexicon({"Tyrannosaurus": {"respell": "Tie-ran-uh-SAWR-us",
                                     "phonemes": "TYR"}})
    assert lex.respell("Then Tyrannosaurus, gone.") == \
        "Then Tie-ran-uh-SAWR-us, gone."
    ph = lex.to_phonemes("That Tyrannosaurus, gone.",
                         lambda s, lang: "<" + s.strip() + ">")
    assert ph == "<That> TYR, <, gone.>".replace("TYR, <, gone.>", "TYR<, gone.>") \
        or ph.startswith("<That> TYR"), ph
    hard = hard_words("Tyrannosaurus, gone. It ran 66 miles in Mexico.", lex)
    words = "Tyrannosaurus, gone. It ran 66 miles in Mexico.".split()
    assert {words[i] for i in hard} == {"Tyrannosaurus,", "66", "Mexico."}


def test_lexicon_heard_as_alias():
    lex = Lexicon({"Betelgeuse": {"heard_as": ["beetlejuice"]}})
    hyp = flat_tokens("it is beetlejuice".split())[0]
    assert lex.canonical(hyp) == ["it", "is", "betelgeuse"]


# -------------------------------------------------------------------- qa --

def _asr(text):
    return [{"w": w, "t0": i * .3, "t1": i * .3 + .25}
            for i, w in enumerate(text.split())]


def test_wer_gate_passes_spelling_and_digit_variants():
    heard = SCRIPT.replace("kilometres", "kilometers").replace(
        "Sixty-six", "66").lower()
    r = qa.round_trip(SCRIPT, _asr(heard), Lexicon())
    assert r["wer"] == 0 and r["verdict"] == "PASS", r


def test_hard_token_miss_fails_even_under_wer_limit():
    heard = SCRIPT.replace("Tyrannosaurus", "terenasaurus")
    r = qa.round_trip(SCRIPT, _asr(heard), Lexicon({"tyrannosaurus": {}}))
    assert r["wer"] < 0.05
    assert r["hard_missed"] == ["Tyrannosaurus,"], r
    assert r["verdict"] == "FAIL"
    # a long capitalised sentence opener is a hard token even with no lexicon
    r2 = qa.round_trip(SCRIPT, _asr(heard), Lexicon(), max_wer=0.5)
    assert r2["verdict"] == "FAIL" and r2["hard_missed"], r2


def test_wer_over_limit_fails():
    heard = " ".join(SCRIPT.split()[:-6])
    assert qa.round_trip(SCRIPT, _asr(heard), Lexicon())["verdict"] == "FAIL"


# ------------------------------------------------------------- alignment --

def test_script_alignment_uses_script_spelling_and_interpolates():
    asr = _asr("that pigeon is dinosaur not related to one it is one")
    words, direct = align.align_to_script(
        "That pigeon is a dinosaur. Not related to one. It is one.", asr)
    assert [w["w"] for w in words][:5] == ["That", "pigeon", "is", "a",
                                           "dinosaur."]
    assert direct == 11 and len(words) == 12
    a = words[3]  # unheard "a" sits between "is" and "dinosaur."
    assert words[2]["t0"] <= a["t0"] <= words[4]["t0"]
    ts = [w["t0"] for w in words]
    assert ts == sorted(ts)


def test_native_fish_timestamps_parse_and_align():
    segs = json.loads((FIX / "fish_segments_birds.json").read_text())
    events = [{"alignment": {"segments": [
        {"text": s["text"], "start": s["start"], "end": s["end"]}
        for s in segs]}, "chunk_seq": 0, "chunk_audio_offset_sec": 0}]
    audio, words = parse_segments(events)
    assert audio == b"" and len(words) >= 70
    script = ("That pigeon is a dinosaur. Not related to one. It is one. "
              "Sixty-six million years ago, a rock ten kilometres wide slammed "
              "into Mexico, and the age of giants ended.")
    tm = align.timing_from_asr(script, words)
    assert tm["words"][0]["w"] == "That" and tm["words"][0]["t0"] < 0.3
    assert tm["anchored"] >= 20


# ------------------------------------------------------------- synthesis --

def test_designed_gaps_and_speed_by_role():
    cfg = _cfg()
    sents = [V.Sentence("One two.", "hook"), V.Sentence("Three four.", "normal"),
             V.Sentence("Five six.", "normal"), V.Sentence("Seven.", "payoff")]
    prov = FakeProvider()
    with tempfile.TemporaryDirectory() as d:
        r = V.synthesize(sents, cfg, Path(d) / "v.wav", provider=prov,
                         asr_fn=_asr_perfect(lambda: " ".join(
                             s.text for s in sents)))
    g = cfg["gaps_ms"]
    gaps = [round(b[0] - a[1], 2) for a, b in zip(r.sentence_spans,
                                                  r.sentence_spans[1:])]
    # after hook 80 ms; normal 150 ms; before payoff 300 ms
    assert [round(x * 1000) for x in gaps] == [g["hook"], g["normal"],
                                               g["payoff"]], gaps
    sp = cfg["speed_by_role"]
    assert [round(s, 3) for _, s in prov.calls] == [
        sp["hook"], sp["normal"], sp["normal"], sp["payoff"]]
    assert r.qa["verdict"] == "PASS" and r.provider == "kokoro"


def test_speed_by_role_outside_band_is_rejected():
    with tempfile.TemporaryDirectory() as d:
        bad = Path(d) / "v.yaml"
        bad.write_text((V.CONFIG).read_text().replace("hook: 1.03",
                                                       "hook: 1.4"))
        try:
            V.load_config(bad)
        except ValueError as e:
            assert "0.95-1.08" in str(e)
        else:
            raise AssertionError("accepted speed outside band")


def test_asr_unavailable_is_hold_not_pass():
    cfg = _cfg()

    def boom(wav):
        raise ImportError("no whisper")
    with tempfile.TemporaryDirectory() as d:
        r = V.synthesize([V.Sentence("Hello there friend.")], cfg,
                         Path(d) / "v.wav", provider=FakeProvider(),
                         asr_fn=boom)
    assert r.qa["verdict"] == "HOLD" and r.qa["checked"] is False
    assert r.timing["method"] == "silence_v1" and r.words


def test_qa_failure_retries_only_bad_sentence_with_respelling():
    cfg = _cfg()
    lex = Lexicon({"tyrannosaurus": {"respell": "Tie-ran-uh-SAWR-us"}})
    sents = [V.Sentence("That pigeon is a dinosaur."),
             V.Sentence("Tyrannosaurus, gone.")]
    prov, state = FakeProvider(), {"n": 0}
    script = " ".join(s.text for s in sents)

    def asr(wav):
        state["n"] += 1
        text = script if state["n"] > 1 else script.replace(
            "Tyrannosaurus", "terenasaurus")
        return _asr(text)
    with tempfile.TemporaryDirectory() as d:
        r = V.synthesize(sents, cfg, Path(d) / "v.wav", provider=prov,
                         lexicon=lex, asr_fn=asr)
    assert r.qa["verdict"] == "PASS" and r.qa["retried_sentences"] == [1]
    assert len(prov.calls) == 3  # 2 first pass + 1 retry
    assert prov.calls[2][0] == "Tie-ran-uh-SAWR-us, gone."
    assert prov.calls[2][1] < prov.calls[1][1]  # retried slower

    # still wrong after the one retry -> HOLD, no second retry
    prov2 = FakeProvider()
    with tempfile.TemporaryDirectory() as d:
        r2 = V.synthesize(sents, cfg, Path(d) / "v.wav", provider=prov2,
                          lexicon=lex, asr_fn=lambda w: _asr(
                              script.replace("Tyrannosaurus", "terenasaurus")))
    assert r2.qa["verdict"] == "HOLD" and len(prov2.calls) == 3


# ------------------------------------------------------- whole-video switch --

def test_forced_failure_switches_whole_video_to_fallback():
    cfg = _cfg()
    cfg["channel_voice"] = "fish_narrator"       # pretend Fish was chosen
    fish = FakeProvider("fish", fail_after=3)     # dies after 3 sentences
    kok = FakeProvider("kokoro")

    def factory(vid, c):
        return fish if vid == "fish_narrator" else kok
    beats = _beats()
    with tempfile.TemporaryDirectory() as d:
        out = V.synthesize_video(
            d, beats, cfg, provider_factory=factory,
            asr_fn=_asr_perfect(lambda: " ".join(
                b["narration"] for b in beats)))
        # every beat was re-synthesised by the fallback: no mixed voices
        assert len(kok.calls) == 4 and len(fish.calls) == 3
        assert {i["provider"] for i in out["beats"].values()} == {"kokoro"}
        v = out["voice"]
        assert v["provider"] == "kokoro" and v["publishable"] is True
        assert v["switches"][0]["from"] == "fish_narrator"
        assert v["switches"][0]["to"] == "kokoro_michael"
        assert "forced failure" in v["switches"][0]["reason"]
        assert sorted(p.name for p in (Path(d) / "audio").glob("beat_*.wav")
                      ) == ["beat_B1.wav", "beat_B2.wav", "beat_B3.wav"]


def test_all_voices_failing_raises():
    cfg = _cfg()

    def factory(vid, c):
        raise V.VoiceUnavailable("down")
    with tempfile.TemporaryDirectory() as d:
        try:
            V.synthesize_video(d, _beats(), cfg, provider_factory=factory)
        except V.VoiceUnavailable as e:
            assert "every voice" in str(e)
        else:
            raise AssertionError("no error when every voice failed")


def test_cached_beat_reused_only_for_same_voice():
    cfg = _cfg()
    prov = FakeProvider()
    beats = _beats()[:1]
    asr = _asr_perfect(lambda: beats[0]["narration"])
    with tempfile.TemporaryDirectory() as d:
        V.synthesize_video(d, beats, cfg, provider_factory=lambda v, c: prov,
                           asr_fn=asr)
        n = len(prov.calls)
        V.synthesize_video(d, beats, cfg, provider_factory=lambda v, c: prov,
                           asr_fn=asr)
        assert len(prov.calls) == n                       # cache hit
        cfg2 = _cfg()
        cfg2["voices"]["kokoro_michael"]["voice"] = "am_fenrir"
        V.synthesize_video(d, beats, cfg2, provider_factory=lambda v, c: prov,
                           asr_fn=asr)
        assert len(prov.calls) == 2 * n                   # other voice: redo


# -------------------------------------------------------------- fish gate --

def _fish_cfg(**kw):
    return dict(_cfg()["voices"]["fish_narrator"], **kw)


def test_fish_disabled_by_default_and_paid_gated():
    keep = {k: os.environ.pop(k, None) for k in ("FISH_PLAN", "FISH_API_KEY")}
    from engine.voice import fish
    real_load, fish._load_env_keys = fish._load_env_keys, lambda: None
    try:
        def refused(cfg_v, why):
            try:
                FishProvider(cfg_v)
            except V.VoiceUnavailable as e:
                assert why in str(e), e
            else:
                raise AssertionError("Fish constructed: " + why)
        assert _cfg()["voices"]["fish_narrator"]["commercial_ok"] is False
        assert _cfg()["channel_voice"] != "fish_narrator"
        refused(_fish_cfg(), "FISH_PLAN")
        refused(_fish_cfg(model="s2.1-pro-free"), "free tier")
        os.environ["FISH_PLAN"] = "paid"
        refused(_fish_cfg(), "commercial_ok")            # rights not confirmed
        refused(_fish_cfg(commercial_ok=True), "FISH_API_KEY")
        os.environ["FISH_API_KEY"] = "x" * 8
        FishProvider(_fish_cfg(commercial_ok=True))       # all three gates met
    finally:
        fish._load_env_keys = real_load
        for k in ("FISH_PLAN", "FISH_API_KEY"):
            os.environ.pop(k, None)
            if keep[k] is not None:
                os.environ[k] = keep[k]


# ------------------------------------------------------------------ gate --

def test_gate_voice_check_is_fail_closed():
    from engine import v15_gate as g
    ok = {"provider": "kokoro", "voice_id": "am_michael", "publishable": True,
          "switches": [], "qa": {"verdict": "PASS", "wer": 0.01, "max_wer": .03,
                                 "held_beats": [], "unchecked_beats": []}}
    assert g.check_voice(ok)["ok"]
    assert not g.check_voice(None)["ok"]                       # never ran
    held = dict(ok, qa=dict(ok["qa"], held_beats=["B2"], wer=0.08))
    r = g.check_voice(held)
    assert not r["ok"] and "B2" in r["fails"][0]
    unchecked = dict(ok, qa=dict(ok["qa"], held_beats=["B1"],
                                 unchecked_beats=["B1"]))
    assert "did not run" in g.check_voice(unchecked)["fails"][0]
    assert not g.check_voice(dict(ok, publishable=False))["ok"]
    assert g.verdict_of({"voice": g.check_voice(held)}) == "HOLD"


# ------------------------------------------------------------------ live --

def _models_present():
    cfg = _cfg()["voices"]["kokoro_michael"]
    return (Path(cfg["model"]).expanduser().exists()
            and Path(cfg["voices_bin"]).expanduser().exists()
            and (Path.home() / ".cache/huggingface/hub/"
                 "models--Systran--faster-whisper-base.en").exists())


def test_live_lexicon_fixes_tyrannosaurus():
    if not _models_present():
        print("  (skipped: local models absent)")
        return
    cfg = _cfg()
    sents = [V.Sentence(s) for s in split_sentences(
        "Tyrannosaurus rex had tiny arms.")]
    with tempfile.TemporaryDirectory() as d:
        bare = V.synthesize(sents, cfg, Path(d) / "a.wav", lexicon=Lexicon(),
                            asr_fn=lambda w: align.transcribe(w, "base.en"))
        fixed = V.synthesize(sents, cfg, Path(d) / "b.wav")
    assert "tyrannosaurus" not in bare.qa["heard"], bare.qa["heard"]
    assert "tyrannosaurus" in fixed.qa["heard"], fixed.qa["heard"]
    assert fixed.qa["verdict"] == "PASS", fixed.qa


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
