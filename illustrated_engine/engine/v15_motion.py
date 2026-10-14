"""V15 — camera motion vocabulary + seeded, non-repeating per-shot assignment.

Owner review 2026-10-14 ("feels AI generated", item 2): every clip used the
same zoom. Measured on the 11 batch renders of 2026-10-13/14 (246 shots):

  - 68% of shots (167/246) rendered as push_in, runs of 4-6 in a row; the
    planner LLM asked for push_in on 45% of shots and every derived
    punch-in split (39% of shots) was hard-wired to another push-in;
  - every push_in was the identical track (scale 1.0 -> 1.15, the same
    ease_in_out_cubic), every pan the identical +-90 px;
  - the plate layer sits at depth 0.35, so SceneComposition/FallbackRenderer
    apply the camera at pf = 0.3 + 0.7 * 0.35 = 0.545: that "1.15" push-in
    reached the picture as ~1.08 and a "+-90 px" pan as ~+-49 px on a
    1080 px frame — the little variety there was did not read on screen;
  - ease_in_out_cubic on every shot = the camera comes to a dead stop
    before EVERY cut (start-from-rest, stop, cut, start-from-rest), the
    signature rhythm of an automated slideshow.

This module owns the decision. `plan_motion()` walks the video's shots in
timeline order and picks a move per shot from a wider vocabulary (zoom in /
out, push-while-panning, pull-while-panning, lateral pan, vertical
rise/descend, diagonal drift, an impact "settle" for the hook/figure shots,
a near-locked "hold" for short lines), each with its own easing and speed:

  - the planner's camera choice is honoured as INTENT (heaviest weight),
    never as a mandate;
  - the exact same move never repeats back-to-back, the same motion
    FAMILY (zoom-in / zoom-out / lateral / vertical / diagonal / hold) is
    penalised right after itself, and a family over ~1/3 of the shots so
    far is damped;
  - every choice is drawn from sha256(story_id, shot index, ...) — DESIGN
    §8.1 "ties are broken by hashing story_id, never by a random choice":
    the same story always gets the same moves, different stories differ.

`camera_for_motion()` turns a motion dict into a Scene IR camera track with
magnitudes sized for what reaches the screen (pf above), speed tied to the
shot's duration (roughly constant velocity, not a fixed end scale), and
every keyframe clamped so the overscanned plate edge never enters frame.
Only Scene IR camera types and easings that both renderers already support
are emitted — no renderer change.
"""
from __future__ import annotations

import hashlib

from engine.grammars.base import WORLD_H, WORLD_W, camera_track

# keep in step with engine.v15_shots (imported lazily there to avoid a cycle)
OVERSCAN = 1.12
BG_DEPTH, SUBJ_DEPTH = 0.35, 0.6
EDGE_GUARD_PX = 6.0

# move -> (family, Scene IR camera type, semantic purpose)
MOVES = {
    "push_in": ("zoom_in", "push_in",
                "push toward the subject the narration names"),
    "push_pan": ("zoom_in", "push_in",
                 "push in while sliding across to the subject"),
    "pull_out": ("zoom_out", "pull_out",
                 "pull back from the detail to reveal its context"),
    "pull_pan": ("zoom_out", "pull_out",
                 "pull back while sliding away to reveal the surroundings"),
    "settle": ("zoom_out", "pull_out",
               "land hard on the image, then settle while the line lands"),
    "pan_left": ("lateral", "pan", "travel across the scene"),
    "pan_right": ("lateral", "pan", "travel across the scene"),
    "rise": ("vertical", "travel", "rise up the structure"),
    "descend": ("vertical", "travel", "move down through the structure"),
    "drift": ("diagonal", "travel", "drift across the scene at an angle"),
    "hold": ("hold", "static", "hold almost still and let the line land"),
}
FAMILY = {m: v[0] for m, v in MOVES.items()}

# planner camera (v15_plan.CAMERAS, plus the pipeline's derived "punch_in")
# -> moves that honour that intent
INTENT = {
    "push_in": ("push_in", "push_pan", "drift"),
    "pull_out": ("pull_out", "pull_pan", "rise"),
    "pan_left": ("pan_left", "push_pan", "drift"),
    "pan_right": ("pan_right", "push_pan", "drift"),
    "rise": ("rise", "drift", "pull_out"),
    "descend": ("descend", "drift", "push_in"),
    "punch_in": ("push_in", "drift", "hold", "pan_left", "pan_right"),
}
EXACT_W, INTENT_W, BASE_W = 3.0, 1.8, 1.0
SAME_FAMILY_PREV = 0.3       # right after the same family
SAME_FAMILY_PREV2 = 0.65     # two shots after it
FAMILY_SHARE_CAP = 0.34      # damp a family above ~1/3 of the shots so far
FAMILY_SHARE_DAMP = 0.35
HOLD_MAX_DUR_S = 2.8         # a near-locked frame only on a short shot
HOLD_GAP = 5                 # ... and not more than once per 5 shots
EASINGS = (("linear", 0.45), ("ease_out_cubic", 0.35),
           ("ease_in_out_cubic", 0.20))
CAMERA_KINDS = ("plate", "process")   # zoom_through keeps its scale_dive
# frame 0 must move with energy toward/around the subject (scroll stop) —
# never a slow vertical travel or a held frame
HOOK_MOVES = ("settle", "push_in", "push_pan", "drift", "pull_out")


def _unit(*parts) -> float:
    h = hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()
    return int(h[:12], 16) / float(16 ** 12)


def _weighted(options: list, u: float):
    """options [(value, weight>0)] -> value at cumulative fraction u."""
    total = sum(w for _, w in options)
    acc = 0.0
    for v, w in options:
        acc += w / total
        if u < acc:
            return v
    return options[-1][0]


def plan_motion(items: list, seed: str) -> list:
    """items (timeline order): {kind, camera?, dur, hook?, derived?, copy?,
    function?} -> one motion dict {move, easing, amount} per item, or None
    for shot kinds whose camera is not a free choice (zoom_through)."""
    out: list = []
    hist: list = []          # families of the camera-moving shots so far
    last_move = None
    last_hold = -99
    for i, it in enumerate(items):
        if it.get("kind") not in CAMERA_KINDS:
            out.append(None)
            continue
        dur = float(it.get("dur", 2.0))
        intent = it.get("camera") or ("punch_in" if it.get("derived")
                                      else "push_in")
        fav = INTENT.get(intent, INTENT["push_in"])
        hook = bool(it.get("hook"))
        n = len(hist)
        opts = []
        for m in MOVES:
            if m == last_move:
                continue                       # never the same move twice
            if hook and m not in HOOK_MOVES:
                continue
            if m == "hold" and (dur > HOLD_MAX_DUR_S
                                or n - last_hold < HOLD_GAP):
                continue
            if m == "settle" and not (hook or it.get("copy")):
                continue                       # impact only where text lands
            w = EXACT_W if m == intent else INTENT_W if m in fav else BASE_W
            if hook and m in ("settle", "push_in", "push_pan"):
                w *= 2.0                       # the opener moves with energy
            fam = FAMILY[m]
            if hist and hist[-1] == fam:
                w *= SAME_FAMILY_PREV
            if len(hist) >= 2 and hist[-2] == fam:
                w *= SAME_FAMILY_PREV2
            if n >= 4 and hist.count(fam) / n > FAMILY_SHARE_CAP:
                w *= FAMILY_SHARE_DAMP
            opts.append((m, w))
        move = _weighted(opts, _unit(seed, i, "move"))
        if move == "settle":
            easing = "ease_out_cubic"
        elif move == "hold":
            easing = "linear"
        elif hook:
            easing = "ease_out_cubic"   # starts moving on frame 0
        else:
            easing = _weighted(list(EASINGS), _unit(seed, i, "ease"))
        amount = 0.8 + 0.45 * _unit(seed, i, "amount")
        if (it.get("function") or "").upper() in ("HOOK", "PAYOFF"):
            amount *= 1.1
        sign = 1.0 if _unit(seed, i, "sign") < 0.5 else -1.0
        vsign = 1.0 if _unit(seed, i, "vsign") < 0.5 else -1.0
        out.append({"move": move, "easing": easing,
                    "amount": round(amount, 3), "sx": sign, "sy": vsign})
        if move == "hold":
            last_hold = n
        hist.append(FAMILY[move])
        last_move = move
    return out


# --------------------------------------------------------------- tracks --

def _pf(depth: float) -> float:
    return 0.3 + 0.7 * depth     # SceneComposition / FallbackRenderer §15


def _limits(scale: float) -> tuple:
    """Largest |x|, |y| camera offsets at camera `scale` that keep BOTH
    the overscanned plate layer and its subject band covering the frame."""
    mx = my = float("inf")
    for depth in (BG_DEPTH, SUBJ_DEPTH):
        pf = _pf(depth)
        s = 1.0 + (scale - 1.0) * pf
        mx = min(mx, (OVERSCAN * WORLD_W / 2 - WORLD_W / 2 / s
                      - EDGE_GUARD_PX) / pf)
        my = min(my, (OVERSCAN * WORLD_H / 2 - WORLD_H / 2 / s
                      - EDGE_GUARD_PX) / pf)
    return max(0.0, mx), max(0.0, my)


def _kf(t, scale, x, y, easing):
    lx, ly = _limits(scale)
    return {"t": round(t, 3), "scale": round(scale, 4),
            "x": round(max(-lx, min(lx, x)), 2),
            "y": round(max(-ly, min(ly, y)), 2), "easing": easing}


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def camera_for_motion(motion: dict, dur: float, info: dict | None) -> dict:
    """motion (plan_motion) + shot duration + plate analysis -> Scene IR
    camera track. Magnitudes are in camera units; on the plate they read
    at pf(BG_DEPTH)=0.545 of that."""
    move = motion["move"]
    E = motion.get("easing", "linear")
    a = float(motion.get("amount", 1.0))
    sx, sy = float(motion.get("sx", 1.0)), float(motion.get("sy", 1.0))
    dur = max(0.2, float(dur))
    tx = ty = 0.0
    if info and info.get("centroid"):
        tx = _clamp((info["centroid"][0] - WORLD_W / 2) * 0.35, -160.0, 160.0)
        ty = _clamp((info["centroid"][1] - WORLD_H / 2) * 0.25, -200.0, 200.0)
    # speed ~ constant per second (scaled by `amount`), not a fixed end
    # scale: a 4 s shot travels further than a 1.5 s one at a similar pace
    Z = _clamp(0.10 * a * dur, 0.14, 0.30)        # zoom delta
    X = _clamp(60.0 * a * dur, 85.0, 125.0)       # lateral half-travel
    Y = _clamp(70.0 * a * dur, 100.0, 150.0)      # vertical half-travel
    if move == "push_in":
        k = [_kf(0, 1.0, 0, 0, E), _kf(dur, 1.0 + Z, tx, ty, E)]
    elif move == "pull_out":
        k = [_kf(0, 1.0 + Z, tx, ty, E), _kf(dur, 1.0, 0, 0, E)]
    elif move == "push_pan":
        k = [_kf(0, 1.04, -sx * 0.8 * X, ty * 0.5, E),
             _kf(dur, 1.04 + 0.75 * Z, sx * 0.4 * X + tx * 0.5, ty, E)]
    elif move == "pull_pan":
        k = [_kf(0, 1.04 + 0.75 * Z, sx * 0.4 * X + tx * 0.5, ty, E),
             _kf(dur, 1.04, -sx * 0.8 * X, ty * 0.5, E)]
    elif move in ("pan_left", "pan_right"):
        s = 1.0 if move == "pan_right" else -1.0
        k = [_kf(0, 1.12, -s * X, ty * 0.5, E),
             _kf(dur, 1.13, s * X, ty * 0.5, E)]
    elif move in ("rise", "descend"):
        s = 1.0 if move == "descend" else -1.0
        k = [_kf(0, 1.12, tx * 0.5, -s * Y, E),
             _kf(dur, 1.13, tx * 0.5, s * Y, E)]
    elif move == "drift":
        k = [_kf(0, 1.10, -sx * 0.75 * X, -sy * 0.75 * Y, E),
             _kf(dur, 1.14, sx * 0.75 * X, sy * 0.75 * Y, E)]
    elif move == "settle":
        land = min(0.6, 0.35 * dur)
        zs = max(Z, 0.2)
        k = [_kf(0, 1.0 + zs, tx, ty, "ease_out_cubic"),
             _kf(land, 1.0 + 0.3 * zs, tx * 0.6, ty * 0.6, "linear"),
             _kf(dur, 1.0 + 0.18 * zs, tx * 0.5 + sx * 15, ty * 0.5,
                 "linear")]
    elif move == "hold":
        k = [_kf(0, 1.04, 0, 0, "linear"),
             _kf(dur, 1.065, sx * 18.0, sy * 12.0, "linear")]
    else:
        raise ValueError(f"unknown camera move {move!r}")
    _family, ctype, purpose = MOVES[move]
    return camera_track(ctype, k, purpose)


def describe(motions: list) -> dict:
    """Small summary for the pipeline report: move counts, longest run of
    one move, longest run of one family."""
    seq = [m["move"] for m in motions if m]
    fam = [FAMILY[m] for m in seq]

    def _run(xs):
        best = cur = 0
        for i, x in enumerate(xs):
            cur = cur + 1 if i and xs[i - 1] == x else 1
            best = max(best, cur)
        return best
    counts: dict = {}
    for m in seq:
        counts[m] = counts.get(m, 0) + 1
    return {"moves": counts, "max_move_run": _run(seq),
            "max_family_run": _run(fam), "sequence": seq}
