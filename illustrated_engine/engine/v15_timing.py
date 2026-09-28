"""V15 — narration word timing from the TTS audio (silence_v1 fallback).

WP3: the primary timing is now faster-whisper word timestamps aligned to the
script (engine.voice.align); this module keeps silence_v1 as the offline last
resort and owns the per-beat cache. Original design notes follow.


V14 spread captions evenly over the scene and started them at 0.25 s while
the voice started at 0.0, so captions drifted up to ~1 s from speech and no
visual event could land on its word. The TTS provider (Fish, pinned free
tier) returns no timestamps and no ASR is installed, so timing is recovered
from the waveform:

1. 10 ms RMS envelope -> voiced/unvoiced against a threshold relative to
   the loud (p95) level; speech span = first..last voiced frame.
2. Pauses = unvoiced runs >= MIN_PAUSE_S inside the span.
3. Phrase boundaries = words ending in punctuation. Each boundary's expected
   time comes from a syllable-weighted estimate; boundaries snap in order to
   the nearest unused pause within SNAP_TOL_S (monotonic).
4. Between anchors, words are distributed by estimated syllable weight.

Accuracy is phrase-level (~+-0.1 s at anchors, drifting mid-phrase), which is
what phrase captions, shot cuts and on-word reveals need. Word-exact timing
would need an ASR model (a new dependency -> owner approval) and is a later
layer. Result cached next to the WAV keyed by (wav sha16, text).

CLI: python3 -m engine.v15_timing <wav> "<narration text>"
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

import numpy as np

from engine.procedural_audio import SR, load_wav

HOP_S = 0.010
MIN_PAUSE_S = 0.11
SNAP_TOL_S = 0.9
VOICED_MIX = 0.42  # threshold = floor + MIX*(loud - floor), floor=p10 loud=p95
METHOD = "silence_v1"
_PUNCT_END = re.compile(r"[,;:.!?—–-]+[\"'”’)]*$")


def syllables(word: str) -> float:
    """Spoken-length weight of one narration token (heuristic)."""
    w = word.lower().strip(".,;:!?\"'()“”’")
    if not w or w in ("—", "–", "-"):
        return 0.0
    if any(c.isdigit() for c in w):
        digits = sum(c.isdigit() for c in w)
        extra = sum(1 for c in w if c in ".,") * 0.8
        words_part = re.sub(r"[\d.,]+", " ", w)
        return 1.0 + 1.1 * max(0, digits - 1) + extra + sum(
            syllables(p) for p in words_part.split("-") if p.strip())
    total = 0.0
    for part in re.split(r"[-‐]", w):
        groups = re.findall(r"[aeiouy]+", part)
        n = len(groups)
        if part.endswith("e") and n > 1 and not part.endswith(("le", "ee")):
            n -= 1
        total += max(1, n)
    return float(total)


def _envelope(y: np.ndarray) -> np.ndarray:
    mono = y.mean(axis=1) if y.ndim == 2 else y
    hop = int(SR * HOP_S)
    n = len(mono) // hop
    frames = mono[: n * hop].reshape(n, hop)
    rms = np.sqrt((frames.astype(np.float64) ** 2).mean(axis=1) + 1e-12)
    return 20 * np.log10(rms + 1e-9)


def _runs(mask: np.ndarray) -> list:
    """[(start, end_exclusive)] of True runs."""
    out, start = [], None
    for i, v in enumerate(mask):
        if v and start is None:
            start = i
        elif not v and start is not None:
            out.append((start, i))
            start = None
    if start is not None:
        out.append((start, len(mask)))
    return out


def align(wav_path, text: str) -> dict:
    env = _envelope(load_wav(wav_path))
    # adaptive: TTS pauses carry breath/room noise (~-45 dBFS here), so a
    # fixed offset below the loud level misses them; split floor..loud
    loud, floor = float(np.percentile(env, 95)), float(np.percentile(env, 10))
    voiced = env > floor + VOICED_MIX * (loud - floor)
    idx = np.nonzero(voiced)[0]
    words = str(text).split()
    if len(idx) == 0 or not words:
        raise ValueError(f"no speech detected in {wav_path}")
    s0, s1 = int(idx[0]), int(idx[-1]) + 1
    pauses = [((a * HOP_S), (b * HOP_S)) for a, b in _runs(~voiced[s0:s1])
              if (b - a) * HOP_S >= MIN_PAUSE_S]
    pauses = [(s0 * HOP_S + a, s0 * HOP_S + b) for a, b in pauses]
    merged = []  # a 10-30 ms blip (breath click) must not split one pause
    for a, b in pauses:
        if merged and a - merged[-1][1] <= 0.04:
            merged[-1] = (merged[-1][0], b)
        else:
            merged.append((a, b))
    pauses = merged
    t_start, t_end = s0 * HOP_S, s1 * HOP_S

    wts = [max(syllables(w), 0.0) for w in words]
    # punctuation boundaries (after word i), expected time by syllable share
    bounds = [i for i, w in enumerate(words[:-1]) if _PUNCT_END.search(w)]
    speech_len = (t_end - t_start) - sum(b - a for a, b in pauses)
    per = speech_len / max(sum(wts), 1e-6)
    anchors = {}  # boundary word index -> (pause_start, pause_end)
    used = -1
    for bi in bounds:
        # expected boundary time: syllables so far at the speech rate plus
        # the pauses already anchored before it
        spoken = sum(wts[: bi + 1]) * per
        prior = sum(b - a for k, (a, b) in enumerate(pauses) if k <= used)
        t_exp = t_start + spoken + prior
        best, best_d = None, SNAP_TOL_S
        for k in range(used + 1, len(pauses)):
            c = (pauses[k][0] + pauses[k][1]) / 2
            d = abs(c - t_exp)
            if d < best_d:
                best, best_d = k, d
        if best is not None:
            anchors[bi] = pauses[best]
            used = best

    # segments between anchors -> per-word windows by weight
    out = []
    seg_first, seg_t0 = 0, t_start
    cuts = sorted(anchors) + [len(words) - 1]
    for bi in cuts:
        seg_t1 = anchors[bi][0] if bi in anchors else t_end
        seg = list(range(seg_first, bi + 1))
        tot = sum(wts[i] for i in seg) or 1.0
        cur = seg_t0
        for i in seg:
            d = (seg_t1 - seg_t0) * (wts[i] / tot)
            out.append({"w": words[i], "t0": round(cur, 3),
                        "t1": round(cur + d, 3)})
            cur += d
        seg_first = bi + 1
        seg_t0 = anchors[bi][1] if bi in anchors else seg_t1
    return {"method": METHOD, "speech": [round(t_start, 3), round(t_end, 3)],
            "pauses": [[round(a, 3), round(b, 3)] for a, b in pauses],
            "boundaries": len(bounds), "anchored": len(anchors),
            "words": out}


def timing_key(wav_path, text: str) -> str:
    return hashlib.sha256(Path(wav_path).read_bytes()
                          + text.encode("utf-8")).hexdigest()[:16]


def beat_timing(wav_path, text: str) -> dict:
    """<wav>.timing.json keyed by wav bytes + text (the voice layer writes it
    when it synthesises). On a miss: faster-whisper word timing aligned to the
    script, else silence_v1 (offline last resort)."""
    wav_path = Path(wav_path)
    key = timing_key(wav_path, text)
    cache = wav_path.with_suffix(".timing.json")
    if cache.exists():
        try:
            data = json.loads(cache.read_text())
            if data.get("key") == key:
                return data
        except Exception:
            pass
    try:
        from engine.voice import align as voice_align
        data = voice_align.timing_from_asr(
            text, voice_align.transcribe(wav_path), wav_path)
    except Exception:
        data = align(wav_path, text)
    data = dict(data, key=key)
    cache.write_text(json.dumps(data, indent=1))
    return data


def word_time(timing: dict, index: int) -> float:
    ws = timing["words"]
    return float(ws[max(0, min(index, len(ws) - 1))]["t0"])


def main(argv: list) -> int:
    if len(argv) != 2:
        print(__doc__.strip().splitlines()[-1])
        return 2
    r = align(argv[0], argv[1])
    print(json.dumps({k: r[k] for k in ("speech", "boundaries", "anchored",
                                        "pauses")}, indent=1))
    for w in r["words"]:
        print(f"{w['t0']:6.2f} {w['t1']:6.2f}  {w['w']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
