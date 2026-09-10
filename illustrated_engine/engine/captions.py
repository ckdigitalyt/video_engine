"""V10_KINETIC -> V11 caption state machine (Jade_todo V10 §2 / v11 P0).

Clause captions are exploded into 2-4 word chunks timed across the cue
window by word-length weighting (no forced alignment available at plan
time; proportional estimation keeps chunks readable and deterministic).
Each chunk renders one PNG per word position with the currently spoken
word highlighted (accent + emphasis bar), so the reader's eye lands on
the active word — Shorts-style.

V11_CAPTION (Jade_todo_v11 P0): normalize_cues enforces exactly one
ACTIVE_CAPTION semantic state — consecutive states are separated by a
clear off-window, declared multi-line states render max 2 lines, and the
band sits BELOW the card so plate-baked text can never collide with it.
Rollback: V11_CAPTION=0 (V10 band, no normalization) and/or V10_KINETIC=0
(legacy clause-caption path in composev5 untouched).
"""
from __future__ import annotations

import re
from pathlib import Path

from PIL import Image, ImageDraw

from engine import flags as _flags
from engine.layout import _font

FRAME_W, FRAME_H = 1080, 1920
# Legacy (V10) kinetic band — Y 0.70-0.76 of the 1080x1920 canvas (1344..1459),
# per the flags.py V10 header. Kept as the rollback geometry: V11_CAPTION=0
# restores this band byte-for-byte.
BAND_TOP = round(0.70 * FRAME_H)    # 1344
BAND_BOT = round(0.76 * FRAME_H)    # 1459
BAND_CY = (BAND_TOP + BAND_BOT) // 2          # 1401
# Carrier canvas: full width, short band strip. Looping a 1080x1920 RGBA
# input per word overlay makes the ffmpeg graph decode ~30 full-frame
# layers per frame; the strip keeps the same composite at ~1/10 the cost.
KIN_CAP_H = 192
# --- caption state machine (Jade_todo_v11 P0) ------------------------------
# Exactly one ACTIVE_CAPTION semantic state: consecutive states are separated
# by a >= STATE_GAP off-window (the previous state is fully removed before
# the next activates), and each state renders at most MAX_LINES lines.
STATE_GAP = 0.05     # s of no-caption between two semantic states
MIN_CUE = 0.30       # a state shorter than this is dropped, not squeezed
MAX_LINES = 2        # hard cap for declared multi-line compositions


def band_rect() -> tuple:
    """Active kinetic caption band (top, bot) in frame coordinates.

    V11_CAPTION: BELOW the card (card bottom + 24). V10's in-card band
    overlapped the plate footer zone after the 9:16 cover-crop — the baked
    footer text showed through the caption scrim as a ghost second caption
    (evidence 2026-09-10: ice_slippery t=2.4/4.7/50 frames). Below-card
    placement makes a plate/caption collision impossible by construction.
    """
    if _flags.caption11():
        from engine.planv5 import CARD_H, CARD_Y0
        top = CARD_Y0 + CARD_H + 24
        return top, top + KIN_CAP_H
    return BAND_TOP, BAND_BOT


def carrier_y() -> int:
    """Y offset of the strip carrier overlay on the 1080x1920 frame."""
    top, _ = band_rect()
    if _flags.caption11():
        return top
    return BAND_CY - KIN_CAP_H // 2


def normalize_cues(cues: list, dur: float | None = None) -> tuple:
    """Caption state machine -> (normalized_cues, repairs).

    Sorts cues by t0, clamps to [0, dur], drops degenerate/blank states, and
    enforces the off-window: the next state may only activate STATE_GAP after
    the previous one ends (overlaps are repaired by shifting the later state
    forward; states squeezed below MIN_CUE are dropped). Every change is
    recorded in `repairs` so caption_qa can gate on authoring defects instead
    of silently absorbing them. Multi-line states (cue["lines"], max
    MAX_LINES) are ONE semantic state sharing one time window.
    """
    repairs: list = []
    items = []
    for c in cues or []:
        t0, t1 = float(c.get("t0", 0.0)), float(c.get("t1", 0.0))
        lines = c.get("lines")
        text = str(c.get("text", ""))
        has_text = bool(text.strip()) or bool(
            lines and any(str(l).strip() for l in lines))
        if dur is not None:
            if t0 < -0.01 or t1 > float(dur) + 0.01:
                repairs.append({"reason": "clamped_to_shot", "from": [t0, t1]})
            t0, t1 = max(0.0, t0), min(float(dur), t1)
        if not has_text or t1 - t0 < MIN_CUE:
            repairs.append({"reason": "dropped_degenerate", "t0": t0,
                            "t1": t1, "text": text[:40]})
            continue
        n_lines = _cue_lines(c)[1]
        if n_lines > MAX_LINES:
            repairs.append({"reason": "line_cap_exceeded", "lines": n_lines,
                            "text": text[:40]})
        items.append(dict(c, t0=t0, t1=t1))
    items.sort(key=lambda c: (float(c["t0"]), float(c["t1"])))
    out: list = []
    for c in items:
        if out:
            prev = out[-1]
            earliest = float(prev["t1"]) + STATE_GAP
            if float(c["t0"]) < earliest - 1e-9:
                repairs.append({"reason": "overlap_or_gap_repair",
                                "shifted_from": c["t0"], "shifted_to": earliest,
                                "text": str(c.get("text", ""))[:40]})
                c = dict(c, t0=earliest)
            if float(c["t1"]) - float(c["t0"]) < MIN_CUE:
                repairs.append({"reason": "dropped_after_repair",
                                "t0": c["t0"], "t1": c["t1"],
                                "text": str(c.get("text", ""))[:40]})
                continue
        out.append(c)
    return out, repairs


def _cue_lines(cue: dict) -> tuple:
    """-> (list_of_line_strings, n_lines). Explicit cue["lines"] wins, then
    embedded newlines, else the plain text as a single line."""
    lines = cue.get("lines")
    if lines and all(str(l).strip() for l in lines):
        return [str(l) for l in lines], len(lines)
    text = str(cue.get("text", ""))
    if "\n" in text:
        parts = [p for p in text.split("\n") if p.strip()]
        return parts, len(parts)
    return [text], 1


MAX_CHUNK = 4
MIN_CHUNK = 2
BASE_SIZE = 64
MARGIN_X = 56

_WORD_RE = re.compile(r"[A-Za-z0-9'\u2019%$.,:;!?+-]+")


def _words(text: str) -> list:
    return _WORD_RE.findall(str(text or ""))


def chunk_cues(shot: dict, cues: list | None = None) -> list:
    """caption cues -> kinetic chunks (state-machine normalized by default).

    Each chunk: {words, lines, t0, t1, windows} where windows is
    [(word, wt0, wt1)] estimated proportionally to word length inside the
    cue window. A chunk never crosses a declared line boundary; `lines`
    carries the per-line word lists (1 or 2 entries) for the carrier PNG.
    """
    chunks = []
    if cues is None:
        cues, _rep = normalize_cues(shot.get("captions") or [])
    for cue in cues or []:
        t0, t1 = float(cue.get("t0", 0.0)), float(cue.get("t1", 0.0))
        line_texts, _n = _cue_lines(cue)
        line_texts = line_texts[:MAX_LINES]
        line_words = [_words(lt) for lt in line_texts]
        if not any(line_words) or t1 - t0 < 0.3:
            continue
        # flatten words (line order preserved) and time them across the cue
        flat = [w for ws in line_words for w in ws]
        n = len(flat)
        if n <= MAX_CHUNK:
            groups = [list(range(n))]
        else:
            k = -(-n // MAX_CHUNK)
            size = max(MIN_CHUNK, min(MAX_CHUNK, -(-n // k)))
            groups = [list(range(i, min(i + size, n)))
                      for i in range(0, n, size)]
        wts = [max(2.0, len(w)) for w in flat]
        tot = sum(wts)
        acc, wtimes = 0.0, []
        for w, wt in zip(flat, wts):
            wt0 = t0 + (t1 - t0) * acc / tot
            acc += wt
            wtimes.append((w, wt0, t0 + (t1 - t0) * acc / tot))
        # line id per flat word index
        line_of = {}
        i = 0
        for li, ws in enumerate(line_words):
            for w in ws:
                line_of[i] = li
                i += 1
        for g in groups:
            seg = [wtimes[i] for i in g]
            per_line: dict = {}
            for i in g:
                per_line.setdefault(line_of[i], []).append(flat[i])
            chunks.append({"words": [s[0] for s in seg],
                           "lines": [per_line[k] for k in sorted(per_line)],
                           "t0": seg[0][1], "t1": seg[-1][2],
                           "windows": seg})
    return chunks


def _chunk_font(chunk, bible) -> tuple:
    """-> (font, display_words, width). Steps down until the chunk fits its
    lines (max MAX_LINES) in both width and carrier height."""
    from engine import bible as B
    typ = bible.get("typography", {})
    per_line = chunk.get("lines") or [chunk["words"]]
    words = [w.upper() for line in per_line for w in line]
    n_lines = min(max(1, len(per_line)), MAX_LINES)
    size = BASE_SIZE if n_lines == 1 else 56  # 2 lines must fit KIN_CAP_H
    for _ in range(10):
        f = _font(typ.get("display", "BebasNeue-Regular.ttf"), size)
        probe = Image.new("RGBA", (8, 8))
        d = ImageDraw.Draw(probe)
        widths = []
        for line in per_line:
            ws = [w.upper() for w in line]
            widths.append(sum(d.textlength(w, font=f) for w in ws)
                          + d.textlength(" ", font=f) * (len(ws) - 1))
        width = max(widths)
        asc, desc = f.getmetrics()
        if (width <= FRAME_W - 2 * MARGIN_X
                and n_lines * (asc + desc) <= KIN_CAP_H - 28) or size <= 30:
            return f, per_line, width
        size -= 4
    return f, per_line, width


def chunk_png(chunk: dict, bible: dict, out: Path, active: int) -> dict:
    """One chunk PNG with word `active` highlighted. -> layout dict.

    Rendered on the KIN_CAP_H strip carrier; bbox is returned in FULL-frame
    coordinates (y offset by the active carrier_y) so downstream anchoring
    keeps working. Declared 2-line chunks stack their lines centered — still
    ONE caption state on ONE carrier window."""
    from engine import bible as B
    f, per_line, width = _chunk_font(chunk, bible)
    cy_off = carrier_y()
    img = Image.new("RGBA", (FRAME_W, KIN_CAP_H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img, "RGBA")
    line_h = f.size
    asc, desc = f.getmetrics()
    n_lines = len(per_line)
    block_h = n_lines * (asc + desc)
    y0 = int(min(max(KIN_CAP_H // 2 - block_h / 2.0, 0), KIN_CAP_H - block_h))
    text_rgb = B.rgb255(bible, "text")
    if 0.299 * text_rgb[0] + 0.587 * text_rgb[1] + 0.114 * text_rgb[2] < 140:
        text_rgb = (245, 242, 235)  # dark ink is unreadable on the scrim
    text_col = text_rgb + (235,)
    accent = B.rgb255(bible, "accent") + (255,)
    # pass 1 — word positions only, so the scrim can go UNDER the text
    boxes = []  # (x, y, x1, y1, word, flat_index)
    wi = 0
    for li, line in enumerate(per_line):
        lw = sum(d.textlength(w.upper(), font=f) for w in line) \
            + d.textlength(" ", font=f) * (len(line) - 1)
        x = (FRAME_W - lw) / 2.0
        ly = y0 + li * (asc + desc)
        for w in line:
            ww = d.textlength(w.upper(), font=f)
            boxes.append((x, ly, x + ww, ly + line_h, w, wi))
            x += ww + d.textlength(" ", font=f)
            wi += 1
    pad_x, pad_y = 26, 14
    bx0 = min(b[0] for b in boxes) - pad_x
    by0 = min(b[1] for b in boxes) - pad_y
    bx1 = max(b[2] for b in boxes) + pad_x
    by1 = max(b[3] for b in boxes) + pad_y
    d.rounded_rectangle([bx0, by0, bx1, by1], radius=18, fill=(0, 0, 0, 105))
    # pass 2 — words on top of the scrim
    for (wx, wy, wx1, wy1, w, flat_i) in boxes:
        if flat_i == active:
            d.text((wx + 2, wy + 4), w.upper(), font=f, fill=(0, 0, 0, 160))
            d.text((wx, wy), w.upper(), font=f, fill=accent)
            d.rounded_rectangle([wx + 2, wy1 + 6, wx1 - 2, wy1 + 12],
                                radius=3, fill=accent[:3] + (200,))
        else:
            d.text((wx + 2, wy + 4), w.upper(), font=f, fill=(0, 0, 0, 140))
            d.text((wx, wy), w.upper(), font=f, fill=text_col)
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, "PNG")
    return {"ok": True, "png": str(out),
            "bbox": (bx0, by0 + cy_off, bx1, by1 + cy_off),
            "font": f, "y0": y0 + cy_off}


def build_shot_captions(shot: dict, bible: dict, work_dir: Path,
                        dur: float | None = None) -> tuple:
    """-> (inputs, cue_bboxes, normalized_cues, repairs).

    inputs: flat list of {png, t0, t1} overlay windows in time order —
    one PNG per (chunk, word) with that word active. The state-machine
    invariant is asserted here: windows may touch (within one cue) but never
    overlap — two visible caption carriers at one instant is a P0 defect and
    fails the render loudly instead of shipping ghost captions.
    cue_bboxes: one bbox per NORMALIZED cue (None when the cue produced no
    chunks) so downstream consumers that anchor on caption geometry
    (text_emphasis rules) keep working.
    """
    cues, repairs = normalize_cues(shot.get("captions") or [], dur)
    chunks = chunk_cues(shot, cues=cues)
    work_dir = Path(work_dir) / "kin_caps"
    inputs = []
    cue_bboxes = []
    ci = 0
    for cue in cues:
        t0, t1 = float(cue.get("t0", 0.0)), float(cue.get("t1", 0.0))
        mine = [c for c in chunks
                if c["t0"] >= t0 - 0.05 and c["t1"] <= t1 + 0.05]
        if not mine:
            cue_bboxes.append(None)
            continue
        bbox = None
        for c in mine:
            for wi in range(len(c["windows"])):
                png = work_dir / f"cap{ci:03d}_w{wi}.png"
                lay = chunk_png(c, bible, png, active=wi)
                w0, w1 = c["windows"][wi][1], c["windows"][wi][2]
                inputs.append({"png": lay["png"], "t0": w0, "t1": w1,
                               "top": carrier_y()})
                bbox = lay["bbox"]
                ci += 1
        cue_bboxes.append(bbox)
    inputs.sort(key=lambda e: e["t0"])
    for a, b in zip(inputs, inputs[1:]):
        if b["t0"] < a["t1"] - 1e-6:
            raise ValueError(
                f"caption state machine violated: carrier {a['png']} "
                f"[{a['t0']:.3f},{a['t1']:.3f}] overlaps {b['png']} "
                f"[{b['t0']:.3f},{b['t1']:.3f}] — two ACTIVE caption states")
    return inputs, cue_bboxes, cues, repairs
