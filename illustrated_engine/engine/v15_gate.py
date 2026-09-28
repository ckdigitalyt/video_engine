"""V15 — honest publish gate: content, not just plumbing.

V14's gate = codecs + durations + camera smoothness; it stamped PASS on two
videos with wrong-beat captions, an empty scale dive and overflowing text.
V15 adds a handful of HARD deterministic checks computed from the artifacts,
plus ONE vision-judge call (directive §28/§29 — lightweight, no metric zoo):

  caption_identity  burned overlay texts, in time order, == the narration
                    word sequence; each cue lies inside its own beat; every
                    overlay PNG exists and is unique per (text, word)
  text_bounds       every fitted on-screen text box inside the safe frame and
                    clear of the caption band (spec.meta.text_boxes)
  info_floor        sampled pre-caption frames (every 2 s, caption band
                    excluded) must carry visual information: luminance std
                    and edge density above floors (a flat field fails)
  visual_hold       no stretch > MAX_HOLD_S without a visual state change
                    (shot cut or an on-word reveal)
  asset_tier        HOOK/PAYOFF shots must be plate tier; plates that still
                    fail plate QA after regeneration fail the gate
  audio             integrated loudness within target; voice present
  av                final has h264 + aac, duration == scene sum (+-0.1 s)
  judge             1 call on a labelled contact sheet: §28 questions per
                    frame (closed issue enum) + §29 hook/ending/template;
                    critical failures HOLD. Judge unavailable -> HOLD
                    ("unverified"), never a silent pass.

verdict: PASS only when every check passes; else HOLD with reasons.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
MAX_HOLD_S = 4.5
CAPTION_BAND = (1440.0, 1680.0)
SAFE = (40.0, 60.0, 1040.0)          # x0, y0, x1
FLOOR_STD, FLOOR_EDGE = 14.0, 2.2    # calibrated: V14 flat navy fails
LUFS_RANGE = (-16.5, -11.5)
JUDGE_ISSUES = ("none", "empty_or_flat", "subject_unrecognizable",
                "not_story_specific", "text_garbled", "text_unreadable",
                "no_change", "too_dark")
_W = re.compile(r"[^\w.%°'-]+")


def _norm_words(text: str) -> list:
    out = []
    for w in str(text).split():
        w = _W.sub("", w.lower()).strip(".-'")
        if w:
            out.append(w)
    return out


# ------------------------------------------------------------ checks --

def check_caption_identity(overlays: list, story: dict, beat_windows: dict) -> dict:
    """overlays: assembly caption_overlays [{png, t0, t1, cue, text, word}]."""
    fails = []
    if not overlays:
        return {"ok": False, "fails": ["no caption overlays recorded"]}
    seen, cue_seq = {}, []
    for o in sorted(overlays, key=lambda x: x["t0"]):
        if not Path(o["png"]).exists():
            fails.append(f"missing overlay png {o['png']}")
        k = (o.get("text"), o.get("word"))
        if o["png"] in seen and seen[o["png"]] != k:
            fails.append(f"png reused for different text: {Path(o['png']).name}")
        seen[o["png"]] = k
        if not cue_seq or cue_seq[-1][0] != o.get("text") or \
                o["t0"] - cue_seq[-1][2] > 0.05:
            cue_seq.append([o.get("text"), o["t0"], o["t1"]])
        else:
            cue_seq[-1][2] = o["t1"]
    burned = [w for c in cue_seq for w in _norm_words(c[0])]
    spoken = [w for b in story["beats"] for w in _norm_words(b["narration"])]
    if burned != spoken:
        i = next((k for k, (a, b) in enumerate(zip(burned, spoken)) if a != b),
                 min(len(burned), len(spoken)))
        fails.append(f"caption words != narration at word {i}: burned "
                     f"{burned[i:i + 5]} vs spoken {spoken[i:i + 5]} "
                     f"({len(burned)} vs {len(spoken)} words)")
    # each cue inside the beat that speaks it
    wi = 0
    bounds = []
    for b in story["beats"]:
        n = len(_norm_words(b["narration"]))
        bounds.append((wi, wi + n, b["beat_id"]))
        wi += n
    wi = 0
    for text, t0, t1 in cue_seq:
        n = len(_norm_words(text))
        bid = next((bb for a, z, bb in bounds if a <= wi < z), None)
        if bid and bid in beat_windows:
            s, e = beat_windows[bid]
            if t0 < s - 0.05 or t1 > e + 0.05:
                fails.append(f"cue {text!r} [{t0:.2f},{t1:.2f}] outside its "
                             f"beat {bid} [{s:.2f},{e:.2f}]")
        wi += n
    return {"ok": not fails, "fails": fails[:10], "cues": len(cue_seq),
            "words": len(burned)}


def check_text_bounds(specs: dict) -> dict:
    fails = []
    n = 0
    for key, spec in specs.items():
        for tb in (spec.get("meta") or {}).get("text_boxes") or []:
            n += 1
            x0, y0, x1, y1 = tb["box"]
            if x0 < SAFE[0] or x1 > SAFE[2] or y0 < SAFE[1]:
                fails.append(f"{key}.{tb['id']} {tb['text']!r} outside safe "
                             f"frame {[round(v) for v in tb['box']]}")
            if y1 > CAPTION_BAND[0] and y0 < CAPTION_BAND[1]:
                fails.append(f"{key}.{tb['id']} {tb['text']!r} overlaps the "
                             f"caption band")
    return {"ok": not fails, "fails": fails[:10], "boxes": n}


def _frames(video: Path, every: float, out_dir: Path) -> list:
    out_dir.mkdir(parents=True, exist_ok=True)
    for f in out_dir.glob("f_*.png"):
        f.unlink()
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(video), "-vf",
                    f"fps=1/{every},scale=270:480", str(out_dir / "f_%03d.png")],
                   check=True)
    return sorted(out_dir.glob("f_*.png"))


def frame_information(path: Path) -> dict:
    a = np.asarray(Image.open(path).convert("L"), dtype=np.float32)
    band = (int(CAPTION_BAND[0] / 4), int(CAPTION_BAND[1] / 4))
    a = np.concatenate([a[:band[0]], a[band[1]:]], axis=0)
    gy, gx = np.gradient(a)
    return {"std": round(float(a.std()), 2),
            "edge": round(float(np.hypot(gx, gy).mean()), 2)}


def check_info_floor(scene_videos: list, work: Path, every: float = 2.0) -> dict:
    """Pre-caption frames, sampled from the scene renders themselves."""
    fails, rows = [], []
    t0 = 0.0
    samples = []
    for k, v in enumerate(scene_videos):
        fr = _frames(v, every, work / "gate_frames" / f"s{k:02d}")
        samples += [(t0 + every * (i + 0.5), f) for i, f in enumerate(fr)]
        p = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                            "format=duration", "-of", "csv=p=0", str(v)],
                           capture_output=True, text=True)
        t0 += float(p.stdout.strip() or 0)
    for t, f in samples:
        m = frame_information(f)
        t = round(t, 1)
        rows.append(dict(m, t=t))
        if m["std"] < FLOOR_STD or m["edge"] < FLOOR_EDGE:
            fails.append(f"t~{t}s low information (std {m['std']}, "
                         f"edge {m['edge']})")
    return {"ok": not fails, "fails": fails[:10], "frames": rows}


def check_visual_hold(meta: dict, specs: dict) -> dict:
    """State changes = shot starts + on-word reveals (layers with a
    visibility start > 0.05 s inside the shot)."""
    events = []
    t_end = 0.0
    starts = {}
    t = 0.0
    for key, m in meta.items():  # insertion order == timeline order
        starts[key] = t
        events.append(t)
        for lay in specs[key]["layers"]:
            vis = lay.get("visibility")
            if vis and vis[0] > 0.05 and lay["type"] in (
                    "text", "semantic_annotation") or (
                    vis and vis[0] > 0.05 and lay["id"].endswith("_world")):
                events.append(t + float(vis[0]))
        t += float(specs[key]["duration_s"])
    t_end = t
    events = sorted(set(round(e, 2) for e in events)) + [round(t_end, 2)]
    gaps = [(events[i], events[i + 1] - events[i])
            for i in range(len(events) - 1)]
    worst = max(gaps, key=lambda g: g[1]) if gaps else (0, 0)
    fails = [f"{g:.1f}s without a visual change from t={a:.1f}s"
             for a, g in gaps if g > MAX_HOLD_S]
    return {"ok": not fails, "fails": fails, "max_hold_s": round(worst[1], 2),
            "changes": len(events) - 1}


def check_assets(meta: dict) -> dict:
    fails, warns = [], []
    for key, m in meta.items():
        if m.get("qa_fail"):
            fails.append(f"{key}: plate still fails plate QA after regeneration")
        if m["tier"] != "plate":
            msg = f"{key}: asset tier {m['tier']}"
            (fails if m.get("function") in ("HOOK", "PAYOFF") else warns).append(msg)
    return {"ok": not fails, "fails": fails, "warnings": warns}


def check_audio(final: Path, voice_wav: Path) -> dict:
    fails = []
    p = subprocess.run(["ffmpeg", "-nostats", "-i", str(final), "-af",
                        "ebur128=framelog=quiet", "-f", "null", "-"],
                       capture_output=True, text=True)
    m = re.findall(r"I:\s+(-?[\d.]+) LUFS", p.stderr)
    lufs = float(m[-1]) if m else None
    if lufs is None or not (LUFS_RANGE[0] <= lufs <= LUFS_RANGE[1]):
        fails.append(f"integrated loudness {lufs} LUFS outside {LUFS_RANGE}")
    voice_rms = None
    if voice_wav.exists():
        from engine.procedural_audio import load_wav
        v = load_wav(voice_wav)
        voice_rms = round(float(np.sqrt((v ** 2).mean())), 4)
        if voice_rms < 0.01:
            fails.append(f"voice stem near-silent (rms {voice_rms})")
    return {"ok": not fails, "fails": fails, "lufs": lufs,
            "voice_rms": voice_rms}


def check_av(final: Path, specs: dict) -> dict:
    p = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json",
                        "-show_format", "-show_streams", str(final)],
                       capture_output=True, text=True)
    fails = []
    try:
        info = json.loads(p.stdout)
        codecs = {s["codec_name"] for s in info["streams"]}
        dur = float(info["format"]["duration"])
    except Exception:
        return {"ok": False, "fails": ["final.mp4 unreadable"]}
    want = sum(float(s["duration_s"]) for s in specs.values())
    if not {"h264", "aac"} <= codecs:
        fails.append(f"codecs {sorted(codecs)} (need h264 + aac)")
    if abs(dur - want) > 0.15:
        fails.append(f"duration {dur:.2f}s != scene sum {want:.2f}s")
    return {"ok": not fails, "fails": fails, "duration_s": round(dur, 2),
            "codecs": sorted(codecs)}


# -------------------------------------------------------------- judge --

JUDGE_Q = """You are a demanding short-form video editor reviewing an explainer
video "{title}" frame by frame (contact sheet: {n} numbered frames, ~{step}s
apart, with the narration spoken at that moment underneath each).
For EACH frame answer: does the picture itself communicate something specific
to this story (not generic decoration), is it visually rich and readable?
The small caption bar near the bottom is burned-in narration shown a few
words at a time: a phrase FRAGMENT is expected there and is NOT an issue.
"text_garbled" means misspelled/illegible lettering (inside the artwork or
in the large on-screen typography).
Issue codes: {issues}.
Then judge the whole: first frame would stop a scroll? ending resolves the
opening question? would the scenes work unchanged for another topic by only
swapping nouns (template feel)?
Return ONLY JSON:
{{"frames":[{{"n":1,"ok":true,"issue":"none"}}],
 "hook_stops_scroll":true,"ending_resolves":true,"template_feel":false,
 "notes":"<one sentence>"}}"""


def _judge_sheet(video: Path, story: dict, beat_windows: dict, out: Path,
                 step: float) -> tuple:
    frames = _frames(video, step, out.parent / "judge_frames")
    narr_at = []
    for i, _f in enumerate(frames):
        t = step * (i + 0.5)
        bid = next((b for b, (s, e) in beat_windows.items() if s <= t < e),
                   None)
        text = next((b["narration"] for b in story["beats"]
                     if b["beat_id"] == bid), "")
        narr_at.append((t, bid, text))
    cols, tw, th, cap = 6, 216, 384, 64
    rows = -(-len(frames) // cols)
    sheet = Image.new("RGB", (cols * tw, rows * (th + cap)), (15, 15, 15))
    d = ImageDraw.Draw(sheet)
    try:
        f = ImageFont.truetype(str(ROOT / "assets/fonts/Inter-Variable.ttf"), 13)
    except Exception:
        f = None
    for i, fp in enumerate(frames):
        x, y = (i % cols) * tw, (i // cols) * (th + cap)
        sheet.paste(Image.open(fp).convert("RGB").resize((tw, th)), (x, y))
        t, bid, text = narr_at[i]
        d.text((x + 4, y + th + 2), f"#{i + 1} {t:.0f}s {bid}", fill=(255, 210, 80),
               font=f)
        words = text.split()
        lines, cur = [], ""
        for w in words:
            if len(cur) + len(w) > 34:
                lines.append(cur)
                cur = w
            else:
                cur = (cur + " " + w).strip()
        lines.append(cur)
        for k, ln in enumerate(lines[:3]):
            d.text((x + 4, y + th + 18 + 14 * k), ln, fill=(220, 220, 220), font=f)
    sheet.save(out, "JPEG", quality=85)
    return out, len(frames)


def run_judge(video: Path, story: dict, beat_windows: dict, work: Path,
              step: float = 3.5) -> dict:
    from engine.director import vision_ask
    sheet, n = _judge_sheet(video, story, beat_windows, work / "judge_sheet.jpg",
                            step)
    ans = vision_ask(sheet, JUDGE_Q.format(
        title=story.get("title", story["story_id"]), n=n, step=step,
        issues=", ".join(JUDGE_ISSUES)), max_tokens=900,
        stage="final_judge")
    if not isinstance(ans, dict) or "frames" not in ans:
        return {"ok": False, "unverified": True, "raw": ans,
                "fails": ["judge unavailable/unparseable -> unverified"]}
    frames = [f for f in ans.get("frames") or [] if isinstance(f, dict)]
    bad = [f for f in frames if not f.get("ok", True)
           and f.get("issue") not in (None, "none")]
    crit = [f for f in bad if f.get("issue") in (
        "empty_or_flat", "subject_unrecognizable", "text_garbled",
        "text_unreadable", "too_dark")]
    fails = []
    if frames and len(bad) / len(frames) > 0.25:
        fails.append(f"judge flagged {len(bad)}/{len(frames)} frames")
    if len(crit) >= 2:
        fails.append("critical frame issues: " + ", ".join(
            f"#{f.get('n')} {f.get('issue')}" for f in crit[:6]))
    if ans.get("hook_stops_scroll") is False:
        fails.append("judge: first frame would not stop a scroll")
    if ans.get("template_feel") is True:
        fails.append("judge: scenes feel templated (noun-swap reusable)")
    return {"ok": not fails, "fails": fails, "frames_flagged": [
        {"n": f.get("n"), "issue": f.get("issue")} for f in bad],
        "hook_stops_scroll": ans.get("hook_stops_scroll"),
        "ending_resolves": ans.get("ending_resolves"),
        "template_feel": ans.get("template_feel"),
        "notes": ans.get("notes"), "sheet": str(sheet)}


# ---------------------------------------------------------------- run --

def run_gate(work: Path, story: dict, meta: dict, specs: dict, timing: dict,
             captions: dict, lead: float, *, use_judge: bool = True) -> dict:
    work = Path(work)
    arep = json.loads((work / "assembly_report.json").read_text()) \
        if (work / "assembly_report.json").exists() else {}
    t = 0.0
    beat_windows = {}
    for key, m in meta.items():
        s, e = beat_windows.get(m["beat"], (t, t))
        beat_windows[m["beat"]] = (min(s, t), t + float(specs[key]["duration_s"]))
        t += float(specs[key]["duration_s"])
    checks = {
        "caption_identity": check_caption_identity(
            arep.get("caption_overlays") or [], story, beat_windows),
        "text_bounds": check_text_bounds(specs),
        "info_floor": check_info_floor(
            [work / "scenes" / f"{k}.mp4" for k in meta], work),
        "visual_hold": check_visual_hold(meta, specs),
        "asset_tier": check_assets(meta),
        "audio": check_audio(work / "final.mp4", work / "voice.wav"),
        "av": check_av(work / "final.mp4", specs),
    }
    calls = 0
    if use_judge:
        checks["judge"] = run_judge(work / "final.mp4", story, beat_windows,
                                    work)
        calls = 1
    else:
        checks["judge"] = {"ok": False, "unverified": True,
                           "fails": ["judge disabled (--no-judge) -> unverified"]}
    failures = {k: v["fails"] for k, v in checks.items() if not v["ok"]}
    return {"verdict": "PASS" if not failures else "HOLD",
            "failures": failures, "checks": checks, "judge_calls": calls,
            "beat_windows": {k: [round(a, 2), round(b, 2)]
                             for k, (a, b) in beat_windows.items()}}
