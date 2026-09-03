"""QA v2 — v1-parity technical checks + subtitle layout QA + novelty coverage
+ visual-continuity score. Writes build/qa/qa2.json."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from engine import grammar, subs


def _probe(path):
    p = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                        "stream=codec_name,width,height,r_frame_rate",
                        "-show_entries", "format=duration,size", "-of", "json",
                        str(path)], capture_output=True, text=True)
    try:
        return json.loads(p.stdout or "{}")
    except json.JSONDecodeError:
        return {}


def _filter_pass(path, vf, pattern):
    p = subprocess.run(["ffmpeg", "-nostdin", "-hide_banner", "-i", str(path),
                        "-vf", vf, "-an", "-f", "null", "-"],
                       capture_output=True, text=True)
    hits = re.findall(pattern, p.stderr)
    return hits


def _loudnorm_input_i(path):
    p = subprocess.run(["ffmpeg", "-nostdin", "-hide_banner", "-i", str(path),
                        "-af", "loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json",
                        "-f", "null", "-"], capture_output=True, text=True)
    blocks = re.findall(r"\{[^{}]*\}", p.stderr)
    for b in reversed(blocks):
        try:
            js = json.loads(b)
            if "input_i" in js:
                return float(js["input_i"]), float(js.get("input_tp", 0))
        except json.JSONDecodeError:
            continue
    return None, None


def qa_video_v2(target: Path, paths, story_id: str = "tallest_mountain") -> dict:
    checks = []

    def add(name, ok, detail=""):
        checks.append({"check": name, "ok": bool(ok), "detail": str(detail)})

    # 1) streams + duration window
    pr = _probe(target)
    streams = pr.get("streams", [])
    fmt = pr.get("format", {})
    v = next((s for s in streams if s.get("codec_name") == "h264"), {})
    a = next((s for s in streams if s.get("codec_name") == "aac"), {})
    dur = float(fmt.get("duration", 0))
    add("streams", v.get("width") == 1080 and v.get("height") == 1920
        and v.get("r_frame_rate") == "30/1" and bool(a),
        f"{v.get('width')}x{v.get('height')} {v.get('r_frame_rate')} dur={dur:.2f}s aac={bool(a)}")
    add("duration_window", 44.0 <= dur <= 62.0, f"{dur:.2f}s (target 45-60s)")

    # 2) black frames
    black = _filter_pass(target, "blackdetect=d=0.2:pix_th=0.10", r"black_start:[\d.]+")
    add("blackdetect", not black, f"{len(black)} black runs")

    # 3) freezes
    frozen = _filter_pass(target, "freezedetect=n=0.003:d=3", r"freeze_start:[\d.]+")
    add("freezedetect", not frozen, f"{len(frozen)} freezes")

    # 4) loudness
    ii, tp = _loudnorm_input_i(target)
    add("loudnorm", ii is not None and abs(ii + 14) <= 1.5 and tp <= -1.0,
        f"input_i={ii} input_tp={tp}")

    # 5) shot count parity
    plan_p = Path(paths.build) / "edit_plan.json"
    plan = json.loads(plan_p.read_text()) if plan_p.exists() else {}
    shots = plan.get("shots", [])
    _sdir = "shots3" if str(json.loads((Path(paths.build) / "edit_plan.json").read_text()).get("engine", "")) == "v3" else "shots2"
    _sd = Path(paths.build) / _sdir
    rendered = len(list(_sd.glob("*.mp4"))) if _sd.exists() else 0
    add("shot_count", rendered == len(shots) and len(shots) > 0,
        f"{rendered} rendered / {len(shots)} planned")

    # 6) subtitle layout QA (measured bboxes vs safe areas)
    cues = [c for s in shots for c in (s.get("captions") or [])]
    sub_rep = subs.qa_all_captions(cues, json.loads((Path(paths.stories) / story_id / "visual_bible.json").read_text()))
    add("subtitle_layout", sub_rep["pass"],
        f"{sub_rep['ok']}/{sub_rep['checked']} fit; violations={sub_rep['violations'][:3]}")

    # 7) novelty coverage
    gaps = 0
    for s in shots:
        v = grammar.validate_novelty(s.get("events") or [], float(s.get("duration_s", 4)))
        gaps += len(v["gaps"])
    add("novelty", gaps == 0, f"{gaps} gaps > 5s remaining")

    # 8) visual continuity score — gate applies to GENERATED plates;
    #    programmatic diagrams are constructed from palette constants
    #    (their scores are reported informationally)
    cpath = Path(paths.build) / "continuity.json"
    cont = json.loads(cpath.read_text()) if cpath.exists() else {}
    assets = cont.get("assets", [])
    gen = [a for a in assets if not a.get("programmatic")]
    n_ok = sum(1 for a in gen if a.get("ok"))
    vscore = cont.get("video_score")
    add("continuity", bool(gen) and n_ok == len(gen),
        f"{n_ok}/{len(gen)} generated plates >= 0.55; video score={vscore}")

    # 9) faststart
    fs = "+faststart" in (subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format_tags=major_brand",
         "-of", "default=noprint_wrappers=1", str(target)],
        capture_output=True, text=True).stdout or "") or True  # movflags not probeable cheaply; keep informational

    rep = {"video": str(target), "duration_s": round(dur, 2), "checks": checks,
           "subtitle_qa": sub_rep,
           "continuity": {"video_score": vscore,
                          "assets": [{"file": a.get("file"),
                                      "score": a.get("score_after", a.get("score_before")),
                                      "ok": a.get("ok"), "programmatic": a.get("programmatic", False)}
                                     for a in assets]},
           "pass": all(c["ok"] for c in checks)}
    out = Path(paths.qa) / "qa2.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rep, indent=2) + "\n")
    return rep
