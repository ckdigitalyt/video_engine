"""V5 renderer — V4 composev2 + V6 motion (Bézier/cubic + 2x stage) +
V6 3-layer audio (continuous bed + SFX + narration ducking)
+ V10 native 9:16 pass (flags.py V10 header): portrait card on the Shorts
focal band, kinetic captions, depth parallax/glow, punct stems.
+ V6.2 algorithmic update (Jade_todo):

  §1 Timeline & Audio Sync Guard:
     final_duration = ceil(audio_master_dur + tail) with tail >= 0.8s;
     video is extended (tpad clone) to final_duration, never trimmed under
     the audio; mux no longer uses -shortest. QA stem written for the
     narration-completion assertion in qa5.
  §2 Overlay Anti-Collision Compiler (planv5) + render-side enforcement:
     all event rects are CARD-space [0,1] (the rendered PANEL 1080x780 at
     y=176); header/footer exclusion zones enforced again at render time;
     NUMBER_POPs that duplicate plate text render as kinetic pulses.
  §3 Layout: ambient blurred-card background (no raw void), captions
     clamped into the 1350..1520 safe band.
  §4 Kinetic shots: frame-sequence plates (animated clocks/streamlines)
     rendered at the 2x stage, HOLD camera, single lanczos downsample.
  §5 Content-Addressable Storage: shot artifact name =
     <shot_id>_<sha256(story+shot+prompt+motion+kinetic+audio)[:16]>.mp4;
     stale artifacts garbage-collected against the current manifest (the
     .story stamp/wipe hack is retired).
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from engine import grammar, layout, subs
from engine import flags as _flags
from engine.layout import CANVAS_W, CANVAS_H, VISUAL_RECT, CAPTION_RECT, _font
from engine import motion_v6 as motion
from engine import audio_mix
from engine.planv5 import (CARD_W, CARD_H, CARD_Y0, HEADER_Y, FOOTER_Y,
                           _clamp_card_rect)

SAFE_CAPTION_TOP, SAFE_CAPTION_BOT = 1350, 1520
AUDIO_TAIL_S = 0.8
KINETIC_FPS = 15
# V10_KINETIC caption band (Y 0.70-0.76 of the 1080x1920 canvas, flags.py
# V10 header). The legacy safe band above is restored with V10_KINETIC=0.
KIN_BAND_TOP, KIN_BAND_BOT = 1344, 1459

VX, VY, VW, VH = VISUAL_RECT
BG_HEX = None


def _bg_hex(bible) -> str:
    from engine import bible as B
    r, g, b = B.rgb255(bible, "background")
    return f"0x{r:02X}{g:02X}{b:02X}"


def _abs_rect(rect_norm, pad=0.0):
    x, y, w, h = rect_norm
    return (VX + x * VW, VY + y * VH, w * VW, h * VH)


def _card_abs(rect_card, card_y0: float):
    """Card-space [0,1] rect -> absolute canvas px (V6.2 §2)."""
    x, y, w, h = rect_card
    return (x * CARD_W, card_y0 + y * CARD_H, w * CARD_W, h * CARD_H)


def _fonts(bible):
    typ = bible.get("typography", {})
    return _font(typ.get("display", "BebasNeue-Regular.ttf"), 92)


def _title_overlay_png(text: str, bible: dict, out: Path):
    """V7 P0-3 — episode title as a compose overlay; fades out by ~2.5s.
    Lives in the header band, top-center; card content zones untouched."""
    from PIL import ImageDraw
    W, H = 1536, 1024
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    t = " ".join(text.strip().upper())  # letterspaced caps
    size = 72
    fname = bible.get("typography", {}).get("display", "BebasNeue-Regular.ttf")
    while True:
        f = _font(fname, size)
        bbox = d.textbbox((0, 0), t, font=f)
        if bbox[2] - bbox[0] <= W - 160 or size <= 40:
            break
        size -= 6
    x = (W - (bbox[2] - bbox[0])) // 2
    y = 66
    d.text((x + 3, y + 3), t, font=f, fill=(8, 10, 14, 210))
    d.text((x, y), t, font=f, fill=(240, 238, 232, 255))
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, "PNG")


def _build_visual_rect_shot(shot, paths, bible, v3_rect):
    from engine.layout import VISUAL_RECT, VISUAL_RECT_V3
    vr = v3_rect if v3_rect is not None else VISUAL_RECT
    prim, f, t, _curve, _notes = motion.resolve_camera(shot["camera"])
    smax = max(f["w"], t["w"])
    W_c = int(round(motion.CONTENT_W * smax))
    H_c = int(round(motion.CONTENT_H * smax))
    plate = Path(paths.assets) / f"{shot['asset']}.png"
    img = layout.smart_crop(Image.open(plate), W_c, H_c,
                            bias_y=float(shot.get("crop_bias_y", 0.42)))
    out = Path(paths.build) / "cam" / f"{shot['shot_id']}_canvas.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, "PNG")
    return out, smax, W_c, H_c


def _camera_filter(shot, fps: int = 30):
    """Wrap motion_v6.camera_filter for a shot's camera grammar.

    Accepts both V6 (nested {from:{w,cx,cy}, to:{...}}) and V4
    (flat {primitive, from_scale, to_scale, pan, cx, cy, from_cx, from_cy})
    camera schemas. V4 is normalized into V6 here.
    """
    cam = shot["camera"] or {}
    prim = str(cam.get("primitive", "zoompan")).upper()
    if "from" in cam and "to" in cam and isinstance(cam.get("from"), dict):
        return motion.camera_filter(cam, float(shot["duration_s"]), fps)
    fs = float(cam.get("from_scale") or 1.0)
    ts = float(cam.get("to_scale") or 1.0)
    fw = round(1.0 / max(0.01, fs), 4)
    tw = round(1.0 / max(0.01, ts), 4)
    def _num(v, default):
        return float(v) if v is not None else float(default)
    fcx = _num(cam.get("from_cx"), _num(cam.get("cx"), 0.5))
    fcy = _num(cam.get("from_cy"), _num(cam.get("cy"), 0.5))
    tcx = _num(cam.get("cx"), fcx)
    tcy = _num(cam.get("cy"), fcy)
    prim_map = {
        "ZOOMPAN": "ZOOM_IN", "ZOOM_IN": "ZOOM_IN", "ZOOM_OUT": "ZOOM_OUT",
        "PAN_LEFT": "PAN_LEFT", "PAN_RIGHT": "PAN_RIGHT",
        "PAN_UP": "PAN_UP", "PAN_DOWN": "PAN_DOWN",
        "PUSH_IN": "PUSH_IN", "PULL_OUT": "PULL_OUT",
        "DIAGONAL_PAN": "DIAGONAL_PAN",
        "CROP_REVEAL": "CROP_REVEAL", "FOCUS_REVEAL": "FOCUS_REVEAL",
        "HOLD": "HOLD", "STATIC": "HOLD",
    }
    v6_cam = {
        "primitive": prim_map.get(prim, "ZOOM_IN"),
        "from": {"w": fw, "cx": fcx, "cy": fcy},
        "to":   {"w": tw, "cx": tcx, "cy": tcy},
    }
    if abs(fw - tw) < 1e-4 and abs(fcx - tcx) < 1e-4 and abs(fcy - tcy) < 1e-4:
        v6_cam["primitive"] = "HOLD"
    if v6_cam["primitive"] == "HOLD":
        try:
            from engine import flags as _fl
        except Exception:
            _fl = None
        if _fl is not None and _fl.motion9():
            # V9: no static holds — subtle continuous drift over the shot
            # (~0.8% push + ~0.3% pan, eased by the camera profile). The
            # pan direction is a stable hash of the shot id (deterministic
            # across runs, unlike salted str.hash).
            _sid = str(shot.get("shot_id") or "")
            _sign = 1.0 if (int(hashlib.md5(_sid.encode()).hexdigest()[:2], 16) & 1) else -1.0
            v6_cam["primitive"] = "ZOOM_IN"
            v6_cam["from"] = {"w": 1.0, "cx": 0.5 - 0.0015 * _sign,
                              "cy": 0.5 - 0.0010 * _sign}
            v6_cam["to"] = {"w": 0.992, "cx": 0.5 + 0.0015 * _sign,
                            "cy": 0.5 + 0.0010 * _sign}
    return motion.camera_filter(v6_cam, float(shot["duration_s"]), fps)


def _caption_band() -> tuple:
    """Active caption safe band (top, bot) for the current flag set.

    V11_CAPTION/V10_VERTICAL anchor the band below the card (card bottom
    + 24) — plate content cannot reach it. The span is the KIN_CAP_H
    carrier height (engine/captions.py band_rect), so the report band,
    the adaptive zones (caption_place) and the rendered carrier agree
    exactly. Legacy geometry keeps 1350..1520 unchanged.
    """
    if _flags.vertical10():
        from engine.captions import KIN_CAP_H  # carrier height (single source)
        ct = max(SAFE_CAPTION_TOP, CARD_Y0 + CARD_H + 24)
        return ct, ct + KIN_CAP_H
    return SAFE_CAPTION_TOP, SAFE_CAPTION_BOT


def _ambient_base(shot, bible, plate_path: Path):
    """V6.2 §3 — ambient background. Two eras:

    V11_FULLBLEED (default): true 9:16 — the card band keeps the plate art
    and the top/bottom bands are a crafted CONTINUATION of the same art
    (adjacent card rows mirrored, tone-graded toward the bible background,
    stronger toward the frame extremes). No gaussian blur anywhere: the
    canvas reads as one composed piece, not a horizontal card dropped onto
    a blurred backdrop.
    Rollback (V11_FULLBLEED=0): the V6.2/V10 path — 25px gaussian blur of
    the plate cover-scaled to the canvas, darkened 0.55/0.45 toward the
    bible background with a vertical gradient.
    """
    from engine import bible as B
    frame = layout.base_frame(bible)
    if _flags.fullbleed11():
        try:
            plate = Image.open(plate_path).convert("RGB")
            cover = layout.smart_crop(plate, CANVAS_W, CANVAS_H, bias_y=0.5)
            arr = np.asarray(cover).astype(np.float32)
            bg = np.array(B.rgb255(bible, "background"), dtype=np.float32)
            bot_h = CANVAS_H - (CARD_Y0 + CARD_H)
            # Continuation = SMOOTH TONE EXTENSION. The outermost 64 rows of
            # the CARD (card-aspect cover crop of the same plate, so tones
            # match the card edge) are stretched (LANCZOS) to fill each band.
            # Mirroring full card rows duplicated baked plate text into the
            # bands (evidence 2026-09-10: "WATER SKIN" legible upside-down in
            # the bottom band); a stretch keeps the art's edge tones without
            # ever duplicating glyphs, and no gaussian blur anywhere.
            card_cover = layout.smart_crop(plate, CANVAS_W, CARD_H, bias_y=0.5)
            carr = np.asarray(card_cover, dtype=np.float32)
            cont = np.empty_like(arr)
            strip_t = carr[:64].clip(0, 255).astype(np.uint8)
            cont[:CARD_Y0] = np.asarray(
                Image.fromarray(strip_t).resize((CANVAS_W, CARD_Y0), Image.LANCZOS),
                dtype=np.float32)
            strip_b = carr[-64:].clip(0, 255).astype(np.uint8)
            cont[CARD_Y0 + CARD_H:] = np.asarray(
                Image.fromarray(strip_b).resize((CANVAS_W, bot_h), Image.LANCZOS),
                dtype=np.float32)
            cont[CARD_Y0:CARD_Y0 + CARD_H] = arr[CARD_Y0:CARD_Y0 + CARD_H]
            yy = np.arange(CANVAS_H, dtype=np.float32) / float(CANVAS_H)
            edge = np.clip(np.minimum(yy, 1.0 - yy) / 0.25, 0.0, 1.0)
            mix = 0.10 + 0.28 * edge
            arr2 = cont * (1.0 - mix[:, None, None]) + bg * mix[:, None, None]
            amb = Image.fromarray(np.clip(arr2, 0, 255).astype(np.uint8), "RGB")
            frame.paste(amb, (0, 0))
        except Exception:
            pass  # flat bible bg fallback
    else:
        try:
            plate = Image.open(plate_path).convert("RGB")
            cover = layout.smart_crop(plate, CANVAS_W, CANVAS_H, bias_y=0.5)
            cover = cover.filter(ImageFilter.GaussianBlur(25))
            arr = np.asarray(cover).astype(np.float32)
            bg = np.array(B.rgb255(bible, "background"), dtype=np.float32)
            arr = arr * 0.55 + bg * 0.45
            grad = np.linspace(1.06, 0.80, CANVAS_H, dtype=np.float32)[:, None, None]
            arr = arr * grad
            amb = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGB")
            frame.paste(amb, (0, 0))
        except Exception:
            pass  # flat bible bg fallback
    frame = layout.brand_block(frame, bible, shot)
    if shot.get("end_card"):
        d = ImageDraw.Draw(frame, "RGBA")
        typ = bible.get("typography", {})
        f = _font(typ.get("display", "BebasNeue-Regular.ttf"), 44)
        mark = str(shot["end_card"]).upper()
        tw = d.textlength(mark, font=f)
        bx, by, bw, bh = layout.BRAND_RECT
        d.text(((CANVAS_W - tw) / 2, by + (bh - 44) / 2 - 4), mark,
               font=f, fill=B.rgb255(bible, "text") + (255,))
    return frame


# --- card-space overlay builders (V6.2 §2) ---------------------------------

def _number_png_card(text: str, rect_card, bible: dict, out: Path,
                     card_y0: float = CARD_Y0) -> None:
    from engine import bible as B
    img = Image.new("RGBA", (CANVAS_W, CANVAS_H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    ax, ay, aw, ah = _card_abs(rect_card, card_y0)
    size = max(40, min(96, int(ah * 0.72)))
    f = _font(bible["typography"].get("display", "BebasNeue-Regular.ttf"), size)
    while d.textlength(text, font=f) > aw * 0.94 and size > 40:
        size -= 6
        f = _font(bible["typography"].get("display", "BebasNeue-Regular.ttf"), size)
    tw = d.textlength(text, font=f)
    x = ax + (aw - tw) / 2
    y = ay + max(8, int((ah - size) // 2))
    d.text((x + 3, y + 5), text, font=f, fill=(0, 0, 0, 150))
    d.text((x, y), text, font=f, fill=B.rgb255(bible, "accent") + (255,))
    img.save(out, "PNG")


def _highlight_png_card(rect_card, style: str, bible: dict, out: Path,
                        card_y0: float = CARD_Y0) -> None:
    from engine import bible as B
    img = Image.new("RGBA", (CANVAS_W, CANVAS_H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img, "RGBA")
    x, y, w, h = _card_abs(rect_card, card_y0)
    accent = B.rgb255(bible, "accent")
    box = [x, y, x + w, y + h]
    if str(style).startswith("circ"):
        d.ellipse(box, fill=accent + (26,), outline=accent + (210,), width=5)
    else:
        d.rounded_rectangle(box, radius=10, fill=accent + (22,),
                            outline=accent + (210,), width=5)
    img.save(out, "PNG")


def _pulse_png_card(rect_card, style: str, bible: dict, out: Path,
                    card_y0: float = CARD_Y0) -> None:
    """Kinetic pulse on an existing plate element (V6.2 §2 dedup target)."""
    from engine import bible as B
    img = Image.new("RGBA", (CANVAS_W, CANVAS_H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img, "RGBA")
    x, y, w, h = _card_abs(rect_card, card_y0)
    accent = B.rgb255(bible, "accent")
    box = [x, y, x + w, y + h]
    halo = [x - 10, y - 10, x + w + 10, y + h + 10]
    if str(style).startswith("rect"):
        d.rounded_rectangle(halo, radius=20, outline=accent + (110,), width=3)
        d.rounded_rectangle(box, radius=14, fill=accent + (30,),
                            outline=accent + (235,), width=6)
    else:
        d.ellipse(halo, outline=accent + (110,), width=3)
        d.ellipse(box, fill=accent + (30,), outline=accent + (235,), width=6)
    img.save(out, "PNG")


def rule_png(bible, out: Path, y=None):
    from engine import composev2
    return composev2.rule_png(bible, out, y)


# --- captions (V6.2 §3 safe band) -------------------------------------------

def _layout_caption_v5(cue, bible, cap_top: float = SAFE_CAPTION_TOP,
                       cap_bot: float = SAFE_CAPTION_BOT):
    """Caption layout with the anchor clamped into [cap_top, cap_bot].
    Defaults are the legacy V6.2 safe band; V10_VERTICAL passes a band
    pushed below the taller portrait card."""
    lay = subs.layout_caption(cue["text"], bible,
                              zone_y=cap_top,
                              level=int(cue.get("level", 1)))
    if not lay.get("ok"):
        return lay
    bbox = lay.get("bbox")
    block_h = float(lay.get("block_h") or
                    ((bbox[3] - bbox[1]) if bbox else 120.0))
    y0 = float(lay.get("y0") or cap_top)
    new_y0 = min(max(y0, cap_top), cap_bot - block_h)
    new_y0 = max(new_y0, cap_top)
    if bbox and abs(new_y0 - y0) > 0.5:
        dy = new_y0 - y0
        lay["bbox"] = (bbox[0], bbox[1] + dy, bbox[2], bbox[3] + dy)
    lay["y0"] = new_y0
    return lay


def caption_png_v5(cue, bible, out: Path, bg_img=None, v3: bool = False,
                   cap_top: float = SAFE_CAPTION_TOP,
                   cap_bot: float = SAFE_CAPTION_BOT):
    """Full-frame transparent RGBA with one caption block baked, anchored
    inside the V6.2 safe band (or the V10 band via cap_top/cap_bot)."""
    from engine import bible as B
    from engine import contrast as C
    img = Image.new("RGBA", (CANVAS_W, CANVAS_H), (0, 0, 0, 0))
    lay = _layout_caption_v5(cue, bible, cap_top=cap_top, cap_bot=cap_bot)
    if not lay.get("ok"):
        img.save(out, "PNG")
        return lay
    d = ImageDraw.Draw(img)
    text_col = B.rgb255(bible, "text") + (255,)
    accent = B.rgb255(bible, "accent") + (255,)
    if v3 and bg_img is not None and lay.get("bbox"):
        pad = 30
        bb = (lay["bbox"][0] - pad, lay["bbox"][1] - pad,
              lay["bbox"][2] + pad, lay["bbox"][3] + pad)
        dec = C.needs_backing(B.rgb255(bible, "text"), C.bbox_pixels(bg_img, bb))
        lay["backing"] = dec.as_dict()
        if dec.level == "gradient":
            gw = int(lay["bbox"][2] - lay["bbox"][0]) + 200
            gh = int(lay["block_h"]) + 170
            strip = C.gradient_strip(gw, gh, alpha_max=150)
            img.paste(strip, (int(lay["bbox"][0]) - 100, int(lay["bbox"][1]) - 100), strip)
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


# --- CAS (V6.2 §5) -----------------------------------------------------------

def _shot_hash(shot: dict, story_id: str, audio_file=None) -> str:
    prompt = "|".join([str(shot.get("asset", "")), str(shot.get("claim", "")),
                       str(shot.get("purpose", ""))])
    motion_cfg = json.dumps(shot.get("camera") or {}, sort_keys=True,
                            separators=(",", ":"))
    kin = json.dumps(shot.get("kinetic") or {}, sort_keys=True,
                     separators=(",", ":"))
    if audio_file and Path(audio_file).exists():
        ah = hashlib.sha256(Path(audio_file).read_bytes()).hexdigest()
    else:
        ah = hashlib.sha256(json.dumps(shot.get("captions") or [],
                                       sort_keys=True).encode()).hexdigest()
    evx = json.dumps(shot.get("events") or [], sort_keys=True, separators=(",", ":"))
    tox = json.dumps(shot.get("title_overlay") or {}, sort_keys=True, separators=(",", ":"))
    trn = str(shot.get("transition_in") or "")
    payload = (story_id + str(shot.get("shot_id", "")) + prompt + motion_cfg + kin
               + ah + evx + tox + trn)
    try:
        from engine import flags as _fl
        payload += _fl.token()  # "" for baseline -> hash byte-identical
    except Exception:
        pass
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _probe_dur(p) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                        "format=duration", "-of", "csv=p=0", str(p)],
                       capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except Exception:
        return 0.0


def _narration_end(wav_path, thr_dbfs: float = -45.0):
    """Last audible (RMS > thr) time in a 16-bit wav, 10ms windows."""
    import wave as _wave
    try:
        with _wave.open(str(wav_path), "rb") as w:
            n = w.getnframes()
            sr = w.getframerate()
            ch = w.getnchannels()
            sw = w.getsampwidth()
            raw = w.readframes(n)
        if sw != 2:
            return None
        a = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        if ch > 1:
            a = a.reshape(-1, ch).mean(axis=1)
        win = max(1, int(sr * 0.01))
        m = len(a) - (len(a) % win)
        if m == 0:
            return 0.0
        rms = np.sqrt((a[:m].reshape(-1, win) ** 2).mean(axis=1))
        idx = np.nonzero(rms > (10.0 ** (thr_dbfs / 20.0)))[0]
        if len(idx) == 0:
            return 0.0
        return float((idx[-1] + 1) * win / sr)
    except Exception:
        return None


# --- shot render -------------------------------------------------------------

def render_shot_v5(shot: dict, paths, bible: dict, force: bool = False,
                   v3: bool = False, shots_subdir: str = "shots3",
                   fps: int = 30, artifact: str = None) -> Path:
    from engine.layout import VISUAL_RECT, VISUAL_RECT_V3
    from engine import visual_grammar as vg
    from engine import flags as _flags
    vr = VISUAL_RECT_V3 if v3 else VISUAL_RECT
    # V10 §1 — the portrait card fills the Shorts focal band (Y 0.15-0.75
    # of 1080x1920 = 288..1440). planv5.CARD_Y0 carries the active geometry
    # (rollback: V10_VERTICAL=0 restores the VISUAL_RECT anchor).
    card_y0 = CARD_Y0 if _flags.vertical10() else vr[1]
    out = Path(paths.build) / shots_subdir / (artifact or f"{shot['shot_id']}.mp4")
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp_out = out.with_suffix(".tmp.mp4")
    if out.exists() and not force:
        return out
    dur = float(shot["duration_s"])
    work = Path(paths.build) / "ov5" / shot["shot_id"]
    work.mkdir(parents=True, exist_ok=True)

    kin = shot.get("kinetic")
    canvas, smax, W_c, H_c = _build_visual_rect_shot(shot, paths, bible, vr)
    base = _ambient_base(shot, bible, Path(paths.assets) / f"{shot['asset']}.png")
    base_png = work / "base.png"
    base.save(base_png, "PNG")

    if kin:
        n_frames = int(math.ceil(dur * KINETIC_FPS))
        kin_dir = work / "kin"
        have = sorted(kin_dir.glob("f*.png")) if kin_dir.exists() else []
        if force or len(have) < n_frames:
            shutil.rmtree(kin_dir, ignore_errors=True)
            if kin.get("type") == "clocks":
                vg.render_clock_frames(kin_dir, n_frames, motion.STAGE_W,
                                       motion.STAGE_H, bible,
                                       omega_ratio=float(kin.get("omega_ratio", 0.2)),
                                       fps=KINETIC_FPS)
            else:
                vg.render_streamline_frames(kin_dir, n_frames, motion.STAGE_W,
                                            motion.STAGE_H, bible,
                                            fps=KINETIC_FPS)
        # V6.2 §4: the animation IS the motion — HOLD camera, single downsample.
        # ENABLE_BLOOM: multi-pass bloom on the luminous kinetic frames only
        # (bright-pass -> masked screen). Source frames stay untouched so the
        # post-process is deterministic and CAS-safe.
        kin_use = kin_dir
        if _flags.bloom_enabled() or _flags.depth10():
            # ENABLE_BLOOM forced it before; V10_DEPTH makes bloom on the
            # luminous kinetic shots default-on (flags.py V10 header).
            from engine import effects
            kin_use = effects.bloom_dir(kin_dir, work / "kin_bloom")
        cmd = ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
               "-framerate", str(KINETIC_FPS), "-i", str(kin_use / "f%05d.png"),
               "-loop", "1", "-framerate", str(fps), "-t", f"{dur:.3f}", "-i", str(base_png)]
        graph = [f"[0:v]scale={motion.PANEL_W}:{motion.PANEL_H}:flags=lanczos,setsar=1[cam]",
                 f"[1:v][cam]overlay=0:{card_y0}[b]"]
    else:
        cmd = ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
               "-loop", "1", "-framerate", str(fps), "-t", f"{dur:.3f}", "-i", str(canvas),
               "-loop", "1", "-framerate", str(fps), "-t", f"{dur:.3f}", "-i", str(base_png)]
        cam_filter, n, prim, notes = _camera_filter(shot, fps=fps)
        if (_flags.parallax_enabled() and prim != "HOLD"
                and not shot.get("end_card") and not shot.get("opening")
                and not _flags.fullbleed11()):
            # ENABLE_PARALLAX: ambient field moves at damp x camera rate.
            # The card plate keeps the authored camera — text never distorts.
            # Opening/end-card shots keep a fully static base (their baked-in
            # display title / end mark must not drift).
            # V11_FULLBLEED skips the drift: the backdrop is a mirror
            # continuation seam-locked to the card edges — drifting it would
            # tear the seam. Card camera motion is untouched.
            amb_filter, _an, _ap = motion.ambient_parallax_filter(
                shot.get("camera") or {}, dur, fps=fps)
            graph = [f"[1:v]{amb_filter}[amb]",
                     f"[0:v]{cam_filter}[cam]",
                     f"[amb][cam]overlay=0:{card_y0}[b]"]
        else:
            graph = [f"[0:v]{cam_filter}[cam]",
                     f"[1:v][cam]overlay=0:{card_y0}[b]"]
    last = "b"
    idx = 2

    # captions (V6.2 §3 safe band) — V10_KINETIC: word-level chunks with an
    # active-word highlight replace the clause blocks; the legacy clause path
    # stays intact when the flag is off (V10_KINETIC=0).
    # V11_CAPTION: cues pass through the caption state machine
    # (captions.normalize_cues) — one ACTIVE_CAPTION state, off-window
    # between states, repairs recorded for caption_qa.
    bg_canvas = base.convert("RGB") if v3 else None
    cap_layouts = []
    _cap_cues = list(shot.get("captions", []) or [])
    _cap_repairs: list = []
    _ct, _cb = _caption_band()
    _zone = None
    if shot.get("captions"):
        # V11 P1 §5 — adaptive caption placement: per-shot cleanest safe
        # zone (default below-card, top band, or bottom retreat slot);
        # used by BOTH the kinetic and the legacy caption path.
        from engine import caption_place as _cplace
        _zone = _cplace.choose_zone(shot)
        _ct, _cb = int(_zone["top"]), int(_zone["bot"])
    if _flags.kinetic10() and shot.get("captions"):
        from engine import captions as _caps
        kin_inputs, cue_bboxes, _cap_cues, _cap_repairs = _caps.build_shot_captions(
            shot, bible, work, dur=dur, zone_top=_zone["top"])
        for i, kc in enumerate(kin_inputs):
            png = Path(kc["png"])
            cmd += ["-loop", "1", "-framerate", str(fps), "-t", f"{dur:.3f}", "-i", png]
            graph.append(f"[{idx}:v]format=rgba[c{i}]")
            graph.append(f"[{last}][c{i}]overlay=0:{int(kc['top'])}:"
                         f"enable='between(t,{kc['t0']:.3f},{min(kc['t1'], dur):.3f})'[bc{i}]")
            last = f"bc{i}"
            idx += 1
        # cue-aligned layout stubs so text_emphasis rules anchor under the
        # kinetic band exactly as they did under the legacy clause blocks
        cap_layouts = [{"ok": bb is not None, "bbox": bb} for bb in cue_bboxes]
    else:
        # legacy band; under V10_VERTICAL the card bottom (CARD_Y0+CARD_H)
        # overlaps the historical 1350..1520 band, so the band is pushed
        # below the card — legacy geometry keeps 1350..1520 unchanged.
        for i, cue in enumerate(shot.get("captions", []) or []):
            png = work / f"cap{i}.png"
            lay = caption_png_v5(cue, bible, png, bg_img=bg_canvas, v3=v3,
                                 cap_top=_ct, cap_bot=_cb)
            cap_layouts.append(lay)
            if not lay.get("ok") or not lay.get("png"):
                continue
            cmd += ["-loop", "1", "-framerate", str(fps), "-t", f"{dur:.3f}", "-i", png]
            graph.append(f"[{idx}:v]format=rgba,fade=t=in:st=0:d=0.12:alpha=1[c{i}]")
            graph.append(f"[{last}][c{i}]overlay=0:0:enable='between(t,{cue['t0']:.3f},{cue['t1']:.3f})'[bc{i}]")
            last = f"bc{i}"
            idx += 1

    # events: number pops / pulses, highlights, emphasis rules, stage overlays
    for i, ev in enumerate(shot.get("events", []) or []):
        spec = dict(ev.get("spec", {}) or {})
        t0 = float(ev["t"])
        kind = ev["kind"]
        png = work / f"ev{i}.png"
        seq = None
        seq_fps = 30
        rect_c = spec.get("rect")
        if kind in ("number_pop", "highlight") and rect_c:
            # render-side enforcement of the exclusion zones (idempotent)
            rect_c = _clamp_card_rect([float(v) for v in rect_c])
            spec["rect"] = rect_c
        if kind == "number_pop" and spec.get("text") and rect_c:
            if spec.get("pulse"):
                _pulse_png_card(rect_c, spec.get("style", "circle"), bible, png, card_y0)
            else:
                _number_png_card(str(spec["text"]), rect_c, bible, png, card_y0)
            hold = min(2.6, dur - t0)
        elif kind == "highlight" and rect_c:
            if spec.get("pulse"):
                _pulse_png_card(rect_c, spec.get("style", "circle"), bible, png, card_y0)
            else:
                _highlight_png_card(rect_c, spec.get("style", "rect"), bible, png, card_y0)
            hold = min(2.8, dur - t0)
        elif kind == "text_emphasis":
            active = [(l, c) for l, c in zip(cap_layouts, _cap_cues)
                      if l.get("ok") and c["t0"] - 0.01 <= t0 <= c["t1"]]
            yy = (active[0][0]["bbox"][3] + 16) if active and active[0][0].get("bbox") else None
            rule_png(bible, png, yy)
            hold = min(1.4, dur - t0)
            # V11 caption state machine: emphasis modifies the ACTIVE caption
            # only — the rule may never outlive its cue into the next state.
            if active:
                hold = min(hold, max(0.2, float(active[0][1]["t1"]) - t0))
        elif kind == "stage_overlay" and spec.get("png"):
            png = Path(spec["png"])
            hold = dur - t0
        elif kind in ("reveal", "isolate", "flow", "fill_state", "consequence"):
            # V8 living diagrams (brief §3): animate the information itself.
            # Frames carry the full alpha lifecycle; compositor just windows it.
            from engine import living
            hold = min(living.DEFAULT_HOLD.get(kind, 2.2), dur - t0)
            seq = work / f"liv{i}"
            persist = kind in living.PERSIST_KINDS
            living.render_frames(kind, spec, seq,
                                 max(3, int(round(hold * living.EVENT_FPS))),
                                 card_w=CARD_W, card_h=CARD_H,
                                 card_y0=card_y0, persist=persist,
                                 canvas_w=CANVAS_W, canvas_h=CANVAS_H)
            seq_fps = living.EVENT_FPS
            if persist:
                hold = dur - t0  # end-state holds to shot end
            if _flags.depth10() and kind == "flow":
                # V10_DEPTH — additive emissive halo on the flow particles:
                # bright-pass glow re-composited under the strokes, alpha
                # preserved, source frames untouched (CAS-safe, like bloom).
                seq = _glow_frames(seq, work / f"liv{i}_glow")
        else:
            continue
        t1 = min(dur, t0 + hold)
        if t1 - t0 < 0.2:
            continue
        if seq is not None:
            cmd += ["-framerate", str(seq_fps), "-i", str(seq / "f%05d.png")]
            graph.append(f"[{idx}:v]format=rgba[lv{i}]")
            graph.append(f"[{last}][lv{i}]overlay=0:0:enable='between(t,{t0:.3f},{min(t1 + 0.1, dur):.3f})'[be{i}]")
        else:
            cmd += ["-loop", "1", "-framerate", str(fps), "-t", f"{dur:.3f}", "-i", png]
            graph.append(f"[{idx}:v]format=rgba,fade=t=in:st=0:d=0.2:alpha=1[e{i}]")
            graph.append(f"[{last}][e{i}]overlay=0:0:enable='between(t,{t0:.3f},{t1:.3f})'[be{i}]")
        last = f"be{i}"
        idx += 1

    # V7 P0-3 — episode title overlay: DISABLED in this build.
    # The ffmpeg filter chain rejects the title overlay input on the v7 stories
    # with "Error initializing complex filters: Invalid argument" (root cause
    # not fully isolated before deadline).  The opening card carries the story
    # content; the episode title is documented in the V7 report as a known
    # limitation to be resolved by a generator-side alpha approach.
    to = shot.get("title_overlay")
    if False and isinstance(to, dict) and str(to.get("text") or "").strip():
        pass  # title overlay disabled
    # V7 P0-10 — dip transitions (dip_to_white / dip_to_black); 'CUT' and
    # unset keep the historical bg-color fade, so old plans are unchanged.
    _dip = {"dip_to_white": "white", "dip_to_black": "black"}.get(
        str(shot.get("transition_in") or "").strip().lower())
    graph.append(f"[{last}]fade=t=in:st=0:d=0.3:color={_dip or _bg_hex(bible)},format=yuv420p[vout]")
    cmd += ["-filter_complex", ";".join(graph), "-map", "[vout]",
            "-c:v", "libx264", "-preset", "medium", "-crf", "18",
            "-pix_fmt", "yuv420p", "-r", str(fps), "-threads", "1",
            "-t", f"{dur:.3f}", "-flags:v", "+bitexact",
            "-map_metadata", "-1", "-fflags", "+bitexact", str(tmp_out)]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        tmp_out.unlink(missing_ok=True)
        raise RuntimeError(f"render_shot_v5 {shot['shot_id']} failed:\n{p.stderr[-1500:]}")
    # V11 caption state record — what the state machine actually rendered
    # (normalized states + authoring repairs) for engine/caption_qa.py.
    # V11 P1 §5: the record carries the adaptive per-shot placement zone.
    (work / "cap_state.json").write_text(json.dumps({
        "shot_id": shot.get("shot_id"), "dur": dur,
        "band": [int(_zone["top"]), int(_zone["bot"])]
                if _zone else list(_caption_band()),
        "caption_zone": _zone,
        "normalized_cues": [{"text": str(c.get("text", "")),
                             "t0": float(c["t0"]), "t1": float(c["t1"])}
                            for c in _cap_cues],
        "repairs": _cap_repairs,
    }, indent=1) + "\n")
    # CAS integrity: verify stream duration, publish atomically — a killed
    # render must never leave a truncated artifact at the CAS path.
    got = _probe_dur(tmp_out)
    if got < 0.8 * dur:
        tmp_out.unlink(missing_ok=True)
        raise RuntimeError(
            f"render_shot_v5 {shot['shot_id']}: stream {got:.2f}s << expected {dur:.2f}s")
    os.replace(tmp_out, out)
    return out


# --- overlay report (V6.2 verification ground truth) -------------------------

def _build_overlay_report(shots: list, bible: dict, audio_info: dict) -> dict:
    shots_rep = {}
    violations = []
    totals = {"events": 0, "pulses": 0, "suppressed": 0}
    for s in shots:
        sid = str(s.get("shot_id"))
        evs = []
        for ev in s.get("events", []) or []:
            spec = ev.get("spec") or {}
            rc = spec.get("rect")
            if not rc:
                continue
            totals["events"] += 1
            if spec.get("pulse"):
                totals["pulses"] += 1
            if spec.get("suppressed_original"):
                totals["suppressed"] += 1
            x, y, w, h = [float(v) for v in rc]
            if (y < HEADER_Y - 1e-6 or y + h > FOOTER_Y + 1e-6
                    or x < 0.0 - 1e-6 or x + w > 1.0 + 1e-6):
                violations.append({"shot": sid, "kind": ev.get("kind"),
                                   "rect_card": rc, "reason": "exclusion zone"})
            ax, ay, aw, ah = _card_abs(rc, CARD_Y0)
            evs.append({"kind": ev.get("kind"), "t": ev.get("t"),
                        "text": spec.get("text"),
                        "pulse": bool(spec.get("pulse")),
                        "suppressed": bool(spec.get("suppressed_original")),
                        "rect_card": rc,
                        "rect_abs": [round(ax, 1), round(ay, 1),
                                     round(aw, 1), round(ah, 1)]})
        caps = []
        # V11 P1 §5 — per-shot adaptive placement: report the zone this
        # shot's captions actually use and check THAT band (not one global
        # coordinate), so safe-zone QA follows the renderer by construction.
        from engine import caption_place as _cplace
        _zone = _cplace.choose_zone(s)
        _rb_top, _rb_bot = int(_zone["top"]), int(_zone["bot"])
        for cue in s.get("captions", []) or []:
            lay = _layout_caption_v5(cue, bible, cap_top=_rb_top, cap_bot=_rb_bot)
            if not lay.get("ok") or not lay.get("bbox"):
                continue
            bb = lay["bbox"]
            caps.append({"text": cue.get("text", "")[:60],
                         "bbox": [round(float(bb[0]), 1), round(float(bb[1]), 1),
                                  round(float(bb[2]), 1), round(float(bb[3]), 1)]})
            if bb[1] < _rb_top - 10 or bb[3] > _rb_bot + 10:
                violations.append({"shot": sid, "kind": "caption",
                                   "rect_abs": list(caps[-1]["bbox"]),
                                   "reason": "safe band"})
        shots_rep[sid] = {"events": evs, "captions": caps,
                          "caption_zone": {"zone": _zone["zone"],
                                           "band": [_rb_top, _rb_bot],
                                           "reasons": _zone["reasons"],
                                           "considered": _zone["considered"]},
                          "kinetic": s.get("kinetic"),
                          "ambient_bg": True}
    zone_varies = len({r.get("caption_zone", {}).get("zone")
                       for r in shots_rep.values()}) > 1
    return {
        "card": {"x": 0, "y": CARD_Y0, "w": CARD_W, "h": CARD_H},
        "zones": {"header_y": HEADER_Y, "footer_y": FOOTER_Y},
        "safe_caption_band": list(_caption_band()),
        "caption_placement": {"mode": "adaptive_per_shot",
                              "zones_available": sorted(_cplace.zones()),
                              "placement_varies": zone_varies},
        "shots": shots_rep,
        "totals": totals,
        "violations": violations,
        "audio": audio_info,
    }


# --- video render ------------------------------------------------------------

# --- V10_DEPTH — RGBA-preserving additive glow ------------------------------

def _glow_frames(src_dir: Path, dst_dir: Path, strength: float = 0.6,
                 radius: int = 9) -> Path:
    """Additive emissive halo for living-event frame sequences (V10_DEPTH).

    effects.bloom is tuned for opaque luminous frames — its confined
    composite rounds to zero delta on thin transparent strokes — so the
    halo is built directly: blurred stroke chroma + blurred alpha form a
    soft emissive field composited UNDER the crisp strokes (original
    alpha preserved, sources untouched -> CAS-safe). Returns dst_dir."""
    from PIL import ImageFilter
    src_dir, dst_dir = Path(src_dir), Path(dst_dir)
    dst_dir.mkdir(parents=True, exist_ok=True)
    for f in sorted(src_dir.glob("f*.png")):
        img = Image.open(f).convert("RGBA")
        halo_a = img.getchannel("A").filter(
            ImageFilter.GaussianBlur(radius)).point(
            lambda v: int(v * strength))
        halo = img.convert("RGB").filter(
            ImageFilter.GaussianBlur(radius)).convert("RGBA")
        halo.putalpha(halo_a)
        Image.alpha_composite(halo, img).save(dst_dir / f.name, "PNG")
    return dst_dir


# --- V10_PUNCT — cinematic punctuation stems --------------------------------

def _punct_stems(shots: list, shot_durs: list, build_dir: Path,
                 narration_spans: list | None = None) -> list:
    """Deterministic sub-bass punctuation SFX (V10_PUNCT, flags.py header):
    1.5s risers ENDING at each ESCALATION/REVEAL shot start, 40-80Hz
    sub-drops at PAYOFF starts. numpy-generated, wave-written, cached by
    path; entries use audio_mix._concat_sfx absolute-timeline `at`.

    V11 P1 §9 — silence is deliberate: a riser may occupy only the
    narration pad gap before its hit (the span where the previous beat's
    narration has already ended). When the gap is shorter than 0.45s the
    riser is dropped entirely — the sub-bass sweep no longer rides over
    speech tails as continuous low-frequency tonal fill."""
    import wave
    SR = 44100
    adir = Path(build_dir) / "punct"
    adir.mkdir(parents=True, exist_ok=True)

    def _wav(name, data):
        p = adir / name
        if not p.exists():
            pcm = (np.clip(data, -1.0, 1.0) * 32767).astype("<i2")
            with wave.open(str(p), "wb") as w:
                w.setnchannels(2)
                w.setsampwidth(2)
                w.setframerate(SR)
                w.writeframes(pcm.tobytes())
        return p

    def _riser(dur=1.5):
        n = int(dur * SR)
        t = np.arange(n) / SR
        f = 36.0 * (84.0 / 36.0) ** (t / dur)          # 36->84 Hz sweep
        phase = 2 * np.pi * np.cumsum(f) / SR
        amp = 0.08 + 0.44 * (t / dur) ** 2
        x = np.sin(phase) * amp + 0.05 * (t / dur) ** 2 * np.sin(2 * np.pi * 55 * t)
        s = np.stack([x, x], axis=1)
        return _wav(f"riser_{int(dur * 1000)}ms.wav", s)  # hard cut: the shot start IS the hit

    def _subdrop(dur=1.1):
        n = int(dur * SR)
        t = np.arange(n) / SR
        f = 78.0 * (38.0 / 78.0) ** (t / dur)          # 78->38 Hz fall
        phase = 2 * np.pi * np.cumsum(f) / SR
        env = np.exp(-2.6 * t / dur)
        x = np.sin(phase) * 0.55 * env + np.sin(2 * np.pi * 42 * t) * 0.18 * env
        s = np.stack([x, x], axis=1)
        return _wav("subdrop.wav", s)

    sfx, t0 = [], 0.0
    for i, (s, d) in enumerate(zip(shots, shot_durs)):
        stype = str(s.get("shot_type", "")).upper()
        bfn = str(s.get("beat_function", "")).upper()
        if stype == "REVEAL" or bfn == "ESCALATION":
            riser_dur = 1.5
            if narration_spans:
                # gap between the previous narration's end and this cut
                prev_end = 0.0
                for j in range(i - 1, -1, -1):
                    if narration_spans[j] is not None:
                        prev_end = sum(shot_durs[:j]) + narration_spans[j]
                        break
                gap = max(0.0, t0 - prev_end)
                riser_dur = round(min(1.5, gap), 2)
                if riser_dur < 0.45:
                    t0 += float(d)
                    continue  # deliberate silence stays silent
            sfx.append({"file": str(_riser(riser_dur)),
                        "at": max(0.0, t0 - riser_dur),
                        "dur": riser_dur, "kind": "punct_riser"})
        if stype == "PAYOFF" or bfn == "PAYOFF":
            sfx.append({"file": str(_subdrop()), "at": t0,
                        "dur": 1.1, "kind": "punct_subdrop"})
        t0 += float(d)
    return sfx


def _notch_beds(bed_files: list, build_dir: Path) -> list:
    """1-3kHz wide notch (two -7 dB bands at 1.4/2.4 kHz) on each unique
    music-bed stem (V10_PUNCT): the bed yields the voice presence band;
    the V9 sidechain duck still handles level under narration."""
    out_dir = Path(build_dir) / "punct" / "beds"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = []
    for b in bed_files:
        if not b:
            out.append(b)
            continue
        src = Path(b)
        dst = out_dir / f"{src.stem}_notched.wav"
        if not dst.exists():
            subprocess.run(
                ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
                 "-i", str(src),
                 "-af", "equalizer=f=1400:t=q:w=1.6:g=-7,"
                        "equalizer=f=2400:t=q:w=1.6:g=-7",
                 "-ar", "44100", "-ac", "2", str(dst)],
                check=True)
        out.append(str(dst))
    return out


def render_video_v5(paths, story_id: str = "tallest_mountain", force: bool = False,
                    out_name: str = "proto5.mp4", fps: int = 30) -> Path:
    from engine import bible as B
    plan = json.loads((Path(paths.build) / "edit_plan.json").read_text())
    bible = B.load_bible(Path(paths.stories) / story_id)
    shots = plan.get("shots") or []
    if not shots:
        raise ValueError("edit_plan.json has no shots")
    v3 = str(plan.get("engine", "")) in ("v3", "v4", "v5", "v6.2")
    shots_subdir = "shots3"
    sdir = Path(paths.build) / shots_subdir
    sdir.mkdir(parents=True, exist_ok=True)

    # V6.2 §5 — content-addressable artifacts: name = <id>_<hash>.mp4.
    # Any input change (prompt/motion/kinetic/audio) yields a new artifact;
    # cross-story reuse is structurally impossible. Stale artifacts are
    # garbage-collected against the current manifest (replaces the .story
    # stamp/wipe hack).
    timing = json.loads((Path(paths.stories) / story_id / "audio" / "timing.json").read_text())
    artifacts = {}
    for s in shots:
        af = None
        bid = s.get("beat_id")
        if bid and bid in timing:
            af = Path(paths.stories) / story_id / timing[bid]["file"]
        h = _shot_hash(s, story_id, af)
        artifacts[str(s["shot_id"])] = f"{s['shot_id']}_{h}.mp4"
    keep = set(artifacts.values())
    for f in sorted(sdir.glob("*.mp4")):
        if f.name not in keep:
            f.unlink()
    (sdir / "manifest.json").write_text(json.dumps(
        {"story_id": story_id, "artifacts": artifacts}, indent=2) + "\n")
    for s in shots:
        render_shot_v5(s, paths, bible, force=force, v3=v3,
                       shots_subdir=shots_subdir, fps=fps,
                       artifact=artifacts[str(s["shot_id"])])

    # Concat shots
    lst = Path(paths.build) / f"{shots_subdir}.txt"
    lst.write_text("\n".join(f"file '{Path(paths.build) / shots_subdir / artifacts[str(s['shot_id'])]}'"
                              for s in shots) + "\n")
    concat = Path(paths.build) / f"{shots_subdir}_concat.mp4"
    subprocess.run(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
                    "-f", "concat", "-safe", "0", "-i", str(lst),
                    "-c:v", "copy", str(concat)], check=True, capture_output=True)

    # 3-layer audio
    story = json.loads((Path(paths.stories) / story_id / "story.json").read_text())
    narration_beats = []
    for b in story.get("beats", []):
        bid = b["beat_id"]
        if bid in timing:
            t = timing[bid]
            narration_beats.append({
                "file": str(Path(paths.stories) / story_id / t["file"]),
                "duration": float(t.get("duration", 0)),
            })
    bed_plan = json.loads((Path(paths.build) / "audio_bed_plan.json").read_text()) \
        if (Path(paths.build) / "audio_bed_plan.json").exists() else {"bed_files": []}
    bed_files = bed_plan.get("bed_files") or []
    if len(bed_files) < len(shots):
        last = bed_files[-1] if bed_files else None
        bed_files = bed_files + [last] * (len(shots) - len(bed_files))
    sfx = bed_plan.get("sfx") or []
    shot_durs = [float(s.get("duration_s", 0)) for s in shots]
    total = sum(shot_durs)
    if _flags.punct10():
        # V10_PUNCT — risers/sub-drops + 1-3kHz bed notch (rollback:
        # V10_PUNCT=0 restores the pre-punct stems byte-for-byte).
        # V11 P1 §9 — risers only fill the narration pad gap (deliberate
        # silence), never ride over speech tails.
        _nspans = []
        for s in shots:
            _t = timing.get(str(s.get("beat_id")) or "") or {}
            _nd = float(_t.get("duration") or 0)
            _nspans.append(min(_nd, float(s.get("duration_s", 0)))
                           if _nd > 0 else None)
        sfx = list(sfx) + _punct_stems(shots, shot_durs, Path(paths.build),
                                       narration_spans=_nspans)
        bed_files = _notch_beds(bed_files, Path(paths.build))
    audio_out = Path(paths.build) / "v5_audio_master.wav"
    # V9 texture: post-composite subtle radial vignette + 1.5% fine film
    # grain — kills the raw vector/SVG aesthetic (flag: V9_TEXTURE).
    try:
        from engine import flags as _fl9
        _v9_tex = ("vignette=angle=PI/6,noise=alls=1.5:allf=t+u"
                   if _fl9.texture9() else "")
    except Exception:
        _v9_tex = ""
    # V9 audio: feed the mixer the per-shot intensity tiers + story type so
    # the underscore gain and ambience selection are procedural (V9_AUDIO).
    _intensities = [float((s.get("v8") or {}).get("intensity") or 0.62)
                    for s in shots]
    mixinfo = audio_mix.mix(narration_beats, bed_files, sfx, shot_durs, total,
                            audio_out,
                            story_type=str(plan.get("story_type")
                                           or story.get("story_type")
                                           or story.get("type") or ""),
                            intensities=_intensities)

    # V6.2 §1 — narration stem for the QA completion assertion
    stem = None
    nar_path = mixinfo.get("narration")
    if nar_path and Path(nar_path).exists():
        stem = Path(paths.build) / "v5_narration_stem.wav"
        shutil.copyfile(nar_path, stem)

    # V6.2 §1 — audio-derived final duration: video may never end while
    # narration is active. final_duration = ceil(audio + tail>=0.8s); the
    # video stream is extended (clone last frame) if short — never trimmed
    # under the audio.
    a_dur = _probe_dur(audio_out)
    nar_end = _narration_end(stem) if stem else None
    v_dur = total
    target = max(math.ceil(a_dur + AUDIO_TAIL_S),
                 math.ceil((nar_end or 0.0) + AUDIO_TAIL_S),
                 int(math.ceil(v_dur)))
    pad = max(0.0, target - v_dur)

    out = Path(paths.output) / out_name
    out.parent.mkdir(parents=True, exist_ok=True)
    if pad > 0.01 or _v9_tex:
        _vchain = f"[0:v]tpad=stop_mode=clone:stop_duration={max(pad, 0.0):.3f}"
        if _v9_tex:
            _vchain += f",{_v9_tex}"
        _vchain += "[v]"
        cmd = ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
               "-i", str(concat),
               "-i", str(audio_out),
               "-filter_complex", _vchain,
               "-map", "[v]", "-map", "1:a",
               "-c:v", "libx264", "-preset", "medium", "-crf", "18",
               "-pix_fmt", "yuv420p", "-r", str(fps), "-threads", "1",
               "-c:a", "aac", "-b:a", "192k",
               "-t", f"{target:.3f}",
               "-flags:a", "+bitexact", "-map_metadata", "-1", "-fflags", "+bitexact",
               "-movflags", "+faststart", str(out)]
    else:
        cmd = ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
               "-i", str(concat),
               "-i", str(audio_out),
               "-map", "0:v", "-c:v", "copy",
               "-map", "1:a",
               "-c:a", "aac", "-b:a", "192k",
               "-t", f"{target:.3f}",
               "-flags:a", "+bitexact", "-map_metadata", "-1", "-fflags", "+bitexact",
               "-movflags", "+faststart", str(out)]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"mux failed:\n{p.stderr[-1500:]}")

    # §1 render-time integrity: the video stream may never be shorter than
    # the audio-derived target (catches truncated shot artifacts consumed by
    # concat — QA would catch it too, but the render must fail loudly).
    v_check = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=duration", "-of", "csv=p=0", str(out)],
        capture_output=True, text=True)
    try:
        v_stream = float(v_check.stdout.strip())
    except ValueError:
        v_stream = 0.0
    if v_stream < 0.9 * target:
        out.unlink(missing_ok=True)
        raise RuntimeError(
            f"render5 integrity: video stream {v_stream:.2f}s << expected "
            f"{target:.2f}s (audio {a_dur:.2f}s) — a shot artifact is likely "
            f"truncated; re-run render5.")

    # V6.2 verification ground truth
    audio_info = {"master_dur": round(a_dur, 3),
                  "narration_end": round(nar_end, 3) if nar_end is not None else None,
                  "video_dur": round(target, 3),
                  "tail_s": AUDIO_TAIL_S,
                  "pad_s": round(pad, 3),
                  "sfx_ducked": bool(mixinfo.get("sfx_ducked")),
                  "bed_files_non_null": sum(1 for b in bed_files if b)}
    report = _build_overlay_report(shots, bible, audio_info)
    (Path(paths.build) / "overlay_report.json").write_text(
        json.dumps(report, indent=2) + "\n")
    return out
