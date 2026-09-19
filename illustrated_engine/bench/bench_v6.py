#!/usr/bin/env python3
"""V6 cinematography benchmark — bench brief §1-2, §8-9, §11.

Renders ONE representative shot per scene type (space / data / technical)
from the SAME source edit plans under 8 flag variants, and records:
wall-clock render time, CPU seconds + utilization, output res/fps, file
size, ffmpeg QA detectors (black/freeze), objective frame metrics (luma,
RMS contrast, edge energy) and motion_qa trajectory scores.

Expects per-story edit plans at bench/plans/<story>.json (generated once via
`cli.py plan5 <story>`; build/edit_plan.json copied aside). Results go to
bench/results/<scene>__<variant>.json (existing results are reused unless
--force, so interrupted runs resume).

Usage:
  python3 bench/bench_v6.py --list
  python3 bench/bench_v6.py --scene technical --only baseline,par
  python3 bench/bench_v6.py                # full matrix (resumable)
  python3 bench/bench_v6.py --summarize    # matrix.json + comparison strips
"""
from __future__ import annotations

import argparse
import json
import os
import resource
import shutil
import statistics
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine import Paths  # noqa: E402
from engine import motion_qa  # noqa: E402

SCENES = [  # (scene, story, shot picker) — same source VisualSpecs for every variant
    ("space", "blackhole_clocks",
     lambda shots: next((s for s in shots if s.get("kinetic")), shots[0])),
    ("data", "mitochondria_dna",
     lambda shots: next((s for s in shots if s["shot_id"] == "S02"),  # 1.20->1.35 zoom + number pop
                        max(shots, key=lambda s: len(s.get("events") or [])))),
    ("technical", "aircraft_wing_lift",
     lambda shots: next((s for s in shots if s["shot_id"] == "S09"),  # 1.16->1.0 zoom-out, diagram
                        max(shots, key=lambda s: len(s.get("events") or [])))),
]

VARIANTS = [
    ("baseline", {}),
    ("cam", {"CAMERA_PROFILE": "eased"}),
    ("par", {"ENABLE_PARALLAX": "1"}),
    ("bloom", {"ENABLE_BLOOM": "1"}),
    ("cam+par", {"CAMERA_PROFILE": "eased", "ENABLE_PARALLAX": "1"}),
    ("cam+bloom", {"CAMERA_PROFILE": "eased", "ENABLE_BLOOM": "1"}),
    ("par+bloom", {"ENABLE_PARALLAX": "1", "ENABLE_BLOOM": "1"}),
    ("all", {"CAMERA_PROFILE": "eased", "ENABLE_PARALLAX": "1", "ENABLE_BLOOM": "1"}),
]

FLAG_KEYS = ("CAMERA_PROFILE", "ENABLE_PARALLAX", "ENABLE_BLOOM")


def load_plan(story: str) -> dict:
    return json.loads((ROOT / "bench" / "plans" / f"{story}.json").read_text())


def load_bible(story: str):
    from engine import bible as B
    try:
        return B.load_bible(ROOT / "stories" / story)
    except Exception:
        return json.loads((ROOT / "stories" / story / "visual_bible.json").read_text())


def ffprobe(mp4: Path) -> dict:
    p = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "format=duration,size:stream=width,height,avg_frame_rate",
         "-of", "json", str(mp4)],
        capture_output=True, text=True, check=True)
    d = json.loads(p.stdout)
    fmt = d.get("format", {})
    st = (d.get("streams") or [{}])[0]
    fps = 0.0
    fr = str(st.get("avg_frame_rate", "0/1"))
    try:
        num, den = fr.split("/")
        if float(den or 1):
            fps = float(num) / float(den)
    except Exception:
        pass
    return {"duration_s": round(float(fmt.get("duration", 0)), 3),
            "size_bytes": int(fmt.get("size", 0)),
            "width": st.get("width"), "height": st.get("height"),
            "fps": round(fps, 3)}


def frame_metrics(mp4: Path, n_samples: int = 5) -> dict:
    from PIL import Image, ImageFilter, ImageStat
    tmp = mp4.parent / (mp4.stem + "_fm")
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    try:
        subprocess.run(
            ["ffmpeg", "-nostdin", "-y", "-loglevel", "error", "-i", str(mp4),
             "-vf", f"fps={n_samples}", str(tmp / "f%03d.png")],
            capture_output=True, check=True)
        lums, cons, edges = [], [], []
        for f in sorted(tmp.glob("f*.png")):
            im = Image.open(f).convert("L")
            st = ImageStat.Stat(im)
            lums.append(st.mean[0])
            cons.append(st.stddev[0])
            edges.append(ImageStat.Stat(im.filter(ImageFilter.FIND_EDGES)).mean[0])
        return {"luma": round(statistics.fmean(lums), 2),
                "contrast_rms": round(statistics.fmean(cons), 2),
                "edge_energy": round(statistics.fmean(edges), 2)}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def qa_detectors(mp4: Path) -> dict:
    """ffmpeg black/freeze detectors, skipping the 0.6s fade-in."""
    p = subprocess.run(
        ["ffmpeg", "-nostdin", "-ss", "0.6", "-i", str(mp4), "-an",
         "-vf", "blackdetect=d=0.2:pic_th=0.98,freezedetect=n=0.003:d=1.0",
         "-f", "null", "-"],
        capture_output=True, text=True)
    err = p.stderr
    return {"black": "black_start" in err, "freeze": "freeze_start" in err}


def run_variant(scene, story, shot, vname, env_extra, paths, bible) -> dict:
    from engine import composev5
    for k in FLAG_KEYS:
        os.environ.pop(k, None)
    os.environ.update(env_extra)
    r0 = resource.getrusage(resource.RUSAGE_SELF)
    c0 = resource.getrusage(resource.RUSAGE_CHILDREN)
    t0 = time.perf_counter()
    art = composev5.render_shot_v5(
        shot, paths, bible, force=True, shots_subdir="bench_shots",
        artifact=f"{story}__{shot['shot_id']}__{vname}.mp4")
    wall = time.perf_counter() - t0
    r1 = resource.getrusage(resource.RUSAGE_SELF)
    c1 = resource.getrusage(resource.RUSAGE_CHILDREN)
    cpu_s = ((r1.ru_utime - r0.ru_utime) + (r1.ru_stime - r0.ru_stime) +
             (c1.ru_utime - c0.ru_utime) + (c1.ru_stime - c0.ru_stime))
    rec = {"scene": scene, "story": story, "shot": shot["shot_id"],
           "variant": vname, "env": env_extra,
           "wall_s": round(wall, 3), "cpu_s": round(cpu_s, 3),
           "cpu_util_pct": round(100 * cpu_s / max(wall, 1e-6), 1)}
    rec.update(ffprobe(art))
    rec.update(frame_metrics(art))
    rec["detectors"] = qa_detectors(art)
    try:
        rec["motion_qa"] = motion_qa._score_shot(shot.get("camera") or {},
                                                 float(shot["duration_s"]))
    except Exception as e:
        rec["motion_qa"] = {"error": str(e)}
    rec["artifact"] = str(art)
    return rec


def make_strip(scene: str, arts: list) -> Path:
    """Side-by-side mid-frame strip across variants (order = VARIANTS)."""
    from PIL import Image
    res_dir = ROOT / "bench" / "results"
    tiles = []
    for vname, path in arts:
        tmp = res_dir / f"_mid_{scene}_{vname}.png"
        subprocess.run(["ffmpeg", "-nostdin", "-y", "-loglevel", "error",
                        "-ss", "2.5", "-i", str(path), "-frames:v", "1",
                        str(tmp)], capture_output=True, check=True)
        tiles.append((vname, Image.open(tmp).convert("RGB").resize((360, 640))))
        tmp.unlink(missing_ok=True)
    w, h = 360, 640
    strip = Image.new("RGB", (w * len(tiles), h + 0), (16, 16, 16))
    for i, (_v, t) in enumerate(tiles):
        strip.paste(t, (i * w, 0))
    out = res_dir / f"strip_{scene}.png"
    strip.save(out, "PNG")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="", help="comma list of variants")
    ap.add_argument("--scene", default="", help="single scene name")
    ap.add_argument("--force", action="store_true", help="re-render existing results")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--summarize", action="store_true")
    args = ap.parse_args()

    res_dir = ROOT / "bench" / "results"
    res_dir.mkdir(parents=True, exist_ok=True)

    scenes = []
    for scene, story, picker in SCENES:
        if args.scene and scene != args.scene:
            continue
        shots = load_plan(story)["shots"]
        scenes.append((scene, story, picker(shots)))
    if args.list:
        for scene, story, shot in scenes:
            print(f"{scene:10s} {story:20s} -> {shot['shot_id']} "
                  f"({shot['duration_s']:.2f}s cam={bool(shot.get('camera'))} "
                  f"kin={bool(shot.get('kinetic'))} ev={len(shot.get('events') or [])})")
        return

    if args.summarize:
        summarize(res_dir)
        return

    only = [v.strip() for v in args.only.split(",") if v.strip()] if args.only else None
    variants = [(n, e) for n, e in VARIANTS if only is None or n in only]
    paths = Paths(ROOT, build_dir=ROOT / "bench" / "build").ensure_dirs()

    for scene, story, shot in scenes:
        bible = load_bible(story)
        for vname, env in variants:
            key = f"{scene}__{vname}"
            jout = res_dir / f"{key}.json"
            if jout.exists() and not args.force:
                print(f"[skip] {key} (exists)")
                continue
            try:
                rec = run_variant(scene, story, shot, vname, env, paths, bible)
                jout.write_text(json.dumps(rec, indent=2))
                print(f"[ok] {key}: wall={rec['wall_s']}s cpu={rec['cpu_util_pct']}% "
                      f"size={rec['size_bytes']//1024}KB", flush=True)
            except Exception as e:
                jout.write_text(json.dumps(
                    {"scene": scene, "variant": vname, "error": str(e)[:800]}, indent=2))
                print(f"[ERR] {key}: {e}", flush=True)


def summarize(res_dir: Path):
    rows = []
    for scene, story, _shot in SCENES:
        for vname, _env in VARIANTS:
            j = res_dir / f"{scene}__{vname}.json"
            if j.exists():
                rows.append(json.loads(j.read_text()))
    by_key = {(r.get("scene"), r.get("variant")): r for r in rows if "error" not in r}
    summary = []
    for scene, _story, _shot in SCENES:
        base = by_key.get((scene, "baseline"))
        if not base:
            continue
        for vname, _env in VARIANTS:
            r = by_key.get((scene, vname))
            if not r:
                continue
            summary.append({
                "scene": scene, "variant": vname, "shot": r["shot"],
                "wall_s": r["wall_s"],
                "cost_ratio": round(r["wall_s"] / max(base["wall_s"], 1e-6), 3),
                "cpu_util_pct": r["cpu_util_pct"],
                "size_kb": r["size_bytes"] // 1024,
                "d_luma": round(r["luma"] - base["luma"], 2),
                "d_contrast_pct": round(
                    100 * (r["contrast_rms"] / max(base["contrast_rms"], 1e-6) - 1), 1),
                "d_edge_pct": round(
                    100 * (r["edge_energy"] / max(base["edge_energy"], 1e-6) - 1), 1),
                "black": r["detectors"]["black"],
                "freeze": r["detectors"]["freeze"],
                "motion_qa": (r.get("motion_qa") or {}).get("score"),
            })
    (res_dir / "matrix.json").write_text(json.dumps(summary, indent=2))
    for scene, _story, _shot in SCENES:
        arts = [(v, Path(by_key[(scene, v)]["artifact"]))
                for v, _ in VARIANTS if (scene, v) in by_key]
        if len(arts) > 1:
            try:
                out = make_strip(scene, arts)
                print(f"strip -> {out}")
            except Exception as e:
                print(f"strip {scene} failed: {e}")
    print(f"\n{'scene':10s} {'variant':10s} {'cost':>6s} {'cpu%':>6s} "
          f"{'dLuma':>7s} {'dCon%':>7s} {'dEdge%':>7s} black freeze mq")
    for s in summary:
        print(f"{s['scene']:10s} {s['variant']:10s} {s['cost_ratio']:5.2f}x "
              f"{s['cpu_util_pct']:6.1f} {s['d_luma']:+7.2f} "
              f"{s['d_contrast_pct']:+7.1f} {s['d_edge_pct']:+7.1f} "
              f"{str(s['black']):5s} {str(s['freeze']):5s} {s['motion_qa']}")


if __name__ == "__main__":
    main()
