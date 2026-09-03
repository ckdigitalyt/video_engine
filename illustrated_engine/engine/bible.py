"""Visual Bible — the single source of visual truth for one video.

Every asset, caption, diagram and frame inherits the Bible. Generated images
never pick their own style: prompts are assembled from Bible fragments, and
post-generation grading (harmonize.py) pulls stragglers back onto the palette.

Bible JSON lives next to the story: stories/<story_id>/visual_bible.json
"""

from __future__ import annotations

import json
from pathlib import Path

BIBLE_REQUIRED = {
    "version": str,
    "brand": str,
    "palette": dict,          # primary/secondary/accent/background/text/muted/highlight
    "illustration_style": str,
    "lighting": str,
    "contrast": str,
    "saturation": (int, float),   # 0..1.5 multiplier target
    "texture": dict,          # grain (0..0.05), vignette (0..0.6)
    "typography": dict,       # display, body  (font file names in assets/fonts)
    "transition_style": str,
    "prompt_fragments": dict, # prefix, suffix  (injected into every generated prompt)
}

PALETTE_REQUIRED = ("primary", "secondary", "accent", "background", "text", "muted")
TEXT_REQUIRED = ("display", "body")


def load_bible(story_dir: Path) -> dict:
    """Load + validate visual_bible.json. Raises ValueError on schema holes."""
    p = Path(story_dir) / "visual_bible.json"
    bible = json.loads(p.read_text())
    for key, typ in BIBLE_REQUIRED.items():
        if key not in bible:
            raise ValueError(f"visual_bible.json missing key: {key}")
        if not isinstance(bible[key], typ):
            raise ValueError(f"visual_bible.json {key} wrong type: {type(bible[key]).__name__}")
    pal = bible["palette"]
    for name in PALETTE_REQUIRED:
        if name not in pal:
            raise ValueError(f"visual_bible.json palette missing: {name}")
    for name in TEXT_REQUIRED:
        if name not in bible["typography"]:
            raise ValueError(f"visual_bible.json typography missing: {name}")
    tex = bible["texture"]
    tex.setdefault("grain", 0.012)
    tex.setdefault("vignette", 0.25)
    bible["saturation"] = float(bible["saturation"])
    return bible


def rgb(bible: dict, name: str):
    """'#RRGGBB' or palette name -> (r, g, b) floats 0..1."""
    v = bible["palette"].get(name, name)
    h = str(v).lstrip("#")
    if len(h) != 6:
        raise ValueError(f"bad colour {name}={v!r}")
    return tuple(int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))


def rgb255(bible: dict, name: str):
    return tuple(round(c * 255) for c in rgb(bible, name))


def prompt_for(bible: dict, subject: str) -> str:
    """Assemble a generator prompt that inherits the Bible (prefix + subject + suffix)."""
    pf = bible.get("prompt_fragments", {})
    parts = [pf.get("prefix", bible["illustration_style"]), subject.strip().rstrip("."),
             pf.get("suffix", "")]
    return ". ".join(p for p in parts if p)


def reference_stats(bible: dict) -> dict:
    """Target statistics continuity_score compares assets against.

    Hue reference is built from the bible palette itself: each palette colour
    contributes weight to its hue bin (weighted by that colour's saturation so
    greys don't smear the histogram).
    """
    import colorsys
    hue = [0.0] * 36
    for name in ("primary", "secondary", "accent", "muted", "background"):
        r, g, b = rgb(bible, name)
        h, s, v = colorsys.rgb_to_hsv(r, g, b)
        if s < 0.10:
            continue
        hue[min(35, int(h * 36))] += s * (0.35 + 0.65 * v)
    total = sum(hue) or 1.0
    hue = [x / total for x in hue]
    return {
        "hue": hue,
        "saturation": min(1.0, max(0.0, float(bible["saturation"]))),
        "contrast": _contrast_target(bible),
    }


def _contrast_target(bible: dict) -> float:
    """0..1 contrast target parsed from the bible's contrast sentence."""
    c = bible.get("contrast", "").lower()
    if "very high" in c:
        return 0.85
    if "high" in c or "medium-high" in c or "medium high" in c:
        return 0.70
    if "low" in c:
        return 0.35
    return 0.55


# ------------------------------------------------------------------ v3 -----

BIBLE_V3_FIELDS = ("illustration_medium", "framing", "graphic_language")


def validate_bible_v3(bible: dict) -> list:
    """Missing V3 fields (brief §2: the Bible controls more than colour —
    medium, framing and graphic language drive style continuity and grammar).
    V2 stories remain valid; V3 stories must carry all three."""
    return [f for f in BIBLE_V3_FIELDS if f not in bible]
