"""V15 — one-command autonomous production: story -> publish-gated MP4.

    story.json (+facts/bible) -> TTS per beat (cached) -> word timing
    (v15_timing) -> Beat Visual Plan (v15_plan: 1 cached LLM call, validated,
    deterministic fallback) -> one AI plate per shot through the image
    fallback chain (v15_plates, global cache) + 1 plate-QA vision call with
    one regeneration round -> subject analysis -> shot grammars -> Scene IR
    (v15_shots, one scene per shot) -> §24/§25 cache-aware render (existing
    select_backend + v14_cache) -> assembly (existing v14_assembly: concat
    filter, phrase captions on measured word times burned AFTER composition,
    narration + underscore + SFX, loudnorm) -> v15_gate (deterministic hard
    checks + 1 vision-judge call) -> PASS / HOLD with reasons.

Everything V14 built is reused; V15 adds the semantic plan, the plate layer,
timing, and an honest gate. v14_pipeline stays runnable as the floor path.

Usage:
  python3 -m engine.v15_pipeline --story stories/ice_slippery \\
      --work build/v15/ice_slippery [--no-llm] [--no-judge] [--backend auto]
Exit 0 = publish gate PASS, 1 = HOLD (report says why), 2 = error.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPO = ROOT.parent
for _p in (REPO, ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from engine.scene_ir import spec_hash, validate_scene_spec  # noqa: E402
from engine.scene_renderer import compile_spec, select_backend  # noqa: E402
from engine.v14_assembly import assemble  # noqa: E402
from engine.v14_cache import (bed_plan_hash, caption_plan_hash,  # noqa: E402
                              load_index, narration_plan_hash,
                              plan_production, record_assembly, record_scene,
                              save_index, scene_cache_key, style_hash)
from engine.v15_plan import make_plan  # noqa: E402
from engine.v15_plates import (PROVIDER_ORDER, analyze_subject,  # noqa: E402
                               generate_plate, image_chain_report, plate_qa,
                               providers_for_beat_function)
from engine.v15_shots import compile_shot  # noqa: E402
from engine.v15_style import image_prompt, load_style  # noqa: E402
from engine.v15_timing import beat_timing  # noqa: E402
from engine.captions import V15_CAPTION_TOP  # noqa: E402

# 2026-10-15 review: inter-sentence silence averaged 0.62-0.69 s (up to 23%
# of runtime). Measured make-up of that gap on the two reviewed renders:
# ~0.12 s kept clip tail (voice._trim's 150 ms consonant-release guard --
# NOT shortened, it fixed a real "light"->"life" misread) + LEAD_S 0.18 +
# ~0.02 s clip lead + beat_tail 0.28-0.75. LEAD_S 0.18 -> 0.06 and the
# beat_tail magnitudes below cut ~4x; the role-based VARIATION (hook rolls
# straight on, a held beat before the payoff / after a question, a landing
# at the end) is unchanged in shape. Typical gap now ~0.2-0.3 s, ~0.45 s
# before the payoff. NOTE: each beat is still its own TTS clip; synthesising
# a whole paragraph per clip (more natural prosody across sentences) needs
# beat timing re-derived from one long clip -- deferred, see report.
LEAD_S = 0.06      # silence before a beat's narration (breath + first frame)
# B4 (VIS): v16_gate.HOOK_MAX_FIRST_WORD_S=0.25 bounds LEAD_S + the first
# measured word's t0 (typically 0.01-0.05s) — 0.30 alone already missed it
# (WP10/real sample: first word at 0.31-0.32s); 0.18 leaves margin.
TAIL_S = 0.55      # hold after the narration ends
CUT_EARLY_S = 0.12  # cut slightly BEFORE the word that starts a shot
MIN_SHOT_S = 1.4
# 2026-10-15 review: the brand sting at t=0 peaked ~7 dB above the body and
# broke the seamless loop the scripts are written for. Kept at the open
# (moving it to the end would sit on the last spoken line, which also
# loops) but at -10.5 dB, i.e. a few dB UNDER the body instead of over it.
STING_GAIN = 0.3
RENDER_CONFIG = {"concurrency": 2, "pipeline": "v15"}
INTENSITY = {"HOOK": 0.75, "CURIOSITY": 0.62, "REVEAL": 0.85,
             "EXPLANATION": 0.66, "ESCALATION": 0.82, "PAYOFF": 0.88}
_PUNCT_ONLY = re.compile(r"^[\W_]+$")
# decision #18 item 1: one shared set with the gate's clause-break check.
from engine.v15_gate import CAPTION_FUNCTION_WORDS as _FUNCTION_WORDS  # noqa: E402
# Quantifier lead-ins bind to a following "to"/figure ("up to 20", "about
# 430", "over 1.5") \u2014 "dimming it for up" | "to 20 seconds" split the phrase.
_QUANT_LEADS = {"up", "about", "around", "nearly", "roughly", "almost", "over",
                "under", "only", "just", "some", "more", "less", "fewer"}
# decision #18 item 1: cue segmentation is a small per-sentence DP (below),
# not a greedy 4-word cut — the greedy backtrack stranded lone function
# words ("to", "up") as their own cues on dry run 5.
# 2026-10-15 review: captions grew 64 -> 96 px, so cues got shorter (was
# 7 words / 36 chars): 2-3 words is the Shorts norm and keeps the caption
# big; anything wider than one line wraps to two (engine.captions).
CUE_MAX_WORDS = 6
CUE_MAX_CHARS = 26
_LEN_COST = {1: 5, 2: 0, 3: 0, 4: 2, 5: 5, 6: 9}
_BIND_COST = 50      # ending a cue on a word that binds forward
_INNER_CLAUSE_COST = 3  # a clause break (,;:) INSIDE a cue
_SENT_END = re.compile(r"([.!?]|\.\.\.|\u2026)['\")\]]*$")
_CLAUSE_END_W = re.compile(r"[,;:\u2014]['\")\]]*$")


# ---------------------------------------------------------------- captions --

def _binds_forward(word: str, nxt: str | None = None) -> bool:
    """Function words and bare figures belong with the NEXT word (a number
    with its unit, an article with its noun) unless punctuation ends them.
    A quantifier lead-in ("up", "about", ...) binds when the next word is
    "to"/"than" or a figure."""
    if re.search(r"[,.;:!?\u2014\u2026]$", word):
        return False
    w = word.lower()
    # a bare figure or digit RANGE ("430-510") binds to its unit
    if w in _FUNCTION_WORDS or bool(re.fullmatch(r"[\d.,]+(?:-[\d.,]+)?", w)):
        return True
    if nxt is not None and w in _QUANT_LEADS:
        n = nxt.lower()
        return n in ("to", "than") or bool(re.match(r"\d", n))
    return False


def _segment(words: list) -> list:
    """Words of ONE sentence -> list of groups minimising the summed cue
    cost: length (3-4 words ideal), +_BIND_COST when a cue ends on a word
    that grammatically binds to the next one, -1 for ending on a clause
    mark or a >0.25 s pause, +_INNER_CLAUSE_COST per clause mark swallowed
    mid-cue. Hard limits: CUE_MAX_WORDS words and CUE_MAX_CHARS characters
    (a single over-long word is always allowed)."""
    n = len(words)
    best = [0.0] + [float("inf")] * n
    back = [0] * (n + 1)
    for j in range(1, n + 1):
        for i in range(max(0, j - CUE_MAX_WORDS), j):
            g = words[i:j]
            if len(g) > 1 and len(" ".join(w["w"] for w in g)) > CUE_MAX_CHARS:
                continue
            last = g[-1]["w"]
            nxt = words[j] if j < n else None
            c = _LEN_COST[len(g)]
            if nxt is not None:
                if _binds_forward(last, nxt["w"]):
                    c += _BIND_COST
                if _CLAUSE_END_W.search(last) or nxt["t0"] - g[-1]["t1"] > 0.25:
                    c -= 1
            c += _INNER_CLAUSE_COST * sum(
                1 for w in g[:-1] if _CLAUSE_END_W.search(w["w"]))
            if best[i] + c < best[j]:
                best[j], back[j] = best[i] + c, i
    groups, j = [], n
    while j > 0:
        groups.append(words[back[j]:j])
        j = back[j]
    return groups[::-1]


# 2026-10-15: with the faster delivery a 2-word cue can be on screen for
# < 0.4 s; the old fixed 0.4 s floor then overlapped the NEXT cue, and the
# caption state machine shifted / dropped it ("a crater" vanished from the
# e2e re-render -> caption_identity HOLD). Mid-beat cues no longer extend
# into the next one, and a cue too short to survive the state machine
# (engine.captions.MIN_CUE 0.30 + the 0.06 s off-gap) merges into a
# neighbour in its sentence -- capped at CUE_MERGE_MAX_CHARS so a merge
# can't build a long, small-font caption.
CUE_MIN_S = 0.36
CUE_MERGE_MAX_CHARS = 30


def _chars(*gs) -> int:
    return len(" ".join(w["w"] for g in gs for w in g))


def _merge_short_groups(groups: list, lead: float) -> list:
    out = list(groups)
    i = 0
    while i < len(out) - 1:
        g, nxt = out[i], out[i + 1]
        same_sentence = not _SENT_END.search(g[-1]["w"])
        short = nxt[0]["t0"] - g[0]["t0"] < CUE_MIN_S
        if same_sentence and short and _chars(g, nxt) <= CUE_MERGE_MAX_CHARS:
            out[i:i + 2] = [g + nxt]
            continue
        # 2026-10-17: a short mid-sentence cue whose forward merge is too
        # long was left alone and the caption state machine dropped it:
        # live_20261017_181106 t_a_whale_s_fin B4 "a little" (0.16 s, after
        # a 0.46 s pause) vanished -> caption_identity FAIL. Fold it back
        # into the previous cue of its sentence; if that is too long as
        # well, merge forward anyway -- a long caption beats a missing one.
        if same_sentence and short:
            if i > 0 and not _SENT_END.search(out[i - 1][-1]["w"]) \
                    and _chars(out[i - 1], g) <= CUE_MERGE_MAX_CHARS:
                out[i - 1:i + 1] = [out[i - 1] + g]
                i -= 1
                continue
            out[i:i + 2] = [g + nxt]
            continue
        # a short sentence-FINAL cue folds back into its own sentence
        if short and not same_sentence and i > 0 \
                and not _SENT_END.search(out[i - 1][-1]["w"]) \
                and _chars(out[i - 1], g) <= CUE_MERGE_MAX_CHARS:
            out[i - 1:i + 1] = [out[i - 1] + g]
            i -= 1
            continue
        i += 1
    return out


def caption_cues(timing: dict, lead: float, end: float | None = None) -> list:
    """Phrase cues (ideally 3-4 words, never across a sentence end, never
    ending on a word that binds to the next — see _segment) on the
    measured word times; per-word starts drive the active-word highlight.
    B1 (VIS): on-screen text shows DIGITS ("155-145 million years ago")
    while the narration/TTS text keeps the spelled-out words a TTS model
    reads reliably — captions are built from a numeralized copy of the
    measured word timing, never from the narration string itself."""
    from engine.voice.text import numeralize_cue_words
    words = []
    for w in numeralize_cue_words(timing["words"]):
        if _PUNCT_ONLY.match(w["w"]) and words:
            words[-1] = dict(words[-1], w=words[-1]["w"] + " " + w["w"],
                             t1=w["t1"])
            continue
        words.append(dict(w))
    groups, sent = [], []
    for w in words:   # sentences are hard cue boundaries
        sent.append(w)
        if _SENT_END.search(w["w"]):
            groups += _segment(sent)
            sent = []
    if sent:
        groups += _segment(sent)
    groups = _merge_short_groups(groups, lead)
    cues = []
    for gi, g in enumerate(groups):
        t0 = lead + g[0]["t0"]
        nxt_t0 = lead + groups[gi + 1][0]["t0"] if gi + 1 < len(groups) else None
        t1 = (nxt_t0 - 0.06) if nxt_t0 is not None else lead + g[-1]["t1"] + 0.3
        if nxt_t0 is None:
            t1 = max(t1, t0 + 0.4)   # mid-beat cues never run into the next
        if end is not None:          # never past the beat (tails are short now)
            t1 = min(t1, end - 0.02)
        cues.append({"t0": round(t0, 3), "t1": round(t1, 3),
                     "text": " ".join(w["w"] for w in g),
                     "word_starts": [round(lead + w["t0"], 3) for w in g]})
    return cues


# ------------------------------------------------------------------ shots --

def shot_timeline(beat: dict, bplan: dict, timing: dict, tts_s: float,
                  tail_s: float = TAIL_S) -> list:
    """Beat -> [{shot, t0, t1}] in beat-local seconds; shots shorter than
    MIN_SHOT_S merge into the previous one (recorded). `tail_s` is the hold
    after the narration (engine.v15_pipeline.beat_tail in the pipeline)."""
    beat_dur = LEAD_S + tts_s + tail_s
    wt = [w["t0"] for w in timing["words"]]
    starts = []
    for k, sh in enumerate(bplan["shots"]):
        t = 0.0 if k == 0 else LEAD_S + wt[min(sh["start_word"], len(wt) - 1)] \
            - CUT_EARLY_S
        starts.append((t, sh))
    def _copy(s):
        return bool(s.get("headline") or s.get("number") or s.get("label"))

    out, absorbed = [], []
    for i, (t, sh) in enumerate(starts):
        t1 = starts[i + 1][0] if i + 1 < len(starts) else beat_dur
        if out and t1 - t < MIN_SHOT_S:
            out[-1]["t1"] = t1
            out[-1].setdefault("merged", []).append(sh["kind"])
            continue
        if not out and i + 1 < len(starts) and t1 - t < MIN_SHOT_S:
            nxt = starts[i + 1][1]
            if _copy(sh) and not _copy(nxt):
                # first too short but it carries the on-screen copy (the
                # hook headline/number): keep it, fold the next shot in.
                # Dropping it lost "SIX G. LIGHTS OUT." from frame 0 and
                # HOLDed t_pilots_train_to_pass_out_on_purpose ("no
                # headline text box on the opening shot", 2026-10-16).
                starts[i + 1] = (t, sh)
                absorbed.append(nxt["kind"])
            else:
                starts[i + 1] = (t, nxt)  # first too short -> drop
            continue
        out.append({"shot": sh, "t0": round(t, 3), "t1": round(t1, 3)})
        if absorbed:
            out[-1]["merged"], absorbed = absorbed, []
    out[-1]["t1"] = round(beat_dur, 3)
    return out


MAX_HOLD_S = 3.0  # B3 (VIS): <=3s per shot (the gate itself still allows 4.5s)

# ------------------------------------------------------- editorial rhythm --
# Owner review 2026-10-14 ("feels AI generated"): one global MAX_HOLD_S=3.0
# with every split cut at the word nearest the gap MIDPOINT turned the
# average ~4.5 s beat into two near-equal ~2.25 s halves, every time. Across
# the 11 batch renders of 2026-10-13/14, 39% of all shots (96/246) were such
# derived halves, 70% of shots were 1.5-2.5 s long, and 2-shot beats had a
# median shorter/longer ratio of 0.885. A fixed TAIL_S made every sentence-
# to-sentence pause ~1.0 s +-0.1 (13 identical gaps in a 54 s video).
# The rhythm is now driven by the beat's ROLE plus a deterministic per-story
# jitter (sha256 of story_id — reproducible run to run, different per story):
#   - hold ceiling per beat: fast cuts on the HOOK, a tightening run-up
#     before the payoff, longer holds where an idea needs to land (PAYOFF,
#     REVEAL/EXPLANATION), a punchy short line kept as ONE picture;
#   - the split point lands anywhere in 30-70% of the gap, preferring the
#     start of a phrase (cut on the clause boundary, as an editor would);
#   - the pause after a beat depends on what follows it.
# Every ceiling stays under v15_gate.MAX_HOLD_S (4.5 s, the hard floor).
HOLD_BY_FUNCTION = {"HOOK": 2.5, "CURIOSITY": 2.8, "ESCALATION": 2.5,
                    "REVEAL": 3.4, "EXPLANATION": 3.3, "PAYOFF": 3.7}
HOLD_NORMAL_S = 3.0
HOLD_JITTER_S = 0.55
HOLD_SHORT_LINE_WORDS = 7      # a line this short is a single punchy picture
HOLD_SHORT_LINE_BONUS_S = 0.7
HOLD_RUNUP_S = 0.3             # NORMAL beats in the run-up to the payoff
HOLD_RUNUP_BEATS = 3           # only the last N beats dip, not 35% of the video
HOLD_PROGRESS_S = 0.6          # extra hold by the last beat (linear in bi/n)
HOLD_PROGRESS_SCALE = (0.75, 1.25)  # seeded per-story spread of that ramp
HOLD_MIN_S, HOLD_MAX_S = 2.2, 4.0
SPLIT_FRAC = (0.30, 0.70)
SPLIT_PHRASE_BONUS_S = 0.45    # a cut on a phrase start may sit this far off
# 2026-10-15 review: magnitudes cut (were 0.28-0.62 / 0.3 / 0.75 / 0.7 /
# 0.7); the ordering of the roles is preserved.
TAIL_RANGE_S = (0.0, 0.10)     # ordinary beat-to-beat breath (was 0.55 fixed)
TAIL_AFTER_HOOK_S = 0.0        # the hook rolls straight into the story
TAIL_BEFORE_PAYOFF_S = 0.28    # a held beat before the answer lands
TAIL_QUESTION_S = 0.22         # a spoken question gets a moment
TAIL_END_S = 0.35              # last line lands, then loops / sting
_PHRASE_END = re.compile(r"[,.;:!?—…]['\")\]]*$")


def _unit(*parts) -> float:
    """Deterministic uniform [0, 1) from the given parts (DESIGN §8.1: ties
    broken by hashing story ids, never by a random choice)."""
    h = hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()
    return int(h[:12], 16) / float(16 ** 12)


def beat_max_hold(beat: dict, bi: int, n_beats: int, seed: str) -> float:
    """Per-beat ceiling for the longest stretch without a visual change
    (split_long_holds' max_hold_s), from the beat's role + seeded jitter."""
    fn = (beat.get("function") or "NORMAL").upper()
    base = HOLD_BY_FUNCTION.get(fn, HOLD_NORMAL_S)
    # progressive lengthening (owner follow-up 2026-10-14): a fast open,
    # then the pace relaxes as the story unfolds -- every beat, whatever its
    # role, gets up to +HOLD_PROGRESS_S by the last beat, scaled by a seeded
    # per-story factor. Added BEFORE the run-up subtraction so the run-up
    # still reads as a dip against the prevailing trend.
    if n_beats >= 2:
        lo, hi = HOLD_PROGRESS_SCALE
        base += HOLD_PROGRESS_S * (bi / (n_beats - 1)) \
            * (lo + (hi - lo) * _unit(seed, "progress"))
    # Owner follow-up 2026-10-14 ("make best judgment... feels human made"):
    # the 65%-of-video run-up window was swallowing most of the new
    # progressive lengthening on ordinary late beats (frog: late beats
    # 3.56 -> 3.35 average, barely a rise). A real edit only tightens up
    # right before the reveal, not for the last third of the video --
    # narrowed to the last HOLD_RUNUP_BEATS beats so the "relax as the
    # story unfolds" trend actually reads on everything before that.
    if fn not in HOLD_BY_FUNCTION and n_beats >= 5 \
            and bi >= n_beats - HOLD_RUNUP_BEATS:
        base -= HOLD_RUNUP_S
    if len(str(beat.get("narration", "")).split()) <= HOLD_SHORT_LINE_WORDS \
            and fn != "HOOK":
        base += HOLD_SHORT_LINE_BONUS_S
    h = base + (2 * _unit(seed, "hold", beat.get("beat_id")) - 1) * HOLD_JITTER_S
    return round(min(HOLD_MAX_S, max(HOLD_MIN_S, h)), 2)


def beat_tail(beats: list, bi: int, seed: str) -> float:
    """Silence held after beat `bi`'s narration (replaces the fixed TAIL_S
    for the V15 pipeline): depends on what the next beat is."""
    b = beats[bi]
    if bi == len(beats) - 1:
        return TAIL_END_S
    fn = (b.get("function") or "").upper()
    nxt = (beats[bi + 1].get("function") or "").upper()
    if fn == "HOOK":
        return TAIL_AFTER_HOOK_S
    if nxt == "PAYOFF" and fn != "PAYOFF":
        return TAIL_BEFORE_PAYOFF_S
    if str(b.get("narration", "")).rstrip(" \"')").endswith("?"):
        return TAIL_QUESTION_S
    lo, hi = TAIL_RANGE_S
    return round(lo + (hi - lo) * _unit(seed, "tail", b.get("beat_id")), 3)


def split_margin(max_hold_s: float) -> float:
    """Shortest piece a rhythm split may leave: never a sub-1.2 s flicker
    of an AI plate, never more than 1.5 s."""
    return max(1.2, min(1.5, max_hold_s / 3))


def _split_one(s: dict, wt: list, bt: list, max_hold_s: float,
               margin_s: float, frac: float = 0.5,
               words: list | None = None) -> list | None:
    """One shot -> [first, second] split at its single worst gap, or None
    if it's already within max_hold_s or has no valid split word (every
    candidate would land within `margin_s` of a gap edge, producing a
    sliver shot). The cut lands nearest `frac` of the way through the gap
    (0.5 = the old midpoint); with `words` (the measured word strings), a
    word that starts a new phrase is preferred by SPLIT_PHRASE_BONUS_S."""
    sh = s["shot"]
    if sh["kind"] != "plate":
        return None
    ev = [s["t0"]] + sorted(LEAD_S + wt[min(sh[k]["word"], len(wt) - 1)]
                            for k in ("number", "label") if sh.get(k)) \
        + [s["t1"]]
    gaps = [(ev[i], ev[i + 1]) for i in range(len(ev) - 1)]
    a, b = max(gaps, key=lambda g: g[1] - g[0])
    if b - a <= max_hold_s:
        return None
    target = a + (b - a) * frac
    cands = [i for i, t in enumerate(bt) if a + margin_s <= t <= b - margin_s
             and s["t0"] + margin_s <= t <= s["t1"] - margin_s]
    if not cands:
        return None

    def _cost(i):
        c = abs(bt[i] - target)
        if words and i > 0 and _PHRASE_END.search(str(words[i - 1])):
            c -= SPLIT_PHRASE_BONUS_S
        return c
    wi = min(cands, key=_cost)
    first = {k: v for k, v in sh.items()}
    # B3 (VIS): the split-off shot must be a GENUINELY different image (the
    # deterministic seed is a hash of this subject text) — a bare copy of
    # `subject` here reused the exact same cached plate under a new camera
    # move, which is what the vision judge's "no_change" frame flags were
    # catching (bench/ab/vis.md). A tight-crop framing of the same subject
    # is still the right follow-on shot, just backed by its own plate.
    # decision #18 item 3: the old ", tight close-up detail crop" SUFFIX was
    # ignored by the image model (dry run 5: B2_S3/B11_S2 redrew the same
    # whole-planet picture -> judge "no_change"). The derived shot now takes
    # a DIFFERENT view than its parent, prepended by image_prompt.
    parent_view = sh.get("view")
    second = {"kind": "plate", "subject": sh["subject"],
              "view": "wide" if parent_view == "close" else "close",
              "composition": "centered",
              "camera": "punch_in", "start_word": wi, "derived": "punch_in"}
    for k in ("number", "label"):
        if sh.get(k) and sh[k]["word"] >= wi:
            second[k] = first.pop(k)
    return [dict(s, shot=first, t1=round(bt[wi], 3)),
            {"shot": second, "t0": round(bt[wi], 3), "t1": s["t1"]}]


def split_long_holds(tl: list, timing: dict, max_hold_s: float = MAX_HOLD_S,
                     margin_s: float | None = None,
                     seed: str | None = None) -> list:
    """Plate shots whose longest stretch without a visual change exceeds
    `max_hold_s` (default MAX_HOLD_S=4.4, the V15 gate floor) are split at
    the word nearest the gap's middle into a CUT to a tighter framing of
    the same plate (camera punch_in) — an editorial punch-in, not new
    content; planned elements move with their words. Splitting repeats
    (each half re-checked) so a shot with more than one long gap gets more
    than one cut, not just its single worst one. `margin_s` bounds how
    close a split word may sit to either edge of the gap it's splitting
    (no sliver shots); it defaults to min(1.5, max_hold_s/3) so it scales
    down with a tighter threshold instead of making splitting impossible
    for gaps only slightly over a small max_hold_s. WP7 callers pass the
    tighter engine.v15_gate.MAX_HOLD_1_8_S=1.8 target (DESIGN §8.2); the
    V15 pipeline itself keeps calling this with the default.
    `seed` (the V15 pipeline passes story_id + beat_id) turns on the
    editorial rhythm: each split's cut point is drawn deterministically from
    SPLIT_FRAC and prefers a phrase start, instead of the exact midpoint
    (seed=None keeps the old midpoint behaviour)."""
    if margin_s is None:
        margin_s = min(1.5, max_hold_s / 3)
    wt = [w["t0"] for w in timing["words"]]
    ws = [w.get("w", "") for w in timing["words"]] if seed is not None else None
    bt = [LEAD_S + t - CUT_EARLY_S for t in wt]  # beat-time cut per word
    lo, hi = SPLIT_FRAC
    changed = True
    while changed:
        changed = False
        out = []
        for s in tl:
            frac = 0.5 if seed is None else \
                lo + (hi - lo) * _unit(seed, "split", f"{s['t0']:.3f}")
            split = _split_one(s, wt, bt, max_hold_s, margin_s, frac, ws)
            if split is None:
                out.append(s)
            else:
                out.extend(split)
                changed = True
        tl = out
    return tl


def _prompts_for(shot: dict, bible: dict, subject_bible: dict | None = None,
                 hook: bool = False) -> list:
    from engine.species import augment_subject
    from engine.subject_bible import inject_subject

    def _augment(subject):
        return inject_subject(augment_subject(subject), subject_bible or {})
    if shot["kind"] == "zoom_through":
        return [image_prompt(bible, _augment(lv["subject"]), "centered")
                for lv in shot["levels"]]
    return [image_prompt(bible, _augment(shot["subject"]),
                         shot.get("composition", "centered"),
                         view=shot.get("view"), hook=hook)]


def _prompt_parts(shot: dict, subject_bible: dict | None = None,
                  hook: bool = False) -> list:
    """Parallel to _prompts_for: the pieces each prompt was built from, so a
    failed plate's prompt can be REBUILT with steering (decision #18)."""
    from engine.species import augment_subject
    from engine.subject_bible import inject_subject

    def _augment(subject):
        return inject_subject(augment_subject(subject), subject_bible or {})
    if shot["kind"] == "zoom_through":
        return [{"subject": _augment(lv["subject"]), "composition": "centered",
                 "view": None} for lv in shot["levels"]]
    return [{"subject": _augment(shot["subject"]),
             "composition": shot.get("composition", "centered"),
             "view": shot.get("view"), "hook": hook}]


SFX_MAX_GAP_S = 6.0   # longest stretch allowed without any SFX cue


def fill_sfx_gaps(meta: dict, events: dict) -> list:
    """Cheap SFX density floor (2026-10-15 review, priority 7): a soft
    whoosh on the first cut after more than SFX_MAX_GAP_S without any SFX,
    and a pulse accent on the first shot of the first PAYOFF beat if it
    has none. Content-MATCHED SFX (impact / water / machine hum keyed to
    what a beat shows) needs new licensed sound assets -- the library only
    carries pulse/tick (+ procedural whoosh) -- and is deferred.
    Mutates `events`; -> list of added cues."""
    added, t, last, payoff_done = [], 0.0, 0.0, False
    for key, m in meta.items():
        evs = events.setdefault(key, [])
        if (m.get("function") == "PAYOFF" and not payoff_done):
            payoff_done = True
            if not any(e["kind"] == "pulse" for e in evs):
                ev = {"t": 0.05, "kind": "pulse", "gain": 0.55}
                evs.append(ev)
                added.append({"shot": key, **ev})
        if t - last > SFX_MAX_GAP_S and not any(e["t"] < 0.3 for e in evs):
            ev = {"t": 0.0, "kind": "whoosh", "gain": 0.35}
            evs.append(ev)
            added.append({"shot": key, **ev})
        if evs:
            last = t + max(e["t"] for e in evs)
        t += float(m["dur"])
    return added


def dedupe_shot_prompts(shots: list, bible: dict,
                        subject_bible: dict | None = None) -> list:
    """2026-10-15 review: a plate shot whose prompt duplicates an EARLIER
    shot's prompt is re-viewed (next of _DUP_VIEWS that differs from its
    own view and its neighbour's) and its prompts rebuilt, so every shot
    gets its own generated image. Mutates `shots`; -> change log."""
    seen, log = set(), []
    for i, s in enumerate(shots):
        if s["shot"]["kind"] != "plate":
            seen.update(s["prompts"])
            continue
        tries = 0
        while any(p in seen for p in s["prompts"]) and tries < len(_DUP_VIEWS):
            prev_view = shots[i - 1]["shot"].get("view") if i else None
            cur = s["shot"].get("view")
            opts = [v for v in _DUP_VIEWS if v not in (cur, prev_view)]
            new_view = opts[tries % len(opts)]
            s["shot"] = dict(s["shot"], view=new_view, dedup_from=cur)
            s["prompts"] = _prompts_for(s["shot"], bible, subject_bible,
                                        s.get("hook", False))
            tries += 1
            log.append({"shot": f"{s['beat']['beat_id']}_S{s['idx'] + 1}",
                        "from_view": cur, "to_view": new_view})
        seen.update(s["prompts"])
    return log


# decision #18 item 4: a plate that fails QA is regenerated from a prompt
# STEERED by why it failed (positive phrasing only — FLUX has no negative
# prompt), not the identical prompt on another provider. Near-duplicates
# rotate to a different view each round.
_DUP_VIEWS = ("surface", "close", "cutaway", "medium", "wide")
# "one" is NOT stripped (2026-10-17): it is mostly a pronoun in narration,
# and stripping it broke the sentence the image model was asked to draw --
# t_your_finger B8 resubject subject "If it stretches too far, it snaps,
# and a brand-new forms" (narration: "...a brand-new one forms") came back
# as "reptilian creature standing in a cave".
_NUMWORDS_RE = re.compile(
    r"(?i)\b(zero|one(?=[\s-]+(?:and[\s-]+a[\s-]+half|hundred|thousand|million|billion|tenth|half|third|quarter))|two|three|four|five|six|seven|eight|nine|ten|eleven|"
    r"twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|"
    r"twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|"
    r"thousand|million|billion|half|\d[\d.,]*)\b")


def steer_prompt(bible: dict, parts: dict, reason: str | None, rnd: int,
                 identity: dict | None = None,
                 narration: str | None = None) -> str:
    subj = parts["subject"].rstrip(". ")
    comp, view = parts.get("composition", "centered"), parts.get("view")
    ident = identity or {}
    # the plate's OWN named object = first clause of its subject. Steering
    # leads with it for wrong_subject/empty; only generic_subject (a generic
    # stand-in for the recurring subject) leads with the identity. Dry run 6
    # (final): an "empty" land-bridge plate steered toward "the main
    # subject" became a big beaver (the identity was injected in its
    # prompt), then identity-led wrong_subject steering kept drawing the
    # beaver for 2 more rounds -> still failing -> FAIL.
    first = re.split(r"(?<=[.;,])\s", subj, maxsplit=1)[0].rstrip(".,;")
    if reason == "generic_subject" and ident.get("description"):
        name = ident.get("name") or "the main subject"
        subj = (f"{name}, {ident['description'].rstrip('. ')}, "
                f"unmistakably this specific subject. {subj}")
    elif reason in ("wrong_subject", "generic_subject"):
        subj = f"Clearly and unmistakably showing {first}. {subj}"
    elif reason == "empty":
        subj = (f"{first}, large and richly detailed, filling most of the "
                f"frame. {subj}")
        comp = "centered"
        if view in (None, "wide"):
            view = "medium"
    elif reason == "near_duplicate":
        opts = [v for v in _DUP_VIEWS if v != view]
        view = opts[(rnd - 1) % len(opts)]
    elif reason == "narration_mismatch" and narration:
        what = " ".join(_NUMWORDS_RE.sub("", narration).split()).strip(" .,")
        subj += f". The scene clearly depicts: {what}"
    elif reason == "bad_anatomy":
        subj += ". Anatomically accurate in every listed detail"
    elif reason == "text":
        subj += ", clean unmarked painted surfaces only"
    elif reason == "low_information":
        # see plate_low_information: the house look's "deep shadow" came
        # back as near-black frames (mean luma 13-30/255) with nothing to read
        subj += (". Brightly lit scene with fine texture and crisp detail "
                 "across the entire frame, no large empty, black or blank areas")
        if view in (None, "wide"):
            view = "medium"
    return image_prompt(bible, subj, comp, view=view,
                        hook=bool(parts.get("hook")))


# 2026-10-16 (zero-publish day): one failing plate out of 12-24 FAILs the
# whole video (plate QA is critical in v15_gate). 8 of the 21 batch renders
# since 2026-10-13 ended that way. Steering keeps the PLANNER's subject and
# only appends to it, so when that subject itself is the problem it fails
# every round: live_20261016_032600 storm B5_S1 was planned as "a
# hypothetical deep towering column of swirling storm" over the narration
# "this monster likely isn't a deep tower at all, but a thin spinning
# sheet" -> generic_subject, narration_mismatch, narration_mismatch. Two
# last-resort steps, both still judged by the same plate QA / gate:
#   1. RESUBJECT step -- a plate still failing on a CONTENT reason gets
#      RESUBJECT_VARIANTS generations whose subject is rebuilt from the
#      beat's narration (planner subject dropped), in views its beat
#      siblings don't use, judged in one plate QA call; the first variant
#      that passes replaces the plate. Live probe on that storm plate: 2/2
#      such generations passed plate QA.
#   2. drop_unfixable_shots -- a plate shot that still fails is removed and
#      its time given to a QA-passed sibling in the SAME beat, only when the
#      merged shot stays within that beat's own hold ceiling. A failed image
#      never ships; the beat is still covered by an image that passed QA
#      against its narration.
RESUBJECT_REASONS = ("narration_mismatch", "wrong_subject", "generic_subject",
                     "empty")
# Re-run of the storm render with ONE resubject generation: its plate (a
# swirling vortex with a dark centre) was read as a "tunnel" ->
# narration_mismatch, while the probe's 2 generations both passed: the step
# is stochastic, so it draws 2 seed/view variants judged in a single QA call.
RESUBJECT_VARIANTS = 2


def resubject_prompt(bible: dict, narration: str, identity: dict | None,
                     avoid_views=(), variant: int = 0) -> tuple:
    """-> (prompt, subject): the subject rebuilt from the beat narration
    (numbers stripped, as narration_mismatch steering does), recurring-
    subject look injected, in the `variant`-th view no sibling shot of the
    beat uses. The subject is returned so plate QA judges the plate against
    what it was actually asked to show."""
    from engine.subject_bible import inject_subject
    what = " ".join(_NUMWORDS_RE.sub("", narration).split()).strip(" .,")
    subj = inject_subject(what, identity or {})
    ident = identity or {}
    if subj == what and ident.get("description"):
        # 2026-10-17: narration that never NAMES the recurring subject
        # ("The fire screams past them, yet they stay put", "If it stretches
        # too far, it snaps...") gave the image model nothing to draw:
        # live_20261017_064800 t_the_sky_is_carving_rocket_fire_into_diam
        # B2 and t_your_finger B8 both failed resubject 0/2 as "empty"
        # (a silhouetted figure in flames; a reptile in a cave). Lead with
        # the locked subject the pronouns refer to, then the narration.
        name = (ident.get("name") or "the main subject").rstrip(". ")
        subj = (f"{name} ({ident['description'].rstrip('. ')}), "
                f"shown as the narration describes: {what}")
    views = [v for v in ("cutaway", "wide", "medium", "close", "surface")
             if v not in set(avoid_views)] or ["medium"]
    return (image_prompt(bible, subj, "centered", view=views[variant % len(views)]),
            subj)


# 2026-10-17 (zero passes in ~6 batches since the first publish): a plate
# whose generation FAILED outright (every provider errored) was never
# retried -- plate QA and its regen rounds only see plates that exist -- so
# it went straight to the V14 procedural tier. In live_20261017_015400 /
# _064800 that was 12 procedural shots across 3 stories, B1 (HOOK) and
# B7/B8 (PAYOFF) most of all: hero prompts may not use pollinations, the
# one provider that was rescuing the other shots, and Cloudflare's 429s
# came from 3 workers bursting it at once (the same story's regen rounds
# got Cloudflare plates minutes later). Those shots then drew "asset tier
# procedural", judge empty_or_flat and "first frame would not stop a
# scroll". On top, sdcpp_local sat in the parallel chain: 3 concurrent CPU
# runs, each past its 1800 s timeout (plates_s 2460-6570 s, 0 plates).
# Now: cloud providers only in the parallel pass; failures get a cooled-
# down SEQUENTIAL retry of the same prompt/seed (hero plates first); only
# what still fails reaches the local floor, one at a time, capped per
# video (image_gen.sdcpp.max_plates_per_video).
FLOOR_PROVIDERS = ("sdcpp_local",)
GEN_RETRY_COOLDOWN_S = 20.0


def recover_failed_plates(plates: dict, prompts: list, regen, *, hero=(),
                          floor=None, floor_cap: int = 0,
                          cooldown_s: float = GEN_RETRY_COOLDOWN_S,
                          sleep=time.sleep) -> dict:
    """Second chance for plates whose generation failed. `plates` maps
    prompt -> generate_plate result and is updated in place; `prompts` is
    timeline order; regen(prompt) / floor(prompt) -> a new result. -> log."""
    failed = list(dict.fromkeys(p for p in prompts
                                if p in plates and not plates[p].get("ok")))
    log = {"first_pass_failed": len(failed), "recovered": 0, "floor_tried": 0,
           "floor_used": 0, "still_failed": 0}
    if not failed:
        return log
    failed.sort(key=lambda p: p not in set(hero))   # hero first, stable
    sleep(cooldown_s)
    for p in failed:
        r = regen(p)
        if r.get("ok"):
            plates[p] = r
            log["recovered"] += 1
    left = [p for p in failed if not plates[p].get("ok")]
    if floor is not None:
        for p in left[:max(0, floor_cap)]:
            log["floor_tried"] += 1
            r = floor(p)
            if r.get("ok"):
                plates[p] = r
                log["floor_used"] += 1
    log["still_failed"] = sum(1 for p in failed if not plates[p].get("ok"))
    return log


# 2026-10-17: info_floor (v15_gate, unchanged) held stories on frames late
# in the video (t~23-28 s of 30 s). Mapping every hit in live_20261017_*
# to its shot: the std~18.0 / edge~1.5 hits are all PROCEDURAL-tier shots
# (B7/B8 PAYOFF, B1 HOOK -- see recover_failed_plates); the rest are real
# plates that were already below the floor before render, measured the way
# the gate measures a frame: _are_webb_s_farthest_galaxies B6_S2 / B7_S1 /
# B7_S2 plate edge 1.61 / 1.37 / 1.43 (gate t~23.8/25.8/27.8), _that_bullet_
# crack B4_S1 / B4_S2 / B6_S1 1.24 / 1.69 / 1.33 (t~14.1/16.6/27.4), _a_
# planet_beyond B5_S1 / B6_S2 / B7_S2 1.87 / 1.66 / 1.40 -- near-black
# paintings (mean luma 13-30/255) the plate judge passed. Nothing measured
# a plate before render, so they shipped. Now a plate under the gate floor
# is regenerated with low_information steering inside the normal regen
# rounds; a take that fails the judge never replaces a judge-passed plate.
# Margin 1.0: plates at edge 2.25-2.52 cleared the gate in those renders
# (1.1 would flag 92/400 recent cache plates instead of 62/400).
PLATE_INFO_MARGIN = 1.0


def plate_low_information(path) -> dict | None:
    """The gate's frame_information on the plate as the 9:16 frame shows
    it (cover crop, 270x480); the metrics if under the floor x margin."""
    import io

    from PIL import Image

    from engine.v15_gate import FLOOR_EDGE, FLOOR_STD, frame_information
    try:
        im = Image.open(path).convert("RGB")
    except Exception:  # noqa: BLE001 -- unreadable: plate QA's business
        return None
    w, h = im.size
    if w * 16 > h * 9:                       # too wide: crop the sides
        cw = h * 9 // 16
        im = im.crop(((w - cw) // 2, 0, (w - cw) // 2 + cw, h))
    elif w * 16 < h * 9:
        ch = w * 16 // 9
        im = im.crop((0, (h - ch) // 2, w, (h - ch) // 2 + ch))
    buf = io.BytesIO()
    im.resize((270, 480)).save(buf, "PNG")
    buf.seek(0)
    m = frame_information(buf)
    if (m["std"] < FLOOR_STD * PLATE_INFO_MARGIN
            or m["edge"] < FLOOR_EDGE * PLATE_INFO_MARGIN):
        return m
    return None


_COPY_FIELDS = ("headline", "number", "label", "steps")


def drop_unfixable_shots(shots: list, failing: set, max_hold: dict) -> tuple:
    """-> (shots, log). Removes a shot whose ONLY plate is in `failing` when:
    it is a plain plate shot (not the hook, no on-screen copy), an adjacent
    shot of the same beat uses only passing plates, and that neighbour
    extended over the dropped span stays <= max_hold[beat] (the beat's own
    editorial hold ceiling, beat_max_hold). Otherwise the shot is kept and
    the plate stays qa_fail (the gate then FAILs, as before)."""
    out, log = list(shots), []
    k = 0
    while k < len(out):
        s = out[k]
        sh = s["shot"]
        if not (set(s["prompts"]) & failing) or s.get("hook") \
                or sh.get("kind") != "plate" or len(s["prompts"]) != 1 \
                or any(sh.get(f) for f in _COPY_FIELDS):
            k += 1
            continue
        bid = s["beat"]["beat_id"]
        cap = float(max_hold.get(bid) or 0.0)
        best = None
        for j in (k - 1, k + 1):
            if not 0 <= j < len(out):
                continue
            n = out[j]
            if n["beat"]["beat_id"] != bid or set(n["prompts"]) & failing:
                continue
            merged = (n["t1"] - n["t0"]) + (s["t1"] - s["t0"])
            if merged <= cap + 1e-6 and (best is None or merged < best[1]):
                best = (j, merged)
        if best is None:
            k += 1
            continue
        j, merged = best
        n = dict(out[j])
        if j < k:
            n["t1"] = s["t1"]
        else:
            n["t0"] = s["t0"]
        out[j] = n
        log.append({"dropped": f"{bid}_S{s['idx'] + 1}",
                    "covered_by": f"{bid}_S{n['idx'] + 1}",
                    "merged_s": round(merged, 2), "cap_s": round(cap, 2)})
        del out[k]
        k = max(0, k - 1)
    # re-number shots within each beat (scene keys B#_S# stay contiguous)
    per_beat: dict = {}
    for i, s in enumerate(out):
        bid = s["beat"]["beat_id"]
        idx = per_beat.get(bid, 0)
        per_beat[bid] = idx + 1
        if s["idx"] != idx:
            out[i] = dict(s, idx=idx)
    return out, log


def _seed(prompt: str, salt: int = 0) -> int:
    from src.providers.image_gen import deterministic_seed
    return deterministic_seed(prompt, salt)


# --------------------------------------------------------------- pipeline --

def run_pipeline(story_dir: Path, work: Path, *, backend: str = "auto",
                 use_llm: bool = True, use_judge: bool = True,
                 plate_qa_on: bool = True) -> dict:
    t_start = time.time()
    story_dir, work = Path(story_dir), Path(work)
    if story_dir.name == "story.json":
        story_dir = story_dir.parent
    (work / "scenes").mkdir(parents=True, exist_ok=True)
    story = json.loads((story_dir / "story.json").read_text())
    sid = story["story_id"]
    bible = load_style(story_dir, story)
    report: dict = {"story_id": sid, "pipeline": "v15",
                    "deck": bible.get("deck"), "warnings": [], "timings": {},
                    "costs": {"llm_calls": 0, "image_calls": 0,
                              "vision_calls": 0}}

    # 1. narration audio (voice layer: ONE voice for the whole video, lexicon,
    #    round-trip QA) + measured word timing
    from engine.voice import synthesize_video
    vo = synthesize_video(story_dir, story["beats"])
    report["voice"] = vo["voice"]
    tts, timing = {}, {}
    for b in story["beats"]:
        res = vo["beats"][b["beat_id"]]
        tts[b["beat_id"]] = float(res["duration"])
        timing[b["beat_id"]] = beat_timing(story_dir / res["file"],
                                           b["narration"])
    report["timing"] = {bid: {"anchored": t["anchored"],
                              "boundaries": t["boundaries"]}
                        for bid, t in timing.items()}

    # decision #13 item 3 / #18 item 2: one reusable identity description
    # for the video's recurring subject — story["concepts"]' busiest entry,
    # or (auto-generated stories, no concepts) derived from title+narration.
    # Built BEFORE the plan so the planner writes about the specific thing.
    from engine.subject_bible import build_subject_bible
    subj_bible = build_subject_bible(story, use_llm=use_llm)
    report["subject_bible"] = subj_bible
    report["costs"]["llm_calls"] += subj_bible.get("llm_calls", 0)

    # 2. Beat Visual Plan
    t0 = time.time()
    bvp = make_plan(story, bible, use_llm=use_llm, subject=subj_bible)
    report["costs"]["llm_calls"] += bvp["llm_calls"]
    report["plan"] = {"source": bvp["source"], "key": bvp["key"],
                      "errors": bvp["errors"][:10]}
    if bvp["source"] == "fallback":
        report["warnings"].append({"warning": "plan_fallback",
                                   "detail": bvp["errors"][:5]})
    # owner review 2026-10-14: copy-free shots stop repeating the
    # headline-room layout (deterministic, seeded by story id)
    from engine.v15_plan import vary_compositions
    report["plan"]["compositions"] = vary_compositions(bvp["plan"], sid)
    (work / "visual_plan.json").write_text(json.dumps(bvp["plan"], indent=1))
    plan_by = {b["beat_id"]: b for b in bvp["plan"]["beats"]}
    report["timings"]["plan_s"] = round(time.time() - t0, 1)

    # 3. shot timeline — editorial rhythm (see HOLD_BY_FUNCTION): per-beat
    #    hold ceiling + seeded split points + per-beat tail, all keyed on
    #    story_id so a re-run reproduces the same cut list.
    shots = []  # flat: {beat, idx, shot, t0, t1, prompts}
    n_beats = len(story["beats"])
    tails = {b["beat_id"]: beat_tail(story["beats"], bi, sid)
             for bi, b in enumerate(story["beats"])}
    report["rhythm"] = {"tails": tails, "max_hold": {}}
    for bi, b in enumerate(story["beats"]):
        hold = beat_max_hold(b, bi, n_beats, sid)
        report["rhythm"]["max_hold"][b["beat_id"]] = hold
        tl = split_long_holds(
            shot_timeline(b, plan_by[b["beat_id"]], timing[b["beat_id"]],
                          tts[b["beat_id"]], tails[b["beat_id"]]),
            timing[b["beat_id"]], max_hold_s=hold, margin_s=split_margin(hold),
            seed=f"{sid}|{b['beat_id']}")
        for k, s in enumerate(tl):
            # frame 0 of the video (HOOK framing, v15_style.HOOK_FRAMING)
            hook = (b is story["beats"][0] and k == 0
                    and s["shot"]["kind"] == "plate")
            if s["shot"]["kind"] == "zoom_through":
                # decision #18 item 8: fit dive levels to the shot's real
                # duration BEFORE prompts exist, so a level that cannot be
                # shown never gets a plate (dry run 6: its plate was still
                # generated and listed in the manifest -> incomplete)
                from engine.v15_shots import _fit_zoom_levels
                lv, _ = _fit_zoom_levels(s["shot"]["levels"], [],
                                         s["t1"] - s["t0"])
                s = dict(s, shot=dict(s["shot"], levels=lv))
            shots.append({"beat": b, "idx": k, **s, "hook": hook,
                          "prompts": _prompts_for(s["shot"], bible, subj_bible,
                                                  hook)})
        if any(s.get("merged") for s in tl):
            report["warnings"].append({"beat": b["beat_id"],
                                       "warning": "short_shot_merged"})

    # 3a. 2026-10-15 review: no two shots may resolve to the IDENTICAL
    #     prompt -- an identical prompt hits the same cached plate, so the
    #     video showed one generated image twice under a different crop/
    #     camera move (levitation render: B9_S2/B9_S3 shared one plate).
    report["prompt_dedup"] = dedupe_shot_prompts(shots, bible, subj_bible)

    # KNOWN FUTURE DIRECTION (2026-10-15 review, deliberately NOT built):
    # every shot is a still plate animated only by a camera move. Shots
    # whose subject itself moves (a levitating droplet, a breaking wave)
    # would need real in-image motion -- a video-generation provider or
    # layered/masked element animation. Separate R&D effort; out of scope
    # for the camera vocabulary in engine.v15_motion.
    # 3b. camera motion for the whole video at once (engine.v15_motion):
    #     seeded by story_id, planner camera kept as intent, no back-to-back
    #     repeats, no family dominating — owner review 2026-10-14
    from engine.v15_motion import describe as describe_motion
    from engine.v15_motion import plan_motion
    motions = plan_motion([
        {"kind": s["shot"]["kind"], "camera": s["shot"].get("camera"),
         "dur": s["t1"] - s["t0"], "hook": s["hook"],
         "derived": bool(s["shot"].get("derived")),
         "copy": bool(s["shot"].get("headline") or s["shot"].get("number")),
         "function": s["beat"].get("function")} for s in shots], sid)
    for s, mo in zip(shots, motions):
        s["motion"] = mo
    report["motion"] = describe_motion(motions)

    # 4. plates (image fallback chain, global cache) + plate QA
    t0 = time.time()
    uniq = sorted({p for s in shots for p in s["prompts"]})
    fail_log: list = []
    report["image_chain"] = image_chain_report()  # WP8/DESIGN §6.2 preflight visibility
    # WP8/DESIGN §6.1: "Pollinations ... never for hero shots" — a prompt is
    # hero when ANY shot using it belongs to a HOOK/PAYOFF beat (the same
    # function field v15_gate.check_assets already treats as the hero
    # signal for asset_tier).
    hero_prompts = {p for s in shots if s["beat"].get("function") in ("HOOK", "PAYOFF")
                    for p in s["prompts"]}
    # decision #13 item 2: first beat whose shot uses this prompt -> its
    # narration, for plate_qa's per-beat narration-match check. A prompt
    # shared across shots (global cache) keeps the first beat that asked
    # for it; the judge call is about catching a misleading image, not
    # about exhaustively re-checking every reuse.
    prompt_narration: dict = {}
    for s in shots:
        for p in s["prompts"]:
            prompt_narration.setdefault(p, s["beat"]["narration"])

    def _cloud_chain(prompt):
        base = (providers_for_beat_function("HOOK") if prompt in hero_prompts
                else PROVIDER_ORDER)
        return tuple(x for x in base if x not in FLOOR_PROVIDERS)

    def _gen(prompt, salt=0, providers=None):
        return prompt, generate_plate(prompt, _seed(prompt, salt), log=fail_log,
                                      providers=providers or _cloud_chain(prompt))

    with ThreadPoolExecutor(max_workers=3) as ex:
        plates = dict(ex.map(_gen, uniq))
    # a plate whose generation failed outright used to go straight to the
    # V14 procedural tier (see recover_failed_plates)
    from src.utils.config import get_config
    report["plate_generation"] = recover_failed_plates(
        plates, [p for s in shots for p in s["prompts"]],
        lambda p: _gen(p)[1],
        hero=hero_prompts,
        floor=lambda p: _gen(p, providers=FLOOR_PROVIDERS)[1],
        floor_cap=int(get_config("image_gen.sdcpp.max_plates_per_video", 3)))
    report["costs"]["image_calls"] += sum(1 for r in plates.values()
                                          if r.get("ok") and not r.get("cached"))
    qa = {"checked": False}
    plate_realistic_by_prompt: dict = {}   # DESIGN §11 disclosure (WP10)
    # B2 (VIS) / decision #18 item 4: a plate QA fail gets up to
    # MAX_PLATE_REGEN regeneration rounds before it ships still flagged
    # (qa_fail, caught by v15_gate's asset_tier check). Each round rebuilds
    # the prompt STEERED by the failure reason (steer_prompt) on the normal
    # production chain (Cloudflare first). The old rotation to "the next
    # model" sent dry run 5's one failing plate to sdcpp_local (1709 s after
    # a gemini 429) and then to pollinations (commercial_ok:false), each
    # time with the identical prompt.
    MAX_PLATE_REGEN = 3
    if plate_qa_on:
        parts_of: dict = {}
        order: list = []     # timeline order: "earlier"/"last" mean something
        for s in shots:
            for p, pt in zip(s["prompts"], _prompt_parts(s["shot"], subj_bible,
                                                         s.get("hook", False))):
                parts_of.setdefault(p, pt)
                if p not in order:
                    order.append(p)
        identity = subj_bible if subj_bible.get("description") else None
        items = [{"path": plates[p]["path"], "subject": parts_of[p]["subject"],
                  "prompt": p, "narration": prompt_narration.get(p)}
                 for p in order if plates[p].get("ok")]
        qa = plate_qa(items, bible.get("illustration_style", ""),
                      work / "plate_sheet.jpg", identity=identity)
        report["costs"]["vision_calls"] += 1
        for i, it in enumerate(items):
            plate_realistic_by_prompt[it["prompt"]] = (qa.get("realistic")
                                                        or {}).get(i)
        reason_of = {items[i]["prompt"]: r
                     for i, r in (qa.get("fail") or {}).items()}
        shows_of = {items[i]["prompt"]: v
                    for i, v in (qa.get("shows") or {}).items()}
        steering: list = []
        # Bug fix (2026-10-10, owner-reported multi-hour stalls): the exact
        # failure mode the MAX_PLATE_REGEN comment above already names from
        # "dry run 5" (one plate landing on sdcpp_local at 1709s) was still
        # reachable on every regen round, not just the initial pass — a QA
        # rejection that's compositional (not a provider outage) retries the
        # SAME cloud-then-local chain, so a prompt that fell to local once
        # falls to it again each of the 3 regen rounds: ~1700-1800s x up to
        # 3 rounds x however many plates are still failing, run in parallel
        # but still a multi-hour wall-clock tax for one video. sdcpp_local
        # is 30-90x slower than every other provider (cloudflare/pollinations
        # land in 10-50s); regen rounds now skip straight from gemini_image
        # to pollinations instead of waiting on local each time. The initial
        # generation pass (_gen above) is untouched and still tries local.
        REGEN_PROVIDER_ORDER = tuple(
            p for p in PROVIDER_ORDER if p != "sdcpp_local")

        beat_views: dict = {}
        beat_of_prompt: dict = {}
        for s in shots:
            bid = s["beat"]["beat_id"]
            beat_views.setdefault(bid, set()).add(s["shot"].get("view"))
            for p in s["prompts"]:
                beat_of_prompt.setdefault(p, bid)

        def _providers(p):
            if p in hero_prompts:
                return tuple(x for x in providers_for_beat_function("HOOK")
                             if x != "sdcpp_local")
            return REGEN_PROVIDER_ORDER

        def _redo(p, rnd):
            sp = steer_prompt(bible, parts_of[p], reason_of.get(p), rnd,
                              identity, prompt_narration.get(p))
            return p, sp, generate_plate(sp, _seed(sp, rnd), log=fail_log,
                                         providers=_providers(p))

        # judge-passed plates too dark/flat for the info floor (see
        # plate_low_information): regenerated in the same rounds, but kept
        # as they are if no better take passes the judge
        info_only: set = set()
        low_info_log: dict = {}

        def _ik(p):
            return f"{order.index(p)}: {parts_of[p]['subject'][:60]}"
        for p in order:
            if p in reason_of or not plates[p].get("ok"):
                continue
            m = plate_low_information(plates[p]["path"])
            if m:
                reason_of[p] = "low_information"
                info_only.add(p)
                low_info_log[_ik(p)] = {"on_file": m}
        still = set(reason_of)
        regenerated_total, rounds = 0, 0
        while still and rounds < MAX_PLATE_REGEN:
            rounds += 1
            regen = [p for p in order if p in still]
            with ThreadPoolExecutor(max_workers=3) as ex:
                res = list(ex.map(lambda p: _redo(p, rounds), regen))
            report["costs"]["image_calls"] += sum(
                1 for _, _, r in res if r.get("ok") and not r.get("cached"))
            for p, sp, r in res:
                steering.append({"round": rounds, "reason": reason_of.get(p),
                                 "shows": shows_of.get(p),
                                 "subject": parts_of[p]["subject"][:90],
                                 "provider": r.get("provider"),
                                 "seconds": r.get("seconds")})
            ok_redo = {p: r for p, _, r in res if r.get("ok")}
            qa_round = plate_qa(
                [{"path": r["path"], "subject": parts_of[p]["subject"],
                  "narration": prompt_narration.get(p)}
                 for p, r in ok_redo.items()],
                bible.get("illustration_style", ""),
                work / f"plate_sheet_regen{rounds}.jpg",
                identity=identity) if ok_redo else {}
            report["costs"]["vision_calls"] += 1 if ok_redo else 0
            regenerated_total += len(regen)
            next_still = set()
            for j, (p, r) in enumerate(ok_redo.items()):
                judged_bad = j in (qa_round.get("fail") or {})  # incl. OCR
                if p in info_only and judged_bad:
                    # the plate on file passed the judge; a take that fails
                    # it never replaces it -- try again next round
                    next_still.add(p)
                    continue
                low = None if judged_bad else plate_low_information(r["path"])
                if p in info_only and low:
                    prev = low_info_log.get(_ik(p), {}).get("on_file") or {}
                    next_still.add(p)
                    low_info_log.setdefault(_ik(p), {})[f"round{rounds}"] = low
                    if low["edge"] <= prev.get("edge", 0):
                        continue             # no better than what is on file
                    low_info_log[_ik(p)]["on_file"] = low
                plates[p] = r  # regenerated plate replaces the failed one
                plate_realistic_by_prompt[p] = (qa_round.get("realistic")
                                                or {}).get(j)
                if judged_bad:
                    next_still.add(p)
                    reason_of[p] = qa_round["fail"][j]
                    shows_of[p] = (qa_round.get("shows") or {}).get(j)
                elif low and p not in info_only:
                    # content fixed, but too dark/flat to clear the floor
                    next_still.add(p)
                    reason_of[p] = "low_information"
                    info_only.add(p)
                    low_info_log.setdefault(_ik(p), {})["on_file"] = low
                elif p in info_only:
                    low_info_log.setdefault(_ik(p), {})["fixed_round"] = rounds
            for p in regen:
                if p not in ok_redo:
                    next_still.add(p)
            still = next_still
            qa["regenerated"] = regenerated_total
            qa["regen_rounds"] = rounds
            qa["still_failing"] = sorted(x[:100] for x in still)
            qa["second_check"] = bool(qa_round.get("checked"))
        # a judge-passed plate that is only too dark is not a QA failure: it
        # ships as it is (the gate's info_floor still measures the frame)
        info_left = still & info_only
        still -= info_left
        if low_info_log:
            qa["low_information"] = {"flagged": len(low_info_log),
                                     "left": len(info_left),
                                     "plates": low_info_log}
        qa["still_failing"] = sorted(x[:100] for x in still)
        # last resort 1: narration-led RESUBJECT, RESUBJECT_VARIANTS seeds/
        # views per plate judged in ONE plate QA call; first passing wins.
        resub = [p for p in order if p in still
                 and reason_of.get(p) in RESUBJECT_REASONS
                 and prompt_narration.get(p)]
        if resub:
            def _resub(job):
                p, k = job
                sp, subj = resubject_prompt(
                    bible, prompt_narration[p], identity,
                    beat_views.get(beat_of_prompt.get(p), ()), variant=k)
                return p, k, subj, generate_plate(
                    sp, _seed(sp, MAX_PLATE_REGEN + 1 + k), log=fail_log,
                    providers=_providers(p))
            jobs = [(p, k) for p in resub for k in range(RESUBJECT_VARIANTS)]
            with ThreadPoolExecutor(max_workers=3) as ex:
                res = list(ex.map(_resub, jobs))
            report["costs"]["image_calls"] += sum(
                1 for *_, r in res if r.get("ok") and not r.get("cached"))
            ok_res = [x for x in res if x[3].get("ok")]
            qa_r = plate_qa(
                [{"path": r["path"], "subject": subj,
                  "narration": prompt_narration[p]} for p, _, subj, r in ok_res],
                bible.get("illustration_style", ""),
                work / "plate_sheet_resubject.jpg",
                identity=identity) if ok_res else {}
            report["costs"]["vision_calls"] += 1 if ok_res else 0
            fixed = set()
            for j, (p, k, subj, r) in enumerate(ok_res):
                passed = bool(qa_r.get("checked")) and \
                    j not in (qa_r.get("fail") or {})
                steering.append({"round": "resubject", "variant": k,
                                 "reason": reason_of.get(p),
                                 "subject": subj[:90], "passed": passed,
                                 "shows": (qa_r.get("shows") or {}).get(j),
                                 "provider": r.get("provider"),
                                 "seconds": r.get("seconds")})
                if passed and p not in fixed:
                    fixed.add(p)
                    plates[p] = r
                    plate_realistic_by_prompt[p] = (qa_r.get("realistic")
                                                    or {}).get(j)
            still -= fixed
            qa["resubject"] = {"tried": len(resub), "fixed": len(fixed)}
            qa["still_failing"] = sorted(x[:100] for x in still)
        qa["steering"] = steering
        # last resort 2: drop a still-failing shot a sibling can cover
        if still:
            shots, dropped = drop_unfixable_shots(
                shots, still, report["rhythm"]["max_hold"])
            if dropped:
                used = {p for s in shots for p in s["prompts"]}
                for p in still - used:
                    plates.pop(p, None)      # never shown -> not shipped
                    plate_realistic_by_prompt.pop(p, None)
                still &= used
                qa["dropped_shots"] = dropped
                qa["still_failing"] = sorted(x[:100] for x in still)
        for p in still:
            plates[p] = dict(plates[p], qa_fail=True)
    report["plate_qa"] = {k: qa.get(k) for k in
                          ("checked", "ocr_checked", "fail", "ocr_hits",
                           "regenerated", "regen_rounds", "still_failing",
                           "second_check", "reason", "steering",
                           "resubject", "dropped_shots", "low_information")}
    # final prompt -> path map, AFTER any regeneration replaced a path;
    # None (unknown/unanswered) is kept as None, never defaulted here —
    # engine.v16_manifest treats None conservatively (assume realistic).
    report["plate_realistic"] = {
        plates[p]["path"]: v for p, v in plate_realistic_by_prompt.items()
        if plates.get(p, {}).get("ok")}
    # Owner directive (2026-10-12): the YouTube thumbnail needs a clean,
    # caption-free image — the raw hook plate (same "scroll-stopping" art
    # engine.v15_style.HOOK_FRAMING already optimises for), not a frame
    # grabbed from the finished video, which always has captions burned
    # in and produced double/overlapping text on the thumbnail.
    hook_shot = next((s for s in shots if s.get("hook")), None)
    if hook_shot and hook_shot.get("prompts"):
        hp = plates.get(hook_shot["prompts"][0], {})
        if hp.get("ok"):
            report["hook_plate_path"] = hp["path"]
        # the hook shot's own planner-written headline ("NO ROCKETS, JUST A
        # CABLE?") is a curiosity-gap question, punchier thumbnail text
        # than the SEO title -- same text already shown on-screen as the
        # video's own hook caption, so the thumbnail doesn't promise
        # something the video itself doesn't open with. Read from the
        # finalized plan's first shot directly, not hook_shot["shot"]:
        # split_long_holds can turn the hook into a punch-in CUT pair for a
        # long first beat, and whichever piece keeps the "hook" flag isn't
        # guaranteed to be shots[0] from the plan (verified missing on
        # t_life_ignored_earth_s_most_common_element's B1).
        hl = (bvp["plan"]["beats"][0]["shots"][0].get("headline")
              if bvp["plan"]["beats"] and bvp["plan"]["beats"][0].get("shots")
              else None)
        if hl:
            report["hook_headline"] = hl
    if not plate_qa_on:
        report["plate_qa"]["reason"] = "plate QA disabled (--no-plate-qa)"
    report["plate_failures"] = fail_log
    providers = {}
    for r in plates.values():
        if r.get("ok"):
            providers[r["provider"]] = providers.get(r["provider"], 0) + 1
    report["plate_providers"] = providers
    info = {}
    for p, r in plates.items():
        if r.get("ok"):
            info[p] = analyze_subject(r["path"])
    report["timings"]["plates_s"] = round(time.time() - t0, 1)

    # 5. shot grammars -> Scene IR
    specs, events, meta = {}, {}, {}
    for s in shots:
        b = s["beat"]
        scene_id = f"{sid}_{b['beat_id']}_S{s['idx'] + 1}"
        dur = round(s["t1"] - s["t0"], 3)
        wts = [w["t0"] for w in timing[b["beat_id"]]["words"]]
        base = s["t0"]

        def t_of(word, _w=wts, _b=base, _d=dur):
            t = LEAD_S + _w[min(max(0, int(word)), len(_w) - 1)] - _b
            return round(min(max(t, 0.15), max(0.2, _d - 0.35)), 3)

        pl = [({"path": plates[p]["path"], "info": info.get(p)}
               if plates.get(p, {}).get("ok") else None) for p in s["prompts"]]
        res = compile_shot({"scene_id": scene_id, "duration": dur,
                            "shot": s["shot"], "plates": pl, "t_of": t_of,
                            "first": b is story["beats"][0] and s["idx"] == 0,
                            "motion": s.get("motion")},
                           bible)
        ok, errs = validate_scene_spec(res["spec"])
        if not ok:
            raise ValueError(f"{scene_id} invalid Scene IR: {errs[:3]}")
        key = f"{b['beat_id']}_S{s['idx'] + 1}"
        specs[key] = res["spec"]
        events[key] = res["events"]
        meta[key] = {"beat": b["beat_id"], "t0": s["t0"], "dur": dur,
                     "kind": s["shot"]["kind"], "tier": res["asset_tier"],
                     "view": s["shot"].get("view"),
                     "camera": res["spec"].get("camera", {}).get("type"),
                     "move": (s.get("motion") or {}).get("move"),
                     "qa_fail": any(plates.get(p, {}).get("qa_fail")
                                    for p in s["prompts"]),
                     "function": b.get("function")}
        (work / "scenes" / f"{key}.spec.json").write_text(
            json.dumps(res["spec"], indent=1))

    # 5b. 2026-10-15 review: SFX only fired on text-overlay events, so long
    #     copy-free stretches were silent (40 s with no SFX on the
    #     levitation render) and the payoff had no accent.
    report["sfx_fill"] = fill_sfx_gaps(meta, events)

    # 6. §24 keys + §25 production plan + render
    t0 = time.time()
    index = load_index(work)
    scene_inputs, backends = {}, {}
    for key, spec in specs.items():
        be, reason = select_backend(spec, backend)
        from engine.asset_pipeline import stage_assets
        from engine.scene_renderer import RENDER_PROJECT
        staged, _ = stage_assets(spec, RENDER_PROJECT / "public")
        k = scene_cache_key(spec_hash(compile_spec(staged)), style_hash(bible),
                            be.name, str(be.capabilities()["version"]),
                            RENDER_CONFIG)
        scene_inputs[key] = {"key": k,
                             "output": str(work / "scenes" / f"{key}.mp4")}
        backends[key] = (be, reason)
    captions, narr, beds = {}, {}, {}
    first_shot = {}
    for key, m in meta.items():
        first_shot.setdefault(m["beat"], key)
    for b in story["beats"]:
        bid = b["beat_id"]
        captions[first_shot[bid]] = caption_cues(
            timing[bid], LEAD_S, end=LEAD_S + tts[bid] + tails[bid])
    from engine import captions as _caps
    # caption geometry/size is part of the composite's identity (2026-10-15
    # caption move/resize must not reuse an old cached composite)
    cap_h = caption_plan_hash({"c": captions, "e": events,
                               "style": [V15_CAPTION_TOP, _caps.KIN_CAP_H,
                                         _caps.BASE_SIZE]}, bible)
    nar_h = narration_plan_hash({b["beat_id"]: b["narration"]
                                 for b in story["beats"]})

    # V16 (WP9): mood-tagged music selected from the story arc (per-shot
    # "function" weighted by duration), library SFX, and the WP6 brand
    # sting — each with a load-bearing fallback to the existing procedural
    # bed/SFX when the on-disk library has nothing for a mood/kind.
    from engine.v16_audio import load_sfx_library, select_music_for_story
    from engine import brand as brand_mod
    music_sel = select_music_for_story(
        [m["function"] for m in meta.values()],
        [m["dur"] for m in meta.values()], REPO / "assets" / "music",
        seed=sid)
    sfx_lib = load_sfx_library(REPO / "assets" / "sfx")
    audio_brand = brand_mod.load_brand()
    sting_path = work / "sting.wav"
    brand_mod.sting_audio(sting_path, audio_brand)
    report["audio_v16"] = {"mood": music_sel["mood"],
                           "mood_weights": music_sel["weights"],
                           "track": (str(music_sel["track"]["path"])
                                     if music_sel["track"] else None),
                           "sfx_kinds": sorted(sfx_lib.keys())}

    bed_h = bed_plan_hash({
        "intensity": {k: INTENSITY.get(m["function"], 0.6)
                      for k, m in meta.items()},
        "track": report["audio_v16"]["track"],
        "sfx": {k: str(v["path"]) for k, v in sfx_lib.items()},
        "brand_sting": {"version": audio_brand.get("version"),
                        "sting": audio_brand.get("sting"),
                        "gain": STING_GAIN}})
    out_final = work / "final.mp4"
    plan = plan_production(index, scene_inputs, cap_h, nar_h, bed_h, out_final)
    report["production"] = {k: plan[k] for k in ("render", "reuse", "reasons",
                                                 "rebuild_audio",
                                                 "rebuild_composite")}
    render_s = {}
    for key in plan["render"]:
        be = backends[key][0]
        tr = time.time()
        res = be.render(specs[key], scene_inputs[key]["output"],
                        concurrency=RENDER_CONFIG["concurrency"])
        if not res.get("ok"):
            raise RuntimeError(f"{key} render failed: {str(res)[:400]}")
        record_scene(index, scene_inputs[key]["key"], key,
                     Path(scene_inputs[key]["output"]),
                     float(specs[key]["duration_s"]))
        render_s[key] = round(time.time() - tr, 1)
        save_index(work, index)
    report["render_seconds"] = render_s
    report["timings"]["render_s"] = round(time.time() - t0, 1)

    # 7. assembly: captions AFTER composition + audio + mux
    t0 = time.time()
    arep = {}
    if plan["rebuild_composite"]:
        scenes = []
        beat_of = {b["beat_id"]: b for b in story["beats"]}
        for key, m in meta.items():
            bid = m["beat"]
            sc = {"scene_id": key, "video": scene_inputs[key]["output"],
                  "intensity": INTENSITY.get(m["function"], 0.6),
                  "sfx": list(events.get(key) or [])}
            if first_shot[bid] == key:
                beat_dur = LEAD_S + tts[bid] + tails[bid]
                sc["captions"] = captions[key]
                sc["narration"] = {"beat_id": bid,
                                   "text": beat_of[bid]["narration"],
                                   "offset": LEAD_S, "span_s": beat_dur}
            scenes.append(sc)
        from engine.v15_shots import lighten
        cap_bible = json.loads(json.dumps(bible))  # readable active word
        cap_bible["palette"]["accent"] = lighten(bible["palette"]["accent"],
                                                 165.0)
        music_dict = {"track": music_sel["track"]["path"], "gain": 0.16} \
            if music_sel["track"] else {"gain": 0.9}
        arep = assemble({"story_id": sid, "story_dir": str(story_dir),
                         "bible": cap_bible, "scenes": scenes,
                         "music": music_dict, "sfx_library": sfx_lib,
                         "sting_audio": str(sting_path),
                         "sting_gain": STING_GAIN,
                         "single_pass": True,
                         "caption_top": V15_CAPTION_TOP,
                         "out": str(out_final)}, work)
        (work / "assembly_report.json").write_text(json.dumps(arep, indent=1))
        record_assembly(index, plan["assembly_key"], out_final, cap_h, nar_h,
                        bed_h)
        save_index(work, index)
    report["timings"]["assembly_s"] = round(time.time() - t0, 1)
    # manifest_rows computed unconditionally (not just on a fresh composite
    # rebuild): `events` (step 5) carries every shot's sfx kinds regardless
    # of the render/assembly cache state, so a cache-hit run still gets a
    # complete audio asset list for the manifest (WP10).
    kinds_used = {ev["kind"] for evs in events.values() for ev in (evs or [])}
    from engine.v16_audio import manifest_rows
    report["audio_v16"]["manifest_rows"] = manifest_rows(
        music_sel["track"], {k: v for k, v in sfx_lib.items() if k in kinds_used},
        sting_path)

    # 8. gate (recomputed from artifacts; composite cache hit gated alike)
    #    + WP10: distinctness + §10.2 scorecard, + the license manifest.
    from engine.v16_gate import run_gate
    from engine.v16_manifest import (build_manifest, check_manifest_complete,
                                     llm_calls_since, load_distinctness_history,
                                     record_distinctness)
    t0 = time.time()
    history = load_distinctness_history()
    gate = run_gate(work, story, meta, specs, timing, captions, LEAD_S,
                    use_judge=use_judge, plate_qa=report["plate_qa"],
                    voice=report["voice"], brand=audio_brand,
                    plates=plates, sting_present=sting_path.exists(),
                    video_id=sid, history=history)
    report["costs"]["vision_calls"] += gate.get("judge_calls", 0)
    report["gate"] = gate
    report["publish_gate"] = gate["verdict"]
    report["timings"]["gate_s"] = round(time.time() - t0, 1)
    report["shots"] = meta

    # manifest (DESIGN §11, WP10): built from the same provenance the gate
    # just checked, saved regardless of verdict (a HOLD/FAIL still needs an
    # explainable manifest) and cross-checked against the render asset log.
    from engine.v15_gate import _plate_paths
    plate_paths_used = _plate_paths(specs)
    # B5 (VIS): title/description/tags via a real LLM call (cached by story
    # content; falls through to a deterministic story-fields metadata floor
    # on an adapter outage, same convention as the plan/plate-QA calls above).
    from engine.v16_metadata import build_metadata
    metadata = build_metadata(story, use_llm=use_llm)
    report["costs"]["llm_calls"] += metadata.get("llm_calls", 0)
    report["metadata"] = metadata
    manifest = build_manifest(
        video_id=sid, brand=audio_brand, voice=report["voice"], plates=plates,
        plate_realistic=report.get("plate_realistic"),
        audio_rows=report["audio_v16"].get("manifest_rows") or [],
        llm_calls=llm_calls_since(t_start, time.time()), verdict=gate["verdict"],
        metadata=metadata)
    manifest["completeness"] = check_manifest_complete(
        manifest, plate_paths=plate_paths_used, voice_wav=work / "voice.wav",
        audio_rows=report["audio_v16"].get("manifest_rows") or [])
    manifest_dir = ROOT / "build" / "v16" / sid
    manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = manifest_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=1))
    (work / "manifest.json").write_text(json.dumps(manifest, indent=1))
    report["manifest_path"] = str(manifest_path)
    report["manifest"] = manifest
    record_distinctness({
        "video_id": sid,
        "signature": gate["checks"]["distinctness"]["signature"],
        "signature_v2": gate["checks"]["distinctness"].get("signature_v2"),
        "plate_hashes": gate["checks"]["distinctness"]["plate_hashes"]})

    report["timings"]["total_s"] = round(time.time() - t_start, 1)
    (work / "pipeline_report.json").write_text(json.dumps(report, indent=1))
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description="V15 autonomous production")
    ap.add_argument("--story", required=True)
    ap.add_argument("--work", required=True)
    ap.add_argument("--backend", default="auto")
    ap.add_argument("--no-llm", action="store_true")
    ap.add_argument("--no-judge", action="store_true")
    ap.add_argument("--no-plate-qa", action="store_true")
    a = ap.parse_args()
    rep = run_pipeline(Path(a.story), Path(a.work), backend=a.backend,
                       use_llm=not a.no_llm, use_judge=not a.no_judge,
                       plate_qa_on=not a.no_plate_qa)
    print(json.dumps({k: rep.get(k) for k in
                      ("story_id", "deck", "plan", "plate_providers",
                       "plate_qa", "timings", "costs", "publish_gate")},
                     indent=1))
    print(json.dumps(rep["gate"].get("failures"), indent=1))
    return 0 if rep["publish_gate"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
