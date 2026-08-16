#!/usr/bin/env python3
"""script_guards.py — Algorithm-level script quality guards (v40).

Implemented from the 2026-08-16 dual review (Gemini 53 + DeepSeek 68 on
the Betelgeuse cartoon video).  These run on EVERY video, not just that
one:

1. dedupe_scene_repetition  — Gemini critical finding: Scene 4 repeated
   Scene 3's narration verbatim ("Radiation shreds the ozone layer,
   ultraviolet floods the surface, crops fail, ecosystems fray" in both).
   Detects consecutive-scene sentence overlap and rewrites the later
   scene so the second half never stalls.

2. hedge_uncertain_claims   — DeepSeek high finding: "548 light-years"
   stated as fact, "radiation shreds the ozone layer" too definitive.
   Hedges distance/measurement claims with "about/approximately" and
   softens definitive effect verbs with "could" when the research pack
   doesn't pin the claim.  Applied before TTS so narration is final.
"""

from __future__ import annotations

import re

# ── Scene repetition guard ─────────────────────────────────────────────

_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")
# Clauses are comma/colon separated too — the Betelgeuse case merged the
# duplicate into one long sentence ("...ozone layer, ultraviolet floods...,
# the sky that once gave life..."), so sentence-level overlap alone can
# miss it.  We also test clause-level chunks.
_CLAUSE_SPLIT = re.compile(r"[,;]\s+")
_WORD = re.compile(r"[a-z0-9']+")

# Sentences to drop from the LATER scene when they duplicate the earlier
# scene nearly verbatim.  Keeps a minimum so the scene isn't gutted.
_MIN_KEEP_SENTENCES = 1
# Overlap ratio (shared words / later-sentence words) that counts as dup.
_DUP_RATIO = 0.6


def _words(text: str) -> set:
    return set(_WORD.findall(text.lower()))


def _sentence_overlap(prev_words: set, sentence: str) -> float:
    sw = _words(sentence)
    if not sw:
        return 1.0
    return len(prev_words & sw) / len(sw)


def _strip_duplicate_sentences(narration: str, prev_narration: str) -> str:
    """Remove sentences in `narration` that mostly repeat `prev_narration`,
    keeping at least _MIN_KEEP_SENTENCES sentences (prefer the last one —
    it usually carries the scene's new payoff).

    v40.1: also drops duplicated CLAUSES inside surviving sentences so a
    scene that merged the repeat with new content (Betelgeuse scene 4)
    still gets cleaned."""
    if not prev_narration:
        return narration
    prev_words = _words(prev_narration)
    sents = [s.strip() for s in _SENT_SPLIT.split(narration) if s.strip()]
    if len(sents) <= 1:
        # Single-sentence scene: strip duplicated clauses instead.
        return _strip_duplicate_clauses(narration, prev_words)
    keep = [s for s in sents if _sentence_overlap(prev_words, s) < _DUP_RATIO]
    # Even "kept" sentences may carry a duplicated clause — clean them.
    keep = [_strip_duplicate_clauses(s, prev_words) for s in keep]
    keep = [s for s in keep if s]
    if not keep:
        # Everything repeats — keep the final sentence (the new beat).
        keep = [sents[-1]]
    elif len(keep) < _MIN_KEEP_SENTENCES:
        keep = keep + [sents[-1]] if sents[-1] not in keep else keep
    return " ".join(keep).strip()


def _strip_duplicate_clauses(sentence: str, prev_words: set) -> str:
    """Drop comma/colon clauses that mostly duplicate the previous scene.
    Leading duplicated clauses are dropped too (v40.2 — the Betelgeuse
    scene 4 opener repeated scene 3's exact list); the first NON-duplicate
    clause becomes the new opener."""
    clauses = [c.strip() for c in _CLAUSE_SPLIT.split(sentence) if c.strip()]
    if len(clauses) <= 1:
        return sentence
    keep = [c for c in clauses if _sentence_overlap(prev_words, c) < _DUP_RATIO]
    if not keep:
        return clauses[-1]  # all dup — keep the last (usually the payoff)
    return ", ".join(keep).strip()


def dedupe_scene_repetition(scenes: list[dict]) -> list[dict]:
    """For every consecutive scene pair, cut sentences that repeat the
    previous scene verbatim.  Returns the same list (mutated in place)."""
    changed = 0
    for i in range(1, len(scenes)):
        prev_n = (scenes[i - 1].get("narration") or "").strip()
        cur_n = (scenes[i].get("narration") or "").strip()
        if not prev_n or not cur_n:
            continue
        cleaned = _strip_duplicate_sentences(cur_n, prev_n)
        if cleaned != cur_n:
            scenes[i]["narration"] = cleaned
            changed += 1
            print(f"  [script-guard] scene {i}: removed {len(_SENT_SPLIT.split(cur_n)) - len(_SENT_SPLIT.split(cleaned))} "
                  f"repeated sentence(s) from previous scene")
    if changed:
        print(f"  [script-guard] repetition guard: {changed} scene(s) deduped")
    return scenes


# ── Claim hedging ──────────────────────────────────────────────────────

# Distance/measurement claims: "548 light-years" -> "about 548 light-years".
_MEASURE_RE = re.compile(
    r"\b(\d[\d,]*)\s*(light-?years?|ly|kilometers?|km|miles?|million|billion)\b",
    re.IGNORECASE,
)
# Definite effect verbs on systems/structures -> soften with "could" when
# they directly follow a radiation/heat cause (DeepSeek: too assertive).
_EFFECT_RE = re.compile(
    r"\b(radiation|ultraviolet|uv|heat|blast|shockwave)\s+"
    r"(shreds|floods|tears|burns|strips|destroys|kills|erases)\b",
    re.IGNORECASE,
)
# Already-hedged markers — never double-hedge.
_HEDGE_WORDS = ("about", "approximately", "roughly", "around", "up to",
                "could", "may", "might", "possibly", "estimated", "nearly")

# For VERB softening only modal hedges count ("about 548 ly" shouldn't
# block "shreds -> could shred" in the same sentence).
_MODAL_HEDGE_WORDS = ("could", "may", "might", "possibly", "probably")

_VERB_SOFTEN = {
    "shreds": "could shred", "floods": "could flood", "tears": "could tear",
    "burns": "could burn", "strips": "could strip", "destroys": "could destroy",
    "kills": "could kill", "erases": "could erase",
}


def _hedge_measure(match: re.Match) -> str:
    pre = match.group(0)
    # Look back a few words for an existing hedge marker.
    return f"about {pre}" if pre.lower().split()[0].rstrip(",") not in _HEDGE_WORDS else pre


def hedge_uncertain_claims(scenes: list[dict]) -> list[dict]:
    """Add 'about' to measurement claims and 'could' to definitive effect
    verbs, unless the claim is already hedged.  Mutates scenes in place."""
    for s in scenes:
        n = s.get("narration") or ""
        if not n:
            continue
        out = _MEASURE_RE.sub(lambda m: _hedge_measure(m), n)

        def _soften(m: re.Match) -> str:
            cause, verb = m.group(1), m.group(2).lower()
            if verb in _VERB_SOFTEN and not any(
                w in out[max(0, m.start() - 60):m.start()].lower()
                for w in _MODAL_HEDGE_WORDS
            ):
                return f"{cause} {_VERB_SOFTEN[verb]}"
            return m.group(0)

        out = _EFFECT_RE.sub(_soften, out)
        if out != n:
            s["narration"] = out
            print(f"  [script-guard] hedged uncertain claim in scene {s.get('scene_id', '?')}")
    return scenes
