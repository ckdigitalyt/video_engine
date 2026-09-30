"""WP7 A/B #3 (cheap): median shot / max hold for the 3 WP0 baseline
topics (ice, cell, blackhole), run entirely offline — engine.v15_plan's
zero-LLM `fallback_plan`, engine.v15_pipeline's real shot-timing + the
WP7-tightened `split_long_holds(max_hold_s=1.8)`, engine.v16_plan's
planner-v2 template assignment, engine.v15_shots' compilers, and
engine.v15_gate's checks. No Claude call, no image-provider call, no
audio synthesis — per-word timing is the same WORDS_PER_SEC cadence
v15_plan/v16_plan already calibrate against (documented approximation;
real per-word timing comes from voice synthesis once this is wired into
engine.v15_pipeline.run_pipeline, which this script does not do).

  python3 bench/ab/wp7_ab3_pacing.py [out.json]
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "illustrated_engine"
sys.path.insert(0, str(ROOT))
from engine import v15_gate as g  # noqa: E402
from engine import v15_shots as S  # noqa: E402
from engine import v16_plan as P  # noqa: E402
from engine.v15_pipeline import LEAD_S, shot_timeline, split_long_holds  # noqa: E402
from engine.v15_plan import fallback_plan  # noqa: E402
from engine.v15_style import load_style  # noqa: E402

STORIES = ["ice_slippery", "cell_scale_dive", "blackhole_clocks"]


def synthetic_timing(narration: str) -> dict:
    ws = narration.split()
    return {"words": [{"t0": i / P.WORDS_PER_SEC, "t1": (i + 1) / P.WORDS_PER_SEC,
                       "text": w} for i, w in enumerate(ws)]}


def run_story(sid: str) -> dict:
    sd = ROOT / "stories" / sid
    story = json.loads((sd / "story.json").read_text())
    bible = load_style(sd, story)
    plan = fallback_plan(story)  # deterministic, zero LLM calls
    plan_by = {b["beat_id"]: b for b in plan["beats"]}

    flat = []  # [{beat_id, shot, t0, t1, timing}] beat-local seconds
    for b in story["beats"]:
        timing = synthetic_timing(b["narration"])
        tts_s = len(b["narration"].split()) / P.WORDS_PER_SEC
        tl = shot_timeline(b, plan_by[b["beat_id"]], timing, tts_s)
        tl = split_long_holds(tl, timing, max_hold_s=g.MAX_HOLD_1_8_S)
        for s in tl:
            flat.append({"beat_id": b["beat_id"], "shot": s["shot"],
                        "t0": s["t0"], "t1": s["t1"], "timing": timing})

    split_plan = {"beats": []}
    by_beat: dict = {}
    for f in flat:
        by_beat.setdefault(f["beat_id"], []).append(f["shot"])
    for b in story["beats"]:
        split_plan["beats"].append({"beat_id": b["beat_id"],
                                    "shots": by_beat.get(b["beat_id"], [])})
    res = P.assign_templates(split_plan, story)

    meta, specs = {}, {}
    for i, f in enumerate(flat):
        wt = [w["t0"] for w in f["timing"]["words"]]
        t0 = f["t0"]
        t_of = lambda w, wt=wt, t0=t0: max(0.0, wt[min(w, len(wt) - 1)] - (t0 - LEAD_S))
        sc = {"scene_id": f"{f['beat_id']}_{i}",
              "duration": max(0.3, round(f["t1"] - f["t0"], 3)),
              "plates": [], "t_of": t_of, "first": i == 0, "shot": f["shot"]}
        out = S.compile_shot(sc, bible)
        meta[sc["scene_id"]] = out
        specs[sc["scene_id"]] = out["spec"]

    hold = g.check_pattern_interrupt(meta, specs)
    text_bounds = g.check_text_bounds(specs)
    return {"n_shots": len(specs), "templates_used": res["templates_used"],
            "n_templates_used": len(res["templates_used"]),
            "template_errors": res["errors"],
            "median_shot_s": hold["median_shot_s"],
            "max_hold_s": hold["max_hold_s"], "hold_1_8_ok": hold["ok"],
            "hold_1_8_fails": hold["fails"][:6],
            "text_bounds_ok": text_bounds["ok"],
            "text_bounds_fails": text_bounds["fails"][:5]}


def main(out_path: Path | None = None) -> int:
    report = {sid: run_story(sid) for sid in STORIES}
    text = json.dumps(report, indent=1)
    print(text)
    if out_path:
        out_path.write_text(text)
    return 0 if all(r["hold_1_8_ok"] and r["text_bounds_ok"] and
                    not r["template_errors"] for r in report.values()) else 1


if __name__ == "__main__":
    p = Path(sys.argv[1]).expanduser() if len(sys.argv) > 1 else None
    sys.exit(main(p))
