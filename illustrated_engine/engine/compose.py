"""ffmpeg composition: shot renderer + edit-plan concat.

Per shot (render_shot, standalone-safe for one-shot re-renders):
  plate.png -> lanczos scale -> letterbox pad -> zoompan camera (motion.grammar)
  -> pad into 1080x1920 black frame -> timed overlay PNGs (title band +
  shot overlays) -> subtitles=<shot>.ass (fontsdir=assets/fonts)
  -> libx264 crf18 preset medium, yuv420p, -threads 1, bitexact.

Final (render_video): reads build/edit_plan.json, renders missing/outdated
shots (mtime vs plate/ass/plan), then concats with per-shot transition_in:
  CUT -> concat | CROSSFADE -> xfade fade 0.4 | IMAGE_WIPE_UP -> xfade wipeup
  FADE -> fade-in on incoming shot + concat.
Audio: plan.audio_master mapped through loudnorm I=-14 TP=-1.5 LRA=11 when
present, else a silent stereo track. Output: output/final.mp4 (+faststart).

Determinism: -threads 1, no randomness, no timestamps in metadata
(-fflags +bitexact -flags +bitexact -map_metadata -1).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from . import motion
from .text_ass import build_ass, load_style, normalize_cues


def _run(cmd, desc):
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"ffmpeg failed ({desc}):\n{p.stderr[-2000:]}")
    return p


def overlay_throb_ok(paths):
    """One-time probe: does this ffmpeg support t-expressions in
    scale eval=frame (needed for the HIGHLIGHT 1.0->1.03 throb)?
    Result cached in build/.probe_scale_t; falls back to static overlays."""
    flag = Path(paths.build) / ".probe_scale_t"
    if flag.exists():
        return flag.read_text().strip() == "1"
    cmd = ["ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi",
           "-i", "color=c=red:s=64x64:r=30:d=0.4",
           "-vf", "scale=w='iw*(1+0.01*(1-cos(2*PI*t/0.4)))':h='ih':eval=frame",
           "-frames:v", "4", "-f", "null", "-"]
    try:
        ok = subprocess.run(cmd, capture_output=True).returncode == 0
    except OSError:
        ok = False
    Path(paths.build).mkdir(parents=True, exist_ok=True)
    flag.write_text("1" if ok else "0")
    return ok


def ensure_shot_ass(shot, paths, ass_path, style):
    """Build the shot's .ass from its captions/typography (empty if none)."""
    return build_ass(normalize_cues(shot), ass_path, style)


def _plate_path(paths, asset):
    a = str(asset)
    cand = Path(a)
    if a.endswith(".png") and cand.exists():
        return cand
    return Path(paths.assets) / f"{a}.png"


def render_shot(shot, paths, out_path=None, ass_path=None, throb=None):
    """Render one shot dict -> build/shots/<shot_id>.mp4 (or out_path)."""
    paths.ensure_dirs()
    style = load_style(paths)
    shot_id = str(shot.get("shot_id", "shot"))
    plate = _plate_path(paths, shot["asset"])
    if not plate.exists():
        raise FileNotFoundError(f"plate asset missing: {plate} (shot {shot_id})")
    dur = float(shot["duration_s"])
    if dur <= 0:
        raise ValueError(f"{shot_id}: duration_s must be > 0")
    out_path = Path(out_path) if out_path else Path(paths.shots) / f"{shot_id}.mp4"
    ass_path = Path(ass_path) if ass_path else Path(paths.ass) / f"{shot_id}.ass"
    if not ass_path.exists():
        ensure_shot_ass(shot, paths, ass_path, style)

    cam_frag, _n, prim, _notes = motion.camera_filter(shot.get("camera", {}), dur)
    throb = overlay_throb_ok(paths) if throb is None else throb

    overlays = [{"kind": "TITLE_BAND"}]
    if prim == "FOCUS_REVEAL" and not any(
            o.get("kind") == "HIGHLIGHT" for o in shot.get("overlays") or []):
        overlays.append({"kind": "HIGHLIGHT", "style": "ring", "color": "slate",
                         "target": {"x": 0.06, "y": 0.05, "w": 0.88, "h": 0.90},
                         "at": min(0.6, dur * 0.25), "dur": max(1.0, dur - 1.2)})
    overlays += list(shot.get("overlays") or [])

    sublayers = []
    for ov in overlays:
        sublayers.extend(motion.compile_overlay(ov, dur, paths.overlays, style,
                                                throb_ok=throb))

    graph = [f"[0:v]{cam_frag},pad={motion.PANEL_W}:{motion.FRAME_H}:0:"
             f"{motion.PANEL_Y}:color=black[base]"]
    cur = "base"
    idx = 1
    for sl in sublayers:
        graph.append(f"[{idx}:v]format=rgba{sl['pre']}[ov{idx}]")
        en = f":enable='{sl['enable']}'" if sl.get("enable") else ""
        graph.append(f"[{cur}][ov{idx}]overlay=x='{sl['x']}':y='{sl['y']}'{en}[v{idx}]")
        cur = f"v{idx}"
        idx += 1
    graph.append(f"[{cur}]format=yuv420p,"
                 f"subtitles=filename='{ass_path}':fontsdir='{paths.fonts}'[vout]")

    cmd = ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
           "-i", str(plate)]
    for sl in sublayers:
        cmd += ["-framerate", "30", "-loop", "1", "-t", f"{dur:.6f}", "-i", str(sl["png"])]
    cmd += ["-filter_complex", ";".join(graph), "-map", "[vout]",
            "-c:v", "libx264", "-preset", "medium", "-crf", "18",
            "-pix_fmt", "yuv420p", "-threads", "1", "-r", "30",
            "-flags:v", "+bitexact", "-map_metadata", "-1",
            "-fflags", "+bitexact", "-movflags", "+faststart",
            str(out_path)]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    _run(cmd, f"render shot {shot_id}")
    return out_path


def probe_duration(path):
    p = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json",
                        "-show_entries", "format=duration", str(path)],
                       capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"ffprobe failed on {path}: {p.stderr[-500:]}")
    return float(json.loads(p.stdout)["format"]["duration"])


def _shot_stale(out_path, sources):
    if not out_path.exists():
        return True
    m = out_path.stat().st_mtime
    return any(s.stat().st_mtime > m for s in sources if s.exists())


def render_video(paths, force=False):
    """Render missing/outdated shots from build/edit_plan.json, then concat."""
    plan_path = Path(paths.build) / "edit_plan.json"
    if not plan_path.exists():
        raise FileNotFoundError(
            "build/edit_plan.json missing - run: python3 cli.py validate --make-edit-plan")
    plan = json.loads(plan_path.read_text())
    shots = plan.get("shots") or []
    if not shots:
        raise ValueError("edit_plan.json has no shots")
    paths.ensure_dirs()
    durs = []
    for s in shots:
        sid = str(s["shot_id"])
        out = Path(paths.shots) / f"{sid}.mp4"
        ass = Path(paths.ass) / f"{sid}.ass"
        if force or _shot_stale(out, [_plate_path(paths, s["asset"]), ass, plan_path]):
            render_shot(s, paths, out_path=out, ass_path=ass)
        durs.append(probe_duration(out))
    return _concat(paths, plan, shots, durs)


def _concat(paths, plan, shots, durs):
    """Pairwise transition chain -> output/final.mp4 (+ audio track)."""
    n = len(shots)
    cmd = ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y"]
    for s in shots:
        cmd += ["-i", str(Path(paths.shots) / f"{s['shot_id']}.mp4")]

    audio = plan.get("audio_master")
    apath = None
    if audio:
        cand = Path(audio)
        apath = cand if cand.is_absolute() and cand.exists() else None
        if apath is None:
            cand = Path(paths.root) / audio
            apath = cand if cand.exists() else None
    if apath is not None:
        cmd += ["-i", str(apath)]
        a_chain = ("loudnorm=I=-14:TP=-1.5:LRA=11,"
                   "aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo")
    else:
        cmd += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
        a_chain = "anull"

    graph = []
    for i in range(n):
        graph.append(f"[{i}:v]settb=AVTB,fps=30,format=yuv420p[v{i}]")
    cur = "v0"
    running = durs[0]
    for i in range(1, n):
        t = str(shots[i].get("transition_in", "CUT")).upper()
        if t in motion.XFADE_MAP and durs[i] > motion.XFADE_DUR + 0.1 \
                and running > motion.XFADE_DUR:
            off = max(0.0, running - motion.XFADE_DUR)
            graph.append(f"[{cur}][v{i}]xfade=transition={motion.XFADE_MAP[t]}:"
                         f"duration={motion.XFADE_DUR}:offset={off:.6f}[x{i}r]")
            graph.append(f"[x{i}r]settb=AVTB[x{i}]")
            cur = f"x{i}"
            running = off + durs[i]
        else:
            if t == "FADE":
                fd = min(motion.FADE_DUR, durs[i] / 2.0)
                graph.append(f"[v{i}]fade=t=in:st=0:d={fd:.3f}[f{i}]")
                src = f"f{i}"
            else:
                src = f"v{i}"
            graph.append(f"[{cur}][{src}]concat=n=2:v=1:a=0[c{i}]")
            cur = f"c{i}"
            running += durs[i]
    graph.append(f"[{n}:a]{a_chain}[aout]")

    out = Path(paths.output) / "final.mp4"
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd += ["-filter_complex", ";".join(graph), "-map", f"[{cur}]", "-map", "[aout]",
            "-c:v", "libx264", "-preset", "medium", "-crf", "18",
            "-pix_fmt", "yuv420p", "-r", "30", "-threads", "1",
            "-c:a", "aac", "-b:a", "192k", "-shortest",
            "-flags:v", "+bitexact", "-flags:a", "+bitexact",
            "-map_metadata", "-1", "-fflags", "+bitexact",
            "-movflags", "+faststart", str(out)]
    _run(cmd, "concat final")
    return out
