"""v2 renderer — full-bleed 9:16 composition, grammar cameras, baked overlays.

Per shot:
  1. camera canvas = smart-cropped plate at (1080*Smax, 1328*Smax)
  2. zoompan camera (piecewise if a retarget event exists) -> 1080x1328
  3. static base frame (background chrome + brand/title block)
  4. overlays: clause captions (RGBA PNGs, enable windows, 0.12s alpha ramp),
     number pops, highlights, emphasis rules
  5. fade-in from Bible background colour -> encode (deterministic, -threads 1)
Video: concat demuxer (-c:v copy) + narration-first audio master + loudnorm.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from engine import grammar, layout, subs
from engine.layout import CANVAS_W, CANVAS_H, VISUAL_RECT, CAPTION_RECT, _font

VX, VY, VW, VH = VISUAL_RECT
BG_HEX = None  # resolved per bible


def _bg_hex(bible) -> str:
    from engine import bible as B
    r, g, b = B.rgb255(bible, "background")
    return f"0x{r:02X}{g:02X}{b:02X}"


def _abs_rect(rect_norm, pad=0.0):
    """Normalized visual-zone rect [x,y,w,h] -> absolute frame rect."""
    x, y, w, h = rect_norm
    return (VX + x * VW, VY + y * VH, w * VW, h * VH)


def _fonts(bible):
    typ = bible.get("typography", {})
    disp = _font(typ.get("display", "BebasNeue-Regular.ttf"), 92)
    return disp


# ------------------------------------------------------------- overlays -----

def caption_png(cue: dict, bible: dict, out: Path) -> dict:
    """Full-frame transparent RGBA with one caption block baked. -> layout."""
    img = Image.new("RGBA", (CANVAS_W, CANVAS_H), (0, 0, 0, 0))
    lay = subs.layout_caption(cue["text"], bible)
    if not lay.get("ok"):
        lay = subs.layout_caption(cue["text"], bible)  # retry (idempotent)
    if not lay.get("ok"):
        img.save(out, "PNG")
        return lay
    d = ImageDraw.Draw(img)
    from engine import bible as B
    text_col = B.rgb255(bible, "text") + (255,)
    accent = B.rgb255(bible, "accent") + (255,)
    shadow = (0, 0, 0, 120)
    f = lay["font"]
    y = lay["y0"]
    for ln in lay["lines"]:
        lw = sum(f.getlength(t) for t in ln) + f.getlength(" ") * (len(ln) - 1)
        x = (CANVAS_W - lw) / 2
        for tok in ln:
            tok_clean = tok.strip(",.")
            is_num = bool(subs._NUM.fullmatch(tok_clean)) or tok_clean in lay["emph"]
            col = accent if is_num else text_col
            d.text((x + 2, y + 4), tok, font=f, fill=shadow)
            d.text((x, y), tok, font=f, fill=col)
            x += f.getlength(tok) + f.getlength(" ")
        y += lay["line_h"]
    img.save(out, "PNG")
    lay["png"] = str(out)
    return lay


def number_png(text: str, rect_norm, bible: dict, out: Path) -> None:
    """Number pop: display font, accent colour, at the region anchor."""
    from engine import bible as B
    img = Image.new("RGBA", (CANVAS_W, CANVAS_H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    ax, ay, aw, ah = _abs_rect(rect_norm)
    f = _font(bible["typography"].get("display", "BebasNeue-Regular.ttf"), 96)
    tw = d.textlength(text, font=f)
    x = ax + (aw - tw) / 2
    y = ay + 8
    d.text((x + 3, y + 5), text, font=f, fill=(0, 0, 0, 150))
    d.text((x, y), text, font=f, fill=B.rgb255(bible, "accent") + (255,))
    img.save(out, "PNG")


def highlight_png(rect_norm, style: str, bible: dict, out: Path) -> None:
    """Restrained annotation: accent outline (+whisper fill), no animation."""
    from engine import bible as B
    img = Image.new("RGBA", (CANVAS_W, CANVAS_H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img, "RGBA")
    x, y, w, h = _abs_rect(rect_norm)
    box = [x, y, x + w, y + h]
    accent = B.rgb255(bible, "accent")
    if str(style).startswith("circ"):
        d.ellipse(box, fill=accent + (26,), outline=accent + (210,), width=5)
    else:
        d.rounded_rectangle(box, radius=10, fill=accent + (22,),
                            outline=accent + (210,), width=5)
    img.save(out, "PNG")


def rule_png(bible: dict, out: Path, y: float = None) -> None:
    """Emphasis rule: short accent line under the caption block."""
    from engine import bible as B
    img = Image.new("RGBA", (CANVAS_W, CANVAS_H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img, "RGBA")
    yy = y if y else CAPTION_RECT[1] + CAPTION_RECT[3] - 52
    d.line([(CANVAS_W / 2 - 80, yy), (CANVAS_W / 2 + 80, yy)],
           fill=B.rgb255(bible, "accent") + (220,), width=4)
    img.save(out, "PNG")


# ---------------------------------------------------------------- frames ----

def base_frame(shot: dict, bible: dict) -> Image.Image:
    """Chrome: background + brand block (opening title / marker / endcard)."""
    from engine import bible as B
    frame = layout.base_frame(bible)
    d = ImageDraw.Draw(frame, "RGBA")
    typ = bible.get("typography", {})
    text_col = B.rgb255(bible, "text") + (255,)
    muted = B.rgb255(bible, "muted") + (200,)
    bx, by, bw, bh = layout.BRAND_RECT
    if shot.get("opening") and shot.get("title"):
        title = str(shot["title"]).upper()
        # width-fit stepping — protect longer titles (Bebas at 84px overflows on
        # 39+ char lines). Step down in 6pt increments until within 2*64 margin.
        size, max_w = 84, CANVAS_W - 2 * 64
        f = _font(typ.get("display", "BebasNeue-Regular.ttf"), size)
        while d.textlength(title, font=f) > max_w and size > 40:
            size -= 6
            f = _font(typ.get("display", "BebasNeue-Regular.ttf"), size)
        tw = d.textlength(title, font=f)
        d.text(((CANVAS_W - tw) / 2, by + (bh - size) / 2 - 6), title,
               font=f, fill=text_col)
    elif shot.get("end_card"):
        mark = str(shot["end_card"]).upper()
        f = _font(typ.get("display", "BebasNeue-Regular.ttf"), 44)
        tw = d.textlength(mark, font=f)
        d.text(((CANVAS_W - tw) / 2, by + (bh - 44) / 2 - 4), mark, font=f, fill=text_col)
    else:
        marker = str(bible.get("brand", "")).upper()
        f = _font(typ.get("body", "Inter-Variable.ttf"), 26)
        d.text((64, by + (bh - 26) / 2 - 4), marker, font=f, fill=muted)
        tag = str(shot.get("tag", ""))
        if tag:
            ft = _font(typ.get("body", "Inter-Variable.ttf"), 22)
            ttw = d.textlength(tag.upper(), font=ft)
            d.text((CANVAS_W - 64 - ttw, by + (bh - 22) / 2), tag.upper(), font=ft, fill=muted)
    return frame


def camera_canvas(shot: dict, paths, bible: dict):
    """Cover-crop the plate at max camera scale. -> (png path, smax)."""
    cam = shot["camera"]
    smax = max(float(cam["from_scale"]), float(cam["to_scale"]))
    W_c, H_c = int(round(VW * smax)), int(round(VH * smax))
    plate = Path(paths.assets) / f"{shot['asset']}.png"
    img = layout.smart_crop(Image.open(plate), W_c, H_c,
                            bias_y=float(shot.get("crop_bias_y", 0.42)))
    out = Path(paths.build) / "cam" / f"{shot['shot_id']}_canvas.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, "PNG")
    return out, smax, W_c, H_c


def zoompan_filter(shot: dict, smax: float, W_c: int, H_c: int) -> str:
    """Grammar camera -> zoompan expression (piecewise for one retarget)."""
    cam = shot["camera"]
    dur = float(shot["duration_s"])
    N = max(2, int(round(dur * 30)))
    z_from = smax * float(cam["from_scale"])
    z_to = smax * float(cam["to_scale"])
    retgt = next((e for e in shot.get("events", []) if e["kind"] == "camera_retgt"), None)
    if retgt:
        n1 = max(2, min(N - 2, int(float(retgt["t"]) * 30)))
        z_mid = (z_from + z_to) / 2.0
        z = (f"if(lte(on,{n1}),{z_from:.4f}+({z_mid:.4f}-{z_from:.4f})*on/{n1},"
             f"{z_mid:.4f}+({z_to:.4f}-{z_mid:.4f})*(on-{n1})/{max(1, N - n1)})")
    else:
        z = f"{z_from:.4f}+({z_to:.4f}-{z_from:.4f})*min(on,{N})/{N}"
    pan = cam.get("pan")
    if pan and pan[0] == "x":
        f0, f1 = float(pan[1]), float(pan[2])
        x = f"(iw-iw/zoom)*({f0:.3f}+({f1:.3f}-{f0:.3f})*min(on,{N})/{N})"
        y = "(ih-ih/zoom)/2"
    elif cam.get("cx") is not None or cam.get("cy") is not None:
        cx = float(cam.get("cx", 0.5))
        cy = float(cam.get("cy", 0.5))
        x = f"max(0,min(iw-iw/zoom,{cx:.3f}*iw-iw/zoom/2))"
        y = f"max(0,min(ih-ih/zoom,{cy:.3f}*ih-ih/zoom/2))"
    else:
        x = "(iw-iw/zoom)/2"
        y = "(ih-ih/zoom)/2"
    return f"zoompan=z='{z}':x='{x}':y='{y}':d=1:s={VW}x{VH}:fps=30"


# ------------------------------------------------------------ shot render ---

def render_shot_v2(shot: dict, paths, bible: dict, force: bool = False) -> Path:
    out = Path(paths.build) / "shots2" / f"{shot['shot_id']}.mp4"
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists() and not force:
        return out
    dur = float(shot["duration_s"])
    work = Path(paths.build) / "ov2" / shot["shot_id"]
    work.mkdir(parents=True, exist_ok=True)

    canvas, smax, W_c, H_c = camera_canvas(shot, paths, bible)
    base = base_frame(shot, bible)
    base_png = work / "base.png"
    base.save(base_png, "PNG")

    cmd = ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
           "-loop", "1", "-framerate", "30", "-t", f"{dur:.3f}", "-i", str(canvas),
           "-loop", "1", "-framerate", "30", "-t", f"{dur:.3f}", "-i", str(base_png)]
    graph = [f"[0:v]{zoompan_filter(shot, smax, W_c, H_c)}[cam]",
             f"[1:v][cam]overlay=0:{VY}[b]"]
    last = "b"
    idx = 2

    # captions (RGBA, alpha ramp, enable windows)
    cap_layouts = []
    for i, cue in enumerate(shot.get("captions", []) or []):
        png = work / f"cap{i}.png"
        lay = caption_png(cue, bible, png)
        cap_layouts.append(lay)
        if not lay.get("ok") or not lay.get("png"):
            continue
        cmd += ["-loop", "1", "-framerate", "30", "-t", f"{dur:.3f}", "-i", png]
        graph.append(f"[{idx}:v]format=rgba,fade=t=in:st=0:d=0.12:alpha=1[c{i}]")
        graph.append(f"[{last}][c{i}]overlay=0:0:enable='between(t,{cue['t0']:.3f},{cue['t1']:.3f})'[bc{i}]")
        last = f"bc{i}"
        idx += 1

    # events: number pops, highlights, emphasis rules
    for i, ev in enumerate(shot.get("events", []) or []):
        spec = ev.get("spec", {}) or {}
        t0 = float(ev["t"])
        kind = ev["kind"]
        png = work / f"ev{i}.png"
        if kind == "number_pop" and spec.get("text") and spec.get("rect"):
            number_png(str(spec["text"]), spec["rect"], bible, png)
            hold = min(2.6, dur - t0)
        elif kind == "highlight" and spec.get("rect"):
            highlight_png(spec["rect"], spec.get("style", "rect"), bible, png)
            hold = min(2.8, dur - t0)
        elif kind == "text_emphasis":
            active = [l for l, c in zip(cap_layouts, shot.get("captions", []) or [])
                      if l.get("ok") and c["t0"] - 0.01 <= t0 <= c["t1"]]
            yy = (active[0]["bbox"][3] + 16) if active and active[0].get("bbox") else None
            rule_png(bible, png, yy)
            hold = min(1.4, dur - t0)
        else:
            continue
        t1 = min(dur, t0 + hold)
        if t1 - t0 < 0.2:
            continue
        cmd += ["-loop", "1", "-framerate", "30", "-t", f"{dur:.3f}", "-i", png]
        graph.append(f"[{idx}:v]format=rgba,fade=t=in:st=0:d=0.2:alpha=1[e{i}]")
        graph.append(f"[{last}][e{i}]overlay=0:0:enable='between(t,{t0:.3f},{t1:.3f})'[be{i}]")
        last = f"be{i}"
        idx += 1

    graph.append(f"[{last}]fade=t=in:st=0:d=0.3:color={_bg_hex(bible)},format=yuv420p[vout]")
    cmd += ["-filter_complex", ";".join(graph), "-map", "[vout]",
            "-c:v", "libx264", "-preset", "medium", "-crf", "18",
            "-pix_fmt", "yuv420p", "-r", "30", "-threads", "1",
            "-t", f"{dur:.3f}", "-flags:v", "+bitexact",
            "-map_metadata", "-1", "-fflags", "+bitexact", str(out)]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"render_shot_v2 {shot['shot_id']} failed:\n{p.stderr[-1500:]}")
    return out


# ------------------------------------------------------------ video render --

def make_audio_master(paths, story_dir: Path, pad: float = 0.7) -> Path:
    story = json.loads((Path(story_dir) / "story.json").read_text())
    order = [b["beat_id"] for b in story["beats"]]
    build = Path(paths.build)
    sil = build / "sil_pad.wav"
    subprocess.run(["ffmpeg", "-nostdin", "-y", "-f", "lavfi",
                    "-i", f"anullsrc=r=44100:cl=stereo", "-t", f"{pad}",
                    str(sil)], check=True, capture_output=True)
    lst = build / "audio_master2.txt"
    lines = []
    for bid in order:
        lines.append(f"file '{Path(story_dir) / 'audio' / f'beat_{bid}.wav'}'")
        lines.append(f"file '{sil}'")
    lst.write_text("\n".join(lines) + "\n")
    master = build / "audio_master2.wav"
    subprocess.run(["ffmpeg", "-nostdin", "-y", "-f", "concat", "-safe", "0",
                    "-i", str(lst), "-c", "copy", str(master)],
                   check=True, capture_output=True)
    return master


def render_video_v2(paths, story_id: str = "tallest_mountain", force: bool = False):
    from engine import bible as B
    plan = json.loads((Path(paths.build) / "edit_plan.json").read_text())
    bible = B.load_bible(Path(paths.stories) / story_id)
    shots = plan.get("shots") or []
    if not shots:
        raise ValueError("edit_plan.json has no shots")
    for s in shots:
        render_shot_v2(s, paths, bible, force=force)

    lst = Path(paths.build) / "shots2.txt"
    lst.write_text("\n".join(f"file '{Path(paths.build) / 'shots2' / s['shot_id']}.mp4'" for s in shots) + "\n")
    master = make_audio_master(paths, Path(paths.stories) / story_id)

    out = Path(paths.output) / "proto2.mp4"
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
           "-f", "concat", "-safe", "0", "-i", str(lst),
           "-i", str(master),
           "-map", "0:v", "-c:v", "copy",
           "-map", "1:a", "-af", "loudnorm=I=-14:TP=-1.5:LRA=11",
           "-c:a", "aac", "-b:a", "192k", "-shortest",
           "-flags:a", "+bitexact", "-map_metadata", "-1", "-fflags", "+bitexact",
           "-movflags", "+faststart", str(out)]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"mux failed:\n{p.stderr[-1500:]}")
    return out


# ------------------------------------------------------- diagram + assets ---

def prep_diagrams(paths, bible: dict, story_id: str = "tallest_mountain"):
    """Render programmatic diagram assets + the split composite, score them."""
    from engine import bible as B
    from engine import diagrams
    from engine.harmonize import continuity_score
    assets = Path(paths.assets)
    made = {}
    made["D1_scale_compare"] = diagrams.scale_compare(bible)
    made["D2_timeline"] = diagrams.timeline_diagram(bible)
    made["D4_payoff"] = diagrams.payoff_diagram(bible)
    vol = assets / "B3_volcano_plate.png"
    made["D3_split_compare"] = diagrams.split_compare(bible, Image.open(vol).convert("RGB"))
    scores = {}
    for name, img in made.items():
        img.save(assets / f"{name}.png", "PNG")
        scores[name] = continuity_score(np.asarray(img.convert("RGB")), bible)
    cpath = Path(paths.build) / "continuity.json"
    data = json.loads(cpath.read_text()) if cpath.exists() else {"assets": []}
    for name, sc in scores.items():
        data["assets"].append({"file": name + ".png", "score_before": sc,
                               "score_after": sc, "ok": sc >= 0.55, "programmatic": True})
        data.setdefault("video_score_components", []).append(sc)
    vals = [a.get("score_after") for a in data["assets"] if isinstance(a.get("score_after"), (int, float))]
    data["video_score"] = round(sum(vals) / len(vals), 4) if vals else None
    cpath.write_text(json.dumps(data, indent=2))
    return scores
