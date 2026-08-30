"""VisualSpec -> Manim compiler (directive §4, §5, §49 Phase 5).

GLM emits a strict JSON VisualSpec (WHAT/WHY/WHEN).  This deterministic
compiler is the ONLY bridge to Manim — it maps each transformation to a
trusted primitive.  GLM never writes arbitrary Manim code as the
primary interface.

The compiler:
  1. Validates the VisualSpec against the schema (Gate 1).
  2. Verifies every mathematical value (Gate 3) before rendering.
  3. Maintains a SceneState ACROSS beats and consults it on every beat to
     decide which objects ENTER (create), UPDATE (transform in place), or
     EXIT (fade/remove) — the anti-accumulation lifecycle fix.  Objects are
     created once, transformed in place, and removed when their role ends;
     no beat starts with the previous beat's leftovers on stage.
  4. Emits a Manim Scene class that reconstructs the same SceneState at
     runtime and calls the state-aware primitives against it, so the
     scene_state_log is an accurate per-beat ENTER/UPDATE/EXIT record.

Every transformation type maps to a working primitive or raises
CompileError — there are no silent no-op branches.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from engine.primitives import manim_primitives as P
from engine.validation import math_verify as M
from engine.validation.schema import validate_visualspec
from engine.visuals.scene_state import SceneState, Zone


class CompileError(ValueError):
    """Raised when a VisualSpec cannot be compiled safely."""


# ── Duration budget (seconds) ──────────────────────────────────────────────
# Every beat must fit its animations + self.wait() inside its declared
# duration.  MARGIN is the minimum slack left for self.wait(); MIN_ANIM is
# the floor below which a single animation is considered unrenderable.
MARGIN = 0.15
MIN_ANIM = 0.08

# Natural (unscaled) duration per primitive call, in seconds.
_NATURAL: dict[str, float] = {
    "enter_number_main": 0.6,
    "enter_attractor": 0.6,
    "exit_object": 0.4,
    "reorder_digits": 0.9,
    "apply_kaprekar_step": 3.0,
    "morph_number": 0.8,
    "AttractorDiagram": 3.0,
    "FixedPointReveal": 2.4,
    "ExceptionVisual": 3.0,
    "ConvergenceParticles": 1.6,
    "HighlightTarget": 0.6,
    "QuestionReveal": 0.9,
    "ClaimReveal": 0.7,
    "KineticTypography": 0.9,
    "Comparison": 0.9,
    "CycleReveal": 0.8,
}

# Transformation type -> (primitive name, requires a resolvable target).
_TRANSFORM_MAP: dict[str, tuple[str, bool]] = {
    "sort": ("reorder_digits", True),
    "reverse": ("reorder_digits", True),
    "digit_permute": ("reorder_digits", True),
    "subtract": ("apply_kaprekar_step", True),
    "transform": ("morph_number", True),
    "morph": ("morph_number", True),
    "count_down": ("ConvergenceParticles", True),
    "converge": ("AttractorDiagram", True),
    "orbital": ("ConvergenceParticles", True),
    "reveal": ("FixedPointReveal", True),
    "highlight": ("HighlightTarget", True),
}

_NARRATIVE_VISUALS: dict[str, str] = {
    "kinetic_title": "KineticTypography",
    "question": "QuestionReveal",
    "claim": "ClaimReveal",
    "comparison": "ClaimReveal",
    "cycle": "CycleReveal",
}

# Declared object ids that are created/exited INSIDE a primitive (the
# compiler never materializes them itself).
_MANAGED_TEMP = {"equation", "kaprekar_result", "result", "ascending"}
# Narrative text objects owned by narrative primitives.
_TEXT_OIDS = {"question", "claim", "kinetic", "comparison", "cycle"}
_DIGIT_IDS = {"digit_1", "digit_2", "digit_3", "digit_4"}

_ATTRACTOR = str(6174).zfill(4)


def _canonical_id(obj_id: str, value: str = "") -> str:
    """Map a declared object id to its persistent semantic id.

    The benchmark's sloppy ids (digit_1..digit_4, number_main with the
    attractor value) collapse onto the real semantic objects so the
    SceneState sees ONE main number and ONE attractor across all beats.
    """
    if obj_id in _DIGIT_IDS:
        return "number_main"
    if obj_id == "number_main" and str(value).zfill(4) == _ATTRACTOR:
        return "attractor"
    if obj_id in ("number", "number_display"):
        return "attractor" if str(value).zfill(4) == _ATTRACTOR else "number_main"
    return obj_id


def _math_guard(beat: dict) -> None:
    """Deterministic math verification for a beat's transformations (Gate 3).

    Uses engine.validation.math_verify exclusively — the LLM is never the
    authority for arithmetic.  Every failure raises CompileError so a wrong
    number can never reach the renderer.
    """
    intent = beat.get("intent", "")
    bid = beat.get("beat_id", "?")
    vtype = str(beat.get("visual_type", "")).lower()
    # Narrative beats (kinetic_title/question/claim/comparison/cycle) carry
    # concept-token from/to on their actions (e.g. "even" -> "odd"); their
    # primitives never execute digit arithmetic, so the 4-digit string checks
    # below apply only to non-narrative transformation beats.
    if vtype in _NARRATIVE_VISUALS:
        return
    for tf in beat.get("transformations", []):
        t = tf.get("type")
        frm = str(tf.get("from", ""))
        to = str(tf.get("to", ""))
        if t in ("sort", "reverse", "digit_permute"):
            if frm and to:
                if len(frm) != 4 or len(to) != 4 or not (frm.isdigit() and to.isdigit()):
                    raise CompileError(
                        f"beat {bid}: {t} needs 4-digit from/to, got {frm!r} -> {to!r}")
                if sorted(frm) != sorted(to):
                    raise CompileError(
                        f"beat {bid}: {t} {frm!r} -> {to!r} is not a permutation "
                        "(a reorder never changes the digit multiset)")
        if t == "subtract":
            v = M.verify_kaprekar_step(str(to).zfill(4), 4, str(frm).zfill(4))
            if not v.ok:
                raise CompileError(
                    f"beat {bid}: math verification failed for {intent}: "
                    + "; ".join(f["detail"] for f in v.failures()))
        if t == "converge":
            for traj in _trajectories_for(tf):
                if str(traj[-1]).zfill(4) != _ATTRACTOR:
                    raise CompileError(
                        f"beat {bid}: trajectory {traj} does not converge to {_ATTRACTOR}")
        if t in ("transform", "morph") and to and not to.isdigit():
            raise CompileError(f"beat {bid}: {t} target {to!r} is not a digit string")


def _trajectories_for(tf: dict, ndigits: int = 4) -> list[list[str]]:
    """Compute VERIFIED trajectories for a converge action.

    Parses start numbers from the action's ``to`` field (e.g. "8352 -> 6174")
    and verifies each orbit deterministically with math_verify; falls back to
    the benchmark's verified demo starts.  Raises CompileError on anything
    that does not converge to 6174 — never renders an unverified claim.
    """
    to = str(tf.get("to", ""))
    starts = [s for s in re.findall(r"\d{4}", to) if s != _ATTRACTOR]
    if not starts:
        starts = ["3524", "1000", "9998", "3087"]  # verified demo starts
    trajs: list[list[str]] = []
    for s in starts:
        v = M.verify_kaprekar_sequence(s, ndigits)
        orbit: list[str] | None = None
        for c in v.checks:
            if c["name"] == "all_steps_valid" and "orbit: " in c["detail"]:
                orbit = [p.strip() for p in
                         c["detail"].split("orbit: ", 1)[1].split("->")]
        if orbit is None or str(orbit[-1]).zfill(ndigits) != _ATTRACTOR:
            raise CompileError(
                f"trajectory from {s} does not converge to {_ATTRACTOR} "
                f"(verified: {[f['detail'] for f in v.failures()]})")
        # verify_kaprekar_sequence appends the fixed point twice (once when
        # reached, once when confirmed) — collapse consecutive duplicates
        # so the emitted trajectory is a clean orbit.
        clean = [orbit[0]]
        for x in orbit[1:]:
            if x != clean[-1]:
                clean.append(x)
        trajs.append(clean)
    return trajs


def _resolve_target(beat: dict, tf: dict, state: SceneState) -> str:
    """Resolve the object a transformation acts on.

    Never a silent no-op: a transformation that cannot point at an object
    raises CompileError.
    """
    bid = beat.get("beat_id", "?")
    t = tf.get("type")
    for key in ("targets", "target_objects"):
        raw = tf.get(key)
        if raw:
            first = raw[0] if isinstance(raw, list) else raw
            oid = _canonical_id(str(first))
            if state.get(oid) is None or state.get(oid).exit_beat is not None:
                raise CompileError(
                    f"beat {bid}: transformation {t} targets {oid!r} "
                    "which is not on stage")
            return oid
    objs = beat.get("objects", [])
    focal = [o for o in objs
             if o.get("type") in ("number", "number_display", "digit_array",
                                  "attractor", "number_main")]
    if focal:
        return _canonical_id(str(focal[0].get("id", "")),
                             str(focal[0].get("value", "")))
    if objs:
        return _canonical_id(str(objs[0].get("id", "")),
                             str(objs[0].get("value", "")))
    raise CompileError(
        f"beat {bid}: transformation {t} has no target object "
        "(no declared objects, no targets field)")


def _beat_refs(beat: dict) -> set[str]:
    """Canonical object ids referenced by a beat (declared objects + action
    targets).  Used for the EXIT sweep: objects not referenced by the current
    beat (and not persistent into the future) leave the stage."""
    refs: set[str] = set()
    vtype = str(beat.get("visual_type", "")).lower()
    for obj in beat.get("objects", []):
        # exception beats own a clean separate state; never reference the
        # main number there
        if vtype == "exception" and obj.get("id") in _DIGIT_IDS:
            continue
        refs.add(_canonical_id(str(obj.get("id", "")),
                               str(obj.get("value", ""))))
    for tf in beat.get("transformations", []):
        for key in ("targets", "target_objects"):
            raw = tf.get(key)
            if raw:
                first = raw[0] if isinstance(raw, list) else raw
                refs.add(_canonical_id(str(first)))
    return refs


def _future_refs(beats: list[dict], idx: int) -> set[str]:
    """Canonical ids referenced in any beat AFTER ``idx`` (lookahead used to
    decide whether a persistent object's role has ended)."""
    out: set[str] = set()
    for b in beats[idx + 1:]:
        out |= _beat_refs(b)
    return out


def _compile_beat(beat: dict, state: SceneState, future_ids: set[str],
                  bid: str) -> tuple[list[str], float]:
    """Plan ONE beat against the persistent SceneState.

    Returns (emitted statement lines, total animation seconds).  Raises
    CompileError on: unmapped transforms, untargeted transforms, math
    failures, unverified trajectories, duration overflow, or beats with no
    visual content at all (never a silent no-op).
    """
    _math_guard(beat)
    dur = float(beat.get("duration")
                or (beat.get("end", 0) - beat.get("start", 0))
                or 1.5)
    vtype = str(beat.get("visual_type", "")).lower()
    is_narrative = vtype in _NARRATIVE_VISUALS
    is_exception = vtype == "exception"

    state.begin_beat(bid)
    refs = _beat_refs(beat)
    stmts: list[str] = []
    calls: list[tuple[str, float]] = []  # (rendered call, natural duration)

    # ── EXIT sweep: objects whose role ended leave the stage now ──────
    for oid in list(state.objects):
        obj = state.objects[oid]
        if obj.exit_beat is not None:
            continue
        if oid in refs:
            continue
        if obj.temporary or oid not in future_ids:
            calls.append((f"exit_object(self, self._state, {oid!r}, "
                          f"duration={{d}})", _NATURAL["exit_object"]))
            state.exit(oid)
            state.record_exit(oid)

    # ── ENTER sweep: newly declared objects are created ───────────────
    if not is_narrative and not is_exception:
        for obj in beat.get("objects", []):
            coid = _canonical_id(str(obj.get("id", "")),
                                 str(obj.get("value", "")))
            if coid in _MANAGED_TEMP or coid in _TEXT_OIDS:
                continue  # created inside a primitive
            if coid not in ("number_main", "attractor"):
                raise CompileError(
                    f"beat {bid}: cannot materialize object {coid!r} "
                    f"(type {obj.get('type')!r}) — unsupported focal type")
            if state.get(coid) is not None and state.get(coid).exit_beat is None:
                continue  # already on stage — persists
            value = str(obj.get("value", "")).zfill(4) or _ATTRACTOR
            if coid == "number_main":
                calls.append((f"enter_number_main(self, self._state, {value!r}, "
                              f"ndigits=4, duration={{d}})",
                              _NATURAL["enter_number_main"]))
                state.enter(coid, "number", value=value, zone=Zone.FOCUS,
                            persistent=True)
            else:
                calls.append((f"enter_attractor(self, self._state, {value!r}, "
                              f"duration={{d}})",
                              _NATURAL["enter_attractor"]))
                state.enter(coid, "number", value=value, zone=Zone.CENTER,
                            persistent=True)
            state.record_enter(coid)

    # ── Visual content: narrative primitive or transformations ────────
    if is_narrative:
        prim = _NARRATIVE_VISUALS[vtype]
        narration = str(beat.get("narration", " ") or " ")
        # Data-bearing actions on narrative beats must still resolve a
        # target (never silently dropped).  Bare directives (type only) are
        # realized by the narrative primitive itself — that IS the mapping.
        for tf in beat.get("transformations", []):
            has_data = bool(tf.get("from") or tf.get("to")
                            or tf.get("targets") or tf.get("target_objects"))
            if has_data:
                _resolve_target(beat, tf, state)
        if prim == "KineticTypography":
            word = " ".join(narration.split()[:5]) or "!"
            calls.append((f"KineticTypography(self, {word!r}, "
                          f"scene_state=self._state, duration={{d}})",
                          _NATURAL[prim]))
        else:
            calls.append((f"{prim}(self, {narration!r}, "
                          f"scene_state=self._state, duration={{d}})",
                          _NATURAL[prim]))
        state.enter({"kinetic_title": "kinetic", "question": "question",
                     "claim": "claim", "comparison": "comparison",
                     "cycle": "cycle"}[vtype], "text", value=narration,
                    zone=Zone.CENTER, persistent=False)
        state.record_enter({"kinetic_title": "kinetic", "question": "question",
                            "claim": "claim", "comparison": "comparison",
                            "cycle": "cycle"}[vtype])
    elif is_exception:
        # clean separate state: ExceptionVisual owns everything, creates and
        # removes its own digits/equation within the beat
        value = _ATTRACTOR
        for obj in beat.get("objects", []):
            if obj.get("value"):
                value = str(obj["value"]).zfill(4)
        for tf in beat.get("transformations", []):
            if tf.get("from"):
                value = str(tf["from"]).zfill(4)
        calls.append((f"ExceptionVisual(self, self._state, {value!r}, "
                      f"ndigits=4, duration={{d}})",
                      _NATURAL["ExceptionVisual"]))
        state.enter("exception", "digit_array", value=value, zone=Zone.CENTER,
                    persistent=False)
        state.enter("exception_equation", "equation", persistent=False)
        state.exit("exception")
        state.exit("exception_equation")
    else:
        for tf in beat.get("transformations", []):
            t = tf.get("type")
            mapping = _TRANSFORM_MAP.get(t)
            if mapping is None:
                raise CompileError(f"beat {bid}: unmapped transformation {t!r}")
            prim, needs_target = mapping
            target = _resolve_target(beat, tf, state) if needs_target else ""
            frm = str(tf.get("from", "")).zfill(4)
            to = str(tf.get("to", "")).zfill(4)

            if prim == "reorder_digits":
                calls.append((f"reorder_digits(self, self._state, {target!r}, "
                              f"{frm!r}, {to!r}, ndigits=4, duration={{d}}, "
                              f"stagger=0.12)", _NATURAL[prim]))
                state.update(target, {"op": "sort", "to": to}, value=to)
                state.record_update(target)
            elif prim == "apply_kaprekar_step":
                calls.append((f"apply_kaprekar_step(self, self._state, "
                              f"{frm!r}, {to!r}, ndigits=4, duration={{d}})",
                              _NATURAL[prim]))
                state.update("number_main", {"op": "kaprekar_step", "to": to},
                             value=to)
                state.record_update("number_main")
                for tmp in ("ascending", "equation", "result"):
                    state.enter(tmp, "equation", persistent=False)
                    state.exit(tmp)
            elif prim == "morph_number":
                calls.append((f"morph_number(self, self._state, {target!r}, "
                              f"{frm!r}, {to!r}, ndigits=4, duration={{d}})",
                              _NATURAL[prim]))
                state.update(target, {"op": "morph", "to": to}, value=to)
                state.record_update(target)
            elif prim == "AttractorDiagram":
                trajs = _trajectories_for(tf)
                calls.append((f"AttractorDiagram(self, self._state, "
                              f"{trajs!r}, ndigits=4, duration={{d}})",
                              _NATURAL[prim]))
                if state.get("attractor") is None or \
                        state.get("attractor").exit_beat is not None:
                    state.enter("attractor", "number", value=_ATTRACTOR,
                                zone=Zone.CENTER, persistent=True)
                    state.record_enter("attractor")
                for i in range(len(trajs)):
                    lane = f"lane_{i}"
                    state.enter(lane, "digit_array", persistent=False)
                    state.exit(lane)
            elif prim == "FixedPointReveal":
                value = str(tf.get("to", _ATTRACTOR)).zfill(4)
                calls.append((f"FixedPointReveal(self, self._state, {value!r}, "
                              f"duration={{d}})", _NATURAL[prim]))
                if state.get("attractor") is None or \
                        state.get("attractor").exit_beat is not None:
                    state.enter("attractor", "number", value=value,
                                zone=Zone.CENTER, persistent=True)
                    state.record_enter("attractor")
                state.update("attractor", {"op": "dominate"}, value=value)
                state.record_update("attractor")
                state.enter("converge_paths", "particles", persistent=False)
                state.exit("converge_paths")
            elif prim == "ConvergenceParticles":
                calls.append((f"ConvergenceParticles(self, self._state, "
                              f"{target!r}, n=40, duration={{d}})",
                              _NATURAL[prim]))
                state.enter("particles", "particles", persistent=False)
                state.exit("particles")
            elif prim == "HighlightTarget":
                calls.append((f"HighlightTarget(self, self._state, {target!r}, "
                              f"duration={{d}})", _NATURAL[prim]))
                state.update(target, {"op": "highlight"})
                state.record_update(target)
            else:  # pragma: no cover — mapping table is exhaustive
                raise CompileError(f"beat {bid}: unhandled primitive {prim!r}")

    if not calls:
        raise CompileError(
            f"beat {bid}: no visual content (no objects, no transformations, "
            "no narrative) — refusing to emit a silent no-op")

    # ── Duration budget: animations + self.wait() must fit the beat ───
    budget = dur - MARGIN
    total_natural = sum(n for _, n in calls)
    if total_natural > budget:
        scale = budget / total_natural
        if min(n * scale for _, n in calls) < MIN_ANIM:
            raise CompileError(
                f"beat {bid}: animation budget {budget:.2f}s too small for "
                f"{len(calls)} animations (min {MIN_ANIM:.2f}s each) — "
                "declared duration overflow")
    else:
        scale = 1.0
    total_anim = 0.0
    for code, natural in calls:
        d = natural * scale
        total_anim += d
        stmts.append(code.format(d=f"{d:.3f}"))
    wait = dur - total_anim
    if wait < 0:
        raise CompileError(
            f"beat {bid}: animations ({total_anim:.2f}s) exceed declared "
            f"duration ({dur:.2f}s)")
    stmts.append(f"self.wait({wait:.3f})")
    state.record_persist()
    return stmts, total_anim


def emit_scene(vs: dict, scene_name: str = "BenchScene") -> str:
    """Compile a full VisualSpec into a standalone Manim Scene source string.

    Returns source that Manim can render via:
        manim render --format=mp4 <scene.py> <SceneName>

    The emitted Scene reconstructs a SceneState at runtime, and every beat
    calls the state-aware primitives against it (ENTER/UPDATE/EXIT recorded
    per beat).  Set VE_SCENE_STATE_LOG to a path to have the render write
    the per-beat lifecycle log.
    """
    errs = validate_visualspec(vs)
    if errs:
        raise CompileError("VisualSpec failed schema validation:\n" + "\n".join(errs))

    beats = vs["beats"]
    state = SceneState()
    body: list[str] = []
    for idx, beat in enumerate(beats):
        bid = beat.get("beat_id", f"b{idx + 1:03d}")
        future_ids = _future_refs(beats, idx)
        stmts, _ = _compile_beat(beat, state, future_ids, bid)
        body.append(f"        # ---- beat {bid}: {beat.get('intent','')} ----")
        body.append("        self._state.begin_beat(%r)" % bid)
        body.extend("        " + s for s in stmts)
        body.append("        self._state.record_persist()")

    source = f'''"""
Auto-generated by the VisualSpec compiler.  Deterministic; do not hand-edit.
"""
import os
import sys

# Ensure the video_engine repo root (ancestor containing the engine/ package)
# is importable regardless of Manim's working directory.
_REPO = os.path.dirname(os.path.abspath(__file__))
while _REPO and not os.path.isdir(os.path.join(_REPO, "engine")):
    _parent = os.path.dirname(_REPO)
    if _parent == _REPO:
        break
    _REPO = _parent
if os.path.isdir(os.path.join(_REPO, "engine")) and _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from manim import Scene, Text
from engine.visuals.scene_state import SceneState
from engine.primitives.manim_primitives import (
    enter_number_main, enter_attractor, exit_object, reorder_digits,
    apply_kaprekar_step, morph_number, AttractorDiagram, FixedPointReveal,
    ExceptionVisual, ConvergenceParticles, HighlightTarget,
    QuestionReveal, ClaimReveal, KineticTypography, Comparison, CycleReveal,
)
from engine.config.loader import get_style

_STYLE = get_style()
STYLE_FONT = _STYLE.get("font_family", "DejaVu Sans")
STYLE_DIGIT = _STYLE.get("font_sizes", {{}}).get("digit", 64)
ACCENT0 = _STYLE.get("accent_colors", ["#4FC3F7"])[0]


class {scene_name}(Scene):
    def construct(self):
        self._state = SceneState()
{chr(10).join(body)}
        if os.environ.get("VE_SCENE_STATE_LOG"):
            self._state.write_log(os.environ["VE_SCENE_STATE_LOG"])
'''

    return source


def compile_to_file(vs: dict, out_path: str | Path,
                    scene_name: str = "BenchScene") -> Path:
    """Compile VisualSpec to a .py scene file on disk (for incremental render)."""
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(emit_scene(vs, scene_name), encoding="utf-8")
    return out


if __name__ == "__main__":
    demo = {
        "version": "v1",
        "beats": [
            {
                "beat_id": "b001",
                "intent": "hook",
                "narration": "Try this number trick.",
                "duration": 1.5,
                "objects": [{"id": "number_main", "type": "number",
                             "value": "3524"}],
                "transformations": [
                    {"type": "highlight", "from": "3524", "to": "3524",
                     "params": {}}
                ],
            },
            {
                "beat_id": "b002",
                "intent": "demonstrate_transformation",
                "narration": "Now rearrange and subtract.",
                "duration": 2.5,
                "objects": [{"id": "number_main", "type": "number",
                             "value": "3524"}],
                "transformations": [
                    {"type": "subtract", "from": "3524", "to": "3087",
                     "params": {}}
                ],
            },
        ],
    }
    src = emit_scene(demo)
    print(src[:1800])
