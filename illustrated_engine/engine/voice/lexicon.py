"""Pronunciation lexicon (brand/<id>/lexicon.yaml).

    word: {respell: "Tie-ran-uh-SAWR-us", phonemes: "taɪɹˌænəsˈɔːɹəs",
           heard_as: ["tie ran a sorus"]}

`phonemes` (IPA in Kokoro's alphabet) is used on the first attempt; if the
round-trip QA still hears the word wrong, the sentence is re-synthesised
once with `respell` substituted into the text (works for any provider).
`heard_as` lists spellings the ASR writes for a *correct* pronunciation of a
rare word ("Beetlejuice" for Betelgeuse); QA maps them back to the word.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

from engine.voice.text import NUMBER_WORDS, norm_tokens


class Lexicon:
    def __init__(self, entries: dict | None = None):
        self.entries = {str(k).lower(): dict(v or {})
                        for k, v in (entries or {}).items()}
        self._alias = sorted(
            ((norm_tokens(a), norm_tokens(k)) for k, v in self.entries.items()
             for a in v.get("heard_as") or []), key=lambda p: -len(p[0]))
        self._rx = (re.compile(r"\b(" + "|".join(
            re.escape(k) for k in sorted(self.entries, key=len, reverse=True))
            + r")\b", re.I) if self.entries else None)

    @classmethod
    def load(cls, path) -> "Lexicon":
        p = Path(path) if path else None
        if not p or not p.exists():
            return cls()
        return cls(yaml.safe_load(p.read_text()) or {})

    def respell(self, text: str) -> str:
        if not self._rx:
            return text

        def sub(m):
            return self.entries[m.group(1).lower()].get("respell") or m.group(1)
        return self._rx.sub(sub, text)

    def to_phonemes(self, text: str, phonemize, lang: str = "en-us") -> str:
        """Phonemize `text`, splicing the lexicon phonemes in for entries that
        have them (other words go through the normal phonemizer)."""
        if not self._rx:
            return phonemize(text, lang)
        out, pos = [], 0

        def flush(seg):
            if seg.strip():
                out.append(phonemize(seg, lang).strip())
        for m in self._rx.finditer(text):
            ph = self.entries[m.group(1).lower()].get("phonemes")
            if not ph:
                continue
            flush(text[pos:m.start()])
            out.append(ph)
            pos = m.end()
        flush(text[pos:])
        joined = ""
        for piece in out:  # no space before punctuation
            joined += piece if not joined or re.match(r"[,.;:!?…]", piece) \
                else " " + piece
        return joined

    def canonical(self, tokens: list) -> list:
        """Replace ASR spellings listed in heard_as by the lexicon word."""
        out, i = [], 0
        while i < len(tokens):
            for alias, word in self._alias:
                if alias and tokens[i:i + len(alias)] == alias:
                    out += word
                    i += len(alias)
                    break
            else:
                out.append(tokens[i])
                i += 1
        return out

    def words(self) -> set:
        return set(self.entries)


def hard_words(text: str, lex: Lexicon) -> list:
    """Indices (into text.split()) of words whose sub-tokens must survive the
    round trip: lexicon entries, numbers, and proper names (capitalised
    mid-sentence words / acronyms)."""
    words = text.split()
    hard, sent_start = [], True
    for i, w in enumerate(words):
        bare = re.sub(r"[^A-Za-z0-9']", "", w)
        toks = norm_tokens(w)
        is_num = any(c.isdigit() for c in w) or any(
            t in NUMBER_WORDS and t != "one" for t in toks)
        cap = bare[:1].isupper() and bare != "I" and not bare.startswith("I'")
        # a long capitalised sentence opener is a name too (Tyrannosaurus, gone.)
        is_name = cap and (not sent_start or len(bare) >= 9)
        if toks and (bare.lower() in lex.words() or is_num or is_name
                     or (len(bare) > 1 and bare.isupper())):
            hard.append(i)
        sent_start = bool(re.search(r"[.!?][\"'”’)]*$", w))
    return hard
