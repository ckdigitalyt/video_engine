"""V11 EXPLANATORY_MOTION_RATIO (Jade_todo_v11 P0) — visual information, not
just motion. V12 P1 adds INFO_GAIN_CADENCE (Jade_todo_v12 §P1 Information
Transformation): every ~2-4 s a MEANINGFUL NEW RELATIONSHIP from the
directive vocabulary (cause / consequence / scale / location / mechanism /
comparison / process / uncertainty / evidence), derived from the planv9
beat model (declared state transformations) + v8 events. Decorative motion
does NOT count as gain — a camera-only (A-class) shot contributes nothing.

Shots carry a planner-declared motion_class (planv5._motion_class):
  C = explanatory  (reveals causal relationship, changes physical state,
                    exposes hidden layer, comparison, scale, process,
                    consequence, diagram transformation)
  B = structural   (composition changes: pops, highlights, splits, restyle
                    kinetic)
  A = decorative   (camera-only motion or static — camera movement does NOT
                    count as information)

The metric is duration-weighted. Target ordering: C > B > A. GATE (hard):
A > C fails — decoration must never outweigh explanation. The full strict
ordering C > B > A is reported as an advisory so stories that genuinely
lack B-motion are not punished into faking structural events (Jade: do not
animate purely to satisfy the metric).
"""
from __future__ import annotations

import json
from pathlib import Path


# --- V12 P1 — information-gain cadence --------------------------------------
CADENCE_WINDOW_S = 4.0   # directive: a new relationship every ~2-4 s

# directive relationship vocabulary
RELATIONSHIPS = ("cause", "consequence", "scale", "location", "mechanism",
                 "comparison", "process", "uncertainty", "evidence")

# planv9 beat-model state transformation -> relationship(s) it teaches
_TRANSFORM_GAINS = {
    "scale_change": ("scale",),
    "hidden_layer_revealed": ("mechanism",),
    "object_transforms": ("process",),
    "cause_to_consequence": ("cause", "consequence"),
    "geography_expands": ("location",),
    "geography_contracts": ("location",),
    "timeline_advances": ("process",),
    "comparison_resolves": ("comparison",),
    "mechanism_visible": ("mechanism",),
    "hypothesis_branches": ("uncertainty",),
    "before_after": ("process", "comparison"),
}

# v8 living events -> relationship(s); structural pops/highlights teach no
# new relationship (B-class) and never count here.
_EVENT_GAINS = {
    "reveal": ("evidence",),
    "isolate": ("evidence",),
    "frame_reveal": ("evidence",),
    "flow": ("mechanism",),
    "fill_state": ("process",),
    "consequence": ("consequence",),
    "number_pop": ("evidence",),
}


def _shot_start(plan: dict, shot_id: str) -> float:
    t = 0.0
    for s in plan.get("shots") or []:
        if str(s.get("shot_id")) == shot_id:
            return t
        t += float(s.get("duration_s") or 0)
    return t


def info_gain_cadence(plan: dict) -> dict:
    """Timeline of meaningful new relationships (2-4 s cadence check).

    The beat's declared transformation counts ONCE (at its first shot —
    repeating the same transformation is not new information); v8 events
    count at their authored in-shot time. A camera-only decorative shot
    (A-class, no events) is never a gain source.
    """
    shots = plan.get("shots") or []
    beats = ((plan.get("beat_model") or {}).get("beats") or {})
    gains_at: list = []            # (t, relationships, source)
    seen_transforms: set = set()
    for s in shots:
        cls = str(s.get("motion_class") or "A").upper()
        kinds = {str((e or {}).get("kind") or "").lower()
                 for e in s.get("events") or []}
        t0 = _shot_start(plan, str(s.get("shot_id")))
        decorative_camera = cls == "A" and not kinds
        if not decorative_camera:
            bid = str(s.get("beat_id") or "")
            transform = str((beats.get(bid) or {}).get(
                "state_transformation") or "")
            if transform in _TRANSFORM_GAINS and transform not in seen_transforms:
                seen_transforms.add(transform)
                gains_at.append((t0, list(_TRANSFORM_GAINS[transform]),
                                 f"beat:{bid}:{transform}"))
        for e in s.get("events") or []:
            kind = str((e or {}).get("kind") or "").lower()
            if kind in _EVENT_GAINS:
                t = t0 + float((e or {}).get("t") or 0)
                gains_at.append((t, list(_EVENT_GAINS[kind]),
                                 f"event:{kind}"))
    total = sum(float(s.get("duration_s") or 0) for s in shots)
    n = max(int(total // CADENCE_WINDOW_S), 1)
    rows = [{"t": [round(w * CADENCE_WINDOW_S, 1),
                   round((w + 1) * CADENCE_WINDOW_S, 1)],
             "relationships": [], "sources": []} for w in range(n)]
    for t, rels, src in gains_at:
        w = min(int(t // CADENCE_WINDOW_S), n - 1)
        for r in rels:
            if r not in rows[w]["relationships"]:
                rows[w]["relationships"].append(r)
        if src not in rows[w]["sources"]:
            rows[w]["sources"].append(src)
    empty = [r["t"] for r in rows if not r["relationships"]]
    gaps = []
    run_len = 0
    for r in rows:
        if not r["relationships"]:
            run_len += CADENCE_WINDOW_S
        elif run_len:
            gaps.append(round(run_len, 1))
            run_len = 0
    if run_len:
        gaps.append(round(run_len, 1))
    covered = sum(1 for r in rows if r["relationships"])
    return {
        "window_s": CADENCE_WINDOW_S,
        "vocabulary": list(RELATIONSHIPS),
        "rows": rows,
        "covered_windows": covered,
        "n_windows": n,
        "coverage": round(covered / n, 3) if n else 0.0,
        "no_gain_windows": empty,
        "longest_gain_gap_s": max(gaps) if gaps else 0.0,
        "gains_total": len(gains_at),
        "verdict": ("ok" if not empty else
                    "gaps" if len(empty) <= max(1, n // 3) else "sparse"),
    }


def run(plan: dict) -> dict:
    shares = {"A": 0.0, "B": 0.0, "C": 0.0}
    per_shot = []
    for s in (plan or {}).get("shots", []):
        cls = str(s.get("motion_class") or "A").upper()
        d = float(s.get("duration_s", 0.0))
        if cls not in shares:
            cls = "A"
        shares[cls] += d
        per_shot.append({"shot_id": str(s.get("shot_id")), "class": cls,
                         "dur": round(d, 2)})
    total = sum(shares.values()) or 1.0
    frac = {k: round(v / total, 4) for k, v in shares.items()}
    hard_ok = frac["C"] > frac["A"]          # decoration must not dominate
    strict_ok = frac["C"] > frac["B"] > frac["A"]
    cadence = info_gain_cadence(plan)
    return {
        "EXPLANATORY_MOTION_RATIO": frac["C"],
        "shares": frac,
        "durations": {k: round(v, 2) for k, v in shares.items()},
        "gate_hard_C_over_A": bool(hard_ok),
        "advisory_strict_CBA": bool(strict_ok),
        "motion_pass": bool(hard_ok),
        "per_shot": per_shot,
        "INFO_GAIN_CADENCE": cadence,
    }


def write_report(res: dict, out_dir: Path, story_id: str = "") -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    p = out_dir / (f"motion_class_{story_id}.json" if story_id
                   else "motion_class.json")
    p.write_text(json.dumps(res, indent=1) + "\n")
    return p
