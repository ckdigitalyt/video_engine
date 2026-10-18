"""2026-10-18 generation fixes (verification batch live_20261018_073528)."""
import numpy as np

from engine import voice as V
from engine.voice import qa
from engine.voice.lexicon import Lexicon


def test_isolate_after_breaks_after_a_sentence_initial_misheard_word():
    assert V._isolate_after("Burn deuterium and tritium.", [0]) == \
        "Burn, deuterium and tritium."
    # already followed by a break / last word: untouched
    assert V._isolate_after("Ash, fine as powder.", [0, 3]) == \
        "Ash, fine as powder."
    # _isolate can't help index 0 -- that is why the variant exists
    assert V._isolate("Burn deuterium and tritium.", [0]) == \
        "Burn deuterium and tritium."


def test_isolate_after_variant_rescues_when_the_others_do_not(tmp_path):
    calls = []

    class Prov:
        def synth(self, text, speed):
            calls.append(text)
            return V.Clip(np.full(2400, 0.2, dtype=np.float32), 24000, None)
    script = "Burn deuterium and tritium."
    bad = "burned deuterium and tritium"
    heard = iter([bad, bad, bad, bad, "burn deuterium and tritium"])

    def asr(wav):
        return [{"w": w, "t0": 0.2 * i, "t1": 0.2 * i + 0.1}
                for i, w in enumerate(next(heard).split())]
    r = V.synthesize([V.Sentence(script)], V.load_config(), tmp_path / "v.wav",
                     provider=Prov(), lexicon=Lexicon(), asr_fn=asr)
    assert r.qa["verdict"] == "PASS"
    assert r.qa["retry_variant"] == "isolate_after"
    assert calls[-1] == "Burn, deuterium and tritium."


def test_lexicon_daedalus():
    lex = V.load_lexicon(V.load_config())
    assert lex.entries["daedalus"]["phonemes"] == "dˈɛdələs"
    asr = [{"w": w, "t0": 0.3 * i, "t1": 0.3 * i + 0.25}
           for i, w in enumerate("and dedalus still aimed".split())]
    assert qa.round_trip("and Daedalus still aimed", asr, lex,
                         0.03)["verdict"] == "PASS"
