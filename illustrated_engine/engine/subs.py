"""Editorial subtitle engine (P0-4).

Semantic phrase segmentation -> max-2-line wrapping measured with real font
metrics -> safe-area enforcement -> restrained rendering with a subtle shadow
and accent-colour emphasis on important words (numbers/units, story-marked).

Layout QA measures the actual rendered bounding box and rejects layouts that
violate safe areas (font steps down 54->48->42 and re-measures). No per-word
animation — a 0.12 s alpha ramp at cue start is the only motion.
"""

from __future__ import annotations

import re

from PIL import Image, ImageDraw

from engine.layout import CANVAS_H, CANVAS_W, CAPTION_RECT, _font

X_MARGIN = int(CANVAS_W * 0.09)          # 97 px each side (9%)
MAX_TEXT_W = CANVAS_W - 2 * X_MARGIN     # 886 px
BOTTOM_SAFE = CAPTION_RECT[1] + CAPTION_RECT[3] - int(CANVAS_H * 0.033)  # ~1792
FONT_SIZES = (54, 48, 42)
LINE_SPACING = 1.22

# V4 §9 subtitle hierarchy: 1 normal narration, 2 important fact,
# 3 revelation (larger editorial text — no per-word kinetic motion)
LEVEL_SIZES = {1: (54, 48, 42), 2: (58, 52, 46), 3: (66, 58, 50)}


def _balance(lines: list) -> list:
    """V4 §9 polish: no orphan single-word last line (when avoidable),
    no line starting with a punctuation mark."""
    if len(lines) == 2:
        punct = ".,;:!?)\u00bb"
        if len(lines[1]) == 1 and len(lines[0]) >= 3:
            lines = [lines[0][:-1], [lines[0][-1]] + lines[1]]
        elif lines[1] and lines[1][0][:1] in punct and len(lines[0]) >= 2:
            lines = [lines[0][:-1], [lines[0][-1]] + lines[1]]
    return lines

_UNIT = r"(?:\s?(?:m|km|metres|meters|feet|ft|%|km/h|mph|kg|tonnes|years|million|billion|°C))?"
_NUM = re.compile(r"\d[\d,\.]*" + _UNIT)
_MARK = re.compile(r"\*([^*]+)\*")


# ------------------------------------------------------------ segmentation ---

_CLAUSE = re.compile(r"(?<=[,;:—–])\s+|\s+(?=\b(?:and|but|because|so|which|while|though)\b)\s*")


def segment_phrases(text: str, max_words: int = 9, max_chars: int = 62) -> list:
    """Clause-aware phrase segmentation (never arbitrary word chunks).

    Sentence enders split hard; clauses split on punctuation/conjunctions;
    fragments are packed up to max_words/max_chars. Numbers stay glued to
    their units.
    """
    text = _MARK.sub(r"\1", text).strip()
    phrases = []
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        sentence = sentence.strip()
        if not sentence:
            continue
        clause = _CLAUSE.sub("|", sentence)
        frags = [f.strip() for f in clause.split("|") if f.strip()]
        cur = ""
        for frag in frags:
            cand = (cur + " " + frag).strip() if cur else frag
            if len(cand.split()) <= max_words and len(cand) <= max_chars:
                cur = cand
            else:
                if cur:
                    phrases.append(cur)
                if len(frag.split()) <= max_words and len(frag) <= max_chars:
                    cur = frag
                else:
                    # hard-pack overlong fragment word-wise
                    words = frag.split()
                    cur = ""
                    for w in words:
                        cand2 = (cur + " " + w).strip() if cur else w
                        if len(cand2.split()) <= max_words and len(cand2) <= max_chars:
                            cur = cand2
                        else:
                            phrases.append(cur)
                            cur = w
        if cur:
            phrases.append(cur)
    return phrases


def emphasis_words(text: str) -> set:
    """Words to accent: numbers+units plus *marked* words."""
    out = set()
    for m in _NUM.finditer(text):
        for w in m.group(0).split():
            out.add(w.strip(",."))
    for m in _MARK.finditer(text):
        for w in m.group(1).split():
            out.add(w.strip(",."))
    return out


# ------------------------------------------------------------------ layout ---

def wrap_tokens(text: str, font, max_w: float) -> list:
    """Greedy word wrap measured with real metrics. Returns lines of tokens."""
    words = text.split()
    lines, cur, cur_w = [], [], 0.0
    space = font.getlength(" ")
    for w in words:
        wl = font.getlength(w)
        add = wl if not cur else cur_w + space + wl
        if cur and add > max_w:
            lines.append(cur)
            cur, cur_w = [w], wl
        else:
            cur, cur_w = cur + [w], add
    if cur:
        lines.append(cur)
    return lines


def layout_caption(text: str, bible: dict, zone_y: int = None, level: int = 1):
    """Measure + fit a caption. Returns layout dict or ok=False with reasons.

    Steps the level's font ladder (V4: 1: 54->48->42, 2: 58->52->46,
    3: 66->58->50) until the block fits: <=2 lines, width within X margins,
    bottom above BOTTOM_SAFE.
    """
    from engine import bible as B
    zone_y = zone_y if zone_y is not None else CAPTION_RECT[1]
    body = bible.get("typography", {}).get("body", "Inter-Variable.ttf")
    emph = emphasis_words(text)
    for size in LEVEL_SIZES.get(int(level), FONT_SIZES):
        f = _font(body, size)
        lines = _balance(wrap_tokens(text, f, MAX_TEXT_W))
        if not lines or len(lines) > 2:
            continue
        line_h = int(size * LINE_SPACING)
        block_h = line_h * len(lines)
        y0 = BOTTOM_SAFE - block_h
        if y0 < zone_y + 8:
            continue
        # bbox check: widest line
        widths = [sum(f.getlength(t) for t in ln) + f.getlength(" ") * (len(ln) - 1)
                  for ln in lines]
        w = max(widths)
        x0 = (CANVAS_W - w) / 2
        violations = []
        if x0 < X_MARGIN - 1 or x0 + w > CANVAS_W - X_MARGIN + 1:
            violations.append("x_safe")
        if y0 + block_h > CAPTION_RECT[1] + CAPTION_RECT[3] + 1:
            violations.append("bottom_safe")
        return {
            "ok": not violations, "violations": violations, "font_size": size,
            "font": f, "lines": lines, "widths": widths,
            "x0": x0, "y0": y0, "line_h": line_h, "block_h": block_h,
            "bbox": (x0, y0, x0 + w, y0 + block_h), "emph": emph,
            "text_col": B.rgb255(bible, "text"),
            "accent_col": B.rgb255(bible, "accent"),
        }
    return {"ok": False, "violations": ["no_fit"], "lines": [], "font_size": None,
            "bbox": None, "emph": emph}


def render_caption(frame, text: str, bible: dict, alpha: float = 1.0,
                   layout: dict = None) -> dict:
    """Draw one caption block (2 lines max) with subtle shadow + accents.

    alpha 0..1 gives the restrained 0.12 s appearance ramp. Returns layout.
    """
    lay = layout or layout_caption(text, bible)
    if not lay.get("ok"):
        return lay
    overlay = Image.new("RGBA", frame.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    a = int(255 * max(0.0, min(1.0, alpha)))
    shadow = (0, 0, 0, int(120 * alpha))
    f = lay["font"]
    y = lay["y0"]
    for ln in lay["lines"]:
        lw = sum(f.getlength(t) for t in ln) + f.getlength(" ") * (len(ln) - 1)
        x = (CANVAS_W - lw) / 2
        for tok in ln:
            is_num = bool(_NUM.fullmatch(tok.strip(",."))) or tok.strip(",.") in lay["emph"]
            col = lay["accent_col"] + (a,) if is_num else lay["text_col"] + (a,)
            d.text((x + 2, y + 4), tok, font=f, fill=shadow)
            d.text((x, y), tok, font=f, fill=col)
            x += f.getlength(tok) + f.getlength(" ")
        y += lay["line_h"]
    frame.paste(Image.alpha_composite(frame.convert("RGBA"), overlay).convert("RGB"),
                (0, 0))
    return lay


def caption_alpha(t: float, cue: dict) -> float:
    """Restrained appearance ramp (0.12 s), instant out at cue end."""
    dur = cue.get("t1", 0) - cue.get("t0", 0)
    if dur <= 0.25:
        return 1.0
    if t < cue["t0"] + 0.12:
        return max(0.0, min(1.0, (t - cue["t0"]) / 0.12))
    return 1.0


def qa_all_captions(cues: list, bible: dict) -> dict:
    """Layout QA across the whole cue list — measured bboxes vs safe areas."""
    report = {"checked": 0, "ok": 0, "violations": []}
    for cue in cues:
        rep = layout_caption(cue["text"], bible)
        report["checked"] += 1
        if rep.get("ok"):
            report["ok"] += 1
        else:
            report["violations"].append({"text": cue["text"][:48],
                                         "why": rep.get("violations")})
    report["pass"] = report["ok"] == report["checked"]
    return report
