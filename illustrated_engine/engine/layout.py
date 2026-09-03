"""True 9:16 composition engine — full-bleed visual, zero unintentional voids.

Canvas 1080x1920 allocation (Jade_todo v2 target):
  brand zone    y  64..184   (6.2%)  big title on opening shots, small marker after
  visual zone   y 176..1504  (69.2%) full-width 1080x1328, cover-cropped plates
  caption zone  y 1536..1856 (16.7%) 2-line editorial captions
The chrome (everything outside the visual) is painted in the Bible background
colour — never black filler. Plates are intelligently cropped to the visual
zone aspect; vertical-compatible sources crop less.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

CANVAS_W, CANVAS_H = 1080, 1920

BRAND_RECT = (0, 64, 1080, 120)      # x, y, w, h
VISUAL_RECT = (0, 176, 1080, 1328)   # 1080x1328
CAPTION_RECT = (0, 1536, 1080, 320)

# V3: full-bleed visual — captions overlay the image with dynamic backing
# (no permanently reserved caption box; §3 of the V3 brief)
VISUAL_RECT_V3 = (0, 176, 1080, 1744)  # 1080x1744, visual runs to canvas bottom

FONT_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"


def _font(name: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONT_DIR / name), size)


def smart_crop(img: Image.Image, out_w: int, out_h: int,
               bias_y: float = 0.42) -> Image.Image:
    """Cover-crop `img` to out_w:out_h.

    Horizontal crop: pick the x-window with the highest edge energy (cheap
    saliency) so subjects stay in frame. Vertical crop: bias slightly above
    centre (sky/subject headroom), overridable.
    Deterministic; no randomness.
    """
    im = img.convert("RGB")
    W, H = im.size
    tgt = out_w / out_h
    cur = W / H
    if abs(cur - tgt) < 1e-3:
        return im.resize((out_w, out_h), Image.LANCZOS)

    if cur > tgt:
        # too wide -> slide an x-window over gradient energy
        cw = max(8, int(round(H * tgt)))
        g = np.asarray(im.convert("L"), np.float32)
        gy, gx = np.gradient(g)
        energy = (np.abs(gx) + np.abs(gy)).sum(axis=0)
        csum = np.concatenate([[0.0], np.cumsum(energy)])
        best_x, best_e = 0, -1.0
        step = max(1, (W - cw) // 12)
        for x in range(0, W - cw + 1, step):
            e = csum[x + cw] - csum[x]
            if e > best_e:
                best_e, best_x = e, x
        box = (best_x, 0, best_x + cw, H)
    else:
        # too tall -> vertical window biased by bias_y
        ch = max(8, int(round(W / tgt)))
        y0 = int(round((H - ch) * bias_y))
        box = (0, y0, W, y0 + ch)
    return im.crop(box).resize((out_w, out_h), Image.LANCZOS)


def base_frame(bible: dict) -> Image.Image:
    """Canvas painted in the Bible background colour (never black filler)."""
    from engine import bible as B
    bg = B.rgb255(bible, "background")
    frame = Image.new("RGB", (CANVAS_W, CANVAS_H), bg)
    # faint paper grain over the chrome for cohesion with graded plates
    grain = float(bible.get("texture", {}).get("grain", 0.012)) * 0.6
    if grain > 0:
        rng = np.random.default_rng(11)
        arr = np.asarray(frame).astype(np.float32)
        arr += rng.normal(0.0, grain * 255.0, arr.shape).astype(np.float32) * 0.35
        frame = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGB")
    return frame


def brand_block(frame: Image.Image, bible: dict, shot: dict) -> Image.Image:
    """Opening shots: large display title. Later shots: small brand marker."""
    from engine import bible as B
    draw = ImageDraw.Draw(frame, "RGBA")
    text_col = B.rgb255(bible, "text") + (255,)
    muted = B.rgb255(bible, "muted") + (200,)
    typ = bible.get("typography", {})
    x0, y0, w0, h0 = BRAND_RECT

    if shot.get("opening"):
        title = str(shot.get("title", bible.get("brand", ""))).upper()
        # width-fit stepping: protect longer titles the way captions are protected
        size, max_w = 84, CANVAS_W - 2 * 64
        f = _font(typ.get("display", "BebasNeue-Regular.ttf"), size)
        while draw.textlength(title, font=f) > max_w and size > 40:
            size -= 6
            f = _font(typ.get("display", "BebasNeue-Regular.ttf"), size)
        tw = draw.textlength(title, font=f)
        draw.text(((CANVAS_W - tw) / 2, y0 + (h0 - size) / 2 - 6), title,
                  font=f, fill=text_col)
    else:
        marker = str(bible.get("brand", "")).upper()
        f = _font(typ.get("body", "Inter-Variable.ttf"), 26)
        tw = draw.textlength(marker, font=f)
        draw.text((64, y0 + (h0 - 26) / 2 - 4), marker, font=f, fill=muted)
        # right-aligned episode/plate tag keeps the zone from feeling empty
        tag = str(shot.get("tag", ""))
        if tag:
            ft = _font(typ.get("body", "Inter-Variable.ttf"), 22)
            ttw = draw.textlength(tag.upper(), font=ft)
            draw.text((CANVAS_W - 64 - ttw, y0 + (h0 - 22) / 2), tag.upper(),
                      font=ft, fill=muted)
    return frame


def compose_frame(bible: dict, shot: dict, plate_path, visual_img=None) -> Image.Image:
    """Full v2 frame: background + full-bleed visual + brand/title block."""
    frame = base_frame(bible)
    vis = smart_crop(Image.open(plate_path) if visual_img is None else visual_img,
                     VISUAL_RECT[2], VISUAL_RECT[3],
                     bias_y=float(shot.get("crop_bias_y", 0.42)))
    frame.paste(vis, (VISUAL_RECT[0], VISUAL_RECT[1]))
    frame = brand_block(frame, bible, shot)
    return frame
