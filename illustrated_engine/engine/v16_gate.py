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
SCORE_WEIGHTS = {"hook": 20, "story": 20, "visuals": 15, "pacing": 15,
                 "captions": 10, "audio": 10, "brand": 10}


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
            "hook_stops_scroll": stops_scroll}


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
                       history: list) -> dict:
    """`history`: [{"video_id", "signature", "plate_hashes": [int, ...]}],
    already loaded and capped by the caller (pure function, no I/O — the
    gate never writes history itself; see engine.v16_manifest.
    record_distinctness for the one place that does, called once per real
    pipeline run, not on every re-gate)."""
    sig = template_signature(meta)
    hashes = [dhash(p) for p in plate_paths]
    fails = []
    nearest = None
    for h in history:
        if h.get("video_id") == video_id:
            continue
        d = signature_distance(sig, h.get("signature") or "")
        if nearest is None or d < nearest:
            nearest = d
        if d < SIGNATURE_MIN_DISTANCE:
            fails.append(f"template sequence too close to {h['video_id']} "
                         f"(distance {d:.2f} < {SIGNATURE_MIN_DISTANCE})")
        for ph in h.get("plate_hashes") or []:
            for hh in hashes:
                if hamming(ph, hh) <= DHASH_MAX_REUSE_DISTANCE:
                    fails.append(f"plate near-duplicate of one used in "
                                 f"{h['video_id']} (Hamming {hamming(ph, hh)})")
    return {"ok": not fails, "fails": sorted(set(fails))[:10],
            "signature": sig, "plate_hashes": hashes,
            "nearest_signature_distance": (round(nearest, 3)
                                           if nearest is not None else None),
            "history_size": len(history)}


# ------------------------------------------------------------- scorecard --

def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


def _score_hook(hook: dict) -> float:
    judge_c = {True: 100.0, False: 0.0}.get(hook.get("hook_stops_scroll"), 50.0)
    fw = hook.get("first_word_s")
    fw_c = 0.0 if fw is None else _clamp(
        100.0 - max(0.0, fw - HOOK_MAX_FIRST_WORD_S) * 400.0)
    hl_c = 100.0 if hook.get("headline_at_frame0") else 0.0
    return round((judge_c + fw_c + hl_c) / 3, 1)


def _score_story(story: dict) -> float:
    """v16_script's critic rubric (S2-S4) is not wired into v15_pipeline's
    input story.json yet (v15_pipeline consumes pre-scripted V15-format
    stories, same "not yet wired" precedent as v16_plan/v16_audio before
    their WPs). When `story["critic"]["scores"]` exists, use it directly
    (DESIGN's actual rubric, 1-5 scale). Otherwise fall back to a
    code-only structural proxy over the fields the story DOES carry
    (contradiction/claim/fact_ids per beat, a hook_plan, a payoff_image) —
    flagged as a proxy, not a silent stand-in for the rubric."""
    crit = (story.get("critic") or {}).get("scores")
    if crit:
        vals = list(crit.values())
        return round(_clamp(sum(vals) / len(vals) / 5 * 100), 1)
    beats = story.get("beats") or []
    if not beats:
        return 0.0
    complete = sum(1 for b in beats
                  if b.get("contradiction") and b.get("claim")
                  and b.get("fact_ids"))
    frac = complete / len(beats)
    bonus = (10 if story.get("hook_plan") else 0) + \
        (10 if story.get("payoff_image") else 0)
    return round(_clamp(frac * 80 + bonus), 1)


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


def _score_pacing(meta: dict, specs: dict) -> float:
    pat = v15_gate.check_pattern_interrupt(meta, specs)
    hold_c = 100.0 if pat["max_hold_s"] <= v15_gate.MAX_HOLD_1_8_S else _clamp(
        100.0 - (pat["max_hold_s"] - v15_gate.MAX_HOLD_1_8_S) * 40.0)
    med = pat["median_shot_s"]
    med_c = 100.0 if 1.2 <= med <= 2.0 else _clamp(
        100.0 - min(abs(med - 1.2), abs(med - 2.0)) * 60.0)
    return round((hold_c + med_c) / 2, 1)


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


def compute_scorecard(*, checks: dict, meta: dict, specs: dict, story: dict,
                      plates: dict, brand: dict, sting_present: bool) -> dict:
    dims = {
        "hook": _score_hook(checks.get("hook") or {}),
        "story": _score_story(story),
        "visuals": _score_visuals(checks.get("judge")),
        "pacing": _score_pacing(meta, specs),
        "captions": _score_captions(checks),
        "audio": _score_audio(checks),
        "brand": _score_brand(checks, plates, brand, sting_present),
    }
    total = round(sum(dims[k] * SCORE_WEIGHTS[k] / 100 for k in SCORE_WEIGHTS), 1)
    verdict = "PASS" if total >= 80 else ("HOLD" if total >= 70 else "REJECT")
    return {"total": total, "verdict": verdict, "dimensions": dims,
            "weights": SCORE_WEIGHTS}


# ---------------------------------------------------------------- run --

def run_gate(work, story: dict, meta: dict, specs: dict, timing: dict,
            captions: dict, lead: float, *, use_judge: bool = True,
            plate_qa: dict | None = None, voice: dict | None = None,
            brand: dict | None = None, plates: dict | None = None,
            sting_present: bool = False, video_id: str | None = None,
            history: list | None = None) -> dict:
    """v15_gate.run_gate()'s checks + `hook` + `distinctness`, then the
    §10.2 scorecard when (and only when) the combined verdict is PASS."""
    base = v15_gate.run_gate(work, story, meta, specs, timing, captions, lead,
                             use_judge=use_judge, plate_qa=plate_qa,
                             voice=voice)
    checks = dict(base["checks"])
    checks["hook"] = check_hook(meta, specs, timing, lead, checks.get("judge"))
    plate_paths = v15_gate._plate_paths(specs)
    checks["distinctness"] = check_distinctness(
        video_id or story.get("story_id", ""), meta, plate_paths,
        history or [])
    verdict = v15_gate.verdict_of(checks)
    failures = {k: v["fails"] for k, v in checks.items() if not v["ok"]}
    scorecard = None
    if verdict == "PASS":
        scorecard = compute_scorecard(
            checks=checks, meta=meta, specs=specs, story=story,
            plates=plates or {}, brand=brand or {},
            sting_present=sting_present)
    out = dict(base)
    out.update(checks=checks, verdict=verdict, failures=failures,
               scorecard=scorecard)
    return out
