"""
style_bible.py — Locked visual identity per episode (Jade Operating Spec §2, §9).

One video = one visual universe.  A StyleBible is created once at project
start and every still / AI image / grade in the episode must conform:

  * one canonical palette (hex list)
  * one canonical reference frame prompt (the "look" anchor)
  * one locked style modifier appended to every AI still prompt
  * one character/subject sheet (per-episode, optional)

The bible is persisted to cache/style_bible.json so re-renders and
improvement passes reuse the SAME identity (no drift between iterations).

QA gates exported:
  * ``check_style_drift`` — every placed AI still must carry the locked
    style token in its prompt/query record (rejects scenes that fell back
    to a different art direction or un-styled default prompts).
  * ``check_palette`` — dominant colors of generated stills should fall
    near the canonical palette (loose check; logs deviation, flags only
    gross drift like a full-saturation foreign look).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Optional

DEFAULT_BIBLE_PATH = "cache/style_bible.json"

# One fixed Jade art direction for every stylized shot (studio decision
# 2026-08-03 + v8.1).  The bible's style_modifier is this exact token, so
# every AI still in the episode carries the same look.
# 2026-08-05: channel direction switched to flat-vector documentary
# illustration (Kurzgesagt-style).  2026-08-10: ckdigital reversed it —
# NO flat-vector illustrations; AI stills must be REALISTIC / photoreal.
# 2026-08-16: ckdigital re-reversed it — match the flat-2D cartoon
# explainer reference (JEE rank video); flat-vector Kurzgesagt style.
# 2026-08-16 (v40): ckdigital direction — cartoon methodology locked:
# hand-drawn 2D cartoon with thick dark outlines, cel shading, soft
# gradients, glow, and friendly expressive faces on celestial bodies /
# recurring mascot.  Palette and mascot are FIXED across ALL videos so
# the channel builds one recognizable visual brand (virality factor).
DEFAULT_STYLE_MODIFIER = (
    "hand-drawn 2D cartoon illustration, thick dark outlines, cel shading, "
    "soft gradients, glow, friendly expressive cartoon faces, bold clean "
    "shapes, scientific explainer art, no text, 16:9 composition"
)

# Channel brand palette (v40, locked for every video): deep space navy,
# warm star orange/red, earth blue, UV violet accent, ink outline.
DEFAULT_PALETTE = ["#0A0E26", "#FF8A46", "#4682C8", "#B85CC8", "#1A1A24"]

# v42: HUMAN-READABLE palette names — generators (FLUX/NIM/Pollinations)
# honor color NAMES far more reliably than raw hex codes.  These names map
# 1:1 to DEFAULT_PALETTE so the on-screen grade and the prompt agree; the
# names travel inside STYLE_SUFFIX so EVERY styled prompt on EVERY future
# video carries the same locked brand colors (virality consistency).
DEFAULT_PALETTE_NAMES = (
    "consistent color palette: deep space navy, warm star orange, "
    "earth blue, violet purple accent, dark ink outlines"
)

# Token that must appear in every styled prompt (used by drift QA).
STYLE_TOKEN = "cartoon illustration"

# Recurring brand mascot: injected into the subject sheet + every styled
# prompt so the channel has a recognizable recurring character.  The
# renderer draws it (or a friendly face) into hook/outro keyframes.
DEFAULT_MASCOT = (
    "a cute small green alien observer with big white eyes, floating in a "
    "tiny round spaceship, friendly and curious"
)

# v42: THE single locked brand suffix for every stylized still prompt on
# every video (style modifier + palette names + mascot + friendly faces).
# Previously the palette hex codes were never put into prompts, and each
# runner carried its own drift-prone copy of the mascot text (mission_run
# hardcoded a variant in _AI_STYLE_SUFFIX; mission_stills had NO mascot
# and NO palette).  One source of truth = one recognizable channel brand
# across all future videos.  Keep DEFAULT_STYLE_MODIFIER/STYLE_TOKEN in
# sync with src/director/visual_direction.FIXED_JADE_STYLE.
STYLE_SUFFIX = (
    f"{DEFAULT_STYLE_MODIFIER}, {DEFAULT_PALETTE_NAMES}, "
    f"recurring mascot: {DEFAULT_MASCOT}, "
    "celestial bodies may have friendly cartoon faces"
)

DEFAULT_SUBJECT_SHEET = [
    {"name": "mascot", "description": DEFAULT_MASCOT,
     "usage": "hook scene, outro scene, any scene needing a relatable character"},
    {"name": "friendly_faces",
     "description": "celestial bodies (stars, sun, planets) may have friendly cartoon faces",
     "usage": "stars/sun/planets when narration is awe/hook oriented"},
]


@dataclass
class StyleBible:
    """Locked visual identity for one episode."""

    style_name: str = "jade"
    style_modifier: str = DEFAULT_STYLE_MODIFIER
    palette: list = field(default_factory=lambda: list(DEFAULT_PALETTE))
    reference_frame_prompt: str = ""
    subject_sheet: list = field(default_factory=lambda: list(DEFAULT_SUBJECT_SHEET))
    mascot: str = DEFAULT_MASCOT
    bible_path: str = DEFAULT_BIBLE_PATH
    # record of which style token each placed still was generated with
    placed_style_tokens: dict = field(default_factory=dict)  # shot file -> token

    # ── Persistence ────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "style_name": self.style_name,
            "style_modifier": self.style_modifier,
            "palette": self.palette,
            "reference_frame_prompt": self.reference_frame_prompt,
            "subject_sheet": self.subject_sheet,
            "placed_style_tokens": self.placed_style_tokens,
        }

    def save(self) -> str:
        os.makedirs(os.path.dirname(self.bible_path) or ".", exist_ok=True)
        with open(self.bible_path, "w") as f:
            json.dump(self.to_dict(), f, indent=2)
        return self.bible_path

    @classmethod
    def load(cls, bible_path: str = DEFAULT_BIBLE_PATH) -> Optional["StyleBible"]:
        if not os.path.exists(bible_path):
            return None
        try:
            with open(bible_path) as f:
                d = json.load(f)
            return cls(
                style_name=d.get("style_name", "jade"),
                style_modifier=d.get("style_modifier", DEFAULT_STYLE_MODIFIER),
                palette=d.get("palette", list(DEFAULT_PALETTE)),
                reference_frame_prompt=d.get("reference_frame_prompt", ""),
                subject_sheet=d.get("subject_sheet", list(DEFAULT_SUBJECT_SHEET)),
                mascot=d.get("mascot", DEFAULT_MASCOT),
                bible_path=bible_path,
                placed_style_tokens=d.get("placed_style_tokens", {}),
            )
        except Exception:
            return None

    # ── Prompt helpers ─────────────────────────────────────────────────

    def styled_prompt(self, base: str, photoreal: bool = False) -> str:
        """Append the locked brand suffix (or the photoreal identity).

        v40: subject sheet (mascot + friendly faces) is injected into every
        styled prompt so the recurring character becomes part of the brand.
        v42: the suffix is the single STYLE_SUFFIX constant — style modifier
        + locked palette names + mascot + friendly faces — so the palette
        actually travels into the prompt (it never did before).
        """
        if photoreal:
            return f"{base}. photorealistic, cinematic, high detail, no text"
        sheet = " ".join(s["description"] for s in (self.subject_sheet or []))
        return f"{base}. {STYLE_SUFFIX}. {sheet}"

    def palette_prompt(self) -> str:
        """v42: the locked palette as prompt text (for grading/reference)."""
        return DEFAULT_PALETTE_NAMES

    def reset_episode(self) -> "StyleBible":
        """Clear per-episode placed-token records (identity persists).
        Prevents a previous topic's stills from false-failing drift QA."""
        self.placed_style_tokens = {}
        self.save()
        return self

    # ── QA checks ──────────────────────────────────────────────────────

    def check_style_drift(self, placed: Optional[dict] = None) -> dict:
        """§2 'Do not rotate styles by scene emotion' / §9 'style drift'.

        Every placed AI still's recorded prompt token must contain the
        locked style token.  Any shot placed with a different or missing
        art direction = drift (fails the gate).
        """
        placed = placed if placed is not None else self.placed_style_tokens
        drifted = []
        for fname, token in (placed or {}).items():
            tok = (token or "").lower()
            if STYLE_TOKEN not in tok and "photorealistic" not in tok:
                drifted.append(f"{os.path.basename(fname)}:{token[:40]}")
        return {
            "passed": not drifted,
            "detail": f"{len(placed or {})} placed stills, 0 drifted"
                      if not drifted else f"style drift: {drifted[:6]}",
            "metrics": {"placed": len(placed or {}), "drifted": drifted[:8]},
        }

    def check_palette(self, image_paths: list) -> dict:
        """Loose dominant-color check against the canonical palette.

        Computes average hue of each still; flags only gross drift (an
        image whose dominant color is far from every palette color).
        Not a hard render block — palette is a quality hint, but gross
        drift is logged for the review pass.
        """
        try:
            from PIL import Image
            import numpy as np
        except Exception:
            return {"passed": True, "detail": "palette check unavailable (PIL/numpy)",
                    "metrics": {}}
        pal_rgb = []
        for hx in self.palette:
            hx = hx.lstrip("#")
            if len(hx) == 6:
                pal_rgb.append(tuple(int(hx[i:i + 2], 16) for i in (0, 2, 4)))
        if not pal_rgb:
            return {"passed": True, "detail": "no palette defined", "metrics": {}}

        def _dist(c1, c2):
            return sum((a - b) ** 2 for a, b in zip(c1, c2)) ** 0.5

        min_dists = []
        for p in image_paths:
            if not os.path.exists(p):
                continue
            try:
                with Image.open(p).convert("RGB").resize((64, 64)) as im:
                    arr = np.asarray(im).reshape(-1, 3)
                    mean = tuple(float(x) for x in arr.mean(axis=0))
                min_dists.append(min(_dist(mean, c) for c in pal_rgb))
            except Exception:
                continue
        if not min_dists:
            return {"passed": True, "detail": "no stills to palette-check",
                    "metrics": {"checked": 0}}
        worst = max(min_dists)
        # 441 = distance to an opposite hue in RGB cube (~255*sqrt(3)).
        return {
            "passed": worst < 330.0,
            "detail": (f"dominant-color distance from palette: max {worst:.0f}/441 "
                       f"({len(min_dists)} stills)") if worst < 330.0
                      else f"gross palette drift (max {worst:.0f}/441) — review needed",
            "metrics": {"checked": len(min_dists), "max_dist": round(worst, 1)},
        }


def create_style_bible(style_name: str = "jade",
                       bible_path: str = DEFAULT_BIBLE_PATH,
                       force: bool = False) -> StyleBible:
    """Lock the episode's visual identity once at project start."""
    existing = StyleBible.load(bible_path)
    if existing and not force:
        return existing
    sb = StyleBible(style_name=style_name, bible_path=bible_path)
    sb.save()
    print(f"  [style-bible] '{style_name}' locked → {bible_path}")
    return sb
