"""QA: ffprobe sanity, black/freeze detection, loudness, shot count, contact
sheet. Writes build/qa/qa.json (+ qa/contact_sheet.jpg). Each check reports
pass / warn / fail with detail; overall = fail if any fail, else warn if any
warn, else pass."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path


def _run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)


def ffprobe_json(path):
    p = _run(["ffprobe", "-v", "error", "-print_format", "json",
              "-show_format", "-show_streams", str(path)])
    if p.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {p.stderr[-500:]}")
    return json.loads(p.stdout)


def _faststart(path):
    """True if the moov atom precedes mdat (progressive). None if unknown."""
    moov = mdat = None
    pos = 0
    with open(path, "rb") as f:
        while moov is None or mdat is None:
            chunk = f.read(1 << 20)
            if not chunk:
                break
            if moov is None and b"moov" in chunk:
                moov = pos + chunk.find(b"moov")
            if mdat is None and b"mdat" in chunk:
                mdat = pos + chunk.find(b"mdat")
            pos += len(chunk)
    if moov is None or mdat is None:
        return None
    return moov < mdat


def qa_video(path, paths, story_id="space_closer"):
    """Run all checks on a video -> report dict (also written to qa/qa.json)."""
    path = Path(path)
    rep = {"file": str(path), "checks": []}

    def add(name, status, detail):
        rep["checks"].append({"name": name, "status": status, "detail": detail})

    v = a = None
    fmt_dur = 0.0
    try:
        info = ffprobe_json(path)
        streams = info.get("streams") or []
        v = next((s for s in streams if s.get("codec_type") == "video"), None)
        a = next((s for s in streams if s.get("codec_type") == "audio"), None)
        fmt_dur = float(info.get("format", {}).get("duration") or 0)
        if v is None:
            add("streams", "fail", "no video stream")
        else:
            fs = _faststart(path)
            det = (f"{v.get('width')}x{v.get('height')} {v.get('r_frame_rate')} "
                   f"{v.get('pix_fmt')} dur={fmt_dur:.2f}s faststart={fs}")
            probs = []
            if (v.get("width"), v.get("height")) != (1080, 1920):
                probs.append(f"resolution {v.get('width')}x{v.get('height')} != 1080x1920")
            if v.get("r_frame_rate") not in ("30/1", "30"):
                probs.append(f"fps {v.get('r_frame_rate')} != 30")
            if v.get("pix_fmt") != "yuv420p":
                probs.append(f"pix_fmt {v.get('pix_fmt')} != yuv420p")
            if fs is False:
                probs.append("moov after mdat (no faststart)")
            if a is not None:
                dv = float(v.get("duration") or 0)
                da = float(a.get("duration") or 0)
                diff = abs(da - dv)
                det += f" A/V dur diff={diff:.2f}s"
                if diff > 0.5:
                    probs.append(f"A/V duration diff {diff:.2f}s > 0.5s")
            add("streams", "fail" if probs else "pass",
                det + ("; " + "; ".join(probs) if probs else ""))
    except Exception as e:  # noqa: BLE001 - report, don't crash QA
        add("streams", "fail", f"ffprobe error: {e}")

    try:
        p = _run(["ffmpeg", "-nostdin", "-v", "info", "-i", str(path), "-vf",
                  "blackdetect=d=0.2:pic_th=0.98", "-an", "-f", "null", "-"])
        runs = [(float(x), float(y)) for x, y in re.findall(
            r"black_start:([\d.]+) black_end:([\d.]+)", p.stderr)]
        bad = [(x, y) for (x, y) in runs if not (y <= 0.6 or x >= max(0.0, fmt_dur - 0.6))]
        if bad:
            add("blackdetect", "fail", f"black run(s) inside body (not first/last 0.6s): {bad}")
        elif runs:
            add("blackdetect", "warn", f"black run(s) only at edges: {runs}")
        else:
            add("blackdetect", "pass", "no black runs > 0.2s")
    except Exception as e:  # noqa: BLE001
        add("blackdetect", "warn", f"error: {e}")

    try:
        p = _run(["ffmpeg", "-nostdin", "-v", "info", "-i", str(path), "-vf",
                  "freezedetect=n=-60dB:d=3", "-an", "-f", "null", "-"])
        starts = re.findall(r"freeze_start:([\d.]+)", p.stderr)
        add("freezedetect", "warn" if starts else "pass",
            f"freeze(s) >=3s at {starts}" if starts else "no freezes >= 3s")
    except Exception as e:  # noqa: BLE001
        add("freezedetect", "warn", f"error: {e}")

    if a is not None:
        try:
            p = _run(["ffmpeg", "-nostdin", "-v", "info", "-i", str(path), "-af",
                      "loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json",
                      "-f", "null", "-"])
            ln = {}
            for blob in re.findall(r"\{[^{}]*\}", p.stderr):
                try:
                    d = json.loads(blob)
                    if "input_i" in d:
                        ln = d
                except json.JSONDecodeError:
                    pass
            if ln:
                ii = ln.get("input_i", "?")
                try:
                    ok = abs(float(ii) - (-14.0)) <= 2.0
                except ValueError:
                    ok = False  # e.g. "-inf" (silent track)
                add("loudnorm", "pass" if ok else "warn",
                    f"input_i={ii} input_tp={ln.get('input_tp')} "
                    f"(target I=-14 TP=-1.5 LRA=11)")
            else:
                add("loudnorm", "warn", "loudnorm output not parsed (silent audio?)")
        except Exception as e:  # noqa: BLE001
            add("loudnorm", "warn", f"error: {e}")
    else:
        add("loudnorm", "warn", "no audio stream (shots are silent by design)")

    try:
        ep = Path(paths.build) / "edit_plan.json"
        if ep.exists():
            eplan = json.loads(ep.read_text())
            planned = len(eplan.get("shots") or [])
            have = len(list(Path(paths.shots).glob("*.mp4"))) if Path(paths.shots).exists() else 0
            add("shot_count", "pass" if have == planned else "warn",
                f"{have} rendered shot mp4(s) / {planned} in edit_plan")
        else:
            add("shot_count", "warn", "no edit_plan.json (standalone/smoke file?)")
    except Exception as e:  # noqa: BLE001
        add("shot_count", "warn", f"error: {e}")

    try:
        out = contact_sheet(path, paths)
        add("contact_sheet", "pass" if out and Path(out).exists() else "warn", str(out))
    except Exception as e:  # noqa: BLE001
        add("contact_sheet", "warn", f"error: {e}")

    rep["summary"] = {
        "pass": sum(1 for c in rep["checks"] if c["status"] == "pass"),
        "warn": sum(1 for c in rep["checks"] if c["status"] == "warn"),
        "fail": sum(1 for c in rep["checks"] if c["status"] == "fail"),
    }
    rep["overall"] = ("fail" if rep["summary"]["fail"]
                      else "warn" if rep["summary"]["warn"] else "pass")
    out = Path(paths.qa) / "qa.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rep, indent=2) + "\n")
    return rep


def contact_sheet(path, paths, tiles=12, cols=3, rows=4):
    """12 evenly spaced frames -> 3x4 sheet at build/qa/contact_sheet.jpg."""
    path = Path(path)
    dur = float(ffprobe_json(path)["format"]["duration"] or 0)
    if dur <= 0:
        raise RuntimeError("bad duration for contact sheet")
    out = Path(paths.qa) / "contact_sheet.jpg"
    out.parent.mkdir(parents=True, exist_ok=True)
    vf = f"fps={tiles / dur:.6f},scale=180:320,tile={cols}x{rows}"
    p = _run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(path),
              "-vf", vf, "-frames:v", "1", "-q:v", "3", str(out)])
    if p.returncode != 0:
        raise RuntimeError(p.stderr[-500:])
    return out


def print_qa(rep):
    for c in rep["checks"]:
        print(f"- [{c['status'].upper():4}] {c['name']}: {c['detail']}")
    s = rep["summary"]
    print(f"qa: {s['pass']} pass, {s['warn']} warn, {s['fail']} fail -> {rep['overall'].upper()}")
