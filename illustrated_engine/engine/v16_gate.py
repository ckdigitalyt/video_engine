"""V16 — the full DESIGN.md §10 gate (WP10): v15_gate's hard checks, plus the
two pieces DESIGN §10.1 lists that nothing built yet:

  hook          rule-based half of the Hook row (judge's `hook_stops_scroll`
                already lives in v15_gate's `judge` check) — first-word time
                <=0.25s and a headline text box present in the opening shot
  distinctness  template-sequence signature (Levenshtein distance on the
                ordered per-shot `kind` sequence — v16_plan's named
                templates are not wired into v15_pipeline yet, WP7 §9) and
                plate dHash, both compared against a rolling history of up
                to HISTORY_CAP prior videos

...and then, ONLY when every hard gate here passes, the §10.2 weighted
0-100 scorecard (never computed on a HOLD/FAIL — a video that didn't even
clear the hard gates has no honest score to report).

v15_gate.py itself is untouched (same precedent as WP2/WP7: the existing,
tested hard-check functions are not the layer that changes here). This
module wraps it.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image

from engine import v15_gate

ROOT = Path(__file__).resolve().parent.parent

# DESIGN §10.1 Distinctness thresholds.
SIGNATURE_MIN_DISTANCE = 0.3   # two videos closer than this = too similar
DHASH_MAX_REUSE_DISTANCE = 6   # a past plate within this Hamming distance = reused
HISTORY_CAP = 30
HOOK_MAX_FIRST_WORD_S = 0.25

# §10.2 weights (sum to 100).
# 2026-10-24 analytics review (28-day YouTube Analytics vs each upload's
# scorecard): the old weighting (hook 20, story 20, visuals 15, pacing 15,
# captions/audio/brand 10 each) did NOT predict real performance:
# scorecard-vs-retention -0.23 and scorecard-vs-views -0.33. Two of the
# lowest-retention videos scored 81-82 and passed clean, while the best
# subscriber converter scored 63.2. The critic's own dimensions did track
# retention (+0.5 to +0.6 for escalation / emotional_charge / human_voice /
# payoff_clarity), so story (the retention-weighted critic score,
# v16_script.critic_weighted_score) now carries 50 points. Captions, audio
# loudness and brand were near-constant (captions 100 and brand 100 on
# every recorded render; audio 68-76 purely from LUFS -14.6..-14.8 vs a
# -14.0 target). They are pass/fail GATES (SCORE_GATES): a video clears
# each fixed bar or the scorecard HOLDs, and they add no variable points.
SCORE_WEIGHTS = {"story": 50, "hook": 20, "visuals": 15, "pacing": 15}
SCORE_GATES = ("captions", "audio", "brand")
AUDIO_LUFS_TARGET = -14.0
AUDIO_LUFS_TOLERANCE = 1.5     # gate bar: -15.5..-12.5 LUFS (v15_gate hard range is -16.5..-11.5)


# --------------------------------------------------------------- hook --

def check_hook(meta: dict, specs: dict, timing: dict, lead: float,
              judge: dict | None) -> dict:
    """Rule-based half of DESIGN's Hook row. `headline_at_frame0` is a
    simplification (any text box recorded on the opening shot, not a
    frame-accurate visibility check) — the exact-visibility timeline lives
    per-layer in the spec and cross-referencing it is more plumbing than
    this check needs to be useful; flagged, not hidden."""
    first_key = next(iter(meta), None)
    fails = []
    first_word_s = None
    if first_key is not None:
        bid = meta[first_key]["beat"]
        words = (timing.get(bid) or {}).get("words") or []
        if words:
            first_word_s = round(float(lead) + float(words[0]["t0"]), 3)
    if first_word_s is None:
        fails.append("no narration word timing for the opening shot")
    elif first_word_s > HOOK_MAX_FIRST_WORD_S:
        fails.append(f"first word at {first_word_s}s > {HOOK_MAX_FIRST_WORD_S}s")
    headline_present = bool(first_key is not None and
                            (specs.get(first_key, {}).get("meta") or {})
                            .get("text_boxes"))
    if not headline_present:
        fails.append("no headline text box on the opening shot")
    judge = judge or {}
    stops_scroll = judge.get("hook_stops_scroll")
    if stops_scroll is False:
        fails.append("judge: first frame would not stop a scroll")
    return {"ok": not fails, "fails": fails, "first_word_s": first_word_s,
            "headline_at_frame0": headline_present,
            "hook_stops_scroll": stops_scroll,
            "hook_frame_concrete": judge.get("hook_frame_concrete")}


# --------------------------------------------------------- distinctness --

def dhash(path, hash_size: int = 8) -> int:
    """Standard difference hash (stdlib/PIL only, per DESIGN's tool column):
    a (hash_size+1)-wide grayscale thumbnail, 1 bit per horizontal gradient
    step, packed MSB-first into one int."""
    im = Image.open(path).convert("L").resize((hash_size + 1, hash_size),
                                               Image.LANCZOS)
    px = list(im.getdata())
    val = 0
    for row in range(hash_size):
        base = row * (hash_size + 1)
        for col in range(hash_size):
            val = (val << 1) | int(px[base + col] > px[base + col + 1])
    return val


def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def template_signature(meta: dict) -> str:
    """Ordered per-shot `kind` sequence (engine.v15_shots' actual compiled
    kind — what really appeared on screen; v16_plan's named §8 templates
    are proven standalone but not yet wired into v15_pipeline, WP7 §9)."""
    return ",".join(m["kind"] for m in meta.values())


# decision #18 item 5: the kind-only signature above is near-constant for
# this pipeline (v15_plan only emits plate|zoom_through|process, so every
# video is ~95% "plate"): dry run 5 "collided" with a skater video and
# Tunguska at 0.10-0.29 purely because of that. v2 tokens describe the edit
# grammar actually on screen, read from the COMPILED scene specs (so it can
# also be backfilled from any saved scenes/*.spec.json):
#     <shot_kind>/<camera.type>/<overlay classes>
# overlay classes: H headline, L label, N number, S process steps, other
# text boxes by their id's first letter, "-" none. Plate CONTENT is the
# dHash check's job, not this one's.
SIGNATURE_VERSION = 2


def _overlay_class(box_id: str) -> str:
    b = str(box_id).rstrip("0123456789").lower()
    return {"headline": "H", "label": "L", "number": "N",
            "step": "S"}.get(b, (b[:1] or "?").upper())


def shot_token(spec: dict, kind: str | None = None) -> str:
    meta = spec.get("meta") or {}
    k = meta.get("shot_kind") or kind or "?"
    cam = (spec.get("camera") or {}).get("type") or "?"
    ov = "".join(sorted({_overlay_class(t.get("id"))
                         for t in meta.get("text_boxes") or []})) or "-"
    return f"{k}/{cam}/{ov}"


def template_signature_v2(meta: dict, specs: dict) -> str:
    """Ordered per-shot edit-grammar tokens (meta order == timeline)."""
    return ",".join(shot_token(specs.get(key) or {}, m.get("kind"))
                    for key, m in meta.items())


def signature_v2_from_scene_dir(scene_dir) -> str | None:
    """Backfill helper: rebuild a past video's v2 signature from its saved
    scenes/<B#_S#>.spec.json files (timeline order = beat, then shot)."""
    import json
    import re
    rows = []
    for f in Path(scene_dir).glob("B*_S*.spec.json"):
        m = re.match(r"B(\d+)_S(\d+)\.spec\.json$", f.name)
        if m:
            rows.append(((int(m[1]), int(m[2])), f))
    if not rows:
        return None
    return ",".join(shot_token(json.loads(f.read_text()))
                    for _, f in sorted(rows))


def signature_distance(a: str, b: str) -> float:
    """Levenshtein distance on the comma-split token lists, normalised by
    the longer sequence's length -> [0, 1] (0 = identical)."""
    ta, tb = (a.split(",") if a else []), (b.split(",") if b else [])
    n, m = len(ta), len(tb)
    if n == 0 and m == 0:
        return 0.0
    prev = list(range(m + 1))
    for i in range(1, n + 1):
        cur = [i] + [0] * m
        for j in range(1, m + 1):
            cost = 0 if ta[i - 1] == tb[j - 1] else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
        prev = cur
    return prev[m] / max(n, m, 1)


def check_distinctness(video_id: str, meta: dict, plate_paths: list,
                       history: list, specs: dict | None = None) -> dict:
    """`history`: [{"video_id", "signature", "signature_v2"?, "plate_hashes":
    [int, ...]}], already loaded and capped by the caller (pure function,
    no I/O — the gate never writes history itself; see engine.v16_manifest.
    record_distinctness for the one place that does, called once per real
    pipeline run, not on every re-gate).

    decision #18 item 5: with `specs`, sequences are compared on the v2
    edit-grammar signature against every history entry that has one; an
    entry with only the legacy kind-only signature is listed under
    `legacy_uncomparable` (not compared on a measure known to be
    near-constant). Without `specs` the legacy kind-only comparison runs
    exactly as before."""
    sig = template_signature(meta)
    sig2 = template_signature_v2(meta, specs) if specs is not None else None
    hashes = [dhash(p) for p in plate_paths]
    fails, legacy = [], []
    nearest = None
    for h in history:
        if h.get("video_id") == video_id:
            continue
        if sig2 is not None:
            if not h.get("signature_v2"):
                legacy.append(h.get("video_id"))
                d = None
            else:
                d = signature_distance(sig2, h["signature_v2"])
        else:
            d = signature_distance(sig, h.get("signature") or "")
        for ph in h.get("plate_hashes") or []:
            for hh in hashes:
                if hamming(ph, hh) <= DHASH_MAX_REUSE_DISTANCE:
                    fails.append(f"plate near-duplicate of one used in "
                                 f"{h['video_id']} (Hamming {hamming(ph, hh)})")
        if d is None:
            continue
        if nearest is None or d < nearest:
            nearest = d
        if d < SIGNATURE_MIN_DISTANCE:
            fails.append(f"template sequence too close to {h['video_id']} "
                         f"(distance {d:.2f} < {SIGNATURE_MIN_DISTANCE})")
    # decision #13: demoted HOLD -> warning (sample-set is still small
    # enough that near-miss shot/template sequences are common; still
    # logged + scored, no longer HOLD-causing on its own).
    return {"ok": not fails, "fails": sorted(set(fails))[:10],
            "signature": sig, "signature_v2": sig2,
            "signature_version": 2 if sig2 is not None else 1,
            "legacy_uncomparable": legacy, "plate_hashes": hashes,
            "nearest_signature_distance": (round(nearest, 3)
                                           if nearest is not None else None),
            "history_size": len(history), "warning": True}


# ------------------------------------------------- within-video reuse --
# 2026-10-15 review: the distinctness check above only compares AGAINST
# OTHER videos; nothing stopped one video from showing the same generated
# image twice (same plate on two shots) or a near-identical re-crop of it.
# Crop-robust: each plate's dHash is taken over its full frame AND centred /
# offset sub-crops (CROP_SCALES x CROP_OFFSETS); two plates whose closest
# (crop vs full) pair is within INTERNAL_DUP_MAX_HAMMING are one image.
# Calibrated on the two reviewed renders: 19 + 24 distinct plates, closest
# genuinely different pair = 11 bits; exact reuse = 0.
INTERNAL_DUP_MAX_HAMMING = 4
CROP_SCALES = (1.0, 0.85, 0.7, 0.55)
CROP_OFFSETS = (0.5, 0.25, 0.75)


def _dhash_img(im, hash_size: int = 8) -> int:
    im = im.convert("L").resize((hash_size + 1, hash_size), Image.LANCZOS)
    px = list(im.getdata())
    val = 0
    for row in range(hash_size):
        base = row * (hash_size + 1)
        for col in range(hash_size):
            val = (val << 1) | int(px[base + col] > px[base + col + 1])
    return val


def crop_hashes(path) -> list:
    """[full-frame dHash, then sub-crop dHashes]."""
    im = Image.open(path)
    W, H = im.size
    out = [_dhash_img(im)]
    for sc in CROP_SCALES[1:]:
        w, h = int(W * sc), int(H * sc)
        for ox in CROP_OFFSETS:
            for oy in CROP_OFFSETS:
                x, y = int((W - w) * ox), int((H - h) * oy)
                out.append(_dhash_img(im.crop((x, y, x + w, y + h))))
    return out


def shot_plates(meta: dict, specs: dict) -> dict:
    """shot key -> its first ai_image plate path (timeline order)."""
    out = {}
    for key in meta:
        for lay in (specs.get(key) or {}).get("layers") or []:
            path = (lay.get("payload") or {}).get("path")
            if lay.get("source") == "ai_image" and path:
                out[key] = path
                break
    return out


def check_internal_reuse(meta: dict, specs: dict) -> dict:
    """HOLD when one video shows the same generated image on two shots, or
    two of its plates are crops of one another."""
    by_shot = shot_plates(meta, specs)
    fails, users = [], {}
    for k, p in by_shot.items():
        users.setdefault(p, []).append(k)
    for p, ks in users.items():
        if len(ks) > 1:
            fails.append(f"one plate shown on {len(ks)} shots {ks}")
    hashes = {}
    for p in users:
        try:
            hashes[p] = crop_hashes(p)
        except OSError:
            continue
    paths = list(hashes)
    for i, a in enumerate(paths):
        for b in paths[i + 1:]:
            ha, hb = hashes[a], hashes[b]
            d = min(min(hamming(ha[0], x) for x in hb),
                    min(hamming(hb[0], x) for x in ha))
            if d <= INTERNAL_DUP_MAX_HAMMING:
                fails.append(f"plates of {users[a][0]} and {users[b][0]} are "
                             f"the same image re-cropped (dHash {d})")
    return {"ok": not fails, "fails": fails[:10], "plates": len(users)}


# ------------------------------------------------------------- scorecard --

def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


def _score_hook(hook: dict) -> float:
    judge_c = {True: 100.0, False: 0.0}.get(hook.get("hook_stops_scroll"), 50.0)
    fw = hook.get("first_word_s")
    fw_c = 0.0 if fw is None else _clamp(
        100.0 - max(0.0, fw - HOOK_MAX_FIRST_WORD_S) * 400.0)
    hl_c = 100.0 if hook.get("headline_at_frame0") else 0.0
    parts = [judge_c, fw_c, hl_c]
    # 2026-10-24 analytics review: does frame 1 literally show the hook's
    # concrete claim? Counted only when the judge answered it, so judge
    # results from before the question existed score exactly as before.
    concrete = hook.get("hook_frame_concrete")
    if concrete is not None:
        parts.append(100.0 if concrete else 0.0)
    return round(sum(parts) / len(parts), 1)


def _score_story(story: dict) -> float:
    """When `story["critic"]["scores"]` exists (v16_autostory.script_to_story
    now threads the real script_critic scores into story.json -- 2026-10-15
    review: before that NO auto-generated story carried them), use it
    directly (DESIGN's actual rubric, 0-5 scale). Otherwise fall back to a
    code-only structural proxy, flagged as a proxy, not a stand-in for the
    rubric:

        40 * fraction of beats that are grounded (claim + fact_ids)
      + 40 * fraction of beats with a hand-authored `contradiction`
      + 10 hook_plan + 10 payoff_image

    2026-10-15 review fix: the old proxy only counted a beat when it had
    ALL of contradiction+claim+fact_ids, and auto-generated stories never
    carry `contradiction` -- so every one of them scored story=0 by
    construction (66.6 / 63.2 REJECT scorecards of the asteroid/levitation
    renders), a bug rather than a quality signal. Grounding now earns
    credit on its own; the editorial fields still matter (a story without
    them caps at 40, i.e. it can't carry the scorecard on structure alone)."""
    crit = (story.get("critic") or {}).get("scores")
    if crit:
        # 2026-10-24: retention-weighted, anchored on the critic's own scale
        # (v16_script.STORY_DIM_WEIGHTS / CRITIC_POINTS), not a flat mean x20.
        from engine.v16_script import critic_weighted_score
        w = critic_weighted_score(crit)
        if w is not None:
            return round(_clamp(w), 1)
    beats = story.get("beats") or []
    if not beats:
        return 0.0
    grounded = sum(1 for b in beats if b.get("claim") and b.get("fact_ids"))
    contra = sum(1 for b in beats if b.get("contradiction"))
    bonus = (10 if story.get("hook_plan") else 0) + \
        (10 if story.get("payoff_image") else 0)
    return round(_clamp(40 * grounded / len(beats) + 40 * contra / len(beats)
                        + bonus), 1)


def _score_visuals(judge: dict | None) -> float:
    """v15_gate's `judge` check does not expose a total frame count, only
    the flagged list (a PASS-eligible video already cleared judge's own
    <=25%-flagged hard threshold, so this is always a small number here) —
    scored on a flat per-flagged-frame penalty rather than a fraction."""
    judge = judge or {}
    if judge.get("unverified") or not judge:
        return 50.0
    flagged = judge.get("frames_flagged") or []
    return round(_clamp(100.0 - 20.0 * len(flagged)), 1)


# Pacing score targets (owner follow-up 2026-10-14, "scorer target should
# be upgraded"). The score used to reward the WP7/§8.2 uniform-cut target
# (100 only for max hold <= v15_gate.MAX_HOLD_1_8_S=1.8 s and a median shot
# of 1.2-2.0 s) -- which penalised the editorial-rhythm pipeline's
# deliberate 2.2-4.0 s role-based holds (v15_pipeline.HOLD_MIN_S/HOLD_MAX_S)
# harder than the metronome cutting it replaced. Now it rewards:
#   - the longest hold landing inside the per-beat ceiling band
#     (PACING_HOLD_BAND_S == v15_pipeline HOLD_MIN_S..HOLD_MAX_S): over the
#     top edge is drifting toward a frozen frame, under the bottom edge
#     means no image ever gets to land;
#   - a median shot of 2.0-3.2 s: shots sit BELOW their beat's ceiling
#     (a split cuts a gap at 30-70%), and replaying the new rhythm on the 11
#     batch stories of 2026-10-13/14 gives medians of 1.98-3.02 s;
#   - shot-length variation (coefficient of variation >= 0.30): the
#     "feels AI generated" renders had CVs as low as 0.16 (near-equal
#     midpoint-split halves); the new rhythm's replay is 0.26-0.47.
# check_visual_hold's 4.5 s "never frozen" hard floor is unchanged, and
# v15_gate.check_pattern_interrupt keeps its 1.8 s semantics (WP7 template
# tests and bench/ab scripts still hold templates to it).
PACING_HOLD_BAND_S = (2.2, 4.0)
PACING_MEDIAN_BAND_S = (2.0, 3.2)
PACING_MIN_CV = 0.30


def _score_pacing(meta: dict, specs: dict) -> float:
    pat = v15_gate.check_pattern_interrupt(meta, specs)
    lo, hi = PACING_HOLD_BAND_S
    mh = pat["max_hold_s"]
    hold_c = 100.0 if lo <= mh <= hi else _clamp(
        100.0 - min(abs(mh - lo), abs(mh - hi)) * 40.0)
    med = pat["median_shot_s"]
    lo, hi = PACING_MEDIAN_BAND_S
    med_c = 100.0 if lo <= med <= hi else _clamp(
        100.0 - min(abs(med - lo), abs(med - hi)) * 60.0)
    durs = [float(specs[k]["duration_s"]) for k in meta]
    mean = sum(durs) / len(durs) if durs else 0.0
    cv = (sum((d - mean) ** 2 for d in durs) / len(durs)) ** 0.5 / mean \
        if mean > 0 else 0.0
    var_c = 100.0 if cv >= PACING_MIN_CV else _clamp(
        100.0 - (PACING_MIN_CV - cv) * 250.0)
    return round((hold_c + med_c + var_c) / 3, 1)


def _score_captions(checks: dict) -> float:
    names = ("caption_identity", "text_bounds", "caption_safe",
             "caption_numerals", "caption_clause_breaks")
    present = [checks[n]["ok"] for n in names if n in checks]
    if not present:
        return 50.0
    return round(100.0 * sum(present) / len(present), 1)


def _score_audio(checks: dict) -> float:
    audio = checks.get("audio") or {}
    lufs = audio.get("lufs")
    if lufs is None:
        return 50.0
    return round(_clamp(100.0 - abs(lufs - (-14.0)) * 40.0), 1)


def _score_brand(checks: dict, plates: dict, brand: dict, sting_present: bool) -> float:
    cube_sha = None
    try:
        from engine.brand import cube_sha256, cube_path
        cube_sha = cube_sha256(cube_path(brand))
    except Exception:
        pass
    lut_ok = bool(plates) and all(
        r.get("lut_sha256") == cube_sha for r in plates.values() if r.get("ok"))
    safe_ok = all(checks[n]["ok"] for n in ("text_bounds", "caption_safe")
                 if n in checks)
    components = [lut_ok, sting_present, safe_ok]
    return round(100.0 * sum(components) / len(components), 1)


_CAPTION_CHECKS = ("caption_identity", "text_bounds", "caption_safe",
                   "caption_numerals", "caption_clause_breaks")


def _gate_captions(checks: dict) -> dict:
    """Pass when every caption check that ran is ok, or is a decision #13
    warning (its severity is not raised here). Fails closed when none ran."""
    ran = [n for n in _CAPTION_CHECKS if n in checks]
    bad = [n for n in ran if not checks[n]["ok"] and not checks[n].get("warning")]
    reason = "no caption checks ran" if not ran else (f"failed: {bad}" if bad else "")
    return {"ok": bool(ran) and not bad, "value": _score_captions(checks), "reason": reason}


def _gate_audio(checks: dict) -> dict:
    lufs = (checks.get("audio") or {}).get("lufs")
    if lufs is None:
        return {"ok": False, "value": None, "reason": "loudness not measured"}
    off = abs(float(lufs) - AUDIO_LUFS_TARGET)
    return {"ok": off <= AUDIO_LUFS_TOLERANCE, "value": lufs,
            "reason": "" if off <= AUDIO_LUFS_TOLERANCE else
            f"{lufs} LUFS is {off:.1f} LU from {AUDIO_LUFS_TARGET} (max {AUDIO_LUFS_TOLERANCE})"}


def _gate_brand(checks: dict, plates: dict, brand: dict, sting_present: bool) -> dict:
    """Brand LUT on every recorded plate, the brand sting present, safe-area
    text. No recorded plates means the LUT part is not checked (reported as
    lut_checked=False), so a missing plate record cannot fail it."""
    cube_sha = None
    try:
        from engine.brand import cube_sha256, cube_path
        cube_sha = cube_sha256(cube_path(brand))
    except Exception:
        pass
    graded = [r for r in (plates or {}).values() if r.get("ok")]
    lut_ok = all(r.get("lut_sha256") == cube_sha for r in graded)
    safe_ok = all(checks[n]["ok"] for n in ("text_bounds", "caption_safe") if n in checks)
    missing = [k for k, ok in (("brand LUT", lut_ok), ("sting", sting_present),
                               ("safe-area text", safe_ok)) if not ok]
    return {"ok": not missing, "lut_checked": bool(graded),
            "value": _score_brand(checks, plates, brand, sting_present),
            "reason": f"missing: {missing}" if missing else ""}


def compute_scorecard(*, checks: dict, meta: dict, specs: dict, story: dict,
                      plates: dict, brand: dict, sting_present: bool) -> dict:
    dims = {
        "story": _score_story(story),
        "hook": _score_hook(checks.get("hook") or {}),
        "visuals": _score_visuals(checks.get("judge")),
        "pacing": _score_pacing(meta, specs),
    }
    gates = {
        "captions": _gate_captions(checks),
        "audio": _gate_audio(checks),
        "brand": _gate_brand(checks, plates, brand, sting_present),
    }
    total = round(sum(dims[k] * SCORE_WEIGHTS[k] / 100 for k in SCORE_WEIGHTS), 1)
    failed_gates = [k for k in SCORE_GATES if not gates[k]["ok"]]
    # Thresholds unchanged (PASS >= 80, REJECT < 70). A failed pass/fail gate
    # can only hold a would-be PASS. It never upgrades a REJECT.
    verdict = "PASS" if total >= 80 else ("HOLD" if total >= 70 else "REJECT")
    if verdict == "PASS" and failed_gates:
        verdict = "HOLD"
    return {"total": total, "verdict": verdict, "dimensions": dims,
            "weights": SCORE_WEIGHTS, "gates": gates, "failed_gates": failed_gates}


# ------------------------------------------------- duration / scorecard --

def total_duration_s(meta: dict, specs: dict) -> float:
    """Timeline length = sum of compiled shot durations (meta order)."""
    return round(sum(float((specs.get(k) or {}).get("duration_s") or 0.0)
                     for k in meta), 2)


def check_duration_gate(specs: dict, meta: dict, story: dict,
                        measured_s: float | None = None) -> dict:
    """v16_script.check_duration (DESIGN §4's 30-60 s hard limit; measured
    on the rendered file -- v15_gate's `av` probe -- when available, else
    the compiled timeline) -- defined
    since WP4 but never called anywhere in the render path (2026-10-15
    review: a 62.7 s video shipped unchecked). HOLD-causing, not critical:
    an over-length cut is fixable without re-scripting from scratch."""
    from engine.v16_script import check_duration
    secs = (round(float(measured_s), 2) if measured_s
            else total_duration_s(meta, specs))
    fails = check_duration(secs, story)
    return {"ok": not fails, "fails": fails, "duration_s": secs}


def check_scorecard(scorecard: dict) -> dict:
    v = (scorecard or {}).get("verdict")
    total = (scorecard or {}).get("total")
    if v == "PASS":
        return {"ok": True, "fails": [], "total": total, "score_verdict": v}
    weakest = sorted((scorecard.get("dimensions") or {}).items(),
                     key=lambda kv: kv[1])[:3]
    msg = (f"scorecard {v} ({total}/100; PASS needs >=80) -- weakest: "
           + ", ".join(f"{k}={d}" for k, d in weakest))
    if scorecard.get("failed_gates"):     # message only; ok/critical below unchanged
        msg += "; failed pass/fail gates: " + ", ".join(
            f"{k} ({(scorecard.get('gates') or {}).get(k, {}).get('reason', '')})"
            for k in scorecard["failed_gates"])
    return {"ok": False, "fails": [msg], "total": total, "score_verdict": v,
            "critical": v == "REJECT"}


# ---------------------------------------------------------------- run --

def run_gate(work, story: dict, meta: dict, specs: dict, timing: dict,
            captions: dict, lead: float, *, use_judge: bool = True,
            plate_qa: dict | None = None, voice: dict | None = None,
            brand: dict | None = None, plates: dict | None = None,
            sting_present: bool = False, video_id: str | None = None,
            history: list | None = None) -> dict:
    """v15_gate.run_gate()'s checks + `hook` + `distinctness` + `duration`,
    then the §10.2 scorecard when (and only when) the combined verdict is
    PASS -- and the scorecard's own verdict then GATES (`scorecard` check):
    only a scorecard PASS (>=80) leaves the final verdict at PASS."""
    base = v15_gate.run_gate(work, story, meta, specs, timing, captions, lead,
                             use_judge=use_judge, plate_qa=plate_qa,
                             voice=voice)
    checks = dict(base["checks"])
    checks["hook"] = check_hook(meta, specs, timing, lead, checks.get("judge"))
    plate_paths = v15_gate._plate_paths(specs)
    checks["distinctness"] = check_distinctness(
        video_id or story.get("story_id", ""), meta, plate_paths,
        history or [], specs=specs)
    checks["internal_reuse"] = check_internal_reuse(meta, specs)
    checks["duration"] = check_duration_gate(
        specs, meta, story, (checks.get("av") or {}).get("duration_s"))
    verdict = v15_gate.verdict_of(checks)
    scorecard = None
    if verdict == "PASS":
        scorecard = compute_scorecard(
            checks=checks, meta=meta, specs=specs, story=story,
            plates=plates or {}, brand=brand or {},
            sting_present=sting_present)
        # 2026-10-15 review CRITICAL fix: the §10.2 scorecard verdict used
        # to be computed and saved but never fed back into the gate verdict,
        # so two REJECT-scored videos (66.6, 63.2) still came out
        # publish_gate=PASS / publishable=true and auto-uploaded. It is now
        # a real check: REJECT -> critical (FAIL), HOLD -> HOLD.
        checks["scorecard"] = check_scorecard(scorecard)
        verdict = v15_gate.verdict_of(checks)
    failures = {k: v["fails"] for k, v in checks.items() if not v["ok"]}
    out = dict(base)
    out.update(checks=checks, verdict=verdict, failures=failures,
               scorecard=scorecard)
    return out
