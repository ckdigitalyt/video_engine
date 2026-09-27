"""V15 — art direction: the story's visual bible drives every layer.

V14 hardcoded DEFAULT_BIBLE / DEFAULT_STOPS (navy) for every scene of every
story, so a batch would have produced identical-looking videos. V15 loads
stories/<id>/visual_bible.json (engine.bible schema) and, for stories without
one, DERIVES a bible deterministically from a small set of art decks keyed on
the story's subject/type/title words (ties -> sha of story_id). The bible
feeds: image prompt prefix/suffix, renderer palette, typography (fonts staged
into Remotion), caption colours, and the finish layer (grain/vignette).
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path


DECKS = {
    "vintage_ink": {
        "keys": ("physics", "biology", "cell", "chemistry", "science", "body",
                 "medicine", "molecule", "ice", "heat"),
        "illustration_style": "vintage 1950s scientific illustration, ink and "
                              "sepia wash on aged parchment, engraving linework",
        "palette": {"primary": "#2B2622", "secondary": "#7A6A52",
                    "accent": "#9C522C", "background": "#D6C7AC",
                    "text": "#EFE6D4", "muted": "#8A7B63",
                    "highlight": "#E9DFC8"},
        "texture": {"grain": 0.012, "vignette": 0.25},
    },
    "nocturne_gouache": {
        "keys": ("space", "astronomy", "planet", "star", "ocean", "deep",
                 "night", "black hole", "universe", "sea"),
        "illustration_style": "luminous gouache painting, deep midnight blues "
                              "with glowing amber and teal light, soft painterly "
                              "brushwork, cinematic depth",
        "palette": {"primary": "#0E1A2B", "secondary": "#28476B",
                    "accent": "#F2A65A", "background": "#0B1320",
                    "text": "#F4EFE6", "muted": "#7F93AD",
                    "highlight": "#9FE3E0"},
        "texture": {"grain": 0.015, "vignette": 0.35},
    },
    "blueprint": {
        "keys": ("engineering", "machine", "car", "engine", "bridge", "lock",
                 "canal", "phone", "battery", "microwave", "aircraft", "wing"),
        "illustration_style": "technical cutaway illustration, precise ink "
                              "linework over muted blueprint blue and warm "
                              "paper tones, isometric clarity, subtle shading",
        "palette": {"primary": "#1B2A3A", "secondary": "#3D6A8C",
                    "accent": "#E8793A", "background": "#E4E0D6",
                    "text": "#F3F1EA", "muted": "#8FA3B3",
                    "highlight": "#CFE3F0"},
        "texture": {"grain": 0.008, "vignette": 0.2},
    },
    "archival_etching": {
        "keys": ("history", "1816", "1908", "titanic", "war", "ancient",
                 "empire", "century", "volcano", "eruption"),
        "illustration_style": "19th-century archival copperplate etching, "
                              "cross-hatched shading, warm umber ink with a "
                              "single oxblood accent, museum print texture",
        "palette": {"primary": "#241C16", "secondary": "#6B5847",
                    "accent": "#8E2F25", "background": "#CDBFA6",
                    "text": "#F0E8DA", "muted": "#8C7B68",
                    "highlight": "#E6DAC4"},
        "texture": {"grain": 0.014, "vignette": 0.3},
    },
    "watercolor_atlas": {
        "keys": ("geography", "desert", "sahara", "mountain", "forest", "tree",
                 "lake", "river", "fog", "climate", "earth", "autumn", "leaf"),
        "illustration_style": "naturalist watercolor field-atlas illustration, "
                              "layered transparent washes, fine pen detail, "
                              "sunlit earth tones with sage and ochre",
        "palette": {"primary": "#2E2A22", "secondary": "#6F7F5A",
                    "accent": "#C0662B", "background": "#E8DFCB",
                    "text": "#F6F1E6", "muted": "#9A9380",
                    "highlight": "#DCE7C9"},
        "texture": {"grain": 0.01, "vignette": 0.22},
    },
}
_BASE = {
    "version": "v15-derived", "lighting": "soft directional light",
    "contrast": "medium-high", "saturation": 0.9,
    "typography": {"display": "BebasNeue-Regular.ttf",
                   "body": "Inter-Variable.ttf"},
    "transition_style": "hard cut on the word",
}


def derive_bible(story: dict) -> dict:
    words = " ".join(str(story.get(k, "")) for k in
                     ("subject", "story_type", "title", "story_id")).lower()
    scores = {name: sum(1 for k in d["keys"] if k in words)
              for name, d in DECKS.items()}
    best = max(scores.values())
    names = sorted(n for n, v in scores.items() if v == best)
    pick = names[int(hashlib.sha256(story["story_id"].encode()).hexdigest(),
                     16) % len(names)]
    d = DECKS[pick]
    return dict(_BASE, brand=story.get("brand", "JADE"), deck=pick,
                illustration_style=d["illustration_style"],
                palette=dict(d["palette"]), texture=dict(d["texture"]),
                prompt_fragments={"prefix": d["illustration_style"]})


def load_style(story_dir, story: dict | None = None) -> dict:
    """Story bible (validated by engine.bible) or a derived deck bible."""
    story_dir = Path(story_dir)
    if story is None:
        story = json.loads((story_dir / "story.json").read_text())
    if (story_dir / "visual_bible.json").exists():
        from engine.bible import load_bible
        b = load_bible(story_dir)
        b.setdefault("deck", "story_bible")
        b.setdefault("prompt_fragments", {}).setdefault(
            "prefix", b["illustration_style"])
        return b
    return derive_bible(story)


def _lum(hex_: str) -> float:
    h = hex_.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return 0.299 * r + 0.587 * g + 0.114 * b


def renderer_palette(bible: dict) -> dict:
    """Bible roles -> SceneComposition palette keys."""
    p = bible["palette"]
    dark_bg = _lum(p["background"]) < 110
    return {
        "bg_deep": p["primary"] if not dark_bg else p["background"],
        "bg_mid": p["secondary"],
        "accent_warm": p["accent"],
        "accent_cool": p.get("highlight", p["secondary"]),
        "ink": p["text"] if dark_bg else p["primary"],
        "ink_dim": p["muted"],
        "line": p["primary"],
        "shadow": "#000000",
    }


# FLUX-family models have no negative prompt: "no text" can itself summon
# lettering, and textbook words ("diagram grammar", "materials-science",
# "on aged parchment") summon a PAGE with garbled captions and borders
# (verified on NIM FLUX.2, 2026-09-27). Prompts are therefore phrased
# positively and the bible prefix is filtered of page/diagram vocabulary.
_BANNED_CLAUSE = re.compile(
    r"(?i)diagram|grammar|chart|infographic|typograph|label|poster|page|book|"
    r"annotation|caption|\btext\b|letter|watermark|logo")
_BANNED_WORD = re.compile(
    r"(?i)\b(materials-science|scientific|science|biological|textbook|"
    r"technical)\b\s*")
_ON_SURFACE = re.compile(r"(?i)\s+on\s+(\w+\s+){0,2}(parchment|paper)\b")
PURE = "Pure image, full-bleed, edge to edge, vertical 9:16"


def style_prefix(bible: dict) -> str:
    raw = (bible.get("prompt_fragments") or {}).get("prefix") \
        or bible.get("illustration_style", "")
    keep = []
    for clause in re.split(r"[,.;]", raw):
        c = _ON_SURFACE.sub("", clause).strip()
        if not c or _BANNED_CLAUSE.search(c):
            continue
        c = _BANNED_WORD.sub("", c).strip()
        if c:
            keep.append(c)
    return ", ".join(keep)


def image_prompt(bible: dict, subject: str, composition: str = "centered") -> str:
    comp = {"subject_low": "main subject in the lower two thirds, wide quiet "
                           "open background across the upper third",
            "subject_high": "main subject in the upper half, quiet plain "
                            "ground across the lower third",
            "centered": "single clear focal subject, centered"}.get(
                composition, "single clear focal subject")
    subj = _BANNED_WORD.sub("", subject.strip().rstrip("."))
    return ". ".join(x for x in (style_prefix(bible), subj, comp, PURE) if x)
