"""style.py — VideoStyleSpec authoring (directive §17).

One style document per production, threaded into EVERY renderer call and
every image/video prompt. LLM path with a deterministic built-in
"cinematic_documentary" fallback; validated against style_spec_v2.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from engine.validation.schema import validate as validate_schema
from engine.v3.story.llm import LLMError, ask_json

logger = logging.getLogger(__name__)

STYLE_SYSTEM = (
    "You are a video art director. You author one coherent visual style "
    "system for a documentary production. Output ONLY valid JSON."
)

DEFAULT_STYLE: dict = {
    "version": "v2",
    "style_name": "cinematic_documentary",
    "palette": {
        "primary": "#1b3a5c",
        "secondary": "#3e6b8f",
        "accent": "#e8a13a",
        "background": "#0d1420",
        "text": "#f2ede4",
        "mood": "vast, naturalistic, quietly dramatic",
    },
    "typography": {
        "title_font": "bold humanist sans",
        "body_font": "clean sans",
        "caption_font": "semi-bold sans",
        "title_weight": "700",
        "scale_note": "titles large, captions small and unobtrusive",
    },
    "camera_language": {
        "default": "slow deliberate push-ins and gentle Ken Burns drift",
        "energy": "calm, weighty; handheld only for chaos moments",
    },
    "lighting": "naturalistic with strong key direction; deep but readable "
                "shadows",
    "texture": "subtle film grain, no gloss",
    "motion_language": {
        "easing": "smooth ease-in-out, no snappy cartoon motion",
        "pacing": "unhurried; hero moments move slowly",
    },
    "transition_language": {
        "default": "hard cuts on narration beats",
        "occasional": "slow cross-dissolves for time passing; light leaks "
                      "for reveals",
    },
    "character_style": "none — subjects are environments, objects, evidence",
    "caption_style": {
        "position": "bottom",
        "font": "semi-bold sans",
        "size_hint": "small",
        "kinetic": False,
    },
}


def load_style(path: str | Path) -> dict:
    """Load + validate an authored style spec."""
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    errs = validate_schema(doc, "style_spec_v2")
    if errs:
        raise ValueError(f"style spec invalid: {errs}")
    return doc


def author_style(topic: str, out_path: str | Path | None = None, *,
                 use_llm: bool = True) -> dict:
    """Author (or load cached) the production VideoStyleSpec."""
    if out_path and Path(out_path).exists():
        return load_style(out_path)

    style = _default_style_variant(topic)
    if use_llm:
        try:
            prompt = f"""Author the VideoStyleSpec for a short documentary
video about: "{topic}".

Return STRICT JSON with exactly these keys:
{{"style_name": "<snake_case>", "palette": {{"primary", "secondary",
"accent", "background", "text", "mood"}}, "typography": {{"title_font",
"body_font", "caption_font", "title_weight", "scale_note"}},
"camera_language": <string or object>, "lighting": <string>, "texture":
<string>, "motion_language": <string or object>, "transition_language":
<string or object>, "character_style": <string>, "caption_style":
{{"position": "bottom|lower_third|center|top", "font", "size_hint",
"kinetic": bool}}}}

Rules: coherent and restrained; colors as hex; the style must flatter BOTH
photoreal AI imagery AND flat motion-graphics — no style so stylised it
clashes with real footage."""
            doc = ask_json(STYLE_SYSTEM, prompt, temperature=0.6,
                           max_tokens=1200)
            doc.setdefault("version", "v2")
            errs = validate_schema(doc, "style_spec_v2")
            if not errs:
                style = doc
        except (LLMError, ValueError) as exc:
            logger.warning("style LLM failed (%s) — using built-in "
                           "cinematic_documentary", exc)

    if out_path:
        p = Path(out_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(style, indent=2), encoding="utf-8")
    return style


def _default_style_variant(topic: str) -> dict:
    """Built-in style with a topic-flavoured mood line (deterministic)."""
    style = json.loads(json.dumps(DEFAULT_STYLE))  # deep copy
    style["palette"]["mood"] = (
        f"vast, naturalistic, quietly dramatic — fitting for: {topic}")
    return style
