"""Word timing for captions and on-word cuts.

Primary: faster-whisper base.en word timestamps on the final voice track,
sequence-aligned to the *script* words (the script owns the spelling).
Last resort (offline / model missing): engine.v15_timing silence_v1, kept as a
load-bearing fallback.
"""
from __future__ import annotations

import os
import re

from engine.voice.text import edit_align, flat_tokens

METHOD = "whisper_base_en_v1"
MIN_PAUSE_S = 0.11
_MODELS: dict = {}


def _model(name: str = "base.en"):
    if name not in _MODELS:
        from faster_whisper import WhisperModel
        _MODELS[name] = WhisperModel(
            name, device="cpu", compute_type="int8",
            cpu_threads=int(os.environ.get("WHISPER_THREADS", "4")))
    return _MODELS[name]


_NUM_HEAD = re.compile(r"^\d{1,3}$")
_NUM_GROUP = re.compile(r"^,\d{3}$")
_NUM_FRAC = re.compile(r"^\.\d+$")


def _merge_number_fragments(words: list) -> list:
    """faster-whisper sometimes writes a thousands-grouped number as separate
    word tokens ("2" then ",000") instead of one "2,000" token; normalising
    each fragment on its own turns the second one into a bogus standalone
    "zero"/"thousand" instead of completing the first number. Glue the run
    back into one token (and span its timestamps) before anything else sees
    it, both sides of the round trip are a single formatted numeral."""
    out, i = [], 0
    while i < len(words):
        w = words[i]
        if _NUM_HEAD.match(w["w"]):
            j = i + 1
            while j < len(words) and _NUM_GROUP.match(words[j]["w"]):
                j += 1
            if j < len(words) and _NUM_FRAC.match(words[j]["w"]):
                j += 1
            if j > i + 1:
                out.append({"w": "".join(x["w"] for x in words[i:j]),
                            "t0": w["t0"], "t1": words[j - 1]["t1"]})
                i = j
                continue
        out.append(w)
        i += 1
    return out


def transcribe(wav, model: str = "base.en") -> list:
    """[{w, t0, t1}] as heard (no script knowledge)."""
    segs, _ = _model(model).transcribe(
        str(wav), language="en", word_timestamps=True, beam_size=5,
        condition_on_previous_text=False)
    words = [{"w": w.word.strip(), "t0": float(w.start), "t1": float(w.end)}
             for s in segs for w in (s.words or []) if w.word.strip()]
    return _merge_number_fragments(words)


def align_to_script(script: str, asr: list) -> tuple:
    """-> (words [{w,t0,t1}] one per script token, n_direct). Script words the
    ASR did not hear are interpolated between their timed neighbours."""
    words = script.split()
    ref, r_owner = flat_tokens(words)
    hyp, h_owner = flat_tokens([a["w"] for a in asr])
    span: dict = {}  # script word idx -> [t0, t1] from aligned hyp tokens
    for r, h, op in edit_align(ref, hyp):
        if r is None or h is None:
            continue
        a = asr[h_owner[h]]
        s = span.setdefault(r_owner[r], [a["t0"], a["t1"]])
        s[0], s[1] = min(s[0], a["t0"]), max(s[1], a["t1"])
    if not span:
        raise ValueError("no script word was heard")
    out = [list(span[i]) if i in span else None for i in range(len(words))]
    known = sorted(span)
    for i in range(len(out)):  # interpolate runs of unheard words
        if out[i]:
            continue
        lo = max((k for k in known if k < i), default=None)
        hi = min((k for k in known if k > i), default=None)
        a = out[lo][1] if lo is not None else out[hi][0]
        b = out[hi][0] if hi is not None else out[lo][1]
        run = [k for k in range(len(out)) if (lo is None or k > lo)
               and (hi is None or k < hi)]
        w = [max(len(words[k]), 1) for k in run]
        pos = run.index(i)
        out[i] = [a + (b - a) * sum(w[:pos]) / sum(w),
                  a + (b - a) * sum(w[:pos + 1]) / sum(w)]
    t = 0.0  # monotonic
    res = []
    for w, (t0, t1) in zip(words, out):
        t0 = max(t0, t)
        t1 = max(t1, t0)
        res.append({"w": w, "t0": round(t0, 3), "t1": round(t1, 3)})
        t = t0
    return res, len(span)


ONSET_MIX = 0.15  # voiced threshold = floor + MIX * (loud - floor)


def refine_onsets(wav, words: list) -> list:
    """Whisper starts a word early when a pause precedes it (it can include
    the silence). Move a start LATER to the first voiced 10 ms frame inside
    the word's own window; never earlier."""
    import numpy as np
    from engine.v15_timing import HOP_S, _envelope
    from engine.procedural_audio import load_wav
    env = _envelope(load_wav(wav))
    loud, floor = float(np.percentile(env, 95)), float(np.percentile(env, 10))
    voiced = env > floor + ONSET_MIX * (loud - floor)
    out = []
    for w in words:
        a = int(w["t0"] / HOP_S)
        b = max(a + 1, int(w["t1"] / HOP_S) - 3)
        hit = np.nonzero(voiced[a:b])[0]
        t0 = max(w["t0"], (a + int(hit[0])) * HOP_S) if len(hit) else w["t0"]
        out.append(dict(w, t0=round(t0, 3), t1=round(max(w["t1"], t0), 3)))
    return out


def _timing(words: list, direct: int) -> dict:
    pauses = [[a["t1"], b["t0"]] for a, b in zip(words, words[1:])
              if b["t0"] - a["t1"] >= MIN_PAUSE_S]
    bounds = sum(1 for w in words[:-1] if re.search(
        r"[,;:.!?—–-]+[\"'”’)]*$", w["w"]))
    return {"method": METHOD, "speech": [words[0]["t0"], words[-1]["t1"]],
            "pauses": pauses, "boundaries": bounds, "anchored": direct,
            "words": words}


def timing_from_asr(script: str, asr: list, wav=None) -> dict:
    """v15_timing-compatible dict (words/speech/pauses/boundaries/anchored).
    With `wav`, word onsets are refined against the waveform."""
    words, direct = align_to_script(script, asr)
    if wav is not None:
        words = refine_onsets(wav, words)
    return _timing(words, direct)


def clamp_to_spans(timing: dict, counts: list, spans: list) -> dict:
    """We built the audio, so we know where each sentence sits: keep every
    word inside its own sentence's [t0, t1] (ASR sometimes glues the first
    word of a sentence onto the previous one's tail)."""
    words, i = [dict(w) for w in timing["words"]], 0
    for n, (s0, s1) in zip(counts, spans):
        for w in words[i:i + n]:
            w["t0"] = round(min(max(w["t0"], s0), s1), 3)
            w["t1"] = round(max(min(w["t1"], s1), w["t0"]), 3)
        i += n
    return dict(_timing(words, timing["anchored"]), method=timing["method"])
