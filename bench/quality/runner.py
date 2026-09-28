"""Quality-benchmark harness skeleton (DESIGN §14, WP0).

Two jobs so far:
  * ``load_topics``   - validate the frozen research packs in bench/quality/topics/
  * ``baseline``      - freeze V15 scores from existing pipeline reports (no rendering)

Usage: python -m bench.quality.runner baseline [--out bench/ab]
"""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOPICS_DIR = ROOT / "bench" / "quality" / "topics"

# story -> V15 build dir holding pipeline_report.json + final.mp4
BASELINE_RUNS = {
    "ice_slippery": ROOT / "illustrated_engine/build/v15/ice_slippery",
    "cell_scale_dive": ROOT / "illustrated_engine/build/v15/cell_scale_dive",
    "blackhole_clocks": Path.home() / "phase2_out/e2e_blackhole",
}


def load_topics(topics_dir: Path = TOPICS_DIR) -> dict[str, dict]:
    topics = {}
    for d in sorted(p for p in topics_dir.iterdir() if p.is_dir()):
        pack = json.loads((d / "facts.json").read_text())
        if not pack.get("claims"):
            raise ValueError(f"{d.name}: facts.json has no claims")
        topics[d.name] = pack
    return topics


def _probe(path: Path) -> dict:
    if not path.exists():
        return {}
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=width,height,r_frame_rate:format=duration", "-of", "json", str(path)],
        capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        return {}
    j = json.loads(out.stdout)
    s = (j.get("streams") or [{}])[0]
    return {"duration_s": round(float(j["format"]["duration"]), 2),
            "size": f"{s.get('width')}x{s.get('height')}", "fps": s.get("r_frame_rate")}


def summarize_run(story: str, run_dir: Path) -> dict:
    rep = json.loads((run_dir / "pipeline_report.json").read_text())
    gate = rep.get("gate", {})
    checks = gate.get("checks", {})
    judge = checks.get("judge", {})
    shots = list((rep.get("shots") or {}).values())
    durs = [s["dur"] for s in shots if "dur" in s]
    return {
        "story": story,
        "verdict": gate.get("verdict"),
        "gate_checks": {k: bool(v.get("ok")) for k, v in checks.items() if isinstance(v, dict)},
        "gate_failures": gate.get("failures", {}),
        "video": _probe(run_dir / "final.mp4"),
        "shots": len(durs),
        "median_shot_s": round(sorted(durs)[len(durs) // 2], 2) if durs else None,
        "max_shot_s": round(max(durs), 2) if durs else None,
        "max_hold_s": checks.get("visual_hold", {}).get("max_hold_s"),
        "lufs": checks.get("audio", {}).get("lufs"),
        "judge": {"hook_stops_scroll": judge.get("hook_stops_scroll"),
                  "ending_resolves": judge.get("ending_resolves"),
                  "template_feel": judge.get("template_feel"),
                  "frames_flagged": judge.get("frames_flagged", []),
                  "notes": judge.get("notes")},
        "plate_qa_checked": (rep.get("plate_qa") or {}).get("checked"),
        "plate_providers": rep.get("plate_providers"),
        "timings_s": rep.get("timings"),
    }


def baseline(out_dir: Path) -> list[dict]:
    rows = [summarize_run(s, d) for s, d in BASELINE_RUNS.items() if (d / "pipeline_report.json").exists()]
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "baseline.json").write_text(json.dumps(rows, indent=1) + "\n")
    (out_dir / "baseline.md").write_text(render_md(rows))
    return rows


def render_md(rows: list[dict]) -> str:
    L = ["# V15 baseline (frozen in WP0)", "",
         "Source: existing V15 `pipeline_report.json` + `final.mp4` (no re-render). Reference for every later A/B.", "",
         "| story | verdict | dur s | shots | median shot s | max hold s | LUFS | plate QA ran | hook stops scroll | template feel | total s |",
         "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        j = r["judge"]
        L.append(f"| {r['story']} | {r['verdict']} | {r['video'].get('duration_s')} | {r['shots']} | "
                 f"{r['median_shot_s']} | {r['max_hold_s']} | {r['lufs']} | {r['plate_qa_checked']} | "
                 f"{j['hook_stops_scroll']} | {j['template_feel']} | {(r['timings_s'] or {}).get('total_s')} |")
    L += ["", "## Known baseline defects (do not read PASS as good)", ""]
    for r in rows:
        if r["plate_qa_checked"] is False:
            L.append(f"- **{r['story']}**: plate QA silently skipped (Gemini quota); watermark/garbled plates shipped (RESEARCH §2.3). WP2 makes this a HOLD.")
        for f in r["judge"]["frames_flagged"]:
            L.append(f"- **{r['story']}**: judge flagged frame {f.get('n')}: {f.get('issue')} (gate still PASS).")
        if r["judge"]["notes"]:
            L.append(f"- **{r['story']}** judge note: {r['judge']['notes']}")
    L.append("")
    return "\n".join(L)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["baseline", "topics"])
    ap.add_argument("--out", default=str(ROOT / "bench" / "ab"))
    a = ap.parse_args(argv)
    if a.cmd == "topics":
        for k, v in load_topics().items():
            print(k, len(v["claims"]), "claims")
    else:
        for r in baseline(Path(a.out)):
            print(r["story"], r["verdict"], r["video"].get("duration_s"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
