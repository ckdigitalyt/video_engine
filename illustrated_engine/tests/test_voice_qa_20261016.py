"""2026-10-16 zero-publish day, voice round-trip QA.

live_20261015_104500 t_the_atlantic_ocean_is_actually_a_scar rendered fully
and HELD on one beat: B5 WER 0.0667 (> 0.03), hard token "Pangea," missed.
The narration was right; faster-whisper spells the word "Pangaea".
Replaying every held beat's stored transcript (26 beats) found five more
spelling-only classes no re-synthesis can fix: contraction expansion,
digit+letter designations, letter-spelled acronyms, two true homophones.
max_wer (0.03) and the hard-token rule are unchanged -- a genuinely
misheard word still fails (bottom tests). A second, slower re-synthesis
was measured live on 6 genuinely-misread sentences (1.13/1.07/1.02/0.96x)
and fixed 1 of 6, not reproducibly, so the one-retry policy stays.

Run: python3 -m pytest -q tests/test_voice_qa_20261016.py   (no network)
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
sys.path.insert(0, str(ROOT))

from engine.voice import qa  # noqa: E402
from engine.voice.lexicon import Lexicon  # noqa: E402
from engine.voice.text import join_letter_runs, norm_tokens  # noqa: E402


def _rt(script, heard):
    asr = [{"w": w, "t0": 0.3 * i, "t1": 0.3 * i + 0.25}
           for i, w in enumerate(heard.split())]
    return qa.round_trip(script, asr, Lexicon(), 0.03)


def test_atlantic_b5_pangaea_spelling_passes():
    r = _rt("Because those shores were one seam inside Pangea, a landmass "
            "stretching nearly pole to pole.",
            "because those shores were one seam inside pangaea a landmass "
            "stretching nearly pole to pole")
    assert r["wer"] == 0 and r["verdict"] == "PASS" and r["hard_missed"] == []


def test_ae_digraph_spellings_are_one_word():
    assert norm_tokens("archaeology") == norm_tokens("archeology")
    assert norm_tokens("palaeontologists") == norm_tokens("paleontologists")
    assert norm_tokens("aero") == ["aero"]          # short words untouched


def test_contractions_expand_on_both_sides():
    assert _rt("So the next time they're drawn together, remember.",
               "so the next time they are drawn together remember")["verdict"] == "PASS"
    assert norm_tokens("I'm") == ["i", "am"] and norm_tokens("we'll") == ["we", "will"]
    assert norm_tokens("it's") == ["its"]           # 's stays ambiguous, as before


def test_digit_letter_designation_matches_spelled_form():
    assert _rt("It's been modeled for Kepler ten b and fifty-five Cancri e.",
               "its been modeled for kepler 10b and fifty five cancri e")["verdict"] == "PASS"
    assert norm_tokens("25th") == ["twenty", "fifth"]   # ordinals unaffected


def test_letter_spelled_acronym_matches_heard_acronym():
    r = _rt("ISRO put a satellite called R-S-One into orbit on its own rocket, "
            "the S-L-V three.",
            "isro put a satellite called r s one into orbit on its own rocket "
            "the slv three")
    assert r["verdict"] == "PASS", r
    toks, own = join_letter_runs(["the", "s", "l", "v", "a", "b"], [0, 1, 1, 1, 2, 3])
    assert toks == ["the", "slv", "a", "b"] and own == [0, 1, 2, 3]


def test_true_homophones():
    assert _rt("And Webb might be able to prove it.",
               "and web might be able to prove it")["verdict"] == "PASS"
    assert _rt("It hides in the Milky Way's spiral arms.",
               "it hides in the milky weighs spiral arms")["verdict"] == "PASS"


def test_held_beat_is_reattempted_not_served_from_cache(tmp_path):
    import json
    import numpy as np
    from engine import voice as V

    class Prov:
        calls = 0

        def synth(self, text, speed):
            Prov.calls += 1
            return V.Clip(np.full(2400, 0.2, dtype=np.float32), 24000, None)

    cfg = V.load_config()
    beats = [{"beat_id": "B1", "function": "HOOK", "narration": "Pangea split apart."}]
    heard = {"t": "pangolin split apart"}

    def asr(wav):
        return [{"w": w, "t0": 0.1 * i, "t1": 0.1 * i + 0.05}
                for i, w in enumerate(heard["t"].split())]
    kw = dict(provider_factory=lambda v, c: Prov(), asr_fn=asr)
    out = V.synthesize_video(tmp_path, beats, cfg, **kw)
    assert out["voice"]["qa"]["verdict"] == "HOLD"
    n = Prov.calls
    heard["t"] = "pangaea split apart"           # e.g. after a comparator fix
    out = V.synthesize_video(tmp_path, beats, cfg, **kw)
    assert Prov.calls > n and out["voice"]["qa"]["verdict"] == "PASS"
    n = Prov.calls
    V.synthesize_video(tmp_path, beats, cfg, **kw)
    assert Prov.calls == n                       # a PASSED beat is still cached
    assert json.loads((tmp_path / "audio" / "beat_B1.voice.json").read_text())["qa"]["verdict"] == "PASS"


# ---------------------------------------------------- the bar still holds --

def test_genuine_mispronunciations_still_fail():
    # real Kokoro misreads from held beats, re-measured live 2026-10-16
    for script, heard in [
        ("Then winds may drag that rock vapor toward the endless night side.",
         "then wines may drag that rock vapor toward the endless night side"),
        ("Then the cruelest blow: every atom it catches must be sped up.",
         "then the crew list blow every adamant catches must be sped up"),
        ("A Type Two civilization wouldn't sip a star's light.",
         "a type ii civilization wouldnt sip a stars life"),
    ]:
        r = _rt(script, heard)
        assert r["verdict"] == "FAIL", (script, r)


def test_wrong_letter_in_spelled_acronym_still_fails():
    r = _rt("The rocket was called the S-L-V three.", "the rocket was called the slb three")
    assert r["verdict"] == "FAIL"


def test_misheard_proper_noun_still_a_hard_miss():
    r = _rt("Because those shores were one seam inside Pangea, a landmass.",
            "because those shores were one seam inside pangolin a landmass")
    assert r["verdict"] == "FAIL" and r["hard_missed"] == ["Pangea,"]
