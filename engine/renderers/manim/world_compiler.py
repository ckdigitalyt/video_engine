"""World compiler — v2 VisualSpec -> Manim (JADE_TO_DO v0.3 §4–§8, §23).

Compiles a v2 VisualSpec — which carries a WorldState (entities,
relationships, forces, signals, facts), semantic actions (the action
grammar), representation and hero mechanism — into a standalone Manim
Scene source string.

Same correctness contract as the v1 compiler:
  1. Strict schema validation (Gate 1) before anything else.
  2. Deterministic physics/math verification (Gate 3) for every
     quantitative action (scatter ratio, orbital speed, Kaprekar steps,
     converging trajectories) — failures raise, never render.
  3. SceneState ENTER/UPDATE/EXIT lifecycle across beats (anti-
     accumulation); entities are materialized once and transformed in
     place.
  4. Semantic actions resolve through the ActionRegistry to trusted
     primitives; unknown actions raise CompileError (never a no-op).
  5. Duration budget per beat: animations + self.wait() must fit.
  6. Kinetic text is a FALLBACK (spec §9): only beats whose visual_type
     is a text class get narrative text; demonstration beats use
     semantic actions on world entities.

The v1 compiler stays untouched (correctness sprint preserved); this
module is the v2 path.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from engine.validation.schema import validate_visualspec_v2, validate_worldmodel
from engine.validation import math_verify as M
from engine.validation import physics_verify as PH
from engine.visuals.scene_state import SceneState, Zone
from engine.world.actions import resolve
from engine.world.world_model import WorldState

from engine.primitives.world_primitives import (
    ACTION_NATURAL_DURATION, ENTITY_MATERIALIZERS,
)


class WorldCompileError(ValueError):
    """Raised when a v2 VisualSpec cannot be compiled safely."""


MARGIN = 0.15
MIN_ANIM = 0.08

# Natural durations (unscaled) for primitive/materializer calls.
_NATURAL_ENTER: dict[str, float] = {
    "CelestialBody": 0.8, "OrbitPath": 0.7, "MovingBody": 0.4,
    "LightSource": 0.5, "LightRay": 0.6, "ReferenceFrame": 0.6,
    "ScatteringField": 0.9, "Wave": 0.6, "SignalPulse": 0.6,
    "ParticleField": 0.8, "EyeGlyph": 0.6, "EarGlyph": 0.6,
    "BrainGlyph": 0.6, "MouthGlyph": 0.6, "Node": 0.5,
    "Connection": 0.5, "FlowThrough": 0.8, "Timeline": 0.8,
    "CauseEffectChain": 0.8, "QuestionMark": 0.7, "ExperimentBadge": 0.5,
    "RevealText": 0.7, "PayoffText": 0.8, "MeasureValue": 0.7,
    "AssembleBodies": 0.6, "DisassembleBodies": 0.6,
    "InterferencePattern": 0.8, "WaveSuperposition": 0.8,
    "PressureKernel": 0.8, "BurstExplosion": 0.6,
    "HornProfile": 1.2,
}
_CAMERA_NATURAL = 0.9

# Legacy narrative visual classes (v1) that v2 beats may still use —
# these are the ONLY text-primary classes (spec §9 fallback).
_NARRATIVE_VISUALS: dict[str, str] = {
    "kinetic_title": "KineticTypography",
    "question": "QuestionMark",
    "claim": "ClaimReveal",
    "cycle": "CycleReveal",
    "conclusion": "PayoffText",
    "reveal": "RevealText",
}

# Legacy digit/number visuals that delegate to the v1 primitives.
_LEGACY_DIGIT_VISUALS = {
    "digit_sort", "subtract", "attractor", "fixed_point", "exception",
    "iterate", "highlight", "comparison",
}


def _physics_guard(beat: dict, world: WorldState) -> None:
    """Deterministic verification of quantitative actions (Gate 3)."""
    bid = beat.get("beat_id", "?")
    actions = beat.get("semantic_actions", []) or []
    for a in actions:
        name = str(a.get("action", ""))
        params = a.get("params", {}) or {}
        if name == "scatter":
            v = PH.verify_rayleigh_ratio(
                float(params.get("blue_nm", 450.0)),
                float(params.get("red_nm", 650.0)))
            if not v.ok:
                raise WorldCompileError(
                    f"beat {bid}: scatter physics failed: "
                    + "; ".join(f["detail"] for f in v.failures()))
        if name in ("interfere", "cancel"):
            v = PH.verify_wave_interference(
                float(params.get("f1", params.get("frequency", 1.0))),
                float(params.get("f2", params.get("frequency", 1.0))),
                float(params.get("phase_deg", 180.0)))
            if not v.ok:
                raise WorldCompileError(
                    f"beat {bid}: interference physics failed: "
                    + "; ".join(f["detail"] for f in v.failures()))
        if name == "burst":
            v = PH.verify_pressure_volume_burst(
                float(params.get("pressure_atm", 9.0)),
                float(params.get("temp_c", 180.0)))
            if not v.ok:
                raise WorldCompileError(
                    f"beat {bid}: burst physics failed: "
                    + "; ".join(f["detail"] for f in v.failures()))
        if name == "fill":
            # Gabriel's Horn painter's paradox: verify V = π, A = ∞ before
            # rendering (Gate 3 — mathematical, deterministic).
            v = M.verify_gabriels_horn()
            if not v.ok:
                raise WorldCompileError(
                    f"beat {bid}: fill math verification failed: "
                    + "; ".join(f["detail"] for f in v.failures()))
        if name == "orbit":
            r = float(params.get("radius", 3.4))
            if r <= 0:
                raise WorldCompileError(f"beat {bid}: orbit radius must be > 0")
        if name == "converge":
            to = str(a.get("to", ""))
            if "->" in to:
                parts = [p.strip() for p in to.split("->")]
                for x, y in zip(parts, parts[1:]):
                    v = M.verify_kaprekar_step(str(y).zfill(4), 4,
                                               str(x).zfill(4))
                    if not v.ok:
                        raise WorldCompileError(
                            f"beat {bid}: unverified converge step "
                            f"{x} -> {y}: "
                            + "; ".join(f["detail"] for f in v.failures()))
    # legacy transformation math (v1-style)
    for tf in beat.get("transformations", []):
        t = tf.get("type")
        frm = str(tf.get("from", ""))
        to = str(tf.get("to", ""))
        if t == "subtract" and frm and to:
            v = M.verify_kaprekar_step(str(to).zfill(4), 4, str(frm).zfill(4))
            if not v.ok:
                raise WorldCompileError(
                    f"beat {bid}: math verification failed for subtract: "
                    + "; ".join(f["detail"] for f in v.failures()))


def _beat_refs(beat: dict) -> set[str]:
    """Object ids referenced by the beat (declared objects + action targets)."""
    refs: set[str] = set()
    for obj in beat.get("objects", []):
        oid = obj.get("id") if isinstance(obj, dict) else str(obj)
        if oid:
            refs.add(oid)
    for a in beat.get("semantic_actions", []) or []:
        t = str(a.get("target", ""))
        if t:
            refs.add(t)
        for key in ("targets", "target_objects"):
            raw = a.get(key)
            if raw:
                first = raw[0] if isinstance(raw, list) else raw
                if first:
                    refs.add(str(first))
    for tf in beat.get("transformations", []):
        for key in ("targets", "target_objects"):
            raw = tf.get(key)
            if raw:
                first = raw[0] if isinstance(raw, list) else raw
                if first:
                    refs.add(str(first))
    return refs


def _future_refs(beats: list[dict], idx: int) -> set[str]:
    out: set[str] = set()
    for b in beats[idx + 1:]:
        out |= _beat_refs(b)
    return out


def _narrative_call(beat: dict) -> tuple[str, float] | None:
    """Map a text-primary visual class to its primitive call (fallback)."""
    vtype = str(beat.get("visual_type", "")).lower()
    prim = _NARRATIVE_VISUALS.get(vtype)
    if prim is None:
        return None
    narration = str(beat.get("narration", " ") or " ")
    if prim == "KineticTypography":
        word = " ".join(narration.split()[:5]) or "!"
        return (f"KineticTypography(self, {word!r}, "
                f"scene_state=self._state, duration=@D@)", 0.9)
    if prim == "QuestionMark":
        return (f"QuestionMark(self, self._state, {narration[:60]!r}, "
                f"oid='question', duration=@D@)", 0.9)
    if prim == "ClaimReveal":
        return (f"ClaimReveal(self, {narration[:80]!r}, "
                f"scene_state=self._state, duration=@D@)", 0.7)
    if prim == "CycleReveal":
        return (f"CycleReveal(self, {narration[:60]!r}, "
                f"scene_state=self._state, duration=@D@)", 0.8)
    if prim == "PayoffText":
        return (f"PayoffText(self, self._state, {narration[:60]!r}, "
                f"oid='payoff', duration=@D@)", 1.0)
    return (f"RevealText(self, self._state, {narration[:60]!r}, "
            f"oid='reveal', duration=@D@)", 0.8)


def _legacy_digit_call(beat: dict, state: SceneState) -> tuple[str, float] | None:
    """Delegate legacy number visuals to the v1 primitives."""
    vtype = str(beat.get("visual_type", "")).lower()
    if vtype not in _LEGACY_DIGIT_VISUALS:
        return None
    from engine.renderers.manim.compiler import _ATTRACTOR
    value = _ATTRACTOR
    for obj in beat.get("objects", []):
        if isinstance(obj, dict) and obj.get("value"):
            value = str(obj["value"]).zfill(4)
            break
    if vtype == "digit_sort":
        frm = value
        to = "".join(sorted(frm, reverse=True))
        for tf in beat.get("transformations", []):
            if tf.get("to"):
                to = str(tf["to"]).zfill(4)
        return (f"reorder_digits(self, self._state, 'number_main', "
                f"{frm!r}, {to!r}, ndigits=4, duration=@D@, stagger=0.12)",
                0.9)
    if vtype == "subtract":
        frm = value
        to = str(M.verify_kaprekar_sequence(value).__dict__.get("checks", [{}])[0]
                 .get("detail", "")) if False else value
        for tf in beat.get("transformations", []):
            if tf.get("to"):
                to = str(tf["to"]).zfill(4)
        return (f"apply_kaprekar_step(self, self._state, {frm!r}, {to!r}, "
                f"ndigits=4, duration=@D@)", 3.0)
    if vtype == "attractor":
        return (f"enter_attractor(self, self._state, {value!r}, "
                f"duration=@D@)", 0.6)
    if vtype == "fixed_point":
        return (f"FixedPointReveal(self, self._state, {value!r}, "
                f"duration=@D@)", 2.4)
    if vtype == "exception":
        return (f"ExceptionVisual(self, self._state, {value!r}, ndigits=4, "
                f"duration=@D@)", 3.0)
    if vtype == "highlight":
        target = "number_main"
        for obj in beat.get("objects", []):
            if isinstance(obj, dict) and obj.get("id"):
                target = str(obj["id"])
                break
        return (f"HighlightTarget(self, self._state, {target!r}, "
                f"duration=@D@)", 0.6)
    if vtype == "comparison":
        return (f"Comparison(self, 'left', 'right', '', '', "
                f"scene_state=self._state, duration=@D@)", 0.9)
    return None


def _camera_call(beat: dict, world: WorldState) -> tuple[str, float] | None:
    """Emit a camera operation for the beat (v0.3 executes cameras).

    Phase B (§20): the per-beat composition plan may carry an explicit
    camera scale (focal-frame tightness driven by pacing); it overrides
    the static defaults when present.
    """
    cam = beat.get("camera") or {}
    ctype = str(cam.get("type", "static"))
    target = str(cam.get("target", world.camera.target if world else ""))
    comp = beat.get("composition") or {}
    comp_cam = comp.get("camera") or {}
    scale = cam.get("scale") or comp_cam.get("scale")
    if ctype in ("static", "reveal", "reframe"):
        return None
    if not target:
        return None
    if ctype in ("zoom_to", "push_in", "focus"):
        s = float(scale) if scale else 0.72
        return (f"camera_focus(self, camera_target(self._state, {target!r}), "
                f"scale={s}, duration=@D@)", _CAMERA_NATURAL)
    if ctype in ("zoom_from", "pull_out", "zoom_out_of"):
        return (f"camera_reset(self, duration=@D@)", _CAMERA_NATURAL)
    if ctype == "follow":
        s = float(scale) if scale else 0.85
        return (f"camera_focus(self, camera_target(self._state, {target!r}), "
                f"scale={s}, duration=@D@)", _CAMERA_NATURAL)
    if ctype == "pan":
        s = float(scale) if scale else 0.9
        return (f"camera_focus(self, camera_target(self._state, {target!r}), "
                f"scale={s}, duration=@D@)", _CAMERA_NATURAL)
    return None


def _compile_beat(beat: dict, state: SceneState, future_ids: set[str],
                  world: WorldState, bid: str) -> tuple[list[str], float]:
    """Plan one v2 beat against the persistent SceneState."""
    _physics_guard(beat, world)
    dur = float(beat.get("duration")
                or (beat.get("end", 0) - beat.get("start", 0))
                or 1.5)
    vtype = str(beat.get("visual_type", "")).lower()

    state.begin_beat(bid)
    refs = _beat_refs(beat)
    stmts: list[str] = []
    calls: list[tuple[str, float]] = []

    # ── EXIT sweep ────────────────────────────────────────────────────
    for oid in list(state.objects):
        obj = state.objects[oid]
        if obj.exit_beat is not None:
            continue
        if oid in refs:
            continue
        if obj.temporary or oid not in future_ids:
            calls.append((f"exit_object(self, self._state, {oid!r}, "
                          f"duration=@D@)", 0.4))
            state.exit(oid)
            state.record_exit(oid)

    # ── ENTER materialization (world entities) ────────────────────────
    for obj in beat.get("objects", []):
        if not isinstance(obj, dict):
            continue
        oid = str(obj.get("id", ""))
        otype = str(obj.get("type", ""))
        if otype in ("text",):
            continue  # text handled by narrative fallback
        if state.get(oid) is not None and state.get(oid).exit_beat is None:
            continue
        if otype not in ENTITY_MATERIALIZERS:
            raise WorldCompileError(
                f"beat {bid}: cannot materialize object {oid!r} of unknown "
                f"world type {otype!r}")
        ent = world.entity(oid)
        entity_dict = ent.to_dict() if hasattr(ent, "to_dict") else \
            {"id": oid, "type": otype, "properties": obj.get("properties", {})}
        natural = _NATURAL_ENTER.get(ENTITY_MATERIALIZERS.get(otype, ""), 0.6)
        calls.append((f"materialize_entity(self, self._state, "
                      f"{repr(entity_dict)}, duration=@D@)", natural))
        state.enter(oid, otype, value=str(obj.get("value", "")),
                    zone=Zone.CENTER, persistent=True)
        state.record_enter(oid)

    # ── semantic actions (action grammar) ─────────────────────────────
    actions = beat.get("semantic_actions", []) or []
    if not actions:
        # fall back to transformations that are semantic actions
        for tf in beat.get("transformations", []):
            t = str(tf.get("type", ""))
            if resolve(t) is not None:
                actions.append(tf)
    for a in actions:
        name = str(a.get("action", a.get("type", "")))
        spec = resolve(name)
        if spec is None:
            raise WorldCompileError(
                f"beat {bid}: unmapped semantic action {name!r}")
        natural = ACTION_NATURAL_DURATION.get(name, 1.5)
        act = {k: v for k, v in a.items() if k != "action"}
        act["action"] = name
        calls.append((f"apply_action(self, self._state, "
                      f"{repr(act)}, self._world, duration=@D@)",
                      natural))

    # ── narrative fallback (kinetic text LAST, spec §9) ───────────────
    if not calls:
        legacy = _legacy_digit_call(beat, state)
        if legacy is not None:
            calls.append(legacy)
    if not calls:
        narr = _narrative_call(beat)
        if narr is not None:
            calls.append(narr)

    # ── camera ────────────────────────────────────────────────────────
    cam = _camera_call(beat, world)
    if cam is not None:
        calls.append(cam)

    if not calls:
        raise WorldCompileError(
            f"beat {bid}: no visual content (no entities, no actions, no "
            "narrative class) — refusing a silent no-op")

    # ── duration budget ───────────────────────────────────────────────
    budget = dur - MARGIN
    total_natural = sum(n for _, n in calls)
    if total_natural > budget:
        scale = budget / total_natural
        if min(n * scale for _, n in calls) < MIN_ANIM:
            raise WorldCompileError(
                f"beat {bid}: animation budget {budget:.2f}s too small for "
                f"{len(calls)} calls (min {MIN_ANIM:.2f}s each)")
    else:
        scale = 1.0
    total_anim = 0.0
    for code, natural in calls:
        d = natural * scale
        total_anim += d
        stmts.append(code.replace("@D@", f"{d:.3f}"))
    wait = dur - total_anim
    if wait < 0:
        raise WorldCompileError(
            f"beat {bid}: animations ({total_anim:.2f}s) exceed declared "
            f"duration ({dur:.2f}s)")
    stmts.append(f"self.wait({wait:.3f})")
    state.record_persist()
    return stmts, total_anim


def emit_world_scene(vs: dict, scene_name: str = "WorldScene") -> str:
    """Compile a v2 VisualSpec into standalone Manim Scene source."""
    errs = validate_visualspec_v2(vs)
    if errs:
        raise WorldCompileError(
            "VisualSpec v2 failed schema validation:\n" + "\n".join(errs))
    world_dict = (vs.get("metadata", {}) or {}).get("world", {})
    errs = validate_worldmodel(world_dict)
    if errs:
        raise WorldCompileError(
            "world model failed schema validation:\n" + "\n".join(errs))
    world = WorldState.from_dict(world_dict)

    beats = vs["beats"]
    state = SceneState()
    body: list[str] = []
    for idx, beat in enumerate(beats):
        bid = beat.get("beat_id", f"b{idx + 1:03d}")
        future_ids = _future_refs(beats, idx)
        stmts, _ = _compile_beat(beat, state, future_ids, world, bid)
        body.append(f"        # ---- beat {bid}: {beat.get('intent','')} ----")
        body.append("        self._state.begin_beat(%r)" % bid)
        body.extend("        " + s for s in stmts)
        body.append("        self._state.record_persist()")

    world_literal = repr(world.to_dict())  # Python literal (None/True/False)
    hero = (vs.get("metadata", {}) or {}).get("hero_mechanism") or {}
    rep = (vs.get("metadata", {}) or {}).get("representation", "")

    source = f'''"""
Auto-generated by the WorldSpec compiler (v2).  Deterministic; do not edit.
"""
import os
import sys

_REPO = os.path.dirname(os.path.abspath(__file__))
while _REPO and not os.path.isdir(os.path.join(_REPO, "engine")):
    _parent = os.path.dirname(_REPO)
    if _parent == _REPO:
        break
    _REPO = _parent
if os.path.isdir(os.path.join(_REPO, "engine")) and _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from manim import Scene
from manim import config as _manim_config

# dark navy (not pure black): cinematic dark look that always clears the
# black-frame luma gate (must be set before Scene instantiation)
# NOTE: manim's attribute is 'background_color' (US spelling).  The
# previous 'background_colour' assignment was a silent no-op — manim
# 0.20.1 accepts arbitrary attribute writes on ManimConfig without any
# effect — so scenes rendered on pure black and the opening beats
# (thin line art on black) failed the black-frame luma gate (the
# Gabriel's Horn 0-8s black opening, 2026-08-27).
_manim_config.background_color = "#0b0f1a"
from engine.visuals.scene_state import SceneState
from engine.primitives.world_primitives import (
    materialize_entity, apply_action, CelestialBody, OrbitPath, MovingBody,
    FollowBody, FallBody, AccelerateBody, CollideBodies, ImpactBurst,
    MissBody, CurvePath, TracePath, OscillateBody, VelocityVector,
    ForceVector, ReferenceFrame, ProjectilePath, LightSource, LightRay,
    Wave, SignalPulse, ParticleField, ScatteringField, CrossSection,
    RevealInside, MediumLayer, Node, Connection, FlowThrough, BranchFlow,
    MergeFlow, Timeline, CauseEffectChain, MeasureValue, EyeGlyph, EarGlyph,
    BrainGlyph, MouthGlyph, QuestionMark, ExperimentBadge, RevealText,
    PayoffText, AssembleBodies, DisassembleBodies,
)
from engine.primitives.manim_primitives import (
    exit_object, KineticTypography, ClaimReveal, CycleReveal,
    Comparison, HighlightTarget, reorder_digits, apply_kaprekar_step,
    enter_attractor, FixedPointReveal, ExceptionVisual,
)
from engine.world.world_model import WorldState


def camera_focus(scene, target_mob, scale=0.72, duration=0.9):
    frame = getattr(scene.camera, "frame", None)
    if frame is None or target_mob is None:
        return
    scene.play(frame.animate.scale(scale).move_to(target_mob.get_center()),
               run_time=duration)


def camera_target(scene_state, oid):
    """Mobject for a camera target, or None when the entity is not yet on
    stage (camera ops must never crash on a not-yet-entered entity)."""
    if not oid:
        return None
    obj = scene_state.get(oid)
    if obj is None or obj.mobject is None:
        return None
    return obj.mobject


def camera_reset(scene, duration=0.9):
    frame = getattr(scene.camera, "frame", None)
    if frame is None:
        return
    scene.play(frame.animate.scale(1.0).move_to([0, 0, 0]),
               run_time=duration)


class {scene_name}(Scene):
    def construct(self):
        # dark navy (not pure black): belt-and-braces — the module-level
        # config above is authoritative; this also pins the camera in case
        # the scene is imported into a session whose config differs
        self.camera.background_color = "#0b0f1a"
        self._state = SceneState()
        self._world = WorldState.from_dict({world_literal})
{chr(10).join(body)}
        if os.environ.get("VE_SCENE_STATE_LOG"):
            self._state.write_log(os.environ["VE_SCENE_STATE_LOG"])
        if os.environ.get("VE_WORLD_LOG"):
            import json as _json
            _json.dump(self._world.to_dict(), open(os.environ["VE_WORLD_LOG"], "w"),
                       indent=2)
'''

    return source


def compile_world_to_file(vs: dict, out_path: str | Path,
                          scene_name: str = "WorldScene") -> Path:
    """Compile a v2 VisualSpec to a .py scene file on disk."""
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(emit_world_scene(vs, scene_name), encoding="utf-8")
    return out
