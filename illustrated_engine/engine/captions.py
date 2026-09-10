"""V10_KINETIC — word-level kinetic subtitles (Jade_todo V10 §2).

Clause captions are exploded into 2-4 word chunks timed across the cue
window by word-length weighting (no forced alignment available at plan
time; proportional estimation keeps chunks readable and deterministic).
Each chunk renders one PNG per word position with the currently spoken
word highlighted (accent + emphasis bar), so the reader's eye lands on
the active word — Shorts-style.

Placement: chunk box centered in the Y 0.70-0.76 band of the 1080x1920
canvas (1344..1459), per the flags.py V10 header. Rollback: V10_KINETIC=0
restores the legacy clause-caption path in composev5 untouched.
"""
from __future__ import annotations

import re
from pathlib import Path

from PIL import Image, ImageDraw

from engine.layout import _font

FRAME_W, FRAME_H = 1080, 1920
BAND_TOP = round(0.70 * FRAME_H)    # 1344
BAND_BOT = round(0.76 * FRAME_H)    # 1459
BAND_CY = (BAND_TOP + BAND_BOT) // 2          # 1401
# Carrier canvas: full width, short band strip. Looping a 1080x1920 RGBA
# input per word overlay makes the ffmpeg graph decode ~30 full-frame
# layers per frame; the strip keeps the same composite at ~1/10 the cost.
KIN_CAP_H = 192
KIN_CAP_Y = BAND_CY - KIN_CAP_H // 2          # overlay y on the 1080x1920 frame
MAX_CHUNK = 4
MIN_CHUNK = 2
BASE_SIZE = 64
MARGIN_X = 56

_WORD_RE = re.compile(r"[A-Za-z0-9'\u2019%$.,:;!?+-]+")


def _words(text: str) -> list:
    return _WORD_RE.findall(str(text or ""))


def chunk_cues(shot: dict) -> list:
    """shot["captions"] cues -> kinetic chunks.

    Each chunk: {words, t0, t1, windows} where windows is [(word, wt0, wt1)]
    estimated proportionally to word length inside the cue window.
    """
    chunks = []
    for cue in shot.get("captions", []) or []:
        t0, t1 = float(cue.get("t0", 0.0)), float(cue.get("t1", 0.0))
        ws = _words(cue.get("text", ""))
        if not ws or t1 - t0 < 0.3:
            continue
        n = len(ws)
        if n <= MAX_CHUNK:
            groups = [ws]
        else:
            k = -(-n // MAX_CHUNK)
            size = max(MIN_CHUNK, min(MAX_CHUNK, -(-n // k)))
            groups = [ws[i:i + size] for i in range(0, n, size)]
        wts = [max(2.0, len(w)) for w in ws]
        tot = sum(wts)
        acc, wtimes = 0.0, []
        for w, wt in zip(ws, wts):
            wt0 = t0 + (t1 - t0) * acc / tot
            acc += wt
            wtimes.append((w, wt0, t0 + (t1 - t0) * acc / tot))
        i = 0
        for g in groups:
            seg = wtimes[i:i + len(g)]
            chunks.append({"words": [s[0] for s in seg],
                           "t0": seg[0][1], "t1": seg[-1][2],
                           "windows": seg})
            i += len(g)
    return chunks


def _chunk_font(chunk, bible) -> tuple:
    """-> (font, display_words, width). Steps down until the chunk fits."""
    from engine import bible as B
    typ = bible.get("typography", {})
    words = [w.upper() for w in chunk["words"]]
    size = BASE_SIZE
    for _ in range(8):
        f = _font(typ.get("display", "BebasNeue-Regular.ttf"), size)
        probe = Image.new("RGBA", (8, 8))
        d = ImageDraw.Draw(probe)
        width = sum(d.textlength(w, font=f) for w in words) \
            + d.textlength(" ", font=f) * (len(words) - 1)
        if width <= FRAME_W - 2 * MARGIN_X or size <= 34:
            return f, words, width
        size -= 4
    return f, words, width


def chunk_png(chunk: dict, bible: dict, out: Path, active: int) -> dict:
    """One chunk PNG with word `active` highlighted. -> layout dict.

    Rendered on the KIN_CAP_H strip carrier; bbox is returned in FULL-frame
    coordinates (y offset by KIN_CAP_Y) so downstream anchoring keeps
    working. The strip is overlaid at y=KIN_CAP_Y by the compositor."""
    from engine import bible as B
    f, words, width = _chunk_font(chunk, bible)
    img = Image.new("RGBA", (FRAME_W, KIN_CAP_H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img, "RGBA")
    line_h = f.size
    asc, desc = f.getmetrics()
    cy = KIN_CAP_H // 2
    y = int(min(max(cy - (asc + desc) / 2.0, 0), KIN_CAP_H - line_h))
    x = (FRAME_W - width) / 2.0
    text_rgb = B.rgb255(bible, "text")
    if 0.299 * text_rgb[0] + 0.587 * text_rgb[1] + 0.114 * text_rgb[2] < 140:
        text_rgb = (245, 242, 235)  # dark ink is unreadable on the scrim
    text_col = text_rgb + (235,)
    accent = B.rgb255(bible, "accent") + (255,)
    # pass 1 — word positions only, so the scrim can go UNDER the text
    boxes = []
    for w in words:
        ww = d.textlength(w, font=f)
        boxes.append((x, y, x + ww, y + line_h, w))
        x += ww + d.textlength(" ", font=f)
    pad_x, pad_y = 26, 14
    bx0 = min(b[0] for b in boxes) - pad_x
    by0 = min(b[1] for b in boxes) - pad_y
    bx1 = max(b[2] for b in boxes) + pad_x
    by1 = max(b[3] for b in boxes) + pad_y
    d.rounded_rectangle([bx0, by0, bx1, by1], radius=18, fill=(0, 0, 0, 105))
    # pass 2 — words on top of the scrim
    for i, (wx, wy, wx1, wy1, w) in enumerate(boxes):
        if i == active:
            d.text((wx + 2, wy + 4), w, font=f, fill=(0, 0, 0, 160))
            d.text((wx, wy), w, font=f, fill=accent)
            d.rounded_rectangle([wx + 2, wy1 + 6, wx1 - 2, wy1 + 12],
                                radius=3, fill=accent[:3] + (200,))
        else:
            d.text((wx + 2, wy + 4), w, font=f, fill=(0, 0, 0, 140))
            d.text((wx, wy), w, font=f, fill=text_col)
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, "PNG")
    return {"ok": True, "png": str(out),
            "bbox": (bx0, by0 + KIN_CAP_Y, bx1, by1 + KIN_CAP_Y),
            "font": f, "y0": y + KIN_CAP_Y}


def build_shot_captions(shot: dict, bible: dict, work_dir: Path) -> tuple:
    """-> (inputs, cue_bboxes).

    inputs: flat list of {png, t0, t1} overlay windows in time order —
    one PNG per (chunk, word) with that word active.
    cue_bboxes: one bbox per ORIGINAL cue (aligned with shot["captions"],
    None when the cue produced no chunks) so downstream consumers that
    anchor on caption geometry (text_emphasis rules) keep working.
    """
    chunks = chunk_cues(shot)
    work_dir = Path(work_dir) / "kin_caps"
    inputs = []
    cue_bboxes = []
    ci = 0
    for cue in shot.get("captions", []) or []:
        t0, t1 = float(cue.get("t0", 0.0)), float(cue.get("t1", 0.0))
        mine = [c for c in chunks
                if c["t0"] >= t0 - 0.05 and c["t1"] <= t1 + 0.05]
        if not mine:
            cue_bboxes.append(None)
            continue
        bbox = None
        for c in mine:
            for wi in range(len(c["words"])):
                png = work_dir / f"cap{ci:03d}_w{wi}.png"
                lay = chunk_png(c, bible, png, active=wi)
                w0, w1 = c["windows"][wi][1], c["windows"][wi][2]
                inputs.append({"png": lay["png"], "t0": w0, "t1": w1,
                               "top": KIN_CAP_Y})
                bbox = lay["bbox"]
                ci += 1
        cue_bboxes.append(bbox)
    inputs.sort(key=lambda e: e["t0"])
    return inputs, cue_bboxes
