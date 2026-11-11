"""Phoneme-level word equivalence for round-trip voice QA (2026-11-11 review).

Voice QA compared the script and the ASR transcript by SPELLING, so a
correctly read word written differently by faster-whisper counted as an
error: weight/"wait", sac/"sack", nanometres/"nanometers",
doughnut/"donut". The per-beat limit is 0.03; on a 9-13 word beat one such
word scores 0.08-0.11, so in practice zero spelling differences were
tolerated. At least 3 of 25 recent renders (spider silk B3, pericardium
B2, opabinia/infrasound) held on this alone. ~10 commits had patched it one
word pair at a time in text._SPELLING.

Here two words are "the same speech" when espeak-ng (the phonemizer Kokoro
itself speaks from, en-us) gives them the same phonemes, after dropping
stress and length marks: no recording can tell such words apart, so the
ASR's choice of spelling says nothing about the narration. The
comparison is exact on the normalized phoneme string -- deliberately NOT
an edit-distance threshold: one phoneme is the whole difference between
cat/bat, bear/pear, billion/million, and those are real misreads.

Names, numbers and lexicon words (lexicon.hard_words) are never relaxed
by the caller (qa.round_trip). If espeak cannot be loaded, every check
returns False: QA falls back to the strict spelling comparison, never to
a pass.
"""
from __future__ import annotations

import functools
import re

_MARKS = re.compile(r"[ˈˌːˑ\s]")
_REDUCED = str.maketrans({"ɐ": "ə"})          # espeak's two reduced-vowel symbols
_tokenizer = None
_unavailable = False


def _phonemize_raw(word: str) -> str | None:
    global _tokenizer, _unavailable
    if _unavailable:
        return None
    try:
        if _tokenizer is None:
            from kokoro_onnx.tokenizer import Tokenizer
            _tokenizer = Tokenizer()
        return _tokenizer.phonemize(word, "en-us")
    except Exception:
        _unavailable = True
        return None


@functools.lru_cache(maxsize=4096)
def phonemes(word: str) -> str | None:
    """Normalized en-us phoneme string of one word, or None if espeak is
    unavailable or the word is empty / not alphabetic."""
    w = str(word or "").strip().lower()
    if not w or not re.fullmatch(r"[a-z']+", w):
        return None
    raw = _phonemize_raw(w)
    if not raw:
        return None
    return _MARKS.sub("", raw).translate(_REDUCED) or None


def same_sound(a: str, b: str) -> bool:
    """True when `a` and `b` are spoken identically (homophones / spelling
    variants): weight~wait, sac~sack, doughnut~donut, hours~ours."""
    if a == b:
        return True
    pa, pb = phonemes(a), phonemes(b)
    return pa is not None and pa == pb
