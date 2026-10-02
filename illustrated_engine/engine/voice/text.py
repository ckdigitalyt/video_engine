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
    "travelling": "traveling", "travelled": "traveled",
}
_SENT_SPLIT = re.compile(r"(?<=[.!?])[\"'”’)]*\s+(?=[\"'“‘(]*[A-Z0-9])")
# trailing ordinal suffix (30th, 1st, 2nd, 3rd) is dropped, not spelled out as
# a separate "th" token: faster-whisper itself writes ordinals in speech back
# out as bare digits ("30th" heard -> transcribed "30,"), so the ordinal
# marker is never a token either side can actually match on.
_NUM = re.compile(r"\d[\d,]*(?:\.\d+)?(?:st|nd|rd|th)?\b", re.I)


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
    s = re.sub(r"(?i:st|nd|rd|th)$", "", m.group(0)).replace(",", "")
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


# ---------------------------------------------------- caption numerals --
# B1 (VIS): captions show DIGITS ("155-145 million years ago") while the
# narration/TTS text (this function's INPUT) keeps the spelled-out words a
# TTS model reads reliably — a second, caption-only representation of the
# same beat text, not a rewrite of what's spoken.
_TENS_WORDS = {t for t in _TENS if t != "_"}
_SCALE_WORDS = {"thousand": 10**3, "million": 10**6, "billion": 10**9}
_BARE = re.compile(r"[^\w]")


def _num_atoms(word: str) -> list | None:
    """A whole token (punctuation and all) that is ENTIRELY one or more
    number atoms (a hyphenated compound like "fifty-five" splits on '-'),
    else None."""
    raw = word.lower()
    out = []
    for part in (raw.split("-") if "-" in raw else [raw]):
        p = _BARE.sub("", part)
        if not p:
            continue
        if p in _ONES or p in _TENS_WORDS or p == "hundred" or p in _SCALE_WORDS:
            out.append(p)
        else:
            return None
    return out or None


def _phrase_value(atoms: list) -> tuple:
    """Flat [number-atom, ...] (connectors already dropped) -> (base, scale)."""
    base, scale = 0, None
    for a in atoms:
        if a in _ONES:
            base += _ONES.index(a)
        elif a in _TENS_WORDS:
            base += _TENS.index(a) * 10
        elif a == "hundred":
            base = (base or 1) * 100
        elif a in _SCALE_WORDS:
            scale = a
    return base, scale


def _token_kind(atoms: list) -> str:
    """One NUM token's atoms -> its place-value class, so a run only grows
    across a GRAMMATICAL English compound (e.g. "one hundred fifty-five"),
    never across two unrelated numbers read back to back ("one two three":
    ONES->ONES is not a valid compound and must stay three separate cues)."""
    if len(atoms) == 1:
        a = atoms[0]
        if a in _ONES:
            return "ONES"
        if a in _TENS_WORDS:
            return "TENS"
        if a == "hundred":
            return "HUNDRED"
        if a in _SCALE_WORDS:
            return "SCALE"
    if len(atoms) == 2 and atoms[0] in _TENS_WORDS and atoms[1] in _ONES:
        return "TENS_ONES"
    return "OTHER"


# valid KIND -> {KIND, ...} a number word of this class may be followed by
# and still be THE SAME compound number (English cardinal grammar only).
_NEXT_OK = {"ONES": {"HUNDRED", "SCALE"},
           "TENS": {"ONES", "SCALE"},
           "TENS_ONES": {"SCALE"},
           "HUNDRED": {"ONES", "TENS", "TENS_ONES", "SCALE"},
           "SCALE": set(), "OTHER": set()}


def _extend_phrase(words: list, i: int, n: int) -> tuple:
    """Greedily grow ONE compound number phrase starting at word i (no 'to')
    -> (word indices used, flat atom list, next unconsumed index)."""
    atoms0 = _num_atoms(words[i]["w"])
    run_idx, flat, kind = [i], list(atoms0), _token_kind(atoms0)
    j = i + 1
    while j < n and kind in _NEXT_OK:
        k, bridged_and = j, False
        if kind == "HUNDRED" and _BARE.sub("", words[j]["w"].lower()) == "and" \
                and j + 1 < n:
            k, bridged_and = j + 1, True
        nxt = _num_atoms(words[k]["w"]) if k < n else None
        if nxt is None:
            break
        nxt_kind = _token_kind(nxt)
        if nxt_kind not in _NEXT_OK[kind]:
            break
        if bridged_and:
            run_idx.append(j)
        run_idx.append(k)
        flat += nxt
        kind = nxt_kind
        j = k + 1
    return run_idx, flat, j


def numeralize_cue_words(words: list) -> list:
    """[{w,t0,t1}, ...] script words -> same shape, with each spoken number
    phrase or range ("one hundred fifty-five to one hundred forty-five
    million") merged into ONE digit unit ("155-145 million") spanning the
    run's [t0,t1]; words outside a number run (or a bare run of unrelated
    number words, e.g. "one two three") pass through unchanged."""
    out, i, n = [], 0, len(words)
    while i < n:
        if _num_atoms(words[i]["w"]) is None:
            out.append(words[i])
            i += 1
            continue
        idx1, flat1, j = _extend_phrase(words, i, n)
        phrase_idx = [idx1]
        bare = _BARE.sub("", words[j]["w"].lower()) if j < n else ""
        if bare == "to" and j + 1 < n and _num_atoms(words[j + 1]["w"]) is not None:
            idx2, flat2, j2 = _extend_phrase(words, j + 1, n)
            full_idx = idx1 + [j] + idx2
            phrase_idx.append(idx2)
            vals = [_phrase_value(flat1), _phrase_value(flat2)]
            j = j2
        else:
            full_idx = idx1
            vals = [_phrase_value(flat1)]
        if len(vals) == 1:
            base, scale = vals[0]
            text = str(base) + (f" {scale}" if scale else "")
        else:
            b1, s1 = vals[0]
            b2, s2 = vals[-1]
            if s1 and s2 and s1 != s2:
                text = f"{b1} {s1}-{b2} {s2}"
            else:
                text = f"{b1}-{b2}" + (f" {s1 or s2}" if s1 or s2 else "")
        lead = re.match(r"^[^\w]*", words[full_idx[0]]["w"]).group()
        trail = re.search(r"[^\w]*$", words[full_idx[-1]]["w"]).group()
        out.append({"w": lead + text + trail,
                    "t0": words[full_idx[0]]["t0"],
                    "t1": words[full_idx[-1]]["t1"]})
        i = full_idx[-1] + 1
    return out
