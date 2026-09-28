"""Phase 2: one cold V15 run with per-stage wall-clock (wraps TTS/timing
from outside; pipeline code untouched). Usage: python3 timed_e2e.py <story_dir> <work>"""
import json, sys, time
from pathlib import Path
IE = Path("/home/ubuntu/video_engine/illustrated_engine")
sys.path.insert(0, str(IE))
import engine.tts as tts_mod
import engine.v15_pipeline as vp
T = {"tts_s": 0.0, "timing_s": 0.0, "tts_calls": 0}
_tts, _bt = tts_mod.tts_beat, vp.beat_timing
def tts_beat(*a, **k):
    t = time.time(); r = _tts(*a, **k); T["tts_s"] += time.time() - t; T["tts_calls"] += 1; return r
def beat_timing(*a, **k):
    t = time.time(); r = _bt(*a, **k); T["timing_s"] += time.time() - t; return r
tts_mod.tts_beat, vp.beat_timing = tts_beat, beat_timing
t0 = time.time()
rep = vp.run_pipeline(Path(sys.argv[1]), Path(sys.argv[2]))
wall = time.time() - t0
tm = rep["timings"]
named = sum(tm.get(k, 0) for k in ("plan_s", "plates_s", "render_s", "assembly_s", "gate_s"))
out = {"story": rep["story_id"], "wall_s": round(wall, 1),
       "tts_s": round(T["tts_s"], 1), "tts_calls": T["tts_calls"], "timing_s": round(T["timing_s"], 1),
       **tm, "untimed_residual_s (shot compile etc)": round(tm["total_s"] - named - T["tts_s"] - T["timing_s"], 1),
       "costs": rep["costs"], "plate_providers": rep.get("plate_providers"), "plate_qa": rep.get("plate_qa"),
       "plan_source": rep["plan"]["source"], "verdict": rep["publish_gate"],
       "failures": rep["gate"].get("failures"), "render_seconds": rep.get("render_seconds"),
       "duration_s": rep["gate"]["checks"].get("av", {}).get("duration_s")}
Path(sys.argv[2], "phase2_timings.json").write_text(json.dumps(out, indent=1))
print(json.dumps(out, indent=1))
