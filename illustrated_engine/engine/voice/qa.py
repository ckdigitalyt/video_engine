"""Round-trip QA: transcribe the final voice, compare with the script.

verdict: PASS when normalised WER <= max_wer and every hard token (names,
numbers, lexicon entries) came back; otherwise FAIL (the caller may retry the
failing sentences once, then the video goes to HOLD)."""
from __future__ import annotations

from engine.voice.lexicon import Lexicon, hard_words
from engine.voice.phonetic import same_sound
from engine.voice.text import (UNIT_WORDS, edit_align, flat_tokens, join_letter_runs,
                               join_split_numbers, rejoin_compounds,
                               restore_d_elision, restore_number_words)


def _accept_sound_alikes(ops: list, ref: list, hyp: list, owner: list,
                         hard: set) -> tuple:
    """2026-11-11: a one-for-one substitution of a word that is NOT a
    name, number or lexicon entry counts as correct when the two spellings
    are spoken identically (engine.voice.phonetic.same_sound: weight/wait,
    sac/sack, doughnut/donut, nanometres/nanometers), or when the heard
    word is an expanded unit abbreviation ("hz" -> hertz) and the script
    has that unit, singular or plural. Hard words stay strictly checked.
    -> (ops with those S turned into C, ["script~heard", ...])."""
    out, accepted = [], []
    for r, h, op in ops:
        if (op == "S" and owner[r] not in hard
                and (same_sound(ref[r], hyp[h])
                     or (hyp[h] in UNIT_WORDS and ref[r] in (hyp[h], hyp[h] + "s"))
                     or (ref[r] in UNIT_WORDS and hyp[h] in (ref[r], ref[r] + "s")))):
            accepted.append(f"{ref[r]}~{hyp[h]}")
            op = "C"
        out.append((r, h, op))
    return out, accepted


def round_trip(script: str, asr_words: list, lex: Lexicon,
               max_wer: float = 0.03) -> dict:
    words = script.split()
    ref, owner = join_letter_runs(*flat_tokens(words))
    ref = lex.canonical_ref(ref)
    hyp = restore_d_elision(ref, rejoin_compounds(ref, join_letter_runs(
        lex.canonical(flat_tokens(join_split_numbers(
            [w["w"] for w in asr_words]))[0]))[0]))
    hyp = restore_number_words(ref, hyp)
    ops = edit_align(ref, hyp)
    hard = set(hard_words(script, lex))
    ops, sound_alike = _accept_sound_alikes(ops, ref, hyp, owner, hard)
    errors = sum(1 for _, _, op in ops if op != "C")
    wer = errors / max(len(ref), 1)
    bad_words = sorted({owner[r] for r, _, op in ops
                        if r is not None and op != "C"})
    hard_miss = [i for i in bad_words if i in hard]
    return {"wer": round(wer, 4), "errors": errors, "ref_tokens": len(ref),
            "max_wer": max_wer, "bad_word_idx": bad_words,
            "hard_missed": [words[i] for i in hard_miss],
            "hard_missed_idx": hard_miss,
            "heard": " ".join(hyp),
            "sound_alike": sound_alike,
            "verdict": "PASS" if wer <= max_wer and not hard_miss else "FAIL"}
