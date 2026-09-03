"""Progressive diagram construction (V3 §7).

Diagrams are never shown complete. Each diagram renders as ordered STAGES —
baseline -> subject -> comparison -> annotation -> key number -> conclusion —
and the edit plan reveals them in narrative order via stage-overlay events.

Cards are drawn at the V3 full-bleed visual size (1080x1744) so captions
overlay the card with dynamic backing instead of a reserved black box.

write_stages() produces:
    assets/<name>.png          (raw stage card — usable as a shot base)
    build/diag_stages/<name>_full.png (1080x1920 transparent frame with the
                                stage card at y=176 — used as overlay)
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from engine.diagrams import _fonts, _ridge, _dashed_line
from engine.layout import CANVAS_W, CANVAS_H, VISUAL_RECT, _font

VW3, VH3 = 1080, 1744
OFF_Y = VISUAL_RECT[1]  # 176 — card offset inside the full frame


def _card3(bible) -> tuple:
    """Parchment card at the v3 visual size + ink/accent colours."""
    from engine import bible as B
    ink = B.rgb255(bible, "text")
    navy = B.rgb255(bible, "primary")
    accent = B.rgb255(bible, "accent")
    img = Image.new("RGB", (VW3, VH3), (233, 223, 200))
    rng = np.random.default_rng(23)
    arr = np.asarray(img).astype(np.float32)
    arr += rng.normal(0, 3.0, arr.shape).astype(np.float32)
    img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGB")
    return img, ImageDraw.Draw(img, "RGBA"), ink, navy, accent


# ------------------------------------------------------------- timeline ----
# Stages: baseline -> subject (seedling) -> comparison (pyramid)
#         -> annotation (270 yrs) -> key number (4,850) -> conclusion

def _tl_base(bible):
    img, d, ink, navy, accent = _card3(bible)
    disp, body = _fonts(bible)
    d.text((80, 96), "ONE TREE, FIVE MILLENNIA", font=disp(58), fill=navy + (255,))
    axis_y = int(VH3 * 0.56)
    d.line([(80, axis_y), (VW3 - 80, axis_y)], fill=navy + (255,), width=5)
    return img, d, ink, navy, accent, disp, body, axis_y


def _tl_sprout(img, d, ink, navy, accent, disp, body, axis_y):
    cx = int(VW3 * 0.15)
    pts = _ridge(cx, axis_y - 10, axis_y - int(VH3 * 0.13), 100, sharp=1.5)
    d.polygon(pts, fill=navy + (180,))
    d.ellipse([cx - 11, axis_y - 11, cx + 11, axis_y + 11], fill=accent + (255,))
    d.text((cx - 92, axis_y + 26), "2832 BC", font=body(27), fill=navy + (235,))
    d.text((cx - 92, axis_y + 60), "A SEEDLING", font=body(23), fill=navy + (210,))
    return img


def _tl_pyramid(img, d, ink, navy, accent, disp, body, axis_y, highlight=False):
    cx = int(VW3 * 0.40)
    ph = int(VH3 * 0.115)
    d.polygon([(cx - 62, axis_y - 8), (cx + 62, axis_y - 8), (cx, axis_y - 8 - ph)],
              fill=navy + (200,))
    d.ellipse([cx - 11, axis_y - 11, cx + 11, axis_y + 11], fill=accent + (255,))
    d.text((cx - 100, axis_y + 26), "2560 BC", font=body(27), fill=navy + (235,))
    d.text((cx - 100, axis_y + 60), "GREAT PYRAMID", font=body(23), fill=navy + (210,))
    if highlight:
        d.ellipse([cx - 105, axis_y - ph - 50, cx + 105, axis_y + 55],
                  outline=accent + (230,), width=6)
        d.text((cx - 170, axis_y - ph - 118), "ALREADY 270 YEARS OLD",
               font=body(30), fill=accent + (255,))
    return img


def _tl_today(img, d, ink, navy, accent, disp, body, axis_y, key=True):
    cx = int(VW3 * 0.85)
    d.ellipse([cx - 11, axis_y - 11, cx + 11, axis_y + 11], fill=accent + (255,))
    d.text((cx - 150, axis_y + 26), "TODAY", font=body(27), fill=navy + (235,))
    d.text((cx - 150, axis_y + 60), "4,850 YEARS", font=body(23), fill=accent + (255,))
    if key:
        d.text((cx - 150, axis_y - 88), "4,850", font=disp(64), fill=accent + (255,))
    return img


def _tl_conclusion(img, d, ink, navy, accent, disp, body):
    d.text((80, int(VH3 * 0.72)), "STILL GROWING", font=disp(46), fill=accent + (255,))
    d.line([(80, int(VH3 * 0.72) + 66), (80 + 340, int(VH3 * 0.72) + 66)],
           fill=accent + (220,), width=5)
    return img


def timeline_stages(bible) -> list:
    out = []
    img, d, ink, navy, accent, disp, body, axis_y = _tl_base(bible)
    out.append(img.copy())                                   # s0 baseline
    _tl_sprout(img, d, ink, navy, accent, disp, body, axis_y)
    out.append(img.copy())                                   # s1 subject
    _tl_pyramid(img, d, ink, navy, accent, disp, body, axis_y)
    out.append(img.copy())                                   # s2 comparison
    _tl_pyramid(img, d, ink, navy, accent, disp, body, axis_y, highlight=True)
    out.append(img.copy())                                   # s3 annotation
    _tl_today(img, d, ink, navy, accent, disp, body, axis_y)
    out.append(img.copy())                                   # s4 key number
    _tl_conclusion(img, d, ink, navy, accent, disp, body)
    out.append(img.copy())                                   # s5 conclusion
    return out


# ----------------------------------------------------------- secret map ----
# Stages: baseline (ridge outline) -> redaction -> typography conclusion

def _map_base(bible):
    img, d, ink, navy, accent = _card3(bible)
    disp, body = _fonts(bible)
    d.text((80, 96), "WHERE DOES IT STAND?", font=disp(58), fill=navy + (255,))
    # mountain ridgeline across the card
    pts = _ridge(int(VW3 * 0.5), int(VH3 * 0.52), int(VH3 * 0.24), 460, sharp=2.4)
    d.polygon([(x, min(y, int(VH3 * 0.52))) for x, y in pts], fill=navy + (150,))
    pts2 = _ridge(int(VW3 * 0.22), int(VH3 * 0.52), int(VH3 * 0.17), 190, sharp=2.0)
    d.polygon([(x, min(y, int(VH3 * 0.52))) for x, y in pts2], fill=navy + (190,))
    d.text((80, int(VH3 * 0.60)), "WHITE MOUNTAINS, CALIFORNIA — ~3,000 M",
           font=body(26), fill=navy + (230,))
    return img, d, ink, navy, accent, disp, body


def _map_redact(img, d, ink, navy, accent, disp, body):
    d.text((80, int(VH3 * 0.68)), "EXACT LOCATION: UNDISCLOSED",
           font=body(28), fill=accent + (255,))
    y0 = int(VH3 * 0.30)
    for i, (x0, w) in enumerate([(300, 190), (560, 150), (790, 170)]):
        d.rounded_rectangle([x0, y0 + (i % 2) * 40, x0 + w, y0 + 34 + (i % 2) * 40],
                            radius=8, fill=(12, 12, 16, 235))
        cx = x0 + w / 2
        cy = y0 + 17 + (i % 2) * 40
        r = 12
        d.line([(cx - r, cy - r), (cx + r, cy + r)], fill=accent + (255,), width=5)
        d.line([(cx - r, cy + r), (cx + r, cy - r)], fill=accent + (255,), width=5)
    return img


def _map_secret(img, d, ink, navy, accent, disp, body):
    f = disp(92)
    text = "LOCATION: SECRET"
    tw = d.textlength(text, font=f)
    d.text(((VW3 - tw) / 2, int(VH3 * 0.70)), text, font=f, fill=accent + (255,))
    sub = "and that is exactly why it survives"
    fs = body(30)
    sw = d.textlength(sub, font=fs)
    d.text(((VW3 - sw) / 2, int(VH3 * 0.70) + 116), sub, font=fs, fill=navy + (235,))
    return img


def secret_map_stages(bible) -> list:
    out = []
    img, d, ink, navy, accent, disp, body = _map_base(bible)
    out.append(img.copy())                                   # s0 baseline
    _map_redact(img, d, ink, navy, accent, disp, body)
    out.append(img.copy())                                   # s1 redaction
    _map_secret(img, d, ink, navy, accent, disp, body)
    out.append(img.copy())                                   # s2 conclusion
    return out


# ---------------------------------------------------------------- write ----

DIAGRAMS_V3 = {
    "D1_timeline": timeline_stages,
    "D4_map": secret_map_stages,
}


def write_stages(paths, bible, story_id: str = None) -> dict:
    """Render every staged diagram; write assets + full-frame overlays."""
    assets = Path(paths.assets)
    build = Path(paths.build)
    out_dir = build / "diag_stages"
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = {}
    for name, fn in DIAGRAMS_V3.items():
        stages = fn(bible)
        manifest[name] = []
        for i, card in enumerate(stages):
            apath = assets / f"{name}_s{i}.png"
            card.save(apath, "PNG")
            frame = Image.new("RGBA", (CANVAS_W, CANVAS_H), (0, 0, 0, 0))
            frame.paste(card.convert("RGBA"), (0, OFF_Y))
            fpath = out_dir / f"{name}_s{i}_full.png"
            frame.save(fpath, "PNG")
            manifest[name].append({"stage": i, "asset": f"{name}_s{i}",
                                   "full": str(fpath)})
    (build / "diag_stages" / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return manifest
