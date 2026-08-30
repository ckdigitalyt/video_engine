"""microevents.py — Shot → MicroEvents vocabulary + renderer mapping.

Directive §4: every shot is decomposed into concrete perceptual events the
renderer MUST implement (object enters/exits, camera movement, subject
movement, environmental change, lighting change, transformation, transition,
impact, reaction). A slow zoom on an unchanged image is the failure mode
this module exists to prevent: the V3 audit measured 0.078 scene-internal
events / 10 s and 63.5 % frozen runtime.

This module is the single source of truth for:
  * the event KIND vocabulary (shared by schema, planner, renderers);
  * the per-shot density floor (§2/§19: >= 1.5 events / 10 s);
  * deterministic event derivation for shots the director left eventless;
  * the per-renderer mapping of event kinds to concrete motion primitives:
      - MOTION_CANVAS  → template animation cues (props["micro_events"])
      - PIXIJS         → scene events (scene["events"])
      - AI_IMAGE_MOTION→ Ken Burns zoom/brightness pulses (render_kenburns)

Pure functions; deterministic; no network, no LLM.
"""

from __future__ import annotations

import hashlib
import math

# ── Vocabulary ───────────────────────────────────────────────────────────────

MICRO_EVENT_KINDS: tuple[str, ...] = (
    "object_enter",        # a meaningful object enters frame
    "object_exit",         # a meaningful object exits frame
    "camera_accel",        # camera accelerates / changes speed or direction
    "lighting_change",     # light changes (sun fades, flash, darkness)
    "transformation",      # an object visibly transforms
    "cut_to",              # an internal hard cut / swap of the depicted scene
    "subject_action",      # subject does something (runs, bites, roars…)
    "environment_change",  # environment changes (dust rises, snow starts…)
    "impact",              # collision / shockwave / sudden jolt
    "reveal",              # spatial reveal / unmasking
)

# §2/§19 gate threshold: meaningful visual events per 10 s of runtime.
EVENT_DENSITY_TARGET = 1.5

_DEFAULT_INTENSITY = 0.6


def required_event_count(duration_sec: float) -> int:
    """Minimum number of micro events a shot of *duration_sec* must carry
    to satisfy the §2 density floor (>= EVENT_DENSITY_TARGET / 10 s)."""
    return max(1, math.ceil(float(duration_sec) * EVENT_DENSITY_TARGET / 10.0))


# ── Deterministic derivation ────────────────────────────────────────────────

def _hash_word(*parts: object) -> int:
    digest = hashlib.sha256("|".join(str(p) for p in parts).encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big")


def _event(t: float, duration: float, text: str, kind: str,
           intensity: float = _DEFAULT_INTENSITY) -> dict:
    return {
        "t": round(max(0.0, t), 2),
        "duration": round(max(0.2, duration), 2),
        "event": str(text)[:160],
        "kind": kind,
        "intensity": round(min(1.0, max(0.0, intensity)), 2),
    }


def _filler_event(shot: dict, t: float, duration: float, i: int) -> dict:
    """Deterministic perceptual beat used to reach the density floor when
    the director's fields don't yield enough concrete events. Varied per
    shot so two shots never receive the same filler sequence."""
    word = _hash_word(shot.get("shot_id"), shot.get("subject"), i)
    fillers = (
        ("parallax push deepens foreground/background separation", "camera_accel"),
        ("atmospheric particles drift through the light", "environment_change"),
        ("subtle light shift rakes across the subject", "lighting_change"),
        ("composition tightens toward the attention target", "camera_accel"),
        ("secondary detail enters at frame edge", "object_enter"),
    )
    text, kind = fillers[word % len(fillers)]
    return _event(t, duration, text, kind, 0.35)


def derive_micro_events(shot: dict) -> list[dict]:
    """Build a concrete micro_events timeline from the shot's cinematography
    fields (§5/§6). Deterministic; never returns fewer events than the §2
    density floor requires (filler perceptual beats top the sequence up).

    Event kinds map from fields as:
        camera_move != static          → camera_accel
        subject_motion                 → subject_action
        environment_motion             → environment_change
        lighting_change                → lighting_change
        visual_event text              → transformation/impact/reveal
        transition_out (cut/dissolve)  → cut_to / object_exit
    """
    duration = float(shot.get("duration_sec") or 3.0)
    camera_move = str(shot.get("camera_move") or "static")
    events: list[dict] = []

    if camera_move != "static":
        events.append(_event(
            0.0, min(2.0, duration * 0.4),
            f"camera {camera_move.replace('_', ' ')} begins",
            "camera_accel", 0.5))

    subject_motion = str(shot.get("subject_motion") or "").strip()
    if subject_motion:
        events.append(_event(
            duration * 0.2, duration * 0.5,
            f"subject: {subject_motion}", "subject_action"))

    env_motion = str(shot.get("environment_motion") or "").strip()
    if env_motion:
        events.append(_event(
            duration * 0.15, duration * 0.6,
            f"environment: {env_motion}", "environment_change"))

    lighting = str(shot.get("lighting_change") or "").strip()
    if lighting:
        events.append(_event(
            duration * 0.5, duration * 0.4,
            f"lighting: {lighting}", "lighting_change"))

    visual_event = str(shot.get("visual_event") or "").strip()
    if visual_event:
        low = visual_event.lower()
        if any(w in low for w in ("impact", "collision", "shockwave", "explosion", "crash")):
            kind = "impact"
        elif any(w in low for w in ("reveal", "appears", "emerges", "unmask")):
            kind = "reveal"
        elif any(w in low for w in ("enter", "arrives", "approaches", "falls")):
            kind = "object_enter"
        elif any(w in low for w in ("exit", "leaves", "disappears", "vanishes")):
            kind = "object_exit"
        else:
            kind = "transformation"
        peak = duration * 0.55 if camera_move != "static" else duration * 0.35
        events.append(_event(peak, min(1.8, duration * 0.35), visual_event, kind, 0.9))

    transition_out = str(shot.get("transition_out") or "").strip().lower()
    if transition_out and transition_out not in ("none", "cut", ""):
        kind = "cut_to" if "cut" in transition_out else "object_exit"
        events.append(_event(
            max(0.0, duration - 1.0), 0.8,
            f"transition out: {transition_out}", kind, 0.5))
    elif transition_out == "cut":
        events.append(_event(
            max(0.0, duration - 0.4), 0.4, "hard cut out", "cut_to", 0.4))

    # ── Top up to the §2 density floor with deterministic variety ──
    need = required_event_count(duration)
    i = 0
    while len(events) < need:
        occupied = sorted(e["t"] for e in events)
        slot = duration * (i + 1) / (need + 1)
        # nudge the filler away from occupied times when possible
        while occupied and any(abs(slot - o) < 0.4 for o in occupied):
            slot += 0.3
            if slot > duration - 0.3:
                slot = max(0.1, slot - duration)
                break
        events.append(_filler_event(shot, min(slot, max(0.0, duration - 0.5)),
                                    min(1.2, duration * 0.25), i))
        i += 1

    events.sort(key=lambda e: e["t"])
    return events


def validate_event_coverage(shot: dict,
                            events: list[dict] | None = None) -> list[str]:
    """Issues list (empty = the shot satisfies the §2/§19 density floor)."""
    duration = float(shot.get("duration_sec") or 0)
    events = shot.get("micro_events") if events is None else events
    issues: list[str] = []
    if not events:
        return [f"{shot.get('shot_id', '?')}: no micro_events"]
    if len(events) < required_event_count(duration):
        issues.append(
            f"{shot.get('shot_id', '?')}: {len(events)} micro_events < "
            f"{required_event_count(duration)} required for "
            f"{duration:.1f}s ({EVENT_DENSITY_TARGET}/10s floor)")
    for e in events:
        if float(e.get("t", 0)) + float(e.get("duration", 0)) > duration + 0.51:
            issues.append(
                f"{shot.get('shot_id', '?')}: event at t={e.get('t')} "
                f"overruns shot duration {duration:.1f}s")
            break
    return issues


# ── Renderer mappings ────────────────────────────────────────────────────────

# MOTION_CANVAS: event kind → template animation cue (consumed by the
# motion/templates engine as props["micro_events"]).
_MOTION_CANVAS_CUES: dict[str, dict] = {
    "object_enter": {"anim": "enter", "from": "offscreen"},
    "object_exit": {"anim": "exit", "to": "offscreen"},
    "camera_accel": {"anim": "zoom_pulse"},
    "lighting_change": {"anim": "bg_shift"},
    "transformation": {"anim": "morph"},
    "cut_to": {"anim": "hard_swap"},
    "subject_action": {"anim": "move"},
    "environment_change": {"anim": "ambient"},
    "impact": {"anim": "shake_flash"},
    "reveal": {"anim": "unmask"},
}


def events_to_motion_canvas(events: list[dict]) -> list[dict]:
    """Map micro events → Motion Canvas template cues (mc-json-v1)."""
    out: list[dict] = []
    for e in events:
        cue = dict(_MOTION_CANVAS_CUES.get(str(e.get("kind")), {"anim": "ambient"}))
        out.append({
            "t": e.get("t", 0.0),
            "duration": e.get("duration", 1.0),
            "text": e.get("event", ""),
            "intensity": e.get("intensity", _DEFAULT_INTENSITY),
            **cue,
        })
    return out


# PIXIJS: event kind → scene-event descriptor (scene["events"], consumed by
# pixi/render.mjs scene framework: fly-in props, camera moves, atmosphere,
# character actions, background swaps).
def events_to_pixijs(events: list[dict]) -> list[dict]:
    out: list[dict] = []
    for e in events:
        kind = str(e.get("kind"))
        intensity = float(e.get("intensity", _DEFAULT_INTENSITY))
        if kind == "object_enter":
            out.append({"t": e["t"], "type": "fly_in_prop",
                        "duration": e["duration"], "intensity": intensity,
                        "note": e["event"]})
        elif kind == "object_exit":
            out.append({"t": e["t"], "type": "fly_out_prop",
                        "duration": e["duration"], "intensity": intensity,
                        "note": e["event"]})
        elif kind == "camera_accel":
            out.append({"t": e["t"], "type": "camera_move",
                        "move": "push_in", "duration": e["duration"],
                        "intensity": intensity, "note": e["event"]})
        elif kind == "lighting_change":
            low = str(e.get("event", "")).lower()
            out.append({"t": e["t"], "type": "atmosphere",
                        "atmosphere": "darkness" if "dark" in low or "fade" in low
                        else "flash",
                        "duration": e["duration"], "intensity": intensity,
                        "note": e["event"]})
        elif kind == "impact":
            out.append({"t": e["t"], "type": "camera_shake",
                        "duration": e["duration"], "intensity": intensity,
                        "note": e["event"]})
        elif kind == "transformation":
            out.append({"t": e["t"], "type": "character_action",
                        "action": "transform", "duration": e["duration"],
                        "intensity": intensity, "note": e["event"]})
        elif kind == "cut_to":
            out.append({"t": e["t"], "type": "background_swap",
                        "duration": e["duration"], "intensity": intensity,
                        "note": e["event"]})
        elif kind == "subject_action":
            low = str(e.get("event", "")).lower()
            action = "run" if "run" in low or "rush" in low else (
                "bob" if any(w in low for w in ("bob", "walk", "move")) else "idle")
            out.append({"t": e["t"], "type": "character_action",
                        "action": action, "duration": e["duration"],
                        "intensity": intensity, "note": e["event"]})
        elif kind == "environment_change":
            out.append({"t": e["t"], "type": "particles_burst",
                        "duration": e["duration"], "intensity": intensity,
                        "note": e["event"]})
        elif kind == "reveal":
            out.append({"t": e["t"], "type": "unmask",
                        "duration": e["duration"], "intensity": intensity,
                        "note": e["event"]})
    return out


# AI_IMAGE_MOTION: event kind → Ken Burns motion pulses. camera_accel
# events add a zoom bump; lighting_change/impact add signed brightness
# pulses; the rest keep the base plan alive via ambient pulses.
_ZOOM_KINDS = {"camera_accel", "reveal", "impact"}


def events_to_kenburns_pulses(events: list[dict], duration: float,
                              fps: int) -> dict:
    """Convert micro events into zoom/brightness pulse descriptors used by
    kenburns.render_kenburns(events=...) (directive §15: a still becomes a
    2-4s animated scene, never a 7s slide).

    Returns {"zoom": [{center_frame, amp, width_frames}],
             "brightness": [{center_frame, amp, width_frames}]}.
    """
    zoom: list[dict] = []
    brightness: list[dict] = []
    for e in events:
        kind = str(e.get("kind"))
        intensity = float(e.get("intensity", _DEFAULT_INTENSITY))
        center = min(max(float(e.get("t", 0.0)) + float(e.get("duration", 1.0)) / 2.0,
                         0.0), max(duration - 0.1, 0.0)) * fps
        width = max(1.0, float(e.get("duration", 1.0)) * fps * 0.8)
        if kind in _ZOOM_KINDS:
            zoom.append({"center": round(center, 1),
                         "amp": round(0.04 + 0.08 * intensity, 4),
                         "width": round(width, 1)})
        elif kind == "lighting_change":
            low = str(e.get("event", "")).lower()
            sign = -1.0 if any(w in low for w in ("dark", "fade", "dim", "blocked")) else 1.0
            brightness.append({"center": round(center, 1),
                               "amp": round(sign * (0.02 + 0.05 * intensity), 4),
                               "width": round(width, 1)})
        elif kind == "impact":
            brightness.append({"center": round(center, 1),
                               "amp": 0.10, "width": round(width, 1)})
            zoom.append({"center": round(center, 1), "amp": 0.12,
                         "width": round(max(2.0, width * 0.6), 1)})
        elif kind in ("environment_change", "subject_action", "transformation",
                      "object_enter", "object_exit", "cut_to"):
            # ambient motion cue: slight zoom breathing keeps pixels alive
            zoom.append({"center": round(center, 1),
                         "amp": round(0.015 + 0.02 * intensity, 4),
                         "width": round(width, 1)})
    return {"zoom": zoom, "brightness": brightness}


def shot_index_of(shot: dict) -> int:
    """Stable per-shot index used for de-templating variation (S07 → 7)."""
    sid = str(shot.get("shot_id", ""))
    digits = "".join(ch for ch in sid if ch.isdigit())
    return int(digits) if digits else _hash_word(sid) % 1000
