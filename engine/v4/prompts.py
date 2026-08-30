"""prompts.py — Cinematic prompt builder (directive §11).

Builds video-model prompts from structured shot fields (VisualSpec-shaped),
NOT free-form text. Deterministic — no LLM required — with an optional
polish pass (pass ``polish_fn``; never required).

Two variants:
* ``ltx``     — LTX prompt-guide structure: explicit subject, action,
  environment, camera, movement, lighting, sequence clauses in that order
  (directive §10: "for LTX, prompts must explicitly specify subject, action,
  environment, camera, movement, lighting, sequence").
* ``generic`` — one flowing cinematic sentence (Wan etc.), same clauses but
  composed as natural prose.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable

# ── Cinematography vocabularies (§6 fields) ──────────────────────────────

_SHOT_SCALE_CLAUSE = {
    "wide": "Wide establishing shot",
    "medium": "Medium shot",
    "close": "Close-up shot",
    "macro": "Extreme macro close-up shot",
}

_CAMERA_MOVE_CLAUSE = {
    "static": "The camera holds perfectly still",
    "push_in": "The camera pushes in steadily toward the subject",
    "pull_out": "The camera pulls back steadily to reveal the wider scene",
    "pan": "The camera pans smoothly across the scene",
    "tilt": "The camera tilts vertically across the scene",
    "orbit": "The camera orbits around the subject",
    "tracking": "The camera tracks alongside the moving subject",
    "whip": "The camera whips rapidly to a new subject",
    "dolly": "The camera dollies through the scene",
    "handheld": "Handheld camera with subtle organic shake",
}

# Short verb phrases for the LTX variant (compact clause style).
_CAMERA_MOVE_COMPACT = {
    "static": "static camera, locked-off shot",
    "push_in": "slow push-in camera move",
    "pull_out": "slow pull-back camera move",
    "pan": "smooth lateral pan",
    "tilt": "smooth vertical tilt",
    "orbit": "orbiting camera move around the subject",
    "tracking": "tracking shot following the subject",
    "whip": "fast whip-pan camera move",
    "dolly": "dolly camera move through the scene",
    "handheld": "handheld camera, subtle shake",
}

_DEFAULT_STYLE_CLAUSE = (
    "cinematic, photorealistic, high detail, natural motion, shallow depth of field"
)

_DEFAULT_NEGATIVE = (
    "blurry, low quality, deformed, distorted, disfigured, bad anatomy, "
    "watermark, text, static, motionless, jpeg artifacts"
)


@dataclass
class ShotSpec:
    """Structured shot fields the AI director hands to the prompt builder."""

    subject: str                       # what is in frame (REQUIRED)
    action: str = ""                   # what happens (REQUIRED for motion)
    environment: str = ""              # where it happens
    camera_move: str = "static"        # §6 vocabulary (see _CAMERA_MOVE_CLAUSE)
    shot_scale: str = "medium"         # wide|medium|close|macro
    lighting_change: str = ""          # lighting/mood, incl. changes over time
    motion: str = ""                   # physical motion detail (subject/env)
    style: str = _DEFAULT_STYLE_CLAUSE
    negative: str = _DEFAULT_NEGATIVE
    duration_sec: float = 4.0
    seed: int = 0
    sequence: str = ""                 # explicit temporal sequence (LTX)
    extras: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.subject:
            raise ValueError("ShotSpec.subject is required")
        if self.camera_move not in _CAMERA_MOVE_CLAUSE:
            raise ValueError(
                f"unknown camera_move {self.camera_move!r}; expected one of "
                f"{sorted(_CAMERA_MOVE_CLAUSE)}")
        if self.shot_scale not in _SHOT_SCALE_CLAUSE:
            raise ValueError(
                f"unknown shot_scale {self.shot_scale!r}; expected one of "
                f"{sorted(_SHOT_SCALE_CLAUSE)}")


def _clean(text: str) -> str:
    """Collapse whitespace; strip trailing period (clauses re-punctuated)."""
    out = re.sub(r"\s+", " ", (text or "").strip())
    return out.rstrip(".")


def _sequence_hint(spec: ShotSpec) -> str:
    if spec.sequence:
        return _clean(spec.sequence)
    # Deterministic fallback: motion implies temporal progression.
    return f"The action unfolds continuously across {spec.duration_sec:g} seconds"


# ── LTX variant (§10: explicit clause structure) ─────────────────────────


def build_ltx_prompt(spec: ShotSpec) -> str:
    """LTX-optimized prompt: subject, action, environment, camera, movement,
    lighting, sequence — each an explicit clause, in that order."""
    parts: list[str] = []
    if spec.action:
        parts.append(f"{_clean(spec.subject)} {_clean(spec.action)}")
    else:
        parts.append(_clean(spec.subject))
    if spec.environment:
        parts.append(f"Set in {_clean(spec.environment)}")
    scale = _SHOT_SCALE_CLAUSE[spec.shot_scale]
    move = _CAMERA_MOVE_COMPACT[spec.camera_move]
    parts.append(f"{scale}, {move}")
    if spec.motion:
        parts.append(_clean(spec.motion))
    if spec.lighting_change:
        parts.append(_clean(spec.lighting_change))
    parts.append(_sequence_hint(spec))
    parts.append(spec.style.strip() or _DEFAULT_STYLE_CLAUSE)
    return ", ".join(p for p in parts if p) + "."


# ── Generic variant (flowing cinematic sentence, §11 example style) ──────


def build_generic_prompt(spec: ShotSpec) -> str:
    """One flowing cinematic sentence: shot scale + camera verb up front,
    then subject/action/environment/motion/lighting/sequence."""
    scale = _SHOT_SCALE_CLAUSE[spec.shot_scale].lower()
    move = _CAMERA_MOVE_CLAUSE[spec.camera_move]
    head = f"{scale}. {move}"
    body = _clean(spec.subject)
    if spec.action:
        body += f" {_clean(spec.action)}"
    if spec.environment:
        body += f" in {_clean(spec.environment)}"
    sentence = f"{head}. {body}."
    if spec.motion:
        sentence += f" {_clean(spec.motion)}."
    if spec.lighting_change:
        sentence += f" {_clean(spec.lighting_change)}."
    sentence += f" {_sequence_hint(spec)}."
    sentence += f" {spec.style.strip() or _DEFAULT_STYLE_CLAUSE}."
    sentence = re.sub(r"\s+", " ", sentence)
    return sentence[0].upper() + sentence[1:] if sentence else sentence


VARIANTS = {
    "ltx": build_ltx_prompt,
    "generic": build_generic_prompt,
}


def build_cinematic_prompt(spec: ShotSpec, *, variant: str = "ltx",
                           polish_fn: Callable[[str], str] | None = None,
                           ) -> str:
    """Deterministic cinematic prompt from structured fields.

    ``polish_fn`` (optional, off by default): an LLM callback receiving the
    built prompt and returning a polished version. The builder itself never
    calls an LLM (deterministic guarantee for tests/pipeline reproducibility).
    """
    if variant not in VARIANTS:
        raise ValueError(f"unknown variant {variant!r}; expected {sorted(VARIANTS)}")
    prompt = VARIANTS[variant](spec)
    if polish_fn is not None:
        polished = polish_fn(prompt)
        if polished and polished.strip():
            prompt = polished.strip()
    return prompt


def build_negative_prompt(spec: ShotSpec) -> str:
    """LTX/Wan negative prompt (separate field on those endpoints)."""
    return (spec.negative or _DEFAULT_NEGATIVE).strip()


def build_shot_bundle(spec: ShotSpec, *, variant: str = "ltx") -> dict:
    """Convenience for render runners: prompt + negative + metadata."""
    return {
        "prompt": build_cinematic_prompt(spec, variant=variant),
        "negative_prompt": build_negative_prompt(spec),
        "variant": variant,
        "duration_sec": spec.duration_sec,
        "seed": spec.seed,
        "camera_move": spec.camera_move,
        "shot_scale": spec.shot_scale,
    }
