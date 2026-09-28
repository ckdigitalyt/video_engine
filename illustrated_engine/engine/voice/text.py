"""Text helpers shared by the voice layer: sentence split, token normalisation,
and the word-level edit alignment used for both QA (WER) and caption timing."""
from __future__ import annotations

import re

_ONES = ("zero one two three four five six seven eight nine ten eleven twelve "
         "thirteen fourteen fifteen sixteen seventeen eighteen nineteen").split()
_TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()
_SCALES = ((10**9, "billion"), (10**6, "million"), (10**3, "thousand"))
NUMBER_WORDS = set(_ONES) | {t for t in _TENS if t != "_"} | {
    "hundred", "thousand", "million", "billion"}

# spelling-only differences must not count as errors (Kokoro reads en-us; the
# script and Whisper may spell either way)
_SPELLING = {
    "metre": "meter", "litre": "liter", "centre": "center", "fibre": "fiber",
    "kilometre": "kilometer", "millimetre": "millimeter",
    "centimetre": "centimeter", "colour": "color", "honour": "honor",
    "favour": "favor", "neighbour": "neighbor", "behaviour": "behavior",
    "vapour": "vapor", "grey": "gray", "analyse": "analyze",
    "realise": "realize", "recognise": "recognize", "organise": "organize",
    "programme": "program", "tyre": "tire", "whilst": "while",
    "ageing": "aging", "sulphur": "sulfur", "aluminium": "aluminum",
}
_SENT_SPLIT = re.compile(r"(?<=[.!?])[\"'”’)]*\s+(?=[\"'“‘(]*[A-Z0-9])")
_NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")


def int_to_words(n: int) -> str:
    if n < 20:
        return _ONES[n]
    if n < 100:
        return _TENS[n // 10] + (" " + _ONES[n % 10] if n % 10 else "")
    if n < 1000:
        return (_ONES[n // 100] + " hundred"
                + (" " + int_to_words(n % 100) if n % 100 else ""))
    for size, name in _SCALES:
        if n >= size:
            rest = n % size
            return (int_to_words(n // size) + " " + name
                    + (" " + int_to_words(rest) if rest else ""))
    raise ValueError(n)


def _num_words(m: re.Match) -> str:
    s = m.group(0).replace(",", "")
    whole, _, frac = s.partition(".")
    out = int_to_words(int(whole))
    if frac:
        out += " point " + " ".join(_ONES[int(c)] for c in frac)
    return " " + out + " "


def split_sentences(text: str) -> list:
    """Split at .!? followed by a capital/digit ('stares at you... remember'
    stays one sentence)."""
    parts = [p.strip() for p in _SENT_SPLIT.split(text.strip())]
    return [p for p in parts if p]


def norm_tokens(word: str) -> list:
    """One spoken token as a list of normalised sub-tokens ('66' -> sixty six,
    'Sixty-six' -> sixty six)."""
    w = word.lower().replace("’", "'").replace("%", " percent ")
    w = _NUM.sub(_num_words, w)
    w = re.sub(r"[-‐–—/]", " ", w)
    out = []
    for t in w.split():
        t = re.sub(r"[^a-z0-9]", "", t)
        if not t:
            continue
        if t in _SPELLING:
            t = _SPELLING[t]
        elif t.endswith("s") and t[:-1] in _SPELLING:
            t = _SPELLING[t[:-1]] + "s"
        out.append(t)
    return out


def flat_tokens(words: list) -> tuple:
    """(tokens, owner) — owner[i] is the index in `words` token i came from."""
    toks, owner = [], []
    for i, w in enumerate(words):
        for t in norm_tokens(w):
            toks.append(t)
            owner.append(i)
    return toks, owner


def edit_align(ref: list, hyp: list) -> list:
    """Levenshtein alignment -> [(ref_i|None, hyp_j|None, op)], op in
    C(orrect) S(ubstitute) D(elete from hyp) I(nsert in hyp)."""
    n, m = len(ref), len(hyp)
    d = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        d[i][0] = i
    for j in range(m + 1):
        d[0][j] = j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            d[i][j] = min(d[i - 1][j - 1] + (ref[i - 1] != hyp[j - 1]),
                          d[i - 1][j] + 1, d[i][j - 1] + 1)
    ops, i, j = [], n, m
    while i or j:
        if i and j and d[i][j] == d[i - 1][j - 1] + (ref[i - 1] != hyp[j - 1]):
            ops.append((i - 1, j - 1, "C" if ref[i - 1] == hyp[j - 1] else "S"))
            i, j = i - 1, j - 1
        elif i and d[i][j] == d[i - 1][j] + 1:
            ops.append((i - 1, None, "D"))
            i -= 1
        else:
            ops.append((None, j - 1, "I"))
            j -= 1
    return ops[::-1]
