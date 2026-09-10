"""V11 EXPLANATORY_MOTION_RATIO (Jade_todo_v11 P0) — visual information, not
just motion.

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
    return {
        "EXPLANATORY_MOTION_RATIO": frac["C"],
        "shares": frac,
        "durations": {k: round(v, 2) for k, v in shares.items()},
        "gate_hard_C_over_A": bool(hard_ok),
        "advisory_strict_CBA": bool(strict_ok),
        "motion_pass": bool(hard_ok),
        "per_shot": per_shot,
    }


def write_report(res: dict, out_dir: Path, story_id: str = "") -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    p = out_dir / (f"motion_class_{story_id}.json" if story_id
                   else "motion_class.json")
    p.write_text(json.dumps(res, indent=1) + "\n")
    return p
