"""V6 enhancement flags — benchmark-gated cinematography options.

Production default (baked 2026-09-06 after the cinematography benchmark):
eased camera profile and card parallax are ON by default; bloom stays opt-in
per story. Baseline remains independently selectable for rollback / AB via
CAMERA_PROFILE=baseline ENABLE_PARALLAX=0 — token() then returns "" and CAS
reuses the pre-flag baseline artifacts byte-identically.

Env vars:
  CAMERA_PROFILE   baseline | eased
                   eased = all non-HOLD camera trajectories re-evaluated with
                   a C2 quintic smoothstep (zero velocity AND zero
                   acceleration at both endpoints) instead of the authored
                   per-shot curve.
  ENABLE_PARALLAX  1/true/yes/on
                   Card shots with a moving camera get a damped-rate ambient
                   background layer (2.5D parallax). Text/cards never distort:
                   the card plate keeps the authored camera; only the blurred
                   ambient field moves at 85% rate. HOLD shots are skipped.
  ENABLE_BLOOM     1/true/yes/on
                   Multi-pass bloom on kinetic (luminous) frames only:
                   bright-pass -> 2-pass blur -> masked screen composite.
                   Never applied to text/cards.
"""

from __future__ import annotations

import os

_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}
_PROFILES = {"baseline", "eased"}


def camera_profile() -> str:
    v = os.environ.get("CAMERA_PROFILE", "").strip().lower()
    return v if v in _PROFILES else "eased"  # baked production default


def parallax_enabled() -> bool:
    v = os.environ.get("ENABLE_PARALLAX", "").strip().lower()
    return v not in _FALSE  # baked production default: on unless explicitly disabled


def bloom_enabled() -> bool:
    return os.environ.get("ENABLE_BLOOM", "").strip().lower() in _TRUE


def parallax_damp() -> float:
    """Ambient-layer motion rate as a fraction of the card camera rate."""
    v = os.environ.get("PARALLAX_DAMP", "").strip()
    if v:
        try:
            return min(max(float(v), 0.5), 0.95)
        except ValueError:
            return 0.85
    # V10_DEPTH: multi-plane parallax — the background plane drifts at 0.3x
    # of the foreground card (Jade_todo V10 §3).
    return 0.30 if depth10() else 0.85


def token() -> str:
    """Short token describing the active flag set. Empty string == baseline.

    Appended to the CAS shot hash so artifacts never mix across variants
    (baseline hash is byte-identical to the pre-flag pipeline)."""
    parts = []
    if camera_profile() == "eased":
        parts.append("cameased")
    if parallax_enabled():
        d = f"{parallax_damp():.2f}".replace(".", "")
        parts.append(f"par{d}")
    if bloom_enabled():
        parts.append("bloom")
    if motion9():
        parts.append("v9mo")
    if texture9():
        parts.append("v9tx")
    if compound9():
        parts.append("v9cp")
    if vertical10():
        parts.append("v10v")
    if kinetic10():
        parts.append("v10k")
    if depth10():
        parts.append("v10d")
    if punct10():
        parts.append("v10p")
    if caption11():
        parts.append("v11c")
    if fullbleed11():
        parts.append("v11f")
    return "-".join(parts)


# --- V9 engine upgrades (2026-09-08) ---------------------------------------
# All default ON; set the env var to 0/false/no/off for instant rollback
# without a code revert. Each flag maps to one upgrade area:
#   V9_MOTION    - non-linear easing in living.py events + camera drift on
#                  HOLD shots in composev5._camera_filter
#   V9_TEXTURE   - post-composite radial vignette + fine film grain at the
#                  final mux in composev5.render_video_v5
#   V9_COMPOUND  - consequence/fill_state/flow visual magnitude scales with
#                  the beat's planv8 intensity tier (living.py)
#   V9_AUDIO     - 4-stem procedural mix in engine/audio_mix.py (voice at
#                  -14 LUFS, intensity-pegged underscore ducked -16 dB
#                  250/500 ms, event-synced SFX, grammar ambience)


def motion9() -> bool:
    return os.environ.get("V9_MOTION", "").strip().lower() not in _FALSE


def texture9() -> bool:
    return os.environ.get("V9_TEXTURE", "").strip().lower() not in _FALSE


def compound9() -> bool:
    return os.environ.get("V9_COMPOUND", "").strip().lower() not in _FALSE


def audio9() -> bool:
    return os.environ.get("V9_AUDIO", "").strip().lower() not in _FALSE


def describe() -> dict:
    return {
        "camera_profile": camera_profile(),
        "parallax": parallax_enabled(),
        "parallax_damp": parallax_damp(),
        "bloom": bloom_enabled(),
        "v9_motion": motion9(),
        "v9_texture": texture9(),
        "v9_compound": compound9(),
        "v9_audio": audio9(),
        "v10_vertical": vertical10(),
        "v10_kinetic": kinetic10(),
        "v10_depth": depth10(),
        "v10_punct": punct10(),
        "v11_caption": caption11(),
        "v11_fullbleed": fullbleed11(),
        "v11_gates": gates11(),
    }


# --- V10 engine upgrades (2026-09-09) ---------------------------------------
# Native 9:16 short-form pass (Jade_todo V10). All default ON; set the env
# var to 0/false/no/off for instant rollback without a code revert. Each
# flag maps to one upgrade area:
#   V10_VERTICAL - native 9:16 layout: portrait panel + card fills the
#                  Shorts focal band (Y 0.15-0.75), camera windows re-scaled
#                  so wide assets cover height and track-pan across width
#                  (60-75%), diagonal stage stacking for horizontal chains
#   V10_KINETIC  - word-level kinetic subtitles (engine/captions.py):
#                  2-4 word chunks, active-word highlight, Y 0.70-0.76
#   V10_DEPTH    - multi-plane parallax (ambient 0.3x) + emissive halo on
#                  flow particles + bloom on kinetic (luminous) shots
#   V10_PUNCT    - cinematic audio: 1.5s sub-bass risers into
#                  ESCALATION/REVEAL shots, 40-80Hz sub-drop on PAYOFF,
#                  1-3kHz notch of the music bed under voiceover


def vertical10() -> bool:
    return os.environ.get("V10_VERTICAL", "").strip().lower() not in _FALSE


def kinetic10() -> bool:
    return os.environ.get("V10_KINETIC", "").strip().lower() not in _FALSE


def depth10() -> bool:
    return os.environ.get("V10_DEPTH", "").strip().lower() not in _FALSE


def punct10() -> bool:
    return os.environ.get("V10_PUNCT", "").strip().lower() not in _FALSE


# --- V11 engine upgrades (2026-09-10, Jade_todo_v11 P0) ---------------------
# All default ON; set the env var to 0/false/no/off for instant rollback.
#   V11_CAPTION   caption state machine: one ACTIVE caption semantic state,
#                 kinetic band re-anchored BELOW the card (frame y = card
#                 bottom + 24) so plate-baked footer text can never collide
#                 with the caption band (V10 ghost-caption root cause).
#                 Rollback restores the V10 in-card band (1344..1459).
#   V11_FULLBLEED true 9:16 composition: the plate card owns y 192..1440
#                 (1080x1248, 65% of canvas) and the remaining bands are a
#                 crafted mirror continuation of the plate art — NOT a blur
#                 panel. Blurred extension becomes the rollback path.
#                 Requires V10_VERTICAL (legacy geometry wins if that is off).
#   V11_GATES     engine-level QA gates (caption_qa, leak_scan, occupancy,
#                 motion ratio, publish_gate) integrated into qa8full.
#                 Rollback restores the pre-V11 qa8full behavior exactly.

def caption11() -> bool:
    return vertical10() and os.environ.get("V11_CAPTION", "").strip().lower() not in _FALSE


def fullbleed11() -> bool:
    return vertical10() and os.environ.get("V11_FULLBLEED", "").strip().lower() not in _FALSE


def gates11() -> bool:
    return os.environ.get("V11_GATES", "").strip().lower() not in _FALSE
