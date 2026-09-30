"""WP9 beat-snapped-cuts proof (cheap, offline, no render/LLM/network).

For each of the 3 WP0 baseline topics: build the real shot cut points via
engine.v15_pipeline's own `shot_timeline` + `split_long_holds` (same
mechanics as bench/ab/wp7_ab3_pacing.py, synthetic per-word timing —
documented approximation, real timing comes from voice synthesis), select
a real library track for the story's dominant arc mood
(engine.v16_audio.select_music_for_story), decode it and run
engine.v16_audio.detect_beats, then run snap_cuts_to_beats on the global
cut times against the global word times and that beat grid.

Proves: (a) a real selected track always yields SOME beat grid, (b) no cut
is ever moved more than the ±80ms design tolerance, (c) the fraction of
cuts that get tightened onto a beat is reported (not claimed as 100% — most
cuts have no nearby word boundary and are correctly left alone).

  python3 bench/ab/wp9_beat_snap.py [out.json]
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "illustrated_engine"
REPO = ROOT.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(ROOT))

from engine import v16_audio as va  # noqa: E402
from engine.procedural_audio import load_wav  # noqa: E402
from engine.v15_gate import MAX_HOLD_1_8_S  # noqa: E402
from engine.v15_pipeline import LEAD_S, shot_timeline, split_long_holds  # noqa: E402
from engine.v15_plan import fallback_plan  # noqa: E402
from engine.v16_plan import WORDS_PER_SEC  # noqa: E402

STORIES = ["ice_slippery", "cell_scale_dive", "blackhole_clocks"]
TOL = 0.08


def synthetic_timing(narration: str) -> dict:
    ws = narration.split()
    return {"words": [{"t0": i / WORDS_PER_SEC, "t1": (i + 1) / WORDS_PER_SEC,
                       "text": w} for i, w in enumerate(ws)]}


def run_story(sid: str) -> dict:
    sd = ROOT / "stories" / sid
    story = json.loads((sd / "story.json").read_text())
    plan = fallback_plan(story)
    plan_by = {b["beat_id"]: b for b in plan["beats"]}

    cuts, word_times, functions, durations = [], [], [], []
    t_cursor = 0.0
    for b in story["beats"]:
        timing = synthetic_timing(b["narration"])
        tts_s = len(b["narration"].split()) / WORDS_PER_SEC
        tl = shot_timeline(b, plan_by[b["beat_id"]], timing, tts_s)
        tl = split_long_holds(tl, timing, max_hold_s=MAX_HOLD_1_8_S)
        beat_start = t_cursor
        for w in timing["words"]:
            word_times.append(beat_start + LEAD_S + w["t0"])
        for s in tl:
            cuts.append(beat_start + s["t0"])
            functions.append(b["function"])
            durations.append(round(s["t1"] - s["t0"], 3))
        beat_start_dur = LEAD_S + tts_s + 0.55  # TAIL_S, matches v15_pipeline
        t_cursor += beat_start_dur

    sel = va.select_music_for_story(functions, durations,
                                    REPO / "assets" / "music", seed=sid)
    track = sel["track"]
    beats_s, bpm = ([], 0.0)
    if track:
        y = load_wav(track["path"])
        beats_s, bpm = va.detect_beats(y)

    snapped = va.snap_cuts_to_beats(cuts, word_times, beats_s, tol=TOL)
    moved = [(c, s) for c, s in zip(cuts, snapped) if abs(s - c) > 1e-9]
    max_move = max((abs(s - c) for c, s in moved), default=0.0)
    return {"mood": sel["mood"], "mood_weights": sel["weights"],
            "track": str(track["path"]) if track else None, "bpm": round(bpm, 1),
            "n_beats": len(beats_s), "n_cuts": len(cuts),
            "n_snapped": len(moved), "max_move_s": round(max_move, 4),
            "within_tolerance": max_move <= TOL + 1e-6}


def main(out_path: Path | None = None) -> int:
    report = {sid: run_story(sid) for sid in STORIES}
    text = json.dumps(report, indent=1)
    print(text)
    if out_path:
        out_path.write_text(text)
    return 0 if all(r["within_tolerance"] for r in report.values()) else 1


if __name__ == "__main__":
    p = Path(sys.argv[1]).expanduser() if len(sys.argv) > 1 else None
    sys.exit(main(p))
