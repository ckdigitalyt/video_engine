"""ASS (.ass) builder: Caption / NumberPop / EndCard styles + WordReveal mode.

Cue lists come from edit_plan shots (normalize_cues merges typography and
captions):
  {"kind": "caption",    "text": ..., "t0": ..., "t1": ...}
  {"kind": "caption",    "text": ..., "t0": ..., "t1": ..., "mode": "word_reveal"}
  {"kind": "number_pop", "text": ..., "t0": ..., "t1": ..., "pos": [x, y],
                          "color": "rust"|"ink"}     # pos = frame coords
  {"kind": "end_card",   "text": ..., "t0": ..., "t1": ...}

Captions are measured with Pillow (same TTF libass receives via the
subtitles filter's fontsdir) and wrapped to <= 2 lines inside the safe area;
WrapStyle 2 keeps our breaks. Number pos is clamped to the panel
(y 460..1240 with half-height margin); captions stay in y 1240..1580 via
Alignment 2 + MarginV. WordReveal: words appear sequentially, 120 ms stagger,
via per-word \\t alpha ramps.
"""

from __future__ import annotations

import json
from pathlib import Path

from PIL import ImageFont

ASS_HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
"""

DEJAVU_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

_SAFE_NUM = {"x": (100, 980), "y": (560, 1140)}  # keeps numbers inside the panel
_STYLE_CACHE = {}


def load_style(paths):
    """Parse templates/ass_style.json once; resolve font families/paths."""
    p = Path(paths.templates) / "ass_style.json"
    key = str(p)
    st = _STYLE_CACHE.get(key)
    if st:
        return st
    st = json.loads(p.read_text())
    root = Path(paths.root)
    st["_style_path"] = key

    def _font(name):
        f = st["fonts"][name]
        fp = root / f["path"]
        if fp.exists():
            return fp, f["family"], False
        return Path(DEJAVU_BOLD), f.get("fallback_family", "DejaVu Sans"), \
            bool(f.get("fallback_bold", True))

    for name, prefix in (("caption", "caption"), ("number", "number"), ("endcard", "endcard")):
        fp, fam, bold = _font(name)
        st[f"_{prefix}_font_path"] = str(fp)
        st[f"_{prefix}_family"] = fam
        st[f"_{prefix}_bold"] = bold
    if not Path(st["_endcard_font_path"]).exists():
        st["_endcard_font_path"] = DEJAVU_BOLD
    if not Path(st["_caption_font_path"]).exists():
        st["_caption_font_path"] = DEJAVU_BOLD
    if not Path(st["_number_font_path"]).exists():
        st["_number_font_path"] = DEJAVU_BOLD
    _STYLE_CACHE[key] = st
    return st


def hex_to_ass(hex_color, alpha=0):
    """#RRGGBB -> ASS &HAABBGGRR."""
    h = str(hex_color).lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"&H{alpha:02X}{b:02X}{g:02X}{r:02X}"


def _inline_color(hex_color):
    """#RRGGBB -> &HBBGGRR& for \\\\1c overrides."""
    h = str(hex_color).lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"&H{b:02X}{g:02X}{r:02X}&"


def normalize_cues(shot):
    """Merge a shot's captions + typography into one sorted cue list."""
    cues = []
    for c in shot.get("captions") or []:
        cues.append({"kind": "caption", "text": c["text"],
                     "t0": float(c["t0"]), "t1": float(c["t1"])})
    for t in shot.get("typography") or []:
        kind = str(t.get("kind", "")).lower()
        if kind == "number_pop":
            cues.append({"kind": "number_pop", "text": t["text"],
                         "t0": float(t.get("at", 0.0)),
                         "t1": float(t.get("at", 0.0)) + float(t.get("dur", 1.8)),
                         "pos": t.get("pos"), "color": t.get("color")})
        elif kind == "end_card":
            cues.append({"kind": "end_card", "text": t["text"],
                         "t0": float(t.get("at", 0.0)),
                         "t1": float(t.get("at", 0.0)) + float(t.get("dur", 4.0))})
        elif kind in ("caption", "text_reveal"):
            mode = t.get("mode", "word" if kind == "text_reveal" else "normal")
            mode = "word_reveal" if mode in ("word", "word_reveal") else "normal"
            t0 = float(t.get("t0", t.get("at", 0.0)))
            t1 = float(t.get("t1", t0 + float(t.get("dur", 3.0))))
            cues.append({"kind": "caption", "text": t["text"], "t0": t0, "t1": t1,
                         "mode": mode})
    cues.sort(key=lambda c: (c["t0"], c["t1"]))
    return cues


def _wrap_lines(text, font_path, size, max_w, max_lines=2):
    """Greedy wrap to max_w; if that needs more than max_lines, re-balance
    the words evenly across max_lines (Pillow-measured, libass-compatible)."""
    font = ImageFont.truetype(str(font_path), size)
    words = str(text).split()
    lines, cur = [], ""
    for w in words:
        trial = f"{cur} {w}".strip()
        if not cur or font.getlength(trial) <= max_w:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    if len(lines) <= max_lines:
        return lines
    target = font.getlength(" ".join(words)) / max_lines
    out, cur = [], ""
    for w in words:
        trial = f"{cur} {w}".strip()
        if cur and font.getlength(trial) > target and len(out) < max_lines - 1:
            out.append(cur)
            cur = w
        else:
            cur = trial
    if cur:
        out.append(cur)
    return out[:max_lines]


def _word_reveal_text(text, font_path, size, max_w):
    """Per-word \\t alpha ramp, 120 ms stagger, honoring 2-line wrap."""
    lines = _wrap_lines(text, font_path, size, max_w)
    out, i = [], 0
    for ln in lines:
        parts = []
        for w in ln.split():
            t0 = i * 120
            i += 1
            parts.append("{\\alpha&HFF&\\t(%d,%d,\\alpha&H00&)}%s" % (t0, t0 + 120, _esc(w)))
        out.append(" ".join(parts))
    return "\\N".join(out)


def _esc(text):
    return str(text).replace("{", "(").replace("}", ")").replace("\n", " ").strip()


def _clamp_pos(pos):
    x = float((pos or [540, 850])[0])
    y = float((pos or [540, 850])[1])
    x = int(min(max(x, _SAFE_NUM["x"][0]), _SAFE_NUM["x"][1]))
    y = int(min(max(y, _SAFE_NUM["y"][0]), _SAFE_NUM["y"][1]))
    return x, y


def _ts(t):
    t = max(0.0, float(t))
    cs = int(round(t * 100))
    h, rem = divmod(cs, 360000)
    m, rem = divmod(rem, 6000)
    s, c = divmod(rem, 100)
    return f"{h}:{m:02d}:{s:02d}.{c:02d}"


def build_ass(cues, out_path, style):
    """Write the .ass for a cue list (shot-local times). -> out_path"""
    pal = style["palette"]
    sizes = style["sizes"]
    safe = style["safe"]
    bold = lambda b: "-1" if b else "0"
    off = hex_to_ass(pal["offwhite"])
    blk = "&H00000000"
    nc = pal.get("number_default_color", pal["rust"])
    if not str(nc).startswith("#"):
        nc = pal.get(str(nc), pal["rust"])
    num_c = hex_to_ass(nc)
    styles = (
        f"Style: Caption,{style['_caption_family']},{sizes['caption']},{off},&H000000FF,"
        f"{blk},{blk},{bold(style['_caption_bold'])},0,0,0,100,100,0,0,1,"
        f"{style['outline']['caption']},0,2,{safe['x0']},{1080 - safe['x1']},{safe['margin_v']},1\n"
        f"Style: NumberPop,{style['_number_family']},{sizes['number']},{num_c},{blk},"
        f"{blk},{blk},{bold(style['_number_bold'])},0,0,0,100,100,0,0,1,3,0,5,0,0,0,1\n"
        f"Style: EndCard,{style['_endcard_family']},{sizes['endcard']},{off},{blk},"
        f"{blk},{blk},{bold(style['_endcard_bold'])},0,0,0,100,100,0,0,1,3,0,5,0,0,0,1\n"
    )
    lines = [ASS_HEADER, styles,
             "\n[Events]\n"
             "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"]
    wrap_w = safe.get("caption_wrap_w", 972)
    for c in cues:
        kind = c["kind"]
        if kind == "caption":
            if c.get("mode") == "word_reveal":
                txt = _word_reveal_text(c["text"], style["_caption_font_path"],
                                        sizes["caption"], wrap_w)
                fx = ""
            else:
                lns = _wrap_lines(c["text"], style["_caption_font_path"],
                                  sizes["caption"], wrap_w)
                txt = "\\N".join(_esc(l) for l in lns)
                fx = "{\\fad(80,80)}"
            lines.append(f"Dialogue: 0,{_ts(c['t0'])},{_ts(c['t1'])},Caption,,0,0,0,,"
                         f"{fx}{txt}\n")
        elif kind == "number_pop":
            x, y = _clamp_pos(c.get("pos"))
            col = c.get("color")
            coltag = ""
            if col and col in pal:
                coltag = "{\\1c" + _inline_color(pal[col]) + "}"
            tag = (f"{{\\an5\\pos({x},{y})\\fscx80\\fscy80"
                   f"\\t(0,160,\\fscx100\\fscy100)\\fad(140,160)}}")
            lines.append(f"Dialogue: 0,{_ts(c['t0'])},{_ts(c['t1'])},NumberPop,,0,0,0,,"
                         f"{coltag}{tag}{_esc(c['text'])}\n")
        elif kind == "end_card":
            tag = "{\\an5\\pos(540,960)\\fad(300,300)}"
            lines.append(f"Dialogue: 0,{_ts(c['t0'])},{_ts(c['t1'])},EndCard,,0,0,0,,"
                         f"{tag}{_esc(c['text'])}\n")
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("".join(lines))
    return out_path
