"""Round-trip QA: transcribe the final voice, compare with the script.

verdict: PASS when normalised WER <= max_wer and every hard token (names,
numbers, lexicon entries) came back; otherwise FAIL (the caller may retry the
failing sentences once, then the video goes to HOLD)."""
from __future__ import annotations

from engine.voice.lexicon import Lexicon, hard_words
from engine.voice.text import edit_align, flat_tokens


def round_trip(script: str, asr_words: list, lex: Lexicon,
               max_wer: float = 0.03) -> dict:
    words = script.split()
    ref, owner = flat_tokens(words)
    hyp = lex.canonical(flat_tokens([w["w"] for w in asr_words])[0])
    ops = edit_align(ref, hyp)
    errors = sum(1 for _, _, op in ops if op != "C")
    wer = errors / max(len(ref), 1)
    bad_words = sorted({owner[r] for r, _, op in ops
                        if r is not None and op != "C"})
    hard = set(hard_words(script, lex))
    hard_miss = [i for i in bad_words if i in hard]
    return {"wer": round(wer, 4), "errors": errors, "ref_tokens": len(ref),
            "max_wer": max_wer, "bad_word_idx": bad_words,
            "hard_missed": [words[i] for i in hard_miss],
            "hard_missed_idx": hard_miss,
            "heard": " ".join(hyp),
            "verdict": "PASS" if wer <= max_wer and not hard_miss else "FAIL"}
